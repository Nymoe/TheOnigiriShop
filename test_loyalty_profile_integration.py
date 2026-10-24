"""Integration regressions: optional sample users, editable profiles for every role, and loyalty."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory_db import connect
from inventory_service import InventoryService
from inventory_cli import menu, profile_menu
from loyalty_service import LoyaltyService
from profile_service import ProfileService, ProfileError
from sample_users import DEMO_PASSWORDS, DEMO_USERS, load_sample_users
from user_management_service import UserManagementService
from demo_tools import reset_database


class IntegratedUserProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / 'shop.db'
        self.svc = InventoryService(self.db_path)
        self.owner = self.svc.create_user('Real Owner', 'my-owner', 'my-owner-password', 'Owner')
        self.new_employee = self.svc.create_user('New Staff', 'new-staff', 'my-staff-password', 'Employee')
        self.new_customer = self.svc.create_user('New Customer', 'new-customer',
                                                 'my-customer-password', 'Customer')
        self.profiles = ProfileService(self.db_path)
        self.loyalty = LoyaltyService(self.db_path)

    def sample_id(self, username):
        with connect(self.db_path) as db:
            return db.execute('SELECT userID FROM "User" WHERE username=?',
                              (username,)).fetchone()['userID']

    def test_samples_only_appear_after_import_and_no_automatic_loyalty_enrolment(self):
        with connect(self.db_path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM DemoUserImport').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount').fetchone()[0], 0)
        self.assertEqual(load_sample_users(self.svc, self.owner)['created'], 8)
        with connect(self.db_path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM DemoUserImport').fetchone()[0], 8)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount').fetchone()[0], 0)
        for username, name, role, email, phone, dob in DEMO_USERS:
            logged_in = self.svc.login(username, DEMO_PASSWORDS[role])
            profile = self.profiles.view_profile(logged_in['userID'])
            self.assertEqual((profile.name, profile.email, profile.phone_number,
                              str(profile.date_of_birth)), (name, email, phone, dob))
        self.assertEqual(self.loyalty.enroll_existing_customer(self.sample_id('maya.customer'),
                                                              self.owner)['pointsBalance'], 0)

    def test_own_profile_all_editable_fields_for_new_and_sample_users_all_roles(self):
        load_sample_users(self.svc, self.owner)
        identities = [self.owner, self.new_employee, self.new_customer] + [
            self.sample_id('akira.owner'), self.sample_id('emma.staff'),
            self.sample_id('maya.customer')]
        for index, uid in enumerate(identities):
            with self.subTest(uid=uid):
                before = self.profiles.view_profile(uid)
                changed = self.profiles.update_profile(uid, {
                    'name': f'Edited Profile {index}',
                    'email': f'edited{index}@example.test',
                    'phoneNumber': '514-555-0199',
                    'dateOfBirth': '2000-08-15',
                }, expected_version=before.version)
                self.assertEqual(changed.name, f'Edited Profile {index}')
                self.assertEqual(changed.email, f'edited{index}@example.test')
                self.assertEqual(changed.phone_number, '514-555-0199')
                self.assertEqual(changed.date_of_birth.isoformat(), '2000-08-15')
                with connect(self.db_path) as db:
                    user = db.execute('SELECT name,email FROM "User" WHERE userID=?',
                                      (uid,)).fetchone()
                    self.assertEqual(user['name'], changed.name)
                    self.assertEqual(user['email'], changed.email)
                self.assertEqual(changed.username, before.username)
                self.assertEqual(changed.role, before.role)
                self.assertEqual(changed.profile_id, before.profile_id)
                self.assertEqual(self.profiles.view_profile(uid), changed)

    def test_blank_optional_fields_can_be_added_then_cleared(self):
        before = self.profiles.view_profile(self.new_customer)
        self.assertIsNone(before.email)
        self.assertIsNone(before.phone_number)
        self.assertIsNone(before.date_of_birth)
        updated = self.profiles.update_profile(self.new_customer, {
            'email': 'newly-added@example.test',
            'phoneNumber': '514-555-0200',
            'dateOfBirth': '1995-10-10'
        })
        self.assertEqual(updated.email, 'newly-added@example.test')
        updated = self.profiles.update_profile(self.new_customer, {
            'email': '', 'phoneNumber': '', 'dateOfBirth': ''
        })
        self.assertIsNone(updated.email)
        self.assertIsNone(updated.phone_number)
        self.assertIsNone(updated.date_of_birth)
        with connect(self.db_path) as db:
            self.assertIsNone(db.execute('SELECT email FROM "User" WHERE userID=?',
                                         (self.new_customer,)).fetchone()[0])

    def test_profile_cli_keeps_original_view_update_confirm_cancel_flow(self):
        load_sample_users(self.svc, self.owner)
        for username, password in [('maya.customer', DEMO_PASSWORDS['Customer']),
                                   ('emma.staff', DEMO_PASSWORDS['Employee']),
                                   ('akira.owner', DEMO_PASSWORDS['Owner']),
                                   ('new-customer', 'my-customer-password')]:
            with self.subTest(username=username):
                user = self.svc.login(username, password)
                before = self.profiles.view_profile(user['userID'])
                with patch('inventory_cli.confirm', side_effect=[True, False]), \
                     patch('builtins.input', side_effect=['Discarded', 'discard@example.test', '', '']):
                    profile_menu(self.profiles, user)
                self.assertEqual(self.profiles.view_profile(user['userID']), before)
                with patch('inventory_cli.confirm', side_effect=[True, True]), \
                     patch('builtins.input', side_effect=['Changed in Menu',
                                                         'profile-new@example.test',
                                                         '514-555-0187', '1998-01-01']):
                    profile_menu(self.profiles, user)
                after = self.profiles.view_profile(user['userID'])
                self.assertEqual(after.name, 'Changed in Menu')
                self.assertEqual(after.email, 'profile-new@example.test')
                self.assertEqual(after.phone_number, '514-555-0187')
                self.assertEqual(str(after.date_of_birth), '1998-01-01')
                self.assertEqual(user['email'], after.email)

    def test_profile_validation_and_rollback_preserve_both_tables(self):
        original = self.profiles.view_profile(self.new_customer)
        with self.assertRaises(ProfileError):
            self.profiles.update_profile(self.new_customer, {
                'name': 'Should Not Save', 'email': 'bad email',
                'phoneNumber': '514-555-0177'
            })
        self.assertEqual(self.profiles.view_profile(self.new_customer), original)
        with connect(self.db_path) as db:
            db.execute('''CREATE TRIGGER prevent_email BEFORE UPDATE OF email ON "User"
                          BEGIN SELECT RAISE(ABORT, 'no email'); END''')
            db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.profiles.update_profile(self.new_customer, {
                'name': 'Should Not Save', 'email': 'valid@example.test',
            })
        self.assertEqual(self.profiles.view_profile(self.new_customer), original)

    def test_import_repeat_after_edited_sample_profile_and_username_is_safe(self):
        load_sample_users(self.svc, self.owner)
        sample = self.sample_id('maya.customer')
        before_id = self.profiles.view_profile(sample).profile_id
        self.profiles.update_profile(sample, {'name': 'My Own Name', 'email': 'new@example.test'})
        admin = UserManagementService(self.db_path)
        admin.edit_account(self.owner, sample, {'username': 'my-new-maya'})
        result = load_sample_users(self.svc, self.owner)
        self.assertEqual(result, {'created': 0, 'already_present': 8})
        saved = self.profiles.view_profile(sample)
        self.assertEqual(saved.name, 'My Own Name')
        self.assertEqual(saved.email, 'new@example.test')
        self.assertEqual(saved.username, 'my-new-maya')
        self.assertEqual(saved.profile_id, before_id)
        self.assertEqual(self.svc.login('my-new-maya', DEMO_PASSWORDS['Customer'])['userID'], sample)

    def test_sample_tracking_survives_account_preserving_database_reset(self):
        load_sample_users(self.svc, self.owner)
        sample = self.sample_id('emma.staff')
        self.profiles.update_profile(sample, {'name': 'Edited Emma', 'email': 'emma-new@example.test'})
        reset_database(self.svc, self.owner, with_demo=False, preserve_accounts=True)
        self.assertEqual(load_sample_users(self.svc, self.owner), {'created': 0, 'already_present': 8})
        self.assertEqual(self.profiles.view_profile(sample).email, 'emma-new@example.test')
        self.assertEqual(self.profiles.view_profile(sample).name, 'Edited Emma')

    def test_option_18_customer_route_and_option_19_loyalty_route(self):
        load_sample_users(self.svc, self.owner)
        customer = self.svc.login('maya.customer', DEMO_PASSWORDS['Customer'])
        with patch('inventory_cli.prompt', side_effect=['18', '19', '17']), \
             patch('inventory_cli.confirm', side_effect=[False, True]), \
             patch('builtins.input', return_value=''):
            menu(self.svc, customer)
        cid = self.loyalty.customer_id_for_user(customer['userID'])
        self.assertEqual(self.loyalty.retrieve_customer_account(cid)['pointsBalance'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
