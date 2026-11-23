"""Rounded native controls and inline confirmations preserve saved state and input."""
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from desktop_app import OnigiriDesktop, card, action_button
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(),'Display required')
class SurfaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=OnigiriDesktop(Path(self.tmp.name)/'shop.db');self.addCleanup(self.app.destroy)
        self.errors=[];self.app.report_callback_exception=lambda k,v,t:self.errors.append(v)
        self.addCleanup(lambda:self.assertEqual(self.errors,[]))
        self.owner=self.app.svc.create_user('Owner','owner','OwnerPassword123!','Owner')
        self.app.user=self.app.svc.login('owner','OwnerPassword123!')
        self.app.set_fullscreen(False);self.app.geometry('1000x700')
        self.app.show_page('Inventory');self.app.update()
        error=patch('desktop_app.messagebox.showerror',return_value=None)
        error.start();self.addCleanup(error.stop)

    def visit(self,parent):
        yield parent
        for child in parent.winfo_children():yield from self.visit(child)

    def test_committed_stock_change_has_inline_confirmation_after_refresh(self):
        # Exercise manual dismissal without racing the automatic expiry while
        # Windows paints/resizes the test window on a busy desktop.
        schedule=self.app.after
        timer=patch.object(self.app,'after',side_effect=lambda ms,fn=None,*args:schedule(60000 if ms==5000 else ms,fn,*args))
        timer.start();self.addCleanup(timer.stop)
        iid=self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
        data=dict(id=str(iid),mode='remove',qty='5',note='',amount='')
        with patch.object(self.app,'ask',return_value=data),patch('desktop_app.messagebox.showinfo') as info:
            self.app.adjust_stock();self.app.update()
        self.assertFalse(info.called)
        self.assertEqual(self.app.svc.inventory()[0]['quantityOnHand'],95)
        self.assertIn('Stock adjusted',self.app._success_message)
        self.assertTrue(self.app.notice_host.winfo_ismapped())
        labels=[w.cget('text') for w in self.visit(self.app.notice_host) if isinstance(w,tk.Label)]
        self.assertTrue(any('Stock adjusted' in text for text in labels))
        self.app.show_page('Inventory');self.app.update()
        self.assertIn('Stock adjusted',self.app._success_message)
        before=self.app.db_path.read_bytes()
        dismiss=next(w for w in self.visit(self.app.notice_host) if isinstance(w,tk.Button) and w.cget('text')=='Dismiss')
        dismiss.invoke();self.app.update()
        self.assertEqual(self.app._success_message,'')
        self.assertEqual(self.app.db_path.read_bytes(),before)

    def test_failed_save_clears_previous_success_and_keeps_error_dialog(self):
        iid=self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
        self.app.show_success('Earlier change saved.')
        data=dict(id=str(iid),mode='remove',qty='5',note='',amount='-2')
        before=self.app.db_path.read_bytes()
        with patch.object(self.app,'ask',return_value=data),patch('desktop_app.messagebox.showerror') as error,patch('desktop_app.messagebox.showinfo') as info:
            self.app.adjust_stock();self.app.update()
        self.assertTrue(error.called);self.assertFalse(info.called)
        self.assertEqual(self.app._success_message,'')
        self.assertEqual(self.app.db_path.read_bytes(),before)

    def test_preferences_report_saved_in_green_in_every_theme(self):
        from appearance_preferences import THEMES
        for theme in THEMES:
            with patch('desktop_app.messagebox.showinfo') as info:self.app.choose_theme(theme)
            self.app.update()
            self.assertFalse(info.called)
            self.assertEqual(self.app.appearance.get(self.owner),theme)
            self.assertEqual(self.app._success_message,'Colour scheme saved.')
            bar=self.app.notice_host.winfo_children()[0]
            self.assertIn(bar.cget('bg'),('#E8F5ED','#173D2A'))

    def test_reset_confirmation_is_visible_after_returning_to_login(self):
        self.app.svc.add_ingredient('Rice','g',100,1,self.owner)
        with patch.object(self.app,'ask',return_value={'confirm':'RESET'}),patch.object(self.app,'_verify_owner',return_value=True),patch('desktop_app.messagebox.showinfo') as info:
            self.app.reset_gui(False);self.app.update()
        self.assertFalse(info.called)
        self.assertIsNone(self.app.user)
        self.assertIn('Reset complete',self.app._success_message)
        self.assertEqual(self.app.svc.inventory(),[])
        self.assertTrue(self.app.notice_host.winfo_ismapped())
        self.assertTrue(list((Path(self.tmp.name)/'backups').glob('*.db')))

    def test_credentials_are_available_on_request_and_clear_on_logout(self):
        data=dict(name='Visitor',email='visitor@example.test',phone='',username='visitor',password='VisitorPassword123!')
        with patch.object(self.app,'ask',return_value=data),patch('desktop_app.messagebox.showinfo') as info:
            self.app.register_walkin();self.app.update()
        self.assertFalse(info.called)
        self.assertNotIn('VisitorPassword123!',self.app._success_message)
        with patch.object(self.app,'details_dialog') as details:self.app._success_details()
        self.assertIn('VisitorPassword123!',details.call_args.args[1])
        self.assertIsNone(self.app._success_details)
        self.assertEqual(self.app.svc.login('visitor','VisitorPassword123!')['role'],'Customer')
        self.app.show_auth();self.app.update()
        self.assertEqual(self.app._success_message,'')
        self.assertIsNone(self.app._success_details)

    def test_rounded_controls_keep_native_widgets_and_update_on_resize(self):
        panel=card(self.app.body)
        panel.bind('<Configure>',lambda e:None)
        panel.pack(fill='x')
        called=[];button=action_button(panel,'Save',lambda:called.append(True));button.pack(fill='x')
        entry=ttk.Entry(panel,style='Search.TEntry');entry.pack(fill='x')
        self.app.update()
        self.assertEqual(len(panel._surface_canvas.find_withtag('surface')),1)
        for width in (1000,820):
            self.app.geometry(f'{width}x700');self.app.update()
            for widget in (panel,button,entry):
                corner=widget._aa_corners['ne']
                self.assertEqual(corner.winfo_x()+corner.winfo_width(),widget.winfo_width())
                image=corner._corner_photo
                colours={image.get(x,y) for y in range(image.height()) for x in range(image.width())}
                self.assertGreater(len(colours),3,'Curves must contain blended edge pixels, not binary clipping.')
        self.assertIsInstance(button,tk.Button);self.assertIsInstance(entry,ttk.Entry)
        original=button.cget('bg')
        button.event_generate('<Enter>');self.app.update()
        hovered=button.cget('bg');self.assertNotEqual(hovered,original)
        button.event_generate('<Enter>');button.event_generate('<Leave>',detail='NotifyInferior');self.app.update()
        self.assertEqual(button.cget('bg'),hovered,'Crossing decorative corners must not darken or clear hover.')
        button.event_generate('<Leave>');self.app.update()
        self.assertEqual(button.cget('bg'),original)
        button.invoke();self.assertEqual(called,[True])
        entry.insert(0,'Keyboard input');self.assertEqual(entry.get(),'Keyboard input')
