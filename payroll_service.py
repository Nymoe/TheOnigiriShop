"""Payroll persistence, transaction coordination, and Owner-only authorization.

Business rules are handled by the domain classes in payroll.py and committed in
SQLite transactions. Owner access is checked on every call so Employee and Customer
accounts cannot invoke these operations directly.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

from inventory_db import connect, initialize, transaction
from payroll import Employee, Payroll, PayrollEntry, PayrollError
from accounting_service import post_source_transaction


def _ident(value: object, label: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit() and int(value) > 0:
        return int(value)
    raise PayrollError(f'{label} must be a positive whole number.')


def _owner_id(db: sqlite3.Connection, actor_id: int) -> int:
    """Return the actor's Owner.ownerID, or refuse anyone who is not an active Owner."""
    row = db.execute('''SELECT o.ownerID FROM "User" u JOIN "Owner" o ON o.userID=u.userID
                        WHERE u.userID=? AND u.role='Owner' AND u.accountActive=1
                        AND u.passwordHash IS NOT NULL''',
                     (_ident(actor_id, 'User ID'),)).fetchone()
    if row is None:
        raise PayrollError('Only an active Owner can manage payroll.')
    return row['ownerID']


def _employees(db: sqlite3.Connection, active_only: bool = True) -> dict[int, Employee]:
    sql = '''SELECT e.employeeID, e.hourlyRate, u.name FROM "Employee" e
             JOIN "User" u ON u.userID=e.userID'''
    if active_only:
        sql += ''' WHERE u.role='Employee' AND u.accountActive=1 AND COALESCE(e.isActive, 1)=1'''
    rows = db.execute(sql + ' ORDER BY u.name COLLATE NOCASE').fetchall()
    return {r['employeeID']: Employee(r['employeeID'], r['hourlyRate'] or 0, r['name'] or '')
            for r in rows}


def _load(db: sqlite3.Connection, payroll_id: int) -> Payroll:
    row = db.execute('SELECT * FROM Payroll WHERE payrollID=?',
                     (_ident(payroll_id, 'Payroll ID'),)).fetchone()
    if row is None:
        raise PayrollError(f'Payroll #{payroll_id} was not found.')
    entries = [PayrollEntry(e['entryID'], e['employeeID'], e['hoursWorked'], e['overtimeHours'],
                            e['deductions'], e['netPay'])
               for e in db.execute('SELECT * FROM PayrollEntry WHERE payrollID=? ORDER BY entryID',
                                   (row['payrollID'],))]
    return Payroll(row['payrollID'], row['payDate'], row['status'], row['totalAmount'],
                   entries, row['approvedByOwnerID'])


def _employee_problems(payroll: Payroll, employees: dict[int, Employee]) -> list[str]:
    """Alternate flow 2A / 3A data checks: each employee on the payroll must still be
    active and have an hourly rate before PayrollEntry.calculateNetPay() can run."""
    problems = []
    for entry in payroll.entries:
        employee = employees.get(entry.employeeID)
        if employee is None:
            problems.append(f'Employee #{entry.employeeID} is no longer an active employee. '
                            'Remove them from this payroll.')
        elif (employee.getHourlyRate() or 0) <= 0:
            problems.append(f'{employee.name or f"Employee #{entry.employeeID}"} has no hourly rate set.')
    return problems


def _named(problems: list[str], employees: dict[int, Employee]) -> list[str]:
    """Show names instead of IDs in the domain's hour-validation messages."""
    for employee in employees.values():
        if employee.name:
            problems = [p.replace(f'Employee #{employee.employeeID} ', f'{employee.name} ')
                        for p in problems]
    return problems


def _save_calculation(db: sqlite3.Connection, payroll: Payroll) -> None:
    for entry in payroll.entries:
        db.execute('UPDATE PayrollEntry SET deductions=?, netPay=? WHERE entryID=?',
                   (entry.deductions, entry.netPay, entry.entryID))
    db.execute('UPDATE Payroll SET totalAmount=? WHERE payrollID=?',
               (payroll.totalAmount, payroll.payrollID))


def _clear_calculation(db: sqlite3.Connection, payroll_id: int) -> None:
    """Changed hours or rates make earlier results stale: recalculate before approving."""
    db.execute('UPDATE PayrollEntry SET deductions=NULL, netPay=NULL WHERE payrollID=?', (payroll_id,))
    db.execute('UPDATE Payroll SET totalAmount=0 WHERE payrollID=?', (payroll_id,))


class PayrollService:
    """UI-independent payroll actions for an authenticated Owner."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        initialize(db_path)

    # ----- Employees and hourly rates (step 2, alternate flows 2A / 3A) -----
    def employees(self, actor_id: int) -> list[Employee]:
        db = connect(self.db_path)
        try:
            _owner_id(db, actor_id)
            return list(_employees(db).values())
        finally:
            db.close()

    def set_hourly_rate(self, actor_id: int, employee_id: int, rate: object) -> Employee:
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            employee = _employees(db).get(_ident(employee_id, 'Employee ID'))
            if employee is None:
                raise PayrollError(f'Employee #{employee_id} is not an active employee.')
            employee.setHourlyRate(rate)
            db.execute('UPDATE "Employee" SET hourlyRate=? WHERE employeeID=?',
                       (employee.hourlyRate, employee.employeeID))
            for (payroll_id,) in db.execute('''SELECT DISTINCT p.payrollID FROM Payroll p
                                               JOIN PayrollEntry e ON e.payrollID=p.payrollID
                                               WHERE p.status='Draft' AND e.employeeID=?''',
                                            (employee.employeeID,)).fetchall():
                _clear_calculation(db, payroll_id)
            return employee

    # ----- Payroll runs (steps 1, 3, 4-7, 8, 9-10) -----
    def open_payroll(self, actor_id: int, pay_date: object) -> int:
        """Step 1: the Owner opens a payroll for a pay date."""
        payroll = Payroll(None, pay_date)
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            if db.execute('SELECT 1 FROM Payroll WHERE payDate=?', (payroll.payDate,)).fetchone():
                raise PayrollError(f'A payroll for {payroll.payDate} already exists.')
            return db.execute('INSERT INTO Payroll(payDate, status, totalAmount) VALUES(?,?,0)',
                              (payroll.payDate, payroll.status)).lastrowid

    def payrolls(self, actor_id: int) -> list[dict]:
        db = connect(self.db_path)
        try:
            _owner_id(db, actor_id)
            return [dict(r) for r in db.execute('''
                SELECT p.payrollID, p.payDate, p.status, p.totalAmount,
                       COUNT(e.entryID) AS employees, p.accountingTransactionID
                FROM Payroll p LEFT JOIN PayrollEntry e ON e.payrollID=p.payrollID
                GROUP BY p.payrollID ORDER BY p.payDate DESC''')]
        finally:
            db.close()

    def get_payroll(self, actor_id: int, payroll_id: int) -> Payroll:
        db = connect(self.db_path)
        try:
            _owner_id(db, actor_id)
            return _load(db, payroll_id)
        finally:
            db.close()

    def enter_hours(self, actor_id: int, payroll_id: int, employee_id: int,
                    hours_worked: object, overtime_hours: object = 0) -> None:
        """Enter or correct hours for an employee in a draft payroll."""
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            payroll = _load(db, payroll_id)
            if payroll.status != 'Draft':
                raise PayrollError(f'This payroll is {payroll.status}; hours can no longer change.')
            employee_id = _ident(employee_id, 'Employee ID')
            if employee_id not in _employees(db):
                raise PayrollError(f'Employee #{employee_id} is not an active employee.')
            entry = PayrollEntry(None, employee_id, hours_worked, overtime_hours)
            db.execute('''INSERT INTO PayrollEntry(payrollID, employeeID, hoursWorked, overtimeHours)
                          VALUES(?,?,?,?)
                          ON CONFLICT(payrollID, employeeID) DO UPDATE SET
                          hoursWorked=excluded.hoursWorked, overtimeHours=excluded.overtimeHours''',
                       (payroll.payrollID, employee_id, entry.hoursWorked, entry.overtimeHours))
            _clear_calculation(db, payroll.payrollID)

    def remove_employee(self, actor_id: int, payroll_id: int, employee_id: int) -> None:
        """Take an employee who did not work this period off a draft payroll."""
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            payroll = _load(db, payroll_id)
            if payroll.status != 'Draft':
                raise PayrollError(f'This payroll is {payroll.status}; it can no longer change.')
            removed = db.execute('DELETE FROM PayrollEntry WHERE payrollID=? AND employeeID=?',
                                 (payroll.payrollID, _ident(employee_id, 'Employee ID'))).rowcount
            if not removed:
                raise PayrollError(f'Employee #{employee_id} is not on this payroll.')
            _clear_calculation(db, payroll.payrollID)

    def check_hours(self, actor_id: int, payroll_id: int) -> list[str]:
        """Validate recorded employee hours and return problems to correct."""
        db = connect(self.db_path)
        try:
            _owner_id(db, actor_id)
            payroll, employees = _load(db, payroll_id), _employees(db)
            problems: list[str] = _employee_problems(payroll, employees)
            payroll.validateHours(problems)
            return _named(problems, employees)
        finally:
            db.close()

    def calculate(self, actor_id: int, payroll_id: int) -> Payroll:
        """Steps 5-6: Payroll.calculatePay(), saved for the Owner's review."""
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            payroll, employees = _load(db, payroll_id), _employees(db)
            problems = _employee_problems(payroll, employees)
            if problems:
                raise PayrollError(' '.join(problems))
            payroll.calculatePay(employees)
            _save_calculation(db, payroll)
            return payroll

    def approve(self, actor_id: int, payroll_id: int) -> Payroll:
        """Step 7: Payroll.approve() records the approving Owner."""
        with transaction(self.db_path) as db:
            owner_id = _owner_id(db, actor_id)
            payroll = _load(db, payroll_id)
            payroll.approve(owner_id)
            db.execute('UPDATE Payroll SET status=?, approvedByOwnerID=? WHERE payrollID=?',
                       (payroll.status, payroll.approvedBy, payroll.payrollID))
            return payroll

    def pay_stubs(self, actor_id: int, payroll_id: int) -> list[str]:
        """Step 8: Payroll.generatePayStubs()."""
        db = connect(self.db_path)
        try:
            _owner_id(db, actor_id)
            # Include disabled employees so stubs for past payrolls still show names.
            names = {i: e.name for i, e in _employees(db, active_only=False).items()}
            return _load(db, payroll_id).generatePayStubs(names)
        finally:
            db.close()

    def record_expense(self, actor_id: int, payroll_id: int, today: object | None = None) -> int:
        """Steps 9-10: Payroll.recordExpense(). Marking the payroll Paid and posting
        the expense to the Accounting Ledger commit together or not at all."""
        with transaction(self.db_path) as db:
            _owner_id(db, actor_id)
            payroll = _load(db, payroll_id)
            expense = payroll.recordExpense(today or date.today())
            transaction_id = post_source_transaction(
                db, kind=expense.type, when=expense.date,
                description=expense.description, reference=expense.reference,
                amount=expense.amount, source_type='Payroll', source_id=payroll_id,
            )
            if transaction_id is None:
                raise PayrollError('This payroll has no positive payment amount to post.')
            db.execute('UPDATE Payroll SET status=?, accountingTransactionID=? WHERE payrollID=?',
                       (payroll.status, transaction_id, payroll.payrollID))
            return transaction_id
