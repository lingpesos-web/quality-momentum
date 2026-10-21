import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import time
import base64
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import email.utils
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(page_title="Momentum, Swing & TCT Cockpit", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

# --- SESSION STATE & URL ROUTING ---
for k, v in [("inspect_symbol", None), ("rt_chart_symbol", None), ("nav_radio", "Dashboard"),
             ("screener_matches", None), ("screener_title", None), ("wl_preset_filter", "ALL"), ("last_good_data", {})]:
    if k not in st.session_state:
        st.session_state[k] = v

if "inspect" in st.query_params:
    sym_q = st.query_params.get("inspect", "").strip().upper()
    if sym_q:
        st.session_state.inspect_symbol = sym_q
    st.query_params.clear()

if "rt_chart" in st.query_params:
    rt_q = st.query_params.get("rt_chart", "").strip().upper()
    if rt_q:
        st.session_state.rt_chart_symbol = rt_q
        st.session_state.inspect_symbol = None
        st.session_state.nav_radio = "⚡ Live Real-Time Quotes"
    st.query_params.clear()

def clear_inspection():
    st.session_state.inspect_symbol = None
    if "inspect" in st.query_params or "rt_chart" in st.query_params:
        st.query_params.clear()

# --- NTFY ALERT ENGINE (ASCII-SAFE HEADER) ---
def send_ntfy_alert(message, title="Daily Portfolio Briefing"):
    try:
        ascii_title = title.encode("ascii", "ignore").decode("ascii").strip() or "Market Alert"
        req = urllib.request.Request(
            "https://ntfy.sh/2026_USstockspicks",
            data=message.encode("utf-8"),
            headers={"Title": ascii_title, "Priority": "high", "Content-Type": "text/plain; charset=utf-8"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, f"Delivered (HTTP {resp.status}) to '2026_USstockspicks'"
    except Exception as e:
        return False, f"ntfy error: {str(e)}"

# --- THEME & COMPACT 2-COLUMN LIVE BOARD CSS ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,600&family=Inter:wght@400;500;600;700;800&display=swap');
.stApp { background-color: #fbf9f4 !important; color: #1a1a1a !important; font-family: 'Inter', sans-serif; }
[data-testid="stSidebar"] { background-color: #0f291e !important; border-right: 1px solid #1c3d2f; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
h1, h2, h3 { font-family: 'Newsreader', Georgia, serif !important; font-weight: 600 !important; color: #0f291e !important; }
.macro-container { display: flex; flex-wrap: nowrap; gap: 8px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 10px; }
.macro-card { flex: 1 1 0px; min-width: 105px; background: #fff; border: 1px solid #e7e2d9; border-radius: 8px; padding: 8px 6px; text-align: center; }
.macro-title { font-size: 0.68rem; color: #71717a; text-transform: uppercase; font-weight: 700; white-space: nowrap; }
.macro-price { font-size: 0.88rem; font-weight: 700; color: #18181b; margin: 2px 0; white-space: nowrap; }
.tick-pos { color: #15803d; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.tick-neg { color: #b91c1c; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.stock-card { background: #fff; border: 1px solid #e7e2d9; border-radius: 10px; padding: 15px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
.ticker-link { font-size: 1.22rem; font-weight: 800; color: #0f291e !important; text-decoration: none !important; border-bottom: 2px solid #c5a059; }
.ticker-link:hover { color: #15803d !important; background-color: #f0fdf4; border-radius: 4px; padding: 2px 5px; }
.hero-ticker-link { font-size: 1.8rem; font-weight: 800; color: #fff !important; text-decoration: none !important; border-bottom: 2px dashed #c5a059; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 0.67rem; font-weight: 700; text-transform: uppercase; }
.badge-breakout { background: #dcfce7; color: #15803d; }
.badge-trend { background: #dbeafe; color: #1d4ed8; }
.badge-candidate { background: #fef9c3; color: #a16207; }
.badge-caution { background: #fee2e2; color: #b91c1c; }
.badge-tct-buy { background: #15803d; color: #fff; }
.badge-tct-watch { background: #fef08a; color: #854d0e; border: 1px solid #fde047; }
.badge-tct-sell { background: #b91c1c; color: #fff; }
.badge-rs-lead { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.badge-rs-lag { background: #f4f4f5; color: #71717a; }
.pill { display: inline-flex; align-items: center; background: #e9e4db; color: #0f291e !important; text-decoration: none !important; padding: 4px 10px; border-radius: 14px; font-size: 0.8rem; font-weight: 600; margin: 0 6px 6px 0; }
.scroll-news-box { max-height: 540px; overflow-y: auto; padding-right: 6px; }
.ticker-news-badge { background: #dcfce7; color: #15803d; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 0.7rem; margin-right: 6px; }
.age-badge { background: #f1f5f9; color: #334155; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.68rem; margin-left: 6px; }
.trade-ticket { background: #f8f6f0; border: 1px solid #e2ddd2; border-radius: 8px; padding: 9px 12px; margin-top: 9px; font-size: 0.80rem; }
.live-board-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; margin-top: 4px; }
@media (max-width: 900px) { .live-board-grid { grid-template-columns: 1fr; } }
.live-quote-table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d4cec3; border-radius: 6px; overflow: hidden; font-size: 1.12rem; }
.live-quote-table thead th { background: #0f291e; color: #f4efe6; font-weight: 700; font-size: 0.80rem; text-transform: uppercase; padding: 6px 5px; text-align: right; white-space: nowrap; }
.live-quote-table thead th:nth-child(1), .live-quote-table thead th:nth-child(2) { text-align: left; }
.live-quote-table tbody tr { border-bottom: 1px solid #eae5dc; line-height: 1.25; }
.live-quote-table tbody tr:nth-child(even) { background-color: #faf8f5; }
.live-quote-table tbody tr:hover { background-color: #ecfdf5; }
.live-quote-table td { padding: 5px 5px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.live-quote-table td:nth-child(1) { text-align: left; font-size: 0.90rem; font-weight: 700; padding-left: 6px; }
.live-quote-table td:nth-child(2) { text-align: left; font-weight: 800; }
.rt-sym-link { color: #0f291e !important; text-decoration: none !important; font-weight: 800; font-size: 1.16rem; border-bottom: 2px solid #c5a059; }
.rt-dossier-link { text-decoration: none !important; font-size: 0.85rem; margin-left: 3px; opacity: 0.75; }
</style>
""", unsafe_allow_html=True)

# --- WATCHLISTS & GITHUB AUTO-SYNC ---
DATA_FILE = "watchlists.json"
SETTINGS_FILE = "settings.json"
GITHUB_REPO = "lingpesos-web/quality-momentum"
GITHUB_BRANCH = "main"

DEFAULT_WATCHLISTS = {
    "Active Portfolio": [
        "SLV", "VRT", "COHR", "SKHY", "SNDK", "MU", "DRAM", "HOOD", "SOFI",
        "PLTR", "GLW", "LRCX", "MRVL", "CLS", "CRCL", "LITE", "ADPT", "SPCX",
        "STX", "WDC", "TEM", "IREN", "CBRS", "CDE", "SOXL", "IONQ", "QUBT",
        "AMD", "APP", "COIN", "MSTR", "CRDO", "NVDA"
    ],
    "Opportunity Radar": ["PLTR", "MU", "HOOD", "LRCX", "SOFI", "MRVL", "AVGO", "COST"],
    "Special Case Stocks": ["COIN", "MSTR", "SOXL", "IONQ"]
}

def get_github_token():
    try:
        if "GITHUB_TOKEN" in st.secrets:
            return str(st.secrets["GITHUB_TOKEN"]).strip()
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "").strip()

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                if isinstance(data, dict) and data:
                    return data
        except Exception:
            pass
    return default

def save_json(filepath, data):
    try:
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def sync_watchlists_to_github(data):
    save_json(DATA_FILE, data)
    token = get_github_token()
    if not token:
        return False, "Saved locally (Add GITHUB_TOKEN in Streamlit Secrets for GitHub sync)."
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "QMCockpit"}
    try:
        sha = None
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{api_url}?ref={GITHUB_BRANCH}", headers=headers), timeout=6) as r:
                sha = json.loads(r.read().decode("utf-8")).get("sha")
        except Exception:
            pass
        payload = {
            "message": f"Sync watchlists.json ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "content": base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8"),
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        req_put = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers={**headers, "Content-Type": "application/json"}, method="PUT")
        with urllib.request.urlopen(req_put, timeout=8) as resp:
            if resp.status in (200, 201):
                return True, "✅ Permanently synced to GitHub watchlists.json!"
    except Exception as e:
        return False, f"Saved locally ({str(e)[:50]})"
    return False, "Saved locally."

watchlists = load_json(DATA_FILE, DEFAULT_WATCHLISTS)
for k_def, v_def in DEFAULT_WATCHLISTS.items():
    if k_def not in watchlists or not isinstance(watchlists[k_def], list):
        watchlists[k_def] = v_def

def get_all_monitored_tickers():
    out = []
    for syms in watchlists.values():
        if isinstance(syms, list):
            out.extend([str(s).strip().upper() for s in syms if str(s).strip()])
    return list(dict.fromkeys(out))

settings = load_json(SETTINGS_FILE, {
    "w_fund": 40, "w_tech": 40, "w_mom": 20, "account_size": 100000,
    "news_limit": 60, "max_news_age_hours": 72, "alert_breakout": True, "alert_support": True
})
for k_s, v_s in [("account_size", 100000), ("news_limit", 60), ("max_news_age_hours", 72), ("w_fund", 40), ("w_tech", 40), ("w_mom", 20)]:
    if k_s not in settings:
        settings[k_s] = v_s

# --- EXPANDED ~220-STOCK LIQUID MARKET UNIVERSE ---
GICS_SECTORS = {
    "AI, Semiconductors & Hardware": ["NVDA", "AVGO", "AMD", "MU", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MRVL", "ARM", "QCOM", "TXN", "ADI", "ON", "MPWR", "NXPI", "CRDO", "VRT", "COHR", "LITE", "CIEN", "ANET", "SMCI", "DELL", "SNDK", "STX", "WDC", "NTAP", "PSTG", "GLW", "CLS", "APH"],
    "Software, Cloud & Cyber": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "PLTR", "APP", "SNOW", "PANW", "CRWD", "FTNT", "ZS", "NET", "DDOG", "MDB", "TEAM", "WDAY", "HUBS", "TTD", "IOT", "DUOL", "MNDY", "S", "CYBR"],
    "Quantum, Space & Next-Gen": ["IONQ", "QUBT", "RGTI", "QBTS", "RKLB", "ASTS", "LUNR", "JOBY", "ACHR", "SERV", "SOUN", "BBAI", "SYM", "UPST", "AFRM", "RDDT", "ALAB"],
    "Crypto, Fintech & Financials": ["COIN", "MSTR", "HOOD", "SOFI", "XYZ", "PYPL", "MARA", "RIOT", "CLSK", "IREN", "CORZ", "HUT", "WULF", "CIFR", "JPM", "GS", "MS", "BLK", "BX", "KKR", "APO", "V", "MA", "AXP", "BAC", "WFC"],
    "Communication & Internet": ["GOOGL", "META", "NFLX", "AMZN", "AAPL", "TSLA", "SPOT", "UBER", "DASH", "ABNB", "BKNG", "TMUS", "DIS", "RBLX", "TTWO", "PINS"],
    "Energy, Nuclear & Metals": ["CEG", "VST", "NRG", "TLN", "OKLO", "SMR", "CCJ", "UEC", "NXE", "NEE", "GEV", "XOM", "CVX", "COP", "EOG", "SLB", "NEM", "AEM", "WPM", "PAAS", "AG", "CDE", "FCX", "SLV", "GLD"],
    "Industrials & Defense": ["GE", "CAT", "ETN", "PWR", "EME", "URI", "PH", "TT", "RTX", "LMT", "NOC", "GD", "LHX", "AXON", "TDG", "HWM", "UNP", "DE", "HON"],
    "Health Care & Biotech": ["LLY", "NVO", "VRTX", "REGN", "AMGN", "GILD", "ISRG", "SYK", "BSX", "ABT", "TMO", "UNH", "IDXX", "DXCM", "ADPT", "TEM", "EXAS", "NTRA", "VKTX"],
    "Consumer & Retail": ["WMT", "COST", "TGT", "HD", "LOW", "TJX", "NKE", "ONON", "DECK", "LULU", "SBUX", "CMG", "CAVA", "SHAK", "MCD", "PG", "KO", "PEP", "PM"]
}

# --- STRICT 72H VERIFIED NEWS ENGINE ---
BLOCKED_NEWS_SOURCES = {"marketbeat", "zacks", "defense world", "etf daily news", "ticker report", "american banking news", "simply wall st", "stocknews.com", "wall street zen", "holdings channel"}
STALE_PATTERNS = ["if you invested", "years ago", "last year", "months ago", "why shares plunged in "]

def _fetch_rss_raw(query, max_per_query=16, ticker_tag="MARKET", max_age_hours=72):
    q_time = query if "when:" in query else f"{query} when:3d"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_time)}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    out, now_utc = [], datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            root = ET.fromstring(resp.read())
        for item in root.findall(".//item")[:max_per_query]:
            raw_t = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else "#"
            pub_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            src = item.find("source").text if item.find("source") is not None else "News"
            if not raw_t or not pub_raw or any(b in src.lower() for b in BLOCKED_NEWS_SOURCES):
                continue
            clean_t = raw_t.rsplit(" - ", 1)[0] if " - " in raw_t else raw_t
            if any(p in clean_t.lower() for p in STALE_PATTERNS):
                continue
            try:
                dt = email.utils.parsedate_to_datetime(pub_raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age_h = (now_utc - dt).total_seconds() / 3600.0
            if age_h < -1.0 or age_h > max_age_hours:
                continue
            age_lbl = f"{max(1, int(age_h*60))}m ago" if age_h < 1 else (f"{int(age_h)}h ago" if age_h < 24 else f"{int(age_h//24)}d ago")
            out.append({"title": clean_t, "link": link, "publisher": src, "date": dt.strftime("%b %d · %H:%M UTC"), "age": age_lbl, "timestamp": dt.timestamp(), "ticker": ticker_tag})
    except Exception:
        pass
    return out

@st.cache_data(ttl=600)
def fetch_news_pool(queries_with_tags, max_items=60, max_age_hours=72):
    pool, seen = [], set()
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(_fetch_rss_raw, q, 15, tag, max_age_hours) for q, tag in queries_with_tags]
        for f in futs:
            for it in f.result():
                key = it["title"][:42].lower()
                if key not in seen:
                    seen.add(key)
                    pool.append(it)
    return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

# --- 6-PLAYBOOK MULTI-STRATEGY ENGINE (TCT + 4 SWING STRATEGIES + MOMENTUM) ---
def analyze_six_playbooks(df, account_size=100000, spy_ret_63d=0.0, df_1h=None):
    n = len(df)
    close_arr = df["Close"].values.astype(float)
    high_arr = df["High"].values.astype(float)
    low_arr = df["Low"].values.astype(float)
    open_arr = df["Open"].values.astype(float)
    vol_arr = np.nan_to_num(df["Volume"].values.astype(float), nan=0.0)
    curr_close = float(close_arr[-1])
    prev_close = float(close_arr[-2]) if n >= 2 else curr_close

    # Relative Strength vs S&P 500 (63-Day)
    lb_rs = min(63, n - 1)
    ret_63d = ((curr_close - float(close_arr[-1 - lb_rs])) / float(close_arr[-1 - lb_rs])) * 100.0 if lb_rs > 5 and close_arr[-1 - lb_rs] > 0 else 0.0
    rs_diff = ret_63d - spy_ret_63d
    rs_leader = bool(rs_diff >= 2.0)

    dollar_vol_20 = float(pd.Series(close_arr[-20:] * vol_arr[-20:]).median()) if n >= 20 else 0.0
    liq_pass = bool(dollar_vol_20 >= 50_000_000)

    # Technical Building Blocks: ATR(14), EMA20/50/200, RSI(14), RSI(2), ADX(14), Bollinger Bandwidth
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - df["Close"].shift(1)).abs(), (df["Low"] - df["Close"].shift(1)).abs()], axis=1).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1])
    if np.isnan(atr14) or atr14 <= 0:
        atr14 = curr_close * 0.025
    atr14_1h = atr14 / 2.55

    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])
    ema200 = float(df["EMA200"].iloc[-1]) if len(df) >= 200 else ema50
    rsi14 = float(df["RSI"].iloc[-1])

    # Connors 2-Period RSI for Oversold Snapback Swing
    delta = df["Close"].diff()
    g2 = delta.where(delta > 0, 0.0).ewm(alpha=1/2, adjust=False).mean()
    l2 = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/2, adjust=False).mean()
    rsi2_series = 100 - (100 / (1 + (g2 / (l2 + 1e-9))))
    rsi2 = float(rsi2_series.iloc[-1]) if not np.isnan(rsi2_series.iloc[-1]) else 50.0

    # Bollinger Band Squeeze Width
    bb_width = ((df["BB_Upper"] - df["BB_Lower"]) / (df["BB_Mid"] + 1e-9)).values
    curr_bb_w = float(bb_width[-1]) if not np.isnan(bb_width[-1]) else 0.10
    min_bb_w20 = float(np.nanmin(bb_width[-25:])) if n >= 25 else curr_bb_w
    is_bb_squeeze = bool(curr_bb_w <= min_bb_w20 * 1.18)

    # Pace-Adjusted RVOL (fixes missing intraday breakout alerts during market hours)
    vol20 = float(df["Vol20"].iloc[-1]) if not np.isnan(df["Vol20"].iloc[-1]) else 0.0
    now_utc = datetime.now(timezone.utc)
    if 13 <= now_utc.hour <= 20 and now_utc.weekday() < 5:
        mins_open = max(25.0, min(390.0, (now_utc.hour * 60 + now_utc.minute) - (13 * 60 + 30)))
        pace_factor = max(0.20, mins_open / 390.0)
    else:
        pace_factor = 1.0
    raw_rvol = float(vol_arr[-1] / vol20) if vol20 > 0 else 1.0
    paced_rvol = float(vol_arr[-1] / (vol20 * pace_factor)) if vol20 > 0 else 1.0

    # Confirmed Swing Points (k = 3)
    swing_highs = [(i, float(high_arr[i])) for i in range(3, n - 3) if high_arr[i] == np.max(high_arr[i - 3:i + 4])]
    swing_lows = [(i, float(low_arr[i])) for i in range(3, n - 3) if low_arr[i] == np.min(low_arr[i - 3:i + 4])]

    # --- PLAYBOOK 1: TRUE TCT BOTTOM ACCUMULATION (25+ Bar Slow Decline) ---
    lookback = min(n, 130)
    start_idx = n - lookback
    peak_idx = start_idx + int(np.argmax(high_arr[start_idx:max(start_idx + 1, n - 20)]))
    peak_price = float(high_arr[peak_idx])
    recent_lows = [(idx, val) for idx, val in swing_lows if idx > peak_idx]

    tct_valid_range, slow_decline_25 = False, False
    tap1_price, tap2_price, tap3_price, range_high, bos_level = None, None, None, None, None

    if len(recent_lows) >= 2 and curr_close <= peak_price * 0.92:
        for i_l in range(len(recent_lows) - 1):
            t1_idx, t1_val = recent_lows[i_l]
            for j_l in range(i_l + 1, len(recent_lows)):
                t2_idx, t2_val = recent_lows[j_l]
                if t2_idx - t1_idx < 3 or (n - t2_idx) > 45:
                    continue
                r_high = float(np.max(high_arr[t1_idx:t2_idx + 1]))
                rng_h = r_high - t1_val
                if rng_h <= t1_val * 0.03 or rng_h >= t1_val * 0.38 or (peak_price - t1_val) < 0.30 * rng_h:
                    continue
                if t2_val <= t1_val * 1.015 and float(np.min(close_arr[t1_idx:t2_idx + 1])) >= (t1_val - 0.30 * rng_h):
                    if (t2_idx - peak_idx) < 25:
                        continue
                    slow_decline_25 = True
                    tap1_price, tap2_price, range_high = t1_val, t2_val, r_high
                    tap3_price = float(np.min(low_arr[t2_idx:]))
                    if df_1h is not None and len(df_1h) >= 15:
                        h1_h = df_1h["High"].values.astype(float)
                        h1_sw = [float(h1_h[k]) for k in range(3, len(h1_h) - 3) if h1_h[k] == np.max(h1_h[k - 3:k + 4])]
                        rec_h1 = [v for v in h1_sw[-6:] if tap3_price * 1.005 <= v <= range_high * 0.96]
                        bos_level = float(rec_h1[-1]) if rec_h1 else float(np.max(high_arr[-4:-1]))
                    else:
                        bos_level = max(min(float(np.max(high_arr[-5:-1])), tap3_price + 0.35 * rng_h), tap3_price * 1.012)
                    if (tap2_price - 0.30 * (range_high - tap2_price)) <= curr_close <= range_high * 0.98:
                        tct_valid_range = True
                        break
            if tct_valid_range:
                break

    # --- EVALUATE ALL 6 PLAYBOOKS ---
    high_20d_prev = float(np.max(high_arr[-21:-1])) if n >= 22 else curr_close
    high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_close
    high_3d_prev = float(np.max(high_arr[-4:-1])) if n >= 5 else curr_close
    low_3d = float(np.min(low_arr[-3:]))

    is_20d_breakout = (curr_close >= high_20d_prev) and (paced_rvol >= 1.25) and (curr_close > ema50)
    is_holy_grail_pullback = (curr_close > ema50) and (ema20 > ema50) and (abs(low_arr[-1] - ema20) / ema20 <= 0.022 or abs(curr_close - ema20) / ema20 <= 0.022) and (curr_close >= open_arr[-1] or curr_close > prev_close)
    is_squeeze_breakout = is_bb_squeeze and (curr_close > ema50) and (curr_close >= high_3d_prev)
    is_rsi2_snapback = (curr_close > ema200 * 0.96) and (rsi2 <= 18.0 or low_arr[-1] <= float(df["BB_Lower"].iloc[-1]))
    day_rng = max(high_arr[-1] - low_arr[-1], 1e-6)
    is_gap_ignition = ((curr_close - prev_close) / prev_close >= 0.032) and (paced_rvol >= 1.7) and ((curr_close - low_arr[-1]) / day_rng >= 0.55) and (curr_close > ema50)

    playbook_cat = "TREND"
    if tct_valid_range and range_high and bos_level and tap3_price:
        playbook_name = "📐 Playbook 1: TCT Bottom Box"
        playbook_cat = "TCT"
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        effective_stop = max(min(tap3_price - 0.5 * atr14_1h, entry_ref * 0.98), entry_ref * 0.93)
        target_price = range_high
    elif is_20d_breakout:
        playbook_name = "🚀 Playbook 2: 20D Momentum Breakout"
        playbook_cat = "BREAKOUT"
        bos_level = high_20d_prev
        entry_ref = curr_close
        effective_stop = max(min(ema20, curr_close - 1.5 * atr14), curr_close * 0.94)
        target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
    elif is_gap_ignition:
        playbook_name = "🔥 Playbook 6: High-Vol Gap Ignition"
        playbook_cat = "BREAKOUT"
        bos_level = float(high_arr[-1]) if curr_close < high_arr[-1] else curr_close
        entry_ref = curr_close
        effective_stop = max(float(low_arr[-1]) - 0.2 * atr14, curr_close * 0.94)
        target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
    elif is_squeeze_breakout:
        playbook_name = "⚡ Playbook 4: Volatility Squeeze Coil"
        playbook_cat = "SWING_PULLBACK"
        bos_level = high_3d_prev
        entry_ref = curr_close
        effective_stop = max(low_3d - 0.3 * atr14, curr_close * 0.95)
        target_price = entry_ref + 2.8 * (entry_ref - effective_stop)
    elif is_holy_grail_pullback:
        playbook_name = "🎯 Playbook 3: 20-EMA Pullback Swing"
        playbook_cat = "SWING_PULLBACK"
        bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
        entry_ref = curr_close
        effective_stop = max(min(low_3d, ema20) - 0.5 * atr14, curr_close * 0.95)
        target_price = max(high_20d_prev, entry_ref + 2.4 * (entry_ref - effective_stop))
    elif is_rsi2_snapback:
        playbook_name = f"🪃 Playbook 5: RSI-2 Oversold Bounce (RSI2={rsi2:.0f})"
        playbook_cat = "OVERSOLD"
        bos_level = curr_close
        entry_ref = curr_close
        effective_stop = max(curr_close - 1.5 * atr14, curr_close * 0.945)
        target_price = max(ema20, entry_ref + 2.0 * (entry_ref - effective_stop))
    else:
        playbook_name = "📈 Standard Trend Swing"
        bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        effective_stop = max(min(entry_ref - 1.5 * atr14, entry_ref * 0.978), entry_ref * 0.935)
        target_price = entry_ref + 2.5 * (entry_ref - effective_stop)

    risk_ps = max(entry_ref - effective_stop, 0.0001)
    reward_ps = max(target_price - entry_ref, 0.0)
    r_mult = reward_ps / risk_ps
    shares_05 = max(1, int((account_size * 0.005) / risk_ps))
    pos_val = shares_05 * entry_ref
    tgt_pct = ((target_price - entry_ref) / entry_ref) * 100.0
    stp_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0

    # Fixed trigger comparison against prior close
    crossed_5d = (curr_close >= high_5d_prev) and (prev_close < high_5d_prev)

    if tct_valid_range and curr_close >= bos_level and r_mult >= 1.9:
        act, badge, dot, short_s, prio = "BUY NOW (TCT BOS)", "badge-tct-buy", "🟢", "🟢 TCT Buy", 0
        expl = f"TCT bottom breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
    elif is_20d_breakout or is_gap_ignition:
        act, badge, dot, short_s, prio = "BUY NOW (BREAKOUT)", "badge-tct-buy", "🟢", "🟢 Breakout", 0
        expl = f"{playbook_name}: Surge above ${bos_level:,.2f} on {paced_rvol:.1f}x pace volume."
    elif is_squeeze_breakout or is_holy_grail_pullback:
        act, badge, dot, short_s, prio = "SWING BUY (PULLBACK/COIL)", "badge-tct-buy", "🎯", "🎯 Swing Buy", 0
        expl = f"{playbook_name}: High-probability swing entry near ${entry_ref:,.2f}, stop ${effective_stop:,.2f}."
    elif is_rsi2_snapback:
        act, badge, dot, short_s, prio = "SWING BUY (OVERSOLD)", "badge-tct-watch", "🪃", "🪃 Oversold", 1
        expl = f"RSI-2 extreme oversold ({rsi2:.0f}) above 200-EMA. Target mean-reversion bounce to ${target_price:,.2f}."
    elif tct_valid_range and curr_close < bos_level:
        act, badge, dot, short_s, prio = "WATCHING TCT BOX", "badge-tct-watch", "📐", "📐 TCT Box", 1
        expl = f"Valid 25+ bar TCT bottom box. Buy when price closes above BOS ${bos_level:,.2f}."
    elif curr_close > ema50 and (curr_close >= ema20 * 0.99 or crossed_5d):
        act, badge, dot, short_s, prio = "HOLD / RIDE TREND", "badge-trend", "🔵", "🔵 Uptrend", 2
        expl = f"Holding above 20 & 50 EMA support. Swing target ${target_price:,.2f}, stop ${effective_stop:,.2f}."
    elif curr_close < ema50 and not tct_valid_range and not is_rsi2_snapback:
        act, badge, dot, short_s, prio = "SELL / AVOID", "badge-tct-sell", "🔴", "🔴 Below 50", 4
        expl = f"Below 50-day EMA (${ema50:,.2f}) with no active bottoming box. Protect capital."
    else:
        act, badge, dot, short_s, prio = "WAIT FOR TRIGGER", "badge-candidate", "🟡", "🟡 Wait", 3
        expl = f"Consolidating. Wait for breakout above ${bos_level:,.2f} before entering."

    return {
        "TCT_Valid_Range": tct_valid_range, "TCT_Model": playbook_name, "Playbook_Cat": playbook_cat,
        "TCT_Slow_25": slow_decline_25, "TCT_Liq_50M": liq_pass, "TCT_2R_Pass": bool(r_mult >= 2.0),
        "TCT_Action": act, "TCT_Badge": badge, "TCT_Dot": dot, "TCT_Short_Sig": short_s,
        "TCT_Explain": expl, "TCT_Priority": prio, "BOS_Entry": entry_ref, "BOS_Level": bos_level,
        "Target_Price": target_price, "Stop_Price": effective_stop, "R_Multiple": r_mult,
        "Target_Pct": tgt_pct, "Stop_Pct": stp_pct, "Shares_05Pct": shares_05, "Pos_Value": pos_val,
        "Dollar_Vol_M": dollar_vol_20 / 1e6, "RS_Diff": rs_diff, "RS_Leader": rs_leader,
        "RSI2": rsi2, "Paced_RVOL": paced_rvol, "Is_Squeeze": is_bb_squeeze,
        "Is_Pullback_Swing": is_holy_grail_pullback, "Is_Oversold_Swing": is_rsi2_snapback
    }

# --- ROBUST BATCH ENGINE + 8:00 AM HKT SETTLEMENT GLITCH PATCH ---
def _extract_ticker_df(data, ticker, total_tickers):
    if data is None or data.empty:
        return pd.DataFrame()
    if not isinstance(data.columns, pd.MultiIndex):
        return data.copy() if total_tickers == 1 else pd.DataFrame()
    if ticker in data.columns.get_level_values(0):
        return data[ticker].copy()
    if ticker in data.columns.get_level_values(1):
        return data.xs(ticker, axis=1, level=1).copy()
    return pd.DataFrame()

@st.cache_data(ttl=120)
def fetch_batch_market_data(tickers, account_size=100000, refresh_bucket=0):
    clean_tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]
    if not clean_tickers:
        return {}
    download_list = list(dict.fromkeys(clean_tickers + ["^GSPC"]))
    try:
        data_1d = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False, threads=True)
        # 5-day 15m intraday fetch patches Yahoo's 8:00 AM HKT daily settlement drop and provides fresh intraday High/Low/Close
        data_intraday = yf.download(clean_tickers[:50], period="5d", interval="15m", group_by="ticker", progress=False, threads=True)
    except Exception:
        return st.session_state.get("last_good_data", {})

    spy_ret_63d = 0.0
    try:
        spy_df = _extract_ticker_df(data_1d, "^GSPC", len(download_list)).dropna(subset=["Close"])
        if len(spy_df) >= 64:
            spy_ret_63d = ((float(spy_df["Close"].iloc[-1]) - float(spy_df["Close"].iloc[-64])) / float(spy_df["Close"].iloc[-64])) * 100.0
    except Exception:
        pass

    w_fund, w_tech, w_mom = settings["w_fund"] / 100.0, settings["w_tech"] / 100.0, settings["w_mom"] / 100.0
    results = {}

    for t in clean_tickers:
        try:
            df = _extract_ticker_df(data_1d, t, len(download_list))
            df.dropna(subset=["Close", "High", "Low"], inplace=True)
            if len(df) < 25:
                continue

            # 8:00 AM HKT Settlement Glitch Patch: Check if 15m intraday feed has a newer session date than 1d history
            try:
                df_intra = _extract_ticker_df(data_intraday, t, len(clean_tickers[:50])).dropna(subset=["Close"])
                if not df_intra.empty:
                    intra_dates = pd.to_datetime(df_intra.index).tz_localize(None).normalize()
                    last_intra_date = intra_dates[-1]
                    last_1d_date = pd.to_datetime(df.index[-1]).tz_localize(None).normalize()
                    today_slice = df_intra[intra_dates == last_intra_date]
                    if not today_slice.empty:
                        i_open = float(today_slice["Open"].iloc[0])
                        i_high = float(today_slice["High"].max())
                        i_low = float(today_slice["Low"].min())
                        i_close = float(today_slice["Close"].iloc[-1])
                        i_vol = float(today_slice["Volume"].sum())
                        if last_intra_date > last_1d_date:
                            # Append missing settled session row so 8 AM HKT never reverts to prior day!
                            new_row = pd.DataFrame({"Open": [i_open], "High": [i_high], "Low": [i_low], "Close": [i_close], "Volume": [i_vol]}, index=[last_intra_date])
                            df = pd.concat([df, new_row])
                        elif last_intra_date == last_1d_date:
                            df.iloc[-1, df.columns.get_loc("Close")] = i_close
                            df.iloc[-1, df.columns.get_loc("High")] = max(float(df["High"].iloc[-1]), i_high)
                            df.iloc[-1, df.columns.get_loc("Low")] = min(float(df["Low"].iloc[-1]), i_low)
            except Exception:
                pass

            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
            day_high = float(df["High"].iloc[-1])
            day_low = float(df["Low"].iloc[-1])
            change = close - prev_close
            change_pct = (change / prev_close) * 100.0 if prev_close != 0 else 0.0

            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
            df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
            df["High20"] = df["High"].rolling(20).max()
            df["High52"] = df["High"].rolling(252, min_periods=25).max()
            df["Vol20"] = df["Volume"].fillna(0).rolling(20).mean()

            df["BB_Mid"] = df["Close"].rolling(20).mean()
            df["BB_Std"] = df["Close"].rolling(20).std()
            df["BB_Upper"] = df["BB_Mid"] + (df["BB_Std"] * 2)
            df["BB_Lower"] = df["BB_Mid"] - (df["BB_Std"] * 2)

            delta = df["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
            df["RSI"] = 100 - (100 / (1 + (gain / (loss + 1e-9))))
            rsi = float(df["RSI"].iloc[-1]) if not np.isnan(df["RSI"].iloc[-1]) else 50.0

            ema12 = df["Close"].ewm(span=12, adjust=False).mean()
            ema26 = df["Close"].ewm(span=26, adjust=False).mean()
            df["MACD"] = ema12 - ema26
            df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
            df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]

            vol20 = float(df["Vol20"].iloc[-1]) if not np.isnan(df["Vol20"].iloc[-1]) else 0.0
            rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
            high20_prev = float(df["High20"].iloc[-2]) if len(df) >= 22 else close
            ema20_val, ema50_val = float(df["EMA20"].iloc[-1]), float(df["EMA50"].iloc[-1])
            above_ema50 = close > ema50_val
            above_ema200 = close > float(df["EMA200"].iloc[-1]) if len(df) >= 200 else True
            within_52w = (close / float(df["High52"].iloc[-1])) >= 0.90 if float(df["High52"].iloc[-1]) > 0 else False

            pb_info = analyze_six_playbooks(df, account_size=account_size, spy_ret_63d=spy_ret_63d)
            is_breakout = (close >= high20_prev) and (pb_info["Paced_RVOL"] >= 1.25)

            if is_breakout and above_ema50:
                state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Cleared 20D high (${high20_prev:,.2f}) on {pb_info['Paced_RVOL']:.1f}x vol"
            elif above_ema50 and close > ema20_val:
                state, badge_class, reason = "Active Trend", "badge-trend", "Holding above 20-day & 50-day EMA support"
            elif close < ema50_val:
                state, badge_class, reason = "Support Break", "badge-caution", "Below 50-day EMA support level"
            else:
                state, badge_class, reason = "Entry Candidate", "badge-candidate", "Consolidating near support; setup developing"

            tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 15) + (30 if pb_info["Paced_RVOL"] >= 1.2 else 10)
            mom_score = (50 if is_breakout else 20) + (50 if within_52w else 20)
            composite = int((80 * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))

            rec = {
                "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
                "Day_High": day_high, "Day_Low": day_low, "RSI": rsi, "RVOL": rvol,
                "Above_EMA50": above_ema50, "Above_EMA200": above_ema200, "Is_Breakout": is_breakout,
                "EMA20_Val": ema20_val, "EMA50_Val": ema50_val,
                "State": state, "Badge": badge_class, "Reason": reason, "Score": composite,
                "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
            }
            rec.update(pb_info)
            results[t] = rec
        except Exception:
            continue

    if results:
        st.session_state.last_good_data.update(results)
    else:
        return {k: v for k, v in st.session_state.get("last_good_data", {}).items() if k in clean_tickers}
    return results

@st.cache_data(ttl=180)
def fetch_single_ticker_data(sym, account_size=100000):
    res = fetch_batch_market_data([sym], account_size=account_size)
    if sym in res:
        return res[sym]
    try:
        t = yf.Ticker(sym)
        df = t.history(period="1y", interval="1d")
        if df.empty or len(df) < 20:
            return None
        df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
        df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
        df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
        df["Vol20"] = df["Volume"].fillna(0).rolling(20).mean()
        df["BB_Mid"] = df["Close"].rolling(20).mean()
        df["BB_Std"] = df["Close"].rolling(20).std()
        df["BB_Upper"] = df["BB_Mid"] + (df["BB_Std"] * 2)
        df["BB_Lower"] = df["BB_Mid"] - (df["BB_Std"] * 2)
        delta = df["Close"].diff()
        df["RSI"] = 100 - (100 / (1 + (delta.where(delta > 0, 0).rolling(14).mean() / ((-delta.where(delta < 0, 0)).rolling(14).mean() + 1e-9))))
        df["MACD"] = df["Close"].ewm(span=12, adjust=False).mean() - df["Close"].ewm(span=26, adjust=False).mean()
        df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
        df["MACD_Hist"] = df["MACD"] - df["MACD_Signal"]
        close = float(df["Close"].iloc[-1])
        prev = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
        pb = analyze_six_playbooks(df, account_size=account_size)
        rec = {"Ticker": sym, "Price": close, "Change": close - prev, "Change_Pct": ((close - prev)/prev)*100 if prev else 0,
               "Day_High": float(df["High"].iloc[-1]), "Day_Low": float(df["Low"].iloc[-1]),
               "RSI": float(df["RSI"].iloc[-1]), "RVOL": 1.0, "EMA20_Val": float(df["EMA20"].iloc[-1]), "EMA50_Val": float(df["EMA50"].iloc[-1]),
               "State": "Active", "Badge": "badge-trend", "Reason": pb["TCT_Explain"], "Score": 75, "History": df}
        rec.update(pb)
        return rec
    except Exception:
        return None

@st.cache_data(ttl=86400)
def fetch_ticker_fundamentals(sym):
    data = {"Market Cap": "N/A", "Trailing P/E": "N/A", "EPS (TTM)": "N/A", "Target Price": "N/A", "52W High": "N/A", "52W Low": "N/A", "Business Summary": "No corporate overview provided."}
    try:
        t = yf.Ticker(sym)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            pass
        fast = getattr(t, "fast_info", None)
        data["Market Cap"] = info.get("marketCap") or (getattr(fast, "market_cap", None) if fast else "N/A") or "N/A"
        data["Trailing P/E"] = info.get("trailingPE") or "N/A"
        data["EPS (TTM)"] = info.get("trailingEps") or "N/A"
        data["Target Price"] = info.get("targetMeanPrice") or "N/A"
        data["52W High"] = info.get("fiftyTwoWeekHigh") or (getattr(fast, "year_high", None) if fast else "N/A") or "N/A"
        data["52W Low"] = info.get("fiftyTwoWeekLow") or (getattr(fast, "year_low", None) if fast else "N/A") or "N/A"
        data["Business Summary"] = info.get("longBusinessSummary", "No corporate overview provided.")
    except Exception:
        pass
    return data

# --- RATE-LIMIT-SAFE EARNINGS CALENDAR (90-DAY LOOKAHEAD + FALLBACK) ---
@st.cache_data(ttl=21600)
def fetch_upcoming_earnings_safe(tickers):
    out = {}
    now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    stock_only = [s for s in dict.fromkeys(tickers) if not any(c in s for c in ["=X", "=F", "-USD", "^", "."]) and s not in {"SLV", "GLD", "SOXL", "UGL"}]
    for sym in stock_only[:35]:
        try:
            t = yf.Ticker(sym)
            found_dt = None
            try:
                cal = t.calendar
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date") or cal.get("earningsDate")
                    if ed:
                        found_dt = ed[0] if isinstance(ed, list) else ed
                elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                    found_dt = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                pass
            if found_dt is None:
                try:
                    ed_df = t.get_earnings_dates(limit=6)
                    if ed_df is not None and not ed_df.empty:
                        fut_dates = [d.to_pydatetime().replace(tzinfo=None) for d in ed_df.index if d.to_pydatetime().replace(tzinfo=None) >= now_dt]
                        if fut_dates:
                            found_dt = min(fut_dates)
                except Exception:
                    pass
            if found_dt is not None:
                dt_p = pd.to_datetime(found_dt).to_pydatetime().replace(tzinfo=None, hour=0, minute=0, second=0)
                days_diff = (dt_p - now_dt).days
                if 0 <= days_diff <= 90:
                    out[sym] = (days_diff, dt_p.strftime("%Y-%m-%d"))
        except Exception:
            continue
    return out

def render_sparkline(prices, is_pos):
    fig = go.Figure(go.Scatter(y=prices, mode='lines', line=dict(color="#15803d" if is_pos else "#b91c1c", width=1.8)))
    fig.update_layout(height=42, width=115, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig

def render_watchlist_reorder_panel(folder_name, key_prefix="wl"):
    st.markdown('<div style="background:#fff; border:1px solid #dcd6cb; border-radius:8px; padding:12px 16px; margin-bottom:12px;">', unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2.2, 2.2, 1.6])
    with c1:
        st.markdown(f"**✏️ Editing Watchlist: `{folder_name}`**")
        st.caption("Tap ⏫ (Top), ⬆️ (Up), ⬇️ (Down), or 🗑️ (Remove).")
    with c2:
        new_f = st.text_input("New Watchlist Name", placeholder="e.g. Swing Candidates", key=f"{key_prefix}_nf", label_visibility="collapsed")
        if st.button("➕ Create New Watchlist", key=f"{key_prefix}_btn_nf") and new_f.strip():
            if new_f.strip() not in watchlists:
                watchlists[new_f.strip()] = []
                sync_watchlists_to_github(watchlists)
                st.rerun()
    with c3:
        if st.button("💾 Save & Sync Order to GitHub", type="primary", use_container_width=True, key=f"{key_prefix}_sync"):
            ok, msg = sync_watchlists_to_github(watchlists)
            st.success(msg) if ok else st.warning(msg)

    syms = watchlists.get(folder_name, [])
    if syms:
        ec1, ec2 = st.columns(2)
        half = (len(syms) + 1) // 2
        for i, s in enumerate(syms):
            with (ec1 if i < half else ec2):
                r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
                r1.markdown(f"**{i+1}. {s}**")
                if r2.button("⏫", key=f"{key_prefix}_t_{folder_name}_{s}_{i}", disabled=(i == 0)):
                    syms.pop(i); syms.insert(0, s); save_json(DATA_FILE, watchlists); st.rerun()
                if r3.button("⬆️", key=f"{key_prefix}_u_{folder_name}_{s}_{i}", disabled=(i == 0)):
                    syms[i-1], syms[i] = syms[i], syms[i-1]; save_json(DATA_FILE, watchlists); st.rerun()
                if r4.button("⬇️", key=f"{key_prefix}_d_{folder_name}_{s}_{i}", disabled=(i == len(syms)-1)):
                    syms[i+1], syms[i] = syms[i], syms[i+1]; save_json(DATA_FILE, watchlists); st.rerun()
                if r5.button("🗑️", key=f"{key_prefix}_x_{folder_name}_{s}_{i}"):
                    syms.pop(i); sync_watchlists_to_github(watchlists); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- MACRO BANNER & REGIME TRAFFIC LIGHT ---
MACRO_SYMBOLS = {
    "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
    "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F", "DXY (USD)": "DX-Y.NYB",
    "USD/JPY": "JPY=X", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"
}

@st.cache_data(ttl=300)
def fetch_macro_and_regime():
    ticks = list(MACRO_SYMBOLS.values())
    out = {}
    regime = {"label": "🟢 MARKET REGIME: BULLISH — Favorable for TCT & Swing Setups", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
    try:
        df = yf.download(ticks, period="3mo", interval="1d", group_by="ticker", progress=False, threads=True)
        for name, sym in MACRO_SYMBOLS.items():
            sub = _extract_ticker_df(df, sym, len(ticks)).dropna(subset=["Close"])
            if len(sub) >= 2:
                c, pc = float(sub["Close"].iloc[-1]), float(sub["Close"].iloc[-2])
                out[name] = (c, c - pc, ((c - pc) / pc) * 100.0 if pc else 0.0)
        sp = _extract_ticker_df(df, "^GSPC", len(ticks)).dropna(subset=["Close"])
        if len(sp) >= 50:
            sp_c = float(sp["Close"].iloc[-1])
            sp_20 = float(sp["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            sp_50 = float(sp["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
            vix_c = out.get("VIX", (18.0, 0, 0))[0]
            if sp_c > sp_50 and sp_c > sp_20 and vix_c < 21.0:
                regime = {"label": f"🟢 MARKET REGIME: BULLISH (S&P Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for Swing & TCT Buys", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
            elif sp_c < sp_50 or vix_c >= 25.0:
                regime = {"label": f"🔴 MARKET REGIME: RISK-OFF / CAUTION (S&P Below 50 EMA or VIX {vix_c:.1f}) — Protect Capital, Avoid Aggressive Buys", "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"}
            else:
                regime = {"label": f"🟡 MARKET REGIME: CONSOLIDATING (VIX {vix_c:.1f}) — Focus on 20-EMA Pullbacks & True TCT Bottoms", "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"}
    except Exception:
        pass
    return out, regime

# --- SIDEBAR ---
st.sidebar.markdown("""<div style="padding: 8px 0 16px 0;"><span style="display:inline-block;width:9px;height:9px;background:#22c55e;border-radius:50%;margin-right:6px;"></span><span style="font-size:0.82rem;font-weight:600;color:#a1a1aa;">6-PLAYBOOK ENGINE v11.0</span><h2 style="color:#f4efe6 !important;margin:4px 0 0 0;font-size:1.35rem;">Ledger</h2><span style="font-size:0.74rem;color:#c5a059;text-transform:uppercase;letter-spacing:0.08em;font-weight:600;">Momentum · Swing · TCT</span></div>""", unsafe_allow_html=True)

navigation = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "⚡ Live Real-Time Quotes", "Screener", "Watchlist", "Precious Metals, Crypto & Currency", "News & Earnings", "Settings"],
    key="nav_radio", label_visibility="collapsed", on_change=clear_inspection
)
st.sidebar.markdown("---")
st.sidebar.markdown(f"""<div style="font-size:0.74rem;color:#a1a1aa;">{"🟢 GitHub Auto-Sync Active" if get_github_token() else "🟡 Local Mode"}<br>Tap any <b>Stock Symbol</b> for Chart</div>""", unsafe_allow_html=True)

# --- TOP MACRO RIBBON (HIDDEN ON LIVE QUOTES PAGE) ---
if navigation != "⚡ Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
    macro_data, regime_info = fetch_macro_and_regime()
    if macro_data:
        cards_html = "".join([f'<div class="macro-card"><div class="macro-title">{k}</div><div class="macro-price">{p:,.2f}</div><div class="{"tick-pos" if c>=0 else "tick-neg"}">{"▲ +" if c>=0 else "▼ "}{c:.2f} ({"+" if c>=0 else ""}{pct:.2f}%)</div></div>' for k, (p, c, pct) in macro_data.items()])
        st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="background:{regime_info["bg"]};border:1px solid {regime_info["border"]};color:{regime_info["color"]};padding:8px 14px;border-radius:8px;font-size:0.82rem;font-weight:600;margin-bottom:14px;">{regime_info["label"]}</div>', unsafe_allow_html=True)

# ==============================================================================
# ROUTING: INSPECT DOSSIER OR PAGES
# ==============================================================================
if st.session_state.inspect_symbol is not None:
    sym = st.session_state.inspect_symbol
    c_b, c_t = st.columns([1.2, 8.8])
    if c_b.button("⬅ Back", type="primary"):
        clear_inspection()
        st.rerun()
    c_t.markdown(f"<h1>{sym} · 6-Playbook Technical & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)
    if d is not None:
        df_hist = d["History"]
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        f1.metric("Live Price", f"${d['Price']:,.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Active Signal", d["TCT_Action"])
        f3.metric("Buy Trigger", f"${d['BOS_Level']:,.2f}")
        f4.metric("Take Profit Target", f"${d['Target_Price']:,.2f}", f"+{d['Target_Pct']:.1f}%")
        f5.metric("Safety Stop-Loss", f"${d['Stop_Price']:,.2f}", f"{d['Stop_Pct']:.1f}%", delta_color="inverse")
        f6.metric("0.5% Risk Size", f"{d['Shares_05Pct']} shs", f"{d['R_Multiple']:.1f}R")
        st.markdown("---")
        c_ctrl, c_plot = st.columns([1.2, 3.8])
        with c_ctrl:
            show_lines = st.checkbox("Target / Buy / Stop Lines", value=True)
            show_e20 = st.checkbox("EMA 20 (Gold)", value=True)
            show_e50 = st.checkbox("EMA 50 (Green)", value=True)
            show_e200 = st.checkbox("EMA 200 (Purple)", value=False)
            show_bb = st.checkbox("Bollinger Bands", value=False)
            st.markdown("---")
            st.markdown(f"**Playbook:** `{d['TCT_Model']}`\n\n**Action:** `{d['TCT_Action']}`\n\n**Buy Trigger:** `${d['BOS_Level']:,.2f}`\n\n**Target:** `${d['Target_Price']:,.2f}` (+{d['Target_Pct']:.1f}%)\n\n**Stop:** `${d['Stop_Price']:,.2f}` ({d['Stop_Pct']:.1f}%)\n\n**Size:** `{d['Shares_05Pct']} shs` (${d['Pos_Value']:,.0f})\n\n**RSI(14) / RSI(2):** `{d['RSI']:.1f}` / `{d['RSI2']:.0f}`\n\n*{d['TCT_Explain']}*")
        with c_plot:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.62, 0.19, 0.19])
            fig.add_trace(go.Candlestick(x=df_hist.index, open=df_hist['Open'], high=df_hist['High'], low=df_hist['Low'], close=df_hist['Close'], name="Price"), row=1, col=1)
            if show_e20: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA20'], line=dict(color="#d4af37", width=1.5), name="EMA 20"), row=1, col=1)
            if show_e50: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA50'], line=dict(color="#15803d", width=1.5), name="EMA 50"), row=1, col=1)
            if show_e200: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA200'], line=dict(color="#7c3aed", width=1.5), name="EMA 200"), row=1, col=1)
            if show_bb:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Upper'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Lower'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Lower"), row=1, col=1)
            if show_lines:
                fig.add_hline(y=d["Target_Price"], line_dash="dash", line_color="#15803d", line_width=1.8, annotation_text=f"TARGET: ${d['Target_Price']:,.2f}", row=1, col=1)
                fig.add_hline(y=d["BOS_Level"], line_dash="dot", line_color="#2563eb", line_width=1.6, annotation_text=f"BUY TRIGGER: ${d['BOS_Level']:,.2f}", row=1, col=1)
                fig.add_hline(y=d["Stop_Price"], line_dash="dash", line_color="#b91c1c", line_width=1.8, annotation_text=f"STOP: ${d['Stop_Price']:,.2f}", row=1, col=1)
            v_cols = ['#15803d' if c >= o else '#b91c1c' for c, o in zip(df_hist['Close'], df_hist['Open'])]
            fig.add_trace(go.Bar(x=df_hist.index, y=df_hist['Volume'], marker_color=v_cols, name="Vol"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD'], line=dict(color="#2563eb", width=1.2), name="MACD"), row=3, col=1)
            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD_Signal'], line=dict(color="#ea580c", width=1.2), name="Signal"), row=3, col=1)
            fig.update_layout(height=620, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="white", plot_bgcolor="white", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)
        st.write(funds.get("Business Summary", ""))
    else:
        st.error(f"Could not load data for {sym}.")

elif navigation == "Dashboard":
    st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
    all_monitored = get_all_monitored_tickers()
    stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])

    if stock_records:
        best = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + (15 if x["RS_Leader"] else 0) + x["Score"])
        arr = "▲ +" if best["Change"] >= 0 else "▼ "
        st.markdown(f"""
        <div style="background:#0f291e;border-radius:10px;padding:18px 24px;color:#fbf9f4;margin-bottom:18px;">
            <div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.1em;color:#c5a059;font-weight:700;">STANDOUT SETUP · {best['TCT_Action']} · {best['TCT_Model']}</div>
            <div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
                <div>
                    <a href="?inspect={best['Ticker']}" target="_self" class="hero-ticker-link">📊 {best['Ticker']}</a>
                    <span style="font-size:1.25rem;color:#fff;margin-left:10px;font-weight:700;">${best['Price']:,.2f}</span>
                    <span style="color:{'#4ade80' if best['Change']>=0 else '#f87171'};font-weight:700;margin-left:8px;">{arr}${abs(best['Change']):.2f} ({'+' if best['Change']>=0 else ''}{best['Change_Pct']:.2f}%)</span>
                    <div style="color:#cbd5e1;font-size:0.88rem;margin-top:6px;"><b>Buy Trigger:</b> ${best['BOS_Level']:,.2f} · <b>Target:</b> ${best['Target_Price']:,.2f} (+{best['Target_Pct']:.1f}%) · <b>Stop:</b> ${best['Stop_Price']:,.2f} ({best['Stop_Pct']:.1f}%) · <b>0.5% Size:</b> {best['Shares_05Pct']} shs ({best['R_Multiple']:.1f}R)</div>
                </div>
                <div style="text-align:right;"><div style="font-size:2.1rem;font-weight:700;color:#c5a059;">{best['Score']}</div><div style="font-size:0.68rem;color:#94a3b8;">SCORE</div></div>
            </div>
        </div>""", unsafe_allow_html=True)

    col_l, col_r = st.columns([1.95, 1.05])
    with col_l:
        t_w, t_m, t_c = st.tabs([f"Watchlist News ({len(all_monitored)})", "General Market", "Metals, Crypto & USD"])
        with t_w:
            wl_n = fetch_news_pool([(f'"{s}" stock', s) for s in all_monitored[:25]], settings["news_limit"], settings["max_news_age_hours"])
            if wl_n:
                st.markdown('<div class="scroll-news-box">' + "".join([f'<div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:11px 15px;margin-bottom:8px;"><div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;"><span><span class="ticker-news-badge">[{a["ticker"]}]</span><b>{a["publisher"]}</b><span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight:600;font-size:0.92rem;margin-top:4px;"><a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">{a["title"]}</a></div></div>' for a in wl_n]) + '</div>', unsafe_allow_html=True)
        with t_m:
            mk_n = fetch_news_pool([("S&P 500 Nasdaq stock market", "MARKET"), ("Wall Street stocks Federal Reserve", "MACRO")], settings["news_limit"], settings["max_news_age_hours"])
            if mk_n:
                st.markdown('<div class="scroll-news-box">' + "".join([f'<div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:11px 15px;margin-bottom:8px;"><div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;"><span><b>{a["publisher"]}</b><span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight:600;font-size:0.92rem;margin-top:4px;"><a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">{a["title"]}</a></div></div>' for a in mk_n]) + '</div>', unsafe_allow_html=True)
        with t_c:
            mc_n = fetch_news_pool([("gold silver copper commodities market", "METALS"), ("Bitcoin Ethereum Solana XRP crypto", "CRYPTO"), ("US Dollar Index DXY USD JPY EUR", "FX")], settings["news_limit"], settings["max_news_age_hours"])
            if mc_n:
                st.markdown('<div class="scroll-news-box">' + "".join([f'<div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:11px 15px;margin-bottom:8px;"><div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;"><span><span class="ticker-news-badge">[{a["ticker"]}]</span><b>{a["publisher"]}</b><span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight:600;font-size:0.92rem;margin-top:4px;"><a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">{a["title"]}</a></div></div>' for a in mc_n]) + '</div>', unsafe_allow_html=True)

    with col_r:
        st.subheader("Action Signals Snapshot")
        if stock_records:
            for r in sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))[:10]:
                arr_s = "▲ +" if r["Change"] >= 0 else "▼ -"
                clr_s = "#15803d" if r["Change"] >= 0 else "#b91c1c"
                st.markdown(f"""
                <div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:10px 13px;margin-bottom:8px;">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div><a href="?inspect={r['Ticker']}" target="_self" class="ticker-link" style="font-size:1.05rem;">📊 {r['Ticker']}</a> <span class="badge {r['TCT_Badge']}" style="margin-left:5px;">{r['TCT_Action']}</span></div>
                        <div style="font-weight:700;font-size:0.9rem;">${r['Price']:,.2f} <span style="color:{clr_s};font-size:0.78rem;">{arr_s}${abs(r['Change']):.2f} ({r['Change_Pct']:+.2f}%)</span></div>
                    </div>
                    <div style="font-size:0.73rem;color:#52525b;margin-top:4px;"><b>{r['TCT_Model']}</b> · Buy: <b>${r['BOS_Level']:,.2f}</b> · Tgt: <b style="color:#15803d;">${r['Target_Price']:,.2f}</b> · Stop: <b style="color:#b91c1c;">${r['Stop_Price']:,.2f}</b></div>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("Loading market snapshot... Tap 🔄 Refresh if needed.")

elif navigation == "⚡ Live Real-Time Quotes":
    st.markdown("""<style>.block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; padding-left: 1.1rem !important; padding-right: 1.1rem !important; }</style>""", unsafe_allow_html=True)
    folder_names = list(watchlists.keys())
    c1, c2, c3, c4, c5, c6, c7 = st.columns([1.8, 1.9, 1.9, 1.2, 1.3, 0.7, 1.1])
    with c1:
        sel_folder = st.selectbox("Watchlist", folder_names + ["All Watchlists Combined"], index=0, label_visibility="collapsed")
    with c2:
        board_mode = st.selectbox("Mode", ["📊 Custom Signal Board (Large Font)", "⚡ TradingView Streaming (Tick-by-Tick)"], index=0, label_visibility="collapsed")
    with c3:
        live_sort = st.selectbox("Rank", ["Rank: My Saved Order", "Rank: 🟢 Action Signal (Buy First)", "Rank: 📈 Day % Change (Gainers)", "Rank: 📉 Day % Change (Losers)", "Rank: 🔥 Relative Strength vs S&P", "Rank: 💯 Composite Score"], index=0, label_visibility="collapsed")
    with c4:
        auto_ref = st.selectbox("Timer", ["⏱️ Auto: Off", "⏱️ Auto: 15s", "⏱️ Auto: 30s", "⏱️ Auto: 60s"], index=0, label_visibility="collapsed")
    with c5:
        if sel_folder != "All Watchlists Combined":
            qa = st.text_input("Add", placeholder=f"+ Add to {sel_folder}", label_visibility="collapsed").upper().strip()
            if qa and qa not in watchlists[sel_folder]:
                watchlists[sel_folder].append(qa)
                sync_watchlists_to_github(watchlists)
                st.rerun()
    with c6:
        if st.button("🔄", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with c7:
        ed_live = st.checkbox("✏️ Edit List", value=False)

    if ed_live:
        render_watchlist_reorder_panel(sel_folder if sel_folder != "All Watchlists Combined" else folder_names[0], key_prefix="lv")

    active_syms = get_all_monitored_tickers() if sel_folder == "All Watchlists Combined" else list(watchlists.get(sel_folder, []))
    sec_map = {"⏱️ Auto: Off": None, "⏱️ Auto: 15s": 15, "⏱️ Auto: 30s": 30, "⏱️ Auto: 60s": 60}
    run_sec = sec_map.get(auto_ref)

    def render_live_board():
        bkt = int(time.time() // run_sec) if run_sec else int(time.time() // 120)
        live_recs = fetch_batch_market_data(active_syms, account_size=settings["account_size"], refresh_bucket=bkt)
        ord_syms = [s for s in active_syms if s in live_recs]
        unloaded_syms = [s for s in active_syms if s not in live_recs]

        if live_sort == "Rank: 🟢 Action Signal (Buy First)":
            ord_syms = sorted(ord_syms, key=lambda s: (live_recs[s]["TCT_Priority"], -live_recs[s]["Score"]))
        elif live_sort == "Rank: 📈 Day % Change (Gainers)":
            ord_syms = sorted(ord_syms, key=lambda s: live_recs[s]["Change_Pct"], reverse=True)
        elif live_sort == "Rank: 📉 Day % Change (Losers)":
            ord_syms = sorted(ord_syms, key=lambda s: live_recs[s]["Change_Pct"])
        elif live_sort == "Rank: 🔥 Relative Strength vs S&P":
            ord_syms = sorted(ord_syms, key=lambda s: live_recs[s]["RS_Diff"], reverse=True)
        elif live_sort == "Rank: 💯 Composite Score":
            ord_syms = sorted(ord_syms, key=lambda s: live_recs[s]["Score"], reverse=True)

        display_all = ord_syms + unloaded_syms

        if board_mode.startswith("📊 Custom Signal Board"):
            def build_half_html(slice_syms):
                rows = ""
                for sym in slice_syms:
                    if sym in live_recs:
                        d = live_recs[sym]
                        chg, pct = d["Change"], d["Change_Pct"]
                        clr = "#15803d" if chg >= 0 else "#b91c1c"
                        tick_arrow = "▲" if chg >= 0 else "▼"
                        sign = "+" if chg >= 0 else "-"
                        rows += (f'<tr><td>{d.get("TCT_Short_Sig", "🔵 Uptrend")}</td>'
                                 f'<td><a href="?rt_chart={sym}" target="_self" class="rt-sym-link">{sym}</a><a href="?inspect={sym}" target="_self" class="rt-dossier-link">📋</a></td>'
                                 f'<td style="font-weight:800;color:{clr};">{tick_arrow} ${d["Price"]:,.2f}</td>'
                                 f'<td style="color:{clr};font-weight:700;">{sign}${abs(chg):.2f} ({pct:+.2f}%)</td>'
                                 f'<td style="color:#15803d;font-weight:600;">${d["Day_High"]:,.2f}</td>'
                                 f'<td style="color:#b91c1c;font-weight:600;">${d["Day_Low"]:,.2f}</td></tr>')
                    else:
                        rows += f'<tr><td>⚪ N/A</td><td><a href="?rt_chart={sym}" target="_self" class="rt-sym-link">{sym}</a></td><td>—</td><td>—</td><td>—</td><td>—</td></tr>'
                return f'<table class="live-quote-table"><thead><tr><th>Signal</th><th>Symbol</th><th>Live Price</th><th>Day Chg ($ / %)</th><th>High</th><th>Low</th></tr></thead><tbody>{rows}</tbody></table>'

            if display_all:
                mid = (len(display_all) + 1) // 2
                st.markdown(f'<div class="live-board-grid"><div>{build_half_html(display_all[:mid])}</div><div>{build_half_html(display_all[mid:]) if display_all[mid:] else ""}</div></div>', unsafe_allow_html=True)
                st.caption(f"🟢 Buy Now · 🎯 Swing Buy · 🪃 Oversold · 📐 TCT Box · 🔵 Uptrend · 🔴 Below 50  |  **Tap Symbol** for Bottom Live Chart · Tap **📋** for Full Dossier  |  *Updated: {datetime.now().strftime('%H:%M:%S')}*")
            else:
                st.info("No stocks in this folder yet.")
        else:
            # TRADINGVIEW STREAMING MODE (UNCLIPPED 84PX RUNNER TAPE + 2-COLUMN QUOTES)
            if display_all:
                tape_syms = [{"proName": "FOREXCOM:SPXUSD", "title": "S&P 500"}, {"proName": "FOREXCOM:NSXUSD", "title": "Nasdaq 100"}, {"proName": "BITSTAMP:BTCUSD", "title": "BTC"}] + [{"proName": s, "title": s} for s in display_all[:25]]
                components.html(f"""
                <div class="tradingview-widget-container" style="height:80px;">
                  <div class="tradingview-widget-container__widget"></div>
                  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
                  {{"symbols": {json.dumps(tape_syms)}, "showSymbolLogo": true, "isTransparent": false, "displayMode": "regular", "colorTheme": "light", "locale": "en"}}
                  </script>
                </div>""", height=84)

                mid = (len(display_all) + 1) // 2
                l_tv = [{"name": s, "displayName": f"{live_recs[s]['TCT_Dot']} {s}" if s in live_recs else s} for s in display_all[:mid]]
                r_tv = [{"name": s, "displayName": f"{live_recs[s]['TCT_Dot']} {s}" if s in live_recs else s} for s in display_all[mid:]]
                wh = max(460, mid * 38 + 100)
                tc1, tc2 = st.columns(2)
                with tc1:
                    components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>{{"width": "100%", "height": {wh}, "symbolsGroups": {json.dumps([{"name": f"{sel_folder} (Col 1)", "symbols": l_tv}])}, "showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}</script></div>""", height=wh + 16)
                with tc2:
                    if r_tv:
                        components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>{{"width": "100%", "height": {wh}, "symbolsGroups": {json.dumps([{"name": f"{sel_folder} (Col 2)", "symbols": r_tv}])}, "showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}</script></div>""", height=wh + 16)
                pills_b = "".join([f'<a href="?rt_chart={s}" target="_self" class="pill">{live_recs[s]["TCT_Dot"] if s in live_recs else "📈"} {s}</a>' for s in display_all])
                st.markdown(f"<div><b>Tap symbol for Bottom Live Chart:</b> {pills_b}</div>", unsafe_allow_html=True)

    if run_sec and hasattr(st, "fragment"):
        @st.fragment(run_every=run_sec)
        def _frag():
            render_live_board()
        _frag()
    else:
        render_live_board()

    if st.session_state.rt_chart_symbol:
        cs = st.session_state.rt_chart_symbol
        st.markdown("---")
        cc1, cc2, cc3, cc4 = st.columns([3.5, 2.0, 2.0, 1.5])
        cc1.markdown(f"### 📈 Live Streaming Chart: `{cs}`")
        rt_int = cc2.selectbox("TF", ["5", "15", "60", "240", "D"], format_func=lambda x: {"5": "5m", "15": "15m", "60": "1H (BOS)", "240": "4H", "D": "Daily"}[x], index=2, label_visibility="collapsed")
        if cc3.button(f"📋 Open {cs} Full Dossier", use_container_width=True):
            st.session_state.inspect_symbol = cs
            st.rerun()
        if cc4.button("✖ Close Chart", type="primary", use_container_width=True):
            st.session_state.rt_chart_symbol = None
            st.rerun()
        components.html(f"""<div class="tradingview-widget-container" style="height:480px;width:100%;"><div id="tv_rt" style="height:465px;width:100%;"></div><script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script><script type="text/javascript">new TradingView.widget({{"autosize":true,"symbol":"{cs}","interval":"{rt_int}","timezone":"America/New_York","theme":"light","style":"1","locale":"en","studies":["EMA@tv-basicstudies","RSI@tv-basicstudies"],"container_id":"tv_rt"}});</script></div>""", height=485)

elif navigation == "Screener":
    st.markdown("<h1>6-Playbook Market Screener</h1>", unsafe_allow_html=True)
    all_wl = get_all_monitored_tickers()
    full_univ = list(dict.fromkeys([s for sl in GICS_SECTORS.values() for s in sl] + all_wl))

    u_mode = st.radio("1. Select Scan Universe", [f"Expanded Liquid Market (~{len(full_univ)} Stocks)", f"My Watchlists Only ({len(all_wl)} Stocks — Instant)"], horizontal=True)
    target_u = all_wl if u_mode.startswith("My Watchlists") else full_univ

    st.markdown("### 2. One-Tap Multi-Strategy Preset Scans")
    p1, p2, p3, p4, p5 = st.columns(5)
    if p1.button("🟢 All 'BUY NOW'", use_container_width=True, type="primary"):
        s_d = fetch_batch_market_data(target_u, account_size=settings["account_size"])
        st.session_state.screener_matches = sorted([d for d in s_d.values() if d["TCT_Priority"] == 0], key=lambda x: -x["Score"])
        st.session_state.screener_title = "🟢 All 'BUY NOW' Triggers Across All 6 Playbooks"
    if p2.button("📐 TCT Bottoms", use_container_width=True):
        s_d = fetch_batch_market_data(target_u, account_size=settings["account_size"])
        st.session_state.screener_matches = sorted([d for d in s_d.values() if d["TCT_Valid_Range"]], key=lambda x: (x["TCT_Priority"], -x["R_Multiple"]))
        st.session_state.screener_title = "📐 Playbook 1: True 25+ Bar TCT Accumulation Boxes"
    if p3.button("🎯 Pullback & Coil", use_container_width=True):
        s_d = fetch_batch_market_data(target_u, account_size=settings["account_size"])
        st.session_state.screener_matches = sorted([d for d in s_d.values() if d["Playbook_Cat"] == "SWING_PULLBACK"], key=lambda x: -x["Score"])
        st.session_state.screener_title = "🎯 Playbooks 3 & 4: 20-EMA Pullback & Volatility Squeeze Swings"
    if p4.button("🪃 RSI-2 Oversold", use_container_width=True):
        s_d = fetch_batch_market_data(target_u, account_size=settings["account_size"])
        st.session_state.screener_matches = sorted([d for d in s_d.values() if d["Is_Oversold_Swing"]], key=lambda x: x["RSI2"])
        st.session_state.screener_title = "🪃 Playbook 5: RSI-2 Extreme Oversold Snapback Swings"
    if p5.button("🚀 20D & Gap Breakouts", use_container_width=True):
        s_d = fetch_batch_market_data(target_u, account_size=settings["account_size"])
        st.session_state.screener_matches = sorted([d for d in s_d.values() if d["Playbook_Cat"] == "BREAKOUT" or (d["RS_Leader"] and d["Is_Breakout"])], key=lambda x: -x["Score"])
        st.session_state.screener_title = "🚀 Playbooks 2 & 6: Momentum & High-Volume Gap Breakouts"

    if st.session_state.screener_matches is not None:
        st.markdown("---")
        matches = st.session_state.screener_matches
        st.markdown(f"### {st.session_state.screener_title} ({len(matches)} Matches)")
        dest_f = st.selectbox("Add selected stock to Watchlist folder:", list(watchlists.keys()), index=1)
        for m in matches:
            c1, c2, c3, c4 = st.columns([3.4, 2.8, 1.8, 1.0])
            arr = "▲ +" if m["Change"] >= 0 else "▼ -"
            c1.markdown(f"""<div><a href="?inspect={m['Ticker']}" target="_self" class="ticker-link">📊 {m['Ticker']}</a> <span class="badge {m['TCT_Badge']}">{m['TCT_Action']}</span></div><div style="font-size:0.85rem;color:#52525b;margin-top:3px;"><b>${m['Price']:,.2f}</b> ({arr}${abs(m['Change']):.2f} / {m['Change_Pct']:+.2f}%) · <b>{m['TCT_Model']}</b></div><div style="font-size:0.79rem;color:#475569;margin-top:3px;">{m['TCT_Explain']}</div>""", unsafe_allow_html=True)
            c2.markdown(f"""<div style="font-size:0.82rem;line-height:1.5;"><b>Buy Trigger:</b> ${m['BOS_Level']:,.2f} · <b>R/R:</b> {m['R_Multiple']:.1f}R<br><b>Target:</b> <span style="color:#15803d;font-weight:700;">${m['Target_Price']:,.2f} (+{m['Target_Pct']:.1f}%)</span><br><b>Stop:</b> <span style="color:#b91c1c;font-weight:700;">${m['Stop_Price']:,.2f} ({m['Stop_Pct']:.1f}%)</span> · <b>{m['Shares_05Pct']} shs</b></div>""", unsafe_allow_html=True)
            c3.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
            if c4.button("➕ Add", key=f"sc_add_{m['Ticker']}"):
                if m["Ticker"] not in watchlists[dest_f]:
                    watchlists[dest_f].append(m["Ticker"])
                    sync_watchlists_to_github(watchlists)
                    st.success("Added!")

elif navigation == "Watchlist":
    st.markdown("<h1>Watchlists & 6-Playbook Action Tickets</h1>", unsafe_allow_html=True)
    folder = st.radio("Select Watchlist Folder", list(watchlists.keys()), horizontal=True)
    symbols = watchlists.get(folder, [])

    ca, cs, ce = st.columns([2.6, 2.2, 1.2])
    with ca:
        ci, cb = st.columns([3, 1])
        ns = ci.text_input("Add symbol", placeholder=f"Add to {folder} (e.g. AVGO)", label_visibility="collapsed").upper().strip()
        if cb.button("+ Add") and ns:
            if ns not in symbols:
                watchlists[folder].append(ns)
                sync_watchlists_to_github(watchlists)
                st.rerun()
    with cs:
        sort_by = st.selectbox("Sort By", ["Saved Order (My Custom Sequence)", "Action Signal (Buy Now First)", "Relative Strength vs S&P 500", "Composite Score (High → Low)", "Reward-to-Risk Ratio (High → Low)", "Day % Change (High → Low)", "Alphabetical (A → Z)"], index=0, label_visibility="collapsed")
    with ce:
        show_ed = st.checkbox("✏️ Edit / Reorder", value=False)

    if show_ed:
        render_watchlist_reorder_panel(folder, key_prefix="wl_main")

    # ONE-TAP STRATEGY PRESET FILTER BUTTONS FOR WATCHLIST
    st.markdown("**Filter This Watchlist by Strategy Playbook:**")
    wf1, wf2, wf3, wf4, wf5, wf6 = st.columns(6)
    if wf1.button("📋 Show All", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "ALL" else "secondary"):
        st.session_state.wl_preset_filter = "ALL"; st.rerun()
    if wf2.button("🟢 Buy Now Only", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "BUY" else "secondary"):
        st.session_state.wl_preset_filter = "BUY"; st.rerun()
    if wf3.button("📐 TCT Bottoms", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "TCT" else "secondary"):
        st.session_state.wl_preset_filter = "TCT"; st.rerun()
    if wf4.button("🎯 Pullback & Coil", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "SWING" else "secondary"):
        st.session_state.wl_preset_filter = "SWING"; st.rerun()
    if wf5.button("🪃 Oversold RSI-2", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "OVERSOLD" else "secondary"):
        st.session_state.wl_preset_filter = "OVERSOLD"; st.rerun()
    if wf6.button("🔴 Below 50 EMA", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "SELL" else "secondary"):
        st.session_state.wl_preset_filter = "SELL"; st.rerun()

    st.markdown("---")
    data_dict = fetch_batch_market_data(symbols, account_size=settings["account_size"])

    disp = [s for s in symbols if s in data_dict]
    flt = st.session_state.wl_preset_filter
    if flt == "BUY": disp = [s for s in disp if data_dict[s]["TCT_Priority"] == 0]
    elif flt == "TCT": disp = [s for s in disp if data_dict[s]["TCT_Valid_Range"]]
    elif flt == "SWING": disp = [s for s in disp if data_dict[s]["Playbook_Cat"] == "SWING_PULLBACK"]
    elif flt == "OVERSOLD": disp = [s for s in disp if data_dict[s]["Is_Oversold_Swing"]]
    elif flt == "SELL": disp = [s for s in disp if data_dict[s]["TCT_Priority"] == 4]

    if sort_by == "Action Signal (Buy Now First)": disp = sorted(disp, key=lambda s: (data_dict[s]["TCT_Priority"], -data_dict[s]["Score"]))
    elif sort_by == "Relative Strength vs S&P 500": disp = sorted(disp, key=lambda s: data_dict[s]["RS_Diff"], reverse=True)
    elif sort_by == "Composite Score (High → Low)": disp = sorted(disp, key=lambda s: data_dict[s]["Score"], reverse=True)
    elif sort_by == "Reward-to-Risk Ratio (High → Low)": disp = sorted(disp, key=lambda s: data_dict[s]["R_Multiple"], reverse=True)
    elif sort_by == "Day % Change (High → Low)": disp = sorted(disp, key=lambda s: data_dict[s]["Change_Pct"], reverse=True)
    elif sort_by == "Alphabetical (A → Z)": disp = sorted(disp)

    if not disp:
        st.info("No stocks in this folder matched that strategy filter. Tap '📋 Show All' above to view all stocks.")
    lc, rc = st.columns(2)
    for idx, sym in enumerate(disp):
        d = data_dict[sym]
        arr = "▲ +" if d["Change"] >= 0 else "▼ -"
        clr = "#15803d" if d["Change"] >= 0 else "#b91c1c"
        rs_h = f'<span class="badge badge-rs-lead" style="margin-left:4px;">🔥 RS {d["RS_Diff"]:+.1f}%</span>' if d["RS_Leader"] else f'<span class="badge badge-rs-lag" style="margin-left:4px;">RS {d["RS_Diff"]:+.1f}%</span>'
        with (lc if idx % 2 == 0 else rc):
            st.markdown(f"""
            <div class="stock-card">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;">
                    <div>
                        <a href="?inspect={d['Ticker']}" target="_self" class="ticker-link">📊 {d['Ticker']}</a>
                        <span class="badge {d['TCT_Badge']}" style="margin-left:6px;">{d['TCT_Action']}</span>{rs_h}
                        <div style="font-size:1.32rem;font-weight:800;margin-top:5px;">${d['Price']:,.2f} <span style="font-size:0.9rem;color:{clr};font-weight:700;">{arr}${abs(d['Change']):.2f} ({d['Change_Pct']:+.2f}%)</span></div>
                    </div>
                    <div style="text-align:right;"><div style="font-size:1.55rem;font-weight:700;color:#c5a059;">{d['Score']}</div><div style="font-size:0.68rem;color:#71717a;">SCORE</div></div>
                </div>
                <div class="trade-ticket">
                    <div style="display:flex;justify-content:space-between;font-weight:700;color:#0f291e;margin-bottom:3px;"><span>{d['TCT_Model']}</span><span>📐 {d['R_Multiple']:.1f}R</span></div>
                    <div style="display:flex;justify-content:space-between;"><span>🎯 <b>Buy Trigger:</b> ${d['BOS_Level']:,.2f}</span><span>🟢 <b>Target:</b> <b style="color:#15803d;">${d['Target_Price']:,.2f}</b> (+{d['Target_Pct']:.1f}%)</span></div>
                    <div style="display:flex;justify-content:space-between;margin-top:3px;"><span>🔴 <b>Stop-Loss:</b> <b style="color:#b91c1c;">${d['Stop_Price']:,.2f}</b> ({d['Stop_Pct']:.1f}%)</span><span><b>0.5% Size:</b> {d['Shares_05Pct']} shs (${d['Pos_Value']:,.0f})</span></div>
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:8px;font-size:0.76rem;color:#52525b;">
                    <span>High: <b>${d['Day_High']:,.2f}</b></span><span>Low: <b>${d['Day_Low']:,.2f}</b></span><span>RSI(14/2): <b>{d['RSI']:.0f}/{d['RSI2']:.0f}</b></span><span>EMA50: <b>${d['EMA50_Val']:,.2f}</b></span>
                </div>
                <div style="font-size:0.79rem;color:#475569;margin-top:5px;font-style:italic;">"{d['TCT_Explain']}"</div>
            </div>""", unsafe_allow_html=True)

elif navigation == "Precious Metals, Crypto & Currency":
    st.markdown("<h1>Precious Metals, Crypto & Currency</h1>", unsafe_allow_html=True)
    METALS_G = {"Gold Futures (USD/oz)": "GC=F", "Silver Futures (USD/oz)": "SI=F", "Copper Futures (USD/lb)": "HG=F", "Platinum Futures (USD/oz)": "PL=F", "SPDR Gold ETF (GLD)": "GLD", "iShares Silver ETF (SLV)": "SLV"}
    CRYPTO_G = {"Bitcoin (BTC/USD)": "BTC-USD", "Ethereum (ETH/USD)": "ETH-USD", "XRP (XRP/USD)": "XRP-USD", "Solana (SOL/USD)": "SOL-USD"}
    FX_G = {"US Dollar Index (DXY)": "DX-Y.NYB", "USD / JPY": "JPY=X", "EUR / USD": "EURUSD=X"}

    all_mcf = list(METALS_G.values()) + list(CRYPTO_G.values()) + list(FX_G.values())
    mcf_data = fetch_batch_market_data(all_mcf, account_size=settings["account_size"])

    def render_mcf_section(sec_title, grp):
        st.subheader(sec_title)
        c1, c2 = st.columns(2)
        for idx, (title, sym) in enumerate(grp.items()):
            if sym in mcf_data:
                m = mcf_data[sym]
                dec = 4 if sym in ("EURUSD=X", "XRP-USD", "HG=F") else 2
                clr = "#15803d" if m["Change"] >= 0 else "#b91c1c"
                arr = "▲ +" if m["Change"] >= 0 else "▼ -"
                with (c1 if idx % 2 == 0 else c2):
                    st.markdown(f"""
                    <div class="stock-card">
                        <div style="display:flex;justify-content:space-between;align-items:center;"><span style="font-size:0.75rem;color:#71717a;font-weight:700;text-transform:uppercase;">{title}</span><span class="badge {m['TCT_Badge']}">{m['TCT_Action']}</span></div>
                        <div style="margin-top:6px;"><a href="?inspect={sym}" target="_self" class="ticker-link">📊 {sym}</a> <span style="font-size:1.38rem;font-weight:800;margin-left:8px;">${m['Price']:,.{dec}f}</span> <span style="color:{clr};font-weight:700;font-size:0.9rem;">{arr}${abs(m['Change']):.{dec}f} ({m['Change_Pct']:+.2f}%)</span></div>
                        <div class="trade-ticket">
                            <div style="display:flex;justify-content:space-between;"><span>🎯 <b>Buy Trigger:</b> ${m['BOS_Level']:,.{dec}f}</span><span>📐 <b>{m['R_Multiple']:.1f}R</b></span></div>
                            <div style="display:flex;justify-content:space-between;margin-top:3px;"><span>🟢 <b>Target:</b> <b style="color:#15803d;">${m['Target_Price']:,.{dec}f}</b> (+{m['Target_Pct']:.1f}%)</span><span>🔴 <b>Stop:</b> <b style="color:#b91c1c;">${m['Stop_Price']:,.{dec}f}</b> ({m['Stop_Pct']:.1f}%)</span></div>
                        </div>
                        <div style="display:flex;justify-content:space-between;margin-top:7px;font-size:0.76rem;color:#52525b;"><span>High: <b>${m['Day_High']:,.{dec}f}</b></span><span>Low: <b>${m['Day_Low']:,.{dec}f}</b></span><span>RSI: <b>{m['RSI']:.1f}</b></span><span>EMA50: <b>${m['EMA50_Val']:,.{dec}f}</b></span></div>
                    </div>""", unsafe_allow_html=True)

    render_mcf_section("1. Precious & Industrial Metals", METALS_G)
    st.markdown("---")
    render_mcf_section("2. Cryptocurrencies", CRYPTO_G)
    st.markdown("---")
    render_mcf_section("3. Currencies & US Dollar Index", FX_G)

elif navigation == "News & Earnings":
    st.markdown("<h1>News & Catalyst Monitor</h1>", unsafe_allow_html=True)
    tracked = get_all_monitored_tickers()
    nc1, nc2 = st.columns([1.95, 1.05])
    with nc1:
        nt1, nt2 = st.tabs([f"Watchlist News ({len(tracked)} Stocks)", "Metals, Crypto & USD News"])
        with nt1:
            p_art = fetch_news_pool([(f'"{s}" stock', s) for s in tracked[:30]], settings["news_limit"], settings["max_news_age_hours"])
            if p_art:
                st.markdown('<div class="scroll-news-box">' + "".join([f'<div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:11px 15px;margin-bottom:8px;"><div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;"><span><span class="ticker-news-badge">[{a["ticker"]}]</span><b>{a["publisher"]}</b><span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight:600;font-size:0.92rem;margin-top:4px;"><a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">{a["title"]}</a></div></div>' for a in p_art]) + '</div>', unsafe_allow_html=True)
        with nt2:
            m_art = fetch_news_pool([("gold silver copper commodities", "METALS"), ("Bitcoin Ethereum XRP Solana crypto", "CRYPTO"), ("US Dollar DXY USD JPY EUR", "FX")], settings["news_limit"], settings["max_news_age_hours"])
            if m_art:
                st.markdown('<div class="scroll-news-box">' + "".join([f'<div style="background:#fff;border:1px solid #e7e2d9;border-radius:8px;padding:11px 15px;margin-bottom:8px;"><div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;"><span><span class="ticker-news-badge">[{a["ticker"]}]</span><b>{a["publisher"]}</b><span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight:600;font-size:0.92rem;margin-top:4px;"><a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">{a["title"]}</a></div></div>' for a in m_art]) + '</div>', unsafe_allow_html=True)
    with nc2:
        st.subheader("Upcoming Earnings (Next 90 Days)")
        with st.spinner("Checking earnings dates..."):
            e_map = fetch_upcoming_earnings_safe(tracked)
        if e_map:
            rows = sorted([{"Ticker": s, "Earnings Date": dt_s, "Countdown": f"In {d_left}d" + (" ⚠️" if d_left <= 7 else ""), "_s": d_left} for s, (d_left, dt_s) in e_map.items()], key=lambda x: x["_s"])
            st.table(pd.DataFrame([{"Ticker": r["Ticker"], "Earnings Date": r["Earnings Date"], "Countdown": r["Countdown"]} for r in rows]))
        else:
            st.info("Yahoo Finance calendar is temporarily throttling lookups. Tap Refresh in a moment.")

elif navigation == "Settings":
    st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
    sc1, sc2 = st.columns(2)
    with sc1:
        acc_v = st.number_input("Total Trading Account Size ($ USD) — For 0.5% Risk Share Sizing", min_value=1000, max_value=50000000, value=int(settings["account_size"]), step=5000)
        n_lim = st.slider("Max News Headlines", 20, 100, int(settings["news_limit"]), 10)
        m_age = st.slider("Strict News Age Cutoff (Hours)", 24, 120, int(settings["max_news_age_hours"]), 12)
        if st.button("Save Settings", type="primary"):
            settings.update({"account_size": acc_v, "news_limit": n_lim, "max_news_age_hours": m_age})
            save_json(SETTINGS_FILE, settings)
            st.cache_data.clear()
            st.success("Saved!")
    with sc2:
        st.subheader("Push Notifications & CSV Export")
        cur_d = fetch_batch_market_data(get_all_monitored_tickers(), account_size=settings["account_size"])
        if st.button("🔔 Send Live 6-Playbook Briefing Ping to iPad Now", type="primary"):
            buys = [f"{k} ({v['TCT_Short_Sig']} @ ${v['Price']:.2f})" for k, v in cur_d.items() if v["TCT_Priority"] == 0]
            sells = [f"{k} (${v['Price']:.2f})" for k, v in cur_d.items() if v["TCT_Priority"] == 4]
            msg = f"🟢 BUY / SWING TRIGGERS ({len(buys)}): {', '.join(buys[:8]) if buys else 'None'}\n🔴 BELOW 50 EMA ({len(sells)}): {', '.join(sells[:8]) if sells else 'None'}"
            ok, s_msg = send_ntfy_alert(msg, "Daily Portfolio Briefing")
            st.success(f"✅ {s_msg}") if ok else st.error(f"❌ {s_msg}")
        if cur_d:
            df_ex = pd.DataFrame([{"Ticker": k, "Price": v["Price"], "Change_Pct": v["Change_Pct"], "Playbook": v["TCT_Model"], "Action": v["TCT_Action"], "Buy_Trigger": v["BOS_Level"], "Target": v["Target_Price"], "Stop": v["Stop_Price"], "R_Multiple": round(v["R_Multiple"], 2), "Shares_05Pct": v["Shares_05Pct"]} for k, v in cur_d.items()])
            st.download_button("📥 Download 6-Playbook Plan CSV", df_ex.to_csv(index=False).encode("utf-8"), f"playbook_plan_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")
