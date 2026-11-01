import os
import re
import json
import time
import argparse
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

# =====================================================================
# 1. INITIALIZE CONNECTIONS, CREDENTIALS & 3-TIER UNIVERSES
# =====================================================================
API_KEY = os.environ.get("APCA_API_KEY_ID") or "PK24UBUQJRV4IZBY2PEP2RJA7I"
API_SECRET = os.environ.get("APCA_API_SECRET_KEY") or "DbZoPN5n93m5T1g3PH6aiENiNgQhhpoAoVBrABfVkx7H"
BASE_URL = "https://paper-api.alpaca.markets"

# Uses your GitHub Actions secret automatically, or you can paste your Discord URL in the quotes on the right:
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL") or "PASTE_DISCORD_WEBHOOK_URL_HERE_IF_NOT_IN_GITHUB_SECRETS"

DEFAULT_GOOGLE_CREDS = {
    "type": "service_account",
    "project_id": "trading-bot-logger-511317",
    "private_key_id": "16241fed957acbd53894d939b93bf99c2cc2cc55",
    "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDUOBEo96vmYfI5\nPm//578PO18EPzdJppF8qZMQN8CHuEaMHQfe8NPApJpND5yYiAHuqAGji3qrlUPc\nwRB9EUTZT9Qf8h2gqYDMuMNhIcIqExbUiuUBqf7SB+eCWbQDJ6xTHgX9jUDUYRgB\nxggsO6eEelLjJuS9ZwmcgkppUeqdIciZSUfPxgPQOaYiMABwLXlX/kC8VJjjXMzZ\nX8qL1eOQzV8EVbP4XsmHOyYENUYHxsbIUjLkAYU1PK/0Jb3igmswqv7553UZ8DEG\nJlrHGntUhRfsb11r0Rt17En597BpYlz5CMYtAtcEQFdGF1l3M+zgLX+MAN3W97CN\nJqt3mm4dAgMBAAECggEAIXBWL9zarrn3N1LhxfJntgg2YA5v8UB4QyrbG96VDS2Z\nnCFE6LmMvBmToJnZpGUl3MuHOpRTN28VGtcm+HX8obtE4uW9CmA7BccFLixqEkQg\nwEvEat804jZRocXtqeOZ8RzVd87GjNBhvoHMLuAVdLfrkJRDzZ5LMuiKvg6kx65O\nAP0iAuEO552GLFbFiRHOR2wJbtpboB5c/FKc77wQGWK6gIn/q36UL/PuuuARWAYK\n4VaL0BHjv9qBNYRJBueJS1D7b7m3qSE3vAS1DLL+KqNECvZszeXRJWKYBvdQimSS\nDB4fPIZk6Zx88MziDALjtm98xkZduOgr4OWo1iqFpwKBgQD2ywD8mvnpy8wkUmTa\nyyQLMUN1TWet/mFFcgdVv3nIkGQXrb4lFBKXRJcN+1poPA2xCUHiycgXDBkB2bwE\ncxEwGYGyBHTcZENHg2D7EowIYOTdhJayujae3eKsRrXy0ctgIm0siCXjVrUfEzse\nr0I175unUSCePI8dXQu28cMpTwKBgQDcIt1PW73XCo2EV/6Q2wKHpIvk+5R9dP3I\nQ37zGQMmCOGqH0Jo41Mbv+rRIDmfe322wHQtlCOxhelu3KKOQf/lTmmmlYEW5cWu\naqa0yfZJqOJKY9GVGwW9+VwFqHbkNfMGMS0QA/G0AM4z0ORqDy54hXgrNcDTkkei\nMmjtnE3+0wKBgQComwxzh9WRmwA/GGN67yoS03dI3rckshP2g+7q8EPdeHhJjRPI\n9Su2WM/yZ3TenZilCLQQotammEdFcmH3kD1/5Q0sd8r2/zDP3LwXDBbLapcxl/H0\n7S9/3guMs0p/OEF/zkVUFTf9VzGqp1LOpeHQQ4DOEKj+MlV8NCNau1UgFQKBgFo2\nK21/EiAS4gWvLdJc/f9qTi4Lb0GudOXhyx+CS4kFsLzPzJ5BMmi30FndE+Aock83\nNSUMhUgVsaDN6AvWPjDRXnh24gzpIoakjCagcT6kZ//GQjgRd9vvWWe0Luy8sxgB\nhQ8AHsf+YIJZg5F3ITsgrys9/wR0+MgeUmO1Xz0jAoGBAK9LrgClrYJGtcmGs3Hb\nV4NqTo7wLUKcXhqDE3wPFSPH4Sr12UQ/PJ06LyKi2oYlwv9Z6DlZ5gXRPdog7tIl\nEl5Gis8s3yT7xb10uxG+A9UJOA1bQb1ZQhivBIEdON94DrtiyZhRs9PrSptHo7SR\nJFnweXaZbt8AiiRYiY6gRlyw\n-----END PRIVATE KEY-----\n",
    "client_email": "bot-logger@trading-bot-logger-511317.iam.gserviceaccount.com",
    "client_id": "112953992063609615267",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/bot-logger%40trading-bot-logger-511317.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
}

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

raw_creds = os.environ.get("GOOGLE_CREDENTIALS", "").replace("\xa0", " ").replace("\u00a0", " ").strip()
if raw_creds:
    try:
        creds_json = json.loads(raw_creds, strict=False)
    except Exception:
        creds_json = dict(DEFAULT_GOOGLE_CREDS)
else:
    creds_json = dict(DEFAULT_GOOGLE_CREDS)

if "private_key" in creds_json:
    creds_json["private_key"] = repair_pem_key(creds_json["private_key"])

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
gc = gspread.authorize(creds)
spreadsheet = gc.open("Auto-Trading Bot Log")

def get_or_create_worksheet(sh, title, headers):
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows="1500", cols="10")
        ws.append_row(headers)
    return ws

LOG_HEADERS = ["Timestamp", "Ticker", "FinBERT Score", "Decision", "Action Taken", "Position Status"]
core_sheet = spreadsheet.sheet1
momentum_sheet = get_or_create_worksheet(spreadsheet, "Momentum Log", LOG_HEADERS)
crypto_sheet = get_or_create_worksheet(spreadsheet, "Crypto Log", LOG_HEADERS)
closed_sheet = get_or_create_worksheet(
    spreadsheet,
    "Closed Trades",
    ["Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID"]
)

# 3 Non-Overlapping Strategy Universes
CORE_TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG', 'CAT', 'DIS']
MOMENTUM_TICKERS = ['AMD', 'PLTR', 'META', 'COIN', 'NFLX', 'AMZN', 'CRM', 'UBER']
CRYPTO_PAIRS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AVAX/USD', 'LINK/USD']

# =====================================================================
# 2. SHARED AI, NEWS & TECHNICAL HELPER FUNCTIONS
# =====================================================================
def send_discord_alert(message):
    if not DISCORD_WEBHOOK or "PASTE_DISCORD" in DISCORD_WEBHOOK:
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

print("Loading ProsusAI/finbert financial AI model once into shared RAM...")
finbert = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None
)

def to_yf_symbol(ticker):
    return ticker.replace("/", "-")

def to_alpaca_pos_symbol(ticker):
    return ticker.replace("/", "")

def get_fresh_dual_news(ticker):
    """Fetches 24h news from Alpaca + Yahoo Finance with a 72h fallback for quiet blue-chips."""
    headlines = []
    seen = set()
    now_utc = datetime.now(timezone.utc)
    cutoff_24h = now_utc - timedelta(hours=24)
    cutoff_72h = now_utc - timedelta(hours=72)
    older_backup = []

    alpaca_query = ticker.replace("/", "") if "/" in ticker else ticker
    try:
        alpaca_news = api.get_news(alpaca_query, limit=15)
        for item in alpaca_news:
            created = item.created_at
            title = (getattr(item, 'headline', '') or '').strip()
            if not title or title.lower() in seen:
                continue
            if hasattr(created, 'tzinfo') and created.tzinfo is not None:
                if created >= cutoff_24h:
                    seen.add(title.lower())
                    headlines.append(title)
                elif created >= cutoff_72h:
                    older_backup.append(title)
            else:
                seen.add(title.lower())
                headlines.append(title)
    except Exception as e:
        print(f"Alpaca news warning for {ticker}: {e}")

    yf_sym = to_yf_symbol(ticker)
    try:
        yf_news = yf.Ticker(yf_sym).news
        if yf_news:
            for item in yf_news[:10]:
                if not isinstance(item, dict):
                    continue
                content = item.get('content') or {}
                title = item.get('title') or (content.get('title') if isinstance(content, dict) else '') or ''
                title = str(title).strip()
                if title and title.lower() not in seen:
                    seen.add(title.lower())
                    headlines.append(title)
    except Exception as e:
        print(f"yfinance news warning for {ticker}: {e}")

    if not headlines and older_backup:
        headlines = older_backup[:5]

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
    yf_sym = to_yf_symbol(ticker)
    df = yf.Ticker(yf_sym).history(period="1y")
    if df.empty or len(df) < 50:
        return None
    close = df['Close']
    current_price = float(close.iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else float(close.mean())
    sma50 = float(close.rolling(50).mean().iloc[-1])
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])

    # Wilder's Exponentially Smoothed RSI-14
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0

    # Native 14-Day ATR
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
        "sma50": sma50,
        "ema20": ema20,
        "ema9": ema9,
        "rsi14": rsi14,
        "atr14": atr14
    }

def was_stopped_out_last_24h(ticker, closed_orders):
    norm = to_alpaca_pos_symbol(ticker)
    for o in closed_orders:
        if to_alpaca_pos_symbol(o.symbol) == norm and o.side == 'sell' and o.type in ['stop', 'stop_limit'] and o.status == 'filled':
            return True
    return False

def has_upcoming_earnings_48h(ticker):
    if "/" in ticker:
        return False
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
    norm = to_alpaca_pos_symbol(ticker)
    return [o for o in active_orders if to_alpaca_pos_symbol(o.symbol) == norm and o.status in ['new', 'held', 'accepted', 'partially_filled']]

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
                    new_fill_alerts.append(f"🛑 **STOP-LOSS TRIGGERED ({o.symbol})**: Sold {o.filled_qty} @ `${fill_price:.2f}` ({filled_time} UTC)")
                elif o.type == 'limit':
                    new_fill_alerts.append(f"🎯 **TAKE-PROFIT HIT ({o.symbol})**: Sold {o.filled_qty} @ `${fill_price:.2f}` ({filled_time} UTC)")
    except Exception as e:
        print(f"Closed trades sheet sync warning: {e}")
    return new_fill_alerts

# =====================================================================
# 3. ENGINE 1 & 2: EQUITY TRANCHE EXECUTOR (CORE & MOMENTUM)
# =====================================================================
def run_equity_tranche(
    tranche_name,
    tickers,
    sheet_ws,
    positions_map,
    active_orders,
    closed_orders_24h,
    equity,
    pdt_restricted,
    macro_ok,
    macro_reason,
    buy_score_min,
    exit_score_max,
    sl_atr_mult,
    tp_atr_mult,
    ratchet_trigger_pct,
    alloc_pct,
    require_sma200=True
):
    tranche_alerts = []
    scan_lines = []

    for ticker in tickers:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(ticker)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(ticker)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"

        pos = positions_map.get(ticker)
        owned_qty = float(pos.qty) if pos else 0.0
        decision = "HOLD"
        action_taken = "None"

        if owned_qty > 0:
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price

            if score <= exit_score_max:
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
                        tranche_alerts.append(f"🔴 **[{tranche_name}] SOLD {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`)")
                    except Exception as e:
                        decision = "BEARISH"
                        action_taken = f"Sell Failed: {e}"
            else:
                if unrealized_pct >= ratchet_trigger_pct:
                    ticker_orders = get_all_orders_for_ticker(ticker, active_orders)
                    ticker_stops = [o for o in ticker_orders if o.side == 'sell' and o.type in ['stop', 'stop_limit']]
                    if ticker_stops:
                        stop_order = ticker_stops[0]
                        if float(stop_order.stop_price) < entry_price:
                            try:
                                api.replace_order(stop_order.id, stop_price=round(entry_price, 2))
                                action_taken = f"Ratcheted Stop to Break-Even (${entry_price:.2f})"
                                tranche_alerts.append(f"🛡️ **[{tranche_name}] BREAK-EVEN ({ticker})**: Stop moved to `${entry_price:.2f}` (`+{unrealized_pct*100:.1f}%` gain)")
                            except Exception as e:
                                print(f"Break-even replace note for {ticker}: {e}")

                decision = "BULLISH (Already Owned)" if score >= buy_score_min else "HOLD"
        else:
            if score >= buy_score_min:
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
                elif require_sma200 and tech['price'] < tech['sma200']:
                    decision = f"BULLISH (Blocked: Below 200-SMA ${tech['sma200']:.2f})"
                elif not require_sma200 and tech['ema20'] < tech['sma50']:
                    decision = f"BULLISH (Blocked: 20-EMA < 50-SMA)"
                elif tech['price'] < tech['ema20']:
                    decision = f"BULLISH (Blocked: Below 20-EMA ${tech['ema20']:.2f})"
                elif tech['rsi14'] > 72.0:
                    decision = f"BULLISH (Blocked: RSI Overbought {tech['rsi14']:.1f})"
                else:
                    target_dollars = equity * alloc_pct
                    price = tech['price']
                    qty_to_buy = max(1, int(round(target_dollars / price)))

                    atr = max(tech['atr14'], price * 0.01)
                    stop_price = round(price - (sl_atr_mult * atr), 2)
                    target_price = round(price + (tp_atr_mult * atr), 2)

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
                        action_taken = f"Bought {qty_to_buy} @ ~${price:.2f} | TP: ${target_price:.2f}, SL: ${stop_price:.2f}"
                        owned_qty = qty_to_buy
                        tranche_alerts.append(f"🟢 **[{tranche_name}] BUY {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`, RSI: `{rsi_val}`)")
                    except Exception as e:
                        decision = "BULLISH"
                        action_taken = f"Buy Failed: {e}"
            elif score <= -0.10:
                decision = "BEARISH (Not Owned)"
            else:
                decision = "HOLD"

        row = [now_str, ticker, f"{score:+.3f}", decision, action_taken, f"Holding {int(owned_qty)} shares"]
        sheet_ws.append_row(row)
        print(f"[{tranche_name}] {ticker}: {score:+.3f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{ticker}**: FinBERT `{score:+.3f}` ({len(headlines)} news) | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(1)

    return tranche_alerts, scan_lines

# =====================================================================
# 4. ENGINE 3: 24/7 CRYPTO AI QUANT EXECUTOR
# =====================================================================
def run_crypto_tranche(positions_map, active_orders, equity):
    crypto_alerts = []
    scan_lines = []

    for pair in CRYPTO_PAIRS:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(pair)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(pair)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"

        norm_sym = to_alpaca_pos_symbol(pair)
        pos = positions_map.get(norm_sym) or positions_map.get(pair)
        owned_qty = float(pos.qty) if pos else 0.0
        decision = "HOLD"
        action_taken = "None"

        if owned_qty > 0:
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price

            exit_reason = None
            if unrealized_pct >= 0.060:
                exit_reason = f"Crypto Take-Profit Hit (+{unrealized_pct*100:.2f}%)"
            elif unrealized_pct <= -0.030:
                exit_reason = f"Crypto Stop-Loss Hit ({unrealized_pct*100:.2f}%)"
            elif score <= -0.15:
                exit_reason = f"Bearish Crypto Sentiment ({score:+.3f})"
            elif tech and tech['rsi14'] > 78.0 and unrealized_pct > 0.02:
                exit_reason = f"RSI Extreme Overbought Profit Lock (RSI {tech['rsi14']:.1f})"

            if exit_reason:
                try:
                    cancel_existing_orders_for_ticker(pair, active_orders)
                    sell_order = api.submit_order(
                        symbol=pair,
                        qty=owned_qty,
                        side='sell',
                        type='market',
                        time_in_force='gtc'
                    )
                    decision = "EXIT"
                    action_taken = f"Sold {owned_qty:.4f} @ ~${current_price:.2f} ({exit_reason})"
                    closed_sheet.append_row([
                        now_str[:19], pair, f"{owned_qty:.4f}", exit_reason, f"${current_price:.2f}", str(getattr(sell_order, 'id', 'CRYPTO_MKT'))
                    ])
                    owned_qty = 0.0
                    crypto_alerts.append(f"🪙 **[CRYPTO EXIT] {pair}**: {action_taken}")
                except Exception as e:
                    decision = "EXIT"
                    action_taken = f"Crypto Sell Failed: {e}"
            else:
                if unrealized_pct >= 0.025:
                    decision = "HOLD (🛡️ +2.5% Profit Trail Active)"
                elif score >= 0.05:
                    decision = "BULLISH (Holding)"
                else:
                    decision = "HOLD"
        else:
            is_bullish_ai = (score >= 0.05) and (tech is not None and tech['price'] >= tech['ema20'] and tech['rsi14'] < 70.0)
            is_oversold_bounce = (score >= 0.0) and (tech is not None and tech['rsi14'] <= 35.0 and tech['price'] >= tech['sma200'] * 0.95)

            if is_bullish_ai or is_oversold_bounce:
                target_dollars = equity * 0.020
                price = tech['price']
                qty_to_buy = round(target_dollars / price, 4)

                if qty_to_buy > 0:
                    try:
                        api.submit_order(
                            symbol=pair,
                            qty=qty_to_buy,
                            side='buy',
                            type='market',
                            time_in_force='gtc'
                        )
                        decision = "BULLISH"
                        trigger_lbl = "AI Breakout" if is_bullish_ai else "Oversold Bounce"
                        action_taken = f"Bought {qty_to_buy:.4f} @ ~${price:.2f} ({trigger_lbl} | Dynamic TP +6% / SL -3%)"
                        owned_qty = qty_to_buy
                        crypto_alerts.append(f"🪙 **[CRYPTO BUY] {pair}**: {action_taken} (FinBERT: `{score:+.3f}`, RSI: `{rsi_val}`)")
                    except Exception as e:
                        decision = "BULLISH"
                        action_taken = f"Crypto Buy Failed: {e}"
            elif score >= 0.05 and tech is not None and tech['price'] < tech['ema20']:
                decision = f"BULLISH (Blocked: Below 20-EMA ${tech['ema20']:.2f})"
            elif score <= -0.10:
                decision = "BEARISH (Not Owned)"
            else:
                decision = "HOLD"

        row = [now_str, pair, f"{score:+.3f}", decision, action_taken, f"Holding {owned_qty:.4f} units"]
        crypto_sheet.append_row(row)
        print(f"[CRYPTO] {pair}: {score:+.3f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{pair}**: FinBERT `{score:+.3f}` ({len(headlines)} news) | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(1)

    return crypto_alerts, scan_lines

# =====================================================================
# 5. MASTER ORCHESTRATOR
# =====================================================================
def run_bot(mode="all"):
    clock = api.get_clock()
    is_nyse_open = bool(clock.is_open)

    account = api.get_account()
    equity = float(account.equity)
    daytrade_count = int(getattr(account, 'daytrade_count', 0) or 0)
    pdt_restricted = daytrade_count >= 3

    raw_positions = api.list_positions()
    positions_map = {}
    for p in raw_positions:
        positions_map[p.symbol] = p
        positions_map[to_alpaca_pos_symbol(p.symbol)] = p

    active_orders = fetch_active_and_held_orders()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    automated_exit_alerts = sync_recent_closed_sells(closed_orders_24h)
    macro_ok, macro_reason = check_macro_regime()

    all_alerts = list(automated_exit_alerts)
    core_lines, mom_lines, crypto_lines = [], [], []

    # 1. Execute 24/7 Crypto AI Quant Tranche (Always runs 24/7/365!)
    if mode in ["all", "crypto"]:
        print("=== Running Engine 3: 24/7 Crypto AI Quant ===")
        c_alerts, crypto_lines = run_crypto_tranche(positions_map, active_orders, equity)
        all_alerts.extend(c_alerts)

    # 2. Execute Core & Momentum Equity Tranches (Requires NYSE Open)
    if mode in ["all", "core", "momentum"]:
        if not is_nyse_open:
            print("NYSE is currently CLOSED. Skipped Equity engines (24/7 Crypto AI ran normally).")
        else:
            if mode in ["all", "core"]:
                print("=== Running Engine 1: Core Long-Term Equities ===")
                core_alerts, core_lines = run_equity_tranche(
                    tranche_name="CORE",
                    tickers=CORE_TICKERS,
                    sheet_ws=core_sheet,
                    positions_map=positions_map,
                    active_orders=active_orders,
                    closed_orders_24h=closed_orders_24h,
                    equity=equity,
                    pdt_restricted=pdt_restricted,
                    macro_ok=macro_ok,
                    macro_reason=macro_reason,
                    buy_score_min=0.10,
                    exit_score_max=-0.15,
                    sl_atr_mult=1.5,
                    tp_atr_mult=3.5,
                    ratchet_trigger_pct=0.025,
                    alloc_pct=0.020,
                    require_sma200=True
                )
                all_alerts.extend(core_alerts)

            if mode in ["all", "momentum"]:
                print("=== Running Engine 2: Short-Term Momentum Equities ===")
                mom_alerts, mom_lines = run_equity_tranche(
                    tranche_name="MOMENTUM",
                    tickers=MOMENTUM_TICKERS,
                    sheet_ws=momentum_sheet,
                    positions_map=positions_map,
                    active_orders=active_orders,
                    closed_orders_24h=closed_orders_24h,
                    equity=equity,
                    pdt_restricted=pdt_restricted,
                    macro_ok=macro_ok,
                    macro_reason=macro_reason,
                    buy_score_min=0.05,
                    exit_score_max=-0.12,
                    sl_atr_mult=1.0,
                    tp_atr_mult=2.0,
                    ratchet_trigger_pct=0.015,
                    alloc_pct=0.015,
                    require_sma200=False
                )
                all_alerts.extend(mom_alerts)

    if all_alerts:
        send_discord_alert("🚨 **Multi-Strategy Bot v3.0 Execution Alert:**\n" + "\n".join(all_alerts))

    # =====================================================================
    # 6. POST-SCAN MULTI-STRATEGY DISCORD BRIEFING
    # =====================================================================
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

        positions_list = api.list_positions()
        ny_time = datetime.now(ZoneInfo("America/New_York"))
        total_unrealized_pl = sum(float(p.unrealized_pl) for p in positions_list)
        invested_val = sum(float(p.market_value) for p in positions_list)

        detailed_report = (
            f"🏛️ **Multi-Strategy Hedge Fund v3.0 Telemetry Report**\n"
            f"🕒 **Time (NY):** `{ny_time.strftime('%Y-%m-%d %I:%M %p')}` | 🏦 **NYSE:** `{'OPEN' if is_nyse_open else 'CLOSED (Crypto 24/7 Active)'}` | 🌍 **Macro:** `{macro_reason}`\n"
            f"💰 **Total Equity:** `${equity:,.2f}` (All-Time: `${total_pl:+,.2f}` / `{total_pl_pct:+.2f}%`)\n"
            f"📅 **Today's Change:** `${day_pl:+,.2f}` (`{day_pl_pct:+.2f}%`) | 📊 **Open P/L:** `${total_unrealized_pl:+,.2f}`\n"
            f"💵 **Cash:** `${cash:,.2f}` | 💼 **Invested:** `${invested_val:,.2f}` ({len(positions_list)} total positions)\n"
        )

        if core_lines:
            detailed_report += "\n🛡️ **Engine 1 — Core Long-Term Scan:**\n" + "\n".join(core_lines) + "\n"
        if mom_lines:
            detailed_report += "\n⚡ **Engine 2 — Short-Term Momentum Scan:**\n" + "\n".join(mom_lines) + "\n"
        if crypto_lines:
            detailed_report += "\n🪙 **Engine 3 — 24/7 Crypto AI Scan:**\n" + "\n".join(crypto_lines) + "\n"

        send_discord_alert(detailed_report)
    except Exception as e:
        print(f"Detailed portfolio report error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=os.environ.get("BOT_MODE", "all"), choices=["all", "core", "momentum", "crypto"])
    args = parser.parse_args()
    run_bot(mode=args.mode)
