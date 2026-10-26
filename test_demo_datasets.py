"""Optional module-specific demo datasets and their shared-ledger effects."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_service import AccountingLedger, AccountingTransaction
from demo_tools import (populate_accounting_activity, populate_demo_data,
                        populate_payroll_activity, populate_trend_history)
from inventory_cli import demo_menu
from inventory_db import connect
from inventory_service import InventoryError, InventoryService
from payroll_service import PayrollService
from trend_prediction_service import BusinessData, IngredientData, TrendPrediction


class DemoDatasetTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'shop.db'
        self.shop = InventoryService(self.path)
        self.owner = self.shop.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.employee = self.shop.create_user('Staff', 'staff', 'staff-password', 'Employee')

    def _count(self, table):
        with connect(self.path) as db:
            return db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]

    def test_historical_orders_use_existing_recipes_and_post_sales_and_restocks(self):
        populate_demo_data(self.shop, self.owner)
        before = self._count('Order')
        result = populate_trend_history(self.shop, self.owner)
        self.assertEqual(result, {'days': 12, 'completed_orders': 41,
                                  'sales_posted': 41, 'restock_deliveries': 1})
        self.assertEqual(self._count('Order'), before + 41)
        sale_entries = [e for e in AccountingLedger(self.path).getTransactions()
                        if e['sourceType'] == 'Order']
        self.assertEqual(len(sale_entries), 45)  # Includes four starter shop Sales.
        purchased = [e for e in AccountingLedger(self.path).getTransactions()
                     if e['sourceType'] == 'Delivery']
        self.assertEqual(len(purchased), 1)
        self.assertEqual(purchased[0]['transactionType'], 'Purchase')
        self.assertEqual(len(BusinessData('Sales', self.path).retrieve_data()), 13)
        self.assertEqual(len(BusinessData('Financial', self.path).retrieve_data()), 13)
        items = IngredientData.list_ingredients(self.path)
        rice = next(r for r in items if r['ingredientName'] == 'Sushi Rice')
        self.assertEqual(len(IngredientData(rice['ingredientID'], self.path).retrieve_data()), 13)
        self.assertGreater(TrendPrediction(BusinessData('Sales', self.path)).generate_prediction(), 0)
        self.assertTrue(all(float(item['quantityOnHand']) >= 0 for item in items))
        with connect(self.path) as db:
            assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            # A dated stock movement and its mirrored InventoryAdjustment date agree.
            self.assertGreater(db.execute("SELECT COUNT(*) FROM InventoryTransaction "
                                          "WHERE transactionType='Customer Order' "
                                          "AND substr(transactionDate,1,10) < date('now')").fetchone()[0], 0)

    def test_history_requires_starter_shop_and_has_no_partial_import(self):
        with self.assertRaisesRegex(InventoryError, 'starter shop dataset'):
            populate_trend_history(self.shop, self.owner)
        self.assertEqual(self._count('Order'), 0)
        populate_demo_data(self.shop, self.owner)
        self.assertEqual(populate_trend_history(self.shop, self.owner)['completed_orders'], 41)

    def test_repeating_history_does_not_create_more_orders_or_financial_entries(self):
        populate_demo_data(self.shop, self.owner)
        populate_trend_history(self.shop, self.owner)
        count_orders = self._count('Order')
        count_transactions = self._count('AccountingTransaction')
        with self.assertRaisesRegex(InventoryError, 'already loaded'):
            populate_trend_history(self.shop, self.owner)
        self.assertEqual(self._count('Order'), count_orders)
        self.assertEqual(self._count('AccountingTransaction'), count_transactions)

    def test_history_failure_rolls_back_all_new_orders_and_restock(self):
        populate_demo_data(self.shop, self.owner)
        before = (self._count('Order'), self._count('InventoryTransaction'),
                  self._count('AccountingTransaction'))
        with patch('demo_tools.post_source_transaction', side_effect=sqlite3.IntegrityError('test failure')):
            with self.assertRaises(sqlite3.IntegrityError):
                populate_trend_history(self.shop, self.owner)
        self.assertEqual((self._count('Order'), self._count('InventoryTransaction'),
                          self._count('AccountingTransaction')), before)
        self.assertEqual(populate_trend_history(self.shop, self.owner)['sales_posted'], 41)

    def test_accounting_examples_are_independent_and_reconcile_duplicate_reference(self):
        result = populate_accounting_activity(self.shop, self.owner)
        self.assertEqual(result['manual_transactions'], 10)
        self.assertEqual(self._count('AccountingTransaction'), 10)
        ledger = AccountingLedger(self.path)
        self.assertEqual(len(ledger.getTransactions()), 10)
        self.assertEqual(ledger.reconcile_with_report()['newFlags'], 2)
        duplicates = ledger.getDiscrepancies('Flagged')
        self.assertEqual(len(duplicates), 2)
        with self.assertRaisesRegex(InventoryError, 'already loaded'):
            populate_accounting_activity(self.shop, self.owner)
        self.assertEqual(self._count('AccountingTransaction'), 10)
        tx = next(row for row in ledger.getTransactions() if row['description'].endswith(' B'))
        ledger.updateTransaction(AccountingTransaction(tx['transactionID'], 'Expense',
                                                        tx['transactionDate'], tx['description'],
                                                        'DEMO-FIXED-1', tx['amount']))
        self.assertEqual(ledger.reconcile_with_report()['clearedFlags'], 2)

    def test_payroll_requires_eligible_employee_and_posts_one_real_source_link(self):
        with self.assertRaisesRegex(InventoryError, 'hourly rate'):
            populate_payroll_activity(self.shop, self.owner)
        with connect(self.path) as db:
            eid = db.execute('SELECT employeeID FROM Employee WHERE userID=?',
                             (self.employee,)).fetchone()[0]
        pay = PayrollService(self.path)
        pay.set_hourly_rate(self.owner, eid, 23.50)
        result = populate_payroll_activity(self.shop, self.owner)
        self.assertEqual(result['employees'], 1)
        record = pay.get_payroll(self.owner, result['payroll_id'])
        self.assertEqual(record.status, 'Paid')
        self.assertGreater(record.totalAmount, 0)
        self.assertIn('NET PAY:', pay.pay_stubs(self.owner, result['payroll_id'])[0])
        entries = [e for e in AccountingLedger(self.path).getTransactions()
                   if e['sourceType'] == 'Payroll']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['sourceID'], result['payroll_id'])
        self.assertEqual(entries[0]['amount'], record.totalAmount)
        with self.assertRaisesRegex(InventoryError, 'already loaded'):
            populate_payroll_activity(self.shop, self.owner)

    def test_payroll_example_rolls_back_if_accounting_post_fails(self):
        with connect(self.path) as db:
            eid = db.execute('SELECT employeeID FROM Employee WHERE userID=?',
                             (self.employee,)).fetchone()[0]
        PayrollService(self.path).set_hourly_rate(self.owner, eid, 20)
        with patch('demo_tools.post_source_transaction', side_effect=sqlite3.IntegrityError('posting failed')):
            with self.assertRaises(sqlite3.IntegrityError):
                populate_payroll_activity(self.shop, self.owner)
        self.assertEqual(self._count('Payroll'), 0)
        self.assertEqual(self._count('AccountingTransaction'), 0)
        self.assertEqual(populate_payroll_activity(self.shop, self.owner)['accounting_expenses'], 1)

    def test_employee_cannot_seed_financial_data(self):
        for loader in (populate_accounting_activity, populate_payroll_activity,
                       populate_trend_history):
            with self.assertRaisesRegex(InventoryError, 'Owner'):
                loader(self.shop, self.employee)
        self.assertEqual(self._count('AccountingTransaction'), 0)

    def test_accounting_examples_work_with_newer_date_and_type_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'new_accounting.db'
            with sqlite3.connect(path) as db:
                db.executescript('''
                    CREATE TABLE AccountingLedger(ledgerID INTEGER PRIMARY KEY, ledgerName TEXT);
                    INSERT INTO AccountingLedger VALUES(1,'Sample');
                    CREATE TABLE AccountingTransaction(
                        transactionID INTEGER PRIMARY KEY, ledgerID INTEGER,
                        transactionDate TEXT NOT NULL, transactionType TEXT NOT NULL,
                        description TEXT NOT NULL, reference TEXT NOT NULL,
                        amount REAL NOT NULL CHECK(amount >= 0));
                ''')
            svc = InventoryService(path)
            owner = svc.create_user('Owner', 'owner', 'owner-password', 'Owner')
            self.assertEqual(populate_accounting_activity(svc, owner)['manual_transactions'], 10)
            with connect(path) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM AccountingTransaction').fetchone()[0], 10)
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')

    def test_demo_menu_nested_accounting_seed(self):
        owner = self.shop.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=['1', '3', '', '0']), \
             patch('inventory_cli.confirm', return_value=True), \
             patch('inventory_cli.getpass', return_value='owner-password'), \
             patch('builtins.input', return_value=''), redirect_stdout(StringIO()) as printed:
            self.assertFalse(demo_menu(self.shop, owner))
        self.assertEqual(self._count('AccountingTransaction'), 10)
        self.assertIn('reconciliation', printed.getvalue())


if __name__ == '__main__':
    unittest.main()
