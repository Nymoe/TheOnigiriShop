"""The Onigiri Shop desktop UI. Uses the existing, shared application services.

Launch from the project folder: python Source/desktop_app.py
This prototype does NOT collect/process payments or settle loyalty discounts.
"""
from __future__ import annotations

from datetime import datetime, date
from dataclasses import asdict
from contextlib import redirect_stdout
from functools import wraps
from io import StringIO
from pathlib import Path
from time import perf_counter
import sqlite3
import sys
from statistics import mean
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont

from desktop_widgets import AutoScrollbar, SmoothCombobox, scroll_if_needed, display_datetime, EST, title_label, hover_button, table_hover, darken_color, modern_controls
from user_identity_service import role_id, user_id_for_role
from inventory_db import DEFAULT_DB
from inventory_service import InventoryService, InventoryError, _ident
from profile_service import ProfileService, ProfileError
from user_management_service import UserManagementService
from loyalty_service import LoyaltyService, LoyaltyError, AccountNotFoundError
from desktop_details_service import DetailService
from desktop_demo_service import load_complete_demo
from demo_tools import (backup_database, reset_database, restore_database, list_backups,
                        populate_trend_history, populate_accounting_activity, populate_payroll_activity)
from accounting_service import AccountingLedger, AccountingTransaction
from feedback_service import FeedbackService
from payroll_service import PayrollService
from trend_prediction_service import (BusinessData, IngredientData, TrendPrediction,
                                      plot_prediction_chart)
from sample_users import load_sample_users
from appearance_preferences import ThemePreferences, THEMES, DEFAULT_THEME
from application_paths import asset_path

# The palette is selected at runtime; services and data remain unchanged.
def set_palette(name: str) -> None:
    global INK, DARK, ACCENT, LIGHT, SURFACE, MUTED, BORDER, MINT, RED
    global SECONDARY, ENTRY, HEADING, SELECTED, SIDE_TEXT, SIDE_MUTED
    global SIDE_ACCENT, SIDE_HOVER, SIDE_BUTTON, SIDE_DIVIDER
    palette = THEMES[name]
    for key, value in palette.items():
        globals()[key] = value


set_palette(DEFAULT_THEME)

FONT = 'Segoe UI'


def database_path() -> Path:
    """Both source interfaces use the project's Data/btm495.db."""
    return DEFAULT_DB


def requires_role(*roles):
    """Check the current database account before opening a protected action."""
    def decorate(method):
        @wraps(method)
        def checked(self, *args, **kwargs):
            if self._authorize(roles):
                previous=getattr(self, '_action_roles', ())
                self._action_roles=roles
                try:
                    return method(self, *args, **kwargs)
                finally:
                    self._action_roles=previous
            return None
        return checked
    return decorate


def resource(name: str) -> Path:
    return asset_path(name)


def money(value) -> str:
    return f'${float(value or 0):,.2f}'


def popup_dimensions(parent, desired_width: int, desired_height: int,
                     *, margin: int = 28) -> tuple[int, int]:
    """Fit a dialog inside the visible display, including small laptop screens."""
    screen_w = max(320, parent.winfo_screenwidth())
    screen_h = max(280, parent.winfo_screenheight())
    return (max(260, min(desired_width, screen_w - margin * 2)),
            max(240, min(desired_height, screen_h - margin * 2)))


def center_popup(window, parent, width: int, height: int) -> None:
    """Position with screen bounds to avoid off-screen dialog edges."""
    parent.update_idletasks()
    screen_w = max(width, window.winfo_screenwidth())
    screen_h = max(height, window.winfo_screenheight())
    x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
    x = max(0, min(x, screen_w - width))
    y = max(0, min(y, screen_h - height))
    window.geometry(f'{width}x{height}+{x}+{y}')


def numeric_column(key: str, rows) -> bool:
    """Identify numeric values independently of their centered presentation."""
    lowered = key.casefold()
    if lowered.endswith('id') or any(term in lowered for term in (
            'amount', 'total', 'price', 'cost', 'quantity', 'balance',
            'points', 'rate', 'hours', 'count', 'revenue', 'rating', 'employees')):
        return True
    values = [r.get(key) for r in rows if r.get(key) not in (None, '', '—')]
    if not values:
        return False
    if any(isinstance(v, bool) for v in values):
        return False
    try:
        for value in values:
            float(str(value).strip().replace('$', '').replace(',', ''))
        return True
    except (TypeError, ValueError):
        return False


def format_table_value(key: str, value) -> str:
    """Display monetary columns with consistent cents for easy comparison.

    This changes presentation only; raw amounts remain unchanged in the
    database and are still used for numeric sorting and calculations.
    """
    if value is None:
        return ''
    raw = str(value)
    if key in ('isActive','affordable'):return 'Yes' if value in (True,1,'1') else 'No'
    if raw=='Inactive':return 'Inactive'
    if any(part in key.lower() for part in ('date','createdat','updatedat','resolvedat','loadedat','performedat')):
        return str(display_datetime(value,utc=key in ('createdAt','updatedAt','resolvedAt','loadedAt','performedAt')))
    label = key.casefold()
    if ('point' not in label and not label.endswith('id') and
        any(part in label for part in ('amount', 'price', 'revenue', 'expense',
                                      'discount', 'grosspay', 'netpay', 'hourlyrate',
                                      'totalcost'))):
        try:
            return f'{float(value):.2f}'
        except (TypeError, ValueError, OverflowError):
            pass
    return raw


def allocate_table_widths(preferred: list[int], viewport: int) -> list[int]:
    """Fill a wide table viewport without crushing columns on narrow displays.

    Keep the preferred widths and horizontal scroll when the table is narrower
    than its content. When there is extra space, distribute it across every
    heading/data column so the last header reaches the right of the table.
    """
    if not preferred:return []
    minimum=max(110,min(220,max(preferred)))
    total=max(int(viewport),minimum*len(preferred))
    width,extra=divmod(total,len(preferred))
    return [width+(i<extra) for i in range(len(preferred))]



def size_table_columns(tree: ttk.Treeview, preferred: dict[str, int], width: int) -> None:
    """Align headers to a full-width responsive grid; keep horizontal scroll."""
    keys = list(tree['columns'])
    # Leave a small border allowance to avoid a spurious horizontal scroll bar.
    widths = allocate_table_widths([preferred[k] for k in keys], max(0, width - 5))
    for key, size in zip(keys, widths):
        tree.column(key, width=size, stretch=False)


def preferred_table_widths(rows, cols) -> dict[str, int]:
    """Use actual font measurements so headings fit without magic char counts."""
    regular = tkfont.Font(family=FONT, size=10)
    bold = tkfont.Font(family=FONT, size=10, weight='bold')
    widths = {}
    for key, title in cols:
        heading_width = bold.measure(str(title)) + 32
        widest_value = max((regular.measure(str(row.get(key) if row.get(key) is not None else ''))
                            for row in rows), default=0) + 26
        widths[key] = max(95, min(370, heading_width))
    return widths


class InputDialog(tk.Toplevel):
    """Responsive modal form: editable fields scroll; Save/Cancel remain visible."""
    def __init__(self, parent, title, fields, help_text='', confirm='Save', batch=None):
        super().__init__(parent)
        self.result = None
        self.batch = batch
        self.staged = []
        self.title(title_label(title))
        self.configure(bg=SURFACE)
        self.transient(parent)
        self._vars = {}
        self._password_fields = set()
        width, height = popup_dimensions(parent, 600, 240 + 84 * len(fields))
        self.geometry(f'{width}x{height}')
        self.minsize(min(width, 340), min(height, 270))
        self.resizable(True, True)

        head = tk.Frame(self, bg=SURFACE, padx=18, pady=12)
        head.pack(fill='x')
        tk.Label(head, text=title, fg=INK, bg=SURFACE,
                 font=(FONT, 17, 'bold'), justify='center',
                 wraplength=width-55).pack(fill='x')
        if help_text:
            help_label = tk.Label(head, text=help_text, fg=MUTED, bg=SURFACE,
                    font=(FONT, 10), justify='center', wraplength=width-55)
            help_label.pack(fill='x', pady=(8,0))
            head.bind('<Configure>', lambda e:help_label.configure(wraplength=max(150,e.width-40)))

        holder = tk.Frame(self, bg=SURFACE)
        holder.pack(fill='both', expand=True, padx=16)
        canvas = tk.Canvas(holder, bg=SURFACE, highlightthickness=0)
        scrollbar = AutoScrollbar(holder, orient='vertical', command=canvas.yview)
        inside = tk.Frame(canvas, bg=SURFACE, padx=12, pady=8)
        inside_id = canvas.create_window((0,0), window=inside, anchor='nw')
        inside.bind('<Configure>', lambda _e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e:canvas.itemconfigure(inside_id,width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='left', fill='both', expand=True)
        first = None
        for field in fields:
            key, label, default, kind, *options = field
            tk.Label(inside,text=label,bg=SURFACE,fg=INK,
                 font=(FONT,10,'bold'),justify='center').pack(fill='x',pady=(10,4))
            var=tk.StringVar(value=str(default) if default is not None else '')
            if kind == 'choice':
                control=SmoothCombobox(inside,textvariable=var,values=options[0],state='readonly')
            else:
                control=tk.Entry(inside,textvariable=var,relief='solid',bd=1,
                  justify='center',show='•' if kind=='password' else '',
                  font=(FONT,11),fg=INK,bg=ENTRY,insertbackground=INK)
            control.pack(fill='x', ipady=6, padx=4)
            control.bind('<FocusIn>',lambda e:e.widget.icursor('end'),add='+')
            if first is None:first=control
            self._vars[key]=var
            if kind == 'password':
                self._password_fields.add(key)

        footer=tk.Frame(self,bg=SURFACE,padx=18,pady=13)
        footer.pack(fill='x', side='bottom', before=holder)  # Reserve button space before scroll area
        footer.columnconfigure(tuple(range(3 if batch else 2)),weight=1,uniform='form')
        action_button(footer,'Cancel',self.destroy,primary=False).grid(row=0,column=0,sticky='ew',padx=(0,5))
        if batch:
            action_button(footer,'Add',self._add_batch,primary=False).grid(row=0,column=1,sticky='ew',padx=5)
            self.batch_label=tk.Label(inside,text='No employees added yet.',bg=SURFACE,fg=MUTED,wraplength=450)
            self.batch_label.pack(fill='x',pady=10)
        action_button(footer,confirm,self._submit).grid(row=0,column=2 if batch else 1,sticky='ew',padx=(5,0))
        self.bind('<Escape>',lambda _e:self.destroy())
        self.bind('<Return>',lambda _e:self._submit())
        self.update_idletasks()
        # Display as many fields as the monitor can show without scrolling.
        # For longer forms, keep the footer visible and scroll the middle.
        ideal = head.winfo_reqheight() + inside.winfo_reqheight() + footer.winfo_reqheight() + 40
        width, height = popup_dimensions(parent, width, max(300, ideal))
        center_popup(self, parent, width, height)
        self.grab_set()
        if first:
            first.focus_set()
            first.icursor('end')
        parent.wait_window(self)

    def _submit(self):
        if self.batch:
            if self._vars['hours'].get().strip() and not self._add_batch():return
            if not self.staged:
                messagebox.showinfo('No hours added','Add at least one employee before saving.',parent=self);return
            self.result=list(self.staged)
            self.destroy()
            return
        self.result={key:var.get() if key in self._password_fields else var.get().strip()
                     for key,var in self._vars.items()}
        self.destroy()

    def _add_batch(self):
        values={key:var.get().strip() for key,var in self._vars.items()}
        try:
            self.batch(values)
            if any(row['employee']==values['employee'] for row in self.staged):
                raise ValueError('This employee is already added. Cancel and restart to change the staged hours.')
        except ValueError as exc:
            messagebox.showerror('Invalid hours',str(exc),parent=self);return False
        self.staged.append(values)
        self.batch_label.config(text='\n'.join(f"{r['employee']} | {r['hours']} regular / {r['overtime']} overtime" for r in self.staged))
        self._vars['hours'].set('');self._vars['overtime'].set('0')
        return True

def action_button(parent, text, command, primary=True, small=False, danger=False):
    bg = (RED if danger else ACCENT) if primary else SECONDARY
    fg = 'white' if primary else INK
    btn = tk.Button(parent, text=title_label(text), command=command, bg=bg, fg=fg,
                    activebackground=DARK if primary else BORDER,
                    activeforeground='white' if primary else INK,
                    font=(FONT, 10 if small else 11, 'bold'), bd=0,
                    padx=16 if small else 21, pady=8 if small else 11,
                    cursor='hand2', relief='flat', highlightthickness=0)
    hover_button(btn)
    return btn


def card(parent, padding=20):
    frame = tk.Frame(parent, bg=SURFACE, highlightbackground=BORDER, highlightthickness=1,
                     padx=padding, pady=padding)
    return frame


class OrderComposer(tk.Toplevel):
    """POS-style cart editor for recipes; returning a validated recipe-ID -> quantity map."""
    def __init__(self, parent, recipes):
        super().__init__(parent)
        self.result = None
        self.title('New customer order | The Onigiri Shop')
        self.configure(bg=LIGHT)
        width, height = popup_dimensions(parent, 760, 720)
        self.geometry(f'{width}x{height}')
        self.minsize(min(width, 400), min(height, 370))
        self.transient(parent)
        box=tk.Frame(self,bg=LIGHT,padx=27,pady=23)
        box.pack(fill='both',expand=True)
        tk.Label(box,text='Build a new order',bg=LIGHT,fg=INK,font=(FONT,22,'bold'),justify='center').pack(fill='x')
        tk.Label(box,text='Choose a quantity for each recipe. Inventory is deducted only when the order is completed.',
                 bg=LIGHT,fg=MUTED,wraplength=560,justify='center').pack(fill='x',pady=(5,18))
        catalog_filters=tk.Frame(box,bg=LIGHT)
        catalog_filters.pack(fill='x',pady=(0,10))
        tk.Label(catalog_filters,text='Find a recipe',bg=LIGHT,fg=INK,
                 font=(FONT,10,'bold')).grid(row=0,column=0,sticky='ew',padx=4)
        tk.Label(catalog_filters,text='Sort menu',bg=LIGHT,fg=INK,
                 font=(FONT,10,'bold')).grid(row=0,column=1,sticky='ew',padx=4)
        self.recipe_search=tk.StringVar()
        self.recipe_sort=tk.StringVar(value='Name A–Z')
        tk.Entry(catalog_filters,textvariable=self.recipe_search,justify='center',
                 font=(FONT,10),bd=1,relief='solid').grid(row=1,column=0,sticky='nsew',padx=4)
        SmoothCombobox(catalog_filters,values=['Name A–Z','Name Z–A','Price: low to high','Price: high to low'],
                     textvariable=self.recipe_sort,state='readonly').grid(row=1,column=1,sticky='ew',padx=4)
        catalog_filters.columnconfigure((0,1),weight=1)
        outer=tk.Frame(box,bg=SURFACE,highlightbackground=BORDER,highlightthickness=1)
        outer.pack(fill='both',expand=True)
        canvas=tk.Canvas(outer,bg=SURFACE,highlightthickness=0)
        sb=AutoScrollbar(outer,orient='vertical',command=canvas.yview)
        content=tk.Frame(canvas,bg=SURFACE)
        content.bind('<Configure>',lambda _:canvas.configure(scrollregion=canvas.bbox('all')))
        content_id=canvas.create_window((0,0),window=content,anchor='nw')
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(content_id,width=e.width))
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        self.quantities={}
        self.recipe_rows={}
        self.recipes=recipes
        for item in recipes:
            row=tk.Frame(content,bg=SURFACE,padx=19,pady=13)
            row.pack(fill='x')
            self.recipe_rows[item['recipeID']]=row
            row.columnconfigure(0,weight=1,uniform='menu')
            row.columnconfigure(1,weight=3,uniform='menu')
            row.columnconfigure(2,weight=1,uniform='menu')
            tk.Label(row,text=money(item['price']),bg=SURFACE,fg=MUTED,
                     font=(FONT,10)).grid(row=0,column=0,sticky='ew')
            tk.Label(row,text=item['name'],bg=SURFACE,fg=INK,
                     font=(FONT,12,'bold'),wraplength=300).grid(row=0,column=1,sticky='ew')
            var=tk.StringVar(value='0')
            self.quantities[item['recipeID']]=var
            var.trace_add('write',lambda *_:self.update_total())
            spin=tk.Spinbox(row,from_=0,to=99,textvariable=var,width=5,justify='center',
                           font=(FONT,12),relief='solid',bd=1)
            spin.grid(row=0,column=2,padx=8)
            spin.bind('<FocusIn>',lambda e:e.widget.icursor('end'),add='+')
        self.recipe_search.trace_add('write',lambda *_:self.filter_recipes())
        self.recipe_sort.trace_add('write',lambda *_:self.filter_recipes())
        bar=tk.Frame(box,bg=LIGHT)
        bar.pack(fill='x',pady=(10,0),before=outer)  # Always leave action buttons visible
        self.total=tk.Label(bar,text='Total   $0.00',fg=INK,bg=LIGHT,
                            font=(FONT,16,'bold'),anchor='e')
        self.total.pack(fill='x',pady=(0,8))
        actions=tk.Frame(bar,bg=LIGHT)
        actions.pack(fill='x')
        actions.columnconfigure((0,1),weight=1,uniform='order')
        action_button(actions,'Cancel',self.destroy,primary=False).grid(row=0,column=0,sticky='ew',padx=(0,5))
        action_button(actions,'Create order',self.submit).grid(row=0,column=1,sticky='ew',padx=(5,0))
        self.bind('<Escape>',lambda _:self.destroy())
        self.filter_recipes()
        self.update_total()
        center_popup(self, parent, width, height)
        self.grab_set()
        parent.wait_window(self)

    def filter_recipes(self):
        # Hide and order menu rows without resetting any quantities in the cart.
        term=self.recipe_search.get().strip().casefold()
        mode=self.recipe_sort.get()
        visible=[r for r in self.recipes if term in r['name'].casefold()]
        if mode=='Name Z–A':
            visible.sort(key=lambda r:r['name'].casefold(),reverse=True)
        elif mode=='Price: low to high':
            visible.sort(key=lambda r:(float(r['price']),r['name'].casefold()))
        elif mode=='Price: high to low':
            visible.sort(key=lambda r:(float(r['price']),r['name'].casefold()),reverse=True)
        else:
            visible.sort(key=lambda r:r['name'].casefold())
        for row in self.recipe_rows.values():row.pack_forget()
        for r in visible:self.recipe_rows[r['recipeID']].pack(fill='x')

    def update_total(self):
        if len(self.quantities) < len(self.recipes) or not hasattr(self,'total'):
            return
        total=0
        for r in self.recipes:
            raw=self.quantities[r['recipeID']].get()
            try:
                qty=int(raw)
                if qty < 0:raise ValueError()
                total+=qty*float(r['price'])
            except ValueError:
                self.total.config(text='Check quantities')
                return
        self.total.config(text=f'Total   {money(total)}')

    def submit(self):
        lines={}
        try:
            for key,var in self.quantities.items():
                raw=var.get().strip()
                if not raw.isdecimal():raise ValueError('Quantities must be nonnegative whole numbers.')
                amount=int(raw)
                if amount:lines[key]=amount
        except ValueError as exc:
            messagebox.showerror('Invalid quantity',str(exc),parent=self)
            return
        if not lines:
            messagebox.showwarning('Empty order','Select at least one recipe.',parent=self)
            return
        self.result=lines
        self.destroy()


class OnigiriDesktop(tk.Tk):
    def __init__(self, db_path=None):
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('TheOnigiriShop.Desktop')
        super().__init__()
        self.bind('<MouseWheel>',self._route_page_scroll,add='+')
        self.bind('<Button-4>',self._route_page_scroll,add='+')
        self.bind('<Button-5>',self._route_page_scroll,add='+')
        self.db_path = Path(db_path) if db_path is not None else database_path()
        self.svc = InventoryService(self.db_path)
        self.profile = ProfileService(self.db_path)
        self.users = UserManagementService(self.db_path)
        self.loyalty = LoyaltyService(self.db_path)
        self.accounting = AccountingLedger(self.db_path)
        self.payroll = PayrollService(self.db_path)
        self.feedback = FeedbackService(self.db_path)
        self.appearance = ThemePreferences(self.db_path)
        self.theme_name = DEFAULT_THEME
        set_palette(self.theme_name)
        self.user = None
        self.current_page = 'Dashboard'
        self.title('The Onigiri Shop | Restaurant Management')
        self.geometry('1230x800')
        self.minsize(760, 550)
        self.configure(bg=LIGHT)
        # Launch in true full-screen mode. F11 switches between full-screen and
        # a regular window; Escape always returns to a regular window.
        self.fullscreen = False
        self.bind('<F11>', self.toggle_fullscreen)
        self.bind('<Escape>', self.leave_fullscreen)
        self.protocol('WM_DELETE_WINDOW', self.exit_application)
        self._style()
        try:
            self.iconbitmap(default=str(resource('onigiri.ico')))
            self.iconbitmap(str(resource('onigiri.ico')))
        except (tk.TclError, OSError):
            pass
        if sys.platform == 'win32':
            from windows_icons import WindowsWindowIcons
            self._window_icons = WindowsWindowIcons(self, resource('onigiri.ico'))
        self.show_auth()
        self.set_fullscreen(True)

    def set_fullscreen(self, enabled: bool):
        """Show the application edge-to-edge on launch, with a windowed escape.

        Uses Tk's native full-screen flag on Windows, macOS and Linux. If the
        display server cannot enable it, maximize or resize to the screen.
        """
        enabled = bool(enabled)
        if enabled:
            # Explicitly size to the display as well: some Linux X servers have
            # no window manager to honor the full-screen attribute on their own.
            self.geometry(f'{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0')
            try:
                self.attributes('-fullscreen', True)
            except tk.TclError:
                try:
                    self.state('zoomed')
                except tk.TclError:
                    self.geometry(f'{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0')
        else:
            try:
                self.attributes('-fullscreen', False)
            except tk.TclError:
                pass
            self.state('normal')
            width = min(1230, max(640, self.winfo_screenwidth() - 100))
            height = min(800, max(480, self.winfo_screenheight() - 100))
            self.geometry(f'{width}x{height}')
        self.fullscreen = enabled

    def toggle_fullscreen(self, _event=None):
        self.set_fullscreen(not self.fullscreen)

    def leave_fullscreen(self, _event=None):
        if self.fullscreen:
            self.set_fullscreen(False)

    def exit_application(self):
        """Close the desktop UI cleanly, including from the initial screen."""
        self.destroy()

    def _use_theme(self, name: str) -> None:
        """Apply palette to newly-created widgets; never touch business records."""
        self.theme_name = name if name in THEMES else DEFAULT_THEME
        set_palette(self.theme_name)
        self.configure(bg=LIGHT)
        self._style()

    def choose_theme(self, name: str) -> None:
        """Change the current account's colour scheme from Settings only."""
        if not self.user:
            raise ValueError('Sign in and open Settings to change your colour scheme.')
        self.appearance.set(name, self.user['userID'])
        self._use_theme(name)
        self.show_page('Settings')

    def page_settings(self):
        self.section('Settings',
                     'Personalize your application. Preferences are saved to your account.')
        pane = card(self.body, 26)
        pane.pack(fill='x', pady=(0, 18))
        tk.Label(pane,text='Select your colour scheme',bg=SURFACE,fg=INK,
                 font=(FONT,15,'bold'),justify='center').pack(fill='x',pady=(0,14))
        choice = tk.StringVar(value=self.theme_name)
        picker = SmoothCombobox(pane,textvariable=choice,values=list(THEMES),
                              state='readonly',justify='left',font=(FONT,12))
        picker.pack(fill='x',pady=(0,14))
        action_button(pane,'Save colour scheme',lambda:self.choose_theme(choice.get())).pack(fill='x')
        summary=tk.Label(pane,text='Classic · orange and cream  |  Sage · soft green  |  '
                 'Ocean · blue  |  Midnight · dark mode',
                 bg=SURFACE,fg=MUTED,justify='center',wraplength=350,
                 font=(FONT,10))
        summary.pack(fill='x',pady=(15,0))
        pane.bind('<Configure>',lambda e:summary.configure(
            wraplength=max(120,e.width-55)))
        note=tk.Label(self.body,text='This setting changes the interface only. '
                 'Your orders, points, profiles and accounting records remain unchanged.',
                 bg=LIGHT,fg=MUTED,justify='center',wraplength=350)
        note.pack(fill='x')
        note.bind('<Configure>',lambda e:note.configure(
            wraplength=max(120,e.width-45)),add='+')

    def _style(self):
        style = ttk.Style(self)
        if style.theme_use()!='clam':style.theme_use('clam')
        style.configure('POS.Treeview', font=(FONT, 10), rowheight=34, background=SURFACE,
                        fieldbackground=SURFACE, foreground=INK, borderwidth=0)
        style.configure('POS.Treeview.Heading', font=(FONT, 10, 'bold'),
                        background=HEADING, foreground=INK, relief='flat', padding=8)
        style.map('POS.Treeview', background=[('selected', SELECTED)],
                  foreground=[('selected', INK)])
        style.configure('TCombobox', padding=6, font=(FONT, 11),
                        fieldbackground=ENTRY, background=SECONDARY, foreground=INK,
                        selectbackground=ENTRY, selectforeground=INK)
        style.map('TCombobox', fieldbackground=[('readonly',ENTRY)],
                  foreground=[('readonly',INK)])
        modern_controls(self,THEMES[self.theme_name])

    def clear(self):
        self._cancel_nav_animation()
        self._shell_signature=None
        if getattr(self,'_clock_after_id',None):
            self.after_cancel(self._clock_after_id)
            self._clock_after_id=None
        for child in self.winfo_children():
            child.destroy()
        self.data_tree=None

    def ask(self, title, fields, help_text='', confirm='Save', **options):
        dlg = InputDialog(self, title, fields, help_text, confirm, **options)
        return dlg.result

    def run_action(self, fn, *, refresh=True, success=None):
        try:
            if not self._authorize(getattr(self, '_action_roles', ())):
                return None
            outcome = fn()
            if success:
                messagebox.showinfo('Saved', success, parent=self)
            if refresh and self.user:
                self.show_page(self.current_page)
            return outcome
        except (ValueError, sqlite3.Error, OSError) as exc:
            messagebox.showerror('Could not complete action', str(exc), parent=self)
            return None

    def _authorize(self, roles=()):
        """Revalidate the session even if an account changed while a form was open."""
        if not self.user:
            messagebox.showwarning('Sign in required', 'Please sign in first.', parent=self)
            return False
        try:
            live = self.svc._read('''SELECT name,username,role FROM "User"
                WHERE userID=? AND accountActive=1 AND passwordHash IS NOT NULL''',
                (self.user['userID'],))
        except (sqlite3.Error, OSError) as exc:
            messagebox.showerror('Session check failed', str(exc), parent=self)
            return False
        if not live:
            messagebox.showwarning('Session expired',
                'This account is no longer active. Please sign in again.', parent=self)
            self.show_auth()
            return False
        self.user.update(live[0])
        if roles and self.user['role'] not in roles:
            messagebox.showerror('Access denied',
                'This action is available to ' + ' or '.join(roles) + ' accounts only.', parent=self)
            return False
        # Recheck the role after a modal form, before its action runs.
        if not roles and self.current_page not in self.allowed_pages():
            messagebox.showerror('Access denied',
                'Your account no longer has access to this page.', parent=self)
            self.current_page='Dashboard'
            self.show_page('Dashboard')
            return False
        return True

    def show_auth(self):
        """Centered start screen; hide decorative panel when the window narrows."""
        self.user = None
        # The welcome/login screen has no appearance controls and always uses Classic.
        # Each user-specific theme is applied after successful login.
        self._use_theme(DEFAULT_THEME)
        self.clear()
        background=tk.Frame(self,bg=LIGHT)
        background.pack(fill='both',expand=True)
        left=tk.Frame(background,bg=DARK,padx=30,pady=28)
        left.pack(side='left',fill='both',expand=True)
        tk.Label(left,text='●  THE ONIGIRI SHOP',bg=DARK,fg=SIDE_ACCENT,
                 font=(FONT,15,'bold'),justify='center').pack(fill='x',pady=(12,0))
        tk.Label(left,text='Fresh food.\nSmarter service.',bg=DARK,fg='white',
                 font=(FONT,32,'bold'),justify='center').pack(fill='x',expand=True)
        tk.Label(left,text='One workspace for the restaurant.\nOrders, loyalty, payroll, accounts, trends and feedback.',
                 bg=DARK,fg=SIDE_MUTED,font=(FONT,11),justify='center',wraplength=370).pack(fill='x')
        tk.Label(left,text='THE ONIGIRI SHOP  /  DESKTOP',bg=DARK,fg=SIDE_MUTED,
                 font=(FONT,9,'bold'),justify='center').pack(fill='x',pady=(25,0))
        right=tk.Frame(background,bg=LIGHT,padx=38)
        right.pack(side='right',fill='both',expand=True)
        form=tk.Frame(right,bg=LIGHT)
        form.place(relx=.5,rely=.5,anchor='center',relwidth=.98)
        tk.Label(form,text='Welcome back',bg=LIGHT,fg=INK,
                 font=(FONT,27,'bold'),justify='center').pack(fill='x')
        has_logins=self.svc.has_logins()
        caption=('Create your first Owner account to begin.' if not has_logins
                 else 'Sign in to your restaurant workspace.')
        subtitle=tk.Label(form,text=caption,bg=LIGHT,fg=MUTED,font=(FONT,11),
                          anchor='center',justify='center')
        subtitle.pack(fill='x',pady=(8,20))
        form.bind('<Configure>',lambda e:subtitle.configure(wraplength=max(120,e.width-18)))
        if not has_logins:
            action_button(form,'Set up Owner account',self.register_owner).pack(fill='x',pady=(3,12))
            tk.Label(form,text='Sample users are not loaded automatically.',bg=LIGHT,fg=MUTED,
                 font=(FONT,9),justify='center',wraplength=300).pack(fill='x')
        else:
            user_var,pass_var=tk.StringVar(),tk.StringVar()
            for label,var,hidden in [('Username',user_var,False),('Password',pass_var,True)]:
                tk.Label(form,text=label,bg=LIGHT,fg=INK,font=(FONT,10,'bold'),
                         justify='center').pack(fill='x',pady=(7,6))
                field=tk.Entry(form,textvariable=var,font=(FONT,12),relief='solid',bd=1,
                               justify='center',bg=SURFACE,fg=INK,show='•' if hidden else '')
                field.pack(fill='x',ipady=7)
                if not hidden:field.focus_set()
            def login():
                try:
                    self.user=self.svc.login(user_var.get(),pass_var.get())
                    self._use_theme(self.appearance.get(self.user['userID']))
                    self.show_page('Dashboard')
                except InventoryError as exc:
                    messagebox.showerror('Login failed',str(exc),parent=self)
            action_button(form,'Log in  →',login).pack(fill='x',pady=(15,8))
            self.bind('<Return>',lambda _e:login())
        action_button(form,'Exit Application',self.exit_application,primary=False).pack(fill='x',pady=(14,0))
        tk.Label(form,text='F11: full screen  ·  Esc: windowed mode',bg=LIGHT,fg=MUTED,
                 font=(FONT,9),justify='center').pack(fill='x',pady=(10,0))
        def resize_auth(event):
            if event.widget is not background:return
            compact=event.width<1130
            if compact and left.winfo_manager():
                left.pack_forget()
            elif not compact and not left.winfo_manager():
                left.pack(side='left',fill='both',expand=True,before=right)
            right.configure(padx=24 if compact else 38)
        background.bind('<Configure>',resize_auth)

    def register_owner(self):
        self._register_new_user('Owner')

    def _register_new_user(self, role):
        if role != 'Owner':
            messagebox.showerror('Unavailable', 'An Owner or staff member must create Customer accounts.', parent=self)
            return
        if role == 'Owner' and self.svc.has_logins():
            messagebox.showerror('Unavailable', 'Owner setup is for the first account only.')
            return
        fields = [('name','Full name','','text'),('username','Username','','text'),
                  ('password','Password (at least 8 characters)','','password'),
                  ('email','Email address (optional)','','text'),
                  ('phone','Phone number (optional)','','text'),
                  ('dob','Date of birth (YYYY-MM-DD, optional)','','text')]
        result = self.ask(f'Create {role} account', fields, confirm='Create account')
        if result is None:
            return
        def submit():
            user_id = self.svc.create_user(result['name'], result['username'], result['password'],
                role, email=result['email'] or None, phone_number=result['phone'] or None,
                date_of_birth=result['dob'] or None)
            messagebox.showinfo('Account created', f'Your {role} account is ready (user #{user_id}).\nPlease log in.', parent=self)
            self.show_auth()
        try:
            submit()
        except (ValueError, sqlite3.Error, OSError) as exc:
            messagebox.showerror('Could not create account', str(exc), parent=self)

    def show_page(self, page):
        if not self.user:
            self.show_auth()
            return
        if not self._authorize(('Owner','Employee','Customer')):
            return
        allowed = self.allowed_pages()
        if page not in allowed:
            page = 'Dashboard'
        self.current_page = page
        signature=(self.user['userID'],self.user['role'],self.theme_name)
        if getattr(self,'_shell_signature',None)==signature:
            for child in self.body.winfo_children():child.destroy()
            self.trend_results=None
            self.header_title.config(text=title_label(page))
            for name,button in self.nav_buttons.items():
                button.config(bg=DARK)
                button._normal_bg=button.cget('bg')
            for name,button in self.footer_buttons.items():
                button.config(bg=ACCENT if name==page else SIDE_BUTTON)
                button._normal_bg=button.cget('bg')
            self.page_canvas.yview_moveto(0)
            self._render_current_page()
            self._animate_navigation(page)
            return
        self.unbind('<Return>')
        self.clear()
        base = tk.Frame(self, bg=LIGHT)
        base.pack(fill='both', expand=True)
        sidebar = tk.Frame(base, bg=DARK, width=230)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text='●  ONIGIRI', bg=DARK, fg=SIDE_ACCENT,
                 font=(FONT, 17, 'bold'), padx=12, pady=25).pack(fill='x')
        tk.Frame(sidebar, bg=SIDE_DIVIDER, height=1).pack(fill='x', padx=18, pady=(0, 22))
        # The new combined system contains more than a screenful of modules.
        # Keep all of them reachable at 768p / 1080p using a scrollable sidebar.
        nav_shell = tk.Frame(sidebar, bg=DARK)
        nav_shell.pack(fill='both', expand=True)
        nav_canvas = tk.Canvas(nav_shell, bg=DARK, highlightthickness=0, bd=0)
        nav_scroll = AutoScrollbar(nav_shell, orient='vertical', command=nav_canvas.yview)
        nav_items = tk.Frame(nav_canvas, bg=DARK)
        item_window = nav_canvas.create_window((0, 0), window=nav_items, anchor='nw')
        nav_items.bind('<Configure>', lambda e: nav_canvas.configure(scrollregion=nav_canvas.bbox('all')))
        nav_canvas.bind('<Configure>', lambda e: nav_canvas.itemconfigure(item_window, width=e.width, height=nav_items.winfo_reqheight()))
        nav_canvas.configure(yscrollcommand=nav_scroll.set)
        nav_scroll.pack(side='right', fill='y')
        nav_canvas.pack(side='left', fill='both', expand=True)
        def scroll_nav(event):
            direction = -1 if (event.delta > 0 or getattr(event, 'num', 0) == 4) else 1
            return scroll_if_needed(nav_canvas, direction)
        for widget in (nav_canvas, nav_items):
            widget.bind('<MouseWheel>', scroll_nav)
            widget.bind('<Button-4>', scroll_nav)
            widget.bind('<Button-5>', scroll_nav)
        self.nav_buttons = {}
        for name in allowed:
            if name in ('Settings', 'My profile'):
                continue  # Settings is pinned below the scrollable module list.
            active = name == page
            button = tk.Button(nav_items, text=title_label(name), anchor='w', bd=0, cursor='hand2',
                               bg=DARK, highlightthickness=0,
                               fg=SIDE_TEXT,
                               activebackground=SIDE_HOVER, activeforeground='white',
                               padx=17, pady=7, font=(FONT, 10),
                               command=lambda p=name:self.show_page(p))
            button.pack(fill='x')
            hover_button(button)
            self.nav_buttons[name] = button
            button.bind('<MouseWheel>', scroll_nav)
            button.bind('<Button-4>', scroll_nav)
            button.bind('<Button-5>', scroll_nav)
        self.nav_indicator=tk.Frame(nav_items,bg=ACCENT)
        # The moving canvas clips stationary bold copies of the menu labels.
        # Only the highlight moves: text keeps its position in the sidebar.
        self.nav_highlight=tk.Canvas(self.nav_indicator,bg=ACCENT,bd=0,
            highlightthickness=0,takefocus=False,cursor='hand2')
        self.nav_highlight.pack(fill='both',expand=True)
        self.nav_text_ids={name:self.nav_highlight.create_text(17,0,text=title_label(name),
            anchor='w',fill='white',font=(FONT,10,'bold')) for name in self.nav_buttons}
        self.nav_highlight.bind('<Button-1>',self._click_nav_highlight)
        tk.Frame(self.nav_indicator,bg=SIDE_ACCENT,width=4).place(x=0,y=0,relheight=1)
        for widget in (self.nav_indicator,self.nav_highlight):
            widget.bind('<MouseWheel>',scroll_nav)
        self.update_idletasks()
        selected=self.nav_buttons.get(page)
        if selected:
            self._position_nav_highlight(selected.winfo_y(),selected.winfo_height())
        tk.Label(sidebar, text=f"{self.user['name'].upper()}\n{self.user['role']} | {self.user['username']}",
                 justify='center', bg=DARK, fg=SIDE_MUTED, font=(FONT,10), pady=12).pack(fill='x')
        self.footer_buttons={}
        for name in ('My profile','Settings'):
            footer_button=tk.Button(sidebar,text=title_label(name),command=lambda p=name:self.show_page(p),
                bg=ACCENT if page==name else SIDE_BUTTON,fg='white',bd=0,
                font=(FONT,11,'bold'),pady=12)
            footer_button.pack(fill='x',padx=12,pady=5);hover_button(footer_button);self.footer_buttons[name]=footer_button
        container = tk.Frame(base, bg=LIGHT)
        container.pack(side='left', fill='both', expand=True)
        top = tk.Frame(container, bg=LIGHT, padx=18, pady=11)
        top.pack(fill='x')
        top.columnconfigure(0,weight=1,uniform='header')
        top.columnconfigure(1,weight=3,uniform='header')
        top.columnconfigure(2,weight=1,uniform='header')
        self.clock_label=tk.Label(top,bg=LIGHT,fg=MUTED,font=(FONT,10,'bold'),anchor='w')
        self.clock_label.grid(row=0,column=0,sticky='ew')
        self._tick_clock()
        self.header_title=tk.Label(top,text=title_label(page),fg=INK,bg=LIGHT,font=(FONT,22,'bold'),anchor='center')
        self.header_title.grid(row=0,column=1,sticky='ew')
        account_actions=tk.Frame(top,bg=LIGHT)
        account_actions.grid(row=0,column=2,sticky='e')
        action_button(account_actions,'Log out',self.show_auth,primary=False,small=True).pack(side='left',padx=(0,8))
        action_button(account_actions,'Exit',self.exit_application,primary=False,small=True).pack(side='left')
        # The page itself scrolls. Buttons, summaries and tables cannot disappear
        # underneath the bottom edge on shorter laptop and tablet-size windows.
        page_shell=tk.Frame(container,bg=LIGHT)
        page_shell.pack(fill='both',expand=True)
        self.page_canvas=tk.Canvas(page_shell,bg=LIGHT,highlightthickness=0)
        page_scroll=AutoScrollbar(page_shell,orient='vertical',command=self.page_canvas.yview)
        self.body=tk.Frame(self.page_canvas,bg=LIGHT,padx=20,pady=12)
        window=self.page_canvas.create_window((0,0),window=self.body,anchor='nw')
        self.body.bind('<Configure>',lambda _e:self.page_canvas.configure(scrollregion=self.page_canvas.bbox('all')))
        self.page_canvas.bind('<Configure>',lambda e:self.page_canvas.itemconfigure(window,width=e.width))
        self.page_canvas.configure(yscrollcommand=page_scroll.set)
        page_scroll.pack(side='right',fill='y')
        self.page_canvas.pack(side='left',fill='both',expand=True)
        self.page_canvas.bind('<MouseWheel>',self._scroll_page)
        self.page_canvas.bind('<Button-4>',lambda _e:scroll_if_needed(self.page_canvas,-2))
        self.page_canvas.bind('<Button-5>',lambda _e:scroll_if_needed(self.page_canvas,2))
        self._shell_signature=signature
        self._render_current_page()

    def _cancel_nav_animation(self):
        pending=getattr(self,'_nav_after',None)
        if pending:self.after_cancel(pending)
        self._nav_after=None

    def _animate_navigation(self,page):
        self._cancel_nav_animation()
        indicator=getattr(self,'nav_indicator',None)
        target=self.nav_buttons.get(page)
        if not indicator or not indicator.winfo_exists():return
        if not target:
            indicator.place_forget();return
        self.update_idletasks()
        start=indicator.winfo_y() if indicator.winfo_ismapped() else target.winfo_y()
        end=target.winfo_y()
        started=perf_counter()
        def step():
            self._nav_after=None
            progress=min(1,(perf_counter()-started)/.11)
            fraction=progress*progress*(3-2*progress)
            self._position_nav_highlight(round(start+(end-start)*fraction),target.winfo_height())
            if progress<1:self._nav_after=self.after(8,step)
        step()

    def _position_nav_highlight(self,top,height):
        self.nav_indicator.place(x=0,y=top,relwidth=1,height=height)
        for name,button in self.nav_buttons.items():
            self.nav_highlight.coords(self.nav_text_ids[name],17,
                button.winfo_y()+button.winfo_height()/2-top)
        self.nav_indicator.lift()

    def _click_nav_highlight(self,event):
        y=self.nav_indicator.winfo_y()+event.y
        for name,button in self.nav_buttons.items():
            if button.winfo_y()<=y<button.winfo_y()+button.winfo_height():
                self.show_page(name)
                break
        return 'break'

    def _render_current_page(self):
        pages = {'Dashboard':self.page_dashboard, 'Inventory':self.page_inventory,
                 'Recipes':self.page_recipes, 'Orders':self.page_orders,
                 'Suppliers':self.page_suppliers, 'Purchase orders':self.page_purchases,
                 'Alerts':self.page_alerts, 'Inventory history':self.page_history,
                 'Loyalty':self.page_loyalty, 'My profile':self.page_profile,
                 'Settings':self.page_settings,
                 'Users':self.page_users, 'Demo & backups':self.page_demo,
                 'Accounting':self.page_accounting, 'Payroll':self.page_payroll,
                 'Feedback':self.page_feedback, 'Trends':self.page_trends}
        try:
            pages[self.current_page]()
            def normalize(parent):
                for child in parent.winfo_children():
                    if isinstance(child,tk.Button):
                        child.configure(text=title_label(child.cget('text')))
                        hover_button(child)
                    normalize(child)
            normalize(self.body)

        except (ValueError, sqlite3.Error, OSError) as exc:
            tk.Label(self.body, text=f'Unable to load page: {exc}', fg=RED,
                     bg=LIGHT, font=(FONT, 11)).pack(anchor='w')

    def _scroll_page(self, event):
        return scroll_if_needed(self.page_canvas,-1 if event.delta>0 else 1)

    def _route_page_scroll(self, event):
        canvas=getattr(self,'page_canvas',None)
        if not canvas or not canvas.winfo_exists():return
        if not str(event.widget).startswith(str(canvas)+'.'):return
        if isinstance(event.widget,(ttk.Treeview,ttk.Combobox,tk.Text,tk.Entry)):return
        up=getattr(event,'delta',0)>0 or getattr(event,'num',0)==4
        return scroll_if_needed(canvas,-2 if up else 2)

    def _tick_clock(self):
        if self.clock_label.winfo_exists():
            self.clock_label.config(text=datetime.now(EST).strftime('%H:%M:%S %b %d, %Y EST'))
            if getattr(self,'feedback_badge',None) and self.feedback_badge.winfo_exists() and self.user and self.user['role'] in ('Owner','Employee'):
                try:
                    count=len(self.feedback.view_feedback(self.user['userID'],status='Submitted'))
                    self.feedback_badge.config(text=title_label(f'\U0001f514 Feedback ({count} awaiting review)'))
                except ValueError:pass
            self._clock_after_id=self.after(1000,self._tick_clock)

    def destroy(self):
        self._cancel_nav_animation()
        if getattr(self,'_clock_after_id',None):
            self.after_cancel(self._clock_after_id)
            self._clock_after_id=None
        super().destroy()

    def allowed_pages(self):
        if self.user['role'] == 'Customer':
            return ['Dashboard', 'Loyalty', 'Feedback', 'My profile', 'Settings']
        pages = ['Dashboard','Inventory','Recipes','Orders','Suppliers',
                 'Purchase orders','Alerts','Inventory history','Loyalty','Feedback','Trends','My profile','Settings']
        if self.user['role']=='Owner':
            pages += ['Accounting','Payroll','Users','Demo & backups']
        return pages

    def section(self, title, subtitle=None, buttons=None):
        """Centered headings and a responsive action grid; no clipped toolbar buttons."""
        heading=tk.Frame(self.body,bg=LIGHT)
        heading.pack(fill='x',pady=(0,12))
        tk.Label(heading,text=title_label(title),font=(FONT,16,'bold'),fg=INK,bg=LIGHT,
                 justify='center').pack(fill='x',pady=(2,3))
        if subtitle:
            text=tk.Label(heading,text=subtitle,font=(FONT,10),fg=MUTED,bg=LIGHT,
                          justify='center')
            text.pack(fill='x',pady=(0,7))
            heading.bind('<Configure>',lambda e:text.configure(wraplength=max(180,e.width-22)))
        actions=buttons or []
        if not actions:return
        panel=tk.Frame(heading,bg=LIGHT)
        panel.pack(fill='x',pady=(8,7))
        widgets=[action_button(panel,label,callback,primary=(i==0),small=True)
                 for i,(label,callback) in enumerate(actions)]
        state={'cols':None}
        def reflow(event=None):
            width=event.width if event is not None else panel.winfo_width()
            cols=1 if width<470 else 2 if width<800 else 3
            if state['cols']==cols:return
            state['cols']=cols
            for b in widgets:b.grid_forget()
            for j in range(3):panel.columnconfigure(j,weight=1 if j<cols else 0,uniform='actions' if j<cols else '')
            for i,b in enumerate(widgets):
                b.grid(row=i//cols,column=i%cols,sticky='ew',padx=4,pady=4)
        panel.bind('<Configure>',reflow)

    def table(self, rows, cols, *, height=12, parent=None, **options):
        """Filter, sort, and horizontally scroll every management table.

        Search is case-insensitive; numeric values sort numerically. Header clicks
        also sort. The controls and list remain usable at narrow window sizes.
        """
        wrap=card(parent or self.body,12)
        wrap.pack(fill='x',pady=(0,14))
        keys=[key for key,_ in cols]
        if not keys:
            tk.Label(wrap,text='No records yet.',font=(FONT,11),bg=SURFACE,
                     fg=MUTED,justify='center',pady=20).pack(fill='x')
            self.data_tree=None
            return None
        dataset=[dict(r) for r in rows]
        toolbar=tk.Frame(wrap,bg=SURFACE)
        toolbar.pack(fill='x',pady=(0,9))
        # Controls wrap into two rows to remain usable on 1024px displays.
        controls=tk.Frame(toolbar,bg=SURFACE)
        controls.pack(fill='x')
        query=tk.StringVar()
        filter_var=tk.StringVar(value='All columns')
        sort_var=tk.StringVar(value=options.get('sort_by',cols[0][1]))
        direction=tk.StringVar(value=options.get('direction','Ascending'))
        status_field=next((k for k in ('status','transactionType','role','isActive') if k in keys),None)
        contracts={
            'Alerts':('status',['Open','Reviewed','Closed'],'low-stock alerts'),
            'Orders':('status',['Pending','Completed','Cancelled'],'orders'),
            'Purchase orders':('status',['Confirmed','Partially Received','Received'],'purchase orders'),
            'Payroll':('status',['Draft','Approved','Paid'],'payroll runs'),
            'Feedback':('status',['Submitted','Reviewed'],'feedback submissions'),
            'Loyalty':('isActive',['Yes','No'],'rewards'),
            'Users':('status',['Active','Inactive'],'user accounts'),
            'Accounting':('transactionType',['Sale','Purchase','Expense','Inventory Adjustment'],'transactions')}
        contract=contracts.get(self.current_page)
        if contract and contract[0] in keys:
            status_field=contract[0];status_options=['All']+contract[1];entity=contract[2]
        else:
            status_options=['All']+sorted({format_table_value(status_field,r.get(status_field,'')) for r in dataset}) if status_field else ['All']
            entity='records'
        status=tk.StringVar(value='All')
        def label(parent,text):
            tk.Label(parent,text=text,bg=SURFACE,fg=MUTED,font=(FONT,9,'bold'),
                     justify='center').pack(fill='x',pady=(0,3))
        filter_groups=[]
        def input_group(text,widget):
            box=tk.Frame(controls,bg=SURFACE)
            filter_groups.append(box)
            label(box,text)
            widget(box).pack(fill='both',expand=True)
        input_group('Search',lambda p:tk.Entry(p,textvariable=query,justify='center',
             font=(FONT,10),relief='solid',bd=1))
        input_group('Search in',lambda p:SmoothCombobox(p,values=['All columns']+[v for _,v in cols],
             textvariable=filter_var,state='readonly',width=13))
        input_group('Sort by',lambda p:SmoothCombobox(p,values=[v for _,v in cols],
             textvariable=sort_var,state='readonly',width=12))
        input_group('Direction',lambda p:SmoothCombobox(p,values=['Ascending','Descending'],
             textvariable=direction,state='readonly',width=12))
        if status_field:
            input_group('Reward Active' if status_field=='isActive' else 'Filter '+status_field.replace('transaction','').title(),
             lambda p:SmoothCombobox(p,values=status_options,textvariable=status,
                                  state='readonly',width=12))
        # Arrange search/sort selectors in multiple rows when the app is windowed.
        filter_layout={'cols':None}
        def layout_filters(event):
            n=2 if event.width<630 else 3 if event.width<890 else len(filter_groups)
            if filter_layout['cols']==n:return
            filter_layout['cols']=n
            for group in filter_groups:group.grid_forget()
            for col in range(len(filter_groups)):
                controls.columnconfigure(col,weight=1 if col<n else 0)
            for index,group in enumerate(filter_groups):
                group.grid(row=index//n,column=index%n,sticky='nsew',padx=4,pady=4)
        controls.bind('<Configure>',layout_filters)
        # Use root window width for the initial configuration, rather than
        # depending on an after-idle callback which can fire after a page is gone.
        first_n=2 if self.winfo_width()<1160 else 3
        filter_layout['cols']=first_n
        for column in range(first_n):controls.columnconfigure(column,weight=1)
        for index,group in enumerate(filter_groups):
            group.grid(row=index//first_n,column=index%first_n,sticky='nsew',padx=4,pady=4)
        total_label=tk.Label(toolbar,bg=SURFACE,fg=MUTED,font=(FONT,9),justify='center')
        total_label.pack(fill='x',pady=(7,0))
        holder=tk.Frame(wrap,bg=SURFACE)
        holder.pack(fill='x')
        tree=ttk.Treeview(holder,columns=keys,show='headings',height=min(height,11),style='POS.Treeview')
        preferred = preferred_table_widths(dataset, cols)
        for key,title in cols:
            tree.heading(key,text=title_label(title),anchor='center')
            alignment='center'
            tree.column(key,width=preferred[key],minwidth=85,
                        anchor=alignment,stretch=False)
        # This is shared by Accounting, Payroll, Orders, Users, Inventory,
        # Loyalty, and the other management tabs. Resize to match the window:
        # full-width headers on large screens, scrollable data on small ones.
        tree.bind('<Configure>', lambda e: size_table_columns(tree, preferred, e.width))
        tree.bind('<ButtonRelease-1>',lambda e:size_table_columns(tree,preferred,tree.winfo_width()),add='+')
        tree.tag_configure('hover',background=darken_color(SURFACE))
        table_hover(tree)
        vertical=AutoScrollbar(holder,command=tree.yview,orient='vertical')
        horizontal=AutoScrollbar(holder,command=tree.xview,orient='horizontal')
        tree.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        holder.columnconfigure(0,weight=1);holder.rowconfigure(0,weight=1)
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
        tree.grid(row=0,column=0,sticky='nsew')
        title_to_key={title:key for key,title in cols}
        def sort_key(row,key):
            value=row.get(key)
            if value is None:return (2,'')
            try:return (0,float(value))
            except (TypeError,ValueError):return (1,str(value).casefold())
        empty_label=tk.Label(wrap,bg=SURFACE,fg=MUTED,wraplength=700)
        self.empty_label=empty_label
        def redraw(*_):
            phrase=query.get().strip().casefold()
            filt=title_to_key.get(filter_var.get())
            sort=title_to_key.get(sort_var.get(),keys[0])
            data=[r for r in dataset
                  if (not phrase or any(phrase in str(r.get(k,'')).casefold()
                      for k in ([filt] if filt else keys)))
                  and (not status_field or status.get()=='All'
                       or format_table_value(status_field,r.get(status_field,''))==status.get())]
            data.sort(key=lambda r:sort_key(r,sort),reverse=(direction.get()=='Descending'))
            tree.delete(*tree.get_children())
            for row in data:
                tree.insert('','end',values=[format_table_value(k,row.get(k)) for k in keys])
            total_label.config(text=f'Showing {len(data)} of {len(dataset)} records')
            if not data:
                selected=status.get()
                text=(f'No {selected.lower()} {entity} to display.' if selected!='All' else f'No {entity} to display.')
                if status_field=='isActive' and selected in ('Yes','No'):
                    text='No '+('active' if selected=='Yes' else 'inactive')+' rewards to display.'
                if phrase:text+=' No records match the search text; clear the search or change filters.'
                empty_label.config(text=text);empty_label.pack(fill='x',pady=8)
            else:empty_label.pack_forget()
        query.trace_add('write',redraw)
        for v in (filter_var,sort_var,direction,status):v.trace_add('write',redraw)
        for key,title in cols:
            def sort_by(k=key,t=title):
                if sort_var.get()==t:
                    direction.set('Descending' if direction.get()=='Ascending' else 'Ascending')
                else:
                    sort_var.set(t)
                    direction.set('Ascending')
            tree.heading(key,text=title_label(title),command=sort_by)
        redraw()
        def show_detail(_event=None):
            selected=tree.selection()
            if not selected:return
            values=tree.item(selected[0],'values')
            if parent is None and self.user['role']!='Customer' and self.current_page in ('Recipes','Orders','Suppliers','Purchase orders','Loyalty'):
                self.open_record(self.current_page,values[0])
            else:self.details_dialog('Full record details', '\n'.join(f'{title}: {values[i]}' for i,(_,title) in enumerate(cols)))
        tree.bind('<Double-1>',show_detail)
        self.data_tree=tree
        self.table_controls={'query':query,'column':filter_var,'sort':sort_var,
                             'direction':direction,'status':status}
        return tree

    def selected_id(self) -> str:
        """First column (ID) of the currently highlighted data row."""
        tree=getattr(self,'data_tree',None)
        if tree and tree.winfo_exists() and tree.selection():
            values=tree.item(tree.selection()[0],'values')
            return str(values[0]) if values else ''
        return ''

    def display_card(self, parent, title, value, detail=''):
        """Center dashboard-style card contents with responsive text wrapping.

        Dashboard, loyalty and accounting share this card renderer. Equal grid
        columns keep the card group balanced even when labels have different
        lengths; text wraps when the app is changed to a smaller window.
        """
        column = len(parent.grid_slaves(row=0))
        parent.columnconfigure(column, weight=1, uniform='summary_cards')
        frame = card(parent)
        frame.grid(row=0, column=column, sticky='nsew', padx=6)
        # Wrapped labels must not resize the same columns used to choose their
        # wrap length; that feedback can keep Tk's geometry loop running forever.
        frame.configure(width=180, height=150)
        frame.pack_propagate(False)
        heading = tk.Label(frame, text=str(title).upper(), font=(FONT, 9, 'bold'),
                           fg=MUTED, bg=SURFACE, anchor='center', justify='center')
        heading.pack(fill='x')
        amount = tk.Label(frame, text=str(value), font=(FONT, 23, 'bold'),
                          fg=INK, bg=SURFACE, anchor='center', justify='center')
        amount.pack(fill='x', pady=(7, 4))
        explanation = tk.Label(frame, text=detail, font=(FONT, 9), fg=MUTED,
                               bg=SURFACE, anchor='center', justify='center')
        explanation.pack(fill='x')

        def keep_text_inside_card(event):
            limit = max(75, event.width - 45)
            for label in (heading, amount, explanation):
                if label.cget('wraplength') != limit:
                    label.configure(wraplength=limit)
            height=max(150,sum(label.winfo_reqheight() for label in (heading,amount,explanation))+51)
            if int(frame.cget('height')) != height:
                frame.configure(height=height)

        frame.bind('<Configure>', keep_text_inside_card, add='+')
        return frame

    def page_dashboard(self):
        tk.Label(self.body, text=f"Good to see you, {self.user['name'].split()[0]}. 👋",
                 bg=LIGHT, fg=INK, font=(FONT, 21, 'bold'),justify='center').pack(fill='x', pady=(3, 6))
        tk.Label(self.body, text='Here is what is happening across your shop today.',
                 bg=LIGHT, fg=MUTED, font=(FONT, 11),justify='center').pack(fill='x', pady=(0, 26))
        row = tk.Frame(self.body, bg=LIGHT)
        row.pack(fill='x', pady=(0, 25))
        if self.user['role'] == 'Customer':
            try:
                cid = self.loyalty.customer_id_for_user(self.user['userID'])
                acc = self.loyalty.retrieve_customer_account(cid)
                balance = str(acc['pointsBalance'])
            except AccountNotFoundError:
                balance = 'Not enrolled'
            self.display_card(row, 'Loyalty points', balance, '10 points per $1 CAD')
            self.display_card(row, 'Available recipes', str(len(self.svc.recipes())), 'Explore the menu')
            self.display_card(row, 'My role', 'Customer', 'My profile is available')
        else:
            inv, orders, alerts = self.svc.inventory(),self.svc.customer_orders(),self.svc.alerts()
            self.display_card(row, 'Ingredients', str(len(inv)), 'Tracked stock items')
            self.display_card(row, 'Orders', str(len(orders)), 'Pending and completed')
            self.display_card(row, 'Low stock', str(len(alerts)), 'Items needing attention')
        if self.user['role'] in ('Owner','Employee'):
            count=len(self.feedback.view_feedback(self.user['userID'],status='Submitted'))
            self.feedback_badge=action_button(self.body,f'\U0001f514 Feedback ({count} awaiting review)',
                lambda:self.show_page('Feedback'),primary=False,small=True)
            self.feedback_badge.pack(fill='x',pady=(0,12))
        panel = card(self.body, 26)
        panel.pack(fill='x')
        tk.Label(panel, text='QUICK ACTIONS', bg=SURFACE, fg=MUTED,
                 font=(FONT, 10, 'bold'), anchor='center', justify='center').pack(fill='x', pady=(0,15))
        shortcuts = [('My profile', 'My profile'),('Loyalty program','Loyalty')]
        if self.user['role'] != 'Customer':
            shortcuts += [('Browse recipes','Recipes')]
            shortcuts += [('Manage inventory','Inventory'),('Customer orders','Orders')]
            if self.user['role']=='Owner':
                shortcuts += [('Accounting','Accounting'),('Payroll','Payroll')]
            shortcuts += [('Trends','Trends'),('Feedback','Feedback')]
        action_grid=tk.Frame(panel,bg=SURFACE)
        action_grid.pack(fill='x')
        quick_buttons=[action_button(action_grid,label,lambda p=page:self.show_page(p),
                                     primary=False,small=True) for label,page in shortcuts]
        quick_layout={'cols':None}
        def reflow_quick(e):
            cols=1 if e.width<460 else 2 if e.width<850 else 3
            if quick_layout['cols']==cols:return
            quick_layout['cols']=cols
            for b in quick_buttons:b.grid_forget()
            for col in range(3):action_grid.columnconfigure(col,weight=1 if col<cols else 0)
            for i,b in enumerate(quick_buttons):b.grid(row=i//cols,column=i%cols,
                                                     sticky='ew',padx=4,pady=5)
        action_grid.bind('<Configure>',reflow_quick)
        initial_cols=2
        quick_layout['cols']=initial_cols
        for col in range(initial_cols):action_grid.columnconfigure(col,weight=1)
        for i,b in enumerate(quick_buttons):b.grid(row=i//initial_cols,column=i%initial_cols,
                                                 sticky='ew',padx=4,pady=5)
        tk.Label(self.body, text='All features share one local SQLite database. There is no real card payment processing.',
                 bg=LIGHT, fg=MUTED, font=(FONT, 9),justify='center',wraplength=650).pack(fill='x', pady=20)

    @requires_role('Owner', 'Employee')
    def page_inventory(self):
        self.section('Inventory overview','Stock levels and reorder thresholds',[
            ('+ New ingredient',self.new_ingredient),('Adjust stock',self.adjust_stock),
            ('Set reorder level',self.set_reorder),('Receive stock',self.receive_stock)])
        rows = [{**r, 'stockStatus': 'LOW' if r['quantityOnHand'] < r['reorderLevel'] else 'OK'}
                for r in self.svc.inventory()]
        self.table(rows,[('ingredientID','ID'),('ingredientName','Ingredient'),('unit','Unit'),
                         ('quantityOnHand','On hand'),('reorderLevel','Reorder at'),('stockStatus','Stock status')])

    @requires_role('Owner', 'Employee')
    def new_ingredient(self):
        a=self.ask('Add ingredient',[('name','Ingredient name','','text'),('unit','Unit (g / ml / pieces)','','text'),
          ('qty','Starting quantity','0','text'),('level','Reorder level','0','text')])
        if a:self.run_action(lambda:self.svc.add_ingredient(a['name'],a['unit'],a['qty'],a['level'],self.user['userID']),success='Ingredient added.')

    @requires_role('Owner', 'Employee')
    def set_reorder(self):
        a=self.ask('Update reorder level',[('id','Ingredient ID',self.selected_id(),'text'),('level','New reorder level','','text')])
        if a:self.run_action(lambda:self.svc.set_reorder_level(a['id'],a['level']),success='Reorder level updated.')

    @requires_role('Owner', 'Employee')
    def adjust_stock(self):
        a=self.ask('Adjust inventory',[('id','Ingredient ID',self.selected_id(),'text'),('mode','Action','add','choice',['add','remove']),
          ('qty','Quantity','','text'),('note','Reason (optional)','','text'),
          ('amount','Accounting value CAD (optional)','','text')],
          'Leave the value blank for a quantity-only adjustment. No price is assumed.')
        if a:
            def save():
                self.svc.adjust_stock(a['id'],a['mode'],a['qty'],self.user['userID'],a['note'],
                    accounting_amount=a['amount'] if a['amount'] else None)
            self.run_action(save,success='Stock adjusted. ' +
                ('An Inventory Adjustment was posted to accounting.' if a['amount'] else
                 'No financial entry was posted because no value was provided.'))

    @requires_role('Owner', 'Employee')
    def receive_stock(self):
        a=self.ask('Receive supplier delivery',[('id','Ingredient ID','','text'),('qty','Quantity received','','text'),
           ('supplier','Supplier ID (optional)','','text'),('order','Purchase order ID (optional)','','text'),
           ('amount','Invoice amount CAD (optional)','','text'),('reference','Invoice reference (optional)','','text')],
           'Receive one ingredient per action. Enter only the invoice value for this receipt; do not repeat a full invoice on each line.')
        if a:
            self.run_action(lambda:self.svc.receive_delivery({_ident(a['id'], 'Ingredient ID'):a['qty']},self.user['userID'],
                  supplier_id=_ident(a['supplier'], 'Supplier ID') if a['supplier'] else None,
                  purchase_order_id=_ident(a['order'], 'Purchase order ID') if a['order'] else None,
                  purchase_amount=a['amount'] if a['amount'] else None,
                  invoice_reference=a['reference']),success='Delivery recorded. ' +
                  ('A Purchase was posted to accounting.' if a['amount'] else
                   'No financial Purchase was posted because no invoice amount was provided.'))

    @requires_role('Owner', 'Employee')
    def page_recipes(self):
        actions=[] if self.user['role']=='Customer' else [('+ New recipe',self.new_recipe),
            ('Add / update ingredient',self.recipe_ingredient),('Remove ingredient',self.remove_recipe_ingredient),('View ingredients',self.show_recipe_ingredients)]
        self.section('Menu recipes','Current dishes and ingredient lists',actions)
        self.table(self.svc.recipes(),[('recipeID','Recipe ID'),('name','Recipe'),('price','Price CAD')])

    @requires_role('Owner', 'Employee')
    def new_recipe(self):
        a=self.ask('Create recipe',[('name','Recipe name','','text'),('price','Price (CAD)','0','text')])
        if a:self.run_action(lambda:self.svc.add_recipe(a['name'],a['price']),success='Recipe created.')

    @requires_role('Owner', 'Employee')
    def recipe_ingredient(self):
        a=self.ask('Assign recipe ingredient',[('recipe','Recipe ID','','text'),
          ('ingredient','Ingredient ID','','text'),('qty','Quantity required per serving','','text')])
        if a:self.run_action(lambda:self.svc.set_recipe_ingredient(a['recipe'],a['ingredient'],a['qty']),success='Recipe ingredient saved.')

    @requires_role('Owner', 'Employee')
    def remove_recipe_ingredient(self):
        a=self.ask('Remove recipe ingredient',[('recipe','Recipe ID','','text'),
              ('ingredient','Ingredient ID','','text')],
              'Removes this ingredient requirement from the chosen recipe.',confirm='Remove ingredient')
        if a and messagebox.askyesno('Confirm','Remove this ingredient from the recipe?',parent=self):
            self.run_action(lambda:self.svc.remove_recipe_ingredient(a['recipe'],a['ingredient']),
                            success='Ingredient removed from recipe.')

    @requires_role('Owner', 'Employee')
    def show_recipe_ingredients(self):
        a=self.ask('View recipe ingredients',[('recipe','Recipe ID','','text')],confirm='View')
        if a:
            rows=self.run_action(lambda:self.svc.recipe_ingredients(a['recipe']),refresh=False)
            if rows is not None:self._records_dialog('Recipe ingredients',rows)

    @requires_role('Owner', 'Employee')
    def page_orders(self):
        self.section('Customer orders','Track pending and completed orders; order completion deducts inventory',[
            ('+ New order',self.new_order),('Complete order',self.complete_order),
            ('Cancel order',self.cancel_order),('Assign customer',self.assign_order_customer),
            ('View order lines',self.show_order_lines)])
        self.table(self.svc.customer_orders(),[('orderID','Order ID'),('orderDate','Date'),
                     ('customerID','Customer ID'),('totalAmount','Total CAD'),('status','Status'),('recipesCount','Recipes')])

    @requires_role('Owner', 'Employee')
    def new_order(self):
        recipes=self.svc.recipes()
        if not recipes:
            messagebox.showinfo('No recipes yet','Create a recipe and assign its ingredients first.',parent=self)
            return
        dialog=OrderComposer(self,recipes)
        if dialog.result:
            customer=self.ask('Customer (optional)',[('cid','Customer User ID (blank for walk-in)','','text')],
                              'For points or rewards, choose an enrolled customer. You can also assign the customer later.')
            if customer is None:return
            def call():
                cid=role_id(self.db_path,customer['cid'],'Customer') if customer['cid'] else None
                ident=self.svc.create_customer_order(dialog.result,self.user['userID'],cid)
                messagebox.showinfo('Order created',f'Order #{ident} was created as Pending.',parent=self)
            self.run_action(call)

    @requires_role('Owner', 'Employee')
    def assign_order_customer(self):
        a=self.ask('Assign customer to pending order',[('id','Order ID',self.selected_id(),'text'),
                   ('cid','Customer User ID','','text')],
                   'Find a Customer User ID in Loyalty → Find customer or the Customers list.')
        if a:self.run_action(lambda:self.svc.set_order_customer(int(a['id']),role_id(self.db_path,a['cid'],'Customer')),
                             success='Order assigned to customer.')

    @requires_role('Owner', 'Employee')
    def complete_order(self):
        a=self.ask('Complete pending order',[('id','Pending order ID',self.selected_id(),'text')],
                   'Completion deducts ingredients and posts an internal ledger sale. No real payment is charged.',
                   confirm='Continue')
        if not a:return
        def complete():
            order_id=_ident(a['id'], 'Order ID')
            order=self.svc.order_details(order_id)
            if order['status'] != 'Pending':
                raise InventoryError('Only a Pending order can be completed. No stock or points were changed.')
            cid=order.get('customerID')
            if cid:
                status=self.loyalty.customer_status(cid)
                apply_loyalty=False
                if not status['accountActive']:
                    messagebox.showinfo('Customer inactive', 'The Customer login is inactive. This order can be completed without loyalty.', parent=self)
                elif status['loyaltyAccountID'] is None:
                    if messagebox.askyesno('Enroll customer', 'This customer is not enrolled. Enroll now so this order earns points?', parent=self):
                        self.loyalty.enroll_existing_customer(status['userID'],self.user['userID'])
                        apply_loyalty=True
                elif status['loyaltyStatus'] != 'Active':
                    messagebox.showinfo('Loyalty suspended', 'An Owner must reactivate loyalty to earn or redeem points. This order can be completed without loyalty.', parent=self)
                else:
                    apply_loyalty=True
                if apply_loyalty:
                    self.loyalty.ensure_sample_rewards()
                    details=self.loyalty.view_loyalty_details(cid)
                    balance=details['account']['pointsBalance']
                    eligible=[r for r in details['rewards'] if r.get('affordable') and r['discountAmount'] <= order['totalAmount']]
                    hint=', '.join(f"{r['rewardID']}: {r['name']} ({r['pointsCost']} pts)" for r in eligible)
                    loyalty_form=self.ask('Loyalty checkout',[
                      ('reward','Reward ID (blank = earn points only)','','text')],
                      f'Customer #{cid} has {balance:,} points. Available: {hint or "none"}. '
                      'Loyalty, inventory and the ledger update together.',confirm='Review checkout')
                    if loyalty_form is None:return
                    reward=_ident(loyalty_form['reward'], 'Reward ID') if loyalty_form['reward'] else None
                    if reward is not None and reward not in {r['rewardID'] for r in eligible}:
                        raise ValueError('Choose an affordable reward applicable to this order, or leave it blank.')
                    quote=self.loyalty.preview_purchase(cid,order_id,reward_id=reward)
                    if not messagebox.askyesno('Confirm order',
                       f'Complete order #{order_id}?\nOriginal: {money(quote.purchase_amount)}\n'
                       f'Discount: {money(quote.discount_amount)}\nNet sale: {money(quote.final_amount)}\n'
                       f'Points: {quote.previous_balance} - {quote.points_redeemed} + {quote.points_earned} = {quote.new_balance}',parent=self):return
                    result=self.loyalty.complete_order_with_loyalty(self.user['userID'],cid,order_id,reward_id=reward)
                    self.show_page(self.current_page)
                    self.details_dialog('Order complete',self.loyalty.generate_receipt(result['loyaltyTransactionID']))
                    return
            if messagebox.askyesno('Confirm order',
                    f'Complete order #{order_id} and deduct inventory? Customer loyalty is not applied.',parent=self):
                result=self.svc.complete_customer_order(order_id,self.user['userID'])
                self.show_page(self.current_page)
                messagebox.showinfo('Order complete','Inventory deducted. ' +
                    ('Sale posted to accounting.' if result.get('accounting_transaction_id') else
                     'No financial Sale was posted for this zero-value order.'),parent=self)
        self.run_action(complete,refresh=False)

    @requires_role('Owner', 'Employee')
    def cancel_order(self):
        a=self.ask('Cancel order',[('id','Pending order ID',self.selected_id(),'text')],confirm='Cancel order')
        if a:self.run_action(lambda:self.svc.cancel_customer_order(a['id']),success='Order cancelled.')

    @requires_role('Owner', 'Employee')
    def show_order_lines(self):
        a=self.ask('Order line items',[('id','Order ID',self.selected_id(),'text')],confirm='View')
        if a:
            rows=self.run_action(lambda:self.svc.order_recipes(a['id']),refresh=False)
            if rows is not None:self._records_dialog('Order line items',rows)

    @requires_role('Owner', 'Employee')
    def page_suppliers(self):
        self.section('Suppliers','Contact directory for ingredient deliveries',[
            ('+ New supplier',self.add_supplier),('Receive delivery',self.receive_stock),('Set supplied ingredient',self.supplier_catalogue),
            ('View supplied ingredients',self.view_supplier_ingredients)])
        self.table(self.svc.suppliers(),[('supplierID','Supplier ID'),('name','Name'),('contactInfo','Contact')])

    @requires_role('Owner', 'Employee')
    def view_supplier_ingredients(self):
        selected=self.selected_id()
        if not selected:
            messagebox.showinfo('Select a supplier','Select a supplier row to view its supplied ingredients.',parent=self);return
        win=self.open_record('Suppliers',selected)
        notebook=next(c for c in win.winfo_children() if isinstance(c,ttk.Notebook))
        notebook.select(notebook.tabs()[-1])

    @requires_role('Owner', 'Employee')
    def add_supplier(self):
        a=self.ask('New supplier',[('name','Supplier name','','text'),('contact','Contact information','','text')])
        if a:self.run_action(lambda:self.svc.add_supplier(a['name'],a['contact']),success='Supplier saved.')

    @requires_role('Owner', 'Employee')
    def page_purchases(self):
        self.section('Purchase orders','Supplier purchase orders and outstanding quantities',[
            ('+ Create purchase order',self.create_purchase),('Receive delivery',self.receive_purchase),('View order items',self.show_purchase_lines)])
        self.table(self.svc.purchase_orders(),[('inventoryOrderID','PO ID'),('status','Status'),
                     ('orderDate','Created'),('itemsCount','Items'),('notes','Notes')])

    def select_purchase(self,*,open_only=False):
        rows=self.svc.purchase_orders()
        if open_only:rows=[r for r in rows if r['status'] in ('Confirmed','Partially Received')]
        if not rows:
            messagebox.showinfo('No purchase orders','No open purchase orders to receive.' if open_only else 'Create a purchase order first.',parent=self);return None
        choices=[f"{r['inventoryOrderID']}: {r['status']} ? {r['notes']}" for r in rows]
        selected=next((v for v in choices if v.split(':')[0]==self.selected_id()),choices[0])
        a=self.ask('Select purchase order',[('order','Purchase order',selected,'choice',choices)],confirm='Open')
        return int(a['order'].split(':')[0]) if a else None

    @requires_role('Owner','Employee')
    def show_purchase_lines(self):
        pid=self.select_purchase()
        if pid is not None:self.open_record('Purchase orders',pid)

    @requires_role('Owner','Employee')
    def receive_purchase(self):
        pid=self.select_purchase(open_only=True)
        if pid is None:return
        summary,lines,_=DetailService(self.db_path).purchase(pid)
        if not messagebox.askyesno('Receive purchase order',f'Receive items for PO #{pid} from {summary["supplier"]}?',parent=self):return
        fields=[(str(r['ingredientID']),f"{r['ingredientName']} ? outstanding {r['remaining']:g} {r['unit']}",'0','text') for r in lines if r['remaining']>0]
        fields += [('amount','Invoice amount CAD (optional)','','text'),('reference','Invoice reference (optional)','','text')]
        a=self.ask('Record partial or full delivery',fields,'Enter received quantities; leave zero for items not delivered. One invoice covers this receipt.')
        if not a:return
        def receive():
            quantities={r['ingredientID']:a[str(r['ingredientID'])] for r in lines
                if str(r['ingredientID']) in a and float(a[str(r['ingredientID'])])!=0}
            self.svc.receive_delivery(quantities,self.user['userID'],supplier_id=summary.get('supplierID'),
                purchase_order_id=pid,purchase_amount=a['amount'] or None,invoice_reference=a['reference'])
        self.run_action(receive,success='Delivery recorded. '+('Purchase posted to accounting.' if a['amount'] else 'No financial Purchase posted: no invoice amount was supplied.'))

    @requires_role('Owner','Employee')
    def create_purchase(self):
        suppliers=self.svc.suppliers();inventory=self.svc.inventory()
        if not inventory:
            messagebox.showinfo('No ingredients','Add ingredients under Inventory before creating a purchase order.',parent=self);return
        choices=['Not assigned']+[f"{r['supplierID']}: {r['name']}" for r in suppliers]
        a=self.ask('Create purchase order',[('supplier','Supplier',choices[0],'choice',choices),('notes','Notes','','text')])
        if a is None:return
        sid=int(a['supplier'].split(':')[0]) if a['supplier']!='Not assigned' else None
        if sid is not None:
            inventory=DetailService(self.db_path).supplier(sid)[2]
            if not inventory:
                messagebox.showinfo('Supplier catalogue empty','Set supplied ingredients under Suppliers before ordering from this supplier.',parent=self)
                return
        ingredient_choices=['Finish adding']+[f"{r['ingredientID']}: {r['ingredientName']} | {r['quantityOnHand']:g} {r['unit']}"+
            (' [LOW STOCK]' if r['quantityOnHand']<r['reorderLevel'] else '') for r in inventory]
        items={};costs={}
        while True:
            line=self.ask('Purchase order ingredients',[('ingredient','Ingredient / current stock',ingredient_choices[1] if not items else ingredient_choices[0],'choice',ingredient_choices),
                ('quantity','Quantity to order','','text'),('cost','Unit cost CAD (optional)','','text')],
                'Choose Finish adding to review and save. Cancel discards the entire unfinished purchase order.',confirm='Continue')
            if line is None:return
            if line['ingredient']=='Finish adding':break
            try:
                iid=int(line['ingredient'].split(':')[0]);qty=float(line['quantity'])
                from inventory_service import _quantity
                qty=_quantity(qty)
                if iid in items:raise ValueError('This ingredient is already added; finish or cancel and start again to change it.')
                if line['cost']:costs[iid]=_quantity(line['cost'],'Unit cost',zero_ok=True)
                items[iid]=qty
            except ValueError as exc:messagebox.showerror('Invalid purchase line',str(exc),parent=self)
        if not items:return
        if not messagebox.askyesno('Confirm purchase order',f'Create a purchase order with {len(items)} ingredients?',parent=self):return
        sid=int(a['supplier'].split(':')[0]) if a['supplier']!='Not assigned' else None
        self.run_action(lambda:self.svc.create_purchase_order(items,a['notes'],supplier_id=sid,unit_costs=costs),success='Purchase order created; inventory is unchanged until delivery.')

    @requires_role('Owner','Employee')
    def supplier_catalogue(self):
        suppliers=self.svc.suppliers();items=self.svc.inventory()
        if not suppliers or not items:
            messagebox.showinfo('Setup required','Add a supplier and ingredients first.',parent=self);return
        sc=[f"{r['supplierID']}: {r['name']}" for r in suppliers];ic=[f"{r['ingredientID']}: {r['ingredientName']}" for r in items]
        a=self.ask('Supplier ingredient catalogue',[('supplier','Supplier',sc[0],'choice',sc),('ingredient','Supplied ingredient',ic[0],'choice',ic)])
        if a:self.run_action(lambda:DetailService(self.db_path).set_catalogue(self.user['userID'],int(a['supplier'].split(':')[0]),int(a['ingredient'].split(':')[0])),success='Supplier catalogue updated.')

    @requires_role('Owner','Employee')
    def open_record(self,kind,ident):
        ident=_ident(ident);detail=DetailService(self.db_path)
        if kind=='Recipes':
            rows,capacity=detail.recipe(ident)
            summary=next(r for r in self.svc.recipes() if r['recipeID']==ident)
            summary['servingsAvailable']=capacity if capacity is not None else 'No ingredient requirements configured'
            tabs=[('Ingredients',rows)]
        elif kind=='Orders':
            summary,lines,loyalty,sales=detail.order(ident)
            tabs=[('Recipes ordered',lines),('Loyalty',loyalty),('Accounting Sale',sales)]
        elif kind=='Purchase orders':
            summary,lines,invoices=detail.purchase(ident);tabs=[('Ingredients ordered',lines),('Recorded invoices',invoices)]
        elif kind=='Suppliers':
            summary,orders,ingredients=detail.supplier(ident)
            tabs=[('Open purchase orders',[r for r in orders if r['status']!='Received']),
                  ('Closed purchase orders',[r for r in orders if r['status']=='Received']),('Supplied ingredients',ingredients)]
        else:
            summary=next(r for r in self.loyalty.rewards(active_only=False) if r['rewardID']==ident)
            eligible=detail.eligible_customers(ident);summary['eligibleCustomers']=len(eligible)
            tabs=[('Eligible customers',eligible)]
        previous_tree=getattr(self,'data_tree',None);previous_controls=getattr(self,'table_controls',None)
        win=tk.Toplevel(self);win.title(f'{kind} #{ident}');win.geometry('1000x700');win.configure(bg=LIGHT)
        footer=tk.Frame(win,bg=LIGHT,height=58)
        footer.pack(side='bottom',fill='x');footer.pack_propagate(False)
        action_button(footer,'Close',win.destroy,primary=False).pack(fill='both',expand=True,padx=12,pady=8)
        notebook=ttk.Notebook(win);notebook.pack(fill='both',expand=True,padx=12,pady=12)
        summary_tab=tk.Frame(notebook,bg=SURFACE);notebook.add(summary_tab,text='Details')
        content='\n'.join(f'{title_label(k)}: {format_table_value(k,v) if v is not None else "Not recorded"}' for k,v in summary.items())
        text=tk.Text(summary_tab,wrap='word',font=(FONT,11));text.insert('1.0',content);text.config(state='disabled');text.pack(fill='both',expand=True)
        # Recipe ingredients and order lines are immediately visible in the details tab.
        if tabs and kind in ('Recipes','Orders','Purchase orders'):
            text.config(height=8);text.pack_configure(expand=False)
            rows=tabs[0][1]
            if rows:self.table(rows,[(k,k) for k in rows[0]],parent=summary_tab,height=6)
        for title,rows in tabs:
            frame=tk.Frame(notebook,bg=LIGHT);notebook.add(frame,text=title_label(title))
            tree=self.table(rows,[(k,k) for k in rows[0]] if rows else [],parent=frame)
            if kind=='Suppliers' and 'purchase orders' in title and tree:
                tree.bind('<Double-1>',lambda e,t=tree:self.open_record('Purchase orders',t.item(t.selection()[0],'values')[0]) if t.selection() else None)
        self.data_tree=previous_tree;self.table_controls=previous_controls
        return win

    @requires_role('Owner', 'Employee')
    def page_alerts(self):
        self.section('Low-stock alerts','Ingredients reaching their reorder thresholds',[
            ('Update alert status',self.update_alert)])
        self.table(self.svc.alerts(active_only=False),[('alertID','Alert ID'),
                     ('ingredientName','Ingredient'),('quantityOnHand','On hand'),
                     ('reorderLevel','Reorder at'),('status','Status')])

    @requires_role('Owner', 'Employee')
    def update_alert(self):
        a=self.ask('Update alert',[('id','Alert ID',self.selected_id(),'text'),('status','Status','Reviewed',
                         'choice',['Reviewed','Closed'])])
        if a:self.run_action(lambda:self.svc.update_alert(a['id'],a['status']),success='Alert updated.')

    @requires_role('Owner', 'Employee')
    def page_history(self):
        self.section('Inventory activity','Recent inventory adjustments and order stock changes')
        rows=self.svc.transactions()
        cols=[('transactionID','ID'),('transactionDate','Transaction date'),('transactionType','Type'),
              ('ingredientName','Ingredient'),('unit','Unit'),('quantity','Quantity'),('notes','Notes')]
        self.table(rows,cols,sort_by='Transaction date',direction='Descending')

    def details_dialog(self, title, content, parent=None):
        """Scrollable, resizable record-details popup with an always-visible Close."""
        parent = parent or self
        win = tk.Toplevel(parent)
        win.title(title_label(title))
        win.configure(bg=LIGHT)
        win.transient(parent)
        text = str(content)
        width,height = popup_dimensions(parent,700,max(310,120+23*(text.count('\n')+1)))
        center_popup(win,parent,width,height)
        win.minsize(min(width,320),min(height,240))
        tk.Label(win,text=title,bg=LIGHT,fg=INK,font=(FONT,17,'bold'),
                 justify='center',wraplength=width-35).pack(fill='x',padx=15,pady=12)
        footer=tk.Frame(win,bg=LIGHT,padx=18,pady=12)
        footer.pack(fill='x',side='bottom')
        action_button(footer,'Close',win.destroy,primary=False).pack(fill='x')
        area=tk.Frame(win,bg=SURFACE)
        area.pack(fill='both',expand=True,padx=18,pady=(4,0))
        scroll=AutoScrollbar(area,orient='vertical')
        display=tk.Text(area,wrap='word',bg=SURFACE,fg=INK,font=(FONT,11),
                        bd=0,relief='flat',padx=15,pady=12,yscrollcommand=scroll.set)
        scroll.config(command=display.yview)
        scroll.pack(side='right',fill='y')
        display.pack(side='left',fill='both',expand=True)
        display.insert('1.0',text)
        display.config(state='disabled')
        return win

    def _records_dialog(self, title, rows):
        """Scrollable details window; every full value can be opened by double-click."""
        win=tk.Toplevel(self)
        win.title(title_label(title))
        width,height=popup_dimensions(self,1050,690)
        center_popup(win,self,width,height)
        win.minsize(min(width,380),min(height,290))
        win.configure(bg=LIGHT)
        tk.Label(win,text=title_label(title),font=(FONT,17,'bold'),fg=INK,bg=LIGHT,
                 justify='center',wraplength=width-50).pack(fill='x',padx=20,pady=12)
        footer=tk.Frame(win,bg=LIGHT)
        footer.pack(side='bottom',fill='x',padx=20,pady=(4,14))
        action_button(footer,'Close',win.destroy,primary=False).pack(fill='x')
        if not rows:
            tk.Label(win,text='No records found.',bg=LIGHT,fg=MUTED,justify='center').pack(fill='x')
            return
        keys=list(rows[0].keys())
        bar=tk.Frame(win,bg=LIGHT)
        bar.pack(fill='x',padx=20,pady=(0,10))
        tk.Label(bar,text='Search records',fg=MUTED,bg=LIGHT).pack(fill='x')
        query=tk.StringVar()
        tk.Entry(bar,textvariable=query,justify='center').pack(fill='x')
        area=tk.Frame(win,bg=LIGHT)
        area.pack(fill='both',expand=True,padx=20,pady=(0,15))
        tree=ttk.Treeview(area,columns=keys,show='headings',style='POS.Treeview')
        preferred = preferred_table_widths(rows, [(key,key) for key in keys])
        for k in keys:
            tree.heading(k,text=title_label(k),anchor='center')
            tree.column(k,width=preferred[k],minwidth=85,
                        anchor='center',stretch=False)
        tree.bind('<Configure>', lambda e: size_table_columns(tree, preferred, e.width))
        tree.bind('<ButtonRelease-1>',lambda e:size_table_columns(tree,preferred,tree.winfo_width()),add='+')
        tree.tag_configure('hover',background=darken_color(SURFACE))
        table_hover(tree)
        vs=AutoScrollbar(area,command=tree.yview,orient='vertical')
        hs=AutoScrollbar(area,command=tree.xview,orient='horizontal')
        tree.configure(yscrollcommand=vs.set,xscrollcommand=hs.set)
        area.columnconfigure(0,weight=1);area.rowconfigure(0,weight=1)
        vs.grid(row=0,column=1,sticky='ns')
        hs.grid(row=1,column=0,sticky='ew')
        tree.grid(row=0,column=0,sticky='nsew')
        def update(*_):
            text=query.get().strip().casefold()
            tree.delete(*tree.get_children())
            for row in rows:
                if not text or any(text in str(v).casefold() for v in row.values()):
                    tree.insert('','end',values=[format_table_value(k,row.get(k)) for k in keys])
        def details(_event=None):
            sel=tree.selection()
            if sel:
                values=tree.item(sel[0],'values')
                self.details_dialog('Record details',
                    '\n'.join(f'{title_label(k)}: {values[i]}' for i,k in enumerate(keys)),parent=win)
        tree.bind('<Double-1>',details)
        query.trace_add('write',update)
        update()

    def page_profile(self):
        p=self.profile.view_profile(self.user['userID'])
        self.section('My profile','Update your own personal details; username and role remain protected',[
            ('Edit profile',lambda:self.edit_profile(p))])
        pane=card(self.body,30)
        pane.pack(fill='x')
        for label,value in [('Full name',p.name),('Username',p.username+'  (read only)'),
                            ('Role',p.role+'  (read only)'),('Email',p.email or 'Not provided'),
                            ('Phone number',p.phone_number or 'Not provided'),
                            ('Date of birth',str(p.date_of_birth or 'Not provided'))]:
            line=tk.Frame(pane,bg=SURFACE,pady=8)
            line.pack(fill='x')
            line.columnconfigure(0,weight=1,uniform='profile')
            line.columnconfigure(1,weight=2,uniform='profile')
            tk.Label(line,text=label,bg=SURFACE,fg=MUTED,font=(FONT,10),
                     justify='center').grid(row=0,column=0,sticky='ew',padx=5)
            tk.Label(line,text=value,bg=SURFACE,fg=INK,font=(FONT,11,'bold'),
                     justify='center',wraplength=470).grid(row=0,column=1,sticky='ew',padx=5)
        tk.Label(self.body,text='Updates are validated and saved to both User and Profile records.',
                 font=(FONT,10),bg=LIGHT,fg=MUTED,justify='center').pack(fill='x',pady=16)

    def edit_profile(self, p):
        a=self.ask('Edit your profile',[('name','Full name',p.name,'text'),
             ('email','Email address (optional)',p.email or '', 'text'),
             ('phoneNumber','Phone number (optional)',p.phone_number or '','text'),
             ('dateOfBirth','Date of birth (YYYY-MM-DD, optional)',str(p.date_of_birth or ''),'text')],
             'Leave an optional field empty to remove it. Cancel discards all changes.')
        if a is None:
            return
        # Full submitted form is validated before any write and prevents partial updates.
        if not messagebox.askyesno('Confirm profile update','Save these profile changes?',parent=self):
            return
        def save():
            updated=self.profile.update_profile(self.user['userID'],a,expected_version=p.version)
            self.user['name']=updated.name
        self.run_action(save,success='Your profile was updated.')

    @requires_role('Owner')
    def page_users(self):
        self.section('User management','Owner only · accounts and roles',[
             ('+ Create user',self.create_user_admin),('Edit user',self.edit_user_admin),
             ('Activate / deactivate',self.toggle_user),('Reset password',self.reset_user_password),
             ('Change role',self.change_user_role),('View user',self.view_user_admin),
             ('Delete unused account',self.delete_user_admin)])
        self.table(self.users.list_accounts(self.user['userID']),[('userID','User ID'),
                     ('employeeID','Employee ID'),('name','Name'),('username','Username'),
                     ('role','Role'),('status','Status')])

    @requires_role('Owner')
    def create_user_admin(self):
        a=self.ask('New user account',[('name','Name','','text'),('username','Username','','text'),
            ('password','Password','','password'),('role','Role','Customer','choice',['Customer','Employee','Owner']),
            ('email','Email (optional)','','text'),('phone','Phone (optional)','','text'),
            ('dob','DOB (YYYY-MM-DD, optional)','','text')])
        if a:self.run_action(lambda:self.users.create_account(self.user['userID'],a['name'],a['username'],a['password'],
              a['role'],email=a['email'] or None,phone_number=a['phone'] or None,
              date_of_birth=a['dob'] or None),success='New user created.')

    @requires_role('Owner')
    def edit_user_admin(self):
        a=self.ask('Select user to edit',[('id','User ID',self.selected_id(),'text')],confirm='Load')
        if not a:return
        current=self.run_action(lambda:self.users.get_account(self.user['userID'],a['id']),refresh=False)
        if current is None:return
        fields=[(k,label,current.get(k) or '','text') for k,label in [
            ('name','Full name'),('username','Username'),('email','Email (optional)'),
            ('phoneNumber','Phone (optional)'),('dateOfBirth','DOB (YYYY-MM-DD, optional)')]]
        changes=self.ask('Edit user',fields,'Leave an optional field empty to clear it. Cancel discards changes.')
        if changes and messagebox.askyesno('Confirm update','Save these account and profile changes?',parent=self):
            self.run_action(lambda:self.users.edit_account(self.user['userID'],a['id'],changes),success='User updated.')

    @requires_role('Owner')
    def delete_user_admin(self):
        a=self.ask('Delete unused account',[('id','User ID',self.selected_id(),'text')],
            'Accounts linked to business history cannot be deleted. Disable them instead.',confirm='Review')
        if not a:return
        current=self.run_action(lambda:self.users.get_account(self.user['userID'],a['id']),refresh=False)
        if current is not None and messagebox.askyesno('Permanently delete account',
            f"Delete {current['name']} (@{current['username']})? This cannot be undone.",parent=self):
            self.run_action(lambda:self.users.delete_account(self.user['userID'],a['id']),success='Unused account deleted.')

    @requires_role('Owner')
    def toggle_user(self):
        a=self.ask('Account status',[('id','User ID',self.selected_id(),'text'),('state','Set account','Inactive','choice',['Active','Inactive'])])
        if a:self.run_action(lambda:self.users.set_active(self.user['userID'],int(a['id']),a['state']=='Active'),success='Account status updated.')

    @requires_role('Owner')
    def change_user_role(self):
        a=self.ask('Change user role',[('id','User ID',self.selected_id(),'text'),
            ('role','New role','Customer','choice',['Customer','Employee','Owner'])],
            'Customer accounts with loyalty history cannot change role; use disable instead.')
        if a and messagebox.askyesno('Change role','Confirm this role change?',parent=self):
            self.run_action(lambda:self.users.change_role(self.user['userID'],int(a['id']),a['role']),success='Role changed.')

    @requires_role('Owner')
    def view_user_admin(self):
        a=self.ask('View user account',[('id','User ID',self.selected_id(),'text')],confirm='View')
        if a:
            data=self.run_action(lambda:self.users.get_account(self.user['userID'],int(a['id'])),refresh=False)
            if data is not None:
                role=data['role']
                # Each subtype has its own identifier. Do not confuse Employee ID
                # with Customer ID (which is used only by orders/loyalty).
                visible={k:v for k,v in data.items() if k not in ('customerID','employeeID','ownerID')}
                if role=='Employee':visible['Employee ID']=data.get('employeeID')
                elif role=='Owner':visible['Owner ID']=data.get('ownerID')
                elif role=='Customer':visible['Customer ID']=data.get('customerID')
                lines='\n'.join(f'{title_label(k)}: {v if v is not None else "(not set)"}' for k,v in visible.items())
                self.details_dialog('User details',lines)

    @requires_role('Owner')
    def reset_user_password(self):
        a=self.ask('Reset user password',[('id','User ID',self.selected_id(),'text'),('pw','New password','','password')])
        if a:self.run_action(lambda:self.users.reset_password(self.user['userID'],int(a['id']),a['pw']),success='Password reset.')

    @requires_role('Owner')
    def page_demo(self):
        self.section('Demo data & backups',
            'Owner-only tools. Demo data is imported only after confirmation.')
        choices=[
            ('Load complete demo', 'All sample workflows, fictional customer histories, employees, payroll, feedback and profitable sales. A safety backup is created.', self.import_complete_demo),
            ('Load 8 sample users',
             'Import eight fictional accounts and profiles. Existing users are preserved.',
             self.import_samples),
            ('Load sample restaurant data',
             'Example ingredients, recipes, suppliers and orders.',self.import_shop_demo),
            ('Load accounting demo',
             'Ten sample bookkeeping entries, including a repeated invoice reference to practice reconciliation.',
             self.import_accounting_demo),
            ('Load sales trend history',
             'Optional historical sales and stock usage. Load restaurant data first.',
             lambda:self.import_aux_demo('trend')),
            ('Load sample payroll',
             'Optional fictional payroll example for testing calculations.',
             lambda:self.import_aux_demo('payroll')),
            ('Back up database',
             'Save a consistent SQLite copy before adding sample transactions.',
             self.backup_database),
        ]
        for title,summary,handler in choices:
            pane=card(self.body,14)
            pane.pack(fill='x',pady=5)
            tk.Label(pane,text=title,bg=SURFACE,fg=INK,font=(FONT,12,'bold'),
                     justify='center').pack(fill='x')
            label=tk.Label(pane,text=summary,bg=SURFACE,fg=MUTED,font=(FONT,9),justify='center')
            label.pack(fill='x',pady=5)
            pane.bind('<Configure>',lambda e,w=label:w.configure(wraplength=max(180,e.width-35)))
            action_button(pane,'Run '+title,handler,small=True).pack(fill='x',padx=20,pady=(4,0))
        self.section('Reset and restore','These actions replace the entire active database.',[
            ('Reset business data',lambda:self.reset_gui(False)),
            ('Factory reset',lambda:self.reset_gui(True)),('Restore backup',self.restore_gui)])

    def _reload_after_replace(self):
        path=self.db_path
        self.svc=InventoryService(path);self.profile=ProfileService(path)
        self.users=UserManagementService(path);self.loyalty=LoyaltyService(path)
        self.accounting=AccountingLedger(path);self.payroll=PayrollService(path)
        self.feedback=FeedbackService(path);self.appearance=ThemePreferences(path)
        self.show_auth()

    @requires_role('Owner')
    def import_complete_demo(self):
        if not messagebox.askyesno('Complete fictional dataset',
            'Add sample data across all modules? Existing records are retained and backed up. Close other sessions first.',parent=self):return
        if not self._verify_owner():return
        def load():
            result=load_complete_demo(self.svc,self.user['userID'])
            messagebox.showinfo('Complete demo', 'Already loaded; no duplicates added.' if result['already_loaded'] else
                'Complete fictional data loaded. Safety backup: '+result['backup'],parent=self)
        self.run_action(load)

    @requires_role('Owner')
    def reset_gui(self,factory=False):
        a=self.ask('Confirm database reset',[('confirm','Type RESET to replace all business data','','text')],
            'A full safety backup will be created. '+('All accounts will also be removed.' if factory else 'Login accounts and profiles will be retained.'))
        if not a or a['confirm']!='RESET':return
        if not self._verify_owner():return
        def reset():
            backup=reset_database(self.svc,self.user['userID'],with_demo=False,preserve_accounts=not factory)
            messagebox.showinfo('Reset complete',f'Safety backup: {backup}\nSign in again or set up the first Owner.',parent=self)
            self._reload_after_replace()
        self.run_action(reset,refresh=False)

    @requires_role('Owner')
    def restore_gui(self):
        backups=list_backups(self.svc)
        if not backups:
            messagebox.showinfo('No backups','Create a backup before restoring.',parent=self);return
        choices=[p.name for p in backups]
        a=self.ask('Restore backup',[('backup','Backup',choices[0],'choice',choices),
            ('confirm','Type RESTORE to replace the entire database','','text')],
            'Accounts and records will return to the selected backup. Current data is backed up first.')
        if not a or a['confirm']!='RESTORE':return
        if not self._verify_owner():return
        def restore():
            selected=next(p for p in backups if p.name==a['backup'])
            backup=restore_database(self.svc,self.user['userID'],selected)
            messagebox.showinfo('Restore complete',f'Current data was backed up to {backup}. Sign in using the restored accounts.',parent=self)
            self._reload_after_replace()
        self.run_action(restore,refresh=False)

    @requires_role('Owner')
    def import_accounting_demo(self):
        """Use the existing business-layer demo importer; never insert on startup."""
        if not messagebox.askyesno('Load accounting demo',
          'Add ten fictional accounting entries? This is optional and can be imported once.\n'
          'It includes a duplicate invoice reference to test reconciliation.',parent=self):
            return
        if not self._verify_owner():return
        outcome=self.run_action(lambda:populate_accounting_activity(self.svc,self.user['userID']),
                                refresh=False)
        if outcome is not None:
            messagebox.showinfo('Accounting demo loaded',
                f"Created {outcome['manual_transactions']} sample ledger entries.\n"
                'Open Accounting to filter, sort, and reconcile them.',parent=self)
            self.show_page(self.current_page)

    @requires_role('Owner')
    def import_aux_demo(self,which):
        labels={'trend':('sales trend history',populate_trend_history),
                'payroll':('sample payroll',populate_payroll_activity)}
        title,func=labels[which]
        if messagebox.askyesno('Load demo data',f'Load {title}?',parent=self) and self._verify_owner():
            self.run_action(lambda:func(self.svc,self.user['userID']),success=title.capitalize()+' loaded.')

    @requires_role('Owner')
    def _verify_owner(self):
        a=self.ask('Confirm owner password',[('password','Your current password','','password')],
                   'Sensitive demo actions require reauthentication.',confirm='Verify')
        if a is None:
            return False
        try:
            check=self.svc.login(self.user['username'],a['password'])
            return check['role']=='Owner' and check['userID']==self.user['userID']
        except InventoryError:
            messagebox.showerror('Verification failed','Incorrect Owner password.',parent=self)
            return False

    @requires_role('Owner')
    def import_samples(self):
        if messagebox.askyesno('Load demo users','Import eight fictional sample users and profiles?',parent=self):
            if self._verify_owner():
                result=self.run_action(lambda:load_sample_users(self.svc,self.user['userID']),refresh=False)
                if result is not None:
                    messagebox.showinfo('Import completed',f"Created {result['created']} users; {result['already_present']} already existed.",parent=self)
                    self.show_page('Demo & backups')

    @requires_role('Owner')
    def import_shop_demo(self):
        if messagebox.askyesno('Load sample restaurant','Populate demonstration ingredients, orders and recipes?',parent=self):
            self.run_action(lambda:self.svc.load_demo_data(self.user['userID']),success='Sample restaurant data loaded.')

    @requires_role('Owner')
    def backup_database(self):
        path=self.run_action(lambda:backup_database(self.svc),refresh=False)
        if path is not None:messagebox.showinfo('Backup created',f'Backup stored at:\n{path}',parent=self)

    def page_loyalty(self):
        self.loyalty.ensure_sample_rewards()
        self.section('Loyalty rewards','Earn 10 points per $1 CAD · Redeem $5 off for 1,000 points')
        if self.user['role']=='Customer':
            self.customer_loyalty()
        else:
            self.staff_loyalty()

    @requires_role('Customer')
    def customer_loyalty(self):
        cid=self.loyalty.customer_id_for_user(self.user['userID'])
        try:
            info=self.loyalty.view_loyalty_details(cid)
        except AccountNotFoundError:
            pane=card(self.body,28)
            pane.pack(fill='x')
            tk.Label(pane,text='You are not enrolled yet.',fg=INK,bg=SURFACE,
                     font=(FONT,17,'bold'),anchor='center',justify='center').pack(fill='x')
            tk.Label(pane,text='Join to earn points and view available rewards.',fg=MUTED,bg=SURFACE,justify='center').pack(fill='x',pady=(9,18))
            action_button(pane,'Join loyalty program',lambda:self.run_action(
                lambda:self.loyalty.enroll_existing_customer(self.user['userID'],self.user['userID']),
                success='Welcome to the loyalty program!')).pack(fill='x')
            return
        summary=tk.Frame(self.body,bg=LIGHT)
        summary.pack(fill='x',pady=(0,18))
        self.display_card(summary,'Your balance',f"{info['account']['pointsBalance']:,} pts",'Earn 10 points per $1')
        self.display_card(summary,'Membership',info['account']['status'],'Discounts at checkout')
        self.section('Available rewards','A staff member confirms redemptions against a completed order')
        self.table(info['rewards'],[('name','Reward'),('pointsCost','Points'),
                                   ('discountAmount','CAD off'),('affordable','Can redeem')],height=4)
        # Table fills remaining space, so history is accessible in a separate window.
        action_button(self.body,'View my loyalty history',lambda:self._records_dialog('Loyalty history',
                      self.loyalty.transaction_history(cid)),small=True,primary=False).pack(fill='x',pady=12)

    @requires_role('Owner', 'Employee')
    def staff_loyalty(self):
        actions=[('Customer directory',self.list_customers),('View customer',self.view_customer_loyalty),('Find customer',self.find_customer),('Enroll customer',self.enroll_customer),
                 ('Record purchase points / reward',self.record_loyalty),('Register walk-in',self.register_walkin)]
        if self.user['role']=='Owner':
            actions += [('+ Create reward',self.create_reward),('Activate / deactivate reward',self.toggle_reward),
                        ('Suspend loyalty account',self.suspend_loyalty)]
        self.section('Loyalty account actions',
                     'View, register or update customers using the options below.',actions)
        self.table(self.loyalty.rewards(active_only=False),[('rewardID','Reward ID'),('name','Reward'),
                ('pointsCost','Points'),('discountAmount','CAD off'),('isActive','Reward Active')],height=6)

    @requires_role('Owner', 'Employee')
    def register_walkin(self):
        a=self.ask('Register walk-in loyalty customer',[('name','Name','','text'),('email','Email (optional)','','text'),
                ('phone','Phone (optional)','','text'),('username','Username (blank = generate)','','text'),
                ('password','Password (blank = generate temporary password)','','password')],
                'Provide an email or phone. Login credentials will be displayed once after creation.')
        if a:
            def register():
                result=self.loyalty.register_customer(self.user['userID'],a['name'],
                    email=a['email'] or None,phone_number=a['phone'] or None,
                    username=a['username'] or None,password=a['password'] or None)
                messagebox.showinfo('Walk-in account created',
                    f"Customer ID: {result['customerID']}\nUser ID: {result['userID']}\n"
                    f"Username: {result['username']}\nPassword: {result['initialPassword']}\n\n"
                    'Give these credentials to the customer. The password will not be shown again.',parent=self)
            self.run_action(register)

    @requires_role('Owner', 'Employee')
    def list_customers(self):
        rows=self.run_action(lambda:self.loyalty.list_customers(self.user['userID']),refresh=False)
        if rows is not None:
            self._records_dialog('Customers - use User ID in all forms',rows)

    @requires_role('Owner', 'Employee')
    def enroll_customer(self):
        a=self.ask('Enroll an existing Customer',[('id','Customer User ID','','text')],
                   'Enter the User ID of an existing Customer, not their Customer ID.')
        if a:self.run_action(lambda:self.loyalty.enroll_existing_customer(int(a['id']),self.user['userID']),success='Customer enrolled.')

    @requires_role('Owner', 'Employee')
    def find_customer(self):
        a=self.ask('Find Customer',[('query','Exact email or phone number','','text')],confirm='Search')
        if a:
            result=self.run_action(lambda:self.loyalty.find_customers(self.user['userID'],a['query']),refresh=False)
            if result is not None:self._records_dialog('Matching customers',result)

    @requires_role('Owner')
    def suspend_loyalty(self):
        a=self.ask('Loyalty account status',[('id','Customer User ID','','text'),
          ('status','Status','Suspended','choice',['Suspended','Active'])])
        if a:self.run_action(lambda:self.loyalty.set_loyalty_account_status(self.user['userID'],role_id(self.db_path,a['id'],'Customer'),a['status']),
                 success='Loyalty account status updated.')

    @requires_role('Owner', 'Employee')
    def view_customer_loyalty(self):
        a=self.ask('View loyalty account',[('id','Customer User ID','','text')],confirm='View')
        if a:
            info=self.run_action(lambda:self.loyalty.view_loyalty_details(role_id(self.db_path,a['id'],'Customer')),refresh=False)
            if info is not None:
                acc=info['account']
                messagebox.showinfo('Customer balance',f"{acc['name']}\nBalance: {acc['pointsBalance']:,} points\nStatus: {acc['status']}",parent=self)
                self._records_dialog('Loyalty transaction history',info['transactions'])

    @requires_role('Owner', 'Employee')
    def record_loyalty(self):
        a=self.ask('Process completed order loyalty',[('cid','Customer User ID','','text'),
                  ('order','COMPLETED order ID','','text'),('reward','Reward ID (optional)','','text'),
                  ('eligible','Eligible CAD amount (blank = order amount)','','text')],
                  'Requires a completed order. Review the points and discount before confirming. No payment is charged.',confirm='Preview')
        if a:
            def quote():
                cid,oid=role_id(self.db_path,a['cid'],'Customer'),int(a['order'])
                reward=int(a['reward']) if a['reward'] else None
                amount=a['eligible'] if a['eligible'] else None
                p=self.loyalty.preview_purchase(cid,oid,reward_id=reward,eligible_amount=amount)
                msg=(f'Order: {money(p.purchase_amount)}\nEligible: {money(p.eligible_amount)}\n'
                     f'Discount: {money(p.discount_amount)}\nAmount after discount: {money(p.final_amount)}\n\n'
                     f'Points: {p.previous_balance} − {p.points_redeemed} + {p.points_earned} = {p.new_balance}\n\n'
                     'Customer and employee confirm this loyalty transaction?')
                if not messagebox.askyesno('Confirm loyalty transaction',msg,parent=self):
                    return
                if reward is None:
                    t=self.loyalty.process_eligible_purchase(self.user['userID'],cid,oid,eligible_amount=amount)
                else:
                    t=self.loyalty.redeem_reward(self.user['userID'],cid,oid,reward,eligible_amount=amount)
                self.show_page(self.current_page)
                self.details_dialog('Loyalty receipt',self.loyalty.generate_receipt(t['loyaltyTransactionID']))
            self.run_action(quote,refresh=False)

    @requires_role('Owner')
    def create_reward(self):
        a=self.ask('Create reward',[('name','Reward name','','text'),('points','Points needed','','text'),
                 ('discount','Discount CAD','','text')])
        if a:self.run_action(lambda:self.loyalty.create_reward(self.user['userID'],a['name'],a['points'],a['discount']),success='Reward created.')

    @requires_role('Owner')
    def toggle_reward(self):
        a=self.ask('Set reward availability',[('id','Reward ID','','text'),
                   ('active','Reward Active','Yes','choice',['Yes','No'])])
        if a:self.run_action(lambda:self.loyalty.set_reward_active(self.user['userID'],int(a['id']),a['active']=='Yes'),success='Reward updated.')


    @requires_role('Owner')
    def page_accounting(self):
        self.accounting.sync_completed_orders()
        summary=self.accounting.calculateSummary().displaySummary()
        self.section('Accounting ledger','Internal bookkeeping — not a bank/payment gateway',[
            ('+ New entry',self.accounting_add),('Edit selected',self.accounting_edit),
            ('Reconcile',self.accounting_reconcile),('Discrepancies',self.accounting_discrepancies),
            ('Review historical order sales',self.accounting_sync_orders),('Reconciliation history',self.accounting_history)])
        cards=tk.Frame(self.body,bg=LIGHT)
        cards.pack(fill='x',pady=(0,14))
        self.display_card(cards,'Revenue',money(summary['totalSales']))
        self.display_card(cards,'Expenses',money(summary['totalExpenses']+summary['totalPurchases']))
        self.display_card(cards,'Balance',money(summary['balance']),'Internal ledger only')
        self.table(self.accounting.getTransactions(),[
            ('transactionID','ID'),('transactionDate','Date'),('transactionType','Type'),
            ('description','Description'),('reference','Reference'),('amount','CAD'),('source','Origin')],height=10,sort_by='Date',direction='Descending')

    @requires_role('Owner')
    def accounting_add(self):
        a=self.ask('Record accounting transaction',[
            ('type','Type','Expense','choice',['Sale','Purchase','Expense','Inventory Adjustment']),
            ('date','Date (YYYY-MM-DD)',date.today().isoformat(),'text'),
            ('description','Description','','text'),('reference','Reference (optional)','','text'),
            ('amount','Amount CAD','','text')],
            'A manual entry is not a payment or a payroll transaction.')
        if a and messagebox.askyesno('Confirm transaction','Save this manual ledger entry?',parent=self):
            self.run_action(lambda:self.accounting.addTransaction(AccountingTransaction(None,a['type'],a['date'],
                           a['description'],a['reference'],float(a['amount']))),success='Entry recorded.')

    @requires_role('Owner')
    def accounting_edit(self):
        a=self.ask('Edit manual ledger entry',[('id','Transaction ID',self.selected_id(),'text')],confirm='Load')
        if not a:return
        result=self.run_action(lambda:next((r for r in self.accounting.getTransactions()
                                    if r['transactionID']==int(a['id'])),None),refresh=False)
        if result is None:
            messagebox.showerror('Not found','No such transaction.',parent=self)
            return
        a=self.ask('Update accounting entry',[
            ('type','Type',result['transactionType'],'choice',['Sale','Purchase','Expense','Inventory Adjustment']),
            ('date','Date',result['transactionDate'],'text'),
            ('description','Description',result['description'],'text'),
            ('reference','Reference',result['reference'] or '','text'),
            ('amount','Amount CAD',result['amount'],'text')],
            'Linked order / payroll / delivery entries cannot be manually changed.')
        if a and messagebox.askyesno('Confirm update','Save accounting changes?',parent=self):
            self.run_action(lambda:self.accounting.updateTransaction(AccountingTransaction(result['transactionID'],
                a['type'],a['date'],a['description'],a['reference'],float(a['amount']))),success='Entry updated.')

    @requires_role('Owner')
    def accounting_reconcile(self):
        def perform():
            result=self.accounting.reconcile_with_report()
            messagebox.showinfo('Reconciliation',
                f"Reviewed {result['transactionCount']} transactions.\n"
                f"New flags: {result['newFlags']}\nCleared flags: {result['clearedFlags']}\n"
                f"Open discrepancies: {result['flaggedCount']}\n"
                + ('No flags changed.' if result['newFlags']==0 and result['clearedFlags']==0 else ''),parent=self)
        self.run_action(perform)

    @requires_role('Owner')
    def accounting_history(self):
        rows=self.run_action(self.accounting.getReconciliationLog,refresh=False)
        if rows is not None:self._records_dialog('Reconciliation history',rows)

    def record_browser(self,title,rows,choose,action_label,*,allow_id=False):
        win=tk.Toplevel(self);win.title(title_label(title));win.geometry('1100x720');win.configure(bg=LIGHT)
        tk.Label(win,text=title,bg=LIGHT,fg=INK,font=(FONT,16,'bold')).pack(fill='x',pady=12)
        old_tree=getattr(self,'data_tree',None);old_controls=getattr(self,'table_controls',None)
        tree=self.table(rows,[(k,k) for k in rows[0]] if rows else [],parent=win)
        self.data_tree=old_tree;self.table_controls=old_controls
        identity=tk.StringVar()
        if allow_id:
            tk.Label(win,text='Select a row above or enter its Order ID below',bg=LIGHT,fg=MUTED).pack(fill='x')
            tk.Entry(win,textvariable=identity,justify='center').pack(fill='x',padx=20)
        def perform():
            if not self._authorize(('Owner',)):return
            raw=identity.get().strip()
            if not raw and tree and tree.selection():raw=tree.item(tree.selection()[0],'values')[0]
            def act():
                ident=_ident(raw,'Selected record ID')
                record=next((r for r in rows if r[next(iter(r))]==ident),None)
                if not record:raise ValueError('Select a record shown in this window first.')
                if choose(record):
                    rows.remove(record)
                    for item in tree.get_children():
                        if str(tree.item(item,'values')[0])==str(ident):tree.delete(item)
                    identity.set('')
            self.run_action(act,refresh=False)
        def close():
            win.destroy()
            if self.user:self.show_page(self.current_page)
        footer=tk.Frame(win,bg=LIGHT);footer.pack(side='bottom',fill='x',padx=16,pady=12)
        action_button(footer,action_label,perform).pack(side='left',fill='x',expand=True)
        action_button(footer,'Close',close,primary=False).pack(side='right',fill='x',expand=True)
        win.protocol('WM_DELETE_WINDOW',close)
        return win,perform

    @requires_role('Owner')
    def accounting_discrepancies(self):
        rows=self.accounting.getDiscrepancies(status='Flagged')
        def resolve(record):
            if not messagebox.askyesno('Resolve discrepancy','Mark this investigated discrepancy as resolved?',parent=self):return False
            self.accounting.resolveDiscrepancy(record['discrepancyID']);return True
        return self.record_browser('Current accounting discrepancies',rows,resolve,'Resolve selected discrepancy')

    @requires_role('Owner')
    def accounting_sync_orders(self):
        pending=self.accounting.pending_completed_orders()
        def post(record):
            if not messagebox.askyesno('Review historical order sale',
                f"Post order #{record['orderID']} as a Sale of {money(record['paidAmount'])}?\n"
                'Check manual Sales first to avoid counting the same revenue twice.',parent=self):return False
            self.accounting.sync_completed_orders(allow_with_manual_sales=True,order_ids={record['orderID']})
            return True
        return self.record_browser('Review historical order sales ? check manual Sales before posting',pending,post,'Post selected order Sale',allow_id=True)

    @requires_role('Owner')
    def page_payroll(self):
        self.section('Payroll','Owner only · sample rates/deductions, not statutory pay advice',[
            ('+ New pay period',self.payroll_open),('Enter hours',self.payroll_hours),
            ('Hourly rates',self.payroll_rates),('Calculate',self.payroll_calculate),
            ('Approve',self.payroll_approve),('Mark paid',self.payroll_pay),('Pay stubs',self.payroll_stubs),
            ('Remove employee',self.payroll_remove),('View payroll entries',self.payroll_entries)])
        rows=self.payroll.payrolls(self.user['userID'])
        for row in rows:
            if row.get('payTime'):row['payDate']=row['payDate']+'T'+row['payTime']
        self.table(rows,[
            ('payrollID','ID'),('payDate','Pay date'),('status','Status'),
            ('totalAmount','Total CAD'),('employees','Employees'),('accountingTransactionID','Ledger ID')],height=12)

    @requires_role('Owner')
    def payroll_open(self):
        a=self.ask('Open payroll period',[('date','Pay date YYYY-MM-DD',date.today().isoformat(),'text')])
        if a:self.run_action(lambda:self.payroll.open_payroll(self.user['userID'],a['date']),success='Payroll period opened.')

    @requires_role('Owner')
    def payroll_rates(self):
        employees=self.run_action(lambda:self.payroll.employees(self.user['userID']),refresh=False)
        if employees is None:return
        if not employees:
            messagebox.showinfo('No employees',
                'Create an active Employee account under Users before setting an hourly rate.',parent=self)
            return
        self._records_dialog('Employee rates',sorted([{'userID':user_id_for_role(self.db_path,e.employeeID,'Employee'),**asdict(e)} for e in employees],key=lambda e:e['userID']))
        a=self.ask('Set hourly rate (optional)',[('id','Employee User ID','','text'),('rate','Hourly rate CAD','','text')])
        if a and a['id']:
            self.run_action(lambda:self.payroll.set_hourly_rate(self.user['userID'],role_id(self.db_path,a['id'],'Employee'),a['rate']),success='Hourly rate saved.')

    @requires_role('Owner')
    def payroll_hours(self):
        pid=self._payroll_id('Select draft payroll',draft=True)
        if pid is None:return
        employees=self.run_action(lambda:self.payroll.employees(self.user['userID']),refresh=False)
        if employees is None:return
        eligible=[e for e in employees if e.hourlyRate > 0]
        if not eligible:
            messagebox.showinfo('No eligible employees',
                'Create an active Employee under Users and set a positive hourly rate under Payroll → Hourly rates.',parent=self)
            return
        choices=[f"{user_id_for_role(self.db_path,e.employeeID,'Employee')}: {e.name} ({money(e.hourlyRate)}/hour)" for e in sorted(eligible,key=lambda e:(e.name.casefold(),e.employeeID))]
        def validate(values):
            from payroll import PayrollEntry
            PayrollEntry(None,role_id(self.db_path,values['employee'].split(':')[0],'Employee'),values['hours'],values['overtime'])
        a=self.ask('Enter or correct hours',[
                    ('employee','Employee',choices[0],'choice',choices),('hours','Regular hours','','text'),
                    ('overtime','Overtime hours','0','text')],
                    'Add employees to the list, then Save commits all hours together. Cancel discards the list.',batch=validate)
        if a:
            rows=a if isinstance(a,list) else [a]
            self.run_action(lambda:self.payroll.enter_hours_batch(self.user['userID'],pid,
                [(role_id(self.db_path,r['employee'].split(':')[0],'Employee'),r['hours'],r['overtime']) for r in rows]),success='Hours saved.')

    @requires_role('Owner')
    def payroll_remove(self):
        pid=self._payroll_id('Select draft payroll',draft=True)
        if pid is None:return
        a=self.ask('Remove employee from draft payroll',[
                  ('employee','Employee User ID','','text')],confirm='Remove')
        if a and messagebox.askyesno('Confirm','Remove this payroll entry?',parent=self):
            self.run_action(lambda:self.payroll.remove_employee(self.user['userID'],pid,
                            role_id(self.db_path,a['employee'],'Employee')),success='Payroll entry removed.')

    def _payroll_id(self,title,*,draft=False):
        a=self.ask(title,[('id','Payroll ID',self.selected_id(),'text')],confirm='Continue')
        if not a or not a['id']:return None
        def select():
            payroll=self.payroll.get_payroll(self.user['userID'],_ident(a['id'],'Payroll ID'))
            if draft and payroll.status!='Draft':
                raise ValueError(f'This payroll is {payroll.status}; only Draft payrolls can be changed.')
            return payroll.payrollID
        return self.run_action(select,refresh=False)

    @requires_role('Owner')
    def payroll_entries(self):
        pid=self._payroll_id('Review payroll entries')
        if pid is None:return
        payroll=self.run_action(lambda:self.payroll.get_payroll(self.user['userID'],pid),refresh=False)
        if payroll is not None:
            names={r['employeeID']:r['name'] for r in DetailService(self.db_path).rows('SELECT e.employeeID,u.name FROM Employee e JOIN "User" u ON u.userID=e.userID')}
            self._records_dialog(f'Payroll #{pid} — {payroll.status}',[{'userID':user_id_for_role(self.db_path,e.employeeID,'Employee'),'employeeID':e.employeeID,'employeeName':names.get(e.employeeID,'Not recorded'),**{k:v for k,v in asdict(e).items() if k!='employeeID'}} for e in payroll.entries])

    @requires_role('Owner')
    def payroll_calculate(self):
        pid=self._payroll_id('Validate and calculate payroll',draft=True)
        if pid is None:return
        def compute():
            issues=self.payroll.check_hours(self.user['userID'],pid)
            if issues:raise ValueError('Correct hours first:\n'+'\n'.join(issues))
            calculation=self.payroll.calculate(self.user['userID'],pid)
            messagebox.showinfo('Payroll calculated',
                f'Total pay: {money(calculation.totalAmount)}\nReview and approve separately.',parent=self)
        self.run_action(compute)

    @requires_role('Owner')
    def payroll_approve(self):
        pid=self._payroll_id('Approve payroll',draft=True)
        if pid is not None and messagebox.askyesno('Approve payroll','Approve these calculated amounts?',parent=self):
            self.run_action(lambda:self.payroll.approve(self.user['userID'],pid),success='Payroll approved.')

    @requires_role('Owner')
    def payroll_pay(self):
        pid=self._payroll_id('Record paid payroll')
        if pid is not None and messagebox.askyesno('Record payroll expense',
             'Confirm the Owner has paid staff outside this application? This creates a ledger expense; it does not send money.',parent=self):
            self.run_action(lambda:self.payroll.record_expense(self.user['userID'],pid),
                            success='Payroll marked paid and expense recorded.')

    @requires_role('Owner')
    def payroll_stubs(self):
        pid=self._payroll_id('View employee pay stubs')
        if pid is None:return
        stubs=self.run_action(lambda:self.payroll.pay_stubs(self.user['userID'],pid),refresh=False)
        if stubs is not None:self.details_dialog('Pay stubs','\n\n'.join(stubs))

    def page_feedback(self):
        uid=self.user['userID']
        if self.user['role']=='Customer':
            self.section('My feedback','Tell the restaurant about your order or service',[
                ('+ Submit feedback',self.feedback_submit)])
            rows=[asdict(f) for f in self.feedback.view_submitted_feedback(uid)]
        else:
            self.section('Customer feedback','Review customer submissions',[
                ('Mark reviewed',self.feedback_review),('View details',self.feedback_details)])
            rows=[asdict(f) for f in self.feedback.view_feedback(uid)]
        self.table(rows,[('feedbackID','ID'),('customerUsername','Customer'),
             ('rating','Rating'),('feedbackText','Feedback'),('submissionDate','Submitted'),('status','Status')])

    @requires_role('Customer')
    def feedback_submit(self):
        a=self.ask('Submit feedback',[('rating','Rating (1-5; optional)','','text'),
                    ('text','Your feedback','','text')],
                    'Feedback is stored for employee and owner review.')
        if a:self.run_action(lambda:self.feedback.submit_feedback(self.user['userID'],a['text'],
                 int(a['rating']) if a['rating'] else None),success='Thank you! Feedback submitted.')

    @requires_role('Owner', 'Employee')
    def feedback_review(self):
        a=self.ask('Mark feedback reviewed',[('id','Feedback ID',self.selected_id(),'text')],confirm='Review')
        if a:self.run_action(lambda:self.feedback.review_feedback(self.user['userID'],int(a['id'])),
                             success='Feedback marked reviewed.')

    @requires_role('Owner', 'Employee')
    def feedback_details(self):
        a=self.ask('View feedback',[('id','Feedback ID',self.selected_id(),'text')],confirm='View')
        if a:
            records=self.run_action(lambda:self.feedback.view_feedback(self.user['userID'],int(a['id'])),refresh=False)
            if records is not None:self._records_dialog('Feedback details',[asdict(f) for f in records])

    @requires_role('Owner', 'Employee')
    def page_trends(self):
        self.section('Trend dashboard','Three or more distinct activity dates required for a forecast',[
            ('Sales forecast',lambda:self.trend_show('Sales')),
            ('Revenue forecast',lambda:self.trend_show('Financial')),
            ('Ingredient forecast',self.trend_ingredient)])
        panel=card(self.body,25)
        panel.pack(fill='x')
        tk.Label(panel,text='Predict sales, revenue and ingredient consumption',bg=SURFACE,fg=INK,
            font=(FONT,15,'bold'),anchor='center',justify='center').pack(fill='x')
        tk.Label(panel,text='Forecasts use the last three recorded dates, not a machine learning model.\n'
            'Results are planning estimates only. No inventory order is placed automatically.',
            bg=SURFACE,fg=MUTED,justify='center',font=(FONT,11)).pack(fill='x',pady=(10,15))
        for typ in ('Sales','Financial'):
            points=BusinessData(typ,self.db_path).retrieve_data()
            tk.Label(panel,text=f'{typ}: {len(points)} recorded dates',bg=SURFACE,fg=INK,
                     font=(FONT,11),anchor='center',justify='center').pack(fill='x',pady=3)

    @requires_role('Owner', 'Employee')
    def trend_show(self,kind):
        def compute():
            source=BusinessData(kind,self.db_path)
            history=source.retrieve_data()
            if len(history)<TrendPrediction.MIN_OBSERVATIONS:
                messagebox.showinfo('More history needed',
                    'At least three distinct dates of completed-order history are required for this forecast.',parent=self)
                predictor=TrendPrediction(source);predictor.generate_prediction(history)
                self.show_trend_chart(history,predictor,title='Recorded history',ylabel='Value')
                return
            prediction=TrendPrediction(source)
            estimate=prediction.generate_prediction(history)
            trend=prediction.generate_trend(history)
            self.show_trend_chart(history,prediction,
                title='Net Order Revenue' if kind=='Financial' else 'Completed Orders',
                ylabel='Revenue (CAD)' if kind=='Financial' else 'Number of orders')
        self.run_action(compute,refresh=False)

    def show_trend_chart(self,history,prediction,*,title,ylabel,summary=''):
        """Embed optional Matplotlib output and its source records in the page."""
        if not hasattr(self,'body'):self.show_page('Trends')
        if not getattr(self,'trend_results',None) or not self.trend_results.winfo_exists():
            self.trend_results=tk.Frame(self.body,bg=LIGHT)
            self.trend_results.pack(fill='both',expand=True)
        for child in self.trend_results.winfo_children():child.destroy()
        text=summary or (f'{title}: {prediction.predicted_value:,.2f} for {prediction.prediction_date} - {prediction.generate_trend(history)}' if prediction.predicted_value is not None else 'At least three distinct recorded dates are required for a forecast.')
        tk.Label(self.trend_results,text=text,bg=LIGHT,fg=INK,justify='center',wraplength=700).pack(fill='x',pady=10)
        opened=False
        if prediction.predicted_value is None:
            self.table(history,[('date','Recorded date'),('value',ylabel)],parent=self.trend_results)
            return False
        try:
            from matplotlib.figure import Figure
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
            figure=Figure(figsize=(9,4),dpi=100,layout='constrained')
            axis=figure.add_subplot(111)
            days=[date.fromisoformat(r['date']) for r in history]
            values=[r['value'] for r in history]
            axis.plot(days,values,marker='o',label='Recorded history')
            axis.plot([days[-1],date.fromisoformat(prediction.prediction_date)],
                [values[-1],prediction.predicted_value],marker='D',linestyle='--',label='Next-day estimate')
            axis.set(title=title,ylabel=ylabel,xlabel='Date');axis.legend();axis.grid(alpha=.25)
            axis.tick_params(axis='x',labelrotation=30)
            canvas=FigureCanvasTkAgg(figure,master=self.trend_results)
            toolbar=NavigationToolbar2Tk(canvas,self.trend_results,pack_toolbar=False)
            toolbar.update();toolbar.pack(fill='x')
            canvas.draw();canvas.get_tk_widget().pack(fill='both',expand=True)
            self.trend_figure=figure
            opened=True
        except (ImportError,OSError,RuntimeError,ValueError,tk.TclError) as exc:
            tk.Label(self.trend_results,text=f'Graph unavailable: {exc}. Numerical forecast and history remain available.',
                bg=LIGHT,fg=MUTED,wraplength=650).pack(fill='x')
        self.table(history,[('date','Recorded date'),('value',ylabel)],parent=self.trend_results)
        return opened

    @requires_role('Owner', 'Employee')
    def trend_ingredient(self):
        items=IngredientData.list_ingredients(self.db_path)
        if not items:
            messagebox.showinfo('No inventory','Create some ingredients before forecasting.',parent=self)
            return
        choices=[f"{v['ingredientID']}: {v['ingredientName']}" for v in items]
        a=self.ask('Select ingredient',[('ingredient','Ingredient',choices[0],'choice',choices)])
        if not a:return
        ingredient_id=int(a['ingredient'].split(':')[0])
        def compute():
            item=next(v for v in items if v['ingredientID']==ingredient_id)
            unit=item['unit'] or 'unit'
            source=IngredientData(ingredient_id,self.db_path)
            history=source.retrieve_data()
            if len(history)<TrendPrediction.MIN_OBSERVATIONS:
                messagebox.showinfo('More consumption history needed',
                    'At least three distinct dates of completed-order ingredient consumption are required.',parent=self)
                predictor=TrendPrediction(source);predictor.generate_prediction(history)
                self.show_trend_chart(history,predictor,title='Recorded history',ylabel='Value')
                return
            predictor=TrendPrediction(source)
            result=predictor.generate_prediction(history)
            trend=predictor.generate_trend(history)
            stock=float(item['quantityOnHand'] or 0)
            reorder=float(item['reorderLevel'] or 0)
            coverage=f'{stock/result:.1f} days (assuming daily use)' if result>0 else 'Unavailable for a zero-use forecast'
            recommendation=('Consider replenishment: estimated use exceeds current stock.' if stock<result*7 else
                'Current stock is at or below its reorder level.' if stock<=reorder else
                'Stock appears sufficient for seven days at this estimated rate.')
            summary=(f"{item['ingredientName']}\nCurrent stock: {stock:,.2f} {unit}\nReorder level: {reorder:,.2f} {unit}\n"
                f"Average per recorded date: {mean(v['value'] for v in history):,.2f} {unit}\n"
                f'Next recorded-day estimate: {result:,.2f} {unit}\n7-day estimate: {result*7:,.2f} {unit}\n'
                f'Stock coverage: {coverage}\nTrend: {trend}\n{recommendation}\n'
                'Forecast uses the last three recorded dates; seven-day estimates assume daily use.')
            self.show_trend_chart(history,predictor,title=f"{item['ingredientName']} Consumption",ylabel=f'{unit} consumed',summary=summary)
        self.run_action(compute,refresh=False)

def main():
    app=OnigiriDesktop()
    app.mainloop()


if __name__=='__main__':
    main()
