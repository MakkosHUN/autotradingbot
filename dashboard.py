import json
import re
import requests
from datetime import datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
import alpaca_trade_api as tradeapi
import yfinance as yf
import gspread
from google.oauth2.service_account import Credentials

# =====================================================================
# 1. PAGE CONFIG & MILLION-DOLLAR OBSIDIAN QUANT CSS
# =====================================================================
st.set_page_config(
    page_title="AETHER QUANT // Institutional Terminal",
    page_icon="💠",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        color: #E2E8F0;
    }

    /* Hide default Streamlit chrome for native desktop terminal feel */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {background: transparent !important;}

    .stApp {
        background-color: #05070B;
        background-image: 
            radial-gradient(at 0% 0%, rgba(16, 185, 129, 0.05) 0px, transparent 45%),
            radial-gradient(at 100% 0%, rgba(56, 189, 248, 0.06) 0px, transparent 50%),
            radial-gradient(at 50% 100%, rgba(99, 102, 241, 0.04) 0px, transparent 50%);
    }

    .block-container {
        padding-top: 1.0rem !important;
        padding-bottom: 2.5rem !important;
        max-width: 97% !important;
    }

    /* Scrolling Live Telemetry Ticker Tape */
    @keyframes ticker-slide {
        0% { transform: translateX(0%); }
        100% { transform: translateX(-50%); }
    }
    .ticker-wrap {
        width: 100%;
        overflow: hidden;
        background: rgba(11, 15, 25, 0.85);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 8px;
        padding: 7px 0;
        margin-bottom: 14px;
        white-space: nowrap;
        box-shadow: inset 0 1px 0 0 rgba(255,255,255,0.04);
    }
    .ticker-move {
        display: inline-block;
        animation: ticker-slide 38s linear infinite;
    }
    .ticker-wrap:hover .ticker-move {
        animation-play-state: paused;
    }
    .ticker-item {
        display: inline-block;
        padding: 0 22px;
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.76rem;
        color: #94A3B8;
        border-right: 1px solid rgba(255,255,255,0.06);
    }
    .ticker-sym { color: #F8FAFC; font-weight: 600; margin-right: 6px; }
    .up { color: #10B981; font-weight: 600; }
    .down { color: #F43F5E; font-weight: 600; }
    .flat { color: #38BDF8; font-weight: 600; }

    /* Top Institutional Telemetry Bar */
    .inst-header {
        background: linear-gradient(180deg, rgba(15, 23, 42, 0.75) 0%, rgba(9, 13, 22, 0.85) 100%);
        backdrop-filter: blur(16px);
        -webkit-backdrop-filter: blur(16px);
        border: 1px solid rgba(255, 255, 255, 0.08);
        border-top: 1px solid rgba(255, 255, 255, 0.14);
        border-radius: 12px;
        padding: 16px 24px;
        margin-bottom: 16px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 12px;
        box-shadow: 0 12px 32px -8px rgba(0, 0, 0, 0.6);
    }
    .brand-cluster {
        display: flex;
        align-items: center;
        gap: 14px;
    }
    .brand-orb {
        width: 10px;
        height: 36px;
        border-radius: 4px;
        background: linear-gradient(180deg, #10B981 0%, #38BDF8 100%);
        box-shadow: 0 0 14px rgba(16, 185, 129, 0.45);
    }
    .brand-title {
        font-size: 1.25rem;
        font-weight: 700;
        letter-spacing: 0.5px;
        color: #F8FAFC;
        margin: 0;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .brand-version {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.68rem;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 4px;
        background: rgba(56, 189, 248, 0.12);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.25);
    }
    .brand-sub {
        color: #64748B;
        font-size: 0.78rem;
        margin: 2px 0 0 0;
        font-weight: 400;
    }
    .badge-cluster {
        display: flex;
        align-items: center;
        gap: 8px;
        flex-wrap: wrap;
    }
    .hud-pill {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.72rem;
        font-weight: 600;
        padding: 5px 11px;
        border-radius: 6px;
        letter-spacing: 0.3px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .hud-emerald {
        background: rgba(16, 185, 129, 0.10);
        color: #34D399;
        border: 1px solid rgba(16, 185, 129, 0.25);
    }
    .hud-amber {
        background: rgba(245, 158, 11, 0.10);
        color: #FBBF24;
        border: 1px solid rgba(245, 158, 11, 0.25);
    }
    .hud-rose {
        background: rgba(244, 63, 94, 0.10);
        color: #FB7185;
        border: 1px solid rgba(244, 63, 94, 0.25);
    }
    .hud-cyan {
        background: rgba(56, 189, 248, 0.10);
        color: #38BDF8;
        border: 1px solid rgba(56, 189, 248, 0.25);
    }
    .hud-slate {
        background: rgba(148, 163, 184, 0.08);
        color: #CBD5E1;
        border: 1px solid rgba(148, 163, 184, 0.18);
    }

    /* Custom Bento Glass KPI Cards */
    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(5, 1fr);
        gap: 14px;
        margin-bottom: 16px;
    }
    @media (max-width: 1100px) {
        .kpi-grid { grid-template-columns: repeat(2, 1fr); }
    }
    .kpi-card {
        background: linear-gradient(160deg, rgba(17, 24, 39, 0.78) 0%, rgba(9, 13, 22, 0.88) 100%);
        border: 1px solid rgba(255, 255, 255, 0.07);
        border-top: 1px solid rgba(255, 255, 255, 0.13);
        border-radius: 12px;
        padding: 16px 18px;
        position: relative;
        overflow: hidden;
        transition: all 0.22s cubic-bezier(0.16, 1, 0.3, 1);
        box-shadow: 0 8px 24px -6px rgba(0, 0, 0, 0.5);
    }
    .kpi-card:hover {
        transform: translateY(-2px);
        border-color: rgba(56, 189, 248, 0.3);
        box-shadow: 0 12px 30px -6px rgba(0, 0, 0, 0.7);
    }
    .kpi-label {
        font-size: 0.71rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.9px;
        color: #64748B;
        margin-bottom: 6px;
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    .kpi-value {
        font-family: 'JetBrains Mono', monospace;
        font-size: 1.55rem;
        font-weight: 700;
        color: #F8FAFC;
        letter-spacing: -0.5px;
        font-variant-numeric: tabular-nums;
        margin-bottom: 8px;
    }
    .kpi-delta {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.73rem;
        font-weight: 500;
        padding: 2px 7px;
        border-radius: 4px;
        display: inline-block;
    }
    .delta-pos { background: rgba(16, 185, 129, 0.12); color: #34D399; }
    .delta-neg { background: rgba(244, 63, 94, 0.12); color: #FB7185; }
    .delta-neu { background: rgba(56, 189, 248, 0.12); color: #38BDF8; }

    /* Quantitative Risk & Alpha Telemetry Strip */
    .alpha-strip {
        background: rgba(11, 15, 25, 0.65);
        border: 1px solid rgba(255, 255, 255, 0.06);
        border-radius: 10px;
        padding: 10px 20px;
        margin-bottom: 18px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        flex-wrap: wrap;
        gap: 14px;
    }
    .alpha-item {
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .alpha-lbl {
        font-size: 0.72rem;
        color: #64748B;
        text-transform: uppercase;
        letter-spacing: 0.7px;
        font-weight: 600;
    }
    .alpha-val {
        font-family: 'JetBrains Mono', monospace;
        font-size: 0.85rem;
        color: #E2E8F0;
        font-weight: 600;
    }

    /* Section Headers */
    .sec-title {
        font-size: 0.95rem;
        font-weight: 600;
        color: #F1F5F9;
        letter-spacing: 0.3px;
        margin: 6px 0 12px 0;
        display: flex;
        align-items: center;
        gap: 8px;
    }
    .sec-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #38BDF8;
        display: inline-block;
    }

    /* Modernized Streamlit Tabs */
    div[data-testid="stTabs"] button {
        font-family: 'Inter', sans-serif !important;
        font-size: 0.82rem !important;
        font-weight: 600 !important;
        letter-spacing: 0.3px;
        color: #64748B !important;
        padding: 10px 18px !important;
        transition: all 0.2s ease;
    }
    div[data-testid="stTabs"] button[aria-selected="true"] {
        color: #38BDF8 !important;
        border-bottom-color: #38BDF8 !important;
    }

    /* Sidebar Polish */
    section[data-testid="stSidebar"] {
        background-color: #070A10 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.06) !important;
    }
</style>
""", unsafe_allow_html=True)

# 68-Asset Master Pools
CORE_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG',
    'CAT', 'DIS', 'V', 'MA', 'UNH', 'HD', 'COST', 'ABBV', 'KO', 'PEP',
    'AVGO', 'ORCL', 'CVX', 'MRK', 'BAC', 'LLY', 'MCD', 'TMO', 'CSCO', 'ACN'
]
MOMENTUM_TICKERS = [
    'AMD', 'PLTR', 'META', 'COIN', 'NFLX', 'AMZN', 'CRM', 'UBER', 'SHOP', 'XYZ',
    'SNOW', 'CRWD', 'PANW', 'DKNG', 'ROKU', 'HOOD', 'MARA', 'RIOT', 'SOFI', 'ARM',
    'SMCI', 'MU', 'INTC', 'MSTR'
]
CRYPTO_PAIRS = [
    'BTC/USD', 'ETH/USD', 'SOL/USD', 'AVAX/USD', 'LINK/USD', 'DOGE/USD', 'XRP/USD',
    'LTC/USD', 'UNI/USD', 'AAVE/USD', 'DOT/USD', 'BCH/USD', 'SHIB/USD', 'SUI/USD'
]
CRYPTO_NORM = {c.replace("/", ""): c for c in CRYPTO_PAIRS}

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in CORE_TICKERS:
        return "CORE"
    if sym in MOMENTUM_TICKERS:
        return "MOMENTUM"
    if sym in CRYPTO_PAIRS or s_clean in CRYPTO_NORM or sym.endswith("/USD") or sym.endswith("USD"):
        return "CRYPTO"
    return "CORE"

# =====================================================================
# 2. CREDENTIALS & CONNECTION INITIALIZATION
# =====================================================================
def get_secret(key, default=""):
    try:
        val = st.secrets.get(key, default)
        return val if val else default
    except Exception:
        return default

API_KEY = str(get_secret("APCA_API_KEY_ID", "")).strip()
API_SECRET = str(get_secret("APCA_API_SECRET_KEY", "")).strip()
GOOGLE_CREDS_RAW = get_secret("GOOGLE_CREDENTIALS", "")
GITHUB_PAT_SECRET = str(get_secret("GITHUB_PAT", "")).strip().strip('"').strip("'")
BASE_URL = "https://paper-api.alpaca.markets"

@st.cache_resource
def init_alpaca():
    if not API_KEY or not API_SECRET:
        return None
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
    if not GOOGLE_CREDS_RAW:
        return None, "Missing GOOGLE_CREDENTIALS in Streamlit Secrets"
    try:
        if isinstance(GOOGLE_CREDS_RAW, str) and GOOGLE_CREDS_RAW.strip():
            clean_str = GOOGLE_CREDS_RAW.replace("\xa0", " ").replace("\u00a0", " ").strip()
            try:
                creds_dict = json.loads(clean_str, strict=False)
            except Exception:
                try:
                    import tomllib
                    parsed = tomllib.loads(clean_str)
                    creds_dict = parsed.get("GOOGLE_CREDENTIALS", parsed)
                except Exception:
                    creds_dict = {}
        elif isinstance(GOOGLE_CREDS_RAW, dict) or hasattr(GOOGLE_CREDS_RAW, "get"):
            creds_dict = dict(GOOGLE_CREDS_RAW)
        else:
            creds_dict = {}

        if "private_key" in creds_dict:
            creds_dict["private_key"] = repair_pem_key(creds_dict["private_key"])

        if not creds_dict:
            return None, "Invalid Google Credentials format."

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
# 3. LIVE TELEMETRY & QUANTITATIVE METRICS FETCHERS
# =====================================================================
def get_nyse_bell_countdown():
    """Calculates exact time remaining until NYSE Opening or Closing Bell."""
    ny_now = datetime.now(ZoneInfo("America/New_York"))
    wk = ny_now.weekday()
    open_t = dtime(9, 30)
    close_t = dtime(16, 0)

    if wk < 5 and open_t <= ny_now.time() < close_t:
        target = datetime.combine(ny_now.date(), close_t, tzinfo=ZoneInfo("America/New_York"))
        rem = target - ny_now
        hrs, rem_s = divmod(int(rem.total_seconds()), 3600)
        mins = rem_s // 60
        return True, f"CLOSING BELL IN {hrs}H {mins:02d}M"
    else:
        days_ahead = 0
        if wk == 4 and ny_now.time() >= close_t:
            days_ahead = 3
        elif wk == 5:
            days_ahead = 2
        elif wk == 6:
            days_ahead = 1
        elif ny_now.time() >= close_t:
            days_ahead = 1
        next_open_date = ny_now.date() + timedelta(days=days_ahead)
        target = datetime.combine(next_open_date, open_t, tzinfo=ZoneInfo("America/New_York"))
        rem = target - ny_now
        hrs, rem_s = divmod(int(rem.total_seconds()), 3600)
        mins = rem_s // 60
        return False, f"OPENING BELL IN {hrs}H {mins:02d}M"

@st.cache_data(ttl=30)
def fetch_alpaca_state():
    if not api:
        return False, {}, [], [], [], pd.DataFrame()
    clock_obj = api.get_clock()
    is_open = bool(clock_obj.is_open)

    account_obj = api.get_account()
    account_data = {
        "equity": float(account_obj.equity),
        "last_equity": float(getattr(account_obj, 'last_equity', account_obj.equity) or account_obj.equity),
        "cash": float(getattr(account_obj, 'cash', 0.0) or 0.0),
        "buying_power": float(getattr(account_obj, 'buying_power', 0.0) or 0.0),
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
            "submitted_at": str(o.submitted_at)[:19],
            "symbol": display_sym,
            "tranche": classify_symbol(display_sym),
            "side": str(o.side).upper(),
            "type": str(o.type).upper(),
            "qty": str(o.qty),
            "filled_qty": str(getattr(o, 'filled_qty', '0')),
            "filled_avg_price": float(o.filled_avg_price) if getattr(o, 'filled_avg_price', None) else None,
            "limit_price": float(o.limit_price) if getattr(o, 'limit_price', None) else None,
            "stop_price": float(o.stop_price) if getattr(o, 'stop_price', None) else None,
            "status": str(o.status).upper()
        })

    try:
        hist = api.get_portfolio_history(period="1M", timeframe="1D").df
    except Exception:
        hist = pd.DataFrame()

    return is_open, account_data, positions_data, orders_data, recent_data, hist

@st.cache_data(ttl=120)
def fetch_macro_telemetry():
    spy_chg, vix_val, spy_30d = 0.0, 0.0, 0.0
    try:
        spy = yf.Ticker("SPY").history(period="1mo")
        vix = yf.Ticker("^VIX").history(period="5d")
        if len(spy) >= 2:
            spy_chg = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]) * 100
            spy_30d = ((spy['Close'].iloc[-1] - spy['Close'].iloc[0]) / spy['Close'].iloc[0]) * 100
        if not vix.empty:
            vix_val = float(vix['Close'].iloc[-1])
    except Exception:
        pass
    macro_ok = (spy_chg > -1.5) and (vix_val < 28.0)
    return macro_ok, spy_chg, vix_val, spy_30d

@st.cache_data(ttl=300)
def fetch_ticker_history(ticker):
    try:
        yf_sym = ticker.replace("/", "-")
        return yf.Ticker(yf_sym).history(period="1y")
    except Exception:
        return pd.DataFrame()

def compute_quant_metrics(port_hist, equity, spy_30d):
    """Calculates Sharpe Ratio, Max Drawdown, Volatility, and Benchmark Alpha."""
    port_ret = ((equity - 100000.0) / 100000.0) * 100.0
    alpha = port_ret - spy_30d
    if port_hist.empty or "equity" not in port_hist.columns:
        return 0.0, 0.0, 0.0, alpha
    eq_series = port_hist[port_hist["equity"] > 0]["equity"]
    if len(eq_series) < 3:
        return 0.0, 0.0, 0.0, alpha
    rets = eq_series.pct_change().dropna()
    vol = float(rets.std() * np.sqrt(252) * 100.0) if len(rets) > 1 and rets.std() > 0 else 0.0
    sharpe = float((rets.mean() / rets.std()) * np.sqrt(252)) if len(rets) > 1 and rets.std() > 0 else 0.0
    roll_max = eq_series.cummax()
    dd = ((eq_series - roll_max) / roll_max) * 100.0
    max_dd = float(dd.min()) if not dd.empty else 0.0
    return sharpe, max_dd, vol, alpha

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
            df = pd.DataFrame(data_rows, columns=cols)
            if "Ticker" in df.columns:
                df = df[df["Ticker"].astype(str).str.strip() != ""]
            return df
    except Exception:
        pass
    return pd.DataFrame()

@st.cache_data(ttl=45)
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

def trigger_github_workflow(token, mode="all"):
    if not token:
        st.sidebar.error("⚠️ Missing GitHub PAT. Paste token in sidebar or Streamlit Secrets.")
        return
    resp = requests.post(
        "https://api.github.com/repos/MakkosHUN/autotradingbot/actions/workflows/schedule.yml/dispatches",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        },
        json={"ref": "main", "inputs": {"bot_mode": mode}},
        timeout=10
    )
    if resp.status_code == 204:
        st.sidebar.success(f"✅ Dispatched `{mode.upper()}` Engine!")
    else:
        # Fallback if schedule.yml hasn't been updated with inputs yet
        resp2 = requests.post(
            "https://api.github.com/repos/MakkosHUN/autotradingbot/actions/workflows/schedule.yml/dispatches",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"ref": "main"},
            timeout=10
        )
        if resp2.status_code == 204:
            st.sidebar.success(f"✅ Dispatched Workflow (`{mode.upper()}`)!")
        else:
            st.sidebar.error(f"GitHub Error ({resp.status_code}): Check token scopes (`repo`, `workflow`).")

# =====================================================================
# 4. SIDEBAR TELEMETRY & GRANULAR ENGINE DISPATCH DECK
# =====================================================================
with st.sidebar:
    st.markdown("### 💠 AETHER QUANT `v4.0`")
    st.caption("Institutional Multi-Strategy Execution Deck")

    @st.fragment(run_every="30s")
    def sidebar_clocks():
        ny_now = datetime.now(ZoneInfo("America/New_York"))
        cet_now = datetime.now(ZoneInfo("Europe/Budapest"))
        _, bell_str = get_nyse_bell_countdown()
        st.markdown(f"""
        <div style="background:rgba(15,23,42,0.65); border:1px solid rgba(255,255,255,0.07); border-radius:8px; padding:10px 12px; font-family:'JetBrains Mono',monospace; font-size:0.74rem; line-height:1.6;">
            <div style="color:#94A3B8;">🗽 NYC: <span style="color:#F8FAFC; font-weight:600;">{ny_now.strftime('%H:%M:%S %p')}</span></div>
            <div style="color:#94A3B8;">🇪🇺 CET: <span style="color:#F8FAFC; font-weight:600;">{cet_now.strftime('%H:%M:%S')}</span></div>
            <div style="color:#38BDF8; font-weight:600; margin-top:4px;">⏱️ {bell_str}</div>
        </div>
        """, unsafe_allow_html=True)

    sidebar_clocks()
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    if st.button("🔄 Sync Live Telemetry", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("#### 🚀 Engine Dispatch Controls")
    st.caption("Fire all 3 engines together or dispatch a single strategy on GitHub Actions.")

    custom_pat = st.text_input(
        "GitHub PAT Override (Optional):",
        value="",
        type="password",
        placeholder="Uses GITHUB_PAT secret by default"
    )
    active_pat = custom_pat.strip() if custom_pat.strip() else GITHUB_PAT_SECRET

    if st.button("⚡ Dispatch All 3 Engines", use_container_width=True):
        trigger_github_workflow(active_pat, "all")

    d_col1, d_col2, d_col3 = st.columns(3)
    with d_col1:
        if st.button("🛡️ Core", use_container_width=True, help="Run Engine 1: Core Blue-Chips"):
            trigger_github_workflow(active_pat, "core")
    with d_col2:
        if st.button("⚡ Mom", use_container_width=True, help="Run Engine 2: Short-Term Momentum"):
            trigger_github_workflow(active_pat, "momentum")
    with d_col3:
        if st.button("🪙 Cryp", use_container_width=True, help="Run Engine 3: 24/7 Crypto AI"):
            trigger_github_workflow(active_pat, "crypto")

    st.markdown("---")
    st.markdown("#### 🛡️ System Safeguards")
    if spreadsheet:
        st.caption("🟢 **Cloud Audit Ledger:** `Connected`")
    else:
        st.warning(f"🔴 **Sheets Disconnected:** `{sheet_status}`")

    @st.fragment(run_every="30s")
    def sidebar_safeguards():
        if api:
            _, acct_s, _, _, _, _ = fetch_alpaca_state()
            dt_count = int(acct_s.get('daytrade_count', 0))
            st.progress(min(dt_count / 3.0, 1.0), text=f"FINRA PDT Shield: {dt_count} / 3 Day Trades")
        _, spy_s, vix_s, _ = fetch_macro_telemetry()
        st.markdown(f"""
        <div style="font-family:'JetBrains Mono',monospace; font-size:0.75rem; color:#94A3B8; margin-top:4px;">
            SPY 24H: <span style="color:{'#10B981' if spy_s>=0 else '#F43F5E'}; font-weight:600;">{spy_s:+.2f}%</span> &nbsp;|&nbsp;
            VIX: <span style="color:{'#10B981' if vix_s<22 else '#F59E0B'}; font-weight:600;">{vix_s:.1f}</span>
        </div>
        """, unsafe_allow_html=True)

    sidebar_safeguards()

    st.markdown("---")
    with st.expander("🚨 Kill-Switch & Overrides"):
        st.caption("Immediate market liquidation and order book purge.")
        unlock_kill = st.checkbox("Arm Emergency Controls")
        if st.button("Cancel Open Orders", disabled=not unlock_kill, use_container_width=True):
            if api:
                api.cancel_all_orders()
                st.cache_data.clear()
                st.success("All open orders purged.")
                st.rerun()
        if st.button("🔥 Liquidate All to Cash", disabled=not unlock_kill, use_container_width=True):
            if api:
                api.close_all_positions(cancel_orders=True)
                st.cache_data.clear()
                st.error("Portfolio liquidated.")
                st.rerun()

# =====================================================================
# 5. PRO TECHNICAL CHART BUILDER (CANDLESTICKS + BBANDS + WILDER'S RSI)
# =====================================================================
def build_pro_technical_chart(ticker, df_yf):
    df = df_yf.copy()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()

    # Bollinger Bands (20, 2)
    std20 = df["Close"].rolling(20).std()
    df["BB_UP"] = df["EMA20"] + (2.0 * std20)
    df["BB_LOW"] = df["EMA20"] - (2.0 * std20)

    # Wilder's RSI-14
    delta = df["Close"].diff()
    gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
    rs = gain / loss
    df["RSI"] = 100.0 - (100.0 / (1.0 + rs))

    df_plot = df.tail(110)

    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.72, 0.28]
    )

    # Bollinger Band Cloud
    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot["BB_UP"],
        line=dict(color="rgba(148, 163, 184, 0.2)", width=1, dash="dot"),
        name="Upper BB", showlegend=False
    ), row=1, col=1)
    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot["BB_LOW"],
        line=dict(color="rgba(148, 163, 184, 0.2)", width=1, dash="dot"),
        fill="tonexty", fillcolor="rgba(56, 189, 248, 0.04)",
        name="Bollinger Cloud (20,2)"
    ), row=1, col=1)

    # Candlesticks
    fig.add_trace(go.Candlestick(
        x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"], close=df_plot["Close"], name=ticker,
        increasing_line_color="#10B981", decreasing_line_color="#F43F5E"
    ), row=1, col=1)

    # Moving Averages
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#38BDF8", width=1.7), name="20-EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA50"], line=dict(color="#A855F7", width=1.5, dash="dash"), name="50-SMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], line=dict(color="#F59E0B", width=2.0, dash="dot"), name="200-SMA"), row=1, col=1)

    # Wilder's RSI Subplot
    fig.add_trace(go.Scatter(
        x=df_plot.index, y=df_plot["RSI"],
        line=dict(color="#34D399", width=1.8),
        name="Wilder RSI (14)"
    ), row=2, col=1)
    fig.add_hline(y=70, line_dash="dash", line_color="rgba(244,63,94,0.5)", row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="rgba(16,185,129,0.5)", row=2, col=1)

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(11,15,25,0.55)",
        height=480,
        xaxis_rangeslider_visible=False,
        margin=dict(t=10, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(size=11)),
        hovermode="x unified"
    )
    fig.update_yaxes(title_text="Price ($)", gridcolor="rgba(255,255,255,0.05)", row=1, col=1)
    fig.update_yaxes(title_text="RSI-14", range=[15, 85], gridcolor="rgba(255,255,255,0.05)", row=2, col=1)
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    return fig

# =====================================================================
# 6. REUSABLE STRATEGY ENGINE WORKSTATION (ENGINES 1, 2, AND 3)
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

    # Calculate Bullish vs Bearish Signal Ratio from Latest Scan
    bull_count, bear_count = 0, 0
    if not df_log.empty and "FinBERT Score" in df_log.columns:
        t_col = "Ticker" if "Ticker" in df_log.columns else df_log.columns[1]
        latest_scan = df_log.drop_duplicates(subset=[t_col], keep="last")
        scores_num = pd.to_numeric(latest_scan["FinBERT Score"], errors="coerce").fillna(0.0)
        bull_count = int((scores_num >= buy_thresh).sum())
        bear_count = int((scores_num <= exit_thresh).sum())

    pl_cls = "delta-pos" if tranche_pl >= 0 else "delta-neg"
    st.markdown(f"""
    <div style="margin-bottom: 12px;">
        <div class="sec-title"><span class="sec-dot"></span>{engine_title}</div>
        <div style="color:#64748B; font-size:0.78rem; margin-top:-8px; margin-bottom:14px;">{engine_subtitle}</div>
    </div>
    <div class="kpi-grid" style="grid-template-columns: repeat(4, 1fr);">
        <div class="kpi-card">
            <div class="kpi-label"><span>TRANCHE CAPITAL DEPLOYED</span><span>🎯</span></div>
            <div class="kpi-value">${tranche_invested:,.2f}</div>
            <span class="kpi-delta delta-neu">{tranche_exposure:.1f}% of Account Equity</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>TRANCHE OPEN ALPHA (P/L)</span><span>📈</span></div>
            <div class="kpi-value">${tranche_pl:+,.2f}</div>
            <span class="kpi-delta {pl_cls}">{len(tranche_pos)} Active Positions</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>DYNAMIC SCREENER POOL</span><span>🛰️</span></div>
            <div class="kpi-value">{len(universe_tickers)} Assets</div>
            <span class="kpi-delta delta-neu">{'24/7/365 Continuous' if is_crypto else 'Hourly Intraday + Radar'}</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>LATEST AI SIGNAL BREADTH</span><span>🧠</span></div>
            <div class="kpi-value">{bull_count} Bull / {bear_count} Bear</div>
            <span class="kpi-delta delta-pos">Buy ≥ {buy_thresh:+.2f} | Exit ≤ {exit_thresh:+.2f}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    t1, t2, t3, t4 = st.tabs([
        "💼 Active Positions & Live Screener Matrix",
        "🧠 FinBERT Sentiment Radar & Audit Ledger",
        "🔬 Pro Technical Workstation (BBands + RSI)",
        "📜 Tranche Order Book"
    ])

    with t1:
        if tranche_pos:
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
                    shield_status = "🛡️ +2.5% TRAIL ACTIVE" if pl_pct >= 2.5 else "Dynamic +6% / -3%"
                else:
                    shield_status = "🛡️ BREAK-EVEN LOCKED" if (sl_price and sl_price >= entry - 0.01) else ("⚡ RATCHET READY" if pl_pct >= 1.5 else "ATR Bracket Active")

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
            col_table, col_pie = st.columns([2.35, 1])
            with col_table:
                st.markdown('<div class="sec-title"><span class="sec-dot"></span>Active Tranche Holdings & Bracket Telemetry</div>', unsafe_allow_html=True)
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
                st.markdown('<div class="sec-title"><span class="sec-dot"></span>Tranche Weighting</div>', unsafe_allow_html=True)
                alloc_df = pd.DataFrame({
                    "Asset": [r["Ticker"] for r in pos_rows],
                    "Value": [r["Market Value"] for r in pos_rows]
                })
                fig_pie = px.pie(
                    alloc_df, values="Value", names="Asset", hole=0.68,
                    color_discrete_sequence=["#10B981", "#38BDF8", "#6366F1", "#8B5CF6", "#F59E0B", "#EC4899"]
                )
                fig_pie.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Invested: $%{value:,.2f}<br>Share: %{percent}<extra></extra>"
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=8, b=8, l=8, r=8), height=290,
                    showlegend=False,
                    annotations=[dict(
                        text=(
                            f"<span style='color:#64748B; font-size:10px;'>{tranche_key}</span><br>"
                            f"<b style='color:#F8FAFC; font-size:15px;'>${tranche_invested:,.2f}</b><br>"
                            f"<span style='color:#10B981; font-size:10px;'>{tranche_exposure:.1f}% Equity</span>"
                        ),
                        x=0.5, y=0.5, showarrow=False
                    )]
                )
                st.plotly_chart(fig_pie, use_container_width=True)

        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>Latest Screened {tranche_key} Candidates & Pre-Market Target Matrix</div>', unsafe_allow_html=True)
        if not df_log.empty:
            ticker_col = "Ticker" if "Ticker" in df_log.columns else df_log.columns[1]
            latest_matrix = df_log.drop_duplicates(subset=[ticker_col], keep="last").iloc[::-1].copy()
            if "FinBERT Score" in latest_matrix.columns:
                latest_matrix["FinBERT Score"] = pd.to_numeric(latest_matrix["FinBERT Score"], errors="coerce").fillna(0.0)
            st.dataframe(
                latest_matrix,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "FinBERT Score": st.column_config.NumberColumn("FinBERT Score (-1 to +1)", format="%+.3f")
                }
            )
        else:
            st.info(f"No scan records in `{tranche_key}` yet. Use the sidebar dispatch buttons to run an immediate scan.")

    with t2:
        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>{tranche_key} Neural Sentiment Spectrum (ProsusAI/FinBERT)</div>', unsafe_allow_html=True)
        if not df_log.empty:
            score_col = "FinBERT Score" if "FinBERT Score" in df_log.columns else df_log.columns[2]
            ticker_col = "Ticker" if "Ticker" in df_log.columns else df_log.columns[1]
            latest_df = df_log.drop_duplicates(subset=[ticker_col], keep="last").tail(14).copy()
            latest_df["Score_Num"] = pd.to_numeric(latest_df[score_col], errors="coerce").fillna(0.0)
            latest_df = latest_df.sort_values("Score_Num", ascending=False)

            bar_colors = ["#10B981" if s >= buy_thresh else ("#F43F5E" if s <= exit_thresh else "#475569") for s in latest_df["Score_Num"]]
            fig_sent = go.Figure(go.Bar(
                x=latest_df[ticker_col], y=latest_df["Score_Num"],
                marker_color=bar_colors,
                text=[f"{s:+.3f}" for s in latest_df["Score_Num"]],
                textposition="outside"
            ))
            fig_sent.add_hline(y=buy_thresh, line_dash="dash", line_color="#10B981", annotation_text=f"Buy Trigger ({buy_thresh:+.2f})")
            fig_sent.add_hline(y=exit_thresh, line_dash="dash", line_color="#F43F5E", annotation_text=f"Exit Trigger ({exit_thresh:+.2f})")
            fig_sent.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(11,15,25,0.55)", height=330,
                margin=dict(t=20, b=10, l=10, r=10),
                yaxis=dict(title="Net Sentiment Score", range=[-1.05, 1.05], gridcolor="rgba(255,255,255,0.05)")
            )
            st.plotly_chart(fig_sent, use_container_width=True)

            st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>Historical {tranche_key} Execution Ledger</div>', unsafe_allow_html=True)
            st.dataframe(df_log.iloc[::-1].head(100), use_container_width=True, hide_index=True)
        else:
            st.info("Audit ledger will populate automatically after the next scan.")

    with t3:
        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>Multi-Timeframe Technical & Volatility Inspector ({len(universe_tickers)}-Asset Pool)</div>', unsafe_allow_html=True)
        sel_ticker = st.selectbox(f"Select {tranche_key} Instrument:", universe_tickers, index=0, key=f"sel_{tranche_key}")
        df_yf = fetch_ticker_history(sel_ticker)
        if not df_yf.empty:
            fig_tech = build_pro_technical_chart(sel_ticker, df_yf)
            st.plotly_chart(fig_tech, use_container_width=True)

    with t4:
        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>{tranche_key} Alpaca Order & Fill Ledger</div>', unsafe_allow_html=True)
        if tranche_orders:
            st.dataframe(pd.DataFrame(tranche_orders), use_container_width=True, hide_index=True)
        else:
            st.info(f"No recent Alpaca orders recorded for the {tranche_key} tranche.")

# =====================================================================
# 7. MAIN OBSIDIAN TERMINAL RENDERER (AUTO-SYNCS EVERY 30S)
# =====================================================================
@st.fragment(run_every="30s")
def render_live_terminal():
    if not api:
        st.error("⚠️ Alpaca API credentials missing in Streamlit Secrets. Add `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`.")
        return

    is_open, account, positions, active_orders, recent_orders, port_hist = fetch_alpaca_state()
    macro_ok, spy_chg, vix_val, spy_30d = fetch_macro_telemetry()
    df_core, df_mom, df_crypto, df_closed = fetch_all_sheet_logs()
    _, bell_countdown = get_nyse_bell_countdown()

    equity = float(account.get('equity', 0.0))
    last_equity = float(account.get('last_equity', equity))
    cash = float(account.get('cash', 0.0))
    daytrades = int(account.get('daytrade_count', 0))

    day_pl = equity - last_equity
    day_pl_pct = (day_pl / last_equity) * 100 if last_equity > 0 else 0.0
    all_time_pl = equity - 100000.0
    all_time_pct = (all_time_pl / 100000.0) * 100.0
    open_pl = sum(p['unrealized_pl'] for p in positions)
    invested = sum(p['market_value'] for p in positions)
    exposure_pct = (invested / equity) * 100 if equity > 0 else 0.0

    sharpe, max_dd, ann_vol, bench_alpha = compute_quant_metrics(port_hist, equity, spy_30d)

    # 1. Live Scrolling Institutional Ticker Tape
    tape_items = [
        f'<span class="ticker-item"><span class="ticker-sym">SPY</span><span class="{"up" if spy_chg>=0 else "down"}">{spy_chg:+.2f}%</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">VIX</span><span class="{"up" if vix_val<22 else "down"}">{vix_val:.2f}</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">NET LIQ</span><span class="flat">${equity:,.2f}</span></span>'
    ]
    for p in positions:
        ret_p = ((p['current_price'] - p['avg_entry_price']) / p['avg_entry_price']) * 100.0
        cls_p = "up" if ret_p >= 0 else "down"
        tape_items.append(
            f'<span class="ticker-item"><span class="ticker-sym">{p["symbol"]}</span>'
            f'${p["current_price"]:,.2f} <span class="{cls_p}">({ret_p:+.2f}%)</span></span>'
        )
    tape_html = "".join(tape_items) * 2
    st.markdown(f'<div class="ticker-wrap"><div class="ticker-move">{tape_html}</div></div>', unsafe_allow_html=True)

    # 2. Top Institutional Header
    mkt_pill = f'<span class="hud-pill hud-emerald">● NYSE OPEN ({bell_countdown})</span>' if is_open else f'<span class="hud-pill hud-amber">● NYSE CLOSED ({bell_countdown})</span>'
    cryp_pill = '<span class="hud-pill hud-cyan">◈ CRYPTO 24/7 ACTIVE</span>'
    mac_pill = '<span class="hud-pill hud-emerald">🛡️ MACRO NORMAL</span>' if macro_ok else '<span class="hud-pill hud-rose">⚠️ MACRO SHIELD ACTIVE</span>'
    pdt_pill = f'<span class="hud-pill hud-slate">PDT: {daytrades}/3</span>'

    st.markdown(f"""
    <div class="inst-header">
        <div class="brand-cluster">
            <div class="brand-orb"></div>
            <div>
                <div class="brand-title">AETHER QUANTITATIVE COMMAND <span class="brand-version">v4.0 OBSIDIAN</span></div>
                <div class="brand-sub">68-Asset Multi-Strategy Funnel • ProsusAI/FinBERT Neural Engine • Dynamic ATR & Trailing Ratchets</div>
            </div>
        </div>
        <div class="badge-cluster">
            {mkt_pill}
            {cryp_pill}
            {mac_pill}
            {pdt_pill}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 3. Custom Bento Glass KPI Cards
    all_cls = "delta-pos" if all_time_pl >= 0 else "delta-neg"
    day_cls = "delta-pos" if day_pl >= 0 else "delta-neg"
    open_cls = "delta-pos" if open_pl >= 0 else "delta-neg"

    st.markdown(f"""
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-label"><span>NET LIQUIDATION VALUE</span><span>🏛️</span></div>
            <div class="kpi-value">${equity:,.2f}</div>
            <span class="kpi-delta {all_cls}">{all_time_pl:+,.2f} ({all_time_pct:+.2f}%) All-Time</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>INTRADAY P/L (24H)</span><span>⚡</span></div>
            <div class="kpi-value">${day_pl:+,.2f}</div>
            <span class="kpi-delta {day_cls}">{day_pl_pct:+.2f}% Today</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>OPEN UNREALIZED ALPHA</span><span>📈</span></div>
            <div class="kpi-value">${open_pl:+,.2f}</div>
            <span class="kpi-delta {open_cls}">{len(positions)} Active Positions</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>DEPLOYED CAPITAL</span><span>🎯</span></div>
            <div class="kpi-value">${invested:,.2f}</div>
            <span class="kpi-delta delta-neu">{exposure_pct:.1f}% Portfolio Exposure</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>LIQUID DRY POWDER</span><span>💵</span></div>
            <div class="kpi-value">${cash:,.2f}</div>
            <span class="kpi-delta delta-neu">{100.0 - exposure_pct:.1f}% Cash Reserve</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 4. Quantitative Risk & Benchmark Alpha Telemetry Strip
    alpha_color = "#10B981" if bench_alpha >= 0 else "#F43F5E"
    st.markdown(f"""
    <div class="alpha-strip">
        <div class="alpha-item">
            <span class="alpha-lbl">SHARPE RATIO (ANN.):</span>
            <span class="alpha-val">{sharpe:+.2f}</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">MAX DRAWDOWN (30D):</span>
            <span class="alpha-val" style="color:#FB7185;">{max_dd:.2f}%</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">ANNUALIZED VOLATILITY:</span>
            <span class="alpha-val">{ann_vol:.2f}%</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">ALPHA VS. S&P 500 (30D):</span>
            <span class="alpha-val" style="color:{alpha_color};">{bench_alpha:+.2f}%</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">TOTAL AI SCANS LOGGED:</span>
            <span class="alpha-val" style="color:#38BDF8;">{len(df_core) + len(df_mom) + len(df_crypto):,} Rows</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5. Sleek Top Horizontal Strategy Switcher
    nav_options = [
        "🏛️ Master Hedge Fund Overview",
        "🛡️ Engine 1: Core Long-Term (30 Pool)",
        "⚡ Engine 2: Short-Term Momentum (24 Pool)",
        "🪙 Engine 3: 24/7 Crypto AI (14 Pool)"
    ]
    if hasattr(st, "segmented_control"):
        selected_page = st.segmented_control(
            "Command View",
            options=nav_options,
            default=nav_options[0],
            selection_mode="single",
            label_visibility="collapsed"
        )
        if not selected_page:
            selected_page = nav_options[0]
    else:
        selected_page = st.radio("Command View", nav_options, horizontal=True, label_visibility="collapsed")

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # =================================================================
    # VIEW 1: MASTER HEDGE FUND OVERVIEW
    # =================================================================
    if selected_page == nav_options[0]:
        st.markdown('<div class="sec-title"><span class="sec-dot"></span>Multi-Strategy Tranche Attribution & Mandate Matrix</div>', unsafe_allow_html=True)

        tranche_summary = []
        for t_key, t_label, t_freq, t_risk, df_t in [
            ("CORE", "🛡️ Engine 1: Core Long-Term Equities", "2x Daily (Open/Close)", "Low Risk • 1.5x/3.5x ATR • 200-SMA", df_core),
            ("MOMENTUM", "⚡ Engine 2: Short-Term Momentum", "Hourly (NYSE Hours)", "Mid Risk • 1.0x/2.0x ATR • Fast EMA", df_mom),
            ("CRYPTO", "🪙 Engine 3: 24/7 Crypto AI Quant", "Every 2 Hours (24/7)", "High Risk • Dynamic +6%/-3% • RSI/AI", df_crypto)
        ]:
            t_pos = [p for p in positions if p['tranche'] == t_key]
            t_val = sum(p['market_value'] for p in t_pos)
            t_pl = sum(p['unrealized_pl'] for p in t_pos)
            t_exp = (t_val / equity) * 100 if equity > 0 else 0.0
            tranche_summary.append({
                "Strategy Tranche": t_label,
                "Execution Frequency": t_freq,
                "Quantitative Mandate": t_risk,
                "Logged Scans": len(df_t),
                "Open Positions": len(t_pos),
                "Invested Capital": t_val,
                "Equity Weight": t_exp,
                "Open Alpha ($)": t_pl
            })

        st.dataframe(
            pd.DataFrame(tranche_summary),
            use_container_width=True,
            hide_index=True,
            column_config={
                "Invested Capital": st.column_config.NumberColumn("Deployed ($)", format="$%.2f"),
                "Equity Weight": st.column_config.ProgressColumn("Allocation (% Equity)", format="%.1f%%", min_value=0, max_value=100),
                "Open Alpha ($)": st.column_config.NumberColumn("Open P/L ($)", format="$%+.2f")
            }
        )

        col_eq, col_pie = st.columns([1.45, 1])
        with col_eq:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>30-Day Portfolio Net Liquidation Curve</div>', unsafe_allow_html=True)
            if not port_hist.empty and "equity" in port_hist.columns:
                df_eq = port_hist[port_hist["equity"] > 0].copy()
                fig_eq = go.Figure()
                fig_eq.add_trace(go.Scatter(
                    x=df_eq.index, y=df_eq["equity"], mode="lines+markers",
                    line=dict(color="#10B981", width=2.5),
                    marker=dict(size=5, color="#38BDF8"),
                    fill="tozeroy", fillcolor="rgba(16, 185, 129, 0.07)",
                    name="Net Equity"
                ))
                fig_eq.add_hline(y=100000.0, line_dash="dot", line_color="rgba(148,163,184,0.35)", annotation_text="Initial Capital ($100k)")
                fig_eq.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(11,15,25,0.55)", height=330,
                    margin=dict(t=12, b=12, l=10, r=10),
                    yaxis=dict(title="Account Equity ($)", gridcolor="rgba(255,255,255,0.05)"),
                    xaxis=dict(gridcolor="rgba(255,255,255,0.03)")
                )
                st.plotly_chart(fig_eq, use_container_width=True)
            else:
                st.info("Equity curve will populate as daily historical bars accumulate.")

        with col_pie:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Capital Allocation Ring & Exposure HUD</div>', unsafe_allow_html=True)
            if positions:
                alloc_df = pd.DataFrame({
                    "Asset": [f"{p['symbol']} ({p['tranche']})" for p in positions],
                    "Value": [p["market_value"] for p in positions]
                })
                fig_pie = px.pie(
                    alloc_df, values="Value", names="Asset", hole=0.68,
                    color_discrete_sequence=["#10B981", "#38BDF8", "#6366F1", "#8B5CF6", "#F59E0B", "#EC4899"]
                )
                fig_pie.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Invested: $%{value:,.2f}<br>Share: %{percent}<extra></extra>"
                )
                fig_pie.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10), height=330,
                    showlegend=False,
                    annotations=[dict(
                        text=(
                            f"<span style='color:#64748B; font-size:10px;'>DEPLOYED</span><br>"
                            f"<b style='color:#F8FAFC; font-size:16px;'>${invested:,.2f}</b><br>"
                            f"<span style='color:#10B981; font-size:11px;'>{exposure_pct:.1f}% of Equity</span>"
                        ),
                        x=0.5, y=0.5, showarrow=False
                    )]
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.info("Portfolio is currently 100% in cash.")

        # Interactive Portfolio Treemap + Pre-Market Bullish Radar
        col_tree, col_radar = st.columns([1.15, 1])
        with col_tree:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Live Portfolio Heatmap (Size = Value | Color = P/L %)</div>', unsafe_allow_html=True)
            if positions:
                tree_df = pd.DataFrame([{
                    "Tranche": p["tranche"],
                    "Symbol": p["symbol"],
                    "Value": round(p["market_value"], 2),
                    "Return_Pct": round(((p["current_price"] - p["avg_entry_price"]) / p["avg_entry_price"]) * 100.0, 2)
                } for p in positions])
                fig_tree = px.treemap(
                    tree_df, path=[px.Constant("PORTFOLIO"), "Tranche", "Symbol"],
                    values="Value", color="Return_Pct",
                    color_continuous_scale=["#F43F5E", "#1E293B", "#10B981"],
                    color_continuous_midpoint=0.0
                )
                fig_tree.update_traces(
                    textinfo="label+value+percent parent",
                    hovertemplate="<b>%{label}</b><br>Value: $%{value:,.2f}<br>Return: %{color:+.2f}%<extra></extra>"
                )
                fig_tree.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=8, b=8, l=8, r=8), height=300,
                    coloraxis_showscale=False
                )
                st.plotly_chart(fig_tree, use_container_width=True)
            else:
                st.info("Heatmap activates when positions are open.")

        with col_radar:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Top Bullish AI Signals Queued Across All 3 Engines</div>', unsafe_allow_html=True)
            combined_logs = []
            for tag, d_f in [("CORE", df_core), ("MOMENTUM", df_mom), ("CRYPTO", df_crypto)]:
                if not d_f.empty and "Ticker" in d_f.columns and "FinBERT Score" in d_f.columns:
                    sub = d_f.drop_duplicates(subset=["Ticker"], keep="last").copy()
                    sub["Engine"] = tag
                    sub["Score_Num"] = pd.to_numeric(sub["FinBERT Score"], errors="coerce").fillna(0.0)
                    combined_logs.append(sub)
            if combined_logs:
                df_all_sig = pd.concat(combined_logs, ignore_index=True)
                df_top_bull = df_all_sig.sort_values("Score_Num", ascending=False).head(8)
                st.dataframe(
                    df_top_bull[["Engine", "Ticker", "FinBERT Score", "Decision", "Action Taken"]],
                    use_container_width=True,
                    hide_index=True
                )
            else:
                st.info("No AI scan signals logged yet.")

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Automated Bracket & Crypto Exits (`Closed Trades`)</div>', unsafe_allow_html=True)
            if not df_closed.empty:
                st.dataframe(df_closed.iloc[::-1].head(25), use_container_width=True, hide_index=True)
            else:
                st.info("No automated exits recorded yet.")
        with col_c2:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Master Alpaca Order Book (All Engines)</div>', unsafe_allow_html=True)
            if recent_orders:
                st.dataframe(pd.DataFrame(recent_orders).head(25), use_container_width=True, hide_index=True)
            else:
                st.info("No recent orders found.")

    # =================================================================
    # VIEW 2: ENGINE 1 — CORE LONG-TERM EQUITIES
    # =================================================================
    elif selected_page == nav_options[1]:
        render_strategy_engine_view(
            engine_title="Engine 1: Core Blue-Chip Trend Equities (30-Stock Screener ➔ Top 10 Active)",
            engine_subtitle="Mandate: S&P 500 Leaders • Price > 200-SMA & 20-EMA • Wilder's RSI < 72 • FinBERT ≥ +0.10 • 1.5x / 3.5x ATR Brackets (+2.5% Break-Even Ratchet)",
            tranche_key="CORE",
            universe_tickers=CORE_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_core,
            equity=equity,
            buy_thresh=0.10,
            exit_thresh=-0.15,
            is_crypto=False
        )

    # =================================================================
    # VIEW 3: ENGINE 2 — SHORT-TERM MOMENTUM
    # =================================================================
    elif selected_page == nav_options[2]:
        render_strategy_engine_view(
            engine_title="Engine 2: Tactical Short-Term Momentum (24-Stock Screener ➔ Top 8 Movers)",
            engine_subtitle="Mandate: High-Beta Tech & Growth • 20-EMA > 50-SMA • FinBERT ≥ +0.05 or 9-EMA Breakout • Tight 1.0x / 2.0x ATR Brackets (+1.5% Fast Ratchet)",
            tranche_key="MOMENTUM",
            universe_tickers=MOMENTUM_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_mom,
            equity=equity,
            buy_thresh=0.05,
            exit_thresh=-0.12,
            is_crypto=False
        )

    # =================================================================
    # VIEW 4: ENGINE 3 — 24/7 CRYPTO AI QUANT
    # =================================================================
    elif selected_page == nav_options[3]:
        render_strategy_engine_view(
            engine_title="Engine 3: 24/7 Crypto AI Quant (14-Pair Screener ➔ Top 6 Movers)",
            engine_subtitle="Mandate: Round-the-Clock Crypto Execution (Zero PDT) • FinBERT ≥ +0.05, EMA Breakout, or RSI ≤ 33 Oversold Bounce • Dynamic +6% TP / -3% SL",
            tranche_key="CRYPTO",
            universe_tickers=CRYPTO_PAIRS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_crypto,
            equity=equity,
            buy_thresh=0.05,
            exit_thresh=-0.20,
            is_crypto=True
        )

render_live_terminal()
