import os
import json
import time
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import alpaca_trade_api as tradeapi
import yfinance as yf
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
from transformers import pipeline
import re

# =====================================================================
# 1. INITIALIZE CONNECTIONS & CREDENTIALS
# =====================================================================
API_KEY = os.environ.get("APCA_API_KEY_ID")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY")
BASE_URL = "https://paper-api.alpaca.markets"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

def repair_pem_key(pk_str):
    """Automatically repairs newlines and missing Base64 '=' padding in PEM keys."""
    pk_str = pk_str.replace("\\n", "\n").strip()
    header = "-----BEGIN PRIVATE KEY-----"
    footer = "-----END PRIVATE KEY-----"
    if header in pk_str and footer in pk_str:
        body = pk_str.split(header)[1].split(footer)[0]
        clean_b64 = re.sub(r'[^A-Za-z0-9+/=]', '', body).rstrip('=')
        rem = len(clean_b64) % 4
        if rem == 2:
            clean_b64 += "=="
        elif rem == 3:
            clean_b64 += "="
        lines = [clean_b64[i:i+64] for i in range(0, len(clean_b64), 64)]
        return f"{header}\n" + "\n".join(lines) + f"\n{footer}\n"
    return pk_str

# Connect to Google Sheets with robust PEM sanitization
raw_creds = os.environ.get("GOOGLE_CREDENTIALS", "{}")
creds_json = json.loads(raw_creds, strict=False)
if "private_key" in creds_json:
    creds_json["private_key"] = repair_pem_key(creds_json["private_key"])

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
gc = gspread.authorize(creds)
spreadsheet = gc.open("Auto-Trading Bot Log")
log_sheet = spreadsheet.sheet1

# Ensure "Closed Trades" tab exists for Win Rate & P/L tracking
try:
    closed_sheet = spreadsheet.worksheet("Closed Trades")
except Exception:
    closed_sheet = spreadsheet.add_worksheet(title="Closed Trades", rows="1000", cols="10")
    closed_sheet.append_row([
        "Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID"
    ])

TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG', 'CAT', 'DIS']

# =====================================================================
# 2. HELPER FUNCTIONS
# =====================================================================
def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        return
    try:
        if len(message) <= 1950:
            requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=5)
        else:
            lines = message.split("\n")
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 1900:
                    requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=5)
                    chunk = line + "\n"
                else:
                    chunk += line + "\n"
            if chunk:
                requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=5)
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
    headlines = []
    seen = set()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

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
    try:
        spy = yf.Ticker("SPY").history(period="2d")
        vix = yf.Ticker("^VIX").history(period="2d")
        spy_change = 0.0
        vix_level = 0.0
        if len(spy) >= 2:
            spy_change = (spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]
            if spy_change <= -0.015:
                return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} (PANIC BLOCK)"
        if not vix.empty:
            vix_level = float(vix['Close'].iloc[-1])
            if vix_level > 28.0:
                return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} (VIX BLOCK)"
        return True, f"Normal (SPY {spy_change*100:+.2f}%, VIX {vix_level:.1f})"
    except Exception as e:
        print(f"Macro check warning: {e}")
    return True, "Macro Normal"

def get_technicals_and_atr(ticker):
    df = yf.Ticker(ticker).history(period="1y")
    if df.empty or len(df) < 200:
        return None
    close = df['Close']
    current_price = float(close.iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    
    # Wilder's Exponentially Smoothed RSI-14 Calculation
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0

    # Native ATR-14 Calculation
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - close.shift())
    low_close = np.abs(df['Low'] - close.shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr_series = true_range.rolling(14).mean()
    atr14 = float(atr_series.iloc[-1]) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (current_price * 0.02)

    return {
        "price": current_price,
        "sma200": sma200,
        "ema20": ema20,
        "rsi14": rsi14,
        "atr14": atr14
    }

def was_stopped_out_last_24h(ticker, closed_orders):
    for o in closed_orders:
        if o.symbol == ticker and o.side == 'sell' and o.type in ['stop', 'stop_limit'] and o.status == 'filled':
            return True
    return False

def has_upcoming_earnings_48h(ticker):
    try:
        cal = yf.Ticker(ticker).calendar
        now_date = datetime.now(timezone.utc).date()
        if isinstance(cal, dict) and 'Earnings Date' in cal:
            for d in cal['Earnings Date']:
                if hasattr(d, 'date'):
                    d = d.date()
                if abs((d - now_date).days) <= 2:
                    return True
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            for val in cal.values.flatten():
                if hasattr(val, 'date'):
                    val = val.date()
                if hasattr(val, 'year') and abs((val - now_date).days) <= 2:
                    return True
    except Exception:
        pass
    return False

def fetch_active_and_held_orders():
    active = {}
    try:
        for o in api.list_orders(status='open', nested=True, limit=200):
            active[o.id] = o
            if hasattr(o, 'legs') and o.legs:
                for leg in o.legs:
                    if leg.status in ['new', 'held', 'accepted', 'partially_filled']:
                        active[leg.id] = leg
        for o in api.list_orders(status='closed', nested=True, limit=200):
            if hasattr(o, 'legs') and o.legs:
                for leg in o.legs:
                    if leg.status in ['new', 'held', 'accepted', 'partially_filled']:
                        active[leg.id] = leg
    except Exception as e:
        print(f"Order fetch warning: {e}")
    return list(active.values())

def get_all_orders_for_ticker(ticker, active_orders):
    return [o for o in active_orders if o.symbol == ticker and o.status in ['new', 'held', 'accepted', 'partially_filled']]

def cancel_existing_orders_for_ticker(ticker, active_orders):
    canceled = False
    for o in get_all_orders_for_ticker(ticker, active_orders):
        try:
            api.cancel_order(o.id)
            canceled = True
        except Exception as e:
            print(f"Cancel order warning for {ticker}: {e}")
    if canceled:
        time.sleep(1.5)

def sync_recent_closed_sells(closed_orders):
    new_fill_alerts = []
    try:
        existing_ids = set(closed_sheet.col_values(6))
        for o in closed_orders:
            if o.side == 'sell' and o.status == 'filled' and o.id not in existing_ids:
                filled_time = str(o.filled_at)[:19] if o.filled_at else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                fill_price = float(o.filled_avg_price) if o.filled_avg_price else 0.0
                order_type = o.type.upper()
                closed_sheet.append_row([
                    filled_time, o.symbol, str(o.filled_qty), order_type, f"${fill_price:.2f}", o.id
                ])
                existing_ids.add(o.id)
                if o.type in ['stop', 'stop_limit']:
                    new_fill_alerts.append(f"🛑 **STOP-LOSS TRIGGERED ({o.symbol})**: Sold {o.filled_qty} sh @ `${fill_price:.2f}` ({filled_time} UTC)")
                elif o.type == 'limit':
                    new_fill_alerts.append(f"🎯 **TAKE-PROFIT HIT ({o.symbol})**: Sold {o.filled_qty} sh @ `${fill_price:.2f}` ({filled_time} UTC)")
    except Exception as e:
        print(f"Closed trades sheet sync warning: {e}")
    return new_fill_alerts

# =====================================================================
# 3. MAIN EXECUTION ENGINE
# =====================================================================
def run_bot():
    clock = api.get_clock()
    if not clock.is_open:
        print("US Stock Market is currently CLOSED. Aborting scan to prevent blind order queuing.")
        return

    account = api.get_account()
    equity = float(account.equity)
    daytrade_count = int(getattr(account, 'daytrade_count', 0) or 0)
    pdt_restricted = daytrade_count >= 3

    positions = {p.symbol: p for p in api.list_positions()}
    active_orders = fetch_active_and_held_orders()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    automated_exit_alerts = sync_recent_closed_sells(closed_orders_24h)
    macro_ok, macro_reason = check_macro_regime()
    summary_alerts = list(automated_exit_alerts)
    scan_table_lines = []

    for ticker in TICKERS:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(ticker)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(ticker)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"

        owned_qty = float(positions[ticker].qty) if ticker in positions else 0.0
        decision = "HOLD"
        action_taken = "None"

        if owned_qty > 0:
            pos = positions[ticker]
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price

            if score <= -0.15:
                if pdt_restricted:
                    decision = "BEARISH (PDT Shield Locked)"
                    action_taken = "Skipped sell to prevent PDT lock"
                else:
                    try:
                        cancel_existing_orders_for_ticker(ticker, active_orders)
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
                        summary_alerts.append(f"🔴 **SOLD {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`)")
                    except Exception as e:
                        decision = "BEARISH"
                        action_taken = f"Sell Failed: {e}"
            else:
                if unrealized_pct >= 0.025:
                    ticker_orders = get_all_orders_for_ticker(ticker, active_orders)
                    ticker_stops = [o for o in ticker_orders if o.side == 'sell' and o.type in ['stop', 'stop_limit']]
                    if ticker_stops:
                        stop_order = ticker_stops[0]
                        if float(stop_order.stop_price) < entry_price:
                            try:
                                api.replace_order(stop_order.id, stop_price=round(entry_price, 2))
                                action_taken = f"Ratcheted Stop to Break-Even (${entry_price:.2f})"
                                summary_alerts.append(f"🛡️ **BREAK-EVEN SHIELD ({ticker})**: Stop moved up to `${entry_price:.2f}` (`+{unrealized_pct*100:.1f}%` gain locked)")
                            except Exception as e:
                                print(f"Break-even replace note for {ticker}: {e}")

                if score >= 0.10:
                    decision = "BULLISH (Already Owned)"
                else:
                    decision = "HOLD"
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
                    if score >= 0.25:
                        target_dollars = equity * 0.025
                    elif score >= 0.15:
                        target_dollars = equity * 0.015
                    else:
                        target_dollars = equity * 0.008

                    price = tech['price']
                    qty_to_buy = max(1, int(round(target_dollars / price)))

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
                        summary_alerts.append(f"🟢 **BUY {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`, RSI: `{rsi_val}`)")
                    except Exception as e:
                        decision = "BULLISH"
                        action_taken = f"Buy Failed: {e}"
            elif score <= -0.10:
                decision = "BEARISH (Not Owned)"
            else:
                decision = "HOLD"

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
        scan_table_lines.append(f"• **{ticker}**: FinBERT `{score:+.3f}` ({len(headlines)} news) | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(1)

    if summary_alerts:
        send_discord_alert("🚨 **Bot v2.0 Trade & Risk Execution Alert:**\n" + "\n".join(summary_alerts))

    try:
        time.sleep(2)
        account = api.get_account()
        equity = float(account.equity)
        last_equity = float(getattr(account, 'last_equity', equity) or equity)
        cash = float(getattr(account, 'cash', 0.0) or 0.0)
        day_pl = equity - last_equity
        day_pl_pct = (day_pl / last_equity) * 100 if last_equity > 0 else 0.0
        total_pl = equity - 100000.0
        total_pl_pct = (total_pl / 100000.0) * 100

        positions = {p.symbol: p for p in api.list_positions()}
        active_orders = fetch_active_and_held_orders()

        ny_time = datetime.now(ZoneInfo("America/New_York"))
        is_midday = ny_time.hour < 12
        report_title = "☀️ **Mid-Day Market Briefing & Scan Report**" if is_midday else "🌙 **End-of-Day Portfolio & Scan Closeout**"

        total_unrealized_pl = sum(float(p.unrealized_pl) for p in positions.values())
        invested_val = sum(float(p.market_value) for p in positions.values())

        detailed_report = (
            f"{report_title}\n"
            f"🕒 **Time (NY):** `{ny_time.strftime('%Y-%m-%d %I:%M %p')}` | 🌍 **Macro:** `{macro_reason}`\n"
            f"💰 **Total Equity:** `${equity:,.2f}` (All-Time: `${total_pl:+,.2f}` / `{total_pl_pct:+.2f}%`)\n"
            f"📅 **Today's Change:** `${day_pl:+,.2f}` (`{day_pl_pct:+.2f}%`) | 📊 **Open P/L:** `${total_unrealized_pl:+,.2f}`\n"
            f"💵 **Cash:** `${cash:,.2f}` | 💼 **Invested:** `${invested_val:,.2f}` ({len(positions)} positions)\n\n"
            f"📈 **Active Portfolio Breakdown ({len(positions)}):**\n"
        )

        for sym, p in sorted(positions.items()):
            qty = float(p.qty)
            entry = float(p.avg_entry_price)
            curr = float(p.current_price)
            mkt_val = float(p.market_value)
            pl_dollar = float(p.unrealized_pl)
            pl_pct = float(p.unrealized_plpc) * 100 if hasattr(p, 'unrealized_plpc') and p.unrealized_plpc else ((curr - entry) / entry) * 100

            sym_orders = get_all_orders_for_ticker(sym, active_orders)
            stop_str = "None"
            tp_str = "None"
            for o in sym_orders:
                if o.side == 'sell':
                    if o.type in ['stop', 'stop_limit'] and o.stop_price:
                        stop_str = f"${float(o.stop_price):.2f}"
                    elif o.type == 'limit' and o.limit_price:
                        tp_str = f"${float(o.limit_price):.2f}"

            detailed_report += (
                f"• **{sym}** ({int(qty)} sh | `${mkt_val:,.0f}`): "
                f"`${entry:.2f}` ➔ `${curr:.2f}` | P/L: `${pl_dollar:+,.2f}` (`{pl_pct:+.2f}%`) | "
                f"🎯 TP: `{tp_str}` | 🛑 SL: `{stop_str}`\n"
            )

        detailed_report += "\n🧠 **12-Ticker AI & Technical Scan Summary:**\n" + "\n".join(scan_table_lines)
        send_discord_alert(detailed_report)
    except Exception as e:
        print(f"Detailed portfolio report error: {e}")

if __name__ == "__main__":
    run_bot()
