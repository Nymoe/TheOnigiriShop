"""Business logic for inventory, recipes, orders, suppliers, purchasing and alerts.

A GUI or another module can call InventoryService directly without importing the
command-line interface. Quantities are stored in the ingredient's named unit.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from hashlib import pbkdf2_hmac
import hmac
import math
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from inventory_db import connect, initialize, transaction
from profile_service import _validate_dob, _validate_phone

EPSILON = 1e-8


class InventoryError(ValueError):
    """Invalid action, missing record, or failed business rule."""


class InsufficientStockError(InventoryError):
    """Includes the shortages found while checking an order."""

    def __init__(self, shortages: list[str]):
        self.shortages = shortages
        super().__init__("Insufficient inventory: " + "; ".join(shortages))


def _validate_email(email: str | None) -> str | None:
    """Use the same optional email validation for account creation and editing."""
    if email is None:
        return None
    if not isinstance(email, str):
        raise InventoryError('Email must be text.')
    email = email.strip() or None
    if email and (len(email) > 254 or email.count('@') != 1 or
                  any(c.isspace() or ord(c) < 32 for c in email) or
                  not all(email.split('@')) or '.' not in email.split('@')[1]):
        raise InventoryError('Enter a valid email address, or clear the email field.')
    return email


def _quantity(value: int | float | str, label: str = "Quantity", *, zero_ok: bool = False) -> float:
    try:
        number = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise InventoryError(f"{label} must be a number.") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not zero_ok):
        constraint = "zero or greater" if zero_ok else "greater than zero"
        raise InventoryError(f"{label} must be {constraint}.")
    return number


def _ident(value: int | str, label: str = "ID") -> int:
    try:
        result = int(value)
    except (ValueError, TypeError) as exc:
        raise InventoryError(f"{label} must be a positive integer.") from exc
    if result < 1 or (isinstance(value, float) and value != result):
        raise InventoryError(f"{label} must be a positive integer.")
    if isinstance(value, str) and value.strip() != str(result):
        raise InventoryError(f"{label} must be a positive integer.")
    return result


def _must_get(db: sqlite3.Connection, table: str, key: str, value: int):
    # Only call with table/key constants within this module.
    row = db.execute(f'SELECT * FROM "{table}" WHERE "{key}" = ?', (value,)).fetchone()
    if row is None:
        raise InventoryError(f"{table} #{value} was not found.")
    return row


def _today() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _date_today() -> str:
    """Use a simple ISO date for fields shared with other team modules."""
    return date.today().isoformat()


def _rows(query_result: sqlite3.Cursor) -> list[dict]:
    return [dict(row) for row in query_result.fetchall()]


class InventoryService:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        self.created_database = initialize(db_path)

    def _read(self, sql: str, args: tuple = ()) -> list[dict]:
        db = connect(self.db_path)
        try:
            return _rows(db.execute(sql, args))
        finally:
            db.close()

    # ----- USERS (shared User table; no passwords stored in plaintext) -----
    def has_logins(self) -> bool:
        return bool(self._read('SELECT 1 FROM "User" WHERE passwordHash IS NOT NULL AND accountActive=1 LIMIT 1'))

    def create_user(self, name: str, username: str, password: str, role: str = "Employee",
                    email: str | None = None, phone_number: str | None = None,
                    date_of_birth: str | None = None) -> int:
        name, username = name.strip(), username.strip()
        role = role.title()
        email = _validate_email(email)
        phone_number = _validate_phone(phone_number)
        birth_date = _validate_dob(date_of_birth)
        if not name or not username:
            raise InventoryError("Name and username are required.")
        if role not in {"Owner", "Employee", "Customer"}:
            raise InventoryError("Role must be Owner, Employee or Customer.")
        if len(password) < 8:
            raise InventoryError("Password must contain at least eight characters.")
        with transaction(self.db_path) as db:
            if db.execute('SELECT 1 FROM "User" WHERE lower(username) = lower(?)', (username,)).fetchone():
                raise InventoryError("That username is already in use.")
            if role != "Owner" and not db.execute(
                'SELECT 1 FROM "User" WHERE role = ? AND passwordHash IS NOT NULL LIMIT 1',
                ("Owner",)
            ).fetchone():
                raise InventoryError("Create an owner account before adding employees.")
            salt = secrets.token_hex(16)
            password_hash = pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), 220_000).hex()
            result = db.execute(
                'INSERT INTO "User" (name, username, role, email, passwordHash, passwordSalt) '
                'VALUES (?, ?, ?, ?, ?, ?)', (name, username, role, email, password_hash, salt)
            )
            if role == "Owner":
                db.execute('INSERT INTO "Owner"(userID) VALUES (?)', (result.lastrowid,))
            elif role == "Employee":
                db.execute('INSERT INTO "Employee"(userID, hourlyRate, isActive) VALUES (?, 0, 1)',
                           (result.lastrowid,))
            else:
                db.execute('INSERT INTO "Customer"(userID) VALUES (?)', (result.lastrowid,))
            # Create the one-to-one profile in the same transaction as the login.
            db.execute('INSERT INTO Profile(profileID,userID,name,phoneNumber,dateOfBirth) '
                       'VALUES(?,?,?,?,?)',
                       (uuid4().hex, result.lastrowid, name, phone_number,
                        birth_date.isoformat() if birth_date else None))
            return result.lastrowid

    def login(self, username: str, password: str) -> dict:
        rows = self._read(
            'SELECT userID, name, username, role, passwordHash, passwordSalt, accountActive FROM "User" '
            'WHERE lower(username) = lower(?) AND passwordHash IS NOT NULL', (username.strip(),)
        )
        if len(rows) != 1:
            raise InventoryError("Invalid username or password.")
        user = rows[0]
        try:
            calculated = pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(user["passwordSalt"]), 220_000)
            stored = bytes.fromhex(user["passwordHash"])
        except (TypeError, ValueError):
            raise InventoryError("Invalid username or password.") from None
        if not hmac.compare_digest(calculated, stored):
            raise InventoryError("Invalid username or password.")
        if not user["accountActive"]:
            raise InventoryError("This account has been disabled. Please contact an Owner to reactivate it.")
        return {k: user[k] for k in ("userID", "name", "username", "role")}

    def list_users(self) -> list[dict]:
        return self._read('SELECT userID, name, username, role FROM "User" ORDER BY userID')

    # ----- INGREDIENTS -----
    def inventory(self) -> list[dict]:
        return self._read('SELECT ingredientID, ingredientName, unit, quantityOnHand, '
                          'reorderLevel FROM InventoryItem ORDER BY ingredientName COLLATE NOCASE')

    def add_ingredient(self, name: str, unit: str, starting_quantity: float = 0,
                       reorder_level: float = 0, user_id: int | None = None) -> int:
        name, unit = name.strip(), unit.strip()
        if not name or not unit:
            raise InventoryError("Ingredient name and unit are required.")
        qty = _quantity(starting_quantity, "Starting quantity", zero_ok=True)
        minimum = _quantity(reorder_level, "Reorder level", zero_ok=True)
        with transaction(self.db_path) as db:
            if db.execute('SELECT 1 FROM InventoryItem WHERE lower(ingredientName)=lower(?)', (name,)).fetchone():
                raise InventoryError("An ingredient with this name already exists.")
            item_id = db.execute(
                'INSERT INTO InventoryItem(ingredientName, unit, quantityOnHand, reorderLevel) '
                'VALUES(?, ?, ?, ?)', (name, unit, qty, minimum)
            ).lastrowid
            if qty:
                self._record_transaction(db, item_id, user_id, "Opening Stock", qty, notes="Initial stock")
            self._sync_alert(db, item_id)
            return item_id

    def set_reorder_level(self, ingredient_id: int, level: float) -> None:
        level = _quantity(level, "Reorder level", zero_ok=True)
        with transaction(self.db_path) as db:
            ingredient_id = _ident(ingredient_id)
            _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
            db.execute('UPDATE InventoryItem SET reorderLevel=? WHERE ingredientID=?', (level, ingredient_id))
            self._sync_alert(db, ingredient_id)

    def _record_transaction(self, db: sqlite3.Connection, ingredient_id: int,
                            user_id: int | None, action: str, delta: float,
                            *, supplier_id: int | None = None,
                            customer_order_id: int | None = None,
                            inventory_order_id: int | None = None,
                            notes: str = "") -> None:
        timestamp = _today()
        db.execute('''
            INSERT INTO InventoryTransaction
                (ingredientID, userID, supplierID, customerOrderID,
                 inventoryOrderID, transactionType, quantity, transactionDate, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (ingredient_id, user_id, supplier_id, customer_order_id,
              inventory_order_id, action, delta, timestamp, notes))
        # Mirror stock movements to the broad system's existing InventoryAdjustment.
        db.execute('''
            INSERT INTO InventoryAdjustment(quantityChange, reason, adjustmentDate, ingredientID)
            VALUES (?, ?, ?, ?)
        ''', (delta, action if not notes else f"{action}: {notes}", _date_today(), ingredient_id))

    def _apply_change(self, db: sqlite3.Connection, ingredient_id: int, delta: float,
                      user_id: int | None, action: str, **kwargs) -> float:
        item = _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
        new_qty = float(item["quantityOnHand"]) + delta
        if new_qty < -EPSILON:
            raise InsufficientStockError([
                f'{item["ingredientName"]} requires {-delta:g} {item["unit"]}; '
                f'only {item["quantityOnHand"]:g} available'
            ])
        new_qty = max(0.0, round(new_qty, 8))
        db.execute('UPDATE InventoryItem SET quantityOnHand=? WHERE ingredientID=?',
                   (new_qty, ingredient_id))
        self._record_transaction(db, ingredient_id, user_id, action, delta, **kwargs)
        self._sync_alert(db, ingredient_id)
        return new_qty

    def adjust_stock(self, ingredient_id: int, action: str, quantity: float,
                     user_id: int, notes: str = "") -> float:
        quantity = _quantity(quantity)
        action = action.strip().lower()
        if action not in {"add", "remove"}:
            raise InventoryError("Choose add or remove.")
        delta = quantity if action == "add" else -quantity
        with transaction(self.db_path) as db:
            return self._apply_change(db, _ident(ingredient_id), delta, user_id,
                                      "Manual Adjustment", notes=notes.strip())

    # ----- SUPPLIERS / DELIVERIES -----
    def add_supplier(self, name: str, contact_info: str = "") -> int:
        if not name.strip():
            raise InventoryError("Supplier name is required.")
        with transaction(self.db_path) as db:
            try:
                return db.execute('INSERT INTO Supplier(name, contactInfo) VALUES(?, ?)',
                                  (name.strip(), contact_info.strip())).lastrowid
            except sqlite3.IntegrityError as exc:
                raise InventoryError("That supplier already exists.") from exc

    def suppliers(self) -> list[dict]:
        return self._read('SELECT * FROM Supplier ORDER BY name COLLATE NOCASE')

    def receive_delivery(self, quantities: dict[int, float], user_id: int,
                         supplier_id: int | None = None,
                         purchase_order_id: int | None = None) -> None:
        if not quantities:
            raise InventoryError("Select at least one ingredient to receive.")
        clean = {_ident(k, "Ingredient ID"): _quantity(v) for k, v in quantities.items()}
        with transaction(self.db_path) as db:
            if supplier_id is not None:
                _must_get(db, "Supplier", "supplierID", _ident(supplier_id))
            if purchase_order_id is not None:
                purchase_order_id = _ident(purchase_order_id, "Purchase order ID")
                po = _must_get(db, "InventoryOrder", "inventoryOrderID", purchase_order_id)
                if po["status"] not in {"Confirmed", "Partially Received"}:
                    raise InventoryError("This purchase order is not open for receiving.")
                outstanding = {
                    r["ingredientID"]: r for r in db.execute(
                        'SELECT ingredientID, quantityOrdered, receivedQuantity, orderLineID '
                        'FROM InventoryOrderLine WHERE inventoryOrderID=?', (purchase_order_id,)
                    )
                }
                for ingredient_id, quantity in clean.items():
                    line = outstanding.get(ingredient_id)
                    if line is None:
                        raise InventoryError(f"Ingredient #{ingredient_id} is not in the purchase order.")
                    remaining = line["quantityOrdered"] - line["receivedQuantity"]
                    if quantity > remaining + EPSILON:
                        raise InventoryError(
                            f"Receiving {quantity:g} exceeds {remaining:g} outstanding for ingredient #{ingredient_id}."
                        )
            for ingredient_id, quantity in clean.items():
                self._apply_change(db, ingredient_id, quantity, user_id, "Supplier Delivery",
                                   supplier_id=supplier_id,
                                   inventory_order_id=purchase_order_id)
                if purchase_order_id is not None:
                    db.execute('UPDATE InventoryOrderLine SET receivedQuantity=receivedQuantity+? '
                               'WHERE inventoryOrderID=? AND ingredientID=?',
                               (quantity, purchase_order_id, ingredient_id))
            if purchase_order_id is not None:
                lines = list(db.execute('SELECT quantityOrdered, receivedQuantity FROM InventoryOrderLine '
                                        'WHERE inventoryOrderID=?', (purchase_order_id,)))
                complete = all(r["receivedQuantity"] >= r["quantityOrdered"] - EPSILON for r in lines)
                db.execute('UPDATE InventoryOrder SET status=? WHERE inventoryOrderID=?',
                           ("Received" if complete else "Partially Received", purchase_order_id))

    # ----- RECIPES (join table stores quantity of each ingredient per serving) -----
    def add_recipe(self, name: str, price: float = 0) -> int:
        name = name.strip()
        if not name:
            raise InventoryError("Recipe name is required.")
        price = _quantity(price, "Price", zero_ok=True)
        with transaction(self.db_path) as db:
            try:
                return db.execute('INSERT INTO Recipe(name, price) VALUES(?, ?)',
                                  (name, price)).lastrowid
            except sqlite3.IntegrityError as exc:
                raise InventoryError("A recipe with this name already exists.") from exc

    def set_recipe_ingredient(self, recipe_id: int, ingredient_id: int, quantity: float) -> None:
        quantity = _quantity(quantity)
        with transaction(self.db_path) as db:
            recipe_id, ingredient_id = _ident(recipe_id), _ident(ingredient_id)
            _must_get(db, "Recipe", "recipeID", recipe_id)
            _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
            db.execute('''INSERT INTO RecipeIngredient(recipeID, ingredientID, quantityRequired)
                          VALUES (?, ?, ?)
                          ON CONFLICT(recipeID, ingredientID)
                          DO UPDATE SET quantityRequired=excluded.quantityRequired''',
                       (recipe_id, ingredient_id, quantity))

    def remove_recipe_ingredient(self, recipe_id: int, ingredient_id: int) -> None:
        with transaction(self.db_path) as db:
            db.execute('DELETE FROM RecipeIngredient WHERE recipeID=? AND ingredientID=?',
                       (_ident(recipe_id), _ident(ingredient_id)))

    def recipes(self) -> list[dict]:
        return self._read('SELECT recipeID, name, price FROM Recipe ORDER BY name COLLATE NOCASE')

    def recipe_ingredients(self, recipe_id: int) -> list[dict]:
        return self._read('''SELECT ri.ingredientID, i.ingredientName, i.unit,
                                   ri.quantityRequired, i.quantityOnHand
                             FROM RecipeIngredient ri
                             JOIN InventoryItem i ON i.ingredientID=ri.ingredientID
                             WHERE ri.recipeID=? ORDER BY i.ingredientName''', (_ident(recipe_id),))

    # ----- CUSTOMER ORDERS -----
    def create_customer_order(self, recipes: dict[int, int], user_id: int,
                              customer_id: int | None = None) -> int:
        if not recipes:
            raise InventoryError("Select at least one recipe.")
        clean: dict[int, int] = {}
        for recipe_id, count in recipes.items():
            recipe_id = _ident(recipe_id, "Recipe ID")
            count_num = _ident(count, "Servings")
            if float(count) != float(count_num):
                raise InventoryError("Servings must be whole numbers.")
            clean[recipe_id] = count_num
        with transaction(self.db_path) as db:
            _must_get(db, "User", "userID", user_id)
            if customer_id is not None:
                self._validate_order_customer(db, customer_id)
            total = 0.0
            for recipe_id, count in clean.items():
                recipe = _must_get(db, "Recipe", "recipeID", recipe_id)
                if not db.execute('SELECT 1 FROM RecipeIngredient WHERE recipeID=?', (recipe_id,)).fetchone():
                    raise InventoryError(f'{recipe["name"]} needs ingredients before it can be ordered.')
                total += recipe["price"] * count
            order_id = db.execute('INSERT INTO "Order"(orderDate, totalAmount, status, createdByUserID, customerID) '
                                  'VALUES(?, ?, ?, ?, ?)',
                                  (_date_today(), round(total, 2), "Pending", user_id, customer_id)).lastrowid
            for recipe_id, count in clean.items():
                db.execute('INSERT INTO OrderRecipe(orderID, recipeID, quantity) VALUES(?, ?, ?)',
                           (order_id, recipe_id, count))
            return order_id

    def customer_orders(self) -> list[dict]:
        # Include existing broad-system orders. POC-created orders have OrderRecipe rows.
        return self._read('''SELECT o.orderID, o.orderDate, o.totalAmount, o.status, o.customerID,
                                    COUNT(orcp.recipeID) AS recipesCount
                             FROM "Order" o LEFT JOIN OrderRecipe orcp ON o.orderID=orcp.orderID
                             GROUP BY o.orderID ORDER BY o.orderID DESC''')

    def order_details(self, order_id: int) -> dict:
        rows = self._read('SELECT orderID, totalAmount, status, customerID FROM "Order" WHERE orderID=?',
                          (_ident(order_id, 'Order ID'),))
        if not rows:
            raise InventoryError(f'Order #{order_id} was not found.')
        return rows[0]

    @staticmethod
    def _validate_order_customer(db: sqlite3.Connection, customer_id: int) -> None:
        row = db.execute('''SELECT u.role,u.accountActive FROM Customer c
                            JOIN "User" u ON u.userID=c.userID WHERE c.customerID=?''',
                         (_ident(customer_id, 'Customer ID'),)).fetchone()
        if not row or row['role'] != 'Customer':
            raise InventoryError('Customer ID was not found. Use Loyalty option 9 to find customer IDs, '
                                 'or option 1 to register a walk-in.')
        if not row['accountActive']:
            raise InventoryError('That Customer account is disabled. Ask an Owner to enable it under option 15.')

    def set_order_customer(self, order_id: int, customer_id: int) -> None:
        """Associate a customer with a pending order before it is completed."""
        with transaction(self.db_path) as db:
            order = _must_get(db, 'Order', 'orderID', _ident(order_id, 'Order ID'))
            if order['status'] != 'Pending':
                raise InventoryError('Customer assignment can only be changed while the order is Pending.')
            self._validate_order_customer(db, customer_id)
            db.execute('UPDATE "Order" SET customerID=? WHERE orderID=?', (customer_id, order_id))

    def order_recipes(self, order_id: int) -> list[dict]:
        return self._read('''SELECT r.name, r.recipeID, o.quantity, r.price
                             FROM OrderRecipe o JOIN Recipe r ON r.recipeID=o.recipeID
                             WHERE o.orderID=? ORDER BY r.name''', (_ident(order_id),))

    def complete_customer_order(self, order_id: int, user_id: int) -> dict:
        order_id = _ident(order_id, "Order ID")
        with transaction(self.db_path) as db:
            return self._complete_order_in_transaction(db, order_id, user_id)

    def _complete_order_in_transaction(self, db: sqlite3.Connection, order_id: int,
                                       user_id: int) -> dict:
        """Shared stock update, used by normal and atomic loyalty completion."""
        order = _must_get(db, "Order", "orderID", order_id)
        if order["status"] != "Pending":
            raise InventoryError("Only a pending order can be completed.")
        lines = list(db.execute('''SELECT ori.recipeID, ori.quantity, r.name
                                       FROM OrderRecipe ori JOIN Recipe r ON r.recipeID=ori.recipeID
                                       WHERE ori.orderID=?''', (order_id,)))
        if not lines:
            raise InventoryError("This order has no recipes. Existing external orders cannot be completed here.")
        required: dict[int, float] = defaultdict(float)
        for recipe in lines:
            ingredients = list(db.execute('SELECT ingredientID, quantityRequired FROM RecipeIngredient '
                                          'WHERE recipeID=?', (recipe["recipeID"],)))
            if not ingredients:
                raise InventoryError(f'Recipe {recipe["name"]} has no ingredients.')
            for ingredient in ingredients:
                required[ingredient["ingredientID"]] += ingredient["quantityRequired"] * recipe["quantity"]
        shortages = []
        for ingredient_id, qty in required.items():
            ingredient = _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
            if ingredient["quantityOnHand"] + EPSILON < qty:
                shortages.append(
                    f'{ingredient["ingredientName"]}: need {qty:g} {ingredient["unit"]}, '
                    f'have {ingredient["quantityOnHand"]:g}'
                )
        if shortages:
            raise InsufficientStockError(shortages)
        for ingredient_id, qty in required.items():
            self._apply_change(db, ingredient_id, -qty, user_id, "Customer Order",
                               customer_order_id=order_id, notes=f"Order #{order_id} completed")
        db.execute('UPDATE "Order" SET status=? WHERE orderID=?', ("Completed", order_id))
        return {"order_id": order_id, "deductions": dict(required)}

    def cancel_customer_order(self, order_id: int) -> None:
        with transaction(self.db_path) as db:
            order = _must_get(db, "Order", "orderID", _ident(order_id))
            if order["status"] != "Pending" or not db.execute(
                'SELECT 1 FROM OrderRecipe WHERE orderID=?', (order_id,)
            ).fetchone():
                raise InventoryError("Only a pending prototype order can be cancelled.")
            db.execute('UPDATE "Order" SET status=? WHERE orderID=?', ("Cancelled", order_id))

    # ----- LOW-STOCK ALERTS -----
    def _sync_alert(self, db: sqlite3.Connection, ingredient_id: int) -> None:
        item = _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
        below = item["quantityOnHand"] < item["reorderLevel"] - EPSILON
        if not below:
            db.execute('''UPDATE LowStockAlert SET status='Closed'
                          WHERE ingredientID=? AND status IN ('Open','Reviewed')''', (ingredient_id,))
        elif not db.execute('''SELECT 1 FROM LowStockAlert WHERE ingredientID=?
                               AND status IN ('Open','Reviewed') LIMIT 1''', (ingredient_id,)).fetchone():
            db.execute('INSERT INTO LowStockAlert(createdAt, status, ingredientID) VALUES(?,?,?)',
                       (_date_today(), "Open", ingredient_id))

    def alerts(self, active_only: bool = True) -> list[dict]:
        where = "WHERE a.status IN ('Open','Reviewed')" if active_only else ""
        return self._read(f'''SELECT a.alertID, a.createdAt, a.status, a.ingredientID,
                                  i.ingredientName, i.quantityOnHand, i.reorderLevel, i.unit
                            FROM LowStockAlert a JOIN InventoryItem i ON i.ingredientID=a.ingredientID
                            {where} ORDER BY a.alertID DESC''')

    def update_alert(self, alert_id: int, status: str) -> None:
        if status not in {"Reviewed", "Closed"}:
            raise InventoryError("Status must be Reviewed or Closed.")
        with transaction(self.db_path) as db:
            alert = _must_get(db, "LowStockAlert", "alertID", _ident(alert_id))
            if alert["status"] == "Closed":
                raise InventoryError("This alert is already closed.")
            db.execute('UPDATE LowStockAlert SET status=? WHERE alertID=?', (status, alert_id))

    # ----- INVENTORY PURCHASE ORDERS -----
    def create_purchase_order(self, items: dict[int, float], notes: str = "") -> int:
        if not items:
            raise InventoryError("Select at least one ingredient to order.")
        clean = {_ident(k, "Ingredient ID"): _quantity(v) for k, v in items.items()}
        with transaction(self.db_path) as db:
            for ingredient_id in clean:
                _must_get(db, "InventoryItem", "ingredientID", ingredient_id)
            po_id = db.execute('INSERT INTO InventoryOrder(orderDate, status, notes) VALUES(?,?,?)',
                               (_date_today(), "Confirmed", notes.strip())).lastrowid
            for ingredient_id, qty in clean.items():
                db.execute('INSERT INTO InventoryOrderLine(quantityOrdered, inventoryOrderID, '
                           'ingredientID, receivedQuantity) VALUES(?, ?, ?, 0)',
                           (qty, po_id, ingredient_id))
            return po_id

    def purchase_orders(self) -> list[dict]:
        return self._read('''SELECT io.inventoryOrderID, io.orderDate, io.status, io.notes,
                                    COUNT(iol.orderLineID) AS itemsCount
                             FROM InventoryOrder io LEFT JOIN InventoryOrderLine iol
                             ON io.inventoryOrderID=iol.inventoryOrderID
                             GROUP BY io.inventoryOrderID ORDER BY io.inventoryOrderID DESC''')

    def purchase_order_lines(self, order_id: int) -> list[dict]:
        return self._read('''SELECT iol.ingredientID, i.ingredientName, i.unit,
                                   iol.quantityOrdered, iol.receivedQuantity,
                                   (iol.quantityOrdered - iol.receivedQuantity) AS remaining
                             FROM InventoryOrderLine iol
                             JOIN InventoryItem i ON i.ingredientID=iol.ingredientID
                             WHERE iol.inventoryOrderID=? ORDER BY i.ingredientName''',
                          (_ident(order_id),))

    # ----- AUDIT / DEMO DATA -----
    def transactions(self, limit: int = 40) -> list[dict]:
        return self._read('''SELECT t.transactionID, t.transactionDate, t.transactionType,
                                   i.ingredientName, i.unit, t.quantity, t.notes,
                                   t.customerOrderID, t.inventoryOrderID, s.name AS supplier
                             FROM InventoryTransaction t
                             JOIN InventoryItem i ON t.ingredientID=i.ingredientID
                             LEFT JOIN Supplier s ON t.supplierID=s.supplierID
                             ORDER BY t.transactionID DESC LIMIT ?''', (limit,))

    def load_demo_data(self, user_id: int) -> dict[str, int]:
        """Populate an empty inventory with an atomic, realistic demo scenario."""
        from demo_tools import populate_demo_data  # Lazy import avoids dependency cycle.
        return populate_demo_data(self, user_id)
