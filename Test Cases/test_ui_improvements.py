"""Regression checks for desktop navigation and business workflows."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
try:
    import tkinter as tk
    from tkinter import ttk
except ImportError as exc:
    raise unittest.SkipTest('Tkinter required') from exc
from desktop_app import OnigiriDesktop
from desktop_widgets import AutoScrollbar, scroll_if_needed
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(), 'Display required')
class ImprovementsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.app=OnigiriDesktop(Path(self.tmp.name)/'shop.db')
        self.addCleanup(self.app.destroy)
        self.app.set_fullscreen(False)
        self.owner=self.app.svc.create_user('Owner Person','owner','owner-password','Owner')
        self.app.user=self.app.svc.login('owner','owner-password')
        self.app.geometry('1280x900')
        for name in ('showinfo','showerror','showwarning','askyesno'):
            p=patch('desktop_app.messagebox.'+name,return_value=True)
            setattr(self,name,p.start());self.addCleanup(p.stop)

    def test_sidebar_header_and_conditional_scrollbars(self):
        for theme in ('Classic','Sage','Ocean','Midnight'):
            self.app._use_theme(theme)
            self.app.show_page('Dashboard');self.app.update()
            button=self.app.nav_buttons['Dashboard']
            self.assertEqual(button.cget('anchor'),'w')
            self.assertEqual(button.pack_info()['padx'],0)
            self.assertNotIn('My profile',self.app.nav_buttons)
            self.assertIn('EST',self.app.clock_label.cget('text'))
        bar=AutoScrollbar(self.app,orient='vertical');bar.pack(side='right')
        bar.set('0','1');self.app.update()
        self.assertFalse(bar.winfo_ismapped())
        bar.set('0','.5');self.app.update()
        self.assertTrue(bar.winfo_ismapped())
        bar.set('0','1');self.app.update()
        self.assertFalse(bar.winfo_ismapped())
        canvas=tk.Canvas(self.app);canvas.configure(scrollregion=(0,0,100,100))
        canvas.pack();self.app.update();before=canvas.yview()
        scroll_if_needed(canvas,4)
        self.assertEqual(canvas.yview(),before)

    def test_complete_demo_repeat_safety_profit_and_reset_restore(self):
        from desktop_demo_service import load_complete_demo
        from inventory_db import connect
        from contextlib import closing
        result=load_complete_demo(self.app.svc,self.owner)
        self.assertTrue(Path(result['backup']).exists())
        self.assertGreater(self.app.accounting.calculateSummary().balance,0)
        with closing(connect(self.app.db_path)) as db:
            for table in ('User','Customer','Employee','Feedback','Payroll','PayrollEntry',
                          'LoyaltyAccount','LoyaltyTransaction','Redemption','Reward',
                          'Recipe','InventoryItem','Order','InventoryOrder','AccountingDiscrepancy',
                          'AccountingReconciliationLog','SupplierIngredient','InventoryAdjustment'):
                self.assertGreater(db.execute(f'SELECT count(*) FROM "{table}"').fetchone()[0],0,table)
        before=self.app.db_path.read_bytes()
        self.assertTrue(load_complete_demo(self.app.svc,self.owner)['already_loaded'])
        self.assertEqual(self.app.db_path.read_bytes(),before)

        with patch.object(self.app,'ask',return_value={'confirm':'RESET'}),patch.object(self.app,'_verify_owner',return_value=True):
            self.app.reset_gui(False)
        self.assertIsNone(self.app.user)
        self.assertFalse(self.app.svc.inventory())
        self.app.user=self.app.svc.login('owner','owner-password')
        from demo_tools import list_backups
        selected=next(p for p in list_backups(self.app.svc) if 'before_reset' in p.name)
        with patch.object(self.app,'ask',return_value={'confirm':'RESTORE','backup':selected.name}),patch.object(self.app,'_verify_owner',return_value=True):
            self.app.restore_gui()
        self.assertIsNone(self.app.user)
        self.assertTrue(self.app.svc.inventory())


    def test_equal_centered_columns_full_filter_contracts_and_est(self):
        from desktop_app import format_table_value,allocate_table_widths
        widths=allocate_table_widths([100,200,300],1200)
        self.assertLessEqual(max(widths)-min(widths),1)
        self.assertEqual(format_table_value('createdAt','2026-07-01T12:00:00Z'),'07-01-2026 07:00:00 EST')
        self.assertEqual(format_table_value('orderDate','2026-07-01'),'07-01-2026 00:00:00 EST')
        for page,expected in [('Alerts','Open'),('Orders','Pending'),('Purchase orders','Partially Received')]:
            self.app.show_page(page);self.app.update()
            self.app.table_controls['status'].set(expected)
            self.assertIn(expected.lower(),self.app.empty_label.cget('text'))
            for key in self.app.data_tree['columns']:
                self.assertEqual(str(self.app.data_tree.column(key,'anchor')),'center')
        self.app.show_page('Loyalty');self.app.update()
        self.assertEqual(format_table_value('isActive',1),'Yes')
        self.app.table_controls['status'].set('No')
        self.assertFalse(self.app.data_tree.get_children())
    def test_trends_embed_plot_and_history_without_popup(self):
        from inventory_service import InventoryService
        for day in ('2026-10-01','2026-10-02','2026-10-03'):
            if not self.app.svc.recipes():
                rice=self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
                rid=self.app.svc.add_recipe('Onigiri',5)
                self.app.svc.set_recipe_ingredient(rid,rice,1)
            with patch('inventory_service._today',return_value=day+'T12:00:00'),patch('inventory_service._date_today',return_value=day):
                oid=self.app.svc.create_customer_order({rid:1},self.owner)
                self.app.svc.complete_customer_order(oid,self.owner)
        self.app._use_theme('Midnight');self.app.show_page('Trends');self.app.update()
        before=self.app.db_path.read_bytes()
        self.app.trend_show('Sales');self.app.update()
        self.assertEqual(len(self.app.trend_figure.axes[0].lines),2)
        from appearance_preferences import THEMES
        surface=THEMES['Midnight']['SURFACE']
        self.assertEqual(self.app.trend_figure.canvas.get_tk_widget().cget('bg'),surface)
        self.assertEqual(ttk.Style(self.app).lookup('POS.Treeview','lightcolor'),surface)
        self.assertEqual(len(self.app.data_tree.get_children()),3)
        self.assertFalse(any(isinstance(c,tk.Toplevel) for c in self.app.winfo_children()))
        self.assertEqual(self.app.db_path.read_bytes(),before)

    def test_user_ids_resolve_distinct_subtypes_in_gui_and_cli(self):
        from user_identity_service import role_id
        from inventory_cli import ask_account_user_id
        uid=self.app.svc.create_user('Customer','customer','customer-password','Customer')
        cid=role_id(self.app.db_path,uid,'Customer')
        self.assertNotEqual(uid,cid)
        self.app.loyalty.enroll_existing_customer(uid,self.owner)
        with patch.object(self.app,'ask',return_value={'id':str(uid)}):
            self.app.view_customer_loyalty()
        self.assertIn('Customer',self.showinfo.call_args.args[1])
        with patch('inventory_cli.ask_id',return_value=uid):
            self.assertEqual(ask_account_user_id(self.app.svc,'User ID','Customer'),cid)
        with self.assertRaisesRegex(ValueError,'not a Customer'):
            role_id(self.app.db_path,self.owner,'Customer')

    def test_navigation_reuses_shell_and_feedback_badge_and_user_status(self):
        uid=self.app.svc.create_user('Customer','customer','customer-password','Customer')
        self.app.feedback.submit_feedback(uid,'Test feedback',5)
        self.app.show_page('Dashboard');self.app.update()
        shell=self.app.nav_buttons['Dashboard']
        self.assertIn('1 Awaiting',self.app.feedback_badge.cget('text'))
        self.app.show_page('Inventory');self.app.update()
        self.assertIs(self.app.nav_buttons['Dashboard'],shell)
        self.app.users.set_active(self.owner,uid,False)
        self.assertEqual(next(r for r in self.app.users.list_accounts(self.owner) if r['userID']==uid)['status'],'Inactive')

    def test_purchase_selectors_details_catalogue_costs_and_atomic_receipt(self):
        from desktop_details_service import DetailService
        rice=self.app.svc.add_ingredient('Rice','g',5,10,self.owner)
        supplier=self.app.svc.add_supplier('Supplier')
        DetailService(self.app.db_path).set_catalogue(self.owner,supplier,rice)
        with patch.object(self.app,'ask',side_effect=[{'supplier':f'{supplier}: Supplier','notes':'Test'},
            {'ingredient':f'{rice}: Rice','quantity':'20','cost':'2'}, {'ingredient':'Finish adding'}]):
            self.app.create_purchase()
        po=self.app.svc.purchase_orders()[0]['inventoryOrderID']
        summary,lines,invoices=DetailService(self.app.db_path).purchase(po)
        self.assertEqual(summary['estimatedCost'],40)
        self.assertEqual(summary['supplier'],'Supplier')
        self.assertEqual(DetailService(self.app.db_path).supplier(supplier)[0]['totalPOs'],1)
        self.assertEqual(self.app.svc.inventory()[0]['quantityOnHand'],5)
        with patch.object(self.app,'ask',side_effect=[{'order':f'{po}: Confirmed'},
            {str(rice):'5','amount':'10','reference':'INV'}]):
            self.app.receive_purchase()
        self.assertEqual(self.app.svc.inventory()[0]['quantityOnHand'],10)
        self.assertEqual(DetailService(self.app.db_path).purchase(po)[0]['recordedInvoices'],10)
        with patch.object(self.app,'ask',side_effect=[{'order':f'{po}: Partially Received'},
            {str(rice):'16','amount':'10','reference':'INV2'}]):
            self.app.receive_purchase()
        self.assertEqual(self.app.svc.inventory()[0]['quantityOnHand'],10)
        rid=self.app.svc.add_recipe('Rice ball',5);self.app.svc.set_recipe_ingredient(rid,rice,2)
        self.assertEqual(DetailService(self.app.db_path).recipe(rid)[1],5)
        window=self.app.open_record('Recipes',rid)
        self.assertTrue(window.winfo_exists())

    def test_accounting_single_window_selected_order_and_discrepancy(self):
        from inventory_db import transaction
        from accounting_service import AccountingTransaction
        iid=self.app.svc.add_ingredient('Rice','g',20,1,self.owner)
        rid=self.app.svc.add_recipe('Rice ball',5);self.app.svc.set_recipe_ingredient(rid,iid,1)
        oid=self.app.svc.create_customer_order({rid:1},self.owner)
        self.app.svc.complete_customer_order(oid,self.owner)
        with transaction(self.app.db_path) as db:db.execute("DELETE FROM AccountingTransaction WHERE sourceType='Order'")
        for amount in (5,6):self.app.accounting.addTransaction(AccountingTransaction(None,'Sale','2026-10-01','Sample','DUP',amount))
        self.app.show_page('Accounting')
        win,post=self.app.accounting_sync_orders()
        self.assertEqual(len([c for c in self.app.winfo_children() if isinstance(c,tk.Toplevel)]),1)
        def trees(parent):
            return [c for c in parent.winfo_children() if c.winfo_class()=='Treeview']+[t for c in parent.winfo_children() for t in trees(c)]
        tree=trees(win)[0];tree.selection_set(tree.get_children()[0]);post()
        self.assertFalse(self.app.accounting.pending_completed_orders())
        self.app.accounting.reconcile_with_report()
        win,resolve=self.app.accounting_discrepancies()
        tree=trees(win)[0];before=len(self.app.accounting.getDiscrepancies(status='Flagged'))
        tree.selection_set(tree.get_children()[0]);resolve()
        self.assertEqual(len(self.app.accounting.getDiscrepancies(status='Flagged')),before-1)

    def test_order_reward_supplier_and_purchase_detail_contents(self):
        from desktop_details_service import DetailService
        from desktop_demo_service import load_complete_demo
        load_complete_demo(self.app.svc,self.owner)
        details=DetailService(self.app.db_path)
        completed=next(r for r in self.app.svc.customer_orders() if r['status']=='Completed' and r['customerID'])
        summary,lines,loyalty,sales=details.order(completed['orderID'])
        self.assertTrue(lines);self.assertTrue(loyalty);self.assertTrue(sales)
        self.assertEqual(sales[0]['amount'],loyalty[0]['finalAmount'])
        reward=self.app.loyalty.rewards()[0]
        eligible=details.eligible_customers(reward['rewardID'])
        self.assertTrue(eligible)
        self.assertTrue(all(r['pointsBalance']>=reward['pointsCost'] for r in eligible))
        for kind,ident in [('Orders',completed['orderID']),('Loyalty',reward['rewardID']),
            ('Suppliers',self.app.svc.suppliers()[0]['supplierID']),('Purchase orders',self.app.svc.purchase_orders()[0]['inventoryOrderID'])]:
            self.assertTrue(self.app.open_record(kind,ident).winfo_exists())

    def test_demo_failure_rolls_back_and_factory_reset_requires_confirmation(self):
        from desktop_demo_service import load_complete_demo
        before=self.app.db_path.read_bytes()
        with patch('desktop_demo_service.populate_trend_history',side_effect=ValueError('Test failure')):
            with self.assertRaises(ValueError):load_complete_demo(self.app.svc,self.owner)
        self.assertEqual(self.app.db_path.read_bytes(),before)
        with patch.object(self.app,'ask',return_value={'confirm':'RESET'}),patch.object(self.app,'_verify_owner',return_value=False):
            self.app.reset_gui(True)
        self.assertEqual(self.app.db_path.read_bytes(),before)
        with patch.object(self.app,'ask',return_value={'confirm':'RESET'}),patch.object(self.app,'_verify_owner',return_value=True):
            self.app.reset_gui(True)
        self.assertFalse(self.app.svc.has_logins())
        self.assertTrue(list((self.app.db_path.parent/'backups').glob('*.db')))

    def test_complete_demo_preserves_existing_stock_and_employee_rates(self):
        from desktop_demo_service import load_complete_demo
        from sample_users import load_sample_users
        from user_identity_service import role_id
        iid=self.app.svc.add_ingredient('A first unrelated stock','kg',123,4,self.owner)
        load_sample_users(self.app.svc,self.owner)
        employee=next(r for r in self.app.svc.list_users() if r['username']=='emma.staff')
        eid=role_id(self.app.db_path,employee['userID'],'Employee')
        self.app.payroll.set_hourly_rate(self.owner,eid,24)
        load_complete_demo(self.app.svc,self.owner)
        self.assertEqual(next(r for r in self.app.svc.inventory() if r['ingredientID']==iid)['quantityOnHand'],123)
        self.assertEqual(next(r for r in self.app.svc.inventory() if r['ingredientID']==iid)['reorderLevel'],4)
        self.assertEqual(next(e for e in self.app.payroll.employees(self.owner) if e.employeeID==eid).hourlyRate,24)

    def test_page_switches_and_resizing_have_no_stale_callbacks(self):
        failures=[]
        self.app.report_callback_exception=lambda *args:failures.append(args)
        for geometry in ('1280x900','820x600','1600x1000'):
            self.app.geometry(geometry)
            for page in ('Settings','Inventory','Orders','Loyalty','Payroll','Accounting','Dashboard','Trends'):
                self.app.show_page(page);self.app.update()
        self.assertEqual(failures,[])

    def test_hover_feedback_scrollbar_grid_and_column_resize(self):
        for i in range(15):self.app.svc.add_ingredient(f'Ingredient {i}','g',10,1,self.owner)
        self.app.geometry('820x600');self.app.show_page('Inventory');self.app.update()
        button=self.app.nav_buttons['Inventory'];before=button.cget('bg')
        button.event_generate('<Enter>');self.app.update()
        self.assertNotEqual(button.cget('bg'),before)
        button.event_generate('<Leave>');self.app.update()
        self.assertEqual(button.cget('bg'),before)
        tree=self.app.data_tree
        self.assertEqual(tree.grid_info()['row'],0)
        bars=[w for w in tree.master.winfo_children() if isinstance(w,AutoScrollbar)]
        self.assertEqual(len(bars),2)
        self.assertEqual(sorted(b._grid_options['row'] for b in bars),[0,1])
        tree.column(tree['columns'][0],width=85)
        tree.event_generate('<ButtonRelease-1>');self.app.update()
        widths=[tree.column(k,'width') for k in tree['columns']]
        self.assertLessEqual(max(widths)-min(widths),1)
        self.assertGreaterEqual(sum(widths),tree.winfo_width()-6)



class PresentationHelperTests(unittest.TestCase):
    def test_readable_titles_and_new_palettes(self):
        from desktop_widgets import title_label
        from appearance_preferences import THEMES
        for raw,label in [('ingredientID','Ingredient ID'),('quantityOrdered','Quantity Ordered'),('accountingTransactionID','Accounting Transaction ID')]:
            self.assertEqual(title_label(raw),label)
        for name in ("McDonald's",'Starbucks','Tim Hortons'):
            self.assertEqual(set(THEMES[name]),set(THEMES['Classic']))
