import os
import json
import time
from datetime import datetime, timezone
import alpaca_trade_api as tradeapi
from textblob import TextBlob
import gspread
from google.oauth2.service_account import Credentials

# 1. Broker Setup
BASE_URL = 'https://paper-api.alpaca.markets'
api = tradeapi.REST(base_url=BASE_URL, api_version='v2')

# 2. Google Sheets Setup
SHEET_TITLE = "Auto-Trading Bot Log"
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

sheet = None
try:
    raw_creds = os.environ.get("GOOGLE_CREDENTIALS")
    if raw_creds:
        creds_dict = json.loads(raw_creds)
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open(SHEET_TITLE).sheet1
        print("Connected to Google Sheets successfully.")
    else:
        print("GOOGLE_CREDENTIALS secret not found. Logging to Sheets will be skipped.")
except Exception as e:
    print(f"Failed to connect to Google Sheets: {e}")

# 3. Strategy Configuration
SYMBOLS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA']
TRADE_QTY = 1
BULLISH_THRESHOLD = 0.10
BEARISH_THRESHOLD = -0.10
PROFIT_TARGET_PERCENT = 1.05
STOP_LOSS_PERCENT = 0.98

print("Auto-Trading Bot initialized with Google Sheets Logging")
print("=" * 60)

for symbol in SYMBOLS:
    print(f"\nAnalyzing {symbol}...")
    
    # Portfolio Check
    try:
        position = api.get_position(symbol)
        we_own_stock = True
        current_holding = f"{position.qty} shares"
    except Exception:
        we_own_stock = False
        current_holding = "0 shares"

    # News & Sentiment
    news_items = api.get_news(symbol, limit=5)
    if not news_items:
        print(f"No recent headlines found for {symbol}. Skipping.")
        continue

    total_polarity = 0
    valid_articles = 0
    for article in news_items:
        content = article.summary if article.summary else article.headline
        score = TextBlob(content).sentiment.polarity
        total_polarity += score
        valid_articles += 1

    avg_sentiment = total_polarity / valid_articles if valid_articles else 0.0
    sentiment_display = f"{avg_sentiment:+.3f}"
    print(f"Market Sentiment: {sentiment_display}")

    # Decision & Execution
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S UTC")

    ai_decision = "HOLD"
    executed_action = "None"
    portfolio_impact = f"Holding {current_holding}"

    if avg_sentiment >= BULLISH_THRESHOLD and not we_own_stock:
        ai_decision = "BULLISH"
        try:
            latest_trade = api.get_latest_trade(symbol)
            current_price = latest_trade.price
            target_price = round(current_price * PROFIT_TARGET_PERCENT, 2)
            stop_price = round(current_price * STOP_LOSS_PERCENT, 2)

            api.submit_order(
                symbol=symbol,
                qty=TRADE_QTY,
                side='buy',
                type='market',
                time_in_force='gtc',
                order_class='bracket',
                take_profit={'limit_price': target_price},
                stop_loss={'stop_price': stop_price}
            )
            executed_action = f"Bought {TRADE_QTY} @ ~${current_price:.2f}"
            portfolio_impact = f"Entered position (Target: ${target_price}, Stop: ${stop_price})"
            print(f"Buy bracket order submitted for {symbol}.")
        except Exception as err:
            executed_action = f"Buy Failed: {err}"
            print(f"Error submitting buy order: {err}")

    elif avg_sentiment <= BEARISH_THRESHOLD and we_own_stock:
        ai_decision = "BEARISH"
        try:
            api.close_position(symbol)
            executed_action = f"Closed position ({current_holding})"
            portfolio_impact = "Liquidated to cash"
            print(f"Closed position for {symbol}.")
        except Exception as err:
            executed_action = f"Sell Failed: {err}"
            print(f"Error submitting sell order: {err}")
    else:
        if avg_sentiment >= BULLISH_THRESHOLD and we_own_stock:
            ai_decision = "BULLISH (Already Owned)"
        elif avg_sentiment <= BEARISH_THRESHOLD and not we_own_stock:
            ai_decision = "BEARISH (Not Owned)"
        print(f"Action: Hold. No state change required.")

    # Write Entry to Google Sheet
    if sheet:
        try:
            row_data = [
                date_str,
                time_str,
                symbol,
                sentiment_display,
                ai_decision,
                executed_action,
                portfolio_impact
            ]
            sheet.append_row(row_data)
            print(f"Logged {symbol} record to Google Sheet.")
        except Exception as log_err:
            print(f"Failed to append row to Google Sheet: {log_err}")

    time.sleep(2)

print("\nScan completed.")
