"""Reusable desktop presentation helpers."""
from datetime import datetime, timezone, timedelta
from tkinter import ttk
from tkinter import font as tkfont
import tkinter as tk
from time import perf_counter
from desktop_icons import eye_icon, rgba_photo, checkbox_icon, notebook_tab_icon


FADE_STEPS=12
FADE_SECONDS=.12
DROPDOWN_FONT=('Segoe UI',12)


def modern_checkbuttons(window,palette,scale=1):
    size=round(22*scale)
    key=(size,palette['ENTRY'],palette['BORDER'],palette['ACCENT'])
    if getattr(window,'_active_check_style',None)==key:return
    window._active_check_style=key
    cache=getattr(window,'_check_images',{});window._check_images=cache
    style=ttk.Style(window)
    if key not in cache:
        off=checkbox_icon(window,palette['ENTRY'],palette['MUTED'],palette['INK'],False,size)
        on=checkbox_icon(window,palette['ACCENT'],palette['ACCENT'],'white',True,size)
        element=f'Shop.Check{len(cache)}.indicator'
        style.element_create(element,'image',off,('selected',on),sticky='w')
        cache[key]=(element,off,on)
    element=cache[key][0]
    style.layout('Shop.TCheckbutton',[('Checkbutton.padding',{'sticky':'nswe','children':[
        (element,{'side':'left','sticky':'w'}),('Checkbutton.focus',{'side':'left','sticky':'w',
        'children':[('Checkbutton.label',{'sticky':'w'})]})]})])
    style.configure('Shop.TCheckbutton',font=('Segoe UI',round(12*scale)),padding=(0,4),
                    background=palette['SURFACE'],foreground=palette['INK'],focuscolor=palette['ACCENT'])
    style.map('Shop.TCheckbutton',background=[('active',palette['SURFACE'])],
              foreground=[('disabled',palette['MUTED']),('!disabled',palette['INK'])])


def modern_notebooks(window,palette):
    style=ttk.Style(window)
    cache=getattr(window,'_tab_images',{});window._tab_images=cache
    key=tuple(palette[k] for k in ('SURFACE','HEADING','BORDER','LIGHT'))
    if key not in cache:
        off=notebook_tab_icon(window,palette['HEADING'],palette['BORDER'])
        on=notebook_tab_icon(window,palette['SURFACE'],palette['BORDER'])
        name=f'Shop.Tab{len(cache)}.tab'
        style.element_create(name,'image',off,('selected',on),border=(7,7,7,0),sticky='nswe')
        cache[key]=(name,off,on)
    style.configure('TNotebook',background=palette['LIGHT'],borderwidth=0,tabmargins=(0,0,0,0),
                    bordercolor=palette['LIGHT'],lightcolor=palette['LIGHT'],darkcolor=palette['LIGHT'])
    style.layout('TNotebook.Tab',[(cache[key][0],{'sticky':'nswe','children':[
        ('Notebook.padding',{'sticky':'nswe','children':[('Notebook.focus',{'sticky':'nswe',
        'children':[('Notebook.label',{'sticky':'nswe'})]})]})]})])
    style.configure('TNotebook.Tab',padding=(12,6),foreground=palette['INK'],background=palette['HEADING'])
    style.map('TNotebook.Tab',foreground=[('!disabled',palette['INK'])],background=[('selected',palette['SURFACE'])],
              padding=[('!disabled',(12,6))],expand=[('!disabled',(0,0,0,0))])


class RoundedFrame(tk.Frame):
    """A normal layout frame with a rounded, theme-coloured surface behind it."""
    def __init__(self,parent,*,radius=8,**kwargs):
        border=kwargs.pop('highlightbackground',None)
        thickness=kwargs.pop('highlightthickness',0)
        super().__init__(parent,highlightthickness=0,**kwargs)
        self._round_radius=radius
        self._surface_border=border if thickness else None
        self._surface_canvas=tk.Canvas(self,bd=0,highlightthickness=0,takefocus=False)
        self._surface_canvas._decoration=True
        self._surface_canvas.place(x=0,y=0,relwidth=1,relheight=1,bordermode='ignore')
        self.tk.call('lower',self._surface_canvas._w)
        # Application layouts may replace the frame's Configure binding.
        # The private drawing layer must repaint independently of those handlers.
        self._surface_canvas.bind('<Configure>',self._draw_surface,add='+')

    def _draw_surface(self,_event=None):
        width,height=self.winfo_width(),self.winfo_height()
        if width<2 or height<2:return
        fill=self.cget('bg')
        try:outside=self.master.cget('bg')
        except tk.TclError:outside=fill
        canvas=self._surface_canvas
        canvas.configure(bg=outside)
        radius=min(self._round_radius,width/2,height/2)
        points=[radius,.5,width-radius,.5,width-.5,.5,width-.5,radius,
                width-.5,height-radius,width-.5,height-.5,width-radius,height-.5,
                radius,height-.5,.5,height-.5,.5,height-radius,.5,radius,.5,.5]
        canvas.delete('surface')
        canvas.create_polygon(points,smooth=True,splinesteps=24,fill=fill,
                              outline='',tags='surface')
        rounding=getattr(self._root(),'_rounding',None)
        if rounding:rounding.apply(self)


class RoundedControls:
    """Small antialiased corner patches around existing native controls.

    Only the corners are rasterized. Wide fields keep their native centre and
    borders, avoiding stretched/tiled images and retaining native input bindings.
    """
    def __init__(self,window):
        from collections import OrderedDict
        self.window=window
        self._geometry={};self._proxies={};self._photos=OrderedDict();self._coverage={};self._paint_after={}
        self._button_clip=None
        if window.tk.call('tk','windowingsystem')=='win32':
            import ctypes as c
            from ctypes import wintypes as w
            user=c.WinDLL('user32')
            user.GetWindowLongW.argtypes=[w.HWND,c.c_int];user.GetWindowLongW.restype=w.LONG
            user.SetWindowLongW.argtypes=[w.HWND,c.c_int,w.LONG]
            self._button_clip=user
        for sequence in ('<Map>','<Configure>','<Expose>','<FocusIn>','<FocusOut>','<Enter>','<Leave>',
                         '<ButtonPress-1>','<ButtonRelease-1>','<KeyPress-space>','<KeyRelease-space>',
                         '<KeyRelease-Return>','<<ThemeChanged>>','<<NotebookTabChanged>>','<<TreeviewSelect>>'):
            window.bind_all(sequence,self._event,add='+')
        window.bind_all('<Unmap>',self._unmap,add='+')
        window.bind_all('<Destroy>',self._forget,add='+')
        window.bind_all('<Motion>',lambda event:self.apply(event.widget) if isinstance(event.widget,ttk.Treeview) else None,add='+')

    def _forget(self,event):
        path=str(event.widget)
        pending=self._paint_after.pop(path,None)
        if pending is not None:self.window.after_cancel(pending)
        self._geometry.pop(path,None);self._proxies.pop(path,None)

    def _event(self,event):
        widget=event.widget
        if getattr(widget,'_decoration',False):return
        path=str(widget)
        popup=path if path.endswith('.popdown') else path+'.popdown' if isinstance(widget,ttk.Combobox) else None
        if popup and self.window.tk.call('winfo','exists',popup) and self.window.tk.call('winfo','ismapped',popup):
            combo=popup.removesuffix('.popdown')
            above=int(self.window.tk.call('winfo','rooty',popup))<int(self.window.tk.call('winfo','rooty',combo))
            self.join_dropdown(combo,popup,above);return
        if isinstance(widget,(tk.Button,tk.Entry,tk.Spinbox,tk.Text,tk.Listbox,ttk.Entry,ttk.Combobox,ttk.Treeview,ttk.Notebook)) or getattr(widget,'_round_radius',None):
            self.apply(widget)

    def _unmap(self,event):
        path=str(event.widget)
        if path.endswith('.popdown'):
            combo=path.removesuffix('.popdown')
            if self.window.tk.call('winfo','exists',combo):self.apply(combo)

    def _widget(self,path):
        try:return self.window.nametowidget(path)
        except KeyError:
            if not path.endswith('.popdown'):return None
            # Tk creates this popup in Tcl. Register a Python wrapper so its
            # decorative children participate in normal widget destruction.
            parent=self.window.nametowidget(path.removesuffix('.popdown'))
            proxy=tk.Frame.__new__(tk.Frame)
            proxy.master=parent;proxy.tk=parent.tk;proxy._w=path
            proxy._name='popdown';proxy.children={};proxy._tclCommands=[]
            proxy._round_radius=6
            parent.children['popdown']=proxy;self._proxies[path]=proxy
            return proxy

    def _background(self,widget):
        override=getattr(widget,'_round_outside',None)
        if override:return override
        if str(widget).endswith('.popdown'):return self._background(widget.master)
        try:return widget.master.cget('bg')
        except tk.TclError:
            parent=widget.master
            if isinstance(parent,ttk.Widget):
                name=parent.cget('style') or parent.winfo_class()
                return ttk.Style(parent).lookup(name,'background',parent.state()) or self.window._dropdown_palette['SURFACE']
            return self.window._dropdown_palette['SURFACE']

    def _queue_paint(self,widget):
        path=str(widget)
        if path in self._paint_after:return
        def paint():
            self._paint_after.pop(path,None)
            if not widget.winfo_exists():return
            # Native button/entry drawing runs at idle too. Repaint the small
            # corner windows afterwards so presses cannot paint over them.
            for layer in [*getattr(widget,'_aa_rows',{}).values(),*getattr(widget,'_aa_corners',{}).values(),*getattr(widget,'_aa_edges',{}).values()]:
                if layer.winfo_manager():
                    self.window.tk.call('raise',str(layer))
                    layer.event_generate('<Expose>')
        self._paint_after[path]=self.window.after_idle(paint)

    def _appearance(self,widget):
        palette=self.window._dropdown_palette
        if str(widget).endswith('.popdown'):
            return palette['ENTRY'],palette['ACCENT'],2,None
        if isinstance(widget,ttk.Widget):
            style=ttk.Style(widget);name=widget.cget('style') or widget.winfo_class();state=widget.state()
            fill=style.lookup(name,'fieldbackground',state) or style.lookup(name,'background',state) or palette['SURFACE']
            if isinstance(widget,(ttk.Entry,ttk.Combobox)):
                return fill,style.lookup(name,'bordercolor',state) or palette['BORDER'],2,None
            top=style.lookup(name+'.Heading','background') if isinstance(widget,ttk.Treeview) else None
            if isinstance(widget,ttk.Treeview):
                return fill,palette['ACCENT'] if widget.instate(['focus']) else palette['BORDER'],1,top
            return fill,None,0,top
        fill=widget.cget('bg')
        if isinstance(widget,tk.Button) and widget.cget('state')=='active':fill=widget.cget('activebackground')
        if isinstance(widget,RoundedFrame):
            return fill,widget._surface_border,1 if widget._surface_border else 0,None
        # The combobox picker is created in Tcl and need not have a Python
        # widget wrapper. Compare paths rather than resolving its focus object.
        border=palette['ACCENT'] if self.window.tk.call('focus')==str(widget) else palette['BORDER']
        if isinstance(widget,(tk.Text,tk.Listbox)):
            stroke=widget.winfo_pixels(widget.cget('highlightthickness'))+widget.winfo_pixels(widget.cget('bd'))
            return fill,border if stroke else None,stroke,None
        return fill,border if isinstance(widget,(tk.Entry,tk.Spinbox)) else None,2 if isinstance(widget,(tk.Entry,tk.Spinbox)) else 0,None

    def _corner(self,radius,stroke,fill,border,outside,corner,square,seam):
        key=(radius,stroke,fill,border,outside,corner,square,seam)
        if key in self._photos:
            self._photos.move_to_end(key);return self._photos[key]
        geometry=(radius,stroke,square)
        if geometry not in self._coverage:
            coverage=[]
            for y in range(radius):
                for x in range(radius):
                    inner=outline=0
                    for sy in range(4):
                        for sx in range(4):
                            px=x+(sx+.5)/4;py=y+(sy+.5)/4
                            distance=((radius-px)**2+(radius-py)**2)**.5
                            outer=square or distance<=radius
                            inside=outer and (px>=stroke and py>=stroke if square else distance<=radius-stroke)
                            inner+=inside;outline+=bool(outer and not inside)
                    coverage.append((inner/16,outline/16))
            self._coverage[geometry]=coverage
        rgb=lambda color:tuple(v/257 for v in self.window.winfo_rgb(color))
        f=rgb(fill);b=rgb(border or fill);o=rgb(outside);pixels=[]
        for y in range(radius):
            for x in range(radius):
                xx=radius-1-x if corner.endswith('e') else x
                yy=radius-1-y if corner.startswith('s') else y
                inside,outline=self._coverage[geometry][yy*radius+xx]
                if seam and yy==0 and xx>=stroke:inside,outline=1,0
                pixels.extend((*[round(f[i]*inside+b[i]*outline+o[i]*(1-inside-outline)) for i in range(3)],255))
        image=rgba_photo(self.window,radius,radius,pixels)
        self._photos[key]=image
        if len(self._photos)>384:self._photos.popitem(last=False)
        return image

    def _wire(self,layer,widget):
        layer._decoration=True
        def forward(event,sequence):
            target=getattr(widget,'_round_hit_target',widget)
            if not target.winfo_exists():return
            x=event.x_root-target.winfo_rootx();y=event.y_root-target.winfo_rooty()
            if sequence=='<Leave>' and 0<=x<target.winfo_width() and 0<=y<target.winfo_height():
                return 'break'
            options={'x':x,'y':y}
            if sequence=='<MouseWheel>':options['delta']=event.delta
            target.event_generate(sequence,**options)
            return 'break'
        for sequence in ('<Enter>','<Leave>','<Motion>','<ButtonPress-1>','<ButtonRelease-1>','<MouseWheel>'):
            layer.bind(sequence,lambda event,s=sequence:forward(event,s))

    def _tree_rows(self,tree):
        masks=getattr(tree,'_aa_rows',{});tree._aa_rows=masks
        selected=set(tree.selection());hover=getattr(tree,'_hover_row','')
        rows=list(selected)+([hover] if hover and hover not in selected else [])
        used=set();palette=self.window._dropdown_palette
        for index,row in enumerate(rows):
            if not tree.exists(row):continue
            box=tree.bbox(row)
            if not box:continue
            x,y,width,height=box
            left=max(1,x);right=min(tree.winfo_width()-1,x+width)
            bottom=min(tree.winfo_height()-1,y+height)
            radius=min(6,(bottom-y)//2,(right-left)//2)
            if radius<2 or y<1:continue
            fill=palette['SELECTED'] if row in selected else tree.tag_configure('hover','background')
            if not fill:continue
            fill=str(fill)
            for corner,px,py,anchor in (('nw',left,y,'nw'),('ne',right,y,'ne'),('sw',left,bottom,'sw'),('se',right,bottom,'se')):
                key=(index,corner);used.add(key);layer=masks.get(key)
                if layer is None:
                    layer=tk.Canvas(tree,bd=0,highlightthickness=0,takefocus=False)
                    self._wire(layer,tree);masks[key]=layer
                    layer._corner_item=layer.create_image(0,0,anchor='nw')
                signature=(px,py,anchor,fill,palette['SURFACE'],radius)
                if getattr(layer,'_row_geometry',None)!=signature:
                    layer._row_geometry=signature
                    photo=self._corner(radius,0,fill,None,palette['SURFACE'],corner,False,False)
                    layer._corner_photo=photo;layer.itemconfigure(layer._corner_item,image=photo)
                    layer.place(x=px,y=py,width=radius,height=radius,anchor=anchor,bordermode='ignore')
                elif not layer.winfo_manager():layer.place(x=px,y=py,width=radius,height=radius,anchor=anchor,bordermode='ignore')
        for key,layer in masks.items():
            if key not in used:layer.place_forget()

    def apply(self,widget,join=None):
        path=str(widget);app=self.window.tk
        if not app.call('winfo','exists',path):return
        if not isinstance(widget,tk.Widget):widget=self._widget(path)
        if widget is None:return
        if self._button_clip and isinstance(widget,tk.Button) and getattr(widget,'_clip_handle',None)!=widget.winfo_id():
            # Win32 owner-drawn buttons otherwise paint straight over their
            # decorative child windows on mouse-down, despite their z-order.
            handle=widget.winfo_id();style=self._button_clip.GetWindowLongW(handle,-16)
            self._button_clip.SetWindowLongW(handle,-16,style|0x02000000)  # WS_CLIPCHILDREN
            widget._clip_handle=handle
        if join is None and isinstance(widget,ttk.Combobox):
            popup=path+'.popdown'
            if app.call('winfo','exists',popup) and app.call('winfo','ismapped',popup):
                join='top' if int(app.call('winfo','rooty',popup))<widget.winfo_rooty() else 'bottom'
        width,height=widget.winfo_width(),widget.winfo_height()
        if width<3 or height<3:return
        radius=min(getattr(widget,'_round_radius',6),width//2,height//2)
        fill,border,stroke,top=self._appearance(widget);outside=self._background(widget)
        if isinstance(widget,ttk.Treeview):self._tree_rows(widget)
        geometry=(widget.winfo_id(),width,height,radius,join,fill,border,outside,stroke,top)
        self._queue_paint(widget)
        if self._geometry.get(path)==geometry:return
        self._geometry[path]=geometry
        masks=getattr(widget,'_aa_corners',{});widget._aa_corners=masks
        for corner,rx,ry,anchor in (('nw',0,0,'nw'),('ne',1,0,'ne'),('sw',0,1,'sw'),('se',1,1,'se')):
            if isinstance(widget,ttk.Notebook) and corner.startswith('n'):
                if corner in masks:masks[corner].place_forget()
                continue  # The native notebook's individual tabs own these corners.
            square=(join=='top' and corner.startswith('n')) or (join=='bottom' and corner.startswith('s'))
            local_fill=top if top and corner.startswith('n') else fill
            if not border and local_fill==outside:
                if corner in masks:masks[corner].place_forget()
                continue
            layer=masks.get(corner)
            if layer is None:
                layer=tk.Canvas(widget,bd=0,highlightthickness=0,takefocus=False)
                self._wire(layer,widget);masks[corner]=layer
                layer._corner_item=layer.create_image(0,0,anchor='nw')
            image=self._corner(radius,stroke,local_fill,border,outside,corner,square,square and path.endswith('.popdown'))
            layer._corner_photo=image
            layer.configure(bg=outside,width=radius,height=radius)
            layer.itemconfigure(layer._corner_item,image=image)
            layer.place(relx=rx,rely=ry,anchor=anchor,width=radius,height=radius,bordermode='ignore')
            app.call('raise',str(layer))
        if isinstance(widget,(ttk.Entry,ttk.Combobox,ttk.Treeview,tk.Entry,tk.Spinbox)) or path.endswith('.popdown') or isinstance(widget,(RoundedFrame,tk.Text,tk.Listbox)) and border:
            edges=getattr(widget,'_aa_edges',{});widget._aa_edges=edges
            for side in ('top','bottom','left','right'):
                layer=edges.get(side)
                if layer is None:
                    layer=tk.Frame(widget,bd=0,highlightthickness=0,takefocus=False)
                    self._wire(layer,widget);edges[side]=layer
                if path.endswith('.popdown') and side==join:
                    layer.place_forget();continue
                layer.configure(bg=border)
                if side in ('top','bottom'):
                    layer.place(x=radius,y=0 if side=='top' else height-stroke,relwidth=1,width=-2*radius,height=stroke,bordermode='ignore')
                else:
                    layer.place(x=0 if side=='left' else width-stroke,y=radius,width=stroke,relheight=1,height=-2*radius,bordermode='ignore')
                app.call('raise',str(layer))

    def join_dropdown(self,combo,popup,above):
        self.apply(combo,join='top' if above else 'bottom')
        self.apply(popup,join='bottom' if above else 'top')


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
    rounding=getattr(window,'_rounding',None)
    if rounding:rounding.join_dropdown(combo,popup,above)


class SmoothCombobox(ttk.Combobox):
    """Native dropdown behavior with a cancellable, lightweight hover fade."""
    def __init__(self,*args,**kwargs):
        kwargs.setdefault('style','Fade0.TCombobox')
        kwargs.setdefault('font','ShopDropdownFont')
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
        self.selection_clear()
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
            duration=0 if getattr(self.winfo_toplevel()._root(),'reduced_motion',False) else FADE_SECONDS
            progress=min(1,(perf_counter()-began)/duration) if duration else 1
            eased=progress*progress*(3-2*progress)
            self._fade_value=start+(target-start)*eased
            style=f'Fade{round(self._fade_value*FADE_STEPS)}.TCombobox'
            if self.cget('style')!=style:
                self.configure(style=style)
                rounding=getattr(self._root(),'_rounding',None)
                if rounding:rounding.apply(self)
            if progress<1:self._fade_after=self.after(8,draw)
        draw()


def modern_controls(window, palette):
    """Theme-aware ttk controls, preserving native keyboard and dropdown behavior."""
    style=ttk.Style(window)
    modern_checkbuttons(window,palette)
    modern_notebooks(window,palette)
    if 'ShopDropdownFont' not in tkfont.names(window):
        window._dropdown_font=tkfont.Font(root=window,name='ShopDropdownFont',family='Segoe UI',size=12)
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
        style.element_create('Shop.Combobox.field','from','clam','Entry.field')
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
    style.map('TCombobox',fieldbackground=[('readonly',palette['ENTRY']),('!disabled',palette['ENTRY'])],
        background=[('disabled',palette['ENTRY']),('pressed',palette['ENTRY']),('active',palette['ENTRY']),('!disabled',palette['ENTRY'])],
        lightcolor=[('!disabled',palette['ENTRY'])],darkcolor=[('!disabled',palette['ENTRY'])],
        selectbackground=[('!disabled',palette['ENTRY'])],selectforeground=[('!disabled',palette['INK'])],
        foreground=[('!disabled',palette['INK'])])
    style.configure('Search.TEntry',padding=(9,6),borderwidth=1,relief='solid',
        fieldbackground=palette['ENTRY'],foreground=palette['INK'],insertcolor=palette['INK'],
        bordercolor=palette['BORDER'],lightcolor=palette['ENTRY'],darkcolor=palette['ENTRY'])
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
    row_height=max(32,tkfont.nametofont('ShopDropdownFont',root=window).metrics('linespace')+11)
    style.configure('Dropdown.Treeview',font='ShopDropdownFont',rowheight=row_height,
        indent=0,borderwidth=0,padding=0,background=palette['ENTRY'],fieldbackground=palette['ENTRY'],foreground=palette['INK'],
        bordercolor=palette['ENTRY'],lightcolor=palette['ENTRY'],darkcolor=palette['ENTRY'])
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
    text=re.sub(r'\bPOs\b','POSACRONYM',str(value))
    text=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',text).replace('_',' ')
    text=re.sub(r'([A-Z])([A-Z][a-z])',r'\1 \2',text)
    words=text.title().split()
    result=' '.join('POs' if w.lower()=='posacronym' else w.upper() if w.lower() in ('id','po','cad','uuid','est') else w for w in words)
    result=re.sub(r'yyyy-mm-dd','YYYY-MM-DD',result,flags=re.I)
    result=re.sub(r'\b(id|po|cad|uuid|est)\b',lambda match:match[0].upper(),result,flags=re.I)
    return re.sub(r'\bP Os\b','POs',result)


def button_colors(widget,background,foreground=None):
    """Keep native normal/active drawing and corner colours on the same base."""
    widget._normal_bg=background;widget._normal_active_bg=background;widget._hover_active=False
    widget.configure(bg=background,activebackground=background,**({'fg':foreground} if foreground else {}))
    rounding=getattr(widget._root(),'_rounding',None)
    if rounding:rounding.apply(widget)


def hover_button(widget):
    if getattr(widget,'_hover_installed',False):return
    widget._hover_installed=True
    def enter(_):
        if getattr(widget,'_selection_action',False) or widget.cget('state')=='disabled':return
        if getattr(widget,'_hover_active',False):return
        widget._hover_active=True
        base=widget.cget('bg');widget._normal_bg=base
        rgb=widget.winfo_rgb(base)
        widget._normal_active_bg=widget.cget('activebackground')
        shade='#'+''.join(f'{int(c/257*.88):02x}' for c in rgb)
        widget.configure(bg=shade,activebackground=shade)
    def leave(_):
        if getattr(widget,'_selection_action',False):return
        widget._hover_active=False
        if hasattr(widget,'_normal_bg'):widget.configure(bg=widget._normal_bg,activebackground=getattr(widget,'_normal_active_bg',widget.cget('activebackground')))
    widget.bind('<Enter>',enter,add='+');widget.bind('<Leave>',leave,add='+')
    # Crossing into a decorative corner remains inside the same button.
    # Tcl exposes the crossing detail that Tkinter's Event does not include.
    widget.bind('<Leave>','if {"%d" eq "NotifyInferior"} {break}\n'+widget.bind('<Leave>'))


def selection_action(button, tree, eligible, neutral, accent, ink):
    """Enable an action only for eligible selected rows; share the dropdown fade."""
    button._selection_action=True
    state={'after':None,'value':0.0}
    def cancel(_event=None):
        if state['after'] is not None:button.after_cancel(state['after'])
        state['after']=None
    def update(_event=None):
        chosen=tree.selection() if tree else ()
        record=getattr(tree,'records',{}).get(chosen[0]) if chosen else None
        enabled=bool(record and eligible(record))
        button.configure(state='normal' if enabled else 'disabled',disabledforeground=ink)
        cancel();start=state['value'];began=perf_counter()
        def draw():
            state['after']=None
            duration=0 if getattr(button._root(),'reduced_motion',False) else FADE_SECONDS
            p=min(1,(perf_counter()-began)/duration) if duration else 1
            state['value']=start+(float(enabled)-start)*p*p*(3-2*p)
            color='#'+''.join(f'{round(int(neutral[i:i+2],16)+(int(accent[i:i+2],16)-int(neutral[i:i+2],16))*state["value"]):02x}' for i in (1,3,5))
            button.configure(bg=color,activebackground=color,fg='white' if enabled else ink)
            rounding=getattr(button._root(),'_rounding',None)
            if rounding:rounding.apply(button)
            if p<1:state['after']=button.after(8,draw)
        draw()
    if tree:tree.bind('<<TreeviewSelect>>',update,add='+')
    button.bind('<Destroy>',cancel,add='+')
    update()


def password_entry(parent, variable, *, bg, fg):
    """A centred password field with a keyboard-accessible eye toggle."""
    frame=tk.Frame(parent,bg=parent.cget('bg'))
    style=ttk.Style(parent)
    style.configure('Password.Search.TEntry',padding=(34,6,34,6))
    entry=ttk.Entry(frame,textvariable=variable,font='ShopDropdownFont',style='Password.Search.TEntry',show='•',justify='center')
    entry._is_password=True
    entry.pack(fill='both',expand=True)
    images=[eye_icon(parent,fg),eye_icon(parent,fg,visible=True)]
    def toggle():
        visible=bool(entry.cget('show'))
        entry.configure(show='' if visible else '•')
        reveal.configure(image=images[int(visible)])
        reveal.accessible_name='Hide Password' if visible else 'Show Password'
    reveal=tk.Button(frame,text='',image=images[0],command=toggle,takefocus=True,
                     bg=bg,fg=fg,activebackground=bg,activeforeground=fg,bd=0,
                     relief='flat',highlightthickness=0,padx=2,pady=2,cursor='hand2')
    reveal._round_outside=bg
    reveal._icon_images=images
    reveal.accessible_name='Show Password'
    reveal.place(relx=1,rely=.5,x=-6,anchor='e',width=26,height=26)
    reveal.bind('<Return>',lambda e:(toggle(),'break')[1])
    frame.focus_set=entry.focus_set
    frame.icursor=entry.icursor
    frame.entry=entry;frame.reveal=reveal
    return frame


def table_hover(tree):
    def motion(event):
        tree._hover_y=event.y if event.y>=0 else None
        old=getattr(tree,'_hover_row',None);row=tree.identify_row(event.y)
        if old==row:return
        if old and tree.exists(old):tree.item(old,tags=tuple(tag for tag in tree.item(old,'tags') if tag!='hover'))
        if row:tree.item(row,tags=(*tree.item(row,'tags'),'hover'))
        tree._hover_row=row
        rounding=getattr(tree._root(),'_rounding',None)
        if rounding:rounding.apply(tree)
    tree.bind('<Motion>',motion,add='+')
    tree._hover_refresh=motion
    tree.bind('<Leave>',lambda e: motion(type('Pointer',(),{'y':-1})()),add='+')
    tree.bind('<Leave>','if {"%d" eq "NotifyInferior"} {break}\n'+tree.bind('<Leave>'))


def rounded_scroll(tree,scrollbar):
    def update(first,last):
        scrollbar.set(first,last)
        if getattr(tree,'_hover_y',None) is not None:
            tree._hover_refresh(type('Pointer',(),{'y':tree._hover_y})())
        rounding=getattr(tree._root(),'_rounding',None)
        if rounding:rounding.apply(tree)
    return update


def darken_color(value):
    return '#'+''.join(f'{int(int(value[i:i+2],16)*.88):02x}' for i in (1,3,5))
