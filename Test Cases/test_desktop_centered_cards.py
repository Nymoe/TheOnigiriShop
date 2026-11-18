"""Regression checks: centered dashboard/summary cards; table alignment unaffected."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc

from desktop_app import OnigiriDesktop
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(), 'Requires a working graphical display')
class CenteredCardsGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.app = OnigiriDesktop(Path(self.temp.name) / 'test.db')
        self.app.svc.create_user('Test Owner', 'owner', 'TestOwnerPass123!', 'Owner')
        self.app.user = self.app.svc.login('owner', 'TestOwnerPass123!')
        self.app.set_fullscreen(False)
        self.app.geometry('1250x780')
        self.app.update()

    def tearDown(self):
        if self.app.winfo_exists():
            self.app.destroy()
        self.temp.cleanup()

    def _metrics(self, title):
        for row in self.app.body.winfo_children():
            if not isinstance(row, tk.Frame):
                continue
            boxes = row.grid_slaves(row=0)
            for box in boxes:
                labels = [child for child in box.winfo_children()
                          if isinstance(child, tk.Label)]
                if labels and labels[0].cget('text') == title.upper():
                    return row, box, labels
        self.fail(f'Cannot find summary card {title}')

    def assert_centered_card(self, title):
        row, box, labels = self._metrics(title)
        self.assertEqual(box.winfo_manager(), 'grid')
        self.assertEqual(len(labels), 3)
        for label in labels:
            self.assertEqual(label.cget('anchor'), 'center')
            self.assertEqual(label.cget('justify'), 'center')
            self.assertGreaterEqual(int(label.cget('wraplength')), 75)
        return row, box

    def test_dashboard_metric_cards_centered_and_evenly_spaced(self):
        self.app.show_page('Dashboard')
        self.app.update()
        row, first = self.assert_centered_card('Ingredients')
        self.assert_centered_card('Orders')
        self.assert_centered_card('Low stock')
        boxes = sorted(row.grid_slaves(row=0), key=lambda b: int(b.grid_info()['column']))
        self.assertEqual(len(boxes), 3)
        widths = [box.winfo_width() for box in boxes]
        self.assertLessEqual(max(widths) - min(widths), 2)
        # The group uses the full panel and leaves balanced spacing on both sides.
        self.assertAlmostEqual(boxes[0].winfo_rootx() - row.winfo_rootx(),
                               row.winfo_rootx()+row.winfo_width() -
                               (boxes[-1].winfo_rootx()+boxes[-1].winfo_width()), delta=4)
        self.app.geometry('850x650')
        self.app.update()
        self.assert_centered_card('Ingredients')
        self.assert_centered_card('Orders')
        self.assert_centered_card('Low stock')

    def test_accounting_metric_cards_centered_tables_still_right_aligned(self):
        self.app.show_page('Accounting')
        self.app.update()
        for name in ('Revenue', 'Expenses', 'Balance'):
            self.assert_centered_card(name)
        self.assertEqual(self.app.data_tree.column('amount')['anchor'], 'center')
        self.assertEqual(self.app.data_tree.heading('amount')['anchor'], 'center')

    def test_quick_actions_and_trends_panel_heading_centered(self):
        self.app.show_page('Dashboard')
        self.app.update()
        quick_headers = [label for frame in self.app.body.winfo_children()
                         for label in frame.winfo_children()
                         if isinstance(label, tk.Label) and label.cget('text') == 'QUICK ACTIONS']
        self.assertEqual(len(quick_headers), 1)
        self.assertEqual(quick_headers[0].cget('anchor'), 'center')
        self.app.show_page('Trends')
        self.app.update()
        trend_labels = [label for frame in self.app.body.winfo_children()
                        for label in frame.winfo_children()
                        if isinstance(label, tk.Label) and
                        label.cget('text') == 'Predict sales, revenue and ingredient consumption']
        self.assertEqual(len(trend_labels), 1)
        self.assertEqual(trend_labels[0].cget('anchor'), 'center')


if __name__ == '__main__':
    unittest.main()
