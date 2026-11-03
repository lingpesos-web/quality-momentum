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
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

st.set_page_config(
    page_title="Quality Momentum & TCT Cockpit",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZE SESSION STATE & URL ROUTING ---
for k, v in [
    ("inspect_symbol", None),
    ("rt_chart_symbol", None),
    ("nav_radio", "Dashboard"),
    ("screener_matches", None),
    ("screener_title", None),
    ("wl_preset_filter", "ALL"),
    ("last_good_data", {})
]:
    if k not in st.session_state:
        st.session_state[k] = v

if "inspect" in st.query_params:
    clicked_sym = st.query_params.get("inspect", "").strip().upper()
    if clicked_sym:
        st.session_state.inspect_symbol = clicked_sym
    st.query_params.clear()

if "rt_chart" in st.query_params:
    rt_sym = st.query_params.get("rt_chart", "").strip().upper()
    if rt_sym:
        st.session_state.rt_chart_symbol = rt_sym
        st.session_state.inspect_symbol = None
        st.session_state.nav_radio = "⚡ Live Real-Time Quotes"
    st.query_params.clear()

def clear_inspection():
    st.session_state.inspect_symbol = None
    if "inspect" in st.query_params or "rt_chart" in st.query_params:
        st.query_params.clear()

# --- FILE PATHS & GITHUB AUTO-SYNC ENGINE ---
STATE_FILE = "alert_state.json"
DATA_FILE = "watchlists.json"
POSITIONS_FILE = "positions.json"
SETTINGS_FILE = "settings.json"
GITHUB_REPO = "lingpesos-web/quality-momentum"
GITHUB_BRANCH = "main"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                if isinstance(data, dict):
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

def get_github_token():
    try:
        if "GITHUB_TOKEN" in st.secrets:
            return str(st.secrets["GITHUB_TOKEN"]).strip()
    except Exception:
        pass
    return os.environ.get("GITHUB_TOKEN", "").strip()

def sync_file_to_github(filepath, data):
    save_json(filepath, data)
    token = get_github_token()
    if not token:
        return False, "Saved locally (Add GITHUB_TOKEN in Secrets for cloud sync)."
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filepath}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Quality-Momentum-Cockpit"
    }
    try:
        sha = None
        try:
            req_g = urllib.request.Request(f"{api_url}?ref={GITHUB_BRANCH}", headers=headers)
            with urllib.request.urlopen(req_g, timeout=6) as resp:
                sha = json.loads(resp.read().decode("utf-8")).get("sha")
        except Exception:
            pass
        b64 = base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8")
        payload = {
            "message": f"Auto-sync {filepath} ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "content": b64,
            "branch": GITHUB_BRANCH
        }
        if sha:
            payload["sha"] = sha
        req_put = urllib.request.Request(
            api_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={**headers, "Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req_put, timeout=8) as resp:
            if resp.status in (200, 201):
                return True, f"✅ Synced {filepath} to GitHub!"
    except Exception as e:
        return False, f"Saved locally (GitHub sync error: {str(e)[:50]})"
    return False, "Saved locally."

def sync_watchlists_to_github(data):
    return sync_file_to_github(DATA_FILE, data)

def sync_positions_to_github(data):
    return sync_file_to_github(POSITIONS_FILE, data)

# --- NTFY ALERT ENGINE (ASCII-SAFE HEADER + ACTIVE POSITIONS MONITOR) ---
def send_ntfy_alert(message, title="Daily Portfolio Briefing"):
    try:
        ascii_title = title.encode("ascii", "ignore").decode("ascii").strip() or "Market Alert"
        req = urllib.request.Request(
            "https://ntfy.sh/2026_USstockspicks",
            data=message.encode("utf-8"),
            headers={
                "Title": ascii_title,
                "Priority": "high",
                "Content-Type": "text/plain; charset=utf-8"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return True, f"Delivered (HTTP {resp.status}) to topic '2026_USstockspicks'"
    except Exception as e:
        return False, f"ntfy error: {str(e)}"

# --- LOAD WATCHLISTS, POSITIONS & SETTINGS ---
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

watchlists = load_json(DATA_FILE, DEFAULT_WATCHLISTS)
if not watchlists:
    watchlists = DEFAULT_WATCHLISTS.copy()
for k_def, v_def in DEFAULT_WATCHLISTS.items():
    if k_def not in watchlists or not isinstance(watchlists[k_def], list):
        watchlists[k_def] = v_def

positions = load_json(POSITIONS_FILE, {})

def get_all_monitored_tickers():
    combined = list(positions.keys())
    for folder_syms in watchlists.values():
        if isinstance(folder_syms, list):
            combined.extend([str(s).strip().upper() for s in folder_syms if str(s).strip()])
    return list(dict.fromkeys(combined))

settings = load_json(SETTINGS_FILE, {
    "w_fund": 40, "w_tech": 40, "w_mom": 20, "account_size": 100000,
    "news_limit": 60, "max_news_age_hours": 72, "alert_breakout": True, "alert_support": True
})
for k_s, v_s in [
    ("account_size", 100000), ("news_limit", 60),
    ("max_news_age_hours", 72), ("w_fund", 40), ("w_tech", 40), ("w_mom", 20)
]:
    if k_s not in settings:
        settings[k_s] = v_s

def check_and_fire_live_ntfy(records):
    """Fires instant ntfy alerts during US market hours for Active Positions & Watchlist."""
    if not records:
        return
    try:
        now_et = datetime.now(ZoneInfo("America/New_York"))
        if now_et.weekday() >= 5 or not ((now_et.hour == 9 and now_et.minute >= 30) or (10 <= now_et.hour < 16)):
            return
        today_et = now_et.strftime("%Y-%m-%d")
        state = load_json(STATE_FILE, {"date": today_et, "alerted": []})
        if state.get("date") != today_et:
            state = {"date": today_et, "alerted": []}
        alerted = set(state.get("alerted", []))

        pos_alerts, new_buys, new_targets, new_stops = [], [], [], []

        # 1. Check Personal Active Positions Rules (10% Stop, +15% Sell Half, 20-EMA Break)
        for sym, pos in positions.items():
            if sym not in records:
                continue
            d = records[sym]
            price = d["Price"]
            buy_p = float(pos.get("buy_price", price))
            stop_p = float(pos.get("stop_loss", buy_p * 0.90))
            tgt_15 = float(pos.get("target_15", buy_p * 1.15))
            half_sold = bool(pos.get("half_sold", False))
            ema20_v = d["EMA20_Val"]

            if price <= stop_p and f"POS_{sym}_STOP" not in alerted:
                pos_alerts.append(f"🚨 {sym} HIT MY STOP (${price:,.2f} <= Stop ${stop_p:,.2f}) — SELL!")
                alerted.add(f"POS_{sym}_STOP")
            if not half_sold and price >= tgt_15 and f"POS_{sym}_15PCT" not in alerted:
                shs_half = max(1, int(float(pos.get("shares", 1)) // 2))
                pos_alerts.append(f"💰 {sym} UP +15% (${price:,.2f} >= ${tgt_15:,.2f}) — Sell 50% ({shs_half} shs) & Raise Stop!")
                alerted.add(f"POS_{sym}_15PCT")
            if price < ema20_v and f"POS_{sym}_EMA20" not in alerted:
                pos_alerts.append(f"⚠️ {sym} BROKE 20-EMA (${price:,.2f} < 20-EMA ${ema20_v:,.2f}) — Check Trail Exit!")
                alerted.add(f"POS_{sym}_EMA20")

        # 2. Check General Watchlist Triggers
        for sym, d in records.items():
            if d["TCT_Priority"] == 0 and f"{sym}_BUY" not in alerted:
                new_buys.append(f"{sym} ({d['TCT_Short_Sig']} @ ${d['Price']:,.2f})")
                alerted.add(f"{sym}_BUY")
            if d["Price"] >= d["Target_Price"] * 0.996 and f"{sym}_TGT" not in alerted:
                new_targets.append(f"{sym} (${d['Price']:,.2f} >= Tgt ${d['Target_Price']:,.2f})")
                alerted.add(f"{sym}_TGT")
            if d["Price"] <= d["Stop_Price"] and f"{sym}_STOP" not in alerted:
                new_stops.append(f"{sym} (${d['Price']:,.2f} <= Stop ${d['Stop_Price']:,.2f})")
                alerted.add(f"{sym}_STOP")

        if pos_alerts or new_buys or new_targets or new_stops:
            lines = []
            if pos_alerts:
                lines.append("💼 MY ACTIVE POSITIONS:\n" + "\n".join(pos_alerts))
            if new_buys:
                lines.append("🟢 WATCHLIST BUY TRIGGER: " + ", ".join(new_buys[:6]))
            if new_targets:
                lines.append("🎯 WATCHLIST TARGET HIT: " + ", ".join(new_targets[:6]))
            if new_stops:
                lines.append("🔴 WATCHLIST STOP HIT: " + ", ".join(new_stops[:6]))
            send_ntfy_alert("\n".join(lines), "Live Position and Market Alert")
            state["alerted"] = sorted(list(alerted))
            save_json(STATE_FILE, state)
    except Exception:
        pass

# --- CUSTOM CSS ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600;700;800&display=swap');

.stApp { background-color: #fbf9f4 !important; color: #1a1a1a !important; font-family: 'Inter', sans-serif; }
[data-testid="stSidebar"] { background-color: #0f291e !important; border-right: 1px solid #1c3d2f; }
[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label { padding: 8px 12px; border-radius: 6px; margin-bottom: 4px; }
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover { background-color: #183d2e; }
h1, h2, h3 { font-family: 'Newsreader', Georgia, serif !important; font-weight: 600 !important; color: #0f291e !important; }
.macro-container { display: flex; flex-wrap: nowrap; gap: 8px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 12px; }
.macro-card { flex: 1 1 0px; min-width: 105px; background: #ffffff; border: 1px solid #e7e2d9; border-radius: 8px; padding: 8px 6px; text-align: center; }
.macro-title { font-size: 0.68rem; color: #71717a; text-transform: uppercase; font-weight: 700; white-space: nowrap; }
.macro-price { font-size: 0.88rem; font-weight: 700; color: #18181b; margin: 2px 0; white-space: nowrap; }
.tick-pos { color: #15803d; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.tick-neg { color: #b91c1c; font-size: 0.72rem; font-weight: 600; white-space: nowrap; }
.stock-card { background: #ffffff; border: 1px solid #e7e2d9; border-radius: 10px; padding: 16px; margin-bottom: 14px; box-shadow: 0 1px 4px rgba(0,0,0,0.03); }
.ticker-link { font-size: 1.25rem; font-weight: 700; color: #0f291e !important; text-decoration: none !important; border-bottom: 2px solid #c5a059; padding-bottom: 1px; }
.ticker-link:hover { color: #15803d !important; background-color: #f0fdf4; border-radius: 4px; padding: 2px 6px; }
.hero-ticker-link { font-size: 1.85rem; font-weight: 700; color: #ffffff !important; text-decoration: none !important; border-bottom: 2px dashed #c5a059; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.68rem; font-weight: 700; text-transform: uppercase; }
.badge-breakout { background: #dcfce7; color: #15803d; }
.badge-trend { background: #dbeafe; color: #1d4ed8; }
.badge-candidate { background: #fef9c3; color: #a16207; }
.badge-caution { background: #fee2e2; color: #b91c1c; }
.badge-tct-buy { background: #15803d; color: #ffffff; }
.badge-tct-watch { background: #fef08a; color: #854d0e; border: 1px solid #fde047; }
.badge-tct-sell { background: #b91c1c; color: #ffffff; }
.badge-mom-fire { background: #7c2d12; color: #ffedd5; border: 1px solid #f97316; }
.badge-rs-lead { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.badge-rs-lag { background: #f4f4f5; color: #71717a; }
.badge-earn-warn { background: #ffedd5; color: #c2410c; border: 1px solid #fdba74; font-weight: 700; }
.pill { display: inline-flex; align-items: center; background: #e9e4db; color: #0f291e !important; text-decoration: none !important; padding: 4px 10px; border-radius: 14px; font-size: 0.8rem; font-weight: 600; margin-right: 6px; margin-bottom: 6px; }
.scroll-news-box { max-height: 540px; overflow-y: auto; padding-right: 6px; }
.ticker-news-badge { background: #dcfce7; color: #15803d; padding: 2px 6px; border-radius: 4px; font-weight: 700; font-size: 0.7rem; margin-right: 6px; }
.age-badge { background: #f1f5f9; color: #334155; padding: 2px 6px; border-radius: 4px; font-weight: 600; font-size: 0.68rem; margin-left: 6px; }
.trade-ticket { background: #f8f6f0; border: 1px solid #e2ddd2; border-radius: 8px; padding: 10px 12px; margin-top: 10px; font-size: 0.80rem; }

/* LARGE-FONT LIVE WATCHBOARD & FULL-WIDTH ACTIVE POSITIONS TABLE */
.live-board-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; width: 100%; margin-top: 4px; }
@media (max-width: 900px) { .live-board-grid { grid-template-columns: 1fr; } }
.live-quote-table { width: 100%; border-collapse: collapse; background: #ffffff; border: 1px solid #d4cec3; border-radius: 6px; overflow: hidden; font-size: 1.12rem; table-layout: auto; }
.live-quote-table thead th { background: #0f291e; color: #f4efe6; font-weight: 700; font-size: 0.82rem; text-transform: uppercase; padding: 7px 6px; text-align: right; white-space: nowrap; }
.live-quote-table thead th:nth-child(1), .live-quote-table thead th:nth-child(2) { text-align: left; }
.live-quote-table tbody tr { border-bottom: 1px solid #eae5dc; line-height: 1.3; }
.live-quote-table tbody tr:nth-child(even) { background-color: #faf8f5; }
.live-quote-table tbody tr:hover { background-color: #ecfdf5; }
.live-quote-table td { padding: 6px 6px; text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
.live-quote-table td:nth-child(1) { text-align: left; font-size: 0.94rem; font-weight: 700; padding-left: 8px; }
.live-quote-table td:nth-child(2) { text-align: left; font-weight: 800; }
.rt-sym-link { color: #0f291e !important; text-decoration: none !important; font-weight: 800; font-size: 1.18rem; border-bottom: 2px solid #c5a059; }
.rt-sym-link:hover { color: #15803d !important; background: #dcfce7; padding: 1px 4px; border-radius: 3px; }
.rt-dossier-link { text-decoration: none !important; font-size: 0.85rem; margin-left: 3px; opacity: 0.7; }
</style>
""", unsafe_allow_html=True)

# --- EXPANDED ~220-STOCK LIQUID MARKET UNIVERSE ---
GICS_SECTORS = {
    "AI, Semiconductors & Hardware": [
        "NVDA", "AVGO", "AMD", "MU", "TSM", "ASML", "AMAT", "LRCX", "KLAC", "MRVL",
        "ARM", "QCOM", "TXN", "ADI", "ON", "MPWR", "NXPI", "MCHP", "TER", "ENTG",
        "CRDO", "VRT", "COHR", "LITE", "CIEN", "FN", "ANET", "SMCI", "DELL", "HPE",
        "SNDK", "STX", "WDC", "NTAP", "PSTG", "GLW", "CLS", "JBL", "FLEX", "APH"
    ],
    "Software, Cloud & Cybersecurity": [
        "MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "PLTR", "APP", "SNOW", "PANW",
        "CRWD", "FTNT", "ZS", "NET", "DDOG", "MDB", "TEAM", "WDAY", "HUBS", "TTD",
        "IOT", "DUOL", "MNDY", "PATH", "CFLT", "GTLB", "S", "OKTA", "CYBR", "DOCU"
    ],
    "Quantum, Space & Next-Gen Tech": [
        "IONQ", "QUBT", "RGTI", "QBTS", "ARQQ", "RKLB", "ASTS", "LUNR", "PL", "SPIR",
        "JOBY", "ACHR", "SERV", "SOUN", "BBAI", "SYM", "UPST", "AFRM", "RDDT", "ALAB"
    ],
    "Crypto, Fintech & Financials": [
        "COIN", "MSTR", "HOOD", "SOFI", "PYPL", "MARA", "RIOT", "CLSK", "IREN",
        "CORZ", "HUT", "WULF", "CIFR", "JPM", "GS", "MS", "BLK", "BX",
        "KKR", "APO", "ARES", "V", "MA", "AXP", "BAC", "WFC", "C", "SCHW"
    ],
    "Communication & Internet Leaders": [
        "GOOGL", "META", "NFLX", "AMZN", "AAPL", "TSLA", "SPOT", "UBER", "DASH", "ABNB",
        "BKNG", "EXPE", "TMUS", "DIS", "CMCSA", "RBLX", "U", "EA", "TTWO", "PINS"
    ],
    "Energy, Nuclear & Precious Metals": [
        "CEG", "VST", "NRG", "TLN", "OKLO", "SMR", "CCJ", "UEC", "NXE", "DNN",
        "NEE", "SO", "DUK", "GEV", "XOM", "CVX", "COP", "EOG", "SLB", "HAL",
        "NEM", "AEM", "WPM", "FNV", "PAAS", "AG", "CDE", "HL", "FCX", "SLV", "GLD"
    ],
    "Industrials, Defense & Infrastructure": [
        "GE", "CAT", "ETN", "PWR", "EME", "FIX", "URI", "PH", "TT", "CARR",
        "RTX", "LMT", "NOC", "GD", "LHX", "HII", "AXON", "TDG", "HEI", "HWM",
        "UNP", "CSX", "FDX", "UPS", "DE", "HON", "WM", "RSG"
    ],
    "Health Care & Biotech Innovators": [
        "LLY", "NVO", "VRTX", "REGN", "AMGN", "GILD", "ISRG", "SYK", "BSX", "MDT",
        "ABT", "TMO", "DHR", "UNH", "ELV", "CI", "HCA", "IDXX", "DXCM", "PODD",
        "ADPT", "TEM", "EXAS", "NTRA", "GH", "TWST", "CRSP", "NTLA", "BEAM", "VKTX"
    ],
    "Consumer & Retail Powerhouses": [
        "WMT", "COST", "TGT", "HD", "LOW", "TJX", "ROST", "NKE", "ONON", "DECK",
        "LULU", "SBUX", "CMG", "CAVA", "SHAK", "MCD", "YUM", "DPZ", "PG", "KO", "PEP", "PM"
    ]
}

# --- STRICT FRESHNESS NEWS ENGINE (STOCKTWITS PERMANENTLY BLOCKED) ---
BLOCKED_NEWS_SOURCES = {
    "stocktwits", "stockwits", "marketbeat", "zacks", "defense world",
    "etf daily news", "ticker report", "american banking news", "simply wall st",
    "stocknews.com", "wall street zen", "holdings channel", "transcript daily",
    "modern readers", "watch list news", "barchart", "guru focus", "gurufocus"
}
STALE_HEADLINE_PATTERNS = [
    "if you invested", "years ago", "last year", "months ago",
    "why shares plunged in ", "heres how much ", "stocktwits"
]

def _fetch_rss_raw(query, max_per_query=18, ticker_tag=None, max_age_hours=72):
    q_with_time = query if "when:" in query else f"{query} when:3d"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_with_time)}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    articles = []
    now_utc = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            root = ET.fromstring(response.read())
        for item in root.findall(".//item")[:max_per_query]:
            raw_title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else "#"
            pub_date_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"
            if not raw_title or not pub_date_raw:
                continue
            src_low = source.lower().strip()
            if any(bad in src_low for bad in BLOCKED_NEWS_SOURCES) or "stocktwits" in link.lower():
                continue
            clean_title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            if any(pat in clean_title.lower() for pat in STALE_HEADLINE_PATTERNS):
                continue
            try:
                dt_obj = email.utils.parsedate_to_datetime(pub_date_raw)
                if dt_obj.tzinfo is None:
                    dt_obj = dt_obj.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            age_hours = (now_utc - dt_obj).total_seconds() / 3600.0
            if age_hours < -1.0 or age_hours > max_age_hours:
                continue
            age_label = (
                f"{max(1, int(age_hours * 60))}m ago" if age_hours < 1.0
                else (f"{int(age_hours)}h ago" if age_hours < 24.0 else f"{int(age_hours // 24)}d ago")
            )
            articles.append({
                "title": clean_title, "link": link, "publisher": source,
                "date": dt_obj.strftime("%b %d · %H:%M UTC"), "age": age_label,
                "timestamp": dt_obj.timestamp(), "ticker": ticker_tag or "MARKET"
            })
    except Exception:
        pass
    return articles

@st.cache_data(ttl=600)
def fetch_google_news_rss(query, max_items=60, max_age_hours=72):
    queries = [
        f"{query} when:3d",
        "S&P 500 Nasdaq stock market today when:3d",
        "Wall Street stocks earnings Federal Reserve when:3d",
        "US tech stocks semiconductors market news when:3d"
    ]
    pool, seen_links, seen_titles = [], set(), set()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for fut in [executor.submit(_fetch_rss_raw, q, 25, "MARKET", max_age_hours) for q in queries]:
            for item in fut.result():
                norm_t = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_t not in seen_titles:
                    seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
    return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

@st.cache_data(ttl=600)
def fetch_watchlist_news_pool(tickers, max_items=60, max_age_hours=72):
    if not tickers:
        return []
    pool, seen_links, seen_titles = [], set(), set()
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_fetch_rss_raw, f'"{sym}" stock when:3d', 4, sym, max_age_hours) for sym in list(dict.fromkeys(tickers))]
        for fut in futures:
            for item in fut.result():
                norm_t = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_t not in seen_titles:
                    seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
    return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

@st.cache_data(ttl=600)
def fetch_metals_crypto_fx_news(max_items=50, max_age_hours=72):
    queries = [
        ("gold silver copper prices commodities market when:3d", "METALS"),
        ("Bitcoin Ethereum Solana XRP crypto market when:3d", "CRYPTO"),
        ("US Dollar Index DXY USD JPY EUR USD forex when:3d", "FX/USD")
    ]
    pool, seen_links, seen_titles = [], set(), set()
    with ThreadPoolExecutor(max_workers=3) as executor:
        for fut in [executor.submit(_fetch_rss_raw, q, 22, tag, max_age_hours) for q, tag in queries]:
            for item in fut.result():
                norm_t = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_t not in seen_titles:
                    seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
    return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

# --- PARALLEL EARNINGS CALENDAR & WATCHLIST BADGE ENGINE ---
@st.cache_data(ttl=14400)
def fetch_upcoming_earnings_map(tickers):
    if not tickers:
        return {}
    out = {}
    now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    def _check_one(sym):
        if any(ch in sym for ch in ["=X", "=F", "-USD", "^", "."]) or sym in {"SLV", "GLD", "SOXL", "SPCX", "DRAM"}:
            return sym, None
        try:
            t_obj = yf.Ticker(sym)
            raw_date = None
            try:
                cal = t_obj.calendar
                if isinstance(cal, dict) and "Earnings Date" in cal:
                    dates = cal["Earnings Date"]
                    raw_date = dates[0] if isinstance(dates, list) and dates else dates
                elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                    raw_date = cal.loc["Earnings Date"].iloc[0]
            except Exception:
                pass
            if raw_date is None:
                try:
                    ed_df = t_obj.get_earnings_dates(limit=4)
                    if ed_df is not None and not ed_df.empty:
                        fut = [d.to_pydatetime().replace(tzinfo=None) for d in ed_df.index if d.to_pydatetime().replace(tzinfo=None) >= now_dt]
                        if fut:
                            raw_date = min(fut)
                except Exception:
                    pass
            if raw_date is not None:
                dt_parsed = pd.to_datetime(raw_date).to_pydatetime().replace(tzinfo=None, hour=0, minute=0, second=0)
                days_diff = (dt_parsed - now_dt).days
                if 0 <= days_diff <= 60:
                    return sym, (days_diff, dt_parsed.strftime("%Y-%m-%d"))
        except Exception:
            pass
        return sym, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, res in ex.map(_check_one, list(dict.fromkeys(tickers))):
            if res is not None:
                out[sym] = res
    return out

# --- PURE MOMENTUM + 6-PLAYBOOK MULTI-STRATEGY ENGINE ---
def analyze_six_playbooks(df, account_size=100000, spy_ret_63d=0.0, df_1h=None):
    n = len(df)
    close_arr = df["Close"].values.astype(float)
    high_arr = df["High"].values.astype(float)
    low_arr = df["Low"].values.astype(float)
    open_arr = df["Open"].values.astype(float)
    vol_arr = np.nan_to_num(df["Volume"].values.astype(float), nan=0.0)
    curr_close = float(close_arr[-1])
    prev_close = float(close_arr[-2]) if n >= 2 else curr_close

    lookback_rs = min(63, n - 1)
    stock_ret_63d = (
        ((curr_close - float(close_arr[-1 - lookback_rs])) / float(close_arr[-1 - lookback_rs])) * 100.0
        if lookback_rs > 5 and close_arr[-1 - lookback_rs] > 0 else 0.0
    )
    rs_diff = stock_ret_63d - spy_ret_63d
    rs_leader = bool(rs_diff >= 2.0)

    dollar_vol_20 = float(pd.Series(close_arr[-20:] * vol_arr[-20:]).median()) if n >= 20 else 0.0
    liq_pass = bool(dollar_vol_20 >= 50_000_000)

    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"] - df["Close"].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr14_daily = float(tr.rolling(14).mean().iloc[-1])
    if np.isnan(atr14_daily) or atr14_daily <= 0:
        atr14_daily = curr_close * 0.025
    atr14_1h_est = atr14_daily / 2.55

    ema20 = float(df["EMA20"].iloc[-1])
    ema50 = float(df["EMA50"].iloc[-1])
    ema200 = float(df["EMA200"].iloc[-1]) if len(df) >= 200 else ema50
    rsi14 = float(df["RSI"].iloc[-1]) if not np.isnan(df["RSI"].iloc[-1]) else 50.0

    # Pure Momentum Institutional Leader Definition (Your Core Strategy)
    is_pure_momentum = bool(
        curr_close > ema20 and ema20 > ema50 and curr_close > ema200
        and rs_leader and (52.0 <= rsi14 <= 80.0)
    )

    delta = df["Close"].diff()
    g2 = delta.where(delta > 0, 0.0).ewm(alpha=1/2, adjust=False).mean()
    l2 = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/2, adjust=False).mean()
    rsi2_series = 100 - (100 / (1 + (g2 / (l2 + 1e-9))))
    rsi2 = float(rsi2_series.iloc[-1]) if not np.isnan(rsi2_series.iloc[-1]) else 50.0

    bb_width = ((df["BB_Upper"] - df["BB_Lower"]) / (df["BB_Mid"] + 1e-9)).values
    curr_bb_w = float(bb_width[-1]) if not np.isnan(bb_width[-1]) else 0.10
    min_bb_w20 = float(np.nanmin(bb_width[-25:])) if n >= 25 else curr_bb_w
    is_bb_squeeze = bool(curr_bb_w <= min_bb_w20 * 1.18)

    vol20 = float(df["Vol20"].iloc[-1]) if not np.isnan(df["Vol20"].iloc[-1]) else 0.0
    now_utc = datetime.now(timezone.utc)
    if 13 <= now_utc.hour <= 20 and now_utc.weekday() < 5:
        mins_open = max(25.0, min(390.0, (now_utc.hour * 60 + now_utc.minute) - (13 * 60 + 30)))
        pace_factor = max(0.20, mins_open / 390.0)
    else:
        pace_factor = 1.0
    paced_rvol = float(vol_arr[-1] / (vol20 * pace_factor)) if vol20 > 0 else 1.0

    swing_lows = [(i, float(low_arr[i])) for i in range(3, n - 3) if low_arr[i] == np.min(low_arr[i - 3:i + 4])]

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
                rng_height = r_high - t1_val
                if rng_height <= t1_val * 0.03 or rng_height >= t1_val * 0.38 or (peak_price - t1_val) < 0.30 * rng_height:
                    continue
                if t2_val <= t1_val * 1.015 and float(np.min(close_arr[t1_idx:t2_idx + 1])) >= (t1_val - 0.30 * rng_height):
                    if (t2_idx - peak_idx) < 25:
                        continue
                    slow_decline_25 = True
                    tap1_price, tap2_price, range_high = t1_val, t2_val, r_high
                    tap3_price = float(np.min(low_arr[t2_idx:]))
                    if df_1h is not None and len(df_1h) >= 15:
                        h1_highs = df_1h["High"].values.astype(float)
                        h1_swings = [float(h1_highs[k]) for k in range(3, len(h1_highs) - 3) if h1_highs[k] == np.max(h1_highs[k - 3:k + 4])]
                        recent_h1 = [v for v in h1_swings[-6:] if tap3_price * 1.005 <= v <= range_high * 0.96]
                        bos_level = float(recent_h1[-1]) if recent_h1 else float(np.max(high_arr[-4:-1]))
                    else:
                        bos_level = max(min(float(np.max(high_arr[-5:-1])), tap3_price + 0.35 * rng_height), tap3_price * 1.012)
                    if (tap2_price - 0.30 * (range_high - tap2_price)) <= curr_close <= range_high * 0.98:
                        tct_valid_range = True
                        break
            if tct_valid_range:
                break

    high_20d_prev = float(np.max(high_arr[-21:-1])) if n >= 22 else curr_close
    high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_close
    high_3d_prev = float(np.max(high_arr[-4:-1])) if n >= 5 else curr_close
    low_3d = float(np.min(low_arr[-3:]))

    is_20d_breakout = (curr_close >= high_20d_prev) and (paced_rvol >= 1.25) and (curr_close > ema50)
    is_holy_grail_pullback = (
        (curr_close > ema50) and (ema20 > ema50)
        and (abs(low_arr[-1] - ema20) / ema20 <= 0.022 or abs(curr_close - ema20) / ema20 <= 0.022)
        and (curr_close >= open_arr[-1] or curr_close > prev_close)
    )
    is_squeeze_breakout = is_bb_squeeze and (curr_close > ema50) and (curr_close >= high_3d_prev)
    is_rsi2_snapback = (curr_close > ema200 * 0.96) and (rsi2 <= 18.0 or low_arr[-1] <= float(df["BB_Lower"].iloc[-1]))
    day_rng = max(high_arr[-1] - low_arr[-1], 1e-6)
    is_gap_ignition = (
        ((curr_close - prev_close) / prev_close >= 0.032)
        and (paced_rvol >= 1.7)
        and ((curr_close - low_arr[-1]) / day_rng >= 0.55)
        and (curr_close > ema50)
    )

    playbook_cat = "TREND"
    if tct_valid_range and range_high and bos_level and tap3_price:
        playbook_name = "📐 Playbook 1: TCT Bottom Box"
        playbook_cat = "TCT"
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        effective_stop = max(min(tap3_price - (0.5 * atr14_1h_est), entry_ref * 0.98), entry_ref * 0.93)
        target_price = range_high
    elif is_20d_breakout:
        playbook_name = "🚀 Playbook 2: 20D Momentum Breakout"
        playbook_cat = "BREAKOUT"
        bos_level = high_20d_prev
        entry_ref = curr_close
        effective_stop = max(min(ema20, curr_close - 1.5 * atr14_daily), curr_close * 0.90)
        target_price = entry_ref * 1.15
    elif is_gap_ignition:
        playbook_name = "🔥 Playbook 6: High-Vol Gap Ignition"
        playbook_cat = "BREAKOUT"
        bos_level = float(high_arr[-1]) if curr_close < high_arr[-1] else curr_close
        entry_ref = curr_close
        effective_stop = max(float(low_arr[-1]) - 0.2 * atr14_daily, curr_close * 0.90)
        target_price = entry_ref * 1.15
    elif is_squeeze_breakout:
        playbook_name = "⚡ Playbook 4: Volatility Squeeze Coil"
        playbook_cat = "SWING_PULLBACK"
        bos_level = high_3d_prev
        entry_ref = curr_close
        effective_stop = max(low_3d - 0.3 * atr14_daily, curr_close * 0.92)
        target_price = entry_ref + 2.8 * (entry_ref - effective_stop)
    elif is_holy_grail_pullback:
        playbook_name = "🎯 Playbook 3: 20-EMA Pullback Swing"
        playbook_cat = "SWING_PULLBACK"
        bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
        entry_ref = curr_close
        effective_stop = max(min(low_3d, ema20) - 0.5 * atr14_daily, curr_close * 0.92)
        target_price = max(high_20d_prev, entry_ref * 1.15)
    elif is_rsi2_snapback:
        playbook_name = f"🪃 Playbook 5: RSI-2 Oversold Bounce (RSI2={rsi2:.0f})"
        playbook_cat = "OVERSOLD"
        bos_level = curr_close
        entry_ref = curr_close
        effective_stop = max(curr_close - 1.5 * atr14_daily, curr_close * 0.92)
        target_price = max(ema20, entry_ref + 2.0 * (entry_ref - effective_stop))
    elif is_pure_momentum:
        playbook_name = "🔥 Pure Momentum Leader (Above 20/50/200 EMA)"
        playbook_cat = "MOMENTUM"
        bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        effective_stop = max(min(ema20, entry_ref * 0.90), entry_ref * 0.90)
        target_price = entry_ref * 1.15
    else:
        playbook_name = "📈 Standard Trend Swing"
        bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        effective_stop = max(min(entry_ref - 1.5 * atr14_daily, entry_ref * 0.978), entry_ref * 0.90)
        target_price = entry_ref * 1.15

    risk_per_share = max(entry_ref - effective_stop, 0.0001)
    reward_per_share = max(target_price - entry_ref, 0.0)
    r_multiple = reward_per_share / risk_per_share
    suggested_shares = max(1, int((account_size * 0.005) / risk_per_share))
    position_value = suggested_shares * entry_ref
    target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
    stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0

    crossed_5d = (curr_close >= high_5d_prev) and (prev_close < high_5d_prev)

    if tct_valid_range and curr_close >= bos_level and r_multiple >= 1.9:
        act, badge, dot, short_s, prio = "BUY NOW (TCT BOS)", "badge-tct-buy", "🟢", "🟢 Buy Now", 0
        expl = f"TCT accumulation breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
    elif is_20d_breakout or is_gap_ignition:
        act, badge, dot, short_s, prio = "BUY NOW (MOMENTUM)", "badge-tct-buy", "🔥", "🔥 Mom Buy", 0
        expl = f"{playbook_name}: Breakout above ${bos_level:,.2f} on {paced_rvol:.1f}x pace volume."
    elif is_squeeze_breakout or is_holy_grail_pullback:
        act, badge, dot, short_s, prio = "SWING BUY (20-EMA/COIL)", "badge-tct-buy", "🎯", "🎯 Swing Buy", 0
        expl = f"{playbook_name}: High-probability swing entry near ${entry_ref:,.2f}, stop ${effective_stop:,.2f}."
    elif is_pure_momentum:
        act, badge, dot, short_s, prio = "PURE MOMENTUM LEADER", "badge-mom-fire", "🔥", "🔥 Momentum", 1
        expl = f" Pure Momentum: Beating S&P 500 ({rs_diff:+.1f}%), riding above 20-EMA (${ema20:,.2f}) & 50-EMA."
    elif is_rsi2_snapback:
        act, badge, dot, short_s, prio = "SWING BUY (OVERSOLD)", "badge-tct-watch", "🪃", "🪃 Oversold", 1
        expl = f"RSI-2 extreme oversold ({rsi2:.0f}) above 200-EMA. Target bounce to ${target_price:,.2f}."
    elif tct_valid_range and curr_close < bos_level:
        act, badge, dot, short_s, prio = "WATCHING TCT BOX", "badge-tct-watch", "📐", "📐 TCT Box", 1
        expl = f"Valid 25+ bar TCT bottom box formed. Buy if price closes above BOS ${bos_level:,.2f}."
    elif curr_close > ema50 and (curr_close >= ema20 * 0.99 or crossed_5d):
        act, badge, dot, short_s, prio = "HOLD / UPTREND", "badge-trend", "🔵", "🔵 Uptrend", 2
        expl = f"Holding above 20 & 50 EMA. +15% target ${target_price:,.2f}, stop ${effective_stop:,.2f}."
    elif curr_close < ema50 and not tct_valid_range and not is_rsi2_snapback:
        act, badge, dot, short_s, prio = "SELL / AVOID", "badge-tct-sell", "🔴", "🔴 Below 50", 4
        expl = f"Below 50-day EMA (${ema50:,.2f}) without a valid TCT bottom box. Protect capital."
    else:
        act, badge, dot, short_s, prio = "WAIT FOR TRIGGER", "badge-candidate", "🟡", "🟡 Wait", 3
        expl = f"Consolidating. Wait for a clean move above ${bos_level:,.2f} before entering."

    return {
        "TCT_Valid_Range": tct_valid_range, "TCT_Model": playbook_name, "Playbook_Cat": playbook_cat,
        "Is_Pure_Momentum": is_pure_momentum, "TCT_Slow_25": slow_decline_25, "TCT_Liq_50M": liq_pass,
        "TCT_2R_Pass": bool(r_multiple >= 2.0), "TCT_Action": act, "TCT_Badge": badge,
        "TCT_Dot": dot, "TCT_Short_Sig": short_s, "TCT_Explain": expl, "TCT_Priority": prio,
        "BOS_Entry": entry_ref, "BOS_Level": bos_level, "Target_Price": target_price,
        "Stop_Price": effective_stop, "R_Multiple": r_multiple, "Target_Pct": target_gain_pct,
        "Stop_Pct": stop_loss_pct, "Shares_05Pct": suggested_shares, "Pos_Value": position_value,
        "Dollar_Vol_M": dollar_vol_20 / 1e6, "RS_Diff": rs_diff, "RS_Leader": rs_leader,
        "RSI2": rsi2, "Paced_RVOL": paced_rvol, "Is_Oversold_Swing": is_rsi2_snapback
    }

# --- DATA ENGINE 1: FAST BATCH INGESTION + 8:00 AM HKT SETTLEMENT PATCH ---
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
        data = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False)
        now_utc = datetime.now(timezone.utc)
        data_intraday = None
        if now_utc.hour in (0, 1):
            try:
                data_intraday = yf.download(clean_tickers[:45], period="5d", interval="15m", group_by="ticker", progress=False)
            except Exception:
                data_intraday = None
    except Exception:
        return st.session_state.get("last_good_data", {})

    spy_ret_63d = 0.0
    try:
        spy_df = _extract_ticker_df(data, "^GSPC", len(download_list)).dropna(subset=["Close"])
        if len(spy_df) >= 64:
            spy_ret_63d = ((float(spy_df["Close"].iloc[-1]) - float(spy_df["Close"].iloc[-64])) / float(spy_df["Close"].iloc[-64])) * 100.0
    except Exception:
        pass

    w_fund, w_tech, w_mom = settings["w_fund"] / 100.0, settings["w_tech"] / 100.0, settings["w_mom"] / 100.0
    results = {}

    for t in clean_tickers:
        try:
            df = _extract_ticker_df(data, t, len(download_list))
            df.dropna(subset=["Close", "High", "Low"], inplace=True)
            if len(df) < 25:
                continue

            if data_intraday is not None:
                try:
                    df_intra = _extract_ticker_df(data_intraday, t, len(clean_tickers[:45])).dropna(subset=["Close"])
                    if not df_intra.empty:
                        intra_dates = pd.to_datetime(df_intra.index).tz_localize(None).normalize()
                        last_intra_date = intra_dates[-1]
                        last_1d_date = pd.to_datetime(df.index[-1]).tz_localize(None).normalize()
                        if last_intra_date > last_1d_date:
                            ts = df_intra[intra_dates == last_intra_date]
                            new_r = pd.DataFrame({
                                "Open": [float(ts["Open"].iloc[0])], "High": [float(ts["High"].max())],
                                "Low": [float(ts["Low"].min())], "Close": [float(ts["Close"].iloc[-1])],
                                "Volume": [float(ts["Volume"].sum())]
                            }, index=[last_intra_date])
                            df = pd.concat([df, new_r])
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
            macd_above_zero = float(df["MACD"].iloc[-1]) > 0
            macd_cross = float(df["MACD"].iloc[-1]) > float(df["MACD_Signal"].iloc[-1])

            vol20 = float(df["Vol20"].iloc[-1]) if not np.isnan(df["Vol20"].iloc[-1]) else 0.0
            rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
            high20_prev = float(df["High20"].iloc[-2]) if len(df) >= 22 else close
            ema20_val = float(df["EMA20"].iloc[-1])
            ema50_val = float(df["EMA50"].iloc[-1])
            pullback_ema = (abs(close - ema20_val) / ema20_val <= 0.025) or (abs(close - ema50_val) / ema50_val <= 0.025)
            above_ema50 = close > ema50_val
            above_ema200 = close > float(df["EMA200"].iloc[-1]) if len(df) >= 200 else True
            within_52w = (close / float(df["High52"].iloc[-1])) >= 0.90 if float(df["High52"].iloc[-1]) > 0 else False

            pb_info = analyze_six_playbooks(df, account_size=account_size, spy_ret_63d=spy_ret_63d)
            is_breakout = (close >= high20_prev) and (pb_info["Paced_RVOL"] >= 1.25)

            if is_breakout and above_ema50:
                state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Closed above 20D high (${high20_prev:,.2f}) with {pb_info['Paced_RVOL']:.1f}x volume"
            elif above_ema50 and close > ema20_val:
                state, badge_class, reason = "Active Trend", "badge-trend", "Holding steadily above 20-day & 50-day EMA support"
            elif close < ema50_val:
                state, badge_class, reason = "Support Break", "badge-caution", "Violated 50-day EMA support level"
            else:
                state, badge_class, reason = "Entry Candidate", "badge-candidate", "Consolidating below resistance; setup developing"

            tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 10) + (30 if pb_info["Paced_RVOL"] >= 1.2 else 10)
            mom_score = (50 if is_breakout else 15) + (50 if within_52w else 20)
            composite = int((80 * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))

            record = {
                "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
                "Day_High": day_high, "Day_Low": day_low, "RSI": rsi, "RVOL": rvol,
                "EMA20_Val": ema20_val, "EMA50_Val": ema50_val,
                "MACD_Above_Zero": macd_above_zero, "MACD_Cross": macd_cross,
                "Above_EMA50": above_ema50, "Above_EMA200": above_ema200,
                "Is_Breakout": is_breakout, "Pullback_EMA50": pullback_ema,
                "Within_52W": within_52w, "State": state, "Badge": badge_class,
                "Reason": reason, "Score": composite,
                "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
            }
            record.update(pb_info)
            results[t] = record
        except Exception:
            continue

    if results:
        st.session_state.last_good_data.update(results)
        check_and_fire_live_ntfy(results)
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
        try:
            df_1h = t.history(period="1mo", interval="1h")
        except Exception:
            df_1h = None
        close = float(df["Close"].iloc[-1])
        prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
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
        pb_info = analyze_six_playbooks(df, account_size=account_size, df_1h=df_1h)
        rec = {
            "Ticker": sym, "Price": close, "Change": close - prev_close,
            "Change_Pct": ((close - prev_close) / prev_close) * 100 if prev_close else 0,
            "Day_High": float(df["High"].iloc[-1]), "Day_Low": float(df["Low"].iloc[-1]),
            "RSI": float(df["RSI"].iloc[-1]), "RVOL": 1.0,
            "EMA20_Val": float(df["EMA20"].iloc[-1]), "EMA50_Val": float(df["EMA50"].iloc[-1]),
            "State": "Active Trend", "Badge": "badge-trend", "Reason": pb_info["TCT_Explain"],
            "Score": 80, "History": df
        }
        rec.update(pb_info)
        return rec
    except Exception:
        return None

@st.cache_data(ttl=86400)
def fetch_ticker_fundamentals(ticker_symbol):
    data = {
        "Market Cap": "N/A", "Trailing P/E": "N/A", "Forward P/E": "N/A",
        "EPS (TTM)": "N/A", "Target Price": "N/A", "52W High": "N/A",
        "52W Low": "N/A", "Debt/Equity": "N/A", "Business Summary": "No corporate overview provided."
    }
    try:
        t = yf.Ticker(ticker_symbol)
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        fast = getattr(t, "fast_info", None)
        data["Market Cap"] = info.get("marketCap") or (getattr(fast, "market_cap", None) if fast else "N/A") or "N/A"
        data["Trailing P/E"] = info.get("trailingPE") or info.get("trailingPe") or "N/A"
        data["Forward P/E"] = info.get("forwardPE") or info.get("forwardPe") or "N/A"
        data["EPS (TTM)"] = info.get("trailingEps") or "N/A"
        data["Target Price"] = info.get("targetMeanPrice") or "N/A"
        data["52W High"] = info.get("fiftyTwoWeekHigh") or (getattr(fast, "year_high", None) if fast else "N/A") or "N/A"
        data["52W Low"] = info.get("fiftyTwoWeekLow") or (getattr(fast, "year_low", None) if fast else "N/A") or "N/A"
        data["Debt/Equity"] = info.get("debtToEquity", "N/A")
        data["Business Summary"] = info.get("longBusinessSummary", "No corporate overview provided.")
    except Exception:
        pass
    return data

def render_sparkline(prices, is_positive):
    fig = go.Figure(go.Scatter(y=prices, mode='lines', line=dict(color="#15803d" if is_positive else "#b91c1c", width=1.8)))
    fig.update_layout(
        height=45, width=120, margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)'
    )
    return fig

# --- MY ACTIVE POSITIONS MANAGER PANEL (10% DEFAULT STOP + 15% SELL HALF + 20-EMA TRAIL) ---
def render_active_positions_manager(key_prefix="pos"):
    st.markdown(
        '<div style="background:#ffffff; border:2px solid #0f291e; border-radius:10px; padding:14px 18px; margin-bottom:14px;">',
        unsafe_allow_html=True
    )
    st.markdown("### 💼 Log a Committed Buy / Manage Active Positions")
    st.caption(
        "Default rules applied automatically: **Initial Stop-Loss = -10% below Buy Price** · "
        "**Profit Target 1 = +15% Gain (Sell 50% of shares & raise Stop-Loss)** · "
        "**Trail Rule = Alert if price breaks below 20-Day EMA**."
    )
    f1, f2, f3, f4, f5, f6 = st.columns([1.3, 1.3, 1.2, 1.4, 1.4, 1.4])
    with f1:
        p_sym = st.text_input("Ticker Symbol", placeholder="e.g. NVDA", key=f"{key_prefix}_sym").upper().strip()
    with f2:
        p_buy = st.number_input("Buy Price ($)", min_value=0.01, value=100.0, step=0.5, key=f"{key_prefix}_buy")
    with f3:
        p_shs = st.number_input("Shares Bought", min_value=1, value=100, step=10, key=f"{key_prefix}_shs")
    with f4:
        p_dt = st.text_input("Date Bought", value=datetime.now().strftime("%Y-%m-%d"), key=f"{key_prefix}_dt")
    with f5:
        default_stop = round(p_buy * 0.90, 2)
        p_stop = st.number_input("Stop-Loss ($) [0 = Auto -10%]", min_value=0.0, value=0.0, step=0.5, key=f"{key_prefix}_stop")
    with f6:
        st.write("")
        if st.button("➕ Save Position", type="primary", use_container_width=True, key=f"{key_prefix}_add_btn") and p_sym:
            final_stop = round(p_stop, 2) if p_stop > 0 else default_stop
            positions[p_sym] = {
                "ticker": p_sym,
                "buy_price": round(float(p_buy), 2),
                "shares": int(p_shs),
                "buy_date": p_dt.strip(),
                "stop_loss": final_stop,
                "target_15": round(float(p_buy) * 1.15, 2),
                "half_sold": False
            }
            ok, msg = sync_positions_to_github(positions)
            st.toast(msg)
            st.rerun()

    if positions:
        st.markdown("---")
        st.markdown("**🔧 Quick Rule Actions: Raise Stop-Loss, Mark 50% Sold at +15%, or Close Position**")
        for sym, pos in list(positions.items()):
            mc1, mc2, mc3, mc4, mc5 = st.columns([2.2, 1.6, 1.4, 2.2, 1.0])
            status_tag = "✅ 50% Sold (Riding Trail)" if pos.get("half_sold") else "⏳ Full Position"
            mc1.markdown(
                f"**{sym}** · Bought **{pos['shares']} shs** @ **${pos['buy_price']:,.2f}** ({pos.get('buy_date', '')}) · *{status_tag}*"
            )
            new_stp = mc2.number_input(
                f"Stop for {sym}", min_value=0.01, value=float(pos.get("stop_loss", pos["buy_price"] * 0.90)),
                step=0.5, key=f"{key_prefix}_ed_stp_{sym}", label_visibility="collapsed"
            )
            if mc3.button("💾 Raise/Set Stop", key=f"{key_prefix}_btn_stp_{sym}", use_container_width=True):
                positions[sym]["stop_loss"] = round(float(new_stp), 2)
                sync_positions_to_github(positions)
                st.toast(f"Updated {sym} Stop-Loss to ${new_stp:,.2f}")
                st.rerun()
            if mc4.button(
                "💰 Mark 50% Sold & Raise Stop to Breakeven",
                key=f"{key_prefix}_btn_half_{sym}",
                disabled=bool(pos.get("half_sold", False)),
                use_container_width=True
            ):
                positions[sym]["shares"] = max(1, int(pos["shares"]) // 2)
                positions[sym]["half_sold"] = True
                positions[sym]["stop_loss"] = max(float(pos["stop_loss"]), float(pos["buy_price"]))
                sync_positions_to_github(positions)
                st.toast(f"{sym}: 50% shares sold & stop raised to breakeven (${pos['buy_price']:,.2f})!")
                st.rerun()
            if mc5.button("🗑️ Close", key=f"{key_prefix}_btn_del_{sym}", use_container_width=True):
                positions.pop(sym, None)
                sync_positions_to_github(positions)
                st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

def evaluate_position_rules(sym, pos, d):
    """Evaluates personal trade rules (10% stop, +15% half-profit, 20-EMA break)."""
    price = d["Price"]
    buy_p = float(pos.get("buy_price", price))
    shares = int(pos.get("shares", 1))
    stop_p = float(pos.get("stop_loss", round(buy_p * 0.90, 2)))
    tgt_15 = float(pos.get("target_15", round(buy_p * 1.15, 2)))
    half_sold = bool(pos.get("half_sold", False))
    ema20 = d["EMA20_Val"]

    pnl_per_share = price - buy_p
    pnl_dollars = pnl_per_share * shares
    pnl_pct = ((price - buy_p) / buy_p) * 100.0 if buy_p > 0 else 0.0

    if price <= stop_p:
        rule_badge = "🚨 STOP HIT — SELL"
        rule_bg = "#fee2e2"
        rule_clr = "#b91c1c"
    elif not half_sold and price >= tgt_15:
        rule_badge = "💰 +15% HIT: SELL 50% & RAISE STOP"
        rule_bg = "#dcfce7"
        rule_clr = "#15803d"
    elif price < ema20:
        rule_badge = "⚠️ BROKE 20-EMA — TRAIL WARNING"
        rule_bg = "#ffedd5"
        rule_clr = "#c2410c"
    elif half_sold:
        rule_badge = "✅ 50% SOLD · RIDING ABOVE 20-EMA"
        rule_bg = "#dbeafe"
        rule_clr = "#1d4ed8"
    else:
        rule_badge = "🟢 HOLDING · RULES INTACT"
        rule_bg = "#f0fdf4"
        rule_clr = "#15803d"

    return {
        "buy_price": buy_p, "shares": shares, "buy_date": pos.get("buy_date", "—"),
        "stop_p": stop_p, "tgt_15": tgt_15, "half_sold": half_sold,
        "pnl_dollars": pnl_dollars, "pnl_pct": pnl_pct,
        "rule_badge": rule_badge, "rule_bg": rule_bg, "rule_clr": rule_clr
    }

def render_watchlist_reorder_panel(folder_name, key_prefix="wl"):
    st.markdown(
        '<div style="background:#ffffff; border:1px solid #dcd6cb; border-radius:8px; padding:12px 16px; margin-bottom:12px;">',
        unsafe_allow_html=True
    )
    c_top1, c_top2, c_top3 = st.columns([2.2, 2.2, 1.6])
    with c_top1:
        st.markdown(f"**✏️ Editing Watchlist: `{folder_name}`**")
        st.caption("Tap ⏫ (Top), ⬆️ (Up), ⬇️ (Down), or 🗑️ (Delete) to arrange your exact order.")
    with c_top2:
        new_list_name = st.text_input("Create New Watchlist Folder", placeholder="e.g. AI & Semis", key=f"{key_prefix}_new_folder_in", label_visibility="collapsed")
        if st.button("➕ Create New Watchlist", key=f"{key_prefix}_btn_new_folder") and new_list_name.strip():
            clean_name = new_list_name.strip()
            if clean_name not in watchlists:
                watchlists[clean_name] = []
                ok, msg = sync_watchlists_to_github(watchlists)
                st.toast(msg)
                st.rerun()
    with c_top3:
        if st.button("💾 Save & Sync Order to GitHub", type="primary", use_container_width=True, key=f"{key_prefix}_sync_gh"):
            ok, msg = sync_watchlists_to_github(watchlists)
            st.success(msg) if ok else st.warning(msg)

    syms = watchlists.get(folder_name, [])
    if not syms:
        st.info("This watchlist is currently empty. Add a stock symbol above!")
    else:
        e_col1, e_col2 = st.columns(2)
        half = (len(syms) + 1) // 2
        for i, s in enumerate(syms):
            with (e_col1 if i < half else e_col2):
                r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
                r1.markdown(f"**{i+1}. {s}**")
                if r2.button("⏫", key=f"{key_prefix}_top_{folder_name}_{s}_{i}", disabled=(i == 0)):
                    syms.pop(i); syms.insert(0, s); save_json(DATA_FILE, watchlists); st.rerun()
                if r3.button("⬆️", key=f"{key_prefix}_up_{folder_name}_{s}_{i}", disabled=(i == 0)):
                    syms[i - 1], syms[i] = syms[i], syms[i - 1]; save_json(DATA_FILE, watchlists); st.rerun()
                if r4.button("⬇️", key=f"{key_prefix}_dn_{folder_name}_{s}_{i}", disabled=(i == len(syms) - 1)):
                    syms[i + 1], syms[i] = syms[i], syms[i + 1]; save_json(DATA_FILE, watchlists); st.rerun()
                if r5.button("🗑️", key=f"{key_prefix}_del_{folder_name}_{s}_{i}"):
                    syms.pop(i); sync_watchlists_to_github(watchlists); st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# --- TOP UNIFORM MACRO BANNER & MARKET REGIME TRAFFIC LIGHT ---
MACRO_SYMBOLS = {
    "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
    "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
    "DXY (USD)": "DX-Y.NYB", "USD/JPY": "JPY=X", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"
}

@st.cache_data(ttl=300)
def fetch_macro_and_regime():
    ticks = list(MACRO_SYMBOLS.values())
    out = {}
    regime = {
        "label": "🟢 MARKET REGIME: BULLISH — S&P 500 Holding Trend · Favorable for Momentum & TCT Setups",
        "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
    }
    try:
        df = yf.download(ticks, period="3mo", interval="1d", group_by="ticker", progress=False)
        for name, sym in MACRO_SYMBOLS.items():
            sub = _extract_ticker_df(df, sym, len(ticks)).dropna(subset=["Close"])
            if len(sub) >= 2:
                c, pc = float(sub["Close"].iloc[-1]), float(sub["Close"].iloc[-2])
                out[name] = (c, c - pc, ((c - pc) / pc) * 100.0 if pc != 0 else 0.0)
        sp = _extract_ticker_df(df, "^GSPC", len(ticks)).dropna(subset=["Close"])
        if len(sp) >= 50:
            sp_c = float(sp["Close"].iloc[-1])
            sp_ema20 = float(sp["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
            sp_ema50 = float(sp["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
            vix_c = out.get("VIX", (18.0, 0, 0))[0]
            if sp_c > sp_ema50 and sp_c > sp_ema20 and vix_c < 21.0:
                regime = {
                    "label": f"🟢 MARKET REGIME: BULLISH (S&P 500 Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for Pure Momentum & TCT Buys",
                    "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
                }
            elif sp_c < sp_ema50 or vix_c >= 25.0:
                regime = {
                    "label": f"🔴 MARKET REGIME: RISK-OFF / CORRECTION (S&P Below 50 EMA or VIX {vix_c:.1f}) — Protect Capital, Honor Stop-Losses",
                    "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"
                }
            else:
                regime = {
                    "label": f"🟡 MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating · VIX {vix_c:.1f}) — Focus on Pure Momentum Leaders & 20-EMA Pullbacks",
                    "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"
                }
    except Exception:
        pass
    return out, regime

# --- PRIMARY SIDEBAR NAVIGATION ---
st.sidebar.markdown(
    '<div style="padding: 10px 0 20px 0;">'
    '<span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span>'
    '<span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">MOMENTUM & POSITION ENGINE</span>'
    '<h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2>'
    '<span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Momentum · Swing · TCT v11.2</span>'
    '</div>',
    unsafe_allow_html=True
)

navigation = st.sidebar.radio(
    "Navigation",
    [
        "Dashboard",
        "⚡ Live Real-Time Quotes",
        "Screener",
        "Watchlist",
        "Precious Metals, Crypto & Currency",
        "News & Earnings",
        "Settings"
    ],
    key="nav_radio", label_visibility="collapsed", on_change=clear_inspection
)

st.sidebar.markdown("---")
sync_badge = "🟢 GitHub Auto-Sync Active" if get_github_token() else "🟡 Local Mode (Add GITHUB_TOKEN)"
st.sidebar.markdown(
    f'<div style="position: fixed; bottom: 18px; font-size: 0.74rem; color: #a1a1aa;">{sync_badge}<br>Tap any <b>Stock Symbol</b> to open chart</div>',
    unsafe_allow_html=True
)

# --- MACRO BANNER & MARKET REGIME (HIDDEN ON FULL-SCREEN LIVE QUOTES PAGE) ---
if navigation != "⚡ Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
    macro_data, regime_info = fetch_macro_and_regime()
    if macro_data:
        cards_html = "".join([
            f'<div class="macro-card"><div class="macro-title">{name}</div>'
            f'<div class="macro-price">{price:,.2f}</div>'
            f'<div class="{"tick-pos" if chg >= 0 else "tick-neg"}">'
            f'{"▲ +" if chg >= 0 else "▼ "}{chg:.2f} ({"+" if chg >= 0 else ""}{pct:.2f}%)</div></div>'
            for name, (price, chg, pct) in macro_data.items()
        ])
        st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:{regime_info["bg"]}; border:1px solid {regime_info["border"]}; '
        f'color:{regime_info["color"]}; padding:8px 14px; border-radius:8px; font-size:0.82rem; '
        f'font-weight:600; margin-bottom:16px;">{regime_info["label"]}</div>',
        unsafe_allow_html=True
    )

# ==============================================================================
# CONTENT ROUTING
# ==============================================================================
if st.session_state.inspect_symbol is not None:
    sym = st.session_state.inspect_symbol
    col_back, col_title = st.columns([1.2, 8.8])
    with col_back:
        if st.button("⬅ Back", type="primary"):
            clear_inspection()
            st.rerun()
    with col_title:
        st.markdown(f"<h1>{sym} · Momentum, Swing & TCT Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        raw_mcap = funds.get("Market Cap")
        mcap_text = f"${raw_mcap/1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"

        f1.metric("Price", f"${d['Price']:,.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Action Signal", d["TCT_Action"])
