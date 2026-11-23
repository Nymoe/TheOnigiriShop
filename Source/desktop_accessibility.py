"""Desktop accessibility helpers using Tk and optional built-in Windows tools."""
import os
from pathlib import Path
import subprocess
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

from desktop_preferences import DEFAULT_ACCESSIBILITY


def accessible_palette(palette,mode):
    result=dict(palette)
    if mode=='Colourblind Friendly':
        result.update(ACCENT='#006DAA',RED='#A33B00',SELECTED='#C4DFF1',
                      INK='#122C3C',DARK='#122C3C',LIGHT='#F5F7FA',SURFACE='#FFFFFF',
                      ENTRY='#FFFFFF',MUTED='#455667',BORDER='#6C7C8C',HEADING='#DDEBF5',
                      SECONDARY='#DDEBF5',SIDE_HOVER='#234B68',SIDE_BUTTON='#234B68')
    elif mode=='High Contrast':
        result.update(INK='#FFFFFF',DARK='#000000',LIGHT='#000000',SURFACE='#000000',
                      ENTRY='#000000',MUTED='#FFFFFF',BORDER='#FFFFFF',HEADING='#202020',
                      SECONDARY='#303030',ACCENT='#005FCC',RED='#B52020',SELECTED='#005FCC',
                      SIDE_TEXT='#FFFFFF',SIDE_MUTED='#FFFFFF',SIDE_ACCENT='#FFFF00',
                      SIDE_HOVER='#005FCC',SIDE_BUTTON='#303030',SIDE_DIVIDER='#FFFFFF')
    return result


class Accessibility:
    def __init__(self,app):
        self.app=app
        self.options=dict(DEFAULT_ACCESSIBILITY)
        self._pending=None
        self._speech=None
        app.bind_all('<Map>',self.queue,add='+')
        app.bind_all('<FocusIn>',self.focus_changed,add='+')
        app.bind_all('<Control-Shift-R>',lambda e:self.read_focus(),add='+')
        app.bind_all('<Control-Shift-S>',lambda e:self.stop_speech(),add='+')

    def queue(self,_event=None):
        if self._pending is None:self._pending=self.app.after_idle(self.apply)

    def apply(self):
        self._pending=None
        scale=self.options['text_size']/100
        from desktop_widgets import modern_checkbuttons
        modern_checkbuttons(self.app,self.app._dropdown_palette,scale)
        style=ttk.Style(self.app)
        tkfont.nametofont('ShopDropdownFont',root=self.app).configure(size=round(12*scale))
        style.configure('POS.Treeview',font=('Segoe UI',round(10*scale)),rowheight=round(34*scale))
        style.configure('POS.Treeview.Heading',font=('Segoe UI',round(10*scale),'bold'))
        style.configure('Dropdown.Treeview',rowheight=max(32,tkfont.nametofont('ShopDropdownFont',root=self.app).metrics('linespace')+11))
        def visit(widget):
            try:
                if hasattr(widget,'_notice_base_height'):
                    height=round(widget._notice_base_height*scale)
                    if int(widget.cget('height'))!=height:
                        widget.configure(height=height)
                        position=getattr(widget,'_position_notice',None)
                        if position:position()
                if 'font' in widget.keys() and str(widget.cget('font'))!='ShopDropdownFont':
                    if not hasattr(widget,'_a11y_base_font'):
                        widget._a11y_base_font=tkfont.Font(root=self.app,font=widget.cget('font')).actual()
                    if getattr(widget,'_a11y_scale',None)!=scale:
                        settings=dict(widget._a11y_base_font)
                        settings['size']=round(settings['size']*scale)
                        widget._a11y_font=tkfont.Font(root=self.app,**settings)
                        widget.configure(font=widget._a11y_font);widget._a11y_scale=scale
                if 'cursor' in widget.keys():
                    if not hasattr(widget,'_a11y_cursor'):widget._a11y_cursor=widget.cget('cursor')
                    cursor={'Standard':widget._a11y_cursor,'Crosshair':'crosshair','Hand':'hand2'}[self.options['cursor']]
                    if widget.cget('cursor')!=cursor:widget.configure(cursor=cursor)
                for child in widget.winfo_children():visit(child)
            except tk.TclError:pass
        visit(self.app)

    def focus_changed(self,event):
        # Keep keyboard focus within the visible section of scrolling forms.
        widget=event.widget
        if not isinstance(widget,tk.Widget):return
        parent=widget.master if isinstance(widget,(tk.Entry,ttk.Entry,tk.Button,tk.Checkbutton,ttk.Checkbutton,tk.Listbox,ttk.Treeview)) else None
        while parent and parent is not self.app:
            if isinstance(parent,tk.Canvas):
                box=parent.bbox('all')
                if box and box[3]>parent.winfo_height():
                    y=widget.winfo_rooty()-parent.winfo_rooty()+parent.canvasy(0)
                    if y<parent.canvasy(0):parent.yview_moveto(max(0,y-8)/box[3])
                    elif y+widget.winfo_height()>parent.canvasy(0)+parent.winfo_height():
                        parent.yview_moveto(max(0,y+widget.winfo_height()-parent.winfo_height()+8)/box[3])
                break
            parent=parent.master
        if self.options['narration']:self.read_focus(widget)

    def read_focus(self,widget=None):
        widget=widget or self.app.focus_get()
        if widget is None:return
        try:
            if isinstance(widget,(tk.Entry,ttk.Entry,ttk.Combobox)):
                label=getattr(widget,'accessible_name','Input')
                text=f'{label}. Password hidden.' if getattr(widget,'_is_password',False) or widget.cget('show') else f'{label}. {widget.get()}'
            elif isinstance(widget,ttk.Treeview):
                selected=widget.selection()
                text=' | '.join(widget.item(selected[0],'values')) if selected else 'Table. Use arrow keys to select a row.'
            elif isinstance(widget,tk.Text):text=widget.get('1.0','end')
            else:text=getattr(widget,'accessible_name',None) or (widget.cget('text') if 'text' in widget.keys() else widget.winfo_class())
        except tk.TclError:return
        self.speak(text)
        return 'break'

    def read_page(self):
        texts=[]
        def visit(widget):
            if isinstance(widget,tk.Label) and widget.winfo_ismapped():texts.append(widget.cget('text'))
            for child in widget.winfo_children():visit(child)
        visit(getattr(self.app,'body',self.app))
        self.speak('. '.join(texts))

    def speak(self,text):
        if os.name!='nt':
            messagebox.showinfo('Speech','Use your operating system screen reader on this platform.',parent=self.app);return
        text=str(text).strip()[:12000]
        if not text:return
        # Text is passed as Unicode environment data, never interpolated as code.
        self.stop_speech()
        environment=dict(os.environ,ONIGIRI_SPEECH=text)
        script="Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak($env:ONIGIRI_SPEECH)"
        try:self._speech=subprocess.Popen(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=environment,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        except OSError as exc:messagebox.showerror('Speech unavailable',str(exc),parent=self.app)

    def stop_speech(self):
        if self._speech and self._speech.poll() is None:
            try:self._speech.terminate()
            except OSError:pass
        self._speech=None
        return 'break'

    def open_tool(self,tool):
        if os.name!='nt':
            messagebox.showinfo('Accessibility tools','Open your operating system accessibility settings for this tool.',parent=self.app);return
        names={'Magnifier':'Magnify.exe','Narrator':'Narrator.exe','On-Screen Keyboard':'osk.exe'}
        try:
            # UIAccess system applications must be launched through the Windows
            # shell, which handles their signed manifests and normal OS consent.
            os.startfile(str(Path(os.environ.get('SystemRoot',r'C:\Windows'))/'System32'/names[tool]),'open')
        except OSError as exc:
            if getattr(exc,'winerror',None)==1223:
                messagebox.showinfo('Accessibility tool','Windows cancelled the launch.',parent=self.app)
            else:messagebox.showerror('Accessibility tool',f'Could not open {tool}: {exc}',parent=self.app)

    def close(self):
        if self._pending is not None:self.app.after_cancel(self._pending)
        self._pending=None
        self.stop_speech()
