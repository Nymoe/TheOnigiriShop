"""New demo/reset/restore regression tests; use temp DBs only."""
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from demo_tools import backup_database, list_backups, populate_demo_data, reset_database, restore_database
from inventory_db import connect
from inventory_service import InventoryError, InventoryService


class DemoToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'btm495.db'
        self.svc = InventoryService(self.path)
        self.owner_id = self.svc.create_user('Owner Person', 'owner', 'my-secret-password', 'Owner')
        self.employee_id = self.svc.create_user('Staff Person', 'staff', 'staff-password', 'Employee')

    def _counts(self):
        with sqlite3.connect(self.path) as db:
            return {t: db.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    for t in ('User','Recipe','InventoryItem','Supplier','Order','OrderRecipe',
                              'InventoryTransaction','LowStockAlert','InventoryOrder',
                              'InventoryOrderLine','InventoryAdjustment')}

    def test_demo_data_is_realistic_and_atomic(self):
        result = populate_demo_data(self.svc, self.owner_id)
        self.assertEqual(result, {'ingredients':14, 'suppliers':3, 'recipes':7,
                                  'customer_orders':5, 'completed_orders':4,
                                  'purchase_orders':1})
        self.assertEqual(len(self.svc.alerts()), 3)
        stocks = {i['ingredientName']: i['quantityOnHand'] for i in self.svc.inventory()}
        self.assertEqual(stocks['Sushi Rice'], 1130)
        self.assertEqual(stocks['Nori Sheets'], 9)
        self.assertEqual(stocks['Canned Tuna'], 225)
        orders = self.svc.customer_orders()
        self.assertEqual(sum(o['status']=='Completed' for o in orders), 4)
        self.assertEqual(sum(o['status']=='Pending' for o in orders), 1)
        po = self.svc.purchase_orders()[0]
        self.assertEqual(po['status'], 'Partially Received')
        self.assertEqual(len(self.svc.purchase_order_lines(po['inventoryOrderID'])), 3)
        old = self._counts()
        with self.assertRaises(InventoryError):
            populate_demo_data(self.svc, self.owner_id)
        self.assertEqual(self._counts(), old)

    def test_demo_rejects_non_empty_without_touching_stock(self):
        self.svc.add_ingredient('Existing rice', 'g', 3, 1, self.owner_id)
        old = self._counts()
        with self.assertRaises(InventoryError):
            populate_demo_data(self.svc, self.owner_id)
        self.assertEqual(self._counts(), old)

    def test_manual_backup_is_consistent_and_not_destructive(self):
        populate_demo_data(self.svc, self.owner_id)
        before = self._counts()
        backup = backup_database(self.svc)
        self.assertTrue(backup.exists())
        self.assertIn(backup, list_backups(self.svc))
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Recipe').fetchone()[0], 7)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.assertEqual(before, self._counts())

    def test_backup_reset_empty_keeps_users(self):
        populate_demo_data(self.svc, self.owner_id)
        old = self._counts()
        backup = reset_database(self.svc, self.owner_id, with_demo=False)
        self.assertTrue(backup.exists())
        counts = self._counts()
        self.assertEqual(counts['User'], 2)
        self.assertEqual(counts['Recipe'], 0)
        self.assertEqual(counts['InventoryItem'], 0)
        self.assertEqual(self.svc.login('owner','my-secret-password')['userID'], self.owner_id)
        self.assertEqual(self.svc.login('staff','staff-password')['userID'], self.employee_id)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Recipe').fetchone()[0], old['Recipe'])

    def test_demo_reset_can_repeat_and_restore_full_database(self):
        populate_demo_data(self.svc, self.owner_id)
        # A representative non-inventory table in the broader team's system.
        with sqlite3.connect(self.path) as db:
            db.execute('CREATE TABLE OtherModule(marker TEXT)')
            db.execute('INSERT INTO OtherModule VALUES (?)', ('original data',))
        snapshot = self._counts()
        first_backup = reset_database(self.svc, self.owner_id, with_demo=True)
        self.assertEqual(self._counts(), snapshot)
        with sqlite3.connect(self.path) as db:
            with self.assertRaises(sqlite3.OperationalError):
                db.execute('SELECT * FROM OtherModule')
        self.svc.adjust_stock(next(i['ingredientID'] for i in self.svc.inventory()
                                   if i['ingredientName'] == 'Sushi Rice'), 'add', 12, self.owner_id)
        pre_restore = self._counts()
        safety_backup = restore_database(self.svc, self.owner_id, first_backup)
        self.assertTrue(safety_backup.exists())
        self.assertEqual(self._counts(), snapshot)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute('SELECT marker FROM OtherModule').fetchone()[0], 'original data')
        with sqlite3.connect(safety_backup) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM InventoryTransaction').fetchone()[0],
                             pre_restore['InventoryTransaction'])

    def test_factory_reset_clears_all_accounts_but_preserves_backup(self):
        populate_demo_data(self.svc, self.owner_id)
        backup = reset_database(self.svc, self.owner_id, with_demo=False, preserve_accounts=False)
        self.assertTrue(backup.exists())
        self.assertFalse(self.svc.has_logins())
        self.assertEqual(self._counts()['User'], 0)
        self.assertEqual(self._counts()['InventoryItem'], 0)
        # New owner setup is now possible again.
        replacement = self.svc.create_user('New Owner', 'new-owner', 'new-owner-password', 'Owner')
        self.assertEqual(self.svc.login('new-owner', 'new-owner-password')['userID'], replacement)

    def test_unsupported_factory_with_seed_does_not_wipe_live_database(self):
        populate_demo_data(self.svc, self.owner_id)
        counts = self._counts()
        with self.assertRaises(InventoryError):
            reset_database(self.svc, self.owner_id, with_demo=True, preserve_accounts=False)
        self.assertEqual(self._counts(), counts)

    def test_invalid_restore_path_is_rejected(self):
        populate_demo_data(self.svc, self.owner_id)
        other = self.path.parent / 'untrusted.db'
        other.write_text('fake database')
        before = self._counts()
        with self.assertRaises(InventoryError):
            restore_database(self.svc, self.owner_id, other)
        self.assertEqual(self._counts(), before)

    def test_failed_swap_does_not_modify_current_database(self):
        populate_demo_data(self.svc, self.owner_id)
        original = self._counts()
        with patch('demo_tools._safe_swap', side_effect=OSError('simulated file lock')):
            with self.assertRaises(OSError):
                reset_database(self.svc, self.owner_id, with_demo=False)
        self.assertEqual(self._counts(), original)
        self.assertTrue(list_backups(self.svc))

    def test_only_owner_can_seed_or_reset(self):
        with self.assertRaises(InventoryError):
            populate_demo_data(self.svc, self.employee_id)
        with self.assertRaises(InventoryError):
            reset_database(self.svc, self.employee_id)

class DemoMenuFlowTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'btm495.db'
        self.svc = InventoryService(self.path)
        self.user_id = self.svc.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.user = self.svc.login('owner', 'owner-password')

    def test_reset_menu_requests_password_and_returns_to_login(self):
        from inventory_cli import demo_menu
        # menu choice=3; confirmation=RESET; re-authentication via mocked getpass
        with patch('inventory_cli.prompt', side_effect=['3', 'RESET']), \
             patch('inventory_cli.getpass', return_value='owner-password'):
            self.assertTrue(demo_menu(self.svc, self.user))
        self.assertEqual(len(self.svc.inventory()), 14)
        self.assertEqual(self.svc.login('owner', 'owner-password')['role'], 'Owner')
        self.assertTrue(list_backups(self.svc))

    def test_account_menu_adds_owner(self):
        from inventory_cli import employees_menu
        with patch('inventory_cli.confirm', side_effect=[True, True]), \
             patch('inventory_cli.prompt', side_effect=['o', 'Secondary Owner', 'second']), \
             patch('inventory_cli.getpass', side_effect=['second-password','second-password']):
            employees_menu(self.svc, self.user)
        self.assertEqual(self.svc.login('second', 'second-password')['role'], 'Owner')


if __name__ == '__main__':
    unittest.main(verbosity=2)
