"""Regression tests; run `python -m unittest -v test_inventory.py`."""
from pathlib import Path
import sqlite3
import tempfile
import unittest

from inventory_service import InventoryError, InventoryService, InsufficientStockError
from inventory_db import connect


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "btm495.db"
        self.s = InventoryService(self.db_path)
        self.assertTrue(self.s.created_database)
        self.user_id = self.s.create_user("Test Owner", "owner", "not-a-default-password", "Owner")
        self.rice = self.s.add_ingredient("Rice", "g", 1000, 400, self.user_id)
        self.nori = self.s.add_ingredient("Nori", "sheets", 6, 4, self.user_id)
        self.onigiri = self.s.add_recipe("Plain Onigiri", 3.5)
        self.s.set_recipe_ingredient(self.onigiri, self.rice, 120)
        self.s.set_recipe_ingredient(self.onigiri, self.nori, 1)

    def stock(self, item_id):
        return next(x for x in self.s.inventory() if x["ingredientID"] == item_id)["quantityOnHand"]

    def test_persistence_between_instances(self):
        self.s.adjust_stock(self.rice, "remove", 100, self.user_id)
        other = InventoryService(self.db_path)
        self.assertFalse(other.created_database)
        self.assertEqual(self.stock(self.rice), 900)
        self.assertEqual(other.login("owner", "not-a-default-password")["role"], "Owner")
        self.assertEqual(len(other.inventory()), 2)

    def test_pending_order_does_not_change_inventory(self):
        oid = self.s.create_customer_order({self.onigiri: 2}, self.user_id)
        self.assertEqual(self.stock(self.rice), 1000)
        self.assertEqual(self.stock(self.nori), 6)
        self.assertEqual(self.s.customer_orders()[0]["status"], "Pending")
        self.assertEqual(self.s.customer_orders()[0]["totalAmount"], 7.0)
        self.assertEqual(self.s.order_recipes(oid)[0]["quantity"], 2)

    def test_complete_deducts_correct_amount_and_cannot_repeat(self):
        oid = self.s.create_customer_order({self.onigiri: 2}, self.user_id)
        self.s.complete_customer_order(oid, self.user_id)
        self.assertEqual(self.stock(self.rice), 760)
        self.assertEqual(self.stock(self.nori), 4)
        with self.assertRaises(InventoryError):
            self.s.complete_customer_order(oid, self.user_id)
        self.assertEqual(self.stock(self.rice), 760)

    def test_insufficient_stock_leaves_entire_order_pending(self):
        oid = self.s.create_customer_order({self.onigiri: 8}, self.user_id)
        with self.assertRaises(InsufficientStockError) as cm:
            self.s.complete_customer_order(oid, self.user_id)
        self.assertIn("Nori", str(cm.exception))
        self.assertEqual(self.stock(self.rice), 1000)
        self.assertEqual(self.stock(self.nori), 6)
        self.assertEqual(self.s.customer_orders()[0]["status"], "Pending")
        self.assertEqual(len(self.s.transactions()), 2)  # opening stock only

    def test_invalid_manual_remove_no_negative_stock(self):
        with self.assertRaises(InsufficientStockError):
            self.s.adjust_stock(self.nori, "remove", 15, self.user_id)
        with self.assertRaises(InventoryError):
            self.s.adjust_stock(self.nori, "remove", -1, self.user_id)
        self.assertEqual(self.stock(self.nori), 6)

    def test_one_alert_while_low_and_closes_after_receipt(self):
        self.s.adjust_stock(self.nori, "remove", 3, self.user_id)
        self.assertEqual(len(self.s.alerts()), 1)
        self.s.adjust_stock(self.nori, "remove", 1, self.user_id)
        self.assertEqual(len(self.s.alerts()), 1)
        alert = self.s.alerts()[0]
        self.s.update_alert(alert["alertID"], "Reviewed")
        self.assertEqual(self.s.alerts()[0]["status"], "Reviewed")
        self.s.receive_delivery({self.nori: 3}, self.user_id)
        self.assertEqual(len(self.s.alerts()), 0)
        self.assertEqual(self.s.alerts(False)[0]["status"], "Closed")

    def test_threshold_equality_no_alert(self):
        self.s.adjust_stock(self.nori, "remove", 2, self.user_id)  # 6 -> 4
        self.assertEqual(len(self.s.alerts()), 0)
        self.s.adjust_stock(self.nori, "remove", 1, self.user_id)
        self.assertEqual(len(self.s.alerts()), 1)

    def test_purchase_and_partial_delivery(self):
        sup = self.s.add_supplier("Supply House", "contact")
        po = self.s.create_purchase_order({self.rice: 200, self.nori: 10}, "Replenish stock")
        self.assertEqual(self.stock(self.rice), 1000)  # ordering alone adds nothing
        self.s.receive_delivery({self.rice: 100}, self.user_id, sup, po)
        self.assertEqual(self.s.purchase_orders()[0]["status"], "Partially Received")
        self.assertEqual(self.stock(self.rice), 1100)
        self.s.receive_delivery({self.rice: 100, self.nori: 10}, self.user_id, sup, po)
        self.assertEqual(self.s.purchase_orders()[0]["status"], "Received")
        self.assertEqual(self.stock(self.rice), 1200)
        self.assertEqual(self.stock(self.nori), 16)

    def test_over_receipt_rolls_back_entire_batch(self):
        po = self.s.create_purchase_order({self.rice: 50, self.nori: 2})
        with self.assertRaises(InventoryError):
            self.s.receive_delivery({self.rice: 50, self.nori: 3}, self.user_id,
                                    purchase_order_id=po)
        self.assertEqual(self.stock(self.rice), 1000)
        self.assertEqual(self.stock(self.nori), 6)
        self.assertEqual(self.s.purchase_order_lines(po)[0]["receivedQuantity"], 0)

    def test_transactions_mirror_to_shared_adjustment(self):
        self.s.adjust_stock(self.rice, "remove", 30, self.user_id)
        db = connect(self.db_path)
        try:
            a = db.execute('SELECT quantityChange FROM InventoryAdjustment ORDER BY adjustmentID DESC LIMIT 1').fetchone()
            b = db.execute('SELECT quantity FROM InventoryTransaction ORDER BY transactionID DESC LIMIT 1').fetchone()
            self.assertEqual(a[0], -30)
            self.assertEqual(b[0], -30)
        finally:
            db.close()

    def test_owner_employee_subtype_compatibility(self):
        employee = self.s.create_user("Staff", "staff", "another-password", "Employee")
        db = connect(self.db_path)
        try:
            self.assertEqual(db.execute('SELECT userID FROM "Owner"').fetchone()[0], self.user_id)
            self.assertEqual(db.execute('SELECT userID FROM "Employee"').fetchone()[0], employee)
        finally:
            db.close()

    def test_order_cancelled_without_stock_change(self):
        oid = self.s.create_customer_order({self.onigiri: 1}, self.user_id)
        self.s.cancel_customer_order(oid)
        self.assertEqual(self.stock(self.rice), 1000)
        with self.assertRaises(InventoryError):
            self.s.complete_customer_order(oid, self.user_id)

    def test_stock_audited_after_order_completion(self):
        oid = self.s.create_customer_order({self.onigiri: 1}, self.user_id)
        self.s.complete_customer_order(oid, self.user_id)
        events = [x for x in self.s.transactions() if x["customerOrderID"] == oid]
        self.assertEqual(len(events), 2)
        self.assertEqual({x["ingredientName"] for x in events}, {"Rice", "Nori"})

    def test_schema_does_not_erase_existing_custom_user(self):
        db = connect(self.db_path)
        try:
            with db:
                db.execute('INSERT INTO "User"(userID,name,username) VALUES(?,?,?)',
                           (987, "Existing Person", "prior_user"))
        finally:
            db.close()
        self.s = InventoryService(self.db_path)
        db = connect(self.db_path)
        try:
            self.assertEqual(db.execute('SELECT name FROM "User" WHERE userID=987').fetchone()[0],
                             "Existing Person")
        finally:
            db.close()

    def test_database_failure_rolls_back_stock_and_history(self):
        before = self.stock(self.rice)
        tx_before = len(self.s.transactions())
        db = connect(self.db_path)
        try:
            db.execute("""CREATE TRIGGER fail_audit BEFORE INSERT ON InventoryAdjustment
                          BEGIN SELECT RAISE(ABORT, 'test simulated write error'); END""")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(sqlite3.DatabaseError):
            self.s.adjust_stock(self.rice, "remove", 25, self.user_id)
        self.assertEqual(self.stock(self.rice), before)
        self.assertEqual(len(self.s.transactions()), tx_before)

    def test_multiple_recipes_share_ingredients_correctly(self):
        other = self.s.add_recipe("Rice snack", 2)
        self.s.set_recipe_ingredient(other, self.rice, 50)
        oid = self.s.create_customer_order({self.onigiri: 2, other: 3}, self.user_id)
        self.s.complete_customer_order(oid, self.user_id)
        self.assertEqual(self.stock(self.rice), 610)
        self.assertEqual(self.stock(self.nori), 4)

    def test_external_broad_system_order_not_completable(self):
        db = connect(self.db_path)
        try:
            with db:
                oid = db.execute('INSERT INTO "Order"(status, totalAmount) VALUES(?, ?)',
                                 ("Pending", 0)).lastrowid
        finally:
            db.close()
        with self.assertRaisesRegex(InventoryError, "no recipes"):
            self.s.complete_customer_order(oid, self.user_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
