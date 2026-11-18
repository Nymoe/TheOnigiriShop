"""Regression coverage for supplier selection, detail layout and batch payroll."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
import tkinter as tk
import os
from tkinter import ttk

from desktop_app import OnigiriDesktop, InputDialog, format_table_value
from desktop_details_service import DetailService
from payroll import PayrollError
from test_desktop_ui import gui_display_ready


@unittest.skipUnless(gui_display_ready(), 'Display required')
class ImprovementsThreeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.app=OnigiriDesktop(Path(self.tmp.name)/'shop.db')
        callback_errors=[]
        self.app.report_callback_exception=lambda kind,value,trace:callback_errors.append(value)
        self.addCleanup(lambda:self.assertEqual(callback_errors,[]))
        self.addCleanup(self.app.destroy)
        self.app.set_fullscreen(False)
        self.owner=self.app.svc.create_user('Owner','owner','OwnerPassword123!','Owner')
        self.app.user=self.app.svc.login('owner','OwnerPassword123!')
        self.app.geometry('1200x800')

    def test_supplier_choices_only_include_supplied_ingredients(self):
        svc=self.app.svc
        banana=svc.add_ingredient('Banana','g',20,5,self.owner)
        svc.add_ingredient('Rice','g',30,5,self.owner)
        sid=svc.add_supplier('Market','')
        DetailService(self.app.db_path).set_catalogue(self.owner,sid,banana)
        with patch.object(self.app,'ask',side_effect=[{'supplier':f'{sid}: Market','notes':''},None]) as ask:
            self.app.create_purchase()
        choices=ask.call_args_list[1].args[1][0][4]
        self.assertEqual(len(choices),2)
        self.assertIn('Banana |',choices[1]);self.assertNotIn('?',choices[1])

    def test_dates_use_requested_format_without_modifying_values(self):
        self.assertEqual(format_table_value('date','2026-11-16'),'11-16-2026 00:00:00 EST')
        self.assertEqual(format_table_value('createdAt','2026-11-16T12:30:00Z'),'11-16-2026 07:30:00 EST')
        self.assertEqual(format_table_value('date','not a date'),'not a date')

    def test_batch_payroll_rolls_back_and_saves_all_entries(self):
        ids=[]
        from user_identity_service import role_id
        for name in ('Zoe','Amy'):
            uid=self.app.svc.create_user(name,name.lower(),'EmployeePass123!','Employee')
            eid=role_id(self.app.db_path,uid,'Employee');ids.append(eid)
            self.app.payroll.set_hourly_rate(self.owner,eid,20)
        pid=self.app.payroll.open_payroll(self.owner,'2026-11-16')
        with self.assertRaises(PayrollError):
            self.app.payroll.enter_hours_batch(self.owner,pid,[(ids[0],8,0),(999999,8,0)])
        self.assertEqual(self.app.payroll.get_payroll(self.owner,pid).entries,[])
        self.app.payroll.enter_hours_batch(self.owner,pid,[(ids[0],8,0),(ids[1],7,1)])
        self.assertEqual(len(self.app.payroll.get_payroll(self.owner,pid).entries),2)
        with self.assertRaises(PayrollError):
            self.app.payroll.enter_hours_batch(self.owner,pid,[(ids[0],1,0),(ids[0],2,0)])
        self.assertEqual(self.app.payroll.get_payroll(self.owner,pid).entries[0].hoursWorked,8)

    def test_form_cursor_and_staging_do_not_commit_until_save(self):
        def interact(dialog):
            controls=[]
            def visit(widget):
                if isinstance(widget,tk.Entry):controls.append(widget)
                for child in widget.winfo_children():visit(child)
            visit(dialog)
            self.assertEqual(controls[0].index('insert'),len('Pre-filled'))
            dialog._vars['hours'].set('8');dialog._add_batch()
            self.assertIsNone(dialog.result)
            dialog._submit()
            self.assertEqual(len(dialog.result),1)
        with patch.object(self.app,'wait_window',side_effect=interact):
            InputDialog(self.app,'Hours',[('employee','Employee','Pre-filled','text'),
                ('hours','Hours','','text'),('overtime','Overtime','0','text')],batch=lambda row:None)

    def test_detail_footer_remains_fixed_across_tabs_and_completion_name(self):
        svc=self.app.svc
        iid=svc.add_ingredient('Rice','g',20,1,self.owner)
        rid=svc.add_recipe('Rice dish',5);svc.set_recipe_ingredient(rid,iid,1)
        oid=svc.create_customer_order({rid:1},self.owner);svc.complete_customer_order(oid,self.owner)
        self.assertEqual(DetailService(self.app.db_path).order(oid)[0]['completedBy'],'Owner')
        win=self.app.open_record('Orders',oid);self.app.update()
        footer=win.winfo_children()[0]
        notebook=next(c for c in win.winfo_children() if isinstance(c,ttk.Notebook))
        heights=[]
        for tab in notebook.tabs():
            notebook.select(tab);self.app.update();heights.append(footer.winfo_height())
        self.assertEqual(set(heights),{58})

    def test_trend_graph_scroll_toolbar_and_axis_label(self):
        from trend_prediction_service import BusinessData,TrendPrediction
        self.app.show_page('Trends')
        history=[{'date':f'2026-11-{day:02d}','value':day*10} for day in (1,2,3)]
        prediction=TrendPrediction(BusinessData('Financial',self.app.db_path))
        prediction.generate_prediction(history)
        self.assertTrue(self.app.show_trend_chart(history,prediction,title='Revenue',ylabel='Revenue (CAD)'))
        self.app.update()
        figure=self.app.trend_figure;figure.canvas.draw()
        bounds=figure.axes[0].yaxis.label.get_window_extent(figure.canvas.get_renderer())
        self.assertGreaterEqual(bounds.x0,0)
        self.assertLessEqual(bounds.x1,figure.bbox.width)
        children=self.app.trend_results.pack_slaves()
        graph=figure.canvas.get_tk_widget()
        toolbar=next(c for c in children if c.winfo_class()=='NavigationToolbar2Tk') if any(c.winfo_class()=='NavigationToolbar2Tk' for c in children) else figure.canvas.toolbar
        self.assertLess(children.index(toolbar),children.index(graph))
        before=self.app.page_canvas.yview()
        graph.event_generate('<MouseWheel>',delta=-120);self.app.update()
        self.assertGreater(self.app.page_canvas.yview()[0],before[0])

    def test_accounting_defaults_to_newest_and_navigation_finishes(self):
        self.app.show_page('Accounting');self.app.update()
        self.assertEqual(self.app.table_controls['sort'].get(),'Date')
        self.assertEqual(self.app.table_controls['direction'].get(),'Descending')
        self.app.show_page('Inventory')
        self.app.after(220,self.app.quit);self.app.mainloop()
        self.assertEqual(self.app.nav_indicator.winfo_y(),self.app.nav_buttons['Inventory'].winfo_y())
        self.assertEqual(self.app.nav_indicator.winfo_width(),self.app.nav_buttons['Inventory'].winfo_width())
        self.assertEqual(self.app.nav_highlight.itemcget(self.app.nav_text_ids['Inventory'],'text'),'Inventory')

    def test_highlight_reveals_stationary_bold_labels_in_both_directions(self):
        from tkinter import font
        from types import SimpleNamespace
        self.app.show_page('Dashboard');self.app.update()
        first=self.app.nav_buttons['Dashboard'];last=self.app.nav_buttons['Inventory']
        start,end=first.winfo_y(),last.winfo_y()
        for top in (start,(start+end)//2,end,(start+end)//2,start):
            self.app._position_nav_highlight(top,first.winfo_height());self.app.update_idletasks()
            for name,button in self.app.nav_buttons.items():
                item=self.app.nav_text_ids[name]
                x,y=self.app.nav_highlight.coords(item)
                self.assertEqual(x,17)
                self.assertEqual(y+top,button.winfo_y()+button.winfo_height()/2)
                self.assertEqual(font.Font(font=button.cget('font')).actual('weight'),'normal')
                self.assertEqual(font.Font(font=self.app.nav_highlight.itemcget(item,'font')).actual('weight'),'bold')
        self.app._position_nav_highlight(end,last.winfo_height());self.app.update_idletasks()
        with patch.object(self.app,'show_page') as navigate:
            self.app._click_nav_highlight(SimpleNamespace(y=last.winfo_height()//2))
            navigate.assert_called_once_with('Inventory')

    def test_filter_heights_and_full_width_order_columns(self):
        from desktop_app import OrderComposer
        self.app.show_page('Orders');self.app.update()
        def widgets(parent):
            for child in parent.winfo_children():
                yield child
                yield from widgets(child)
        entry=next(w for w in widgets(self.app.body) if isinstance(w,tk.Entry))
        combo=next(w for w in widgets(self.app.body) if isinstance(w,ttk.Combobox))
        self.assertEqual(entry.winfo_height(),combo.winfo_height())
        def inspect(dialog):
            dialog.update()
            row=dialog.recipe_rows[1]
            self.assertEqual([c.grid_info()['column'] for c in row.winfo_children()],[0,1,2])
            self.assertEqual(row.winfo_width(),row.master.master.winfo_width())
            dialog.destroy()
        with patch.object(self.app,'wait_window',side_effect=inspect):
            OrderComposer(self.app,[{'recipeID':1,'name':'Rice dish','price':5}])

    def test_modern_controls_keep_native_selection_and_refresh_all_palettes(self):
        from appearance_preferences import THEMES
        for name,palette in THEMES.items():
            self.app._use_theme(name);self.app.show_page('Orders');self.app.update()
            style=ttk.Style(self.app)
            self.assertNotIn('uparrow',str(style.layout('Vertical.TScrollbar')))
            self.assertNotIn('downarrow',str(style.layout('Vertical.TScrollbar')))
            self.assertIn('Shop.downarrow',str(style.layout('TCombobox')))
            self.assertTrue(self.app._control_images)
            combo=ttk.Combobox(self.app,values=['First','Second'],state='readonly')
            combo.current(1);self.assertEqual(combo.get(),'Second');combo.destroy()

    @unittest.skipUnless(os.name=='nt','Windows dropdown border rendering')
    def test_dropdown_fields_and_popups_have_complete_accent_outlines(self):
        import ctypes as c
        from ctypes import wintypes as w
        from appearance_preferences import THEMES
        user=c.WinDLL('user32');gdi=c.WinDLL('gdi32')
        user.GetDC.argtypes=[w.HWND];user.GetDC.restype=w.HDC
        user.ReleaseDC.argtypes=[w.HWND,w.HDC]
        gdi.GetPixel.argtypes=[w.HDC,c.c_int,c.c_int];gdi.GetPixel.restype=w.DWORD
        def check_border(path,color,joined=False):
            self.app.update()
            hwnd=int(str(self.app.tk.call('winfo','id',path)),0)
            width=int(self.app.tk.call('winfo','width',path));height=int(self.app.tk.call('winfo','height',path))
            left=int(self.app.tk.call('winfo','rootx',path));top=int(self.app.tk.call('winfo','rooty',path))
            rgb=int(color[1:],16);expected=((rgb>>16)&255)|(rgb&0xff00)|((rgb&255)<<16)
            def pixel(x,y):
                target=hwnd;point=w.POINT(x,y)
                if joined:
                    # Read the control's own native layers, so another application
                    # passing over the test window cannot corrupt the pixel sample.
                    for layer in reversed(self.app.tk.call('winfo','children',path)):
                        lx=int(self.app.tk.call('winfo','rootx',layer));ly=int(self.app.tk.call('winfo','rooty',layer))
                        lw=int(self.app.tk.call('winfo','width',layer));lh=int(self.app.tk.call('winfo','height',layer))
                        if lx<=left+x<lx+lw and ly<=top+y<ly+lh:
                            target=int(str(self.app.tk.call('winfo','id',layer)),0)
                            point=w.POINT(left+x-lx,top+y-ly)
                            break
                dc=user.GetDC(target)
                try:return gdi.GetPixel(dc,point.x,point.y)
                finally:user.ReleaseDC(target,dc)
            points=((1,0),(width-2,0),(0,1),(width-1,1),
                        (0,height-2),(width-1,height-2),(1,height-1),(width-2,height-1),
                        (width//2,0),(width//2,height-1),(0,height//2),(width-1,height//2))
            if joined:
                combo=str(path).removesuffix('.popdown')
                above=top<int(self.app.tk.call('winfo','rooty',combo))
                points=[(x,y) for x,y in points if y!= (height-1 if above else 0)]
            for x,y in points:
                self.assertEqual(pixel(x,y),expected,(path,width,height,x,y,color))
            if joined:
                entry=THEMES[self.app.theme_name]['ENTRY']
                rgb=int(entry[1:],16);fill=((rgb>>16)&255)|(rgb&0xff00)|((rgb&255)<<16)
                seam=height-1 if above else 0;divider=height-2 if above else 1
                self.assertEqual(pixel(width//2,seam),fill)
                self.assertEqual(pixel(width//2,divider),expected)
        win=tk.Toplevel(self.app);win.geometry('650x400+100+100');win.attributes('-topmost',True)
        self.addCleanup(win.destroy)
        for theme,palette in THEMES.items():
            self.app._use_theme(theme)
            for width,count in ((160,2),(560,30)):
                combo=ttk.Combobox(win,values=[f'Choice {i}' for i in range(count)],height=5,state='readonly')
                combo.place(x=20,y=20,width=width);combo.current(0)
                self.app.update()
                combo.state(['!focus','!active','!pressed'])
                combo.event_generate('<Enter>',x=1,y=1)
                for x in (width//2,width-7,8,width//2):
                    combo.event_generate('<Motion>',x=x,y=combo.winfo_height()//2)
                    self.assertTrue(combo.instate(['hover']))
                    check_border(str(combo),palette['ACCENT'])
                combo.event_generate('<Leave>')
                self.assertFalse(combo.instate(['hover']))
                check_border(str(combo),palette['BORDER'])
                combo.state(['focus'])
                check_border(str(combo),palette['ACCENT'])
                combo.state(['!focus','!active','pressed'])
                check_border(str(combo),palette['ACCENT'])
                try:
                    self.app.tk.call('ttk::combobox::Post',str(combo))
                    check_border(str(combo)+'.popdown',palette['ACCENT'],joined=True)
                finally:
                    self.app.tk.call('ttk::combobox::Unpost',str(combo));combo.destroy()

    def test_joined_dropdown_edges_and_single_divider_above_and_below(self):
        from desktop_widgets import SmoothCombobox
        win=tk.Toplevel(self.app);win.attributes('-topmost',True);self.addCleanup(win.destroy)
        for direction in ('below','above'):
            y=100 if direction=='below' else self.app.winfo_screenheight()-280
            win.geometry(f'650x230+100+{y}');self.app.update()
            for width in (160,560):
                combo=SmoothCombobox(win,values=[str(i) for i in range(30)],height=8,state='readonly')
                combo.place(x=20,y=20 if direction=='below' else 180,width=width)
                self.app.update()
                popup=str(combo)+'.popdown'
                try:
                    self.app.tk.call('ttk::combobox::Post',str(combo));self.app.update()
                    x=int(self.app.tk.call('winfo','rootx',popup));top=int(self.app.tk.call('winfo','rooty',popup))
                    w=int(self.app.tk.call('winfo','width',popup));h=int(self.app.tk.call('winfo','height',popup))
                    self.assertEqual(x,combo.winfo_rootx());self.assertEqual(w,combo.winfo_width())
                    if direction=='below':self.assertEqual(top,combo.winfo_rooty()+combo.winfo_height()-2)
                    else:self.assertEqual(top+h,combo.winfo_rooty()+2)
                    self.assertLessEqual(top+h,self.app.winfo_screenheight())
                    lb=popup+'.f.l';self.app.tk.call(lb,'selection','clear',0,'end')
                    self.app.tk.call(lb,'selection','set',2)
                    self.app.tk.call('ttk::combobox::LBSelected',lb);self.app.update()
                    self.assertEqual(combo.get(),'2')
                finally:
                    self.app.tk.call('ttk::combobox::Unpost',str(combo));combo.destroy()

    def test_dropdown_fonts_text_alignment_and_roomy_rows(self):
        from desktop_widgets import SmoothCombobox,DROPDOWN_FONT
        from tkinter import font
        from appearance_preferences import THEMES
        win=tk.Toplevel(self.app);win.geometry('650x400+100+100');self.addCleanup(win.destroy)
        for theme in THEMES:
            self.app._use_theme(theme)
            for width in (160,560):
                combo=SmoothCombobox(win,values=['All columns','Ingredient'],state='readonly')
                combo.place(x=20,y=20,width=width);combo.current(0);self.app.update()
                self.app.tk.call('ttk::combobox::Post',str(combo));self.app.update()
                tree=combo._picker
                field_font=font.Font(font=combo.cget('font')).actual()
                list_font=font.Font(font=ttk.Style(self.app).lookup('Dropdown.Treeview','font')).actual()
                self.assertEqual(field_font,list_font)
                self.assertEqual(field_font['size'],DROPDOWN_FONT[1])
                box=self.app.tk.call(tree,'bbox','v0');self.assertGreaterEqual(int(box[3]),30)
                cy=int(box[1])+int(box[3])//2
                text_start=next(x for x in range(60) if str(self.app.tk.call(tree,'identify','element',x,cy)).endswith('text'))
                tree_left=int(self.app.tk.call('winfo','rootx',tree))
                self.assertEqual(tree_left+text_start,combo.winfo_rootx()+combo.bbox(0)[0])
                self.app.tk.call('ttk::combobox::Unpost',str(combo));combo.destroy()

    def test_roomy_dropdown_mouse_keyboard_typeahead_scroll_and_reopen(self):
        from desktop_widgets import SmoothCombobox
        win=tk.Toplevel(self.app);win.geometry('650x400+100+100');self.addCleanup(win.destroy)
        combo=SmoothCombobox(win,values=['Alpha','Beta','Gamma'],height=2,state='readonly')
        combo.pack(fill='x');next_field=tk.Entry(win);next_field.pack()
        changes=[];combo.bind('<<ComboboxSelected>>',lambda e:changes.append(combo.get()),add='+')
        combo.current(0);self.app.update()
        def post():
            self.app.tk.call('ttk::combobox::Post',str(combo));self.app.update()
            return combo._picker
        tree=post()
        self.app.tk.call('event','generate',tree,'<KeyPress-Down>');self.app.update()
        self.app.tk.call('event','generate',tree,'<KeyPress-Return>');self.app.update()
        self.assertEqual(combo.get(),'Beta')
        tree=post();self.app.tk.call('event','generate',tree,'<KeyPress-g>');self.app.update()
        self.assertEqual(self.app.tk.call(tree,'selection'),('v2',))
        self.app.tk.call('event','generate',tree,'<KeyPress-Escape>');self.app.update()
        self.assertEqual(combo.get(),'Beta')
        tree=post();self.app.tk.call(tree,'yview','moveto',0);self.app.update()
        box=self.app.tk.call(tree,'bbox','v0');y=int(box[1])+int(box[3])//2
        combo._picker_hover(12,y)
        self.app.tk.call('event','generate',tree,'<ButtonRelease-1>','-x',12,'-y',y);self.app.update()
        self.assertEqual(combo.get(),'Alpha');self.assertEqual(changes,['Beta','Alpha'])
        tree=post();self.app.tk.call(tree,'selection','set','v2')
        self.app.tk.call('event','generate',tree,'<KeyPress-Tab>');self.app.update()
        self.assertEqual(combo.get(),'Gamma');self.assertEqual(self.app.focus_get(),next_field)
        combo.configure(values=[str(i) for i in range(30)])
        tree=post();self.app.tk.call(tree,'yview','moveto',.5);self.app.update()
        view=self.app.tk.call(tree,'yview');bar=self.app.tk.call(str(combo)+'.popdown.f.sb','get')
        self.assertGreater(float(view[0]),0)
        self.assertEqual(tuple(map(float,view)),tuple(map(float,bar)))
        combo._picker_cancel()

    def test_dropdown_fade_reverses_without_snapping_and_cleans_up(self):
        from desktop_widgets import SmoothCombobox
        self.app.show_page('Settings');self.app.update()
        def descendants(parent):
            for child in parent.winfo_children():
                yield child;yield from descendants(child)
        combo=next(w for w in descendants(self.app.body) if isinstance(w,SmoothCombobox))
        combo.state(['!focus','!pressed','!active'])
        combo.event_generate('<Enter>')
        self.app.after(60,self.app.quit);self.app.mainloop()
        self.assertGreater(combo._fade_value,0);self.assertLess(combo._fade_value,1)
        midpoint=combo._fade_value
        combo.event_generate('<Leave>')
        self.assertAlmostEqual(combo._fade_value,midpoint,places=2)
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.assertEqual(combo._fade_value,0);self.assertIsNone(combo._fade_after)
        combo.event_generate('<Enter>')
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.assertEqual(combo._fade_value,1)
        combo.event_generate('<Leave>');self.assertIsNotNone(combo._fade_after)
        combo.destroy();self.assertIsNone(combo._fade_after)

    def test_dropdown_selection_and_click_away_clear_outline_despite_focus(self):
        from desktop_widgets import SmoothCombobox
        from appearance_preferences import THEMES
        self.app.show_page('Settings');self.app.update()
        combo=SmoothCombobox(self.app,values=['First','Second'],state='readonly')
        combo.pack();self.app.update();combo.focus_force()
        combo.event_generate('<Enter>')
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.app.tk.call('ttk::combobox::Post',str(combo));self.app.update()
        lb=str(combo)+'.popdown.f.l'
        self.app.tk.call(lb,'selection','clear',0,'end')
        self.app.tk.call(lb,'selection','set',1)
        self.app.tk.call('ttk::combobox::LBSelected',lb)
        self.app.update()
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.assertEqual(combo.get(),'Second')
        self.assertEqual(combo._fade_value,0)
        combo.state(['focus','hover'])
        style=ttk.Style(self.app)
        self.assertEqual(style.lookup(combo.cget('style'),'bordercolor',combo.state()).lower(),THEMES[self.app.theme_name]['BORDER'].lower())
        combo.event_generate('<Enter>')
        self.assertIsNone(combo._fade_after)
        combo.event_generate('<Leave>');combo.event_generate('<Enter>')
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.assertEqual(combo._fade_value,1)
        combo.event_generate('<Leave>')
        self.app.after(160,self.app.quit);self.app.mainloop()
        self.assertEqual(combo._fade_value,0)
        self.assertEqual(style.lookup(combo.cget('style'),'bordercolor',('focus',)).lower(),THEMES[self.app.theme_name]['BORDER'].lower())
        combo.destroy()

    def test_payroll_choices_alphabetical_and_entries_include_employee_names(self):
        from user_identity_service import role_id
        uids=[]
        for name in ('Zoe','Amy'):
            uid=self.app.svc.create_user(name,name.lower(),'EmployeePass123!','Employee');uids.append(uid)
            self.app.payroll.set_hourly_rate(self.owner,role_id(self.app.db_path,uid,'Employee'),20)
        pid=self.app.payroll.open_payroll(self.owner,'2026-11-16')
        with patch.object(self.app,'_payroll_id',return_value=pid),patch.object(self.app,'ask',return_value=None) as ask:
            self.app.payroll_hours()
            self.assertIn('Amy',ask.call_args.args[1][0][4][0])
        self.app.payroll.enter_hours(self.owner,pid,role_id(self.app.db_path,uids[0],'Employee'),8)
        with patch.object(self.app,'_payroll_id',return_value=pid),patch.object(self.app,'_records_dialog') as records:
            self.app.payroll_entries()
            row=records.call_args.args[1][0];keys=list(row)
            self.assertEqual(row['employeeName'],'Zoe')
            self.assertEqual(keys.index('employeeName'),keys.index('employeeID')+1)
