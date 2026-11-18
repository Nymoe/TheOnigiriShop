"""Regression tests for full-width table headers and consistent value alignment."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc
from tkinter import ttk

from desktop_app import OnigiriDesktop, allocate_table_widths, format_table_value
from test_desktop_ui import gui_display_ready


class TableWidthMathTests(unittest.TestCase):
    def test_money_columns_have_two_decimal_places_without_changing_ids_or_points(self):
        self.assertEqual(format_table_value('amount', 34.5), '34.50')
        self.assertEqual(format_table_value('totalAmount', 175), '175.00')
        self.assertEqual(format_table_value('pointsCost', 500), '500')
        self.assertEqual(format_table_value('customerID', 42), '42')

    def test_expands_into_all_available_space(self):
        widths = allocate_table_widths([95, 140, 100, 160], 1130)
        self.assertEqual(sum(widths), 1130)
        self.assertTrue(all(actual >= base for actual, base in zip(widths,[95,140,100,160])))
        self.assertGreater(widths[-1], 160)

    def test_preserves_minimum_width_for_horizontal_scrolling(self):
        self.assertEqual(allocate_table_widths([100, 150, 190], 280),[190,190,190])
        self.assertEqual(allocate_table_widths([], 1000),[])


@unittest.skipUnless(gui_display_ready(), 'Requires a graphical display (xvfb-run on Linux)')
class FullWidthTableGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.app=OnigiriDesktop(Path(self.tmp.name)/'test.db')
        self.app.svc.create_user('Owner','owner','OwnerDemoPass123!','Owner')
        self.app.user=self.app.svc.login('owner','OwnerDemoPass123!')
        self.app.set_fullscreen(False)
        self.app.geometry('1490x850')
        self.app.update()

    def tearDown(self):
        if self.app.winfo_exists():
            self.app.destroy()
        self.tmp.cleanup()

    def check_width_fills(self, tree):
        self.app.update()
        available=tree.winfo_width()
        actual=sum(tree.column(k,'width') for k in tree['columns'])
        self.assertGreaterEqual(actual, available-9,
                                f'Table ends before panel edge: {actual} / {available}')
        return actual, available

    def test_accounting_fills_wide_window_and_reflows_after_resize(self):
        from accounting_service import AccountingTransaction
        self.app.accounting.addTransaction(AccountingTransaction(None,'Sale','2026-11-01',
                               'Restaurant sale for several items','DEMO-001',125.75))
        self.app.show_page('Accounting')
        tree=self.app.data_tree
        wide_total,wide_view=self.check_width_fills(tree)
        self.assertGreater(wide_view,900)
        self.assertEqual(tree.heading('amount')['anchor'],'center')
        self.assertEqual(tree.column('amount')['anchor'],'center')
        self.assertEqual(tree.column('transactionID')['anchor'],'center')
        self.assertEqual(tree.column('description')['anchor'],'center')
        self.assertEqual(tree.item(tree.get_children()[0],'values')[5], '125.75')
        # Resizing the app shouldn't leave headings stranded in the middle.
        self.app.geometry('840x700')
        self.app.update()
        narrow_total,narrow_view=self.check_width_fills(tree)
        self.assertLess(narrow_view,wide_view)
        self.assertLess(narrow_total,wide_total)
        self.assertEqual(len(tree.get_children()),1)

    def test_shared_tables_all_fill_right_edge_and_keep_numeric_alignment(self):
        for page in ('Users','Orders','Inventory','Payroll','Loyalty','Purchase orders'):
            with self.subTest(page=page):
                self.app.show_page(page)
                tree=self.app.data_tree
                self.assertIsNotNone(tree)
                self.check_width_fills(tree)
                for key in tree['columns']:
                    self.assertEqual(tree.heading(key)['anchor'],'center')

    def test_details_dialog_table_uses_full_width(self):
        self.app._records_dialog('Sample Details',[
            {'entryID':1,'name':'First','amount':25.5,'description':'Sample description'},
            {'entryID':2,'name':'Second','amount':49.0,'description':'Another description'}])
        self.app.update()
        windows=[w for w in self.app.winfo_children() if isinstance(w,tk.Toplevel) and w.title()=='Sample Details']
        self.assertEqual(len(windows),1)
        dlg=windows[0]
        trees=[]
        def find_trees(parent):
            for child in parent.winfo_children():
                if isinstance(child,ttk.Treeview): trees.append(child)
                find_trees(child)
        find_trees(dlg)
        self.assertEqual(len(trees),1)
        self.check_width_fills(trees[0])
        self.assertEqual(trees[0].column('amount')['anchor'],'center')
        self.assertEqual(trees[0].heading('amount')['anchor'],'center')
        dlg.destroy()


if __name__=='__main__':
    unittest.main()
