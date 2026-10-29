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
    page_title="QUANT V2.0 // Command Center",
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
        padding-top: 1.5rem;
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
        margin-bottom: 20px;
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
</style>
""", unsafe_allow_html=True)

TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'TSLA', 'NVDA', 'JPM', 'WMT', 'JNJ', 'XOM', 'PG', 'CAT', 'DIS']

# =====================================================================
# 2. CREDENTIALS & CONNECTION INITIALIZATION
# =====================================================================
def get_secret(key, default=""):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default

API_KEY = get_secret("APCA_API_KEY_ID")
API_SECRET = get_secret("APCA_API_SECRET_KEY")
GOOGLE_CREDS_RAW = get_secret("GOOGLE_CREDENTIALS")
GITHUB_PAT = get_secret("GITHUB_PAT")
BASE_URL = "https://paper-api.alpaca.markets"

if not API_KEY or not API_SECRET:
    st.error("⚠️ Missing Alpaca API keys in Streamlit Secrets. Add `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` in App Settings -> Secrets.")
    st.stop()

@st.cache_resource
def init_alpaca():
    return tradeapi.REST(API_KEY, API_SECRET, BASE_URL, api_version='v2')

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

def connect_gsheets():
    if not GOOGLE_CREDS_RAW:
        return None, "GOOGLE_CREDENTIALS not found in Streamlit Secrets."
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
# 3. LIVE TELEMETRY FETCHERS (UNPACKED TO AVOID RECURSION)
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
        positions_data.append({
            "symbol": str(p.symbol),
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
        orders_data.append({
            "id": str(o.id),
            "symbol": str(o.symbol),
            "side": str(o.side),
            "type": str(o.type),
            "status": str(o.status),
            "stop_price": float(o.stop_price) if getattr(o, 'stop_price', None) else None,
            "limit_price": float(o.limit_price) if getattr(o, 'limit_price', None) else None
        })

    recent_orders_raw = api.list_orders(status='all', limit=60)
    recent_data = []
    for o in recent_orders_raw:
        recent_data.append({
            "submitted_at": str(o.submitted_at),
            "symbol": str(o.symbol),
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

@st.cache_data(ttl=60)
def fetch_sheet_logs():
    if not spreadsheet:
        return pd.DataFrame(), pd.DataFrame()
    try:
        log_rows = spreadsheet.sheet1.get_all_values()
        if len(log_rows) > 1:
            ncol = len(log_rows[0])
            default_cols = ["Timestamp", "Ticker", "FinBERT Score", "Decision", "Action Taken", "Position Status"]
            # Use header row if valid, otherwise map default column names dynamically
            first_row = [str(c).strip() for c in log_rows[0]]
            if "Ticker" in first_row or "Timestamp" in first_row:
                cols = [c if c else f"Col_{i}" for i, c in enumerate(first_row)]
                data_rows = log_rows[1:]
            else:
                cols = default_cols[:ncol] + [f"Extra_{i}" for i in range(max(0, ncol - len(default_cols)))]
                data_rows = log_rows
            df_log = pd.DataFrame(data_rows, columns=cols)
        else:
            df_log = pd.DataFrame()
    except Exception:
        df_log = pd.DataFrame()

    try:
        closed_ws = spreadsheet.worksheet("Closed Trades")
        closed_rows = closed_ws.get_all_values()
        if len(closed_rows) > 1:
            df_closed = pd.DataFrame(closed_rows[1:], columns=closed_rows[0])
        else:
            df_closed = pd.DataFrame()
    except Exception:
        df_closed = pd.DataFrame()

    return df_log, df_closed

is_open, account, positions, active_orders, recent_orders, port_hist = fetch_alpaca_state()
macro_ok, spy_chg, vix_val = fetch_macro_telemetry()
df_log, df_closed = fetch_sheet_logs()

# =====================================================================
# 4. SIDEBAR COMMAND DECK
# =====================================================================
with st.sidebar:
    st.markdown("## ⚡ COMMAND DECK")
    ny_now = datetime.now(ZoneInfo("America/New_York"))
    st.caption(f"🗽 **NYC Time:** `{ny_now.strftime('%Y-%m-%d %I:%M:%S %p')}`")

    if st.button("🔄 Refresh Live Telemetry", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown("---")
    st.markdown("### 🚀 Remote Bot Trigger")
    st.caption("Fires `.github/workflows/schedule.yml` on GitHub Actions immediately.")
    if st.button("⚡ Trigger FinBERT Scan Now", use_container_width=True):
        if not GITHUB_PAT:
            st.warning("Add `GITHUB_PAT` (Personal Access Token) to Streamlit Secrets to enable 1-click remote triggers.")
        else:
            resp = requests.post(
                "https://api.github.com/repos/MakkosHUN/autotradingbot/actions/workflows/schedule.yml/dispatches",
                headers={"Authorization": f"Bearer {GITHUB_PAT}", "Accept": "application/vnd.github+json"},
                json={"ref": "main"},
                timeout=10
            )
            if resp.status_code == 204:
                st.success("✅ GitHub Action Dispatched! Scan will complete in ~60s.")
            else:
                st.error(f"GitHub API Error ({resp.status_code}): {resp.text}")

    st.markdown("---")
    st.markdown("### 🛡️ System Safeguards")
    daytrades = int(account.get('daytrade_count', 0))
    st.progress(min(daytrades / 3.0, 1.0), text=f"PDT Counter: {daytrades} / 3 Day Trades")
    st.markdown(f"**SPY 24h:** `{spy_chg:+.2f}%`  \n**CBOE VIX:** `{vix_val:.1f}`")

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
# 5. TOP TERMINAL HEADER & KPI CARDS
# =====================================================================
mkt_badge = '<span class="status-pill pill-green">● NYSE OPEN</span>' if is_open else '<span class="status-pill pill-amber">● NYSE CLOSED</span>'
macro_badge = '<span class="status-pill pill-green">🛡️ MACRO NORMAL</span>' if macro_ok else '<span class="status-pill pill-red">⚠️ MACRO CRASH SHIELD</span>'
pdt_badge = f'<span class="status-pill pill-green">PDT: {daytrades}/3 SAFE</span>' if daytrades < 3 else '<span class="status-pill pill-red">PDT LOCKED (3/3)</span>'

st.markdown(f"""
<div class="terminal-header">
    <div>
        <p class="terminal-title">⚡ QUANTITATIVE AI COMMAND CENTER // v2.0</p>
        <p class="terminal-sub">Engine: ProsusAI/FinBERT • Dynamic 14-ATR Brackets • Break-Even Profit Ratchet • Dual-News Feed</p>
    </div>
    <div>
        {mkt_badge}
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
c2.metric("Intraday P/L (NYSE)", f"${day_pl:+,.2f}", f"{day_pl_pct:+.2f}% Today")
c3.metric("Open Unrealized P/L", f"${open_pl:+,.2f}", f"{len(positions)} Active Positions")
c4.metric("Invested Capital", f"${invested:,.2f}", f"{exposure_pct:.1f}% Portfolio Exposure")
c5.metric("Available Cash Reserve", f"${cash:,.2f}", f"{100-exposure_pct:.1f}% Dry Powder")

st.markdown("<br>", unsafe_allow_html=True)

# =====================================================================
# 6. MAIN TABS
# =====================================================================
tab1, tab2, tab3, tab4 = st.tabs([
    "💼 Live Positions & ATR Risk Matrix",
    "📈 Equity Curve & Technical Charts",
    "🧠 FinBERT AI Brain & Sheet Logs",
    "📜 Live Order Book & Fill History"
])

with tab1:
    if not positions:
        st.info("No active positions currently open. Portfolio is 100% in cash.")
    else:
        pos_rows = []
        for p in sorted(positions, key=lambda x: x['market_value'], reverse=True):
            sym = p['symbol']
            qty = int(p['qty'])
            entry = p['avg_entry_price']
            curr = p['current_price']
            mkt_val = p['market_value']
            pl_dlr = p['unrealized_pl']
            pl_pct = ((curr - entry) / entry) * 100.0

            sl_price, tp_price = None, None
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

            shield_status = "🛡️ BREAK-EVEN LOCKED" if (sl_price and sl_price >= entry - 0.01) else ("⚡ +2.5% READY" if pl_pct >= 2.5 else "Active ATR Bracket")

            pos_rows.append({
                "Ticker": sym,
                "Shares": qty,
                "Market Value": mkt_val,
                "Avg Entry": entry,
                "Current Price": curr,
                "Unrealized P/L ($)": pl_dlr,
                "Return (%)": pl_pct,
                "🛑 Stop-Loss": f"${sl_price:.2f}" if sl_price else "None",
                "🎯 Take-Profit": f"${tp_price:.2f}" if tp_price else "None",
                "SL ➔ TP Gauge": range_progress,
                "Profit Shield": shield_status
            })

        df_pos = pd.DataFrame(pos_rows)

        col_table, col_pie = st.columns([2.3, 1])
        with col_table:
            st.subheader("🎯 Active Holdings & Dynamic ATR Brackets")
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
                        help="0% = At Stop-Loss | 100% = At Take-Profit Target",
                        format="%.0f%%",
                        min_value=0,
                        max_value=100
                    )
                }
            )

        with col_pie:
            st.subheader("🧩 Capital Allocation")
            alloc_df = pd.DataFrame({
                "Asset": [r["Ticker"] for r in pos_rows],
                "Value": [r["Market Value"] for r in pos_rows]
            })
            fig_pie = px.pie(
                alloc_df, values="Value", names="Asset", hole=0.62,
                color_discrete_sequence=px.colors.sequential.Tealgrn
            )
            fig_pie.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                margin=dict(t=10, b=10, l=10, r=10), height=320,
                legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5)
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
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=300,
            margin=dict(t=25, b=10, l=10, r=10),
            yaxis=dict(title="Unrealized P/L ($)", gridcolor="rgba(255,255,255,0.06)"),
            xaxis=dict(title="")
        )
        st.plotly_chart(fig_bar, use_container_width=True)

with tab2:
    col_eq, col_chart = st.columns([1, 1.3])
    with col_eq:
        st.subheader("📈 30-Day Portfolio Equity Curve")
        if not port_hist.empty and "equity" in port_hist.columns:
            df_eq = port_hist[port_hist["equity"] > 0].copy()
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=df_eq.index, y=df_eq["equity"], mode="lines+markers",
                line=dict(color="#00FFAA", width=2.5), fill="tozeroy",
                fillcolor="rgba(0, 255, 170, 0.08)", name="Equity"
            ))
            fig_eq.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=420,
                margin=dict(t=15, b=15, l=10, r=10),
                yaxis=dict(title="Account Equity ($)", gridcolor="rgba(255,255,255,0.06)"),
                xaxis=dict(gridcolor="rgba(255,255,255,0.04)")
            )
            st.plotly_chart(fig_eq, use_container_width=True)
        else:
            st.info("Portfolio history curve will populate as daily bars accumulate.")

    with col_chart:
        st.subheader("🔬 Technical Trend Inspector")
        selected_ticker = st.selectbox("Select Universe Ticker:", TICKERS, index=3)
        df_yf = yf.Ticker(selected_ticker).history(period="1y")
        if not df_yf.empty:
            df_yf["SMA200"] = df_yf["Close"].rolling(200).mean()
            df_yf["EMA20"] = df_yf["Close"].ewm(span=20, adjust=False).mean()
            df_plot = df_yf.tail(120)

            fig_candle = go.Figure()
            fig_candle.add_trace(go.Candlestick(
                x=df_plot.index, open=df_plot["Open"], high=df_plot["High"],
                low=df_plot["Low"], close=df_plot["Close"], name=selected_ticker,
                increasing_line_color="#00FFAA", decreasing_line_color="#FF4B4B"
            ))
            fig_candle.add_trace(go.Scatter(x=df_plot.index, y=df_plot["EMA20"], line=dict(color="#38BDF8", width=1.8), name="20-EMA"))
            fig_candle.add_trace(go.Scatter(x=df_plot.index, y=df_plot["SMA200"], line=dict(color="#F59E0B", width=2.2, dash="dot"), name="200-SMA"))
            fig_candle.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=370,
                xaxis_rangeslider_visible=False, margin=dict(t=10, b=10, l=10, r=10),
                yaxis=dict(gridcolor="rgba(255,255,255,0.06)"),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig_candle, use_container_width=True)

with tab3:
    st.subheader("🧠 Latest 12-Stock FinBERT Sentiment Radar")
    if not df_log.empty:
        latest_12 = df_log.tail(12).copy()
        score_col = "FinBERT Score" if "FinBERT Score" in latest_12.columns else latest_12.columns[2]
        ticker_col = "Ticker" if "Ticker" in latest_12.columns else latest_12.columns[1]
        latest_12["Score_Num"] = pd.to_numeric(latest_12[score_col], errors="coerce").fillna(0.0)

        bar_colors = ["#00FFAA" if s >= 0.10 else ("#FF4B4B" if s <= -0.10 else "#64748B") for s in latest_12["Score_Num"]]
        fig_sent = go.Figure(go.Bar(
            x=latest_12[ticker_col], y=latest_12["Score_Num"],
            marker_color=bar_colors, text=latest_12[score_col], textposition="outside"
        ))
        fig_sent.add_hline(y=0.10, line_dash="dash", line_color="#00FFAA", annotation_text="Buy Threshold (+0.10)")
        fig_sent.add_hline(y=-0.15, line_dash="dash", line_color="#FF4B4B", annotation_text="Bearish Exit (-0.15)")
        fig_sent.update_layout(
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(17,22,34,0.5)", height=310,
            margin=dict(t=20, b=10, l=10, r=10),
            yaxis=dict(title="Net FinBERT Score (-1 to +1)", range=[-0.6, 0.9], gridcolor="rgba(255,255,255,0.06)")
        )
        st.plotly_chart(fig_sent, use_container_width=True)

        col_l1, col_l2 = st.columns([1.6, 1])
        with col_l1:
            st.markdown("#### 📋 Auto-Trading Bot Log")
            st.dataframe(df_log.iloc[::-1].head(100), use_container_width=True, hide_index=True)
        with col_l2:
            st.markdown("#### 🏆 Automated Exits (`Closed Trades`)")
            if not df_closed.empty:
                st.dataframe(df_closed.iloc[::-1], use_container_width=True, hide_index=True)
            else:
                st.info("No closed bracket exits logged yet.")
    else:
        if spreadsheet:
            st.info("✅ Connected to Google Sheet `Auto-Trading Bot Log`, but it currently has 0 data rows. It will populate automatically on the next market-open scan!")
        else:
            st.warning(f"⚠️ Google Sheets Connection Status: `{sheet_status}`")

with tab4:
    st.subheader("📜 Alpaca Order Book")
    if recent_orders:
        df_orders = pd.DataFrame(recent_orders)
        st.dataframe(df_orders, use_container_width=True, hide_index=True)
    else:
        st.info("No recent orders found.")
