"""Regression checks for timestamped loyalty, forecasts and desktop accessibility."""
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk, font as tkfont
import unittest
from unittest.mock import patch

from accounting_service import AccountingError
from desktop_app import OnigiriDesktop, InputDialog
from desktop_preferences import DesktopPreferences
from desktop_widgets import password_entry, title_label
from inventory_db import connect, transaction
from inventory_service import InventoryService, InventoryError
from loyalty_service import LoyaltyService, LoyaltyError
from trend_prediction_service import BusinessData, IngredientData, TrendPrediction
from test_desktop_ui import gui_display_ready


class ImprovementsSixServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'shop.db';self.shop=InventoryService(self.path)
        self.owner=self.shop.create_user('Owner','owner','OwnerPassword123!','Owner')
        self.customer=self.shop.create_user('Customer','customer','CustomerPassword123!','Customer')
        self.loyalty=LoyaltyService(self.path)
        self.cid=self.loyalty.customer_id_for_user(self.customer)
        self.loyalty.enroll_existing_customer(self.customer,self.owner)
        self.iid=self.shop.add_ingredient('Rice','g',1000,1,self.owner)
        self.rid=self.shop.add_recipe('Onigiri',10);self.shop.set_recipe_ingredient(self.rid,self.iid,1)

    def order(self,stamp):
        with patch('inventory_service._date_today',return_value='2026-11-18'),patch('inventory_service._today',return_value=stamp if stamp!='not-a-date' else '2026-11-18T12:00:00'):
            oid=self.shop.create_customer_order({self.rid:1},self.owner,self.cid)
            self.shop.complete_customer_order(oid,self.owner)
        with transaction(self.path) as db:db.execute('UPDATE "Order" SET orderDate=? WHERE orderID=?',(stamp,oid))
        return oid

    def test_timestamped_completed_order_loyalty_updates_one_sale_once(self):
        oid=self.order('2026-11-18T14:23:51')
        before=self.shop.inventory()[0]['quantityOnHand']
        reward=self.loyalty.create_reward(self.owner,'Two dollars off',10,2)
        with transaction(self.path) as db:db.execute('UPDATE LoyaltyAccount SET pointsBalance=100')
        receipt=self.loyalty.process_eligible_purchase(self.owner,self.cid,oid,reward_id=reward)
        self.assertEqual(receipt['finalAmount'],8)
        with closing(connect(self.path)) as db:
            rows=db.execute("SELECT * FROM AccountingTransaction WHERE sourceType='Order' AND sourceID=?",(oid,)).fetchall()
            self.assertEqual(len(rows),1);self.assertEqual(rows[0]['amount'],8)
            date_key='date' if 'date' in rows[0].keys() else 'transactionDate'
            self.assertEqual(rows[0][date_key],'2026-11-18T14:23:51')
        self.assertEqual(self.shop.inventory()[0]['quantityOnHand'],before)
        original=self.path.read_bytes()
        with self.assertRaises(LoyaltyError):self.loyalty.process_eligible_purchase(self.owner,self.cid,oid)
        self.assertEqual(self.path.read_bytes(),original)

    def test_invalid_historical_timestamp_rolls_back_loyalty_and_sale(self):
        oid=self.order('not-a-date')
        before=self.path.read_bytes()
        with self.assertRaises(AccountingError):self.loyalty.process_eligible_purchase(self.owner,self.cid,oid)
        self.assertEqual(before,self.path.read_bytes())

    def test_range_is_inclusive_and_preserves_actual_event_times(self):
        for day in (17,18,19,20):self.order(f'2026-11-{day}T14:23:51')
        before=self.path.read_bytes()
        history=BusinessData('Financial',self.path).retrieve_data('2026-11-18','2026-11-20')
        self.assertEqual([r['date'] for r in history],['2026-11-18','2026-11-19','2026-11-20'])
        self.assertEqual(history[0]['lastRecordedAt'],'2026-11-18T14:23:51')
        self.assertEqual(TrendPrediction(BusinessData('Financial',self.path)).generate_prediction(history),10)
        for source in (BusinessData('Sales',self.path),IngredientData(self.iid,self.path)):
            self.assertEqual(len(source.retrieve_data('2026-11-18','2026-11-18')),1)
            with self.assertRaises(ValueError):source.retrieve_data('2026-11-20','2026-11-18')
            with self.assertRaises(ValueError):source.retrieve_data('11-18-2026',None)
        self.assertEqual(before,self.path.read_bytes())

    def test_supplier_edit_preserves_identity_catalogue_and_history(self):
        sid=self.shop.add_supplier('Market','old@example.test')
        po=self.shop.create_purchase_order({self.iid:5},supplier_id=sid)
        self.shop.update_supplier(sid,'New Market','new@example.test',user_id=self.owner)
        with closing(connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT supplierID FROM InventoryOrder WHERE inventoryOrderID=?',(po,)).fetchone()[0],sid)
            self.assertIsNotNone(db.execute('SELECT * FROM SupplierIngredient WHERE supplierID=?',(sid,)).fetchone())
        self.assertEqual(self.shop.suppliers()[0]['name'],'New Market')
        self.shop.add_supplier('Other')
        before=self.path.read_bytes()
        for target,name in ((sid,''),(sid,'Other'),(99999,'Missing')):
            with self.assertRaises(InventoryError):self.shop.update_supplier(target,name,'x',user_id=self.owner)
            self.assertEqual(before,self.path.read_bytes())
        with self.assertRaises(InventoryError):self.shop.update_supplier(sid,'No','',user_id=self.customer)
        self.assertEqual(before,self.path.read_bytes())

    def test_new_alert_times_and_demo_randomization_exclude_real_alerts(self):
        from demo_timestamps import snapshot_demo_events, randomize_new_demo_events
        self.shop.add_ingredient('Real ingredient','g',0,10,self.owner)
        with closing(connect(self.path)) as db:
            original=dict(db.execute('SELECT * FROM LowStockAlert').fetchone())
            boundary=snapshot_demo_events(db)
        self.assertGreater(len(original['createdAt']),10)
        for i in range(4):self.shop.add_ingredient(f'Demo ingredient {i}','g',0,10,self.owner)
        with transaction(self.path) as db:randomize_new_demo_events(db,boundary)
        with closing(connect(self.path)) as db:
            self.assertEqual(dict(db.execute('SELECT * FROM LowStockAlert WHERE alertID=?',(original['alertID'],)).fetchone()),original)
            stamps=[r[0] for r in db.execute('SELECT createdAt FROM LowStockAlert WHERE alertID>?',(original['alertID'],))]
            self.assertEqual(len(set(stamps)),4)
            self.assertTrue(all(len(s)>10 and s[11:19]!='00:00:00' for s in stamps))

    def test_preferences_are_account_specific_and_drop_disallowed_actions(self):
        prefs=DesktopPreferences(self.path)
        prefs.save(self.owner,quick_actions=['Payroll','Orders','Orders','Made Up'],
                   accessibility={'text_size':150,'contrast':'High Contrast','cursor':'Hand'})
        prefs.save(None,accessibility={'text_size':130})
        self.assertEqual(prefs.accessibility(self.customer)['text_size'],100)
        self.assertEqual(prefs.accessibility(self.owner)['text_size'],150)
        defaults=[('Orders','Orders'),('Payroll','Payroll')]
        self.assertEqual([p for _,p in prefs.quick_actions(self.owner,defaults)],['Payroll','Orders'])
        self.assertEqual(prefs.quick_actions(self.owner,[('Loyalty','Loyalty')]),[('Loyalty','Loyalty')])


@unittest.skipUnless(gui_display_ready(),'Display required')
class ImprovementsSixGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=OnigiriDesktop(Path(self.tmp.name)/'shop.db');self.addCleanup(self.app.destroy)
        self.errors=[];self.app.report_callback_exception=lambda kind,value,trace:self.errors.append(value)
        self.addCleanup(lambda:self.assertEqual(self.errors,[]))
        self.owner=self.app.svc.create_user('Owner','owner','OwnerPassword123!','Owner')
        self.app.user=self.app.svc.login('owner','OwnerPassword123!')
        self.app.set_fullscreen(False);self.app.geometry('1000x650')

    def visit(self,widget):
        yield widget
        for child in widget.winfo_children():yield from self.visit(child)

    def select(self,tree,identifier):
        iid=next(i for i in tree.get_children() if str(tree.item(i,'values')[0])==str(identifier))
        tree.selection_set(iid);self.app.update()

    def button(self,text):
        return next(w for w in self.visit(self.app) if isinstance(w,tk.Button) and w.cget('text')==text)

    def test_stock_forms_select_ingredient_and_focus_quantity(self):
        iid=self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
        self.app.show_page('Inventory');self.app.update();self.select(self.app.data_tree,iid)
        for action in (self.app.adjust_stock,self.app.receive_stock):
            with patch.object(self.app,'ask',return_value=None) as ask:action()
            self.assertEqual(ask.call_args.args[1][0][2],str(iid));self.assertEqual(ask.call_args.kwargs['focus'],'qty')

    def test_supplier_forms_use_selected_row(self):
        self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
        self.app.svc.add_supplier('A');sid=self.app.svc.add_supplier('Z')
        self.app.show_page('Suppliers');self.app.update();self.select(self.app.data_tree,sid)
        with patch.object(self.app,'ask',return_value=None) as ask:self.app.supplier_catalogue()
        self.assertTrue(ask.call_args.args[1][0][2].startswith(f'{sid}:'))
        with patch.object(self.app,'ask',return_value=None) as ask:self.app.modify_supplier()
        self.assertEqual(ask.call_args.args[1][0][2],'Z')

    def test_alert_action_state_tracks_selection_and_filtering(self):
        self.app.svc.add_ingredient('Rice','g',0,1,self.owner)
        self.app.show_page('Alerts');self.app.update()
        button=self.button('Update Alert Status');tree=self.app.data_tree
        self.assertEqual(button.cget('state'),'disabled')
        tree.selection_set(tree.get_children()[0]);self.app.update()
        self.assertEqual(button.cget('state'),'normal')
        self.assertIn('createdAt',tree['columns'])
        self.app.table_controls['query'].set('no matches');self.app.update()
        self.assertEqual(button.cget('state'),'disabled')

    def test_feedback_and_discrepancy_actions_require_eligible_rows(self):
        customer=self.app.svc.create_user('Customer','customer','CustomerPassword123!','Customer')
        feedback=self.app.feedback.submit_feedback(customer,'Good food',5)
        self.app.show_page('Feedback');self.app.update()
        button=self.button('Mark Reviewed');self.assertEqual(button.cget('state'),'disabled')
        self.select(self.app.data_tree,feedback.feedbackID);self.assertEqual(button.cget('state'),'normal')
        self.app.feedback.review_feedback(self.owner,feedback.feedbackID)
        self.app.show_page('Feedback');self.app.update();self.select(self.app.data_tree,feedback.feedbackID)
        self.assertEqual(self.button('Mark Reviewed').cget('state'),'disabled')
        rows=[{'discrepancyID':1,'status':'Flagged'}]
        win,perform=self.app.record_browser('Discrepancies',rows,lambda record:True,'Resolve Selected Discrepancy')
        self.app.update();button=self.button('Resolve Selected Discrepancy')
        self.assertEqual(button.cget('state'),'disabled')
        tree=next(w for w in self.visit(win) if isinstance(w,ttk.Treeview))
        self.select(tree,1);self.assertEqual(button.cget('state'),'normal')
        footer=button.master;close=next(w for w in footer.winfo_children() if isinstance(w,tk.Button) and w.cget('text')=='Close')
        self.assertLessEqual(abs(button.winfo_width()-close.winfo_width()),1)
        perform();self.app.update();self.assertEqual(len(tree.get_children()),0)
        self.assertEqual(button.cget('state'),'disabled')
        tree.redraw();self.assertEqual(len(tree.get_children()),0)

    def test_user_details_display_actual_role_identity_before_enrollment(self):
        cid=self.app.svc.create_user('Customer','customer','CustomerPassword123!','Customer')
        self.app.show_page('Users');self.app.update()
        for uid,label,wrong in [(cid,'Customer ID:','Employee ID:'),(self.owner,'Owner ID:','Employee ID:')]:
            self.select(self.app.data_tree,uid)
            self.app.data_tree.focus_force();self.app.update()
            with patch.object(self.app,'details_dialog') as details:
                self.app.data_tree.event_generate('<Return>');self.app.update()
            self.assertIn(label,details.call_args.args[1]);self.assertNotIn(wrong,details.call_args.args[1])

    def test_titles_midnight_fields_and_equal_search_control_heights(self):
        self.assertEqual(title_label('totalPOs'),'Total POs')
        self.app._use_theme('Midnight');self.app.show_page('Inventory');self.app.update()
        controls=[w for w in self.visit(self.app.body) if isinstance(w,(ttk.Entry,ttk.Combobox))]
        self.assertEqual(len({w.winfo_height() for w in controls}),1)
        self.assertTrue(all(w.winfo_height()>=32 for w in controls))
        self.assertEqual(ttk.Style(self.app).lookup('Fade0.TCombobox','fieldbackground',('readonly',)),'#263844')
        self.app.show_page('Suppliers')
        sid=self.app.svc.add_supplier('Market','email')
        win=self.app.open_record('Suppliers',sid);self.app.update()
        for combo in (w for w in self.visit(win) if isinstance(w,ttk.Combobox)):
            self.assertTrue(all('supplierID' not in str(v) for v in combo['values']))

    def test_password_click_toggle_and_speech_never_reads_secret(self):
        var=tk.StringVar(value=' Secret123! ')
        field=password_entry(self.app,var,bg='white',fg='black');field.pack();self.app.update()
        field.reveal.invoke();self.app.update()
        self.assertEqual(field.entry.cget('show'),'')
        with patch.object(self.app.accessibility,'speak') as speak:self.app.accessibility.read_focus(field.entry)
        self.assertNotIn('Secret',speak.call_args.args[0])
        field.reveal.event_generate('<Leave>');self.app.update()
        self.assertEqual(field.entry.cget('show'),'')
        field.reveal.invoke();self.app.update()
        self.assertEqual(field.entry.cget('show'),'•');self.assertEqual(var.get(),' Secret123! ')

    def test_quick_action_navigation_reveals_payroll_on_small_screen(self):
        self.app.geometry('820x550');self.app.show_page('Dashboard');self.app.update()
        self.app.nav_canvas.yview_moveto(0)
        self.app.show_page('Payroll');self.app.update()
        target=self.app.nav_buttons['Payroll'];canvas=self.app.nav_canvas
        self.assertGreaterEqual(target.winfo_y(),canvas.canvasy(0)-1)
        self.assertLessEqual(target.winfo_y()+target.winfo_height(),canvas.canvasy(0)+canvas.winfo_height()+1)

    def test_accessibility_scale_is_saved_without_cumulative_growth(self):
        self.app.show_page('Inventory');self.app.update()
        original=tkfont.nametofont('ShopDropdownFont',root=self.app).actual('size')
        self.app.save_accessibility({'text_size':150,'contrast':'High Contrast','cursor':'Crosshair','reduced_motion':True,'narration':False})
        self.app.update();self.app.accessibility.apply();self.app.accessibility.apply()
        self.assertEqual(tkfont.nametofont('ShopDropdownFont',root=self.app).actual('size'),round(original*1.5))
        self.assertTrue(self.app.reduced_motion)
        self.app.show_auth();self.app.update()
        self.assertEqual(self.app.accessibility.options['text_size'],100)

    def test_forecast_tab_and_range_apply_when_generated(self):
        self.app.show_page('Trends');self.app.update()
        self.app.select_forecast('Financial')
        import desktop_app
        self.assertEqual(self.app.trend_buttons[1].cget('bg'),desktop_app.ACCENT)
        self.assertEqual(self.app.trend_buttons[0].cget('bg'),desktop_app.SECONDARY)
        self.app.trend_start.set('2026-11-20');self.app.trend_end.set('2026-11-18')
        with patch('desktop_app.messagebox.showerror') as error:self.app.generate_forecast()
        self.assertIn('start date',error.call_args.args[1])

    def test_form_choice_display_keeps_service_value_and_quantity_focus(self):
        def drive(dialog):
            self.app.update()
            self.assertEqual(dialog.controls['mode'].get(),'Add')
            self.assertEqual(dialog._vars['mode'].get(),'add')
            self.assertEqual(dialog.focus_lastfor(),dialog.controls['qty'])
            self.assertLessEqual(abs(dialog.controls['qty'].winfo_height()-dialog.controls['mode'].winfo_height()),1)
            dialog.destroy()
        with patch.object(self.app,'wait_window',side_effect=drive):
            InputDialog(self.app,'Stock',[('mode','Action','add','choice',['add','remove']),('qty','Quantity','','text')],focus='qty')
