"""Cross-module financial postings, source links, and legacy-schema checks."""
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_service import AccountingError, AccountingLedger, AccountingTransaction
from inventory_cli import accounting_menu, menu
from inventory_db import connect
from inventory_service import InventoryError, InventoryService, InsufficientStockError
from loyalty_service import LoyaltyService
from payroll_service import PayrollService
from payroll import PayrollError


class FinancialIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'shop.db'
        self.inv = InventoryService(self.path)
        self.owner = self.inv.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.employee = self.inv.create_user('Employee', 'employee', 'employee-password', 'Employee')
        self.customer_user = self.inv.create_user('Customer', 'customer', 'customer-password', 'Customer')
        self.ledger = AccountingLedger(self.path)
        self.loyalty = LoyaltyService(self.path)
        self.rice = self.inv.add_ingredient('Rice', 'g', 1000, 100, self.owner)
        self.recipe = self.inv.add_recipe('Onigiri', 10)
        self.inv.set_recipe_ingredient(self.recipe, self.rice, 20)

    def _entries(self, source):
        return [r for r in self.ledger.getTransactions() if r['sourceType'] == source]

    def test_completed_order_posts_one_sale_and_pending_does_not(self):
        order_id = self.inv.create_customer_order({self.recipe: 2}, self.employee)
        self.assertEqual(self._entries('Order'), [])
        result = self.inv.complete_customer_order(order_id, self.employee)
        self.assertIsNotNone(result['accounting_transaction_id'])
        self.assertEqual([(r['amount'], r['sourceID'], r['transactionType'])
                          for r in self._entries('Order')], [(20, order_id, 'Sale')])
        with self.assertRaises(InventoryError):
            self.inv.complete_customer_order(order_id, self.employee)
        self.assertEqual(len(self._entries('Order')), 1)
        self.assertEqual(self.ledger.sync_completed_orders(), 0)

    def test_failed_completion_does_not_post_sale_or_deduct_stock(self):
        order = self.inv.create_customer_order({self.recipe: 60}, self.employee)
        with self.assertRaises(InsufficientStockError):
            self.inv.complete_customer_order(order, self.employee)
        self.assertEqual(self._entries('Order'), [])
        self.assertEqual(self.inv.order_details(order)['status'], 'Pending')

    def test_loyalty_discount_updates_one_sale_even_when_recorded_later(self):
        self.loyalty.enroll_existing_customer(self.customer_user, self.employee)
        cid = self.loyalty.customer_id_for_user(self.customer_user)
        reward = self.loyalty.create_reward(self.owner, 'Five off', 10, '5.00')
        earning_order = self.inv.create_customer_order({self.recipe: 2}, self.employee, cid)
        self.loyalty.complete_order_with_loyalty(self.employee, cid, earning_order)
        discounted_order = self.inv.create_customer_order({self.recipe: 1}, self.employee, cid)
        self.loyalty.complete_order_with_loyalty(self.employee, cid, discounted_order,
                                                reward_id=reward)
        sale = next(r for r in self._entries('Order') if r['sourceID'] == discounted_order)
        self.assertEqual(sale['amount'], 5.0)
        self.assertEqual(len(self._entries('Order')), 2)
        later_order = self.inv.create_customer_order({self.recipe: 1}, self.employee)
        original = self.inv.complete_customer_order(later_order, self.employee)
        self.loyalty.process_eligible_purchase(self.employee, cid, later_order,
                                               reward_id=reward)
        new_row = next(r for r in self._entries('Order') if r['sourceID'] == later_order)
        self.assertEqual(new_row['transactionID'], original['accounting_transaction_id'])
        self.assertEqual(new_row['amount'], 5.0)

    def test_zero_net_discount_creates_no_false_sale(self):
        self.loyalty.enroll_existing_customer(self.customer_user, self.employee)
        cid = self.loyalty.customer_id_for_user(self.customer_user)
        reward = self.loyalty.create_reward(self.owner, 'Full discount', 10, '10.00')
        order_one = self.inv.create_customer_order({self.recipe: 2}, self.employee, cid)
        self.loyalty.complete_order_with_loyalty(self.employee, cid, order_one)
        order_two = self.inv.create_customer_order({self.recipe: 1}, self.employee, cid)
        completed = self.loyalty.complete_order_with_loyalty(self.employee, cid, order_two,
                                                               reward_id=reward)
        self.assertEqual(completed['finalAmount'], 0)
        self.assertIsNone(completed['accounting_transaction_id'])
        self.assertNotIn(order_two, [r['sourceID'] for r in self._entries('Order')])

    def test_delivery_posts_only_known_invoice_value_and_rolls_back_invalid(self):
        supplier = self.inv.add_supplier('Rice supplier')
        po = self.inv.create_purchase_order({self.rice: 100})
        self.assertEqual(self._entries('Purchase'), [])
        self.assertIsNone(self.inv.receive_delivery({self.rice: 20}, self.employee, supplier, po))
        self.assertEqual(self._entries('Delivery'), [])
        tx_id = self.inv.receive_delivery({self.rice: 30}, self.employee, supplier, po,
                                          purchase_amount=12.50, invoice_reference='RICE-30')
        self.assertGreater(tx_id, 0)
        purchased = self._entries('Delivery')
        self.assertEqual([(r['amount'], r['reference'], r['transactionType']) for r in purchased],
                         [(12.50, 'RICE-30', 'Purchase')])
        stock_before = self.inv.inventory()[0]['quantityOnHand']
        with self.assertRaises((InventoryError, AccountingError)):
            self.inv.receive_delivery({self.rice: 10}, self.employee, supplier, po,
                                      purchase_amount=-4)
        self.assertEqual(self.inv.inventory()[0]['quantityOnHand'], stock_before)
        self.assertEqual(len(self._entries('Delivery')), 1)

    def test_valued_stock_adjustment_posts_separately_from_quantity_movements(self):
        self.inv.adjust_stock(self.rice, 'remove', 10, self.owner, 'Spoiled')
        self.assertEqual(self._entries('Adjustment'), [])
        self.inv.adjust_stock(self.rice, 'remove', 5, self.owner, 'Write-off',
                              accounting_amount=7.25)
        valued = self._entries('Adjustment')
        self.assertEqual([(r['transactionType'], r['amount']) for r in valued],
                         [('Inventory Adjustment', 7.25)])
        self.assertEqual(self.ledger.calculateSummary().totalAdjustments, 7.25)

    def test_paid_payroll_posts_once_and_all_sources_appear_in_dashboard(self):
        with connect(self.path) as db:
            eid = db.execute('SELECT employeeID FROM Employee WHERE userID=?',
                             (self.employee,)).fetchone()[0]
        pay = PayrollService(self.path)
        pay.set_hourly_rate(self.owner, eid, 20)
        payroll = pay.open_payroll(self.owner, '2026-10-30')
        pay.enter_hours(self.owner, payroll, eid, 40)
        pay.calculate(self.owner, payroll)
        pay.approve(self.owner, payroll)
        posting = pay.record_expense(self.owner, payroll)
        self.assertEqual([(r['transactionID'], r['sourceID']) for r in self._entries('Payroll')],
                         [(posting, payroll)])
        with self.assertRaises(PayrollError):
            pay.record_expense(self.owner, payroll)
        order = self.inv.create_customer_order({self.recipe: 1}, self.owner)
        self.inv.complete_customer_order(order, self.owner)
        dashboard = self.ledger.dashboard()
        self.assertEqual({r['sourceType'] for r in dashboard['transactions']}, {'Order', 'Payroll'})
        with self.assertRaisesRegex(AccountingError, 'belongs to'):
            self.ledger.updateTransaction(AccountingTransaction(
                posting, 'Expense', date.today().isoformat(), 'Edited', 'PAYROLL-1', 100))

    def test_historical_completed_orders_backfill_only_once(self):
        old_order = self.inv.create_customer_order({self.recipe: 1}, self.owner)
        with connect(self.path) as db:
            db.execute('UPDATE "Order" SET status="Completed" WHERE orderID=?', (old_order,))
            db.commit()
        self.assertEqual(self.ledger.sync_completed_orders(), 1)
        self.assertEqual(self.ledger.sync_completed_orders(), 0)
        self.assertEqual(len(self._entries('Order')), 1)

    def test_existing_manual_sales_block_automatic_historical_import(self):
        old_order = self.inv.create_customer_order({self.recipe: 1}, self.owner)
        with connect(self.path) as db:
            db.execute('UPDATE "Order" SET status="Completed" WHERE orderID=?', (old_order,))
            db.commit()
        self.ledger.addTransaction(AccountingTransaction(
            None, 'Sale', date.today().isoformat(), 'Possible past sale', 'OLD-SALE', 10))
        self.assertEqual(self.ledger.manual_sale_count(), 1)
        self.assertEqual(self.ledger.sync_completed_orders(), 0)
        self.assertEqual(len(self.ledger.pending_completed_orders()), 1)
        self.assertEqual(self.ledger.sync_completed_orders(
            allow_with_manual_sales=True, order_ids={old_order}), 1)
        self.assertEqual(self.ledger.sync_completed_orders(
            allow_with_manual_sales=True, order_ids={old_order}), 0)

    def test_accounting_menu_owner_only_no_auto_demo_data(self):
        with redirect_stdout(StringIO()) as out:
            accounting_menu({'role': 'Employee'}, self.path)
        self.assertIn('Owners only', out.getvalue())
        with patch('builtins.input', side_effect=['2', '', '0']):
            with redirect_stdout(StringIO()) as result:
                accounting_menu({'role': 'Owner'}, self.path)
        self.assertIn('No accounting transactions', result.getvalue())

    def test_main_menu_routes_accounting_after_renumbering(self):
        owner = self.inv.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=['18', '23']), \
             patch('inventory_cli.accounting_menu') as accounting, \
             patch('builtins.input', return_value=''), redirect_stdout(StringIO()) as out:
            menu(self.inv, owner)
        accounting.assert_called_once_with(owner, self.path)
        displayed = out.getvalue()
        self.assertIn('12. Create inventory purchase order', displayed)
        self.assertIn('13. View inventory purchase orders', displayed)
        self.assertIn('17. Payroll (Owner)', displayed)
        self.assertIn('18. Accounting Ledger (Owner)', displayed)


class NewAccountingSchemaTests(unittest.TestCase):
    def test_payroll_can_post_to_preexisting_accounting_format(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'shop.db'
            with sqlite3.connect(path) as db:
                db.executescript('''
                    CREATE TABLE AccountingLedger (
                        ledgerID INTEGER PRIMARY KEY CHECK(ledgerID=1),
                        ledgerName TEXT NOT NULL DEFAULT 'Onigiri Shop Accounting Ledger');
                    INSERT INTO AccountingLedger(ledgerID) VALUES (1);
                    CREATE TABLE AccountingTransaction (
                        transactionID INTEGER PRIMARY KEY, ledgerID INTEGER NOT NULL DEFAULT 1,
                        transactionType TEXT NOT NULL, transactionDate TEXT NOT NULL,
                        description TEXT NOT NULL, reference TEXT NOT NULL DEFAULT '',
                        amount REAL NOT NULL CHECK(amount>=0),
                        createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY(ledgerID) REFERENCES AccountingLedger(ledgerID));
                ''')
            inv = InventoryService(path)
            owner = inv.create_user('Owner', 'owner', 'owner-password', 'Owner')
            worker = inv.create_user('Worker', 'worker', 'worker-password', 'Employee')
            with connect(path) as db:
                employee_id = db.execute('SELECT employeeID FROM Employee WHERE userID=?',
                                         (worker,)).fetchone()[0]
            pay = PayrollService(path)
            pay.set_hourly_rate(owner, employee_id, 25)
            payroll = pay.open_payroll(owner, '2026-10-30')
            pay.enter_hours(owner, payroll, employee_id, 40)
            pay.calculate(owner, payroll)
            pay.approve(owner, payroll)
            transaction_id = pay.record_expense(owner, payroll)
            with connect(path) as db:
                record = db.execute('SELECT transactionType,transactionDate,sourceType,sourceID '
                                    'FROM AccountingTransaction WHERE transactionID=?',
                                    (transaction_id,)).fetchone()
                self.assertEqual(tuple(record), ('Expense', date.today().isoformat(), 'Payroll', payroll))
                self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main()
