"""Profile acceptance tests, including validation and error handling."""
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory_db import connect
from inventory_service import InventoryService
from profile_service import ProfileConflictError, ProfileError, ProfileNotFoundError, ProfileService
from demo_tools import reset_database, restore_database


class ProfileUseCaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'shop.db'
        self.inventory = InventoryService(self.path)
        self.owner_id = self.inventory.create_user('Shop Owner', 'owner', 'password-owner', 'Owner')
        self.employee_id = self.inventory.create_user('Shop Employee', 'employee', 'password-staff', 'Employee')
        self.customer_id = self.inventory.create_user('A Customer', 'customer', 'password-customer', 'Customer')
        self.profiles = ProfileService(self.path)

    def test_profiles_exist_for_all_roles_and_are_one_to_one(self):
        for identity, username, role in ((self.owner_id, 'owner', 'Owner'),
                                         (self.employee_id, 'employee', 'Employee'),
                                         (self.customer_id, 'customer', 'Customer')):
            self.assertEqual(self.inventory.login(username, 'password-' +
                             {'owner':'owner','employee':'staff','customer':'customer'}[username])['userID'], identity)
            p = self.profiles.view_profile(identity)
            self.assertEqual(p.role, role)
            self.assertTrue(p.profile_id)
            self.assertEqual(p.user_id, identity)
            self.assertEqual(p.version, 0)
            self.assertIsNone(p.phone_number)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Profile').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT userID FROM Customer').fetchone()[0], self.customer_id)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('INSERT INTO Profile (profileID,userID,name) VALUES (?,?,?)',
                           ('another', self.customer_id, 'Duplicate'))

    def test_view_only_never_changes_data(self):
        before = self.profiles.view_profile(self.employee_id)
        self.assertEqual(before, self.profiles.view_profile(self.employee_id))
        self.assertEqual(before.version, 0)

    def test_profile_edit_is_persistent_and_syncs_shared_user_name(self):
        before = self.profiles.view_profile(self.owner_id)
        after = self.profiles.update_profile(self.owner_id, {
            'name': '  Updated Owner  ', 'phoneNumber': '+1 (514) 555-0134',
            'dateOfBirth': '2000-08-15'
        }, expected_version=before.version)
        self.assertEqual(after.name, 'Updated Owner')
        self.assertEqual(after.phone_number, '+1 (514) 555-0134')
        self.assertEqual(after.date_of_birth, date(2000, 8, 15))
        self.assertEqual(after.version, before.version + 1)
        self.assertEqual(after.profile_id, before.profile_id)
        self.assertEqual(self.inventory.login('owner', 'password-owner')['name'], 'Updated Owner')
        self.assertEqual(ProfileService(self.path).view_profile(self.owner_id), after)
        self.assertEqual(self.profiles.view_profile(self.employee_id).name, 'Shop Employee')
        self.assertEqual(self.profiles.view_profile(self.customer_id).name, 'A Customer')

    def test_optional_fields_may_be_cleared_but_identity_fields_are_read_only(self):
        self.profiles.update_profile(self.customer_id, {'phoneNumber': '514-555-0112',
                                                          'dateOfBirth': '1998-02-04'})
        p = self.profiles.update_profile(self.customer_id, {'phoneNumber': '', 'dateOfBirth': ''})
        self.assertIsNone(p.phone_number)
        self.assertIsNone(p.date_of_birth)
        for key in ('username', 'role', 'userID', 'profileID', 'passwordHash'):
            with self.subTest(key=key), self.assertRaises(ProfileError):
                self.profiles.update_profile(self.customer_id, {key: 'illegal'})
        self.assertEqual(self.profiles.view_profile(self.customer_id).username, 'customer')

    def test_invalid_entries_reject_all_changes_without_changing_existing_data(self):
        before = self.profiles.view_profile(self.employee_id)
        bad = (
            {'name': ''}, {'name': 'a' * 121}, {'phoneNumber': 'abc'},
            {'phoneNumber': '123'}, {'dateOfBirth': 'not-a-date'},
            {'dateOfBirth': '2001-02-29'},
            {'dateOfBirth': (date.today() + timedelta(days=1)).isoformat()},
            {'name': 'New Name', 'phoneNumber': 'broken'}, {},
        )
        for change in bad:
            with self.subTest(change=change), self.assertRaises(ProfileError):
                self.profiles.update_profile(self.employee_id, change)
            self.assertEqual(self.profiles.view_profile(self.employee_id), before)

    def test_stale_profile_update_is_prevented(self):
        displayed = self.profiles.view_profile(self.owner_id)
        self.profiles.update_profile(self.owner_id, {'name': 'First Update'},
                                     expected_version=displayed.version)
        with self.assertRaises(ProfileConflictError):
            self.profiles.update_profile(self.owner_id, {'name': 'Stale Update'},
                                         expected_version=displayed.version)
        self.assertEqual(self.profiles.view_profile(self.owner_id).name, 'First Update')

    def test_missing_profile_error_is_explicit(self):
        with connect(self.path) as db:
            db.execute('DELETE FROM Profile WHERE userID=?', (self.employee_id,))
            db.commit()
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.view_profile(self.employee_id)
        with self.assertRaises(ProfileNotFoundError):
            self.profiles.update_profile(self.employee_id, {'name': 'Try Again'})
        with self.assertRaises(ProfileError):
            self.profiles.view_profile(-1)

    def test_database_failure_rolls_back_profile_and_user_together(self):
        before = self.profiles.view_profile(self.owner_id)
        with connect(self.path) as db:
            db.execute('''CREATE TRIGGER reject_name BEFORE UPDATE OF name ON "User"
                          BEGIN SELECT RAISE(ABORT, 'simulated User table failure'); END''')
            db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.profiles.update_profile(self.owner_id,
                                         {'name': 'Should Never Commit', 'phoneNumber': '514-555-0123'})
        self.assertEqual(self.profiles.view_profile(self.owner_id), before)
        self.assertEqual(self.inventory.login('owner', 'password-owner')['name'], 'Shop Owner')

    def test_legacy_users_get_profiles_without_overwriting_existing_data(self):
        with connect(self.path) as db:
            db.execute('INSERT INTO "User"(userID,name,username) VALUES(?,?,?)',
                       (888, 'Imported Customer', 'imported'))
            db.commit()
        ProfileService(self.path)  # additive migration on initialization
        a = self.profiles.view_profile(888)
        self.assertEqual(a.name, 'Imported Customer')
        ProfileService(self.path)
        self.assertEqual(self.profiles.view_profile(888).profile_id, a.profile_id)
        self.assertEqual(self.profiles.view_profile(self.owner_id).name, 'Shop Owner')

    def test_reset_preserves_login_linked_profiles_and_restore(self):
        original = self.profiles.update_profile(self.customer_id,
                                                 {'phoneNumber': '+1 514 555 0101', 'dateOfBirth': '2003-09-15'})
        self.profiles.update_profile(self.owner_id, {'name': 'Owner Renamed'})
        backup = reset_database(self.inventory, self.owner_id, with_demo=False)
        self.assertTrue(backup.exists())
        self.assertEqual(self.profiles.view_profile(self.customer_id), original)
        self.assertEqual(self.profiles.view_profile(self.owner_id).name, 'Owner Renamed')
        self.assertEqual(self.inventory.login('customer', 'password-customer')['role'], 'Customer')
        self.profiles.update_profile(self.customer_id, {'phoneNumber': '514-555-0199'})
        restore_database(self.inventory, self.owner_id, backup)
        self.assertEqual(self.profiles.view_profile(self.customer_id), original)

    def test_user_cancel_from_cli_discards_unsaved_changes(self):
        from inventory_cli import profile_menu
        user = self.inventory.login('employee', 'password-staff')
        before = self.profiles.view_profile(self.employee_id)
        with patch('inventory_cli.confirm', side_effect=[True, False]), \
             patch('builtins.input', side_effect=['Revised Name', '', '', '']):
            profile_menu(self.profiles, user)
        self.assertEqual(self.profiles.view_profile(self.employee_id), before)

    def test_cli_profile_edit_success(self):
        from inventory_cli import profile_menu
        user = self.inventory.login('employee', 'password-staff')
        with patch('inventory_cli.confirm', side_effect=[True, True]), \
             patch('builtins.input', side_effect=['Staff Revised', '', '5145550144', '1997-05-09']):
            profile_menu(self.profiles, user)
        self.assertEqual(self.profiles.view_profile(self.employee_id).name, 'Staff Revised')
        self.assertEqual(user['name'], 'Staff Revised')

    def test_customer_menu_rejects_inventory_admin_options(self):
        from inventory_cli import menu
        user = self.inventory.login('customer', 'password-customer')
        with patch('inventory_cli.prompt', side_effect=['8', '23']), \
             patch('inventory_cli.create_ingredient') as make_ingredient:
            menu(self.inventory, user)
        make_ingredient.assert_not_called()
        self.assertEqual(self.inventory.inventory(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
