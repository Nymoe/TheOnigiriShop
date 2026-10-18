"""Persistent SQLite schema for the JMSB inventory proof of concept.

Shares the broad project's User, Order, InventoryItem, InventoryAdjustment,
InventoryOrder, InventoryOrderLine and LowStockAlert tables. Existing tables and
rows are preserved. All new columns and supporting tables are additive.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

DEFAULT_DB = Path(__file__).resolve().with_name("btm495.db")


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(db_path) if db_path is not None else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 10000")
    return db


@contextmanager
def transaction(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Each business action either commits completely or leaves no changes."""
    db = connect(db_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _ensure_column(db: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
    cols = {r["name"] for r in db.execute(f'PRAGMA table_info("{table}")')}
    if name not in cols:
        db.execute(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {declaration}')


def initialize(db_path: str | Path | None = None) -> bool:
    """Create database if missing, reuse and non-destructively upgrade otherwise.

    Return True only when the file did not exist before this call.
    """
    path = Path(db_path) if db_path is not None else DEFAULT_DB
    fresh = not path.exists()
    db = connect(path)
    try:
        # These broad-system table names/columns follow the supplied database.py.
        # SQLite CREATE TABLE IF NOT EXISTS does not erase any existing table.
        db.executescript('''
            CREATE TABLE IF NOT EXISTS "User" (
                userID INTEGER PRIMARY KEY, name TEXT, email TEXT, username TEXT
            );
            CREATE TABLE IF NOT EXISTS "Owner" (
                ownerID INTEGER PRIMARY KEY, userID INTEGER,
                FOREIGN KEY(userID) REFERENCES "User"(userID)
            );
            CREATE TABLE IF NOT EXISTS "Employee" (
                employeeID INTEGER PRIMARY KEY, userID INTEGER,
                hourlyRate REAL, isActive INTEGER,
                FOREIGN KEY(userID) REFERENCES "User"(userID)
            );
            CREATE TABLE IF NOT EXISTS "Customer" (
                customerID INTEGER PRIMARY KEY, userID INTEGER,
                FOREIGN KEY(userID) REFERENCES "User"(userID)
            );
            CREATE TABLE IF NOT EXISTS "Order" (
                orderID INTEGER PRIMARY KEY, orderDate TEXT, totalAmount REAL,
                status TEXT, customerID INTEGER,
                FOREIGN KEY(customerID) REFERENCES "Customer"(customerID)
            );
            CREATE TABLE IF NOT EXISTS InventoryItem (
                ingredientID INTEGER PRIMARY KEY, ingredientName TEXT,
                quantityOnHand REAL, reorderLevel REAL
            );
            CREATE TABLE IF NOT EXISTS InventoryAdjustment (
                adjustmentID INTEGER PRIMARY KEY, quantityChange REAL, reason TEXT,
                adjustmentDate TEXT, ingredientID INTEGER,
                FOREIGN KEY(ingredientID) REFERENCES InventoryItem(ingredientID)
            );
            CREATE TABLE IF NOT EXISTS InventoryOrder (
                inventoryOrderID INTEGER PRIMARY KEY, orderDate TEXT, status TEXT
            );
            CREATE TABLE IF NOT EXISTS InventoryOrderLine (
                orderLineID INTEGER PRIMARY KEY, quantityOrdered REAL,
                inventoryOrderID INTEGER, ingredientID INTEGER,
                FOREIGN KEY(inventoryOrderID) REFERENCES InventoryOrder(inventoryOrderID),
                FOREIGN KEY(ingredientID) REFERENCES InventoryItem(ingredientID)
            );
            CREATE TABLE IF NOT EXISTS LowStockAlert (
                alertID INTEGER PRIMARY KEY, createdAt TEXT, status TEXT,
                ingredientID INTEGER,
                FOREIGN KEY(ingredientID) REFERENCES InventoryItem(ingredientID)
            );
        ''')
        with db:
            _ensure_column(db, "User", "role", "TEXT NOT NULL DEFAULT 'Employee'")
            _ensure_column(db, "User", "passwordHash", "TEXT")
            _ensure_column(db, "User", "passwordSalt", "TEXT")
            _ensure_column(db, "InventoryItem", "unit", "TEXT NOT NULL DEFAULT 'unit'")
            _ensure_column(db, "InventoryOrder", "notes", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(db, "InventoryOrderLine", "receivedQuantity", "REAL NOT NULL DEFAULT 0")
            _ensure_column(db, "Order", "createdByUserID", "INTEGER")
            db.executescript('''
                CREATE TABLE IF NOT EXISTS Supplier (
                    supplierID INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    contactInfo TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS Recipe (
                    recipeID INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    price REAL NOT NULL DEFAULT 0 CHECK(price >= 0)
                );
                CREATE TABLE IF NOT EXISTS RecipeIngredient (
                    recipeID INTEGER NOT NULL,
                    ingredientID INTEGER NOT NULL,
                    quantityRequired REAL NOT NULL CHECK(quantityRequired > 0),
                    PRIMARY KEY(recipeID, ingredientID),
                    FOREIGN KEY(recipeID) REFERENCES Recipe(recipeID),
                    FOREIGN KEY(ingredientID) REFERENCES InventoryItem(ingredientID)
                );
                CREATE TABLE IF NOT EXISTS OrderRecipe (
                    orderID INTEGER NOT NULL,
                    recipeID INTEGER NOT NULL,
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    PRIMARY KEY(orderID, recipeID),
                    FOREIGN KEY(orderID) REFERENCES "Order"(orderID),
                    FOREIGN KEY(recipeID) REFERENCES Recipe(recipeID)
                );
                CREATE TABLE IF NOT EXISTS InventoryTransaction (
                    transactionID INTEGER PRIMARY KEY,
                    ingredientID INTEGER NOT NULL,
                    userID INTEGER,
                    supplierID INTEGER,
                    customerOrderID INTEGER,
                    inventoryOrderID INTEGER,
                    transactionType TEXT NOT NULL,
                    quantity REAL NOT NULL,
                    transactionDate TEXT NOT NULL,
                    notes TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(ingredientID) REFERENCES InventoryItem(ingredientID),
                    FOREIGN KEY(userID) REFERENCES "User"(userID),
                    FOREIGN KEY(supplierID) REFERENCES Supplier(supplierID),
                    FOREIGN KEY(customerOrderID) REFERENCES "Order"(orderID),
                    FOREIGN KEY(inventoryOrderID) REFERENCES InventoryOrder(inventoryOrderID)
                );
                CREATE INDEX IF NOT EXISTS idx_inv_transactions_ingredient
                    ON InventoryTransaction(ingredientID, transactionID);
                CREATE INDEX IF NOT EXISTS idx_inv_alerts_ingredient
                    ON LowStockAlert(ingredientID, status);
                CREATE INDEX IF NOT EXISTS idx_inv_orderlines_order
                    ON InventoryOrderLine(inventoryOrderID);
            ''')
    finally:
        db.close()
    return fresh
