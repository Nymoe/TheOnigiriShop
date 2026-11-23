"""UI layout and native interaction checks on disposable restaurant data."""
from pathlib import Path
import os
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import ttk,font as tkfont
import unittest
from unittest.mock import patch

from appearance_preferences import THEMES
import desktop_app
from desktop_app import OnigiriDesktop,action_button,InputDialog
from desktop_widgets import modern_checkbuttons,SmoothCombobox,darken_color,RoundedFrame
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(),'Display required')
class ImprovementsEightTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.app=OnigiriDesktop(Path(self.tmp.name)/'review.db')
        self.errors=[];self.app.report_callback_exception=lambda k,v,t:self.errors.append(str(v))
        self.app.svc.create_user('Review Owner','review','ReviewPassword123!','Owner')
        self.app.user=self.app.svc.login('review','ReviewPassword123!')
        self.app.set_fullscreen(False);self.app.geometry('1100x780')
        self.app.show_page('Settings');self.app.update()

    def tearDown(self):
        self.app.destroy();self.tmp.cleanup();self.assertEqual(self.errors,[])

    def visit(self,parent):
        yield parent
        for child in parent.winfo_children():yield from self.visit(child)

    def bounds(self,widget):
        return widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height()

    def test_confirmation_slots_never_move_login_or_page_content(self):
        for width in (1100,1700):
            self.app.geometry(f'{width}x850');self.app.update()
            before=self.bounds(self.app.page_canvas)
            self.app.show_success('Order completed. Receipt saved.',details=lambda:None,detail_label='View Receipt')
            self.app.update();host=self.app.notice_host;bar=self.app._notice_bar
            self.assertEqual(self.bounds(self.app.page_canvas),before)
            self.assertEqual(host.winfo_rootx(),self.app.clock_label.winfo_rootx())
            self.assertGreater(host.winfo_rooty(),self.app.clock_label.winfo_rooty()+self.app.clock_label.winfo_height())
            self.assertLessEqual(host.winfo_width(),420)
            self.assertLessEqual(bar.winfo_height()+4,host.winfo_height())
            self.app.clear_success();self.app.update()
            self.assertEqual(self.bounds(self.app.page_canvas),before)
        self.app.show_auth();self.app.update()
        title=next(w for w in self.visit(self.app) if isinstance(w,tk.Label) and w.cget('text')=='Welcome back')
        before=self.bounds(title)
        self.app.show_success('Accessibility options saved.');self.app.update()
        self.assertEqual(self.bounds(title),before)
        self.app.clear_success();self.app.update()
        self.assertEqual(self.bounds(title),before)
        self.assertTrue(self.app.notice_host.winfo_ismapped())

    def test_confirmation_fades_automatically_without_collapsing_its_slot(self):
        before=self.bounds(self.app.page_canvas)
        self.app.show_success('Saved successfully.');bar=self.app._notice_bar
        self.app.after(5500,self.app.quit);self.app.mainloop();self.app.update()
        self.assertEqual(self.app._success_message,'')
        self.assertFalse(bar.winfo_exists())
        self.assertTrue(self.app.notice_host.winfo_ismapped())
        self.assertEqual(self.bounds(self.app.page_canvas),before)

    def test_modern_checkboxes_scale_and_keep_native_variable_and_keyboard_behaviour(self):
        win=tk.Toplevel(self.app)
        value=tk.BooleanVar(value=False)
        box=ttk.Checkbutton(win,text='Reduce Animations',variable=value,style='Shop.TCheckbutton')
        box.pack(padx=15,pady=15)
        for theme,palette in THEMES.items():
            self.app._use_theme(theme);win.configure(bg=palette['SURFACE'])
            for scale in (1,1.5):
                modern_checkbuttons(self.app,palette,scale);self.app.update()
                element,off,on=self.app._check_images[(round(22*scale),palette['ENTRY'],palette['BORDER'],palette['ACCENT'])]
                self.assertTrue(off.transparency_get(0,0))
                self.assertTrue(on.transparency_get(0,0))
                self.assertLessEqual(abs(off.height()-tkfont.Font(font=ttk.Style(self.app).lookup('Shop.TCheckbutton','font')).metrics('linespace')),5)
                value.set(False);box.invoke();self.assertTrue(value.get())
                value.set(False);self.assertFalse(box.instate(['selected']))
        box.focus_force();self.app.update()
        box.event_generate('<KeyPress-space>');box.event_generate('<KeyRelease-space>');self.app.update()
        self.assertTrue(value.get())
        box.invoke();self.assertFalse(value.get())
        win.destroy()

    def test_popup_details_and_dropdown_join_remain_themed_during_repaints(self):
        iid=self.app.svc.add_ingredient('Rice','g',100,1,self.app.user['userID'])
        rid=self.app.svc.add_recipe('Onigiri',5);self.app.svc.set_recipe_ingredient(rid,iid,1)
        for theme,palette in THEMES.items():
            self.app._use_theme(theme)
            win=self.app.open_record('Recipes',rid);self.app.update()
            text=next(w for w in self.visit(win) if isinstance(w,tk.Text))
            self.assertEqual(text.cget('bg'),palette['SURFACE'])
            self.assertEqual(text.cget('fg'),palette['INK'])
            self.assertEqual(int(text.cget('bd')),0)
            notebook=next(w for w in self.visit(win) if isinstance(w,ttk.Notebook))
            notebook.select(1);self.app.update();notebook.select(0);self.app.update()
            self.assertIn('Shop.Tab',str(ttk.Style(self.app).layout('TNotebook.Tab')))
            combo=next(w for w in self.visit(win) if isinstance(w,SmoothCombobox))
            self.app.tk.call('ttk::combobox::Post',str(combo));self.app.update()
            joined=self.app._rounding._geometry[str(combo)][4]
            self.assertIn(joined,('top','bottom'))
            for value in (0,1,0):
                combo._fade_to(value);self.app._rounding.apply(combo);self.app.update()
                self.assertEqual(self.app._rounding._geometry[str(combo)][4],joined)
            self.app.tk.call('ttk::combobox::Unpost',str(combo));win.destroy();self.app.update()

    def test_table_header_focus_and_row_corners_follow_selection_and_scrolling(self):
        for theme,palette in THEMES.items():
            self.app._use_theme(theme)
            win=tk.Toplevel(self.app);win.geometry('900x950+80+60');win.configure(bg=palette['LIGHT'])
            tree=self.app.table([{'id':n,'value':f'Row {n}'} for n in range(30)],
                                [('id','ID'),('value','Value')],parent=win,height=4)
            self.app.update()
            first,second=tree.get_children()[:2]
            box=tree.bbox(second);tree.event_generate('<Motion>',x=20,y=box[1]+box[3]//2);self.app.update()
            self.assertEqual(tree._hover_row,second)
            self.assertEqual(sum(bool(w.winfo_manager()) for w in tree._aa_rows.values()),4)
            surface=tuple(v//257 for v in tree.winfo_rgb(palette['SURFACE']))
            for layer in tree._aa_rows.values():
                self.assertEqual(layer._corner_photo.get(0 if layer._row_geometry[2].endswith('w') else layer.winfo_width()-1,
                                                         0 if layer._row_geometry[2].startswith('n') else layer.winfo_height()-1),surface)
            tree.selection_set(first);tree.focus_force();self.app.update()
            self.assertEqual(tree._aa_edges['left'].cget('bg'),palette['ACCENT'])
            self.assertEqual(sum(bool(w.winfo_manager()) for w in tree._aa_rows.values()),8)
            self.assertGreater(len({tree._aa_corners['nw']._corner_photo.get(x,y) for x in range(6) for y in range(6)}),3)
            tree.yview_scroll(4,'units');self.app.update()
            self.assertEqual(tree._hover_row,tree.identify_row(tree._hover_y))
            tree.event_generate('<Leave>');tree.selection_remove(*tree.selection());self.app.update()
            self.assertFalse(any(w.winfo_manager() for w in tree._aa_rows.values()))
            win.destroy();self.app.update()

    def test_sidebar_hover_after_navigation_colours_the_entire_button(self):
        for theme,palette in THEMES.items():
            self.app._use_theme(theme);self.app.show_page('Dashboard');self.app.update()
            button=self.app.nav_buttons['Inventory']
            button.event_generate('<Enter>');self.app.update()
            self.app.show_page('Orders');self.app.update()
            button.event_generate('<Enter>');self.app.update()
            shade=darken_color(palette['DARK'])
            self.assertEqual(button.cget('bg'),shade)
            self.assertEqual(button.cget('activebackground'),shade)
            rgb=tuple(v//257 for v in button.winfo_rgb(shade))
            self.assertEqual(button._aa_corners['nw']._corner_photo.get(5,5),rgb)
            button.event_generate('<Leave>');self.app.update()
            self.assertEqual(button.cget('bg'),palette['DARK'])
            self.assertEqual(button.cget('activebackground'),palette['DARK'])

    @unittest.skipUnless(os.name=='nt','Native Windows paint verification')
    def test_button_corners_remain_visible_on_screen_after_press_and_release(self):
        import ctypes as c
        from ctypes import wintypes as w
        user=c.WinDLL('user32');gdi=c.WinDLL('gdi32')
        user.GetDC.argtypes=[w.HWND];user.GetDC.restype=w.HDC
        user.ReleaseDC.argtypes=[w.HWND,w.HDC]
        gdi.GetPixel.argtypes=[w.HDC,c.c_int,c.c_int];gdi.GetPixel.restype=w.DWORD
        def pixel(widget,x,y):
            dc=user.GetDC(None)
            try:return gdi.GetPixel(dc,widget.winfo_rootx()+x,widget.winfo_rooty()+y)
            finally:user.ReleaseDC(None,dc)
        for theme,palette in THEMES.items():
            self.app._use_theme(theme)
            win=tk.Toplevel(self.app);win.geometry('400x160+150+150');win.configure(bg=palette['SURFACE']);win.attributes('-topmost',True)
            called=[];button=action_button(win,'Save',lambda:called.append(True));button.pack(fill='x',padx=20,pady=20)
            self.app.update();button.event_generate('<Enter>');self.app.update()
            self.app.after(350,self.app.quit);self.app.mainloop()
            rgb=int(palette['SURFACE'][1:],16);outside=((rgb>>16)&255)|(rgb&0xff00)|((rgb&255)<<16)
            for sequence in ('<ButtonPress-1>','<ButtonRelease-1>'):
                button.event_generate(sequence,x=button.winfo_width()//2,y=button.winfo_height()//2);self.app.update()
                c.WinDLL('dwmapi').DwmFlush()
                self.assertEqual(pixel(button,0,0),outside,(theme,sequence))
                self.assertNotEqual(pixel(button,button.winfo_width()-20,button.winfo_height()//2),outside)
            self.assertEqual(called,[True])
            win.destroy();self.app.update()

    def test_dashboard_feedback_and_quick_actions_align_with_metric_cards(self):
        for width in (1100,1700):
            self.app.geometry(f'{width}x850');self.app.show_page('Dashboard');self.app.update()
            cards=[w for w in self.visit(self.app.body) if isinstance(w,RoundedFrame) and w.winfo_manager()=='grid' and w.master.master is self.app.body]
            cards.sort(key=lambda w:w.winfo_rootx())
            self.assertEqual(len(cards),3)
            panel=next(w for w in self.app.body.winfo_children() if isinstance(w,RoundedFrame))
            for widget in (panel,self.app.feedback_badge):
                self.assertEqual(widget.winfo_rootx(),cards[0].winfo_rootx())
                self.assertEqual(widget.winfo_rootx()+widget.winfo_width(),cards[-1].winfo_rootx()+cards[-1].winfo_width())

    def test_popup_fields_have_final_width_when_first_revealed(self):
        original=desktop_app.present_popup
        for size,count in ((100,3),(150,3),(100,12),(150,12)):
            self.app.accessibility.options['text_size']=size
            first={};final={}
            def present(window,parent):
                def finish():
                    if not window.winfo_exists():return
                    final.update({key:(w.winfo_rootx(),w.winfo_width()) for key,w in window.controls.items()})
                    window.destroy()
                def mapped(event):
                    if event.widget is window:self.assertEqual(float(window.attributes('-alpha')),0)
                window.bind('<Map>',mapped,add='+')
                original(window,parent)
                self.assertEqual(float(window.attributes('-alpha')),1)
                first.update({key:(w.winfo_rootx(),w.winfo_width()) for key,w in window.controls.items()})
                window.after(150,finish)
            fields=[('recipe','Recipe ID','','text'),('ingredient','Ingredient','','choice',['Rice','Tuna']),('password','Password','','password')]
            fields.extend((f'field{n}',f'Field {n}','','text') for n in range(count-3))
            with patch('desktop_app.present_popup',side_effect=present):InputDialog(self.app,'Assign recipe ingredient',fields)
            self.assertEqual(len(first),count)
            self.assertEqual(first,final,(size,count))
            self.assertGreater(final['recipe'][1],450)
