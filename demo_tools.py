"""Optional demo data and reversible database reset/restore tools.

IMPORTANT: Reset replaces the *entire* database (including any broader-system
module tables). Login accounts and their linked profiles are copied over if requested.
A SQLite-consistent backup is created before either reset or restore.
Run these actions only when no other app is using the SQLite file.
"""
from __future__ import annotations

from contextlib import closing
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

from inventory_db import DEFAULT_DB, connect, transaction
from inventory_service import InventoryError, InventoryService
from accounting_service import post_source_transaction
from payroll import Employee, Payroll, PayrollEntry

# Fictional sample quantities and prices, not live business records.
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
                post_source_transaction(
                    db, kind='Sale', when=datetime.now().date().isoformat(),
                    description=f'Completed customer order #{order_id}',
                    reference=f'ORDER-{order_id}', amount=total,
                    source_type='Order', source_id=order_id,
                )
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


def _require_demo_owner(db: sqlite3.Connection, user_id: int) -> int:
    """Check current Owner permissions before inserting optional sample activity."""
    row = db.execute('''SELECT o.ownerID FROM "User" u JOIN Owner o ON o.userID=u.userID
                        WHERE u.userID=? AND u.role='Owner' AND u.accountActive=1
                        AND u.passwordHash IS NOT NULL''', (user_id,)).fetchone()
    if row is None:
        raise InventoryError('Only an active Owner can load sample activity.')
    return int(row['ownerID'])


def _check_demo_run(db: sqlite3.Connection, key: str) -> None:
    """Keep each optional dataset all-or-nothing and prevent repeated imports."""
    db.execute('''CREATE TABLE IF NOT EXISTS DemoDataSet (
                      dataset TEXT PRIMARY KEY,
                      loadedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                  )''')
    if db.execute('SELECT 1 FROM DemoDataSet WHERE dataset=?', (key,)).fetchone():
        raise InventoryError('This sample dataset was already loaded. No records were added. '
                             'Use other menus to inspect it, or back up and reset if you need to reload.')


def _finish_demo_run(db: sqlite3.Connection, key: str) -> None:
    db.execute('INSERT INTO DemoDataSet(dataset) VALUES (?)', (key,))


def populate_trend_history(svc: InventoryService, user_id: int) -> dict[str, int]:
    """Add 12 days of real stock deductions and source-linked Sales to sample recipes.

    Inventory and financial postings share one SQLite transaction. If stock must
    be replenished, a sample received purchase order and invoice are also recorded.
    """
    daily_order_counts = (2, 2, 3, 2, 3, 3, 4, 3, 4, 4, 5, 6)
    with transaction(svc.db_path) as db:
        _require_demo_owner(db, user_id)
        _check_demo_run(db, 'trend_12day_v1')
        starter_supplier = db.execute('SELECT supplierID FROM Supplier WHERE name=?',
                                      ('North Shore Rice & Dry Goods (Demo)',)).fetchone()
        if starter_supplier is None:
            raise InventoryError('The starter shop dataset is required for order history. '
                                 'Load 16 -> 1 -> 1 first (or reset after backing up if stock already exists).')

        recipe_ids = []
        recipes = {}
        for name, _price, _components in RECIPES:
            recipe = db.execute('SELECT recipeID, price FROM Recipe WHERE name=?', (name,)).fetchone()
            if recipe is None or recipe['price'] is None or recipe['price'] <= 0:
                raise InventoryError(f'Sample recipe {name!r} is missing or has no positive price. '
                                     'Check recipes in option 7 before loading order history.')
            ingredients = list(db.execute('''SELECT ingredientID,quantityRequired
                                              FROM RecipeIngredient WHERE recipeID=?''',
                                          (recipe['recipeID'],)))
            if not ingredients:
                raise InventoryError(f'Sample recipe {name!r} has no ingredients. '
                                     'Finish its ingredient setup under option 6.')
            recipe_ids.append(recipe['recipeID'])
            recipes[recipe['recipeID']] = (float(recipe['price']), ingredients)

        schedule = []
        needed = {}
        for day_idx, count in enumerate(daily_order_counts):
            day = (date.today() - timedelta(days=len(daily_order_counts) - day_idx)).isoformat()
            for order_idx in range(count):
                rid = recipe_ids[(day_idx * 2 + order_idx) % len(recipe_ids)]
                servings = 1 + ((day_idx + order_idx) % 3)
                schedule.append((day, rid, servings))
                for item in recipes[rid][1]:
                    iid = item['ingredientID']
                    needed[iid] = needed.get(iid, 0) + item['quantityRequired'] * servings

        restock = {}
        for iid, qty in needed.items():
            item = db.execute('''SELECT quantityOnHand,reorderLevel
                                 FROM InventoryItem WHERE ingredientID=?''', (iid,)).fetchone()
            if item is None:
                raise InventoryError(f'Recipe ingredient #{iid} no longer exists.')
            safety = max(float(item['reorderLevel'] or 0), qty * 0.10)
            shortfall = qty + safety - float(item['quantityOnHand'] or 0)
            if shortfall > 0.000001:
                restock[iid] = round(shortfall + 1, 2)

        purchases = 0
        if restock:
            restock_day = (date.today() - timedelta(days=13)).isoformat()
            db.execute('''INSERT OR IGNORE INTO Supplier(name,contactInfo) VALUES (?,?)''',
                       ('Onigiri Wholesale Supplier (Demo)', 'wholesale@example.test'))
            supplier_id = db.execute('SELECT supplierID FROM Supplier WHERE name=?',
                                     ('Onigiri Wholesale Supplier (Demo)',)).fetchone()['supplierID']
            po_id = db.execute('''INSERT INTO InventoryOrder(orderDate,status,notes)
                                  VALUES (?,?,?)''',
                               (restock_day, 'Received', 'Sample stock for historical order activity')).lastrowid
            movements = []
            for iid, qty in restock.items():
                db.execute('''INSERT INTO InventoryOrderLine
                    (quantityOrdered,receivedQuantity,inventoryOrderID,ingredientID)
                    VALUES (?,?,?,?)''', (qty, qty, po_id, iid))
                svc._apply_change(db, iid, qty, user_id, 'Supplier Delivery',
                                  supplier_id=supplier_id, inventory_order_id=po_id,
                                  notes='Sample restock for order history',
                                  transaction_date=restock_day + 'T09:00:00', recorded_ids=movements)
            # Approximate wholesale amount: this is an explicitly fictional invoice.
            invoice_amount = round(sum(qty * 0.04 for qty in restock.values()), 2)
            post_source_transaction(db, kind='Purchase', when=restock_day,
                                    description=f'Sample stock delivery for PO #{po_id}',
                                    reference=f'DEMO-PO-{po_id}', amount=invoice_amount,
                                    source_type='Delivery', source_id=movements[0])
            purchases = 1

        for day, rid, servings in schedule:
            price, ingredients = recipes[rid]
            total = round(price * servings, 2)
            order_id = db.execute('''INSERT INTO "Order"
                  (orderDate,totalAmount,status,createdByUserID) VALUES (?,?,?,?)''',
                                  (day + 'T12:00:00', total, 'Pending', user_id)).lastrowid
            db.execute('INSERT INTO OrderRecipe(orderID,recipeID,quantity) VALUES (?,?,?)',
                       (order_id, rid, servings))
            for ingredient in ingredients:
                svc._apply_change(db, ingredient['ingredientID'],
                                  -(ingredient['quantityRequired'] * servings),
                                  user_id, 'Customer Order', customer_order_id=order_id,
                                  notes='Completed sample historical order',
                                  transaction_date=day + 'T12:30:00')
            db.execute('UPDATE "Order" SET status=? WHERE orderID=?', ('Completed', order_id))
            post_source_transaction(db, kind='Sale', when=day,
                                    description=f'Completed customer order #{order_id}',
                                    reference=f'ORDER-{order_id}', amount=total,
                                    source_type='Order', source_id=order_id)
        _finish_demo_run(db, 'trend_12day_v1')
        return {'days': len(daily_order_counts), 'completed_orders': len(schedule),
                'sales_posted': len(schedule), 'restock_deliveries': purchases}


def populate_accounting_activity(svc: InventoryService, user_id: int) -> dict[str, int]:
    """Add dated manual bookkeeping examples, including a reconciliation practice case."""
    examples = (
        (11, 'Sale', 'Sample off-menu catering income', 'DEMO-CATERING-1', 145.00),
        (10, 'Purchase', 'Sample equipment purchase', 'DEMO-EQUIP-1', 325.00),
        (9, 'Expense', 'Sample location rent', 'DEMO-RENT-1', 950.00),
        (8, 'Expense', 'Sample electricity expense', 'DEMO-UTIL-1', 75.20),
        (6, 'Purchase', 'Sample food packaging supplies', 'DEMO-PACK-1', 65.70),
        (5, 'Expense', 'Sample website hosting', 'DEMO-HOST-1', 29.99),
        (4, 'Inventory Adjustment', 'Sample inventory write-off', 'DEMO-WRITEOFF-1', 18.50),
        (3, 'Expense', 'Sample marketing expense', 'DEMO-MARKETING-1', 42.00),
        (2, 'Expense', 'Sample duplicate invoice for reconciliation A', 'DEMO-DUPLICATE-1', 22.50),
        (1, 'Expense', 'Sample duplicate invoice for reconciliation B', 'DEMO-DUPLICATE-1', 22.50),
    )
    with transaction(svc.db_path) as db:
        _require_demo_owner(db, user_id)
        _check_demo_run(db, 'accounting_examples_v1')
        columns = {col['name'] for col in db.execute('PRAGMA table_info("AccountingTransaction")')}
        if {'date', 'type'} <= columns:
            date_col, type_col = 'date', 'type'
        elif {'transactionDate', 'transactionType'} <= columns:
            date_col, type_col = 'transactionDate', 'transactionType'
        else:
            raise InventoryError('Accounting is not initialized. Restart the application '
                                 'or check database compatibility in the README.')
        for age, kind, description, reference, amount in examples:
            when = (date.today() - timedelta(days=age)).isoformat()
            db.execute(f'''INSERT INTO AccountingTransaction
                (ledgerID,"{date_col}","{type_col}",description,reference,amount)
                VALUES (1,?,?,?,?,?)''', (when, kind, description, reference, amount))
        _finish_demo_run(db, 'accounting_examples_v1')
        return {'manual_transactions': len(examples), 'repeated_references': 1}


def populate_payroll_activity(svc: InventoryService, user_id: int) -> dict[str, int]:
    """Build one fictional paid payroll using real pay and accounting calculations."""
    with transaction(svc.db_path) as db:
        owner_id = _require_demo_owner(db, user_id)
        _check_demo_run(db, 'payroll_examples_v1')
        active = db.execute('''SELECT e.employeeID,e.hourlyRate,u.name FROM Employee e
            JOIN "User" u ON u.userID=e.userID
            WHERE u.role='Employee' AND u.accountActive=1 AND COALESCE(e.isActive,1)=1
              AND COALESCE(e.hourlyRate,0)>0 ORDER BY e.employeeID LIMIT 3''').fetchall()
        if not active:
            raise InventoryError('A sample payroll needs at least one active Employee with an '
                                 'hourly rate. Create/enable an Employee under 15, then set '
                                 'their rate under 20 -> 7 before retrying.')
        pay_day = None
        for ago in range(3, 90):
            candidate = (date.today() - timedelta(days=ago)).isoformat()
            if not db.execute('SELECT 1 FROM Payroll WHERE payDate=?', (candidate,)).fetchone():
                pay_day = candidate
                break
        if pay_day is None:
            raise InventoryError('Every candidate sample payroll date is already used. '
                                 'Review the Payroll menu before adding another pay period.')
        payroll_id = db.execute('''INSERT INTO Payroll(payDate,status,totalAmount)
                                   VALUES (?,?,0)''', (pay_day, 'Draft')).lastrowid
        employees = {r['employeeID']: Employee(r['employeeID'], r['hourlyRate'], r['name'])
                     for r in active}
        run = Payroll(payroll_id, pay_day)
        for index, emp in enumerate(active):
            hours = 72 - index * 4
            overtime = 4 if index == 0 else 0
            run.entries.append(PayrollEntry(None, emp['employeeID'], hours, overtime))
        run.calculatePay(employees)
        run.approve(owner_id)
        expense = run.recordExpense(pay_day)
        for item in run.entries:
            db.execute('''INSERT INTO PayrollEntry
                (payrollID,employeeID,hoursWorked,overtimeHours,deductions,netPay)
                VALUES (?,?,?,?,?,?)''', (payroll_id, item.employeeID, item.hoursWorked,
                                         item.overtimeHours, item.deductions, item.netPay))
        tx_id = post_source_transaction(db, kind=expense.type, when=expense.date,
                                        description=expense.description, reference=expense.reference,
                                        amount=expense.amount, source_type='Payroll', source_id=payroll_id)
        db.execute('''UPDATE Payroll SET status=?,totalAmount=?,approvedByOwnerID=?,
                      accountingTransactionID=? WHERE payrollID=?''',
                   (run.status, run.totalAmount, owner_id, tx_id, payroll_id))
        _finish_demo_run(db, 'payroll_examples_v1')
        return {'payroll_id': payroll_id, 'employees': len(run.entries),
                'accounting_expenses': 1}


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
    demo_imports = []
    with closing(connect(db_path)) as db:
        actor = db.execute('SELECT role FROM "User" WHERE userID=? AND passwordHash IS NOT NULL',
                           (user_id,)).fetchone()
        if not actor or actor['role'] != 'Owner':
            raise InventoryError('Only an authenticated Owner can reset the database.')
        if preserve_accounts:
            demo_imports = [dict(r) for r in db.execute(
                'SELECT sourceUsername,userID FROM DemoUserImport')]
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
                for imported in demo_imports:
                    db.execute('INSERT INTO DemoUserImport(sourceUsername,userID) VALUES(?,?)',
                               (imported['sourceUsername'], imported['userID']))
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
