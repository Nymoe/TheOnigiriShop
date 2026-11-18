"""Desktop workflows against disposable databases and the shared CLI services."""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc
from unittest.mock import patch

from accounting_service import AccountingLedger
from desktop_app import InputDialog, OnigiriDesktop, database_path
from inventory_db import DEFAULT_DB, connect, transaction
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(), 'Requires Tkinter and a graphical display')
class DesktopIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'shop.db'
        self.app = OnigiriDesktop(self.path)
        self.addCleanup(self.app.destroy)
        self.app.set_fullscreen(False)
        self.app.withdraw()
        self.owner = self.app.svc.create_user('Owner', 'owner', ' owner password ', 'Owner')
        self.employee = self.app.svc.create_user('Employee', 'employee', 'employee-password', 'Employee')
        self.customer = self.app.svc.create_user('Customer', 'customer', 'customer-password', 'Customer')
        self.app.user = self.app.svc.login('owner', ' owner password ')
        self.app.current_page = 'Dashboard'
        for kind in ('showinfo', 'showwarning', 'showerror', 'askyesno'):
            patcher = patch('desktop_app.messagebox.' + kind, return_value=True)
            mock = patcher.start()
            self.addCleanup(patcher.stop)
            setattr(self, kind, mock)
        self.rice = self.app.svc.add_ingredient('Rice', 'g', 1000, 100, self.owner)
        self.recipe = self.app.svc.add_recipe('Onigiri', 10)
        self.app.svc.set_recipe_ingredient(self.recipe, self.rice, 10)

    def entries(self, source=None):
        rows = self.app.accounting.getTransactions()
        return rows if source is None else [r for r in rows if r['sourceType'] == source]

    def stock(self):
        return self.app.svc.inventory()[0]['quantityOnHand']

    def customer_id(self, enroll=True):
        if enroll:
            self.app.loyalty.enroll_existing_customer(self.customer, self.owner)
        return self.app.loyalty.customer_id_for_user(self.customer)

    def checkout(self, oid, reward=''):
        with patch.object(self.app, 'ask', side_effect=[{'id': str(oid)}, {'reward': str(reward)}]):
            self.app.complete_order()

    def test_source_database_path_matches_cli_from_another_directory(self):
        import os
        previous = Path.cwd()
        try:
            os.chdir(self.tmp.name)
            self.assertEqual(database_path(), DEFAULT_DB)
        finally:
            os.chdir(previous)

    def test_password_fields_preserve_whitespace(self):
        def submit():
            dlg = next(c for c in self.app.winfo_children() if isinstance(c, InputDialog))
            dlg._vars['password'].set(' password with spaces ')
            dlg._vars['name'].set(' Customer ')
            dlg._submit()
        self.app.after(50, submit)
        dlg = InputDialog(self.app, 'Password', [('password', 'Password', '', 'password'),
                                                ('name', 'Name', '', 'text')])
        self.assertEqual(dlg.result, {'password': ' password with spaces ', 'name': 'Customer'})

    def test_walkin_credentials_are_displayed_and_allow_login(self):
        data = dict(name='Walk In', email='walkin@example.test', phone='', username='', password='')
        with patch.object(self.app, 'ask', return_value=data):
            self.app.register_walkin()
        text = self.showinfo.call_args.args[1]
        username = text.split('Username: ')[1].split('\n')[0]
        password = text.split('Password: ')[1].split('\n')[0]
        user = self.app.svc.login(username, password)
        cid = self.app.loyalty.customer_id_for_user(user['userID'])
        self.assertIn(f'Customer ID: {cid}', text)
        self.assertIn(f"User ID: {user['userID']}", text)
        self.assertEqual(user['role'], 'Customer')
        self.assertEqual(self.app.loyalty.retrieve_customer_account(cid)['pointsBalance'], 0)

    def test_public_signup_and_customer_admin_actions_are_denied(self):
        original = len(self.app.svc.list_users())
        self.app._register_new_user('Customer')
        self.assertEqual(len(self.app.svc.list_users()), original)
        self.app.user = self.app.svc.login('customer', 'customer-password')
        self.assertNotIn('Recipes', self.app.allowed_pages())
        with patch.object(self.app, 'ask') as ask:
            for name in ('new_ingredient', 'new_order', 'accounting_add', 'payroll_open',
                         'create_user_admin', 'backup_database', 'list_customers', 'feedback_review'):
                getattr(self.app, name)()
            ask.assert_not_called()
        self.assertEqual(self.entries(), [])
        self.app.show_page('Accounting')
        self.assertEqual(self.app.current_page, 'Dashboard')

    def test_role_is_rechecked_after_form_before_financial_write(self):
        def demote(*args, **kwargs):
            with transaction(self.path) as db:
                db.execute('UPDATE "User" SET role=? WHERE userID=?', ('Employee', self.owner))
            return {'type': 'Sale', 'date': date.today().isoformat(), 'description': 'Denied',
                    'reference': '', 'amount': '10'}
        with patch.object(self.app, 'ask', side_effect=demote):
            self.app.accounting_add()
        self.assertEqual(self.entries(), [])
        self.assertTrue(self.showerror.called)

    def test_disabled_session_cannot_adjust_inventory(self):
        with transaction(self.path) as db:
            db.execute('UPDATE "User" SET accountActive=0 WHERE userID=?', (self.owner,))
        with patch.object(self.app, 'ask') as ask:
            self.app.adjust_stock()
            ask.assert_not_called()
        self.assertIsNone(self.app.user)
        self.assertEqual(self.stock(), 1000)

    def test_adjustments_post_only_provided_value_and_rollback_invalid_value(self):
        data = dict(id=str(self.rice), mode='remove', qty='5', note='Spoilage', amount='')
        with patch.object(self.app, 'ask', return_value=data):
            self.app.adjust_stock()
        self.assertEqual(self.stock(), 995)
        self.assertEqual(self.entries(), [])
        self.assertIn('No financial entry', self.showinfo.call_args.args[1])
        data['amount'] = '7.25'
        with patch.object(self.app, 'ask', return_value=data):
            self.app.adjust_stock()
        self.assertEqual(self.stock(), 990)
        self.assertEqual(self.entries('Adjustment')[0]['amount'], 7.25)
        data['amount'] = '-1'
        with patch.object(self.app, 'ask', return_value=data):
            self.app.adjust_stock()
        self.assertEqual(self.stock(), 990)
        self.assertEqual(len(self.entries('Adjustment')), 1)

    def test_partial_deliveries_post_known_invoice_and_reject_overreceipt(self):
        po = self.app.svc.create_purchase_order({self.rice: 20})
        self.assertEqual(self.stock(), 1000)
        data = dict(id=str(self.rice), qty='5', supplier='', order=str(po), amount='', reference='')
        with patch.object(self.app, 'ask', return_value=data):
            self.app.receive_stock()
        self.assertEqual(self.stock(), 1005)
        self.assertEqual(self.entries(), [])
        self.assertIn('No financial Purchase', self.showinfo.call_args.args[1])
        data.update(qty='10', amount='12.50', reference='INV-1')
        with patch.object(self.app, 'ask', return_value=data):
            self.app.receive_stock()
        self.assertEqual(self.stock(), 1015)
        self.assertEqual(self.app.svc.purchase_orders()[0]['status'], 'Partially Received')
        self.assertEqual([(r['amount'], r['reference']) for r in self.entries('Delivery')], [(12.5, 'INV-1')])
        data['qty'] = '6'
        with patch.object(self.app, 'ask', return_value=data):
            self.app.receive_stock()
        self.assertEqual(self.stock(), 1015)
        self.assertEqual(len(self.entries('Delivery')), 1)

    def test_invalid_ids_are_reported_and_payroll_validation_is_early(self):
        for name in ('complete_order', 'payroll_hours', 'payroll_calculate'):
            with self.subTest(name=name), patch.object(self.app, 'ask', return_value={'id': 'abc'}) as ask:
                getattr(self.app, name)()
                self.assertEqual(ask.call_count, 1)
        with patch.object(self.app, 'ask', return_value={'id': '9999'}) as ask:
            self.app.payroll_hours()
            self.assertEqual(ask.call_count, 1)
        self.assertEqual(self.stock(), 1000)
        self.assertEqual(self.entries(), [])
        self.assertGreaterEqual(self.showerror.call_count, 4)

    def test_invalid_customer_does_not_create_pending_order(self):
        with patch('desktop_app.OrderComposer') as cart, patch.object(self.app, 'ask', return_value={'cid': 'abc'}):
            cart.return_value.result = {self.recipe: 1}
            self.app.new_order()
        self.assertEqual(self.app.svc.customer_orders(), [])
        self.assertTrue(self.showerror.called)

    def test_checkout_discount_is_atomic_and_duplicate_completion_is_blocked(self):
        cid = self.customer_id()
        earning = self.app.svc.create_customer_order({self.recipe: 2}, self.owner, cid)
        self.app.loyalty.complete_order_with_loyalty(self.owner, cid, earning)
        reward = self.app.loyalty.create_reward(self.owner, 'Five off', 10, 5)
        oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner, cid)
        self.checkout(oid, reward)
        self.assertEqual(self.app.svc.order_details(oid)['status'], 'Completed')
        self.assertEqual(self.stock(), 970)
        self.assertEqual(next(r for r in self.entries('Order') if r['sourceID'] == oid)['amount'], 5)
        self.assertEqual(self.app.loyalty.retrieve_customer_account(cid)['pointsBalance'], 240)
        text = self.askyesno.call_args.args[1]
        self.assertIn('Net sale: $5.00', text)
        self.assertEqual(len([w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel)]), 1)
        self.checkout(oid, reward)
        self.assertEqual(self.stock(), 970)
        self.assertEqual(len(self.entries('Order')), 2)
        self.assertEqual(len(self.app.loyalty.transaction_history(cid)), 2)

    def test_insufficient_stock_and_ledger_failure_leave_checkout_pending(self):
        cid = self.customer_id()
        oid = self.app.svc.create_customer_order({self.recipe: 101}, self.owner, cid)
        self.checkout(oid)
        self.assertEqual(self.app.svc.order_details(oid)['status'], 'Pending')
        self.assertEqual(self.stock(), 1000)
        oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner, cid)
        with patch('loyalty_service.post_source_transaction', side_effect=sqlite3.IntegrityError('Posting failed')):
            self.checkout(oid)
        self.assertEqual(self.app.svc.order_details(oid)['status'], 'Pending')
        self.assertEqual(self.stock(), 1000)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.app.loyalty.transaction_history(cid), [])

    def test_checkout_cancel_preserves_pending_order_stock_and_loyalty(self):
        cid = self.customer_id()
        oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner, cid)
        self.askyesno.return_value = False
        self.checkout(oid)
        self.assertEqual(self.app.svc.order_details(oid)['status'], 'Pending')
        self.assertEqual(self.stock(), 1000)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.app.loyalty.transaction_history(cid), [])

    def test_checkout_can_enroll_customer_before_completion(self):
        cid = self.customer_id(enroll=False)
        oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner, cid)
        self.checkout(oid)
        self.assertEqual(self.app.loyalty.retrieve_customer_account(cid)['pointsBalance'], 100)
        self.assertEqual(self.entries('Order')[0]['amount'], 10)

    def test_completed_order_loyalty_receipt_survives_refresh(self):
        cid = self.customer_id()
        oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner, cid)
        self.app.svc.complete_customer_order(oid, self.owner)
        with patch.object(self.app, 'ask', return_value=dict(cid=str(self.customer), order=str(oid), reward='', eligible='')):
            self.app.record_loyalty()
        self.assertEqual(len(self.entries('Order')), 1)
        self.assertEqual(len([w for w in self.app.winfo_children() if isinstance(w, tk.Toplevel)]), 1)

    def test_payroll_paid_once_and_approved_hours_are_protected(self):
        eid = self.app.users.get_account(self.owner, self.employee)['employeeID']
        self.app.payroll.set_hourly_rate(self.owner, eid, 20)
        pid = self.app.payroll.open_payroll(self.owner, date.today().isoformat())
        with patch.object(self.app, 'ask', side_effect=[{'id': str(pid)},
                {'employee': f'{self.employee}: Employee', 'hours': '8', 'overtime': '0'}]):
            self.app.payroll_hours()
        with patch.object(self.app, 'ask', return_value={'id': str(pid)}):
            self.app.payroll_calculate()
            self.app.payroll_entries()
            self.app.payroll_approve()
            self.app.payroll_hours()
            self.app.payroll_pay()
            self.app.payroll_pay()
        saved = self.app.payroll.get_payroll(self.owner, pid)
        self.assertEqual(saved.status, 'Paid')
        self.assertEqual(saved.entries[0].hoursWorked, 8)
        self.assertEqual(len(self.entries('Payroll')), 1)
        self.assertEqual(self.entries('Payroll')[0]['amount'], saved.totalAmount)

    def test_account_edit_clears_fields_and_safe_deletion_preserves_history(self):
        changes = dict(name='Updated', username='renamed', email='', phoneNumber='', dateOfBirth='')
        with patch.object(self.app, 'ask', side_effect=[{'id': str(self.customer)}, changes]):
            self.app.edit_user_admin()
        self.assertEqual(self.app.users.get_account(self.owner, self.customer)['username'], 'renamed')
        self.assertIsNone(self.app.users.get_account(self.owner, self.customer)['email'])
        self.app.feedback.submit_feedback(self.customer, 'Keep my feedback', 5)
        with patch.object(self.app, 'ask', return_value={'id': str(self.customer)}):
            self.app.delete_user_admin()
        self.assertEqual(len(self.app.feedback.view_feedback(self.owner)), 1)
        unused = self.app.svc.create_user('Unused', 'unused', 'unused-password', 'Customer')
        with patch.object(self.app, 'ask', return_value={'id': str(unused)}):
            self.app.delete_user_admin()
        self.assertNotIn(unused, [r['userID'] for r in self.app.svc.list_users()])

    def test_customer_directory_keeps_distinct_ids_without_enrollment(self):
        with patch.object(self.app, '_records_dialog') as show:
            self.app.list_customers()
        rows = show.call_args.args[1]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['userID'], self.customer)
        self.assertNotEqual(rows[0]['customerID'], self.customer)
        self.assertEqual(rows[0]['loyaltyStatus'], 'Not enrolled')

    def test_historical_sales_are_imported_only_for_selected_order(self):
        from accounting_service import AccountingTransaction
        ids = []
        for _ in range(2):
            oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner)
            self.app.svc.complete_customer_order(oid, self.owner)
            ids.append(oid)
        with transaction(self.path) as db:
            db.execute("DELETE FROM AccountingTransaction WHERE sourceType='Order'")
        self.app.accounting.addTransaction(AccountingTransaction(None, 'Sale', date.today().isoformat(),
                                                                 'Possibly overlapping sale', '', 10))
        win,post=self.app.accounting_sync_orders()
        def trees(parent):
            return [c for c in parent.winfo_children() if c.winfo_class()=='Treeview']+[t for c in parent.winfo_children() for t in trees(c)]
        tree=trees(win)[0]
        tree.selection_set(next(i for i in tree.get_children() if int(tree.item(i,'values')[0])==ids[0]))
        post()
        self.assertEqual([r['sourceID'] for r in self.entries('Order')], [ids[0]])
        self.assertEqual([r['orderID'] for r in self.app.accounting.pending_completed_orders()], [ids[1]])

    def test_trends_show_graphs_and_do_not_change_business_data(self):
        # Record actual consumption and revenue on three distinct dates.
        for day in ('2026-10-01', '2026-10-02', '2026-10-03'):
            with patch('inventory_service._today', return_value=day+'T12:00:00'), \
                 patch('inventory_service._date_today', return_value=day):
                oid = self.app.svc.create_customer_order({self.recipe: 1}, self.owner)
                self.app.svc.complete_customer_order(oid, self.owner)
        before = self.path.read_bytes()
        with patch.object(self.app,'show_trend_chart',wraps=self.app.show_trend_chart) as graph:
            self.app.trend_show('Sales')
            self.app.trend_show('Financial')
            with patch.object(self.app, 'ask', return_value={'ingredient': f'{self.rice}: Rice'}):
                self.app.trend_ingredient()
        self.assertEqual(graph.call_count, 3)
        self.assertEqual(graph.call_args.kwargs['ylabel'], 'g consumed')
        self.assertEqual(self.path.read_bytes(), before)
        import sys
        with patch.dict(sys.modules,{'matplotlib.backends.backend_tkagg':None}):
            self.app.trend_show('Sales')
        labels=[c.cget('text') for c in self.app.trend_results.winfo_children() if isinstance(c,tk.Label)]
        self.assertTrue(any('Numerical forecast' in text for text in labels))

    def test_missing_history_explains_prerequisite_without_opening_graph(self):
        with patch('desktop_app.plot_prediction_chart') as graph:
            self.app.trend_show('Sales')
        graph.assert_not_called()
        self.assertIn('three distinct dates', self.showinfo.call_args.args[1])


if __name__ == '__main__':
    unittest.main()
