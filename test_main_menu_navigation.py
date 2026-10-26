"""Main-menu option routing after grouping the shop's management features."""
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from inventory_cli import menu
from inventory_service import InventoryService


class MainMenuNavigationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.shop = InventoryService(Path(folder.name) / 'shop.db')
        self.shop.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.shop.create_user('Customer', 'customer', 'customer-password', 'Customer')

    def test_all_staff_options_reach_the_correct_feature(self):
        handler_names = (
            'order_create', 'orders_menu', 'edit_recipe', 'recipes_menu',
            'loyalty_staff_menu', 'feedback_menu', 'inventory_view',
            'create_ingredient', 'adjustment', 'set_reorder', 'alerts_menu',
            'purchase_create', 'purchase_menu', 'delivery', 'suppliers_menu',
            'transaction_history', 'payroll_menu', 'accounting_menu',
            'TrendPredictingDashboard', 'employees_menu', 'demo_menu',
            'profile_menu',
        )
        owner = self.shop.login('owner', 'owner-password')
        output = StringIO()
        with ExitStack() as stack:
            handlers = {name: stack.enter_context(patch('inventory_cli.' + name))
                        for name in handler_names}
            stack.enter_context(patch('inventory_cli.prompt',
                                     side_effect=[*(str(i) for i in range(1, 24))]))
            stack.enter_context(patch('builtins.input', return_value=''))
            with redirect_stdout(output):
                self.assertIsNone(menu(self.shop, owner))

        for name in handler_names:
            with self.subTest(feature=name):
                handlers[name].assert_called_once()
        handlers['TrendPredictingDashboard'].return_value.run.assert_called_once_with()
        rendered = output.getvalue()
        for category in ('ORDERS & CUSTOMERS', 'INVENTORY & PURCHASING',
                         'MANAGEMENT & REPORTING', 'ACCOUNT'):
            self.assertIn(category, rendered)
        self.assertIn('22. My Profile', rendered)
        self.assertIn('23. Log out', rendered)
        self.assertIn('0. Exit', rendered)
        self.assertLess(rendered.index('22. My Profile'), rendered.index('23. Log out'))

    def test_customer_options_and_access_restrictions_follow_new_numbers(self):
        customer = self.shop.login('customer', 'customer-password')
        output = StringIO()
        with patch('inventory_cli.prompt', side_effect=['20', '5', '6', '22', '23']), \
             patch('inventory_cli.loyalty_customer_menu') as loyalty, \
             patch('inventory_cli.feedback_menu') as feedback, \
             patch('inventory_cli.profile_menu') as profile, \
             patch('inventory_cli.employees_menu') as staff_only, \
             patch('builtins.input', return_value=''), redirect_stdout(output):
            self.assertIsNone(menu(self.shop, customer))
        loyalty.assert_called_once()
        feedback.assert_called_once()
        profile.assert_called_once()
        staff_only.assert_not_called()
        self.assertIn('Customer inventory administration is not available', output.getvalue())
        self.assertIn('23. Log out', output.getvalue())


if __name__ == '__main__':
    unittest.main()
