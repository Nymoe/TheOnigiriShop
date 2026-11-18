"""Reusable desktop presentation helpers."""
from datetime import datetime, timezone, timedelta
from tkinter import ttk
from tkinter import font as tkfont
import tkinter as tk
from time import perf_counter


FADE_STEPS=12
DROPDOWN_FONT=('Segoe UI',12)


def join_dropdown_popup(window,event):
    """Align the native list with its field and draw one shared divider.

    Keep Tk's popup ownership, scrolling widgets and grab handling intact.
    The native two-pixel outlines share their joining edge in either direction.
    """
    tkapp=window.tk
    popup=str(event.widget)
    if not tkapp.call('winfo','exists',popup):return
    combo=tkapp.call('winfo','parent',popup)
    tree=popup+'.f.picker'
    if tkapp.call('winfo','exists',tree):
        tkapp.call('grid','remove',popup+'.f.l')
        tkapp.call('grid',tree,'-row',0,'-column',0,'-sticky','nsew','-padx',0,'-pady',1)
        tkapp.call('update','idletasks')
        tkapp.call('after','idle',f'if {{[winfo exists {tree}] && [winfo ismapped {tree}]}} {{focus -force {tree}}}')
    x=int(tkapp.call('winfo','rootx',combo));y=int(tkapp.call('winfo','rooty',combo))
    width=int(tkapp.call('winfo','width',combo));field_height=int(tkapp.call('winfo','height',combo))
    height=int(tkapp.call('winfo','reqheight',popup))
    above=int(tkapp.call('winfo','rooty',popup))<y
    top=y-height+2 if above else y+field_height-2
    tkapp.call('wm','geometry',popup,f'{width}x{height}+{x}+{top}')
    palette=window._dropdown_palette
    # Square only the joined corners; the field's outer corners stay native.
    for name,color in (('join_left',palette['ACCENT']),('join_right',palette['ACCENT']),
                       ('join_seam',palette['ENTRY']),('join_divider',palette['ACCENT'])):
        path=popup+'.'+name
        if not tkapp.call('winfo','exists',path):
            tkapp.call('frame',path,'-borderwidth',0,'-highlightthickness',0)
            tkapp.call('bind',path,'<Button-1>',f'ttk::combobox::Unpost {combo}')
        tkapp.call(path,'configure','-background',color)
    edge_top=1 if above else 0
    tkapp.call('place',popup+'.join_left','-x',0,'-y',edge_top,'-width',2,'-height',height-1)
    tkapp.call('place',popup+'.join_right','-relx',1,'-y',edge_top,'-width',2,'-height',height-1,'-anchor','ne')
    tkapp.call('place',popup+'.join_seam','-x',2,'-y',height-1 if above else 0,
               '-relwidth',1,'-width',-4,'-height',1)
    tkapp.call('place',popup+'.join_divider','-x',2,'-y',height-2 if above else 1,
               '-relwidth',1,'-width',-4,'-height',1)
    if not tkapp.call('winfo','exists',tree):
        has_scrollbar=tkapp.call('winfo','manager',popup+'.f.sb')=='grid'
        tkapp.call('grid','configure',popup+'.f.l','-padx',(9,1 if has_scrollbar else 9))
    for name in ('join_seam','join_divider','join_left','join_right'):tkapp.call('raise',popup+'.'+name)


class SmoothCombobox(ttk.Combobox):
    """Native dropdown behavior with a cancellable, lightweight hover fade."""
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('style','Fade0.TCombobox')
        kwargs.setdefault('font',DROPDOWN_FONT)
        original_post=kwargs.pop('postcommand',None)
        super().__init__(*args,**kwargs)
        self._original_post=original_post
        self._search_text='';self._search_time=0
        self.configure(postcommand=self._prepare_picker)
        self._fade_value=0.0
        self._fade_after=None
        self._hover_suppressed=False
        self.bind('<Enter>',self._hover_enter,add='+')
        self.bind('<Leave>',self._hover_leave,add='+')
        self.bind('<<ComboboxSelected>>',self._selection_finished,add='+')
        self.bind('<Destroy>',self._stop_fade,add='+')

    def _prepare_picker(self):
        if callable(self._original_post):self._original_post()
        elif self._original_post:self.tk.call('uplevel','#0',self._original_post)
        popup=self.tk.call('ttk::combobox::PopdownWindow',self._w)
        self._picker=popup+'.f.picker'
        # The hidden native list keeps Tk's value/selection and grab protocol.
        # Its geometry reserves the same row height before Tk places the popup.
        linespace=tkfont.Font(master=self,font=self.cget('font')).metrics('linespace')
        row_height=int(ttk.Style(self).lookup('Dropdown.Treeview','rowheight'))
        padding=max(5,(row_height-linespace)//2)
        self.tk.call(popup+'.f.l','configure','-font',self.cget('font'),'-selectborderwidth',padding)
        if not self.tk.call('winfo','exists',self._picker):
            self.tk.call('ttk::treeview',self._picker,'-show','tree','-selectmode','browse',
                         '-style','Dropdown.Treeview','-yscrollcommand',(popup+'.f.sb','set'))
            for sequence,callback,args in (
                ('<Motion>',self._picker_hover,'%x %y'),
                ('<ButtonRelease-1>',self._picker_choose,''),
                ('<Return>',self._picker_choose,''),
                ('<Escape>',self._picker_cancel,''),
                ('<Tab>',lambda:self._picker_tab('next'),''),
                ('<Shift-Tab>',lambda:self._picker_tab('prev'),''),
                ('<KeyPress>',self._picker_typeahead,'%A')):
                command=self._register(callback)
                script=command+(' '+args if args else '')
                self.tk.call('bind',self._picker,sequence,f'if {{"[{script}]" == "break"}} break')
        self.tk.call(popup+'.f.sb','configure','-command',(self._picker,'yview'))
        children=self.tk.call(self._picker,'children','')
        if children:self.tk.call(self._picker,'delete',children)
        values=self.cget('values')
        for i,value in enumerate(values):
            self.tk.call(self._picker,'insert','','end','-id',f'v{i}','-text',value)
        self.tk.call(self._picker,'configure','-height',min(len(values),int(self.cget('height'))))
        self.tk.call(self._picker,'column','#0','-width',max(1,self.winfo_width()-4),'-stretch',True)
        if values:
            item=f'v{max(0,self.current())}'
            self.tk.call(self._picker,'selection','set',item);self.tk.call(self._picker,'focus',item)
            self.tk.call(self._picker,'see',item)
        self._search_text=''

    def _picker_hover(self,x,y):
        item=self.tk.call(self._picker,'identify','row',int(x),int(y))
        if item:
            self.tk.call(self._picker,'selection','set',item);self.tk.call(self._picker,'focus',item)

    def _copy_picker_selection(self):
        selected=self.tk.call(self._picker,'selection')
        if not selected:return False
        index=int(selected[0][1:]);lb=self._w+'.popdown.f.l'
        self.tk.call(lb,'selection','clear',0,'end');self.tk.call(lb,'selection','set',index)
        return True

    def _picker_choose(self):
        if self._copy_picker_selection():self.tk.call('ttk::combobox::LBSelected',self._w+'.popdown.f.l')
        return 'break'

    def _picker_cancel(self):
        self.tk.call('ttk::combobox::Unpost',self._w);self.focus_set()
        return 'break'

    def _picker_tab(self,direction):
        self._copy_picker_selection()
        self.tk.call('ttk::combobox::LBTab',self._w+'.popdown.f.l',direction)
        return 'break'

    def _picker_typeahead(self,char):
        if not char or not char.isprintable():return
        now=perf_counter()
        self._search_text=(self._search_text+char if now-self._search_time<.7 else char).casefold()
        self._search_time=now
        for i,value in enumerate(self.cget('values')):
            if str(value).casefold().startswith(self._search_text):
                item=f'v{i}';self.tk.call(self._picker,'selection','set',item)
                self.tk.call(self._picker,'focus',item);self.tk.call(self._picker,'see',item)
                break
        return 'break'

    def _hover_enter(self,event):
        if not self._hover_suppressed:self._fade_to(1)

    def _hover_leave(self,event):
        self._hover_suppressed=False
        self._fade_to(0)

    def _selection_finished(self,event):
        # Tk restores keyboard focus after selection; that must not pin the
        # hover outline on. A new pointer entry can start the next hover fade.
        self._hover_suppressed=True
        self._fade_to(0)

    def _stop_fade(self,event=None):
        if event is not None and event.widget is not self:return
        if self._fade_after is not None:self.after_cancel(self._fade_after)
        self._fade_after=None

    def _fade_to(self,target):
        self._stop_fade()
        if self.instate(['disabled']):return
        start=self._fade_value;began=perf_counter()
        def draw():
            self._fade_after=None
            progress=min(1,(perf_counter()-began)/.12)
            eased=progress*progress*(3-2*progress)
            self._fade_value=start+(target-start)*eased
            style=f'Fade{round(self._fade_value*FADE_STEPS)}.TCombobox'
            if self.cget('style')!=style:self.configure(style=style)
            if progress<1:self._fade_after=self.after(8,draw)
        draw()


def modern_controls(window, palette):
    """Theme-aware ttk controls, preserving native keyboard and dropdown behavior."""
    style=ttk.Style(window)
    window._dropdown_palette=palette
    if not getattr(window,'_joined_popup_binding',None):
        window._joined_popup_binding=window.bind_class('ComboboxPopdown','<Map>',
            lambda event:join_dropdown_popup(window,event),add='+')
    images=getattr(window,'_control_images',{})
    def image(name,width,height,color,arrow=False):
        picture=images.get(name)
        if picture is None:
            picture=tk.PhotoImage(master=window,width=width,height=height)
            images[name]=picture
        picture.blank()
        if arrow:
            for offset in range(4):
                for x in (3+offset,9-offset):picture.put(color,(x,4+offset))
        else:
            radius=4
            for y in range(height):
                inset=max(0,radius-y-1,y-(height-radius))
                picture.put(color,to=(inset,y,width-inset,y+1))
        return picture
    thumb=image('thumb',12,24,palette['MUTED'])
    active=image('thumb_active',12,24,palette['ACCENT'])
    horizontal=image('hthumb',24,12,palette['MUTED'])
    hactive=image('hthumb_active',24,12,palette['ACCENT'])
    arrow=image('arrow',13,12,palette['INK'],arrow=True)
    elements=style.element_names()
    for name,normal,hover,border,sticky in (
            ('Shop.Vertical.thumb',thumb,active,(4,5),'ns'),
            ('Shop.Horizontal.thumb',horizontal,hactive,(5,4),'ew')):
        if name not in elements:
            style.element_create(name,'image',normal,('pressed',hover),('active',hover),
                                 border=border,sticky=sticky)
    if 'Shop.downarrow' not in elements:
        style.element_create('Shop.downarrow','image',arrow,sticky='e')
    if 'Shop.Combobox.field' not in elements:
        # Native border drawing avoids tiling a tiny image over a wide popup.
        style.element_create('Shop.Combobox.field','from','clam','border')
        style.element_create('Shop.Combobox.popup','from','clam','border')
    for direction in ('Vertical','Horizontal'):
        sticky='ns' if direction=='Vertical' else 'ew'
        style.layout(direction+'.TScrollbar',[(direction+'.Scrollbar.trough',
            {'sticky':'nswe','children':[('Shop.'+direction+'.thumb',{'sticky':sticky,'expand':True})]})])
        style.configure(direction+'.TScrollbar',background=palette['SURFACE'],
            troughcolor=palette['SURFACE'],borderwidth=0,relief='flat',width=12)
    style.layout('TCombobox',[('Shop.Combobox.field',{'sticky':'nswe','children':[
        ('Shop.downarrow',{'side':'right','sticky':'e'}),
        ('Combobox.padding',{'expand':True,'sticky':'nswe','children':[
            ('Combobox.textarea',{'sticky':'nswe'})]})]})])
    style.configure('TCombobox',padding=(9,6),borderwidth=1,relief='solid',background=palette['ENTRY'],
        bordercolor=palette['BORDER'],lightcolor=palette['ENTRY'],darkcolor=palette['ENTRY'])
    style.map('TCombobox',bordercolor=[('pressed',palette['ACCENT']),('focus',palette['ACCENT']),('hover',palette['ACCENT']),('active',palette['ACCENT'])])
    low=tuple(int(palette['BORDER'][i:i+2],16) for i in (1,3,5))
    high=tuple(int(palette['ACCENT'][i:i+2],16) for i in (1,3,5))
    for step in range(FADE_STEPS+1):
        color='#'+''.join(f'{round(a+(b-a)*step/FADE_STEPS):02x}' for a,b in zip(low,high))
        style.configure(f'Fade{step}.TCombobox',bordercolor=color)
        style.map(f'Fade{step}.TCombobox',bordercolor=[('disabled',palette['BORDER']),
            ('pressed',palette['ACCENT']),('!disabled',color)])
    style.layout('ComboboxPopdownFrame',[('Shop.Combobox.popup',{'sticky':'nswe'})])
    style.configure('ComboboxPopdownFrame',padding=1,borderwidth=1,relief='solid',
        background=palette['ENTRY'],bordercolor=palette['ACCENT'],
        lightcolor=palette['ACCENT'],darkcolor=palette['ACCENT'])
    row_height=max(32,tkfont.Font(master=window,font=DROPDOWN_FONT).metrics('linespace')+11)
    style.configure('Dropdown.Treeview',font=DROPDOWN_FONT,rowheight=row_height,
        indent=0,borderwidth=0,padding=0,background=palette['ENTRY'],fieldbackground=palette['ENTRY'],foreground=palette['INK'])
    style.layout('Dropdown.Treeview.Item',[('Treeitem.padding',{'sticky':'nswe',
        'children':[('Treeitem.text',{'sticky':'nswe'})]})])
    style.configure('Dropdown.Treeview.Item',padding=(9,0))
    style.map('Dropdown.Treeview',background=[('selected',palette['SELECTED'])],foreground=[('selected',palette['INK'])])
    # Keep the native backing list consistent with the visible option picker.
    window.option_add('*TCombobox*Listbox.background',palette['ENTRY'])
    window.option_add('*TCombobox*Listbox.foreground',palette['INK'])
    window.option_add('*TCombobox*Listbox.selectBackground',palette['SELECTED'])
    window.option_add('*TCombobox*Listbox.selectForeground',palette['INK'])
    window.option_add('*TCombobox*Listbox.relief','flat')
    window.option_add('*TCombobox*Listbox.borderWidth',0)
    window._control_images=images

EST = timezone(timedelta(hours=-5), 'EST')


class AutoScrollbar(ttk.Scrollbar):
    """Only occupy space when the associated view actually overflows."""
    def pack(self, **kwargs):
        self._pack_options = kwargs

    def grid(self, **kwargs):
        self._grid_options=kwargs

    def set(self, first, last):
        needed = float(first) > 0.00001 or float(last) < 0.99999
        if needed and not self.winfo_manager():
            if hasattr(self,'_grid_options'):super().grid(**self._grid_options)
            else:super().pack(**getattr(self, '_pack_options', {}))
        elif not needed and self.winfo_manager():
            if self.winfo_manager()=='grid':self.grid_remove()
            else:self.pack_forget()
        super().set(first, last)


def scroll_if_needed(canvas, amount):
    first, last = canvas.yview()
    if last-first < 0.99999:
        canvas.yview_scroll(amount, 'units')
    return 'break'


def display_datetime(value, *, utc=False):
    """Display dates and timestamps consistently in fixed UTC-05:00 EST.

    Date-only records have no recorded time and display local midnight.
    """
    if not isinstance(value, str):
        return value
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc if utc and len(value)>10 else EST)
    return parsed.astimezone(EST).strftime('%m-%d-%Y %H:%M:%S EST')


def title_label(value):
    import re
    text=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',str(value)).replace('_',' ')
    text=re.sub(r'([A-Z])([A-Z][a-z])',r'\1 \2',text)
    words=text.title().split()
    return ' '.join(w.upper() if w.lower() in ('id','po','cad','uuid') else w for w in words)


def hover_button(widget):
    if getattr(widget,'_hover_installed',False):return
    widget._hover_installed=True
    def enter(_):
        base=widget.cget('bg');widget._normal_bg=base
        rgb=widget.winfo_rgb(base)
        widget._normal_active_bg=widget.cget('activebackground')
        shade='#'+''.join(f'{int(c/257*.88):02x}' for c in rgb)
        widget.configure(bg=shade,activebackground=shade)
    def leave(_):
        if hasattr(widget,'_normal_bg'):widget.configure(bg=widget._normal_bg,activebackground=getattr(widget,'_normal_active_bg',widget.cget('activebackground')))
    widget.bind('<Enter>',enter,add='+');widget.bind('<Leave>',leave,add='+')


def table_hover(tree):
    def motion(event):
        old=getattr(tree,'_hover_row',None);row=tree.identify_row(event.y)
        if old and tree.exists(old):tree.item(old,tags=())
        if row:tree.item(row,tags=('hover',))
        tree._hover_row=row
    tree.bind('<Motion>',motion,add='+')
    tree.bind('<Leave>',lambda e: motion(type('Pointer',(),{'y':-1})()),add='+')


def darken_color(value):
    return '#'+''.join(f'{int(int(value[i:i+2],16)*.88):02x}' for i in (1,3,5))
