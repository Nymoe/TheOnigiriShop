        """
        if self.data_type == "Sales":
            sql = '''SELECT substr(orderDate, 1, 10) AS day, COUNT(*) AS amount
                     FROM "Order"
                     WHERE status='Completed' AND orderDate IS NOT NULL
                     GROUP BY substr(orderDate, 1, 10) ORDER BY day'''
        elif self.data_type == "Financial":
            sql = '''SELECT substr(orderDate, 1, 10) AS day, SUM(totalAmount) AS amount
                     FROM "Order"
                     WHERE status='Completed' AND orderDate IS NOT NULL
                       AND totalAmount IS NOT NULL
                     GROUP BY substr(orderDate, 1, 10) ORDER BY day'''
        else:
            # Count customer-order ingredient consumption events, not quantities:
            # ingredients may have incompatible units (grams, pieces, litres).
            sql = '''SELECT substr(transactionDate, 1, 10) AS day,
                            COUNT(*) AS amount
                     FROM InventoryTransaction
                     WHERE transactionType='Customer Order' AND quantity < 0
                       AND transactionDate IS NOT NULL
                     GROUP BY substr(transactionDate, 1, 10) ORDER BY day'''

        db = connect(self.db_path)
        try:
            records = db.execute(sql).fetchall()
        finally:
            db.close()
        result = []
        for row in records:
            try:
                day = date.fromisoformat(row["day"])
            except (ValueError, TypeError):
                continue
            result.append({"date": day.isoformat(), "value": float(row["amount"])})
        return result


class TrendPrediction:
    MIN_OBSERVATIONS = 3

    def __init__(self, business_data):
        self.business_data = business_data
        self.prediction_id = None
        self.trend_type = business_data.data_type
        self.predicted_value = None
        self.prediction_date = None

    def generate_trend(self, history=None):
        history = self.business_data.retrieve_data() if history is None else history
        if len(history) < self.MIN_OBSERVATIONS:
            return None
        previous = mean(item["value"] for item in history[-3:-1])
        latest = history[-1]["value"]
        return "Increasing" if latest > previous else "Decreasing" if latest < previous else "Stable"

    def generate_prediction(self, history=None):
        history = self.business_data.retrieve_data() if history is None else history
        if len(history) < self.MIN_OBSERVATIONS:
            self.predicted_value = None
            self.prediction_date = None
            return None
        self.predicted_value = round(mean(item["value"] for item in history[-3:]), 2)
        # Next calendar day after the most recent recorded observation.
        self.prediction_date = (date.fromisoformat(history[-1]["date"]) + timedelta(days=1)).isoformat()
        return self.predicted_value


class TrendPredictingDashboard:
    LABELS = {
        "Sales": "completed orders",
        "Inventory": "ingredient consumption events",
        "Financial": "CAD revenue (not profit)",
    }

    def __init__(self, db_path=None):
        self.dashboard_id = None
        self.selected_type = "Sales"
        self.db_path = db_path

    def display_history(self, history, data_type):
        print(f"\nHistorical {data_type.lower()} data:")
        if not history:
            print("No historical records available.")
        for item in history:
            print(f'  {item["date"]}: {item["value"]:,.2f} {self.LABELS[data_type]}')

    def display_trends(self, prediction, history):
        print("Trend:", prediction.generate_trend(history) or "Unavailable (insufficient history)")

    def display_prediction(self, prediction, history):
        value = prediction.generate_prediction(history)
        if value is None:
            print("Prediction unavailable: at least 3 recorded dates are required.")
        else:
            print(f"Forecast for {prediction.prediction_date}: {value:,.2f} "
                  f"{self.LABELS[prediction.trend_type]}")
            print("Method: average of the last 3 recorded dates; illustrative only.")

    def run(self):
        print("\n=== Trend Predicting Dashboard ===")
        print("1. Sales (completed order count)")
        print("2. Inventory (consumption transaction count)")
        print("3. Financial (completed-order revenue)")
        selection = input("Choose 1, 2, or 3 (or q to exit): ").strip().lower()
        if selection == "q":
            return
        options = {"1": "Sales", "2": "Inventory", "3": "Financial"}
        if selection not in options:
            print("Invalid selection.")
            return
        self.selected_type = options[selection]
        source = BusinessData(self.selected_type, self.db_path)
        try:
            history = source.retrieve_data()
        except Exception as exc:
            print(f"Unable to retrieve business data: {exc}")
            print("No trends or predictions were generated.")
            return

        self.display_history(history, self.selected_type)
        if len(history) < TrendPrediction.MIN_OBSERVATIONS:
            print("Insufficient historical data for reliable trends or predictions.")
            return
        proceed = input("Proceed with trend analysis? (y/n): ").strip().lower()
        if proceed != "y":
            print("Analysis cancelled.")
            return
        prediction = TrendPrediction(source)
