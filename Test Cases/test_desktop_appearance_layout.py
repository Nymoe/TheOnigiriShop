"""Desktop responsiveness, role identifiers and appearance persistence tests."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sqlite3
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc

from appearance_preferences import DEFAULT_THEME, THEMES, ThemePreferences
from desktop_app import (InputDialog, OnigiriDesktop, OrderComposer,
                         numeric_column, popup_dimensions)
from test_desktop_ui import gui_display_ready


class AppearanceDataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'testing.db'

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_user_and_guest_themes_are_independent_and_persisted(self):
        from inventory_service import InventoryService
        db = InventoryService(self.path)
        owner = db.create_user('Owner', 'owner', 'StrongOwnerPass123!', 'Owner')
        employee = db.create_user('Employee', 'employee', 'StrongStaffPass123!', 'Employee')
        prefs = ThemePreferences(self.path)
        self.assertEqual(prefs.get(), DEFAULT_THEME)
        prefs.set('Ocean')
        prefs.set('Midnight', owner)
        prefs.set('Sage', employee)
        again = ThemePreferences(self.path)
        self.assertEqual(again.get(), 'Ocean')
        self.assertEqual(again.get(owner), 'Midnight')
        self.assertEqual(again.get(employee), 'Sage')
        self.assertEqual(again.get(999999), DEFAULT_THEME)
        with self.assertRaises(ValueError):
            prefs.set('Nonexistent')

    def test_numeric_fields_end_align_but_non_numeric_center(self):
        rows=[{'employeeID':7,'name':'A','totalAmount':125.5,'status':'Active'},
              {'employeeID':10,'name':'B','totalAmount':2.5,'status':'Inactive'}]
        for key in ('employeeID','totalAmount'):
            self.assertTrue(numeric_column(key,rows))
        for key in ('name','status'):
            self.assertFalse(numeric_column(key,rows))

    def test_owner_lists_employee_id_not_customer_id(self):
        from inventory_service import InventoryService
        from user_management_service import UserManagementService
        db=InventoryService(self.path)
        owner=db.create_user('Owner','owner','StrongOwnerPass123!','Owner')
        employee=db.create_user('Employee','employee','StrongStaffPass123!','Employee')
        customer=db.create_user('Customer','customer','StrongCustomer123!','Customer')
        service=UserManagementService(self.path)
        accounts={row['userID']:row for row in service.list_accounts(owner)}
        self.assertIsNotNone(accounts[employee]['employeeID'])
        self.assertIsNone(accounts[customer]['employeeID'])
        self.assertIsNone(accounts[owner]['employeeID'])
        self.assertEqual(service.get_account(owner,employee)['employeeID'],accounts[employee]['employeeID'])
        self.assertIsNone(service.get_account(owner,customer)['employeeID'])
        # The existing Customer ID remains available to loyalty/order services.
        from inventory_db import connect
        database = connect(self.path)
        try:
            actual = database.execute('SELECT customerID FROM Customer WHERE userID=?',
                                      (customer,)).fetchone()
            self.assertIsNotNone(actual['customerID'])
        finally:
            database.close()


@unittest.skipUnless(gui_display_ready(), 'Requires a usable graphical display')
class AppearanceGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.path=Path(self.tmp.name)/'test.db'
        self.app=OnigiriDesktop(self.path)
        self.owner=self.app.svc.create_user('Demo Owner','owner','StrongOwnerPass123!','Owner')
        self.employee=self.app.svc.create_user('Demo Employee','employee','StrongStaffPass123!','Employee')
        self.app.user=self.app.svc.login('owner','StrongOwnerPass123!')
        self.app.set_fullscreen(False)
        self.app.geometry('820x600')
        self.app.update()

    def tearDown(self):
        if self.app.winfo_exists():self.app.destroy()
        self.tmp.cleanup()

    def test_theme_switch_applies_and_remembers_per_user(self):
        self.app.show_page('Settings')
        self.app.choose_theme('Midnight')
        self.app.update()
        self.assertEqual(self.app.theme_name,'Midnight')
        self.assertEqual(self.app.appearance.get(self.owner),'Midnight')
        self.assertEqual(self.app.cget('bg'),THEMES['Midnight']['LIGHT'])
        self.assertIn('Settings',self.app.allowed_pages())
        self.app.show_auth()
        self.assertEqual(self.app.theme_name,DEFAULT_THEME)

    def test_colour_scheme_only_in_settings_not_welcome_or_login(self):
        def texts(parent):
            found = []
            for child in parent.winfo_children():
                if isinstance(child, (tk.Label, tk.Button)):
                    found.append(str(child.cget('text')))
                found.extend(texts(child))
            return found

        self.app.show_auth()
        self.app.update()
        start_text = ' '.join(texts(self.app))
        self.assertNotIn('Colour Scheme', start_text)
        self.assertFalse(hasattr(self.app, 'login_theme'))
        self.assertEqual(self.app.theme_name, DEFAULT_THEME)
        self.assertNotIn('Settings', start_text)

        self.app.show_page('Settings')  # Not signed in: must stay on welcome screen.
        self.assertIsNone(self.app.user)
        with self.assertRaisesRegex(ValueError, 'Sign in'):
            self.app.choose_theme('Ocean')

        self.app.user = self.app.svc.login('owner','StrongOwnerPass123!')
        self.app.show_page('Settings')
        self.app.update()
        page_text = ' '.join(texts(self.app))
        self.assertIn('Select your colour scheme', page_text)
        self.assertIn('Save Colour Scheme', page_text)
        self.assertIn('Settings', self.app.allowed_pages())
        self.assertIn('Settings', [child.cget('text') for child in self.app.winfo_children()[0].winfo_children()[0].winfo_children() if isinstance(child, tk.Button)])
        self.app.choose_theme('Sage')
        self.assertEqual(self.app.appearance.get(self.owner), 'Sage')
        self.app.show_auth()
        self.assertEqual(self.app.theme_name, DEFAULT_THEME)
        self.assertNotIn('Colour Scheme', ' '.join(texts(self.app)))

    def test_user_list_has_employee_id_not_customer_id_and_columns_end_aligned(self):
        self.app.show_page('Users')
        self.app.update()
        tree=self.app.data_tree
        self.assertIn('employeeID',tree['columns'])
        self.assertNotIn('customerID',tree['columns'])
        self.assertEqual(tree.column('employeeID')['anchor'],'center')
        self.assertEqual(tree.column('name')['anchor'],'center')
        self.assertEqual(tree.heading('employeeID')['anchor'],'center')

    def test_popup_form_fits_display_and_save_cancel_visible(self):
        checks=[]
        fields=[(f'f{i}',f'Demo field number {i}','','text') for i in range(9)]
        def inspect():
            windows=[w for w in self.app.winfo_children() if isinstance(w,InputDialog)]
            if not windows:
                self.app.after(20,inspect)
                return
            dlg=windows[0]
            dlg.update_idletasks()
            all_buttons=[]
            def collect(parent):
                for child in parent.winfo_children():
                    if isinstance(child,tk.Button):all_buttons.append(child)
                    collect(child)
            collect(dlg)
            checks.append((dlg.winfo_rootx(),dlg.winfo_rooty(),dlg.winfo_width(),dlg.winfo_height(),
                           dlg.winfo_screenwidth(),dlg.winfo_screenheight(),
                           [(b.cget('text'),b.winfo_rooty()+b.winfo_height()) for b in all_buttons]))
            dlg.destroy()
        self.app.after(60,inspect)
        result=self.app.ask('Long editable profile',fields,'All the fields should be reachable.')
        self.assertIsNone(result)
        x,y,w,h,sw,sh,buttons=checks[0]
        self.assertGreaterEqual(x,0)
        self.assertGreaterEqual(y,0)
        self.assertLessEqual(x+w,sw)
        self.assertLessEqual(y+h,sh)
        self.assertTrue({'Cancel','Save'} <= {b[0] for b in buttons})
        self.assertTrue(all(bottom<=sh for _,bottom in buttons))

    def test_order_composer_buttons_fit_display(self):
        checks=[]
        def inspect():
            wins=[w for w in self.app.winfo_children() if isinstance(w,OrderComposer)]
            if not wins:
                self.app.after(20,inspect)
                return
            dlg=wins[0]
            dlg.update_idletasks()
            buttons=[]
            def collect(p):
                for child in p.winfo_children():
                    if isinstance(child,tk.Button):buttons.append(child)
                    collect(child)
            collect(dlg)
            checks.append((dlg.winfo_height(),dlg.winfo_screenheight(),
                [(b.cget('text'),b.winfo_rooty()+b.winfo_height()) for b in buttons]))
            dlg.destroy()
        self.app.after(60,inspect)
        OrderComposer(self.app,[{'recipeID':1,'name':'Onigiri','price':4}])
        h,sh,buttons=checks[0]
        self.assertTrue({'Cancel','Create Order'} <= {b[0] for b in buttons})
        self.assertTrue(all(y<=sh for _,y in buttons))


if __name__=='__main__':
    unittest.main()
