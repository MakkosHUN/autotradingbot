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
# 1. INITIALIZE CONNECTIONS & SANITIZED CREDENTIALS
# =====================================================================
API_KEY = os.environ.get("APCA_API_KEY_ID", "").strip()
API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "").strip()
BASE_URL = "https://paper-api.alpaca.markets"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "https://share.streamlit.io").strip().rstrip("/")

api = tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

def repair_pem_key(pk_str):
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

raw_creds = os.environ.get("GOOGLE_CREDENTIALS", "{}").replace("\xa0", " ").replace("\u00a0", " ").strip()
try:
    creds_json = json.loads(raw_creds, strict=False)
except json.JSONDecodeError:
    try:
        import tomllib
        parsed = tomllib.loads(raw_creds)
        creds_json = parsed.get("GOOGLE_CREDENTIALS", parsed)
    except Exception:
        creds_json = {}

if "private_key" in creds_json:
    creds_json["private_key"] = repair_pem_key(creds_json["private_key"])

if creds_json:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    try:
        creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open("Auto-Trading Bot Log")
    except Exception as e:
        print(f"Google Sheets Auth Error: {e}")
        spreadsheet = None
else:
    spreadsheet = None

def get_or_create_worksheet(sh, title, headers):
    if not sh:
        return None
    try:
        ws = sh.worksheet(title)
    except Exception:
        ws = sh.add_worksheet(title=title, rows="2500", cols="12")
        ws.append_row(headers)
    return ws

LOG_HEADERS = ["Timestamp", "Ticker", "FinBERT Score", "Decision", "Action Taken", "Position Status"]
core_sheet = spreadsheet.sheet1 if spreadsheet else None
momentum_sheet = get_or_create_worksheet(spreadsheet, "Momentum Log", LOG_HEADERS)
crypto_sheet = get_or_create_worksheet(spreadsheet, "Crypto Log", LOG_HEADERS)
closed_sheet = get_or_create_worksheet(
    spreadsheet,
    "Closed Trades",
    ["Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID", "Engine", "Entry Price", "Realized P/L ($)", "Return (%)"]
)

# =====================================================================
# 2. EXPANDED 68-ASSET MASTER POOLS & DYNAMIC QUANT SCREENER
# =====================================================================
CORE_POOL = [
    'AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG',
    'CAT', 'DIS', 'V', 'MA', 'UNH', 'HD', 'COST', 'ABBV', 'KO', 'PEP',
    'AVGO', 'ORCL', 'CVX', 'MRK', 'BAC', 'LLY', 'MCD', 'TMO', 'CSCO', 'ACN'
]
MOMENTUM_POOL = [
    'AMD', 'PLTR', 'META', 'COIN', 'NFLX', 'AMZN', 'CRM', 'UBER', 'SHOP', 'XYZ',
    'SNOW', 'CRWD', 'PANW', 'DKNG', 'ROKU', 'HOOD', 'MARA', 'RIOT', 'SOFI', 'ARM',
    'SMCI', 'MU', 'INTC', 'MSTR'
]
CRYPTO_POOL = [
    'BTC/USD', 'ETH/USD', 'SOL/USD', 'AVAX/USD', 'LINK/USD', 'DOGE/USD', 'XRP/USD',
    'LTC/USD', 'AAVE/USD', 'DOT/USD', 'BCH/USD', 'SHIB/USD'
]
CRYPTO_NORM = {c.replace("/", ""): c for c in CRYPTO_POOL}

def to_yf_symbol(ticker):
    return ticker.replace("/", "-")

def to_alpaca_pos_symbol(ticker):
    return ticker.replace("/", "")

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in CORE_POOL:
        return "CORE"
    if sym in MOMENTUM_POOL:
        return "MOMENTUM"
    if sym in CRYPTO_POOL or s_clean in CRYPTO_NORM or sym.endswith("/USD") or sym.endswith("USD"):
        return "CRYPTO"
    return "CORE"

def screen_top_candidates(pool, top_n, owned_symbols, mode="core"):
    always_include = []
    for t in pool:
        if t in owned_symbols or to_alpaca_pos_symbol(t) in owned_symbols:
            always_include.append(t)

    remaining_pool = [t for t in pool if t not in always_include]
    slots_left = max(0, top_n - len(always_include))
    if slots_left == 0 or not remaining_pool:
        return always_include[:top_n]

    yf_map = {to_yf_symbol(t): t for t in remaining_pool}
    yf_list = list(yf_map.keys())

    scored = []
    try:
        data = yf.download(yf_list, period="5d", interval="1d", group_by="ticker", threads=True, progress=False)
        for yf_sym, orig_t in yf_map.items():
            try:
                df_t = data[yf_sym] if len(yf_list) > 1 else data
                df_t = df_t.dropna(subset=["Close"])
                if len(df_t) < 2:
                    continue
                close_now = float(df_t["Close"].iloc[-1])
                close_prev = float(df_t["Close"].iloc[-2])
                ret_1d = (close_now - close_prev) / close_prev if close_prev > 0 else 0.0

                vol_now = float(df_t["Volume"].iloc[-1]) if "Volume" in df_t.columns else 1.0
                vol_avg = float(df_t["Volume"].mean()) if "Volume" in df_t.columns and float(df_t["Volume"].mean()) > 0 else 1.0
                rel_vol = vol_now / vol_avg

                if mode == "momentum":
                    rank_score = (abs(ret_1d) * 100.0) * (1.0 + min(rel_vol, 3.0))
                elif mode == "crypto":
                    rank_score = (abs(ret_1d) * 100.0) + (rel_vol * 1.5)
                else:
                    rank_score = (ret_1d * 50.0) + rel_vol

                scored.append((rank_score, orig_t))
            except Exception:
                continue
    except Exception as e:
        print(f"Screener batch warning ({mode}): {e}")

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [t for _, t in scored[:slots_left]]

    for t in remaining_pool:
        if len(always_include) + len(selected) >= top_n:
            break
        if t not in selected:
            selected.append(t)

    final_list = always_include + selected
    print(f"[AI SCREENER - {mode.upper()}] Filtered {len(pool)} pool -> {len(final_list)} active candidates: {final_list}")
    return final_list

# =====================================================================
# 3. MATHEMATICAL ARBITER MATRIX & ATR RISK-PARITY SIZING
# =====================================================================
def compute_arbiter_matrix(finbert_score, tech, base_buy_min=0.05, base_exit_max=-0.15):
    """
    Mathematical Arbiter Matrix:
    Dynamically shifts decision weights between News Sentiment (FinBERT) and
    Technicals (EMA/SMA/RSI/Volume) based on catalyst intensity and volume spikes.
    Returns:
      dict with regime_label, w_news, w_tech, composite_score, tp_mult_adj,
      rsi_ceiling, should_buy, should_exit_profit_or_bearish
    """
    if tech is None:
        return {
            "regime": "NO-TECH",
            "w_news": 1.0,
            "w_tech": 0.0,
            "composite": finbert_score,
            "tp_adj": 1.0,
            "rsi_max": 72.0,
            "buy_signal": False,
            "arbiter_exit_reason": None
        }

    rel_vol = tech.get("rel_vol", 1.0)
    rsi = tech["rsi14"]
    price = tech["price"]
    ema9 = tech["ema9"]
    ema20 = tech["ema20"]
    sma50 = tech["sma50"]

    # Compute normalized Technical Score in [-1.0, +1.0]
    tech_score = 0.0
    if price > ema9 > ema20:
        tech_score += 0.45
    elif price > ema20:
        tech_score += 0.25
    else:
        tech_score -= 0.40

    if ema20 > sma50:
        tech_score += 0.25
    else:
        tech_score -= 0.20

    # RSI contribution (oversold bounce bonus or overbought penalty)
    if rsi <= 33.0:
        tech_score += 0.45
    elif 45.0 <= rsi <= 66.0:
        tech_score += 0.20
    elif rsi >= 76.0:
        tech_score -= 0.45

    tech_score = max(-1.0, min(1.0, tech_score))

    abs_news = abs(finbert_score)

    # Determine Regime Weighting (90/10 News, 50/50 Hybrid, or 10/90 Tech)
    if abs_news >= 0.65 or (abs_news >= 0.45 and rel_vol >= 1.8):
        regime = "NEWS-90/10"
        w_news, w_tech = 0.90, 0.10
        tp_adj = 1.45       # Widen Take-Profit by +45% to ride massive catalyst runner
        rsi_max = 84.0      # Ignore standard overbought RSI during major news catalysts
    elif abs_news >= 0.20 or rel_vol >= 1.35:
        regime = "HYBRID-50/50"
        w_news, w_tech = 0.50, 0.50
        tp_adj = 1.00
        rsi_max = 73.0
    else:
        regime = "TECH-10/90"
        w_news, w_tech = 0.10, 0.90
        tp_adj = 0.85       # Tighten Take-Profit by 15% for pure technical scalps
        rsi_max = 69.0

    composite = round((w_news * finbert_score) + (w_tech * tech_score), 3)

    # Entry Arbiter Decision
    buy_signal = False
    if regime == "NEWS-90/10" and finbert_score >= max(base_buy_min, 0.40) and price >= ema20 * 0.985:
        buy_signal = True
    elif regime == "HYBRID-50/50" and composite >= max(base_buy_min, 0.12) and price >= ema20:
        buy_signal = True
    elif regime == "TECH-10/90" and (
        (composite >= 0.22 and price > ema9 > ema20) or (rsi <= 32.5 and finbert_score > -0.25)
    ):
        buy_signal = True

    # Profit-Taking & Exit Arbiter Decision
    arbiter_exit_reason = None
    if regime == "NEWS-90/10" and finbert_score <= base_exit_max:
        arbiter_exit_reason = f"Arbiter 90/10 News Catalyst Reversal (FinBERT {finbert_score:+.3f})"
    elif regime == "TECH-10/90" and rsi >= 74.0 and finbert_score < 0.25:
        arbiter_exit_reason = f"Arbiter 10/90 Tech Overbought Profit-Take (RSI {rsi:.1f})"
    elif regime == "HYBRID-50/50" and composite <= base_exit_max and price < ema9:
        arbiter_exit_reason = f"Arbiter 50/50 Hybrid Breakdown (Comp {composite:+.3f})"

    return {
        "regime": regime,
        "w_news": w_news,
        "w_tech": w_tech,
        "tech_score": round(tech_score, 3),
        "composite": composite,
        "tp_adj": tp_adj,
        "rsi_max": rsi_max,
        "buy_signal": buy_signal,
        "arbiter_exit_reason": arbiter_exit_reason
    }

def compute_atr_risk_parity_qty(equity, price, atr, sl_atr_mult, risk_bps=0.0045, max_notional_pct=0.040, is_crypto=False):
    """
    ATR Volatility Risk-Parity Position Sizing:
    Ensures every position risks the exact same dollar percentage (risk_bps) of total account equity
    if its ATR Stop-Loss is hit, capped at max_notional_pct of total portfolio value.
    """
    if price <= 0 or equity <= 0:
        return 0
    safe_atr = max(atr, price * 0.01)
    stop_distance_dollars = max(sl_atr_mult * safe_atr, price * 0.008)
    dollar_risk_budget = equity * risk_bps

    raw_qty = dollar_risk_budget / stop_distance_dollars
    max_qty_by_notional = (equity * max_notional_pct) / price
    target_qty = min(raw_qty, max_qty_by_notional)

    if is_crypto:
        return round(max(0.0001, target_qty), 4)
    return max(1, int(round(target_qty)))

# =====================================================================
# 4. SHARED AI, NEWS & TECHNICAL HELPER FUNCTIONS
# =====================================================================
def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        print("Discord alert skipped: DISCORD_WEBHOOK_URL is empty.")
        return
    try:
        if len(message) <= 1950:
            r = requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
            if r.status_code >= 400:
                print(f"Discord HTTP {r.status_code}: {r.text}")
        else:
            lines = message.split("\n")
            chunk = ""
            for line in lines:
                if len(chunk) + len(line) + 1 > 1900:
                    requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=10)
                    time.sleep(0.5)
                    chunk = line + "\n"
                else:
                    chunk += line + "\n"
            if chunk:
                requests.post(DISCORD_WEBHOOK, json={"content": chunk}, timeout=10)
    except Exception as e:
        print(f"Discord alert error: {e}")

print("Loading ProsusAI/finbert financial AI model once into shared RAM...")
finbert = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None
)

def get_fresh_dual_news(ticker):
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
        if not vix.empty:
            vix_level = float(vix['Close'].iloc[-1])
        if len(spy) >= 2:
            spy_change = (spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]
            if spy_change <= -0.015:
                return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} (PANIC BLOCK)"
        if vix_level > 28.0:
            return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} (VIX BLOCK)"
        return True, f"Normal (SPY {spy_change*100:+.2f}%, VIX {vix_level:.1f})"
    except Exception as e:
        print(f"Macro check warning: {e}")
    return True, "Macro Normal"

def get_technicals_and_atr(ticker):
    yf_sym = to_yf_symbol(ticker)
    df = yf.Ticker(yf_sym).history(period="1y")
    if df.empty or len(df) < 30:
        return None
    close = df['Close']
    current_price = float(close.iloc[-1])
    sma200 = float(close.rolling(200).mean().iloc[-1]) if len(df) >= 200 else float(close.mean())
    sma50 = float(close.rolling(50).mean().iloc[-1]) if len(df) >= 50 else float(close.mean())
    ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
    ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])

    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0

    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - close.shift())
    low_close = np.abs(df['Low'] - close.shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    atr_series = true_range.rolling(14).mean()
    atr14 = float(atr_series.iloc[-1]) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (current_price * 0.02)

    vol_series = df['Volume'] if 'Volume' in df.columns else pd.Series([1.0])
    vol_20d = float(vol_series.tail(20).mean()) if len(vol_series) >= 5 and float(vol_series.tail(20).mean()) > 0 else 1.0
    vol_now = float(vol_series.iloc[-1]) if len(vol_series) > 0 else 1.0
    rel_vol = round(vol_now / vol_20d, 2) if vol_20d > 0 else 1.0

    return {
        "price": current_price,
        "sma200": sma200,
        "sma50": sma50,
        "ema20": ema20,
        "ema9": ema9,
        "rsi14": rsi14,
        "atr14": atr14,
        "rel_vol": rel_vol
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

def find_last_buy_fill_price(symbol, closed_orders):
    norm = to_alpaca_pos_symbol(symbol)
    for o in closed_orders:
        if to_alpaca_pos_symbol(o.symbol) == norm and o.side == 'buy' and o.status == 'filled' and getattr(o, 'filled_avg_price', None):
            return float(o.filled_avg_price)
    return 0.0

def sync_recent_closed_sells(closed_orders):
    if not closed_sheet:
        return []
    new_fill_alerts = []
    try:
        existing_ids = set(closed_sheet.col_values(6))
        for o in closed_orders:
            if o.side == 'sell' and o.status == 'filled' and o.id not in existing_ids:
                filled_time = str(o.filled_at)[:19] if o.filled_at else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                fill_price = float(o.filled_avg_price) if o.filled_avg_price else 0.0
                qty_val = float(o.filled_qty) if o.filled_qty else 0.0
                order_type = o.type.upper()
                engine_tag = classify_symbol(o.symbol)
                entry_est = find_last_buy_fill_price(o.symbol, closed_orders)
                if entry_est > 0 and fill_price > 0:
                    realized_pl = (fill_price - entry_est) * qty_val
                    realized_pct = ((fill_price - entry_est) / entry_est) * 100.0
                else:
                    realized_pl, realized_pct = 0.0, 0.0

                closed_sheet.append_row([
                    filled_time,
                    o.symbol,
                    str(o.filled_qty),
                    order_type,
                    f"${fill_price:.2f}",
                    o.id,
                    engine_tag,
                    f"${entry_est:.2f}" if entry_est > 0 else "N/A",
                    f"${realized_pl:+.2f}",
                    f"{realized_pct:+.2f}%"
                ])
                existing_ids.add(o.id)
                if o.type in ['stop', 'stop_limit']:
                    new_fill_alerts.append(f"🛑 **STOP-LOSS TRIGGERED ({o.symbol} | {engine_tag})**: Sold {o.filled_qty} @ `${fill_price:.2f}` (P/L: `${realized_pl:+.2f}` / `{realized_pct:+.2f}%`)")
                elif o.type == 'limit':
                    new_fill_alerts.append(f"🎯 **TAKE-PROFIT HIT ({o.symbol} | {engine_tag})**: Sold {o.filled_qty} @ `${fill_price:.2f}` (P/L: `${realized_pl:+.2f}` / `{realized_pct:+.2f}%`)")
    except Exception as e:
        print(f"Closed trades sheet sync warning: {e}")
    return new_fill_alerts

# =====================================================================
# 5. ENGINE 1 & 2: EQUITY TRANCHE EXECUTOR (ARBITER + ATR RISK PARITY)
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
    is_nyse_open,
    buy_score_min,
    exit_score_max,
    sl_atr_mult,
    tp_atr_mult,
    ratchet_trigger_pct,
    risk_bps,
    require_sma200=True
):
    tranche_alerts = []
    scan_lines = []
    rows_to_append = []

    for ticker in tickers:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(ticker)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(ticker)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"
        arb = compute_arbiter_matrix(score, tech, base_buy_min=buy_score_min, base_exit_max=exit_score_max)
        regime_tag = arb["regime"]

        pos = positions_map.get(ticker)
        owned_qty = float(pos.qty) if pos else 0.0
        decision = f"HOLD [{regime_tag}]"
        action_taken = "None"

        if owned_qty > 0:
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price
            unrealized_dlr = (current_price - entry_price) * owned_qty

            # Arbiter Profit-Taking or Bearish Catalyst Exit
            should_exit = (score <= exit_score_max) or (arb["arbiter_exit_reason"] is not None and unrealized_pct > 0.005)
            exit_label = arb["arbiter_exit_reason"] or f"Bearish Sentiment ({score:+.3f})"

            if should_exit:
                if not is_nyse_open:
                    decision = f"EXIT QUEUED [{regime_tag}]"
                    action_taken = f"Awaiting NYSE Open ({exit_label})"
                elif pdt_restricted:
                    decision = "EXIT BLOCKED (PDT Shield)"
                    action_taken = "Skipped sell to prevent PDT lock"
                else:
                    try:
                        cancel_existing_orders_for_ticker(ticker, active_orders)
                        sell_ord = api.submit_order(
                            symbol=ticker,
                            qty=owned_qty,
                            side='sell',
                            type='market',
                            time_in_force='gtc'
                        )
                        decision = f"ARBITER EXIT [{regime_tag}]"
                        action_taken = f"Sold {int(owned_qty)} @ ~${current_price:.2f} ({exit_label})"
                        if closed_sheet:
                            closed_sheet.append_row([
                                now_str[:19], ticker, str(int(owned_qty)), exit_label[:28],
                                f"${current_price:.2f}", str(getattr(sell_ord, 'id', 'EQ_MKT')),
                                tranche_name, f"${entry_price:.2f}", f"${unrealized_dlr:+.2f}", f"{unrealized_pct*100:+.2f}%"
                            ])
                        owned_qty = 0
                        tranche_alerts.append(f"🔴 **[{tranche_name} | {regime_tag}] EXIT {ticker}**: {action_taken} (P/L: `${unrealized_dlr:+.2f}`)")
                    except Exception as e:
                        decision = "BEARISH"
                        action_taken = f"Sell Failed: {e}"
            else:
                if is_nyse_open and unrealized_pct >= ratchet_trigger_pct:
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

                decision = f"BULLISH (Owned | {regime_tag})" if arb["buy_signal"] else f"HOLD [{regime_tag}]"
        else:
            if arb["buy_signal"]:
                if not is_nyse_open:
                    decision = f"BULLISH (Radar | {regime_tag})"
                    action_taken = f"Pre-Market Target @ ~${tech['price']:.2f} (Comp {arb['composite']:+.2f})" if tech else "Queued Radar"
                elif not macro_ok:
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
                elif not require_sma200 and tech['ema20'] < tech['sma50'] and regime_tag != "NEWS-90/10":
                    decision = "BULLISH (Blocked: 20-EMA < 50-SMA)"
                elif tech[' rsi14' if ' rsi14' in tech else 'rsi14'] > arb["rsi_max"]:
                    decision = f"BULLISH (Blocked: RSI {tech['rsi14']:.1f} > {arb['rsi_max']:.0f})"
                else:
                    price = tech['price']
                    atr = max(tech['atr14'], price * 0.01)
                    qty_to_buy = compute_atr_risk_parity_qty(
                        equity=equity,
                        price=price,
                        atr=atr,
                        sl_atr_mult=sl_atr_mult,
                        risk_bps=risk_bps,
                        max_notional_pct=0.040,
                        is_crypto=False
                    )

                    adj_tp_mult = round(tp_atr_mult * arb["tp_adj"], 2)
                    stop_price = round(price - (sl_atr_mult * atr), 2)
                    target_price = round(price + (adj_tp_mult * atr), 2)

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
                        decision = f"BULLISH [{regime_tag}]"
                        action_taken = f"Risk-Parity Bought {qty_to_buy} @ ~${price:.2f} | TP: ${target_price:.2f} ({adj_tp_mult}x ATR), SL: ${stop_price:.2f}"
                        owned_qty = qty_to_buy
                        tranche_alerts.append(f"🟢 **[{tranche_name} | {regime_tag}] BUY {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`, Comp: `{arb['composite']:+.3f}`)")
                    except Exception as e:
                        decision = f"BULLISH [{regime_tag}]"
                        action_taken = f"Buy Failed: {e}"
            elif score <= -0.10:
                decision = f"BEARISH (Not Owned | {regime_tag})"
            else:
                decision = f"HOLD [{regime_tag}]"

        row = [now_str, ticker, f"{score:+.3f}", decision, action_taken, f"Holding {int(owned_qty)} shares"]
        rows_to_append.append(row)
        print(f"[{tranche_name}] {ticker}: {score:+.3f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{ticker}** `[{regime_tag}]`: FinBERT `{score:+.3f}` | Comp `{arb['composite']:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.4)

    if rows_to_append and sheet_ws:
        try:
            sheet_ws.append_rows(rows_to_append)
        except Exception as e:
            print(f"Batch sheet write warning ({tranche_name}): {e}")

    return tranche_alerts, scan_lines

# =====================================================================
# 6. ENGINE 3: 24/7 CRYPTO AI QUANT EXECUTOR (ARBITER + RISK PARITY)
# =====================================================================
def run_crypto_tranche(crypto_candidates, positions_map, active_orders, equity):
    crypto_alerts = []
    scan_lines = []
    rows_to_append = []

    for pair in crypto_candidates:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(pair)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(pair)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"
        arb = compute_arbiter_matrix(score, tech, base_buy_min=0.05, base_exit_max=-0.20)
        regime_tag = arb["regime"]

        norm_sym = to_alpaca_pos_symbol(pair)
        pos = positions_map.get(norm_sym) or positions_map.get(pair)
        owned_qty = float(pos.qty) if pos else 0.0
        decision = f"HOLD [{regime_tag}]"
        action_taken = "None"

        if owned_qty > 0:
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price
            unrealized_dlr = (current_price - entry_price) * owned_qty

            # Dynamic Arbiter Target (+9.0% in 90/10 News Catalyst, +6.0% in Hybrid, +4.8% in 10/90 Tech)
            dynamic_tp_pct = 0.060 * arb["tp_adj"]
            exit_reason = None
            if unrealized_pct >= dynamic_tp_pct:
                exit_reason = f"Arbiter Take-Profit Hit (+{unrealized_pct*100:.2f}% in {regime_tag})"
            elif unrealized_pct <= -0.030:
                exit_reason = f"Crypto Stop-Loss Hit ({unrealized_pct*100:.2f}%)"
            elif arb["arbiter_exit_reason"] and unrealized_pct > 0.005:
                exit_reason = arb["arbiter_exit_reason"]
            elif score <= -0.25:
                exit_reason = f"Bearish Crypto Catalyst ({score:+.3f})"

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
                    decision = f"EXIT [{regime_tag}]"
                    action_taken = f"Sold {owned_qty:.4f} @ ~${current_price:.2f} ({exit_reason})"
                    if closed_sheet:
                        closed_sheet.append_row([
                            now_str[:19], pair, f"{owned_qty:.4f}", exit_reason[:28],
                            f"${current_price:.2f}", str(getattr(sell_order, 'id', 'CRYPTO_MKT')),
                            "CRYPTO", f"${entry_price:.2f}", f"${unrealized_dlr:+.2f}", f"{unrealized_pct*100:+.2f}%"
                        ])
                    owned_qty = 0.0
                    crypto_alerts.append(f"🪙 **[CRYPTO EXIT | {regime_tag}] {pair}**: {action_taken} (P/L: `${unrealized_dlr:+.2f}`)")
                except Exception as e:
                    decision = "EXIT"
                    action_taken = f"Crypto Sell Failed: {e}"
            else:
                if unrealized_pct >= 0.025:
                    decision = f"HOLD (🛡️ +2.5% Trail | {regime_tag})"
                elif arb["buy_signal"]:
                    decision = f"BULLISH (Holding | {regime_tag})"
                else:
                    decision = f"HOLD [{regime_tag}]"
        else:
            if arb["buy_signal"] and tech is not None:
                price = tech['price']
                atr = max(tech['atr14'], price * 0.015)
                qty_to_buy = compute_atr_risk_parity_qty(
                    equity=equity,
                    price=price,
                    atr=atr,
                    sl_atr_mult=1.2,
                    risk_bps=0.0045,
                    max_notional_pct=0.035,
                    is_crypto=True
                )
                dyn_tp = round(6.0 * arb["tp_adj"], 1)

                if qty_to_buy > 0:
                    try:
                        api.submit_order(
                            symbol=pair,
                            qty=qty_to_buy,
                            side='buy',
                            type='market',
                            time_in_force='gtc'
                        )
                        decision = f"BULLISH [{regime_tag}]"
                        action_taken = f"Risk-Parity Bought {qty_to_buy:.4f} @ ~${price:.2f} ({regime_tag} | TP +{dyn_tp}% / SL -3%)"
                        owned_qty = qty_to_buy
                        crypto_alerts.append(f"🪙 **[CRYPTO BUY | {regime_tag}] {pair}**: {action_taken} (FinBERT: `{score:+.3f}`, Comp: `{arb['composite']:+.2f}`)")
                    except Exception as e:
                        decision = f"BULLISH [{regime_tag}]"
                        action_taken = f"Crypto Buy Failed: {e}"
            elif score <= -0.10:
                decision = f"BEARISH (Not Owned | {regime_tag})"
            else:
                decision = f"HOLD [{regime_tag}]"

        row = [now_str, pair, f"{score:+.3f}", decision, action_taken, f"Holding {owned_qty:.4f} units"]
        rows_to_append.append(row)
        print(f"[CRYPTO] {pair}: {score:+.3f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{pair}** `[{regime_tag}]`: FinBERT `{score:+.3f}` | Comp `{arb['composite']:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.4)

    if rows_to_append and crypto_sheet:
        try:
            crypto_sheet.append_rows(rows_to_append)
        except Exception as e:
            print(f"Batch sheet write warning (CRYPTO): {e}")

    return crypto_alerts, scan_lines

# =====================================================================
# 7. MASTER ORCHESTRATOR & INTERACTIVE DISCORD TELEMETRY
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
    owned_symbols = set()
    for p in raw_positions:
        positions_map[p.symbol] = p
        positions_map[to_alpaca_pos_symbol(p.symbol)] = p
        owned_symbols.add(p.symbol)
        owned_symbols.add(to_alpaca_pos_symbol(p.symbol))

    active_orders = fetch_active_and_held_orders()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    automated_exit_alerts = sync_recent_closed_sells(closed_orders_24h)
    macro_ok, macro_reason = check_macro_regime()

    all_alerts = list(automated_exit_alerts)
    core_lines, mom_lines, crypto_lines = [], [], []

    if mode in ["all", "crypto"]:
        print("=== Screening & Running Engine 3: 24/7 Crypto AI Quant ===")
        crypto_candidates = screen_top_candidates(CRYPTO_POOL, top_n=6, owned_symbols=owned_symbols, mode="crypto")
        c_alerts, crypto_lines = run_crypto_tranche(crypto_candidates, positions_map, active_orders, equity)
        all_alerts.extend(c_alerts)

    if mode in ["all", "core"]:
        print("=== Screening & Running Engine 1: Core Long-Term Equities ===")
        core_candidates = screen_top_candidates(CORE_POOL, top_n=10, owned_symbols=owned_symbols, mode="core")
        core_alerts, core_lines = run_equity_tranche(
            tranche_name="CORE",
            tickers=core_candidates,
            sheet_ws=core_sheet,
            positions_map=positions_map,
            active_orders=active_orders,
            closed_orders_24h=closed_orders_24h,
            equity=equity,
            pdt_restricted=pdt_restricted,
            macro_ok=macro_ok,
            macro_reason=macro_reason,
            is_nyse_open=is_nyse_open,
            buy_score_min=0.10,
            exit_score_max=-0.15,
            sl_atr_mult=1.5,
            tp_atr_mult=3.5,
            ratchet_trigger_pct=0.025,
            risk_bps=0.0050,
            require_sma200=True
        )
        all_alerts.extend(core_alerts)

    if mode in ["all", "momentum"]:
        print("=== Screening & Running Engine 2: Short-Term Momentum Equities ===")
        mom_candidates = screen_top_candidates(MOMENTUM_POOL, top_n=8, owned_symbols=owned_symbols, mode="momentum")
        mom_alerts, mom_lines = run_equity_tranche(
            tranche_name="MOMENTUM",
            tickers=mom_candidates,
            sheet_ws=momentum_sheet,
            positions_map=positions_map,
            active_orders=active_orders,
            closed_orders_24h=closed_orders_24h,
            equity=equity,
            pdt_restricted=pdt_restricted,
            macro_ok=macro_ok,
            macro_reason=macro_reason,
            is_nyse_open=is_nyse_open,
            buy_score_min=0.05,
            exit_score_max=-0.12,
            sl_atr_mult=1.0,
            tp_atr_mult=2.0,
            ratchet_trigger_pct=0.015,
            risk_bps=0.0040,
            require_sma200=False
        )
        all_alerts.extend(mom_alerts)

    if all_alerts:
        send_discord_alert("🚨 **AETHER QUANT v5.0 Execution Alert (Arbiter + Risk Parity):**\n" + "\n".join(all_alerts))

    # =====================================================================
    # 8. POST-SCAN MULTI-STRATEGY BRIEFING + MOBILE COMMAND LINKS
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
        active_orders = fetch_active_and_held_orders()
        ny_time = datetime.now(ZoneInfo("America/New_York"))
        total_unrealized_pl = sum(float(p.unrealized_pl) for p in positions_list)
        invested_val = sum(float(p.market_value) for p in positions_list)

        detailed_report = (
            f"💠 **AETHER QUANT v5.0 Telemetry Report (Arbiter Matrix + ATR Risk Parity)**\n"
            f"🕒 **Time (NY):** `{ny_time.strftime('%Y-%m-%d %I:%M %p')}` | 🏦 **NYSE:** `{'OPEN' if is_nyse_open else 'CLOSED (24/7 Radar & Crypto Active)'}` | 🌍 **Macro:** `{macro_reason}`\n"
            f"💰 **Total Equity:** `${equity:,.2f}` (All-Time: `${total_pl:+,.2f}` / `{total_pl_pct:+.2f}%`)\n"
            f"📅 **Today's Change:** `${day_pl:+,.2f}` (`{day_pl_pct:+.2f}%`) | 📊 **Open P/L:** `${total_unrealized_pl:+,.2f}`\n"
            f"💵 **Cash:** `${cash:,.2f}` | 💼 **Invested:** `${invested_val:,.2f}` ({len(positions_list)} total positions)\n\n"
            f"📈 **Active Portfolio Breakdown ({len(positions_list)}):**\n"
        )

        for p in sorted(positions_list, key=lambda x: float(x.market_value), reverse=True):
            sym = CRYPTO_NORM.get(str(p.symbol), str(p.symbol))
            qty = float(p.qty)
            entry = float(p.avg_entry_price)
            curr = float(p.current_price)
            mkt_val = float(p.market_value)
            pl_dollar = float(p.unrealized_pl)
            pl_pct = float(p.unrealized_plpc) * 100 if hasattr(p, 'unrealized_plpc') and p.unrealized_plpc else ((curr - entry) / entry) * 100

            sym_orders = get_all_orders_for_ticker(sym, active_orders)
            stop_str = "None"
            tp_str = "None"
            tranche_tag = classify_symbol(sym)

            if tranche_tag == "CRYPTO":
                qty_str = f"{qty:.4f} units"
                stop_str = f"${entry * 0.97:.2f}"
                tp_str = f"${entry * 1.06:.2f}"
            else:
                qty_str = f"{int(qty)} sh"
                for o in sym_orders:
                    if o.side == 'sell':
                        if o.type in ['stop', 'stop_limit'] and o.stop_price:
                            stop_str = f"${float(o.stop_price):.2f}"
                        elif o.type == 'limit' and o.limit_price:
                            tp_str = f"${float(o.limit_price):.2f}"

            detailed_report += (
                f"• **{sym}** `({tranche_tag})` ({qty_str} | `${mkt_val:,.0f}`): "
                f"`${entry:.2f}` ➔ `${curr:.2f}` | P/L: `${pl_dollar:+,.2f}` (`{pl_pct:+.2f}%`) | "
                f"🎯 TP: `{tp_str}` | 🛑 SL: `{stop_str}`\n"
            )

        if core_lines:
            detailed_report += "\n🛡️ **Engine 1 — Screened Core Blue-Chips:**\n" + "\n".join(core_lines) + "\n"
        if mom_lines:
            detailed_report += "\n⚡ **Engine 2 — Screened Short-Term Momentum:**\n" + "\n".join(mom_lines) + "\n"
        if crypto_lines:
            detailed_report += "\n🪙 **Engine 3 — Screened 24/7 Crypto AI:**\n" + "\n".join(crypto_lines) + "\n"

        # Interactive Mobile Discord Command Bar
        detailed_report += (
            f"\n🎛️ **Mobile One-Tap Command Deck:**\n"
            f"[🔄 Scan All]({DASHBOARD_URL}/?discord_cmd=scan_all)  |  "
            f"[⚡ Scan Momentum]({DASHBOARD_URL}/?discord_cmd=scan_momentum)  |  "
            f"[🪙 Scan Crypto]({DASHBOARD_URL}/?discord_cmd=scan_crypto)  |  "
            f"[📊 Push Snapshot]({DASHBOARD_URL}/?discord_cmd=snapshot)  |  "
            f"[🛑 Liquidate Crypto]({DASHBOARD_URL}/?discord_cmd=liquidate_crypto)"
        )

        send_discord_alert(detailed_report)
    except Exception as e:
        print(f"Detailed portfolio report error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default=os.environ.get("BOT_MODE", "all"), choices=["all", "core", "momentum", "crypto"])
    args = parser.parse_args()
    run_bot(mode=args.mode)
