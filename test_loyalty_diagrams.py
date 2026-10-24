"""Class diagram alignment: domain methods, relationships, UUIDs and migrations."""
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
import unittest
from uuid import UUID

from inventory_db import connect, initialize
from inventory_service import InventoryService
from loyalty_models import LoyaltyAccount, LoyaltyTransaction, Reward, Redemption
from loyalty_service import LoyaltyError, LoyaltyService


class ClassDiagramAlignmentTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'onigiri.db'
        self.shop = InventoryService(self.path)
        self.owner = self.shop.create_user('Owner', 'owner', 'secure-password', 'Owner')
        self.staff = self.shop.create_user('Employee', 'employee', 'secure-password', 'Employee')
        self.customer_user = self.shop.create_user('Customer', 'customer', 'secure-password', 'Customer')
        self.service = LoyaltyService(self.path, points_per_dollar=1)  # Legacy point examples
        self.customer_id = self.service.customer_id_for_user(self.customer_user)
        ingredient = self.shop.add_ingredient('Rice', 'g', 3000, 300, self.staff)
        recipe = self.shop.add_recipe('Onigiri', 20)
        self.shop.set_recipe_ingredient(recipe, ingredient, 100)
        self.recipe_id = recipe

    def order(self):
        order_id = self.shop.create_customer_order({self.recipe_id: 1}, self.staff)
        self.shop.complete_customer_order(order_id, self.staff)
        return order_id

    def test_optional_account_and_one_to_many_transactions(self):
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount').fetchone()[0], 0)
        self.service.enroll_existing_customer(self.customer_user, self.staff)
        self.service.enroll_existing_customer(self.customer_user, self.staff)
        account = self.service.account_model(self.customer_id)
        self.assertIsInstance(account, LoyaltyAccount)
        self.assertEqual(account.currentPoints, account.pointsBalance)
        UUID(account.publicUUID)
        self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyAccount WHERE customerID=?',
                                        (self.customer_id,)).fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 2)
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('''INSERT INTO LoyaltyAccount(customerID,pointsBalance)
                              VALUES(?,0)''', (self.customer_id,))

    def test_domain_methods_and_diagram_attribute_aliases(self):
        account = LoyaltyAccount(accountID=101, customerID=5)
        account.addPoints(20)
        self.assertEqual(account.pointsBalance, 20)
        self.assertFalse(account.redeemPoints(40))
        self.assertTrue(account.deductPoints(6))
        self.assertEqual(account.currentPoints, 14)
        with self.assertRaises(ValueError):
            account.addPoints(-1)
        reward = Reward(2, 'Reward', 10, True, Decimal('3.00'))
        self.assertEqual(reward.requiredPoints, reward.pointsCost)
        self.assertTrue(reward.isAvailable())
        self.assertTrue(reward.isEligible(14))
        self.assertFalse(reward.isEligible(9))
        pending = Redemption(1, 2, 10, Decimal('3.00'))
        pending.cancelRedemption()
        self.assertEqual(pending.status, 'Cancelled')
        with self.assertRaises(ValueError):
            pending.confirmRedemption()

    def test_earn_only_transaction_uses_no_redemption(self):
        self.service.enroll_existing_customer(self.customer_user, self.staff)
        result = self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        tx = self.service.transaction_model(result['loyaltyTransactionID'])
        self.assertIsInstance(tx, LoyaltyTransaction)
        self.assertEqual((tx.type, tx.pointsChange, tx.points), ('Earn', 20, 20))
        self.assertIsNotNone(tx.transactionDate)
        UUID(tx.publicUUID)
        self.assertIsNone(self.service.redemption_model(tx.transactionID))
        self.assertEqual(self.service.transaction_history(self.customer_id)[0]['pointsChange'], 20)
        with self.assertRaises(ValueError):
            with connect(self.path) as db:
                tx.record(db)  # Cannot record an already-saved transaction again.

    def test_redemption_status_and_reward_cardinality(self):
        self.service.enroll_existing_customer(self.customer_user, self.staff)
        reward_id = self.service.create_reward(self.owner, 'Lunch discount', 10, '5.00')
        reward = self.service.reward_model(reward_id)
        self.assertTrue(reward.isAvailable())
        self.assertFalse(reward.isEligible(0))
        UUID(reward.publicUUID)
        self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        first = self.service.redeem_reward(self.staff, self.customer_id, self.order(), reward_id)
        second = self.service.redeem_reward(self.staff, self.customer_id, self.order(), reward_id)
        for result in (first, second):
            tx = self.service.transaction_model(result['loyaltyTransactionID'])
            redemption = self.service.redemption_model(tx.transactionID)
            self.assertIsNotNone(redemption)
            self.assertEqual(redemption.status, 'Confirmed')
            self.assertEqual(tx.type, 'EarnAndRedeem')
            self.assertEqual((tx.pointsEarned, tx.pointsRedeemed), (15, 10))
            self.assertEqual(tx.pointsChange, 5)
            UUID(redemption.publicUUID)
            self.assertIsNotNone(redemption.redemptionDate)
            with self.assertRaises(ValueError):
                redemption.cancelRedemption()  # Cannot silently refund earned/spent points.
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM Redemption WHERE rewardID=?',
                                        (reward_id,)).fetchone()[0], 2)

    def test_suspension_preserves_balance_and_history_and_requires_owner(self):
        self.service.enroll_existing_customer(self.customer_user, self.staff)
        self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        before = self.service.retrieve_customer_account(self.customer_id)['pointsBalance']
        with self.assertRaises(LoyaltyError):
            self.service.set_loyalty_account_status(self.staff, self.customer_id, 'Suspended')
        self.service.set_loyalty_account_status(self.owner, self.customer_id, 'Suspended')
        self.assertEqual(self.service.account_model(self.customer_id).status, 'Suspended')
        with self.assertRaises(LoyaltyError):
            self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        self.assertEqual(self.service.retrieve_customer_account(self.customer_id)['pointsBalance'], before)
        self.assertEqual(len(self.service.transaction_history(self.customer_id)), 1)
        self.service.set_loyalty_account_status(self.owner, self.customer_id, 'Active')
        self.service.process_eligible_purchase(self.staff, self.customer_id, self.order())
        self.assertEqual(self.service.account_model(self.customer_id).currentPoints, 40)

    def test_upgrade_older_loyalty_database_non_destructively(self):
        """Old loyalty schema with no UML-alignment columns should still work."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'previous_release.db'
            db = sqlite3.connect(path)
            try:
                db.executescript('''
                    CREATE TABLE "User" (userID INTEGER PRIMARY KEY, name TEXT, email TEXT, username TEXT);
                    CREATE TABLE Customer (customerID INTEGER PRIMARY KEY, userID INTEGER);
                    CREATE TABLE "Order" (orderID INTEGER PRIMARY KEY, orderDate TEXT,
                                          totalAmount REAL, status TEXT, customerID INTEGER);
                    CREATE TABLE LoyaltyAccount (loyaltyAccountID INTEGER PRIMARY KEY,
                              customerID INTEGER NOT NULL UNIQUE, pointsBalance INTEGER NOT NULL DEFAULT 0,
                              joinedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE Reward (rewardID INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                             pointsCost INTEGER NOT NULL, discountAmount REAL NOT NULL,
                             isActive INTEGER NOT NULL DEFAULT 1);
                    CREATE TABLE LoyaltyTransaction (
                        loyaltyTransactionID INTEGER PRIMARY KEY, loyaltyAccountID INTEGER NOT NULL,
                        orderID INTEGER NOT NULL UNIQUE, employeeUserID INTEGER NOT NULL,
                        purchaseAmount REAL NOT NULL, eligibleAmount REAL NOT NULL,
                        discountAmount REAL NOT NULL, finalAmount REAL NOT NULL,
                        pointsEarned INTEGER NOT NULL, pointsRedeemed INTEGER NOT NULL,
                        balanceAfter INTEGER NOT NULL, rewardID INTEGER,
                        createdAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
                    CREATE TABLE Redemption (redemptionID INTEGER PRIMARY KEY,
                        loyaltyTransactionID INTEGER NOT NULL UNIQUE, rewardID INTEGER NOT NULL,
                        pointsUsed INTEGER NOT NULL, discountAmount REAL NOT NULL);
                    INSERT INTO "User" VALUES(1,'Legacy Customer',NULL,NULL);
                    INSERT INTO Customer VALUES(1,1);
                    INSERT INTO LoyaltyAccount(customerID,pointsBalance) VALUES(1,15);
                    INSERT INTO Reward(rewardID,name,pointsCost,discountAmount,isActive)
                        VALUES(1,'Legacy Reward',10,5,1);
                    INSERT INTO "Order" VALUES(1,NULL,20,'Completed',1);
                    INSERT INTO LoyaltyTransaction(loyaltyAccountID,orderID,employeeUserID,
                        purchaseAmount,eligibleAmount,discountAmount,finalAmount,
                        pointsEarned,pointsRedeemed,balanceAfter,rewardID)
                        VALUES(1,1,1,20,20,5,15,15,10,15,1);
                    INSERT INTO Redemption(loyaltyTransactionID,rewardID,pointsUsed,discountAmount)
                        VALUES(1,1,10,5);
                ''')
                db.commit()
            finally:
                db.close()
            initialize(path)
            with connect(path) as upgraded:
                t = upgraded.execute('''SELECT pointsChange,type,transactionDate,publicUUID
                                        FROM LoyaltyTransaction''').fetchone()
                self.assertEqual((t['pointsChange'], t['type']), (5, 'EarnAndRedeem'))
                self.assertIsNotNone(t['transactionDate'])
                UUID(t['publicUUID'])
                r = upgraded.execute('SELECT status,redemptionDate,publicUUID FROM Redemption').fetchone()
                self.assertEqual(r['status'], 'Confirmed')
                self.assertIsNotNone(r['redemptionDate'])
                UUID(r['publicUUID'])
                self.assertEqual(upgraded.execute('SELECT pointsBalance FROM LoyaltyAccount').fetchone()[0], 15)
            initialize(path)
            with connect(path) as again:
                self.assertEqual(again.execute('SELECT COUNT(*) FROM LoyaltyTransaction').fetchone()[0], 1)
                self.assertEqual(again.execute('SELECT COUNT(*) FROM Redemption').fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
