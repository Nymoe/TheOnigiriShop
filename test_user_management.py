"""Account-management regressions: owner security, role/profile integrity, safe deletion."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from inventory_db import connect
from inventory_service import InventoryService, InventoryError
from profile_service import ProfileService, ProfileError
from user_management_service import UserManagementService
from demo_tools import reset_database


class ManageUsersTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'onigiri.db'
        self.inventory = InventoryService(self.path)
        self.owner = self.inventory.create_user('Owner One', 'owner', 'owner-password', 'Owner')
        self.employee = self.inventory.create_user('Employee One', 'employee', 'employee-password', 'Employee')
        self.customer = self.inventory.create_user('Customer One', 'customer', 'customer-password', 'Customer')
        self.manager = UserManagementService(self.path)
        self.profiles = ProfileService(self.path)

    def test_owner_lists_and_views_all_users(self):
        users = self.manager.list_accounts(self.owner)
        self.assertEqual({u['role'] for u in users}, {'Owner', 'Employee', 'Customer'})
        self.assertEqual({u['status'] for u in users}, {'Active'})
        self.assertEqual(self.manager.get_account(self.owner, self.employee)['username'], 'employee')

    def test_employees_and_customers_cannot_manage_users_in_service(self):
        for unauthorized in (self.employee, self.customer, 9999):
            for invoke in (
                lambda: self.manager.list_accounts(unauthorized),
                lambda: self.manager.get_account(unauthorized, self.owner),
                lambda: self.manager.create_account(unauthorized, 'Attacker', 'attacker', 'password123'),
                lambda: self.manager.edit_account(unauthorized, self.owner, {'name': 'Pwn'}),
                lambda: self.manager.change_role(unauthorized, unauthorized, 'Owner'),
                lambda: self.manager.reset_password(unauthorized, self.owner, 'new-password'),
                lambda: self.manager.set_active(unauthorized, self.owner, False),
                lambda: self.manager.delete_account(unauthorized, self.owner),
            ):
                with self.subTest(unauthorized=unauthorized), self.assertRaises(InventoryError):
                    invoke()
        self.assertEqual(self.inventory.login('owner', 'owner-password')['role'], 'Owner')
        self.assertEqual(len(self.manager.list_accounts(self.owner)), 3)

    def test_create_user_is_integrated_with_shared_tables(self):
        created = self.manager.create_account(self.owner, '  Jane Test  ', 'jane', 'password123',
                                              'Customer', email=' jane@example.com ',
                                              phone_number=' 514-555-0123 ',
                                              date_of_birth='2001-04-15')
        self.assertEqual(self.profiles.view_profile(created).name, 'Jane Test')
        self.assertEqual(self.profiles.view_profile(created).phone_number, '514-555-0123')
        self.assertEqual(self.profiles.view_profile(created).date_of_birth.isoformat(), '2001-04-15')
        self.assertEqual(self.manager.get_account(self.owner, created)['email'], 'jane@example.com')
        self.assertEqual(self.inventory.login('jane', 'password123')['role'], 'Customer')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT userID FROM Customer WHERE userID=?', (created,)).fetchone()[0], created)
        with self.assertRaises(InventoryError):
            self.manager.create_account(self.owner, 'Duplicate', 'JANE', 'password123')

    def test_new_user_contact_details_are_optional_and_invalid_values_are_rejected(self):
        created = self.manager.create_account(self.owner, 'No Email', 'no-email', 'password123')
        self.assertIsNone(self.manager.get_account(self.owner, created)['email'])
        self.assertIsNone(self.profiles.view_profile(created).phone_number)
        self.assertIsNone(self.profiles.view_profile(created).date_of_birth)
        for invalid_email in ('not-an-email', 'person@invalid', 'with space@example.com'):
            with self.subTest(email=invalid_email), self.assertRaisesRegex(InventoryError, 'valid email'):
                self.manager.create_account(self.owner, 'Invalid Email', 'bad-email',
                                            'password123', email=invalid_email)
        for invalid_phone in ('123', 'abc-def-ghij'):
            with self.subTest(phone=invalid_phone), self.assertRaisesRegex(ProfileError, 'Phone number'):
                self.manager.create_account(self.owner, 'Invalid Phone', 'bad-phone',
                                            'password123', phone_number=invalid_phone)
        for invalid_date in ('2001-02-30', '01/15/2001', '2999-01-01'):
            with self.subTest(date=invalid_date), self.assertRaisesRegex(ProfileError, 'Date of birth'):
                self.manager.create_account(self.owner, 'Invalid Date', 'bad-date',
                                            'password123', date_of_birth=invalid_date)
        self.assertEqual(len(self.manager.list_accounts(self.owner)), 4)

    def test_edit_existing_user_and_profile_remain_synced(self):
        profile_before = self.profiles.view_profile(self.employee)
        account = self.manager.edit_account(self.owner, self.employee, {
            'name': 'Edited Employee', 'username': 'new-employee',
            'phoneNumber': '514-555-0123', 'dateOfBirth': '2000-02-29',
            'email': 'employee@example.com'
        })
        self.assertEqual(account['name'], 'Edited Employee')
        self.assertEqual(account['username'], 'new-employee')
        self.assertEqual(account['email'], 'employee@example.com')
        p = self.profiles.view_profile(self.employee)
        self.assertEqual(p.name, 'Edited Employee')
        self.assertEqual(p.phone_number, '514-555-0123')
        self.assertEqual(p.date_of_birth.isoformat(), '2000-02-29')
        self.assertEqual(p.profile_id, profile_before.profile_id)
        self.assertEqual(p.version, 1)
        self.assertEqual(self.inventory.login('new-employee', 'employee-password')['name'], 'Edited Employee')
        with self.assertRaises(InventoryError):
            self.inventory.login('employee', 'employee-password')

    def test_invalid_update_and_username_conflict_roll_back_all_fields(self):
        original = self.profiles.view_profile(self.employee)
        for changes in ({'name': 'Oops', 'phoneNumber': 'INVALID'},
                        {'name': 'Oops', 'username': 'CUSTOMER'},
                        {'dateOfBirth': '2100-01-01'},
                        {'username': 'bad spaces'},
                        {'role': 'Owner'},
                        {'email': 'bad-email'}):
            with self.subTest(changes=changes), self.assertRaises((ProfileError, InventoryError)):
                self.manager.edit_account(self.owner, self.employee, changes)
            self.assertEqual(self.profiles.view_profile(self.employee), original)

    def test_change_role_updates_subtype_but_keeps_same_profile(self):
        p = self.profiles.view_profile(self.employee)
        self.manager.change_role(self.owner, self.employee, 'Customer')
        self.assertEqual(self.inventory.login('employee', 'employee-password')['role'], 'Customer')
        self.assertEqual(self.profiles.view_profile(self.employee).profile_id, p.profile_id)
        with connect(self.path) as db:
            self.assertFalse(db.execute('SELECT 1 FROM Employee WHERE userID=?', (self.employee,)).fetchone())
            self.assertTrue(db.execute('SELECT 1 FROM Customer WHERE userID=?', (self.employee,)).fetchone())
        self.manager.change_role(self.owner, self.employee, 'Owner')
        self.assertEqual(self.inventory.login('employee', 'employee-password')['role'], 'Owner')

    def test_cannot_demote_disable_or_delete_self(self):
        for fn in (
            lambda: self.manager.change_role(self.owner, self.owner, 'Employee'),
            lambda: self.manager.set_active(self.owner, self.owner, False),
            lambda: self.manager.delete_account(self.owner, self.owner),
        ):
            with self.assertRaises(InventoryError):
                fn()
        self.assertEqual(self.inventory.login('owner', 'owner-password')['role'], 'Owner')

    def test_other_owner_can_be_disabled_enabled_or_demoted(self):
        new_owner = self.manager.create_account(self.owner, 'Other Owner', 'other', 'other-password', 'Owner')
        self.manager.set_active(self.owner, new_owner, False)
        with self.assertRaises(InventoryError):
            self.inventory.login('other', 'other-password')
        self.assertEqual(self.manager.get_account(self.owner, new_owner)['accountActive'], 0)
        self.manager.set_active(self.owner, new_owner, True)
        self.assertEqual(self.inventory.login('other', 'other-password')['role'], 'Owner')
        self.manager.change_role(self.owner, new_owner, 'Employee')
        self.assertEqual(self.inventory.login('other', 'other-password')['role'], 'Employee')
        with self.assertRaises(InventoryError):
            self.manager.list_accounts(new_owner)

    def test_reset_password_does_not_change_username_role_or_profile(self):
        before = self.profiles.view_profile(self.employee)
        self.manager.reset_password(self.owner, self.employee, 'replacement-password')
        with self.assertRaises(InventoryError):
            self.inventory.login('employee', 'employee-password')
        self.assertEqual(self.inventory.login('employee', 'replacement-password')['role'], 'Employee')
        self.assertEqual(self.profiles.view_profile(self.employee), before)
        with self.assertRaises(InventoryError):
            self.manager.reset_password(self.owner, self.employee, 'short')
        self.assertEqual(self.inventory.login('employee', 'replacement-password')['role'], 'Employee')

    def test_disable_blocks_login_without_deleting_business_history(self):
        id_ = self.inventory.add_ingredient('Rice', 'g', 500, 100, self.employee)
        self.manager.set_active(self.owner, self.employee, False)
        with self.assertRaisesRegex(InventoryError, 'account has been disabled'):
            self.inventory.login('employee', 'employee-password')
        with self.assertRaisesRegex(InventoryError, 'Invalid username or password'):
            self.inventory.login('employee', 'wrong-password')
        with self.assertRaisesRegex(InventoryError, 'Invalid username or password'):
            self.inventory.login('missing-user', 'employee-password')
        self.assertEqual(self.profiles.view_profile(self.employee).name, 'Employee One')
        with connect(self.path) as db:
            self.assertTrue(db.execute('SELECT 1 FROM InventoryTransaction WHERE userID=?', (self.employee,)).fetchone())
        with self.assertRaises(InventoryError):
            self.manager.delete_account(self.owner, self.employee)
        self.manager.set_active(self.owner, self.employee, True)
        self.assertEqual(self.inventory.login('employee', 'employee-password')['role'], 'Employee')

    def test_delete_unreferenced_user_only(self):
        self.manager.delete_account(self.owner, self.customer)
        with self.assertRaises(InventoryError):
            self.inventory.login('customer', 'customer-password')
        with self.assertRaises(InventoryError):
            self.manager.get_account(self.owner, self.customer)
        with connect(self.path) as db:
            self.assertFalse(db.execute('SELECT 1 FROM Profile WHERE userID=?', (self.customer,)).fetchone())
            self.assertFalse(db.execute('SELECT 1 FROM Customer WHERE userID=?', (self.customer,)).fetchone())
        self.assertEqual(len(self.manager.list_accounts(self.owner)), 2)

    def test_delete_is_blocked_by_order_createdby_even_without_fk(self):
        with connect(self.path) as db:
            db.execute('INSERT INTO "Order"(orderDate,createdByUserID) VALUES(?,?)', ('2026-10-21', self.employee))
            db.commit()
        with self.assertRaises(InventoryError):
            self.manager.delete_account(self.owner, self.employee)
        self.assertEqual(self.inventory.login('employee', 'employee-password')['role'], 'Employee')

    def test_disable_flag_survives_account_preserving_reset(self):
        self.manager.set_active(self.owner, self.customer, False)
        reset_database(self.inventory, self.owner, with_demo=False, preserve_accounts=True)
        self.assertEqual(self.manager.get_account(self.owner, self.customer)['accountActive'], 0)
        with self.assertRaises(InventoryError):
            self.inventory.login('customer', 'customer-password')

    def test_cli_owner_menu_edit_existing_user(self):
        from inventory_cli import employees_menu
        user = self.inventory.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=['3', str(self.employee), '0']), \
             patch('builtins.input', side_effect=['Changed in CLI', '', '', '', '']), \
             patch('inventory_cli.confirm', return_value=True):
            employees_menu(self.inventory, user)
        self.assertEqual(self.profiles.view_profile(self.employee).name, 'Changed in CLI')

    def test_cli_owner_can_add_all_profile_details_while_creating_user(self):
        from inventory_cli import employees_menu
        user = self.inventory.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=[
            '2', 'e', 'Email Employee', 'email-employee', 'staff@example.com',
            '514-555-0188', '2000-01-20', '0'
        ]), patch('inventory_cli.getpass', side_effect=['password123', 'password123']):
            employees_menu(self.inventory, user)
        created = next(a for a in self.manager.list_accounts(self.owner)
                       if a['username'] == 'email-employee')
        self.assertEqual(self.manager.get_account(self.owner, created['userID'])['email'],
                         'staff@example.com')
        self.assertEqual(self.profiles.view_profile(created['userID']).phone_number,
                         '514-555-0188')
        self.assertEqual(self.profiles.view_profile(created['userID']).date_of_birth.isoformat(),
                         '2000-01-20')

    def test_cli_owner_menu_unauthorized_direct_call(self):
        from inventory_cli import employees_menu
        user = self.inventory.login('employee', 'employee-password')
        with self.assertRaises(InventoryError):
            employees_menu(self.inventory, user)


if __name__ == '__main__':
    unittest.main(verbosity=2)
