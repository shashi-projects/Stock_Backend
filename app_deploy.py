

import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS

# ------------------------------------------------------------------
# APP SETUP
# ------------------------------------------------------------------
app = Flask(__name__)

# Allow all origins (safe for dev + ngrok)
CORS(app, resources={r"/api/*": {"origins": "*"}})

CSV_PATH = "UI/EQUITY_L.csv"
HISTORY_FOLDER = "history_store"

if not os.path.exists(HISTORY_FOLDER):
    os.makedirs(HISTORY_FOLDER)

# ------------------------------------------------------------------
# HELPER: Fetch stock data for a given date
# ------------------------------------------------------------------
def get_stock_data_for_date(target_date_str):
    file_path = os.path.join(HISTORY_FOLDER, f"{target_date_str}.xlsx")

    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()

    # Market close at 3:30 PM
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    is_after_market_close = now >= market_close

    # --------------------------------------------------------------
    # CACHE LOGIC
    # --------------------------------------------------------------
    if target_date_str == today:
        # Today
        if is_after_market_close and os.path.exists(file_path):
            return pd.read_excel(file_path)
    else:
        # Past date
        if os.path.exists(file_path):
            return pd.read_excel(file_path)

    # --------------------------------------------------------------
    # CSV CHECK
    # --------------------------------------------------------------
    if not os.path.exists(CSV_PATH):
        return "FILE_NOT_FOUND"

    try:
        df_input = pd.read_csv(CSV_PATH)
        symbol_col = "SYMBOL" if "SYMBOL" in df_input.columns else "Symbol"

        tickers = [
            f"{str(x)}.NS"
            for x in df_input[symbol_col].tolist()
            if pd.notna(x)
        ]

        target_date_obj = datetime.strptime(target_date_str, "%Y-%m-%d")
        start_date = target_date_obj - timedelta(days=7)
        end_date = target_date_obj + timedelta(days=1)

        # ----------------------------------------------------------
        # YFINANCE DOWNLOAD (safer for ngrok)
        # ----------------------------------------------------------
        data = yf.download(
            tickers,
            start=start_date,
            end=end_date,
            group_by="ticker",
            threads=False,
            progress=False,
        )

        results = []

        for ticker in tickers:
            try:
                if isinstance(data.columns, pd.MultiIndex):
                    if ticker not in data.columns.levels[0]:
                        continue
                    history = data[ticker].dropna()
                else:
                    history = data.dropna()

                if history.empty or len(history) < 2:
                    continue

                last_available_date = history.index[-1].strftime("%Y-%m-%d")
                if last_available_date != target_date_str:
                    continue

                latest = history.iloc[-1]
                prev = history.iloc[-2]

                diff = round(latest["Close"] - prev["Close"], 2)
                pct_change = round((diff / prev["Close"]) * 100, 2)

                results.append({
                    "Symbol": ticker.replace(".NS", ""),
                    "Latest": round(latest["Close"], 2),
                    "Previous": round(prev["Close"], 2),
                    "Difference": diff,
                    "Change": pct_change
                })

            except Exception as e:
                print(f"Ticker error {ticker}: {e}")
                continue

        df_results = pd.DataFrame(results)

        # ----------------------------------------------------------
        # SAVE CACHE
        # ----------------------------------------------------------
        if not df_results.empty:
            df_results = df_results.sort_values(
                by="Difference", ascending=False
            )

            if target_date_str != today or is_after_market_close:
                df_results.to_excel(file_path, index=False)

            return df_results

        return pd.DataFrame()

    except Exception as e:
        print(f"General error: {e}")
        return None


# ------------------------------------------------------------------
# API ENDPOINTS
# ------------------------------------------------------------------
@app.route("/api/stocks", methods=["GET"])
def get_stocks():
    date = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    df = get_stock_data_for_date(date)

    if df == "FILE_NOT_FOUND":
        return jsonify({"error": "CSV file missing"}), 404

    if df is not None and not df.empty:
        return jsonify({
            "data": df.where(pd.notnull(df), None).to_dict("records")
        })

    return jsonify({"data": [], "message": "No data found"})


@app.route("/api/stock_details", methods=["GET"])
def get_details():
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    search_symbol = (
        f"{symbol}.NS"
        if not symbol.endswith((".NS", ".BO"))
        else symbol
    )

    try:
        ticker = yf.Ticker(search_symbol)
        return jsonify(ticker.info)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stock_history", methods=["GET"])
def get_history():
    symbol = request.args.get("symbol")
    period = request.args.get("period", "1mo")

    if not symbol:
        return jsonify({"error": "Symbol required"}), 400

    search_symbol = (
        f"{symbol}.NS"
        if not symbol.endswith((".NS", ".BO"))
        else symbol
    )

    try:
        ticker = yf.Ticker(search_symbol)
        hist = ticker.history(period=period)

        hist.reset_index(inplace=True)
        hist["Date"] = hist["Date"].dt.strftime("%Y-%m-%d")

        return jsonify(hist[["Date", "Close"]].to_dict("records"))

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------------
# APP START
# ------------------------------------------------------------------
if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5001,
        debug=False,
        use_reloader=False
    )
