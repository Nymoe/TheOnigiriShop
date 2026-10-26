"""Regression tests for option 21 -> 7; all tests use disposable databases."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory_db import connect
from inventory_service import InventoryError, InventoryService
from sample_users import DEMO_USERS, DEMO_PASSWORDS, load_sample_users


class SampleUserImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'btm495.db'
        self.svc = InventoryService(self.db)
        self.owner = self.svc.create_user('My Real Owner', 'real-owner', 'owner-strong-password', 'Owner')
        self.staff = self.svc.create_user('Actual Employee', 'actual-staff', 'staff-password', 'Employee')

    def test_not_imported_automatically_on_database_creation_or_restart(self):
        # Creating a database or restarting the app does NOT seed sample users.
        self.assertEqual(len(self.svc.list_users()), 2)
        InventoryService(self.db)
        self.assertEqual(len(self.svc.list_users()), 2)
        with self.assertRaises(InventoryError):
            self.svc.login('akira.owner', DEMO_PASSWORDS['Owner'])

    def test_all_eight_original_accounts_with_profiles_roles_and_logins(self):
        ingredient_id = self.svc.add_ingredient('My existing rice', 'g', 10, 1, self.owner)
        self.assertEqual(load_sample_users(self.svc, self.owner), {'created': 8, 'already_present': 0})
        with connect(self.db) as db:
            records = db.execute('''
                SELECT u.*,p.profileID,p.name AS profileName,p.phoneNumber,p.dateOfBirth
                FROM "User" u JOIN Profile p ON u.userID=p.userID
                WHERE u.username IN ({})
            '''.format(','.join('?' for _ in DEMO_USERS)),
                tuple(u[0] for u in DEMO_USERS)).fetchall()
            self.assertEqual(len(records), 8)
            for username, name, role, email, phone, dob in DEMO_USERS:
                row = next(r for r in records if r['username'] == username)
                self.assertEqual((row['name'], row['profileName'], row['role'], row['email'],
                                  row['phoneNumber'], row['dateOfBirth']),
                                 (name, name, role, email, phone, dob))
                self.assertTrue(row['profileID'])
                self.assertEqual(row['accountActive'], 1)
                self.assertNotEqual(row['passwordHash'], DEMO_PASSWORDS[role])
                subtype = db.execute(f'SELECT 1 FROM "{role}" WHERE userID=?', (row['userID'],)).fetchone()
                self.assertIsNotNone(subtype)
                self.assertEqual(self.svc.login(username, DEMO_PASSWORDS[role])['userID'], row['userID'])
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM "User"').fetchone()[0], 10)
        self.assertEqual(self.svc.inventory()[0]['ingredientID'], ingredient_id)
        self.assertEqual(self.svc.login('real-owner', 'owner-strong-password')['role'], 'Owner')

    def test_repeat_is_idempotent_and_does_not_reset_passwords_or_statuses(self):
        load_sample_users(self.svc, self.owner)
        from user_management_service import UserManagementService
        manager = UserManagementService(self.db)
        with connect(self.db) as db:
            emma = db.execute('SELECT userID FROM "User" WHERE username="emma.staff"').fetchone()[0]
        manager.reset_password(self.owner, emma, 'changed-sample-password')
        manager.set_active(self.owner, emma, False)
        with connect(self.db) as db:
            before = db.execute('SELECT passwordHash,passwordSalt,accountActive FROM "User" WHERE userID=?',
                                (emma,)).fetchone()
            profile_count = db.execute('SELECT COUNT(*) FROM Profile').fetchone()[0]
        self.assertEqual(load_sample_users(self.svc, self.owner), {'created': 0, 'already_present': 8})
        with connect(self.db) as db:
            after = db.execute('SELECT passwordHash,passwordSalt,accountActive FROM "User" WHERE userID=?',
                               (emma,)).fetchone()
            self.assertEqual(tuple(after), tuple(before))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Profile').fetchone()[0], profile_count)
        with self.assertRaises(InventoryError):
            self.svc.login('emma.staff', 'changed-sample-password')

    def test_conflicting_username_aborts_everything(self):
        self.svc.create_user('Someone Else', 'maya.customer', 'regular-password', 'Customer')
        original = len(self.svc.list_users())
        with self.assertRaisesRegex(InventoryError, 'username'):
            load_sample_users(self.svc, self.owner)
        self.assertEqual(len(self.svc.list_users()), original)
        self.assertFalse(any(row['username'] == 'akira.owner' for row in self.svc.list_users()))

    def test_non_owner_and_disabled_owner_cannot_import(self):
        with self.assertRaisesRegex(InventoryError, 'active Owner'):
            load_sample_users(self.svc, self.staff)
        from user_management_service import UserManagementService
        owner2 = self.svc.create_user('Second Owner', 'second-owner', 'second-owner-password', 'Owner')
        UserManagementService(self.db).set_active(self.owner, owner2, False)
        with self.assertRaisesRegex(InventoryError, 'active Owner'):
            load_sample_users(self.svc, owner2)
        self.assertEqual(len(self.svc.list_users()), 3)

    def test_database_failure_rolls_back_all_eight_users(self):
        with connect(self.db) as db:
            db.execute('''CREATE TRIGGER block_noah BEFORE INSERT ON "User"
                          WHEN NEW.username='noah.customer'
                          BEGIN SELECT RAISE(ABORT, 'injected DB error'); END''')
            db.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            load_sample_users(self.svc, self.owner)
        self.assertEqual(len(self.svc.list_users()), 2)
        with connect(self.db) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Profile').fetchone()[0], 2)

    def test_option_16_then_7_imports_only_after_confirmation(self):
        from inventory_cli import demo_menu, menu
        user = self.svc.login('real-owner', 'owner-strong-password')
        with patch('inventory_cli.prompt', side_effect=['7', '0']), \
             patch('inventory_cli.confirm', return_value=False), \
             patch('builtins.input', return_value=''):
            self.assertFalse(demo_menu(self.svc, user))
        self.assertEqual(len(self.svc.list_users()), 2)
        # Now follow the full authenticated main-menu route.
        with patch('inventory_cli.prompt', side_effect=['21', '7', '0', '23']), \
             patch('inventory_cli.confirm', return_value=True), \
             patch('inventory_cli.getpass', return_value='owner-strong-password'), \
             patch('builtins.input', return_value=''):
            self.assertIsNone(menu(self.svc, user))
        self.assertEqual(len(self.svc.list_users()), 10)
        self.assertEqual(self.svc.login('maya.customer', DEMO_PASSWORDS['Customer'])['role'], 'Customer')


if __name__ == '__main__':
    unittest.main(verbosity=2)
