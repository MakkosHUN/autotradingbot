import os
import re
import json
import time
import math
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
discovery_sheet = get_or_create_worksheet(spreadsheet, "Discovery Log", LOG_HEADERS)
closed_sheet = get_or_create_worksheet(
    spreadsheet,
    "Closed Trades",
    ["Closed At (UTC)", "Ticker", "Qty", "Exit Type", "Fill Price", "Order ID", "Engine", "Entry Price", "Realized P/L ($)", "Return (%)"]
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
# --- UPGRADED CRYPTO UNIVERSE (CLEAN YF/ALPACA PAIRS) ---
CRYPTO_MAJORS = ["BTC/USD", "ETH/USD", "SOL/USD", "DOGE/USD"]
CRYPTO_ALTS = [
    "XRP/USD", "AVAX/USD", "LINK/USD", "SHIB/USD",
    "DOT/USD", "LTC/USD", "AAVE/USD", "BCH/USD"
]
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

# --- NEW: MULTI-ASSET DEFENSIVE TRANCHES ---
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
    "COMMODITIES":{"enabled": True, "cap": 0.10, "risk_bps": 0.0035, "desc": "Precious Metals & Energy Hard Assets"},
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
                except Exception:
                    pass
    except Exception as e:
        print(f"Engine config read warning: {e}")
    return cfg

def to_yf_symbol(ticker):
    return ticker.replace("/", "-")

def to_alpaca_pos_symbol(ticker):
    return ticker.replace("/", "")

def classify_symbol(sym):
    s_clean = sym.replace("/", "")
    if sym in TAIL_HEDGE_POOL:
        return "TAIL_HEDGE"
    if sym in CRYPTO_POOL or s_clean in CRYPTO_NORM or sym.endswith("/USD") or sym.endswith("USD"):
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
            print(f"RL Meta-Allocator note: {e}")

    # --- NEW: DEFENSIVE SHIFT BASED ON GEX ---
    if net_gex_score <= -0.15:
        print(f"[RL META] GEX {net_gex_score:.2f} <= -0.15. Shifting capital defensively.")
        if "MOMENTUM" in adjusted_caps: adjusted_caps["MOMENTUM"] = round(max(0.05, adjusted_caps["MOMENTUM"] * 0.5), 3)
        if "SMALL_CAP" in adjusted_caps: adjusted_caps["SMALL_CAP"] = round(max(0.05, adjusted_caps["SMALL_CAP"] * 0.5), 3)
        if "CORE" in adjusted_caps: adjusted_caps["CORE"] = round(max(0.05, adjusted_caps["CORE"] * 0.7), 3)
        
        safe_havens = [k for k in ["COMMODITIES", "DEFENSE", "TAIL_HEDGE"] if k in adjusted_caps]
        for sh in safe_havens:
            adjusted_caps[sh] = round(min(0.50, adjusted_caps[sh] * 1.5), 3)

    print(f"[v8.6 RL META-ALLOCATOR] Dynamic Tranche Caps: {adjusted_caps}")
    return adjusted_caps

# =====================================================================
# 4. v7.0 LEVEL-2 ORDER-BOOK IMBALANCE (OBI) & v8.0 OPTIONS GEX
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
    except Exception:
        pass
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
        if len(spy) >= 2:
            c_now = float(spy['Close'].iloc[-1])
            c_prev = float(spy['Close'].iloc[-2])
            if c_prev > 0 and not pd.isna(c_now) and not pd.isna(c_prev):
                spy_change = (c_now - c_prev) / c_prev

        exps = spy_tk.options
        if exps:
            chain = spy_tk.option_chain(exps[0])
            call_oi = float(chain.calls["openInterest"].fillna(0).sum())
            put_oi = float(chain.puts["openInterest"].fillna(0).sum())
            if (call_oi + put_oi) > 0:
                net_gex_score = round((call_oi - put_oi) / (call_oi + put_oi), 3)
    except Exception as e:
        print(f"GEX/Macro sensor warning: {e}")

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
    discovered_pool = list(DISCOVERY_RADAR_POOL)

    try:
        for scr_name in ["day_gainers", "most_actives"]:
            scr = yf.screen(scr_name)
            quotes = scr.get("quotes", []) if isinstance(scr, dict) else []
            for q in quotes[:15]:
                sym = str(q.get("symbol", "")).strip().upper()
                if sym and sym.isalpha() and len(sym) <= 5 and sym not in known_static and sym not in discovered_pool:
                    discovered_pool.insert(0, sym)
    except Exception:
        pass

    try:
        batch_query = ",".join(discovered_pool[:25])
        alpaca_news = api.get_news(batch_query, limit=40)
        for item in alpaca_news:
            for s in (getattr(item, "symbols", []) or []):
                s_clean = str(s).strip().upper()
                if s_clean and s_clean.isalpha() and len(s_clean) <= 5 and s_clean not in known_static and s_clean not in discovered_pool:
                    discovered_pool.insert(0, s_clean)
    except Exception as e:
        print(f"Discovery news batch note: {e}")

    screened = screen_top_candidates(discovered_pool[:45], top_n=top_n, owned_symbols=owned_symbols, mode="momentum")
    verified = []
    for sym in screened:
        try:
            asset = api.get_asset(sym)
            if getattr(asset, "tradable", False) and getattr(asset, "status", "") == "active":
                verified.append(sym)
        except Exception:
            continue

    print(f"[AI DISCOVERY AGENT] Selected {len(verified)} unconstrained market-wide catalysts: {verified}")
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
# 6. MATHEMATICAL ARBITER MATRIX (FEE-AWARE NET ALPHA FILTER)
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
        tp_adj = 0.75
        rsi_max = 36.0
        composite = round((w_news * finbert_score) + (w_tech * tech_score), 3)
        buy_signal = (rsi <= 33.0 or price <= bb_low * 1.005) and finbert_score > -0.30 and obi_score >= -0.25
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

        # Anti-Churn Crypto Arbiter
        if strategy_mode == "crypto":
            is_crypto_oversold_snipe = (
                (rsi <= 32.0 or price <= bb_low * 1.005)
                and obi_score >= -0.02
                and finbert_score > -0.15
            )
            is_crypto_quiet_breakout = (
                price > ema20
                and 42.0 <= rsi <= 72.0
                and obi_score >= 0.00
                and finbert_score >= 0.00
            )
            if is_crypto_oversold_snipe:
                regime = "CRYPTO-SNIPE"
                composite = round(max(composite, 0.45), 3)
                tp_adj = 0.85
                rsi_max = 75.0
                buy_signal = True
            elif is_crypto_quiet_breakout and not buy_signal:
                regime = "TECH-10/90"
                composite = round(max(composite, 0.35), 3)
                buy_signal = True

        arbiter_exit_reason = None
        if regime == "CRYPTO-SNIPE" and rsi >= 60.0:
            arbiter_exit_reason = f"Crypto Oversold Snapback Target (RSI {rsi:.1f})"
        elif regime == "NEWS-90/10" and finbert_score <= base_exit_max:
            arbiter_exit_reason = f"Arbiter 90/10 News Reversal ({finbert_score:+.3f})"
        elif regime == "TECH-10/90" and rsi >= 74.0 and finbert_score < 0.25:
            arbiter_exit_reason = f"Arbiter 10/90 Tech Overbought Profit-Take (RSI {rsi:.1f})"
        elif regime == "HYBRID-50/50" and composite <= base_exit_max and price < ema9:
            arbiter_exit_reason = f"Arbiter 50/50 Hybrid Breakdown (Comp {composite:+.3f})"

    # --- NEW: Slippage & Fee-Aware Net Alpha Filter ---
    fee_block_reason = None
    fee_hurdle = 0.50 if strategy_mode == "crypto" else 0.20
    if price > 0:
        atr = tech["atr14"]
        expected_alpha_pct = abs(composite) * (atr / price) * 100.0 * 2.0
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

def compute_atr_risk_parity_qty(equity, price, atr, sl_atr_mult, risk_bps=0.0045, max_notional_pct=0.040, is_crypto=False):
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

def check_correlation_and_exposure_guard(candidate, tranche_name, raw_positions, equity, candidate_returns, held_returns_map, dynamic_caps):
    tranche_invested = sum(
        float(p.market_value) for p in raw_positions
        if classify_symbol(CRYPTO_NORM.get(str(p.symbol), str(p.symbol))) == tranche_name
    )
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
# 7. SHARED AI, NEWS & TECHNICAL HELPER FUNCTIONS
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
    except Exception:
        pass

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
    except Exception:
        pass

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
    yf_sym = to_yf_symbol(ticker)
    df = yf.Ticker(yf_sym).history(period="1y")
    if df.empty or len(df) < 25:
        return None
    close = df['Close'].dropna()
    if len(close) < 25:
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
    returns_60d = close.pct_change().dropna().tail(60)

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
        "returns_60d": returns_60d
    }

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
                    filled_time, o.symbol, str(o.filled_qty), order_type,
                    f"${fill_price:.2f}", o.id, engine_tag,
                    f"${entry_est:.2f}" if entry_est > 0 else "N/A",
                    f"${realized_pl:+.2f}", f"{realized_pct:+.2f}%"
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
    strategy_mode="core"
):
    tranche_alerts = []
    scan_lines = []
    rows_to_append = []

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

            should_exit = (score <= exit_score_max) or (arb["arbiter_exit_reason"] is not None and unrealized_pct > 0.005)
            exit_label = arb["arbiter_exit_reason"] or f"Bearish Sentiment ({score:+.3f})"

            if should_exit:
                if not is_nyse_open:
                    decision = f"EXIT QUEUED [{regime_tag}]"
                    action_taken = f"Awaiting NYSE Open ({exit_label})"
                elif pdt_restricted and unrealized_pct > -0.04: # Allow emergency panic sells
    decision = "EXIT BLOCKED (PDT Shield)"
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
                        curr_stop = float(stop_order.stop_price)
                        atr_val = tech['atr14'] if tech else (current_price * 0.02)

                        if unrealized_pct >= 0.060:
                            new_stop = round(max(entry_price * 1.035, current_price - (1.2 * atr_val)), 2)
                            stage_lbl = "Stage-3 Chandelier Trail"
                        elif unrealized_pct >= 0.040:
                            new_stop = round(entry_price * 1.020, 2)
                            stage_lbl = "Stage-2 (+2.0% Profit Lock)"
                        else:
                            new_stop = round(entry_price, 2)
                            stage_lbl = "Stage-1 Break-Even"

                        if new_stop > curr_stop + 0.05:
                            try:
                                api.replace_order(stop_order.id, stop_price=new_stop)
                                action_taken = f"{stage_lbl} Stop -> ${new_stop:.2f}"
                                tranche_alerts.append(f"🛡️ **[{tranche_name}] {stage_lbl.upper()} ({ticker})**: Stop ratcheted `${curr_stop:.2f}` ➔ `${new_stop:.2f}` (`+{unrealized_pct*100:.1f}%` open gain)")
                            except Exception as e:
                                print(f"Chandelier ratchet note for {ticker}: {e}")

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
                    dynamic_caps=dynamic_caps
                )
                if not is_nyse_open:
                    decision = f"BULLISH (Radar | {regime_tag})"
                    action_taken = f"Pre-Market Target @ ~${tech['price']:.2f} (Comp {arb['composite']:+.2f}, OBI {obi:+.2f})" if tech else "Queued Radar"
                elif not macro_ok:
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
                elif require_sma200 and tech['price'] < tech['sma200']:
                    decision = f"BULLISH (Blocked: Below 200-SMA ${tech['sma200']:.2f})"
                elif not require_sma200 and strategy_mode != "mean_rev" and tech['ema20'] < tech['sma50'] and regime_tag != "NEWS-90/10":
                    decision = "BULLISH (Blocked: 20-EMA < 50-SMA)"
                elif tech['rsi14'] > arb["rsi_max"]:
                    decision = f"BULLISH (Blocked: RSI {tech['rsi14']:.1f} > {arb['rsi_max']:.0f})"
                else:
                    price = tech['price']
                    atr = max(tech['atr14'], price * 0.01)
                    qty_to_buy = compute_atr_risk_parity_qty(
                        equity=equity, price=price, atr=atr,
                        sl_atr_mult=sl_atr_mult, risk_bps=risk_bps,
                        max_notional_pct=0.040, is_crypto=False
                    )

                    adj_tp_mult = round(tp_atr_mult * arb["tp_adj"], 2)
                    stop_price = round(price - (sl_atr_mult * atr), 2)
                    target_price = round(price + (adj_tp_mult * atr), 2)

                    try:
                        api.submit_order(
                            symbol=ticker, qty=qty_to_buy, side='buy', type='market', time_in_force='gtc',
                            order_class='bracket',
                            take_profit={'limit_price': target_price},
                            stop_loss={'stop_price': stop_price}
                        )
                        decision = f"BULLISH [{regime_tag}]"
                        action_taken = f"Risk-Parity Bought {qty_to_buy} @ ~${price:.2f} | TP: ${target_price:.2f} ({adj_tp_mult}x ATR), SL: ${stop_price:.2f}"
                        owned_qty = qty_to_buy
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
        print(f"[{tranche_name}] {ticker}: {score:+.3f} | OBI {obi:+.2f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{ticker}** `[{tranche_name} | {regime_tag}]`: FinBERT `{score:+.3f}` | OBI `{obi:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.35)

    if rows_to_append and sheet_ws:
        try:
            sheet_ws.append_rows(rows_to_append)
        except Exception as e:
            print(f"Batch sheet write warning ({tranche_name}): {e}")

    return tranche_alerts, scan_lines

# =====================================================================
# 9. ENGINE 7: v8.0 OPTIONS GEX & INVERSE ETF TAIL-HEDGE OVERLAY
# =====================================================================
def run_tail_hedge_engine(raw_positions, positions_map, active_orders, equity, is_nyse_open, macro_ok, macro_reason, net_gex_score, risk_bps):
    hedge_alerts = []
    hedge_lines = []
    hedge_sym = "SH"
    pos = positions_map.get(hedge_sym)
    owned_qty = float(pos.qty) if pos else 0.0
    tech = get_technicals_and_atr(hedge_sym)
    price = tech["price"] if tech else 12.0

    needs_hedge = (not macro_ok) or (net_gex_score <= -0.18)

    if owned_qty > 0 and macro_ok and net_gex_score > -0.05 and is_nyse_open:
        try:
            cancel_existing_orders_for_ticker(hedge_sym, active_orders)
            api.submit_order(symbol=hedge_sym, qty=owned_qty, side="sell", type="market", time_in_force="gtc")
            hedge_alerts.append(f"🛡️ **[TAIL_HEDGE UNWOUND] Sold {int(owned_qty)} {hedge_sym}**: Macro & GEX normalized (`{macro_reason}`).")
            hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: Unwound hedge as Macro/GEX normalized.")
        except Exception as e:
            print(f"Tail hedge unwind note: {e}")
    elif owned_qty == 0 and needs_hedge and is_nyse_open and tech is not None:
        atr = max(tech["atr14"], price * 0.01)
        qty_to_buy = compute_atr_risk_parity_qty(equity, price, atr, sl_atr_mult=1.2, risk_bps=risk_bps, max_notional_pct=0.05, is_crypto=False)
        try:
            api.submit_order(symbol=hedge_sym, qty=qty_to_buy, side="buy", type="market", time_in_force="gtc")
            hedge_alerts.append(f"🛡️ **[v8.0 TAIL_HEDGE DEPLOYED] Bought {qty_to_buy} {hedge_sym} @ ~${price:.2f}**: Triggered by `{macro_reason}`")
            hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: Deployed {qty_to_buy} sh inverse shield (`{macro_reason}`).")
        except Exception as e:
            print(f"Tail hedge buy note: {e}")
    else:
        status_str = f"Holding {int(owned_qty)} sh Active Shield" if owned_qty > 0 else f"Standby (GEX {net_gex_score:+.2f} Normal)"
        hedge_lines.append(f"• **{hedge_sym}** `[TAIL_HEDGE]`: `{status_str}`")

    return hedge_alerts, hedge_lines

# =====================================================================
# 10. ENGINE 3: 24/7 CRYPTO AI QUANT EXECUTOR (ANTI-CHURN + 4H COOLDOWN)
# =====================================================================
def run_crypto_tranche(crypto_candidates, raw_positions, positions_map, held_returns_map, dynamic_caps, active_orders, closed_orders_24h, equity, macro_ok, macro_reason, risk_bps):
    crypto_alerts = []
    scan_lines = []
    rows_to_append = []

    for pair in crypto_candidates:
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        headlines = get_fresh_dual_news(pair)
        score = get_finbert_sentiment(headlines)
        tech = get_technicals_and_atr(pair)
        obi = get_orderbook_imbalance(pair)
        rsi_val = f"{tech['rsi14']:.1f}" if tech else "N/A"
        arb = compute_arbiter_matrix(score, tech, obi_score=obi, base_buy_min=0.05, base_exit_max=-0.35, strategy_mode="crypto")
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

            dynamic_tp_pct = 0.060 * arb["tp_adj"]
            exit_reason = None
            if unrealized_pct >= dynamic_tp_pct:
                exit_reason = f"Arbiter Take-Profit Hit (+{unrealized_pct*100:.2f}% in {regime_tag})"
            elif unrealized_pct <= -0.030:
                exit_reason = f"Crypto Stop-Loss Hit ({unrealized_pct*100:.2f}%)"
            elif arb["arbiter_exit_reason"] and unrealized_pct > 0.008:
                exit_reason = arb["arbiter_exit_reason"]
            elif score <= -0.35:
                exit_reason = f"Bearish Crypto Catalyst ({score:+.3f})"

            if exit_reason:
                try:
                    cancel_existing_orders_for_ticker(pair, active_orders)
                    # --- FIXED: Use stop_limit with strict offset instead of blind market sell to prevent slippage ---
                    stop_px = round(current_price * 0.992, 8)
                    limit_px = round(current_price * 0.985, 8)
                    sell_order = api.submit_order(
                        symbol=pair, qty=owned_qty, side='sell', type='stop_limit',
                        stop_price=stop_px, limit_price=limit_px, time_in_force='gtc'
                    )
                    decision = f"EXIT [{regime_tag}]"
                    action_taken = f"Stop-Limit Sold {owned_qty:.4f} @ ~${current_price:.2f} ({exit_reason})"
                    if closed_sheet:
                        closed_sheet.append_row([
                            now_str[:19], pair, f"{owned_qty:.4f}", exit_reason[:28],
                            f"${current_price:.2f}", str(getattr(sell_order, 'id', 'CRYPTO_STPLMT')),
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
                elif arb.get("fee_block_reason"):
                    decision = f"BULLISH (Blocked: {arb['fee_block_reason']})"
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
                elif was_crypto_sold_recently(pair, closed_orders_24h, hours=4):
                    decision = "BULLISH (Blocked: 4h Exit Cooldown)"
                elif not corr_ok:
                    decision = f"BULLISH (Blocked: {corr_reason})"
                elif regime_tag != "CRYPTO-SNIPE" and tech["price"] < tech["ema20"]:
                    decision = f"BULLISH (Blocked: Below 20-EMA ${tech['ema20']:.2f})"
                else:
                    price = tech['price']
                    atr = max(tech['atr14'], price * 0.015)
                    qty_to_buy = compute_atr_risk_parity_qty(
                        equity=equity, price=price, atr=atr,
                        sl_atr_mult=1.2, risk_bps=risk_bps,
                        max_notional_pct=0.035, is_crypto=True
                    )
                    dyn_tp = round(6.0 * arb["tp_adj"], 1)

                    if qty_to_buy > 0:
                        try:
                            api.submit_order(
                                symbol=pair, qty=qty_to_buy, side='buy', type='market', time_in_force='gtc'
                            )
                            decision = f"BULLISH [{regime_tag}]"
                            action_taken = f"Risk-Parity Bought {qty_to_buy:.4f} @ ~${price:.2f} ({regime_tag} | OBI {obi:+.2f} | TP +{dyn_tp}%)"
                            owned_qty = qty_to_buy
                            held_returns_map[pair] = tech["returns_60d"]
                            crypto_alerts.append(f"🪙 **[CRYPTO BUY | {regime_tag}] {pair}**: {action_taken} (FinBERT: `{score:+.3f}`, Comp: `{arb['composite']:+.2f}`)")
                        except Exception as e:
                            decision = f"BULLISH [{regime_tag}]"
                            action_taken = f"Crypto Buy Failed: {e}"
            elif tech is not None and score >= 0.15 and tech["price"] < tech["ema20"]:
                decision = f"BULLISH (Blocked: Below 20-EMA ${tech['ema20']:.2f})"
            elif score <= -0.10:
                decision = f"BEARISH (Not Owned | {regime_tag})"
            else:
                decision = f"HOLD [{regime_tag}]"

        row = [now_str, pair, f"{score:+.3f}", decision, action_taken, f"Holding {owned_qty:.4f} units"]
        rows_to_append.append(row)
        print(f"[CRYPTO] {pair}: {score:+.3f} | OBI {obi:+.2f} | {decision} | {action_taken}")
        scan_lines.append(f"• **{pair}** `[{regime_tag}]`: FinBERT `{score:+.3f}` | OBI `{obi:+.2f}` | RSI `{rsi_val}` ➔ `{decision}`")
        time.sleep(0.35)

    if rows_to_append and crypto_sheet:
        try:
            crypto_sheet.append_rows(rows_to_append)
        except Exception as e:
            print(f"Batch sheet write warning (CRYPTO): {e}")

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
    
    # --- FIXED: Check falling-knife velocity / recent momentum to avoid catching free-falling knives ---
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
    predator_bid = cluster_px * (1.0 - flush_discount)
    
    # Risk-Parity Sizing based on a catastrophic hard stop 
    catastrophic_stop = predator_bid - (atr * 1.5)
    stop_dist = predator_bid - catastrophic_stop
    raw_qty = (equity * (risk_bps / 100.0)) / stop_dist
    max_qty = (equity * 0.05) / predator_bid
    qty = max(1, int(min(raw_qty, max_qty)))
    
    # Instant Mean-Reversion Target (Snapback to the broken cluster level)
    snapback_tp = cluster_px * 1.015 
    
    return {
        "Ticker": ticker,
        "Cluster Level": round(cluster_px, 2),
        "Cluster Type": target_cluster["type"],
        "Live Price": round(close, 2),
        "Predator Bid": round(predator_bid, 2),
        "Snapback TP": round(snapback_tp, 2),
        "Hard Stop": round(catastrophic_stop, 2),
        "Qty": qty,
        "Capital Req": round(qty * predator_bid, 2)
    }

def run_predator_tranche(equity, active_orders, positions_map, sheet_ws, risk_bps):
    alerts = []
    lines = []
    rows_to_append = []
    
    pool = CORE_POOL + MOMENTUM_POOL
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    # Batch download for speed and efficiency
    yf_list = [to_yf_symbol(t) for t in pool]
    try:
        data = yf.download(yf_list, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
    except Exception as e:
        print(f"Predator data fetch error: {e}")
        return alerts, lines

    for ticker in pool:
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
                action_taken = f"Armed {trap['Cluster Type']} Trap: Limit Buy {trap['Qty']} @ ${trap['Predator Bid']} | TP ${trap['Snapback TP']}"
                decision = "BULLISH [PREDATOR-FLUSH]"
                alerts.append(f"🩸 **[PREDATOR TRAP ARMED] {ticker}**: {action_taken} (Cluster: `${trap['Cluster Level']}`)")
                lines.append(f"• **{ticker}** `[PREDATOR]`: {action_taken}")
                rows_to_append.append([now_str, ticker, "N/A (Predator)", decision, action_taken, f"Capital Req: ${trap['Capital Req']}"])
                time.sleep(0.35)
            except Exception as e:
                print(f"Predator order failed for {ticker}: {e}")
                
    if rows_to_append and sheet_ws:
        try:
            sheet_ws.append_rows(rows_to_append)
        except Exception as e:
            print(f"Predator sheet write warning: {e}")
            
    return alerts, lines

# =====================================================================
# 11. MASTER ORCHESTRATOR
# =====================================================================
def run_bot(mode="auto"):
    clock = api.get_clock()
    is_nyse_open = bool(clock.is_open)

    # If triggered by fallback schedule while NYSE is closed, only run Crypto
    if mode in ["auto", "intraday"] and not is_nyse_open:
        mode = "crypto"

    account = api.get_account()
    equity = float(account.equity)
    last_equity = float(getattr(account, 'last_equity', equity) or equity)
    daytrade_count = int(getattr(account, 'daytrade_count', 0) or 0)
    pdt_restricted = daytrade_count >= 3

    engine_cfg = load_or_init_engine_config()
    
    macro_ok, macro_reason, net_gex_score = check_macro_gex_and_circuit_breaker(equity, last_equity)
    dynamic_caps = compute_rl_meta_allocation(engine_cfg, net_gex_score)

    def should_run(eng_key):
        if mode == "all":
            return True
        if mode == eng_key.lower():
            return True
        if mode == "intraday":
            return eng_key in ["MOMENTUM", "CRYPTO", "DISCOVERY", "MEAN_REV", "SMALL_CAP", "TAIL_HEDGE", "COMMODITIES", "DEFENSE", "PREDATOR"] and engine_cfg.get(eng_key, {}).get("enabled", False)
        if mode == "auto":
            return engine_cfg.get(eng_key, {}).get("enabled", False)
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
        except Exception:
            pass

    active_orders = fetch_active_and_held_orders()
    since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    closed_orders_24h = api.list_orders(status='closed', after=since_24h, limit=100)

    automated_exit_alerts = sync_recent_closed_sells(closed_orders_24h)
    all_alerts = list(automated_exit_alerts)
    section_reports = []

    if should_run("CRYPTO"):
        print("=== Running Engine 3: 24/7 Crypto AI Quant ===")
        alt_candidates = screen_top_candidates(CRYPTO_ALTS, top_n=4, owned_symbols=owned_symbols, mode="crypto", tranche_name="CRYPTO")
        crypto_candidates = list(dict.fromkeys(CRYPTO_MAJORS + alt_candidates))
        c_alerts, crypto_lines = run_crypto_tranche(
            crypto_candidates, raw_positions, positions_map, held_returns_map, dynamic_caps,
            active_orders, closed_orders_24h, equity, macro_ok, macro_reason, engine_cfg.get("CRYPTO", {}).get("risk_bps", 0.0045)
        )
        all_alerts.extend(c_alerts)
        if crypto_lines:
            section_reports.append("🪙 **Engine 3 — 24/7 Crypto AI (48x/Day):**\n" + "\n".join(crypto_lines))

    if should_run("CORE"):
        print("=== Running Engine 1: Core Long-Term Equities ===")
        core_candidates = screen_top_candidates(CORE_POOL, top_n=8, owned_symbols=owned_symbols, mode="core", tranche_name="CORE")
        core_alerts, core_lines = run_equity_tranche(
            tranche_name="CORE", tickers=core_candidates, sheet_ws=core_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.10, exit_score_max=-0.15,
            sl_atr_mult=1.5, tp_atr_mult=3.5, ratchet_trigger_pct=0.025,
            risk_bps=engine_cfg.get("CORE", {}).get("risk_bps", 0.0050), require_sma200=True, strategy_mode="core"
        )
        all_alerts.extend(core_alerts)
        if core_lines:
            section_reports.append("🛡️ **Engine 1 — Core Blue-Chips:**\n" + "\n".join(core_lines))

    if should_run("MOMENTUM"):
        print("=== Running Engine 2: Short-Term Momentum ===")
        mom_candidates = screen_top_candidates(MOMENTUM_POOL, top_n=6, owned_symbols=owned_symbols, mode="momentum", tranche_name="MOMENTUM")
        mom_alerts, mom_lines = run_equity_tranche(
            tranche_name="MOMENTUM", tickers=mom_candidates, sheet_ws=momentum_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.12,
            sl_atr_mult=1.0, tp_atr_mult=2.0, ratchet_trigger_pct=0.015,
            risk_bps=engine_cfg.get("MOMENTUM", {}).get("risk_bps", 0.0040), require_sma200=False, strategy_mode="momentum"
        )
        all_alerts.extend(mom_alerts)
        if mom_lines:
            section_reports.append("⚡ **Engine 2 — Short-Term Momentum (14x/Day):**\n" + "\n".join(mom_lines))
            
    if should_run("COMMODITIES"):
        print("=== Running Engine: Commodities & Hard Assets ===")
        comm_candidates = screen_top_candidates(COMMODITY_POOL, top_n=3, owned_symbols=owned_symbols, mode="core", tranche_name="COMMODITIES")
        comm_alerts, comm_lines = run_equity_tranche(
            tranche_name="COMMODITIES", tickers=comm_candidates, sheet_ws=core_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.20,
            sl_atr_mult=1.5, tp_atr_mult=3.0, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("COMMODITIES", {}).get("risk_bps", 0.0035), require_sma200=True, strategy_mode="core"
        )
        all_alerts.extend(comm_alerts)
        if comm_lines:
            section_reports.append("🛢️ **Engine — Commodities (Safe Haven):**\n" + "\n".join(comm_lines))

    if should_run("DEFENSE"):
        print("=== Running Engine: Aerospace & Defense ===")
        def_candidates = screen_top_candidates(DEFENSE_POOL, top_n=4, owned_symbols=owned_symbols, mode="core", tranche_name="DEFENSE")
        def_alerts, def_lines = run_equity_tranche(
            tranche_name="DEFENSE", tickers=def_candidates, sheet_ws=core_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.05, exit_score_max=-0.20,
            sl_atr_mult=1.5, tp_atr_mult=3.0, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("DEFENSE", {}).get("risk_bps", 0.0035), require_sma200=True, strategy_mode="core"
        )
        all_alerts.extend(def_alerts)
        if def_lines:
            section_reports.append("🛡️ **Engine — Aerospace & Defense (Safe Haven):**\n" + "\n".join(def_lines))

    if should_run("DISCOVERY"):
        print("=== Running Engine 4: Market-Wide AI Discovery Agent ===")
        disc_candidates = discover_market_wide_catalysts(owned_symbols, top_n=5)
        if disc_candidates:
            disc_alerts, disc_lines = run_equity_tranche(
                tranche_name="DISCOVERY", tickers=disc_candidates, sheet_ws=discovery_sheet,
                raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
                dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
                equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
                is_nyse_open=is_nyse_open, buy_score_min=0.15, exit_score_max=-0.15,
                sl_atr_mult=1.2, tp_atr_mult=2.8, ratchet_trigger_pct=0.020,
                risk_bps=engine_cfg.get("DISCOVERY", {}).get("risk_bps", 0.0035), require_sma200=False, strategy_mode="discovery"
            )
            all_alerts.extend(disc_alerts)
            if disc_lines:
                section_reports.append("🛰️ **Engine 4 — Market-Wide AI Discovery Agent:**\n" + "\n".join(disc_lines))

    if should_run("MEAN_REV"):
        print("=== Running Engine 5: Statistical Mean-Reversion ===")
        mr_candidates = screen_top_candidates(MEAN_REV_POOL, top_n=5, owned_symbols=owned_symbols, mode="mean_rev", tranche_name="MEAN_REV")
        mr_alerts, mr_lines = run_equity_tranche(
            tranche_name="MEAN_REV", tickers=mr_candidates, sheet_ws=discovery_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=-0.10, exit_score_max=-0.30,
            sl_atr_mult=1.0, tp_atr_mult=1.8, ratchet_trigger_pct=0.015,
            risk_bps=engine_cfg.get("MEAN_REV", {}).get("risk_bps", 0.0035), require_sma200=True, strategy_mode="mean_rev"
        )
        all_alerts.extend(mr_alerts)
        if mr_lines:
            section_reports.append("🧲 **Engine 5 — Statistical Mean-Reversion:**\n" + "\n".join(mr_lines))

    if should_run("SMALL_CAP"):
        print("=== Running Engine 6: Small-Cap Speculative Breakouts ===")
        sc_candidates = screen_top_candidates(SMALL_CAP_POOL, top_n=5, owned_symbols=owned_symbols, mode="small_cap", tranche_name="SMALL_CAP")
        sc_alerts, sc_lines = run_equity_tranche(
            tranche_name="SMALL_CAP", tickers=sc_candidates, sheet_ws=discovery_sheet,
            raw_positions=raw_positions, positions_map=positions_map, held_returns_map=held_returns_map,
            dynamic_caps=dynamic_caps, active_orders=active_orders, closed_orders_24h=closed_orders_24h,
            equity=equity, pdt_restricted=pdt_restricted, macro_ok=macro_ok, macro_reason=macro_reason,
            is_nyse_open=is_nyse_open, buy_score_min=0.10, exit_score_max=-0.12,
            sl_atr_mult=1.2, tp_atr_mult=2.5, ratchet_trigger_pct=0.020,
            risk_bps=engine_cfg.get("SMALL_CAP", {}).get("risk_bps", 0.0030), require_sma200=False, strategy_mode="small_cap"
        )
        all_alerts.extend(sc_alerts)
        if sc_lines:
            section_reports.append("🚀 **Engine 6 — Small-Cap Alpha Breakouts:**\n" + "\n".join(sc_lines))

    if should_run("TAIL_HEDGE"):
        print("=== Running Engine 7: v8.0 Options GEX & Tail-Hedge Overlay ===")
        th_alerts, th_lines = run_tail_hedge_engine(
            raw_positions, positions_map, active_orders, equity, is_nyse_open,
            macro_ok, macro_reason, net_gex_score, engine_cfg.get("TAIL_HEDGE", {}).get("risk_bps", 0.0050)
        )
        all_alerts.extend(th_alerts)
        if th_lines:
            section_reports.append("🛡️ **Engine 7 — Options GEX & Tail-Hedge Overlay:**\n" + "\n".join(th_lines))

    if should_run("PREDATOR") and is_nyse_open:
        print("=== Running Engine 8: Liquidity Predator ===")
        pred_alerts, pred_lines = run_predator_tranche(
            equity=equity, active_orders=active_orders, positions_map=positions_map,
            sheet_ws=discovery_sheet, risk_bps=engine_cfg.get("PREDATOR", {}).get("risk_bps", 0.0050)
        )
        all_alerts.extend(pred_alerts)
        if pred_lines:
            section_reports.append("🩸 **Engine 8 — Liquidity Predator (Flush Hunter):**\n" + "\n".join(pred_lines))

    if all_alerts:
        send_discord_alert("🚨 **AETHER QUANT v8.6 Execution Alert (Multi-Asset Suites • RL Defensive Meta • Fee-Aware Arbiter):**\n" + "\n".join(all_alerts))

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
            f"💠 **AETHER QUANT v8.6 OMEGA Telemetry (Multi-Asset Suites • GEX Defensive Meta)**\n"
            f"🕒 **Time (NY):** `{ny_time.strftime('%Y-%m-%d %I:%M %p')}` | 🏦 **NYSE:** `{'OPEN' if is_nyse_open else 'CLOSED (24/7 Radar & Crypto)'}` | 🌍 **Regime:** `{macro_reason}`\n"
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
        print(f"Detailed portfolio report error: {e}")

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

        print(f"🕰️ Smart Cron Router Triggered at NY Time: {hr:02d}:{mn:02d}")

        # 1. NYSE Open/Close (Fires at 9:30-9:45 AM and 3:30-3:45 PM NY Time) -> Runs FULL SUITE
        if is_weekday and ((hr == 9 and 30 <= mn <= 45) or (hr == 15 and 30 <= mn <= 45)):
            print("➡️ Routing to: AUTO (Full Suite including Core)")
            run_bot(mode="auto")

        # 2. Intraday Market Hours (10:00 AM to 3:00 PM NY Time) -> Runs HIGH-FREQ EQUITIES + CRYPTO
        elif is_weekday and ((hr == 9 and mn > 45) or (10 <= hr <= 14) or (hr == 15 and mn < 30) or (hr == 16 and mn == 0)):
            print("➡️ Routing to: INTRADAY (Equities + Crypto + Discovery + Predator, excluding Core)")
            run_bot(mode="intraday")

        # 3. Overnight & Weekends -> Runs CRYPTO ONLY
        else:
            print("➡️ Routing to: CRYPTO (24/7 Digital Asset Quant)")
            run_bot(mode="crypto")
    else:
        run_bot(mode=args.mode)
