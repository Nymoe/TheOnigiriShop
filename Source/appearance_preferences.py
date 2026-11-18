"""Optional desktop-only appearance preferences kept in the shared SQLite file.

No changes are made to user, employee, customer or business data.  Guest theme
and individual logged-in user preferences have distinct keys.
"""
from __future__ import annotations

from pathlib import Path
from inventory_db import connect

DEFAULT_THEME = 'Classic'
THEMES = {
    'Classic': {
        'INK': '#173237', 'DARK': '#122C2D', 'ACCENT': '#DE7848',
        'LIGHT': '#F6F7F3', 'SURFACE': '#FFFFFF', 'MUTED': '#687B7A',
        'BORDER': '#E3EAE5', 'MINT': '#E4F2E8', 'RED': '#B53B35',
        'SECONDARY': '#E9EFEB', 'ENTRY': '#FBFCFA', 'HEADING': '#E9F0EB',
        'SELECTED': '#D5E8DD', 'SIDE_TEXT': '#C8D8CE',
        'SIDE_MUTED': '#B6CCBE', 'SIDE_ACCENT': '#F3CEAF',
        'SIDE_HOVER': '#31514A', 'SIDE_BUTTON': '#2B4744',
        'SIDE_DIVIDER': '#35504A',
    },
    'Sage': {
        'INK': '#294339', 'DARK': '#244837', 'ACCENT': '#3B8064',
        'LIGHT': '#F5F7ED', 'SURFACE': '#FFFFFF', 'MUTED': '#63736B',
        'BORDER': '#DEE8D7', 'MINT': '#E3EFE0', 'RED': '#AD4643',
        'SECONDARY': '#E5EDDD', 'ENTRY': '#FBFCF6', 'HEADING': '#E5EEDF',
        'SELECTED': '#CFDFD3', 'SIDE_TEXT': '#D9EAD9',
        'SIDE_MUTED': '#C7DCCB', 'SIDE_ACCENT': '#E7E7B4',
        'SIDE_HOVER': '#315D49', 'SIDE_BUTTON': '#315A46',
        'SIDE_DIVIDER': '#54725C',
    },
    'Ocean': {
        'INK': '#173349', 'DARK': '#102C49', 'ACCENT': '#2676B7',
        'LIGHT': '#F1F7FC', 'SURFACE': '#FFFFFF', 'MUTED': '#5E7284',
        'BORDER': '#D9E5F0', 'MINT': '#DEEAF7', 'RED': '#AE4040',
        'SECONDARY': '#E4EDF7', 'ENTRY': '#FCFDFF', 'HEADING': '#E4EDF7',
        'SELECTED': '#CDE2F6', 'SIDE_TEXT': '#D8E8F7',
        'SIDE_MUTED': '#B4C9DA', 'SIDE_ACCENT': '#F4E3B9',
        'SIDE_HOVER': '#254966', 'SIDE_BUTTON': '#22445C',
        'SIDE_DIVIDER': '#476883',
    },
    'Midnight': {
        'INK': '#F0F4F8', 'DARK': '#0C1924', 'ACCENT': '#3278B4',
        'LIGHT': '#121F2A', 'SURFACE': '#1C2B37', 'MUTED': '#ADBFCC',
        'BORDER': '#405260', 'MINT': '#263E47', 'RED': '#BE5757',
        'SECONDARY': '#304452', 'ENTRY': '#263844', 'HEADING': '#314454',
        'SELECTED': '#3B5668', 'SIDE_TEXT': '#D5E4EE',
        'SIDE_MUTED': '#B5C7D5', 'SIDE_ACCENT': '#C5E7FF',
        'SIDE_HOVER': '#284458', 'SIDE_BUTTON': '#274357',
        'SIDE_DIVIDER': '#375264',
    },
}


# Restaurant-inspired palettes share every theme token with the standard schemes.
for name,dark,accent,light in [
    ("McDonald's",'#282320','#C42026','#FFF8E5'),
    ('Starbucks','#123D30','#00754A','#F1F8F3'),
    ('Tim Hortons','#542320','#C8102E','#FFF5EC')]:
    THEMES[name]={**THEMES['Classic'],'DARK':dark,'ACCENT':accent,'LIGHT':light,
                  'SIDE_BUTTON':dark,'SIDE_HOVER':accent,'SIDE_DIVIDER':accent}


class ThemePreferences:
    """Persist guest/default and per-user theme without altering core tables."""
    def __init__(self, db_path: str | Path):
        self.db_path = db_path
        db = connect(db_path)
        try:
            with db:
                db.execute('''CREATE TABLE IF NOT EXISTS DesktopAppearance (
                    accountKey TEXT PRIMARY KEY,
                    themeName TEXT NOT NULL
                )''')
        finally:
            db.close()

    @staticmethod
    def key(user_id: int | None = None) -> str:
        return f'user:{int(user_id)}' if user_id is not None else 'guest'

    def get(self, user_id: int | None = None) -> str:
        db = connect(self.db_path)
        try:
            row = db.execute('SELECT themeName FROM DesktopAppearance WHERE accountKey=?',
                             (self.key(user_id),)).fetchone()
            if row and row['themeName'] in THEMES:
                return row['themeName']
            # User accounts start with Classic unless they selected a scheme
            # in Settings. Legacy guest preferences are not applied to accounts.
            return DEFAULT_THEME
        finally:
            db.close()

    def set(self, name: str, user_id: int | None = None) -> None:
        if name not in THEMES:
            raise ValueError('Choose an available appearance theme.')
        db = connect(self.db_path)
        try:
            with db:
                db.execute('''INSERT INTO DesktopAppearance(accountKey,themeName)
                    VALUES(?,?) ON CONFLICT(accountKey) DO UPDATE SET
                    themeName=excluded.themeName''', (self.key(user_id), name))
        finally:
            db.close()
