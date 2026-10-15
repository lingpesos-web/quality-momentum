import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import email.utils
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Quality Momentum & TCT Cockpit",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZE SESSION STATE ---
if "inspect_symbol" not in st.session_state:
    st.session_state.inspect_symbol = None
if "screener_matches" not in st.session_state:
    st.session_state.screener_matches = None
if "alerted_states" not in st.session_state:
    st.session_state.alerted_states = {}

def clear_inspection():
    st.session_state.inspect_symbol = None

# --- NTFY ALERT ENGINE ---
def send_ntfy_alert(message, title="Momentum & TCT Alert"):
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/2026_USstockspicks",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

# --- CUSTOM CSS: MANUS EDITORIAL THEME ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600;700&display=swap');

.stApp {
    background-color: #fbf9f4 !important;
    color: #1a1a1a !important;
    font-family: 'Inter', sans-serif;
}
[data-testid="stSidebar"] {
    background-color: #0f291e !important;
    border-right: 1px solid #1c3d2f;
}
[data-testid="stSidebar"] * {
    color: #e2e8f0 !important;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label {
    padding: 8px 12px;
    border-radius: 6px;
    margin-bottom: 4px;
    transition: all 0.2s;
}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover {
    background-color: #183d2e;
}
h1, h2, h3 {
    font-family: 'Newsreader', Georgia, serif !important;
    font-weight: 600 !important;
    color: #0f291e !important;
}
.macro-container {
    display: flex;
    flex-wrap: nowrap;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 8px;
    margin-bottom: 16px;
}
.macro-card {
    flex: 1 1 0px;
    min-width: 105px;
    background: #ffffff;
    border: 1px solid #e7e2d9;
    border-radius: 8px;
    padding: 8px 6px;
    text-align: center;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
}
.macro-title {
    font-size: 0.68rem;
    color: #71717a;
    text-transform: uppercase;
    font-weight: 700;
    letter-spacing: 0.04em;
    white-space: nowrap;
}
.macro-price {
    font-size: 0.88rem;
    font-weight: 700;
    color: #18181b;
    margin: 2px 0;
    white-space: nowrap;
}
.tick-pos { color: #15803d; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.tick-neg { color: #b91c1c; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.stock-card {
    background: #ffffff;
    border: 1px solid #e7e2d9;
    border-radius: 10px;
    padding: 16px;
    margin-bottom: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.70rem;
    font-weight: 600;
    text-transform: uppercase;
}
.badge-breakout { background: #dcfce7; color: #15803d; }
.badge-trend { background: #dbeafe; color: #1d4ed8; }
.badge-candidate { background: #fef9c3; color: #a16207; }
.badge-caution { background: #fee2e2; color: #b91c1c; }
.badge-tct-buy { background: #15803d; color: #ffffff; }
.badge-tct-watch { background: #fef08a; color: #854d0e; border: 1px solid #fde047; }
.badge-tct-sell { background: #b91c1c; color: #ffffff; }
.pill {
    display: inline-flex;
    align-items: center;
    background: #e9e4db;
    color: #0f291e;
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 6px;
    margin-bottom: 6px;
}
.scroll-news-box {
    max-height: 540px;
    overflow-y: auto;
    padding-right: 6px;
}
.scroll-news-box::-webkit-scrollbar {
    width: 6px;
}
.scroll-news-box::-webkit-scrollbar-thumb {
    background: #d1d5db;
    border-radius: 4px;
}
.ticker-news-badge {
    background: #dcfce7;
    color: #15803d;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 0.7rem;
    margin-right: 6px;
}
.trade-ticket {
    background: #f8f6f0;
    border: 1px solid #e2ddd2;
    border-radius: 8px;
    padding: 10px 12px;
    margin-top: 10px;
    font-size: 0.80rem;
}
</style>
""", unsafe_allow_html=True)

# --- FILE PERSISTENCE ---
DATA_FILE = "watchlists.json"
SETTINGS_FILE = "settings.json"

DEFAULT_WATCHLISTS = {
    "Active Portfolio": [
        "SLV", "VRT", "COHR", "SKHY", "SNDK", "MU", "DRAM", "HOOD", "SOFI",
        "PLTR", "GLW", "LRCX", "MRVL", "CLS", "CRCL", "LITE", "ADPT", "SPCX",
        "STX", "WDC", "TEM", "IREN", "CBRS", "CDE", "SOXL", "IONQ", "QUBT",
        "AMD", "APP", "COIN", "MSTR", "CRDO", "NVDA"
    ],
    "Opportunity Radar": [
        "PLTR", "MU", "HOOD", "LRCX", "UGL", "SOFI", "MRVL", "AVGO", "COST"
    ]
}

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

watchlists = load_json(DATA_FILE, DEFAULT_WATCHLISTS)

settings = load_json(SETTINGS_FILE, {
    "w_fund": 40, "w_tech": 40, "w_mom": 20,
    "account_size": 100000,
    "news_limit": 60,
    "alert_breakout": True, "alert_support": True, "alert_earnings": True,
    "email": "cashmiles@gmail.com"
})
if "account_size" not in settings:
    settings["account_size"] = 100000
if "news_limit" not in settings:
    settings["news_limit"] = 60

# --- UNIVERSE DEFINITION ---
GICS_SECTORS = {
    "Information Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "AMAT", "LRCX", "MU", "PANW", "CRWD", "CRDO", "VRT", "COHR", "SNDK", "GLW", "CLS", "LITE", "STX", "WDC", "IONQ", "QUBT", "APP"],
    "Communication Services": ["GOOGL", "META", "NFLX", "TMUS", "CMCSA", "DIS", "CHTR"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG", "LULU", "EBAY"],
    "Consumer Staples": ["WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ", "KDP"],
    "Health Care": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "AMGN", "GILD", "ISRG", "VRTX", "ADPT", "TEM"],
    "Financials": ["JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "AXP", "BLK", "HOOD", "SOFI", "COIN", "MSTR", "CRCL"],
    "Industrials": ["GE", "CAT", "UNP", "HON", "BA", "RTX", "DE", "LMT", "ADP", "FAST", "IREN"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "BKR"],
    "Materials": ["LIN", "SHW", "FCX", "NEM", "APD", "ECL", "CDE", "SLV"],
    "Utilities": ["NEE", "SO", "DUK", "CEG", "AEP", "EXC"],
    "Real Estate": ["PLD", "AMT", "EQIX", "PSA", "O"]
}

# --- HIGH-CAPACITY CHRONOLOGICAL GOOGLE NEWS RSS ENGINE ---
def parse_pub_date(date_str):
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)

def _fetch_rss_raw(query, max_per_query=20, ticker_tag=None):
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    articles = []
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:max_per_query]:
            raw_title = item.find("title").text if item.find("title") is not None else "Financial Update"
            link = item.find("link").text if item.find("link") is not None else "#"
            pub_date_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"
            
            clean_title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            dt_obj = parse_pub_date(pub_date_raw)
            formatted_date = dt_obj.strftime("%b %d, %Y · %H:%M") if dt_obj.year > 1900 else pub_date_raw[:16]
            
            articles.append({
                "title": clean_title,
                "link": link,
                "publisher": source,
                "date": formatted_date,
                "timestamp": dt_obj.timestamp(),
                "ticker": ticker_tag or "MARKET"
            })
    except Exception:
        pass
    return articles

@st.cache_data(ttl=600)
def fetch_google_news_rss(query, max_items=60):
    # Combines multiple macro queries in parallel so the user gets 50+ stories instead of 12
    queries = [
        query,
        "S&P 500 Nasdaq stock market today",
        "Wall Street stocks earnings Federal Reserve",
        "US tech stocks semiconductors market news"
    ]
    pool = []
    seen_links = set()
    seen_titles = set()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_rss_raw, q, 25, "MARKET") for q in queries]
        for fut in futures:
            for item in fut.result():
                if item["link"] not in seen_links and item["title"] not in seen_titles:
                    seen_links.add(item["link"])
                    seen_titles.add(item["title"])
                    pool.append(item)
    pool = sorted(pool, key=lambda x: x["timestamp"], reverse=True)
    return pool[:max_items]

@st.cache_data(ttl=600)
def fetch_watchlist_news_pool(tickers, max_items=60):
    if not tickers:
        return []
    pool = []
    seen_links = set()
    seen_titles = set()
    # Fetch across ALL watchlist tickers in parallel (no more [:8] truncation!)
    unique_tickers = list(dict.fromkeys(tickers))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_rss_raw, f"{sym} stock when:7d", 4, sym): sym for sym in unique_tickers}
        for fut in futures:
            for item in fut.result():
                if item["link"] not in seen_links and item["title"] not in seen_titles:
                    seen_links.add(item["link"])
                    seen_titles.add(item["title"])
                    pool.append(item)
    pool = sorted(pool, key=lambda x: x["timestamp"], reverse=True)
    return pool[:max_items]


# --- TCT ACCUMULATION STRATEGY ENGINE (RULES HANDBOOK) ---
def analyze_tct_strategy(df, account_size=100000):
    """
    Implements the TCT Accumulation Strategy rules from the handbook:
    - Candle coloring by previous close (green = Close > prior Close)
    - Swing points (k = 3 on each side, confirmed after 3rd bar closes)
    - Tap 1, Sweep & Tap 2, Range High, 25-bar slow decline check, vertical flush filter
    - Tap 3 & Break of Structure (BOS) entry, Stop-Loss, Range High Target, 2R & 2% stop admission filters
    - 0.5% Account Risk Share Calculator
    """
    n = len(df)
    close_arr = df["Close"].values.astype(float)
    high_arr = df["High"].values.astype(float)
    low_arr = df["Low"].values.astype(float)
    vol_arr = df["Volume"].values.astype(float)
    curr_close = float(close_arr[-1])

    # 1. Liquidity Check: 20D Median Daily Dollar Volume >= $50M
    dollar_vol_20 = pd.Series(close_arr[-20:] * vol_arr[-20:]).median() if n >= 20 else 0.0
    liq_pass = bool(dollar_vol_20 >= 50_000_000)

    # 2. ATR(14) & 1H ATR Approximation for Stop Calculation
    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"] - df["Close"].shift(1)).abs()
    atr14_daily = float(pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
    if np.isnan(atr14_daily) or atr14_daily <= 0:
        atr14_daily = curr_close * 0.025
    atr14_1h_est = atr14_daily / 2.55  # 6.5 regular trading hours per day

    # 3. Confirmed Swing Points (k = 3, known only after 3rd bar after it has closed)
    swing_highs = []  # (idx, price)
    swing_lows = []   # (idx, price)
    for i in range(3, n - 3):
        if high_arr[i] == np.max(high_arr[i - 3:i + 4]):
            swing_highs.append((i, float(high_arr[i])))
        if low_arr[i] == np.min(low_arr[i - 3:i + 4]):
            swing_lows.append((i, float(low_arr[i])))

    # 4. Scan recent history (last 140 bars) for a TCT Accumulation Range (Tap 1 -> Range High -> Tap 2 Sweep -> Push-Up -> Tap 3)
    lookback = min(n, 140)
    start_idx = n - lookback

    # Peak before decline
    peak_rel_idx = int(np.argmax(high_arr[start_idx:max(start_idx + 1, n - 15)]))
    peak_idx = start_idx + peak_rel_idx
    peak_price = float(high_arr[peak_idx])

    # Candidate Tap 1 & Tap 2 in the aftermath of the peak
    recent_lows = [(idx, val) for idx, val in swing_lows if idx > peak_idx]

    tct_valid_range = False
    slow_decline_25 = False
    no_vertical_flush = True
    tap1_price, tap2_price, tap3_price = None, None, None
    range_high, bos_level = None, None
    tct_model = "None"

    if len(recent_lows) >= 2:
        # Try finding Tap 1 and a Tap 2 that sweeps or tests Tap 1 at least 2 bars later
        for i_l in range(len(recent_lows) - 1):
            t1_idx, t1_val = recent_lows[i_l]
            for j_l in range(i_l + 1, len(recent_lows)):
                t2_idx, t2_val = recent_lows[j_l]
                if t2_idx - t1_idx < 2:
                    continue
                r_high = float(np.max(high_arr[t1_idx:t2_idx + 1]))
                if r_high <= t1_val * 1.02:
                    continue
                # Check Sweep (Tap 2 trades below or near Tap 1, and doesn't close below 30% deviation)
                dev_limit = t1_val - 0.30 * (r_high - t1_val)
                min_close_t2 = float(np.min(close_arr[t1_idx:t2_idx + 1]))
                if t2_val <= t1_val * 1.015 and min_close_t2 >= dev_limit:
                    tap1_price = t1_val
                    tap2_price = t2_val
                    range_high = r_high
                    # Check 25-bar slow decline rule from peak/high to Tap 2
                    bars_decline = t2_idx - peak_idx
                    slow_decline_25 = bool(bars_decline >= 25)
                    # Check single-bar vertical flush filter (80% to 22% of range in 1 bar)
                    rng_span = max(range_high - tap1_price, 1e-6)
                    for b_i in range(t1_idx, t2_idx + 1):
                        bar_top_pct = (high_arr[b_i] - tap1_price) / rng_span
                        bar_bot_pct = (low_arr[b_i] - tap1_price) / rng_span
                        if bar_top_pct >= 0.80 and bar_bot_pct <= 0.22:
                            no_vertical_flush = False
                    # Find Push-Up & Tap 3 after Tap 2
                    post_t2_highs = [(idx, val) for idx, val in swing_highs if idx > t2_idx]
                    if post_t2_highs:
                        push_idx, push_val = post_t2_highs[0]
                        if push_val > tap1_price and t2_idx + 3 < n:
                            # Tap 3 is lowest low after push-up window opens
                            win_start = min(push_idx + 3, n - 1)
                            tap3_price = float(np.min(low_arr[win_start:]))
                            if tap3_price < tap2_price:
                                tct_model = "Model 1 (Tap 2 Sweep)"
                            else:
                                tct_model = "Model 2 (Higher Low / OB)"
                            # BOS is the last lower swing high before Tap 3 (or push-up high)
                            bos_candidates = [val for idx, val in swing_highs if idx >= push_idx and val < range_high]
                            bos_level = float(bos_candidates[-1]) if bos_candidates else float(push_val)
                            # Check range not dead or already completed in the past
                            death_low = tap2_price - 0.30 * (range_high - tap2_price)
                            if curr_close >= death_low and curr_close <= range_high * 1.03:
                                tct_valid_range = True
                    break
            if tct_valid_range:
                break

    # 5. Fallback Structural Box if Stock is not in a Strict TCT Range (so user ALWAYS has Buy/Target/Stop)
    recent_20_high = float(np.max(high_arr[-21:-1])) if n >= 22 else float(np.max(high_arr[-10:]))
    recent_20_low = float(np.min(low_arr[-20:]))
    high_52w = float(np.max(high_arr[-252:])) if n >= 252 else float(np.max(high_arr))

    if not tct_valid_range or range_high is None or bos_level is None or tap3_price is None:
        # Construct practical structural range levels
        tap1_price = float(np.min(low_arr[-40:-15])) if n >= 45 else recent_20_low
        tap2_price = recent_20_low
        tap3_price = float(np.min(low_arr[-10:]))
        range_high = float(np.max(high_arr[-60:])) if n >= 60 else high_52w
        # Last short-term swing high as BOS trigger
        recent_sh = [val for idx, val in swing_highs if idx >= n - 25]
        bos_level = float(recent_sh[-1]) if recent_sh else recent_20_high
        if range_high <= bos_level * 1.03:
            # Reaccumulation / Breakout projection target
            range_high = max(high_52w, curr_close + (2.5 * atr14_daily))

    # 6. Calculate Stop, Target, Entry, R-Multiple & 0.5% Account Risk Share Size (Handbook Sec 6, 7, 8)
    raw_stop = tap3_price - (0.5 * atr14_1h_est)
    entry_ref = curr_close if curr_close >= bos_level else bos_level

    # Handbook Sec 7: Stop must be at least 2% below entry
    stop_dist_pct = (entry_ref - raw_stop) / entry_ref if entry_ref > 0 else 0.02
    stop_2pct_pass = bool(stop_dist_pct >= 0.02)
    effective_stop = raw_stop if stop_2pct_pass else (entry_ref * 0.98)

    # Handbook Sec 6: Reaccumulation at a 12-month peak check
    target_price = range_high
    if target_price <= entry_ref * 1.01:
        target_price = entry_ref + max(2.2 * (entry_ref - effective_stop), 2.0 * atr14_daily)

    risk_per_share = max(entry_ref - effective_stop, 0.01)
    reward_per_share = max(target_price - entry_ref, 0.0)
    r_multiple = reward_per_share / risk_per_share

    # Handbook Sec 8: Risk 0.5% of account per trade
    risk_dollars = account_size * 0.005
    suggested_shares = max(1, int(risk_dollars / risk_per_share))
    position_value = suggested_shares * entry_ref
    target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
    stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0

    # 7. Determine Plain-English Action Signal
    prev_close = float(close_arr[-2]) if n >= 2 else curr_close
    ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])

    just_crossed_bos = (curr_close >= bos_level) and (prev_close < bos_level * 1.015)

    if curr_close <= effective_stop or curr_close < ema50 * 0.985:
        action_signal = "SELL / EXIT"
        action_badge = "badge-tct-sell"
        action_explain = f"Price violated safety support (${effective_stop:.2f}). Step aside or exit."
        action_priority = 4
    elif curr_close >= target_price * 0.995:
        action_signal = "TAKE PROFIT (TARGET HIT)"
        action_badge = "badge-tct-sell"
        action_explain = f"Reached Range High target zone (${target_price:.2f}). Lock in gains."
        action_priority = 3
    elif (tct_valid_range and curr_close >= bos_level and r_multiple >= 1.8) or (just_crossed_bos and r_multiple >= 2.0):
        action_signal = "BUY NOW (BOS TRIGGERED)"
        action_badge = "badge-tct-buy"
        action_explain = f"Broke above BOS (${bos_level:.2f}) with {r_multiple:.1f}R reward-to-risk."
        action_priority = 0
    elif tct_valid_range and curr_close < bos_level:
        action_signal = "WATCHING BOX (WAIT FOR BOS)"
        action_badge = "badge-tct-watch"
        action_explain = f"In TCT accumulation box. Wait for close above BOS ${bos_level:.2f} to buy."
        action_priority = 1
    elif curr_close > ema50 and curr_close >= bos_level:
        action_signal = "HOLD / RIDE TREND"
        action_badge = "badge-trend"
        action_explain = f"Holding above support. Trail stop at ${effective_stop:.2f}, target ${target_price:.2f}."
        action_priority = 2
    else:
        action_signal = "WAIT (CONSOLIDATING)"
        action_badge = "badge-candidate"
        action_explain = f"Wait for breakout above ${bos_level:.2f} before entering."
        action_priority = 2

    return {
        "TCT_Valid_Range": tct_valid_range,
        "TCT_Model": tct_model if tct_valid_range else "Structure Levels",
        "TCT_Slow_25": slow_decline_25 and no_vertical_flush,
        "TCT_Liq_50M": liq_pass,
        "TCT_2R_Pass": bool(r_multiple >= 2.0),
        "TCT_Action": action_signal,
        "TCT_Badge": action_badge,
        "TCT_Explain": action_explain,
        "TCT_Priority": action_priority,
        "BOS_Entry": entry_ref,
        "BOS_Level": bos_level,
        "Target_Price": target_price,
        "Stop_Price": effective_stop,
        "Tap1": tap1_price,
        "Tap2": tap2_price,
        "Tap3": tap3_price,
        "R_Multiple": r_multiple,
        "Target_Pct": target_gain_pct,
        "Stop_Pct": stop_loss_pct,
        "Shares_05Pct": suggested_shares,
        "Pos_Value": position_value,
        "Dollar_Vol_M": dollar_vol_20 / 1e6
    }


# --- DATA ENGINE 1: BATCH INGESTION ---
@st.cache_data(ttl=900)
def fetch_batch_market_data(tickers, account_size=100000):
    if not tickers:
        return {}
    results = {}
    try:
        data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False)
    except Exception:
        return {}

    w_fund = settings["w_fund"] / 100.0
    w_tech = settings["w_tech"] / 100.0
    w_mom = settings["w_mom"] / 100.0

    for t in tickers:
        try:
            if len(tickers) == 1:
                df = data.copy()
            else:
                if t in data.columns.levels[0]:
                    df = data[t].copy()
                else:
                    continue

            df.dropna(inplace=True)
            if len(df) < 40:
                continue

            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            change = close - prev_close
            change_pct = (change / prev_close) * 100

            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
            df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
            df["High20"] = df["High"].rolling(20).max()
            df["High52"] = df["High"].rolling(252, min_periods=40).max()
            df["Vol20"] = df["Volume"].rolling(20).mean()

            df["BB_Mid"] = df["Close"].rolling(20).mean()
            df["BB_Std"] = df["Close"].rolling(20).std()
            df["BB_Upper"] = df["BB_Mid"] + (df["BB_Std"] * 2)
            df["BB_Lower"] = df["BB_Mid"] - (df["BB_Std"] * 2)

            delta = df["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            rs = gain / (loss + 1e-9)
            df["RSI"] = 100 - (100 / (1 + rs))
            rsi = float(df["RSI"].iloc[-1])

            ema12 = df["Close"].ewm(span=12, adjust=False).mean()
            ema26 = df["Close"].ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
            df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
            macd_above_zero = float(df["MACD"].iloc[-1]) > 0
            macd_cross = float(df["MACD"].iloc[-1]) > float(df["MACD_Signal"].iloc[-1])

            low14 = df["Low"].rolling(14).min()
            high14 = df["High"].rolling(14).max()
            df["%K"] = ((df["Close"] - low14) / (high14 - low14 + 1e-9)) * 100
            df["%D"] = df["%K"].rolling(3).mean()
            stoch_bullish = float(df["%K"].iloc[-1]) > float(df["%D"].iloc[-1])

            tr1 = df["High"] - df["Low"]
            tr2 = (df["High"] - df["Close"].shift(1)).abs()
            tr3 = (df["Low"] - df["Close"].shift(1)).abs()
            tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
            atr = tr.rolling(14).mean()
            up_move = df["High"] - df["High"].shift(1)
            down_move = df["Low"].shift(1) - df["Low"]
            pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
            neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
            pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(14).mean() / (atr + 1e-9))
            neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(14).mean() / (atr + 1e-9))
            dx = 100 * ((pos_di - neg_di).abs() / (pos_di + neg_di + 1e-9))
            adx = float(dx.rolling(14).mean().iloc[-1]) if len(dx) >= 28 else 20.0

            obv_diff = np.where(df["Close"] > df["Close"].shift(1), df["Volume"],
                       np.where(df["Close"] < df["Close"].shift(1), -df["Volume"], 0))
            df["OBV"] = pd.Series(obv_diff, index=df.index).cumsum()
            obv_rising = float(df["OBV"].iloc[-1]) > float(df["OBV"].rolling(10).mean().iloc[-1])

            vol20 = float(df["Vol20"].iloc[-1])
            rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
            high20_prev = float(df["High20"].iloc[-2]) if len(df) >= 22 else close
            is_breakout = (close >= high20_prev) and (rvol >= 1.4)
            bb_upper_break = close >= float(df["BB_Upper"].iloc[-1])
            bb_lower_touch = float(df["Low"].iloc[-1]) <= float(df["BB_Lower"].iloc[-1])
            ema50_val = float(df["EMA50"].iloc[-1])
            pullback_ema50 = abs(close - ema50_val) / ema50_val <= 0.02
            above_ema50 = close > ema50_val
            above_ema200 = close > float(df["EMA200"].iloc[-1]) if len(df) >= 200 else True
            within_52w = (close / float(df["High52"].iloc[-1])) >= 0.90

            if is_breakout and above_ema50:
                state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Closed above 20D high (${high20_prev:.2f}) with {rvol:.1f}x volume"
            elif above_ema50 and close > float(df["EMA20"].iloc[-1]):
                state, badge_class, reason = "Active Trend", "badge-trend", "Holding steadily above 20-day & 50-day EMA support"
            elif close < ema50_val:
                state, badge_class, reason = "Support Break", "badge-caution", "Violated 50-day EMA support level"
            else:
                state, badge_class, reason = "Entry Candidate", "badge-candidate", "Consolidating below resistance; setup developing"

            tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 10) + (30 if rvol >= 1.2 else 10)
            mom_score = (50 if is_breakout else 15) + (50 if within_52w else 20)
            fund_score = 80
            composite = int((fund_score * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))

            # Run TCT Handbook Analysis
            tct_info = analyze_tct_strategy(df, account_size=account_size)

            record = {
                "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
                "RSI": rsi, "RVOL": rvol, "ADX": adx, "MACD_Above_Zero": macd_above_zero,
                "MACD_Cross": macd_cross, "Stoch_Bullish": stoch_bullish, "OBV_Rising": obv_rising,
                "Above_EMA50": above_ema50, "Above_EMA200": above_ema200, "Is_Breakout": is_breakout,
                "BB_Upper_Break": bb_upper_break, "BB_Lower_Touch": bb_lower_touch,
                "Pullback_EMA50": pullback_ema50, "Within_52W": within_52w,
                "State": state, "Badge": badge_class, "Reason": reason, "Score": composite,
                "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
            }
            record.update(tct_info)
            results[t] = record
        except Exception:
            continue
    return results


# --- DATA ENGINE 2: ISOLATED SINGLE-TICKER ENGINE ---
@st.cache_data(ttl=300)
def fetch_single_ticker_data(sym, account_size=100000):
    try:
        t = yf.Ticker(sym)
        df = t.history(period="1y")
        if df.empty or len(df) < 20:
            return None

        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
        change = close - prev_close
        change_pct = (change / prev_close) * 100 if prev_close != 0 else 0

        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df["Vol20"] = df["Volume"].rolling(20).mean()

        df["BB_Mid"] = df["Close"].rolling(20).mean()
        df["BB_Std"] = df["Close"].rolling(20).std()
        df["BB_Upper"] = df["BB_Mid"] + (df["BB_Std"] * 2)
        df["BB_Lower"] = df["BB_Mid"] - (df["BB_Std"] * 2)

        delta = df["Close"].diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["RSI"] = 100 - (100 / (1 + rs))
        rsi = float(df["RSI"].iloc[-1]) if not np.isnan(df["RSI"].iloc[-1]) else 50.0

        ema12 = df["Close"].ewm(span=12, adjust=False).mean()
        ema26 = df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD"] = ema12 - ema26
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

        vol20 = float(df["Vol20"].iloc[-1]) if float(df["Vol20"].iloc[-1]) > 0 else 1.0
        rvol = float(df["Volume"].iloc[-1]) / vol20
        high20_prev = float(df["High"].rolling(20).max().iloc[-2]) if len(df) >= 22 else close
        is_breakout = (close >= high20_prev) and (rvol >= 1.4)
        above_ema50 = close > float(df["EMA50"].iloc[-1])

        if is_breakout and above_ema50:
            state, badge_class = "Confirmed Breakout", "badge-breakout"
            reason = f"Closed above 20D high (${high20_prev:.2f}) with {rvol:.1f}x volume"
        elif above_ema50 and close > float(df["EMA20"].iloc[-1]):
            state, badge_class = "Active Trend", "badge-trend"
            reason = "Holding steadily above 20-day & 50-day EMA support"
        elif close < float(df["EMA50"].iloc[-1]):
            state, badge_class = "Support Break", "badge-caution"
            reason = "Violated 50-day EMA support level"
        else:
            state, badge_class = "Entry Candidate", "badge-candidate"
            reason = "Consolidating below resistance; setup developing"

        w_fund = settings["w_fund"] / 100.0
        w_tech = settings["w_tech"] / 100.0
        w_mom = settings["w_mom"] / 100.0
        tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 10) + (30 if rvol >= 1.2 else 10)
        mom_score = (50 if is_breakout else 15) + (50 if close >= float(df["High"].rolling(50, min_periods=20).max().iloc[-2]) else 20)
        fund_score = 80
        composite = int((fund_score * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))

        tct_info = analyze_tct_strategy(df, account_size=account_size)

        rec = {
            "Ticker": sym, "Price": close, "Change": change, "Change_Pct": change_pct,
            "RSI": rsi, "RVOL": rvol, "State": state, "Badge": badge_class,
            "Reason": reason, "Score": composite, "History": df
        }
        rec.update(tct_info)
        return rec
    except Exception:
        return None


# --- RESILIENT FUNDAMENTALS WITH FAST_INFO FALLBACK & 24H CACHE ---
@st.cache_data(ttl=86400)
def fetch_ticker_fundamentals(ticker_symbol):
    data = {
        "Market Cap": "N/A", "Trailing P/E": "N/A", "Forward P/E": "N/A",
        "EPS (TTM)": "N/A", "Target Price": "N/A", "52W High": "N/A",
        "52W Low": "N/A", "Debt/Equity": "N/A",
        "Business Summary": "No corporate overview provided."
    }
    try:
        t = yf.Ticker(ticker_symbol)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}

        fast = getattr(t, "fast_info", None)

        mcap = info.get("marketCap")
        if not mcap and fast:
            mcap = getattr(fast, "market_cap", None)
        data["Market Cap"] = mcap if mcap else "N/A"

        data["Trailing P/E"] = info.get("trailingPE") or info.get("trailingPe") or "N/A"
        data["Forward P/E"] = info.get("forwardPE") or info.get("forwardPe") or "N/A"
        data["EPS (TTM)"] = info.get("trailingEps") or "N/A"
        data["Target Price"] = info.get("targetMeanPrice") or "N/A"

        hi = info.get("fiftyTwoWeekHigh")
        if not hi and fast:
            hi = getattr(fast, "year_high", None)
        data["52W High"] = hi if hi else "N/A"

        lo = info.get("fiftyTwoWeekLow")
        if not lo and fast:
            lo = getattr(fast, "year_low", None)
        data["52W Low"] = lo if lo else "N/A"

        data["Debt/Equity"] = info.get("debtToEquity", "N/A")
        data["Business Summary"] = info.get("longBusinessSummary", "No corporate overview provided.")
    except Exception:
        pass
    return data

def render_sparkline(prices, is_positive):
    color = "#15803d" if is_positive else "#b91c1c"
    fig = go.Figure()
    fig.add_trace(go.Scatter(y=prices, mode='lines', line=dict(color=color, width=1.8)))
    fig.update_layout(
        height=45, width=120, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- TOP UNIFORM MACRO BANNER ---
MACRO_SYMBOLS = {
    "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
    "ES Futures": "ES=F", "NQ Futures": "NQ=F", "YM Futures": "YM=F",
    "Crude Oil": "CL=F", "USD/JPY": "JPY=X", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"
}

@st.cache_data(ttl=300)
def fetch_macro_ribbon():
    ticks = list(MACRO_SYMBOLS.values())
    try:
        df = yf.download(ticks, period="5d", interval="1d", group_by="ticker", progress=False)
        out = {}
        for name, sym in MACRO_SYMBOLS.items():
            sub = df[sym].dropna() if len(ticks) > 1 else df.dropna()
            if len(sub) >= 2:
                c = float(sub["Close"].iloc[-1])
                pc = float(sub["Close"].iloc[-2])
                chg = c - pc
                pct = (chg / pc) * 100
                out[name] = (c, chg, pct)
        return out
    except Exception:
        return {}


# ==============================================================================
# 1. PRIMARY SIDEBAR NAVIGATION
# ==============================================================================
st.sidebar.markdown(
    """<div style="padding: 10px 0 20px 0;"><span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span><span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">MARKET OPEN · 15M DELAY</span><h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2><span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Momentum & TCT Engine</span></div>""", 
    unsafe_allow_html=True
)

navigation = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Screener", "Watchlist", "Precious Metals", "News & Earnings", "Settings"],
    label_visibility="collapsed",
    on_change=clear_inspection
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """<div style="position: fixed; bottom: 20px; font-size: 0.75rem; color: #71717a;">Quality Momentum + TCT v7.0<br>Provider: Yahoo / Google RSS</div>""", 
    unsafe_allow_html=True
)


# ==============================================================================
# 2. MACRO BANNER RENDERING
# ==============================================================================
macro_data = fetch_macro_ribbon()
if macro_data:
    cards_html = ""
    for name, (price, chg, pct) in macro_data.items():
        tick_class = "tick-pos" if chg >= 0 else "tick-neg"
        tick_sign = "+" if chg >= 0 else ""
        cards_html += f'<div class="macro-card"><div class="macro-title">{name}</div><div class="macro-price">{price:,.2f}</div><div class="{tick_class}">{tick_sign}{chg:.2f} ({tick_sign}{pct:.2f}%)</div></div>'
    st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)


# ==============================================================================
# 3. CONTENT ROUTING
# ==============================================================================
if st.session_state.inspect_symbol is not None:
    sym = st.session_state.inspect_symbol
    col_back, col_title = st.columns([1, 8])
    with col_back:
        if st.button("⬅ Back", type="primary"):
            st.session_state.inspect_symbol = None
            st.rerun()

    with col_title:
        st.markdown(f"<h1>{sym} · Technical, TCT & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        raw_mcap = funds.get('Market Cap')
        mcap_text = f"${raw_mcap/1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"
        
        f1.metric("Price", f"${d['Price']:.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Action Signal", d["TCT_Action"])
        f3.metric("Buy Trigger (BOS)", f"${d['BOS_Level']:.2f}")
        f4.metric("Take Profit Target", f"${d['Target_Price']:.2f}", f"+{d['Target_Pct']:.1f}%")
        f5.metric("Safety Stop-Loss", f"${d['Stop_Price']:.2f}", f"{d['Stop_Pct']:.1f}%", delta_color="inverse")
        f6.metric("0.5% Risk Size", f"{d['Shares_05Pct']} shs", f"{d['R_Multiple']:.1f}R Reward/Risk")

        st.markdown("---")

        c_ctrl, c_plot = st.columns([1.15, 3.85])
        with c_ctrl:
            st.markdown("### Chart Overlays")
            show_tct_lines = st.checkbox("TCT Target / Buy / Stop Lines", value=True)
            show_ema20 = st.checkbox("EMA 20 (Gold)", value=True)
            show_ema50 = st.checkbox("EMA 50 (Green)", value=True)
            show_ema200 = st.checkbox("EMA 200 (Purple)", value=False)
            show_bb = st.checkbox("Bollinger Bands (20, 2)", value=False)

            st.markdown("---")
            st.markdown("### TCT Trade Ticket")
            st.markdown(f"**Action:** `{d['TCT_Action']}`")
            st.markdown(f"**Setup Mode:** `{d['TCT_Model']}`")
            st.markdown(f"**Buy Above (BOS):** `${d['BOS_Level']:.2f}`")
            st.markdown(f"**Profit Target:** `${d['Target_Price']:.2f}` (+{d['Target_Pct']:.1f}%)")
            st.markdown(f"**Stop-Loss:** `${d['Stop_Price']:.2f}` ({d['Stop_Pct']:.1f}%)")
            st.markdown(f"**Reward/Risk:** `{d['R_Multiple']:.2f}R` ({'Pass ≥2R' if d['TCT_2R_Pass'] else 'Below 2R'})")
            st.markdown(f"**Suggested Shares:** `{d['Shares_05Pct']} shares` (${d['Pos_Value']:,.0f})")
            st.markdown(f"*{d['TCT_Explain']}*")

            st.markdown("---")
            st.markdown("### Momentum & Valuation")
            st.markdown(f"**Momentum State:** `{d['State']}` ({d['Score']}/100)")
            st.markdown(f"**Market Cap:** `{mcap_text}` | **P/E:** `{funds.get('Trailing P/E', 'N/A')}`")

        with c_plot:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.62, 0.19, 0.19])
            fig.add_trace(go.Candlestick(x=df_hist.index, open=df_hist['Open'], high=df_hist['High'], low=df_hist['Low'], close=df_hist['Close'], name="Candles"), row=1, col=1)

            if show_ema20:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA20'], line=dict(color="#d4af37", width=1.5), name="EMA 20"), row=1, col=1)
            if show_ema50:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA50'], line=dict(color="#15803d", width=1.5), name="EMA 50"), row=1, col=1)
            if show_ema200:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA200'], line=dict(color="#7c3aed", width=1.5), name="EMA 200"), row=1, col=1)
            if show_bb:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Upper'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Lower'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Lower"), row=1, col=1)

            if show_tct_lines:
                fig.add_hline(y=d["Target_Price"], line_dash="dash", line_color="#15803d", line_width=1.8, annotation_text=f"TAKE PROFIT TARGET: ${d['Target_Price']:.2f}", annotation_position="top left", row=1, col=1)
                fig.add_hline(y=d["BOS_Level"], line_dash="dot", line_color="#2563eb", line_width=1.6, annotation_text=f"BUY TRIGGER (BOS): ${d['BOS_Level']:.2f}", annotation_position="bottom left", row=1, col=1)
                fig.add_hline(y=d["Stop_Price"], line_dash="dash", line_color="#b91c1c", line_width=1.8, annotation_text=f"STOP-LOSS (EXIT): ${d['Stop_Price']:.2f}", annotation_position="bottom right", row=1, col=1)

            vol_colors = ['#15803d' if c >= o else '#b91c1c' for c, o in zip(df_hist['Close'], df_hist['Open'])]
            fig.add_trace(go.Bar(x=df_hist.index, y=df_hist['Volume'], marker_color=vol_colors, name="Volume"), row=2, col=1)

            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD'], line=dict(color="#2563eb", width=1.2), name="MACD"), row=3, col=1)
            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD_Signal'], line=dict(color="#ea580c", width=1.2), name="Signal"), row=3, col=1)
            fig.add_trace(go.Bar(x=df_hist.index, y=df_hist['MACD_Hist'], marker_color="#cbd5e1", name="Histogram"), row=3, col=1)

            fig.update_layout(height=650, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="white", plot_bgcolor="white", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Profile Summary")
        st.write(funds.get("Business Summary", "No business overview provided."))
    else:
        st.error(f"Unable to retrieve historical chart data for {sym}. Please verify the ticker.")

else:
    if navigation == "Dashboard":
        st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Straightforward Buy, Hold, and Sell signals combining Quality Momentum and TCT Accumulation rules.</p>", unsafe_allow_html=True)

        all_monitored = list(dict.fromkeys(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))
        stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])

        if stock_records:
            best_pick = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + x["Score"])
            h_col1, h_col2 = st.columns([11, 1])
            with h_col1:
                st.markdown(
                    f"""
                    <div style="background-color: #0f291e; border-radius: 10px; padding: 20px 24px; color: #fbf9f4;">
                        <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.12em; color: #c5a059; font-weight: 700;">
                            TODAY'S STANDOUT SETUP · {best_pick['TCT_Action']}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                            <div>
                                <span style="font-size: 1.8rem; font-weight: 700; color: #ffffff;">{best_pick['Ticker']}</span>
                                <span style="font-size: 1.2rem; color: #e2e8f0; margin-left: 8px;">${best_pick['Price']:.2f}</span>
                                <span style="color: {'#4ade80' if best_pick['Change'] >= 0 else '#f87171'}; font-weight: 600; margin-left: 6px;">
                                    {'+' if best_pick['Change'] >= 0 else ''}{best_pick['Change_Pct']:.2f}%
                                </span>
                                <div style="color: #cbd5e1; font-size: 0.90rem; margin-top: 4px;">
                                    <b>Buy/BOS:</b> ${best_pick['BOS_Level']:.2f} · <b>Take Profit:</b> ${best_pick['Target_Price']:.2f} (+{best_pick['Target_Pct']:.1f}%) · <b>Stop-Loss:</b> ${best_pick['Stop_Price']:.2f} · <b>Size (0.5% Risk):</b> {best_pick['Shares_05Pct']} shs ({best_pick['R_Multiple']:.1f}R)
                                </div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 2.2rem; font-weight: 700; color: #c5a059; font-family: 'Newsreader', serif;">
                                    {best_pick['Score']}
                                </div>
                                <div style="font-size: 0.70rem; color: #94a3b8; text-transform: uppercase;">Composite Score</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True
                )
            with h_col2:
                st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
                if st.button("🔍", key="btn_hero_inspect", help=f"Inspect {best_pick['Ticker']}"):
                    st.session_state.inspect_symbol = best_pick['Ticker']
                    st.rerun()

        st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

        col_left, col_right = st.columns([2, 1])
        with col_left:
            tab_watch, tab_macro = st.tabs([f"Watchlist News ({len(all_monitored)} Tickers)", "General Market News"])
            
            with tab_watch:
                wl_news = fetch_watchlist_news_pool(all_monitored, max_items=settings["news_limit"])
                if wl_news:
                    st.caption(f"Showing {len(wl_news)} chronological stories across your entire portfolio. Scroll down inside the box for more.")
                    news_html = '<div class="scroll-news-box">'
                    for a in wl_news:
                        ticker_name = a.get("ticker", "NEWS")
                        news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;"><span class="ticker-news-badge">[{ticker_name}]</span> {a["publisher"]}</span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                    news_html += '</div>'
                    st.markdown(news_html, unsafe_allow_html=True)
                else:
                    st.info("No recent specific news found for tracked assets.")

            with tab_macro:
                market_news = fetch_google_news_rss("US stock market news", max_items=settings["news_limit"])
                if market_news:
                    st.caption(f"Showing {len(market_news)} chronological market stories. Scroll down inside the box for more.")
                    m_news_html = '<div class="scroll-news-box">'
                    for n in market_news:
                        m_news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;">{n["publisher"]}</span><span>{n["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 3px;"><a href="{n["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{n["title"]}</a></div></div>'
                    m_news_html += '</div>'
                    st.markdown(m_news_html, unsafe_allow_html=True)
                else:
                    st.info("Market headlines feed currently refreshing.")

        with col_right:
            st.subheader("Action Signals Snapshot")
            sorted_snap = sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))
            for r in sorted_snap[:8]:
                s = r["Ticker"]
                c_card, c_btn = st.columns([5, 1])
                with c_card:
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 8px 12px; margin-bottom: 8px;">
                            <div style="display: flex; justify-content: space-between; align-items: center;">
                                <div>
                                    <span style="font-weight: 700; color: #0f291e;">{r['Ticker']}</span>
                                    <span class="badge {r['TCT_Badge']}" style="margin-left: 6px; font-size: 0.62rem;">{r['TCT_Action']}</span>
                                </div>
                                <div style="text-align: right;">
                                    <span style="font-weight: 600; font-size: 0.9rem;">${r['Price']:.2f}</span>
                                </div>
                            </div>
                            <div style="font-size: 0.73rem; color: #52525b; margin-top: 4px;">
                                Buy: <b>${r['BOS_Level']:.2f}</b> · Target: <b style="color:#15803d;">${r['Target_Price']:.2f}</b> · Stop: <b style="color:#b91c1c;">${r['Stop_Price']:.2f}</b>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
                with c_btn:
                    if st.button("🔍", key=f"insp_dash_{s}", help=f"Inspect {s}"):
                        st.session_state.inspect_symbol = s
                        st.rerun()

    elif navigation == "Screener":
        st.markdown("<h1>Find the Next Quality Leader or TCT Setup</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Scan for Momentum breakouts or your friend's TCT Accumulation setups with automatic Buy, Target, and Stop levels.</p>", unsafe_allow_html=True)

        f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])

        with f_col1:
            st.markdown("**1. GICS Sectors (Pick Any)**")
            selected_sectors = []
            for sec in list(GICS_SECTORS.keys()):
                if st.checkbox(sec, value=False, key=f"sec_{sec}"):
                    selected_sectors.append(sec)

        with f_col2:
            st.markdown("**2. Momentum Signals**")
            s1 = st.checkbox("RSI Rising Above 60 (Momentum)", value=False)
            s2 = st.checkbox("MACD Line Above Zero", value=False)
            s3 = st.checkbox("MACD Bullish Crossover", value=False)
            s4 = st.checkbox("20-Day High Breakout (Volume Confirmed)", value=False)
            s5 = st.checkbox("Bollinger Upper Band Breakout", value=False)
            s6 = st.checkbox("Bollinger Lower Band Touch (Pullback)", value=False)
            s7 = st.checkbox("Pullback Near 50-day EMA (Support)", value=False)
            s8 = st.checkbox("Price Above 200-day EMA", value=False)
            s9 = st.checkbox("Within 10% of 52-Week High", value=False)
            s10 = st.checkbox("Relative Volume (RVOL) > 1.5x", value=False)

        with f_col3:
            st.markdown("**3. TCT Accumulation Strategy Filters**")
            tct1 = st.checkbox("🟢 TCT 'BUY NOW' (BOS Breakout Triggered)", value=False)
            tct2 = st.checkbox("🟡 TCT Valid Accumulation Box (Tap 1 & Tap 2)", value=False)
            tct3 = st.checkbox("TCT Slow Decline (≥ 25 Bars from Peak)", value=False)
            tct4 = st.checkbox("TCT Reward-to-Risk ≥ 2.0R to Target", value=False)
            tct5 = st.checkbox("TCT Liquidity (20D Dollar Volume ≥ $50M)", value=False)

        scan_universe = []
        for s in selected_sectors:
            scan_universe.extend(GICS_SECTORS[s])
        scan_universe = list(set(scan_universe))

        c_run, c_clear = st.columns([2, 10])
        with c_run:
            if st.button("Run Scan", type="primary"):
                if not scan_universe:
                    st.warning("Please check at least one GICS Sector above to run the scan.")
                else:
                    with st.spinner(f"Scanning {len(scan_universe)} liquid names across selected sectors..."):
                        screener_data = fetch_batch_market_data(scan_universe, account_size=settings["account_size"])
                        matches = []
                        for t, d in screener_data.items():
                            if s1 and d["RSI"] < 60: continue
                            if s2 and not d["MACD_Above_Zero"]: continue
                            if s3 and not d["MACD_Cross"]: continue
                            if s4 and not d["Is_Breakout"]: continue
                            if s5 and not d["BB_Upper_Break"]: continue
                            if s6 and not d["BB_Lower_Touch"]: continue
                            if s7 and not d["Pullback_EMA50"]: continue
                            if s8 and not d["Above_EMA200"]: continue
                            if s9 and not d["Within_52W"]: continue
                            if s10 and d["RVOL"] < 1.5: continue
                            if tct1 and d["TCT_Action"] != "BUY NOW (BOS TRIGGERED)": continue
                            if tct2 and not d["TCT_Valid_Range"]: continue
                            if tct3 and not d["TCT_Slow_25"]: continue
                            if tct4 and not d["TCT_2R_Pass"]: continue
                            if tct5 and not d["TCT_Liq_50M"]: continue
                            matches.append(d)
                        st.session_state.screener_matches = sorted(matches, key=lambda x: (x["TCT_Priority"], -x["Score"]))

        with c_clear:
            if st.session_state.screener_matches is not None:
                if st.button("Clear Results"):
                    st.session_state.screener_matches = None
                    st.rerun()

        if st.session_state.screener_matches is not None:
            matches = st.session_state.screener_matches
            st.markdown(f"### Results: {len(matches)} Matches Found")
            for m in matches:
                c1, c2, c3, c4 = st.columns([3.2, 2.5, 1.8, 1.2])
                with c1:
                    st.markdown(
                        f"""
                        <div>
                            <span style="font-size: 1.15rem; font-weight: 700; color: #0f291e;">{m['Ticker']}</span>
                            <span class="badge {m['TCT_Badge']}" style="margin-left: 8px;">{m['TCT_Action']}</span>
                        </div>
                        <div style="font-size: 0.85rem; color: #71717a;">${m['Price']:.2f} · <span style="color: {'#15803d' if m['Change']>=0 else '#b91c1c'}; font-weight: 600;">{'+' if m['Change']>=0 else ''}{m['Change_Pct']:.2f}%</span></div>
                        <div style="font-size: 0.8rem; color: #475569; margin-top: 4px;">{m['TCT_Explain']}</div>
                        """, unsafe_allow_html=True
                    )
                with c2:
                    st.markdown(
                        f"""
                        <div style="font-size: 0.82rem; line-height: 1.5;">
                            <b>Buy Trigger (BOS):</b> ${m['BOS_Level']:.2f}<br>
                            <b>Take Profit:</b> <span style="color:#15803d; font-weight:600;">${m['Target_Price']:.2f} (+{m['Target_Pct']:.1f}%)</span><br>
                            <b>Stop-Loss:</b> <span style="color:#b91c1c; font-weight:600;">${m['Stop_Price']:.2f} ({m['Stop_Pct']:.1f}%)</span> · <b>{m['R_Multiple']:.1f}R</b> · <b>{m['Shares_05Pct']} shs</b>
                        </div>
                        """, unsafe_allow_html=True
                    )
                with c3:
                    st.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
                with c4:
                    col_insp, col_add = st.columns(2)
                    with col_insp:
                        if st.button("🔍", key=f"insp_sc_{m['Ticker']}", help=f"Inspect {m['Ticker']}"):
                            st.session_state.inspect_symbol = m['Ticker']
                            st.rerun()
                    with col_add:
                        if st.button("➕", key=f"add_sc_{m['Ticker']}", help="Add to Radar"):
                            if m["Ticker"] not in watchlists["Opportunity Radar"]:
                                watchlists["Opportunity Radar"].append(m["Ticker"])
                                save_json(DATA_FILE, watchlists)
                                st.success("Added")

    elif navigation == "Watchlist":
        st.markdown("<h1>Watchlist & TCT Action Tickets</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Every stock shows a clear Buy Trigger, Take Profit Target, Safety Stop-Loss, and 0.5% Risk Share Size.</p>", unsafe_allow_html=True)

        folder = st.radio("Folder View", ["Active Portfolio", "Opportunity Radar"], horizontal=True)
        symbols = watchlists[folder]

        col_add, col_sort = st.columns([3, 2])
        with col_add:
            c_in, c_btn = st.columns([3, 1])
            new_sym = c_in.text_input("Add symbol to folder", placeholder="e.g. AVGO", label_visibility="collapsed").upper().strip()
            if c_btn.button("+ Add") and new_sym:
                if new_sym not in symbols:
                    watchlists[folder].append(new_sym)
                    save_json(DATA_FILE, watchlists)
                    st.rerun()

        with col_sort:
            sort_by = st.selectbox(
                "Sort By",
                [
                    "Action Signal (Buy Now First)",
                    "Composite Score (High → Low)",
                    "Reward-to-Risk Ratio (High → Low)",
                    "Momentum State",
                    "Day % Change (High → Low)",
                    "Alphabetical (A → Z)",
                    "Saved Order"
                ],
                index=0
            )

        pills_html = "".join([f"<span class='pill'>{s}</span>" for s in symbols])
        st.markdown(f"<div style='margin-bottom: 16px;'>{pills_html}</div>", unsafe_allow_html=True)

        if st.checkbox("Manage / Remove Tickers"):
            del_sym = st.selectbox("Select symbol to remove", ["-- Select --"] + symbols)
            if st.button("Confirm Removal") and del_sym != "-- Select --":
                watchlists[folder].remove(del_sym)
                save_json(DATA_FILE, watchlists)
                st.rerun()

        st.markdown("---")

        data_dict = fetch_batch_market_data(symbols, account_size=settings["account_size"])

        # APPLY SORTING
        display_symbols = list(symbols)
        if sort_by == "Action Signal (Buy Now First)":
            display_symbols = sorted(display_symbols, key=lambda s: (data_dict.get(s, {}).get("TCT_Priority", 9), -data_dict.get(s, {}).get("Score", 0)))
        elif sort_by == "Composite Score (High → Low)":
            display_symbols = sorted(display_symbols, key=lambda s: data_dict.get(s, {}).get("Score", 0), reverse=True)
        elif sort_by == "Reward-to-Risk Ratio (High → Low)":
            display_symbols = sorted(display_symbols, key=lambda s: data_dict.get(s, {}).get("R_Multiple", 0), reverse=True)
        elif sort_by == "Momentum State":
            state_priority = {"Confirmed Breakout": 0, "Active Trend": 1, "Entry Candidate": 2, "Support Break": 3}
            display_symbols = sorted(display_symbols, key=lambda s: state_priority.get(data_dict.get(s, {}).get("State", ""), 4))
        elif sort_by == "Day % Change (High → Low)":
            display_symbols = sorted(display_symbols, key=lambda s: data_dict.get(s, {}).get("Change_Pct", -999), reverse=True)
        elif sort_by == "Alphabetical (A → Z)":
            display_symbols = sorted(display_symbols)

        left_c, right_c = st.columns(2)

        for idx, sym in enumerate(display_symbols):
            target_c = left_c if idx % 2 == 0 else right_c
            if sym in data_dict:
                d = data_dict[sym]
                with target_c:
                    c_info, c_action = st.columns([8.5, 1])
                    with c_info:
                        st.markdown(
                            f'<div class="stock-card" style="margin-bottom: 0;"><div style="display: flex; justify-content: space-between; align-items: flex-start;"><div><span style="font-size: 1.25rem; font-weight: 700; color: #0f291e;">{d["Ticker"]}</span><span class="badge {d["TCT_Badge"]}" style="margin-left: 8px;">{d["TCT_Action"]}</span><span class="badge {d["Badge"]}" style="margin-left: 4px;">{d["State"]}</span><div style="font-size: 1.35rem; font-weight: 700; margin-top: 4px;">${d["Price"]:.2f} <span style="font-size: 0.9rem; color: {"#15803d" if d["Change"]>=0 else "#b91c1c"}; font-weight: 600;">{"+" if d["Change"]>=0 else ""}{d["Change_Pct"]:.2f}%</span></div></div><div style="text-align: right;"><div style="font-size: 1.6rem; font-weight: 700; color: #c5a059; font-family: \'Newsreader\', serif;">{d["Score"]}</div><div style="font-size: 0.7rem; color: #71717a; text-transform: uppercase;">Score</div></div></div><div class="trade-ticket"><div style="display: flex; justify-content: space-between; font-weight: 600; color: #0f291e; margin-bottom: 4px;"><span>🎯 Buy Trigger (BOS): ${d["BOS_Level"]:.2f}</span><span>📐 Reward/Risk: {d["R_Multiple"]:.1f}R</span></div><div style="display: flex; justify-content: space-between;"><span>🟢 <b>Take Profit:</b> <span style="color:#15803d; font-weight:700;">${d["Target_Price"]:.2f}</span> (+{d["Target_Pct"]:.1f}%)</span><span>🔴 <b>Stop-Loss:</b> <span style="color:#b91c1c; font-weight:700;">${d["Stop_Price"]:.2f}</span> ({d["Stop_Pct"]:.1f}%)</span></div><div style="margin-top: 4px; font-size: 0.76rem; color: #52525b; display: flex; justify-content: space-between;"><span><b>0.5% Risk Size:</b> Buy {d["Shares_05Pct"]} shares (${d["Pos_Value"]:,.0f})</span><span><b>Mode:</b> {d["TCT_Model"]}</span></div></div><div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.78rem; color: #52525b;"><div>RSI: <b>{d["RSI"]:.1f}</b></div><div>RVOL: <b>{d["RVOL"]:.1f}x</b></div><div>EMA 50: <b>${d["History"]["EMA50"].iloc[-1]:.2f}</b></div><div>20D Vol: <b>${d["Dollar_Vol_M"]:.0f}M</b></div></div><div style="font-size: 0.80rem; color: #475569; margin-top: 6px; font-style: italic;">"{d["TCT_Explain"]}"</div></div>',
                            unsafe_allow_html=True
                        )
                    with c_action:
                        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                        if st.button("🔍", key=f"insp_wl_{sym}", help=f"Inspect {sym}"):
                            st.session_state.inspect_symbol = sym
                            st.rerun()
                    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

    elif navigation == "Precious Metals":
        st.markdown("<h1>Precious Metals & Commodities</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Real-time Spot Gold, Spot Silver, and core commodity proxies with TCT Buy/Target/Stop levels.</p>", unsafe_allow_html=True)

        METALS_UNIVERSE = {
            "Spot Gold (USD/oz)": "XAUUSD=X", "Spot Silver (USD/oz)": "XAGUSD=X",
            "Platinum Futures": "PL=F", "Gold ETF (GLD)": "GLD",
            "Silver ETF (SLV)": "SLV", "ProShares Ultra Gold 2x (UGL)": "UGL"
        }

        metals_data = fetch_batch_market_data(list(METALS_UNIVERSE.values()), account_size=settings["account_size"])

        m_col1, m_col2 = st.columns(2)
        for idx, (title, sym) in enumerate(METALS_UNIVERSE.items()):
            col = m_col1 if idx % 2 == 0 else m_col2
            if sym in metals_data:
                m = metals_data[sym]
                with col:
                    pm_info, pm_btn = st.columns([8.5, 1])
                    with pm_info:
                        st.markdown(
                            f'<div class="stock-card" style="margin-bottom: 0;"><div style="font-size: 0.75rem; color: #71717a; text-transform: uppercase; font-weight: 600;">{title}</div><div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;"><div style="font-size: 1.5rem; font-weight: 700; color: #0f291e;">${m["Price"]:,.2f} <span style="font-size: 0.95rem; color: {"#15803d" if m["Change"]>=0 else "#b91c1c"}; font-weight: 600;">{"+" if m["Change"]>=0 else ""}{m["Change_Pct"]:.2f}%</span></div><span class="badge {m["TCT_Badge"]}">{m["TCT_Action"]}</span></div><div style="margin-top: 8px; font-size: 0.80rem; color: #52525b;">Buy/BOS: <b>${m["BOS_Level"]:,.2f}</b> · Target: <b style="color:#15803d;">${m["Target_Price"]:,.2f}</b> · Stop: <b style="color:#b91c1c;">${m["Stop_Price"]:,.2f}</b></div></div>',
                            unsafe_allow_html=True
                        )
                    with pm_btn:
                        st.markdown("<div style='height: 18px;'></div>", unsafe_allow_html=True)
                        if st.button("🔍", key=f"btn_metal_{sym}", help=f"Inspect {title}"):
                            st.session_state.inspect_symbol = sym
                            st.rerun()
                    st.markdown("<div style='margin-bottom: 12px;'></div>", unsafe_allow_html=True)

    elif navigation == "News & Earnings":
        st.markdown("<h1>News & Catalyst Monitor</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Full-portfolio Google News RSS stream and chronologically organized earnings announcements.</p>", unsafe_allow_html=True)

        n_col1, n_col2 = st.columns([2, 1])

        tracked_symbols = list(dict.fromkeys(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))

        with n_col1:
            st.subheader(f"Watchlist News Feed ({len(tracked_symbols)} Monitored Stocks)")
            pool_articles = fetch_watchlist_news_pool(tracked_symbols, max_items=settings["news_limit"])
            if pool_articles:
                st.caption(f"Showing {len(pool_articles)} recent articles sorted newest-first.")
                news_html = '<div class="scroll-news-box">'
                for a in pool_articles:
                    ticker_name = a.get("ticker", "ALERT")
                    news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{ticker_name}]</span> {a["publisher"]}</span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                news_html += '</div>'
                st.markdown(news_html, unsafe_allow_html=True)
            else:
                st.info("Watchlist news feed refreshing.")

        with n_col2:
            st.subheader("Upcoming Earnings Calendar")
            earnings_rows = []
            now_dt = datetime.now()
            for s in tracked_symbols:
                try:
                    cal = yf.Ticker(s).calendar
                    raw_date = None
                    if isinstance(cal, dict) and "Earnings Date" in cal:
                        dates = cal["Earnings Date"]
                        raw_date = dates[0] if isinstance(dates, list) and dates else dates
                    elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                        raw_date = cal.loc["Earnings Date"].iloc[0]
                    
                    if raw_date is not None:
                        dt_parsed = pd.to_datetime(raw_date)
                        if dt_parsed.to_pydatetime().replace(tzinfo=None) >= now_dt.replace(hour=0, minute=0, second=0):
                            earnings_rows.append({
                                "Ticker": s,
                                "Earnings Date": dt_parsed.strftime("%Y-%m-%d"),
                                "_sort": dt_parsed
                            })
                except Exception:
                    continue

            if earnings_rows:
                earnings_rows = sorted(earnings_rows, key=lambda x: x["_sort"])
                clean_df = pd.DataFrame([{"Ticker": r["Ticker"], "Earnings Date": r["Earnings Date"]} for r in earnings_rows])
                st.table(clean_df)
            else:
                st.info("No confirmed upcoming earnings within your monitored universe.")

    elif navigation == "Settings":
        st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Configure your TCT account size (for 0.5% risk share sizing), news capacity, and scoring weights.</p>", unsafe_allow_html=True)

        s_col1, s_col2 = st.columns(2)

        with s_col1:
            st.subheader("TCT Portfolio & News Capacity")
            acc_val = st.number_input("Total Trading Account Size ($ USD) — Used for 0.5% Risk Share Sizing", min_value=1000, max_value=50000000, value=int(settings.get("account_size", 100000)), step=5000)
            news_lim = st.slider("Max News Headlines in Scrollable Feed", min_value=20, max_value=100, value=int(settings.get("news_limit", 60)), step=10)

            st.markdown("---")
            st.subheader("Score Weighting Defaults")
            w_f = st.slider("Fundamentals Weight", 0, 100, settings["w_fund"])
            w_t = st.slider("Technical Trend Weight", 0, 100, settings["w_tech"])
            w_m = st.slider("Momentum Weight", 0, 100, settings["w_mom"])

            if st.button("Save All Settings", type="primary"):
                settings["account_size"] = acc_val
                settings["news_limit"] = news_lim
                settings["w_fund"] = w_f
                settings["w_tech"] = w_t
                settings["w_mom"] = w_m
                save_json(SETTINGS_FILE, settings)
                st.cache_data.clear()
                st.success("Settings saved and cache refreshed!")

        with s_col2:
            st.subheader("Push Notifications")
            if st.button("🔔 Test iPad Ping (ntfy)"):
                send_ntfy_alert("This is a test alert from your Quality Momentum & TCT Dashboard!", "Test Ping")
                st.success("Test ping sent to your iPad! Make sure the ntfy app is listening to '2026_USstockspicks'.")
            
            st.markdown("<br>", unsafe_allow_html=True)
            st.checkbox("Alert on Confirmed Breakouts & TCT Buy Signals", value=settings["alert_breakout"])
            st.checkbox("Alert on EMA 50 & TCT Stop-Loss Breaks", value=settings["alert_support"])

            st.markdown("---")
            st.subheader("Export Strategy Review CSV")
            all_syms = list(dict.fromkeys(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))
            current_data = fetch_batch_market_data(all_syms, account_size=settings["account_size"])

            if current_data:
                export_rows = []
                for sym_name, d in current_data.items():
                    export_rows.append({
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Ticker": sym_name,
                        "Price": d["Price"],
                        "Change_Pct": d["Change_Pct"],
                        "TCT_Action": d["TCT_Action"],
                        "Buy_BOS_Trigger": d["BOS_Level"],
                        "Take_Profit_Target": d["Target_Price"],
                        "Stop_Loss": d["Stop_Price"],
                        "Reward_Risk_R": round(d["R_Multiple"], 2),
                        "Suggested_Shares_05Pct": d["Shares_05Pct"],
                        "Composite_Score": d["Score"],
                        "Momentum_State": d["State"]
                    })
                df_export = pd.DataFrame(export_rows)

                st.download_button(
                    label="📥 Download Full TCT & Momentum Plan CSV",
                    data=df_export.to_csv(index=False).encode("utf-8"),
                    file_name=f"tct_momentum_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv", type="primary"
                )
