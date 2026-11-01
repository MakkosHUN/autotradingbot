import json
import re
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
import alpaca_trade_api as tradeapi
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

# =====================================================================
# 1. PAGE CONFIG & INSTITUTIONAL DARK GLASSMORPHISM CSS
# =====================================================================
st.set_page_config(
    page_title="QUANT V3.0 // Multi-Strategy Command Center",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .stApp {
        background: radial-gradient(circle at top right, #0d1527 0%, #07090e 60%);
    }
    .block-container {
        padding-top: 1.3rem;
        padding-bottom: 2rem;
    }
    div[data-testid="stMetric"] {
        background: linear-gradient(145deg, rgba(17, 22, 34, 0.92), rgba(11, 14, 23, 0.92));
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-left: 3px solid #00FFAA;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 8px 28px rgba(0, 0, 0, 0.45);
    }
    div[data-testid="stMetricLabel"] > div {
        color: #8B949E !important;
        font-size: 0.82rem !important;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }
    div[data-testid="stMetricValue"] > div {
        font-family: 'Courier New', monospace;
        font-weight: 700;
        font-size: 1.75rem !important;
    }
    .terminal-header {
        background: linear-gradient(90deg, rgba(17,22,34,0.95) 0%, rgba(0,255,170,0.06) 100%);
        border: 1px solid rgba(0, 255, 170, 0.2);
        border-radius: 12px;
        padding: 18px 24px;
        margin-bottom: 18px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
    }
    .terminal-title {
        font-size: 1.5rem;
        font-weight: 800;
        letter-spacing: 1.2px;
        color: #FFFFFF;
        margin: 0;
    }
    .terminal-sub {
        color: #8B949E;
        font-size: 0.85rem;
        margin-top: 4px;
    }
    .status-pill {
        display: inline-block;
        padding: 5px 12px;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.8px;
        margin-left: 8px;
    }
    .pill-green {
        background: rgba(0, 255, 170, 0.12);
        color: #00FFAA;
        border: 1px solid rgba(0, 255, 170, 0.35);
    }
    .pill-amber {
        background: rgba(255, 184, 0, 0.12);
        color: #FFB800;
        border: 1px solid rgba(255, 184, 0, 0.35);
    }
    .pill-red {
        background: rgba(255, 75, 75, 0.12);
        color: #FF4B4B;
        border: 1px solid rgba(255, 75, 75, 0.35);
    }
    .pill-blue {
        background: rgba(56, 189, 248, 0.12);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.35);
    }
</style>
""", unsafe_allow_html=True)

CORE_TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG', 'CAT', 'DIS']
MOMENTUM_TICKERS = ['AMD', 'PLTR', 'META', 'COIN', 'NFLX', 'AMZN', 'CRM', 'UBER']
CRYPTO_PAIRS = ['BTC/USD', 'ETH/USD', 'SOL/USD', 'AVAX/USD', 'LINK/USD']
CRYPTO_NORM = {c.replace("/", ""): c for c in CRYPTO_PAIRS}

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in CORE_TICKERS:
        return "CORE"
    if sym in MOMENTUM_TICKERS:
        return "MOMENTUM"
    if sym in CRYPTO_PAIRS or s_clean in CRYPTO_NORM:
        return "CRYPTO"
    return "CORE"

# =====================================================================
# 2. CREDENTIALS & CONNECTION INITIALIZATION (WITH BUILT-IN FALLBACKS)
# =====================================================================
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

def get_secret(key, default=""):
    try:
        val = st.secrets.get(key, default)
        return val if val else default
    except Exception:
        return default

API_KEY = get_secret("APCA_API_KEY_ID", "PK24UBUQJRV4IZBY2PEP2RJA7I")
API_SECRET = get_secret("APCA_API_SECRET_KEY", "DbZoPN5n93m5T1g3PH6aiENiNgQhhpoAoVBrABfVkx7H")
GOOGLE_CREDS_RAW = get_secret("GOOGLE_CREDENTIALS", DEFAULT_GOOGLE_CREDS)
GITHUB_PAT = get_secret("GITHUB_PAT", "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")
BASE_URL = "https://paper-api.alpaca.markets"

@st.cache_resource
def init_alpaca():
    return tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

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

def connect_gsheets():
    try:
        if isinstance(GOOGLE_CREDS_RAW, str):
            creds_dict = json.loads(GOOGLE_CREDS_RAW, strict=False)
        else:
            creds_dict = dict(GOOGLE_CREDS_RAW)

        if "private_key" in creds_dict:
            creds_dict["private_key"] = repair_pem_key(creds_dict["private_key"])

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open("Auto-Trading Bot Log")
        return sh, "Connected"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

api = init_alpaca()
spreadsheet, sheet_status = connect_gsheets()

# =====================================================================
# 3. LIVE TELEMETRY FETCHERS
# =====================================================================
@st.cache_data(ttl=30)
def fetch_alpaca_state():
    clock_obj = api.get_clock()
    is_open = bool(clock_obj.is_open)

    account_obj = api.get_account()
    account_data = {
        "equity": float(account_obj.equity),
        "last_equity": float(getattr(account_obj, 'last_equity', account_obj.equity) or account_obj.equity),
        "cash": float(getattr(account_obj, 'cash', 0.0) or 0.0),
        "daytrade_count": int(getattr(account_obj, 'daytrade_count', 0) or 0)
    }

    positions_raw = api.list_positions()
    positions_data = []
    for p in positions_raw:
        raw_sym = str(p.symbol)
        display_sym = CRYPTO_NORM.get(raw_sym, raw_sym)
        positions_data.append({
            "symbol": display_sym,
            "raw_symbol": raw_sym,
            "tranche": classify_symbol(display_sym),
            "qty": float(p.qty),
            "avg_entry_price": float(p.avg_entry_price),
            "current_price": float(p.current_price),
            "market_value": float(p.market_value),
            "unrealized_pl": float(p.unrealized_pl),
            "unrealized_plpc": float(getattr(p, 'unrealized_plpc', 0.0) or 0.0)
        })

    active_orders = {}
    for o in api.list_orders(status='open', nested=True, limit=200):
        active_orders[o.id] = o
        if hasattr(o, 'legs') and o.legs:
            for leg in o.legs:
                if leg.status in ['new', 'held', 'accepted', 'partially_filled']:
                    active_orders[leg.id] = leg
    for o in api.list_orders(status='closed', nested=True, limit=200):
        if hasattr(o, 'legs') and o.legs:
            for leg in o.legs:
                if leg.status in ['new', 'held', 'accepted', 'partially_filled']:
                    active_orders[leg.id] = leg

    orders_data = []
    for o in list(active_orders.values()):
        raw_sym = str(o.symbol)
        display_sym = CRYPTO_NORM.get(raw_sym, raw_sym)
        orders_data.append({
            "id": str(o.id),
            "symbol": display_sym,
            "tranche": classify_symbol(display_sym),
            "side": str(o.side),
            "type": str(o.type),
            "status": str(o.status),
            "stop_price": float(o.stop_price) if getattr(o, 'stop_price', None) else None,
            "limit_price": float(o.limit_price) if getattr(o, 'limit_price', None) else None
        })

    recent_orders_raw = api.list_orders(status='all', limit=80)
    recent_data = []
    for o in recent_orders_raw:
        raw_sym = str(o.symbol)
        display_sym = CRYPTO_NORM.get(raw_sym, raw_sym)
        recent_data.append({
            "submitted_at": str(o.submitted_at),
            "symbol": display_sym,
            "tranche": classify_symbol(display_sym),
            "side": str(o.side),
            "type": str(o.type),
            "qty": str(o.qty),
            "filled_qty": str(getattr(o, 'filled_qty', '0')),
            "filled_avg_price": float(o.filled_avg_price) if getattr(o, 'filled_avg_price', None) else None,
            "limit_price": float(o.limit_price) if getattr(o, 'limit_price', None) else None,
            "stop_price": float(o.stop_price) if getattr(o, 'stop_price', None) else None,
            "status": str(o.status)
        })

    try:
        hist = api.get_portfolio_history(period="1M", timeframe="1D").df
    except Exception:
        hist = pd.DataFrame()

    return is_open, account_data, positions_data, orders_data, recent_data, hist

@st.cache_data(ttl=120)
def fetch_macro_telemetry():
    spy_chg, vix_val = 0.0, 0.0
    try:
        spy = yf.Ticker("SPY").history(period="2d")
        vix = yf.Ticker("^VIX").history(period="2d")
        if len(spy) >= 2:
            spy_chg = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]) * 100
        if not vix.empty:
            vix_val = float(vix['Close'].iloc[-1])
    except Exception:
        pass
    macro_ok = (spy_chg > -1.5) and (vix_val < 28.0)
    return macro_ok, spy_chg, vix_val

@st.cache_data(ttl=300)
def fetch_ticker_history(ticker):
    try:
        yf_sym = ticker.replace("/", "-")
        return yf.Ticker(yf_sym).history(period="1y")
    except Exception:
        return pd.DataFrame()

def parse_sheet_tab(ws):
    try:
        rows = ws.get_all_values()
        if len(rows) > 1:
            ncol = len(rows[0])
            default_cols = ["Timestamp", "Ticker", "FinBERT Score", "Decision", "Action Taken", "Position Status"]
            first_row = [str(c).strip() for c in rows[0]]
            if "Ticker" in first_row or "Timestamp" in first_row:
                cols = [c if c else f"Col_{i}" for i, c in enumerate(first_row)]
                data_rows = rows[1:]
            else:
                cols = default_cols[:ncol] + [f"Extra_{i}" for i in range(max(0, ncol - len(default_cols)))]
                data_rows = rows
            return pd.DataFrame(data_rows, columns=cols)
    except Exception:
        pass
    return pd.DataFrame()

@st.cache_data(ttl=60)
def fetch_all_sheet_logs():
    if not spreadsheet:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    df_core = parse_sheet_tab(spreadsheet.sheet1)
    try:
        df_mom = parse_sheet_tab(spreadsheet.worksheet("Momentum Log"))
    except Exception:
        df_mom = pd.DataFrame()
    try:
        df_crypto = parse_sheet_tab(spreadsheet.worksheet("Crypto Log"))
    except Exception:
        df_crypto = pd.DataFrame()
    try:
        closed_ws = spreadsheet.worksheet("Closed Trades")
        closed_rows = closed_ws.get_all_values()
        df_closed = pd.DataFrame(closed_rows[1:], columns=closed_rows[0]) if len(closed_rows) > 1 else pd.DataFrame()
    except Exception:
        df_closed = pd.DataFrame()
    return df_core, df_mom, df_crypto, df_closed

# =====================================================================
# 4. SIDEBAR COMMAND DECK & PAGE ROUTER
# =====================================================================
with st.sidebar:
    st.markdown("## ⚡ COMMAND DECK v3.0")

    @st.fragment(run_every="30s")
    def sidebar_live_clock():
        ny_now = datetime.now(ZoneInfo("America/New_York"))
        st.caption(f"🗽 **NYC Time:** `{ny_now.strftime('%Y-%m-%d %I:%M:%S %p')}` *(Auto-Sync: 30s)*")

    sidebar_live_clock()

    st.markdown("### 🧭 Strategy Command Pages")
    selected_page = st.radio(
        "Select Oversight View:",
        [
            "🏛️ Master Hedge Fund Overview",
            "🛡️ Engine 1: Core Long-Term",
            "⚡ Engine 2: Short-Term Momentum",
            "🪙 Engine 3: 24/7 Crypto AI"
        ],
        index=0
    )

    if st.button("🔄 Refresh Live Telemetry", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### 🚀 Remote Bot Trigger")
    st.caption("Dispatches all 3 engines on GitHub Actions immediately.")
    if st.button("⚡ Trigger 3-Engine Scan Now", use_container_width=True):
        resp = requests.post(
            "https://api.github.com/repos/MakkosHUN/autotradingbot/actions/workflows/schedule.yml/dispatches",
            headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
            json={"ref": "main"},
            timeout=10
        )
        if resp.status_code == 204:
            st.success("✅ 3-Engine Scan Dispatched! Completes in ~60s.")
        else:
            st.error(f"GitHub API Error ({resp.status_code}): {resp.text}")

    st.markdown("---")
    st.markdown("### 🛡️ System Safeguards")

    @st.fragment(run_every="30s")
    def sidebar_live_safeguards():
        _, acct_s, _, _, _, _ = fetch_alpaca_state()
        _, spy_s, vix_s = fetch_macro_telemetry()
        dt_count = int(acct_s.get('daytrade_count', 0))
        st.progress(min(dt_count / 3.0, 1.0), text=f"PDT Counter: {dt_count} / 3 Day Trades")
        st.markdown(f"**SPY 24h:** `{spy_s:+.2f}%`  \n**CBOE VIX:** `{vix_s:.1f}`")

    sidebar_live_safeguards()

    st.markdown("---")
    with st.expander("🚨 Emergency Override Controls"):
        st.warning("Use only in extreme black-swan events.")
        confirm_override = st.checkbox("Unlock Emergency Buttons")
        if st.button("Cancel All Open Orders", disabled=not confirm_override, use_container_width=True):
            api.cancel_all_orders()
            st.cache_data.clear()
            st.success("All open orders canceled.")
            st.rerun()
        if st.button("🔥 Liquidate All Positions", disabled=not confirm_override, use_container_width=True):
            api.close_all_positions(cancel_orders=True)
            st.cache_data.clear()
            st.error("All positions liquidated to cash.")
            st.rerun()

# =====================================================================
# 5. REUSABLE ENGINE RENDERER FOR PAGES 2, 3, AND 4
# =====================================================================
def render_strategy_engine_view(
    engine_title,
    engine_subtitle,
    tranche_key,
    universe_tickers,
    positions,
    active_orders,
    recent_orders,
    df_log,
    df_closed,
    equity,
    buy_thresh,
    exit_thresh,
    is_crypto=False
):
    tranche_pos = [p for p in positions if p['tranche'] == tranche_key]
    tranche_orders = [o for o in recent_orders if o['tranche'] == tranche_key]
    tranche_invested = sum(p['market_value'] for p in tranche_pos)
    tranche_pl = sum(p['unrealized_pl'] for p in tranche_pos)
    tranche_exposure = (tranche_invested / equity) * 100 if equity > 0 else 0.0

    st.markdown(f"### {engine_title}")
    st.caption(engine_subtitle)

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Tranche Invested Capital", f"${tranche_invested:,.2f}", f"{tranche_exposure:.1f}% of Total Equity")
    k2.metric("Tranche Open P/L", f"${tranche_pl:+,.2f}", f"{len(tranche_pos)} Active Holdings")
    k3.metric("Universe Size", f"{len(universe_tickers)} Assets", "24/7 Active" if is_crypto else "NYSE Market Hours")
    k4.metric("FinBERT Trigger Thresholds", f"Buy ≥ {buy_thresh:+.2f}", f"Exit ≤ {exit_thresh:+.2f}")

    st.markdown("<br>", unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs([
        "💼 Tranche Positions & Risk Matrix",
        "🧠 FinBERT Sentiment Radar & Sheet Logs",
        "🔬 Technical Trend Inspector",
        "📜 Tranche Order History"
    ])

    with t1:
        if not tranche_pos:
            st.info(f"No active positions currently open in the {tranche_key} tranche.")
        else:
            pos_rows = []
            for p in sorted(tranche_pos, key=lambda x: x['market_value'], reverse=True):
                sym = p['symbol']
                qty = p['qty']
                entry = p['avg_entry_price']
                curr = p['current_price']
                mkt_val = p['market_value']
                pl_dlr = p['unrealized_pl']
                pl_pct = ((curr - entry) / entry) * 100.0

                sl_price, tp_price = None, None
                if is_crypto:
                    sl_price = entry * 0.97
                    tp_price = entry * 1.06
                else:
                    for o in active_orders:
                        if o['symbol'] == sym and o['side'] == 'sell':
                            if o['type'] in ['stop', 'stop_limit'] and o['stop_price']:
                                sl_price = o['stop_price']
                            elif o['type'] == 'limit' and o['limit_price']:
                                tp_price = o['limit_price']

                if sl_price and tp_price and tp_price > sl_price:
                    range_progress = max(0.0, min(100.0, ((curr - sl_price) / (tp_price - sl_price)) * 100.0))
                else:
                    range_progress = 50.0

                if is_crypto:
                    shield_status = "🛡️ +2.5% TRAIL ACTIVE" if pl_pct >= 2.5 else "24/7 Dynamic TP/SL (+6% / -3%)"
                else:
                    shield_status = "🛡️ BREAK-EVEN LOCKED" if (sl_price and sl_price >= entry - 0.01) else ("⚡ RATCHET READY" if pl_pct >= 1.5 else "Active ATR Bracket")

                pos_rows.append({
                    "Ticker": sym,
                    "Qty": round(qty, 4) if is_crypto else int(qty),
                    "Market Value": mkt_val,
                    "Avg Entry": entry,
                    "Current Price": curr,
                    "Unrealized P/L ($)": pl_dlr,
                    "Return (%)": pl_pct,
                    "🛑 Stop-Loss": f"${sl_price:,.2f}" if sl_price else "None",
                    "🎯 Take-Profit": f"${tp_price:,.2f}" if tp_price else "None",
                    "SL ➔ TP Gauge": range_progress,
                    "Profit Shield": shield_status
                })

            df_pos = pd.DataFrame(pos_rows)
            col_table, col_pie = st.columns([2.3, 1])
            with col_table:
                st.subheader("🎯 Active Holdings & Risk Brackets")
                st.dataframe(
                    df_pos,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Market Value": st.column_config.NumberColumn("Market Value", format="$%.2f"),
                        "Avg Entry": st.column_config.NumberColumn("Avg Entry", format="$%.2f"),
                        "Current Price": st.column_config.NumberColumn("Live Price", format="$%.2f"),
                        "Unrealized P/L ($)": st.column_config.NumberColumn("Open P/L ($)", format="$%+.2f"),
                        "Return (%)": st.column_config.NumberColumn("Return (%)", format="%+.2f%%"),
                        "SL ➔ TP Gauge": st.column_config.ProgressColumn(
                            "SL ➔ TP Trajectory",
                            format="%.0f%%",
                            min_value=0,
                            max_value=100
                        )
                    }
                )

            with col_pie:
                st.subheader("🧩 Tranche Allocation")
                alloc_df = pd.DataFrame({
                    "Asset": [r["Ticker"] for r in pos_rows],
                    "Value": [r["Market Value"] for r in pos_rows]
                })
                fig_pie = px.pie(
                    alloc_df, values="Value", names="Asset", hole=0.65,
                    color_discrete_sequence=px.colors.sequential.Tealgrn
                )
                fig_pie.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Invested: $%{value:,.2f}<br>Tranche Share: %{percent}<extra></extra>"
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10), height=320,
                    legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5),
                    annotations=[dict(
                        text=(
                            f"<span style='color:#8B949E; font-size:11px;'>{tranche_key}</span><br>"
                            f"<b style='color:#FFFFFF; font-size:16px;'>${tranche_invested:,.2f}</b><br>"
                            f"<span style='color:#00FFAA; font-size:11px;'>{tranche_exposure:.1f}% of Equity</span>"
                        ),
                        x=0.5, y=0.5, font_size=13, showarrow=False
                    )]
                )
                st.plotly_chart(fig_pie, use_container_width=True)

            st.subheader("📊 Unrealized Profit / Loss by Position ($)")
            colors = ["#00FFAA" if x >= 0 else "#FF4B4B" for x in df_pos["Unrealized P/L ($)"]]
            fig_bar = go.Figure(go.Bar(
                x=df_pos["Ticker"], y=df_pos["Unrealized P/L ($)"],
                marker_color=colors,
                text=[f"${x:+.2f} ({p:+.2f}%)" for x, p in zip(df_pos["Unrealized P/L ($)"], df_pos["Return (%)"])],
                textposition="outside"
            ))
            fig_bar.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=290,
                margin=dict(t=25, b=10, l=10, r=10),
                yaxis=dict(title="Unrealized P/L ($)", gridcolor="rgba(255,255,255,0.06)")
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    with t2:
        st.subheader(f"🧠 Latest {tranche_key} FinBERT Sentiment Radar")
        if not df_log.empty:
            n_latest = len(universe_tickers)
            latest_df = df_log.tail(n_latest).copy()
            score_col = "FinBERT Score" if "FinBERT Score" in latest_df.columns else latest_df.columns[2]
            ticker_col = "Ticker" if "Ticker" in latest_df.columns else latest_df.columns[1]
            latest_df["Score_Num"] = pd.to_numeric(latest_df[score_col], errors="coerce").fillna(0.0)

            bar_colors = ["#00FFAA" if s >= buy_thresh else ("#FF4B4B" if s <= exit_thresh else "#64748B") for s in latest_df["Score_Num"]]
            fig_sent = go.Figure(go.Bar(
                x=latest_df[ticker_col], y=latest_df["Score_Num"],
                marker_color=bar_colors, text=latest_df[score_col], textposition="outside"
            ))
            fig_sent.add_hline(y=buy_thresh, line_dash="dash", line_color="#00FFAA", annotation_text=f"Buy ({buy_thresh:+.2f})")
            fig_sent.add_hline(y=exit_thresh, line_dash="dash", line_color="#FF4B4B", annotation_text=f"Exit ({exit_thresh:+.2f})")
            fig_sent.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=310,
                margin=dict(t=20, b=10, l=10, r=10),
                yaxis=dict(title="Net FinBERT Score (-1 to +1)", range=[-0.6, 0.9], gridcolor="rgba(255,255,255,0.06)")
            )
            st.plotly_chart(fig_sent, use_container_width=True)

            st.markdown(f"#### 📋 {tranche_key} Audit Log")
            st.dataframe(df_log.iloc[::-1].head(100), use_container_width=True, hide_index=True)
        else:
            st.info(f"✅ Ready! The `{tranche_key}` log worksheet will populate automatically on the next scan.")

    with t3:
        st.subheader(f"🔬 {tranche_key} Technical Trend Inspector")
        sel_ticker = st.selectbox(f"Select {tranche_key} Asset:", universe_tickers, index=0, key=f"sel_{tranche_key}")
        df_yf = fetch_ticker_history(sel_ticker).copy()
        if not df_yf.empty:
            df_yf["SMA200"] = df_yf["Close"].rolling(200).mean()
            df_yf["SMA50"] = df_yf["Close"].rolling(50).mean()
            df_yf["EMA20"] = df_yf["Close"].ewm(span=20, adjust=False).mean()
            df_plot = df_yf.tail(120)

            fig_candle = go.Figure()
            fig_candle.add_trace(go.Candlestick(
                x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
                low=df_plot["Low"], close=df_plot["Close"], name=sel_ticker,
                increasing_line_color="#00FFAA", decreasing_line_color="#FF4B4B"
            ))
            fig_candle.add_trace(go.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#38BDF8", width=1.8), name="20-EMA"))
            fig_candle.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA50"], line=dict(color="#A855F7", width=1.8, dash="dash"), name="50-SMA"))
            fig_candle.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], line=dict(color="#F59E0B", width=2.2, dash="dot"), name="200-SMA"))
            fig_candle.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=400,
                xaxis_rangeslider_visible=False, margin=dict(t=10, b=10, l=10, r=10),
                yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_candle, use_container_width=True)

    with t4:
        st.subheader(f"📜 {tranche_key} Order Book")
        if tranche_orders:
            st.dataframe(pd.DataFrame(tranche_orders), use_container_width=True, hide_index=True)
        else:
            st.info(f"No recent orders for {tranche_key} assets.")

# =====================================================================
# 6. AUTO-SYNCING MAIN TERMINAL
# =====================================================================
@st.fragment(run_every="30s")
def render_live_terminal():
    is_open, account, positions, active_orders, recent_orders, port_hist = fetch_alpaca_state()
    macro_ok, spy_chg, vix_val = fetch_macro_telemetry()
    df_core, df_mom, df_crypto, df_closed = fetch_all_sheet_logs()
    daytrades = int(account.get('daytrade_count', 0))

    mkt_badge = '<span class="status-pill pill-green">● NYSE OPEN</span>' if is_open else '<span class="status-pill pill-amber">● NYSE CLOSED</span>'
    crypto_badge = '<span class="status-pill pill-blue">🪙 CRYPTO 24/7 ACTIVE</span>'
    macro_badge = '<span class="status-pill pill-green">🛡️ MACRO NORMAL</span>' if macro_ok else '<span class="status-pill pill-red">⚠️ MACRO CRASH SHIELD</span>'
    pdt_badge = f'<span class="status-pill pill-green">PDT: {daytrades}/3 SAFE</span>' if daytrades < 3 else '<span class="status-pill pill-red">PDT LOCKED (3/3)</span>'

    st.markdown(f"""
    <div class="terminal-header">
        <div>
            <p class="terminal-title">⚡ QUANTITATIVE AI COMMAND CENTER // v3.0 MULTI-STRATEGY</p>
            <p class="terminal-sub">3-Tier Architecture: Core Long-Term Equities • Short-Term Momentum • 24/7 Crypto AI Quant</p>
        </div>
        <div>
            {mkt_badge}
            {crypto_badge}
            {macro_badge}
            {pdt_badge}
        </div>
    </div>
    """, unsafe_allow_html=True)

    equity = float(account.get('equity', 0.0))
    last_equity = float(account.get('last_equity', equity))
    cash = float(account.get('cash', 0.0))
    day_pl = equity - last_equity
    day_pl_pct = (day_pl / last_equity) * 100 if last_equity > 0 else 0.0
    all_time_pl = equity - 100000.0
    all_time_pct = (all_time_pl / 100000.0) * 100.0
    open_pl = sum(p['unrealized_pl'] for p in positions)
    invested = sum(p['market_value'] for p in positions)
    exposure_pct = (invested / equity) * 100 if equity > 0 else 0.0

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Net Liquidation Value", f"${equity:,.2f}", f"{all_time_pl:+,.2f} ({all_time_pct:+.2f}%) All-Time")
    c2.metric("Intraday P/L", f"${day_pl:+,.2f}", f"{day_pl_pct:+.2f}% Today")
    c3.metric("Total Open P/L", f"${open_pl:+,.2f}", f"{len(positions)} Total Positions")
    c4.metric("Total Invested Capital", f"${invested:,.2f}", f"{exposure_pct:.1f}% Portfolio Exposure")
    c5.metric("Available Cash Reserve", f"${cash:,.2f}", f"{100-exposure_pct:.1f}% Dry Powder")

    st.markdown("---")

    # -----------------------------------------------------------------
    # PAGE 1: MASTER HEDGE FUND OVERVIEW
    # -----------------------------------------------------------------
    if selected_page == "🏛️ Master Hedge Fund Overview":
        st.subheader("🏛️ 3-Tranche Strategy Performance & Capital Allocation")

        tranche_summary = []
        for t_key, t_label, t_risk in [
            ("CORE", "🛡️ Engine 1: Core Long-Term Equities", "Low Risk • 1.5x/3.5x ATR • 200-SMA Filter"),
            ("MOMENTUM", "⚡ Engine 2: Short-Term Momentum", "Mid Risk • 1.0x/2.0x ATR • Fast 20-EMA/50-SMA"),
            ("CRYPTO", "🪙 Engine 3: 24/7 Crypto AI Quant", "High Risk • 24/7 Execution • Dynamic +6%/-3%")
        ]:
            t_pos = [p for p in positions if p['tranche'] == t_key]
            t_val = sum(p['market_value'] for p in t_pos)
            t_pl = sum(p['unrealized_pl'] for p in t_pos)
            t_exp = (t_val / equity) * 100 if equity > 0 else 0.0
            tranche_summary.append({
                "Strategy Engine": t_label,
                "Risk Profile & Mandate": t_risk,
                "Active Positions": len(t_pos),
                "Invested Capital": t_val,
                "Portfolio Share (%)": t_exp,
                "Open Unrealized P/L ($)": t_pl
            })

        df_tranches = pd.DataFrame(tranche_summary)
        st.dataframe(
            df_tranches,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Invested Capital": st.column_config.NumberColumn("Invested Capital", format="$%.2f"),
                "Portfolio Share (%)": st.column_config.ProgressColumn("Allocation (% of Equity)", format="%.1f%%", min_value=0, max_value=100),
                "Open Unrealized P/L ($)": st.column_config.NumberColumn("Open P/L ($)", format="$%+.2f")
            }
        )

        col_ov1, col_ov2 = st.columns([1.3, 1])
        with col_ov1:
            st.subheader("📈 30-Day Master Portfolio Equity Curve")
            if not port_hist.empty and "equity" in port_hist.columns:
                df_eq = port_hist[port_hist["equity"] > 0].copy()
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=df_eq.index, y=df_eq["equity"], mode="lines+markers",
                    line=dict(color="#00FFAA", width=2.5), fill="tozeroy",
                    fillcolor="rgba(0, 255, 170, 0.08)", name="Equity"
                ))
                fig_eq.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=340,
                    margin=dict(t=15, b=15, l=10, r=10),
                    yaxis=dict(title="Account Equity ($)", gridcolor="rgba(255,255,255,0.06)")
                )
                st.plotly_chart(fig_eq, use_container_width=True)
            else:
                st.info("Portfolio history curve will populate as daily bars accumulate.")

        with col_ov2:
            st.subheader("🧩 Master Holdings Breakdown")
            if positions:
                alloc_df = pd.DataFrame({
                    "Asset": [f"{p['symbol']} ({p['tranche']})" for p in positions],
                    "Value": [p["market_value"] for p in positions]
                })
                fig_pie = px.pie(
                    alloc_df, values="Value", names="Asset", hole=0.65,
                    color_discrete_sequence=px.colors.sequential.Tealgrn
                )
                fig_pie.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Invested: $%{value:,.2f}<br>Share of Invested: %{percent}<extra></extra>"
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10), height=340,
                    showlegend=False,
                    annotations=[dict(
                        text=(
                            f"<span style='color:#8B949E; font-size:11px;'>TOTAL INVESTED</span><br>"
                            f"<b style='color:#FFFFFF; font-size:16px;'>${invested:,.2f}</b><br>"
                            f"<span style='color:#00FFAA; font-size:11px;'>{exposure_pct:.1f}% of Equity</span>"
                        ),
                        x=0.5, y=0.5, font_size=13, showarrow=False
                    )]
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Portfolio is currently 100% in cash.")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("#### 🏆 Automated Exits (`Closed Trades`)")
            if not df_closed.empty:
                st.dataframe(df_closed.iloc[::-1], use_container_width=True, hide_index=True)
            else:
                st.info("No closed exits logged yet.")
        with col_c2:
            st.markdown("#### 📜 Master Order Book (All Engines)")
            if recent_orders:
                st.dataframe(pd.DataFrame(recent_orders).head(30), use_container_width=True, hide_index=True)
            else:
                st.info("No recent orders found.")

    # -----------------------------------------------------------------
    # PAGE 2: ENGINE 1 — CORE LONG-TERM EQUITIES
    # -----------------------------------------------------------------
    elif selected_page == "🛡️ Engine 1: Core Long-Term":
        render_strategy_engine_view(
            engine_title="🛡️ Engine 1: Core Blue-Chip Trend Equities (Low Risk / Steady Alpha)",
            engine_subtitle="Universe: 12 S&P 500 Leaders • Filters: Price > 200-SMA & 20-EMA, Wilder's RSI < 72, FinBERT ≥ +0.10 • Brackets: 1.5x ATR Stop / 3.5x ATR Target (+2.5% Break-Even Ratchet)",
            tranche_key="CORE",
            universe_tickers=CORE_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_core,
            df_closed=df_closed,
            equity=equity,
            buy_thresh=0.10,
            exit_thresh=-0.15,
            is_crypto=False
        )

    # -----------------------------------------------------------------
    # PAGE 3: ENGINE 2 — SHORT-TERM MOMENTUM
    # -----------------------------------------------------------------
    elif selected_page == "⚡ Engine 2: Short-Term Momentum":
        render_strategy_engine_view(
            engine_title="⚡ Engine 2: Tactical Short-Term Momentum (Mid Risk / Mid Reward)",
            engine_subtitle="Universe: 8 High-Beta Tech & Growth Movers • Filters: 20-EMA > 50-SMA, Wilder's RSI < 72, FinBERT ≥ +0.05 • Brackets: Tight 1.0x ATR Stop / 2.0x ATR Target (+1.5% Fast Break-Even Ratchet)",
            tranche_key="MOMENTUM",
            universe_tickers=MOMENTUM_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_mom,
            df_closed=df_closed,
            equity=equity,
            buy_thresh=0.05,
            exit_thresh=-0.12,
            is_crypto=False
        )

    # -----------------------------------------------------------------
    # PAGE 4: ENGINE 3 — 24/7 CRYPTO AI QUANT
    # -----------------------------------------------------------------
    elif selected_page == "🪙 Engine 3: 24/7 Crypto AI":
        render_strategy_engine_view(
            engine_title="🪙 Engine 3: 24/7 Crypto AI Quant (High Risk / High Reward)",
            engine_subtitle="Universe: BTC/USD, ETH/USD, SOL/USD, AVAX/USD, LINK/USD • Runs 24/7/365 (Zero PDT Restrictions) • Dynamic +6.0% Take-Profit / -3.0% Stop-Loss / Oversold RSI Bounce & AI Breakout",
            tranche_key="CRYPTO",
            universe_tickers=CRYPTO_PAIRS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_crypto,
            df_closed=df_closed,
            equity=equity,
            buy_thresh=0.05,
            exit_thresh=-0.15,
            is_crypto=True
        )

render_live_terminal()
