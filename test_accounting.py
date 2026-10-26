"""Focused tests for the Accounting subsystem; all tests use temporary databases."""
from datetime import date, timedelta
from contextlib import redirect_stdout
import io
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from accounting_service import (
    AccountingError, AccountingLedger, AccountingTransaction
)
import inventory_cli


class AccountingTests(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        self.ledger = AccountingLedger(self.db_path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(self.db_path + suffix)
            except FileNotFoundError:
                pass

    def add(self, kind, description, amount, reference=""):
        entry = AccountingTransaction(
            None, kind, date.today().isoformat(), description, reference, amount
        )
        return self.ledger.addTransaction(entry)

    def test_add_and_calculate_summary(self):
        self.add("Sale", "Customer sale", 125.50, "S-1")
        self.add("Purchase", "Ingredient purchase", 25.25, "P-1")
        self.add("Expense", "Packaging", 10, "E-1")
        self.add("Inventory Adjustment", "Stock correction", 3)
        summary = self.ledger.calculateSummary().displaySummary()
        self.assertEqual(summary["totalSales"], 125.50)
        self.assertEqual(summary["totalPurchases"], 25.25)
        self.assertEqual(summary["totalExpenses"], 10)
        self.assertEqual(summary["totalAdjustments"], 3)
        self.assertEqual(summary["balance"], 90.25)

    def test_invalid_entry_is_rejected(self):
        entry = AccountingTransaction(None, "Refund", date.today().isoformat(), "Bad type", "", 10)
        with self.assertRaises(AccountingError):
            self.ledger.addTransaction(entry)

    def test_future_date_is_rejected(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        entry = AccountingTransaction(None, "Sale", future, "Future sale", "", 10)
        with self.assertRaises(AccountingError):
            self.ledger.addTransaction(entry)

    def test_duplicate_reference_flags_both_entries(self):
        self.add("Sale", "First sale", 20, "INV-1")
        self.add("Purchase", "Purchase with repeated reference", 10, "INV-1")
        self.ledger.reconcile()
        flagged = self.ledger.getDiscrepancies("Flagged")
        self.assertEqual(len(flagged), 2)
        self.assertEqual(len(self.ledger.getReconciliationLog()), 1)

    def test_update_and_resolve_discrepancy(self):
        first = self.add("Sale", "First", 20, "DUP-1")
        self.add("Expense", "Second", 5, "DUP-1")
        self.ledger.reconcile()
        discrepancy_id = self.ledger.getDiscrepancies("Flagged")[0]["discrepancyID"]
        self.ledger.resolveDiscrepancy(discrepancy_id)
        self.assertEqual(
            next(d for d in self.ledger.getDiscrepancies() if d["discrepancyID"] == discrepancy_id)["status"],
            "Resolved",
        )
        self.ledger.updateTransaction(
            AccountingTransaction(first, "Sale", date.today().isoformat(), "Updated sale", "NEW-1", 30)
        )
        updated = next(row for row in self.ledger.getTransactions()
                       if row["transactionID"] == first)
        self.assertEqual(updated["description"], "Updated sale")

    def test_reconcile_reports_new_and_cleared_flags(self):
        first = self.add("Sale", "Sale A", 20, "SAME")
        self.add("Expense", "Expense B", 10, "SAME")
        report = self.ledger.reconcile_with_report()
        self.assertEqual((report["transactionCount"], report["newFlags"], report["flaggedCount"]), (2, 2, 2))
        self.ledger.updateTransaction(
            AccountingTransaction(first, "Sale", date.today().isoformat(), "Sale A", "DIFFERENT", 20)
        )
        report = self.ledger.reconcile_with_report()
        self.assertEqual((report["newFlags"], report["clearedFlags"], report["flaggedCount"]), (0, 2, 0))

    def test_transaction_type_accepts_number_and_text_and_blank_cancel(self):
        for raw, expected in (("2", "Purchase"), ("inventory adjustment", "Inventory Adjustment")):
            answers = iter([raw, "", "Test entry", "", "12.50"])
            with patch("builtins.input", side_effect=lambda _="": next(answers)):
                with redirect_stdout(io.StringIO()):
                    entry = inventory_cli.accounting_entry_fields()
            self.assertEqual(entry.transactionType, expected)
        with patch("builtins.input", return_value=""):
            with redirect_stdout(io.StringIO()):
                self.assertIsNone(inventory_cli.accounting_entry_fields())

    def test_accounting_menu_pauses_after_selection(self):
        with patch("inventory_cli.AccountingLedger", return_value=self.ledger):
            with patch("builtins.input", side_effect=["2", "", "0"]) as inputs:
                out = io.StringIO()
                with redirect_stdout(out):
                    inventory_cli.accounting_menu({"role": "Owner"})
        self.assertEqual(inputs.call_count, 3)
        self.assertIn("Press Enter to return to the Accounting Ledger menu",
                      str(inputs.call_args_list))
        self.assertIn("Accounting Transactions", out.getvalue())

    def test_blank_id_returns_from_update_and_review(self):
        self.add("Sale", "Initial", 10, "R1")
        with patch("builtins.input", return_value=""):
            with redirect_stdout(io.StringIO()):
                inventory_cli.accounting_update(self.ledger)
        self.add("Expense", "Another", 5, "R1")
        with patch("builtins.input", return_value=""):
            with redirect_stdout(io.StringIO()):
                inventory_cli.accounting_review_discrepancies(self.ledger)
        self.assertEqual(len(self.ledger.getDiscrepancies("Flagged")), 2)


class LegacyPayrollDatabaseTests(unittest.TestCase):
    def test_existing_payroll_schema_and_links_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "btm495.db")
            with sqlite3.connect(path) as db:
                db.executescript('''
                    PRAGMA foreign_keys = ON;
                    CREATE TABLE AccountingLedger (ledgerID INTEGER PRIMARY KEY);
                    INSERT INTO AccountingLedger VALUES (1);
                    CREATE TABLE AccountingTransaction (
                        transactionID INTEGER PRIMARY KEY,
                        ledgerID INTEGER NOT NULL DEFAULT 1,
                        date TEXT NOT NULL, description TEXT NOT NULL,
                        reference TEXT NOT NULL, amount REAL NOT NULL CHECK(amount > 0),
                        type TEXT NOT NULL,
                        FOREIGN KEY(ledgerID) REFERENCES AccountingLedger(ledgerID)
                    );
                    CREATE TABLE Payroll (
                        payrollID INTEGER PRIMARY KEY,
                        accountingTransactionID INTEGER,
                        FOREIGN KEY(accountingTransactionID) REFERENCES AccountingTransaction(transactionID)
                    );
                    INSERT INTO AccountingTransaction(ledgerID,date,description,reference,amount,type)
                        VALUES (1,'2026-01-01','Payroll expense','PAY-1',590,'Expense');
                    INSERT INTO Payroll VALUES (1,1);
                ''')
            ledger = AccountingLedger(path)
            self.assertTrue(ledger.legacy_payroll_schema)
            self.assertEqual(ledger.getTransactions()[0]["transactionType"], "Expense")
            new_id = ledger.addTransaction(
                AccountingTransaction(None, "Sale", date.today().isoformat(), "Counter sale", "S-2", 20)
            )
            ledger.updateTransaction(
                AccountingTransaction(new_id, "Sale", date.today().isoformat(), "Updated sale", "S-2", 25)
            )
            with self.assertRaisesRegex(AccountingError, "greater than zero"):
                ledger.addTransaction(
                    AccountingTransaction(None, "Expense", date.today().isoformat(), "Zero", "", 0)
                )
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(db.execute("SELECT accountingTransactionID FROM Payroll").fetchone()[0], 1)
                self.assertEqual(db.execute("SELECT date, type FROM AccountingTransaction WHERE transactionID=?",
                                            (new_id,)).fetchone(), (date.today().isoformat(), "Sale"))
                columns = {row[1] for row in db.execute("PRAGMA table_info(AccountingTransaction)")}
                self.assertNotIn("transactionDate", columns)
            self.assertEqual(ledger.ensure_demo_transactions(), 0)


if __name__ == "__main__":
    unittest.main()
