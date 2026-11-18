"""Executable entry point with explicit, persistent database selection."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from application_paths import project_root, default_database, backup_folder


def settings_path() -> Path:
    return Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'TheOnigiriShop' / 'settings.json'


def existing_database(value) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f'Database not found: {path}\nSelect the existing file; no replacement was created.')
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
        if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('The selected database failed its integrity check.')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'User', 'InventoryItem', 'Order'} <= tables:
            raise ValueError('Select an existing Onigiri Shop database.')
    return path


def new_database(value) -> Path:
    path = Path(value).expanduser().resolve()
    if path.exists():
        raise ValueError('A file already exists there. Use the existing-database option; it will not be overwritten.')
    if not path.parent.is_dir():
        raise ValueError('Choose an existing, writable folder for the new database.')
    return path


def remembered_database(config: Path) -> Path | None:
    if not config.exists():
        return None
    value = json.loads(config.read_text(encoding='utf-8'))
    if not isinstance(value, dict) or not isinstance(value.get('database'), str) or not value['database'].strip():
        raise ValueError('Saved settings do not contain a valid database path.')
    path = Path(value['database']).expanduser().resolve()
    # Only relocate this installation's former default, never another shop's file.
    if not path.exists() and path == project_root() / 'btm495.db' and default_database().is_file():
        path = existing_database(default_database())
        remember_database(path, config)
        return path
    return existing_database(path)


def remember_database(path: Path, config: Path) -> None:
    config.parent.mkdir(parents=True, exist_ok=True)
    temporary = config.with_suffix('.tmp')
    temporary.write_text(json.dumps({'database': str(path)}, indent=2), encoding='utf-8')
    temporary.replace(config)


def choose_database() -> tuple[Path | None, bool]:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        use_existing = messagebox.askyesnocancel('Choose restaurant data',
            'Use an existing Onigiri Shop database?\n\nYes: select your existing btm495.db. '
            'Project data uses Backups in the application folder; external data keeps backups beside it.\n'
            'No: create a new, empty restaurant database.\nCancel: exit.', parent=root)
        if use_existing is None:
            return None, False
        if use_existing:
            name = filedialog.askopenfilename(parent=root, title='Select existing btm495.db',
                filetypes=[('SQLite database', '*.db'), ('All files', '*.*')])
            return (existing_database(name), False) if name else (None, False)
        name = filedialog.asksaveasfilename(parent=root, title='Choose a NEW database location',
            initialfile='btm495.db', defaultextension='.db', confirmoverwrite=False,
            filetypes=[('SQLite database', '*.db')])
        return (new_database(name), True) if name else (None, False)
    finally:
        root.destroy()


def create_shortcut(executable: Path, database: Path, destination: Path | None = None) -> Path:
    """Pin the data file in shortcut arguments; never copy or replace shop data."""
    database = existing_database(database)
    executable = executable.resolve(strict=True)
    if '"' in str(database):
        raise ValueError('The database path cannot contain quotation marks.')
    project_icon=executable.parent / 'Source' / 'Assets' / 'onigiri.ico'
    icon=str(project_icon) if project_icon.is_file() else str(executable)+',0'
    env = dict(os.environ, ONIGIRI_EXE=str(executable), ONIGIRI_DB=str(database), ONIGIRI_ICON=icon,
               ONIGIRI_SHORTCUT=str(destination.resolve()) if destination else '')
    script = """
$ErrorActionPreference='Stop'
$target=$env:ONIGIRI_SHORTCUT
$shell=New-Object -ComObject WScript.Shell
if (-not $target) {
    $desktop=[Environment]::GetFolderPath('Desktop')
    $target=Join-Path $desktop 'The Onigiri Shop.lnk'
    $number=2
    while (Test-Path -LiteralPath $target) {
        if ($shell.CreateShortcut($target).TargetPath -eq $env:ONIGIRI_EXE) { break }
        $target=Join-Path $desktop ('The Onigiri Shop ('+$number+').lnk')
        $number++
    }
}
if (Test-Path -LiteralPath $target) {
    $existing=$shell.CreateShortcut($target)
    if ($existing.TargetPath -ne $env:ONIGIRI_EXE) { throw 'A different shortcut already uses this name. Rename it first.' }
}
$link=$shell.CreateShortcut($target)
$link.TargetPath=$env:ONIGIRI_EXE
$link.Arguments='--database "'+$env:ONIGIRI_DB+'"'
$link.WorkingDirectory=Split-Path -Parent $env:ONIGIRI_EXE
$link.IconLocation=$env:ONIGIRI_ICON
$link.Description='The Onigiri Shop restaurant management'
$link.Save()
Write-Output $target
"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
            env=env, check=True, capture_output=True, text=True,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.CalledProcessError as exc:
        raise OSError('Could not create the shortcut: ' + (exc.stderr or '').strip()) from exc
    return Path(result.stdout.strip())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='The Onigiri Shop desktop application')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--database', help='Existing database to use in place; never created if missing')
    group.add_argument('--new-database', help='Explicit location for a new database; must not exist')
    parser.add_argument('--choose-database', action='store_true', help='Choose data again instead of using saved settings')
    parser.add_argument('--create-shortcut', action='store_true', help='Create a desktop shortcut without opening business data')
    args = parser.parse_args(argv)
    from tkinter import messagebox
    try:
        if args.database:
            path, fresh = existing_database(args.database), False
        elif args.new_database:
            path, fresh = new_database(args.new_database), True
        else:
            path = None if args.choose_database else remembered_database(settings_path())
            fresh = False
            if path is None and not args.choose_database and default_database().is_file():
                path = existing_database(default_database())
            if path is None:
                path, fresh = choose_database()
        if path is None:
            return 0
        if args.create_shortcut:
            if fresh:
                raise ValueError('Create the new restaurant database first, then create its shortcut.')
            executable = Path(sys.executable) if getattr(sys, 'frozen', False) else project_root() / 'TheOnigiriShop.exe'
            shortcut = create_shortcut(executable, path)
            messagebox.showinfo('Shortcut created', f'{shortcut}\n\nUses database:\n{path}\n\nBackups:\n{backup_folder(path)}\n\nDatabase and backups were left in place.')
            return 0
        from desktop_app import OnigiriDesktop
        app = OnigiriDesktop(path)
        # Explicit shortcut arguments do not change another installation's saved choice.
        if not args.database:
            remember_database(path, settings_path())
        app.mainloop()
        return 0
    except (OSError, ValueError, KeyError, sqlite3.Error, subprocess.SubprocessError) as exc:
        messagebox.showerror('Could not start The Onigiri Shop',
            f'{exc}\n\nExisting data was not replaced. Use --choose-database to select another database.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
