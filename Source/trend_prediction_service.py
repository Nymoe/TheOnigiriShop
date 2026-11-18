"""Read-only sales, ingredient-use and revenue forecasts for shop managers.

Forecasts use the average of the last three dates with recorded activity.
They are simple planning estimates, not automatic purchasing or bookkeeping.
"""

from contextlib import closing
from datetime import date, timedelta
import sqlite3
from statistics import mean

from inventory_db import connect


class BusinessData:
    def __init__(self, data_type, db_path=None):
        self.data_type = data_type
        self.db_path = db_path

    def retrieve_data(self):
        queries = {
            "Sales": '''SELECT substr(orderDate, 1, 10) AS day, COUNT(*) AS amount
                        FROM "Order" WHERE status='Completed' AND orderDate IS NOT NULL
                        GROUP BY substr(orderDate, 1, 10) ORDER BY day''',
            # The original menu-price total remains in Order. A loyalty purchase
            # stores the actual discounted total in LoyaltyTransaction. The
            # forecast uses that net value, matching the automatically posted
            # order Sale, without counting manually entered ledger Sales twice.
            "Financial": '''SELECT substr(o.orderDate, 1, 10) AS day,
                                   SUM(COALESCE(lt.finalAmount, o.totalAmount)) AS amount
                            FROM "Order" o
                            LEFT JOIN LoyaltyTransaction lt ON lt.orderID=o.orderID
                            WHERE o.status='Completed' AND o.orderDate IS NOT NULL
                              AND o.totalAmount > 0
                            GROUP BY substr(o.orderDate, 1, 10) ORDER BY day''',
        }
        if self.data_type not in queries:
            raise ValueError('Unknown trend type.')
        with closing(connect(self.db_path)) as db:
            records = db.execute(queries[self.data_type]).fetchall()
        history = []
        for row in records:
            try:
                day = date.fromisoformat(row['day'])
            except (ValueError, TypeError):
                continue
            history.append({'date': day.isoformat(), 'value': float(row['amount'])})
        return history


class IngredientData:
    """Read actual recipe ingredient consumption from completed orders."""

    def __init__(self, ingredient_id, db_path=None):
        self.ingredient_id = ingredient_id
        self.db_path = db_path
        self.data_type = 'Inventory'

    @staticmethod
    def list_ingredients(db_path=None):
        with closing(connect(db_path)) as db:
            return db.execute('''SELECT ingredientID, ingredientName, quantityOnHand,
                                        reorderLevel, unit FROM InventoryItem
                                 ORDER BY ingredientName, ingredientID''').fetchall()

    def retrieve_data(self):
        with closing(connect(self.db_path)) as db:
            rows = db.execute('''
                SELECT substr(transactionDate, 1, 10) AS day,
                       SUM(-quantity) AS amount
                FROM InventoryTransaction
                WHERE ingredientID = ? AND transactionType = 'Customer Order'
                  AND quantity < 0 AND transactionDate IS NOT NULL
                GROUP BY substr(transactionDate, 1, 10)
                ORDER BY day
            ''', (self.ingredient_id,)).fetchall()
        history = []
        for row in rows:
            try:
                day = date.fromisoformat(row['day'])
            except (ValueError, TypeError):
                continue
            history.append({'date': day.isoformat(), 'value': float(row['amount'])})
        return history


class TrendPrediction:
    MIN_OBSERVATIONS = 3

    def __init__(self, business_data):
        self.business_data = business_data
        self.trend_type = business_data.data_type
        self.predicted_value = None
        self.prediction_date = None

    def generate_trend(self, history=None):
        history = self.business_data.retrieve_data() if history is None else history
        if len(history) < self.MIN_OBSERVATIONS:
            return None
        previous = mean(item['value'] for item in history[-3:-1])
        latest = history[-1]['value']
        return 'Increasing' if latest > previous else 'Decreasing' if latest < previous else 'Stable'

    def generate_prediction(self, history=None):
        history = self.business_data.retrieve_data() if history is None else history
        if len(history) < self.MIN_OBSERVATIONS:
            self.predicted_value = None
            self.prediction_date = None
            return None
        self.predicted_value = round(mean(item['value'] for item in history[-3:]), 2)
        self.prediction_date = (date.fromisoformat(history[-1]['date']) + timedelta(days=1)).isoformat()
        return self.predicted_value


def plot_prediction_chart(history, prediction, *, title, ylabel):
    """Open a line chart for historical activity and its next-day estimate.

    The rest of the shop works without Matplotlib; charts are an optional desktop
    feature, loaded only after the user requests a completed trend analysis.
    """
    if not history or prediction.prediction_date is None or prediction.predicted_value is None:
        return False
    try:
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        print('  Graph unavailable: Matplotlib is not installed.')
        print('  Install it with: py -m pip install matplotlib  (Windows), '
              'or python3 -m pip install matplotlib (macOS/Linux).')
        return False

    figure = None
    try:
        dates = [date.fromisoformat(item['date']) for item in history]
        values = [item['value'] for item in history]
        forecast_day = date.fromisoformat(prediction.prediction_date)
        forecast = prediction.predicted_value
        trend = prediction.generate_trend(history)
        trend_color = {'Increasing': '#238b45', 'Decreasing': '#d97706',
                       'Stable': '#2563eb'}.get(trend, '#2563eb')

        figure, axis = plt.subplots(figsize=(9, 5))
        axis.plot(dates, values, color='#2563eb', marker='o', linewidth=2,
                  label='Recorded activity')
        axis.plot([dates[-1], forecast_day], [values[-1], forecast],
                  color=trend_color, marker='D', linestyle='--', linewidth=2,
                  label='Next-day estimate')
        axis.annotate(f'{forecast:,.2f}', (forecast_day, forecast),
                      xytext=(8, 10), textcoords='offset points', color=trend_color)
        axis.set_title(f'{title} — {trend} trend')
        axis.set_xlabel('Date')
        axis.set_ylabel(ylabel)
        axis.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        axis.grid(True, alpha=0.25)
        axis.legend(loc='best')
        figure.autofmt_xdate()
        figure.tight_layout()

        backend = plt.get_backend().lower()
        if backend in {'agg', 'pdf', 'ps', 'svg', 'cairo', 'template'} or 'inline' in backend:
            print(f'  Matplotlib is using the non-interactive {backend} backend; '
                  'it cannot open a graph window here.')
            print('  Run the application in a desktop Python session with a GUI '
                  'backend (such as TkAgg or QtAgg) to display the chart.')
            return False
        print('  Opening the trend graph. Close its window to continue in the menu.')
        plt.show(block=True)
        return True
    except (OSError, RuntimeError, ValueError, TypeError, ImportError) as exc:
        print(f'  Could not open the trend graph: {exc}')
        print('  The forecast above is still available. Check your Matplotlib '
              'installation and desktop display settings.')
        return False
    finally:
        if figure is not None:
            plt.close(figure)


class TrendPredictingDashboard:
    LABELS = {
        'Sales': 'completed orders',
        'Inventory': 'units consumed',
        'Financial': 'CAD in net order revenue (not profit)',
    }

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.selected_type = 'Sales'

    @staticmethod
    def _pause():
        input('\nPress Enter to return to the trend dashboard...')

    def display_history(self, history, data_type):
        print(f'\nHistorical {data_type.lower()} data:')
        if not history:
            print('No historical records available. Complete orders under options 1 or 2 first.')
        for item in history:
            print(f"  {item['date']}: {item['value']:,.2f} {self.LABELS[data_type]}")

    def display_trends(self, prediction, history):
        print('Trend:', prediction.generate_trend(history) or 'Unavailable (insufficient history)')

    def display_prediction(self, prediction, history):
        value = prediction.generate_prediction(history)
        if value is None:
            print('Prediction unavailable: at least 3 recorded dates are required.')
        else:
            print(f'Estimate for the day after the last recorded date '
                  f'({prediction.prediction_date}): {value:,.2f} '
                  f'{self.LABELS[prediction.trend_type]}')
            print('Method: average of the last 3 recorded dates; illustrative only.')
            print('Dates without recorded activity are not assumed to be zero.')
            titles = {'Sales': 'Completed Orders', 'Financial': 'Net Order Revenue'}
            units = {'Sales': 'Number of orders', 'Financial': 'Revenue (CAD)'}
            plot_prediction_chart(history, prediction,
                                  title=titles[prediction.trend_type],
                                  ylabel=units[prediction.trend_type])

    def run_inventory(self):
        try:
            ingredients = IngredientData.list_ingredients(self.db_path)
        except (sqlite3.Error, OSError, ValueError) as exc:
            print(f'Unable to read inventory: {exc}. Check the database and restart.')
            return
        if not ingredients:
            print('No ingredients yet. Add inventory from main menu option 8 first.')
            return
        while True:
            print('\n=== Ingredient Forecasting ===')
            for index, item in enumerate(ingredients, 1):
                print(f"{index}. {item['ingredientName']} ({item['unit'] or 'unit'})")
            print('0. Return to trend dashboard (or leave blank)')
            choice = input('Select ingredient: ').strip().lower()
            if choice in ('', '0', 'q'):
                return
            if not choice.isdigit() or not 1 <= int(choice) <= len(ingredients):
                print('Invalid selection. Choose an ingredient number, or leave blank to return.')
                continue
            item = ingredients[int(choice) - 1]
            unit = item['unit'] or 'unit'
            source = IngredientData(item['ingredientID'], self.db_path)
            try:
                history = source.retrieve_data()
            except (sqlite3.Error, OSError, ValueError) as exc:
                print(f'Unable to read ingredient consumption: {exc}. Check inventory transaction history.')
                self._pause()
                continue
            print(f"\n=== {item['ingredientName']} Forecast ===")
            stock = float(item['quantityOnHand'] or 0)
            reorder = float(item['reorderLevel'] or 0)
            print(f'Current stock: {stock:,.2f} {unit}')
            print(f'Reorder level: {reorder:,.2f} {unit}')
            if not history:
                print('No customer-order consumption recorded for this ingredient yet.')
                print('Complete an order for a recipe containing it (main menu option 1 or 2).')
                self._pause()
                continue
            print('Historical consumption:')
            for entry in history:
                print(f"  {entry['date']}: {entry['value']:,.2f} {unit}")
            average = mean(entry['value'] for entry in history)
            print(f'Average per recorded consumption day: {average:,.2f} {unit}')
            if len(history) < TrendPrediction.MIN_OBSERVATIONS:
                print('At least 3 distinct consumption dates are needed for forecasting.')
                self._pause()
                continue
            prediction = TrendPrediction(source)
            daily = prediction.generate_prediction(history)
            print(f'Trend: {prediction.generate_trend(history)}')
            print(f'Next recorded-day estimate: {daily:,.2f} {unit}')
            print(f'7-day estimate (assuming daily use): {daily * 7:,.2f} {unit}')
            if daily > 0:
                print(f'Estimated stock coverage: {stock / daily:.1f} days (assuming daily use)')
                if stock < daily * 7:
                    print('Recommendation: stock may be insufficient for 7 days; consider replenishment.')
                elif stock <= reorder:
                    print('Recommendation: current stock is at or below reorder level.')
                else:
                    print('Stock appears sufficient for 7 days at the estimated rate.')
            print('Note: the last 3 dates with recorded consumption are used, not a calendar-day average.')
            plot_prediction_chart(history, prediction,
                                  title=f"{item['ingredientName']} Consumption",
                                  ylabel=f'{unit} consumed')
            self._pause()

    def run(self):
        while True:
            print('\n=== Trend Predicting Dashboard ===')
            print('1. Sales (completed order count)')
            print('2. Inventory (forecast by ingredient)')
            print('3. Financial (net completed-order revenue)')
            print('0. Return to main menu (or leave blank)')
            selection = input('Choose an option: ').strip().lower()
            if selection in ('', '0', 'q'):
                return
            options = {'1': 'Sales', '2': 'Inventory', '3': 'Financial'}
            if selection not in options:
                print('Invalid selection. Choose 0-3 or leave blank to return.')
                continue
            self.selected_type = options[selection]
            if self.selected_type == 'Inventory':
                self.run_inventory()
                continue
            source = BusinessData(self.selected_type, self.db_path)
            try:
                history = source.retrieve_data()
            except (sqlite3.Error, OSError, ValueError) as exc:
                print(f'Unable to retrieve business data: {exc}. Check the saved order history.')
                self._pause()
                continue
            self.display_history(history, self.selected_type)
            if len(history) < TrendPrediction.MIN_OBSERVATIONS:
                print('At least 3 distinct dates with records are required for a forecast.')
            elif input('Proceed with trend analysis? (y/n, blank cancels): ').strip().lower() != 'y':
                print('Analysis cancelled.')
            else:
                prediction = TrendPrediction(source)
                self.display_trends(prediction, history)
                self.display_prediction(prediction, history)
            self._pause()
