"""Sample reward catalogue: appears in option 19 but does not preload user accounts."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from inventory_db import connect
from inventory_cli import loyalty_customer_menu, loyalty_staff_menu
from inventory_service import InventoryService
from loyalty_service import LoyaltyService, SAMPLE_REWARDS


class SampleRewardTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'test.db'
        self.inventory = InventoryService(self.path)
        self.loyalty = LoyaltyService(self.path)
        self.owner = self.inventory.create_user('Original Owner', 'my-own-owner',
                                                'own-password', 'Owner')
        self.customer_user = self.inventory.create_user('New Customer', 'my-own-customer',
                                                        'own-customer-password', 'Customer')

    def test_reward_examples_load_only_when_loyalty_menu_opens(self):
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Reward').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM DemoUserImport').fetchone()[0], 0)
        with redirect_stdout(StringIO()) as out, patch('builtins.input', side_effect=['6', '', '0']):
            loyalty_staff_menu(self.loyalty, {'userID': self.owner, 'role': 'Owner'})
        shown = out.getvalue()
        for name, points, discount in SAMPLE_REWARDS:
            self.assertIn(name, shown)
        self.assertEqual([(r['name'], r['pointsCost'], r['discountAmount'])
                          for r in self.loyalty.rewards()],
                         [(name, points, float(discount)) for name, points, discount in SAMPLE_REWARDS])
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM DemoUserImport').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM LoyaltyAccount').fetchone()[0], 0)

    def test_customer_can_view_reward_examples_with_balance_and_history(self):
        with redirect_stdout(StringIO()) as out, patch('builtins.input', side_effect=['y']):
            loyalty_customer_menu(self.loyalty, {'userID': self.customer_user, 'role': 'Customer'})
        self.assertIn('$5 Discount', out.getvalue())
        self.assertIn('1000', out.getvalue())
        self.assertIn('Current balance: 0 points', out.getvalue())
        self.assertEqual(len(self.loyalty.rewards()), 4)

    def test_reopening_preserves_manual_changes_and_deactivated_examples(self):
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 4)
        first = self.loyalty.rewards(active_only=False)
        self.loyalty.set_reward_active(self.owner, first[0]['rewardID'], False)
        with connect(self.path) as db:
            db.execute('UPDATE Reward SET pointsCost=550 WHERE rewardID=?', (first[1]['rewardID'],))
            db.commit()
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 0)
        rows = self.loyalty.rewards(active_only=False)
        self.assertEqual(len(rows), 4)
        by_name = {r['name']: r for r in rows}
        original_by_name = {r['name']: r for r in first}
        self.assertEqual(by_name['$5 Discount']['isActive'], 0)
        self.assertEqual(by_name['$10 Discount']['pointsCost'], 550)
        self.assertEqual({name: r['publicUUID'] for name, r in by_name.items()},
                         {name: r['publicUUID'] for name, r in original_by_name.items()})

    def test_preexisting_custom_reward_is_left_unchanged(self):
        rid = self.loyalty.create_reward(self.owner, '$10 Discount', 750, '10.00')
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 3)
        rows = self.loyalty.rewards()
        self.assertEqual(len(rows), 4)
        existing = next(r for r in rows if r['name'] == '$10 Discount')
        self.assertEqual((existing['rewardID'], existing['pointsCost']), (rid, 750))

    def test_failure_rolls_back_all_sample_rewards(self):
        with connect(self.path) as db:
            db.execute('''CREATE TRIGGER reject_sample BEFORE INSERT ON Reward
                          WHEN NEW.name='$15 Discount'
                          BEGIN SELECT RAISE(ABORT, 'simulated write error'); END''')
            db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.loyalty.ensure_sample_rewards()
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM Reward').fetchone()[0], 0)

    def test_updated_earning_rate_and_5_percent_value(self):
        self.assertEqual(self.loyalty.points_per_dollar, 10)
        self.assertEqual(self.loyalty.calculate_points_earned('1'), 10)
        self.assertEqual(self.loyalty.calculate_points_earned('10'), 100)
        self.assertEqual(self.loyalty.calculate_points_earned('9.99'), 99)
        self.assertEqual(self.loyalty.calculate_points_earned('0.01'), 0)
        self.assertEqual(SAMPLE_REWARDS, (
            ('$5 Discount', 1000, '5.00'), ('$10 Discount', 2000, '10.00'),
            ('$15 Discount', 3000, '15.00'), ('$20 Discount', 4000, '20.00'),
        ))

    def test_legacy_sample_reward_costs_are_migrated_in_place(self):
        old = (('$5 Discount', 500, 5), ('$10 Discount', 1000, 10),
               ('$15 Discount', 1500, 15), ('$20 Discount', 2000, 20))
        with connect(self.path) as db:
            for name, cost, discount in old:
                db.execute('INSERT INTO Reward(name,pointsCost,discountAmount) VALUES(?,?,?)',
                           (name, cost, discount))
            db.commit()
        original_ids = {r['name']: r['rewardID'] for r in self.loyalty.rewards()}
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 0)
        self.assertEqual({r['name']: (r['rewardID'], r['pointsCost'])
                          for r in self.loyalty.rewards()},
                         {name: (original_ids[name], points)
                          for name, points, _ in SAMPLE_REWARDS})
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 0)
        self.assertEqual(len(self.loyalty.rewards()), 4)

    def test_custom_and_inactive_legacy_rewards_keep_their_prices(self):
        with connect(self.path) as db:
            db.execute('INSERT INTO Reward(name,pointsCost,discountAmount,isActive) '
                       'VALUES(?, ?, ?, ?)', ('$5 Discount', 500, 5, 0))
            db.execute('INSERT INTO Reward(name,pointsCost,discountAmount,isActive) '
                       'VALUES(?, ?, ?, ?)', ('$10 Discount', 550, 10, 1))
            db.execute('INSERT INTO Reward(name,pointsCost,discountAmount,isActive) '
                       'VALUES(?, ?, ?, ?)', ('$15 Discount', 1500, 14, 1))
            db.commit()
        self.assertEqual(self.loyalty.ensure_sample_rewards(), 1)
        rewards = {r['name']: r for r in self.loyalty.rewards(active_only=False)}
        self.assertEqual((rewards['$5 Discount']['pointsCost'], rewards['$5 Discount']['isActive']), (500, 0))
        self.assertEqual(rewards['$10 Discount']['pointsCost'], 550)
        self.assertEqual(rewards['$15 Discount']['pointsCost'], 1500)
        self.assertEqual(rewards['$20 Discount']['pointsCost'], 4000)

    def test_failed_legacy_migration_rolls_back_every_change(self):
        with connect(self.path) as db:
            for name, points, money in (('$5 Discount', 500, 5), ('$10 Discount', 1000, 10)):
                db.execute('INSERT INTO Reward(name,pointsCost,discountAmount) VALUES(?,?,?)',
                           (name, points, money))
            db.execute("CREATE TRIGGER fail_sample_migration BEFORE UPDATE ON Reward "
                       "WHEN NEW.name='$10 Discount' "
                       "BEGIN SELECT RAISE(ABORT, 'simulated migration error'); END")
            db.commit()
        with self.assertRaises(sqlite3.DatabaseError):
            self.loyalty.ensure_sample_rewards()
        with connect(self.path) as db:
            rows = [(r['name'], r['pointsCost']) for r in db.execute(
                'SELECT name,pointsCost FROM Reward ORDER BY rewardID')]
            self.assertEqual(rows, [('$5 Discount', 500), ('$10 Discount', 1000)])

    def test_example_reward_can_be_redeemed_for_exact_points(self):
        self.loyalty.ensure_sample_rewards()
        self.loyalty.enroll_existing_customer(self.customer_user, self.customer_user)
        customer_id = self.loyalty.customer_id_for_user(self.customer_user)
        ingredient = self.inventory.add_ingredient('Rice', 'g', 1000, 100, self.owner)
        recipe = self.inventory.add_recipe('Sample Rice Ball', 10)
        self.inventory.set_recipe_ingredient(recipe, ingredient, 10)
        expensive_order = self.inventory.create_customer_order({recipe: 10}, self.owner)
        self.inventory.complete_customer_order(expensive_order, self.owner)
        earned = self.loyalty.process_eligible_purchase(self.owner, customer_id, expensive_order)
        self.assertEqual(earned['balanceAfter'], 1000)
        reward_id = next(r['rewardID'] for r in self.loyalty.rewards() if r['pointsCost'] == 1000)
        small_order = self.inventory.create_customer_order({recipe: 1}, self.owner)
        self.inventory.complete_customer_order(small_order, self.owner)
        redeemed = self.loyalty.redeem_reward(self.owner, customer_id, small_order, reward_id)
        self.assertEqual((redeemed['pointsRedeemed'], redeemed['pointsEarned'],
                          redeemed['discountAmount'], redeemed['finalAmount'], redeemed['balanceAfter']),
                         (1000, 50, 5.0, 5.0, 50))


if __name__ == '__main__':
    unittest.main()
