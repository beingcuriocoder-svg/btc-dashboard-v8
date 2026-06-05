from flask import Flask
import csv
import os

app = Flask(__name__)

@app.route("/")
def home():
    try:
        if not os.path.exists("btc_dashboard_log.csv"):
            return "CSV file not found"

        with open("btc_dashboard_log.csv", "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        if not rows:
            return "No data available"

        last = rows[-1]

        return f"""
        <h1>BTC Dashboard</h1>
        <p>Price: {last.get('price')}</p>
        <p>Direction: {last.get('direction')}</p>
        <p>Confidence: {last.get('confidence')}%</p>
        <p>Setup: {last.get('setup_type')}</p>
        <p>Action: {last.get('action')}</p>
        """

    except Exception as e:
        return str(e)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)