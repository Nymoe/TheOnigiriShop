"""Persistent SQLite schema shared by the Onigiri Shop management modules.

Shares the existing User, Order, InventoryItem, InventoryAdjustment,
InventoryOrder, InventoryOrderLine and LowStockAlert tables. Existing tables and
rows are preserved. All new columns and supporting tables are additive.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from uuid import uuid4
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
        # Keep the existing shared table names and columns compatible.
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
            _ensure_column(db, "User", "accountActive", "INTEGER NOT NULL DEFAULT 1 CHECK(accountActive IN (0,1))")
            _ensure_column(db, "InventoryItem", "unit", "TEXT NOT NULL DEFAULT 'unit'")
            _ensure_column(db, "InventoryOrder", "notes", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(db, "InventoryOrderLine", "receivedQuantity", "REAL NOT NULL DEFAULT 0")
            _ensure_column(db, "Order", "createdByUserID", "INTEGER")
            # One persistent profile for every shared User row. No
            # existing User/Employee/Owner/Customer columns are replaced.
            db.execute('''
                CREATE TABLE IF NOT EXISTS Profile (
                    profileID TEXT PRIMARY KEY,
                    userID INTEGER NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    phoneNumber TEXT,
                    dateOfBirth TEXT,
                    version INTEGER NOT NULL DEFAULT 0,
                    FOREIGN KEY(userID) REFERENCES "User"(userID)
                )
            ''')
            # Backfill legacy users so existing login accounts can open Profile
            # Management immediately. The backfill is additive and idempotent.
            missing = db.execute('''
                SELECT u.userID, u.name FROM "User" u
                LEFT JOIN Profile p ON p.userID=u.userID
                WHERE p.userID IS NULL
            ''').fetchall()
            for row in missing:
                db.execute(
                    'INSERT INTO Profile(profileID,userID,name) VALUES(?,?,?)',
                    (uuid4().hex, row['userID'], row['name'] or '')
                )
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
            # Only option 16 -> 7 populates this import ledger. This table stores
            # provenance, not sample users, so edited sample profiles remain editable
            # without the next optional import overwriting their changes.
            db.execute('''
                CREATE TABLE IF NOT EXISTS DemoUserImport (
                    sourceUsername TEXT PRIMARY KEY COLLATE NOCASE,
                    userID INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(userID) REFERENCES "User"(userID) ON DELETE CASCADE
                )
            ''')
            # Loyalty tables are additive and use existing customer identities.
            db.executescript('''
                CREATE TABLE IF NOT EXISTS LoyaltyAccount (
                    loyaltyAccountID INTEGER PRIMARY KEY,
                    customerID INTEGER NOT NULL UNIQUE,
                    pointsBalance INTEGER NOT NULL DEFAULT 0 CHECK(pointsBalance >= 0),
                    joinedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(customerID) REFERENCES Customer(customerID)
                );
                CREATE TABLE IF NOT EXISTS Reward (
                    rewardID INTEGER PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    pointsCost INTEGER NOT NULL CHECK(pointsCost > 0),
                    discountAmount REAL NOT NULL CHECK(discountAmount > 0),
                    isActive INTEGER NOT NULL DEFAULT 1 CHECK(isActive IN (0,1))
                );
                CREATE TABLE IF NOT EXISTS LoyaltyTransaction (
                    loyaltyTransactionID INTEGER PRIMARY KEY,
                    loyaltyAccountID INTEGER NOT NULL,
                    orderID INTEGER NOT NULL UNIQUE,
                    employeeUserID INTEGER NOT NULL,
                    purchaseAmount REAL NOT NULL CHECK(purchaseAmount >= 0),
                    eligibleAmount REAL NOT NULL CHECK(eligibleAmount >= 0),
                    discountAmount REAL NOT NULL DEFAULT 0 CHECK(discountAmount >= 0),
                    finalAmount REAL NOT NULL CHECK(finalAmount >= 0),
                    pointsEarned INTEGER NOT NULL CHECK(pointsEarned >= 0),
                    pointsRedeemed INTEGER NOT NULL DEFAULT 0 CHECK(pointsRedeemed >= 0),
                    balanceAfter INTEGER NOT NULL CHECK(balanceAfter >= 0),
                    rewardID INTEGER,
                    createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(loyaltyAccountID) REFERENCES LoyaltyAccount(loyaltyAccountID),
                    FOREIGN KEY(orderID) REFERENCES "Order"(orderID),
                    FOREIGN KEY(employeeUserID) REFERENCES "User"(userID),
                    FOREIGN KEY(rewardID) REFERENCES Reward(rewardID)
                );
                CREATE TABLE IF NOT EXISTS Redemption (
                    redemptionID INTEGER PRIMARY KEY,
                    loyaltyTransactionID INTEGER NOT NULL UNIQUE,
                    rewardID INTEGER NOT NULL,
                    pointsUsed INTEGER NOT NULL CHECK(pointsUsed > 0),
                    discountAmount REAL NOT NULL CHECK(discountAmount > 0),
                    FOREIGN KEY(loyaltyTransactionID) REFERENCES LoyaltyTransaction(loyaltyTransactionID),
                    FOREIGN KEY(rewardID) REFERENCES Reward(rewardID)
                );
                CREATE INDEX IF NOT EXISTS idx_loyalty_history
                    ON LoyaltyTransaction(loyaltyAccountID, loyaltyTransactionID);
            ''')
            # Both class diagrams share the loyalty tables but differ on IDs.
            # Keep original integer FKs and expose stable public UUIDs as well.
            _ensure_column(db, 'LoyaltyAccount', 'status',
                           "TEXT NOT NULL DEFAULT 'Active' CHECK(status IN ('Active','Suspended'))")
            _ensure_column(db, 'LoyaltyAccount', 'publicUUID', 'TEXT')
            _ensure_column(db, 'Reward', 'publicUUID', 'TEXT')
            _ensure_column(db, 'LoyaltyTransaction', 'pointsChange', 'INTEGER NOT NULL DEFAULT 0')
            _ensure_column(db, 'LoyaltyTransaction', 'type', "TEXT NOT NULL DEFAULT 'NoPoints'")
            _ensure_column(db, 'LoyaltyTransaction', 'transactionDate', 'TEXT')
            _ensure_column(db, 'LoyaltyTransaction', 'publicUUID', 'TEXT')
            _ensure_column(db, 'Redemption', 'redemptionDate', 'TEXT')
            _ensure_column(db, 'Redemption', 'status',
                           "TEXT NOT NULL DEFAULT 'Confirmed' CHECK(status IN ('Pending','Confirmed','Cancelled'))")
            _ensure_column(db, 'Redemption', 'publicUUID', 'TEXT')
            # Non-destructive historical backfill for previously shipped loyalty databases.
            db.execute('''UPDATE LoyaltyTransaction
                SET pointsChange=pointsEarned-pointsRedeemed,
                    type=CASE WHEN pointsEarned>0 AND pointsRedeemed>0 THEN 'EarnAndRedeem'
                              WHEN pointsEarned>0 THEN 'Earn'
                              WHEN pointsRedeemed>0 THEN 'Redeem' ELSE 'NoPoints' END,
                    transactionDate=COALESCE(transactionDate,createdAt)
                WHERE transactionDate IS NULL''')
            db.execute('''UPDATE Redemption SET redemptionDate=COALESCE(redemptionDate,
                (SELECT createdAt FROM LoyaltyTransaction t
                 WHERE t.loyaltyTransactionID=Redemption.loyaltyTransactionID))
                WHERE redemptionDate IS NULL''')
            for table, key in (('LoyaltyAccount','loyaltyAccountID'),
                               ('LoyaltyTransaction','loyaltyTransactionID'),
                               ('Reward','rewardID'), ('Redemption','redemptionID')):
                rows = db.execute(f'SELECT {key} FROM {table} WHERE publicUUID IS NULL').fetchall()
                for row in rows:
                    db.execute(f'UPDATE {table} SET publicUUID=? WHERE {key}=?',
                               (str(uuid4()), row[key]))
                db.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_uuid ON {table}(publicUUID)')
            # Payroll runs, employee pay entries, and their accounting postings.
            db.executescript('''
                CREATE TABLE IF NOT EXISTS AccountingLedger (
                    ledgerID INTEGER PRIMARY KEY
                );
                INSERT OR IGNORE INTO AccountingLedger(ledgerID) VALUES (1);
                CREATE TABLE IF NOT EXISTS AccountingTransaction (
                    transactionID INTEGER PRIMARY KEY,
                    ledgerID INTEGER NOT NULL DEFAULT 1,
                    date TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reference TEXT NOT NULL,
                    amount REAL NOT NULL CHECK(amount > 0),
                    type TEXT NOT NULL,
                    FOREIGN KEY(ledgerID) REFERENCES AccountingLedger(ledgerID)
                );
                CREATE TABLE IF NOT EXISTS Payroll (
                    payrollID INTEGER PRIMARY KEY,
                    payDate TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL DEFAULT 'Draft'
                        CHECK(status IN ('Draft', 'Approved', 'Paid')),
                    totalAmount REAL NOT NULL DEFAULT 0 CHECK(totalAmount >= 0),
                    approvedByOwnerID INTEGER,
                    accountingTransactionID INTEGER UNIQUE,
                    FOREIGN KEY(approvedByOwnerID) REFERENCES "Owner"(ownerID),
                    FOREIGN KEY(accountingTransactionID)
                        REFERENCES AccountingTransaction(transactionID)
                );
                CREATE TABLE IF NOT EXISTS PayrollEntry (
                    entryID INTEGER PRIMARY KEY,
                    payrollID INTEGER NOT NULL,
                    employeeID INTEGER NOT NULL,
                    hoursWorked REAL NOT NULL CHECK(hoursWorked >= 0),
                    overtimeHours REAL NOT NULL DEFAULT 0 CHECK(overtimeHours >= 0),
                    deductions REAL CHECK(deductions >= 0),
                    netPay REAL CHECK(netPay >= 0),
                    UNIQUE(payrollID, employeeID),
                    FOREIGN KEY(payrollID) REFERENCES Payroll(payrollID),
                    FOREIGN KEY(employeeID) REFERENCES "Employee"(employeeID)
                );
                CREATE INDEX IF NOT EXISTS idx_payroll_entries_payroll
                    ON PayrollEntry(payrollID);
            ''')
    finally:
        db.close()
    return fresh
