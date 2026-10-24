
from datetime import date, timedelta
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
            "Financial": '''SELECT substr(orderDate, 1, 10) AS day, SUM(totalAmount) AS amount
                            FROM "Order" WHERE status='Completed' AND orderDate IS NOT NULL
                            AND totalAmount IS NOT NULL
                            GROUP BY substr(orderDate, 1, 10) ORDER BY day''',
            "Inventory": '''SELECT substr(transactionDate, 1, 10) AS day, COUNT(*) AS amount
                            FROM InventoryTransaction WHERE transactionType='Customer Order'
                            AND quantity < 0 AND transactionDate IS NOT NULL
                            GROUP BY substr(transactionDate, 1, 10) ORDER BY day''',
        }
        if self.data_type not in queries:
            raise ValueError("Unknown trend type")
        db = connect(self.db_path)
        try:
            records = db.execute(queries[self.data_type]).fetchall()
        finally:
            db.close()
        history = []
        for row in records:
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


class TrendPredictingDashboard:
    LABELS = {
        'Sales': 'completed orders',
        'Inventory': 'ingredient consumption events',
        'Financial': 'CAD revenue (not profit)',
    }

    def __init__(self, db_path=None):
        self.db_path = db_path
        self.selected_type = 'Sales'

    def display_history(self, history, data_type):
        print(f"\nHistorical {data_type.lower()} data:")
        if not history:
            print('No historical records available.')
        for item in history:
            print(f"  {item['date']}: {item['value']:,.2f} {self.LABELS[data_type]}")

    def display_trends(self, prediction, history):
        print('Trend:', prediction.generate_trend(history) or 'Unavailable (insufficient history)')

    def display_prediction(self, prediction, history):
        value = prediction.generate_prediction(history)
        if value is None:
            print('Prediction unavailable: at least 3 recorded dates are required.')
        else:
            print(f'Forecast for {prediction.prediction_date}: {value:,.2f} '
                  f'{self.LABELS[prediction.trend_type]}')
            print('Method: average of the last 3 recorded dates; illustrative only.')

    def run(self):
        while True:
            print('\n=== Trend Predicting Dashboard ===')
            print('1. Sales (completed order count)')
            print('2. Inventory (consumption transaction count)')
            print('3. Financial (completed-order revenue)')
            print('0. Return to main menu')
            selection = input('Choose an option: ').strip().lower()
            if selection in ('0', 'q'):
                return
            options = {'1': 'Sales', '2': 'Inventory', '3': 'Financial'}
            if selection not in options:
                print('Invalid selection.')
                continue
            self.selected_type = options[selection]
            source = BusinessData(self.selected_type, self.db_path)
            try:
                history = source.retrieve_data()
            except Exception as exc:
                print(f'Unable to retrieve business data: {exc}')
                continue
            self.display_history(history, self.selected_type)
            if len(history) < TrendPrediction.MIN_OBSERVATIONS:
                print('At least 3 distinct dates with records are required for a forecast.')
                continue
            if input('Proceed with trend analysis? (y/n): ').strip().lower() != 'y':
                print('Analysis cancelled.')
                continue
            prediction = TrendPrediction(source)
            self.display_trends(prediction, history)
            self.display_prediction(prediction, history)
