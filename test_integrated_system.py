"""Regression checks for loyalty, payroll, inventory, profiles, and shared menus."""

from pathlib import Path
from contextlib import redirect_stdout
from io import StringIO
import tempfile
import unittest
from unittest.mock import patch

from inventory_cli import menu, payroll_menu
from inventory_db import connect
from inventory_service import InventoryService
from loyalty_service import LoyaltyService
from payroll_service import PayrollService
from profile_service import ProfileService


class IntegratedSystemTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db_path = Path(temporary.name) / 'shop.db'
        self.inventory = InventoryService(self.db_path)
        self.owner_id = self.inventory.create_user(
            'Shop Owner', 'owner', 'owner-password', 'Owner')
        self.employee_id = self.inventory.create_user(
            'Shop Employee', 'employee', 'employee-password', 'Employee')
        self.customer_user_id = self.inventory.create_user(
            'Shop Customer', 'customer', 'customer-password', 'Customer')
        with connect(self.db_path) as db:
            self.employee_record_id = db.execute(
                'SELECT employeeID FROM Employee WHERE userID=?',
                (self.employee_id,)).fetchone()[0]
        self.loyalty = LoyaltyService(self.db_path)
        self.payroll = PayrollService(self.db_path)

    def test_loyalty_and_payroll_share_one_persistent_database(self):
        # One order updates stock and loyalty; a separate payroll posts an expense.
        ingredient_id = self.inventory.add_ingredient('Rice', 'g', 1000, 200, self.owner_id)
        recipe_id = self.inventory.add_recipe('Plain Onigiri', 8)
        self.inventory.set_recipe_ingredient(recipe_id, ingredient_id, 100)
        customer_id = self.loyalty.customer_id_for_user(self.customer_user_id)
        self.loyalty.enroll_existing_customer(self.customer_user_id, self.owner_id)
        order_id = self.inventory.create_customer_order(
            {recipe_id: 2}, self.employee_id, customer_id)
        result = self.loyalty.complete_order_with_loyalty(
            self.employee_id, customer_id, order_id)
        self.assertEqual(result['pointsEarned'], 160)

        self.payroll.set_hourly_rate(self.owner_id, self.employee_record_id, 20)
        payroll_id = self.payroll.open_payroll(self.owner_id, '2026-10-30')
        self.payroll.enter_hours(self.owner_id, payroll_id, self.employee_record_id, 40, 2)
        self.assertEqual(self.payroll.check_hours(self.owner_id, payroll_id), [])
        self.assertEqual(self.payroll.calculate(self.owner_id, payroll_id).totalAmount, 860)
        self.payroll.approve(self.owner_id, payroll_id)
        transaction_id = self.payroll.record_expense(self.owner_id, payroll_id)

        updated = ProfileService(self.db_path).update_profile(
            self.customer_user_id, {'email': 'customer@example.test'})
        self.assertEqual(updated.email, 'customer@example.test')

        # Re-initializing the program must neither wipe history nor duplicate rows.
        InventoryService(self.db_path)
        LoyaltyService(self.db_path)
        PayrollService(self.db_path)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute(
                'SELECT quantityOnHand FROM InventoryItem WHERE ingredientID=?',
                (ingredient_id,)).fetchone()[0], 800)
            self.assertEqual(db.execute(
                'SELECT pointsBalance FROM LoyaltyAccount WHERE customerID=?',
                (customer_id,)).fetchone()[0], 160)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM PayrollEntry').fetchone()[0], 1)
            self.assertEqual(db.execute(
                'SELECT status FROM Payroll WHERE payrollID=?',
                (payroll_id,)).fetchone()[0], 'Paid')
            expense = db.execute(
                'SELECT amount, type FROM AccountingTransaction WHERE transactionID=?',
                (transaction_id,)).fetchone()
            self.assertEqual(tuple(expense), (860, 'Expense'))
            self.assertEqual(db.execute(
                'SELECT email FROM "User" WHERE userID=?',
                (self.customer_user_id,)).fetchone()[0], 'customer@example.test')

    def test_staff_main_menu_routes_loyalty_and_payroll_independently(self):
        owner = self.inventory.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=['19', '20', '17']), \
             patch('inventory_cli.loyalty_staff_menu') as loyalty_menu, \
             patch('inventory_cli.payroll_menu') as payroll_menu, \
             patch('builtins.input', return_value=''):
            menu(self.inventory, owner)
        loyalty_menu.assert_called_once()
        payroll_menu.assert_called_once()

    def test_customer_menu_has_loyalty_but_no_payroll(self):
        customer = self.inventory.login('customer', 'customer-password')
        with patch('inventory_cli.prompt', side_effect=['20', '17']), \
             patch('inventory_cli.payroll_menu') as payroll_menu:
            menu(self.inventory, customer)
        payroll_menu.assert_not_called()

    def test_payroll_cli_guides_missing_records_and_loops_rate_entry(self):
        owner = self.inventory.login('owner', 'owner-password')
        answers = [
            '2',                          # No payroll exists; direct instruction to create one
            '7', '999',                    # Invalid Employee ID, then valid Employee ID
            str(self.employee_record_id), '19', '',
            '1', '2026-10-30',            # Open draft
            '2', '999', '1', '',           # Payroll ID is checked before employee hours
            '0',
        ]
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=answers), \
             patch('inventory_cli.confirm', return_value=True), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            payroll_menu(self.inventory, owner)
        self.assertIn('No payrolls exist yet', output.getvalue())
        self.assertIn('not active or does not exist', output.getvalue())
        self.assertIn('was not found', output.getvalue())
        self.assertEqual(
            self.payroll.employees(self.owner_id)[0].getHourlyRate(), 19)
        self.assertEqual(len(self.payroll.payrolls(self.owner_id)), 1)


if __name__ == '__main__':
    unittest.main()
