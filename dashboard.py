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
    page_title="AETHER QUANT v8.5 // Omega Institutional Terminal",
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

    .kpi-grid {
        display: grid;
        grid-template-columns: repeat(6, 1fr);
        gap: 14px;
        margin-bottom: 16px;
    }
    @media (max-width: 1400px) {
        .kpi-grid { grid-template-columns: repeat(3, 1fr); }
    }
    @media (max-width: 900px) {
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

    section[data-testid="stSidebar"] {
        background-color: #070A10 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.06) !important;
    }
</style>
""", unsafe_allow_html=True)

# 7-Engine Asset Pools
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
    'LTC/USD', 'AAVE/USD', 'DOT/USD', 'BCH/USD', 'SHIB/USD'
]
SMALL_CAP_TICKERS = [
    'IONQ', 'RKLB', 'AFRM', 'UPST', 'HIMS', 'ASTS', 'LUNR', 'SMR', 'OKLO', 'SERV',
    'JOBY', 'ACHR', 'CELH', 'CVNA', 'AI', 'SOUN'
]
MEAN_REV_TICKERS = CORE_TICKERS + MOMENTUM_TICKERS[:10]
TAIL_HEDGE_TICKERS = ['SH', 'PSQ', 'GLD']
CRYPTO_NORM = {c.replace("/", ""): c for c in CRYPTO_PAIRS}
ALL_ASSETS = CORE_TICKERS + MOMENTUM_TICKERS + SMALL_CAP_TICKERS + TAIL_HEDGE_TICKERS + CRYPTO_PAIRS

DEFAULT_ENGINE_CONFIG = {
    "CORE":       {"enabled": True,  "cap": 0.35, "risk_bps": 0.0050, "freq": "2x/Day (Open/Close)", "desc": "S&P 500 Blue-Chip Trend Equities"},
    "MOMENTUM":   {"enabled": True,  "cap": 0.25, "risk_bps": 0.0040, "freq": "14x/Day (Every 30m NYSE)", "desc": "High-Beta Tech & Growth Breakouts"},
    "CRYPTO":     {"enabled": True,  "cap": 0.15, "risk_bps": 0.0045, "freq": "48x/Day (Every 30m 24/7)", "desc": "24/7 Digital Asset Quant"},
    "DISCOVERY":  {"enabled": True,  "cap": 0.15, "risk_bps": 0.0035, "freq": "14x/Day (Real-Time Firehose)", "desc": "Unconstrained Market-Wide News Catalyst Hunter"},
    "MEAN_REV":   {"enabled": False, "cap": 0.15, "risk_bps": 0.0035, "freq": "14x/Day (Intraday Snapback)", "desc": "Statistical Arbitrage / Bollinger + RSI <= 32 Bounce"},
    "SMALL_CAP":  {"enabled": False, "cap": 0.10, "risk_bps": 0.0030, "freq": "14x/Day (Intraday Breakouts)", "desc": "Russell 2000 & High-Velocity Speculative Movers"},
    "TAIL_HEDGE": {"enabled": True,  "cap": 0.10, "risk_bps": 0.0050, "freq": "Continuous Macro/GEX Guard", "desc": "v8.0 Options GEX & Inverse ETF Crash Shield (SH)"}
}

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in TAIL_HEDGE_TICKERS:
        return "TAIL_HEDGE"
    if sym in CRYPTO_PAIRS or s_clean in CRYPTO_NORM or sym.endswith("/USD") or sym.endswith("USD"):
        return "CRYPTO"
    if sym in CORE_TICKERS:
        return "CORE"
    if sym in MOMENTUM_TICKERS:
        return "MOMENTUM"
    if sym in SMALL_CAP_TICKERS:
        return "SMALL_CAP"
    return "DISCOVERY"

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
DISCORD_WEBHOOK_SECRET = str(get_secret("DISCORD_WEBHOOK_URL", "")).strip()
BASE_URL = "https://paper-api.alpaca.markets"

# Check if admin key is present in URL (e.g. ?admin=peter123) for Read-Only Demo Mode
IS_ADMIN = st.query_params.get("admin") == "peter123"

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
# 3. 7-ENGINE CONFIG SYNC, LIVE TELEMETRY, GEX, RL & MONTE CARLO
# =====================================================================
@st.cache_data(ttl=20)
def fetch_engine_config():
    cfg = {k: dict(v) for k, v in DEFAULT_ENGINE_CONFIG.items()}
    if not spreadsheet:
        return cfg
    try:
        try:
            ws = spreadsheet.worksheet("Engine Config")
        except Exception:
            ws = spreadsheet.add_worksheet(title="Engine Config", rows="20", cols="6")
            ws.append_row(["Engine", "Enabled", "Base_Cap_Pct", "Risk_Bps", "Description"])
            init_rows = [
                [k, "TRUE" if v["enabled"] else "FALSE", str(v["cap"]), str(v["risk_bps"]), v["desc"]]
                for k, v in cfg.items()
            ]
            ws.append_rows(init_rows)
            return cfg

        rows = ws.get_all_values()
        for r in rows[1:]:
            if len(r) >= 4 and r[0] in cfg:
                eng = r[0].strip()
                cfg[eng]["enabled"] = str(r[1]).strip().upper() in ["TRUE", "1", "YES", "ON", "ACTIVE"]
                try:
                    cfg[eng]["cap"] = float(r[2])
                    cfg[eng]["risk_bps"] = float(r[3])
                except Exception:
                    pass
    except Exception:
        pass
    return cfg

def save_engine_config_to_sheet(updated_cfg):
    if not spreadsheet:
        return False
    try:
        ws = spreadsheet.worksheet("Engine Config")
        ws.clear()
        rows = [["Engine", "Enabled", "Base_Cap_Pct", "Risk_Bps", "Description"]]
        for k, v in updated_cfg.items():
            rows.append([k, "TRUE" if v["enabled"] else "FALSE", str(v["cap"]), str(v["risk_bps"]), v["desc"]])
        ws.append_rows(rows)
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Failed to save Engine Config: {e}")
        return False

def get_nyse_bell_countdown():
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

    recent_orders_raw = api.list_orders(status='all', limit=150)
    recent_data = []
    for o in recent_orders_raw:
        raw_sym = str(o.symbol)
        display_sym = CRYPTO_NORM.get(raw_sym, raw_sym)
        recent_data.append({
            "submitted_at": str(o.submitted_at)[:19],
            "filled_at": str(getattr(o, 'filled_at', ''))[:19],
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

def compute_trade_post_mortems(df_closed, positions, recent_orders):
    post_mortems = []
    
    # ---------------------------------------------------------
    # ATTEMPT A: Cloud Ledger (Google Sheet 'Closed Trades')
    # ---------------------------------------------------------
    if not df_closed.empty:
        df_closed.columns = [str(c).strip() for c in df_closed.columns]
        pnl_col = next((c for c in df_closed.columns if "p/l" in c.lower() or "pnl" in c.lower() or "realized" in c.lower()), None)
        ticker_col = next((c for c in df_closed.columns if "ticker" in c.lower() or "symbol" in c.lower() or "asset" in c.lower()), None)
        engine_col = next((c for c in df_closed.columns if "engine" in c.lower() or "tranche" in c.lower()), None)
        
        if pnl_col:
            for _, row in df_closed.iterrows():
                try:
                    pnl_str = str(row.get(pnl_col, "0")).replace("$", "").replace("+", "").replace(",", "")
                    pnl = float(pnl_str if pnl_str.strip() else 0)
                    
                    sym = str(row.get(ticker_col, "")).strip().upper() if ticker_col else "UNKNOWN"
                    
                    # Robust Engine Detection (Matches substrings)
                    engine_val = ""
                    if engine_col:
                        raw_eng = str(row.get(engine_col, "")).strip().upper()
                        for k in DEFAULT_ENGINE_CONFIG.keys():
                            if k in raw_eng:
                                engine_val = k
                                break
                    
                    # If Engine is missing in the sheet, auto-classify via ticker dictionary
                    if not engine_val and sym != "UNKNOWN":
                        engine_val = classify_symbol(sym)
                        
                    if engine_val:
                        post_mortems.append({
                            "Engine": engine_val,
                            "Ticker": sym,
                            "Realized P/L ($)": pnl,
                            "Hold (Hrs)": 24.0, 
                            "Outcome": "WIN" if pnl > 0 else "LOSS"
                        })
                except Exception:
                    continue

    # ---------------------------------------------------------
    # ATTEMPT B: Direct Alpaca Deep Fetch (Merges Missing Trades)
    # ---------------------------------------------------------
    try:
        if api:
            # Fetch 400 closed orders to bypass the short 150 limit
            deep_orders = api.list_orders(status='closed', limit=400)
            
            sells = [o for o in deep_orders if o.side == 'sell' and o.status == 'filled']
            buys = [o for o in deep_orders if o.side == 'buy' and o.status == 'filled']
            
            for s in sells:
                sym = str(s.symbol)
                display_sym = CRYPTO_NORM.get(sym, sym)
                
                # Match sell to preceding buy
                matching_buy = next((b for b in buys if str(b.symbol) == sym and b.filled_at < s.filled_at), None)
                
                if matching_buy and s.filled_avg_price and matching_buy.filled_avg_price:
                    qty = float(s.filled_qty or s.qty or 0.0)
                    pnl = (float(s.filled_avg_price) - float(matching_buy.filled_avg_price)) * qty
                    
                    eng = classify_symbol(display_sym)
                    
                    # Deduplicate: Only add if this trade isn't already listed from the Google Sheet
                    is_dup = False
                    for pm in post_mortems:
                        if pm['Engine'] == eng and pm.get('Ticker') == display_sym and abs(pm['Realized P/L ($)'] - pnl) < 2.0:
                            is_dup = True
                            break
                            
                    if not is_dup:
                        post_mortems.append({
                            "Engine": eng,
                            "Ticker": display_sym,
                            "Realized P/L ($)": pnl,
                            "Hold (Hrs)": 12.0,
                            "Outcome": "WIN" if pnl > 0 else "LOSS"
                        })
    except Exception as e:
        pass

    df_pm = pd.DataFrame(post_mortems)
    attr_rows = []
    
    # ---------------------------------------------------------
    # Calculate Win Rates & RL Multipliers per Engine
    # ---------------------------------------------------------
    for eng in DEFAULT_ENGINE_CONFIG.keys():
        eng_pm = df_pm[df_pm["Engine"] == eng] if not df_pm.empty else pd.DataFrame()
        eng_pos = [p for p in positions if p["tranche"] == eng]

        wins = eng_pm[eng_pm["Realized P/L ($)"] > 0] if not eng_pm.empty else pd.DataFrame()
        losses = eng_pm[eng_pm["Realized P/L ($)"] <= 0] if not eng_pm.empty else pd.DataFrame()

        n_closed = len(eng_pm)
        win_rate = (len(wins) / n_closed * 100.0) if n_closed > 0 else 0.0
        gross_win = float(wins["Realized P/L ($)"].sum()) if not wins.empty else 0.0
        gross_loss = abs(float(losses["Realized P/L ($)"].sum())) if not losses.empty else 0.0
        profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (gross_win if gross_win > 0 else 0.0)
        avg_win = float(wins["Realized P/L ($)"].mean()) if not wins.empty else 0.0
        avg_loss = float(losses["Realized P/L ($)"].mean()) if not losses.empty else 0.0
        realized_net = gross_win - gross_loss
        unrealized_net = sum(p["unrealized_pl"] for p in eng_pos)
        avg_hold = float(eng_pm["Hold (Hrs)"].mean()) if not eng_pm.empty else 0.0

        reward_sig = np.clip(((profit_factor - 1.0) * 0.25) + ((win_rate - 50.0) / 200.0), -0.35, 0.35) if n_closed > 0 else 0.0
        rl_mult = float(np.exp(reward_sig))

        attr_rows.append({
            "Strategy Engine": eng,
            "Closed Trades": n_closed,
            "Open Trades": len(eng_pos),
            "Win Rate (%)": round(win_rate, 1),
            "Profit Factor": round(profit_factor, 2),
            "RL Policy Mult": f"{rl_mult:.2f}x",
            "Avg Win ($)": round(avg_win, 2),
            "Avg Loss ($)": round(avg_loss, 2),
            "Avg Hold (Hrs)": round(avg_hold, 1),
            "Realized P/L ($)": round(realized_net, 2),
            "Open P/L ($)": round(unrealized_net, 2),
            "Total Engine Alpha ($)": round(realized_net + unrealized_net, 2)
        })

    return pd.DataFrame(attr_rows), df_pm

@st.cache_data(ttl=120)
def fetch_macro_and_gex_telemetry():
    spy_chg, vix_val, spy_30d, net_gex = 0.0, 0.0, 0.0, 0.0
    try:
        spy_tk = yf.Ticker("SPY")
        spy = spy_tk.history(period="1mo")
        vix = yf.Ticker("^VIX").history(period="5d")
        if len(spy) >= 2:
            spy_chg = ((spy['Close'].iloc[-1] - spy['Close'].iloc[-2]) / spy['Close'].iloc[-2]) * 100
            spy_30d = ((spy['Close'].iloc[-1] - spy['Close'].iloc[0]) / spy['Close'].iloc[0]) * 100
        if not vix.empty:
            vix_val = float(vix['Close'].iloc[-1])
        exps = spy_tk.options
        if exps:
            ch = spy_tk.option_chain(exps[0])
            c_oi = float(ch.calls["openInterest"].fillna(0).sum())
            p_oi = float(ch.puts["openInterest"].fillna(0).sum())
            if (c_oi + p_oi) > 0:
                net_gex = round((c_oi - p_oi) / (c_oi + p_oi), 3)
    except Exception:
        pass
    macro_ok = (spy_chg > -1.5) and (vix_val < 28.0)
    return macro_ok, spy_chg, vix_val, spy_30d, net_gex

@st.cache_data(ttl=300)
def fetch_ticker_history(ticker, period="1y"):
    try:
        yf_sym = ticker.replace("/", "-")
        return yf.Ticker(yf_sym).history(period=period)
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=300)
def compute_portfolio_var_and_correlation(positions_tuple, equity):
    if not positions_tuple:
        return 0.0, 0.0, 0.0, pd.DataFrame()
    syms = [p[0] for p in positions_tuple]
    weights = np.array([p[1] for p in positions_tuple], dtype=float)
    if float(weights.sum()) <= 0:
        return 0.0, 0.0, 0.0, pd.DataFrame()

    ret_dict = {}
    for s in syms:
        df_h = fetch_ticker_history(s, period="3mo")
        if not df_h.empty and len(df_h) >= 20:
            ret_dict[s] = df_h["Close"].pct_change().dropna().tail(60)

    if not ret_dict:
        return 0.0, 0.0, 0.0, pd.DataFrame()

    df_rets = pd.DataFrame(ret_dict).dropna(how="all").fillna(0.0)
    corr_matrix = df_rets.corr() if len(df_rets.columns) >= 2 else pd.DataFrame()

    valid_syms = [s for s in syms if s in df_rets.columns]
    if not valid_syms:
        return 0.0, 0.0, 0.0, corr_matrix

    w_vec = np.array([dict(positions_tuple)[s] for s in valid_syms])
    port_daily_dlr_changes = df_rets[valid_syms].values @ w_vec

    var_95 = float(abs(np.percentile(port_daily_dlr_changes, 5))) if len(port_daily_dlr_changes) >= 10 else 0.0
    var_99 = float(abs(np.percentile(port_daily_dlr_changes, 1))) if len(port_daily_dlr_changes) >= 10 else 0.0
    tail_losses = port_daily_dlr_changes[port_daily_dlr_changes <= -var_95]
    cvar_95 = float(abs(tail_losses.mean())) if len(tail_losses) > 0 else var_99

    return round(var_95, 2), round(var_99, 2), round(cvar_95, 2), corr_matrix

def compute_quant_metrics(port_hist, equity, spy_30d):
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
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
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
        df_disc = parse_sheet_tab(spreadsheet.worksheet("Discovery Log"))
    except Exception:
        df_disc = pd.DataFrame()
    try:
        closed_ws = spreadsheet.worksheet("Closed Trades")
        closed_rows = closed_ws.get_all_values()
        df_closed = pd.DataFrame(closed_rows[1:], columns=closed_rows[0]) if len(closed_rows) > 1 else pd.DataFrame()
    except Exception:
        df_closed = pd.DataFrame()
    return df_core, df_mom, df_crypto, df_disc, df_closed

def filter_sub_engine_log(df_disc, tranche_key):
    """Isolates rows belonging to DISCOVERY, MEAN_REV, SMALL_CAP, or TAIL_HEDGE."""
    if df_disc.empty or "Decision" not in df_disc.columns:
        return pd.DataFrame()
    mask = df_disc["Decision"].astype(str).str.contains(f"\\[{tranche_key}\\]", regex=True, na=False)
    filtered = df_disc[mask].copy()
    if filtered.empty and tranche_key == "DISCOVERY":
        other_tags = ["\\[MEAN_REV\\]", "\\[SMALL_CAP\\]", "\\[TAIL_HEDGE\\]"]
        mask_other = df_disc["Decision"].astype(str).str.contains("|".join(other_tags), regex=True, na=False)
        return df_disc[~mask_other].copy()
    return filtered

def trigger_github_workflow(token, mode="auto"):
    if not token:
        st.sidebar.error("⚠️ Missing GitHub PAT. Paste token in sidebar or Streamlit Secrets.")
        return False
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
        st.sidebar.success(f"✅ Dispatched `{mode.upper()}` Mode!")
        return True
    else:
        resp2 = requests.post(
            "https://api.github.com/repos/MakkosHUN/autotradingbot/actions/workflows/schedule.yml/dispatches",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            json={"ref": "main"},
            timeout=10
        )
        if resp2.status_code == 204:
            st.sidebar.success(f"✅ Dispatched Workflow (`{mode.upper()}`)!")
            return True
        else:
            st.sidebar.error(f"GitHub Error ({resp.status_code}): Check token scopes (`repo`, `workflow`).")
            return False

# =====================================================================
# 4. DISCORD INTERACTIVE URL COMMAND HANDLER (`?discord_cmd=...`)
# =====================================================================
if "discord_cmd" in st.query_params:
    cmd_val = str(st.query_params["discord_cmd"]).strip().lower()
    st.query_params.clear()
    if cmd_val == "scan_all":
        trigger_github_workflow(GITHUB_PAT_SECRET, "auto")
        st.toast("🚀 Discord Command Executed: Dispatched Enabled Engines!", icon="✅")
    elif cmd_val == "scan_discovery":
        trigger_github_workflow(GITHUB_PAT_SECRET, "discovery")
        st.toast("🛰️ Discord Command Executed: Dispatched AI Discovery Agent!", icon="✅")
    elif cmd_val == "scan_momentum":
        trigger_github_workflow(GITHUB_PAT_SECRET, "momentum")
        st.toast("⚡ Discord Command Executed: Dispatched Momentum Engine!", icon="✅")
    elif cmd_val == "scan_crypto":
        trigger_github_workflow(GITHUB_PAT_SECRET, "crypto")
        st.toast("🪙 Discord Command Executed: Dispatched 24/7 Crypto Engine!", icon="✅")
    elif cmd_val == "snapshot" and DISCORD_WEBHOOK_SECRET and api:
        _, acct_snap, pos_snap, _, _, _ = fetch_alpaca_state()
        eq_s = acct_snap.get("equity", 0.0)
        open_s = sum(p["unrealized_pl"] for p in pos_snap)
        snap_msg = (
            f"📊 **Instant Mobile Snapshot Requested via Discord**\n"
            f"💰 **Net Equity:** `${eq_s:,.2f}` | 📈 **Open Alpha:** `${open_s:+,.2f}` ({len(pos_snap)} active positions)"
        )
        requests.post(DISCORD_WEBHOOK_SECRET, json={"content": snap_msg}, timeout=5)
        st.toast("📊 Live Snapshot pushed to your Discord channel!", icon="📲")
    elif cmd_val == "liquidate_crypto" and api:
        for p in api.list_positions():
            sym_c = CRYPTO_NORM.get(str(p.symbol), str(p.symbol))
            if classify_symbol(sym_c) == "CRYPTO":
                api.close_position(p.symbol)
        st.cache_data.clear()
        st.toast("🛑 Discord Command Executed: All Crypto positions liquidated!", icon="⚠️")

# =====================================================================
# 5. SIDEBAR TELEMETRY, 7-ENGINE DISPATCH & PRECISION ORDER DESK
# =====================================================================
if IS_ADMIN:
    with st.sidebar:
        st.markdown("### 💠 AETHER QUANT `v8.5 OMEGA`")
        st.caption("7-Engine Pod • L2 OBI • RL Meta • 10k Monte Carlo")

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

        st.markdown("#### 🚀 7-Engine Remote Dispatch")
        custom_pat = st.text_input(
            "GitHub PAT Override (Optional):",
            value="",
            type="password",
            placeholder="Uses GITHUB_PAT secret by default"
        )
        active_pat = custom_pat.strip() if custom_pat.strip() else GITHUB_PAT_SECRET

        dispatch_choice = st.selectbox(
            "Select Engine Mode to Fire:",
            ["auto (All Enabled Engines)", "all (Force All 7)", "core", "momentum", "crypto", "discovery", "mean_rev", "small_cap", "tail_hedge"],
            index=0
        )
        
        if st.button("⚡ Dispatch Selected Mode Now", use_container_width=True):
            clean_mode = dispatch_choice.split(" ")[0]
            trigger_github_workflow(active_pat, clean_mode)

        with st.expander("🎯 Manual Precision Order Desk"):
            st.caption("Execute an instant ATR Risk-Parity trade on any asset.")
            man_sym = st.selectbox("Select Asset:", ALL_ASSETS, index=0)
            man_risk_bps = st.slider("Risk Budget (% Equity):", 0.20, 1.00, 0.45, 0.05)
            
            if st.button("🚀 Submit Risk-Parity Buy", use_container_width=True):
                if api:
                    try:
                        _, acct_m, _, _, _, _ = fetch_alpaca_state()
                        eq_m = float(acct_m.get("equity", 100000.0))
                        df_m = fetch_ticker_history(man_sym, period="3mo")
                        px_m = float(df_m["Close"].iloc[-1])
                        tr_m = (df_m["High"] - df_m["Low"]).rolling(14).mean().iloc[-1]
                        atr_m = max(float(tr_m), px_m * 0.015)
                        is_c = "/" in man_sym
                        stop_d = 1.2 * atr_m
                        raw_q = (eq_m * (man_risk_bps / 100.0)) / stop_d
                        max_q = (eq_m * 0.04) / px_m
                        qty_m = round(min(raw_q, max_q), 4) if is_c else max(1, int(round(min(raw_q, max_q))))
                        if is_c:
                            api.submit_order(symbol=man_sym, qty=qty_m, side="buy", type="market", time_in_force="gtc")
                        else:
                            api.submit_order(
                                symbol=man_sym, qty=qty_m, side="buy", type="market", time_in_force="gtc",
                                order_class="bracket",
                                take_profit={"limit_price": round(px_m + 2.8 * atr_m, 2)},
                                stop_loss={"stop_price": round(px_m - stop_d, 2)}
                            )
                        st.cache_data.clear()
                        st.success(f"Submitted Buy: {qty_m} {man_sym} @ ~${px_m:.2f}")
                    except Exception as e:
                        st.error(f"Order error: {e}")

        st.markdown("#### 🛡️ System Safeguards")
        if spreadsheet:
            st.caption("🟢 **Cloud Audit & Config Ledger:** `Connected`")
        else:
            st.warning(f"🔴 **Sheets Disconnected:** `{sheet_status}`")

        @st.fragment(run_every="30s")
        def sidebar_safeguards():
            if api:
                _, acct_s, _, _, _, _ = fetch_alpaca_state()
                dt_count = int(acct_s.get('daytrade_count', 0))
                st.progress(min(dt_count / 3.0, 1.0), text=f"FINRA PDT Shield: {dt_count} / 3 Day Trades")
            _, spy_s, vix_s, _, gex_s = fetch_macro_and_gex_telemetry()
            st.markdown(f"""
            <div style="font-family:'JetBrains Mono',monospace; font-size:0.74rem; color:#94A3B8; margin-top:4px;">
                SPY: <span style="color:{'#10B981' if spy_s>=0 else '#F43F5E'}; font-weight:600;">{spy_s:+.2f}%</span> |
                VIX: <span style="color:{'#10B981' if vix_s<22 else '#F59E0B'}; font-weight:600;">{vix_s:.1f}</span> |
                GEX: <span style="color:{'#10B981' if gex_s>=0 else '#F43F5E'}; font-weight:600;">{gex_s:+.2f}</span>
            </div>
            """, unsafe_allow_html=True)

        sidebar_safeguards()

        with st.expander("🚨 Kill-Switch & Overrides"):
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
# 6. PRO TECHNICAL CHART, BACKTESTER & v8.5 10,000-PATH MONTE CARLO
# =====================================================================
def build_pro_technical_chart(ticker, df_yf):
    df = df_yf.copy()
    df["SMA200"] = df["Close"].rolling(200).mean()
    df["SMA50"] = df["Close"].rolling(50).mean()
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()

    typ_p = (df["High"] + df["Low"] + df["Close"]) / 3.0
    if "Volume" in df.columns and df["Volume"].sum() > 0:
        df["VWAP5"] = (typ_p * df["Volume"]).rolling(5).sum() / df["Volume"].rolling(5).sum()
    else:
        df["VWAP5"] = df["Close"]

    std20 = df["Close"].rolling(20).std()
    df["BB_UP"] = df["EMA20"] + (2.0 * std20)
    df["BB_LOW"] = df["EMA20"] - (2.0 * std20)

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

    fig.add_trace(go.Candlestick(
        x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
        low=df_plot["Low"], close=df_plot["Close"], name=ticker,
        increasing_line_color="#10B981", decreasing_line_color="#F43F5E"
    ), row=1, col=1)

    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["VWAP5"], line=dict(color="#EC4899", width=1.6, dash="dot"), name="5D-VWAP"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#38BDF8", width=1.7), name="20-EMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA50"], line=dict(color="#A855F7", width=1.5, dash="dash"), name="50-SMA"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], line=dict(color="#F59E0B", width=2.0, dash="dot"), name="200-SMA"), row=1, col=1)

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
        margin=dict(t=40, b=10, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.05, xanchor="left", x=0.01, font=dict(size=11)),
        hovermode="x unified"
    )
    fig.update_yaxes(title_text="Price ($)", gridcolor="rgba(255,255,255,0.05)", row=1, col=1)
    fig.update_yaxes(title_text="RSI-14", range=[15, 85], gridcolor="rgba(255,255,255,0.05)", row=2, col=1)
    fig.update_xaxes(gridcolor="rgba(255,255,255,0.03)")
    return fig

@st.cache_data(ttl=600)
def run_arbiter_backtest(tickers, period_str, sl_atr, tp_atr, risk_bps, w_news_override, vol_spike_mult):
    initial_cap = 100000.0
    equity = initial_cap
    trades_log = []
    regime_counts = {"NEWS-90/10": 0, "HYBRID-50/50": 0, "TECH-10/90": 0}
    equity_curve = []

    for sym in tickers:
        df = fetch_ticker_history(sym, period=period_str)
        if df.empty or len(df) < 40:
            continue
        df = df.copy()
        close = df["Close"]
        df["EMA9"] = close.ewm(span=9, adjust=False).mean()
        df["EMA20"] = close.ewm(span=20, adjust=False).mean()
        df["SMA50"] = close.rolling(50).mean().bfill()

        delta = close.diff()
        gain = delta.where(delta > 0, 0.0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        df["RSI"] = 100.0 - (100.0 / (1.0 + (gain / loss)))

        high_low = df["High"] - df["Low"]
        high_close = np.abs(df["High"] - close.shift())
        low_close = np.abs(df["Low"] - close.shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df["ATR"] = tr.rolling(14).mean().bfill()

        vol_ma = df["Volume"].rolling(20).mean().replace(0, 1.0).bfill()
        df["RelVol"] = (df["Volume"] / vol_ma).fillna(1.0)
        df["Ret1D"] = close.pct_change().fillna(0.0)

        in_pos = False
        entry_px, entry_dt, stop_px, target_px, pos_qty, entry_regime = 0.0, None, 0.0, 0.0, 0.0, ""

        for idx in range(25, len(df)):
            row = df.iloc[idx]
            dt_idx = df.index[idx]
            px_now = float(row["Close"])
            high_now = float(row["High"])
            low_now = float(row["Low"])
            atr_now = max(float(row["ATR"]), px_now * 0.01)
            rsi_now = float(row["RSI"]) if not pd.isna(row["RSI"]) else 50.0
            rel_v = float(row["RelVol"])
            ret_1d = float(row["Ret1D"])

            sim_finbert = float(np.clip(ret_1d * 12.0 * min(rel_v, 2.5), -0.95, 0.95))
            tech_s = 0.45 if px_now > row["EMA9"] > row["EMA20"] else (-0.35 if px_now < row["EMA20"] else 0.15)
            if rsi_now <= 32.0:
                tech_s += 0.45
            elif rsi_now >= 75.0:
                tech_s -= 0.45

            if abs(sim_finbert) >= 0.60 or rel_v >= vol_spike_mult:
                reg = "NEWS-90/10"
                w_n = max(w_news_override, 0.85)
                tp_m = tp_atr * 1.45
                rsi_ceil = 84.0
            elif abs(sim_finbert) >= 0.22:
                reg = "HYBRID-50/50"
                w_n = w_news_override
                tp_m = tp_atr
                rsi_ceil = 72.0
            else:
                reg = "TECH-10/90"
                w_n = min(w_news_override, 0.15)
                tp_m = tp_atr * 0.85
                rsi_ceil = 68.0

            comp = (w_n * sim_finbert) + ((1.0 - w_n) * tech_s)

            if in_pos:
                exit_hit, exit_px, reason = False, px_now, ""
                if low_now <= stop_px:
                    exit_hit, exit_px, reason = True, stop_px, "Chandelier / ATR Stop"
                elif high_now >= target_px:
                    exit_hit, exit_px, reason = True, target_px, f"Arbiter TP ({entry_regime})"
                elif reg == "TECH-10/90" and rsi_now >= 75.0 and px_now > entry_px:
                    exit_hit, exit_px, reason = True, px_now, "Arbiter 10/90 RSI Profit-Take"
                elif reg == "NEWS-90/10" and sim_finbert <= -0.50:
                    exit_hit, exit_px, reason = True, px_now, "Arbiter 90/10 News Reversal"

                if exit_hit:
                    pnl_d = (exit_px - entry_px) * pos_qty
                    pnl_p = ((exit_px - entry_px) / entry_px) * 100.0
                    equity += pnl_d
                    trades_log.append({
                        "Ticker": sym,
                        "Regime": entry_regime,
                        "Entry Date": str(entry_dt)[:10],
                        "Exit Date": str(dt_idx)[:10],
                        "Entry ($)": round(entry_px, 2),
                        "Exit ($)": round(exit_px, 2),
                        "Realized P/L ($)": round(pnl_d, 2),
                        "Return (%)": round(pnl_p, 2),
                        "Exit Reason": reason
                    })
                    equity_curve.append({"Date": dt_idx, "Equity": round(equity, 2)})
                    in_pos = False
                else:
                    gain_pct = (px_now - entry_px) / entry_px

if gain_pct >= 0.040:
    # At +4% and above: Trail peak price closely with ATR
    stop_px = max(stop_px, px_now - (1.0 * atr_now))
elif gain_pct >= 0.035:
    # At +3.5%: Lock in +2.5% guaranteed profit
    stop_px = max(stop_px, entry_px * 1.025)
elif gain_pct >= 0.030:
    # At +3.0%: Lock in +2.0% guaranteed profit
    stop_px = max(stop_px, entry_px * 1.020)
elif gain_pct >= 0.025:
    # At +2.5%: Lock in +1.5% guaranteed profit
    stop_px = max(stop_px, entry_px * 1.015)
elif gain_pct >= 0.020:
    # At +2.0%: Lock in +1.0% guaranteed profit
    stop_px = max(stop_px, entry_px * 1.010)
elif gain_pct >= 0.015:
    # At +1.5%: Lock in +0.5% guaranteed profit
    stop_px = max(stop_px, entry_px * 1.005)
elif gain_pct >= 0.010:
    # At +1.0%: Move stop to exact Break-Even (Risk-Free Trade)
    stop_px = max(stop_px, entry_px)
elif gain_pct >= 0.005:
    # At +0.5%: Cut initial risk in half
    initial_risk = entry_px - stop_px
    stop_px = max(stop_px, entry_px - (initial_risk * 0.5))
                if comp >= 0.16 and px_now >= float(row["EMA20"]) and rsi_now <= rsi_ceil:
                    stop_dist = max(sl_atr * atr_now, px_now * 0.01)
                    raw_q = (equity * (risk_bps / 100.0)) / stop_dist
                    max_q = (equity * 0.08) / px_now
                    pos_qty = max(0.01, min(raw_q, max_q))
                    entry_px = px_now
                    entry_dt = dt_idx
                    stop_px = px_now - stop_dist
                    target_px = px_now + (tp_m * atr_now)
                    entry_regime = reg
                    regime_counts[reg] = regime_counts.get(reg, 0) + 1
                    in_pos = True

    df_trades = pd.DataFrame(trades_log)
    df_eq = pd.DataFrame(equity_curve).sort_values("Date") if equity_curve else pd.DataFrame()
    return equity, df_trades, df_eq, regime_counts

def run_monte_carlo_10k(trade_pnls, n_paths=10000, horizon_trades=60, start_equity=100000.0):
    if len(trade_pnls) < 3:
        return None
    pnl_arr = np.array(trade_pnls, dtype=float)
    rng = np.random.default_rng(42)
    sampled = rng.choice(pnl_arr, size=(n_paths, horizon_trades), replace=True)
    cum_paths = start_equity + np.cumsum(sampled, axis=1)
    cum_paths = np.hstack([np.full((n_paths, 1), start_equity), cum_paths])

    p05 = np.percentile(cum_paths, 5, axis=0)
    p25 = np.percentile(cum_paths, 25, axis=0)
    p50 = np.percentile(cum_paths, 50, axis=0)
    p75 = np.percentile(cum_paths, 75, axis=0)
    p95 = np.percentile(cum_paths, 95, axis=0)

    terminal_eqs = cum_paths[:, -1]
    prob_profit = float((terminal_eqs > start_equity).mean() * 100.0)
    median_end = float(np.median(terminal_eqs))
    tail_5_end = float(np.percentile(terminal_eqs, 5))

    return {
        "steps": np.arange(horizon_trades + 1),
        "p05": p05, "p25": p25, "p50": p50, "p75": p75, "p95": p95,
        "prob_profit": prob_profit,
        "median_end": median_end,
        "tail_5_end": tail_5_end
    }

# =====================================================================
# 7. REUSABLE STRATEGY ENGINE WORKSTATION (ENGINES 1 THROUGH 7)
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

    dynamic_tickers = list(universe_tickers)
    if not df_log.empty and "Ticker" in df_log.columns:
        # Only accept valid stock tickers (1-6 uppercase letters, optional slash for crypto)
        import re
        logged_syms = [str(x).strip().upper() for x in df_log["Ticker"].unique() 
                       if str(x).strip() and re.match(r'^[A-Z]{1,6}(/[A-Z]{1,4})?$', str(x).strip().upper())]
        
        for s in reversed(logged_syms):
            if s not in dynamic_tickers:
                dynamic_tickers.insert(0, s)

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
            <div class="kpi-label"><span>MICROSTRUCTURE & RATCHET</span><span>⚖️</span></div>
            <div class="kpi-value">L2 OBI + Trail</div>
            <span class="kpi-delta delta-neu">VWAP • Corr Guard • Chandelier</span>
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
        "🔬 Pro Technical Workstation (VWAP + BBands + RSI)",
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

                if pl_pct >= 6.0:
                    shield_status = "🔥 STAGE-3 CHANDELIER TRAIL"
                elif pl_pct >= 4.0 or (sl_price and sl_price >= entry * 1.015):
                    shield_status = "🔒 STAGE-2 (+2% PROFIT LOCKED)"
                elif sl_price and sl_price >= entry - 0.01:
                    shield_status = "🛡️ STAGE-1 BREAK-EVEN LOCKED"
                else:
                    shield_status = "ATR Risk-Parity Bracket"

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
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Active Tranche Holdings & 3-Stage Chandelier Telemetry</div>', unsafe_allow_html=True)
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
                    "SL ➔ TP Gauge": st.column_config.ProgressColumn("SL ➔ TP Trajectory", format="%.0f%%", min_value=0, max_value=100)
                }
            )
        else:
            st.info(f"No open positions currently held in the **{tranche_key}** tranche.")

        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>Latest Screened {tranche_key} Candidates & Arbiter Regime Matrix</div>', unsafe_allow_html=True)
        if not df_log.empty:
            ticker_col = "Ticker" if "Ticker" in df_log.columns else df_log.columns[1]
            latest_matrix = df_log.drop_duplicates(subset=[ticker_col], keep="last").iloc[::-1].copy()
            if "FinBERT Score" in latest_matrix.columns:
                latest_matrix["FinBERT Score"] = pd.to_numeric(latest_matrix["FinBERT Score"], errors="coerce").fillna(0.0)
            st.dataframe(latest_matrix, use_container_width=True, hide_index=True)
        else:
            st.info(f"No scan records in `{tranche_key}` yet. Select `{tranche_key.lower()}` in the sidebar dispatch box to fire an immediate scan.")

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
            st.dataframe(df_log.iloc[::-1].head(100), use_container_width=True, hide_index=True)
        else:
            st.info("Audit ledger will populate automatically after the next scan.")

    with t3:
        st.markdown(f'<div class="sec-title"><span class="sec-dot"></span>Multi-Timeframe Technical & VWAP Inspector</div>', unsafe_allow_html=True)
        sel_ticker = st.selectbox(f"Select {tranche_key} Instrument:", dynamic_tickers, index=0, key=f"sel_{tranche_key}")
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
# 8. MAIN OMEGA TERMINAL RENDERER (AUTO-SYNCS EVERY 30S)
# =====================================================================
@st.fragment(run_every="30s")
def render_live_terminal():
    if not api:
        st.error("⚠️ Alpaca API credentials missing in Streamlit Secrets. Add `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY`.")
        return

    is_open, account, positions, active_orders, recent_orders, port_hist = fetch_alpaca_state()
    macro_ok, spy_chg, vix_val, spy_30d, net_gex = fetch_macro_and_gex_telemetry()
    df_core, df_mom, df_crypto, df_disc, df_closed = fetch_all_sheet_logs()
    engine_cfg = fetch_engine_config()
    df_attr, df_post_mortems = compute_trade_post_mortems(df_closed, positions,recent_orders)
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
    pos_tuple = tuple((p["symbol"], float(p["market_value"])) for p in positions)
    var_95, var_99, cvar_95, corr_matrix = compute_portfolio_var_and_correlation(pos_tuple, equity)
    breaker_ok = day_pl_pct > -2.0
    enabled_engines = [k for k, v in engine_cfg.items() if v["enabled"]]

    # Calculate Realized Fee & Estimated Spread Drag over recent FILLED orders
    total_fee_drag = 0.0
    for o in recent_orders:
        if o['status'] == 'FILLED' and float(o.get('qty', 0) or 0) > 0 and o['filled_avg_price'] is not None:
            qty = float(o['filled_qty'] or o['qty'])
            fill_px = float(o['filled_avg_price'])
            lim_px = float(o['limit_price']) if o['limit_price'] is not None else None
            
            base_fee = (fill_px * qty * 0.0015) if o['tranche'] == 'CRYPTO' else (qty * 0.003) # Alpaca Crypto vs Reg fees
            slippage = 0.0
            if lim_px:
                if o['side'] == 'BUY':
                    slippage = max(0.0, (fill_px - lim_px) * qty)
                elif o['side'] == 'SELL':
                    slippage = max(0.0, (lim_px - fill_px) * qty)
            else:
                slippage = fill_px * qty * 0.0005 # Base spread estimate for market fills
                
            total_fee_drag += (base_fee + slippage)

    # 1. Live Scrolling Institutional Ticker Tape
    tape_items = [
        f'<span class="ticker-item"><span class="ticker-sym">SPY</span><span class="{"up" if spy_chg>=0 else "down"}">{spy_chg:+.2f}%</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">VIX</span><span class="{"up" if vix_val<22 else "down"}">{vix_val:.2f}</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">GEX</span><span class="{"up" if net_gex>=0 else "down"}">{net_gex:+.2f}</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">95% VaR</span><span class="flat">${var_95:,.2f}</span></span>',
        f'<span class="ticker-item"><span class="ticker-sym">ACTIVE PODS</span><span class="flat">{len(enabled_engines)}/7</span></span>'
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
    cryp_pill = f'<span class="hud-pill hud-cyan">◈ {len(enabled_engines)}/7 ENGINES ACTIVE</span>'
    gex_pill = f'<span class="hud-pill {"hud-emerald" if net_gex>=0 else "hud-rose"}">SPY GEX: {net_gex:+.2f}</span>'
    pdt_pill = f'<span class="hud-pill hud-slate">PDT: {daytrades}/3</span>'

    st.markdown(f"""
    <div class="inst-header">
        <div class="brand-cluster">
            <div class="brand-orb"></div>
            <div>
                <div class="brand-title">AETHER QUANTITATIVE COMMAND <span class="brand-version">v8.5 OMEGA INSTITUTIONAL</span></div>
                <div class="brand-sub">7-Engine Pod Switchboard • Market-Wide AI Discovery Agent • v7.0 L2 OBI • v7.5 RL Meta-Allocator • v8.0 Options GEX • v8.5 10k Monte Carlo</div>
            </div>
        </div>
        <div class="badge-cluster">
            {mkt_pill}
            {cryp_pill}
            {gex_pill}
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
            <span class="kpi-delta {day_cls}">{day_pl_pct:+.2f}% (Breaker @ -2.0%)</span>
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
            <div class="kpi-label"><span>DAILY 95% VALUE-AT-RISK</span><span>🛡️</span></div>
            <div class="kpi-value">${var_95:,.2f}</div>
            <span class="kpi-delta delta-neu">99% CVaR Tail: ${cvar_95:,.2f}</span>
        </div>
        <div class="kpi-card">
            <div class="kpi-label"><span>FEE & SPREAD DRAG</span><span>💸</span></div>
            <div class="kpi-value">$-{total_fee_drag:,.2f}</div>
            <span class="kpi-delta delta-neg">Est. Cum. Broker Friction</span>
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
            <span class="alpha-lbl">OPTIONS GAMMA (SPY GEX):</span>
            <span class="alpha-val" style="color:{'#10B981' if net_gex>=0 else '#F43F5E'};">{net_gex:+.3f}</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">ALPHA VS. S&P 500 (30D):</span>
            <span class="alpha-val" style="color:{alpha_color};">{bench_alpha:+.2f}%</span>
        </div>
        <div class="alpha-item">
            <span class="alpha-lbl">LIQUID DRY POWDER:</span>
            <span class="alpha-val" style="color:#38BDF8;">${cash:,.2f} ({100.0 - exposure_pct:.1f}%)</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # 5. Full 11-Tab Top Horizontal Navigation Bar (All 7 Engines Unlocked)
    nav_options = [
        "🏛️ Master Overview & Attribution",
        "🎛️ 7-Engine Pod Switchboard",
        "🛡️ Engine 1: Core Long-Term",
        "⚡ Engine 2: Momentum (14x/NYSE)",
        "🪙 Engine 3: Crypto AI (48x/Day)",
        "🛰️ Engine 4: AI Discovery Agent",
        "🧲 Engine 5: Mean-Reversion",
        "🚀 Engine 6: Small-Cap Alpha",
        "🛡️ Engine 7: Tail-Hedge (GEX)",
        "🧪 Backtest & 10k Monte Carlo Lab",
        "📊 Risk, VaR, GEX & Correlation Lab"
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
    # VIEW 1: MASTER HEDGE FUND OVERVIEW & RL ATTRIBUTION
    # =================================================================
    if selected_page == nav_options[0]:
        st.markdown('<div class="sec-title"><span class="sec-dot"></span>7-Engine Performance Attribution & v7.5 RL Policy Meta-Allocator</div>', unsafe_allow_html=True)
        st.dataframe(
            df_attr,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Win Rate (%)": st.column_config.ProgressColumn("Win Rate (%)", format="%.1f%%", min_value=0, max_value=100),
                "Realized P/L ($)": st.column_config.NumberColumn("Realized P/L ($)", format="$%+.2f"),
                "Open P/L ($)": st.column_config.NumberColumn("Open P/L ($)", format="$%+.2f"),
                "Total Engine Alpha ($)": st.column_config.NumberColumn("Net Engine Alpha ($)", format="$%+.2f")
            }
        )

        col_eq, col_pie, col_asset = st.columns([1.6, 1, 1])
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

        with col_asset:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Asset Class Exposure Breakdown</div>', unsafe_allow_html=True)
            if positions:
                asset_exposures = {"Equities": 0.0, "Crypto": 0.0, "Commodities": 0.0}
                for p in positions:
                    sym = p['symbol']
                    val = p['market_value']
                    if p['tranche'] == 'CRYPTO' or sym in CRYPTO_PAIRS:
                        asset_exposures["Crypto"] += val
                    elif sym in ["GLD", "SLV", "USO", "UNG", "DBA"]:
                        asset_exposures["Commodities"] += val
                    else:
                        asset_exposures["Equities"] += val
                
                asset_df = pd.DataFrame({
                    "Class": list(asset_exposures.keys()),
                    "Value": list(asset_exposures.values())
                })
                asset_df = asset_df[asset_df["Value"] > 0]
                
                fig_asset = px.pie(
                    asset_df, values="Value", names="Class", hole=0.68,
                    color="Class",
                    color_discrete_map={"Equities": "#38BDF8", "Crypto": "#A855F7", "Commodities": "#F59E0B"}
                )
                fig_asset.update_traces(
                    textinfo="label+percent",
                    hovertemplate="<b>%{label}</b><br>Exposure: $%{value:,.2f}<br>Share: %{percent}<extra></extra>"
                )
                max_conc = asset_df['Value'].max() / invested * 100 if invested > 0 else 0.0
                fig_asset.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(t=10, b=10, l=10, r=10), height=330,
                    showlegend=False,
                    annotations=[dict(
                        text=(
                            f"<span style='color:#64748B; font-size:10px;'>MAX CONC.</span><br>"
                            f"<b style='color:#F8FAFC; font-size:16px;'>{max_conc:.1f}%</b><br>"
                            f"<span style='color:#{'10B981' if max_conc<=50 else 'F43F5E'}; font-size:11px;'>{'Safe' if max_conc<=50 else 'Warning >50%'}</span>"
                        ),
                        x=0.5, y=0.5, showarrow=False
                    )]
                )
                st.plotly_chart(fig_asset, use_container_width=True)
            else:
                st.info("No active exposure.")

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
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Top Bullish Arbiter Signals Across All 7 Engines</div>', unsafe_allow_html=True)
            combined_logs = []
            for tag, d_f in [("CORE", df_core), ("MOMENTUM", df_mom), ("CRYPTO", df_crypto), ("DISC/SPEC", df_disc)]:
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

    # =================================================================
    # VIEW 2: 7-ENGINE MODE SWITCHBOARD
    # =================================================================
    elif selected_page == nav_options[1]:
        st.markdown('<div class="sec-title"><span class="sec-dot"></span>7-Engine Strategy Palette & Live Pod Switchboard</div>', unsafe_allow_html=True)
        st.caption("Toggle any combination of the 7 trading engines ON or OFF (e.g., trade 1 specific mode, pick 3, or enable all 7). Changes sync directly to Google Sheets (`Engine Config`) and govern all automated GitHub Actions runs.")

        with st.form("engine_switchboard_form"):
            new_cfg = {}
            cols_row1 = st.columns(4)
            cols_row2 = st.columns(3)
            all_cols = cols_row1 + cols_row2

            for idx, (eng_k, eng_v) in enumerate(engine_cfg.items()):
                with all_cols[idx]:
                    st.markdown(f"**`{eng_k}`**")
                    st.caption(f"{eng_v['desc']}  \n*{DEFAULT_ENGINE_CONFIG[eng_k]['freq']}*")
                    en_val = st.toggle("Enable Engine", value=eng_v["enabled"], key=f"tog_{eng_k}")
                    cap_val = st.slider("Base Cap (% Equity)", 5, 50, int(round(eng_v["cap"] * 100)), 5, key=f"cap_{eng_k}")
                    risk_val = st.slider("Risk/Trade (bps)", 20, 100, int(round(eng_v["risk_bps"] * 10000)), 5, key=f"rsk_{eng_k}")
                    new_cfg[eng_k] = {
                        "enabled": en_val,
                        "cap": round(cap_val / 100.0, 2),
                        "risk_bps": round(risk_val / 10000.0, 4),
                        "desc": eng_v["desc"]
                    }

            if IS_ADMIN:
                if st.form_submit_button("💾 Save 7-Engine Pod Configuration to Cloud Ledger", use_container_width=True, type="primary"):
                    if save_engine_config_to_sheet(new_cfg):
                        st.success("✅ 7-Engine configuration saved! Next scheduled or manual run will trade your exact active pod selection.")
                        st.rerun()
            else:
                st.form_submit_button("💾 Save 7-Engine Pod Configuration to Cloud Ledger (Disabled)", use_container_width=True, type="primary", disabled=True)
                st.info("👀 Read-Only Mode: You are viewing a live demo. Configuration saving is disabled.")

    # =================================================================
    # VIEW 3: ENGINE 1 — CORE LONG-TERM EQUITIES
    # =================================================================
    elif selected_page == nav_options[2]:
        render_strategy_engine_view(
            engine_title="Engine 1: Core Blue-Chip Trend Equities (Arbiter + L2 OBI + 3-Stage Ratchet)",
            engine_subtitle="Mandate: S&P 500 Leaders • 2x/Day Execution • Price > 200-SMA & 5D-VWAP • 1.5x / 3.5x ATR Brackets",
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
    # VIEW 4: ENGINE 2 — SHORT-TERM MOMENTUM (14x/DAY)
    # =================================================================
    elif selected_page == nav_options[3]:
        render_strategy_engine_view(
            engine_title="Engine 2: Tactical Short-Term Momentum (14x/Day High-Frequency • L2 OBI • 3-Stage Ratchet)",
            engine_subtitle="Mandate: High-Beta Tech & Growth • Scans Every 30 Mins During NYSE Hours • 90/10 News Catalyst Runner or 10/90 VWAP Scalp",
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
    # VIEW 5: ENGINE 3 — 24/7 CRYPTO AI QUANT (48x/DAY)
    # =================================================================
    elif selected_page == nav_options[4]:
        render_strategy_engine_view(
            engine_title="Engine 3: 24/7 Crypto AI Quant (48x/Day Every 30 Mins • L2 OBI • Dynamic Trail)",
            engine_subtitle="Mandate: Round-the-Clock Crypto Execution (Zero PDT) • Scans Every 30 Minutes 24/7/365 • Dynamic +8.7% / +6.0% / +5.1% TP",
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

    # =================================================================
    # VIEW 6: ENGINE 4 — MARKET-WIDE AI DISCOVERY AGENT
    # =================================================================
    elif selected_page == nav_options[5]:
        df_sub_disc = filter_sub_engine_log(df_disc, "DISCOVERY")
        render_strategy_engine_view(
            engine_title="Engine 4: Market-Wide AI Discovery Agent (Unconstrained Global Breaking News Hunter)",
            engine_subtitle="Mandate: Scans Alpaca Global Breaking News Firehose (8,000+ Stocks) • Filters Tradable Catalysts via FinBERT + L2 OBI + Arbiter",
            tranche_key="DISCOVERY",
            universe_tickers=MOMENTUM_TICKERS[:10] + SMALL_CAP_TICKERS[:10],
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_sub_disc,
            equity=equity,
            buy_thresh=0.15,
            exit_thresh=-0.15,
            is_crypto=False
        )

    # =================================================================
    # VIEW 7: ENGINE 5 — STATISTICAL MEAN-REVERSION
    # =================================================================
    elif selected_page == nav_options[6]:
        df_sub_mr = filter_sub_engine_log(df_disc, "MEAN_REV")
        render_strategy_engine_view(
            engine_title="Engine 5: Statistical Mean-Reversion (Extreme Oversold Bollinger & Wilder RSI <= 32 Snapback)",
            engine_subtitle="Mandate: Institutional Pullback Arbitrage • Buys 2-Sigma Lower Bollinger & RSI <= 32 Dips Above 200-SMA • Exits on RSI >= 58 Snapback",
            tranche_key="MEAN_REV",
            universe_tickers=MEAN_REV_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_sub_mr,
            equity=equity,
            buy_thresh=-0.10,
            exit_thresh=-0.30,
            is_crypto=False
        )

    # =================================================================
    # VIEW 8: ENGINE 6 — SMALL-CAP ALPHA BREAKOUTS
    # =================================================================
    elif selected_page == nav_options[7]:
        df_sub_sc = filter_sub_engine_log(df_disc, "SMALL_CAP")
        render_strategy_engine_view(
            engine_title="Engine 6: Small-Cap & High-Beta Speculative Breakouts (Russell 2000 / AI / Space / Quantum)",
            engine_subtitle="Mandate: High-Velocity Volume Surges (IONQ, RKLB, ASTS, SMR, OKLO, HIMS, SOFI) • Tight ATR Risk-Parity Sizing (0.30% Risk/Trade)",
            tranche_key="SMALL_CAP",
            universe_tickers=SMALL_CAP_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_sub_sc,
            equity=equity,
            buy_thresh=0.10,
            exit_thresh=-0.12,
            is_crypto=False
        )

    # =================================================================
    # VIEW 9: ENGINE 7 — OPTIONS GEX & TAIL-HEDGE OVERLAY
    # =================================================================
    elif selected_page == nav_options[8]:
        df_sub_th = filter_sub_engine_log(df_disc, "TAIL_HEDGE")
        render_strategy_engine_view(
            engine_title="Engine 7: v8.0 Options Gamma Exposure (GEX) & Inverse ETF Tail-Hedge Shield (SH / PSQ / GLD)",
            engine_subtitle="Mandate: Automated Crash Protection • Deploys ProShares Short S&P 500 (SH) When Macro Shield Trips or SPY Options GEX <= -0.18",
            tranche_key="TAIL_HEDGE",
            universe_tickers=TAIL_HEDGE_TICKERS,
            positions=positions,
            active_orders=active_orders,
            recent_orders=recent_orders,
            df_log=df_sub_th,
            equity=equity,
            buy_thresh=0.00,
            exit_thresh=-0.20,
            is_crypto=False
        )

    # =================================================================
    # VIEW 10: BACKTEST & v8.5 10,000-PATH MONTE CARLO SIMULATOR
    # =================================================================
    elif selected_page == nav_options[9]:
        st.markdown('<div class="sec-title"><span class="sec-dot"></span>In-Terminal Strategy Backtest & v8.5 10,000-Path Walk-Forward Monte Carlo Engine</div>', unsafe_allow_html=True)
        st.caption("Simulate historical Arbiter + Chandelier performance and stress-test parameter stability across 10,000 bootstrap-resampled Monte Carlo trajectories.")

        b_col1, b_col2, b_col3, b_col4 = st.columns(4)
        with b_col1:
            bt_universe_name = st.selectbox("Select Strategy Universe:", ["⚡ Momentum Top 8", "🛡️ Core Blue-Chips Top 8", "🪙 Crypto 24/7 Pairs", "🚀 Small-Cap Alpha Top 8"])
        with b_col2:
            bt_period = st.selectbox("Historical Lookback Window:", ["6mo", "1y", "3mo"], index=0)
        with b_col3:
            bt_w_news = st.slider("Base News vs. Tech Weight:", min_value=0.10, max_value=0.90, value=0.50, step=0.05)
        with b_col4:
            bt_risk_bps = st.slider("ATR Risk-Parity Budget (% Equity/Trade):", min_value=0.20, max_value=1.50, value=0.50, step=0.10)

        p_col1, p_col2, p_col3 = st.columns(3)
        with p_col1:
            bt_sl_atr = st.number_input("Stop-Loss ATR Multiplier:", min_value=0.5, max_value=3.0, value=1.2, step=0.1)
        with p_col2:
            bt_tp_atr = st.number_input("Base Take-Profit ATR Multiplier:", min_value=1.0, max_value=6.0, value=2.5, step=0.25)
        with p_col3:
            bt_vol_spike = st.number_input("90/10 Catalyst Volume Spike Trigger (x Avg):", min_value=1.3, max_value=4.0, value=1.8, step=0.1)

        if bt_universe_name.startswith("⚡"):
            bt_tickers = MOMENTUM_TICKERS[:8]
        elif bt_universe_name.startswith("🛡️"):
            bt_tickers = CORE_TICKERS[:8]
        elif bt_universe_name.startswith("🚀"):
            bt_tickers = SMALL_CAP_TICKERS[:8]
        else:
            bt_tickers = CRYPTO_PAIRS[:6]

        final_eq, df_bt_trades, df_bt_eq, reg_counts = run_arbiter_backtest(
            bt_tickers, bt_period, bt_sl_atr, bt_tp_atr, bt_risk_bps, bt_w_news, bt_vol_spike
        )

        sim_ret_pct = ((final_eq - 100000.0) / 100000.0) * 100.0
        n_bt = len(df_bt_trades)
        bt_wins = df_bt_trades[df_bt_trades["Realized P/L ($)"] > 0] if not df_bt_trades.empty else pd.DataFrame()
        bt_losses = df_bt_trades[df_bt_trades["Realized P/L ($)"] <= 0] if not df_bt_trades.empty else pd.DataFrame()
        bt_wr = (len(bt_wins) / n_bt * 100.0) if n_bt > 0 else 0.0
        bt_gw = float(bt_wins["Realized P/L ($)"].sum()) if not bt_wins.empty else 0.0
        bt_gl = abs(float(bt_losses["Realized P/L ($)"].sum())) if not bt_losses.empty else 0.0
        bt_pf = (bt_gw / bt_gl) if bt_gl > 0 else (bt_gw if bt_gw > 0 else 0.0)

        mc_res = run_monte_carlo_10k(df_bt_trades["Realized P/L ($)"].tolist(), n_paths=10000, horizon_trades=60) if n_bt >= 3 else None

        sim_cls = "delta-pos" if sim_ret_pct >= 0 else "delta-neg"
        st.markdown(f"""
        <div class="kpi-grid" style="grid-template-columns: repeat(4, 1fr); margin-top: 10px;">
            <div class="kpi-card">
                <div class="kpi-label"><span>SIMULATED ENDING EQUITY</span><span>🧪</span></div>
                <div class="kpi-value">${final_eq:,.2f}</div>
                <span class="kpi-delta {sim_cls}">{sim_ret_pct:+.2f}% Historical Return ({bt_period})</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>SIMULATED WIN RATE & PF</span><span>🎯</span></div>
                <div class="kpi-value">{bt_wr:.1f}% ({bt_pf:.2f}x)</div>
                <span class="kpi-delta delta-neu">{n_bt} Historical Trades</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>10K MONTE CARLO MEDIAN (60T)</span><span>🎲</span></div>
                <div class="kpi-value">${mc_res['median_end']:,.0f}</div>
                <span class="kpi-delta delta-pos">Prob. of Profit: {mc_res['prob_profit']:.1f}%</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>MONTE CARLO 5% TAIL FLOOR</span><span>🛡️</span></div>
                <div class="kpi-value">${mc_res['tail_5_end']:,.0f}</div>
                <span class="kpi-delta delta-neu">95% Confidence Survival Floor</span>
            </div>
        </div>
        """ if mc_res else "<p>Run with more trades to populate Monte Carlo metrics.</p>", unsafe_allow_html=True)

        mc_col1, mc_col2 = st.columns(2)
        with mc_col1:
            if not df_bt_eq.empty:
                st.markdown('<div class="sec-title"><span class="sec-dot"></span>Historical Walk-Forward Equity Curve</div>', unsafe_allow_html=True)
                fig_bt = go.Figure()
                fig_bt.add_trace(go.Scatter(
                    x=df_bt_eq["Date"], y=df_bt_eq["Equity"], mode="lines+markers",
                    line=dict(color="#38BDF8", width=2.5), fill="tozeroy", fillcolor="rgba(56, 189, 248, 0.08)",
                    name="Historical Equity"
                ))
                fig_bt.add_hline(y=100000.0, line_dash="dot", line_color="rgba(148,163,184,0.4)")
                fig_bt.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(11,15,25,0.55)", height=330,
                    margin=dict(t=12, b=12, l=10, r=10), yaxis=dict(title="Equity ($)", gridcolor="rgba(255,255,255,0.05)")
                )
                st.plotly_chart(fig_bt, use_container_width=True)

        with mc_col2:
            if mc_res:
                st.markdown('<div class="sec-title"><span class="sec-dot"></span>v8.5 10,000-Path Monte Carlo Fan Chart (5th–95th Percentiles)</div>', unsafe_allow_html=True)
                fig_mc = go.Figure()
                fig_mc.add_trace(go.Scatter(x=mc_res["steps"], y=mc_res["p95"], line=dict(color="rgba(16,185,129,0.3)", width=1), name="95th Pct (Bull)"))
                fig_mc.add_trace(go.Scatter(x=mc_res["steps"], y=mc_res["p05"], line=dict(color="rgba(244,63,94,0.3)", width=1), fill="tonexty", fillcolor="rgba(56,189,248,0.08)", name="5th Pct (Tail Risk)"))
                fig_mc.add_trace(go.Scatter(x=mc_res["steps"], y=mc_res["p75"], line=dict(color="rgba(56,189,248,0.4)", width=1, dash="dot"), name="75th Pct"))
                fig_mc.add_trace(go.Scatter(x=mc_res["steps"], y=mc_res["p25"], line=dict(color="rgba(56,189,248,0.4)", width=1, dash="dot"), fill="tonexty", fillcolor="rgba(16,185,129,0.12)", name="25th Pct"))
                fig_mc.add_trace(go.Scatter(x=mc_res["steps"], y=mc_res["p50"], line=dict(color="#10B981", width=2.6), name="Median Path (50th)"))
                fig_mc.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(11,15,25,0.55)", height=330,
                    margin=dict(t=12, b=12, l=10, r=10),
                    xaxis=dict(title="Forward Trade Sequence (60 Trades)"),
                    yaxis=dict(title="Projected Equity ($)", gridcolor="rgba(255,255,255,0.05)"),
                    showlegend=False
                )
                st.plotly_chart(fig_mc, use_container_width=True)

        if not df_bt_trades.empty:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Simulated Trade-by-Trade Arbiter Ledger</div>', unsafe_allow_html=True)
            st.dataframe(df_bt_trades.iloc[::-1], use_container_width=True, hide_index=True)

    # =================================================================
    # VIEW 11: INSTITUTIONAL RISK, VaR, OPTIONS GEX & CORRELATION LAB
    # =================================================================
    elif selected_page == nav_options[10]:
        st.markdown('<div class="sec-title"><span class="sec-dot"></span>Institutional Risk Management, VaR / CVaR, Options GEX & Correlation Lab</div>', unsafe_allow_html=True)

        st.markdown(f"""
        <div class="kpi-grid" style="grid-template-columns: repeat(4, 1fr);">
            <div class="kpi-card">
                <div class="kpi-label"><span>DAILY 95% VaR (HISTORICAL)</span><span>🛡️</span></div>
                <div class="kpi-value">${var_95:,.2f}</div>
                <span class="kpi-delta delta-neu">{(var_95/equity)*100 if equity>0 else 0:.2f}% of Account Equity</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>EXPECTED SHORTFALL (CVaR)</span><span>📉</span></div>
                <div class="kpi-value">${cvar_95:,.2f}</div>
                <span class="kpi-delta delta-neg">Mean Tail Loss Beyond 95% VaR</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>S&P 500 OPTIONS GEX PROXY</span><span>🧬</span></div>
                <div class="kpi-value">{net_gex:+.3f}</div>
                <span class="kpi-delta {'delta-pos' if net_gex>=0 else 'delta-neg'}">{'Positive Gamma Cushion' if net_gex>=0 else 'Negative Gamma Volatility Regime'}</span>
            </div>
            <div class="kpi-card">
                <div class="kpi-label"><span>INTRADAY CIRCUIT BREAKER</span><span>🔌</span></div>
                <div class="kpi-value">{'ARMED' if breaker_ok else 'TRIPPED'}</div>
                <span class="kpi-delta {'delta-pos' if breaker_ok else 'delta-neg'}">Triggers @ -2.00% Daily Loss</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        r_col1, r_col2 = st.columns([1.15, 1])
        with r_col1:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>60-Day Cross-Asset Pearson Correlation Matrix (Guard Threshold = 0.82)</div>', unsafe_allow_html=True)
            if not corr_matrix.empty and len(corr_matrix.columns) >= 2:
                fig_corr = px.imshow(
                    corr_matrix.round(2), text_auto=True,
                    color_continuous_scale=["#10B981", "#0F172A", "#F43F5E"], zmin=-1.0, zmax=1.0
                )
                fig_corr.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    height=350, margin=dict(t=10, b=10, l=10, r=10)
                )
                st.plotly_chart(fig_corr, use_container_width=True)
            else:
                st.info("Correlation matrix heatmap requires at least 2 active positions.")

        with r_col2:
            st.markdown('<div class="sec-title"><span class="sec-dot"></span>Black-Swan Macro Stress-Test Simulator</div>', unsafe_allow_html=True)
            shock_pct = st.slider("Simulate Instant Market Shock (%):", min_value=-25.0, max_value=15.0, value=-8.0, step=1.0)
            if positions:
                stress_rows = []
                for p in positions:
                    beta_mult = -1.0 if p["tranche"] == "TAIL_HEDGE" else (1.65 if p["tranche"] == "CRYPTO" else (1.35 if p["tranche"] in ["MOMENTUM", "SMALL_CAP"] else 0.85))
                    est_move_pct = shock_pct * beta_mult
                    est_dlr_impact = p["market_value"] * (est_move_pct / 100.0)
                    stress_rows.append({
                        "Ticker": p["symbol"],
                        "Tranche": p["tranche"],
                        "Beta Mult": f"{beta_mult:+.2f}x",
                        "Current Value": f"${p['market_value']:,.2f}",
                        "Est. Shock Move": f"{est_move_pct:+.1f}%",
                        "Projected P/L Impact ($)": round(est_dlr_impact, 2)
                    })
                df_stress = pd.DataFrame(stress_rows)
                tot_shock_dlr = float(df_stress["Projected P/L Impact ($)"].sum())
                st.caption(f"Projected Portfolio Impact under **{shock_pct:+.1f}%** Market Shock: **`${tot_shock_dlr:+,.2f}`** (`{(tot_shock_dlr/equity)*100:+.2f}%` of Total Equity)")
                st.dataframe(df_stress, use_container_width=True, hide_index=True)
            else:
                st.info("No active positions exposed to market shock.")

render_live_terminal()
