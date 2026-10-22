"""Optional demo data and reversible database reset/restore tools.

IMPORTANT: Reset replaces the *entire* database (including any broader-system
module tables). Login accounts and their linked profiles are copied over if requested.
A SQLite-consistent backup is created before either reset or restore.
Run these actions only when no other app is using the SQLite file.
"""
from __future__ import annotations

from contextlib import closing
from contextlib import closing
from datetime import datetime
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from inventory_db import DEFAULT_DB, connect, transaction
from inventory_service import InventoryError, InventoryService

# Invented classroom demonstration numbers, not actual business stock or prices.
INGREDIENTS = [
    ("Sushi Rice", "g", 3500, 1200),
    ("Nori Sheets", "sheets", 30, 12),
    ("Canned Tuna", "g", 650, 250),
    ("Mayonnaise", "g", 600, 150),
    ("Salmon", "g", 800, 250),
    ("Cucumber", "g", 700, 200),
    ("Umeboshi (Pickled Plum)", "g", 350, 150),
    ("Sesame Seeds", "g", 300, 100),
    ("Soy Sauce", "ml", 800, 250),
    ("Furikake", "g", 250, 100),
    ("Firm Tofu", "g", 700, 200),
    ("Teriyaki Sauce", "ml", 750, 200),
    ("Green Onions", "g", 400, 120),
    ("Onigiri Wrappers", "pieces", 50, 20),
]
RECIPES = [
    ("Tuna Mayo Onigiri", 5.50, {"Sushi Rice": 120, "Nori Sheets": 1, "Canned Tuna": 55, "Mayonnaise": 20, "Onigiri Wrappers": 1}),
    ("Salmon Onigiri", 6.25, {"Sushi Rice": 120, "Nori Sheets": 1, "Salmon": 70, "Sesame Seeds": 3, "Onigiri Wrappers": 1}),
    ("Umeboshi Onigiri", 4.75, {"Sushi Rice": 120, "Nori Sheets": 1, "Umeboshi (Pickled Plum)": 25, "Onigiri Wrappers": 1}),
    ("Teriyaki Tofu Onigiri", 5.75, {"Sushi Rice": 120, "Nori Sheets": 1, "Firm Tofu": 65, "Teriyaki Sauce": 15, "Green Onions": 10, "Onigiri Wrappers": 1}),
    ("Cucumber Sesame Onigiri", 4.50, {"Sushi Rice": 120, "Nori Sheets": 1, "Cucumber": 60, "Sesame Seeds": 8, "Onigiri Wrappers": 1}),
    ("Spicy Tuna Onigiri", 6.00, {"Sushi Rice": 120, "Nori Sheets": 1, "Canned Tuna": 65, "Mayonnaise": 18, "Soy Sauce": 8, "Onigiri Wrappers": 1}),
    ("Plain Onigiri", 3.50, {"Sushi Rice": 120, "Nori Sheets": 1, "Onigiri Wrappers": 1}),
]
SUPPLIERS = [
    ("Montreal Seafood Supply (Demo)", "seafood@example.test"),
    ("North Shore Rice & Dry Goods (Demo)", "drygoods@example.test"),
    ("Quebec Fresh Produce (Demo)", "produce@example.test"),
]
COMPLETED_ORDERS = [
    {"Tuna Mayo Onigiri": 3, "Salmon Onigiri": 2},
    {"Umeboshi Onigiri": 4, "Cucumber Sesame Onigiri": 2},
    {"Spicy Tuna Onigiri": 4, "Teriyaki Tofu Onigiri": 2},
    {"Salmon Onigiri": 2, "Plain Onigiri": 2},
]
PENDING_ORDER = {"Salmon Onigiri": 2, "Umeboshi Onigiri": 1}


def populate_demo_data(svc: InventoryService, user_id: int) -> dict[str, int]:
    """Insert a cohesive shop scenario in ONE transaction; refuse nonempty data."""
    with transaction(svc.db_path) as db:
        user = db.execute('SELECT role FROM "User" WHERE userID=? AND passwordHash IS NOT NULL',
                          (user_id,)).fetchone()
        if not user or user['role'] != 'Owner':
            raise InventoryError("Only a logged-in Owner can populate demo data.")
        for table in ('InventoryItem', 'Recipe', 'Supplier', 'InventoryTransaction',
                      'InventoryOrder', 'InventoryAdjustment', 'LowStockAlert', 'OrderRecipe'):
            if db.execute(f'SELECT 1 FROM "{table}" LIMIT 1').fetchone():
                raise InventoryError("Existing inventory/demo records found. To protect your data, "
                                     "use Backup & Reset instead of adding demo records twice.")
        ingredient_ids = {}
        for name, unit, quantity, reorder in INGREDIENTS:
            ingredient_id = db.execute(
                'INSERT INTO InventoryItem(ingredientName, unit, quantityOnHand, reorderLevel) '
                'VALUES (?, ?, ?, ?)', (name, unit, quantity, reorder)
            ).lastrowid
            ingredient_ids[name] = ingredient_id
            svc._record_transaction(db, ingredient_id, user_id, 'Opening Stock', quantity,
                                    notes='Demo opening balance')
            svc._sync_alert(db, ingredient_id)

        supplier_ids = {}
        for name, contact in SUPPLIERS:
            supplier_ids[name] = db.execute(
                'INSERT INTO Supplier(name,contactInfo) VALUES(?,?)', (name, contact)
            ).lastrowid

        recipe_ids = {}
        prices = {}
        for name, price, components in RECIPES:
            recipe_id = db.execute('INSERT INTO Recipe(name,price) VALUES(?,?)',
                                   (name, price)).lastrowid
            recipe_ids[name], prices[name] = recipe_id, price
            for ingredient, quantity in components.items():
                db.execute('INSERT INTO RecipeIngredient(recipeID,ingredientID,quantityRequired) '
                           'VALUES(?,?,?)', (recipe_id, ingredient_ids[ingredient], quantity))

        def insert_order(items: dict[str, int], status: str) -> int:
            total = round(sum(prices[name] * qty for name, qty in items.items()), 2)
            order_id = db.execute(
                'INSERT INTO "Order"(orderDate,totalAmount,status,createdByUserID) '
                'VALUES(date("now"),?,?,?)', (total, 'Pending', user_id)
            ).lastrowid
            for recipe_name, count in items.items():
                db.execute('INSERT INTO OrderRecipe(orderID,recipeID,quantity) VALUES(?,?,?)',
                           (order_id, recipe_ids[recipe_name], count))
            if status == 'Completed':
                # Same ingredient calculations/stock/audit methods used by the service.
                required = {}
                for recipe_name, count in items.items():
                    recipe_spec = next(r for r in RECIPES if r[0] == recipe_name)
                    for ingredient_name, amount in recipe_spec[2].items():
                        iid = ingredient_ids[ingredient_name]
                        required[iid] = required.get(iid, 0) + amount * count
                for iid, amount in required.items():
                    svc._apply_change(db, iid, -amount, user_id, 'Customer Order',
                                      customer_order_id=order_id,
                                      notes='Completed demo customer order')
                db.execute('UPDATE "Order" SET status="Completed" WHERE orderID=?', (order_id,))
            return order_id

        for items in COMPLETED_ORDERS:
            insert_order(items, 'Completed')
        insert_order(PENDING_ORDER, 'Pending')

        # A partially received purchase order demonstrates supplier delivery.
        po_id = db.execute(
            'INSERT INTO InventoryOrder(orderDate,status,notes) '
            'VALUES(date("now"),?,?)', ('Partially Received', 'Sample reorder - delivery in progress')
        ).lastrowid
        for name, quantity, received in [
            ('Sushi Rice', 2000, 150), ('Nori Sheets', 50, 0), ('Canned Tuna', 700, 0)
        ]:
            ingredient_id = ingredient_ids[name]
            db.execute('INSERT INTO InventoryOrderLine(inventoryOrderID,ingredientID,quantityOrdered,receivedQuantity) '
                       'VALUES(?,?,?,?)', (po_id, ingredient_id, quantity, received))
            if received:
                svc._apply_change(db, ingredient_id, received, user_id, 'Supplier Delivery',
                                  supplier_id=supplier_ids['North Shore Rice & Dry Goods (Demo)'],
                                  inventory_order_id=po_id, notes='Partial demo delivery')

        return {'ingredients': len(ingredient_ids), 'suppliers': len(supplier_ids),
                'recipes': len(recipe_ids), 'customer_orders': len(COMPLETED_ORDERS) + 1,
                'completed_orders': len(COMPLETED_ORDERS), 'purchase_orders': 1}


def _path(svc: InventoryService) -> Path:
    return Path(svc.db_path or DEFAULT_DB).resolve()


def _assert_integrity(path: Path) -> None:
    if not path.is_file():
        raise InventoryError(f"Database file not found: {path}")
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
            result = db.execute('PRAGMA integrity_check').fetchone()
            if not result or result[0] != 'ok':
                raise InventoryError(f"Database integrity check failed: {path.name}")
    except sqlite3.DatabaseError as exc:
        raise InventoryError(f"Cannot open a valid SQLite database: {path}") from exc


def _backup_folder(db_path: Path) -> Path:
    return db_path.parent / 'backups'


def list_backups(svc: InventoryService) -> list[Path]:
    db_path = _path(svc)
    folder = _backup_folder(db_path)
    prefix = db_path.stem + '_backup_'
    return sorted((p for p in folder.glob(prefix + '*' + db_path.suffix)
                   if p.is_file() and p.name.startswith(prefix)), reverse=True) if folder.exists() else []


def backup_database(svc: InventoryService, label: str = 'manual') -> Path:
    """Consistent online SQLite backup; originals are never renamed/deleted."""
    db_path = _path(svc)
    _assert_integrity(db_path)
    folder = _backup_folder(db_path)
    folder.mkdir(parents=True, exist_ok=True)
    # A short random suffix prevents collisions even during rapid demo runs.
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    safe_label = ''.join(c for c in label if c.isalnum() or c == '_')[:25] or 'manual'
    target = folder / f'{db_path.stem}_backup_{stamp}_{safe_label}_{uuid4().hex[:8]}{db_path.suffix}'
    temp = target.with_suffix('.incomplete')
    try:
        with closing(sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True, timeout=10)) as src:
            with closing(sqlite3.connect(temp)) as dest:
                src.backup(dest)
        _assert_integrity(temp)
        os.replace(temp, target)
        return target
    finally:
        temp.unlink(missing_ok=True)


def _safe_swap(temp: Path, live: Path) -> None:
    """Replace a complete closed database, only if no WAL clients are active."""
    _assert_integrity(temp)
    # WAL sidecars can replay after an OS replacement: never swap in that state.
    with closing(sqlite3.connect(live, timeout=2)) as db:
        mode = db.execute('PRAGMA journal_mode').fetchone()[0].lower()
        if mode == 'wal':
            # Changing from WAL to DELETE requires exclusive control of the DB.
            mode = db.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower()
            if mode != 'delete':
                raise InventoryError('Close other apps using the database before resetting it.')
    if live.with_name(live.name + '-wal').exists() or live.with_name(live.name + '-shm').exists():
        raise InventoryError('SQLite WAL sidecar files are still active. Close other apps and retry.')
    os.replace(temp, live)


def reset_database(svc: InventoryService, user_id: int, *, with_demo: bool = True,
                   preserve_accounts: bool = True) -> Path:
    """Backup, build/verify a fresh database, then atomically replace the live file.

    All non-login tables (including other modules') are wiped. If preserve_accounts
    is False the next app startup creates a new Owner.
    """
    db_path = _path(svc)
    if not db_path.is_file():
        raise InventoryError('There is no active database to reset.')
    users = []
    with closing(connect(db_path)) as db:
        actor = db.execute('SELECT role FROM "User" WHERE userID=? AND passwordHash IS NOT NULL',
                           (user_id,)).fetchone()
        if not actor or actor['role'] != 'Owner':
            raise InventoryError('Only an authenticated Owner can reset the database.')
        if preserve_accounts:
            users = [dict(r) for r in db.execute(
                'SELECT u.userID,u.name,u.email,u.username,u.role,u.passwordHash,u.passwordSalt,u.accountActive, '
                'e.hourlyRate,e.isActive,p.profileID,p.phoneNumber,p.dateOfBirth,p.version '
                'FROM "User" u LEFT JOIN Employee e ON u.userID=e.userID '
                'LEFT JOIN Profile p ON p.userID=u.userID '
                'WHERE u.passwordHash IS NOT NULL AND u.passwordSalt IS NOT NULL')]
    backup = backup_database(svc, 'before_reset')
    handle, filename = tempfile.mkstemp(prefix='.onigiri_new_', suffix='.db', dir=db_path.parent)
    os.close(handle)
    temp = Path(filename)
    try:
        fresh = InventoryService(temp)
        if users:
            with transaction(temp) as db:
                for u in users:
                    db.execute('INSERT INTO "User"(userID,name,email,username,role,passwordHash,passwordSalt,accountActive) '
                               'VALUES(?,?,?,?,?,?,?,?)',
                               (u['userID'], u['name'], u['email'], u['username'], u['role'],
                                u['passwordHash'], u['passwordSalt'], u['accountActive']))
                    if u['role'] == 'Owner':
                        db.execute('INSERT INTO Owner(userID) VALUES(?)', (u['userID'],))
                    elif u['role'] == 'Customer':
                        db.execute('INSERT INTO Customer(userID) VALUES(?)', (u['userID'],))
                    else:
                        db.execute('INSERT INTO Employee(userID,hourlyRate,isActive) VALUES(?,?,?)',
                                   (u['userID'], u['hourlyRate'] or 0,
                                    u['isActive'] if u['isActive'] is not None else 1))
                    if u['profileID'] is not None:
                        db.execute('INSERT INTO Profile(profileID,userID,name,phoneNumber,dateOfBirth,version) '
                                   'VALUES(?,?,?,?,?,?)',
                                   (u['profileID'],u['userID'],u['name'] or '',u['phoneNumber'],
                                    u['dateOfBirth'],u['version']))
        if with_demo:
            if not preserve_accounts:
                # Can't seed while no owner account exists; start empty instead.
                raise InventoryError('A seeded demo requires preserved login accounts. '
                                     'Choose an empty reset if removing all accounts.')
            populate_demo_data(fresh, user_id)
        _safe_swap(temp, db_path)
        return backup
    finally:
        temp.unlink(missing_ok=True)


def restore_database(svc: InventoryService, user_id: int, backup_file: Path) -> Path:
    """Restore an existing listed backup; back up current state first.

    This restores the ENTIRE SQLite database, including users and other modules.
    """
    db_path = _path(svc)
    with closing(connect(db_path)) as db:
        owner = db.execute('SELECT 1 FROM "User" WHERE userID=? AND role="Owner" '
                           'AND passwordHash IS NOT NULL', (user_id,)).fetchone()
        if not owner:
            raise InventoryError('Only an authenticated Owner can restore a backup.')
    backup_file = Path(backup_file).resolve()
    if backup_file not in list_backups(svc):
        raise InventoryError('Choose a backup from the list shown by this application.')
    _assert_integrity(backup_file)
    safety_backup = backup_database(svc, 'before_restore')
    handle, filename = tempfile.mkstemp(prefix='.onigiri_restore_', suffix='.db', dir=db_path.parent)
    os.close(handle)
    temp = Path(filename)
    try:
        with closing(sqlite3.connect(backup_file.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(temp)) as dest:
                src.backup(dest)
        _safe_swap(temp, db_path)
        return safety_backup
    finally:
        temp.unlink(missing_ok=True)
