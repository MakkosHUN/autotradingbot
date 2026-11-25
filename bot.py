import os
import re
import json
import time
import math
import argparse
import logging
import requests
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal, ROUND_DOWN
import alpaca_trade_api as tradeapi
import yfinance as yf
import pandas as pd
import numpy as np
import gspread
from google.oauth2.service_account import Credentials
from transformers import pipeline
import torch

# Configure structured logging for institutional observability
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# =====================================================================
# 1. INITIALIZE CONNECTIONS & SANITIZED CREDENTIALS
# =====================================================================
API_KEY = os.environ.get("APCA_API_KEY_ID", "").strip()
API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "").strip()
BASE_URL = "https://paper-api.alpaca.markets"
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()

# Fallback to https://share.streamlit.io if DASHBOARD_URL secret is empty
raw_dash_url = os.environ.get("DASHBOARD_URL", "").strip().rstrip("/")
DASHBOARD_URL = raw_dash_url if raw_dash_url.startswith("http") else "https://share.streamlit.io"

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

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
CREDENTIALS_FILE = "service_account.json"
spreadsheet = None

# Supports local file first (for institutional code review), falls back to GitHub Actions env secret
if os.path.exists(CREDENTIALS_FILE):
    try:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open("Auto-Trading Bot Log")
    except Exception as e:
        logging.error(f"Google Sheets File Auth Error: {e}")
else:
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
        try:
            creds = Credentials.from_service_account_info(creds_json, scopes=SCOPES)
            gc = gspread.authorize(creds)
            spreadsheet = gc.open("Auto-Trading Bot Log")
        except Exception as e:
            logging.error(f"Google Sheets Env Auth Error: {e}")
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
discovery_sheet = get_or_create_worksheet(spreadsheet, "Discovery Log", LOG_HEADERS)
mean_rev_sheet = get_or_create_worksheet(spreadsheet, "MeanRev Log", LOG_HEADERS)
small_cap_sheet = get_or_create_worksheet(spreadsheet, "SmallCap Log", LOG_HEADERS)
commodities_sheet = get_or_create_worksheet(spreadsheet, "Commodities Log", LOG_HEADERS)
defense_sheet = get_or_create_worksheet(spreadsheet, "Defense Log", LOG_HEADERS)
tail_hedge_sheet = get_or_create_worksheet(spreadsheet, "TailHedge Log", LOG_HEADERS)
predator_sheet = get_or_create_worksheet(spreadsheet, "Predator Log", LOG_HEADERS)
closed_sheet = get_or_create_worksheet(
    spreadsheet,
    "Closed Trades",
    ["Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID", "Engine", "Entry Price", "Realized P/L ($)", "Return (%)"]
)
slippage_sheet = get_or_create_worksheet(
    spreadsheet,
    "Slippage Audit",
    ["Timestamp (UTC)", "Ticker", "Side", "Order Type", "Ref Price", "Fill Price", "Slippage (bps)", "Qty", "Engine", "Order ID"]
)
config_sheet = get_or_create_worksheet(
    spreadsheet,
    "Engine Config",
    ["Engine", "Enabled", "Base_Cap_Pct", "Risk_Bps", "Description"]
)

# =====================================================================
# 2. STRICTLY DISJOINT MASTER POOLS (NO CANNIBALIZATION) + MULTI-ASSET TRANCHES
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
# --- UPGRADED CRYPTO UNIVERSE (LIQUID PAIRS ONLY) ---
CRYPTO_MAJORS = ["BTC/USD", "ETH/USD", "SOL/USD"]
CRYPTO_ALTS = ["XRP/USD", "DOGE/USD", "AVAX/USD", "LINK/USD", "LTC/USD"]
CRYPTO_POOL = CRYPTO_MAJORS + CRYPTO_ALTS

# Disjoint Mean-Reversion Pool (Sector ETFs & Oversold Value Pullbacks)
MEAN_REV_POOL = [
    'QQQ', 'IWM', 'DIA', 'SMH', 'XLF', 'XLE', 'XLK', 'XLV', 'XBI', 'ARKK',
    'TLT', 'GDX', 'NKE', 'SBUX', 'PYPL', 'TGT', 'BA', 'LULU', 'DE', 'FDX'
]
SMALL_CAP_POOL = [
    'IONQ', 'RKLB', 'AFRM', 'UPST', 'HIMS', 'ASTS', 'LUNR', 'SMR', 'OKLO', 'SERV',
    'JOBY', 'ACHR', 'CELH', 'CVNA', 'AI', 'SOUN'
]

# --- MULTI-ASSET DEFENSIVE TRANCHES ---
COMMODITY_POOL = ['GLD', 'SLV', 'USO']
DEFENSE_POOL = ['LMT', 'RTX', 'NOC', 'GD']

# Broad Market Radar for Engine 4 Discovery Agent (Removed Defense overlaps)
DISCOVERY_RADAR_POOL = [
    'DELL', 'ANET', 'VRT', 'CEG', 'VST', 'AXON', 'APP', 'TTD', 'NET', 'DDOG',
    'ZS', 'MDB', 'TEAM', 'NOW', 'WDAY', 'FTNT', 'GILD', 'AMGN', 'REGN', 'VRTX',
    'ISRG', 'SYK', 'BSX', 'GE', 'GS', 'MS', 'BLK',
    'SCHW', 'AXP', 'C', 'BX', 'KKR', 'APO', 'PGR', 'CB', 'MMC', 'CME'
]
TAIL_HEDGE_POOL = ['SH', 'PSQ']
CRYPTO_NORM = {c.replace("/", ""): c for c in CRYPTO_POOL}

DEFAULT_ENGINE_CONFIG = {
    "CORE":        {"enabled": True, "cap": 0.35, "risk_bps": 0.0050, "desc": "S&P 500 Blue-Chip Trend Equities"},
    "MOMENTUM":    {"enabled": True, "cap": 0.25, "risk_bps": 0.0040, "desc": "High-Beta Tech & Growth Breakouts"},
    "CRYPTO":      {"enabled": True, "cap": 0.15, "risk_bps": 0.0045, "desc": "24/7 Digital Asset Quant (48x/Day)"},
    "DISCOVERY":   {"enabled": True, "cap": 0.15, "risk_bps": 0.0035, "desc": "Unconstrained Market-Wide News Catalyst Agent"},
    "MEAN_REV":    {"enabled": True, "cap": 0.15, "risk_bps": 0.0035, "desc": "Statistical Arbitrage / Bollinger Oversold Snapback"},
    "SMALL_CAP":   {"enabled": True, "cap": 0.10, "risk_bps": 0.0030, "desc": "Russell 2000 & High-Velocity Speculative Breakouts"},
    "TAIL_HEDGE":  {"enabled": True, "cap": 0.10, "risk_bps": 0.0050, "desc": "v8.0 Options GEX & Inverse ETF Crash Shield"},
    "COMMODITIES": {"enabled": True, "cap": 0.10, "risk_bps": 0.0035, "desc": "Precious Metals & Energy Hard Assets"},
    "DEFENSE":     {"enabled": True, "cap": 0.10, "risk_bps": 0.0035, "desc": "Aerospace & Defense Safe Haven"},
    "PREDATOR":    {"enabled": True, "cap": 0.15, "risk_bps": 0.0050, "desc": "Engine 8: Retail Stop-Loss & Liquidity Flush Trapper"}
}

def load_or_init_engine_config():
    cfg = {k: dict(v) for k, v in DEFAULT_ENGINE_CONFIG.items()}
    if not config_sheet:
        return cfg
    try:
        rows = config_sheet.get_all_values()
        if len(rows) <= 1:
            init_rows = [
                [k, "TRUE" if v["enabled"] else "FALSE", str(v["cap"]), str(v["risk_bps"]), v["desc"]]
                for k, v in cfg.items()
            ]
            config_sheet.append_rows(init_rows)
            return cfg
        for r in rows[1:]:
            if len(r) >= 4 and r[0] in cfg:
                eng = r[0].strip()
                cfg[eng]["enabled"] = str(r[1]).strip().upper() in ["TRUE", "1", "YES", "ON", "ACTIVE"]
                try:
                    cfg[eng]["cap"] = float(r[2])
                    cfg[eng]["risk_bps"] = float(r[3])
                except Exception as e:
                    logging.warning(f"Config float parse warning for {eng}: {e}")
    except Exception as e:
        logging.warning(f"Engine config read warning: {e}")
    return cfg

def to_yf_symbol(ticker):
    return ticker.replace("/", "-")

def to_alpaca_pos_symbol(ticker):
    return ticker.replace("/", "")

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in TAIL_HEDGE_POOL:
        return "TAIL_HEDGE"
    if sym in CRYPTO_POOL or s_clean in CRYPTO_NORM or sym.endswith("/USD") or (s_clean.endswith("USD") and len(s_clean) >= 6):
        return "CRYPTO"
    if sym in COMMODITY_POOL:
        return "COMMODITIES"
    if sym in DEFENSE_POOL:
        return "DEFENSE"
    if sym in CORE_POOL:
        return "CORE"
    if sym in MOMENTUM_POOL:
        return "MOMENTUM"
    if sym in MEAN_REV_POOL:
        return "MEAN_REV"
    if sym in SMALL_CAP_POOL:
        return "SMALL_CAP"
    return "DISCOVERY"

# =====================================================================
# 3. v8.6 REINFORCEMENT LEARNING META-ALLOCATOR (GEX DEFENSIVE SHIFT)
# =====================================================================
def compute_rl_meta_allocation(engine_cfg, net_gex_score=0.0):
    base_caps = {k: v["cap"] for k, v in engine_cfg.items()}
    adjusted_caps = dict(base_caps)

    if closed_sheet:
        try:
            rows = closed_sheet.get_all_values()
            if len(rows) > 3:
                df_c = pd.DataFrame(rows[1:], columns=rows[0])
                if "Engine" in df_c.columns and "Realized P/L ($)" in df_c.columns:
                    df_c["PNL"] = df_c["Realized P/L ($)"].astype(str).str.replace("$", "").str.replace("+", "").str.replace(",", "")
                    df_c["PNL"] = pd.to_numeric(df_c["PNL"], errors="coerce").fillna(0.0)

                    rewards = {}
                    for eng in engine_cfg.keys():
                        sub = df_c[df_c["Engine"] == eng].tail(30)
                        if len(sub) < 2:
                            rewards[eng] = 0.0
                            continue
                        mean_r = float(sub["PNL"].mean())
                        std_r = float(sub["PNL"].std()) if float(sub["PNL"].std()) > 0 else 1.0
                        sharpe_proxy = mean_r / std_r
                        wins = float(sub[sub["PNL"] > 0]["PNL"].sum())
                        losses = abs(float(sub[sub["PNL"] <= 0]["PNL"].sum()))
                        pf = (wins / losses) if losses > 0 else (1.5 if wins > 0 else 0.8)
                        rewards[eng] = np.clip((sharpe_proxy * 0.5) + ((pf - 1.0) * 0.3), -0.5, 0.5)

                    for eng, base_c in base_caps.items():
                        r_score = rewards.get(eng, 0.0)
                        mult = float(np.exp(r_score * 0.6))
                        adjusted_caps[eng] = round(float(np.clip(base_c * mult, 0.05, 0.45)), 3)
        except Exception as e:
            logging.warning(f"RL Meta-Allocator note: {e}")

    # --- DEFENSIVE SHIFT BASED ON GEX ---
    if net_gex_score <= -0.15:
        logging.info(f"[RL META] GEX {net_gex_score:.2f} <= -0.15. Shifting capital defensively.")
        if "MOMENTUM" in adjusted_caps:
            adjusted_caps["MOMENTUM"] = round(max(0.05, adjusted_caps["MOMENTUM"] * 0.5), 3)
        if "SMALL_CAP" in adjusted_caps:
            adjusted_caps["SMALL_CAP"] = round(max(0.05, adjusted_caps["SMALL_CAP"] * 0.5), 3)
        if "CORE" in adjusted_caps:
            adjusted_caps["CORE"] = round(max(0.05, adjusted_caps["CORE"] * 0.7), 3)

        safe_havens = [k for k in ["COMMODITIES", "DEFENSE", "TAIL_HEDGE"] if k in adjusted_caps]
        for sh in safe_havens:
            adjusted_caps[sh] = round(min(0.50, adjusted_caps[sh] * 1.5), 3)

    logging.info(f"[v8.7 RL META-ALLOCATOR] Dynamic Tranche Caps: {adjusted_caps}")
    return adjusted_caps

# =====================================================================
# 4. v7.0 LEVEL-2 ORDER-BOOK IMBALANCE (OBI) & v8.0 OPTIONS GEX (MULTI-EXPIRY BS GAMMA)
# =====================================================================
def get_orderbook_imbalance(ticker):
    try:
        if "/" in ticker:
            quotes = api.get_latest_crypto_quotes([ticker], "us")
            q = quotes.get(ticker)
        else:
            q = api.get_latest_quote(ticker)
        if q:
            bid_sz = float(getattr(q, "bs", 0.0) or getattr(q, "bid_size", 0.0) or 1.0)
            ask_sz = float(getattr(q, "as", 0.0) or getattr(q, "ask_size", 0.0) or 1.0)
            if (bid_sz + ask_sz) > 0:
                return round((bid_sz - ask_sz) / (bid_sz + ask_sz), 3)
    except Exception as e:
        logging.warning(f"OBI fetch note for {ticker}: {e}")
    return 0.0

def get_spy_5d_return():
    """Fetches SPY 5-trading-day return once per cycle for cross-engine relative strength confirmation."""
    try:
        spy_hist = yf.Ticker("SPY").history(period="15d").dropna(subset=["Close"])
        if len(spy_hist) >= 6:
            c_now = float(spy_hist["Close"].iloc[-1])
            c_5d = float(spy_hist["Close"].iloc[-6])
            if c_5d > 0 and not pd.isna(c_now) and not pd.isna(c_5d):
                return round((c_now - c_5d) / c_5d, 4)
        elif len(spy_hist) >= 2:
            c_now = float(spy_hist["Close"].iloc[-1])
            c_first = float(spy_hist["Close"].iloc[0])
            if c_first > 0 and not pd.isna(c_now) and not pd.isna(c_first):
                return round((c_now - c_first) / c_first, 4)
    except Exception as e:
        logging.warning(f"SPY 5D return fetch note: {e}")
    return 0.0

def _bs_option_gamma(spot, strike, t_years, sigma, r=0.045):
    if spot <= 0 or strike <= 0 or t_years <= 0 or sigma <= 0:
        return 0.0
    try:
        sqrt_t = math.sqrt(t_years)
        d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * t_years) / (sigma * sqrt_t)
        pdf_d1 = math.exp(-0.5 * d1 * d1) / math.sqrt(2.0 * math.pi)
        return pdf_d1 / (spot * sigma * sqrt_t)
    except Exception:
        return 0.0

def check_macro_gex_and_circuit_breaker(equity, last_equity):
    intraday_dd = ((equity - last_equity) / last_equity) if last_equity > 0 else 0.0
    if intraday_dd <= -0.020:
        return False, f"PORTFOLIO CIRCUIT BREAKER ({intraday_dd*100:+.2f}% Drawdown)", -1.0

    spy_change, vix_level, net_gex_score = 0.0, 0.0, 0.0
    try:
        spy_tk = yf.Ticker("SPY")
        spy = spy_tk.history(period="5d").dropna(subset=["Close"])
        vix = yf.Ticker("^VIX").history(period="5d").dropna(subset=["Close"])
        if not vix.empty:
            vix_level = float(vix['Close'].iloc[-1])
        spot_spy = 0.0
        if len(spy) >= 2:
            c_now = float(spy['Close'].iloc[-1])
            c_prev = float(spy['Close'].iloc[-2])
            spot_spy = c_now
            if c_prev > 0 and not pd.isna(c_now) and not pd.isna(c_prev):
                spy_change = (c_now - c_prev) / c_prev
        elif len(spy) == 1:
            spot_spy = float(spy['Close'].iloc[-1])

        exps = spy_tk.options
        if exps and spot_spy > 0:
            today_utc = datetime.now(timezone.utc).date()
            # Filter out 0DTE/same-day OpEx distortions when later expiries exist; aggregate up to 3 expiries (1-45 DTE)
            valid_exps = []
            for exp_str in exps:
                try:
                    exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                    dte = (exp_date - today_utc).days
                    if 1 <= dte <= 45:
                        valid_exps.append((exp_str, dte))
                except Exception:
                    continue
            if not valid_exps:
                valid_exps = [(exps[0], 1)]

            selected_exps = valid_exps[:3]
            fallback_iv = max(0.10, min(0.80, (vix_level / 100.0) if vix_level > 0 else 0.18))
            total_call_gex = 0.0
            total_put_gex = 0.0
            total_call_oi = 0.0
            total_put_oi = 0.0
            low_strike = spot_spy * 0.90
            high_strike = spot_spy * 1.10

            for exp_str, dte in selected_exps:
                try:
                    chain = spy_tk.option_chain(exp_str)
                    t_years = max(dte, 1) / 365.0
                    # Smoothly down-weight expirations within 1 day of OpEx so roll-offs do not whip-saw gamma
                    opex_weight = 0.35 if dte <= 1 else 1.0

                    for df_side, is_call in [(chain.calls, True), (chain.puts, False)]:
                        if df_side is None or df_side.empty:
                            continue
                        near_df = df_side[(df_side["strike"] >= low_strike) & (df_side["strike"] <= high_strike)]
                        for _, row in near_df.iterrows():
                            oi = float(row.get("openInterest", 0.0) or 0.0)
                            if pd.isna(oi) or oi <= 0:
                                continue
                            strike = float(row.get("strike", 0.0) or 0.0)
                            iv_raw = row.get("impliedVolatility", fallback_iv)
                            iv = float(iv_raw) if (iv_raw is not None and not pd.isna(iv_raw) and 0.05 <= float(iv_raw) <= 2.0) else fallback_iv
                            gamma_val = _bs_option_gamma(spot_spy, strike, t_years, iv)
                            dollar_gex = gamma_val * oi * 100.0 * (spot_spy * spot_spy) * 0.01 * opex_weight
                            if is_call:
                                total_call_gex += dollar_gex
                                total_call_oi += oi
                            else:
                                total_put_gex += dollar_gex
                                total_put_oi += oi
                except Exception as e:
                    logging.warning(f"SPY option chain skip ({exp_str}): {e}")

            if (total_call_gex + total_put_gex) > 0:
                net_gex_score = round((total_call_gex - total_put_gex) / (total_call_gex + total_put_gex), 3)
            elif (total_call_oi + total_put_oi) > 0:
                net_gex_score = round((total_call_oi - total_put_oi) / (total_call_oi + total_put_oi), 3)
    except Exception as e:
        logging.warning(f"GEX/Macro sensor warning: {e}")

    gex_lbl = f"GEX {net_gex_score:+.2f}"
    if spy_change <= -0.015:
        return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} | {gex_lbl} (PANIC BLOCK)", net_gex_score
    if vix_level > 28.0 or (vix_level > 24.0 and net_gex_score < -0.15):
        return False, f"SPY {spy_change*100:+.2f}% | VIX {vix_level:.1f} | {gex_lbl} (NEG-GEX/VIX BLOCK)", net_gex_score

    return True, f"Normal (SPY {spy_change*100:+.2f}%, VIX {vix_level:.1f}, {gex_lbl})", net_gex_score

# =====================================================================
# 5. MARKET-WIDE AI DISCOVERY AGENT (UNCONSTRAINED TICKER HUNTER)
# =====================================================================
def discover_market_wide_catalysts(owned_symbols, top_n=6):
    known_static = set(
        CORE_POOL + MOMENTUM_POOL + MEAN_REV_POOL + SMALL_CAP_POOL + TAIL_HEDGE_POOL + COMMODITY_POOL + DEFENSE_POOL
        + [c.replace("/", "") for c in CRYPTO_POOL]
    )

    # Always force-include every currently owned DISCOVERY ticker (fixes NTSK exit/ratchet blind spot)
    owned_discovery = []
    for sym in owned_symbols:
        s_clean = str(sym).strip().upper()
        if s_clean and classify_symbol(s_clean) == "DISCOVERY" and s_clean not in owned_discovery:
            owned_discovery.append(s_clean)

    discovered_pool = list(owned_discovery)
    for sym in DISCOVERY_RADAR_POOL:
        if sym not in discovered_pool:
            discovered_pool.append(sym)

    try:
        for scr_name in ["day_gainers", "most_actives"]:
            scr = yf.screen(scr_name)
            quotes = scr.get("quotes", []) if isinstance(scr, dict) else []
            for q in quotes[:15]:
                sym = str(q.get("symbol", "")).strip().upper()
                if sym and sym.isalpha() and len(sym) <= 5 and sym not in known_static and sym not in discovered_pool:
                    discovered_pool.insert(len(owned_discovery), sym)
    except Exception as e:
        logging.warning(f"Discovery screener note: {e}")

    try:
        batch_query = ",".join(discovered_pool[:25])
        alpaca_news = api.get_news(batch_query, limit=40)
        for item in alpaca_news:
            for s in (getattr(item, "symbols", []) or []):
                s_clean = str(s).strip().upper()
                if s_clean and s_clean.isalpha() and len(s_clean) <= 5 and s_clean not in known_static and s_clean not in discovered_pool:
                    discovered_pool.insert(len(owned_discovery), s_clean)
    except Exception as e:
        logging.warning(f"Discovery news batch note: {e}")

    effective_top_n = max(top_n, len(owned_discovery) + 2)
    screened = screen_top_candidates(
        discovered_pool[:45],
        top_n=effective_top_n,
        owned_symbols=owned_symbols,
        mode="momentum",
        tranche_name="DISCOVERY"
    )
    verified = list(owned_discovery)
    for sym in screened:
        if sym in verified:
            continue
        try:
            asset = api.get_asset(sym)
            if getattr(asset, "tradable", False) and getattr(asset, "status", "") == "active":
                verified.append(sym)
        except Exception as e:
            logging.warning(f"Asset verification skipped for {sym}: {e}")
            continue

    logging.info(f"[AI DISCOVERY AGENT] Selected {len(verified)} unconstrained market-wide catalysts (owned preserved: {owned_discovery}): {verified}")
    return verified

def screen_top_candidates(pool, top_n, owned_symbols, mode="core", tranche_name=None):
    always_include = []
    for t in pool:
        if t in owned_symbols or to_alpaca_pos_symbol(t) in owned_symbols:
            if tranche_name is None or classify_symbol(t) == tranche_name:
                always_include.append(t)

    remaining_pool = [t for t in pool if t not in always_include]
    slots_left = max(0, top_n - len(always_include))
    if slots_left == 0 or not remaining_pool:
        return always_include

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

                if mode in ["momentum", "small_cap"]:
                    rank_score = (abs(ret_1d) * 100.0) * (1.0 + min(rel_vol, 3.0))
                elif mode == "mean_rev":
                    rank_score = (-ret_1d * 100.0) + rel_vol
                elif mode == "crypto":
                    rank_score = (abs(ret_1d) * 100.0) + (rel_vol * 1.5)
                else:
                    rank_score = (ret_1d * 50.0) + rel_vol

                scored.append((rank_score, orig_t))
            except Exception:
                continue
    except Exception as e:
        logging.warning(f"Screener batch warning ({mode}): {e}")

    scored.sort(key=lambda x: x[0], reverse=True)
    selected = [t for _, t in scored[:slots_left]]

    for t in remaining_pool:
        if len(always_include) + len(selected) >= top_n:
            break
        if t not in selected:
            selected.append(t)

    final_list = always_include + selected
    logging.info(f"[AI SCREENER - {mode.upper()}] Filtered {len(pool)} pool -> {len(final_list)} active candidates: {final_list}")
    return final_list

# =====================================================================
# 6. MATHEMATICAL ARBITER MATRIX & v8.7 MULTI-TIMEFRAME PERSISTENCE FILTER
# =====================================================================
def compute_arbiter_matrix(finbert_score, tech, obi_score=0.0, base_buy_min=0.05, base_exit_max=-0.15, strategy_mode="core"):
    if tech is None:
        return {
            "regime": "NO-TECH",
            "w_news": 1.0,
            "w_tech": 0.0,
            "composite": finbert_score,
            "tp_adj": 1.0,
            "rsi_max": 72.0,
            "buy_signal": False,
            "arbiter_exit_reason": None,
            "fee_block_reason": None
        }

    rel_vol = tech.get("rel_vol", 1.0)
    rsi = tech["rsi14"]
    price = tech["price"]
    ema9 = tech["ema9"]
    ema20 = tech["ema20"]
    sma50 = tech["sma50"]
    vwap5 = tech.get("vwap5", price)
    mfm = tech.get("mfm", 0.0)
    bb_low = tech.get("bb_low", price * 0.96)

    tech_score = 0.0
    if price > ema9 > ema20:
        tech_score += 0.35
    elif price > ema20:
        tech_score += 0.20
    else:
        tech_score -= 0.30

    if ema20 > sma50:
        tech_score += 0.15
    else:
        tech_score -= 0.15

    if price >= vwap5 and (mfm > 0.05 or obi_score > 0.10):
        tech_score += 0.20
    elif price < vwap5 and (mfm < -0.15 or obi_score < -0.15):
        tech_score -= 0.20

    tech_score += (obi_score * 0.20)

    if rsi <= 32.0:
        tech_score += 0.45
    elif 45.0 <= rsi <= 66.0:
        tech_score += 0.15
    elif rsi >= 76.0:
        tech_score -= 0.45

    tech_score = max(-1.0, min(1.0, tech_score))
    abs_news = abs(finbert_score)

    if strategy_mode == "mean_rev":
        regime = "MEAN-REV"
        w_news, w_tech = 0.25, 0.75
        tp_adj = 0.80
        rsi_max = 40.0
        composite = round((w_news * finbert_score) + (w_tech * tech_score), 3)
        # Rebalanced MEAN_REV window: captures ETF/value pullbacks at RSI <= 38 or within 1.2% of lower Bollinger Band
        buy_signal = (rsi <= 38.0 or price <= bb_low * 1.012) and finbert_score > -0.35 and obi_score >= -0.25
        arbiter_exit_reason = f"Mean-Rev Snapback Target (RSI {rsi:.1f})" if rsi >= 58.0 else None
    else:
        if abs_news >= 0.65 or (abs_news >= 0.45 and rel_vol >= 1.8):
            regime = "NEWS-90/10"
            w_news, w_tech = 0.90, 0.10
            tp_adj = 1.45
            rsi_max = 84.0
        elif abs_news >= 0.20 or rel_vol >= 1.35:
            regime = "HYBRID-50/50"
            w_news, w_tech = 0.50, 0.50
            tp_adj = 1.00
            rsi_max = 73.0
        else:
            regime = "TECH-10/90"
            w_news, w_tech = 0.10, 0.90
            tp_adj = 0.85
            rsi_max = 69.0

        composite = round((w_news * finbert_score) + (w_tech * tech_score), 3)

        buy_signal = False
        if regime == "NEWS-90/10" and finbert_score >= max(base_buy_min, 0.40) and price >= ema20 * 0.985 and obi_score >= -0.30:
            buy_signal = True
        elif regime == "HYBRID-50/50" and composite >= max(base_buy_min, 0.12) and price >= ema20 and price >= vwap5 * 0.99:
            buy_signal = True
        elif regime == "TECH-10/90" and (
            (composite >= 0.22 and price > ema9 > ema20 and price >= vwap5 and obi_score >= -0.10)
            or (rsi <= 32.0 and finbert_score > -0.15)
        ):
            buy_signal = True

        # Balanced Crypto Arbiter: Allows verified 1h uptrends when news/OBI are neutral (0.00)
        if strategy_mode == "crypto":
            is_crypto_trend_breakout = (
                price > ema9 > ema20
                and price >= vwap5
                and 50.0 <= rsi <= 68.0
                and finbert_score >= 0.0
                and obi_score >= -0.05
                and (rel_vol >= 1.10 or finbert_score >= 0.15 or obi_score >= 0.08)
            )
            is_crypto_confirmed_reversal = (
                rsi <= 32.0
                and price > ema9  # Must already be bouncing above 9-EMA, never a free-falling knife
                and finbert_score >= 0.05  # Blocks 0.000 "no-news" altcoin traps
                and obi_score >= 0.10
            )
            if is_crypto_confirmed_reversal:
                regime = "CRYPTO-REVERSAL"
                composite = round(max(composite, 0.45), 3)
                tp_adj = 0.90
                rsi_max = 70.0
                buy_signal = True
            elif is_crypto_trend_breakout:
                regime = "CRYPTO-TREND"
                composite = round(max(composite, 0.40), 3)
                tp_adj = 1.15
                rsi_max = 70.0
                buy_signal = True
            else:
                buy_signal = False

        arbiter_exit_reason = None
        if regime == "CRYPTO-REVERSAL" and rsi >= 60.0:
            arbiter_exit_reason = f"Crypto Oversold Snapback Target (RSI {rsi:.1f})"
        elif regime == "NEWS-90/10" and finbert_score <= base_exit_max:
            arbiter_exit_reason = f"Arbiter 90/10 News Reversal ({finbert_score:+.3f})"
        elif regime == "TECH-10/90" and rsi >= 74.0 and finbert_score < 0.25:
            arbiter_exit_reason = f"Arbiter 10/90 Tech Overbought Profit-Take (RSI {rsi:.1f})"
        elif regime == "HYBRID-50/50" and composite <= base_exit_max and price < ema9:
            arbiter_exit_reason = f"Arbiter 50/50 Hybrid Breakdown (Comp {composite:+.3f})"

    # --- Slippage & Fee-Aware Net Alpha Filter (Scaled for 1h Crypto ATR vs 1d Equity ATR) ---
    fee_block_reason = None
    fee_hurdle = 0.45 if strategy_mode == "crypto" else 0.20
    atr_horizon_mult = 4.0 if strategy_mode == "crypto" else 2.0
    if price > 0:
        atr = tech["atr14"]
        expected_alpha_pct = abs(composite) * (atr / price) * 100.0 * atr_horizon_mult
        if buy_signal and expected_alpha_pct < fee_hurdle:
            buy_signal = False
            fee_block_reason = f"Fee Hurdle: Alpha {expected_alpha_pct:.2f}% < {fee_hurdle}%"

    return {
        "regime": regime,
        "w_news": w_news,
        "w_tech": w_tech,
        "tech_score": round(tech_score, 3),
        "composite": composite,
        "tp_adj": tp_adj,
        "rsi_max": rsi_max,
        "buy_signal": buy_signal,
        "arbiter_exit_reason": arbiter_exit_reason,
        "fee_block_reason": fee_block_reason
    }

def load_sheet_signal_history(sheet_ws, lookback_days=5):
    """
    Reads an engine's Google Sheet ONCE per cycle to compute:
      1) Rolling 3-5 day average FinBERT sentiment per ticker
      2) Whether the prior scan (5-180 min ago) staged a bullish confirmation (for 2-scan persistence)
    """
    history_map = {}
    if not sheet_ws:
        return history_map
    try:
        rows = sheet_ws.get_all_values()
        if len(rows) <= 1:
            return history_map

        now_utc = datetime.now(timezone.utc)
        cutoff_sec = lookback_days * 86400.0
        per_ticker_scores = {}
        per_ticker_latest = {}

        for r in rows[-350:]:
            if len(r) < 4:
                continue
            ts_raw = str(r[0]).strip()
            sym = str(r[1]).strip().upper()
            score_raw = str(r[2]).strip()
            dec_raw = str(r[3]).strip()
            if not sym or ts_raw == "Timestamp":
                continue

            row_dt = None
            ts_clean = ts_raw.replace(" UTC", "").strip()[:19]
            try:
                row_dt = datetime.strptime(ts_clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            except Exception:
                continue

            age_sec = (now_utc - row_dt).total_seconds()
            if age_sec < 0 or age_sec > cutoff_sec:
                continue

            try:
                s_val = float(score_raw)
                per_ticker_scores.setdefault(sym, []).append(s_val)
            except Exception:
                pass

            prev_latest = per_ticker_latest.get(sym)
            if prev_latest is None or row_dt >= prev_latest[0]:
                per_ticker_latest[sym] = (row_dt, dec_raw)

        for sym in set(list(per_ticker_scores.keys()) + list(per_ticker_latest.keys())):
            scores = per_ticker_scores.get(sym, [])
            latest_info = per_ticker_latest.get(sym)
            was_staged_prev = False
            last_dec = ""
            if latest_info is not None:
                last_dt, last_dec = latest_info
                age_min = (now_utc - last_dt).total_seconds() / 60.0
                if 5.0 <= age_min <= 180.0:
                    if ("STAGING 1/2" in last_dec) or ("EOD-WAIT" in last_dec):
                        was_staged_prev = True
                    elif ("BULLISH" in last_dec) and ("Blocked:" not in last_dec) and ("Owned" not in last_dec):
                        was_staged_prev = True

            history_map[sym] = {
                "last_decision": last_dec,
                "was_staged_prev": was_staged_prev,
                "rolling_sent_avg": round(sum(scores) / len(scores), 3) if scores else None,
                "sent_samples": len(scores)
            }
    except Exception as e:
        logging.warning(f"Signal history read note: {e}")
    return history_map

def evaluate_multi_timeframe_confirmation(ticker, tranche_name, strategy_mode, score, tech, spy_5d_ret, hist_entry, ny_now):
    """
    v8.7 Multi-Timeframe Confirmation & Anti-Whipsaw Entry Gate:
      - Anti-'Sell the News' reaction check (rejects positive news dumping below VWAP)
      - 5-day rolling sentiment drift check (rejects sharply fading hype)
      - 5-day relative strength vs. SPY for trend & catalyst engines
      - End-of-Day entry window (15:15-15:59 NY) for CORE / COMMODITIES / DEFENSE
      - 2-scan consecutive persistence for MOMENTUM / DISCOVERY / SMALL_CAP / CRYPTO
      - Multi-day pullback + intraday stabilization for MEAN_REV
    (Never delays exits, OCO self-healing, ratchets, or TAIL_HEDGE.)
    """
    rolling_avg = hist_entry.get("rolling_sent_avg") if hist_entry else None
    sent_samples = hist_entry.get("sent_samples", 0) if hist_entry else 0
    was_staged_prev = hist_entry.get("was_staged_prev", False) if hist_entry else False

    sent_drift = round(score - rolling_avg, 3) if (rolling_avg is not None and sent_samples >= 2) else None
    drift_txt = f"SentDrift {sent_drift:+.2f}" if sent_drift is not None else "SentDrift N/A"

    ret_1d = float(tech.get("ret_1d", 0.0))
    ret_5d = float(tech.get("ret_5d", 0.0))
    candle_pos = float(tech.get("candle_pos", 0.5))
    vwap5 = float(tech.get("vwap5", tech["price"]))
    rs_5d = round(ret_5d - spy_5d_ret, 4)
    rs_txt = f"5D-RS {rs_5d*100:+.1f}% vs SPY"

    # 1. Anti-'Sell the News' Price-Reaction Filter
    if strategy_mode != "mean_rev":
        if score >= 0.25 and ret_1d < -0.015 and tech["price"] < vwap5:
            return False, f"Blocked: Sell-The-News Dump ({ret_1d*100:+.1f}% < VWAP)", ""

    # 2. Rolling 3-5D Sentiment Deterioration Filter (Equity Trend / Catalyst Engines)
    if strategy_mode not in ["mean_rev", "crypto"] and sent_drift is not None:
        if sent_drift < -0.20 and score < 0.35:
            return False, f"Blocked: Fading 5D Sentiment ({drift_txt}, Avg {rolling_avg:+.2f})", ""

    # 3. Mean-Reversion Multi-Day Exhaustion + Intraday Stabilization
    if strategy_mode == "mean_rev":
        if ret_5d > -0.010:
            return False, f"Blocked: No 5D Pullback ({ret_5d*100:+.1f}% > -1.0%)", ""
        if candle_pos < 0.30 and tech.get("mfm", 0.0) < -0.20:
            return False, f"Blocked: Falling Knife (CandlePos {candle_pos:.2f}, MFM {tech.get('mfm', 0.0):+.2f})", ""
        return True, "CONFIRMED", f"5D Pullback {ret_5d*100:+.1f}% | CandlePos {candle_pos:.2f}"

    # 4. Crypto 2-Scan Consecutive Persistence
    if strategy_mode == "crypto":
        if not was_staged_prev:
            return False, "STAGING 1/2 — Awaiting 2nd Scan Confirm", ""
        return True, "CONFIRMED 2/2", f"2-Scan Confirmed | {drift_txt}"

    # 5. Trend & Catalyst Equities: 5-Day Relative Strength vs. SPY
    if rs_5d < -0.005:
        return False, f"Blocked: Weak {rs_txt}", ""

    # 6. Slow Swing & Safe-Haven Engines: End-of-Day Confirmation Window (15:15-15:59 NY)
    if tranche_name in ["CORE", "COMMODITIES", "DEFENSE"]:
        in_eod_window = (ny_now.hour == 15 and ny_now.minute >= 15)
        if not in_eod_window:
            return False, f"EOD-WAIT (Fires 15:15-15:59 NY | {rs_txt}, {drift_txt})", ""
        return True, "EOD-CONFIRMED", f"EOD Confirmed | {rs_txt} | {drift_txt}"

    # 7. Fast Catalyst Engines (MOMENTUM / DISCOVERY / SMALL_CAP): 2-Scan Consecutive Persistence
    if not was_staged_prev:
        return False, f"STAGING 1/2 — Awaiting 2nd Scan Confirm ({rs_txt})", ""

    return True, "CONFIRMED 2/2", f"2-Scan Confirmed | {rs_txt} | {drift_txt}"

def compute_atr_risk_parity_qty(equity, price, atr, sl_atr_mult, risk_bps=0.0045, max_notional_pct=0.040, is_crypto=False):
    if price <= 0 or equity <= 0:
        return 0

    # Convert to strict Decimals for institutional precision
    d_equity = Decimal(str(equity))
    d_price = Decimal(str(price))
    d_atr = Decimal(str(atr))
    d_risk_bps = Decimal(str(risk_bps))
    d_max_not = Decimal(str(max_notional_pct))

    safe_atr = max(d_atr, d_price * Decimal('0.01'))
    stop_distance_dollars = max(Decimal(str(sl_atr_mult)) * safe_atr, d_price * Decimal('0.008'))
    dollar_risk_budget = d_equity * d_risk_bps

    raw_qty = dollar_risk_budget / stop_distance_dollars
    max_qty_by_notional = (d_equity * d_max_not) / d_price
    target_qty = min(raw_qty, max_qty_by_notional)

    if is_crypto:
        return float(max(Decimal('0.0001'), target_qty).quantize(Decimal('0.0001'), rounding=ROUND_DOWN))
    return max(1, int(target_qty.quantize(Decimal('1'), rounding=ROUND_DOWN)))

def check_correlation_and_exposure_guard(candidate, tranche_name, raw_positions, equity, candidate_returns, held_returns_map, dynamic_caps, pending_tranche_spend=0.0, max_total_exposure=0.65, reserved_exposure_pct=0.0):
    total_invested = sum(float(p.market_value) for p in raw_positions) + pending_tranche_spend
    effective_max_exposure = max(0.10, max_total_exposure - reserved_exposure_pct)
    if equity > 0 and (total_invested / equity) >= effective_max_exposure:
        if reserved_exposure_pct > 0:
            return False, f"Exposure Cap {effective_max_exposure*100:.0f}% Reached (Reserving {reserved_exposure_pct*100:.0f}% for MEAN_REV/SMALL_CAP)"
        return False, f"Portfolio Max Exposure {max_total_exposure*100:.0f}% Reached (35% Dry Powder Guard)"

    tranche_invested = sum(
        float(p.market_value) for p in raw_positions
        if classify_symbol(CRYPTO_NORM.get(str(p.symbol), str(p.symbol))) == tranche_name
    ) + pending_tranche_spend
    max_cap = dynamic_caps.get(tranche_name, 0.25)
    if equity > 0 and (tranche_invested / equity) >= max_cap:
        return False, f"RL Cap {max_cap*100:.1f}% Reached"

    if candidate_returns is not None and len(candidate_returns) >= 20:
        for held_sym, held_ret in held_returns_map.items():
            if held_sym == candidate or to_alpaca_pos_symbol(held_sym) == to_alpaca_pos_symbol(candidate):
                continue
            aligned = pd.concat([candidate_returns, held_ret], axis=1).dropna()
            if len(aligned) >= 20:
                corr_val = float(aligned.iloc[:, 0].corr(aligned.iloc[:, 1]))
                if not pd.isna(corr_val) and corr_val > 0.82:
                    return False, f"High Corr {corr_val:.2f} w/ {held_sym}"

    return True, "OK"

# =====================================================================
# 7. SHARED AI, NEWS, TECHNICALS & UNIVERSAL OCO SELF-HEALER FUNCTIONS
# =====================================================================
def send_discord_alert(message):
    if not DISCORD_WEBHOOK:
        return
    try:
        if len(message) <= 1950:
            requests.post(DISCORD_WEBHOOK, json={"content": message}, timeout=10)
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
        logging.warning(f"Discord alert error: {e}")

logging.info("Loading ProsusAI/finbert financial AI model once into shared RAM...")
device_id = 0 if torch.cuda.is_available() else -1
finbert = pipeline(
    "sentiment-analysis",
    model="ProsusAI/finbert",
    tokenizer="ProsusAI/finbert",
    top_k=None,
    device=device_id
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
        logging.warning(f"Alpaca news fetch note for {ticker}: {e}")

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
        logging.warning(f"YFinance news fetch note for {ticker}: {e}")

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

def get_technicals_and_atr(ticker):
    try:
        yf_sym = to_yf_symbol(ticker)
        is_crypto = "/" in ticker
        if is_crypto:
            # 1-hour intraday candles for 48x/day crypto execution
            df = yf.Ticker(yf_sym).history(period="1mo", interval="1h")
        else:
            df = yf.Ticker(yf_sym).history(period="1y", interval="1d")

        if df.empty or len(df) < 30:
            return None
        close = df['Close'].dropna()
        if len(close) < 30:
            return None
        current_price = float(close.iloc[-1])
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
        sma50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else float(close.mean())
        ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
        ema9 = float(close.ewm(span=9, adjust=False).mean().iloc[-1])
        std20 = float(close.rolling(20).std().iloc[-1]) if len(close) >= 20 else (current_price * 0.02)
        bb_low = ema20 - (2.0 * std20)

        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi14 = float(rsi_series.iloc[-1]) if not rsi_series.empty and not pd.isna(rsi_series.iloc[-1]) else 50.0

        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = ranges.max(axis=1)
        atr_series = true_range.rolling(14).mean()
        atr14 = float(atr_series.iloc[-1]) if not atr_series.empty and not pd.isna(atr_series.iloc[-1]) else (current_price * 0.02)

        vol_series = df['Volume'] if 'Volume' in df.columns else pd.Series([1.0] * len(df), index=df.index)
        vol_20d = float(vol_series.tail(20).mean()) if len(vol_series) >= 5 and float(vol_series.tail(20).mean()) > 0 else 1.0
        vol_now = float(vol_series.iloc[-1]) if len(vol_series) > 0 else 1.0
        rel_vol = round(vol_now / vol_20d, 2) if vol_20d > 0 else 1.0

        recent5 = df.tail(5)
        typ_p = (recent5['High'] + recent5['Low'] + recent5['Close']) / 3.0
        vol_sum = float(recent5['Volume'].sum()) if 'Volume' in recent5.columns else 0.0
        vwap5 = float((typ_p * recent5['Volume']).sum() / vol_sum) if vol_sum > 0 else current_price

        hl_range = float(df['High'].iloc[-1] - df['Low'].iloc[-1])
        mfm = float(((current_price - float(df['Low'].iloc[-1])) - (float(df['High'].iloc[-1]) - current_price)) / hl_range) if hl_range > 0 else 0.0
        candle_pos = float((current_price - float(df['Low'].iloc[-1])) / hl_range) if hl_range > 0 else 0.5

        if is_crypto:
            daily_close = close.resample("1D").last().dropna()
            returns_60d = daily_close.pct_change().dropna().tail(60)
            ret_1d = float((daily_close.iloc[-1] - daily_close.iloc[-2]) / daily_close.iloc[-2]) if len(daily_close) >= 2 and float(daily_close.iloc[-2]) > 0 else 0.0
            ret_5d = float((daily_close.iloc[-1] - daily_close.iloc[-6]) / daily_close.iloc[-6]) if len(daily_close) >= 6 and float(daily_close.iloc[-6]) > 0 else ret_1d
        else:
            returns_60d = close.pct_change().dropna().tail(60)
            ret_1d = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2]) if len(close) >= 2 and float(close.iloc[-2]) > 0 else 0.0
            ret_5d = float((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]) if len(close) >= 6 and float(close.iloc[-6]) > 0 else ret_1d

        return {
            "price": current_price,
            "sma200": sma200,
            "sma50": sma50,
            "ema20": ema20,
            "ema9": ema9,
            "bb_low": bb_low,
            "rsi14": rsi14,
            "atr14": atr14,
            "rel_vol": rel_vol,
            "vwap5": vwap5,
            "mfm": round(mfm, 2),
            "candle_pos": round(candle_pos, 3),
            "ret_1d": round(ret_1d, 4),
            "ret_5d": round(ret_5d, 4),
            "returns_60d": returns_60d
        }
    except Exception as e:
        logging.warning(f"Technical calculation warning for {ticker}: {e}")
        return None

def was_stopped_out_last_24h(ticker, closed_orders):
    norm = to_alpaca_pos_symbol(ticker)
    for o in closed_orders:
        if to_alpaca_pos_symbol(o.symbol) == norm and o.side == 'sell' and o.type in ['stop', 'stop_limit'] and o.status == 'filled':
            return True
    return False

def was_crypto_sold_recently(pair, closed_orders, hours=4):
    norm = to_alpaca_pos_symbol(pair)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    for o in closed_orders:
        if to_alpaca_pos_symbol(o.symbol) == norm and o.side == 'sell' and o.status == 'filled':
            filled_at = getattr(o, 'filled_at', None)
            if filled_at and hasattr(filled_at, 'tzinfo') and filled_at.tzinfo is not None:
                if filled_at >= cutoff:
                    return True
            else:
                return True
    return False

def has_upcoming_earnings_48h(ticker):
    if "/" in ticker or ticker in TAIL_HEDGE_POOL or ticker in MEAN_REV_POOL[:12] or ticker in COMMODITY_POOL:
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
    except Exception as e:
        logging.warning(f"Earnings check note for {ticker}: {e}")
    return False

def fetch_active_and_held_orders():
    active = {}
    try:
        # Flat query captures all open and 'held' bracket legs directly, even on older positions
        for o in api.list_orders(status='open', nested=False, limit=500):
            if o.status in ['new', 'held', 'accepted', 'partially_filled']:
                active[o.id] = o
        for o in api.list_orders(status='open', nested=True, limit=200):
            active[o.id] = o
            if hasattr(o, 'legs') and o.legs:
                for leg in o.legs:
                    if leg.status in ['new', 'held', 'accepted', 'partially_filled']:
                        active[leg.id] = leg
    except Exception as e:
        logging.warning(f"Order fetch warning: {e}")
    return list(active.values())

def get_all_orders_for_ticker(ticker, active_orders):
    norm = to_alpaca_pos_symbol(ticker)
    return [o for o in active_orders if to_alpaca_pos_symbol(o.symbol) == norm and o.status in ['new', 'held', 'accepted', 'partially_filled']]

def get_active_sell_legs(symbol, active_orders=None):
    """Returns (sell_orders, current_sl, current_tp) including held OCO stop legs."""
    orders_source = active_orders if active_orders is not None else fetch_active_and_held_orders()
    sell_orders = [
        o for o in get_all_orders_for_ticker(symbol, orders_source)
        if str(getattr(o, 'side', '')).lower() == 'sell'
    ]
    current_sl = None
    current_tp = None
    for o in sell_orders:
        otype = str(getattr(o, 'type', '')).lower()
        if otype in ['stop', 'stop_limit'] and getattr(o, 'stop_price', None) is not None:
            current_sl = float(o.stop_price)
        elif otype == 'limit' and getattr(o, 'limit_price', None) is not None:
            current_tp = float(o.limit_price)
    return sell_orders, current_sl, current_tp

def cancel_sells_and_wait_unlock(symbol, sell_orders, required_qty, timeout_s=6.0):
    """Cancels non-held sell legs (Alpaca auto-cancels paired 'held' OCO legs) and polls until shares unlock."""
    canceled_any = False
    for o in sell_orders:
        if str(getattr(o, 'status', '')).lower() != 'held':
            try:
                api.cancel_order(o.id)
                canceled_any = True
            except Exception as e:
                logging.warning(f"[OCO-GUARD] Cancel warning on {symbol} ({o.id}): {e}")

    # Fallback: if only 'held' legs appeared in list, try canceling them directly
    if not canceled_any and sell_orders:
        for o in sell_orders:
            try:
                api.cancel_order(o.id)
                canceled_any = True
            except Exception as e:
                logging.warning(f"[OCO-GUARD] Fallback cancel warning on {symbol} ({o.id}): {e}")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            pos = api.get_position(symbol)
            qty_avail_raw = getattr(pos, 'qty_available', None)
            if qty_avail_raw is None and hasattr(pos, '_raw') and isinstance(pos._raw, dict):
                qty_avail_raw = pos._raw.get('qty_available')
            if qty_avail_raw is not None:
                if int(float(qty_avail_raw)) >= int(required_qty):
                    return True
            else:
                remaining_sells, _, _ = get_active_sell_legs(symbol)
                if not remaining_sells:
                    return True
        except Exception:
            return False
        time.sleep(0.4)

    return False

def cancel_existing_orders_for_ticker(ticker, active_orders):
    norm = to_alpaca_pos_symbol(ticker)
    ticker_orders = get_all_orders_for_ticker(ticker, active_orders)
    canceled = False
    for o in ticker_orders:
        if str(getattr(o, 'status', '')).lower() != 'held':
            try:
                api.cancel_order(o.id)
                canceled = True
            except Exception as e:
                logging.warning(f"Cancel order warning for {ticker}: {e}")
    if not canceled and ticker_orders:
        for o in ticker_orders:
            try:
                api.cancel_order(o.id)
                canceled = True
            except Exception as e:
                logging.warning(f"Cancel held order warning for {ticker}: {e}")
    if canceled:
        # Poll briefly until Alpaca releases locked shares
        deadline = time.time() + 4.0
        while time.time() < deadline:
            try:
                remaining = [
                    o for o in api.list_orders(status='open', nested=False, limit=200)
                    if to_alpaca_pos_symbol(o.symbol) == norm and o.status in ['new', 'held', 'accepted', 'partially_filled']
                ]
                if not remaining:
                    break
            except Exception:
                time.sleep(1.5)
                break
            time.sleep(0.4)

def replace_with_atomic_oco(symbol, qty, live_price, target_sl, target_tp, active_orders=None):
    """Safely clears stale/conflicting sell legs, waits for share unlock, and attaches atomic GTC OCO (SL + TP)."""
    qty_int = int(float(qty))
    if qty_int <= 0 or live_price <= 0:
        return False, None, None

    safe_sl = round(min(float(target_sl), float(live_price) - 0.02), 2)
    safe_tp = round(max(float(target_tp), float(live_price) + 0.02), 2)

    if safe_sl <= 0 or safe_tp <= safe_sl:
        logging.warning(f"[OCO-GUARD] Invalid SL/TP bounds for {symbol}: SL={safe_sl}, TP={safe_tp}")
        return False, None, None

    sell_orders, _, _ = get_active_sell_legs(symbol, active_orders=active_orders)
    if sell_orders:
        unlocked = cancel_sells_and_wait_unlock(symbol, sell_orders, qty_int)
        if not unlocked:
            logging.warning(f"[OCO-GUARD] Shares still locked for {symbol}; skipping to avoid share-lock/duplicate sell.")
            return False, None, None

    try:
        api.submit_order(
            symbol=symbol,
            qty=qty_int,
            side='sell',
            type='limit',
            time_in_force='gtc',
            order_class='oco',
            take_profit={'limit_price': safe_tp},
            stop_loss={'stop_price': safe_sl}
        )
        logging.info(f"[OCO-GUARD] Attached atomic OCO on {symbol} ({qty_int} sh): SL=${safe_sl:.2f} | TP=${safe_tp:.2f}")
        return True, safe_sl, safe_tp
    except Exception as e:
        logging.warning(f"[OCO-GUARD] OCO attach failed on {symbol} ({e}); falling back to standalone GTC Stop @ ${safe_sl:.2f}")
        try:
            api.submit_order(
                symbol=symbol,
                qty=qty_int,
                side='sell',
                type='stop',
                stop_price=safe_sl,
                time_in_force='gtc'
            )
            logging.info(f"[OCO-GUARD] Attached fallback GTC Stop on {symbol} ({qty_int} sh): SL=${safe_sl:.2f}")
            return True, safe_sl, None
        except Exception as e2:
            logging.error(f"[OCO-GUARD] Fallback GTC Stop also failed on {symbol}: {e2}")
            return False, None, None

def enforce_oco_protection_all_positions(is_nyse_open=True):
    """
    Universal OCO Self-Healer & 3-Stage Ratchet Safety Net.
    Runs across ALL open equity positions (CORE, MOMENTUM, DISCOVERY, MEAN_REV,
    SMALL_CAP, COMMODITIES, DEFENSE, TAIL_HEDGE, and filled PREDATOR traps).
    """
    guard_alerts = []
    try:
        positions = api.list_positions()
        fresh_orders = fetch_active_and_held_orders()
    except Exception as e:
        logging.warning(f"[OCO-GUARD] Could not fetch positions/orders: {e}")
        return guard_alerts

    for pos in positions:
        symbol = str(pos.symbol)
        disp_sym = CRYPTO_NORM.get(symbol, symbol)
        tranche_tag = classify_symbol(disp_sym)

        # Alpaca OCO brackets are equity-only
        if tranche_tag == "CRYPTO" or "/" in disp_sym:
            continue

        qty = int(float(pos.qty))
        if qty <= 0:
            continue

        entry = float(pos.avg_entry_price)
        live = float(pos.current_price)
        if entry <= 0 or live <= 0:
            continue

        ret_pct = (live - entry) / entry
        _, current_sl, current_tp = get_active_sell_legs(symbol, active_orders=fresh_orders)

        tech = get_technicals_and_atr(symbol)
        atr = max(tech["atr14"], live * 0.01) if (tech and tech.get("atr14")) else (live * 0.02)

        if symbol in TAIL_HEDGE_POOL or symbol == "SQQQ":
            base_sl = round(min(entry, live) * 0.965, 2)
            base_tp = round(max(entry, live) * 1.12, 2)
        elif tranche_tag == "CORE":
            base_sl = round(min(entry, live) - (1.5 * atr), 2)
            base_tp = round(max(entry, live) + (3.5 * atr), 2)
        elif tranche_tag in ["COMMODITIES", "DEFENSE"]:
            base_sl = round(min(entry, live) - (1.5 * atr), 2)
            base_tp = round(max(entry, live) + (3.0 * atr), 2)
        elif tranche_tag == "DISCOVERY":
            base_sl = round(min(entry, live) - (1.2 * atr), 2)
            base_tp = round(max(entry, live) + (2.8 * atr), 2)
        elif tranche_tag == "MEAN_REV":
            base_sl = round(min(entry, live) - (1.0 * atr), 2)
            base_tp = round(max(entry, live) + (1.8 * atr), 2)
        else:
            base_sl = round(min(entry, live) - (1.2 * atr), 2)
            base_tp = round(max(entry, live) + (2.5 * atr), 2)

        desired_sl = current_sl if current_sl is not None else base_sl
        stage_lbl = None
        if ret_pct >= 0.060:
            trail_sl = round(max(entry * 1.035, live - (1.2 * atr)), 2)
            if trail_sl > desired_sl:
                desired_sl = trail_sl
                stage_lbl = "Stage-3 Chandelier Trail"
        elif ret_pct >= 0.040:
            s2_sl = round(entry * 1.020, 2)
            if s2_sl > desired_sl:
                desired_sl = s2_sl
                stage_lbl = "Stage-2 (+2.0% Profit Lock)"
        elif ret_pct >= 0.020:
            s1_sl = round(entry * 1.002, 2)
            if s1_sl > desired_sl:
                desired_sl = s1_sl
                stage_lbl = "Stage-1 Break-Even"

        desired_tp = current_tp if current_tp is not None else base_tp

        missing_leg = (current_sl is None) or (current_tp is None)
        needs_ratchet = (
            is_nyse_open
            and (current_sl is not None)
            and (desired_sl > current_sl + 0.05)
            and (desired_sl < live - 0.05)
        )

        if missing_leg or needs_ratchet:
            ok, applied_sl, applied_tp = replace_with_atomic_oco(
                symbol=symbol,
                qty=qty,
                live_price=live,
                target_sl=desired_sl,
                target_tp=desired_tp,
                active_orders=fresh_orders
            )
            if ok:
                tp_disp = f"`${applied_tp:.2f}`" if applied_tp else "`None`"
                if missing_leg:
                    guard_alerts.append(
                        f"🛡️ **[{tranche_tag} OCO SELF-HEALER] {symbol}**: Attached atomic GTC OCO (`{qty}` sh) ➔ SL `${applied_sl:.2f}` | TP {tp_disp}"
                    )
                else:
                    guard_alerts.append(
                        f"🛡️ **[{tranche_tag}] {(stage_lbl or 'RATCHET').upper()} ({symbol})**: Atomic OCO ratcheted `${current_sl:.2f}` ➔ `${applied_sl:.2f}` | TP {tp_disp} (`+{ret_pct*100:.1f}%` open gain)"
                    )

    return guard_alerts

def find_last_buy_fill_price(symbol, closed_orders):
    norm = to_alpaca_pos_symbol(symbol)
    for o in closed_orders:
        if to_alpaca_pos_symbol(o.symbol) == norm and o.side == 'buy' and o.status in ['filled', 'partially_filled', 'canceled', 'expired'] and getattr(o, 'filled_avg_price', None):
            return float(o.filled_avg_price)
    return 0.0

def compute_live_fill_slippage_bps(order):
    """Computes adverse fill slippage in bps relative to order limit_price or stop_price when present."""
    fill_px = float(getattr(order, 'filled_avg_price', 0.0) or 0.0)
    if fill_px <= 0:
        return None, 0.0
    ref_raw = getattr(order, 'limit_price', None) or getattr(order, 'stop_price', None)
    if ref_raw is None:
        return None, 0.0
    ref_px = float(ref_raw)
    if ref_px <= 0:
        return None, 0.0
    side = str(getattr(order, 'side', '')).lower()
    if side == 'buy':
        slip_bps = ((fill_px - ref_px) / ref_px) * 10000.0
    else:
        slip_bps = ((ref_px - fill_px) / ref_px) * 10000.0
    return round(slip_bps, 2), ref_px

def sync_recent_closed_sells(closed_orders, active_orders=None):
    if not closed_sheet:
        return []
    new_fill_alerts = []
    try:
        all_rows = closed_sheet.get_all_values()
        logged_qty_by_order = {}
        existing_ids = set()
        for r in all_rows[1:]:
            if len(r) >= 6:
                raw_id = str(r[5]).strip()
                existing_ids.add(raw_id)
                base_id = raw_id.split("#p")[0]
                try:
                    q_logged = float(r[2])
                except Exception:
                    q_logged = 0.0
                logged_qty_by_order[base_id] = logged_qty_by_order.get(base_id, 0.0) + q_logged

        existing_slip_ids = set(slippage_sheet.col_values(10)) if slippage_sheet else set()

        # Combine closed orders and active orders so partial fills are logged immediately without waiting for completion
        combined_by_id = {}
        for o in (closed_orders or []):
            combined_by_id[o.id] = o
        for o in (active_orders or []):
            if o.id not in combined_by_id:
                combined_by_id[o.id] = o

        for o in combined_by_id.values():
            filled_qty_val = float(getattr(o, 'filled_qty', 0.0) or 0.0)
            if filled_qty_val <= 0:
                continue

            # Log live-fill slippage for both buy and sell orders when reference price exists
            if slippage_sheet and o.id not in existing_slip_ids and o.status in ['filled', 'partially_filled']:
                slip_bps, ref_px = compute_live_fill_slippage_bps(o)
                if slip_bps is not None:
                    fill_px_s = float(getattr(o, 'filled_avg_price', 0.0) or 0.0)
                    ts_s = str(getattr(o, 'filled_at', None) or datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))[:19]
                    try:
                        slippage_sheet.append_row([
                            ts_s, o.symbol, str(o.side).upper(), str(o.type).upper(),
                            f"${ref_px:.4f}" if ref_px < 10.0 else f"${ref_px:.2f}",
                            f"${fill_px_s:.4f}" if fill_px_s < 10.0 else f"${fill_px_s:.2f}",
                            f"{slip_bps:+.2f}", f"{filled_qty_val:g}", classify_symbol(o.symbol), o.id
                        ])
                        existing_slip_ids.add(o.id)
                    except Exception as e:
                        logging.warning(f"Slippage audit write warning for {o.symbol}: {e}")

            if o.side != 'sell' or o.status not in ['filled', 'partially_filled', 'canceled', 'expired']:
                continue

            already_logged = logged_qty_by_order.get(o.id, 0.0)
            delta_qty = round(filled_qty_val - already_logged, 6)
            if delta_qty <= 1e-6:
                continue

            filled_time = str(o.filled_at)[:19] if getattr(o, 'filled_at', None) else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            fill_price = float(o.filled_avg_price) if getattr(o, 'filled_avg_price', None) else 0.0
            engine_tag = classify_symbol(o.symbol)
            entry_est = find_last_buy_fill_price(o.symbol, closed_orders or [])
            if entry_est > 0 and fill_price > 0:
                realized_pl = (fill_price - entry_est) * delta_qty
                realized_pct = ((fill_price - entry_est) / entry_est) * 100.0
            else:
                realized_pl, realized_pct = 0.0, 0.0

            is_partial = (o.status == 'partially_filled') or (already_logged > 0)
            if o.status == 'partially_filled':
                order_type = f"{o.type.upper()} (PARTIAL)"
                row_order_id = f"{o.id}#p{int(round(filled_qty_val * 10000))}"
            elif already_logged > 0:
                order_type = f"{o.type.upper()} (FINAL)"
                row_order_id = f"{o.id}#p{int(round(filled_qty_val * 10000))}"
            else:
                order_type = o.type.upper()
                row_order_id = o.id

            if row_order_id in existing_ids:
                continue

            closed_sheet.append_row([
                filled_time, o.symbol, f"{delta_qty:g}", order_type,
                f"${fill_price:.2f}", row_order_id, engine_tag,
                f"${entry_est:.2f}" if entry_est > 0 else "N/A",
                f"${realized_pl:+.2f}", f"{realized_pct:+.2f}%"
            ])
            existing_ids.add(row_order_id)
            logged_qty_by_order[o.id] = already_logged + delta_qty

            partial_lbl = " [PARTIAL FILL]" if is_partial else ""
            if o.type in ['stop', 'stop_limit']:
                new_fill_alerts.append(f"🛑 **STOP-LOSS TRIGGERED{partial_lbl} ({o.symbol} | {engine_tag})**: Sold {delta_qty:g} @ `${fill_price:.2f}` (P/L: `${realized_pl:+.2f}` / `{realized_pct:+.2f}%`)")
            elif o.type == 'limit':
                new_fill_alerts.append(f"🎯 **TAKE-PROFIT HIT{partial_lbl} ({o.symbol} | {engine_tag})**: Sold {delta_qty:g} @ `${fill_price:.2f}` (P/L: `${realized_pl:+.2f}` / `{realized_pct:+.2f}%`)")
    except Exception as e:
        logging.warning(f"Closed trades sheet sync warning: {e}")
    return new_fill_alerts

# =====================================================================
# 8. UNIVERSAL EQUITY TRANCHE EXECUTOR (STRICT TRANCHE OWNERSHIP GUARD)
# =====================================================================
def run_equity_tranche(
    tranche_name,
    tickers,
    sheet_ws,
    raw_positions,
    positions_map,
    held_returns_map,
    dynamic_caps,
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
    require_sma200=True,
    strategy_mode="core",
    reserved_exposure_pct=0.0,
    spy_5d_ret=0.0,
    ny_now=None
):
    tranche_alerts = []
    scan_lines = []
    rows_to_append = []
    pending_tranche_spend = 0.0
    ny_clock = ny_now or datetime.now(ZoneInfo("America/New_York"))
    signal_history = load_sheet_signal_history(sheet_ws, lookback_days=5)

    for ticker in tickers:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(ticker)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(ticker)
        obi = get_orderbook_imbalance(ticker)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"
        arb = compute_arbiter_matrix(
            score, tech, obi_score=obi,
            base_buy_min=buy_score_min, base_exit_max=exit_score_max,
            strategy_mode=strategy_mode
        )
        regime_tag = arb["regime"]

        pos = positions_map.get(ticker)
        owned_qty = float(pos.qty) if pos else 0.0
        decision = f"HOLD [{regime_tag}]"
        action_taken = "None"

        if owned_qty > 0 and classify_symbol(ticker) != tranche_name:
            continue

        if owned_qty > 0:
            entry_price = float(pos.avg_entry_price)
            current_price = float(pos.current_price)
            unrealized_pct = (current_price - entry_price) / entry_price
            unrealized_dlr = (current_price - entry_price) * owned_qty

            should_exit = (score <= exit_score_max) or (arb["arbiter_exit_reason"] is not None and unrealized_pct > 0.025)
            exit_label = arb["arbiter_exit_reason"] or f"Bearish Sentiment ({score:+.3f})"

            if should_exit:
                if not is_nyse_open:
                    decision = f"EXIT QUEUED [{regime_tag}]"
                    action_taken = f"Awaiting NYSE Open ({exit_label})"
                elif pdt_restricted and unrealized_pct > -0.04:
                    decision = "EXIT BLOCKED (PDT Shield)"
                    action_taken = "Skipped sell to prevent PDT lock (Loss < 4%)"
                else:
                    try:
                        cancel_existing_orders_for_ticker(ticker, active_orders)
                        sell_ord = api.submit_order(
                            symbol=ticker, qty=owned_qty, side='sell', type='market', time_in_force='gtc'
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
                        active_orders[:] = fetch_active_and_held_orders()
                        tranche_alerts.append(f"🔴 **[{tranche_name} | {regime_tag}] EXIT {ticker}**: {action_taken} (P/L: `${unrealized_dlr:+.2f}`)")
                    except Exception as e:
                        decision = "BEARISH"
                        action_taken = f"Sell Failed: {e}"
            else:
                if is_nyse_open:
                    _, current_sl, current_tp = get_active_sell_legs(ticker, active_orders=active_orders)
                    atr_val = max(tech['atr14'], current_price * 0.01) if tech is not None else (current_price * 0.02)
                    default_tp = round(max(entry_price, current_price) + (tp_atr_mult * atr_val), 2)
                    target_tp = current_tp if current_tp is not None else default_tp

                    if current_sl is None or current_tp is None:
                        repair_stop = current_sl if current_sl is not None else round(min(entry_price, current_price) - (sl_atr_mult * atr_val), 2)
                        ok, applied_sl, applied_tp = replace_with_atomic_oco(
                            symbol=ticker,
                            qty=owned_qty,
                            live_price=current_price,
                            target_sl=repair_stop,
                            target_tp=target_tp,
                            active_orders=active_orders
                        )
                        if ok:
                            active_orders[:] = fetch_active_and_held_orders()
                            tp_txt = f"${applied_tp:.2f}" if applied_tp else "None"
                            action_taken = f"Self-Healing OCO Attached -> SL ${applied_sl:.2f} | TP {tp_txt}"
                            tranche_alerts.append(f"🛡️ **[{tranche_name}] SELF-HEALING OCO ({ticker})**: Attached atomic GTC OCO ➔ SL `${applied_sl:.2f}` | TP `{tp_txt}`")
                    elif unrealized_pct >= ratchet_trigger_pct:
                        if unrealized_pct >= 0.060:
                            new_stop = round(max(entry_price * 1.035, current_price - (1.2 * atr_val)), 2)
                            stage_lbl = "Stage-3 Chandelier Trail"
                        elif unrealized_pct >= 0.040:
                            new_stop = round(entry_price * 1.020, 2)
                            stage_lbl = "Stage-2 (+2.0% Profit Lock)"
                        else:
                            new_stop = round(entry_price * 1.002, 2)
                            stage_lbl = "Stage-1 Break-Even"

                        if new_stop > current_sl + 0.05 and new_stop < current_price - 0.05:
                            ok, applied_sl, applied_tp = replace_with_atomic_oco(
                                symbol=ticker,
                                qty=owned_qty,
                                live_price=current_price,
                                target_sl=new_stop,
                                target_tp=target_tp,
                                active_orders=active_orders
                            )
                            if ok:
                                active_orders[:] = fetch_active_and_held_orders()
                                tp_txt = f"${applied_tp:.2f}" if applied_tp else "None"
                                action_taken = f"{stage_lbl} OCO Stop -> ${applied_sl:.2f} (TP {tp_txt})"
                                tranche_alerts.append(f"🛡️ **[{tranche_name}] {stage_lbl.upper()} ({ticker})**: Atomic OCO ratcheted `${current_sl:.2f}` ➔ `${applied_sl:.2f}` (`+{unrealized_pct*100:.1f}%` open gain)")

                decision = f"BULLISH (Owned | {regime_tag})" if arb["buy_signal"] else f"HOLD [{regime_tag}]"
        else:
            if arb.get("fee_block_reason"):
                decision = f"BULLISH (Blocked: {arb['fee_block_reason']})"
            elif arb["buy_signal"]:
                corr_ok, corr_reason = check_correlation_and_exposure_guard(
                    candidate=ticker,
                    tranche_name=tranche_name,
                    raw_positions=raw_positions,
                    equity=equity,
                    candidate_returns=tech["returns_60d"] if tech else None,
                    held_returns_map=held_returns_map,
                    dynamic_caps=dynamic_caps,
                    pending_tranche_spend=pending_tranche_spend,
                    reserved_exposure_pct=reserved_exposure_pct
                )
                # MEAN_REV is allowed to buy oversold snapbacks during elevated VIX unless Circuit Breaker or SPY Panic Block tripped
                macro_blocked = (not macro_ok) and not (
                    strategy_mode == "mean_rev"
                    and "CIRCUIT BREAKER" not in macro_reason
                    and "PANIC BLOCK" not in macro_reason
                )
                # CORE strictly enforces 20-EMA >= 50-SMA (even on NEWS-90/10) for multi-week drawdown validation
                core_trend_fail = (tranche_name == "CORE" and tech is not None and tech['ema20'] < tech['sma50'])
                general_trend_fail = (
                    tranche_name != "CORE"
                    and strategy_mode != "mean_rev"
                    and tech is not None
                    and tech['ema20'] < tech['sma50']
                    and regime_tag != "NEWS-90/10"
                )
                sma200_blocked = False
                if tech is not None:
                    if strategy_mode == "mean_rev":
                        sma200_blocked = tech['price'] < (tech['sma200'] * 0.92)
                    elif require_sma200:
                        sma200_blocked = tech['price'] < tech['sma200']

                if not is_nyse_open:
                    decision = f"BULLISH (Radar | {regime_tag})"
                    action_taken = f"Pre-Market Target @ ~${tech['price']:.2f} (Comp {arb['composite']:+.2f}, OBI {obi:+.2f})" if tech else "Queued Radar"
                elif macro_blocked:
                    decision = f"BULLISH (Blocked: {macro_reason})"
                elif not corr_ok:
                    decision = f"BULLISH (Blocked: {corr_reason})"
                elif pdt_restricted:
                    decision = "BULLISH (Blocked: PDT Shield)"
                elif was_stopped_out_last_24h(ticker, closed_orders_24h):
                    decision = "BULLISH (Blocked: 24h Stop Cooldown)"
                elif has_upcoming_earnings_48h(ticker):
                    decision = "BULLISH (Blocked: 48h Earnings Shield)"
                elif tech is None:
                    decision = "BULLISH (Blocked: No Tech Data)"
                elif sma200_blocked:
                    floor_lbl = f"92% of 200-SMA ${tech['sma200']*0.92:.2f}" if strategy_mode == "mean_rev" else f"200-SMA ${tech['sma200']:.2f}"
                    decision = f"BULLISH (Blocked: Below {floor_lbl})"
                elif core_trend_fail:
                    decision = f"BULLISH (Blocked: CORE Trend Guard 20-EMA ${tech['ema20']:.2f} < 50-SMA ${tech['sma50']:.2f})"
                elif general_trend_fail:
                    decision = "BULLISH (Blocked: 20-EMA < 50-SMA)"
                elif tech['rsi14'] > arb["rsi_max"]:
                    decision = f"BULLISH (Blocked: RSI {tech['rsi14']:.1f} > {arb['rsi_max']:.0f})"
                else:
                    # v8.7 Multi-Timeframe Confirmation, 5D RS vs SPY, Sentiment Drift & Persistence Gate
                    mtf_ok, mtf_status, mtf_note = evaluate_multi_timeframe_confirmation(
                        ticker=ticker,
                        tranche_name=tranche_name,
                        strategy_mode=strategy_mode,
                        score=score,
                        tech=tech,
                        spy_5d_ret=spy_5d_ret,
                        hist_entry=signal_history.get(ticker.upper()),
                        ny_now=ny_clock
                    )
                    if not mtf_ok:
                        decision = f"BULLISH ({mtf_status})"
                        if "STAGING 1/2" in mtf_status or "EOD-WAIT" in mtf_status:
                            action_taken = mtf_status
                    else:
                        price = tech['price']
                        atr = max(tech['atr14'], price * 0.01)
                        qty_to_buy = compute_atr_risk_parity_qty(
                            equity=equity, price=price, atr=atr,
                            sl_atr_mult=sl_atr_mult, risk_bps=risk_bps,
                            max_notional_pct=0.040, is_crypto=False
                        )

                        adj_tp_mult = round(tp_atr_mult * arb["tp_adj"], 2)
                        stop_price = round(min(price - (sl_atr_mult * atr), price - 0.05), 2)
                        target_price = round(max(price + (adj_tp_mult * atr), price + 0.05), 2)

                        try:
                            api.submit_order(
                                symbol=ticker, qty=qty_to_buy, side='buy', type='market', time_in_force='gtc',
                                order_class='bracket',
                                take_profit={'limit_price': target_price},
                                stop_loss={'stop_price': stop_price}
                            )
                            decision = f"BULLISH [{regime_tag} | {mtf_status}]"
                            trend_note = f" | EMA20 ${tech['ema20']:.2f}>=SMA50 ${tech['sma50']:.2f}" if tranche_name == "CORE" else ""
                            mtf_suffix = f" | {mtf_note}" if mtf_note else ""
                            action_taken = f"Risk-Parity Bought {qty_to_buy} @ ~${price:.2f} | TP: ${target_price:.2f} ({adj_tp_mult}x ATR), SL: ${stop_price:.2f}{trend_note}{mtf_suffix}"
                            pending_tranche_spend += (qty_to_buy * price)
                            if tech and "returns_60d" in tech:
                                held_returns_map[ticker] = tech["returns_60d"]
                            tranche_alerts.append(f"🟢 **[{tranche_name} | {regime_tag}] BUY {ticker}**: {action_taken} (FinBERT: `{score:+.3f}`, OBI: `{obi:+.2f}`, Comp: `{arb['composite']:+.2f}`)")
                        except Exception as e:
                            decision = f"BULLISH [{regime_tag}]"
                            action_taken = f"Buy Failed: {e}"
            elif score <= -0.10:
                decision = f"BEARISH (Not Owned | {regime_tag})"
            else:
                decision = f"HOLD [{regime_tag}]"

        row = [now_str, ticker, f"{score:+.3f}", f"[{tranche_name}] {decision}", action_taken, f"Holding {int(owned_qty)} shares"]
        rows_to_append.append(row)
        logging.info(f"[{tranche_name}] {ticker}: {score:+.3f} | OBI {obi:+.2f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{ticker}** `[{tranche_name} | {regime_tag}]`: FinBERT `{score:+.3f}` | OBI `{obi:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.35)

    if rows_to_append and sheet_ws:
        try:
            sheet_ws.append_rows(rows_to_append)
        except Exception as e:
            logging.warning(f"Batch sheet write warning ({tranche_name}): {e}")

    if pending_tranche_spend > 0:
        try:
            raw_positions[:] = api.list_positions()
        except Exception:
            pass

    return tranche_alerts, scan_lines

# =====================================================================
# 9. ENGINE 7: v8.0 OPTIONS GEX & INVERSE ETF TAIL-HEDGE OVERLAY
# =====================================================================
def run_tail_hedge_engine(raw_positions, positions_map, active_orders, equity, is_nyse_open, macro_ok, macro_reason, net_gex_score, risk_bps, sheet_ws=None):
    hedge_alerts = []
    hedge_lines = []
    hedge_sym = "SH"
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    pos = positions_map.get(hedge_sym)
    owned_qty = float(pos.qty) if pos else 0.0
    tech = get_technicals_and_atr(hedge_sym)
    price = tech["price"] if tech else 12.0

    needs_hedge = (not macro_ok) or (net_gex_score <= -0.18)
    hedge_notional_cap = 0.12 if not macro_ok else 0.08
    decision = "STANDBY"
    action_taken = "None"

    if owned_qty > 0 and macro_ok and net_gex_score > -0.05 and is_nyse_open:
        try:
            cancel_existing_orders_for_ticker(hedge_sym, active_orders)
            api.submit_order(symbol=hedge_sym, qty=owned_qty, side="sell", type="market", time_in_force="gtc")
            decision = "UNWIND [TAIL_HEDGE]"
            action_taken = f"Sold {int(owned_qty)} {hedge_sym} (Macro/GEX normalized)"
            owned_qty = 0.0
            hedge_alerts.append(f"🛡️ **[TAIL_HEDGE UNWOUND] Sold {int(float(pos.qty))} {hedge_sym}**: Macro & GEX normalized (`{macro_reason}`).")
            hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: Unwound hedge as Macro/GEX normalized.")
        except Exception as e:
            logging.warning(f"Tail hedge unwind note: {e}")
    elif owned_qty == 0 and needs_hedge and is_nyse_open and tech is not None:
        atr = max(tech["atr14"], price * 0.01)
        qty_to_buy = compute_atr_risk_parity_qty(equity, price, atr, sl_atr_mult=1.2, risk_bps=risk_bps * 1.5, max_notional_pct=hedge_notional_cap, is_crypto=False)
        hedge_sl = round(min(price * 0.965, price - 0.05), 2)
        hedge_tp = round(max(price * 1.12, price + 0.05), 2)
        try:
            api.submit_order(
                symbol=hedge_sym,
                qty=qty_to_buy,
                side="buy",
                type="market",
                time_in_force="gtc",
                order_class="bracket",
                take_profit={"limit_price": hedge_tp},
                stop_loss={"stop_price": hedge_sl}
            )
            decision = "DEPLOY [TAIL_HEDGE]"
            action_taken = f"Bracket Bought {qty_to_buy} {hedge_sym} @ ~${price:.2f} | SL ${hedge_sl:.2f} | TP ${hedge_tp:.2f}"
            owned_qty = float(qty_to_buy)
            hedge_alerts.append(f"🛡️ **[v8.0 TAIL_HEDGE DEPLOYED] Bought {qty_to_buy} {hedge_sym} @ ~${price:.2f}** (SL `${hedge_sl:.2f}` / TP `${hedge_tp:.2f}`): Triggered by `{macro_reason}`")
            hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: Deployed {qty_to_buy} sh inverse shield (`{macro_reason}`).")
        except Exception as e:
            logging.warning(f"Tail hedge buy note: {e}")
    else:
        status_str = f"Holding {int(owned_qty)} sh Active Shield" if owned_qty > 0 else f"Standby (GEX {net_gex_score:+.2f} Normal)"
        decision = "HOLD [TAIL_HEDGE]" if owned_qty > 0 else "STANDBY [TAIL_HEDGE]"
        action_taken = status_str
        hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: `{status_str}`")

    if sheet_ws:
        try:
            sheet_ws.append_row([now_str, hedge_sym, f"{net_gex_score:+.3f}", f"[TAIL_HEDGE] {decision}", action_taken, f"Holding {int(owned_qty)} shares"])
        except Exception as e:
            logging.warning(f"Tail hedge sheet write warning: {e}")

    return hedge_alerts, hedge_lines

# =====================================================================
# 10. ENGINE 3: 24/7 CRYPTO AI QUANT EXECUTOR (SPREAD GUARD + BTC SHIELD + ATR STOPS)
# =====================================================================
def get_crypto_quote_and_spread(pair):
    """Fetches live bid, ask, mid-price, and spread % from Alpaca US Crypto feed."""
    try:
        quotes = api.get_latest_crypto_quotes([pair], "us")
        q = quotes.get(pair)
        if q:
            bid = float(getattr(q, "bp", 0.0) or getattr(q, "bid_price", 0.0) or 0.0)
            ask = float(getattr(q, "ap", 0.0) or getattr(q, "ask_price", 0.0) or 0.0)
            if bid > 0 and ask >= bid:
                mid = (bid + ask) / 2.0
                spread_pct = (ask - bid) / mid
                return bid, ask, mid, spread_pct
    except Exception as e:
        logging.warning(f"Crypto quote check note for {pair}: {e}")
    return 0.0, 0.0, 0.0, 0.0

def run_crypto_tranche(crypto_candidates, raw_positions, positions_map, held_returns_map, dynamic_caps, active_orders, closed_orders_24h, equity, macro_ok, macro_reason, risk_bps, ny_now=None):
    crypto_alerts = []
    scan_lines = []
    rows_to_append = []
    ny_clock = ny_now or datetime.now(ZoneInfo("America/New_York"))
    crypto_history = load_sheet_signal_history(crypto_sheet, lookback_days=5)

    # --- 1. BITCOIN MACRO REGIME SHIELD ---
    btc_headlines = get_fresh_dual_news("BTC/USD")
    btc_score = get_finbert_sentiment(btc_headlines)
    btc_tech = get_technicals_and_atr("BTC/USD")
    btc_macro_ok = True
    btc_macro_reason = "BTC Normal"
    if btc_tech is not None:
        if btc_score <= -0.15 or (btc_tech["price"] < btc_tech["ema20"] and btc_tech["rsi14"] < 42.0):
            btc_macro_ok = False
            btc_macro_reason = f"BTC Downtrend Shield (BTC FinBERT {btc_score:+.2f}, RSI {btc_tech['rsi14']:.1f})"

    for pair in crypto_candidates:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = btc_headlines if pair == "BTC/USD" else get_fresh_dual_news(pair)
        score = btc_score if pair == "BTC/USD" else get_finbert_sentiment(headlines)
        tech = btc_tech if pair == "BTC/USD" else get_technicals_and_atr(pair)
        obi = get_orderbook_imbalance(pair)
        bid_px, ask_px, mid_px, spread_pct = get_crypto_quote_and_spread(pair)

        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"
        arb = compute_arbiter_matrix(score, tech, obi_score=obi, base_buy_min=0.15, base_exit_max=-0.30, strategy_mode="crypto")
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

            # Dynamic 2.0x ATR Stop-Loss & 4.0x ATR Take-Profit (clamped for safety)
            atr_val = tech["atr14"] if tech else (entry_price * 0.025)
            dyn_sl_pct = -max(0.025, min(0.060, (2.0 * atr_val) / entry_price))
            dyn_tp_pct = max(0.050, min(0.120, (4.0 * atr_val * arb["tp_adj"]) / entry_price))

            exit_reason = None
            if unrealized_pct >= dyn_tp_pct:
                exit_reason = f"ATR Take-Profit Hit (+{unrealized_pct*100:.2f}% >= +{dyn_tp_pct*100:.1f}%)"
            elif unrealized_pct <= dyn_sl_pct:
                exit_reason = f"ATR Stop-Loss Hit ({unrealized_pct*100:.2f}% <= {dyn_sl_pct*100:.1f}%)"
            elif arb["arbiter_exit_reason"] and unrealized_pct > 0.015:
                exit_reason = arb["arbiter_exit_reason"]
            elif score <= -0.35 and unrealized_pct < 0.01:
                exit_reason = f"Bearish Crypto Catalyst ({score:+.3f})"

            if exit_reason:
                try:
                    cancel_existing_orders_for_ticker(pair, active_orders)
                    sell_order = api.close_position(norm_sym)
                    decision = f"EXIT [{regime_tag}]"
                    action_taken = f"Liquidated Position {owned_qty:.4f} @ ~${current_price:.4f} ({exit_reason})"
                    if closed_sheet:
                        closed_sheet.append_row([
                            now_str[:19], pair, f"{owned_qty:.4f}", exit_reason[:28],
                            f"${current_price:.4f}", str(getattr(sell_order, 'id', 'CRYPTO_CLOSE')),
                            "CRYPTO", f"${entry_price:.4f}", f"${unrealized_dlr:+.2f}", f"{unrealized_pct*100:+.2f}%"
                        ])
                    owned_qty = 0.0
                    crypto_alerts.append(f"🪙 **[CRYPTO EXIT | {regime_tag}] {pair}**: {action_taken} (P/L: `${unrealized_dlr:+.2f}`)")
                except Exception as e:
                    decision = "EXIT"
                    action_taken = f"Crypto Liquidation Failed: {e}"
            else:
                if unrealized_pct >= 0.030:
                    decision = f"HOLD (🛡️ +{unrealized_pct*100:.1f}% Open Gain | {regime_tag})"
                elif arb["buy_signal"]:
                    decision = f"BULLISH (Holding | {regime_tag})"
                else:
                    decision = f"HOLD [{regime_tag}]"
        else:
            if arb.get("fee_block_reason"):
                decision = f"BULLISH (Blocked: {arb['fee_block_reason']})"
            elif arb["buy_signal"] and tech is not None:
                corr_ok, corr_reason = check_correlation_and_exposure_guard(
                    candidate=pair, tranche_name="CRYPTO", raw_positions=raw_positions,
                    equity=equity, candidate_returns=tech["returns_60d"],
                    held_returns_map=held_returns_map, dynamic_caps=dynamic_caps
                )
                if not macro_ok and "CIRCUIT BREAKER" in macro_reason:
                    decision = f"BULLISH (Blocked: {macro_reason})"
                elif not btc_macro_ok:
                    decision = f"BULLISH (Blocked: {btc_macro_reason})"
                elif spread_pct > 0.0035:
                    decision = f"BULLISH (Blocked: Spread {spread_pct*100:.2f}% > 0.35% Max)"
                elif was_crypto_sold_recently(pair, closed_orders_24h, hours=6):
                    decision = "BULLISH (Blocked: 6h Exit Cooldown)"
                elif not corr_ok:
                    decision = f"BULLISH (Blocked: {corr_reason})"
                elif tech["price"] < tech["ema20"]:
                    decision = f"BULLISH (Blocked: Below 1h 20-EMA ${tech['ema20']:.2f})"
                else:
                    # v8.7 Crypto 2-Scan Persistence & Anti-'Sell the News' Filter
                    mtf_ok, mtf_status, mtf_note = evaluate_multi_timeframe_confirmation(
                        ticker=pair,
                        tranche_name="CRYPTO",
                        strategy_mode="crypto",
                        score=score,
                        tech=tech,
                        spy_5d_ret=0.0,
                        hist_entry=crypto_history.get(pair.upper()),
                        ny_now=ny_clock
                    )
                    if not mtf_ok:
                        decision = f"BULLISH ({mtf_status})"
                        if "STAGING 1/2" in mtf_status:
                            action_taken = mtf_status
                    else:
                        price = ask_px if ask_px > 0 else tech['price']
                        atr = max(tech['atr14'], price * 0.015)
                        # Size using 2.0x ATR stop distance so dollar risk is strictly capped
                        qty_to_buy = compute_atr_risk_parity_qty(
                            equity=equity, price=price, atr=atr,
                            sl_atr_mult=2.0, risk_bps=risk_bps,
                            max_notional_pct=0.030, is_crypto=True
                        )
                        price_decimals = 4 if price < 10.0 else 2
                        limit_buy_px = round(price * 1.001, price_decimals)

                        if qty_to_buy > 0:
                            try:
                                # Cancel any unfilled resting orders first so limit buys never stack
                                cancel_existing_orders_for_ticker(pair, active_orders)
                                api.submit_order(
                                    symbol=pair,
                                    qty=qty_to_buy,
                                    side='buy',
                                    type='limit',
                                    limit_price=limit_buy_px,
                                    time_in_force='ioc'
                                )
                                decision = f"BULLISH [{regime_tag} | {mtf_status}]"
                                mtf_suffix = f" | {mtf_note}" if mtf_note else ""
                                action_taken = f"Limit IOC Bought {qty_to_buy:.4f} @ ${limit_buy_px:.4f} (Spread {spread_pct*100:.2f}% | OBI {obi:+.2f}){mtf_suffix}"
                                held_returns_map[pair] = tech["returns_60d"]
                                try:
                                    raw_positions[:] = api.list_positions()
                                except Exception:
                                    pass
                                crypto_alerts.append(f"🪙 **[CRYPTO BUY | {regime_tag}] {pair}**: {action_taken} (FinBERT: `{score:+.3f}`, Comp: `{arb['composite']:+.2f}`)")
                            except Exception as e:
                                decision = f"BULLISH [{regime_tag}]"
                                action_taken = f"Crypto Buy Failed: {e}"
            elif score <= -0.15:
                decision = f"BEARISH (Not Owned | {regime_tag})"
            else:
                decision = f"HOLD [{regime_tag}]"

        row = [now_str, pair, f"{score:+.3f}", decision, action_taken, f"Holding {owned_qty:.4f} units"]
        rows_to_append.append(row)
        logging.info(f"[CRYPTO] {pair}: {score:+.3f} | OBI {obi:+.2f} | Spread {spread_pct*100:.2f}% | {decision} | {action_taken}")
        scan_lines.append(f"• **{pair}** `[{regime_tag}]`: FinBERT `{score:+.3f}` | OBI `{obi:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.35)

    if rows_to_append and crypto_sheet:
        try:
            crypto_sheet.append_rows(rows_to_append)
        except Exception as e:
            logging.warning(f"Batch sheet write warning (CRYPTO): {e}")

    return crypto_alerts, scan_lines

# =====================================================================
# 10.5. ENGINE 8: THE LIQUIDITY PREDATOR (FLUSH HUNTER)
# =====================================================================
def map_liquidity_clusters_and_bid(ticker, df_yf, equity, risk_bps):
    """
    Identifies retail stop-loss clusters (MAs, swing lows, psychological boundaries)
    and formulates predatory limit bids to catch the slippage flush natively on the broker.
    """
    if df_yf.empty or len(df_yf) < 200:
        return None

    close = float(df_yf["Close"].iloc[-1])
    sma200 = float(df_yf["Close"].rolling(200).mean().iloc[-1])
    sma50 = float(df_yf["Close"].rolling(50).mean().iloc[-1])
    swing_low_20 = float(df_yf["Low"].rolling(20).min().iloc[-1])
    atr = float((df_yf["High"] - df_yf["Low"]).rolling(14).mean().iloc[-1])

    # Check falling-knife velocity / recent momentum to avoid catching free-falling knives
    recent_ret = float(df_yf["Close"].pct_change().iloc[-1])
    if recent_ret < -0.06:  # Asset is crashing too violently (>6% single-day drop), skip knife-catching
        return None

    clusters = []

    # 1. Psychological Round Numbers (e.g., $100.00, $50.00)
    order_of_mag = 10 if close < 200 else 50
    nearest_round_floor = math.floor(close / order_of_mag) * order_of_mag
    if (close - nearest_round_floor) / close < 0.04 and nearest_round_floor < close:
        clusters.append({"type": "Psy-Round", "level": nearest_round_floor})

    # 2. Moving Average Floors
    if close > sma200 and (close - sma200) / close < 0.05:
        clusters.append({"type": "200-SMA", "level": sma200})
    if close > sma50 and (close - sma50) / close < 0.04:
        clusters.append({"type": "50-SMA", "level": sma50})

    # 3. Swing Lows
    if close > swing_low_20 and (close - swing_low_20) / close < 0.03:
        clusters.append({"type": "20D-Low", "level": swing_low_20})

    if not clusters:
        return None

    # Find the most relevant cluster (closest below current price)
    clusters = sorted(clusters, key=lambda x: close - x["level"])
    target_cluster = clusters[0]
    cluster_px = target_cluster["level"]

    # The Predator Bid: Set limit order 0.65% to 1.2% BELOW the cluster to catch stop-loss slippage
    flush_discount = max(0.0065, (atr / close) * 0.5)
    predator_bid = round(cluster_px * (1.0 - flush_discount), 2)

    # Risk-Parity Sizing based on a catastrophic hard stop (strictly bounded for Alpaca bracket validity)
    catastrophic_stop = round(min(predator_bid - (atr * 1.5), predator_bid - 0.05), 2)
    stop_dist = max(predator_bid - catastrophic_stop, 0.05)
    raw_qty = (equity * risk_bps) / stop_dist
    max_qty = (equity * 0.05) / predator_bid
    qty = max(1, int(min(raw_qty, max_qty)))

    # Instant Mean-Reversion Target (Snapback to the broken cluster level, strictly above predator_bid)
    snapback_tp = round(max(cluster_px * 1.015, predator_bid + 0.05), 2)

    return {
        "Ticker": ticker,
        "Cluster Level": round(cluster_px, 2),
        "Cluster Type": target_cluster["type"],
        "Live Price": round(close, 2),
        "Predator Bid": predator_bid,
        "Snapback TP": snapback_tp,
        "Hard Stop": catastrophic_stop,
        "Qty": qty,
        "Capital Req": round(qty * predator_bid, 2)
    }

def run_predator_tranche(equity, active_orders, positions_map, sheet_ws, risk_bps, raw_positions=None, dynamic_caps=None, macro_ok=True):
    alerts = []
    lines = []
    rows_to_append = []

    if equity <= 0:
        return alerts, lines

    invested_now = sum(float(p.market_value) for p in (raw_positions or []))
    resting_buy_orders = [o for o in active_orders if o.side == 'buy' and o.type == 'limit' and getattr(o, 'limit_price', None)]

    if not macro_ok or (invested_now / equity) >= 0.65:
        for o in resting_buy_orders:
            try:
                api.cancel_order(o.id)
            except Exception as e:
                logging.warning(f"Predator trap cancel warning for {o.symbol}: {e}")
        logging.info("[PREDATOR] Paused/cleared traps: Macro block or Exposure >= 65% Dry Powder Guard.")
        return alerts, lines

    resting_buy_notional = sum(float(o.qty) * float(o.limit_price) for o in resting_buy_orders)
    max_predator_cap = (dynamic_caps or {}).get("PREDATOR", 0.15)
    pending_predator_spend = 0.0

    if ((invested_now + resting_buy_notional) / equity) >= 0.65:
        logging.info("[PREDATOR] Skipping new traps: Total exposure + resting bids >= 65% Dry Powder Guard.")
        return alerts, lines

    pool = CORE_POOL + MOMENTUM_POOL
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Batch download for speed and efficiency
    yf_list = [to_yf_symbol(t) for t in pool]
    try:
        data = yf.download(yf_list, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
    except Exception as e:
        logging.warning(f"Predator data fetch error: {e}")
        return alerts, lines

    for ticker in pool:
        if ((invested_now + resting_buy_notional + pending_predator_spend) / equity) >= 0.65:
            break
        if ((resting_buy_notional + pending_predator_spend) / equity) >= max_predator_cap:
            break

        if ticker in positions_map or to_alpaca_pos_symbol(ticker) in positions_map:
            continue

        # Check if we already have a resting buy limit order for this trap
        existing_orders = [o for o in active_orders if to_alpaca_pos_symbol(o.symbol) == to_alpaca_pos_symbol(ticker) and o.side == 'buy' and o.type == 'limit']
        if existing_orders:
            continue

        yf_sym = to_yf_symbol(ticker)
        try:
            df_t = data[yf_sym] if len(yf_list) > 1 else data
            df_t = df_t.dropna(subset=["Close"])
        except Exception:
            continue

        trap = map_liquidity_clusters_and_bid(ticker, df_t, equity, risk_bps)
        if trap:
            try:
                api.submit_order(
                    symbol=trap["Ticker"],
                    qty=trap["Qty"],
                    side="buy",
                    type="limit",
                    limit_price=trap["Predator Bid"],
                    time_in_force="gtc",
                    order_class="bracket",
                    take_profit={"limit_price": trap["Snapback TP"]},
                    stop_loss={"stop_price": trap["Hard Stop"]}
                )
                pending_predator_spend += trap["Capital Req"]
                action_taken = f"Armed {trap['Cluster Type']} Trap: Limit Buy {trap['Qty']} @ ${trap['Predator Bid']} | TP ${trap['Snapback TP']} | SL ${trap['Hard Stop']}"
                decision = "BULLISH [PREDATOR-FLUSH]"
                alerts.append(f"🩸 **[PREDATOR TRAP ARMED] {ticker}**: {action_taken} (Cluster: `${trap['Cluster Level']}`)")
                lines.append(f"• **{ticker}** `[PREDATOR]`: {action_taken}")
                rows_to_append.append([now_str, ticker, "N/A (Predator)", decision, action_taken, f"Capital Req: ${trap['Capital Req']}"])
                time.sleep(0.35)
            except Exception as e:
                logging.warning(f"Predator order failed for {ticker}: {e}")

    if rows_to_append and sheet_ws:
        try:
            sheet_ws.append_rows(rows_to_append)
        except Exception as e:
            logging.warning(f"Predator sheet write warning: {e}")

    return alerts, lines

# =====================================================================
# 11. MASTER ORCHESTRATOR
# =====================================================================
def run_bot(mode="auto"):
    for attempt in range(3):
        try:
            clock = api.get_clock()
            account = api.get_account()
            break
        except Exception as e:
            logging.warning(f"Alpaca API temporarily unavailable (Attempt {attempt+1}/3): {e}")
            if attempt == 2:
                logging.error("Alpaca servers are undergoing maintenance. Exiting gracefully.")
                return
            time.sleep(5)

    is_nyse_open = bool(clock.is_open)
    ny_now = datetime.now(ZoneInfo("America/New_York"))

    # If triggered by fallback schedule while NYSE is closed, only run Crypto
    if mode in ["auto", "intraday"] and not is_nyse_open:
        mode = "crypto"

    equity = float(account.equity)
    last_equity = float(getattr(account, 'last_equity', equity) or equity)
    daytrade_count = int(getattr(account, 'daytrade_count', 0) or 0)
    pdt_restricted = daytrade_count >= 3

    engine_cfg = load_or_init_engine_config()

    # If NYSE is closed (routed to crypto) and CRYPTO is disabled on Switchboard, exit cleanly
    if mode == "crypto" and not engine_cfg.get("CRYPTO", {}).get("enabled", False):
        logging.info("NYSE is closed and CRYPTO engine is disabled on Switchboard. Exiting gracefully.")
        return

    macro_ok, macro_reason, net_gex_score = check_macro_gex_and_circuit_breaker(equity, last_equity)
    spy_5d_ret = get_spy_5d_return()
    dynamic_caps = compute_rl_meta_allocation(engine_cfg, net_gex_score)

    def should_run(eng_key):
        if not engine_cfg.get(eng_key, {}).get("enabled", False):
            return False
        if mode in ["all", "auto"] or mode == eng_key.lower():
            return True
        if mode == "intraday":
            return eng_key in ["CORE", "MOMENTUM", "CRYPTO", "DISCOVERY", "MEAN_REV", "SMALL_CAP", "TAIL_HEDGE", "COMMODITIES", "DEFENSE", "PREDATOR"]
        return False

    raw_positions = api.list_positions()
    positions_map = {}
    owned_symbols = set()
    held_returns_map = {}

    for p in raw_positions:
        disp_sym = CRYPTO_NORM.get(str(p.symbol), str(p.symbol))
        positions_map[p.symbol] = p
        positions_map[to_alpaca_pos_symbol(p.symbol)] = p
        owned_symbols.add(p.symbol)
        owned_symbols.add(to_alpaca_pos_symbol(p.symbol))
        try:
            df_h = yf.Ticker(to_yf_symbol(disp_sym)).history(period="3mo")
            if not df_h.empty and len(df_h) >= 20:
                held_returns_map[disp_sym] = df_h["Close"].pct_change().dropna().tail(60)
        except Exception as e:
            logging.warning(f"Held return history note for {disp_sym}: {e}")

    active_orders = fetch_active_and_held_orders()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    automated_exit_alerts = sync_recent_closed_sells(closed_orders_24h, active_orders=active_orders)
    all_alerts = list(automated_exit_alerts)
    section_reports = []

    # Helper to reserve unused exposure headroom for MEAN_REV & SMALL_CAP so CORE/MOMENTUM cannot starve them
    def calc_reserved_opportunity_headroom():
        reserved = 0.0
        if equity <= 0:
            return 0.0
        for opp_eng, target_floor in [("MEAN_REV", 0.08), ("SMALL_CAP", 0.07)]:
            if engine_cfg.get(opp_eng, {}).get("enabled", False):
                opp_inv = sum(
                    float(p.market_value) for p in raw_positions
                    if classify_symbol(CRYPTO_NORM.get(str(p.symbol), str(p.symbol))) == opp_eng
                )
                opp_pct = opp_inv / equity
                if opp_pct < target_floor:
                    reserved += (target_floor - opp_pct)
        return round(min(reserved, 0.15), 3)

    # 1. Crash Protection First (Immediate, never delayed)
    if should_run("TAIL_HEDGE"):
        logging.info("=== Running Engine 7: v8.0 Options GEX & Tail-Hedge Overlay ===")
        th_alerts, th_lines = run_tail_hedge_engine(
            raw_positions, positions_map, active_orders, equity, is_nyse_open,
            macro_ok, macro_reason, net_gex_score, engine_cfg.get("TAIL_HEDGE", {}).get("risk_bps", 0.0050),
            sheet_ws=tail_hedge_sheet
        )
        all_alerts.extend(th_alerts)
        if th_lines:
            section_reports.append("🛡️ **Engine 7 — Options GEX & Tail-Hedge Overlay:**\n" + "\n".join(th_lines))

    # 2. 24/7 Crypto AI Quant (2-Scan Persistence)
    if should_run("CRYPTO"):
        logging.info("=== Running Engine 3: 24/7 Crypto AI Quant ===")
        alt_candidates = screen_top_candidates(CRYPTO_ALTS, top_n=4, owned_symbols=owned_symbols, mode="crypto", tranche_name="CRYPTO")
        crypto_candidates = list(dict.fromkeys(CRYPTO_MAJORS + alt_candidates))
        c_alerts, crypto_lines = run_crypto_tranche(
            crypto_candidates, raw_positions, positions_map, held_returns_map, dynamic_caps,
            active_orders, closed_orders_24h, equity, macro_ok, macro_reason,
            engine_cfg.get("CRYPTO", {}).get("risk_bps", 0.0045), ny_now=ny_now
        )
        all_alerts.extend(c_alerts)
        if crypto_lines:
            section_reports.append("🪙 **Engine 3 — 24/7 Crypto AI (48x/Day):**\n" + "\n".join(crypto_lines))

    # 3. Prioritized Opportunistic Engines (MEAN_REV & SMALL_CAP scan BEFORE CORE/MOMENTUM)
    if should_run("MEAN_REV"):
        logging.info("=== Running Engine 5: Statistical Mean-Reversion ===")
        mr_candidates = screen_top_candidates(MEAN_REV_POOL, top_n=5, owned_symbols=owned_symbols, mode="mean_rev", tranche_name="MEAN_REV")
        mr_alerts, mr_lines = run_equity_tranche(
            tranche_name="MEAN_REV", tickers=mr_candidates, sheet_ws=mean_rev_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=-0.10, exit_score_max=-0.30,
            sl_atr_mult=1.0, tp_atr_mult=1.8, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("MEAN_REV", {}).get("risk_bps", 0.0035), require_sma200=False,
            strategy_mode="mean_rev", spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(mr_alerts)
        if mr_lines:
            section_reports.append("🧲 **Engine 5 — Statistical Mean-Reversion:**\n" + "\n".join(mr_lines))

    if should_run("SMALL_CAP"):
        logging.info("=== Running Engine 6: Small-Cap Speculative Breakouts ===")
        sc_candidates = screen_top_candidates(SMALL_CAP_POOL, top_n=5, owned_symbols=owned_symbols, mode="small_cap", tranche_name="SMALL_CAP")
        sc_alerts, sc_lines = run_equity_tranche(
            tranche_name="SMALL_CAP", tickers=sc_candidates, sheet_ws=small_cap_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.10, exit_score_max=-0.12,
            sl_atr_mult=1.2, tp_atr_mult=2.5, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("SMALL_CAP", {}).get("risk_bps", 0.0030), require_sma200=False,
            strategy_mode="small_cap", spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(sc_alerts)
        if sc_lines:
            section_reports.append("🚀 **Engine 6 — Small-Cap Alpha Breakouts:**\n" + "\n".join(sc_lines))

    # 4. Market-Wide Discovery & Defensive Safe Havens (Dedicated Log Sheets)
    if should_run("DISCOVERY"):
        logging.info("=== Running Engine 4: Market-Wide AI Discovery Agent ===")
        disc_candidates = discover_market_wide_catalysts(owned_symbols, top_n=5)
        if disc_candidates:
            disc_alerts, disc_lines = run_equity_tranche(
                tranche_name="DISCOVERY", tickers=disc_candidates, sheet_ws=discovery_sheet,
                raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
                dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
                equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
                is_nyse_open=is_nyse_open, buy_score_min=0.15, exit_score_max=-0.15,
                sl_atr_mult=1.2, tp_atr_mult=2.8, ratchet_trigger_pct=0.020,
                risk_bps=engine_cfg.get("DISCOVERY", {}).get("risk_bps", 0.0035), require_sma200=False,
                strategy_mode="discovery", spy_5d_ret=spy_5d_ret, ny_now=ny_now
            )
            all_alerts.extend(disc_alerts)
            if disc_lines:
                section_reports.append("🛰️ **Engine 4 — Market-Wide AI Discovery Agent:**\n" + "\n".join(disc_lines))

    if should_run("COMMODITIES"):
        logging.info("=== Running Engine: Commodities & Hard Assets ===")
        comm_candidates = screen_top_candidates(COMMODITY_POOL, top_n=3, owned_symbols=owned_symbols, mode="core", tranche_name="COMMODITIES")
        comm_alerts, comm_lines = run_equity_tranche(
            tranche_name="COMMODITIES", tickers=comm_candidates, sheet_ws=commodities_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.20,
            sl_atr_mult=1.5, tp_atr_mult=3.0, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("COMMODITIES", {}).get("risk_bps", 0.0035), require_sma200=True,
            strategy_mode="core", spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(comm_alerts)
        if comm_lines:
            section_reports.append("🛢️ **Engine — Commodities (Safe Haven):**\n" + "\n".join(comm_lines))

    if should_run("DEFENSE"):
        logging.info("=== Running Engine: Aerospace & Defense ===")
        def_candidates = screen_top_candidates(DEFENSE_POOL, top_n=4, owned_symbols=owned_symbols, mode="core", tranche_name="DEFENSE")
        def_alerts, def_lines = run_equity_tranche(
            tranche_name="DEFENSE", tickers=def_candidates, sheet_ws=defense_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.20,
            sl_atr_mult=1.5, tp_atr_mult=3.0, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("DEFENSE", {}).get("risk_bps", 0.0035), require_sma200=True,
            strategy_mode="core", spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(def_alerts)
        if def_lines:
            section_reports.append("🛡️ **Engine — Aerospace & Defense (Safe Haven):**\n" + "\n".join(def_lines))

    # 5. Core & Momentum (Respect reserved headroom so MEAN_REV / SMALL_CAP are never crowded out)
    if should_run("CORE"):
        logging.info("=== Running Engine 1: Core Long-Term Equities ===")
        core_candidates = screen_top_candidates(CORE_POOL, top_n=8, owned_symbols=owned_symbols, mode="core", tranche_name="CORE")
        core_alerts, core_lines = run_equity_tranche(
            tranche_name="CORE", tickers=core_candidates, sheet_ws=core_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.10, exit_score_max=-0.15,
            sl_atr_mult=1.5, tp_atr_mult=3.5, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("CORE", {}).get("risk_bps", 0.0050), require_sma200=True, strategy_mode="core",
            reserved_exposure_pct=calc_reserved_opportunity_headroom(), spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(core_alerts)
        if core_lines:
            section_reports.append("🛡️ **Engine 1 — Core Blue-Chips:**\n" + "\n".join(core_lines))

    if should_run("MOMENTUM"):
        logging.info("=== Running Engine 2: Short-Term Momentum ===")
        mom_candidates = screen_top_candidates(MOMENTUM_POOL, top_n=6, owned_symbols=owned_symbols, mode="momentum", tranche_name="MOMENTUM")
        mom_alerts, mom_lines = run_equity_tranche(
            tranche_name="MOMENTUM", tickers=mom_candidates, sheet_ws=momentum_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.12,
            sl_atr_mult=1.0, tp_atr_mult=2.0, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("MOMENTUM", {}).get("risk_bps", 0.0040), require_sma200=False, strategy_mode="momentum",
            reserved_exposure_pct=calc_reserved_opportunity_headroom(), spy_5d_ret=spy_5d_ret, ny_now=ny_now
        )
        all_alerts.extend(mom_alerts)
        if mom_lines:
            section_reports.append("⚡ **Engine 2 — Short-Term Momentum (14x/Day):**\n" + "\n".join(mom_lines))

    # 6. Liquidity Predator Traps
    if should_run("PREDATOR") and is_nyse_open:
        logging.info("=== Running Engine 8: Liquidity Predator ===")
        pred_alerts, pred_lines = run_predator_tranche(
            equity=equity, active_orders=active_orders, positions_map=positions_map,
            sheet_ws=predator_sheet, risk_bps=engine_cfg.get("PREDATOR", {}).get("risk_bps", 0.0050),
            raw_positions=raw_positions, dynamic_caps=dynamic_caps, macro_ok=macro_ok
        )
        all_alerts.extend(pred_alerts)
        if pred_lines:
            section_reports.append("🩸 **Engine 8 — Liquidity Predator (Flush Hunter):**\n" + "\n".join(pred_lines))

    # 7. Universal OCO Self-Healer & 3-Stage Ratchet Safety Net (Immediate, covers ALL open equities incl. SH & PREDATOR fills)
    try:
        oco_alerts = enforce_oco_protection_all_positions(is_nyse_open=is_nyse_open)
        all_alerts.extend(oco_alerts)
    except Exception as e:
        logging.error(f"[OCO-GUARD] Top-level safety net error: {e}")

    if all_alerts:
        send_discord_alert("🚨 **AETHER QUANT v8.7 Execution Alert (Multi-Timeframe Persistence • RL Defensive Meta • OCO Guard):**\n" + "\n".join(all_alerts))

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
        enabled_list = [k for k, v in engine_cfg.items() if v["enabled"]]

        detailed_report = (
            f"💠 **AETHER QUANT v8.7 OMEGA Telemetry (Multi-Timeframe Persistence • GEX Defensive Meta)**\n"
            f"🕒 **Time (NY):** `{ny_time.strftime('%Y-%m-%d %I:%M %p')}` | 🏦 **NYSE:** `{'OPEN' if is_nyse_open else 'CLOSED (24/7 Radar & Crypto)'}` | 🌍 **Regime:** `{macro_reason}` | 🧭 **SPY 5D:** `{spy_5d_ret*100:+.2f}%`\n"
            f"🎛️ **Active Engines ({len(enabled_list)}/10):** `{', '.join(enabled_list)}`\n"
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
            stop_str, tp_str = "None", "None"
            tranche_tag = classify_symbol(sym)

            if tranche_tag == "CRYPTO":
                qty_str = f"{qty:.4f} units"
                stop_str = f"${entry * 0.96:.4f}" if entry < 10.0 else f"${entry * 0.96:.2f}"
                tp_str = f"${entry * 1.07:.4f}" if entry < 10.0 else f"${entry * 1.07:.2f}"
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

        if section_reports:
            detailed_report += "\n" + "\n\n".join(section_reports) + "\n"

        detailed_report += (
            f"\n🎛️ **Mobile One-Tap Command Deck:**\n"
            f"[🔄 Run Enabled Suite]({DASHBOARD_URL}/?discord_cmd=scan_all)  |  "
            f"[🛰️ Run Discovery]({DASHBOARD_URL}/?discord_cmd=scan_discovery)  |  "
            f"[🪙 Scan Crypto]({DASHBOARD_URL}/?discord_cmd=scan_crypto)  |  "
            f"[📊 Push Snapshot]({DASHBOARD_URL}/?discord_cmd=snapshot)  |  "
            f"[🛑 Liquidate Crypto]({DASHBOARD_URL}/?discord_cmd=liquidate_crypto)"
        )

        send_discord_alert(detailed_report)
    except Exception as e:
        logging.error(f"Detailed portfolio report error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        default=os.environ.get("BOT_MODE", "smart_cron"),
        choices=["auto", "intraday", "all", "core", "momentum", "crypto", "discovery", "mean_rev", "small_cap", "tail_hedge", "commodities", "defense", "predator", "smart_cron"]
    )
    args = parser.parse_args()

    if args.mode == "smart_cron":
        ny_now = datetime.now(ZoneInfo("America/New_York"))
        is_weekday = ny_now.weekday() < 5
        hr = ny_now.hour
        mn = ny_now.minute

        logging.info(f"🕰️ Smart Cron Router Triggered at NY Time: {hr:02d}:{mn:02d}")

        # 1. NYSE Open/Close (9:30-9:45 AM and 3:30-3:59 PM NY Time) -> Runs FULL SUITE
        if is_weekday and ((hr == 9 and 30 <= mn <= 45) or (hr == 15 and mn >= 30)):
            logging.info("➡️ Routing to: AUTO (Full Suite including Core)")
            run_bot(mode="auto")

        # 2. Intraday Market Hours (9:46 AM to 3:29 PM NY Time) -> Runs HIGH-FREQ EQUITIES + CRYPTO
        elif is_weekday and ((hr == 9 and mn > 45) or (10 <= hr <= 14) or (hr == 15 and mn < 30)):
            logging.info("➡️ Routing to: INTRADAY (Equities + Crypto + Discovery + Predator)")
            run_bot(mode="intraday")

        # 3. Overnight & Weekends -> Runs CRYPTO ONLY
        else:
            logging.info("➡️ Routing to: CRYPTO (24/7 Digital Asset Quant)")
            run_bot(mode="crypto")
    else:
        run_bot(mode=args.mode)
