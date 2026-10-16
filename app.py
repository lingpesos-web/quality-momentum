import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import base64
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

# Handle clickable links (?inspect=SYM or ?rt_chart=SYM) and immediately clean URL
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
            ascii_title = "Momentum and TCT Alert"
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

# --- CUSTOM CSS: MANUS EDITORIAL THEME + ULTRA-COMPACT 2-COLUMN LIVE BOARD ---
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

/* ULTRA-COMPACT 2-COLUMN LIVE WATCHBOARD TABLE */
.live-board-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    width: 100%;
    margin-top: 4px;
}
@media (max-width: 768px) {
    .live-board-grid {
        grid-template-columns: 1fr;
    }
}
.live-quote-table {
    width: 100%;
    border-collapse: collapse;
    background: #ffffff;
    border: 1px solid #dcd6cb;
    border-radius: 6px;
    overflow: hidden;
    font-size: 0.78rem;
}
.live-quote-table thead th {
    background: #0f291e;
    color: #f4efe6;
    font-weight: 600;
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    padding: 5px 7px;
    text-align: right;
}
.live-quote-table thead th:nth-child(1),
.live-quote-table thead th:nth-child(2) {
    text-align: left;
}
.live-quote-table tbody tr {
    border-bottom: 1px solid #efebe4;
    line-height: 1.15;
}
.live-quote-table tbody tr:nth-child(even) {
    background-color: #faf8f5;
}
.live-quote-table tbody tr:hover {
    background-color: #f0fdf4;
}
.live-quote-table td {
    padding: 4px 7px;
    text-align: right;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}
.live-quote-table td:nth-child(1) {
    text-align: left;
    color: #71717a;
    font-size: 0.68rem;
    width: 22px;
    padding-right: 2px;
}
.live-quote-table td:nth-child(2) {
    text-align: left;
    font-weight: 700;
}
.rt-sym-link {
    color: #0f291e !important;
    text-decoration: none !important;
    font-weight: 700;
    font-size: 0.82rem;
    border-bottom: 1px dashed #c5a059;
}
.rt-sym-link:hover {
    color: #15803d !important;
    background: #dcfce7;
    padding: 1px 4px;
    border-radius: 3px;
}
.rt-dossier-link {
    text-decoration: none !important;
    font-size: 0.70rem;
    margin-left: 4px;
    opacity: 0.65;
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

# Ensure all 3 core watchlists always exist
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


# --- DUAL-PLAYBOOK ENGINE: TRUE TCT ACCUMULATION vs. MOMENTUM TREND SWING ---
def analyze_dual_playbook(df, account_size=100000, spy_ret_63d=0.0, df_1h=None):
    n = len(df)
    close_arr = df["Close"].values.astype(float)
    high_arr = df["High"].values.astype(float)
    low_arr = df["Low"].values.astype(float)
    vol_arr = df["Volume"].values.astype(float)
    curr_close = float(close_arr[-1])
    prev_close = float(close_arr[-2]) if n >= 2 else curr_close

    lookback_rs = min(63, n - 1)
    stock_ret_63d = ((curr_close - float(close_arr[-1 - lookback_rs])) / float(close_arr[-1 - lookback_rs])) * 100.0 if lookback_rs > 5 else 0.0
    rs_diff = stock_ret_63d - spy_ret_63d
    rs_leader = bool(rs_diff >= 2.0)

    dollar_vol_20 = pd.Series(close_arr[-20:] * vol_arr[-20:]).median() if n >= 20 else 0.0
    liq_pass = bool(dollar_vol_20 >= 50_000_000)

    tr1 = df["High"] - df["Low"]
    tr2 = (df["High"] - df["Close"].shift(1)).abs()
    tr3 = (df["Low"] - df["Close"].shift(1)).abs()
    atr14_daily = float(pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
    if np.isnan(atr14_daily) or atr14_daily <= 0:
        atr14_daily = curr_close * 0.025
    atr14_1h_est = atr14_daily / 2.55

    ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
    ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])

    swing_highs = []
    swing_lows = []
    for i in range(3, n - 3):
        if high_arr[i] == np.max(high_arr[i - 3:i + 4]):
            swing_highs.append((i, float(high_arr[i])))
        if low_arr[i] == np.min(low_arr[i - 3:i + 4]):
            swing_lows.append((i, float(low_arr[i])))

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
                    bars_decline = t2_idx - peak_idx
                    if bars_decline < 25:
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
                        break
            if tct_valid_range:
                break

    if tct_valid_range and range_high and bos_level and tap3_price:
        entry_ref = curr_close if curr_close >= bos_level else bos_level
        raw_stop = tap3_price - (0.5 * atr14_1h_est)
        min_stop = entry_ref * 0.98
        max_stop = entry_ref * 0.93
        effective_stop = min(raw_stop, min_stop)
        effective_stop = max(effective_stop, max_stop)
        target_price = range_high
    else:
        high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_close
        if curr_close >= high_5d_prev:
            bos_level = curr_close
        elif (high_5d_prev - curr_close) / curr_close <= 0.035:
            bos_level = high_5d_prev
        else:
            bos_level = float(np.max(high_arr[-3:]))

        entry_ref = curr_close if curr_close >= bos_level else bos_level
        atr_stop = entry_ref - (1.5 * atr14_daily)
        ema_stop = min(ema20, entry_ref) - (0.5 * atr14_daily)
        raw_stop = max(atr_stop, ema_stop)
        effective_stop = min(raw_stop, entry_ref * 0.978)
        effective_stop = max(effective_stop, entry_ref * 0.935)

        risk_unit = entry_ref - effective_stop
        target_price = entry_ref + (2.5 * risk_unit)
        tap3_price = float(np.min(low_arr[-10:]))

    risk_per_share = max(entry_ref - effective_stop, 0.0001)
    reward_per_share = max(target_price - entry_ref, 0.0)
    r_multiple = reward_per_share / risk_per_share

    risk_dollars = account_size * 0.005
    suggested_shares = max(1, int(risk_dollars / risk_per_share))
    position_value = suggested_shares * entry_ref
    target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
    stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0

    just_crossed_bos = (curr_close >= bos_level) and (prev_close < bos_level * 1.012)

    if tct_valid_range and curr_close >= bos_level and r_multiple >= 2.0:
        action_signal = "BUY NOW (TCT BOS)"
        action_badge = "badge-tct-buy"
        action_dot = "🟢"
        action_explain = f"TCT accumulation breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
        action_priority = 0
    elif tct_valid_range and curr_close < bos_level:
        action_signal = "WATCHING TCT BOX"
        action_badge = "badge-tct-watch"
        action_dot = "📐"
        action_explain = f"Valid 25+ bar TCT bottom box formed. Buy if price closes above BOS ${bos_level:,.2f}."
        action_priority = 1
    elif not tct_valid_range and curr_close > ema50 and curr_close > ema20 and just_crossed_bos and r_multiple >= 2.0:
        action_signal = "BUY NOW (MOMENTUM)"
        action_badge = "badge-tct-buy"
        action_dot = "🟢"
        action_explain = f"Uptrend breakout above ${bos_level:,.2f} with {r_multiple:.1f}R swing target at ${target_price:,.2f}."
        action_priority = 0
    elif curr_close > ema50 and curr_close >= ema20 * 0.99:
        action_signal = "HOLD / BUY DIP"
        action_badge = "badge-trend"
        action_dot = "🔵"
        action_explain = f"Strong uptrend above 20 & 50 EMA. Swing target ${target_price:,.2f}, trailing stop ${effective_stop:,.2f}."
        action_priority = 2
    elif curr_close < ema50 and not tct_valid_range:
        action_signal = "SELL / AVOID"
        action_badge = "badge-tct-sell"
        action_dot = "🔴"
        action_explain = f"Below 50-day EMA (${ema50:,.2f}) without a valid TCT bottom box. Protect capital."
        action_priority = 4
    else:
        action_signal = "WAIT FOR TRIGGER"
        action_badge = "badge-candidate"
        action_dot = "🟡"
        action_explain = f"Consolidating. Wait for a clean move above ${bos_level:,.2f} before entering."
        action_priority = 3

    return {
        "TCT_Valid_Range": tct_valid_range,
        "TCT_Model": playbook_name,
        "TCT_Slow_25": slow_decline_25 and no_vertical_flush,
        "TCT_Liq_50M": liq_pass,
        "TCT_2R_Pass": bool(r_multiple >= 2.0),
        "TCT_Action": action_signal,
        "TCT_Badge": action_badge,
        "TCT_Dot": action_dot,
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


# --- DATA ENGINE 1: BATCH INGESTION (INCLUDES DAY HIGH & DAY LOW) ---
@st.cache_data(ttl=120)
def fetch_batch_market_data(tickers, account_size=100000):
    if not tickers:
        return {}
    results = {}
    download_list = list(dict.fromkeys(list(tickers) + ["^GSPC"]))
    try:
        data = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False)
    except Exception:
        return {}

    spy_ret_63d = 0.0
    try:
        spy_df = data["^GSPC"].dropna() if len(download_list) > 1 and "^GSPC" in data.columns.levels[0] else pd.DataFrame()
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

            vol20 = float(df["Vol20"].iloc[-1]) if not np.isnan(df["Vol20"].iloc[-1]) else 0.0
            rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
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
                state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Closed above 20D high (${high20_prev:,.2f}) with {rvol:.1f}x volume"
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

            tct_info = analyze_dual_playbook(df, account_size=account_size, spy_ret_63d=spy_ret_63d)

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


# --- DATA ENGINE 2: ISOLATED SINGLE-TICKER ENGINE ---
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
        is_breakout = (close >= high20_prev) and (rvol >= 1.3)
        above_ema50 = close > float(df["EMA50"].iloc[-1])

        if is_breakout and above_ema50:
            state, badge_class = "Confirmed Breakout", "badge-breakout"
            reason = f"Closed above 20D high (${high20_prev:,.2f}) with {rvol:.1f}x volume"
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

        tct_info = analyze_dual_playbook(df, account_size=account_size, df_1h=df_1h)

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
    """Renders Yahoo Finance-style Up / Down / Top reorder controls + Create/Delete Watchlist."""
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
        # Render in 2 side-by-side columns so editing is also compact
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
        "label": "🟢 MARKET REGIME: BULLISH — S&P 500 Holding Trend · Favorable for New Setups",
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
                        "label": f"🟢 MARKET REGIME: BULLISH (S&P 500 Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for TCT & Momentum Buys",
                        "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
                    }
                elif sp_c < sp_ema50 or vix_c >= 25.0:
                    regime = {
                        "label": f"🔴 MARKET REGIME: RISK-OFF / CORRECTION (S&P Below 50 EMA or VIX Elevated at {vix_c:.1f}) — Protect Capital, Avoid Aggressive New Buys",
                        "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"
                    }
                else:
                    regime = {
                        "label": f"🟡 MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating · VIX {vix_c:.1f}) — Be Selective, Demand Strict ≥2.5R Setups",
                        "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"
                    }
    except Exception:
        pass
    return out, regime


# ==============================================================================
# 1. PRIMARY SIDEBAR NAVIGATION
# ==============================================================================
st.sidebar.markdown(
    """<div style="padding: 10px 0 20px 0;"><span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span><span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">LIVE + 15M RESEARCH</span><h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2><span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Momentum & TCT v10.0</span></div>""", 
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
        st.markdown(f"<h1>{sym} · Technical, TCT & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        raw_mcap = funds.get('Market Cap')
        mcap_text = f"${raw_mcap/1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"
        
        f1.metric("Price", f"${d['Price']:,.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Action Signal", d["TCT_Action"])
        f3.metric("Buy Trigger (BOS)", f"${d['BOS_Level']:,.2f}")
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
            st.markdown("### Action Trade Ticket")
            st.markdown(f"**Playbook:** `{d['TCT_Model']}`")
            st.markdown(f"**Action:** `{d['TCT_Action']}`")
            st.markdown(f"**Buy Trigger:** `${d['BOS_Level']:,.2f}`")
            st.markdown(f"**Profit Target:** `${d['Target_Price']:,.2f}` (+{d['Target_Pct']:.1f}%)")
            st.markdown(f"**Stop-Loss:** `${d['Stop_Price']:,.2f}` ({d['Stop_Pct']:.1f}%)")
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
                fig.add_hline(y=d["Target_Price"], line_dash="dash", line_color="#15803d", line_width=1.8, annotation_text=f"TAKE PROFIT TARGET: ${d['Target_Price']:,.2f} (+{d['Target_Pct']:.1f}%)", annotation_position="top left", row=1, col=1)
                fig.add_hline(y=d["BOS_Level"], line_dash="dot", line_color="#2563eb", line_width=1.6, annotation_text=f"BUY TRIGGER: ${d['BOS_Level']:,.2f}", annotation_position="bottom left", row=1, col=1)
                fig.add_hline(y=d["Stop_Price"], line_dash="dash", line_color="#b91c1c", line_width=1.8, annotation_text=f"STOP-LOSS (EXIT): ${d['Stop_Price']:,.2f} ({d['Stop_Pct']:.1f}%)", annotation_position="bottom right", row=1, col=1)

            vol_colors = ['#15803d' if c >= o else '#b91c1c' for c, o in zip(df_hist['Close'], df_hist['Open'])]
            fig.add_trace(go.Bar(x=df_hist.index, y=df_hist['Volume'], marker_color=vol_colors, name="Volume"), row=2, col=1)

            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD'], line=dict(color="#2563eb", width=1.2), name="MACD"), row=3, col=1)
            fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['MACD_Signal'], line=dict(color="#ea580c", width=1.2), name="Signal"), row=3, col=1)
            fig.add_trace(go.Bar(x=df_hist.index, y=df_hist['MACD_Hist'], marker_color="#cbd5e1", name="Histogram"), row=3, col=1)

            fig.update_layout(height=650, margin=dict(l=0, r=0, t=10, b=0), paper_bgcolor="white", plot_bgcolor="white", xaxis_rangeslider_visible=False)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Verified Recent Headlines (Last 72 Hours)")
        sym_news = _fetch_rss_raw(f'"{sym}" stock when:3d', max_per_query=8, ticker_tag=sym, max_age_hours=settings["max_news_age_hours"])
        if sym_news:
            for a in sym_news:
                st.markdown(f'- **[{a["age"]}]** <a href="{a["link"]}" target="_blank" style="color:#0f291e; font-weight:600;">{a["title"]}</a> *({a["publisher"]} · {a["date"]})*', unsafe_allow_html=True)
        else:
            st.caption("No verified headlines in the past 72 hours.")

        st.markdown("### Profile Summary")
        st.write(funds.get("Business Summary", "No business overview provided."))
    else:
        st.error(f"Unable to retrieve historical chart data for {sym}. Please verify the ticker.")

else:
    if navigation == "Dashboard":
        st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Tap any stock symbol to open its interactive chart & Dual-Playbook Trade Ticket.</p>", unsafe_allow_html=True)

        all_monitored = get_all_monitored_tickers()
        stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])

        if stock_records:
            best_pick = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + (15 if x["RS_Leader"] else 0) + x["Score"])
            st.markdown(
                f"""
                <div style="background-color: #0f291e; border-radius: 10px; padding: 20px 24px; color: #fbf9f4; margin-bottom: 20px;">
                    <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.12em; color: #c5a059; font-weight: 700;">
                        TODAY'S STANDOUT SETUP · {best_pick['TCT_Action']} · {best_pick['TCT_Model']}
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                        <div>
                            <a href="?inspect={best_pick['Ticker']}" target="_self" class="hero-ticker-link">📊 {best_pick['Ticker']}</a>
                            <span style="font-size: 1.2rem; color: #e2e8f0; margin-left: 10px;">${best_pick['Price']:,.2f}</span>
                            <span style="color: {'#4ade80' if best_pick['Change'] >= 0 else '#f87171'}; font-weight: 600; margin-left: 6px;">
                                {'+' if best_pick['Change'] >= 0 else ''}{best_pick['Change_Pct']:.2f}%
                            </span>
                            <div style="color: #cbd5e1; font-size: 0.90rem; margin-top: 6px;">
                                <b>Buy Trigger:</b> ${best_pick['BOS_Level']:,.2f} · <b>Take Profit:</b> ${best_pick['Target_Price']:,.2f} (+{best_pick['Target_Pct']:.1f}%) · <b>Stop-Loss:</b> ${best_pick['Stop_Price']:,.2f} ({best_pick['Stop_Pct']:.1f}%) · <b>Size (0.5% Risk):</b> {best_pick['Shares_05Pct']} shs ({best_pick['R_Multiple']:.1f}R)
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

        col_left, col_right = st.columns([2, 1])
        with col_left:
            tab_watch, tab_macro, tab_mcf = st.tabs([
                f"Watchlist News ({len(all_monitored)} Tickers)",
                "General Market",
                "Metals, Crypto & USD"
            ])
            
            with tab_watch:
                wl_news = fetch_watchlist_news_pool(all_monitored, max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if wl_news:
                    st.caption(f"Verified fresh headlines (last {settings['max_news_age_hours']}h only · re-hash blogs blocked). Showing {len(wl_news)} stories.")
                    news_html = '<div class="scroll-news-box">'
                    for a in wl_news:
                        ticker_name = a.get("ticker", "NEWS")
                        news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;"><span class="ticker-news-badge">[{ticker_name}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                    news_html += '</div>'
                    st.markdown(news_html, unsafe_allow_html=True)
                else:
                    st.info("No verified fresh news in the past 72 hours for your tracked stocks.")

            with tab_macro:
                market_news = fetch_google_news_rss("US stock market news", max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if market_news:
                    st.caption(f"Verified fresh market stories (last {settings['max_news_age_hours']}h only). Showing {len(market_news)} stories.")
                    m_news_html = '<div class="scroll-news-box">'
                    for n in market_news:
                        m_news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;">{n["publisher"]}<span class="age-badge">{n["age"]}</span></span><span>{n["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 3px;"><a href="{n["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{n["title"]}</a></div></div>'
                    m_news_html += '</div>'
                    st.markdown(m_news_html, unsafe_allow_html=True)
                else:
                    st.info("Market headlines feed refreshing.")

            with tab_mcf:
                mcf_news = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if mcf_news:
                    st.caption(f"Verified fresh Precious Metals, Crypto & USD stories (last {settings['max_news_age_hours']}h).")
                    c_news_html = '<div class="scroll-news-box">'
                    for a in mcf_news:
                        c_news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;"><span class="ticker-news-badge">[{a["ticker"]}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                    c_news_html += '</div>'
                    st.markdown(c_news_html, unsafe_allow_html=True)

        with col_right:
            st.subheader("Action Signals Snapshot")
            sorted_snap = sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))
            for r in sorted_snap[:9]:
                rs_tag = f'<span class="badge badge-rs-lead" style="margin-left:4px;">🔥 RS +{r["RS_Diff"]:.0f}%</span>' if r["RS_Leader"] else ""
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <a href="?inspect={r['Ticker']}" target="_self" class="ticker-link" style="font-size: 1.05rem;">📊 {r['Ticker']}</a>
                                <span class="badge {r['TCT_Badge']}" style="margin-left: 6px; font-size: 0.62rem;">{r['TCT_Action']}</span>{rs_tag}
                            </div>
                            <div style="text-align: right;">
                                <span style="font-weight: 700; font-size: 0.92rem;">${r['Price']:,.2f}</span>
                            </div>
                        </div>
                        <div style="font-size: 0.74rem; color: #52525b; margin-top: 5px;">
                            Buy: <b>${r['BOS_Level']:,.2f}</b> · Target: <b style="color:#15803d;">${r['Target_Price']:,.2f}</b> (+{r['Target_Pct']:.1f}%) · Stop: <b style="color:#b91c1c;">${r['Stop_Price']:,.2f}</b> ({r['R_Multiple']:.1f}R)
                        </div>
                    </div>
                    """, unsafe_allow_html=True
                )

    elif navigation == "⚡ Live Real-Time Quotes":
        # FULL-SCREEN MODE: Remove top padding so the 2-column live watchboard fills the screen
        st.markdown("""
        <style>
        .block-container {
            padding-top: 1.1rem !important;
            padding-bottom: 1rem !important;
        }
        </style>
        """, unsafe_allow_html=True)

        folder_names = list(watchlists.keys())
        folder_options = folder_names + ["All Watchlists Combined"]

        # Slim Single-Row Control Bar at the very top
        ctrl1, ctrl2, ctrl3, ctrl4, ctrl5 = st.columns([2.1, 2.2, 1.8, 0.9, 1.3])
        with ctrl1:
            selected_live_folder = st.selectbox("Watchlist", folder_options, index=0, label_visibility="collapsed")
        with ctrl2:
            live_sort = st.selectbox(
                "Rank / Sort",
                [
                    "Rank: My Saved Order",
                    "Rank: 🟢 Action Signal (Buy First)",
                    "Rank: 📈 Day % Change (Gainers)",
                    "Rank: 📉 Day % Change (Losers)",
                    "Rank: 🔥 Relative Strength vs S&P",
                    "Rank: 💯 Composite Score"
                ],
                index=0,
                label_visibility="collapsed"
            )
        with ctrl3:
            if selected_live_folder != "All Watchlists Combined":
                quick_add = st.text_input("Quick Add Ticker", placeholder=f"+ Add to {selected_live_folder} (e.g. AVGO)", label_visibility="collapsed").upper().strip()
                if quick_add and quick_add not in watchlists[selected_live_folder]:
                    watchlists[selected_live_folder].append(quick_add)
                    sync_watchlists_to_github(watchlists)
                    st.rerun()
            else:
                st.caption("Viewing All Combined Lists")
        with ctrl4:
            if st.button("🔄 Refresh", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        with ctrl5:
            edit_mode_live = st.checkbox("✏️ Edit / Reorder", value=False)

        if edit_mode_live:
            target_edit_folder = selected_live_folder if selected_live_folder != "All Watchlists Combined" else folder_names[0]
            render_watchlist_reorder_panel(target_edit_folder, key_prefix="live_ed")

        # Determine active symbol list
        if selected_live_folder == "All Watchlists Combined":
            active_live_syms = get_all_monitored_tickers()
        else:
            active_live_syms = list(watchlists.get(selected_live_folder, []))

        live_records = fetch_batch_market_data(active_live_syms, account_size=settings["account_size"])

        # Apply Selected Ranking / Sorting
        ordered_syms = [s for s in active_live_syms if s in live_records]
        if live_sort == "Rank: 🟢 Action Signal (Buy First)":
            ordered_syms = sorted(ordered_syms, key=lambda s: (live_records[s]["TCT_Priority"], -live_records[s]["Score"]))
        elif live_sort == "Rank: 📈 Day % Change (Gainers)":
            ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Change_Pct"], reverse=True)
        elif live_sort == "Rank: 📉 Day % Change (Losers)":
            ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Change_Pct"])
        elif live_sort == "Rank: 🔥 Relative Strength vs S&P":
            ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["RS_Diff"], reverse=True)
        elif live_sort == "Rank: 💯 Composite Score":
            ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Score"], reverse=True)

        # Build Ultra-Compact 2-Column HTML Tables (Left Column: Top Half | Right Column: Bottom Half)
        def build_half_table_html(sym_slice, start_rank):
            rows_html = ""
            for idx_offset, sym in enumerate(sym_slice):
                rk = start_rank + idx_offset
                d = live_records[sym]
                chg = d["Change"]
                pct = d["Change_Pct"]
                color = "#15803d" if chg >= 0 else "#b91c1c"
                sign = "+" if chg >= 0 else ""
                dot = d.get("TCT_Dot", "🔵")
                rows_html += (
                    f'<tr>'
                    f'<td>{rk}</td>'
                    f'<td>{dot} <a href="?rt_chart={sym}" target="_self" class="rt-sym-link" title="Tap to open live chart below">{sym}</a>'
                    f'<a href="?inspect={sym}" target="_self" class="rt-dossier-link" title="Open Full TCT Dossier">📋</a></td>'
                    f'<td style="font-weight:700; color:#18181b;">${d["Price"]:,.2f}</td>'
                    f'<td style="color:{color}; font-weight:600;">{sign}${abs(chg):.2f} ({sign}{pct:.2f}%)</td>'
                    f'<td style="color:#15803d;">${d["Day_High"]:,.2f}</td>'
                    f'<td style="color:#b91c1c;">${d["Day_Low"]:,.2f}</td>'
                    f'</tr>'
                )
            return (
                f'<table class="live-quote-table">'
                f'<thead><tr><th>#</th><th>Symbol</th><th>Live Price</th><th>Day Chg ($ / %)</th><th>Day High</th><th>Day Low</th></tr></thead>'
                f'<tbody>{rows_html}</tbody></table>'
            )

        if ordered_syms:
            mid = (len(ordered_syms) + 1) // 2
            left_syms = ordered_syms[:mid]
            right_syms = ordered_syms[mid:]

            left_table_html = build_half_table_html(left_syms, 1)
            right_table_html = build_half_table_html(right_syms, mid + 1) if right_syms else ""

            st.markdown(
                f'<div class="live-board-grid"><div>{left_table_html}</div><div>{right_table_html}</div></div>',
                unsafe_allow_html=True
            )
            st.caption("🟢 Buy Now · 📐 In TCT Box · 🔵 Hold/Uptrend · 🟡 Wait · 🔴 Below 50 EMA  |  **Tap any Stock Symbol** to open its Live Chart below · Tap **📋** for Full TCT Dossier.")
        else:
            st.info("No symbols found in this watchlist. Use the box above or '✏️ Edit / Reorder' to add stocks.")

        # OPTION A: BOTTOM LIVE CHART (ONLY SHOWN WHEN A STOCK SYMBOL IS TAPPED)
        if st.session_state.rt_chart_symbol:
            chart_sym = st.session_state.rt_chart_symbol
            st.markdown("---")
            ch_c1, ch_c2, ch_c3, ch_c4 = st.columns([3.5, 2.0, 2.0, 1.5])
            with ch_c1:
                st.markdown(f"### 📈 Live Streaming Chart: `{chart_sym}`")
            with ch_c2:
                rt_interval = st.selectbox(
                    "Timeframe",
                    ["5", "15", "60", "240", "D"],
                    format_func=lambda x: {"5": "5-Minute", "15": "15-Minute", "60": "1-Hour (BOS)", "240": "4-Hour", "D": "Daily"}[x],
                    index=2,
                    label_visibility="collapsed"
                )
            with ch_c3:
                if st.button(f"📋 Open {chart_sym} Full Dossier", use_container_width=True):
                    st.session_state.inspect_symbol = chart_sym
                    st.rerun()
            with ch_c4:
                if st.button("✖ Close Chart", type="primary", use_container_width=True):
                    st.session_state.rt_chart_symbol = None
                    st.rerun()

            components.html(f"""
            <div class="tradingview-widget-container" style="height:480px;width:100%;">
              <div id="tradingview_rt_chart" style="height:465px;width:100%;"></div>
              <script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
              <script type="text/javascript">
              new TradingView.widget({{
                "autosize": true,
                "symbol": "{chart_sym}",
                "interval": "{rt_interval}",
                "timezone": "America/New_York",
                "theme": "light",
                "style": "1",
                "locale": "en",
                "enable_publishing": false,
                "hide_top_toolbar": false,
                "save_image": false,
                "studies": ["EMA@tv-basicstudies", "RSI@tv-basicstudies"],
                "container_id": "tradingview_rt_chart"
              }});
              </script>
            </div>
            """, height=485)

    elif navigation == "Screener":
        st.markdown("<h1>Find the Next Quality Leader or TCT Setup</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Use the One-Tap Strategy Presets below or build a custom scan across ~220 liquid US stocks.</p>", unsafe_allow_html=True)

        all_watchlist_syms = get_all_monitored_tickers()
        full_market_syms = []
        for s_list in GICS_SECTORS.values():
            full_market_syms.extend(s_list)
        full_market_syms = list(dict.fromkeys(full_market_syms + all_watchlist_syms))

        u_col1, u_col2 = st.columns([2.2, 1.8])
        with u_col1:
            universe_mode = st.radio(
                "1. Choose Scan Universe",
                [
                    f"Expanded Liquid Market (~{len(full_market_syms)} Top US Stocks)",
                    f"My Watchlists Only ({len(all_watchlist_syms)} Stocks — Instant)",
                    "Custom Sector Selection below"
                ],
                horizontal=False
            )
        with u_col2:
            st.markdown("**Quick Universe Stats**")
            st.caption(
                "• **Expanded Market:** Covers S&P 500 & Nasdaq leaders, AI, Semis, Quantum, Space, Nuclear, Crypto/Fintech, Biotech & Industrials.\n"
                "• **Dual-Playbook Engine:** Automatically separates TCT Bottoms from Momentum Trend Swings."
            )

        st.markdown("### 2. One-Tap Strategy Preset Scans")
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)

        def get_target_universe(selected_secs):
            if universe_mode.startswith("My Watchlists"):
                return all_watchlist_syms
            elif universe_mode.startswith("Expanded Liquid"):
                return full_market_syms
            else:
                out = []
                for sc in selected_secs:
                    out.extend(GICS_SECTORS[sc])
                return list(dict.fromkeys(out))

        with st.expander("Optional: Custom Sector & Technical Filter Builder", expanded=False):
            f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])
            with f_col1:
                st.markdown("**GICS & Theme Sectors**")
                selected_sectors = []
                for sec in list(GICS_SECTORS.keys()):
                    if st.checkbox(sec, value=True, key=f"sec_{sec}"):
                        selected_sectors.append(sec)
            with f_col2:
                st.markdown("**Momentum & Relative Strength**")
                s_rs = st.checkbox("🔥 Outperforming S&P 500 (RS Leader)", value=False)
                s1 = st.checkbox("RSI Rising Above 55 (Momentum)", value=False)
                s2 = st.checkbox("MACD Line Above Zero", value=False)
                s3 = st.checkbox("MACD Bullish Crossover", value=False)
                s4 = st.checkbox("20-Day High Breakout (Volume Confirmed)", value=False)
                s7 = st.checkbox("Pullback Near 20D or 50D EMA Support", value=False)
                s8 = st.checkbox("Price Above 200-day EMA", value=False)
            with f_col3:
                st.markdown("**TCT & Risk Filters**")
                tct1 = st.checkbox("🟢 Action = 'BUY NOW' (TCT or Momentum)", value=False)
                tct2 = st.checkbox("📐 True TCT Bottom Accumulation Box Only", value=False)
                tct4 = st.checkbox("Reward-to-Risk ≥ 2.0R to Target", value=False)
                tct5 = st.checkbox("Liquidity (20D Dollar Volume ≥ $50M)", value=False)

            if st.button("Run Custom Filter Scan", type="primary"):
                scan_univ = get_target_universe(selected_sectors)
                with st.spinner(f"Scanning {len(scan_univ)} stocks with custom filters..."):
                    s_data = fetch_batch_market_data(scan_univ, account_size=settings["account_size"])
                    matches = []
                    for t, d in s_data.items():
                        if s_rs and not d["RS_Leader"]: continue
                        if s1 and d["RSI"] < 55: continue
                        if s2 and not d["MACD_Above_Zero"]: continue
                        if s3 and not d["MACD_Cross"]: continue
                        if s4 and not d["Is_Breakout"]: continue
                        if s7 and not d["Pullback_EMA50"]: continue
                        if s8 and not d["Above_EMA200"]: continue
                        if tct1 and d["TCT_Priority"] != 0: continue
                        if tct2 and not d["TCT_Valid_Range"]: continue
                        if tct4 and not d["TCT_2R_Pass"]: continue
                        if tct5 and not d["TCT_Liq_50M"]: continue
                        matches.append(d)
                    st.session_state.screener_matches = sorted(matches, key=lambda x: (x["TCT_Priority"], -x["Score"]))
                    st.session_state.screener_title = f"Custom Filter Scan ({len(matches)} Matches)"

        with p_col1:
            if st.button("🟢 Preset 1: 'BUY NOW' Triggers", use_container_width=True, type="primary"):
                scan_univ = get_target_universe(list(GICS_SECTORS.keys()))
                with st.spinner(f"Scanning {len(scan_univ)} stocks for immediate BUY NOW triggers..."):
                    s_data = fetch_batch_market_data(scan_univ, account_size=settings["account_size"])
                    matches = [d for d in s_data.values() if d["TCT_Priority"] == 0 and d["TCT_2R_Pass"]]
                    st.session_state.screener_matches = sorted(matches, key=lambda x: (-int(x["TCT_Valid_Range"]), -x["Score"]))
                    st.session_state.screener_title = f"🟢 Preset 1: Immediate 'BUY NOW' Triggers ({len(matches)} Found)"

        with p_col2:
            if st.button("🚀 Preset 2: RS Momentum Leaders", use_container_width=True):
                scan_univ = get_target_universe(list(GICS_SECTORS.keys()))
                with st.spinner(f"Scanning {len(scan_univ)} stocks for S&P-beating Momentum Leaders..."):
                    s_data = fetch_batch_market_data(scan_univ, account_size=settings["account_size"])
                    matches = [d for d in s_data.values() if d["RS_Leader"] and d["Above_EMA50"] and (d["Is_Breakout"] or d["Score"] >= 75)]
                    st.session_state.screener_matches = sorted(matches, key=lambda x: (-x["Score"], -x["RS_Diff"]))
                    st.session_state.screener_title = f"🚀 Preset 2: Outperforming Momentum Leaders ({len(matches)} Found)"

        with p_col3:
            if st.button("🎯 Preset 3: Buy the Dip (Uptrend)", use_container_width=True):
                scan_univ = get_target_universe(list(GICS_SECTORS.keys()))
                with st.spinner(f"Scanning {len(scan_univ)} stocks for Uptrend Pullbacks near EMA support..."):
                    s_data = fetch_batch_market_data(scan_univ, account_size=settings["account_size"])
                    matches = [d for d in s_data.values() if d["Above_EMA50"] and d["Above_EMA200"] and d["Pullback_EMA50"] and 40 <= d["RSI"] <= 62]
                    st.session_state.screener_matches = sorted(matches, key=lambda x: (-int(x["RS_Leader"]), -x["Score"]))
                    st.session_state.screener_title = f"🎯 Preset 3: 'Buy the Dip' Near 20D/50D EMA Support ({len(matches)} Found)"

        with p_col4:
            if st.button("📐 Preset 4: True TCT Bottom Boxes", use_container_width=True):
                scan_univ = get_target_universe(list(GICS_SECTORS.keys()))
                with st.spinner(f"Scanning {len(scan_univ)} stocks for 25+ Bar TCT Accumulation Boxes..."):
                    s_data = fetch_batch_market_data(scan_univ, account_size=settings["account_size"])
                    matches = [d for d in s_data.values() if d["TCT_Valid_Range"]]
                    st.session_state.screener_matches = sorted(matches, key=lambda x: (x["TCT_Priority"], -x["R_Multiple"]))
                    st.session_state.screener_title = f"📐 Preset 4: Valid 25+ Bar TCT Bottom Accumulation Boxes ({len(matches)} Found)"

        if st.session_state.screener_matches is not None:
            st.markdown("---")
            c_hdr, c_clr = st.columns([8, 2])
            with c_hdr:
                st.markdown(f"### {st.session_state.screener_title or 'Scan Results'}")
            with c_clr:
                if st.button("Clear Results"):
                    st.session_state.screener_matches = None
                    st.rerun()

            matches = st.session_state.screener_matches
            if not matches:
                st.info("No stocks matched that exact preset right now. Try switching the Scan Universe above to 'Expanded Liquid Market' or try another preset.")
            target_add_folder = st.selectbox("Add selected stocks to folder:", list(watchlists.keys()), index=1, key="sc_target_folder")
            for m in matches:
                c1, c2, c3, c4 = st.columns([3.4, 2.7, 1.8, 1.0])
                rs_badge = f'<span class="badge badge-rs-lead" style="margin-left:6px;">🔥 RS +{m["RS_Diff"]:.1f}%</span>' if m["RS_Leader"] else f'<span class="badge badge-rs-lag" style="margin-left:6px;">RS {m["RS_Diff"]:.1f}%</span>'
                with c1:
                    st.markdown(
                        f"""
                        <div>
                            <a href="?inspect={m['Ticker']}" target="_self" class="ticker-link">📊 {m['Ticker']}</a>
                            <span class="badge {m['TCT_Badge']}" style="margin-left: 8px;">{m['TCT_Action']}</span>{rs_badge}
                        </div>
                        <div style="font-size: 0.85rem; color: #71717a; margin-top: 3px;">${m['Price']:,.2f} · <span style="color: {'#15803d' if m['Change']>=0 else '#b91c1c'}; font-weight: 600;">{'+' if m['Change']>=0 else ''}{m['Change_Pct']:.2f}%</span> · <b>{m['TCT_Model']}</b></div>
                        <div style="font-size: 0.8rem; color: #475569; margin-top: 4px;">{m['TCT_Explain']}</div>
                        """, unsafe_allow_html=True
                    )
                with c2:
                    st.markdown(
                        f"""
                        <div style="font-size: 0.82rem; line-height: 1.5;">
                            <b>Buy Trigger:</b> ${m['BOS_Level']:,.2f}<br>
                            <b>Take Profit:</b> <span style="color:#15803d; font-weight:600;">${m['Target_Price']:,.2f} (+{m['Target_Pct']:.1f}%)</span><br>
                            <b>Stop-Loss:</b> <span style="color:#b91c1c; font-weight:600;">${m['Stop_Price']:,.2f} ({m['Stop_Pct']:.1f}%)</span> · <b>{m['R_Multiple']:.1f}R</b> · <b>{m['Shares_05Pct']} shs</b>
                        </div>
                        """, unsafe_allow_html=True
                    )
                with c3:
                    st.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
                with c4:
                    if st.button("➕ Add", key=f"add_sc_{m['Ticker']}"):
                        if m["Ticker"] not in watchlists[target_add_folder]:
                            watchlists[target_add_folder].append(m["Ticker"])
                            ok, msg = sync_watchlists_to_github(watchlists)
                            st.success("Synced!" if ok else "Added")

    elif navigation == "Watchlist":
        st.markdown("<h1>Watchlists & Dual-Playbook Action Tickets</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Switch between your 3+ watchlists, reorder stocks with Up/Down buttons, or tap any stock symbol to open its chart.</p>", unsafe_allow_html=True)

        folder = st.radio("Select Watchlist Folder", list(watchlists.keys()), horizontal=True)
        symbols = watchlists.get(folder, [])

        col_add, col_sort, col_ed = st.columns([2.6, 2.2, 1.2])
        with col_add:
            c_in, c_btn = st.columns([3, 1])
            new_sym = c_in.text_input("Add symbol to folder", placeholder=f"Add to {folder} (e.g. AVGO)", label_visibility="collapsed").upper().strip()
            if c_btn.button("+ Add") and new_sym:
                if new_sym not in symbols:
                    watchlists[folder].append(new_sym)
                    ok, msg = sync_watchlists_to_github(watchlists)
                    st.toast(msg)
                    st.rerun()

        with col_sort:
            sort_by = st.selectbox(
                "Sort By",
                [
                    "Saved Order (My Custom Sequence)",
                    "Action Signal (Buy Now First)",
                    "Relative Strength vs S&P 500",
                    "Composite Score (High → Low)",
                    "Reward-to-Risk Ratio (High → Low)",
                    "Momentum State",
                    "Day % Change (High → Low)",
                    "Alphabetical (A → Z)"
                ],
                index=0,
                label_visibility="collapsed"
            )

        with col_ed:
            show_reorder = st.checkbox("✏️ Edit / Reorder List", value=False)

        if show_reorder:
            render_watchlist_reorder_panel(folder, key_prefix="wl_ed")

        pills_html = "".join([f'<a href="?inspect={s}" target="_self" class="pill">{i+1}. {s}</a>' for i, s in enumerate(symbols)])
        st.markdown(f"<div style='margin-bottom: 12px;'>{pills_html}</div>", unsafe_allow_html=True)

        st.markdown("---")

        data_dict = fetch_batch_market_data(symbols, account_size=settings["account_size"])
        earnings_map = fetch_upcoming_earnings_map(symbols)

        display_symbols = list(symbols)
        if sort_by == "Action Signal (Buy Now First)":
            display_symbols = sorted(display_symbols, key=lambda s: (data_dict.get(s, {}).get("TCT_Priority", 9), -data_dict.get(s, {}).get("Score", 0)))
        elif sort_by == "Relative Strength vs S&P 500":
            display_symbols = sorted(display_symbols, key=lambda s: data_dict.get(s, {}).get("RS_Diff", -999), reverse=True)
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
                rs_html = f'<span class="badge badge-rs-lead" style="margin-left: 4px;">🔥 Leading S&P ({d["RS_Diff"]:+.1f}%)</span>' if d["RS_Leader"] else f'<span class="badge badge-rs-lag" style="margin-left: 4px;">RS {d["RS_Diff"]:+.1f}%</span>'
                earn_html = ""
                if sym in earnings_map:
                    days_left, dt_s = earnings_map[sym]
                    if days_left <= 7:
                        earn_html = f'<div style="margin-top:6px;"><span class="badge badge-earn-warn">⚠️ EARNINGS IN {days_left}d ({dt_s}) — AVOID NEW BUY</span></div>'

                with target_c:
                    st.markdown(
                        f'<div class="stock-card"><div style="display: flex; justify-content: space-between; align-items: flex-start;"><div><a href="?inspect={d["Ticker"]}" target="_self" class="ticker-link">#{idx+1} · 📊 {d["Ticker"]}</a><span class="badge {d["TCT_Badge"]}" style="margin-left: 8px;">{d["TCT_Action"]}</span><span class="badge {d["Badge"]}" style="margin-left: 4px;">{d["State"]}</span>{rs_html}{earn_html}<div style="font-size: 1.35rem; font-weight: 700; margin-top: 6px;">${d["Price"]:,.2f} <span style="font-size: 0.9rem; color: {"#15803d" if d["Change"]>=0 else "#b91c1c"}; font-weight: 600;">{"+" if d["Change"]>=0 else ""}{d["Change_Pct"]:.2f}%</span></div></div><div style="text-align: right;"><div style="font-size: 1.6rem; font-weight: 700; color: #c5a059; font-family: \'Newsreader\', serif;">{d["Score"]}</div><div style="font-size: 0.7rem; color: #71717a; text-transform: uppercase;">Score</div></div></div><div class="trade-ticket"><div style="display: flex; justify-content: space-between; font-weight: 600; color: #0f291e; margin-bottom: 4px;"><span>🎯 Buy Trigger: ${d["BOS_Level"]:,.2f}</span><span>📐 Reward/Risk: {d["R_Multiple"]:.1f}R</span></div><div style="display: flex; justify-content: space-between;"><span>🟢 <b>Take Profit:</b> <span style="color:#15803d; font-weight:700;">${d["Target_Price"]:,.2f}</span> (+{d["Target_Pct"]:.1f}%)</span><span>🔴 <b>Stop-Loss:</b> <span style="color:#b91c1c; font-weight:700;">${d["Stop_Price"]:,.2f}</span> ({d["Stop_Pct"]:.1f}%)</span></div><div style="margin-top: 4px; font-size: 0.76rem; color: #52525b; display: flex; justify-content: space-between;"><span><b>0.5% Risk Size:</b> Buy {d["Shares_05Pct"]} shares (${d["Pos_Value"]:,.0f})</span><span><b>{d["TCT_Model"]}</b></span></div></div><div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.78rem; color: #52525b;"><div>Day High: <b>${d["Day_High"]:,.2f}</b></div><div>Day Low: <b>${d["Day_Low"]:,.2f}</b></div><div>RSI: <b>{d["RSI"]:.1f}</b></div><div>EMA 50: <b>${d["History"]["EMA50"].iloc[-1]:,.2f}</b></div></div><div style="font-size: 0.80rem; color: #475569; margin-top: 6px; font-style: italic;">"{d["TCT_Explain"]}"</div></div>',
                        unsafe_allow_html=True
                    )

    elif navigation == "Precious Metals, Crypto & Currency":
        st.markdown("<h1>Precious Metals, Crypto & Currency</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Live Precious & Industrial Metals, Cryptocurrencies, and Major FX with clickable charts, realistic Buy/Target/Stop levels, and dedicated news.</p>", unsafe_allow_html=True)

        METALS_GROUP = {
            "Gold Futures / Spot (USD/oz)": "GC=F",
            "Silver Futures / Spot (USD/oz)": "SI=F",
            "Copper Futures (USD/lb)": "HG=F",
            "Platinum Futures (USD/oz)": "PL=F",
            "SPDR Gold Trust ETF (GLD)": "GLD",
            "iShares Silver Trust ETF (SLV)": "SLV"
        }
        CRYPTO_GROUP = {
            "Bitcoin (BTC/USD)": "BTC-USD",
            "Ethereum (ETH/USD)": "ETH-USD",
            "XRP (XRP/USD)": "XRP-USD",
            "Solana (SOL/USD)": "SOL-USD"
        }
        FX_GROUP = {
            "US Dollar Index (DXY)": "DX-Y.NYB",
            "USD / JPY": "JPY=X",
            "EUR / USD": "EURUSD=X"
        }

        all_mcf_syms = list(METALS_GROUP.values()) + list(CRYPTO_GROUP.values()) + list(FX_GROUP.values())
        mcf_data = fetch_batch_market_data(all_mcf_syms, account_size=settings["account_size"])

        def render_asset_group(group_dict):
            c1, c2 = st.columns(2)
            for idx, (title, sym) in enumerate(group_dict.items()):
                col = c1 if idx % 2 == 0 else c2
                if sym in mcf_data:
                    m = mcf_data[sym]
                    decimals = 4 if sym in ("EURUSD=X", "XRP-USD", "HG=F") else 2
                    with col:
                        st.markdown(
                            f'<div class="stock-card"><div style="display:flex; justify-content:space-between; align-items:center;"><div style="font-size: 0.76rem; color: #71717a; text-transform: uppercase; font-weight: 700;">{title}</div><span class="badge {m["TCT_Badge"]}">{m["TCT_Action"]}</span></div><div style="display: flex; justify-content: space-between; align-items: baseline; margin-top: 6px;"><div><a href="?inspect={sym}" target="_self" class="ticker-link">📊 {sym}</a><span style="font-size: 1.45rem; font-weight: 700; color: #0f291e; margin-left: 10px;">${m["Price"]:,.{decimals}f}</span><span style="font-size: 0.92rem; color: {"#15803d" if m["Change"]>=0 else "#b91c1c"}; font-weight: 600; margin-left: 6px;">{"+" if m["Change"]>=0 else ""}{m["Change_Pct"]:.2f}%</span></div><span class="badge {m["Badge"]}">{m["State"]}</span></div><div class="trade-ticket"><div style="display:flex; justify-content:space-between;"><span>🎯 <b>Buy Trigger:</b> ${m["BOS_Level"]:,.{decimals}f}</span><span>📐 <b>Reward/Risk:</b> {m["R_Multiple"]:.1f}R</span></div><div style="display:flex; justify-content:space-between; margin-top:3px;"><span>🟢 <b>Target:</b> <b style="color:#15803d;">${m["Target_Price"]:,.{decimals}f}</b> (+{m["Target_Pct"]:.1f}%)</span><span>🔴 <b>Stop:</b> <b style="color:#b91c1c;">${m["Stop_Price"]:,.{decimals}f}</b> ({m["Stop_Pct"]:.1f}%)</span></div></div><div style="margin-top: 8px; font-size: 0.78rem; color: #52525b; display:flex; justify-content:space-between;"><span>Day High: <b>${m["Day_High"]:,.{decimals}f}</b></span><span>Day Low: <b>${m["Day_Low"]:,.{decimals}f}</b></span><span>RSI: <b>{m["RSI"]:.1f}</b></span><span>EMA 50: <b>${m["History"]["EMA50"].iloc[-1]:,.{decimals}f}</b></span></div></div>',
                            unsafe_allow_html=True
                        )

        st.subheader("1. Precious & Industrial Metals (Gold, Silver, Copper, Platinum)")
        render_asset_group(METALS_GROUP)

        st.markdown("---")
        st.subheader("2. Cryptocurrencies (BTC, ETH, XRP, SOL)")
        render_asset_group(CRYPTO_GROUP)

        st.markdown("---")
        st.subheader("3. Currencies & US Dollar Index (DXY, USD/JPY, EUR/USD)")
        render_asset_group(FX_GROUP)

        st.markdown("---")
        st.subheader("4. Precious Metals, Crypto & USD News Stream (Last 72 Hours)")
        mcf_news = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if mcf_news:
            news_html = '<div class="scroll-news-box">'
            for a in mcf_news:
                news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{a["ticker"]}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
            news_html += '</div>'
            st.markdown(news_html, unsafe_allow_html=True)

    elif navigation == "News & Earnings":
        st.markdown("<h1>News & Catalyst Monitor</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Strict 72-hour verified news stream (spam aggregators blocked) and chronologically sorted earnings calendar.</p>", unsafe_allow_html=True)

        n_col1, n_col2 = st.columns([2, 1])

        tracked_symbols = get_all_monitored_tickers()

        with n_col1:
            n_tab1, n_tab2 = st.tabs([
                f"Watchlist News ({len(tracked_symbols)} Stocks)",
                "Metals, Crypto & USD News"
            ])
            with n_tab1:
                pool_articles = fetch_watchlist_news_pool(tracked_symbols, max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if pool_articles:
                    st.caption(f"Showing {len(pool_articles)} verified headlines from the past {settings['max_news_age_hours']} hours.")
                    news_html = '<div class="scroll-news-box">'
                    for a in pool_articles:
                        ticker_name = a.get("ticker", "ALERT")
                        news_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{ticker_name}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                    news_html += '</div>'
                    st.markdown(news_html, unsafe_allow_html=True)
                else:
                    st.info("No verified headlines in the past 72 hours for your tracked stocks.")

            with n_tab2:
                mcf_articles = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if mcf_articles:
                    st.caption(f"Showing {len(mcf_articles)} verified Metals, Crypto & USD headlines from the past {settings['max_news_age_hours']} hours.")
                    c_html = '<div class="scroll-news-box">'
                    for a in mcf_articles:
                        c_html += f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{a["ticker"]}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>'
                    c_html += '</div>'
                    st.markdown(c_html, unsafe_allow_html=True)

        with n_col2:
            st.subheader("Upcoming Earnings Calendar")
            earnings_map = fetch_upcoming_earnings_map(tracked_symbols)
            if earnings_map:
                rows = []
                for s, (days_left, dt_str) in earnings_map.items():
                    rows.append({
                        "Ticker": s,
                        "Earnings Date": dt_str,
                        "In Days": f"{days_left}d" + (" ⚠️" if days_left <= 7 else ""),
                        "_sort": days_left
                    })
                rows = sorted(rows, key=lambda x: x["_sort"])
                clean_df = pd.DataFrame([{"Ticker": r["Ticker"], "Earnings Date": r["Earnings Date"], "Countdown": r["In Days"]} for r in rows])
                st.table(clean_df)
            else:
                st.info("No confirmed upcoming earnings within the next 45 days.")

    elif navigation == "Settings":
        st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Configure your TCT account size, news freshness cutoff, and test your Daily Briefing push alert.</p>", unsafe_allow_html=True)

        s_col1, s_col2 = st.columns(2)

        with s_col1:
            st.subheader("TCT Portfolio & News Freshness")
            acc_val = st.number_input("Total Trading Account Size ($ USD) — For 0.5% Risk Share Sizing", min_value=1000, max_value=50000000, value=int(settings.get("account_size", 100000)), step=5000)
            news_lim = st.slider("Max News Headlines in Scrollable Feed", min_value=20, max_value=100, value=int(settings.get("news_limit", 60)), step=10)
            max_age_h = st.slider("Strict News Age Cutoff (Hours) — Blocks Older Articles", min_value=24, max_value=120, value=int(settings.get("max_news_age_hours", 72)), step=12)

            st.markdown("---")
            st.subheader("Score Weighting Defaults")
            w_f = st.slider("Fundamentals Weight", 0, 100, settings["w_fund"])
            w_t = st.slider("Technical Trend Weight", 0, 100, settings["w_tech"])
            w_m = st.slider("Momentum Weight", 0, 100, settings["w_mom"])

            if st.button("Save All Settings", type="primary"):
                settings["account_size"] = acc_val
                settings["news_limit"] = news_lim
                settings["max_news_age_hours"] = max_age_h
                settings["w_fund"] = w_f
                settings["w_tech"] = w_t
                settings["w_mom"] = w_m
                save_json(SETTINGS_FILE, settings)
                st.cache_data.clear()
                st.success("Settings saved and cache refreshed!")

        with s_col2:
            st.subheader("Push Notifications (Style 1 Daily Briefing)")
            all_syms = get_all_monitored_tickers()
            current_data = fetch_batch_market_data(all_syms, account_size=settings["account_size"])

            if st.button("🔔 Send Live Daily Briefing Ping to iPad Now", type="primary"):
                buys = [f"{k} (Buy ${v['BOS_Level']:.2f} -> Target ${v['Target_Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 0]
                tct_boxes = [f"{k} (BOS ${v['BOS_Level']:.2f})" for k, v in current_data.items() if v["TCT_Valid_Range"] and v["TCT_Priority"] != 0]
                breaks = [k for k, v in current_data.items() if v["State"] == "Confirmed Breakout" and v["TCT_Priority"] != 0]
                sells = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 4]
                summary_msg = (
                    f"🟢 BUY NOW ({len(buys)}): {', '.join(buys[:6]) if buys else 'None'}\n"
                    f"📐 In TCT Bottom Box ({len(tct_boxes)}): {', '.join(tct_boxes[:6]) if tct_boxes else 'None'}\n"
                    f"🚀 Momentum Breakouts ({len(breaks)}): {', '.join(breaks[:8]) if breaks else 'None'}\n"
                    f"🔴 Below 50 EMA / Avoid ({len(sells)}): {', '.join(sells[:8]) if sells else 'None'}"
                )
                ok, status_msg = send_ntfy_alert(summary_msg, "Daily Portfolio Briefing")
                if ok:
                    st.success(f"✅ {status_msg}")
                else:
                    st.error(f"❌ {status_msg}")

            st.markdown("---")
            st.subheader("Export Strategy Review CSV")
            if current_data:
                export_rows = []
                for sym_name, d in current_data.items():
                    export_rows.append({
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Ticker": sym_name,
                        "Price": d["Price"],
                        "Change": d["Change"],
                        "Change_Pct": d["Change_Pct"],
                        "Day_High": d["Day_High"],
                        "Day_Low": d["Day_Low"],
                        "Playbook": d["TCT_Model"],
                        "Action_Signal": d["TCT_Action"],
                        "Buy_Trigger": d["BOS_Level"],
                        "Take_Profit_Target": d["Target_Price"],
                        "Stop_Loss": d["Stop_Price"],
                        "Reward_Risk_R": round(d["R_Multiple"], 2),
                        "Suggested_Shares_05Pct": d["Shares_05Pct"],
                        "RS_vs_SP500_Pct": round(d["RS_Diff"], 2),
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
