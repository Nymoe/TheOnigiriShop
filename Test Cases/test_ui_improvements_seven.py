"""Desktop interaction regressions using disposable databases only."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter, sleep
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import patch

from appearance_preferences import THEMES
import desktop_app
from desktop_app import OnigiriDesktop, InputDialog
from desktop_widgets import password_entry
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(),'Display required')
class ImprovementsSevenTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.app=OnigiriDesktop(Path(self.tmp.name)/'review.db')
        self.errors=[]
        self.app.report_callback_exception=lambda k,v,t:self.errors.append(str(v))
        self.app.svc.create_user('Review Owner','review','ReviewPassword123!','Owner')
        self.app.user=self.app.svc.login('review','ReviewPassword123!')
        self.app.set_fullscreen(False);self.app.geometry('1000x750')
        self.app.show_page('Dashboard');self.app.update()

    def tearDown(self):
        self.app.destroy();self.tmp.cleanup()
        self.assertEqual(self.errors,[])

    def visit(self,parent):
        yield parent
        for child in parent.winfo_children():yield from self.visit(child)

    def test_password_eye_preserves_centre_and_toggles_with_keyboard(self):
        value=tk.StringVar(value=' Secret123! ')
        field=password_entry(self.app.body,value,bg=desktop_app.ENTRY,fg=desktop_app.INK)
        field.pack(fill='x');self.app.update()
        self.assertEqual(field.entry.winfo_width(),field.winfo_width())
        self.assertEqual(field.entry.cget('justify'),'center')
        field.reveal.invoke();field.reveal.event_generate('<Leave>');self.app.update()
        self.assertEqual(field.entry.cget('show'),'')
        with patch.object(self.app.accessibility,'speak') as speak:
            self.app.accessibility.read_focus(field.entry)
        self.assertNotIn('Secret',speak.call_args.args[0])
        field.reveal.focus_force();self.app.update()
        field.reveal.event_generate('<Return>');self.app.update()
        self.assertTrue(field.entry.cget('show'))
        self.assertEqual(value.get(),' Secret123! ')

    def test_ingredient_filter_only_appears_for_ingredient_forecast(self):
        self.app.svc.add_ingredient('Rice','g',100,1,self.app.user['userID'])
        self.app.show_page('Trends');self.app.update()
        for kind in ('Sales','Financial','Inventory','Sales','Inventory'):
            self.app.select_forecast(kind);self.app.update()
            self.assertEqual(bool(self.app.trend_ingredient_controls.winfo_ismapped()),kind=='Inventory')
            if kind=='Inventory':
                siblings=self.app.trend_generate_button.master.pack_slaves()
                self.assertLess(siblings.index(self.app.trend_ingredient_controls),siblings.index(self.app.trend_generate_button))

    def test_footer_spacing_icons_and_backup_colours_in_all_themes(self):
        for name,palette in THEMES.items():
            with self.subTest(theme=name):
                self.app._use_theme(name);self.app.show_page('Demo & backups');self.app.update()
                profile=self.app.footer_buttons['My profile']
                left=self.app.footer_buttons['Accessibility'];right=self.app.footer_buttons['Settings']
                self.assertEqual(left.winfo_width(),right.winfo_width())
                self.assertEqual(left.winfo_height(),profile.winfo_height())
                self.assertEqual(left.winfo_rooty(),right.winfo_rooty())
                self.assertEqual(left.winfo_rootx(),profile.winfo_rootx())
                self.assertEqual(right.winfo_rootx()+right.winfo_width(),profile.winfo_rootx()+profile.winfo_width())
                self.assertEqual(right.winfo_rootx()-left.winfo_rootx()-left.winfo_width(),10)
                self.assertEqual(left.winfo_rooty()-profile.winfo_rooty()-profile.winfo_height(),10)
                sidebar=profile.master
                self.assertEqual(sidebar.winfo_rooty()+sidebar.winfo_height()-left.winfo_rooty()-left.winfo_height(),10)
                for widget in (left,right):
                    self.assertTrue(widget.cget('image'));self.assertEqual(widget.cget('text'),'')
                    with patch.object(self.app.accessibility,'speak') as speak:self.app.accessibility.read_focus(widget)
                    self.assertEqual(speak.call_args.args[0],widget.accessible_name)
                buttons={w.cget('text'):w for w in self.visit(self.app.body) if isinstance(w,tk.Button)}
                self.assertEqual(buttons['Restore Backup'].cget('bg'),palette['SECONDARY'])
                self.assertEqual(buttons['Reset Business Data'].cget('bg'),palette['SECONDARY'])
                self.assertEqual(buttons['Factory Reset'].cget('bg'),palette['RED'])
                style=ttk.Style(self.app)
                for state in (('readonly',),('readonly','pressed'),('readonly','active')):
                    for option in ('background','fieldbackground','selectbackground'):
                        self.assertEqual(style.lookup('TCombobox',option,state),palette['ENTRY'])

    def test_footer_controls_open_accessibility_and_settings(self):
        with patch.object(self.app,'accessibility_dialog') as dialog:
            self.app._shell_signature=None;self.app.show_page('Dashboard');self.app.update()
            self.app.footer_buttons['Accessibility'].invoke();dialog.assert_called_once_with()
        self.app.footer_buttons['Settings'].invoke()
        self.app.after(300,self.app.quit);self.app.mainloop()
        self.assertEqual(self.app.current_page,'Settings')
        self.app.accessibility.options['text_size']=150;self.app.accessibility.apply();self.app.update()
        self.assertEqual(self.app.footer_buttons['Accessibility'].winfo_height(),self.app.footer_buttons['My profile'].winfo_height())

    def test_popup_first_map_uses_final_geometry_at_both_font_sizes(self):
        original=desktop_app.present_popup
        for size in (100,150):
            self.app.accessibility.options['text_size']=size
            mapped=[];final=[]
            def present(window,parent):
                window.bind('<Map>',lambda e:mapped.append(window.geometry()) if e.widget is window else None,add='+')
                original(window,parent)
                def finish():
                    final.append(window.geometry());window.destroy()
                window.after(70,finish)
            with patch('desktop_app.present_popup',side_effect=present):
                dialog=InputDialog(self.app,'Review form',[('name','Name','','text'),('secret','Password','','password')])
            self.assertIsNone(dialog.result)
            self.assertTrue(mapped);self.assertEqual(mapped[0],final[0])

    def test_navigation_animation_finishes_before_slow_page_query(self):
        measured=[]
        def slow_page():
            measured.append((self.app.nav_indicator.winfo_y(),self.app.nav_buttons['Accounting'].winfo_y()))
            sleep(.2)
        with patch.object(self.app,'page_accounting',side_effect=slow_page):
            started=perf_counter();self.app.navigate('Accounting')
            self.assertLess(perf_counter()-started,.15)
            self.assertEqual(self.app.current_page,'Dashboard')
            self.app.after(500,self.app.quit);self.app.mainloop()
        self.assertEqual(len(measured),1);self.assertEqual(*measured[0])
        self.app.navigate('Inventory');self.app.navigate('Orders')
        self.app.after(300,self.app.quit);self.app.mainloop()
        self.assertEqual(self.app.current_page,'Orders')

    @unittest.skipUnless(os.name=='nt','Windows accessibility tools')
    def test_windows_tools_use_shell_launch_and_handle_cancelled_consent(self):
        with patch('desktop_accessibility.os.startfile') as launch:
            for tool,file in (('Magnifier','Magnify.exe'),('Narrator','Narrator.exe'),('On-Screen Keyboard','osk.exe')):
                self.app.accessibility.open_tool(tool)
                self.assertEqual(Path(launch.call_args.args[0]).name,file)
                self.assertEqual(launch.call_args.args[1],'open')
        cancelled=OSError('Cancelled');cancelled.winerror=1223
        with patch('desktop_accessibility.os.startfile',side_effect=cancelled),patch('desktop_accessibility.messagebox.showinfo') as info:
            self.app.accessibility.open_tool('Narrator')
        self.assertIn('cancelled',info.call_args.args[1])
