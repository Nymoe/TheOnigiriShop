"""Trend dashboard calculations, historical-data handling and menu integration."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from accounting_service import AccountingLedger, AccountingTransaction
from inventory_cli import menu
from inventory_db import connect
from inventory_service import InventoryService
from loyalty_service import LoyaltyService
from trend_prediction_service import (
    BusinessData, IngredientData, TrendPrediction, TrendPredictingDashboard,
    plot_prediction_chart,
)


class TrendDashboardTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'shop.db'
        self.shop = InventoryService(self.path)
        self.owner = self.shop.create_user('Owner', 'owner', 'owner-password', 'Owner')
        self.rice = self.shop.add_ingredient('Rice', 'g', 2000, 200, self.owner)
        self.recipe = self.shop.add_recipe('Rice ball', 10)
        self.shop.set_recipe_ingredient(self.recipe, self.rice, 20)

    def create_order(self, recorded_date, servings=1):
        # Simulate three days using real order and inventory services.
        with patch('inventory_service._today', return_value=recorded_date + 'T12:00:00'), \
             patch('inventory_service._date_today', return_value=recorded_date):
            order = self.shop.create_customer_order({self.recipe: servings}, self.owner)
            self.shop.complete_customer_order(order, self.owner)
        return order

    def test_pending_and_manual_stock_movements_do_not_count_as_sales_or_consumption(self):
        self.shop.create_customer_order({self.recipe: 2}, self.owner)
        self.shop.adjust_stock(self.rice, 'remove', 10, self.owner, 'Spoiled')
        self.assertEqual(BusinessData('Sales', self.path).retrieve_data(), [])
        self.assertEqual(BusinessData('Financial', self.path).retrieve_data(), [])
        self.assertEqual(IngredientData(self.rice, self.path).retrieve_data(), [])

    def test_completed_orders_aggregate_by_date_and_forecast_three_recorded_days(self):
        self.create_order('2026-10-19', servings=1)
        self.create_order('2026-10-20', servings=2)
        self.create_order('2026-10-20', servings=1)
        self.create_order('2026-10-21', servings=3)
        sales = BusinessData('Sales', self.path)
        revenue = BusinessData('Financial', self.path)
        consumption = IngredientData(self.rice, self.path)
        self.assertEqual([r['value'] for r in sales.retrieve_data()], [1, 2, 1])
        self.assertEqual([r['value'] for r in revenue.retrieve_data()], [10, 30, 30])
        self.assertEqual([r['value'] for r in consumption.retrieve_data()], [20, 60, 60])
        prediction = TrendPrediction(sales)
        self.assertEqual(prediction.generate_trend(), 'Decreasing')
        self.assertEqual(prediction.generate_prediction(), 1.33)
        self.assertEqual(prediction.prediction_date, '2026-10-22')
        self.assertEqual(TrendPrediction(consumption).generate_prediction(), 46.67)

    def test_financial_forecast_uses_net_loyalty_amount_without_duplicate_manual_sales(self):
        self.create_order('2026-10-19')
        customer = self.shop.create_user('Customer', 'customer', 'customer-pass', 'Customer')
        loyalty = LoyaltyService(self.path)
        loyalty.enroll_existing_customer(customer, self.owner)
        customer_id = loyalty.customer_id_for_user(customer)
        reward = loyalty.create_reward(self.owner, 'Discount', 10, 5)
        with patch('inventory_service._today', return_value='2026-10-20T12:00:00'), \
             patch('inventory_service._date_today', return_value='2026-10-20'):
            earning = self.shop.create_customer_order({self.recipe: 2}, self.owner, customer_id)
            loyalty.complete_order_with_loyalty(self.owner, customer_id, earning)
        order = self.shop.create_customer_order({self.recipe: 1}, self.owner, customer_id)
        self.shop.complete_customer_order(order, self.owner)
        loyalty.process_eligible_purchase(self.owner, customer_id, order, reward_id=reward)
        with connect(self.path) as db:
            db.execute('UPDATE "Order" SET orderDate=? WHERE orderID=?',
                       ('2026-10-21', order))
            db.commit()
        ledger = AccountingLedger(self.path)
        ledger.addTransaction(AccountingTransaction(None, 'Sale', '2026-10-21',
                                                   'External manual sale', 'EXT-1', 100))
        financial = BusinessData('Financial', self.path).retrieve_data()
        self.assertEqual([r['value'] for r in financial], [10, 20, 5])
        self.assertEqual(TrendPrediction(BusinessData('Financial', self.path))
                         .generate_prediction(), 11.67)
        self.assertEqual(ledger.calculateSummary().totalSales, 135)

    def test_fully_discounted_order_is_zero_revenue_but_still_one_completed_sale_count(self):
        customer = self.shop.create_user('Customer', 'customer', 'customer-pass', 'Customer')
        loyalty = LoyaltyService(self.path)
        loyalty.enroll_existing_customer(customer, self.owner)
        customer_id = loyalty.customer_id_for_user(customer)
        reward = loyalty.create_reward(self.owner, 'Full reward', 10, 10)
        earning = self.shop.create_customer_order({self.recipe: 2}, self.owner, customer_id)
        loyalty.complete_order_with_loyalty(self.owner, customer_id, earning)
        order = self.shop.create_customer_order({self.recipe: 1}, self.owner, customer_id)
        loyalty.complete_order_with_loyalty(self.owner, customer_id, order, reward_id=reward)
        sales = BusinessData('Sales', self.path).retrieve_data()
        revenue = BusinessData('Financial', self.path).retrieve_data()
        self.assertEqual(sum(r['value'] for r in sales), 2)
        self.assertEqual(sum(r['value'] for r in revenue), 20)

    def test_insufficient_history_is_explained_and_paused_without_database_mutation(self):
        self.create_order('2026-10-19')
        with connect(self.path) as db:
            original = db.execute('SELECT COUNT(*) FROM AccountingTransaction').fetchone()[0]
        with patch('builtins.input', side_effect=['1', '', '0']), redirect_stdout(StringIO()) as output:
            TrendPredictingDashboard(self.path).run()
        self.assertIn('At least 3 distinct dates', output.getvalue())
        with connect(self.path) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM AccountingTransaction').fetchone()[0], original)

    def test_no_inventory_consumption_and_blank_ingredient_escape(self):
        with patch('builtins.input', side_effect=['2', '1', '', '', '0']), \
             redirect_stdout(StringIO()) as output:
            TrendPredictingDashboard(self.path).run()
        self.assertIn('Complete an order for a recipe containing it', output.getvalue())

    def test_dashboard_forecast_result_remains_until_enter(self):
        for day in ('2026-10-19', '2026-10-20', '2026-10-21'):
            self.create_order(day)
        with patch('builtins.input', side_effect=['3', 'y', '', '0']), \
             patch('trend_prediction_service.plot_prediction_chart') as graph, \
             redirect_stdout(StringIO()) as output:
            TrendPredictingDashboard(self.path).run()
        self.assertIn('10.00 CAD in net order revenue', output.getvalue())
        self.assertIn('2026-10-22', output.getvalue())
        self.assertEqual(graph.call_count, 1)
        self.assertEqual(graph.call_args.kwargs['title'], 'Net Order Revenue')

    def test_sales_analysis_opens_history_and_forecast_graph(self):
        for day in ('2026-10-19', '2026-10-20', '2026-10-21'):
            self.create_order(day)
        with patch('builtins.input', side_effect=['1', 'y', '', '0']), \
             patch('trend_prediction_service.plot_prediction_chart') as graph, \
             redirect_stdout(StringIO()):
            TrendPredictingDashboard(self.path).run()
        self.assertEqual(graph.call_count, 1)
        self.assertEqual(graph.call_args.kwargs['title'], 'Completed Orders')

    def test_inventory_screen_calculates_coverage_and_pauses(self):
        for day, servings in (('2026-10-19', 1), ('2026-10-20', 2), ('2026-10-21', 3)):
            self.create_order(day, servings)
        with patch('builtins.input', side_effect=['2', '1', '', '', '0']), \
             patch('trend_prediction_service.plot_prediction_chart') as graph, \
             redirect_stdout(StringIO()) as output:
            TrendPredictingDashboard(self.path).run()
        self.assertIn('Next recorded-day estimate: 40.00 g', output.getvalue())
        self.assertIn('7-day estimate (assuming daily use): 280.00 g', output.getvalue())
        self.assertIn('Estimated stock coverage: 47.0 days', output.getvalue())
        self.assertEqual(graph.call_count, 1)
        self.assertEqual(graph.call_args.kwargs['ylabel'], 'g consumed')

    def test_missing_matplotlib_does_not_interrupt_the_forecast(self):
        history = [{'date': '2026-10-19', 'value': 1},
                   {'date': '2026-10-20', 'value': 2},
                   {'date': '2026-10-21', 'value': 3}]
        prediction = TrendPrediction(BusinessData('Sales', self.path))
        prediction.generate_prediction(history)
        with patch.dict(sys.modules, {'matplotlib': None, 'matplotlib.pyplot': None,
                                      'matplotlib.dates': None}), redirect_stdout(StringIO()) as output:
            shown = plot_prediction_chart(history, prediction,
                                          title='Completed Orders', ylabel='Number of orders')
        self.assertFalse(shown)
        self.assertIn('pip install matplotlib', output.getvalue())

    def test_matplotlib_graph_has_historical_and_forecast_lines(self):
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            self.skipTest('Matplotlib not installed in the test environment')
        history = [{'date': '2026-10-19', 'value': 1},
                   {'date': '2026-10-20', 'value': 2},
                   {'date': '2026-10-21', 'value': 3}]
        prediction = TrendPrediction(BusinessData('Sales', self.path))
        prediction.generate_prediction(history)
        with patch.object(plt, 'get_backend', return_value='TkAgg'), \
             patch.object(plt, 'show') as show, patch.object(plt, 'close') as close, \
             redirect_stdout(StringIO()):
            shown = plot_prediction_chart(history, prediction,
                                          title='Completed Orders', ylabel='Number of orders')
        self.assertTrue(shown)
        show.assert_called_once_with(block=True)
        figure = close.call_args.args[0]
        self.assertEqual(len(figure.axes[0].lines), 2)
        self.assertEqual(len(figure.axes[0].lines[0].get_xdata()), 3)
        self.assertEqual(len(figure.axes[0].lines[1].get_xdata()), 2)
        plt.close(figure)

    def test_empty_inventory_explains_setup_requirement(self):
        with connect(self.path) as db:
            db.execute('DELETE FROM RecipeIngredient')
            db.execute('DELETE FROM InventoryTransaction')
            db.execute('DELETE FROM InventoryAdjustment')
            db.execute('DELETE FROM InventoryItem')
            db.commit()
        with patch('builtins.input', side_effect=['2', '0']), redirect_stdout(StringIO()) as out:
            TrendPredictingDashboard(self.path).run()
        self.assertIn('Add inventory from main menu option 8 first', out.getvalue())

    def test_main_menu_routes_trend_dashboard_after_renumbering(self):
        owner = self.shop.login('owner', 'owner-password')
        with patch('inventory_cli.prompt', side_effect=['19', '23']), \
             patch('inventory_cli.TrendPredictingDashboard') as dashboard, \
             patch('builtins.input', return_value=''), redirect_stdout(StringIO()) as output:
            menu(self.shop, owner)
        dashboard.assert_called_once_with(self.path)
        dashboard.return_value.run.assert_called_once_with()
        self.assertIn('18. Accounting Ledger (Owner)', output.getvalue())
        self.assertIn('19. Trend Predicting Dashboard', output.getvalue())

    def test_employee_can_use_dashboard_but_customer_cannot_open_staff_menu(self):
        self.shop.create_user('Employee', 'employee', 'employee-password', 'Employee')
        employee = self.shop.login('employee', 'employee-password')
        with patch('inventory_cli.prompt', side_effect=['19', '23']), \
             patch('inventory_cli.TrendPredictingDashboard') as dashboard, \
             patch('builtins.input', return_value=''), redirect_stdout(StringIO()):
            menu(self.shop, employee)
        dashboard.assert_called_once_with(self.path)

        self.shop.create_user('Customer', 'customer', 'customer-pass', 'Customer')
        customer = self.shop.login('customer', 'customer-pass')
        with patch('inventory_cli.prompt', side_effect=['19', '23']), \
             patch('inventory_cli.TrendPredictingDashboard') as blocked, \
             redirect_stdout(StringIO()) as output:
            menu(self.shop, customer)
        blocked.assert_not_called()
        self.assertIn('Customer inventory administration is not available', output.getvalue())


if __name__ == '__main__':
    unittest.main()
