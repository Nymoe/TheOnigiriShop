"""Executable data selection and shortcuts never replace restaurant records."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

try:
    import tkinter
except ImportError as exc:
    raise unittest.SkipTest('Executable launcher tests require Tkinter.') from exc

from inventory_service import InventoryService
from demo_tools import backup_database
from windows_launcher import (existing_database, new_database, remembered_database,
                              remember_database, create_shortcut, main)


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)
        self.path = self.folder / 'Existing shop' / 'btm495.db'
        self.service = InventoryService(self.path)
        self.config = self.folder / 'settings.json'

    def test_existing_database_and_backups_stay_in_place(self):
        owner = self.service.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.service.add_ingredient('Rice', 'g', 50, 10, owner)
        backup = backup_database(self.service)
        before = self.path.read_bytes()
        saved_backup = backup.read_bytes()
        self.assertEqual(existing_database(self.path), self.path.resolve())
        remember_database(self.path, self.config)
        self.assertEqual(remembered_database(self.config), self.path.resolve())
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(backup.read_bytes(), saved_backup)
        self.assertEqual(backup.parent, self.path.parent / 'backups')

    def test_missing_selected_or_remembered_database_never_recreated(self):
        missing = self.folder / 'missing.db'
        with self.assertRaises(ValueError):
            existing_database(missing)
        self.config.write_text(json.dumps({'database': str(missing)}))
        with self.assertRaises(ValueError):
            remembered_database(self.config)
        self.assertFalse(missing.exists())

    def test_new_database_refuses_existing_and_missing_folder(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            new_database(self.path)
        with self.assertRaises(ValueError):
            new_database(self.folder / 'missing' / 'shop.db')
        target = self.folder / 'new.db'
        self.assertEqual(new_database(target), target)
        self.assertFalse(target.exists())
        self.assertEqual(self.path.read_bytes(), before)

    def test_non_shop_and_corrupt_files_rejected_without_modification(self):
        for name, data in [('corrupt.db', b'not SQLite'), ('empty.db', b'')]:
            target = self.folder / name
            target.write_bytes(data)
            with self.assertRaises((ValueError, sqlite3.Error)):
                existing_database(target)
            self.assertEqual(target.read_bytes(), data)

    def test_shortcut_pins_quoted_data_path_and_hides_powershell(self):
        exe = self.folder / 'Shop.exe'
        exe.touch()
        before = self.path.read_bytes()
        with patch('windows_launcher.subprocess.run') as run:
            run.return_value.stdout = str(self.folder / 'Test.lnk')
            create_shortcut(exe, self.path, self.folder / 'Test.lnk')
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs['env']['ONIGIRI_DB'], str(self.path.resolve()))
        self.assertEqual(kwargs['env']['ONIGIRI_EXE'], str(exe.resolve()))
        self.assertIn('--database "', run.call_args.args[0][-1])
        self.assertTrue(kwargs['capture_output'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_saved_choice_is_not_replaced_by_explicit_shortcut_argument(self):
        with patch('desktop_app.OnigiriDesktop') as app, \
             patch('windows_launcher.remember_database') as save:
            self.assertEqual(main(['--database', str(self.path)]), 0)
        app.assert_called_once_with(self.path.resolve())
        save.assert_not_called()

    def test_missing_database_reports_error_without_starting_ui(self):
        with patch('tkinter.messagebox.showerror') as error, patch('desktop_app.OnigiriDesktop') as app:
            self.assertEqual(main(['--database', str(self.folder / 'missing.db')]), 1)
        error.assert_called_once()
        app.assert_not_called()

    def test_shortcut_setup_does_not_initialize_or_open_business_data(self):
        before = self.path.read_bytes()
        with patch('windows_launcher.create_shortcut') as shortcut, \
             patch('tkinter.messagebox.showinfo'), patch('desktop_app.OnigiriDesktop') as app:
            self.assertEqual(main(['--create-shortcut', '--database', str(self.path)]), 0)
        shortcut.assert_called_once()
        app.assert_not_called()
        self.assertEqual(self.path.read_bytes(), before)

    def test_cancel_selection_leaves_settings_and_data_untouched(self):
        with patch('windows_launcher.choose_database', return_value=(None, False)), \
             patch('windows_launcher.remember_database') as save:
            self.assertEqual(main(['--choose-database']), 0)
        save.assert_not_called()

    def test_corrupt_settings_do_not_fall_back_to_empty_database(self):
        for data in ('broken json', '[]', '{}', '{"database": null}', '{"database": ""}'):
            self.config.write_text(data)
            with patch('windows_launcher.settings_path', return_value=self.config), \
                 patch('tkinter.messagebox.showerror'), patch('desktop_app.OnigiriDesktop') as app:
                self.assertEqual(main([]), 1)
            app.assert_not_called()


if __name__ == '__main__':
    unittest.main()
