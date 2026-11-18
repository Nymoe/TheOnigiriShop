"""Folder layout, data selection and backup workflows use disposable files."""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import application_paths
from demo_tools import backup_database, list_backups, restore_database
from inventory_service import InventoryService
from windows_launcher import main, remembered_database


class ApplicationPathTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def test_source_paths_are_independent_of_working_directory(self):
        source = Path(application_paths.__file__).resolve().parent
        script = ('import sys;sys.path.insert(0,sys.argv[1]);'
                  'from inventory_db import DEFAULT_DB;'
                  'from desktop_app import database_path,resource;'
                  'assert database_path()==DEFAULT_DB;'
                  'print(DEFAULT_DB);print(resource("onigiri.ico"))')
        result = subprocess.run([sys.executable, '-B', '-c', script, str(source)],
                                cwd=self.root, check=True, capture_output=True, text=True)
        paths = result.stdout.splitlines()
        self.assertEqual(Path(paths[0]), source.parent / 'Data' / 'btm495.db')
        self.assertEqual(Path(paths[1]), source / 'Assets' / 'onigiri.ico')
        self.assertFalse((self.root / 'btm495.db').exists())
        self.assertFalse((source / 'btm495.db').exists())

    def test_frozen_paths_use_executable_and_extracted_assets(self):
        extracted = self.root / 'runtime'
        with patch.object(sys, 'frozen', True, create=True), \
             patch.object(sys, 'executable', str(self.root / 'TheOnigiriShop.exe')), \
             patch.object(sys, '_MEIPASS', str(extracted), create=True):
            self.assertEqual(application_paths.project_root(), self.root)
            self.assertEqual(application_paths.default_database(), self.root / 'Data' / 'btm495.db')
            self.assertEqual(application_paths.asset_path('onigiri.ico'), extracted / 'onigiri.ico')

    def test_project_data_uses_root_backups_and_external_data_stays_local(self):
        with patch('application_paths.project_root', return_value=self.root):
            self.assertEqual(application_paths.backup_folder(self.root / 'Data' / 'btm495.db'),
                             self.root / 'Backups')
            external = self.root / 'Another shop' / 'Data' / 'shop.db'
            self.assertEqual(application_paths.backup_folder(external), external.parent / 'backups')

    def test_project_backup_list_and_restore_keep_history(self):
        path = self.root / 'Data' / 'btm495.db'
        service = InventoryService(path)
        owner = service.create_user('Owner', 'owner', 'owner-password', 'Owner')
        service.add_ingredient('Rice', 'g', 50, 10, owner)
        with patch('application_paths.project_root', return_value=self.root):
            backup = backup_database(service)
            saved = backup.read_bytes()
            service.add_ingredient('Nori', 'sheets', 20, 5, owner)
            safety = restore_database(service, owner, backup)
            self.assertEqual(backup.parent, self.root / 'Backups')
            self.assertEqual(set(list_backups(service)), {backup, safety})
            self.assertEqual(backup.read_bytes(), saved)
        self.assertEqual([r['ingredientName'] for r in service.inventory()], ['Rice'])
        self.assertFalse((path.parent / 'backups').exists())

    def test_old_saved_default_relocates_only_after_validating_existing_data(self):
        path = self.root / 'Data' / 'btm495.db'
        InventoryService(path)
        before = path.read_bytes()
        config = self.root / 'settings.json'
        config.write_text(json.dumps({'database': str(self.root / 'btm495.db')}))
        with patch('application_paths.project_root', return_value=self.root), \
             patch('windows_launcher.project_root', return_value=self.root):
            for _ in range(2):
                self.assertEqual(remembered_database(config), path)
        self.assertEqual(json.loads(config.read_text())['database'], str(path))
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse((self.root / 'btm495.db').exists())

    def test_missing_external_saved_path_is_not_redirected_to_project_data(self):
        InventoryService(self.root / 'Data' / 'btm495.db')
        config = self.root / 'settings.json'
        original = json.dumps({'database': str(self.root / 'Other shop' / 'btm495.db')})
        config.write_text(original)
        with patch('application_paths.project_root', return_value=self.root), \
             patch('windows_launcher.project_root', return_value=self.root):
            with self.assertRaisesRegex(ValueError, 'Database not found'):
                remembered_database(config)
        self.assertEqual(config.read_text(), original)

    def test_corrupt_relocated_default_does_not_update_saved_choice(self):
        data = self.root / 'Data'
        data.mkdir()
        (data / 'btm495.db').write_bytes(b'not SQLite')
        config = self.root / 'settings.json'
        original = json.dumps({'database': str(self.root / 'btm495.db')})
        config.write_text(original)
        import sqlite3
        with patch('application_paths.project_root', return_value=self.root), \
             patch('windows_launcher.project_root', return_value=self.root):
            with self.assertRaises(sqlite3.DatabaseError):
                remembered_database(config)
        self.assertEqual(config.read_text(), original)

    def test_executable_uses_existing_project_data_when_no_choice_is_saved(self):
        path = self.root / 'Data' / 'btm495.db'
        InventoryService(path)
        before = path.read_bytes()
        config = self.root / 'settings.json'
        with patch('application_paths.project_root', return_value=self.root), \
             patch('windows_launcher.settings_path', return_value=config), \
             patch('windows_launcher.choose_database') as choose, \
             patch('desktop_app.OnigiriDesktop') as app:
            self.assertEqual(main([]), 0)
        app.assert_called_once_with(path)
        choose.assert_not_called()
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(json.loads(config.read_text())['database'], str(path))

    def test_explicit_choose_still_overrides_project_default(self):
        InventoryService(self.root / 'Data' / 'btm495.db')
        with patch('application_paths.project_root', return_value=self.root), \
             patch('windows_launcher.choose_database', return_value=(None, False)) as choose, \
             patch('desktop_app.OnigiriDesktop') as app:
            self.assertEqual(main(['--choose-database']), 0)
        choose.assert_called_once()
        app.assert_not_called()

    def test_shortcut_uses_relocated_asset(self):
        from windows_launcher import create_shortcut
        path = self.root / 'Data' / 'btm495.db'
        InventoryService(path)
        executable = self.root / 'TheOnigiriShop.exe'
        executable.touch()
        icon = self.root / 'Source' / 'Assets' / 'onigiri.ico'
        icon.parent.mkdir(parents=True)
        icon.touch()
        with patch('windows_launcher.subprocess.run') as run:
            run.return_value.stdout = str(self.root / 'shop.lnk')
            create_shortcut(executable, path, self.root / 'shop.lnk')
        self.assertEqual(run.call_args.kwargs['env']['ONIGIRI_ICON'], str(icon))
