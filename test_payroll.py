"""Payroll domain rules, Owner-only access, flow and rollback tests."""
from contextlib import closing
import dataclasses
import inspect
import sqlite3
import tempfile
from pathlib import Path
import unittest

from inventory_db import connect
from inventory_service import InventoryError, InventoryService
from user_management_service import UserManagementService
from demo_tools import reset_database
from payroll import (AccountingTransaction, Employee, Payroll, PayrollEntry, PayrollError,
                     MAX_REGULAR_HOURS)
from payroll_service import PayrollService


class DiagramConsistencyTests(unittest.TestCase):
    """Protect the established payroll domain object's public interface."""

    DIAGRAM = {
        Payroll: ({'payrollID', 'payDate', 'status', 'totalAmount'},
                  {'calculatePay', 'validateHours', 'approve', 'generatePayStubs', 'recordExpense'}),
        PayrollEntry: ({'entryID', 'hoursWorked', 'overtimeHours', 'deductions', 'netPay'},
                       {'calculateNetPay'}),
        Employee: ({'employeeID', 'hourlyRate'}, {'getHourlyRate', 'setHourlyRate'}),
        AccountingTransaction: ({'transactionID', 'date', 'description', 'reference', 'amount', 'type'},
                                {'validateTransaction'}),
    }
    # Associations and inherited attributes, implemented as references.
    LINKS = {Payroll: {'entries', 'approvedBy'}, PayrollEntry: {'employeeID'}, Employee: {'name'},
             AccountingTransaction: set()}

    def test_classes_have_exactly_the_diagram_attributes_and_methods(self):
        for cls, (attributes, methods) in self.DIAGRAM.items():
            with self.subTest(cls=cls.__name__):
                fields = {f.name for f in dataclasses.fields(cls)}
                self.assertEqual(fields, attributes | self.LINKS[cls])
                public = {name for name, _ in inspect.getmembers(cls, inspect.isfunction)
                          if not name.startswith('_')}
                self.assertEqual(public, methods)


class PayrollDomainTests(unittest.TestCase):
    def test_net_pay_uses_overtime_and_flat_deductions(self):
        entry = PayrollEntry(None, 1, 80, 5)
        self.assertEqual(entry.calculateNetPay(Employee(1, 20)), 1400.00)  # (1600 + 150) * 0.8
        self.assertEqual(entry.deductions, 350.00)

    def test_entry_and_rate_validation(self):
        for bad in (-1, 'abc', float('inf'), True):
            with self.subTest(bad=bad), self.assertRaises(PayrollError):
                PayrollEntry(None, 1, bad)
        with self.assertRaises(PayrollError):
            PayrollEntry(None, 1, 10).calculateNetPay(Employee(2, 20))
        with self.assertRaises(PayrollError):
            PayrollEntry(None, 1, 10).calculateNetPay(Employee(1, 0))
        employee = Employee(1, 0)
        for bad in (0, -5, 'x'):
            with self.subTest(rate=bad), self.assertRaises(PayrollError):
                employee.setHourlyRate(bad)
        employee.setHourlyRate('17.255')
        self.assertEqual(employee.getHourlyRate(), 17.26)

    def test_status_order_is_enforced(self):
        payroll = Payroll(1, '2026-10-30', entries=[PayrollEntry(1, 1, 10)])
        employees = {1: Employee(1, 20, 'Ana')}
        for blocked in (lambda: payroll.approve(1), lambda: payroll.generatePayStubs({1: 'Ana'}),
                        lambda: payroll.recordExpense('2026-10-30')):
            with self.assertRaises(PayrollError):
                blocked()
        payroll.calculatePay(employees)
        payroll.approve(7)
        self.assertEqual((payroll.status, payroll.approvedBy), ('Approved', 7))
        with self.assertRaises(PayrollError):
            payroll.calculatePay(employees)
        self.assertIn('NET PAY:             $160.00', payroll.generatePayStubs({1: 'Ana'})[0])
        expense = payroll.recordExpense('2026-10-30')
        self.assertEqual((payroll.status, expense.amount, expense.type), ('Paid', 200.0, 'Expense'))
        self.assertTrue(expense.validateTransaction())

    def test_validate_transaction(self):
        good = AccountingTransaction(None, '2026-10-30', 'Payroll', 'PAYROLL-1', 10, 'Expense')
        self.assertTrue(good.validateTransaction())
        for change in ({'date': '30/10/2026'}, {'amount': 0}, {'description': ' '},
                       {'reference': ''}, {'type': 'Gift'}):
            with self.subTest(change=change):
                self.assertFalse(dataclasses.replace(good, **change).validateTransaction())

    def test_bad_pay_date_rejected(self):
        for bad in ('2026-02-30', '30-10-2026', ''):
            with self.subTest(bad=bad), self.assertRaises(PayrollError):
                Payroll(None, bad)


class PayrollServiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'onigiri.db'
        inventory = InventoryService(self.path)
        self.owner = inventory.create_user('Owner One', 'owner', 'owner-password', 'Owner')
        self.ana_user = inventory.create_user('Ana', 'ana', 'employee-password', 'Employee')
        self.ben_user = inventory.create_user('Ben', 'ben', 'employee-password', 'Employee')
        self.customer = inventory.create_user('Cora', 'cora', 'customer-password', 'Customer')
        with closing(connect(self.path)) as db, db:
            ids = dict(db.execute('SELECT userID, employeeID FROM Employee').fetchall())
        self.ana, self.ben = ids[self.ana_user], ids[self.ben_user]
        self.pay = PayrollService(self.path)

    def _ready_payroll(self) -> int:
        self.pay.set_hourly_rate(self.owner, self.ana, 20)
        self.pay.set_hourly_rate(self.owner, self.ben, 18)
        payroll_id = self.pay.open_payroll(self.owner, '2026-10-30')
        self.pay.enter_hours(self.owner, payroll_id, self.ana, 80, 5)
        self.pay.enter_hours(self.owner, payroll_id, self.ben, 40)
        return payroll_id

    def _count(self, table: str) -> int:
        with closing(connect(self.path)) as db, db:
            return db.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]

    def test_only_owner_can_use_payroll(self):
        payroll_id = self._ready_payroll()
        for actor in (self.ana_user, self.customer, 9999):
            for call in (lambda: self.pay.employees(actor),
                         lambda: self.pay.set_hourly_rate(actor, self.ana, 99),
                         lambda: self.pay.open_payroll(actor, '2026-11-13'),
                         lambda: self.pay.payrolls(actor),
                         lambda: self.pay.enter_hours(actor, payroll_id, self.ana, 1),
                         lambda: self.pay.calculate(actor, payroll_id),
                         lambda: self.pay.approve(actor, payroll_id),
                         lambda: self.pay.record_expense(actor, payroll_id)):
                with self.subTest(actor=actor), self.assertRaises(PayrollError):
                    call()

    def test_full_use_case_flow_posts_expense_to_ledger(self):
        payroll_id = self._ready_payroll()
        self.assertEqual(self.pay.check_hours(self.owner, payroll_id), [])
        payroll = self.pay.calculate(self.owner, payroll_id)
        self.assertEqual(payroll.totalAmount, 1750.0 + 720.0)
        self.pay.approve(self.owner, payroll_id)
        self.assertEqual(len(self.pay.pay_stubs(self.owner, payroll_id)), 2)
        transaction_id = self.pay.record_expense(self.owner, payroll_id, '2026-10-30')
        with closing(connect(self.path)) as db, db:
            row = db.execute('SELECT * FROM AccountingTransaction WHERE transactionID=?',
                             (transaction_id,)).fetchone()
            linked = db.execute('SELECT status, accountingTransactionID FROM Payroll').fetchone()
        self.assertEqual((row['amount'], row['type'], row['reference'], row['ledgerID']),
                         (2470.0, 'Expense', f'PAYROLL-{payroll_id}', 1))
        self.assertEqual(tuple(linked), ('Paid', transaction_id))

    def test_missing_rate_and_bad_hours_are_flagged(self):
        payroll_id = self.pay.open_payroll(self.owner, '2026-10-30')
        self.assertTrue(self.pay.check_hours(self.owner, payroll_id))  # no hours yet
        self.pay.enter_hours(self.owner, payroll_id, self.ana, MAX_REGULAR_HOURS + 1)
        self.pay.enter_hours(self.owner, payroll_id, self.ben, 0)
        problems = ' '.join(self.pay.check_hours(self.owner, payroll_id))
        for expected in ('no hourly rate', 'regular hours', '0 hours'):
            self.assertIn(expected, problems)
        with self.assertRaises(PayrollError):
            self.pay.calculate(self.owner, payroll_id)
        self.pay.set_hourly_rate(self.owner, self.ana, 20)
        self.pay.set_hourly_rate(self.owner, self.ben, 20)
        self.pay.enter_hours(self.owner, payroll_id, self.ana, 80, 1)
        self.pay.remove_employee(self.owner, payroll_id, self.ben)
        self.assertEqual(self.pay.check_hours(self.owner, payroll_id), [])

    def test_disabled_employee_is_flagged(self):
        payroll_id = self._ready_payroll()
        UserManagementService(self.path).set_active(self.owner, self.ben_user, False)
        self.assertIn('no longer an active employee', ' '.join(self.pay.check_hours(self.owner, payroll_id)))

    def test_changes_after_calculation_require_recalculation(self):
        payroll_id = self._ready_payroll()
        self.pay.calculate(self.owner, payroll_id)
        self.pay.enter_hours(self.owner, payroll_id, self.ben, 41)
        with self.assertRaises(PayrollError):
            self.pay.approve(self.owner, payroll_id)
        self.pay.calculate(self.owner, payroll_id)
        self.pay.set_hourly_rate(self.owner, self.ana, 21)
        with self.assertRaises(PayrollError):
            self.pay.approve(self.owner, payroll_id)
        self.pay.calculate(self.owner, payroll_id)
        self.pay.approve(self.owner, payroll_id)

    def test_approved_and_paid_payrolls_cannot_change(self):
        payroll_id = self._ready_payroll()
        self.pay.calculate(self.owner, payroll_id)
        self.pay.approve(self.owner, payroll_id)
        self.pay.set_hourly_rate(self.owner, self.ana, 30)  # does not alter the approved amounts
        self.assertEqual(self.pay.get_payroll(self.owner, payroll_id).totalAmount, 2470.0)
        for call in (lambda: self.pay.enter_hours(self.owner, payroll_id, self.ana, 1),
                     lambda: self.pay.remove_employee(self.owner, payroll_id, self.ana),
                     lambda: self.pay.calculate(self.owner, payroll_id),
                     lambda: self.pay.approve(self.owner, payroll_id)):
            with self.assertRaises(PayrollError):
                call()
        self.pay.record_expense(self.owner, payroll_id)
        with self.assertRaises(PayrollError):
            self.pay.record_expense(self.owner, payroll_id)
        self.assertEqual(self._count('AccountingTransaction'), 1)

    def test_duplicate_pay_date_rejected(self):
        self.pay.open_payroll(self.owner, '2026-10-30')
        with self.assertRaises(PayrollError):
            self.pay.open_payroll(self.owner, '2026-10-30')

    def test_failed_expense_save_rolls_back_everything(self):
        payroll_id = self._ready_payroll()
        self.pay.calculate(self.owner, payroll_id)
        self.pay.approve(self.owner, payroll_id)
        with closing(connect(self.path)) as db, db:
            db.execute('''CREATE TRIGGER fail_paid BEFORE UPDATE OF status ON Payroll
                          WHEN NEW.status='Paid' BEGIN SELECT RAISE(ABORT, 'simulated failure'); END''')
        with self.assertRaises(sqlite3.Error):
            self.pay.record_expense(self.owner, payroll_id)
        self.assertEqual(self._count('AccountingTransaction'), 0)
        self.assertEqual(self.pay.get_payroll(self.owner, payroll_id).status, 'Approved')

    def test_payroll_history_protects_employee_from_deletion(self):
        self._ready_payroll()
        with self.assertRaises(InventoryError):
            UserManagementService(self.path).delete_account(self.owner, self.ben_user)

    def test_reset_keeps_rates_and_clears_payrolls(self):
        payroll_id = self._ready_payroll()
        self.pay.calculate(self.owner, payroll_id)
        reset_database(InventoryService(self.path), self.owner, with_demo=False)
        self.assertEqual(self._count('Payroll'), 0)
        rates = sorted(e.getHourlyRate() for e in self.pay.employees(self.owner))
        self.assertEqual(rates, [18.0, 20.0])


if __name__ == '__main__':
    unittest.main()
