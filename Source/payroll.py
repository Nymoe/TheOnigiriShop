"""Payroll calculation and accounting domain classes.

Public method names are kept stable for compatibility with the payroll service:

  Payroll                payrollID, payDate, status, totalAmount
                         calculatePay(), validateHours(), approve(),
                         generatePayStubs(), recordExpense()
  PayrollEntry           entryID, hoursWorked, overtimeHours, deductions, netPay
                         calculateNetPay()
  Employee               employeeID, hourlyRate  (name is inherited from User)
                         getHourlyRate(), setHourlyRate()
  AccountingTransaction  transactionID, date, description, reference, amount, type
                         validateTransaction()

Relationships are stored as object references or identifiers:
Payroll.entries is "Payroll contains PayrollEntry" (aggregation),
PayrollEntry.employeeID is "Employee paid through PayrollEntry", and
Payroll.approvedBy is "Owner approves Payroll".

Persistence and Owner-only authorization are enforced in payroll_service.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite
from typing import Mapping

# Simplified sample pay rules, not statutory Quebec payroll calculations.
DEDUCTION_RATE = Decimal('0.20')       # one flat rate standing in for all statutory deductions
OVERTIME_MULTIPLIER = Decimal('1.5')   # time-and-a-half for overtime hours
MAX_REGULAR_HOURS = 80                 # assumes a two-week pay period
MAX_TOTAL_HOURS = 120                  # regular + overtime; anything higher is flagged

PAYROLL_STATUSES = ('Draft', 'Approved', 'Paid')
TRANSACTION_TYPES = ('Sale', 'Purchase', 'Expense', 'Inventory Adjustment')
_CENT = Decimal('0.01')


class PayrollError(ValueError):
    """A payroll action was invalid or not allowed in the payroll's current status."""


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def _number(value: object, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise PayrollError(f'{label} must be a number.')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise PayrollError(f'{label} must be a number.') from None
    if not isfinite(number) or number < 0 or (positive and number == 0):
        raise PayrollError(f'{label} must be {"greater than zero" if positive else "zero or more"}.')
    return number


def _iso_date(value: object, label: str) -> str:
    if isinstance(value, date):
        return value.isoformat()
    try:
        parsed = date.fromisoformat(str(value).strip())
    except ValueError:
        raise PayrollError(f'{label} must be a real date in YYYY-MM-DD format.') from None
    return parsed.isoformat()


@dataclass
class Employee:
    """Employee (a kind of User). Supplies the hourly rate a PayrollEntry needs."""

    employeeID: int
    hourlyRate: float
    name: str = ''  # inherited from User

    def getHourlyRate(self) -> float:
        return self.hourlyRate

    def setHourlyRate(self, rate: object) -> None:
        """Alternate flows 2A / 3A: the Owner sets or changes an hourly rate."""
        self.hourlyRate = float(_money(Decimal(str(_number(rate, 'Hourly rate', positive=True)))))


@dataclass
class PayrollEntry:
    """One employee's pay for one payroll."""

    entryID: int | None
    employeeID: int
    hoursWorked: float
    overtimeHours: float = 0
    deductions: float | None = None  # None until calculateNetPay() runs
    netPay: float | None = None

    def __post_init__(self) -> None:
        # Validate regular and overtime hours on initialization.
        self.hoursWorked = _number(self.hoursWorked, 'Hours worked')
        self.overtimeHours = _number(self.overtimeHours, 'Overtime hours')

    def calculateNetPay(self, employee: Employee) -> float:
        """Calculate deductions and net pay from the employee's hourly rate."""
        if employee.employeeID != self.employeeID:
            raise PayrollError('This entry belongs to a different employee.')
        rate = Decimal(str(employee.getHourlyRate() or 0))
        if rate <= 0:
            raise PayrollError(f'{employee.name or "Employee"} has no hourly rate set.')
        earnings = _money(Decimal(str(self.hoursWorked)) * rate
                          + Decimal(str(self.overtimeHours)) * rate * OVERTIME_MULTIPLIER)
        deductions = _money(earnings * DEDUCTION_RATE)
        self.deductions = float(deductions)
        self.netPay = float(earnings - deductions)
        return self.netPay


@dataclass
class AccountingTransaction:
    """Accounting record that a paid Payroll posts to the Accounting Ledger."""

    transactionID: int | None
    date: str
    description: str
    reference: str
    amount: float
    type: str

    def validateTransaction(self) -> bool:
        try:
            _iso_date(self.date, 'Date')
            amount = _number(self.amount, 'Amount', positive=True)
        except PayrollError:
            return False
        return (amount > 0 and bool(str(self.description).strip())
                and bool(str(self.reference).strip()) and self.type in TRANSACTION_TYPES)


@dataclass
class Payroll:
    """One payroll run, identified by its pay date."""

    payrollID: int | None
    payDate: str
    status: str = 'Draft'
    totalAmount: float = 0
    entries: list[PayrollEntry] = field(default_factory=list)  # aggregation: contains
    approvedBy: int | None = None  # Owner who approved (association: approves)

    def __post_init__(self) -> None:
        # Validate the selected pay date and status.
        self.payDate = _iso_date(self.payDate, 'Pay date')
        if self.status not in PAYROLL_STATUSES:
            raise PayrollError(f'Unknown payroll status: {self.status}.')

    def _require(self, *statuses: str) -> None:
        if self.status not in statuses:
            raise PayrollError(f'This payroll is {self.status}; that action needs it to be '
                               f'{" or ".join(statuses)}.')

    def validateHours(self, problems: list[str] | None = None) -> bool:
        """Validate each employee's hours, appending issues for the Owner to correct."""
        found: list[str] = []
        if not self.entries:
            found.append('No employee hours have been entered yet.')
        for entry in self.entries:
            who = f'Employee #{entry.employeeID}'
            total = entry.hoursWorked + entry.overtimeHours
            if total == 0:
                found.append(f'{who} has 0 hours. Enter their hours or remove them.')
            if entry.hoursWorked > MAX_REGULAR_HOURS:
                found.append(f'{who} has more than {MAX_REGULAR_HOURS} regular hours. '
                             'Enter the extra hours as overtime.')
            if total > MAX_TOTAL_HOURS:
                found.append(f'{who} has more than {MAX_TOTAL_HOURS} total hours, which is unrealistic.')
        if problems is not None:
            problems.extend(found)
        return not found

    def calculatePay(self, employees: Mapping[int, Employee]) -> None:
        """Calculate deductions, net pay, and total payroll cost for every entry."""
        self._require('Draft')
        problems: list[str] = []
        if not self.validateHours(problems):
            raise PayrollError('Hours need correcting first: ' + ' '.join(problems))
        total = Decimal('0')
        for entry in self.entries:
            if entry.employeeID not in employees:
                raise PayrollError(f'Employee #{entry.employeeID} is not an active employee.')
            entry.calculateNetPay(employees[entry.employeeID])
            total += Decimal(str(entry.netPay)) + Decimal(str(entry.deductions))
        self.totalAmount = float(_money(total))

    def approve(self, ownerID: int) -> None:
        """Step 7. The Owner approves the calculated payroll."""
        self._require('Draft')
        if not self.entries or any(e.netPay is None for e in self.entries):
            raise PayrollError('Calculate the payroll before approving it.')
        self.status = 'Approved'
        self.approvedBy = ownerID

    def generatePayStubs(self, names: Mapping[int, str] | None = None) -> list[str]:
        """Create a pay stub for each entry on an Approved or Paid payroll."""
        self._require('Approved', 'Paid')
        stubs = []
        for entry in self.entries:
            name = (names or {}).get(entry.employeeID) or f'Employee #{entry.employeeID}'
            earnings = Decimal(str(entry.netPay)) + Decimal(str(entry.deductions))
            stubs.append('\n'.join([
                'THE ONIGIRI SHOP | PAY STUB',
                f'Employee:            {name} (ID {entry.employeeID})',
                f'Pay date:            {self.payDate}',
                f'Payroll:             #{self.payrollID} ({self.status})',
                f'Regular hours:       {entry.hoursWorked:g}',
                f'Overtime hours:      {entry.overtimeHours:g} (x{OVERTIME_MULTIPLIER})',
                f'Earnings:            ${earnings:,.2f}',
                f'Deductions ({int(DEDUCTION_RATE * 100)}%):    -${entry.deductions:,.2f}',
                f'NET PAY:             ${entry.netPay:,.2f}',
            ]))
        return stubs

    def recordExpense(self, today: object | None = None) -> AccountingTransaction:
        """Steps 9-10. Once the employees are paid, marks the payroll Paid and
        returns the expense transaction for the Accounting Ledger."""
        self._require('Approved')
        transaction = AccountingTransaction(
            transactionID=None,
            date=_iso_date(today or date.today(), 'Expense date'),
            description=f'Payroll expense for pay date {self.payDate}',
            reference=f'PAYROLL-{self.payrollID}',
            amount=self.totalAmount,
            type='Expense',
        )
        if not transaction.validateTransaction():
            raise PayrollError('The payroll expense could not be validated for accounting.')
        self.status = 'Paid'
        return transaction
