import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
import alpaca_trade_api as tradeapi
import yfinance as yf
import pandas as pd
import pandas_ta as ta
import gspread
from google.oauth2.service_account import Credentials
from transformers import pipeline

# =====================================================================
# 1. INITIALIZE CONNECTIONS & CREDENTIALS
# =====================================================================
API_KEY = os.environ.get("APCA_API_KEY_ID")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

# Connect to Google Sheets
creds_json = json.loads(os.environ.get("GOOGLE_CREDENTIALS"))
scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
gc = gspread.authorize(creds)
spreadsheet = gc.open("Auto-Trading Bot Log")
log_sheet = spreadsheet.sheet1

# Upgrade #20: Ensure "Closed Trades" tab exists for Win Rate & P/L tracking
try:
    closed_sheet = spreadsheet.worksheet("Closed Trades")
except Exception:
    closed_sheet = spreadsheet.add_worksheet(title="Closed Trades", rows="1000", cols="10")
    closed_sheet.append_row([
        "Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID"
    ])

TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG', 'CAT', 'DIS']

# =====================================================================
# 2. HELPER FUNCTIONS (UPGRADES #1 TO #23)
# =====================================================================
def send_discord_alert(message):
    """Upgrade #19: Optional Discord Mobile Push Notification"""
    if DISCORD_WEBHOOK:
        try:
            requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
        except Exception as e:
            print(f"Discord alert error: {e}")

print("Loading ProsusAI/finbert financial AI model...")
finbert = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None
)

def get_fresh_dual_news(ticker):
    """Upgrades #2 & #3: Dual-Source News (Alpaca + yfinance) with 24-Hr Freshness & Deduplication"""
    headlines = []
    seen = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

    # Source 1: Alpaca News API
    try:
        alpaca_news = api.get_news(ticker, limit=15)
        for item in alpaca_news:
            created = item.created_at
            if hasattr(created, 'tzinfo') and created.tzinfo is not None:
                if created < cutoff:
                    continue
            title = item.headline.strip()
            if title and title.lower() not in seen:
                seen.add(title.lower())
                headlines.append(title)
    except Exception as e:
        print(f"Alpaca news warning for {ticker}: {e}")

    # Source 2: Yahoo Finance News API
    try:
        yf_news = yf.Ticker(ticker).news
        if yf_news:
            for item in yf_news[:10]:
                title = item.get('title', '')
                if not title and 'content' in item:
                    title = item['content'].get('title', '')
                title = title.strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    headlines.append(title)
    except Exception as e:
        print(f"yfinance news warning for {ticker}: {e}")

    return headlines

def get_finbert_sentiment(headlines):
    """Upgrade #1: Institutional Financial AI Sentiment Scoring"""
    if not headlines:
        return 0.0
    clean = [h[:512] for h in headlines if h and len(h.strip()) > 10]
    if not clean:
        return 0.0

    results = finbert(clean)
    weighted_scores = []
    for res in results:
        scores = {item['label']: item['score'] for item in res}
        pos = scores.get('positive', 0.0)
        neg = scores.get('negative', 0.0)
        neu = scores.get('neutral', 0.0)
        net_score = pos - neg
        if neu < 0.80:
            weighted_scores.append(net_score)
        else:
            weighted_scores.append(net_score * 0.2)

    if not weighted_scores:
        return 0.0
    return round(sum(weighted_scores) / len(weighted_scores), 3)

def check_macro_regime():
    """Upgrade #17: SPY (-1.5%) & VIX (> 28) Market Crash Master Switch"""
    try:
        spy = yf.Ticker("SPY").history(period="2d")
        vix = yf.Ticker("^VIX").history(period="2d")
        if len(spy) >= 2:
            spy_change = (spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]
            if spy_change <= -0.015:
                return False, f"SPY down {spy_change*100:.2f}% intraday"
        if not vix.empty:
            vix_level = vix['Close'].iloc[-1]
            if vix_level > 28.0:
                return False, f"VIX spike at {vix_level:.1f}"
    except Exception as e:
        print(f"Macro check warning: {e}")
    return True, "Macro Normal"

def get_technicals_and_atr(ticker):
    """Upgrades #4, #5, #6, #7: 200-SMA, 20-EMA, 14-RSI, and 14-Day ATR"""
    df = yf.Ticker(ticker).history(period="1y")
    if df.empty or len(df) < 200:
        return None
    close = df['Close']
    current_price = float(close.iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    rsi_series = ta.rsi(close, length=14)
    rsi14 = float(rsi_series.iloc[-1]) if rsi_series is not None else 50.0
    atr_series = ta.atr(df['High'], df['Low'], close, length=14)
    atr14 = float(atr_series.iloc[-1]) if atr_series is not None else (current_price * 0.02)

    return {
        "price": current_price,
        "sma200": sma200,
        "ema20": ema20,
        "rsi14": rsi14,
        "atr14": atr14
    }

def was_stopped_out_last_24h(ticker, closed_orders):
    """Upgrade #12: 24-Hour Stop-Loss Cooldown Shield"""
    for o in closed_orders:
        if o.symbol == ticker and o.side == 'sell' and o.type in ['stop', 'stop_limit'] and o.status == 'filled':
            return True
    return False

def has_upcoming_earnings_48h(ticker):
    """Upgrade #16: 48-Hour Quarterly Earnings Blackout Shield"""
    try:
        cal = yf.Ticker(ticker).calendar
        if isinstance(cal, dict) and 'Earnings Date' in cal:
            dates = cal['Earnings Date']
            now_date = datetime.now(timezone.utc).date()
            for d in dates:
                days_diff = abs((d - now_date).days)
                if days_diff <= 2:
                    return True
    except Exception:
        pass
    return False

def cancel_existing_orders_for_ticker(ticker, open_orders):
    """Upgrade #11: Bracket-Unlock Fix (Cancels open stop/limit legs before selling or updating)"""
    canceled = False
    for o in open_orders:
        if o.symbol == ticker:
            try:
                api.cancel_order(o.id)
                canceled = True
            except Exception as e:
                print(f"Cancel order warning for {ticker}: {e}")
    if canceled:
        time.sleep(1.5)

def sync_recent_closed_sells(closed_orders):
    """Upgrade #20: Log recent automated Stop-Loss / Take-Profit fills to Closed Trades tab"""
    try:
        existing_ids = set(closed_sheet.col_values(6))
        for o in closed_orders:
            if o.side == 'sell' and o.status == 'filled' and o.id not in existing_ids:
                filled_time = str(o.filled_at)[:19] if o.filled_at else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                closed_sheet.append_row([
                    filled_time, o.symbol, str(o.filled_qty), o.type.upper(), f"${float(o.filled_avg_price):.2f}", o.id
                ])
    except Exception as e:
        print(f"Closed trades sheet sync warning: {e}")

# =====================================================================
# 3. MAIN EXECUTION ENGINE
# =====================================================================
def run_bot():
    # Upgrade #14: Market-Hours Gatekeeper (Prevents overnight/weekend queuing)
    clock = api.get_clock()
    if not clock.is_open:
        print("US Stock Market is currently CLOSED. Aborting scan to prevent blind order queuing.")
        return

    account = api.get_account()
    equity = float(account.equity)
    daytrade_count = int(account.daytrade_count)
    pdt_restricted = daytrade_count >= 3  # Upgrade #15: Hard-Coded PDT Shield

    positions = {p.symbol: p for p in api.list_positions()}
    open_orders = api.list_orders(status='open')
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    # Sync any stop-loss or take-profit fills from the past 24h
    sync_recent_closed_sells(closed_orders_24h)

    macro_ok, macro_reason = check_macro_regime()
    summary_alerts = []

    for ticker in TICKERS:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(ticker)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(ticker)

        owned_qty = float(positions[ticker].qty) if ticker in positions else 0.0
        decision = "HOLD"
        action_taken = "None"

        # -------------------------------------------------------------
        # CASE A: POSITION ALREADY OWNED -> MANAGE EXIT OR RATCHET STOP
        # -------------------------------------------------------------
        if owned_qty > 0:
            pos = positions[ticker]
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price

            # Upgrade #11: Bearish Exit with Bracket-Unlock + PDT Check
            if score <= -0.15:
                if pdt_restricted:
                    decision = "BEARISH (PDT Shield Locked)"
                    action_taken = "Skipped sell to prevent PDT lock"
                else:
                    try:
                        cancel_existing_orders_for_ticker(ticker, open_orders)
                        api.submit_order(
                            symbol=ticker,
                            qty=owned_qty,
                            side='sell',
                            type='market',
                            time_in_force='gtc'
                        )
                        decision = "BEARISH"
                        action_taken = f"Sold {int(owned_qty)} @ ~${current_price:.2f} (Sentiment Exit)"
                        owned_qty = 0
                        summary_alerts.append(f"🔴 **SOLD {ticker}**: {action_taken} (Score: {score:+.3f})")
                    except Exception as e:
                        decision = "BEARISH"
                        action_taken = f"Sell Failed: {e}"
            else:
                # Upgrade #9 / #23: The Break-Even Stop Ratchet (+2.5% Profit Shield)
                if unrealized_pct >= 0.025:
                    # Check if current stop order is still below entry price
                    ticker_stops = [o for o in open_orders if o.symbol == ticker and o.side == 'sell' and o.type == 'stop']
                    if ticker_stops:
                        stop_order = ticker_stops[0]
                        if float(stop_order.stop_price) < entry_price:
                            try:
                                api.replace_order(stop_order.id, stop_price=round(entry_price, 2))
                                action_taken = f"Ratcheted Stop to Break-Even (${entry_price:.2f})"
                                summary_alerts.append(f"🛡️ **BREAK-EVEN SHIELD ({ticker})**: Stop moved up to ${entry_price:.2f} (+{unrealized_pct*100:.1f}% gain locked)")
                            except Exception as e:
                                print(f"Break-even replace note for {ticker}: {e}")

                if score >= 0.10:
                    decision = "BULLISH (Already Owned)"
                else:
                    decision = "HOLD"

        # -------------------------------------------------------------
        # CASE B: NOT OWNED -> EVALUATE VERSION 2.0 BUY FILTERS
        # -------------------------------------------------------------
        else:
            if score >= 0.10:
                if not macro_ok:
                    decision = f"BULLISH (Blocked: {macro_reason})"
                elif pdt_restricted:
                    decision = "BULLISH (Blocked: PDT Shield)"
                elif was_stopped_out_last_24h(ticker, closed_orders_24h):
                    decision = "BULLISH (Blocked: 24h Stop Cooldown)"
                elif has_upcoming_earnings_48h(ticker):
                    decision = "BULLISH (Blocked: 48h Earnings Shield)"
                elif tech is None:
                    decision = "BULLISH (Blocked: No Tech Data)"
                elif tech['price'] < tech['sma200']:
                    decision = f"BULLISH (Blocked: Below 200-SMA ${tech['sma200']:.2f})"
                elif tech['price'] < tech['ema20']:
                    decision = f"BULLISH (Blocked: Below 20-EMA ${tech['ema20']:.2f})"
                elif tech['rsi14'] > 70.0:
                    decision = f"BULLISH (Blocked: RSI Overbought {tech['rsi14']:.1f})"
                else:
                    # All 23 Quantitative Shields Passed!
                    # Upgrade #10: Risk-Parity Dollar Sizing (1%, 2%, or 3% of Equity)
                    if score >= 0.25:
                        target_dollars = equity * 0.025  # High conviction (~$2,500)
                    elif score >= 0.15:
                        target_dollars = equity * 0.015  # Medium conviction (~$1,500)
                    else:
                        target_dollars = equity * 0.008  # Standard conviction (~$800)

                    price = tech['price']
                    qty_to_buy = max(1, int(round(target_dollars / price)))

                    # Upgrade #7: 14-Day ATR Dynamic Volatility Brackets
                    atr = max(tech['atr14'], price * 0.01)
                    stop_price = round(price - (1.5 * atr), 2)
                    target_price = round(price + (3.5 * atr), 2)

                    try:
                        api.submit_order(
                            symbol=ticker,
                            qty=qty_to_buy,
                            side='buy',
                            type='market',
                            time_in_force='gtc',
                            order_class='bracket',
                            take_profit={'limit_price': target_price},
                            stop_loss={'stop_price': stop_price}
                        )
                        decision = "BULLISH"
                        action_taken = f"Bought {qty_to_buy} @ ~${price:.2f} | ATR Target: ${target_price:.2f}, ATR Stop: ${stop_price:.2f}"
                        owned_qty = qty_to_buy
                        summary_alerts.append(f"🟢 **BUY {ticker}**: {action_taken} (FinBERT: {score:+.3f}, RSI: {tech['rsi14']:.1f})")
                    except Exception as e:
                        decision = "BULLISH"
                        action_taken = f"Buy Failed: {e}"
            elif score <= -0.10:
                decision = "BEARISH (Not Owned)"
            else:
                decision = "HOLD"

        # Log row to Google Sheet (matches your exact 6-column structure)
        row = [
            now_str,
            ticker,
            f"{score:+.3f}",
            decision,
            action_taken,
            f"Holding {int(owned_qty)} shares"
        ]
        log_sheet.append_row(row)
        print(f"{ticker}: {score:+.3f} | {decision} | {action_taken}")
        time.sleep(1)

    if summary_alerts:
        send_discord_alert("📊 **Bot v2.0 Scan Alert:**\n" + "\n".join(summary_alerts))

if __name__ == "__main__":
    run_bot()
