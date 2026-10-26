"""Accounting models and services for the shared Onigiri Shop database.

Financial entries, reports and discrepancy checks are independent of the CLI.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import sqlite3

from inventory_db import connect, initialize, transaction as db_transaction

TRANSACTION_TYPES = ("Sale", "Purchase", "Expense", "Inventory Adjustment")


class AccountingError(ValueError):
    """Invalid accounting input or a missing accounting record."""


def _positive_id(value: int | str) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingError("ID must be a positive whole number.") from exc
    if result < 1 or str(value).strip() != str(result):
        raise AccountingError("ID must be a positive whole number.")
    return result


def post_source_transaction(
    db: sqlite3.Connection, *, kind: str, when: str, description: str,
    reference: str, amount: object, source_type: str, source_id: int,
    update_existing: bool = False,
) -> int | None:
    """Post a known financial event inside its caller's SQLite transaction.

    A source has at most one ledger row, even when loyalty later changes a sale's
    net value. Zero-value activity remains in its original operational history
    but is not a monetary ledger entry (also required by older payroll tables).
    """
    if kind not in TRANSACTION_TYPES:
        raise AccountingError('Unsupported accounting transaction type.')
    source_id = _positive_id(source_id)
    try:
        monetary_value = Decimal(str(amount))
        rounded = monetary_value.quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AccountingError('A valid financial amount is required to post to accounting.') from exc
    if not rounded.is_finite() or rounded < 0 or monetary_value != rounded:
        raise AccountingError('Financial amounts must be nonnegative and accurate to cents.')
    try:
        date.fromisoformat(str(when))
    except (ValueError, TypeError) as exc:
        raise AccountingError('Accounting date must use YYYY-MM-DD format.') from exc
    if not description.strip() or not source_type.strip():
        raise AccountingError('A description and a source are required for financial postings.')
    columns = {row['name'] for row in db.execute('PRAGMA table_info("AccountingTransaction")')}
    if {'date', 'type'} <= columns:
        date_col, type_col = 'date', 'type'
    elif {'transactionDate', 'transactionType'} <= columns:
        date_col, type_col = 'transactionDate', 'transactionType'
    else:
        raise AccountingError('Accounting columns are not initialized. Restart with a compatible database.')
    existing = db.execute(
        'SELECT transactionID FROM AccountingTransaction WHERE sourceType=? AND sourceID=?',
        (source_type, source_id),
    ).fetchone()
    if rounded == 0:
        if existing and update_existing:
            db.execute('DELETE FROM AccountingTransaction WHERE transactionID=?',
                       (existing['transactionID'],))
        return None
    values = (kind, str(when), description.strip(), reference.strip(), float(rounded))
    if existing:
        if update_existing:
            updated = ', updatedAt=CURRENT_TIMESTAMP' if 'updatedAt' in columns else ''
            db.execute(
                f'UPDATE AccountingTransaction SET "{type_col}"=?, "{date_col}"=?, '
                f'description=?, reference=?, amount=?{updated} WHERE transactionID=?',
                (*values, existing['transactionID']),
            )
        return int(existing['transactionID'])
    return int(db.execute(
        f'INSERT INTO AccountingTransaction '
        f'(ledgerID, "{type_col}", "{date_col}", description, reference, amount, sourceType, sourceID) '
        f'VALUES (1, ?, ?, ?, ?, ?, ?, ?)',
        (*values, source_type, source_id),
    ).lastrowid)


@dataclass
class AccountingTransaction:
    transactionID: int | None
    transactionType: str
    transactionDate: str
    description: str
    reference: str
    amount: float

    def validateTransaction(self) -> bool:
        if self.transactionType not in TRANSACTION_TYPES:
            raise AccountingError("Choose Sale, Purchase, Expense, or Inventory Adjustment.")
        try:
            parsed_date = date.fromisoformat(self.transactionDate)
        except (TypeError, ValueError) as exc:
            raise AccountingError("Transaction date must use YYYY-MM-DD format.") from exc
        if parsed_date > date.today():
            raise AccountingError("Transaction date cannot be in the future.")
        if not self.description.strip():
            raise AccountingError("Description is required.")
        if not math.isfinite(float(self.amount)) or float(self.amount) < 0:
            raise AccountingError("Amount must be a valid number greater than or equal to zero.")
        if not self.reference.strip():
            # References are optional for ordinary cash expenses, but normalized.
            self.reference = ""
        self.amount = round(float(self.amount), 2)
        self.transactionDate = parsed_date.isoformat()
        self.description = self.description.strip()
        self.reference = self.reference.strip()
        return True

    def updateTransaction(self, **changes) -> None:
        allowed = {"transactionType", "transactionDate", "description", "reference", "amount"}
        unknown = set(changes) - allowed
        if unknown:
            raise AccountingError("Unsupported transaction field(s): " + ", ".join(sorted(unknown)))
        for field, value in changes.items():
            setattr(self, field, value)
        self.validateTransaction()


@dataclass
class AccountingSummary:
    totalSales: float = 0.0
    totalPurchases: float = 0.0
    totalExpenses: float = 0.0
    totalAdjustments: float = 0.0
    balance: float = 0.0

    def calculateSummary(self, transactions: list[dict]) -> "AccountingSummary":
        totals = {"Sale": 0.0, "Purchase": 0.0, "Expense": 0.0, "Inventory Adjustment": 0.0}
        for item in transactions:
            kind = item["transactionType"]
            if kind in totals:
                totals[kind] += float(item["amount"])
        self.totalSales = round(totals["Sale"], 2)
        self.totalPurchases = round(totals["Purchase"], 2)
        self.totalExpenses = round(totals["Expense"], 2)
        self.totalAdjustments = round(totals["Inventory Adjustment"], 2)
        # Report adjustments separately because their recorded value does not
        # identify a debit/credit direction for the financial balance.
        self.balance = round(self.totalSales - self.totalPurchases - self.totalExpenses, 2)
        return self

    def displaySummary(self) -> dict:
        return {
            "totalSales": self.totalSales,
            "totalPurchases": self.totalPurchases,
            "totalExpenses": self.totalExpenses,
            "totalAdjustments": self.totalAdjustments,
            "balance": self.balance,
        }


@dataclass
class AccountingDiscrepancy:
    discrepancyID: int | None
    description: str
    amount: float
    status: str = "Flagged"
    transactionID: int | None = None

    def flag(self) -> None:
        self.status = "Flagged"

    def resolve(self) -> None:
        self.status = "Resolved"


class AccountingLedger:
    """Coordinates accounting transactions, summary calculations and reconciliation."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = db_path
        self.ledgerID = 1
        initialize(db_path)
        with connect(self.db_path) as db:
            columns = {row["name"] for row in db.execute('PRAGMA table_info("AccountingTransaction")')}
        # The payroll module uses `date` and `type`; the standalone accounting
        # module uses `transactionDate` and `transactionType`. Keep either table
        # unchanged so payroll's transaction IDs / foreign keys remain valid.
        if {"transactionDate", "transactionType"} <= columns:
            self.date_column, self.type_column = "transactionDate", "transactionType"
            self.legacy_payroll_schema = False
        elif {"date", "type"} <= columns:
            self.date_column, self.type_column = "date", "type"
            self.legacy_payroll_schema = True
        else:
            raise AccountingError("AccountingTransaction has an unsupported schema. Restore a backup or review its columns.")
        self.has_created_at = "createdAt" in columns
        self.has_updated_at = "updatedAt" in columns

    def ensure_demo_transactions(self) -> int:
        """Seed clearly labelled fictional transactions only when the ledger is empty.

        This makes the Accounting menu demonstrable on first use without
        duplicating samples or overwriting any existing accounting records.
        Returns the number of rows inserted.
        """
        if self.getTransactions():
            return 0
        from datetime import timedelta
        today = date.today()
        samples = [
            ("Sale", today - timedelta(days=1), "DEMO - Onigiri lunch sales", "DEMO-SALE-001", 685.50),
            ("Sale", today - timedelta(days=2), "DEMO - Catering order sales", "DEMO-SALE-002", 1240.00),
            ("Sale", today - timedelta(days=4), "DEMO - Daily counter sales", "DEMO-SALE-003", 532.75),
            ("Purchase", today - timedelta(days=3), "DEMO - Rice and nori supplier invoice", "DEMO-INV-004", 215.40),
            ("Purchase", today - timedelta(days=6), "DEMO - Filling ingredients", "DEMO-PURCHASE-005", 178.25),
            ("Expense", today - timedelta(days=5), "DEMO - Packaging and cleaning supplies", "DEMO-INV-004", 64.90),
            ("Expense", today - timedelta(days=7), "DEMO - Delivery and utilities", "DEMO-EXPENSE-007", 92.00),
            ("Inventory Adjustment", today - timedelta(days=2), "DEMO - Inventory value correction", "DEMO-ADJUST-008", 18.50),
        ]
        with db_transaction(self.db_path) as db:
            # Recheck within the write transaction to avoid duplicate seeding
            # if two application sessions are opened at the same time.
            count = db.execute("SELECT COUNT(*) FROM AccountingTransaction").fetchone()[0]
            if count:
                return 0
            for kind, when, description, reference, amount in samples:
                db.execute(
                    "INSERT INTO AccountingTransaction "
                    f'(ledgerID, "{self.type_column}", "{self.date_column}", '
                    'description, reference, amount) '
                    "VALUES (1, ?, ?, ?, ?, ?)",
                    (kind, when.isoformat(), description, reference, amount),
                )
        return len(samples)

    def _read(self, sql: str, args: tuple = ()) -> list[dict]:
        db = connect(self.db_path)
        try:
            return [dict(row) for row in db.execute(sql, args).fetchall()]
        finally:
            db.close()

    def getTransactions(self, start_date: str | None = None,
                        end_date: str | None = None) -> list[dict]:
        clauses, args = [], []
        if start_date:
            try:
                date.fromisoformat(start_date)
            except ValueError as exc:
                raise AccountingError("Start date must use YYYY-MM-DD format.") from exc
            clauses.append(f'"{self.date_column}" >= ?')
            args.append(start_date)
        if end_date:
            try:
                date.fromisoformat(end_date)
            except ValueError as exc:
                raise AccountingError("End date must use YYYY-MM-DD format.") from exc
            clauses.append(f'"{self.date_column}" <= ?')
            args.append(end_date)
        if start_date and end_date and start_date > end_date:
            raise AccountingError("Start date cannot be after end date.")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        results = self._read(
            f'SELECT transactionID, ledgerID, "{self.type_column}" AS transactionType, '
            f'"{self.date_column}" AS transactionDate, '
            'description, reference, amount, sourceType, sourceID, '
            + ('createdAt' if self.has_created_at else 'NULL') + ' AS createdAt, '
            + ('updatedAt' if self.has_updated_at else 'NULL') + ' AS updatedAt '
            + 'FROM AccountingTransaction' + where
            + f' ORDER BY "{self.date_column}" DESC, transactionID DESC',
            tuple(args),
        )
        for result in results:
            result['source'] = (f"{result['sourceType']} #{result['sourceID']}"
                                if result['sourceType'] and result['sourceID'] is not None
                                else 'Manual')
        return results

    def pending_completed_orders(self) -> list[dict]:
        """Completed priced shop orders that lack a linked accounting Sale."""
        return self._read('''
            SELECT o.orderID, o.orderDate, o.totalAmount,
                   COALESCE(lt.finalAmount, o.totalAmount) AS paidAmount
              FROM "Order" o LEFT JOIN LoyaltyTransaction lt ON lt.orderID=o.orderID
             WHERE o.status='Completed' AND o.totalAmount IS NOT NULL
               AND COALESCE(lt.finalAmount, o.totalAmount) > 0
               AND EXISTS (SELECT 1 FROM OrderRecipe r WHERE r.orderID=o.orderID)
               AND NOT EXISTS (SELECT 1 FROM AccountingTransaction a
                                WHERE a.sourceType='Order' AND a.sourceID=o.orderID)
             ORDER BY o.orderID
        ''')

    def manual_sale_count(self) -> int:
        return self._read(
            f'SELECT COUNT(*) AS count FROM AccountingTransaction '
            f'WHERE sourceType IS NULL AND "{self.type_column}"=?', ('Sale',)
        )[0]['count']

    def sync_completed_orders(self, *, allow_with_manual_sales: bool = False,
                              order_ids: set[int] | None = None) -> int:
        """Add missing past completed shop sales once, preserving all existing rows.

        Only orders with recipe lines qualify. Loyalty finalAmount is used when
        available. If manual sales exist, require explicit Owner review first
        because those sales could already cover some of these old orders.
        """
        selected_ids = ({_positive_id(x) for x in order_ids}
                        if order_ids is not None else None)
        posted = 0
        with db_transaction(self.db_path) as db:
            if not allow_with_manual_sales and db.execute(
                f'SELECT 1 FROM AccountingTransaction '
                f'WHERE sourceType IS NULL AND "{self.type_column}"=? LIMIT 1',
                ('Sale',),
            ).fetchone():
                return 0
            completed = db.execute('''
                SELECT o.orderID, o.orderDate, o.totalAmount,
                       COALESCE(lt.finalAmount, o.totalAmount) AS paidAmount
                  FROM "Order" o LEFT JOIN LoyaltyTransaction lt ON lt.orderID=o.orderID
                 WHERE o.status='Completed' AND o.totalAmount IS NOT NULL
                   AND COALESCE(lt.finalAmount, o.totalAmount) > 0
                   AND EXISTS (SELECT 1 FROM OrderRecipe r WHERE r.orderID=o.orderID)
                 ORDER BY o.orderID
            ''').fetchall()
            for order in completed:
                if selected_ids is not None and order['orderID'] not in selected_ids:
                    continue
                if db.execute('SELECT 1 FROM AccountingTransaction WHERE sourceType=? AND sourceID=?',
                              ('Order', order['orderID'])).fetchone():
                    continue
                if post_source_transaction(
                    db, kind='Sale', when=order['orderDate'] or date.today().isoformat(),
                    description=f"Completed customer order #{order['orderID']}",
                    reference=f"ORDER-{order['orderID']}", amount=order['paidAmount'],
                    source_type='Order', source_id=order['orderID'],
                ) is not None:
                    posted += 1
        return posted

    def addTransaction(self, transaction: AccountingTransaction) -> int:
        transaction.validateTransaction()
        self._check_legacy_amount(transaction.amount)
        with db_transaction(self.db_path) as db:
            result = db.execute(
                "INSERT INTO AccountingTransaction "
                f'(ledgerID, "{self.type_column}", "{self.date_column}", '
                'description, reference, amount) '
                "VALUES (1, ?, ?, ?, ?, ?)",
                (transaction.transactionType, transaction.transactionDate, transaction.description,
                 transaction.reference, transaction.amount),
            )
            transaction.transactionID = int(result.lastrowid)
            return transaction.transactionID

    def updateTransaction(self, transaction: AccountingTransaction) -> None:
        if transaction.transactionID is None:
            raise AccountingError("A transaction ID is required to update an entry.")
        transaction.validateTransaction()
        self._check_legacy_amount(transaction.amount)
        with db_transaction(self.db_path) as db:
            linked = db.execute('SELECT sourceType FROM AccountingTransaction WHERE transactionID=?',
                                (_positive_id(transaction.transactionID),)).fetchone()
            if linked and linked['sourceType']:
                raise AccountingError('This entry belongs to an order, payroll, or delivery. '
                                      'Correct the originating transaction instead.')
            result = db.execute(
                f'UPDATE AccountingTransaction SET "{self.type_column}" = ?, '
                f'"{self.date_column}" = ?, description = ?, reference = ?, amount = ?'
                + (', updatedAt = CURRENT_TIMESTAMP' if self.has_updated_at else '')
                + ' WHERE transactionID = ?',
                (transaction.transactionType, transaction.transactionDate, transaction.description,
                 transaction.reference, transaction.amount, _positive_id(transaction.transactionID)),
            )
            if result.rowcount != 1:
                raise AccountingError(f"Accounting transaction #{transaction.transactionID} was not found.")

    def _check_legacy_amount(self, amount: float) -> None:
        if self.legacy_payroll_schema and amount == 0:
            raise AccountingError(
                "This database uses the payroll accounting format, which requires "
                "a transaction amount greater than zero. Enter a positive amount."
            )

    def reconcile(self) -> bool:
        """Check saved entries and flag duplicate non-empty references for owner review."""
        self.reconcile_with_report()
        return True

    def reconcile_with_report(self) -> dict:
        """Reconcile and return what changed, without changing the existing bool API."""
        rows = self.getTransactions()
        grouped: dict[str, list[dict]] = {}
        for row in rows:
            ref = (row.get("reference") or "").strip().casefold()
            if ref:
                grouped.setdefault(ref, []).append(row)

        new_flags = 0
        cleared_flags = 0
        with db_transaction(self.db_path) as db:
            # Clear prior duplicate-reference flags only when they were resolved
            # or the duplicate condition no longer exists; preserve manual flags.
            for reference, matches in grouped.items():
                if len(matches) < 2:
                    continue
                for row in matches:
                    description = f"Duplicate reference '{row['reference']}' appears on multiple accounting transactions."
                    exists = db.execute(
                        "SELECT 1 FROM AccountingDiscrepancy WHERE transactionID = ? "
                        "AND description = ? LIMIT 1",
                        (row["transactionID"], description),
                    ).fetchone()
                    if not exists:
                        db.execute(
                            "INSERT INTO AccountingDiscrepancy (transactionID, description, amount, status) "
                            "VALUES (?, ?, ?, 'Flagged')",
                            (row["transactionID"], description, row["amount"]),
                        )
                        new_flags += 1
            # If a duplicate has been corrected, resolve stale duplicate flags.
            duplicate_refs = {ref for ref, matches in grouped.items() if len(matches) > 1}
            flagged = db.execute(
                "SELECT discrepancyID, transactionID, description FROM AccountingDiscrepancy "
                "WHERE status = 'Flagged' AND description LIKE 'Duplicate reference %'"
            ).fetchall()
            for discrepancy in flagged:
                match = next((r for r in rows if r["transactionID"] == discrepancy["transactionID"]), None)
                ref = (match.get("reference") or "").strip().casefold() if match else ""
                if ref not in duplicate_refs:
                    db.execute(
                        "UPDATE AccountingDiscrepancy SET status = 'Resolved', resolvedAt = CURRENT_TIMESTAMP "
                        "WHERE discrepancyID = ?", (discrepancy["discrepancyID"],)
                    )
                    cleared_flags += 1
            flagged_count = db.execute(
                "SELECT COUNT(*) FROM AccountingDiscrepancy WHERE status = 'Flagged'"
            ).fetchone()[0]
            result = db.execute(
                "INSERT INTO AccountingReconciliationLog (transactionCount, flaggedCount, result) "
                "VALUES (?, ?, ?)",
                (len(rows), int(flagged_count), "Completed" if flagged_count == 0 else "Completed with flags"),
            )
            log_id = int(result.lastrowid)
        return {
            "transactionCount": len(rows),
            "duplicateReferenceGroups": len(duplicate_refs),
            "newFlags": new_flags,
            "clearedFlags": cleared_flags,
            "flaggedCount": int(flagged_count),
            "reconciliationID": log_id,
        }

    def getReconciliationLog(self, limit: int = 25) -> list[dict]:
        try:
            limit = max(1, min(200, int(limit)))
        except (TypeError, ValueError):
            limit = 25
        return self._read(
            "SELECT reconciliationID, reconciledAt, transactionCount, flaggedCount, result "
            "FROM AccountingReconciliationLog ORDER BY reconciliationID DESC LIMIT ?", (limit,)
        )

    def getDiscrepancies(self, status: str | None = None) -> list[dict]:
        if status is not None and status not in {"Flagged", "Resolved"}:
            raise AccountingError("Discrepancy status must be Flagged or Resolved.")
        if status:
            return self._read(
                "SELECT discrepancyID, transactionID, description, amount, status, createdAt, resolvedAt "
                "FROM AccountingDiscrepancy WHERE status = ? ORDER BY discrepancyID DESC", (status,)
            )
        return self._read(
            "SELECT discrepancyID, transactionID, description, amount, status, createdAt, resolvedAt "
            "FROM AccountingDiscrepancy ORDER BY discrepancyID DESC"
        )

    def resolveDiscrepancy(self, discrepancy_id: int) -> None:
        discrepancy_id = _positive_id(discrepancy_id)
        with db_transaction(self.db_path) as db:
            result = db.execute(
                "UPDATE AccountingDiscrepancy SET status = 'Resolved', resolvedAt = CURRENT_TIMESTAMP "
                "WHERE discrepancyID = ? AND status = 'Flagged'", (discrepancy_id,)
            )
            if result.rowcount != 1:
                raise AccountingError("Flagged discrepancy not found; it may already be resolved.")

    def calculateSummary(self, start_date: str | None = None,
                         end_date: str | None = None) -> AccountingSummary:
        return AccountingSummary().calculateSummary(self.getTransactions(start_date, end_date))

    def dashboard(self) -> dict:
        self.reconcile()
        return {
            "transactions": self.getTransactions(),
            "summary": self.calculateSummary().displaySummary(),
            "discrepancies": self.getDiscrepancies("Flagged"),
            "reconciliationLog": self.getReconciliationLog(),
        }
