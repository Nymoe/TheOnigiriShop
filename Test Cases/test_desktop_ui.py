"""Optional end-to-end Tkinter checks (run using a display/Xvfb on Linux)."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
try:
    import tkinter as tk
except ImportError as exc:
    raise unittest.SkipTest('Desktop tests require Tkinter.') from exc

from desktop_app import OnigiriDesktop, OrderComposer
from sample_users import load_sample_users


def gui_display_ready() -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except tk.TclError:
        return False


@unittest.skipUnless(gui_display_ready(),
                     'Usable graphical display required (e.g., xvfb-run -a python -m unittest test_desktop_ui)')
class DesktopSmokeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.app=OnigiriDesktop(Path(self.tmp.name)/'test.db')
        self.app.update()

    def _app_alive(self):
        try:
            return bool(self.app.winfo_exists())
        except tk.TclError:
            return False  # Tcl interpreter has already shut down after Exit.

    def tearDown(self):
        if self._app_alive():
            self.app.destroy()
        self.tmp.cleanup()

    def _button(self, parent, text):
        for child in parent.winfo_children():
            if isinstance(child, tk.Button) and child.cget('text') == text:
                return child
            found = self._button(child, text)
            if found is not None:
                return found
        return None

    def test_fullscreen_launch_f11_and_escape(self):
        self.assertTrue(self.app.fullscreen)
        self.app.toggle_fullscreen()
        self.assertFalse(self.app.fullscreen)

        self.app.toggle_fullscreen()
        self.assertTrue(self.app.fullscreen)
        self.app.leave_fullscreen()
        self.assertFalse(self.app.fullscreen)

    @unittest.skipUnless(os.name == 'nt', 'Windows window icons')
    def test_main_window_has_explicit_small_and_large_icons(self):
        import ctypes
        from ctypes import wintypes
        api=ctypes.WinDLL('user32')
        api.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
        api.GetAncestor.restype=wintypes.HWND
        api.SendMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        api.SendMessageW.restype=wintypes.LPARAM
        hwnd=api.GetAncestor(self.app.winfo_id(),2)
        for icon_type in (0,1):
            self.assertNotEqual(api.SendMessageW(hwnd,0x007F,icon_type,0),0,
                                'The main window must own its taskbar/titlebar icons.')

    @unittest.skipUnless(os.name == 'nt', 'Windows window icons')
    def test_native_icons_use_full_resolution_images_after_fullscreen_changes(self):
        import ctypes as c
        from ctypes import wintypes as w
        from desktop_app import resource
        api = self.app._window_icons.api
        gdi = c.WinDLL('gdi32')

        class IconInfo(c.Structure):
            _fields_ = [('icon', w.BOOL), ('x', w.DWORD), ('y', w.DWORD),
                        ('mask', w.HBITMAP), ('color', w.HBITMAP)]

        class Bitmap(c.Structure):
            _fields_ = [('type', w.LONG), ('width', w.LONG), ('height', w.LONG),
                        ('stride', w.LONG), ('planes', w.WORD), ('bits', w.WORD),
                        ('data', c.c_void_p)]

        api.GetIconInfo.argtypes = [w.HANDLE, c.POINTER(IconInfo)]
        gdi.GetObjectW.argtypes = [w.HANDLE, c.c_int, c.c_void_p]
        gdi.GetBitmapBits.argtypes = [w.HBITMAP, w.LONG, c.c_void_p]
        gdi.DeleteObject.argtypes = [w.HANDLE]

        def pixels(handle):
            info = IconInfo()
            self.assertTrue(api.GetIconInfo(handle, c.byref(info)))
            try:
                bitmap = Bitmap()
                self.assertTrue(gdi.GetObjectW(info.color, c.sizeof(bitmap), c.byref(bitmap)))
                data = c.create_string_buffer(bitmap.stride * bitmap.height)
                self.assertEqual(gdi.GetBitmapBits(info.color, len(data), data), len(data))
                return bitmap.width, bitmap.height, data.raw
            finally:
                gdi.DeleteObject(info.mask)
                gdi.DeleteObject(info.color)

        for fullscreen in (True, False, True):
            self.app.set_fullscreen(fullscreen)
            self.app.update()
            hwnd = api.GetAncestor(self.app.winfo_id(), 2)
            for kind, metric in ((0, 49), (1, 11)):
                width, height = api.GetSystemMetrics(metric), api.GetSystemMetrics(metric + 1)
                reference = api.LoadImageW(None, str(resource('onigiri.ico')),
                                           1, width, height, 0x10)
                self.assertTrue(reference)
                try:
                    actual = api.SendMessageW(hwnd, 0x007F, kind, 0)
                    self.assertEqual(pixels(actual), pixels(reference))
                finally:
                    api.DestroyIcon(reference)

    @unittest.skipUnless(os.name == 'nt', 'Windows window icons')
    def test_native_icons_release_handles_and_cancel_pending_work_on_destroy(self):
        icons = self.app._window_icons
        self.assertTrue(icons.handles)
        icons._schedule()
        self.assertIsNotNone(icons.pending)
        self.app.destroy()
        self.assertIsNone(icons.pending)
        self.assertEqual(icons.handles, {})

    def test_exit_button_on_initial_setup(self):
        self.assertFalse(self.app.svc.has_logins())
        exit_button = self._button(self.app, 'Exit Application')
        self.assertIsNotNone(exit_button)
        exit_button.invoke()
        self.assertFalse(self._app_alive())

    def test_exit_button_on_login_screen_and_logged_in_header(self):
        self.app.svc.create_user('Test Owner', 'test.owner', 'OwnerDemo987!', 'Owner')
        self.app.show_auth()
        self.app.update()
        self.assertIsNotNone(self._button(self.app, 'Exit Application'))
        self.app.user = self.app.svc.login('test.owner', 'OwnerDemo987!')
        self.app.show_page('Dashboard')
        self.app.update()
        exit_button = self._button(self.app, 'Exit')
        self.assertIsNotNone(exit_button)
        exit_button.invoke()
        self.assertFalse(self._app_alive())

    def test_owner_first_time_then_all_pages_render(self):
        self.assertFalse(self.app.svc.has_logins())
        self.assertEqual(self.app.svc.list_users(),[])
        owner=self.app.svc.create_user('Test Owner','test.owner','OwnerDemo987!','Owner')
        self.app.user=self.app.svc.login('test.owner','OwnerDemo987!')
        self.app.svc.load_demo_data(owner)
        for page in self.app.allowed_pages():
            self.app.show_page(page)
            self.app.update()
            self.assertEqual(self.app.current_page,page)
        self.assertEqual(len(self.app.svc.list_users()),1)

    def test_role_based_new_modules_and_persistent_data(self):
        owner=self.app.svc.create_user('Owner','new.owner','TestOwnerPassword!','Owner')
        employee=self.app.svc.create_user('Employee','new.employee','TestStaffPassword!','Employee')
        customer=self.app.svc.create_user('Customer','new.customer','TestCustomerPassword!','Customer')
        for uid, role, allowed, denied in [
            (owner, 'Owner', {'Accounting','Payroll','Feedback','Trends'}, set()),
            (employee, 'Employee', {'Feedback','Trends'}, {'Accounting','Payroll','Users'}),
            (customer, 'Customer', {'Feedback','Loyalty','My profile'}, {'Trends','Payroll','Accounting'}),
        ]:
            self.app.user={'userID':uid,'role':role}
            pages=set(self.app.allowed_pages())
            self.assertTrue(allowed <= pages)
            self.assertFalse(denied & pages)
            for page in allowed:
                self.app.show_page(page)
                self.app.update()
                self.assertEqual(self.app.current_page,page)
        self.app.feedback.submit_feedback(customer, 'Great onigiri!', 5)
        self.assertEqual(self.app.feedback.view_feedback(owner)[0].feedbackText, 'Great onigiri!')
        self.assertEqual(self.app.accounting.getTransactions(),[])
        self.assertEqual(self.app.payroll.payrolls(owner),[])

    def test_order_composer_graphical_cart(self):
        sample=[{'recipeID':11,'name':'Salmon Onigiri','price':5.0},
                {'recipeID':12,'name':'Veggie Onigiri','price':4.5}]
        def place_order():
            dialogs=[c for c in self.app.winfo_children() if isinstance(c,OrderComposer)]
            if not dialogs:
                self.app.after(30,place_order)
                return
            dlg=dialogs[0]
            dlg.quantities[11].set('2')
            dlg.quantities[12].set('1')
            dlg.submit()
        self.app.after(80,place_order)
        dlg=OrderComposer(self.app,sample)
        self.assertEqual(dlg.result,{11:2,12:1})

    def test_import_customer_profile_loyalty_and_role_views(self):
        owner=self.app.svc.create_user('Test Owner','test.owner','OwnerDemo987!','Owner')
        self.app.user=self.app.svc.login('test.owner','OwnerDemo987!')
        result=load_sample_users(self.app.svc,owner)
        self.assertEqual(result['created'],8)
        self.assertEqual(load_sample_users(self.app.svc,owner)['created'],0)
        self.app.user=self.app.svc.login('maya.customer','CustomerDemo!2026')
        for page in self.app.allowed_pages():
            self.app.show_page(page)
            self.app.update()
        original=self.app.profile.view_profile(self.app.user['userID'])
        changes={'name':'New Maya Name','email':'maya.new@example.test',
                 'phoneNumber':'514-555-0456','dateOfBirth':'2002-01-01'}
        with patch.object(self.app,'ask',return_value=changes), \
             patch('desktop_app.messagebox.askyesno',return_value=True), \
             patch('desktop_app.messagebox.showinfo'):
            self.app.edit_profile(original)
        updated=self.app.profile.view_profile(self.app.user['userID'])
        self.assertEqual(updated.email,'maya.new@example.test')
        self.assertEqual(updated.name,'New Maya Name')
        customer_id=self.app.loyalty.customer_id_for_user(self.app.user['userID'])
        self.app.loyalty.enroll_existing_customer(self.app.user['userID'],self.app.user['userID'])
        self.app.show_page('Loyalty')
        self.assertEqual(self.app.loyalty.retrieve_customer_account(customer_id)['pointsBalance'],0)
        rewards=self.app.loyalty.rewards()
        self.assertEqual(rewards[0]['pointsCost'],1000)
        self.assertEqual(load_sample_users(self.app.svc,owner)['created'],0)
        self.assertEqual(self.app.profile.view_profile(self.app.user['userID']).email,'maya.new@example.test')


if __name__=='__main__':
    unittest.main()
