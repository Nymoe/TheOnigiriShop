"""Feedback regression and integration tests using temporary shop databases."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from feedback_service import Feedback, FeedbackError, FeedbackService, FeedbackStorageError
from inventory_cli import menu
from inventory_db import connect, initialize
from inventory_service import InventoryService
from loyalty_service import LoyaltyService
from profile_service import ProfileService


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / 'shop.sqlite'
        self.inv = InventoryService(self.path)
        self.owner = self.inv.create_user('Owner', 'owner', 'owner12345', 'Owner')
        self.employee = self.inv.create_user('Employee', 'employee', 'employee12345', 'Employee')
        self.customer = self.inv.create_user('Customer', 'customer', 'customer12345', 'Customer')
        self.other = self.inv.create_user('Another Customer', 'other', 'other12345', 'Customer')
        self.svc = FeedbackService(self.path)

    def test_customer_submit_with_rating_and_staff_review(self):
        item = self.svc.submit_feedback(self.customer, '  Helpful staff!  ', 5)
        self.assertEqual(item.feedbackText, 'Helpful staff!')
        self.assertEqual(item.rating, 5)
        self.assertEqual(item.status, 'Submitted')
        self.assertTrue(item.feedbackID > 0)
        self.assertEqual(len(item.publicUUID), 32)
        self.assertTrue(item.submissionDate)
        self.assertTrue(item.validateFeedback())
        self.assertEqual(item.getFeedback(), 'Helpful staff!')
        self.assertEqual(len(self.svc.view_submitted_feedback(self.customer)), 1)
        pending = self.svc.view_feedback(self.employee, status='Submitted')
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0].customerName, 'Customer')
        self.assertEqual(pending[0].customerUsername, 'customer')
        result = self.svc.review_feedback(self.employee, item.feedbackID)
        self.assertEqual(result.status, 'Reviewed')
        self.assertEqual(self.svc.getFeedback(self.owner, item.feedbackID).status, 'Reviewed')
        self.assertEqual(self.svc.view_feedback(self.owner, status='Submitted'), [])
        self.assertEqual(len(self.svc.view_feedback(self.owner, status='Reviewed')), 1)

    def test_optional_rating_text_only_and_multiple_feedback(self):
        one = self.svc.submitFeedback(self.customer, 'Taste was good')
        two = self.svc.storeFeedback(self.customer, 'Please offer vegan options', 4)
        self.assertIsNone(one.rating)
        self.assertEqual([f.feedbackID for f in self.svc.viewSubmittedFeedback(self.customer)],
                         [two.feedbackID, one.feedbackID])
        self.assertEqual(len(self.svc.viewFeedback(self.owner)), 2)
        self.assertEqual(self.svc.updateStatus(self.owner, one.feedbackID, 'Reviewed').status,
                         'Reviewed')
        self.assertEqual(self.svc.reviewFeedback(self.owner, two.feedbackID).status, 'Reviewed')

    def test_customers_can_only_see_their_own_submissions(self):
        first = self.svc.submit_feedback(self.customer, 'First customer')
        second = self.svc.submit_feedback(self.other, 'Other customer')
        self.assertEqual([x.feedbackID for x in self.svc.view_submitted_feedback(self.customer)],
                         [first.feedbackID])
        self.assertEqual([x.feedbackID for x in self.svc.view_submitted_feedback(self.other)],
                         [second.feedbackID])
        with self.assertRaises(FeedbackError):
            self.svc.view_feedback(self.customer, second.feedbackID)
        with self.assertRaises(FeedbackError):
            self.svc.review_feedback(self.customer, first.feedbackID)
        with self.assertRaises(FeedbackError):
            self.svc.update_status(self.customer, first.feedbackID, 'Reviewed')

    def test_employee_owner_cannot_submit_as_customers(self):
        for user in (self.owner, self.employee):
            with self.assertRaises(FeedbackError):
                self.svc.submit_feedback(user, 'Staff pretending to be customer', 5)
            with self.assertRaises(FeedbackError):
                self.svc.view_submitted_feedback(user)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Feedback').fetchone()[0], 0)

    def test_missing_or_invalid_data_does_not_save(self):
        invalid = [('', None), ('   ', 1), (None, 3), ('x' * 2001, None),
                   ('Fine', 0), ('Fine', 6), ('Fine', 1.5), ('Fine', True),
                   ('Fine', '5'), ('null\x00', None)]
        for text, rating in invalid:
            with self.subTest(text=str(text)[:20], rating=rating):
                with self.assertRaises(FeedbackError):
                    self.svc.submit_feedback(self.customer, text, rating)
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Feedback').fetchone()[0], 0)

    def test_disabled_and_changed_accounts_rechecked_on_every_action(self):
        item = self.svc.submit_feedback(self.customer, 'Before disabling')
        with connect(self.path) as db:
            db.execute('UPDATE "User" SET accountActive=0 WHERE userID=?', (self.customer,))
            db.commit()
        with self.assertRaises(FeedbackError):
            self.svc.submit_feedback(self.customer, 'After disabling')
        with self.assertRaises(FeedbackError):
            self.svc.view_submitted_feedback(self.customer)
        with connect(self.path) as db:
            db.execute('UPDATE "User" SET accountActive=0 WHERE userID=?', (self.employee,))
            db.commit()
        with self.assertRaises(FeedbackError):
            self.svc.review_feedback(self.employee, item.feedbackID)
        self.assertEqual(self.svc.view_feedback(self.owner)[0].status, 'Submitted')

    def test_failure_to_store_returns_retry_error_and_rolls_back(self):
        with connect(self.path) as db:
            db.execute('''CREATE TRIGGER fail_feedback BEFORE INSERT ON Feedback
                          BEGIN SELECT RAISE(ABORT, 'simulated write error'); END''')
            db.commit()
        with self.assertRaisesRegex(FeedbackStorageError, 'Please try again'):
            self.svc.submit_feedback(self.customer, 'Please save me')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Feedback').fetchone()[0], 0)
            db.execute('DROP TRIGGER fail_feedback')
            db.commit()
        self.assertTrue(self.svc.submit_feedback(self.customer, 'Retry works').feedbackID)

    def test_existing_data_survives_reinitialization_and_profile_loyalty_integration(self):
        FeedbackService(self.path).submit_feedback(self.customer, 'Original record', 4)
        LoyaltyService(self.path)
        ProfileService(self.path).update_profile(self.customer, {'name': 'Updated Customer'})
        self.assertFalse(initialize(self.path))
        svc = FeedbackService(self.path)
        self.assertEqual(svc.view_submitted_feedback(self.customer)[0].feedbackText,
                         'Original record')
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT name FROM "User" WHERE userID=?',
                                        (self.customer,)).fetchone()[0], 'Updated Customer')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Feedback').fetchone()[0], 1)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('''INSERT INTO Feedback(publicUUID,customerID,feedbackText,submissionDate)
                              VALUES('bad',999999,'Orphan',CURRENT_TIMESTAMP)''')

    def test_upgrade_adds_feedback_without_changing_older_records(self):
        """An existing shop database should gain the new table on its next launch."""
        with connect(self.path) as db:
            old_users = [tuple(row) for row in db.execute(
                'SELECT userID,username,role FROM "User" ORDER BY userID')]
            db.execute('DROP TABLE Feedback')
            db.commit()
        self.assertFalse(initialize(self.path))
        self.assertFalse(initialize(self.path))
        with connect(self.path) as db:
            self.assertEqual([tuple(row) for row in db.execute(
                'SELECT userID,username,role FROM "User" ORDER BY userID')], old_users)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Feedback').fetchone()[0], 0)
        self.assertEqual(self.svc.submit_feedback(self.customer, 'Works after upgrade').status,
                         'Submitted')

    def test_reset_backups_include_feedback_and_restore_recovers_it(self):
        """An intentional reset clears submissions, but its backup restores them."""
        from demo_tools import reset_database, restore_database

        submitted = self.svc.submit_feedback(self.customer, 'Please retain this review', 4)
        backup = reset_database(self.inv, self.owner, with_demo=False, preserve_accounts=True)
        self.assertTrue(backup.is_file())
        self.assertEqual(self.svc.view_submitted_feedback(self.customer), [])
        restore_database(self.inv, self.owner, backup)
        restored = self.svc.view_submitted_feedback(self.customer)
        self.assertEqual([record.feedbackID for record in restored], [submitted.feedbackID])
        self.assertEqual(restored[0].feedbackText, 'Please retain this review')

    def test_customer_history_prevents_accidental_account_deletion(self):
        from user_management_service import UserManagementService
        from inventory_service import InventoryError
        self.svc.submit_feedback(self.customer, 'Retain my feedback history')
        with self.assertRaises(InventoryError):
            UserManagementService(self.path).delete_account(self.owner, self.customer)
        self.assertEqual(len(self.svc.view_submitted_feedback(self.customer)), 1)

    def test_domain_store_method_reuses_authenticated_customer_identity(self):
        with connect(self.path) as db:
            customer_id = db.execute('SELECT customerID FROM Customer WHERE userID=?',
                                     (self.customer,)).fetchone()[0]
        model = Feedback(None, customer_id, 'Service was fast', rating=5)
        saved = model.storeFeedback(self.svc, self.customer)
        self.assertEqual(saved.customerID, customer_id)
        self.assertEqual(saved.feedbackText, model.feedbackText)

    def test_not_found_bad_status_and_bad_id(self):
        for feedback_id in (0, -1, True, '1'):
            with self.assertRaises(FeedbackError):
                self.svc.review_feedback(self.owner, feedback_id)
        with self.assertRaises(FeedbackError):
            self.svc.getFeedback(self.owner, 404)
        with self.assertRaises(FeedbackError):
            self.svc.update_status(self.employee, 404, 'Reviewed')
        with self.assertRaises(FeedbackError):
            self.svc.view_feedback(self.employee, status='Invalid')
        with self.assertRaises(FeedbackError):
            Feedback(None, 1, 'hi').updateStatus('Invalid')

    def test_cli_customer_submit_and_staff_review(self):
        customer = self.inv.login('customer', 'customer12345')
        stdout = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '1', 'Excellent rice', '5', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(stdout):
            menu(self.inv, customer)
        self.assertIn('successfully received and saved', stdout.getvalue())
        item = self.svc.view_submitted_feedback(self.customer)[0]
        staff = self.inv.login('employee', 'employee12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '1', '2', str(item.feedbackID), '0', '23']), \
             patch('inventory_cli.confirm', return_value=True), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, staff)
        self.assertIn('Excellent rice', output.getvalue())
        self.assertIn('Customer #', output.getvalue())
        self.assertIn('(customer)', output.getvalue())
        self.assertEqual(self.svc.getFeedback(self.owner, item.feedbackID).status, 'Reviewed')

    def test_cli_missing_text_and_invalid_rating_show_errors(self):
        customer = self.inv.login('customer', 'customer12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '1', '', '', '1', 'test', '9', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, customer)
        self.assertIn('Please complete the feedback text', output.getvalue())
        self.assertIn('Rating must be a whole number', output.getvalue())
        self.assertEqual(len(self.svc.view_submitted_feedback(self.customer)), 0)

    def test_multiline_comments_are_saved_and_displayed(self):
        note = 'Great service!\nPlease add more vegetarian choices.\tThank you.'
        item = self.svc.submit_feedback(self.customer, note, 4)
        self.assertEqual(item.feedbackText, note)
        self.assertTrue(item.validateFeedback())

    def test_staff_can_cancel_review_using_zero_or_blank(self):
        item = self.svc.submit_feedback(self.customer, 'Keep this unread')
        staff = self.inv.login('employee', 'employee12345')
        for cancel in ('0', ''):
            output = StringIO()
            with patch('inventory_cli.prompt', side_effect=['6', '2', cancel, '0', '23']), \
                 patch('builtins.input', return_value=''), redirect_stdout(output):
                menu(self.inv, staff)
            self.assertIn('Returned to the Feedback System menu.', output.getvalue())
            self.assertIn('Feedback awaiting review', output.getvalue())
            self.assertEqual(self.svc.getFeedback(self.owner, item.feedbackID).status, 'Submitted')

    def test_invalid_review_id_explains_how_to_cancel(self):
        self.svc.submit_feedback(self.customer, 'Test entry')
        staff = self.inv.login('employee', 'employee12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '2', 'not-an-id', '0', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, staff)
        self.assertIn('positive whole-number Feedback ID, or 0 / Enter', output.getvalue())

    def test_no_feedback_and_no_pending_reviews_give_next_steps(self):
        staff = self.inv.login('employee', 'employee12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '1', '2', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, staff)
        self.assertIn('No customer feedback has been submitted yet.', output.getvalue())
        self.assertIn('no feedback waiting for review', output.getvalue())
        customer = self.inv.login('customer', 'customer12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '2', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, customer)
        self.assertIn('You have not submitted feedback yet', output.getvalue())
        record = self.svc.submit_feedback(self.customer, 'Already processed')
        self.svc.review_feedback(self.owner, record.feedbackID)
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '2', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, staff)
        self.assertIn('no feedback waiting for review', output.getvalue())

    def test_feedback_ownership_and_customer_profile_required(self):
        from inventory_service import InventoryError
        with connect(self.path) as db:
            owner_customer_id = db.execute('SELECT customerID FROM Customer WHERE userID=?',
                                            (self.other,)).fetchone()[0]
            db.execute('DELETE FROM Customer WHERE userID=?', (self.other,))
            db.commit()
        with self.assertRaisesRegex(FeedbackError, 'Ask an Owner'):
            self.svc.submit_feedback(self.other, 'Missing customer subtype')
        with connect(self.path) as db:
            customer_id = db.execute('SELECT customerID FROM Customer WHERE userID=?',
                                     (self.customer,)).fetchone()[0]
        with self.assertRaisesRegex(FeedbackError, 'different Customer account'):
            Feedback(None, owner_customer_id, 'Wrong identity').storeFeedback(self.svc, self.customer)
        self.assertEqual(self.svc.view_submitted_feedback(self.customer), [])

    def test_role_change_after_feedback_gives_clear_message_and_preserves_history(self):
        from inventory_service import InventoryError
        from user_management_service import UserManagementService
        manager = UserManagementService(self.path)
        item = self.svc.submit_feedback(self.customer, 'Keep for future owner review')
        with self.assertRaisesRegex(InventoryError, 'Customer has saved feedback'):
            manager.change_role(self.owner, self.customer, 'Employee')
        self.assertEqual(manager.get_account(self.owner, self.customer)['role'], 'Customer')
        manager.set_active(self.owner, self.customer, False)
        with self.assertRaisesRegex(FeedbackError, 'no longer active'):
            self.svc.view_submitted_feedback(self.customer)
        manager.set_active(self.owner, self.customer, True)
        self.assertEqual(self.svc.view_submitted_feedback(self.customer)[0].feedbackID,
                         item.feedbackID)
        # Account management shows the customer number only after loyalty
        # enrollment; feedback still retains its internal customer link.
        with connect(self.path) as db:
            actual_id = db.execute('SELECT customerID FROM Customer WHERE userID=?',
                                   (self.customer,)).fetchone()[0]
        self.assertEqual(actual_id, item.customerID)

    def test_cancel_submission_without_storing(self):
        customer = self.inv.login('customer', 'customer12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '1', '/back', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, customer)
        self.assertIn('submission cancelled', output.getvalue())
        self.assertFalse(self.svc.view_submitted_feedback(self.customer))

    def test_nonexistent_and_reviewed_ids_have_clear_guidance(self):
        self.svc.submit_feedback(self.customer, 'Needs review')
        reviewed = self.svc.submit_feedback(self.customer, 'Already reviewed')
        self.svc.review_feedback(self.owner, reviewed.feedbackID)
        staff = self.inv.login('owner', 'owner12345')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['6', '2', str(reviewed.feedbackID),
                                                      '2', '999999', '0', '23']), \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            menu(self.inv, staff)
        self.assertIn('has already been reviewed', output.getvalue())
        self.assertIn('was not found', output.getvalue())



if __name__ == '__main__':
    unittest.main()
