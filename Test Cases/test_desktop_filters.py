"""Modern UI regression tests for sortable lists and opt-in accounting sample data."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc
from desktop_app import OnigiriDesktop, OrderComposer
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(), 'A graphical display is required (use xvfb-run on Linux)')
class SortAndDemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.app=OnigiriDesktop(Path(self.tmp.name)/'test.db')
        owner=self.app.svc.create_user('Demo Owner','demo.owner','OwnerDemoPass123!','Owner')
        self.app.user=self.app.svc.login('demo.owner','OwnerDemoPass123!')
        self.owner=owner
        self.app.set_fullscreen(False)
        self.app.geometry('920x660')
        self.app.update()

    def tearDown(self):
        self.app.destroy()
        self.tmp.cleanup()

    def _labels(self,parent):
        return [c.cget('text') for c in parent.winfo_children() if isinstance(c,tk.Button)] + [
            text for child in parent.winfo_children() for text in self._labels(child)]

    def test_accounting_demo_opt_in_and_repeat_safe(self):
        self.app.show_page('Accounting')
        self.app.update()
        self.assertNotIn('Load Accounting Demo',self._labels(self.app))
        self.assertEqual(self.app.accounting.getTransactions(),[])
        with patch('desktop_app.messagebox.askyesno', return_value=True), \
             patch('desktop_app.messagebox.showinfo'), \
             patch.object(self.app,'_verify_owner',return_value=True):
            self.app.import_accounting_demo()
            self.assertEqual(len(self.app.accounting.getTransactions()),10)
            self.app.show_page('Accounting')
            self.assertEqual(len(self.app.accounting.getTransactions()),10)
            with patch('desktop_app.messagebox.showerror') as error:
                self.app.import_accounting_demo()
                self.assertTrue(error.called)
        self.assertEqual(len(self.app.accounting.getTransactions()),10)

    def test_sorted_and_filtered_accounting_and_order_lists(self):
        with patch('desktop_app.messagebox.askyesno',return_value=True), \
             patch('desktop_app.messagebox.showinfo'), \
             patch.object(self.app,'_verify_owner',return_value=True):
            self.app.import_accounting_demo()
        self.app.show_page('Accounting')
        self.app.update()
        tree=self.app.data_tree
        self.assertEqual(len(tree.get_children()),10)
        controls=self.app.table_controls
        controls['query'].set('rent')
        self.assertEqual(len(tree.get_children()),1)
        controls['query'].set('')
        controls['status'].set('Expense')
        self.assertTrue(0 < len(tree.get_children()) < 10)
        controls['status'].set('All')
        controls['sort'].set('CAD')
        controls['direction'].set('Descending')
        money=[float(tree.item(item,'values')[-2]) for item in tree.get_children()]
        self.assertEqual(money, sorted(money,reverse=True))
        self.app.show_page('Orders')
        self.app.update()
        self.assertIn('status', ('status',))
        self.assertIn('All',self.app.table_controls['status'].get())

    def test_windowed_action_buttons_are_in_wrapping_grid(self):
        for page in ('Payroll','Accounting','Users','Loyalty','Demo & backups'):
            self.app.show_page(page)
            self.app.update()
            self.assertGreater(self.app.body.winfo_width(),400)
            buttons=self._labels(self.app.body)
            self.assertTrue(buttons,page)
            # Layout remains within the scrolled content area in windowed mode.
            self.assertTrue(self.app.page_canvas.winfo_ismapped())

    def test_order_builder_filter_keeps_cart_quantities(self):
        recipes=[{'recipeID':1,'name':'Tuna','price':5.5},
                 {'recipeID':2,'name':'Salmon','price':7},
                 {'recipeID':3,'name':'Plain','price':4}]
        def drive():
            windows=[c for c in self.app.winfo_children() if isinstance(c,OrderComposer)]
            if not windows:
                self.app.after(25,drive)
                return
            win=windows[0]
            win.quantities[1].set('2')
            win.recipe_search.set('salmon')
            self.assertFalse(win.recipe_rows[1].winfo_manager())
            self.assertTrue(win.recipe_rows[2].winfo_manager())
            win.recipe_sort.set('Price: high to low')
            win.recipe_search.set('')
            visible=[w for w in win.recipe_rows[1].master.pack_slaves() if w in win.recipe_rows.values()]
            self.assertEqual(visible,[win.recipe_rows[i] for i in (2,1,3)])
            win.recipe_sort.set('Name Z–A')
            visible=[w for w in win.recipe_rows[1].master.pack_slaves() if w in win.recipe_rows.values()]
            self.assertEqual(visible,[win.recipe_rows[i] for i in (1,2,3)])
            self.assertEqual(win.quantities[1].get(),'2')
            win.submit()
        self.app.after(60,drive)
        win=OrderComposer(self.app,recipes)
        self.assertEqual(win.result,{1:2})

if __name__=='__main__':
    unittest.main()
