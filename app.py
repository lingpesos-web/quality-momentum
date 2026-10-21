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
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Quality Momentum, Swing & TCT Cockpit",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZE SESSION STATE & URL ROUTING ---
if "inspect_symbol" not in st.session_state:
    st.session_state.inspect_symbol = None
if "rt_chart_symbol" not in st.session_state:
    st.session_state.rt_chart_symbol = None
if "nav_radio" not in st.session_state:
    st.session_state.nav_radio = "Dashboard"
if "screener_matches" not in st.session_state:
    st.session_state.screener_matches = None
if "screener_title" not in st.session_state:
    st.session_state.screener_title = None

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

# --- NTFY ALERT ENGINE (ASCII-SAFE HEADER FIX) ---
def send_ntfy_alert(message, title="Daily Portfolio Briefing"):
    try:
        ascii_title = title.encode("ascii", "ignore").decode("ascii").strip()
        if not ascii_title:
            ascii_title = "Momentum and Swing Alert"
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

# --- CUSTOM CSS: MANUS EDITORIAL THEME + LARGE-FONT 2-COLUMN LIVE BOARD ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600;700;800&display=swap');

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
    margin-bottom: 12px;
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
    margin-bottom: 14px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.03);
}
.ticker-link {
    font-size: 1.25rem;
    font-weight: 700;
    color: #0f291e !important;
    text-decoration: none !important;
    border-bottom: 2px solid #c5a059;
    padding-bottom: 1px;
    transition: all 0.15s ease;
}
.ticker-link:hover {
    color: #15803d !important;
    border-bottom-color: #15803d;
    background-color: #f0fdf4;
    border-radius: 4px;
    padding: 2px 6px;
}
.hero-ticker-link {
    font-size: 1.85rem;
    font-weight: 700;
    color: #ffffff !important;
    text-decoration: none !important;
    border-bottom: 2px dashed #c5a059;
    padding-bottom: 2px;
}
.hero-ticker-link:hover {
    color: #4ade80 !important;
    border-bottom-color: #4ade80;
}
.badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.68rem;
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
.badge-rs-lead { background: #ecfdf5; color: #047857; border: 1px solid #a7f3d0; }
.badge-rs-lag { background: #f4f4f5; color: #71717a; }
.badge-earn-warn { background: #ffedd5; color: #c2410c; border: 1px solid #fdba74; font-weight: 700; }
.pill {
    display: inline-flex;
    align-items: center;
    background: #e9e4db;
    color: #0f291e !important;
    text-decoration: none !important;
    padding: 4px 10px;
    border-radius: 14px;
    font-size: 0.8rem;
    font-weight: 600;
    margin-right: 6px;
    margin-bottom: 6px;
}
.pill:hover {
    background: #d6cfc2;
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
.age-badge {
    background: #f1f5f9;
    color: #334155;
    padding: 2px 6px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.68rem;
    margin-left: 6px;
}
.trade-ticket {
    background: #f8f6f0;
    border: 1px solid #e2ddd2;
    border-radius: 8px;
    padding: 10px 12px;
    margin-top: 10px;
    font-size: 0.80rem;
}

/* LARGE-FONT, TIGHT-COLUMN 2-COLUMN LIVE WATCHBOARD TABLE */
.live-board-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
    width: 100%;
    margin-top: 4px;
}
@media (max-width: 900px) {
    .live-board-grid {
        grid-template-columns: 1fr;
    }
}
.live-quote-table {
    width: 100%;
    border-collapse: collapse;
    background: #ffffff;
    border: 1px solid #d4cec3;
    border-radius: 6px;
    overflow: hidden;
    font-size: 1.12rem;
    table-layout: auto;
}
.live-quote-table thead th {
    background: #0f291e;
    color: #f4efe6;
    font-weight: 700;
    font-size: 0.82rem;
    text-transform: uppercase;
    letter-spacing: 0.02em;
    padding: 6px 5px;
    text-align: right;
    white-space: nowrap;
}
.live-quote-table thead th:nth-child(1),
.live-quote-table thead th:nth-child(2) {
    text-align: left;
}
.live-quote-table tbody tr {
    border-bottom: 1px solid #eae5dc;
    line-height: 1.25;
}
.live-quote-table tbody tr:nth-child(even) {
    background-color: #faf8f5;
}
.live-quote-table tbody tr:hover {
    background-color: #ecfdf5;
}
.live-quote-table td {
    padding: 5px 5px;
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.live-quote-table td:nth-child(1) {
    text-align: left;
    font-size: 0.92rem;
    font-weight: 700;
    padding-left: 6px;
    padding-right: 4px;
}
.live-quote-table td:nth-child(2) {
    text-align: left;
    font-weight: 800;
    padding-left: 4px;
    padding-right: 4px;
}
.rt-sym-link {
    color: #0f291e !important;
    text-decoration: none !important;
    font-weight: 800;
    font-size: 1.18rem;
    border-bottom: 2px solid #c5a059;
}
.rt-sym-link:hover {
    color: #15803d !important;
    background: #dcfce7;
    padding: 1px 4px;
    border-radius: 3px;
}
.rt-dossier-link {
    text-decoration: none !important;
    font-size: 0.85rem;
    margin-left: 3px;
    opacity: 0.7;
}
.rt-dossier-link:hover {
    opacity: 1.0;
}
</style>
""", unsafe_allow_html=True)


# --- GITHUB AUTO-SYNC FOR WATCHLISTS.JSON (WITH 3+ LISTS SUPPORT) ---
DATA_FILE = "watchlists.json"
SETTINGS_FILE = "settings.json"
GITHUB_REPO = "lingpesos-web/quality-momentum"
GITHUB_BRANCH = "main"

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

def sync_watchlists_to_github(data):
    save_json(DATA_FILE, data)
    token = get_github_token()
    if not token:
        return False, "Saved locally (Add GITHUB_TOKEN in Streamlit Secrets for permanent cloud sync)."
    
    api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{DATA_FILE}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Quality-Momentum-Cockpit"
    }
    try:
        req_get = urllib.request.Request(f"{api_url}?ref={GITHUB_BRANCH}", headers=headers)
        sha = None
        try:
            with urllib.request.urlopen(req_get, timeout=6) as resp:
                existing = json.loads(resp.read().decode("utf-8"))
                sha = existing.get("sha")
        except Exception:
            pass

        json_bytes = json.dumps(data, indent=2).encode("utf-8")
        b64_content = base64.b64encode(json_bytes).decode("utf-8")
        payload = {
            "message": f"Auto-sync watchlists.json ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
            "content": b64_content,
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
                return True, "✅ Permanently synced to GitHub watchlists.json!"
    except Exception as e:
        return False, f"Saved locally (GitHub sync error: {str(e)[:60]})"
    return False, "Saved locally."

watchlists = load_json(DATA_FILE, {
    "Active Portfolio": ["NVDA", "SLV"],
    "Opportunity Radar": ["PLTR", "MU"],
    "Special Case Stocks": ["COIN", "MSTR", "SOXL", "IONQ"]
})

if "Active Portfolio" not in watchlists:
    watchlists["Active Portfolio"] = ["NVDA", "SLV"]
if "Opportunity Radar" not in watchlists:
    watchlists["Opportunity Radar"] = ["PLTR", "MU"]
if "Special Case Stocks" not in watchlists:
    watchlists["Special Case Stocks"] = []
    save_json(DATA_FILE, watchlists)

def get_all_monitored_tickers():
    combined = []
    for folder_syms in watchlists.values():
        if isinstance(folder_syms, list):
            combined.extend(folder_syms)
    return list(dict.fromkeys(combined))

settings = load_json(SETTINGS_FILE, {
    "w_fund": 40, "w_tech": 40, "w_mom": 20,
    "account_size": 100000,
    "news_limit": 60,
    "max_news_age_hours": 72,
    "alert_breakout": True, "alert_support": True, "alert_earnings": True,
    "email": "cashmiles@gmail.com"
})
if "account_size" not in settings:
    settings["account_size"] = 100000
if "news_limit" not in settings:
    settings["news_limit"] = 60
if "max_news_age_hours" not in settings:
    settings["max_news_age_hours"] = 72


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
        "COIN", "MSTR", "HOOD", "SOFI", "SQ", "PYPL", "MARA", "RIOT", "CLSK", "IREN",
        "CORZ", "HUT", "WULF", "CIFR", "GALAXY", "JPM", "GS", "MS", "BLK", "BX",
        "KKR", "APO", "ARES", "V", "MA", "AXP", "BAC", "WFC", "C", "SCHW"
    ],
    "Communication & Internet Leaders": [
        "GOOGL", "META", "NFLX", "AMZN", "AAPL", "TSLA", "SPOT", "UBER", "DASH", "ABNB",
        "BKNG", "EXPE", "TMUS", "DIS", "CMCSA", "RBLX", "U", "EA", "TTWO", "PINS"
    ],
    "Energy, Nuclear & Precious Metals": [
        "CEG", "VST", "NRG", "TLN", "OKLO", "SMR", "CCJ", "UEC", "NXE", "DNN",
        "NEE", "SO", "DUK", "GEV", "XOM", "CVX", "COP", "EOG", "SLB", "HAL",
        "NEM", "GOLD", "AEM", "WPM", "FNV", "PAAS", "AG", "CDE", "HL", "FCX", "SLV", "GLD"
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

# --- STRICT FRESHNESS & ANTI-CLICKBAIT NEWS ENGINE ---
BLOCKED_NEWS_SOURCES = {
    "marketbeat", "zacks", "defense world", "etf daily news", "ticker report",
    "american banking news", "simply wall st", "stocknews.com", "wall street zen",
    "holdings channel", "transcript daily", "modern readers", "watch list news"
}

STALE_HEADLINE_PATTERNS = [
    "if you invested", "years ago", "last year", "months ago",
    "why shares plunged in ", "heres how much "
]

def parse_pub_date(date_str):
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None

def format_age_badge(age_hours):
    if age_hours < 1.0:
        mins = max(1, int(age_hours * 60))
        return f"{mins}m ago"
    elif age_hours < 24.0:
        return f"{int(age_hours)}h ago"
    else:
        days = int(age_hours // 24)
        return f"{days}d ago"

def _fetch_rss_raw(query, max_per_query=18, ticker_tag=None, max_age_hours=72):
    q_with_time = query if "when:" in query else f"{query} when:3d"
    encoded_query = urllib.parse.quote(q_with_time)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    articles = []
    now_utc = datetime.now(timezone.utc)
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:max_per_query]:
            raw_title = item.find("title").text if item.find("title") is not None else ""
            link = item.find("link").text if item.find("link") is not None else "#"
            pub_date_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"

            if not raw_title or not pub_date_raw:
                continue

            src_lower = source.lower().strip()
            if any(bad in src_lower for bad in BLOCKED_NEWS_SOURCES):
                continue

            clean_title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            title_lower = clean_title.lower()
            if any(pat in title_lower for pat in STALE_HEADLINE_PATTERNS):
                continue

            dt_obj = parse_pub_date(pub_date_raw)
            if dt_obj is None:
                continue
            age_hours = (now_utc - dt_obj).total_seconds() / 3600.0
            if age_hours < -1.0 or age_hours > max_age_hours:
                continue

            formatted_date = dt_obj.strftime("%b %d · %H:%M UTC")
            age_label = format_age_badge(max(0.05, age_hours))

            articles.append({
                "title": clean_title,
                "link": link,
                "publisher": source,
                "date": formatted_date,
                "age": age_label,
                "timestamp": dt_obj.timestamp(),
                "ticker": ticker_tag or "MARKET"
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
    pool = []
    seen_links = set()
    seen_titles = set()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_fetch_rss_raw, q, 25, "MARKET", max_age_hours) for q in queries]
        for fut in futures:
            for item in fut.result():
                norm_title = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_title not in seen_titles:
                    seen_links.add(item["link"])
                    seen_titles.add(norm_title)
                    pool.append(item)
    pool = sorted(pool, key=lambda x: x["timestamp"], reverse=True)
    return pool[:max_items]

@st.cache_data(ttl=600)
def fetch_watchlist_news_pool(tickers, max_items=60, max_age_hours=72):
    if not tickers:
        return []
    pool = []
    seen_links = set()
    seen_titles = set()
    unique_tickers = list(dict.fromkeys(tickers))
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(_fetch_rss_raw, f'"{sym}" stock when:3d', 4, sym, max_age_hours): sym for sym in unique_tickers}
        for fut in futures:
            for item in fut.result():
                norm_title = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_title not in seen_titles:
                    seen_links.add(item["link"])
                    seen_titles.add(norm_title)
                    pool.append(item)
    pool = sorted(pool, key=lambda x: x["timestamp"], reverse=True)
    return pool[:max_items]

@st.cache_data(ttl=600)
def fetch_metals_crypto_fx_news(max_items=50, max_age_hours=72):
    queries = [
        ("gold silver copper prices commodities market when:3d", "METALS"),
        ("Bitcoin Ethereum Solana XRP crypto market when:3d", "CRYPTO"),
        ("US Dollar Index DXY USD JPY EUR USD forex when:3d", "FX/USD")
    ]
    pool = []
    seen_links = set()
    seen_titles = set()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(_fetch_rss_raw, q, 22, tag, max_age_hours) for q, tag in queries]
        for fut in futures:
            for item in fut.result():
                norm_title = item["title"][:45].lower()
                if item["link"] not in seen_links and norm_title not in seen_titles:
                    seen_links.add(item["link"])
                    seen_titles.add(norm_title)
                    pool.append(item)
    pool = sorted(pool, key=lambda x: x["timestamp"], reverse=True)
    return pool[:max_items]


# --- EARNINGS WARNING HELPER ---
@st.cache_data(ttl=14400)
def fetch_upcoming_earnings_map(tickers):
    if not tickers:
        return {}
    out = {}
    now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    def _check_one(sym):
        if any(ch in sym for ch in ["=X", "=F", "-USD", "^", "."]):
            return sym, None
        try:
            cal = yf.Ticker(sym).calendar
            raw_date = None
            if isinstance(cal, dict) and "Earnings Date" in cal:
                dates = cal["Earnings Date"]
                raw_date = dates[0] if isinstance(dates, list) and dates else dates
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                raw_date = cal.loc["Earnings Date"].iloc[0]
            if raw_date is not None:
                dt_parsed = pd.to_datetime(raw_date).to_pydatetime().replace(tzinfo=None, hour=0, minute=0, second=0)
                days_diff = (dt_parsed - now_dt).days
                if 0 <= days_diff <= 45:
                    return sym, (days_diff, dt_parsed.strftime("%Y-%m-%d"))
        except Exception:
            pass
        return sym, None

    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, res in ex.map(_check_one, list(dict.fromkeys(tickers))):
            if res is not None:
                out[sym] = res
    return out


# --- US MARKET SESSION CLOCK & 8:00 AM HKT SETTLEMENT GLITCH PATCHER ---
def get_expected_us_session_date_and_pace():
    """
    Returns (expected_latest_us_trading_date, intraday_volume_pace_fraction).
    Fixes the 8:00 AM HKT (8:00 PM ET) Yahoo Finance daily bar rollover drop
    and scales intraday volume pace during open market hours.
    """
    now_ny = datetime.now(ZoneInfo("America/New_York"))
    weekday = now_ny.weekday()  # 0=Mon .. 6=Sun
    mins_now = now_ny.hour * 60 + now_ny.minute

    if weekday == 5:  # Saturday -> Friday was last session
        expected_date = (now_ny - timedelta(days=1)).date()
        pace = 1.0
    elif weekday == 6:  # Sunday -> Friday was last session
        expected_date = (now_ny - timedelta(days=2)).date()
        pace = 1.0
    else:
        if mins_now < (9 * 60 + 32):
            # Before 9:32 AM ET on a weekday -> previous trading day
            prev_days = 3 if weekday == 0 else 1
            expected_date = (now_ny - timedelta(days=prev_days)).date()
            pace = 1.0
        elif mins_now < (16 * 60):
            # Regular US Market Hours (9:32 AM to 4:00 PM ET) -> scale volume pace
            expected_date = now_ny.date()
            elapsed = max(15, mins_now - (9 * 60 + 30))
            pace = min(1.0, max(0.08, elapsed / 390.0))
        else:
            # After 4:00 PM ET (including 8:00 PM ET / 8:00 AM HKT settlement window!)
            expected_date = now_ny.date()
            pace = 1.0

    return expected_date, pace

def patch_df_with_1h_session(df_daily, df_1h):
    """
    If Yahoo Finance's 1d dataframe temporarily dropped the latest completed US session
    (e.g. around 8:00 AM HKT), reconstructs the missing daily bar from 1h regular-hours bars.
    """
    if df_1h is None or df_1h.empty or df_daily.empty:
        return df_daily
    try:
        sub_1h = df_1h.dropna(subset=["Close", "High", "Low", "Open"])
        if sub_1h.empty:
            return df_daily
        last_1d_date = pd.to_datetime(df_daily.index[-1]).date()
        idx_dates = pd.to_datetime(sub_1h.index).date
        latest_1h_date = idx_dates[-1]

        if latest_1h_date > last_1d_date:
            day_bars = sub_1h[idx_dates == latest_1h_date]
            if not day_bars.empty:
                new_row = pd.DataFrame({
                    "Open": [float(day_bars["Open"].iloc[0])],
                    "High": [float(day_bars["High"].max())],
                    "Low": [float(day_bars["Low"].min())],
                    "Close": [float(day_bars["Close"].iloc[-1])],
                    "Volume": [float(day_bars["Volume"].sum())]
                }, index=[pd.Timestamp(latest_1h_date)])
                df_patched = pd.concat([df_daily[["Open", "High", "Low", "Close", "Volume"]], new_row])
                return df_patched
    except Exception:
        pass
    return df_daily


# --- 6-PLAYBOOK MULTI-STRATEGY ENGINE (TCT + 4 SWING STRATEGIES + MOMENTUM) ---
def analyze_multi_playbook(df, account_size=100000, spy_ret_63d=0.0, df_1h=None, vol_pace=1.0):
    """
    Evaluates 6 distinct rules-based strategies for each stock:
      1. 📐 TCT Bottom Accumulation (25+ bar slow decline, Tap 1/2/3 & BOS)
      2. 🎯 20-EMA 'Holy Grail' Pullback Swing (Strong uptrend dip to 20 EMA + curl up)
      3. ⚡ Volatility Squeeze Breakout (Bollinger Band / 5-day tight range coil breakout)
      4. 🪃 RSI-2 Oversold Snapback (Larry Connors mean-reversion bounce above 200 EMA)
      5. 🔥 High-Volume Gap Ignition (Power volume >=1.8x surge holding top of range)
      6. 🚀 Momentum Trend Swing (20-day / 5-day breakout & trend following)
    """
    n = len(df)
    open_arr = df["Open"].values.astype(float)
    close_arr = df["Close"].values.astype(float)
    high_arr = df["High"].values.astype(float)
    low_arr = df["Low"].values.astype(float)
    vol_arr = df["Volume"].values.astype(float)
    curr_close = float(close_arr[-1])
    prev_close = float(close_arr[-2]) if n >= 2 else curr_close
    curr_open = float(open_arr[-1])
    curr_high = float(high_arr[-1])
    curr_low = float(low_arr[-1])

    # Relative Strength vs S&P 500 (63-Day / 3-Month)
    lookback_rs = min(63, n - 1)
    stock_ret_63d = ((curr_close - float(close_arr[-1 - lookback_rs])) / float(close_arr[-1 - lookback_rs])) * 100.0 if lookback_rs > 5 else 0.0
    rs_diff = stock_ret_63d - spy_ret_63d
    rs_leader = bool(rs_diff >= 2.0)

    # Liquidity Check: 20D Median Daily Dollar Volume >= $50M
    dollar_vol_20 = pd.Series(close_arr[-20:] * vol_arr[-20:]).median() if n >= 20 else 0.0
    liq_pass = bool(dollar_vol_20 >= 50_000_000)

    # Moving Averages & ATR(14)
    ema20_ser = df["Close"].ewm(span=20, adjust=False).mean()
    ema50_ser = df["Close"].ewm(span=50, adjust=False).mean()
    ema200_ser = df["Close"].ewm(span=200, adjust=False).mean()
    ema20 = float(ema20_ser.iloc[-1])
    ema50 = float(ema50_ser.iloc[-1])
    ema200 = float(ema200_ser.iloc[-1]) if n >= 100 else ema50 * 0.92

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr_ser = tr.rolling(14).mean()
    atr14_daily = float(atr_ser.iloc[-1]) if not np.isnan(atr_ser.iloc[-1]) and float(atr_ser.iloc[-1]) > 0 else curr_close * 0.025
    atr14_1h_est = atr14_daily / 2.55

    # ADX(14) for Trend Strength
    up_move = df["High"] - df["High"].shift(1)
    down_move = df["Low"].shift(1) - df["Low"]
    pos_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    neg_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    pos_di = 100 * (pd.Series(pos_dm, index=df.index).rolling(14).mean() / (atr_ser + 1e-9))
    neg_di = 100 * (pd.Series(neg_dm, index=df.index).rolling(14).mean() / (atr_ser + 1e-9))
    dx = 100 * ((pos_di - neg_di).abs() / (pos_di + neg_di + 1e-9))
    adx_val = float(dx.rolling(14).mean().iloc[-1]) if len(dx) >= 28 and not np.isnan(dx.rolling(14).mean().iloc[-1]) else 22.0

    # 2-Period RSI (Larry Connors RSI-2)
    delta_c = df["Close"].diff()
    gain2 = delta_c.where(delta_c > 0, 0.0).ewm(alpha=1/2, adjust=False).mean()
    loss2 = (-delta_c.where(delta_c < 0, 0.0)).ewm(alpha=1/2, adjust=False).mean()
    rsi2 = float(100 - (100 / (1 + (gain2.iloc[-1] / (loss2.iloc[-1] + 1e-9)))))

    # Bollinger Band Width & 5-Day Tight Coil Width
    bb_mid = df["Close"].rolling(20).mean()
    bb_std = df["Close"].rolling(20).std()
    bb_width_ser = ((bb_std * 4.0) / (bb_mid + 1e-9)) * 100.0
    curr_bb_width = float(bb_width_ser.iloc[-1]) if not np.isnan(bb_width_ser.iloc[-1]) else 10.0
    min_bb_width_60 = float(bb_width_ser.iloc[-60:].quantile(0.25)) if n >= 60 else 6.0

    high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_high
    low_5d_prev = float(np.min(low_arr[-6:-1])) if n >= 7 else curr_low
    coil_5d_pct = ((high_5d_prev - low_5d_prev) / curr_close) * 100.0 if curr_close > 0 else 10.0

    # Pace-Adjusted Volume Ratio
    vol20 = float(df["Volume"].rolling(20).iloc[-20:-1].mean()) if n >= 21 else float(np.mean(vol_arr))
    paced_vol_today = (float(vol_arr[-1]) / max(vol_pace, 0.08))
    paced_rvol = (paced_vol_today / vol20) if vol20 > 0 else 1.0

    # Confirmed Daily Swing Points (k = 3)
    swing_highs = []
    swing_lows = []
    for i in range(3, n - 3):
        if high_arr[i] == np.max(high_arr[i - 3:i + 4]):
            swing_highs.append((i, float(high_arr[i])))
        if low_arr[i] == np.min(low_arr[i - 3:i + 4]):
            swing_lows.append((i, float(low_arr[i])))

    # --- CHECK PLAYBOOK 1: TRUE TCT BOTTOM ACCUMULATION (Handbook Rules) ---
    lookback = min(n, 130)
    start_idx = n - lookback
    peak_rel_idx = int(np.argmax(high_arr[start_idx:max(start_idx + 1, n - 20)]))
    peak_idx = start_idx + peak_rel_idx
    peak_price = float(high_arr[peak_idx])
    recent_lows = [(idx, val) for idx, val in swing_lows if idx > peak_idx]

    tct_valid_range = False
    slow_decline_25 = False
    no_vertical_flush = True
    tap1_price, tap2_price, tap3_price = None, None, None
    range_high, bos_level = None, None
    playbook_name = "🚀 Momentum Trend Swing"
    swing_type = "MOMENTUM"

    if len(recent_lows) >= 2 and curr_close <= peak_price * 0.92:
        for i_l in range(len(recent_lows) - 1):
            t1_idx, t1_val = recent_lows[i_l]
            for j_l in range(i_l + 1, len(recent_lows)):
                t2_idx, t2_val = recent_lows[j_l]
                if t2_idx - t1_idx < 3 or (n - t2_idx) > 45:
                    continue
                r_high = float(np.max(high_arr[t1_idx:t2_idx + 1]))
                rng_height = r_high - t1_val
                if rng_height <= t1_val * 0.03 or rng_height >= t1_val * 0.38:
                    continue
                if (peak_price - t1_val) < 0.30 * rng_height:
                    continue
                dev_limit = t1_val - 0.30 * rng_height
                min_close_t2 = float(np.min(close_arr[t1_idx:t2_idx + 1]))
                if t2_val <= t1_val * 1.015 and min_close_t2 >= dev_limit:
                    if (t2_idx - peak_idx) < 25:
                        continue
                    slow_decline_25 = True
                    flush_ok = True
                    for b_i in range(t1_idx, t2_idx + 1):
                        top_p = (high_arr[b_i] - t1_val) / rng_height
                        bot_p = (low_arr[b_i] - t1_val) / rng_height
                        if top_p >= 0.80 and bot_p <= 0.22:
                            flush_ok = False
                            break
                    if not flush_ok:
                        continue

                    tap1_price = t1_val
                    tap2_price = t2_val
                    range_high = r_high
                    tap3_price = float(np.min(low_arr[t2_idx:]))

                    if df_1h is not None and len(df_1h) >= 15:
                        h1_highs = df_1h["High"].values.astype(float)
                        h1_swings = [float(h1_highs[k]) for k in range(3, len(h1_highs) - 3) if h1_highs[k] == np.max(h1_highs[k - 3:k + 4])]
                        recent_h1 = [v for v in h1_swings[-6:] if tap3_price * 1.005 <= v <= range_high * 0.96]
                        bos_level = float(recent_h1[-1]) if recent_h1 else float(np.max(high_arr[-4:-1]))
                    else:
                        local_minor_high = float(np.max(high_arr[-5:-1])) if n >= 6 else curr_close * 1.015
                        bos_level = min(local_minor_high, tap3_price + 0.35 * rng_height)
                        bos_level = max(bos_level, tap3_price * 1.012)

                    death_low = tap2_price - 0.30 * (range_high - tap2_price)
                    if death_low <= curr_close <= range_high * 0.98:
                        tct_valid_range = True
                        Model_Tag = "TCT Model 1 (Sweep)" if tap3_price < tap2_price else "TCT Model 2 (Higher Low)"
                        playbook_name = f"📐 {Model_Tag}"
                        swing_type = "TCT_BOTTOM"
                        break
            if tct_valid_range:
                break

    # --- CHECK 4 SWING TRADE STRATEGIES IF NOT IN A TCT BOTTOM BOX ---
    is_ema20_pullback = False
    is_squeeze_coil = False
    is_rsi2_snapback = False
    is_gap_ignition = False

    if not tct_valid_range:
        # Swing 1: 🎯 20-EMA "Holy Grail" Pullback Swing
        touched_ema20_recently = (float(np.min(low_arr[-3:])) <= ema20 * 1.018) and (curr_close >= ema20 * 0.988)
        if curr_close > ema50 and ema20 > ema50 and adx_val >= 20.0 and touched_ema20_recently and (curr_close <= high_5d_prev * 0.992):
            is_ema20_pullback = True
            playbook_name = "🎯 20-EMA Pullback Swing"
            swing_type = "EMA20_PULLBACK"

        # Swing 2: ⚡ Volatility Contraction / Bollinger Band Squeeze
        if not is_ema20_pullback and curr_close > ema50 and ((curr_bb_width <= min_bb_width_60 * 1.10) or (coil_5d_pct <= 4.8)):
            is_squeeze_coil = True
            playbook_name = "⚡ Volatility Squeeze Swing"
            swing_type = "VOL_SQUEEZE"

        # Swing 3: 🪃 RSI-2 Oversold Snapback (Larry Connors)
        three_red_days = (n >= 4) and (close_arr[-2] < close_arr[-3] < close_arr[-4])
        if not is_ema20_pullback and not is_squeeze_coil and curr_close > ema200 and (rsi2 <= 18.0 or (three_red_days and rsi2 <= 28.0)):
            is_rsi2_snapback = True
            playbook_name = f"🪃 RSI-2 Oversold Bounce (RSI2={rsi2:.0f})"
            swing_type = "RSI2_BOUNCE"

        # Swing 4: 🔥 High-Volume Gap / Catalyst Ignition
        day_chg_pct = ((curr_close - prev_close) / prev_close) * 100.0 if prev_close > 0 else 0.0
        candle_range = max(curr_high - curr_low, 1e-6)
        close_in_top_60 = ((curr_close - curr_low) / candle_range) >= 0.55
        if day_chg_pct >= 3.2 and paced_rvol >= 1.65 and curr_close > ema50 and close_in_top_60:
            is_gap_ignition = True
            playbook_name = f"🔥 High-Vol Ignition ({paced_rvol:.1f}x Vol)"
            swing_type = "GAP_IGNITION"

    # --- CALCULATE EXACT BUY TRIGGER, STOP-LOSS & TAKE PROFIT FOR ACTIVE PLAYBOOK ---
    high20_prev = float(np.max(high_arr[-21:-1])) if n >= 22 else high_5d_prev

    if swing_type == "TCT_BOTTOM" and range_high and bos_level and tap3_price:
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        raw_stop = tap3_price - (0.5 * atr14_1h_est)
        effective_stop = max(min(raw_stop, entry_ref * 0.98), entry_ref * 0.93)
        target_price = range_high

    elif swing_type == "EMA20_PULLBACK":
        # Buy Trigger is breaking above yesterday's high (or current price if already bouncing above it)
        prev_bar_high = float(high_arr[-2]) if n >= 2 else curr_close
        bos_level = prev_bar_high if prev_bar_high <= curr_close * 1.025 else (curr_close * 1.005)
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        pullback_low = float(np.min(low_arr[-4:]))
        raw_stop = min(pullback_low - 0.3 * atr14_daily, ema50 * 0.995)
        effective_stop = max(min(raw_stop, entry_ref * 0.978), entry_ref * 0.94)
        risk_unit = entry_ref - effective_stop
        target_price = max(high20_prev, entry_ref + 2.5 * risk_unit)

    elif swing_type == "VOL_SQUEEZE":
        # Buy Trigger is top of the tight 5-day coil
        bos_level = high_5d_prev
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        raw_stop = low_5d_prev - (0.3 * atr14_daily)
        effective_stop = max(min(raw_stop, entry_ref * 0.978), entry_ref * 0.945)
        risk_unit = entry_ref - effective_stop
        target_price = entry_ref + (3.0 * risk_unit)

    elif swing_type == "RSI2_BOUNCE":
        # Buy Trigger is reclaiming yesterday's close (or current price on green turn)
        bos_level = prev_close if curr_close < prev_close else curr_close
        entry_ref = curr_close
        raw_stop = min(curr_low, float(np.min(low_arr[-3:]))) - (0.8 * atr14_daily)
        effective_stop = max(min(raw_stop, entry_ref * 0.975), entry_ref * 0.94)
        risk_unit = entry_ref - effective_stop
        # Mean reversion target back to 20-day EMA or 2.2R
        target_price = max(ema20, entry_ref + 2.2 * risk_unit)

    elif swing_type == "GAP_IGNITION":
        bos_level = prev_close * 1.032
        entry_ref = curr_close
        raw_stop = max(curr_low - 0.2 * atr14_daily, entry_ref - 1.5 * atr14_daily)
        effective_stop = max(min(raw_stop, entry_ref * 0.975), entry_ref * 0.935)
        risk_unit = entry_ref - effective_stop
        target_price = entry_ref + (2.5 * risk_unit)

    else:
        # Standard Momentum Trend Swing (Fixed 5-day high trigger, never overwritten by curr_close)
        bos_level = high_5d_prev if (high_5d_prev - curr_close) / curr_close <= 0.04 else float(np.max(high_arr[-3:]))
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        atr_stop = entry_ref - (1.5 * atr14_daily)
        ema_stop = min(ema20, entry_ref) - (0.5 * atr14_daily)
        raw_stop = max(atr_stop, ema_stop)
        effective_stop = max(min(raw_stop, entry_ref * 0.978), entry_ref * 0.935)
        risk_unit = entry_ref - effective_stop
        target_price = entry_ref + (2.5 * risk_unit)

    tap3_price = tap3_price if tap3_price else float(np.min(low_arr[-10:]))
    risk_per_share = max(entry_ref - effective_stop, 0.0001)
    reward_per_share = max(target_price - entry_ref, 0.0)
    r_multiple = reward_per_share / risk_per_share

    risk_dollars = account_size * 0.005
    suggested_shares = max(1, int(risk_dollars / risk_per_share))
    position_value = suggested_shares * entry_ref
    target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
    stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0

    # --- DETERMINE PLAIN-ENGLISH ACTION VERDICT ---
    crossed_bos_today = (curr_close >= bos_level) and (prev_close < bos_level * 1.008)

    if swing_type == "TCT_BOTTOM" and curr_close >= bos_level and r_multiple >= 2.0:
        action_signal = "BUY NOW (TCT BOS)"
        action_badge = "badge-tct-buy"
        action_dot = "🟢"
        short_sig = "🟢 TCT Buy"
        action_explain = f"TCT accumulation breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
        action_priority = 0
    elif swing_type == "EMA20_PULLBACK" and (curr_close >= curr_open or curr_close >= prev_close):
        action_signal = "SWING BUY (20-EMA DIP)"
        action_badge = "badge-tct-buy"
        action_dot = "🎯"
        short_sig = "🎯 Pullback"
        action_explain = f"Holy Grail 20-EMA pullback bounce in strong uptrend (ADX {adx_val:.0f}). Target ${target_price:,.2f} ({r_multiple:.1f}R)."
        action_priority = 0
    elif swing_type == "VOL_SQUEEZE" and curr_close >= bos_level * 0.998:
        action_signal = "SWING BUY (SQUEEZE)"
        action_badge = "badge-tct-buy"
        action_dot = "⚡"
        short_sig = "⚡ Squeeze"
        action_explain = f"Breaking out of tight {coil_5d_pct:.1f}% volatility squeeze above ${bos_level:,.2f}. Target ${target_price:,.2f} ({r_multiple:.1f}R)."
        action_priority = 0
    elif swing_type == "RSI2_BOUNCE" and (curr_close >= curr_open or rsi2 <= 12.0):
        action_signal = "SWING BUY (OVERSOLD)"
        action_badge = "badge-tct-buy"
        action_dot = "🪃"
        short_sig = "🪃 Snapback"
        action_explain = f"RSI-2 deeply oversold ({rsi2:.0f}) above 200-EMA. Mean-reversion target ${target_price:,.2f}."
        action_priority = 0
    elif swing_type == "GAP_IGNITION":
        action_signal = "SWING BUY (IGNITION)"
        action_badge = "badge-tct-buy"
        action_dot = "🔥"
        short_sig = "🔥 Ignition"
        action_explain = f"High-volume catalyst surge ({paced_rvol:.1f}x Vol pace). Target ${target_price:,.2f}, stop ${effective_stop:,.2f}."
        action_priority = 0
    elif swing_type == "MOMENTUM" and curr_close > ema50 and curr_close > ema20 and crossed_bos_today and r_multiple >= 2.0:
        action_signal = "BUY NOW (BREAKOUT)"
        action_badge = "badge-tct-buy"
        action_dot = "🟢"
        short_sig = "🟢 Buy Now"
        action_explain = f"Momentum breakout above 5D high (${bos_level:,.2f}) with {r_multiple:.1f}R target at ${target_price:,.2f}."
        action_priority = 0
    elif swing_type == "TCT_BOTTOM" and curr_close < bos_level:
        action_signal = "WATCHING TCT BOX"
        action_badge = "badge-tct-watch"
        action_dot = "📐"
        short_sig = "📐 TCT Box"
        action_explain = f"Valid 25+ bar TCT bottom box. Buy when price closes above BOS ${bos_level:,.2f}."
        action_priority = 1
    elif swing_type == "VOL_SQUEEZE" and curr_close < bos_level:
        action_signal = "COILING (WATCH SQUEEZE)"
        action_badge = "badge-tct-watch"
        action_dot = "⚡"
        short_sig = "⚡ Coiling"
        action_explain = f"Tight {coil_5d_pct:.1f}% volatility squeeze. Buy on breakout above ${bos_level:,.2f}."
        action_priority = 1
    elif curr_close > ema50 and curr_close >= ema20 * 0.99:
        action_signal = "HOLD / RIDE TREND"
        action_badge = "badge-trend"
        action_dot = "🔵"
        short_sig = "🔵 Uptrend"
        action_explain = f"Holding above 20 & 50 EMA. Swing target ${target_price:,.2f}, trailing stop ${effective_stop:,.2f}."
        action_priority = 2
    elif curr_close < ema50 and not tct_valid_range and not is_rsi2_snapback:
        action_signal = "SELL / AVOID"
        action_badge = "badge-tct-sell"
        action_dot = "🔴"
        short_sig = "🔴 Below 50"
        action_explain = f"Below 50-day EMA (${ema50:,.2f}) without an active bottoming or snapback setup."
        action_priority = 4
    else:
        action_signal = "WAIT FOR TRIGGER"
        action_badge = "badge-candidate"
        action_dot = "🟡"
        short_sig = "🟡 Wait"
        action_explain = f"Consolidating. Wait for a move above ${bos_level:,.2f} before entering."
        action_priority = 3

    return {
        "TCT_Valid_Range": tct_valid_range,
        "Swing_Type": swing_type,
        "Is_EMA20_Pullback": is_ema20_pullback,
        "Is_Squeeze_Coil": is_squeeze_coil,
        "Is_RSI2_Snapback": is_rsi2_snapback,
        "Is_Gap_Ignition": is_gap_ignition,
        "RSI2": rsi2,
        "ADX": adx_val,
        "Paced_RVOL": paced_rvol,
        "TCT_Model": playbook_name,
        "TCT_Slow_25": slow_decline_25 and no_vertical_flush,
        "TCT_Liq_50M": liq_pass,
        "TCT_2R_Pass": bool(r_multiple >= 2.0),
        "TCT_Action": action_signal,
        "TCT_Badge": action_badge,
        "TCT_Dot": action_dot,
        "TCT_Short_Sig": short_sig,
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
        "Dollar_Vol_M": dollar_vol_20 / 1e6,
        "RS_Diff": rs_diff,
        "RS_Leader": rs_leader
    }


# --- DATA ENGINE 1: BATCH INGESTION (WITH 8:00 AM HKT SETTLEMENT PATCH) ---
@st.cache_data(ttl=120)
def fetch_batch_market_data(tickers, account_size=100000, refresh_bucket=0):
    if not tickers:
        return {}
    results = {}
    download_list = list(dict.fromkeys(list(tickers) + ["^GSPC"]))
    try:
        data = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False)
    except Exception:
        return {}

    expected_us_date, vol_pace = get_expected_us_session_date_and_pace()

    # Check if Yahoo's 1d endpoint dropped the latest US trading day (8:00 AM HKT settlement glitch)
    data_1h_patch = None
    try:
        sample_df = data["^GSPC"].dropna(subset=["Close"]) if len(download_list) > 1 and "^GSPC" in data.columns.levels[0] else data.dropna(subset=["Close"])
        if not sample_df.empty:
            last_daily_dt = pd.to_datetime(sample_df.index[-1]).date()
            if last_daily_dt < expected_us_date:
                data_1h_patch = yf.download(download_list, period="5d", interval="1h", group_by="ticker", progress=False)
    except Exception:
        pass

    spy_ret_63d = 0.0
    try:
        spy_df = data["^GSPC"].dropna(subset=["Close"]) if len(download_list) > 1 and "^GSPC" in data.columns.levels[0] else pd.DataFrame()
        if data_1h_patch is not None and "^GSPC" in data_1h_patch.columns.levels[0]:
            spy_df = patch_df_with_1h_session(spy_df, data_1h_patch["^GSPC"])
        if len(spy_df) >= 64:
            spy_ret_63d = ((float(spy_df["Close"].iloc[-1]) - float(spy_df["Close"].iloc[-64])) / float(spy_df["Close"].iloc[-64])) * 100.0
    except Exception:
        pass

    w_fund = settings["w_fund"] / 100.0
    w_tech = settings["w_tech"] / 100.0
    w_mom = settings["w_mom"] / 100.0

    for t in tickers:
        try:
            if len(download_list) == 1:
                df = data.copy()
            else:
                if t in data.columns.levels[0]:
                    df = data[t].copy()
                else:
                    continue

            df.dropna(subset=["Close", "High", "Low"], inplace=True)
            if data_1h_patch is not None:
                sub_1h = data_1h_patch[t] if len(download_list) > 1 and t in data_1h_patch.columns.levels[0] else data_1h_patch
                df = patch_df_with_1h_session(df, sub_1h)

            if len(df) < 30:
                continue

            close = float(df["Close"].iloc[-1])
            prev_close = float(df["Close"].iloc[-2])
            day_high = float(df["High"].iloc[-1])
            day_low = float(df["Low"].iloc[-1])
            change = close - prev_close
            change_pct = (change / prev_close) * 100 if prev_close != 0 else 0.0

            df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
            df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
            df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
            df["High20"] = df["High"].rolling(20).max()
            df["High52"] = df["High"].rolling(252, min_periods=30).max()
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
            macd_above_zero = float(df["MACD"].iloc[-1]) > 0
            macd_cross = float(df["MACD"].iloc[-1]) > float(df["MACD_Signal"].iloc[-1])

            vol20 = float(df["Vol20"].iloc[-2]) if len(df) >= 22 and not np.isnan(df["Vol20"].iloc[-2]) else float(df["Vol20"].iloc[-1])
            paced_vol = float(df["Volume"].iloc[-1]) / max(vol_pace, 0.08)
            rvol = float(paced_vol / vol20) if vol20 > 0 else 1.0
            high20_prev = float(df["High20"].iloc[-2]) if len(df) >= 22 else close
            is_breakout = (close >= high20_prev) and (rvol >= 1.3)
            bb_upper_break = close >= float(df["BB_Upper"].iloc[-1])
            bb_lower_touch = float(df["Low"].iloc[-1]) <= float(df["BB_Lower"].iloc[-1])
            ema20_val = float(df["EMA20"].iloc[-1])
            ema50_val = float(df["EMA50"].iloc[-1])
            pullback_ema = (abs(close - ema20_val) / ema20_val <= 0.025) or (abs(close - ema50_val) / ema50_val <= 0.025)
            above_ema50 = close > ema50_val
            above_ema200 = close > float(df["EMA200"].iloc[-1]) if len(df) >= 200 else True
            within_52w = (close / float(df["High52"].iloc[-1])) >= 0.90 if float(df["High52"].iloc[-1]) > 0 else False

            if is_breakout and above_ema50:
                state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Cleared 20D high (${high20_prev:,.2f}) on {rvol:.1f}x volume pace"
            elif above_ema50 and close > ema20_val:
                state, badge_class, reason = "Active Trend", "badge-trend", "Holding steadily above 20-day & 50-day EMA support"
            elif close < ema50_val:
                state, badge_class, reason = "Support Break", "badge-caution", "Violated 50-day EMA support level"
            else:
                state, badge_class, reason = "Entry Candidate", "badge-candidate", "Consolidating below resistance; setup developing"

            tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 10) + (30 if rvol >= 1.2 else 10)
            mom_score = (50 if is_breakout else 15) + (50 if within_52w else 20)
            fund_score = 80
            composite = int((fund_score * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))

            tct_info = analyze_multi_playbook(df, account_size=account_size, spy_ret_63d=spy_ret_63d, vol_pace=vol_pace)

            record = {
                "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
                "Day_High": day_high, "Day_Low": day_low,
                "RSI": rsi, "RVOL": rvol, "MACD_Above_Zero": macd_above_zero,
                "MACD_Cross": macd_cross, "Above_EMA50": above_ema50, "Above_EMA200": above_ema200,
                "Is_Breakout": is_breakout, "BB_Upper_Break": bb_upper_break,
                "BB_Lower_Touch": bb_lower_touch, "Pullback_EMA50": pullback_ema,
                "Within_52W": within_52w, "State": state, "Badge": badge_class,
                "Reason": reason, "Score": composite,
                "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
            }
            record.update(tct_info)
            results[t] = record
        except Exception:
            continue
    return results


# --- DATA ENGINE 2: ISOLATED SINGLE-TICKER ENGINE (WITH 8:00 AM HKT PATCH) ---
@st.cache_data(ttl=180)
def fetch_single_ticker_data(sym, account_size=100000):
    try:
        t = yf.Ticker(sym)
        df = t.history(period="1y", interval="1d")
        if df.empty or len(df) < 20:
            return None
        try:
            df_1h = t.history(period="1mo", interval="1h")
        except Exception:
            df_1h = None

        df = patch_df_with_1h_session(df, df_1h)
        _, vol_pace = get_expected_us_session_date_and_pace()

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

        vol20 = float(df["Vol20"].iloc[-2]) if len(df) >= 22 and float(df["Vol20"].iloc[-2]) > 0 else 1.0
        rvol = (float(df["Volume"].iloc[-1]) / max(vol_pace, 0.08)) / vol20
        high20_prev = float(df["High"].rolling(20).max().iloc[-2]) if len(df) >= 22 else close
        is_breakout = (close >= high20_prev) and (rvol >= 1.3)
        above_ema50 = close > float(df["EMA50"].iloc[-1])

        if is_breakout and above_ema50:
            state, badge_class = "Confirmed Breakout", "badge-breakout"
            reason = f"Cleared 20D high (${high20_prev:,.2f}) on {rvol:.1f}x volume pace"
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

        tct_info = analyze_multi_playbook(df, account_size=account_size, df_1h=df_1h, vol_pace=vol_pace)

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


# --- YAHOO-STYLE EDIT / REORDER / MULTI-WATCHLIST HELPER ---
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
            if ok:
                st.success(msg)
            else:
                st.warning(msg)

    syms = watchlists.get(folder_name, [])
    if not syms:
        st.info("This watchlist is currently empty. Add a stock symbol above!")
    else:
        e_col1, e_col2 = st.columns(2)
        half = (len(syms) + 1) // 2
        for i, s in enumerate(syms):
            target_col = e_col1 if i < half else e_col2
            with target_col:
                r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
                r1.markdown(f"**{i+1}. {s}**")
                if r2.button("⏫", key=f"{key_prefix}_top_{folder_name}_{s}_{i}", help="Move to #1 Top", disabled=(i == 0)):
                    syms.pop(i)
                    syms.insert(0, s)
                    save_json(DATA_FILE, watchlists)
                    st.rerun()
                if r3.button("⬆️", key=f"{key_prefix}_up_{folder_name}_{s}_{i}", help="Move Up 1 Spot", disabled=(i == 0)):
                    syms[i - 1], syms[i] = syms[i], syms[i - 1]
                    save_json(DATA_FILE, watchlists)
                    st.rerun()
                if r4.button("⬇️", key=f"{key_prefix}_dn_{folder_name}_{s}_{i}", help="Move Down 1 Spot", disabled=(i == len(syms) - 1)):
                    syms[i + 1], syms[i] = syms[i], syms[i + 1]
                    save_json(DATA_FILE, watchlists)
                    st.rerun()
                if r5.button("🗑️", key=f"{key_prefix}_del_{folder_name}_{s}_{i}", help=f"Remove {s}"):
                    syms.pop(i)
                    sync_watchlists_to_github(watchlists)
                    st.rerun()
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
        "label": "🟢 MARKET REGIME: BULLISH — S&P 500 Holding Trend · Favorable for Swing & TCT Setups",
        "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
    }
    try:
        df = yf.download(ticks, period="3mo", interval="1d", group_by="ticker", progress=False)
        for name, sym in MACRO_SYMBOLS.items():
            sub = df[sym].dropna(subset=["Close"]) if len(ticks) > 1 and sym in df.columns.levels[0] else pd.DataFrame()
            if len(sub) >= 2:
                c = float(sub["Close"].iloc[-1])
                pc = float(sub["Close"].iloc[-2])
                chg = c - pc
                pct = (chg / pc) * 100 if pc != 0 else 0.0
                out[name] = (c, chg, pct)

        if "^GSPC" in df.columns.levels[0]:
            sp = df["^GSPC"].dropna(subset=["Close"])
            if len(sp) >= 50:
                sp_c = float(sp["Close"].iloc[-1])
                sp_ema20 = float(sp["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
                sp_ema50 = float(sp["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
                vix_c = out.get("VIX", (18.0, 0, 0))[0]
                if sp_c > sp_ema50 and sp_c > sp_ema20 and vix_c < 21.0:
                    regime = {
                        "label": f"🟢 MARKET REGIME: BULLISH (S&P 500 Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for Swing, TCT & Momentum Buys",
                        "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
                    }
                elif sp_c < sp_ema50 or vix_c >= 25.0:
                    regime = {
                        "label": f"🔴 MARKET REGIME: RISK-OFF / CORRECTION (S&P Below 50 EMA or VIX Elevated at {vix_c:.1f}) — Protect Capital, Favor Oversold Bounce or Cash",
                        "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"
                    }
                else:
                    regime = {
                        "label": f"🟡 MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating · VIX {vix_c:.1f}) — Favor 20-EMA Pullbacks & Tight Volatility Squeezes",
                        "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"
                    }
    except Exception:
        pass
    return out, regime


# ==============================================================================
# 1. PRIMARY SIDEBAR NAVIGATION
# ==============================================================================
st.sidebar.markdown(
    """<div style="padding: 10px 0 20px 0;"><span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span><span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">6-PLAYBOOK ENGINE</span><h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2><span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Swing · TCT · Momentum v11.0</span></div>""", 
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
    key="nav_radio",
    label_visibility="collapsed",
    on_change=clear_inspection
)

st.sidebar.markdown("---")
gh_token_present = bool(get_github_token())
sync_badge = "🟢 GitHub Auto-Sync Active" if gh_token_present else "🟡 Local Mode (Add GITHUB_TOKEN)"
st.sidebar.markdown(
    f"""<div style="position: fixed; bottom: 18px; font-size: 0.74rem; color: #a1a1aa;">{sync_badge}<br>Tap any <b>Stock Symbol</b> to open chart</div>""", 
    unsafe_allow_html=True
)


# ==============================================================================
# 2. MACRO BANNER & MARKET REGIME (HIDDEN ON FULL-SCREEN LIVE QUOTES PAGE)
# ==============================================================================
if navigation != "⚡ Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
    macro_data, regime_info = fetch_macro_and_regime()
    if macro_data:
        cards_html = ""
        for name, (price, chg, pct) in macro_data.items():
            tick_class = "tick-pos" if chg >= 0 else "tick-neg"
            tick_sign = "+" if chg >= 0 else ""
            cards_html += f'<div class="macro-card"><div class="macro-title">{name}</div><div class="macro-price">{price:,.2f}</div><div class="{tick_class}">{tick_sign}{chg:.2f} ({tick_sign}{pct:.2f}%)</div></div>'
        st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)

    st.markdown(
        f'<div style="background:{regime_info["bg"]}; border:1px solid {regime_info["border"]}; color:{regime_info["color"]}; padding:8px 14px; border-radius:8px; font-size:0.82rem; font-weight:600; margin-bottom:16px;">{regime_info["label"]}</div>',
        unsafe_allow_html=True
    )


# ==============================================================================
# 3. CONTENT ROUTING
# ==============================================================================
if st.session_state.inspect_symbol is not None:
    sym = st.session_state.inspect_symbol
    col_back, col_title = st.columns([1.2, 8.8])
    with col_back:
        if st.button("⬅ Back", type="primary"):
            clear_inspection()
            st.rerun()

    with col_title:
        st.markdown(f"<h1>{sym} · Swing, TCT & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        raw_mcap = funds.get('Market Cap')
        mcap_text = f"${raw_mcap/1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"
        
        f1.metric("Price", f"${d['Price']:,.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Action Signal", d["TCT_Action"])
        f3.metric("Buy Trigger", f"${d['BOS_Level']:,.2f}")
        f4.metric("Take Profit Target", f"${d['Target_Price']:,.2f}", f"+{d['Target_Pct']:.1f}%")
        f5.metric("Safety Stop-Loss", f"${d['Stop_Price']:,.2f}", f"{d['Stop_Pct']:.1f}%", delta_color="inverse")
        f6.metric("0.5% Risk Size", f"{d['Shares_05Pct']} shs", f"{d['R_Multiple']:.1f}R Reward/Risk")

        st.markdown("---")

        c_ctrl, c_plot = st.columns([1.15, 3.85])
        with c_ctrl:
            st.markdown("### Chart Overlays")
            show_tct_lines = st.checkbox("Target / Buy / Stop Lines", value=True)
            show_ema20 = st.checkbox("EMA 20 (Gold)", value=True)
            show_ema50 = st.checkbox("EMA 50 (Green)", value=True)
            show_ema200 = st.checkbox("EMA 200 (Purple)", value=False)
            show_bb = st.checkbox("Bollinger Bands (20, 2)", value=False)

            st.markdown("---")
            st.markdown("### 6-Playbook Trade Ticket")
            st.markdown(f"**Active Playbook:** `{d['TCT_Model']}`")
            st.markdown(f"**Action:** `{d['TCT_Action']}`")
            st.markdown(f"**Buy Trigger:** `${d['BOS_Level']:,.2f}`")
            st.markdown(f"**Profit Target:** `${d['Target_Price']:,.2f}` (+{d['Target_Pct']:.1f}%)")
            st.markdown(f"**Stop-Loss:** `${d['Stop_Price']:,.2f}` ({d['Stop_Pct']:.1f}%)")
            st.markdown(f"**Reward/Risk:** `{d['R_Multiple']:.2f}R` ({'Pass ≥2R' if d['TCT_2R_Pass'] else 'Below 2R'})")
            st.markdown(f"**Suggested Shares:** `{d['Shares_05Pct']} shares` (${d['Pos_Value']:,.0f})")
            st.markdown(f"**RSI(14) / RSI(2):** `{d['RSI']:.1f}` / `{d['RSI2']:.0f}` | **ADX:** `{d['ADX']:.0f}`")
            st.markdown(f"*{d['TCT_Explain']}*")

            st.markdown("---")
            st.markdown("### Momentum & Valuation")
            st.markdown(f"**Momentum State:** `{d['State']}` ({d['Score']}/100)")
            st.markdown(f"**Market Cap:** `{mcap_text}` | **P/E:** `{funds.get('Trailing P/E', 'N/A')}`")

        with c_plot:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.62, 0.19, 0.19])
            fig.add_trace(go.Candlestick(x=df_hist.index, open=df_hist['Open'], high=df_hist['High'], low=df_hist['Low'], close=df_hist['Close'], name="Candles"), row=1, col=1)

            if show_ema20
