"""Loyalty integration and error-handling tests. Run: python -m unittest test_loyalty -v"""
from contextlib import redirect_stdout
from decimal import Decimal
import io
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory_db import connect, initialize
from inventory_service import InventoryService, InventoryError
from loyalty_service import (AccountNotFoundError, DuplicatePurchaseError,
                             InsufficientPointsError, LoyaltyError, LoyaltyService)
from user_management_service import UserManagementService
from profile_service import ProfileService
from inventory_cli import loyalty_customer_menu, loyalty_staff_menu, complete_order_flow, orders_menu, order_create


class LoyaltyUseCaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'shop.db'
        self.inv = InventoryService(self.path)
        self.owner = self.inv.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.employee = self.inv.create_user('Worker', 'staff', 'staff-password', 'Employee')
        self.existing_user = self.inv.create_user('Existing Customer', 'patron',
                                                  'customer-password', 'Customer',
                                                  email='existing@example.com')
        self.loyalty = LoyaltyService(self.path, points_per_dollar=1)  # Test legacy rate override
        self.existing_customer = self.loyalty.customer_id_for_user(self.existing_user)
        self.ingredient = self.inv.add_ingredient('Rice', 'g', 1000, 100, self.employee)
        self.recipe = self.inv.add_recipe('Rice Ball', 10.00)
        self.inv.set_recipe_ingredient(self.recipe, self.ingredient, 10)

    def order(self, servings: int = 2, complete: bool = True) -> int:
        order_id = self.inv.create_customer_order({self.recipe: servings}, self.employee)
        if complete:
            self.inv.complete_customer_order(order_id, self.employee)
        return order_id

    def test_additive_database_schema_and_original_inventory_unchanged(self):
        original = self.inv.inventory()
        initialize(self.path)
        initialize(self.path)
        self.assertEqual(self.inv.inventory(), original)
        with connect(self.path) as db:
            names = {r['name'] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({'Profile', 'Customer', 'Order', 'InventoryItem', 'LoyaltyAccount',
                             'LoyaltyTransaction', 'Reward', 'Redemption'} <= names)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Reward').fetchone()[0], 0)

    def test_staff_registers_new_walkin_with_one_shared_customer_and_profile(self):
        acc = self.loyalty.register_customer(self.employee, 'Loyal Member',
                   email='loyal@example.com', phone_number='514-555-0199')
        self.assertGreater(acc['loyaltyAccountID'], 0)
        self.assertEqual(acc['pointsBalance'], 0)
        self.assertEqual(acc['email'], 'loyal@example.com')
        self.assertEqual(self.loyalty.retrieve_customer_account(acc['customerID']),
                         {k: v for k, v in acc.items() if k != 'initialPassword'})
        self.assertEqual(self.inv.login(acc['username'], acc['initialPassword'])['userID'], acc['userID'])
        self.assertEqual(ProfileService(self.path).view_profile(acc['userID']).name, 'Loyal Member')
        self.assertEqual(self.loyalty.find_customers(self.employee, 'loyal@example.com')[0]['customerID'],
                         acc['customerID'])
        self.assertEqual(self.loyalty.find_customers(self.employee, '514-555-0199')[0]['customerID'],
                         acc['customerID'])
        with self.assertRaises(LoyaltyError):
            self.loyalty.register_customer(self.employee, 'Double', email='LOYAL@example.com')

    def test_existing_customer_enrollment_is_idempotent_and_self_enrollment(self):
        enrolled = self.loyalty.enroll_existing_customer(self.existing_user, self.existing_user)
        self.assertEqual(enrolled['customerID'], self.existing_customer)
        self.assertEqual(self.loyalty.enroll_existing_customer(self.existing_user, self.employee), enrolled)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Profile WHERE userID=?',
                                        (self.existing_user,)).fetchone()[0], 1)

    def test_missing_accounts_and_invalid_registration_leave_no_user(self):
        with self.assertRaises(AccountNotFoundError):
            self.loyalty.retrieve_customer_account(self.existing_customer)
        with self.assertRaises(LoyaltyError):
            self.loyalty.register_customer(self.employee, 'No Contact')
        with self.assertRaises(LoyaltyError):
            self.loyalty.register_customer(self.employee, 'Bad email', email='wrong')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM "User"').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount').fetchone()[0], 0)

    def test_non_staff_cannot_register_walkin_or_record_purchase(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.existing_user)
        with self.assertRaises(LoyaltyError):
            self.loyalty.register_customer(self.existing_user, 'Unauthorized', email='bad@example.com')
        with self.assertRaises(LoyaltyError):
            self.loyalty.process_eligible_purchase(self.existing_user, self.existing_customer, self.order())
        with self.assertRaises(LoyaltyError):
            self.loyalty.find_customers(self.existing_user, 'existing@example.com')

    def test_earning_points_links_to_completed_order_without_deducting_inventory_twice(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.order()
        inventory_after_completion = self.inv.inventory()
        quote = self.loyalty.preview_purchase(self.existing_customer, order_id)
        self.assertEqual(quote.points_earned, 20)
        self.assertEqual(quote.new_balance, 20)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 0)
        result = self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id)
        self.assertEqual(result['pointsEarned'], 20)
        self.assertEqual(result['balanceAfter'], 20)
        self.assertEqual(self.inv.inventory(), inventory_after_completion)
        with connect(self.path) as db:
            order = db.execute('SELECT status,totalAmount,customerID FROM "Order" WHERE orderID=?',
                               (order_id,)).fetchone()
            self.assertEqual((order['status'], order['totalAmount'], order['customerID']),
                             ('Completed', 20.0, self.existing_customer))
        receipt = self.loyalty.generate_receipt(result['loyaltyTransactionID'])
        self.assertIn('New points balance: 20', receipt)
        self.assertIn('Payment is handled separately', receipt)

    def test_partial_and_ineligible_purchase_record_zero_or_partial_points(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        a = self.loyalty.process_eligible_purchase(self.employee, self.existing_customer,
                                                   self.order(), eligible_amount='5.00')
        self.assertEqual(a['pointsEarned'], 5)
        b = self.loyalty.process_eligible_purchase(self.employee, self.existing_customer,
                                                   self.order(), eligible_amount='0')
        self.assertEqual(b['pointsEarned'], 0)
        self.assertEqual(b['balanceAfter'], 5)
        with self.assertRaises(LoyaltyError):
            self.loyalty.preview_purchase(self.existing_customer, self.order(), eligible_amount='20.001')
        with self.assertRaises(LoyaltyError):
            self.loyalty.preview_purchase(self.existing_customer, self.order(), eligible_amount=100)

    def test_reward_redemption_transaction_and_history(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        reward_id = self.loyalty.create_reward(self.owner, 'Five Dollars Off', 10, '5.00')
        self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, self.order())
        checkout = self.loyalty.preview_purchase(self.existing_customer, self.order(), reward_id=reward_id)
        self.assertEqual((checkout.previous_balance, checkout.points_redeemed,
                          checkout.points_earned, checkout.new_balance), (20, 10, 15, 25))
        result = self.loyalty.redeem_reward(self.employee, self.existing_customer,
                                            checkout.order_id, reward_id)
        self.assertEqual(result['discountAmount'], 5.0)
        self.assertEqual(result['finalAmount'], 15.0)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 25)
        details = self.loyalty.view_loyalty_details(self.existing_customer)
        self.assertEqual(len(details['transactions']), 2)
        self.assertEqual(details['transactions'][0]['rewardName'], 'Five Dollars Off')
        self.assertTrue(details['rewards'][0]['affordable'])
        with connect(self.path) as db:
            row = db.execute('SELECT pointsUsed,discountAmount FROM Redemption').fetchone()
            self.assertEqual((row['pointsUsed'], row['discountAmount']), (10, 5.0))

    def test_insufficient_points_and_discount_exceeding_price_are_safe(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        reward_id = self.loyalty.create_reward(self.owner, 'Huge Discount', 100, '5.00')
        order_id = self.order()
        with self.assertRaises(InsufficientPointsError):
            self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id,
                                                   reward_id=reward_id)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 0)
        self.loyalty.create_reward(self.owner, 'Too Much', 1, '100.00')
        self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id)
        next_id = self.order()
        with self.assertRaises(LoyaltyError):
            self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, next_id,
                                                   reward_id=2)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 20)

    def test_duplicate_pending_and_other_customer_order_are_rejected(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        pending = self.order(complete=False)
        self.assertEqual(self.loyalty.preview_purchase(self.existing_customer, pending).points_earned, 20)
        with self.assertRaises(LoyaltyError):
            self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, pending)
        order_id = self.order()
        self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id)
        with self.assertRaises(DuplicatePurchaseError):
            self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id)
        other = self.loyalty.register_customer(self.employee, 'New Customer', email='new@example.com')
        with self.assertRaises(LoyaltyError):
            self.loyalty.process_eligible_purchase(self.employee, other['customerID'], order_id)

    def test_failure_to_save_loyalty_transaction_rolls_back_points_and_order_link(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.order()
        with connect(self.path) as db:
            db.execute('''CREATE TRIGGER stop_loyalty BEFORE INSERT ON LoyaltyTransaction
                          BEGIN SELECT RAISE(ABORT, 'simulated outage'); END''')
            db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.loyalty.process_eligible_purchase(self.employee, self.existing_customer, order_id)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 0)
        with connect(self.path) as db:
            self.assertIsNone(db.execute('SELECT customerID FROM "Order" WHERE orderID=?',
                                          (order_id,)).fetchone()['customerID'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 0)

    def test_permission_and_loyalty_history_protection_on_role_change_and_delete(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        management = UserManagementService(self.path)
        with self.assertRaises(InventoryError):
            management.change_role(self.owner, self.existing_user, 'Employee')
        with self.assertRaises(InventoryError):
            management.delete_account(self.owner, self.existing_user)
        with self.assertRaises(LoyaltyError):
            self.loyalty.create_reward(self.employee, 'Not Authorized', 10, '1.00')
        reward_id = self.loyalty.create_reward(self.owner, 'Valid', 10, '1.00')
        self.loyalty.set_reward_active(self.owner, reward_id, False)
        self.assertEqual(len(self.loyalty.rewards()), 0)
        self.assertEqual(len(self.loyalty.rewards(active_only=False)), 1)

    def test_customer_cli_can_enroll_and_view_without_inventory_access(self):
        customer = {'userID': self.existing_user, 'role': 'Customer', 'name': 'Existing Customer'}
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=['y']):
            loyalty_customer_menu(self.loyalty, customer)
        self.assertIn('Current balance: 0 points', out.getvalue())
        with redirect_stdout(io.StringIO()) as out:
            loyalty_customer_menu(self.loyalty, customer)
        self.assertIn('Transaction history', out.getvalue())

    def test_staff_cli_register_walkin_then_reopen(self):
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=[
                '1', 'Visitor', 'visitor@example.com', '', '', '', 'y', '', '0']), \
                patch('inventory_cli.getpass', return_value=''):
            loyalty_staff_menu(self.loyalty, {'userID': self.employee, 'role': 'Employee'})
        self.assertIn('Registered. Customer ID:', out.getvalue())
        self.assertIn('Temporary password (shown only now):', out.getvalue())

    def test_staff_enrollment_blank_returns_to_menu(self):
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input',
                side_effect=['2', '', '', '0']):
            loyalty_staff_menu(self.loyalty, {'userID': self.employee, 'role': 'Employee'})
        self.assertIn('Returning to the Loyalty Program menu', out.getvalue())

    def test_custom_password_walkin_and_customer_listing(self):
        acc = self.loyalty.register_customer(self.employee, 'Visitor', email='visitor@test.com',
                                             username='visitor-signin', password='custom-pass123')
        self.assertEqual(self.inv.login('visitor-signin', 'custom-pass123')['userID'], acc['userID'])
        self.assertEqual(acc['initialPassword'], 'custom-pass123')
        self.assertEqual(self.loyalty.list_customers(self.employee)[-1]['customerID'], acc['customerID'])
        admin = UserManagementService(self.path)
        accounts = {a['userID']: a for a in admin.list_accounts(self.owner)}
        self.assertEqual(accounts[self.owner]['customerID'], '—')
        self.assertEqual(accounts[self.existing_user]['customerID'], '—')
        self.assertEqual(accounts[acc['userID']]['customerID'], str(acc['customerID']))

    def test_pending_order_completion_posts_points_once(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.inv.create_customer_order({self.recipe: 2}, self.employee,
                                                   self.existing_customer)
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=[
                str(order_id), 'c', 'n', 'y']):
            orders_menu(self.inv, {'userID': self.employee, 'role': 'Employee'})
        self.assertIn('loyalty points earned', out.getvalue())
        self.assertEqual(self.inv.order_details(order_id)['status'], 'Completed')
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 200)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction WHERE orderID=?',
                                        (order_id,)).fetchone()[0], 1)
        with self.assertRaises(LoyaltyError):
            self.loyalty.complete_order_with_loyalty(self.employee, self.existing_customer, order_id)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 200)

    def test_completion_offers_and_applies_reward(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        self.loyalty.ensure_sample_rewards()
        with connect(self.path) as db:
            db.execute('UPDATE LoyaltyAccount SET pointsBalance=1000 WHERE customerID=?',
                       (self.existing_customer,))
            db.commit()
        order_id = self.inv.create_customer_order({self.recipe: 2}, self.employee,
                                                   self.existing_customer)
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=['n', '1', 'y']):
            complete_order_flow(self.inv, {'userID': self.employee, 'role': 'Employee'}, order_id)
        self.assertIn('reward: -$5.00', out.getvalue())
        with connect(self.path) as db:
            tx = db.execute('SELECT discountAmount,pointsRedeemed,pointsEarned FROM LoyaltyTransaction '
                            'WHERE orderID=?', (order_id,)).fetchone()
            self.assertEqual((tx['discountAmount'], tx['pointsRedeemed'], tx['pointsEarned']), (5, 1000, 150))
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 150)

    def test_failed_order_completion_rolls_back_stock_and_points(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.inv.create_customer_order({self.recipe: 101}, self.employee,
                                                   self.existing_customer)
        with self.assertRaises(InventoryError):
            self.loyalty.complete_order_with_loyalty(self.employee, self.existing_customer, order_id)
        self.assertEqual(self.inv.order_details(order_id)['status'], 'Pending')
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 0)
        self.assertEqual(self.inv.inventory()[0]['quantityOnHand'], 1000)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 0)

    def test_completion_prompts_to_enroll_unenrolled_customer(self):
        order_id = self.inv.create_customer_order({self.recipe: 1}, self.employee,
                                                   self.existing_customer)
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=['n', 'y', 'y']):
            complete_order_flow(self.inv, {'userID': self.employee, 'role': 'Employee'}, order_id)
        self.assertIn('has not enrolled in loyalty yet', out.getvalue())
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 100)

    def test_order_creation_prompts_for_customer_id_and_preserves_pending_link(self):
        with redirect_stdout(io.StringIO()), patch('builtins.input', side_effect=[
                str(self.recipe), '2', '', str(self.existing_customer), 'y', 'n']):
            order_create(self.inv, {'userID': self.employee, 'role': 'Employee'})
        orders = self.inv.customer_orders()
        self.assertEqual(orders[0]['customerID'], self.existing_customer)
        self.assertEqual(orders[0]['status'], 'Pending')

    def test_unlinked_pending_order_can_link_customer_and_earn_points(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.inv.create_customer_order({self.recipe: 1}, self.employee)
        with redirect_stdout(io.StringIO()), patch('builtins.input', side_effect=[
                str(order_id), 'c', str(self.existing_customer), 'y']):
            orders_menu(self.inv, {'userID': self.employee, 'role': 'Employee'})
        self.assertEqual(self.inv.order_details(order_id)['customerID'], self.existing_customer)
        self.assertEqual(self.loyalty.retrieve_customer_account(self.existing_customer)['pointsBalance'], 100)

    def test_disabled_customer_is_explained_and_can_complete_without_points(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        UserManagementService(self.path).set_active(self.owner, self.existing_user, False)
        order_id = self.inv.create_customer_order({self.recipe: 1}, self.employee)
        # Existing disabled customers cannot be assigned to new orders.
        with self.assertRaisesRegex(InventoryError, 'disabled'):
            self.inv.set_order_customer(order_id, self.existing_customer)
        with connect(self.path) as db:
            db.execute('UPDATE "Order" SET customerID=? WHERE orderID=?', (self.existing_customer, order_id))
            db.commit()  # Previously linked customer later became disabled.
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=['n', 'y']):
            complete_order_flow(self.inv, {'userID': self.employee, 'role': 'Employee'}, order_id)
        self.assertIn('An Owner can enable it', out.getvalue())
        self.assertIn('No loyalty transaction recorded', out.getvalue())
        self.assertEqual(self.inv.order_details(order_id)['status'], 'Completed')

    def test_suspended_loyalty_requires_reactivation_to_earn(self):
        self.loyalty.enroll_existing_customer(self.existing_user, self.employee)
        order_id = self.inv.create_customer_order({self.recipe: 1}, self.employee,
                                                   self.existing_customer)
        self.loyalty.set_loyalty_account_status(self.owner, self.existing_customer, 'Suspended')
        with redirect_stdout(io.StringIO()) as out, patch('builtins.input', side_effect=['n', 'y']):
            complete_order_flow(self.inv, {'userID': self.employee, 'role': 'Employee'}, order_id)
        self.assertIn('Loyalty is suspended', out.getvalue())
        self.assertEqual(self.inv.order_details(order_id)['status'], 'Completed')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
