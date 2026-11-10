import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import io
import time
import base64
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import email.utils
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor
try:
  st.set_option("client.toolbarMode", "minimal")
except Exception:
  pass

st.set_page_config(
  page_title="Quality Momentum & TCT Cockpit",
  layout="wide",
  initial_sidebar_state="expanded"
)

# --- SILENT MULTI-USER URL ROUTING (?user=name) & PERSISTENT FILES ---
if "active_user" not in st.session_state:
  st.session_state["active_user"] = ""

raw_user_q = st.query_params.get("user", "")
if raw_user_q:
  clean_u = "".join(c for c in str(raw_user_q).strip().lower() if c.isalnum() or c in ("_", "-"))
  if clean_u:
    st.session_state["active_user"] = clean_u

ACTIVE_USER = st.session_state.get("active_user", "")
if ACTIVE_USER and st.query_params.get("user") != ACTIVE_USER:
  st.query_params["user"] = ACTIVE_USER

USER_SUFFIX = f"_{ACTIVE_USER}" if ACTIVE_USER else ""
STATE_FILE = f"alert_state{USER_SUFFIX}.json"
DATA_FILE = f"watchlists{USER_SUFFIX}.json"
POSITIONS_FILE = f"positions{USER_SUFFIX}.json"
LEDGER_FILE = f"trade_ledger{USER_SUFFIX}.json"
SETTINGS_FILE = f"settings{USER_SUFFIX}.json"
UI_STATE_FILE = f"ui_state{USER_SUFFIX}.json"
GITHUB_REPO = "lingpesos-web/quality-momentum"
GITHUB_BRANCH = "main"

def load_json(filepath, default):
  if os.path.exists(filepath):
    try:
      with open(filepath, "r") as f:
        data = json.load(f)
        if isinstance(data, dict) or isinstance(data, list):
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
DEFAULT_UI_STATE = {
  "nav_radio": "Dashboard",
  "wl_folder": "Active Portfolio",
  "live_folder": "Active Portfolio",
  "wl_preset_filter": "ALL",
  "screener_tickers": None,
  "screener_title": None
}
saved_ui = load_json(UI_STATE_FILE, DEFAULT_UI_STATE)
if not isinstance(saved_ui, dict):
  saved_ui = dict(DEFAULT_UI_STATE)

# --- INITIALIZE SESSION STATE & URL ROUTING (PERSISTS ACROSS BACK BUTTON & IPAD APP SWITCHING) ---
for k, v in [
  ("inspect_symbol", None),
  ("rt_chart_symbol", None),
  ("nav_radio", saved_ui.get("nav_radio", "Dashboard")),
  ("wl_folder_radio", saved_ui.get("wl_folder", "Active Portfolio")),
  ("live_folder_sel", saved_ui.get("live_folder", "Active Portfolio")),
  ("screener_matches", None),
  ("screener_tickers", saved_ui.get("screener_tickers", None)),
  ("screener_title", saved_ui.get("screener_title", None)),
  ("wl_preset_filter", saved_ui.get("wl_preset_filter", "ALL")),
  ("last_good_data", {}),
  ("chat_messages", []),
  ("sds_videos", [])
]:
  if k not in st.session_state:
    st.session_state[k] = v

def persist_ui_state():
  save_json(UI_STATE_FILE, {
    "nav_radio": st.session_state.get("nav_radio", "Dashboard"),
    "wl_folder": st.session_state.get("wl_folder_radio", "Active Portfolio"),
    "live_folder": st.session_state.get("live_folder_sel", "Active Portfolio"),
    "wl_preset_filter": st.session_state.get("wl_preset_filter", "ALL"),
    "screener_tickers": st.session_state.get("screener_tickers", None),
    "screener_title": st.session_state.get("screener_title", None)
  })

def _reset_transient_query_params():
  st.query_params.clear()
  if ACTIVE_USER:
    st.query_params["user"] = ACTIVE_USER

if "inspect" in st.query_params:
  clicked_sym = st.query_params.get("inspect", "").strip().upper()
  if clicked_sym:
    st.session_state.inspect_symbol = clicked_sym
  _reset_transient_query_params()

if "rt_chart" in st.query_params:
  rt_sym = st.query_params.get("rt_chart", "").strip().upper()
  if rt_sym:
    st.session_state.rt_chart_symbol = rt_sym
    st.session_state.inspect_symbol = None
    st.session_state.nav_radio = "Live Real-Time Quotes"
    persist_ui_state()
  _reset_transient_query_params()

def clear_inspection():
  st.session_state.inspect_symbol = None
  if "inspect" in st.query_params or "rt_chart" in st.query_params:
    _reset_transient_query_params()
  persist_ui_state()

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

# --- CUSTOM CSS: MANUS EDITORIAL THEME + LARGE-FONT 2-COLUMN LIVE BOARD ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600;700;800&display=swap');.stApp{background-color:#fbf9f4 !important;color:#1a1a1a !important;font-family:'Inter', sans-serif;}[data-testid="stSidebar"]{background-color:#0f291e !important;border-right:1px solid #1c3d2f;}[data-testid="stSidebar"] *{color:#e2e8f0 !important;}[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label{padding:8px 12px;border-radius:6px;margin-bottom:4px;transition:all 0.2s;}[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover{background-color:#183d2e;}h1, h2, h3{font-family:'Newsreader', Georgia, serif !important;font-weight:600 !important;color:#0f291e !important;}.macro-container{display:flex;flex-wrap:nowrap;gap:8px;overflow-x:auto;padding-bottom:8px;margin-bottom:12px;}.macro-card{flex:1 1 0px;min-width:105px;background:#ffffff;border:1px solid #e7e2d9;border-radius:8px;padding:8px 6px;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.02);}.macro-title{font-size:0.68rem;color:#71717a;text-transform:uppercase;font-weight:700;letter-spacing:0.04em;white-space:nowrap;}.macro-price{font-size:0.88rem;font-weight:700;color:#18181b;margin:2px 0;white-space:nowrap;}.tick-pos{color:#15803d;font-size:0.72rem;font-weight:600;white-space:nowrap;}.tick-neg{color:#b91c1c;font-size:0.72rem;font-weight:600;white-space:nowrap;}.stock-card{background:#ffffff;border:1px solid #e7e2d9;border-radius:10px;padding:16px;margin-bottom:14px;box-shadow:0 1px 4px rgba(0,0,0,0.03);}.ticker-link{font-size:1.25rem;font-weight:700;color:#0f291e !important;text-decoration:none !important;border-bottom:2px solid #c5a059;padding-bottom:1px;}.ticker-link:hover{color:#15803d !important;border-bottom-color:#15803d;background-color:#f0fdf4;border-radius:4px;padding:2px 6px;}.hero-ticker-link{font-size:1.85rem;font-weight:700;color:#ffffff !important;text-decoration:none !important;border-bottom:2px dashed #c5a059;padding-bottom:2px;}.badge{display:inline-block;padding:2px 8px;border-radius:4px;font-size:0.68rem;font-weight:600;text-transform:uppercase;}.badge-breakout{background:#dcfce7;color:#15803d;}.badge-trend{background:#dbeafe;color:#1d4ed8;}.badge-candidate{background:#fef9c3;color:#a16207;}.badge-caution{background:#fee2e2;color:#b91c1c;}.badge-tct-buy{background:#15803d;color:#ffffff;}.badge-tct-watch{background:#fef08a;color:#854d0e;border:1px solid #fde047;}.badge-tct-sell{background:#b91c1c;color:#ffffff;}.badge-rs-lead{background:#ecfdf5;color:#047857;border:1px solid #a7f3d0;}.badge-rs-lag{background:#f4f4f5;color:#71717a;}.badge-earn-warn{background:#ffedd5;color:#c2410c;border:1px solid #fdba74;font-weight:700;}.pill{display:inline-flex;align-items:center;background:#e9e4db;color:#0f291e !important;text-decoration:none !important;padding:4px 10px;border-radius:14px;font-size:0.8rem;font-weight:600;margin-right:6px;margin-bottom:6px;}.pill:hover{background:#d6cfc2;}.scroll-news-box{max-height:540px;overflow-y:auto;padding-right:6px;}.ticker-news-badge{background:#dcfce7;color:#15803d;padding:2px 6px;border-radius:4px;font-weight:700;font-size:0.7rem;margin-right:6px;}.age-badge{background:#f1f5f9;color:#334155;padding:2px 6px;border-radius:4px;font-weight:600;font-size:0.68rem;margin-left:6px;}.trade-ticket{background:#f8f6f0;border:1px solid #e2ddd2;border-radius:8px;padding:10px 12px;margin-top:10px;font-size:0.80rem;}/* LARGE-FONT 2-COLUMN LIVE WATCHBOARD TABLE */
.live-board-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;width:100%;margin-top:4px;}@media (max-width:900px){.live-board-grid{grid-template-columns:1fr;}}.live-quote-table{width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #d4cec3;border-radius:6px;overflow:hidden;font-size:1.12rem;table-layout:auto;}.live-quote-table thead th{background:#0f291e;color:#f4efe6;font-weight:700;font-size:0.82rem;text-transform:uppercase;letter-spacing:0.02em;padding:6px 5px;text-align:right;white-space:nowrap;}.live-quote-table thead th:nth-child(1), .live-quote-table thead th:nth-child(2){text-align:left;}.live-quote-table tbody tr{border-bottom:1px solid #eae5dc;line-height:1.25;}.live-quote-table tbody tr:nth-child(even){background-color:#faf8f5;}.live-quote-table tbody tr:hover{background-color:#ecfdf5;}.live-quote-table td{padding:5px 5px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}.live-quote-table td:nth-child(1){text-align:left;font-size:0.92rem;font-weight:700;padding-left:6px;padding-right:4px;}.live-quote-table td:nth-child(2){text-align:left;font-weight:800;padding-left:4px;padding-right:4px;}.rt-sym-link{color:#0f291e !important;text-decoration:none !important;font-weight:800;font-size:1.18rem;border-bottom:2px solid #c5a059;}.rt-sym-link:hover{color:#15803d !important;background:#dcfce7;padding:1px 4px;border-radius:3px;}.rt-price-link{text-decoration:none !important;font-weight:800;border-bottom:1px dashed rgba(15,41,30,0.35);padding-bottom:1px;}.rt-price-link:hover{background:#dcfce7;padding:1px 4px;border-radius:3px;}[data-testid="InputInstructions"]{display:none !important;}[data-testid="stToolbarActions"],[data-testid="stActionButtonIcon"],[data-testid="stHeaderActionElements"],[data-testid="manage-app-button"],[data-testid="stMainMenu"],.stDeployButton,.stAppDeployButton,header a[href*="github.com"],div[class*="viewerBadge"],a[class*="viewerBadge"],div[class*="StatusWidget"]{display:none !important;visibility:hidden !important;}</style>
""", unsafe_allow_html=True)

# --- WATCHLISTS & GITHUB AUTO-SYNC ---
DEFAULT_WATCHLISTS = {
  "Active Portfolio": [
    "SLV", "VRT", "COHR", "SKHY", "SNDK", "MU", "DRAM", "HOOD", "SOFI",
    "PLTR", "GLW", "LRCX", "MRVL", "CLS", "CRCL", "LITE", "ADPT", "SPCX",
    "STX", "WDC", "TEM", "IREN", "CBRS", "CDE", "SOXL", "IONQ", "QUBT",
    "AMD", "APP", "COIN", "MSTR", "CRDO", "NVDA"
  ],
  "Opportunity Radar": ["PLTR", "MU", "HOOD", "LRCX", "SOFI", "MRVL", "AVGO", "COST"],
  "Special Case Stocks": ["COIN", "MSTR", "SOXL", "IONQ"],
  "Active Positions": []
}

def get_github_token():
  try:
    if "GITHUB_TOKEN" in st.secrets:
      return str(st.secrets["GITHUB_TOKEN"]).strip()
  except Exception:
    pass
  return os.environ.get("GITHUB_TOKEN", "").strip()

def sync_file_to_github(data, filename):
  save_json(filename, data)
  token = get_github_token()
  if not token:
    return False, f"Saved locally (Add GITHUB_TOKEN in Streamlit Secrets for permanent cloud sync of {filename})."
  api_url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{filename}"
  headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json", "User-Agent": "Quality-Momentum-Cockpit"}
  try:
    sha = None
    try:
      with urllib.request.urlopen(urllib.request.Request(f"{api_url}?ref={GITHUB_BRANCH}", headers=headers), timeout=6) as resp:
        sha = json.loads(resp.read().decode("utf-8")).get("sha")
    except Exception:
      pass
    payload = {
      "message": f"Auto-sync {filename} ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
      "content": base64.b64encode(json.dumps(data, indent=2).encode("utf-8")).decode("utf-8"),
      "branch": GITHUB_BRANCH
    }
    if sha:
      payload["sha"] = sha
    req_put = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers={**headers, "Content-Type": "application/json"}, method="PUT")
    with urllib.request.urlopen(req_put, timeout=8) as resp:
      if resp.status in (200, 201):
        return True, f"Permanently synced to GitHub {filename}!"
  except Exception as e:
    return False, f"Saved locally (GitHub sync error: {str(e)[:60]})"
  return False, "Saved locally."
watchlists = load_json(DATA_FILE, DEFAULT_WATCHLISTS)
for k_def, v_def in DEFAULT_WATCHLISTS.items():
  if k_def not in watchlists or not isinstance(watchlists[k_def], list):
    watchlists[k_def] = v_def
positions = load_json(POSITIONS_FILE, [])
trade_ledger = load_json(LEDGER_FILE, [])
if not isinstance(trade_ledger, list):
  trade_ledger = []

def get_all_monitored_tickers():
  combined = []
  for folder_syms in watchlists.values():
    if isinstance(folder_syms, list):
      combined.extend([str(s).strip().upper() for s in folder_syms if str(s).strip()])
  return list(dict.fromkeys(combined))
settings = load_json(SETTINGS_FILE, {
  "w_fund": 40, "w_tech": 40, "w_mom": 20, "account_size": 100000,
  "news_limit": 60, "max_news_age_hours": 72, "alert_breakout": True, "alert_support": True
})
for k_s, v_s in [("account_size", 100000), ("news_limit", 60), ("max_news_age_hours", 72), ("w_fund", 40), ("w_tech", 40), ("w_mom", 20)]:
  if k_s not in settings:
    settings[k_s] = v_s
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
    "COIN", "MSTR", "HOOD", "SOFI", "PYPL", "MARA", "RIOT", "CLSK", "IREN", "CORZ",
    "HUT", "WULF", "CIFR", "JPM", "GS", "MS", "BLK", "BX", "KKR", "APO",
    "ARES", "V", "MA", "AXP", "BAC", "WFC", "C", "SCHW"
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
  ],
  "Indexes, Precious Metals & Crypto": [
    "^GSPC", "^DJI", "^IXIC", "GC=F", "SI=F", "HG=F", "PL=F", "GLD", "SLV",
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DX-Y.NYB", "JPY=X", "EURUSD=X"
  ]
}
BLOCKED_NEWS_SOURCES = {
  "marketbeat", "zacks", "defense world", "etf daily news", "ticker report",
  "american banking news", "simply wall st", "stocknews.com", "wall street zen",
  "holdings channel", "transcript daily", "modern readers", "watch list news",
  "stocktwits", "stockwits"
}
STALE_HEADLINE_PATTERNS = [
  "if you invested", "years ago", "last year",
  "months ago", "why shares plunged in ", "heres how much "
]

def _fetch_rss_raw(query, max_per_query=15, ticker_tag=None, max_age_hours=72):
  q_with_time = query if "when:" in query else f"{query} when:3d"
  url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q_with_time)}&hl=en-US&gl=US&ceid=US:en"
  req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
  articles = []
  now_utc = datetime.now(timezone.utc)
  try:
    with urllib.request.urlopen(req, timeout=3.5) as response:
      root = ET.fromstring(response.read())
    for item in root.findall(".//item")[:max_per_query]:
      raw_title = item.find("title").text if item.find("title") is not None else ""
      link = item.find("link").text if item.find("link") is not None else "#"
      pub_date_raw = item.find("pubDate").text if item.find("pubDate") is not None else ""
      source = item.find("source").text if item.find("source") is not None else "News"
      if not raw_title or not pub_date_raw:
        continue
      if any(bad in source.lower().strip() for bad in BLOCKED_NEWS_SOURCES):
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
      age_label = f"{max(1, int(age_hours * 60))}m ago" if age_hours < 1.0 else (f"{int(age_hours)}h ago" if age_hours < 24.0 else f"{int(age_hours // 24)}d ago")
      articles.append({
        "title": clean_title, "link": link, "publisher": source,
        "date": dt_obj.strftime("%b %d · %H:%M UTC"), "age": age_label,
        "timestamp": dt_obj.timestamp(), "ticker": ticker_tag or "MARKET"
      })
  except Exception:
    pass
  return articles

def _safe_parallel_map(fn, items, max_workers=2):
  if not items:
    return []
  try:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
      return list(executor.map(fn, items))
  except Exception:
    return [fn(x) for x in items]

@st.cache_data(ttl=600)
def fetch_google_news_rss(query, max_items=60, max_age_hours=72):
  queries = [f"{query} when:3d", "S&P 500 Nasdaq stock market today when:3d", "Wall Street stocks earnings Federal Reserve when:3d", "US tech stocks semiconductors market news when:3d"]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(lambda q: _fetch_rss_raw(q, 25, "MARKET", max_age_hours), queries, max_workers=2)
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

@st.cache_data(ttl=600)
def fetch_watchlist_news_pool(tickers, max_items=60, max_age_hours=72):
  if not tickers:
    return []
  unique_syms = [str(s).strip().upper() for s in dict.fromkeys(tickers) if str(s).strip()][:18]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(
    lambda sym: _fetch_rss_raw(f'"{sym}" stock when:3d', 4, sym, max_age_hours),
    unique_syms,
    max_workers=4
  )
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

@st.cache_data(ttl=600)
def fetch_metals_crypto_fx_news(max_items=50, max_age_hours=72):
  queries = [("gold silver copper prices commodities market when:3d", "METALS"), ("Bitcoin Ethereum Solana XRP crypto market when:3d", "CRYPTO"), ("US Dollar Index DXY USD JPY EUR USD forex when:3d", "FX/USD")]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(lambda qt: _fetch_rss_raw(qt[0], 22, qt[1], max_age_hours), queries, max_workers=2)
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]

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
      if raw_date is not None:
        dt_parsed = pd.to_datetime(raw_date).to_pydatetime().replace(tzinfo=None, hour=0, minute=0, second=0)
        days_diff = (dt_parsed - now_dt).days
        if 0 <= days_diff <= 60:
          return sym, (days_diff, dt_parsed.strftime("%Y-%m-%d"))
    except Exception:
      pass
    return sym, None
  for sym, res in _safe_parallel_map(_check_one, list(dict.fromkeys(tickers))[:25], max_workers=4):
    if res is not None:
      out[sym] = res
  return out

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
  stock_ret_63d = ((curr_close - float(close_arr[-1 - lookback_rs])) / float(close_arr[-1 - lookback_rs])) * 100.0 if lookback_rs > 5 and close_arr[-1 - lookback_rs] > 0 else 0.0
  rs_diff = stock_ret_63d - spy_ret_63d
  rs_leader = bool(rs_diff >= 2.0)
  dollar_vol_20 = float(pd.Series(close_arr[-20:] * vol_arr[-20:]).median()) if n >= 20 else 0.0
  liq_pass = bool(dollar_vol_20 >= 50_000_000)
  tr = pd.concat([df["High"] - df["Low"], (df["High"] - df["Close"].shift(1)).abs(), (df["Low"] - df["Close"].shift(1)).abs()], axis=1).max(axis=1)
  atr14_daily = float(tr.rolling(14).mean().iloc[-1])
  if np.isnan(atr14_daily) or atr14_daily <= 0:
    atr14_daily = curr_close * 0.025
  atr14_1h_est = atr14_daily / 2.55
  ema20 = float(df["EMA20"].iloc[-1])
  ema50 = float(df["EMA50"].iloc[-1])
  ema200 = float(df["EMA200"].iloc[-1]) if len(df) >= 200 else ema50
  if "SMA150" not in df.columns:
    df["SMA150"] = df["Close"].rolling(150, min_periods=1).mean()
  sma150_arr = df["SMA150"].values.astype(float)
  sma150 = float(sma150_arr[-1])
  sma150_20d_ago = float(sma150_arr[-20]) if n >= 20 else sma150
  sma150_rising = bool(sma150 >= sma150_20d_ago * 0.9985)
  below_sma150 = bool(curr_close < sma150)
  ma5 = float(pd.Series(close_arr[-10:]).rolling(5, min_periods=1).mean().iloc[-1])
  ma10 = float(pd.Series(close_arr[-15:]).rolling(10, min_periods=1).mean().iloc[-1])
  delta = df["Close"].diff()
  g2 = delta.where(delta > 0, 0.0).ewm(alpha=1/2, adjust=False).mean()
  l2 = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/2, adjust=False).mean()
  rsi2_series = 100 - (100 / (1 + (g2 / (l2 + 1e-9))))
  rsi2 = float(rsi2_series.iloc[-1]) if not np.isnan(rsi2_series.iloc[-1]) else 50.0
  rsi14 = float(df["RSI"].iloc[-1]) if not np.isnan(df["RSI"].iloc[-1]) else 50.0
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
  swing_highs = [(i, float(high_arr[i])) for i in range(3, n - 3) if high_arr[i] == np.max(high_arr[i - 3:i + 4])]
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
  high_20d_curr = float(np.max(high_arr[-20:])) if n >= 20 else curr_close
  high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_close
  high_3d_prev = float(np.max(high_arr[-4:-1])) if n >= 5 else curr_close
  low_3d = float(np.min(low_arr[-3:]))
  # --- STAGE 2 & 150-DAY MA STRATEGIES ---
  lb_rev = min(n, 30)
  bars_below_150 = int(np.sum(close_arr[-lb_rev:-1] < sma150_arr[-lb_rev:-1])) if lb_rev > 3 else 0
  is_150ma_reversal_radar = bool(
    (curr_close >= sma150) and
    (curr_close <= sma150 * 1.075) and
    (bars_below_150 >= 3)
  )
  recent_pb_low = float(np.min(low_arr[-12:])) if n >= 12 else float(low_arr[-1])
  prior_pb_low = float(np.min(low_arr[-38:-12])) if n >= 38 else sma150
  pulled_back_from_high = (recent_pb_low <= high_20d_curr * 0.982) and (curr_close <= high_20d_curr * 0.994)
  near_rising_support = (recent_pb_low <= max(ema20, ema50) * 1.032) and (recent_pb_low > sma150 * 1.002)
  higher_low_intact = recent_pb_low > prior_pb_low * 1.002
  turning_up_trigger = (curr_close > recent_pb_low * 1.003) and (curr_close >= open_arr[-1] or curr_close > prev_close or ma5 >= ma10 * 0.998)
  is_stage2_higher_low = bool(
    (curr_close > sma150 * 1.015) and
    sma150_rising and
    (ema50 >= sma150 * 0.985) and
    higher_low_intact and
    pulled_back_from_high and
    near_rising_support and
    turning_up_trigger
  )
  is_pure_momentum = (curr_close > ema20) and (curr_close > ema50) and (curr_close > ema200) and rs_leader and (55 <= rsi14 <= 75)
  is_20d_breakout = (curr_close >= high_20d_prev) and (paced_rvol >= 1.25) and (curr_close > ema50)
  is_holy_grail_pullback = (curr_close > ema50) and (ema20 > ema50) and (abs(low_arr[-1] - ema20) / ema20 <= 0.022 or abs(curr_close - ema20) / ema20 <= 0.022) and (curr_close >= open_arr[-1] or curr_close > prev_close)
  is_squeeze_breakout = is_bb_squeeze and (curr_close > ema50) and (curr_close >= high_3d_prev)
  is_rsi2_snapback = (curr_close > ema200 * 0.96) and (rsi2 <= 18.0 or low_arr[-1] <= float(df["BB_Lower"].iloc[-1]))
  day_rng = max(high_arr[-1] - low_arr[-1], 1e-6)
  is_gap_ignition = ((curr_close - prev_close) / prev_close >= 0.032) and (paced_rvol >= 1.7) and ((curr_close - low_arr[-1]) / day_rng >= 0.55) and (curr_close > ema50)
  playbook_cat = "TREND"
  if tct_valid_range and range_high and bos_level and tap3_price:
    playbook_name = "Playbook 1: TCT Bottom Box"
    playbook_cat = "TCT"
    entry_ref = curr_close if curr_close >= bos_level else bos_level
    effective_stop = max(min(tap3_price - (0.5 * atr14_1h_est), entry_ref * 0.98), entry_ref * 0.93)
    target_price = range_high
  elif is_stage2_higher_low:
    playbook_name = "Playbook 7: Stage 2 Higher Low"
    playbook_cat = "STAGE2_HL"
    bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
    entry_ref = curr_close
    effective_stop = max(min(recent_pb_low - 0.35 * atr14_daily, sma150), curr_close * 0.935)
    target_price = max(high_20d_curr * 1.03, entry_ref + 2.5 * (entry_ref - effective_stop))
  elif is_150ma_reversal_radar:
    playbook_name = "Playbook 8: 150-MA Reversal Radar"
    playbook_cat = "REVERSAL_150"
    bos_level = high_5d_prev if curr_close < high_5d_prev else curr_close
    entry_ref = curr_close
    effective_stop = max(sma150 - 0.5 * atr14_daily, curr_close * 0.93)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  elif is_20d_breakout:
    playbook_name = "Playbook 2: 20D Momentum Breakout"
    playbook_cat = "BREAKOUT"
    bos_level = high_20d_prev
    entry_ref = curr_close
    effective_stop = max(min(ema20, curr_close - 1.5 * atr14_daily), curr_close * 0.94)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  elif is_gap_ignition:
    playbook_name = "Playbook 6: High-Vol Gap Ignition"
    playbook_cat = "BREAKOUT"
    bos_level = float(high_arr[-1]) if curr_close < high_arr[-1] else curr_close
    entry_ref = curr_close
    effective_stop = max(float(low_arr[-1]) - 0.2 * atr14_daily, curr_close * 0.94)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  elif is_squeeze_breakout:
    playbook_name = "Playbook 4: Volatility Squeeze Coil"
    playbook_cat = "SWING_PULLBACK"
    bos_level = high_3d_prev
    entry_ref = curr_close
    effective_stop = max(low_3d - 0.3 * atr14_daily, curr_close * 0.95)
    target_price = entry_ref + 2.8 * (entry_ref - effective_stop)
  elif is_holy_grail_pullback:
    playbook_name = "Playbook 3: 20-EMA Pullback Swing"
    playbook_cat = "SWING_PULLBACK"
    bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
    entry_ref = curr_close
    effective_stop = max(min(low_3d, ema20) - 0.5 * atr14_daily, curr_close * 0.95)
    target_price = max(high_20d_prev, entry_ref + 2.4 * (entry_ref - effective_stop))
  elif is_rsi2_snapback:
    playbook_name = f"Playbook 5: RSI-2 Oversold Bounce (RSI2={rsi2:.0f})"
    playbook_cat = "OVERSOLD"
    bos_level = curr_close
    entry_ref = curr_close
    effective_stop = max(curr_close - 1.5 * atr14_daily, curr_close * 0.945)
    target_price = max(ema20, entry_ref + 2.0 * (entry_ref - effective_stop))
  else:
    playbook_name = "Standard Trend Swing"
    bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
    entry_ref = curr_close if curr_close >= bos_level else bos_level
    effective_stop = max(min(entry_ref - 1.5 * atr14_daily, entry_ref * 0.978), entry_ref * 0.935)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  risk_per_share = max(entry_ref - effective_stop, 0.0001)
  reward_per_share = max(target_price - entry_ref, 0.0)
  r_multiple = reward_per_share / risk_per_share
  suggested_shares = max(1, int((account_size * 0.005) / risk_per_share))
  position_value = suggested_shares * entry_ref
  target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
  stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0
  crossed_5d = (curr_close >= high_5d_prev) and (prev_close < high_5d_prev)
  if tct_valid_range and curr_close >= bos_level and r_multiple >= 1.9:
    act, badge, dot, short_s, sig_clr, prio = "BUY NOW (TCT BOS)", "badge-tct-buy", "🟢", "🟢 Buy Now", "#15803d", 0
    expl = f"TCT accumulation breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
  elif is_stage2_higher_low:
    act, badge, dot, short_s, sig_clr, prio = "STAGE 2 HIGHER LOW", "badge-tct-buy", "📈", "📈 Stage 2 HL", "#15803d", 0
    expl = f"Stage 2 Higher Low: Uptrend above rising 150-MA (${sma150:,.2f}), Higher Low at ${recent_pb_low:,.2f} > prior low (${prior_pb_low:,.2f})."
  elif is_20d_breakout or is_gap_ignition:
    act, badge, dot, short_s, sig_clr, prio = "BUY NOW (BREAKOUT)", "badge-tct-buy", "🟢", "🟢 Buy Now", "#15803d", 0
    expl = f"{playbook_name}: Breakout above ${bos_level:,.2f} on {paced_rvol:.1f}x pace volume."
  elif is_squeeze_breakout or is_holy_grail_pullback:
    act, badge, dot, short_s, sig_clr, prio = "SWING BUY (PULLBACK/COIL)", "badge-tct-buy", "🎯", "🎯 Swing Buy", "#059669", 0
    expl = f"{playbook_name}: High-probability swing entry near ${entry_ref:,.2f}, stop ${effective_stop:,.2f}."
  elif is_150ma_reversal_radar:
    act, badge, dot, short_s, sig_clr, prio = "150-MA REVERSAL (RESEARCH)", "badge-tct-watch", "🔔", "🔔 150MA Radar", "#b45309", 1
    expl = f"Reclaimed 150-Day MA (${sma150:,.2f}). Early trend reversal radar — monitor for Stage 2 Higher Low."
  elif is_rsi2_snapback:
    act, badge, dot, short_s, sig_clr, prio = "SWING BUY (OVERSOLD)", "badge-tct-watch", "🪃", "🪃 Oversold", "#b45309", 1
    expl = f"RSI-2 extreme oversold ({rsi2:.0f}) above 200-EMA. Target bounce to ${target_price:,.2f}."
  elif tct_valid_range and curr_close < bos_level:
    act, badge, dot, short_s, sig_clr, prio = "WATCHING TCT BOX", "badge-tct-watch", "📐", "📐 TCT Box", "#854d0e", 1
    expl = f"Valid 25+ bar TCT bottom box formed. Buy if price closes above BOS ${bos_level:,.2f}."
  elif is_pure_momentum:
    act, badge, dot, short_s, sig_clr, prio = "MOMENTUM LEADER", "badge-rs-lead", "🔥", "🔥 Momentum", "#047857", 2
    expl = f"Strong institutional momentum leader (RS+, Price>20/50/200 EMA). Trailing stop ${effective_stop:,.2f}."
  elif curr_close > ema50 and (curr_close >= ema20 * 0.99 or crossed_5d):
    act, badge, dot, short_s, sig_clr, prio = "HOLD / BUY DIP", "badge-trend", "🔵", "🔵 Uptrend", "#1d4ed8", 2
    expl = f"Strong uptrend above 20 & 50 EMA. Swing target ${target_price:,.2f}, stop ${effective_stop:,.2f}."
  elif below_sma150 and not tct_valid_range and not is_rsi2_snapback:
    act, badge, dot, short_s, sig_clr, prio = "BROKE 150-MA (CUT LOSS)", "badge-tct-sell", "🔴", "🔴 Below 150MA", "#b91c1c", 4
    expl = f"Stage 4 Warning: Below 150-day MA (${sma150:,.2f}). Cut loss / avoid until price reclaims 150-MA."
  elif curr_close < ema50 and not tct_valid_range and not is_rsi2_snapback:
    act, badge, dot, short_s, sig_clr, prio = "SELL / AVOID", "badge-tct-sell", "🔴", "🔴 Below 50", "#b91c1c", 4
    expl = f"Below 50-day EMA (${ema50:,.2f}) without a valid TCT bottom box. Protect capital."
  else:
    act, badge, dot, short_s, sig_clr, prio = "WAIT FOR TRIGGER", "badge-candidate", "🟡", "🟡 Wait", "#a16207", 3
    expl = f"Consolidating. Wait for a clean move above ${bos_level:,.2f} before entering."
  return {
    "TCT_Valid_Range": tct_valid_range, "TCT_Model": playbook_name, "Playbook_Cat": playbook_cat,
    "TCT_Slow_25": slow_decline_25, "TCT_Liq_50M": liq_pass, "TCT_2R_Pass": bool(r_multiple >= 2.0),
    "TCT_Action": act, "TCT_Badge": badge, "TCT_Dot": dot, "TCT_Short_Sig": short_s, "TCT_Sig_Color": sig_clr,
    "TCT_Explain": expl, "TCT_Priority": prio, "BOS_Entry": entry_ref, "BOS_Level": bos_level,
    "Target_Price": target_price, "Stop_Price": effective_stop, "R_Multiple": r_multiple,
    "Target_Pct": target_gain_pct, "Stop_Pct": stop_loss_pct, "Shares_05Pct": suggested_shares,
    "Pos_Value": position_value, "Dollar_Vol_M": dollar_vol_20 / 1e6, "RS_Diff": rs_diff,
    "RS_Leader": rs_leader, "RSI2": rsi2, "Paced_RVOL": paced_rvol, "Is_Oversold_Swing": is_rsi2_snapback,
    "Is_Pure_Momentum": is_pure_momentum, "Is_Stage2_Higher_Low": is_stage2_higher_low,
    "Is_150MA_Reversal_Radar": is_150ma_reversal_radar, "Below_SMA150": below_sma150
  }

def check_and_fire_active_position_alerts(records):
  if not records or not positions:
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
    lines = []
    for pos in positions:
      sym = pos["Ticker"]
      if sym not in records: continue
      d = records[sym]
      live_price = d["Price"]
      target15 = pos["Target15"]
      stop_price = pos["StopLoss"]
      ema20 = d["EMA20_Val"]
      pos_id = pos["id"]
      if live_price <= stop_price and f"{pos_id}_STOP" not in alerted:
        lines.append(f"STOP HIT: {sym} dropped to ${live_price:,.2f} (Stop was ${stop_price:,.2f})")
        alerted.add(f"{pos_id}_STOP")
      if live_price >= target15 and not pos.get("HalfSold", False) and f"{pos_id}_TGT15" not in alerted:
        lines.append(f"+15% GAIN: {sym} reached ${live_price:,.2f}! Sell 50% ({int(pos['Shares']*0.5)} shs) and raise stop.")
        alerted.add(f"{pos_id}_TGT15")
      if live_price < ema20 and d["Change"] < 0 and f"{pos_id}_EMA20" not in alerted:
        lines.append(f"BROKE 20-EMA: {sym} dropped to ${live_price:,.2f} (EMA20: ${ema20:,.2f}). Trailing Exit Triggered.")
        alerted.add(f"{pos_id}_EMA20")
    if lines:
      for ln in lines:
        try:
          st.toast(ln)
        except Exception:
          pass
      send_ntfy_alert("\n".join(lines), "Active Position Rule Alert")
      state["alerted"] = sorted(list(alerted))
      save_json(STATE_FILE, state)
  except Exception:
    pass

def check_and_fire_live_ntfy(records):
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
    new_buys, new_reversals, new_targets, new_stops = [], [], [], []
    for sym, d in records.items():
      if d["TCT_Priority"] == 0 and f"{sym}_BUY" not in alerted:
        new_buys.append(f"{sym} ({d['TCT_Short_Sig']} @ ${d['Price']:,.2f} -> Tgt ${d['Target_Price']:,.2f})")
        alerted.add(f"{sym}_BUY")
      if d.get("Is_150MA_Reversal_Radar") and f"{sym}_REV150" not in alerted:
        new_reversals.append(f"{sym} (${d['Price']:,.2f} > 150MA ${d.get('SMA150_Val', d['Price']):,.2f})")
        alerted.add(f"{sym}_REV150")
      if d["Price"] >= d["Target_Price"] * 0.996 and f"{sym}_TGT" not in alerted:
        new_targets.append(f"{sym} Hit Target (${d['Price']:,.2f} >= ${d['Target_Price']:,.2f})")
        alerted.add(f"{sym}_TGT")
      if d["Price"] <= d["Stop_Price"] and f"{sym}_STOP" not in alerted:
        new_stops.append(f"{sym} Hit Stop (${d['Price']:,.2f} <= ${d['Stop_Price']:,.2f})")
        alerted.add(f"{sym}_STOP")
    if new_buys or new_reversals or new_targets or new_stops:
      lines = []
      if new_buys:
        lines.append("INSTANT BUY / STAGE 2 HL: " + ", ".join(new_buys[:6]))
      if new_reversals:
        lines.append("150-MA REVERSAL RADAR (RESEARCH): " + ", ".join(new_reversals[:6]))
      if new_targets:
        lines.append("TAKE PROFIT HIT: " + ", ".join(new_targets[:6]))
      if new_stops:
        lines.append("STOP-LOSS TRIGGERED: " + ", ".join(new_stops[:6]))
      for ln in lines:
        try:
          st.toast(ln)
        except Exception:
          pass
      send_ntfy_alert("\n".join(lines), "Live Intraday Trigger Alert")
      state["alerted"] = sorted(list(alerted))
      save_json(STATE_FILE, state)
  except Exception:
    pass

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
  pos_tickers = [str(p["Ticker"]).strip().upper() for p in positions if str(p.get("Ticker")).strip()]
  clean_tickers = list(dict.fromkeys(clean_tickers + pos_tickers))
  if not clean_tickers:
    return {}
  download_list = list(dict.fromkeys(clean_tickers + ["^GSPC"]))
  try:
    data = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False)
    now_utc = datetime.now(timezone.utc)
    data_intraday = None
    if now_utc.hour in (20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6):
      try:
        data_intraday = yf.download(clean_tickers[:60], period="5d", interval="15m", group_by="ticker", progress=False)
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
          df_intra = _extract_ticker_df(data_intraday, t, len(clean_tickers[:60])).dropna(subset=["Close"])
          if not df_intra.empty:
            intra_dates = pd.to_datetime(df_intra.index).tz_localize(None).normalize()
            last_intra_date = intra_dates[-1]
            last_1d_date = pd.to_datetime(df.index[-1]).tz_localize(None).normalize()
            ts = df_intra[intra_dates == last_intra_date]
            if not ts.empty:
              if last_intra_date > last_1d_date:
                new_r = pd.DataFrame({
                  "Open": [float(ts["Open"].iloc[0])], "High": [float(ts["High"].max())],
                  "Low": [float(ts["Low"].min())], "Close": [float(ts["Close"].iloc[-1])],
                  "Volume": [float(ts["Volume"].sum())]
                }, index=[last_intra_date])
                df = pd.concat([df, new_r])
              elif last_intra_date == last_1d_date:
                df.iloc[-1, df.columns.get_loc("Close")] = float(ts["Close"].iloc[-1])
                df.iloc[-1, df.columns.get_loc("High")] = max(float(df["High"].iloc[-1]), float(ts["High"].max()))
                df.iloc[-1, df.columns.get_loc("Low")] = min(float(df["Low"].iloc[-1]), float(ts["Low"].min()))
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
      df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
      df["SMA150"] = df["Close"].rolling(150, min_periods=1).mean()
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
      ema150_val = float(df["EMA150"].iloc[-1])
      sma150_val = float(df["SMA150"].iloc[-1])
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
        "EMA20_Val": ema20_val, "EMA50_Val": ema50_val, "EMA150_Val": ema150_val, "SMA150_Val": sma150_val,
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
    check_and_fire_active_position_alerts(results)
  else:
    return {k: v for k, v in st.session_state.get("last_good_data", {}).items() if k in clean_tickers}
  return results

@st.cache_data(ttl=180)
def fetch_single_ticker_data(sym, account_size=100000, period="5y", interval="1d"):
  res = fetch_batch_market_data([sym], account_size=account_size)
  base_rec = res.get(sym) if sym in res else None
  if period == "1y" and interval == "1d" and base_rec is not None and "EMA150" in base_rec["History"].columns:
    return base_rec
  try:
    t = yf.Ticker(sym)
    df = t.history(period=period, interval=interval)
    if (df is None or df.empty or len(df) < 20) and base_rec is not None:
      return base_rec
    if df is None or df.empty or len(df) < 10:
      return None
    try:
      df_1h = t.history(period="1mo", interval="1h")
    except Exception:
      df_1h = None
    close = float(df["Close"].iloc[-1])
    prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else close
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA150"] = df["Close"].ewm(span=150, adjust=False).mean()
    df["SMA150"] = df["Close"].rolling(150, min_periods=1).mean()
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
    if base_rec is not None:
      rec = dict(base_rec)
      rec["History"] = df
      rec["EMA150_Val"] = float(df["EMA150"].iloc[-1])
      rec["SMA150_Val"] = float(df["SMA150"].iloc[-1])
      return rec
    pb_info = analyze_six_playbooks(df, account_size=account_size, df_1h=df_1h)
    rec = {
      "Ticker": sym, "Price": close, "Change": close - prev_close,
      "Change_Pct": ((close - prev_close) / prev_close) * 100 if prev_close else 0,
      "Day_High": float(df["High"].iloc[-1]), "Day_Low": float(df["Low"].iloc[-1]),
      "RSI": float(df["RSI"].iloc[-1]), "RVOL": 1.0,
      "EMA20_Val": float(df["EMA20"].iloc[-1]), "EMA50_Val": float(df["EMA50"].iloc[-1]),
      "EMA150_Val": float(df["EMA150"].iloc[-1]), "SMA150_Val": float(df["SMA150"].iloc[-1]),
      "State": "Active Trend", "Badge": "badge-trend", "Reason": pb_info["TCT_Explain"],
      "Score": 80, "History": df
    }
    rec.update(pb_info)
    return rec
  except Exception:
    return base_rec

@st.cache_data(ttl=14400)
def fetch_ticker_fundamentals(ticker_symbol):
  data = {
    "Company Name": ticker_symbol, "Market Cap": "N/A", "Trailing P/E": "N/A",
    "Forward P/E": "N/A", "EPS (TTM)": "N/A", "Target Price": "N/A",
    "52W High": "N/A", "52W Low": "N/A", "All-Time High": "N/A", "All-Time Low": "N/A",
    "Earnings Date": "No upcoming (60d)", "Debt/Equity": "N/A",
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
    c_name = info.get("shortName") or info.get("longName") or ticker_symbol
    data["Company Name"] = str(c_name).strip()
    data["Market Cap"] = info.get("marketCap") or (getattr(fast, "market_cap", None) if fast else "N/A") or "N/A"
    data["Trailing P/E"] = info.get("trailingPE") or info.get("trailingPe") or "N/A"
    data["Forward P/E"] = info.get("forwardPE") or info.get("forwardPe") or "N/A"
    data["EPS (TTM)"] = info.get("trailingEps") or "N/A"
    data["Target Price"] = info.get("targetMeanPrice") or "N/A"
    data["52W High"] = info.get("fiftyTwoWeekHigh") or (getattr(fast, "year_high", None) if fast else "N/A") or "N/A"
    data["52W Low"] = info.get("fiftyTwoWeekLow") or (getattr(fast, "year_low", None) if fast else "N/A") or "N/A"
    data["Debt/Equity"] = info.get("debtToEquity", "N/A")
    data["Business Summary"] = info.get("longBusinessSummary", "No corporate overview provided.")
    try:
      h_max = t.history(period="max", interval="1mo")
      if h_max is not None and not h_max.empty:
        data["All-Time High"] = float(h_max["High"].max())
        data["All-Time Low"] = float(h_max["Low"].min())
    except Exception:
      pass
    e_map = fetch_upcoming_earnings_map([ticker_symbol])
    if ticker_symbol in e_map:
      d_left, d_str = e_map[ticker_symbol]
      data["Earnings Date"] = f"{d_str} (in {d_left}d)"
  except Exception:
    pass
  return data

def render_sparkline(prices, is_positive):
  fig = go.Figure(go.Scatter(y=prices, mode='lines', line=dict(color="#15803d" if is_positive else "#b91c1c", width=1.8)))
  fig.update_layout(height=45, width=120, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
  return fig

def _render_news_box(articles, show_ticker=True):
  items_html = []
  for a in articles:
    t_badge = f'<span class="ticker-news-badge">[{a.get("ticker", "NEWS")}]</span> ' if show_ticker else ''
    items_html.append(
      f'<div style="background:white;border:1px solid #e7e2d9;border-radius:8px;padding:12px 16px;margin-bottom:8px;">'
      f'<div style="display:flex;justify-content:space-between;font-size:0.72rem;color:#71717a;">'
      f'<span style="font-weight:600;color:#0f291e;">{t_badge}{a["publisher"]}'
      f'<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div>'
      f'<div style="font-weight:600;font-size:0.92rem;margin-top:4px;">'
      f'<a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">'
      f'{a["title"]}</a></div></div>'
    )
  st.markdown('<div class="scroll-news-box">' + "".join(items_html) + '</div>', unsafe_allow_html=True)

def render_watchlist_reorder_panel(folder_name, key_prefix="wl"):
  st.markdown('<div style="background:#ffffff;border:1px solid #dcd6cb;border-radius:8px;padding:12px 16px;margin-bottom:12px;">', unsafe_allow_html=True)
  c_top1, c_top2, c_top3 = st.columns([2.2, 2.2, 1.6])
  with c_top1:
    st.markdown(f"**Editing Watchlist: `{folder_name}`**")
    st.caption("Tap Top, Up, Dn, or Del to arrange your exact order.")
  with c_top2:
    new_list_name = st.text_input("Create New Watchlist Folder", placeholder="e.g. AI & Semis", key=f"{key_prefix}_new_folder_in", label_visibility="collapsed")
    if st.button("Create New Watchlist", key=f"{key_prefix}_btn_new_folder") and new_list_name.strip():
      clean_name = new_list_name.strip()
      if clean_name not in watchlists:
        watchlists[clean_name] = []
        ok, msg = sync_file_to_github(watchlists, DATA_FILE)
        st.toast(msg)
        st.rerun()
  with c_top3:
    if st.button("Save & Sync Order to GitHub", type="primary", use_container_width=True, key=f"{key_prefix}_sync_gh"):
      ok, msg = sync_file_to_github(watchlists, DATA_FILE)
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
      with (e_col1 if i < half else e_col2):
        r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
        r1.markdown(f"**{i+1}. {s}**")
        if r2.button("Top", key=f"{key_prefix}_top_{folder_name}_{s}_{i}", disabled=(i == 0)):
          syms.pop(i); syms.insert(0, s); save_json(DATA_FILE, watchlists); st.rerun()
        if r3.button("Up", key=f"{key_prefix}_up_{folder_name}_{s}_{i}", disabled=(i == 0)):
          syms[i - 1], syms[i] = syms[i], syms[i - 1]; save_json(DATA_FILE, watchlists); st.rerun()
        if r4.button("Dn", key=f"{key_prefix}_dn_{folder_name}_{s}_{i}", disabled=(i == len(syms) - 1)):
          syms[i + 1], syms[i] = syms[i], syms[i + 1]; save_json(DATA_FILE, watchlists); st.rerun()
        if r5.button("Del", key=f"{key_prefix}_del_{folder_name}_{s}_{i}"):
          syms.pop(i); sync_file_to_github(watchlists, DATA_FILE); st.rerun()
  st.markdown('</div>', unsafe_allow_html=True)

def log_ledger_entry(action_type, ticker, shares, buy_price, sell_price, pnl_dollar, pnl_pct, stop_loss, remarks, dt_str=None):
  entry = {
    "Date": dt_str or datetime.now().strftime("%Y-%m-%d"),
    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "Action": action_type,
    "Ticker": ticker,
    "Shares": int(shares),
    "BuyPrice": round(float(buy_price), 4),
    "SellPrice": round(float(sell_price), 4) if sell_price is not None else None,
    "Gain_Loss_USD": round(float(pnl_dollar), 2) if pnl_dollar is not None else 0.0,
    "Gain_Loss_Pct": round(float(pnl_pct), 2) if pnl_pct is not None else 0.0,
    "StopLoss": round(float(stop_loss), 4) if stop_loss is not None else 0.0,
    "Remarks": str(remarks or "").strip()
  }
  trade_ledger.append(entry)
  sync_file_to_github(trade_ledger, LEDGER_FILE)

def render_active_positions_manager(key_prefix="ap"):
  st.markdown("<h1>Active Portfolio & Trade Ledger</h1>", unsafe_allow_html=True)
  pos_syms = [p["Ticker"] for p in positions]
  data_dict = fetch_batch_market_data(pos_syms, account_size=settings["account_size"]) if pos_syms else {}
  tot_invested = sum(p["Shares"] * p["BuyPrice"] for p in positions)
  tot_value = sum(p["Shares"] * data_dict.get(p["Ticker"], {}).get("Price", p["BuyPrice"]) for p in positions)
  daily_pnl = sum(p["Shares"] * data_dict.get(p["Ticker"], {}).get("Change", 0.0) for p in positions)
  prev_port_val = tot_value - daily_pnl
  daily_pct = (daily_pnl / prev_port_val * 100.0) if prev_port_val > 0 else 0.0
  unreal_pnl = tot_value - tot_invested
  unreal_pct = (unreal_pnl / tot_invested * 100.0) if tot_invested > 0 else 0.0
  realized_total = sum(float(x.get("Gain_Loss_USD", 0.0)) for x in trade_ledger if x.get("Action") in ("SELL PARTIAL", "CLOSE"))
  m1, m2, m3, m4, m5 = st.columns(5)
  m1.metric("Total Invested Cost", f"${tot_invested:,.2f}")
  m2.metric("Current Market Value", f"${tot_value:,.2f}")
  m3.metric("Today's Daily Gain/Loss", f"${daily_pnl:+,.2f}", f"{daily_pct:+.2f}%")
  m4.metric("Unrealized P&L", f"${unreal_pnl:+,.2f}", f"{unreal_pct:+.2f}%")
  m5.metric("Closed Realized P&L", f"${realized_total:+,.2f}")
  with st.expander("Log a New Position (With Remarks / Trade Thesis)", expanded=not bool(positions)):
    c_in1, c_in2, c_in3, c_in4, c_in5 = st.columns([1.2, 1.2, 1.1, 1.3, 1.2])
    new_pos_sym = c_in1.text_input("Ticker", placeholder="e.g. NVDA", key=f"{key_prefix}_nsym").upper().strip()
    new_pos_px = c_in2.number_input("Buy Price ($)", min_value=0.01, value=100.0, step=1.0, key=f"{key_prefix}_npx")
    new_pos_shs = c_in3.number_input("Shares", min_value=1, value=100, step=10, key=f"{key_prefix}_nshs")
    new_pos_stop = c_in4.number_input("Initial Stop ($)", min_value=0.01, value=round(new_pos_px * 0.92, 2), step=0.5, key=f"{key_prefix}_nstp")
    new_pos_dt = c_in5.date_input("Buy Date", key=f"{key_prefix}_ndt")
    c_rmk, c_btn = st.columns([4.2, 1.2])
    new_pos_rmk = c_rmk.text_input(
      "Remarks / Why I Bought This Trade",
      placeholder="e.g. Stage 2 Higher Low bounce off rising 20-EMA, strong RVOL",
      key=f"{key_prefix}_nrmk"
    )
    if c_btn.button("Save Trade", type="primary", use_container_width=True, key=f"{key_prefix}_nsave"):
      if new_pos_sym:
        dt_s = new_pos_dt.strftime("%Y-%m-%d")
        new_trade = {
          "id": f"{new_pos_sym}_{int(time.time())}",
          "Ticker": new_pos_sym,
          "BuyPrice": float(new_pos_px),
          "Shares": int(new_pos_shs),
          "BuyDate": dt_s,
          "StopLoss": float(new_pos_stop),
          "Target15": float(new_pos_px) * 1.15,
          "HalfSold": False,
          "Remarks": new_pos_rmk.strip()
        }
        positions.append(new_trade)
        sync_file_to_github(positions, POSITIONS_FILE)
        log_ledger_entry("BUY", new_pos_sym, new_pos_shs, new_pos_px, None, 0.0, 0.0, new_pos_stop, new_pos_rmk, dt_str=dt_s)
        if new_pos_sym not in watchlists["Active Positions"]:
          watchlists["Active Positions"].append(new_pos_sym)
          sync_file_to_github(watchlists, DATA_FILE)
        st.success(f"Logged {new_pos_shs} shs of {new_pos_sym} @ ${new_pos_px:,.2f}!")
        st.rerun()
  st.markdown("---")
  if positions:
    for idx, p in enumerate(positions):
      sym = p["Ticker"]
      bp = float(p["BuyPrice"])
      shares = int(p["Shares"])
      live_price = float(data_dict.get(sym, {}).get("Price", bp))
      day_chg = float(data_dict.get(sym, {}).get("Change", 0.0))
      day_pct = float(data_dict.get(sym, {}).get("Change_Pct", 0.0))
      ema20 = float(data_dict.get(sym, {}).get("EMA20_Val", bp))
      pos_day_pnl = day_chg * shares
      pnl = (live_price - bp) * shares
      pnl_pct = ((live_price - bp) / bp) * 100.0 if bp > 0 else 0.0
      clr_pnl = "#15803d" if pnl >= 0 else "#b91c1c"
      clr_day = "#15803d" if pos_day_pnl >= 0 else "#b91c1c"
      rmk_str = p.get("Remarks", "") or "No remarks recorded."
      c_p1, c_p2, c_p3 = st.columns([1.5, 4.6, 1.9])
      with c_p1:
        st.markdown(
          f"**<a href='?inspect={sym}' target='_self' class='ticker-link'>{sym}</a>**<br>"
          f"<span style='font-size:1.35rem;font-weight:800;'>${live_price:,.2f}</span> "
          f"<span style='font-size:0.82rem;color:{clr_day};font-weight:700;'>({day_pct:+.2f}%)</span><br>"
          f"<span style='font-size:0.76rem;color:#64748b;'>Bought: {p.get('BuyDate', 'N/A')}</span>",
          unsafe_allow_html=True
        )
      with c_p2:
        st.markdown(
          f"<div style='display:flex;justify-content:space-between;padding:8px 12px;background:#f8f9fa;border-radius:8px;border:1px solid #e2e8f0;'>"
          f"<div><span style='font-size:0.73rem;color:#64748b;'>Avg Cost & Size</span><br><b>${bp:,.2f}</b> <span style='font-size:0.78rem;'>({shares} shs)</span></div>"
          f"<div><span style='font-size:0.73rem;color:#64748b;'>Stop-Loss</span><br><b style='color:#dc2626;'>${p['StopLoss']:,.2f}</b></div>"
          f"<div><span style='font-size:0.73rem;color:#64748b;'>+15% Target</span><br><b style='color:#059669;'>${p['Target15']:,.2f}</b></div>"
          f"<div><span style='font-size:0.73rem;color:#64748b;'>Today's Gain</span><br><b style='color:{clr_day};'>${pos_day_pnl:+,.2f}</b></div>"
          f"<div><span style='font-size:0.73rem;color:#64748b;'>Unrealized P&L</span><br><b style='color:{clr_pnl};'>${pnl:+,.2f} ({pnl_pct:+.2f}%)</b></div>"
          f"</div>"
          f"<div style='font-size:0.80rem;color:#334155;margin-top:5px;'><b>Thesis / Remarks:</b> <i>{rmk_str}</i> · <b>20-EMA:</b> ${ema20:,.2f}</div>",
          unsafe_allow_html=True
        )
        if live_price <= p["StopLoss"]:
          st.error(f"STOP-LOSS HIT: {sym} (${live_price:,.2f}) is at/below your stop (${p['StopLoss']:,.2f})!")
        elif live_price >= p["Target15"] and not p.get("HalfSold", False):
          st.warning(f"+15% Target Reached! Open 'Manage Trade' to Sell 50% ({max(1, shares//2)} shs), Hold & Lock Profit Stop, or Pyramid.")
        elif live_price < ema20:
          st.error(f"Trailing Warning: {sym} dropped below its 20-day EMA (${ema20:,.2f}).")
      with c_p3:
        with st.popover("Manage Trade", use_container_width=True):
          st.markdown(f"**Manage `{sym}` ({shares} shs @ ${bp:,.2f})**")
          t_sell, t_trail, t_add, t_close = st.tabs(["Sell/Trim", "Trail Stop", "Add Batch", "Note/Close"])
          with t_sell:
            st.caption("Sell a portion (e.g. 50%) to lock in gains & auto-raise your stop-loss.")
            sell_shs = st.number_input("Shares to Sell", min_value=1, max_value=max(1, shares), value=max(1, shares // 2), key=f"{key_prefix}_sshs_{p['id']}")
            sell_px = st.number_input("Sell Price ($)", min_value=0.01, value=float(round(live_price, 2)), step=0.5, key=f"{key_prefix}_spx_{p['id']}")
            stop_rule_after_sell = st.selectbox(
              "Auto-Raise Stop on Remaining Shares",
              [
                f"Breakeven Cost (${bp:,.2f})",
                f"Lock +5% Gain (${bp * 1.05:,.2f})",
                f"20-Day EMA (${ema20:,.2f})",
                f"Keep Current Stop (${p['StopLoss']:,.2f})"
              ],
              key=f"{key_prefix}_srule_{p['id']}"
            )
            sell_rmk = st.text_input("Trim Note", value=f"Sold {sell_shs} shs @ ${sell_px:,.2f}; raised stop", key=f"{key_prefix}_srmk_{p['id']}")
            if st.button("Execute Partial Sale & Raise Stop", type="primary", use_container_width=True, key=f"{key_prefix}_sbtn_{p['id']}"):
              realized_d = (sell_px - bp) * sell_shs
              realized_p = ((sell_px - bp) / bp) * 100.0 if bp > 0 else 0.0
              if stop_rule_after_sell.startswith("Breakeven"):
                new_st = bp
              elif stop_rule_after_sell.startswith("Lock +5%"):
                new_st = bp * 1.05
              elif stop_rule_after_sell.startswith("20-Day EMA"):
                new_st = ema20
              else:
                new_st = float(p["StopLoss"])
              rem_shs = shares - sell_shs
              log_ledger_entry("SELL PARTIAL", sym, sell_shs, bp, sell_px, realized_d, realized_p, new_st, sell_rmk)
              if rem_shs <= 0:
                positions.pop(idx)
              else:
                positions[idx]["Shares"] = rem_shs
                positions[idx]["HalfSold"] = True
                positions[idx]["StopLoss"] = round(float(new_st), 2)
                positions[idx]["Remarks"] = f"{rmk_str} | {sell_rmk}".strip(" |")
              sync_file_to_github(positions, POSITIONS_FILE)
              st.rerun()
          with t_trail:
            st.caption("Hold your shares when momentum is strong & auto-ratchet your stop-loss.")
            trail_mode = st.radio(
              "Select Profit-Protection Stop Rule",
              [
                f"Breakeven Cost (${bp:,.2f})",
                f"Lock +5% Gain (${bp * 1.05:,.2f})",
                f"Lock +10% Gain (${bp * 1.10:,.2f})",
                f"Trail 20-Day EMA (${ema20:,.2f})",
                f"Trail 8% Below Live Price (${live_price * 0.92:,.2f})",
                "Custom Stop Price ($)"
              ],
              key=f"{key_prefix}_tmode_{p['id']}"
            )
            custom_st = st.number_input("Custom Stop ($)", min_value=0.01, value=float(round(p["StopLoss"], 2)), step=0.5, key=f"{key_prefix}_tcust_{p['id']}")
            if st.button("Update Stop-Loss & Arm Alert", type="primary", use_container_width=True, key=f"{key_prefix}_tbtn_{p['id']}"):
              if trail_mode.startswith("Breakeven"):
                chosen_st = bp
              elif trail_mode.startswith("Lock +5%"):
                chosen_st = bp * 1.05
              elif trail_mode.startswith("Lock +10%"):
                chosen_st = bp * 1.10
              elif trail_mode.startswith("Trail 20-Day"):
                chosen_st = ema20
              elif trail_mode.startswith("Trail 8%"):
                chosen_st = live_price * 0.92
              else:
                chosen_st = custom_st
              positions[idx]["StopLoss"] = round(float(chosen_st), 2)
              sync_file_to_github(positions, POSITIONS_FILE)
              st.rerun()
          with t_add:
            st.caption("Add another batch (Pyramid) & auto-recalculate blended cost and stop-loss.")
            add_shs = st.number_input("Added Shares", min_value=1, value=max(10, shares // 2), step=5, key=f"{key_prefix}_ashs_{p['id']}")
            add_px = st.number_input("Add Buy Price ($)", min_value=0.01, value=float(round(live_price, 2)), step=0.5, key=f"{key_prefix}_apx_{p['id']}")
            new_tot_shs = shares + add_shs
            new_avg_bp = ((shares * bp) + (add_shs * add_px)) / new_tot_shs
            st.info(f"**New Blended Cost:** `${new_avg_bp:,.2f}` ({new_tot_shs} total shs)")
            add_stop_rule = st.selectbox(
              "Auto-Recalculate Stop for Combined Position",
              [
                f"New Blended Breakeven (${new_avg_bp:,.2f})",
                f"20-Day EMA Support (${ema20:,.2f})",
                f"5% Below New Blended Cost (${new_avg_bp * 0.95:,.2f})",
                f"8% Below Add Price (${add_px * 0.92:,.2f})"
              ],
              key=f"{key_prefix}_arule_{p['id']}"
            )
            add_rmk = st.text_input("Add Batch Note", value=f"Added {add_shs} shs @ ${add_px:,.2f}", key=f"{key_prefix}_armk_{p['id']}")
            if st.button("Confirm Add & Recalculate Stop", type="primary", use_container_width=True, key=f"{key_prefix}_abtn_{p['id']}"):
              if add_stop_rule.startswith("New Blended"):
                calc_st = new_avg_bp
              elif add_stop_rule.startswith("20-Day EMA"):
                calc_st = ema20
              elif add_stop_rule.startswith("5% Below"):
                calc_st = new_avg_bp * 0.95
              else:
                calc_st = add_px * 0.92
              positions[idx]["Shares"] = int(new_tot_shs)
              positions[idx]["BuyPrice"] = round(float(new_avg_bp), 4)
              positions[idx]["StopLoss"] = round(float(calc_st), 2)
              positions[idx]["Target15"] = round(float(new_avg_bp * 1.15), 2)
              positions[idx]["Remarks"] = f"{rmk_str} | {add_rmk}".strip(" |")
              sync_file_to_github(positions, POSITIONS_FILE)
              log_ledger_entry("ADD", sym, add_shs, add_px, None, 0.0, 0.0, calc_st, add_rmk)
              st.rerun()
          with t_close:
            upd_rmk = st.text_input("Edit Trade Remarks / Thesis", value=rmk_str, key=f"{key_prefix}_urmk_{p['id']}")
            if st.button("Save Remarks", use_container_width=True, key=f"{key_prefix}_srmk_btn_{p['id']}"):
              positions[idx]["Remarks"] = upd_rmk.strip()
              sync_file_to_github(positions, POSITIONS_FILE)
              st.rerun()
            st.markdown("---")
            exit_px = st.number_input("Full Exit Sell Price ($)", min_value=0.01, value=float(round(live_price, 2)), step=0.5, key=f"{key_prefix}_xpx_{p['id']}")
            exit_rmk = st.text_input("Exit Remarks / Lesson", value="Closed full position", key=f"{key_prefix}_xrmk_{p['id']}")
            if st.button("Close Full Position & Log to Ledger", type="primary", use_container_width=True, key=f"{key_prefix}_xbtn_{p['id']}"):
              realized_d = (exit_px - bp) * shares
              realized_p = ((exit_px - bp) / bp) * 100.0 if bp > 0 else 0.0
              log_ledger_entry("CLOSE", sym, shares, bp, exit_px, realized_d, realized_p, p["StopLoss"], f"{rmk_str} | {exit_rmk}".strip(" |"))
              positions.pop(idx)
              sync_file_to_github(positions, POSITIONS_FILE)
              st.rerun()
            if st.button("Delete Without Logging", use_container_width=True, key=f"{key_prefix}_del_{p['id']}"):
              positions.pop(idx)
              sync_file_to_github(positions, POSITIONS_FILE)
              st.rerun()
      st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
  else:
    st.info("No active positions currently open. Use 'Log a New Position' above to start tracking.")
  st.markdown("### Complete Trade Ledger & Excel Export")
  lc1, lc2, lc3 = st.columns([1.4, 1.4, 2.2])
  default_start = datetime(2025, 1, 1).date()
  default_end = datetime.now().date()
  from_dt = lc1.date_input("From Date", value=default_start, key=f"{key_prefix}_lfrom")
  to_dt = lc2.date_input("To Date", value=default_end, key=f"{key_prefix}_lto")
  ledger_filter = lc3.selectbox(
    "Filter Ledger View",
    ["All Records (Open Positions + Closed/Historical)", "Open Positions Only", "Closed & Partial Sales Only", "Buys & Adds Only"],
    key=f"{key_prefix}_lflt"
  )
  combined_rows = []
  from_str, to_str = from_dt.strftime("%Y-%m-%d"), to_dt.strftime("%Y-%m-%d")
  if ledger_filter in ("All Records (Open Positions + Closed/Historical)", "Open Positions Only"):
    for p in positions:
      b_dt = str(p.get("BuyDate", datetime.now().strftime("%Y-%m-%d")))[:10]
      if from_str <= b_dt <= to_str:
        sym = p["Ticker"]
        bp = float(p["BuyPrice"])
        shs = int(p["Shares"])
        lv_px = float(data_dict.get(sym, {}).get("Price", bp))
        u_pnl = (lv_px - bp) * shs
        u_pct = ((lv_px - bp) / bp) * 100.0 if bp > 0 else 0.0
        combined_rows.append({
          "Date": b_dt,
          "Status / Action": "OPEN POSITION",
          "Ticker": sym,
          "Shares": shs,
          "Buy Price ($)": round(bp, 2),
          "Sell / Live Price ($)": round(lv_px, 2),
          "Gain / Loss ($)": round(u_pnl, 2),
          "Gain / Loss (%)": round(u_pct, 2),
          "Stop-Loss ($)": round(float(p.get("StopLoss", 0.0)), 2),
          "Remarks / Thesis": p.get("Remarks", "")
        })
  if ledger_filter != "Open Positions Only":
    for entry in reversed(trade_ledger):
      e_dt = str(entry.get("Date", ""))[:10]
      act = entry.get("Action", "BUY")
      if not (from_str <= e_dt <= to_str):
        continue
      if ledger_filter == "Closed & Partial Sales Only" and act not in ("SELL PARTIAL", "CLOSE"):
        continue
      if ledger_filter == "Buys & Adds Only" and act not in ("BUY", "ADD"):
        continue
      combined_rows.append({
        "Date": e_dt,
        "Status / Action": act,
        "Ticker": entry.get("Ticker", ""),
        "Shares": int(entry.get("Shares", 0)),
        "Buy Price ($)": round(float(entry.get("BuyPrice", 0.0)), 2),
        "Sell / Live Price ($)": round(float(entry["SellPrice"]), 2) if entry.get("SellPrice") is not None else round(float(entry.get("BuyPrice", 0.0)), 2),
        "Gain / Loss ($)": round(float(entry.get("Gain_Loss_USD", 0.0)), 2),
        "Gain / Loss (%)": round(float(entry.get("Gain_Loss_Pct", 0.0)), 2),
        "Stop-Loss ($)": round(float(entry.get("StopLoss", 0.0)), 2),
        "Remarks / Thesis": entry.get("Remarks", "")
      })
  if combined_rows:
    df_ledger = pd.DataFrame(combined_rows)
    st.dataframe(df_ledger, use_container_width=True, hide_index=True)
    tot_gl = df_ledger["Gain / Loss ($)"].sum()
    st.markdown(f"**Filtered Period Net Gain / Loss:** `${tot_gl:+,.2f}` across `{len(df_ledger)}` records.")
    dl_c1, dl_c2 = st.columns(2)
    try:
      excel_buf = io.BytesIO()
      with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
        df_ledger.to_excel(writer, sheet_name="Trade_Ledger", index=False)
        summary_df = pd.DataFrame([
          {"Metric": "Report Date Interval", "Value": f"{from_str} to {to_str}"},
          {"Metric": "Total Invested Cost (Open)", "Value": round(tot_invested, 2)},
          {"Metric": "Current Market Value (Open)", "Value": round(tot_value, 2)},
          {"Metric": "Today's Daily Portfolio Gain ($)", "Value": round(daily_pnl, 2)},
          {"Metric": "Total Unrealized P&L ($)", "Value": round(unreal_pnl, 2)},
          {"Metric": "Total Closed Realized P&L ($)", "Value": round(realized_total, 2)},
          {"Metric": "Combined Net P&L ($)", "Value": round(unreal_pnl + realized_total, 2)}
        ])
        summary_df.to_excel(writer, sheet_name="Portfolio_Summary", index=False)
      dl_c1.download_button(
        "Download Trade Ledger Excel (.xlsx)",
        data=excel_buf.getvalue(),
        file_name=f"trade_ledger_{from_str}_to_{to_str}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        type="primary",
        use_container_width=True,
        key=f"{key_prefix}_dl_xlsx"
      )
    except Exception:
      pass
    dl_c2.download_button(
      "Download Trade Ledger CSV (.csv)",
      data=df_ledger.to_csv(index=False).encode("utf-8"),
      file_name=f"trade_ledger_{from_str}_to_{to_str}.csv",
      mime="text/csv",
      use_container_width=True,
      key=f"{key_prefix}_dl_csv"
    )
  else:
    st.caption("No ledger entries found in the selected date range.")

@st.cache_data(ttl=1800)
def fetch_sds_latest_videos():
  videos = []
  rss_urls = [
    "https://www.youtube.com/feeds/videos.xml?channel_id=UCf2d3_2b7236-m62N-P4c3Q",
    "https://news.google.com/rss/search?q=%2290%E5%BE%8C%E5%89%B5%E6%A5%AD%E5%AE%B6%E6%8E%83%E5%9C%B0%E5%83%A7%22+site:youtube.com&hl=zh-HK&gl=HK&ceid=HK:zh-Hant"
  ]
  for u in rss_urls:
    try:
      req = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
      with urllib.request.urlopen(req, timeout=4.5) as resp:
        raw_xml = resp.read()
      root = ET.fromstring(raw_xml)
      ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
      entries = root.findall("atom:entry", ns)
      for ent in entries[:8]:
        t_el = ent.find("atom:title", ns)
        l_el = ent.find("atom:link", ns)
        p_el = ent.find("atom:published", ns)
        if t_el is not None and t_el.text:
          videos.append({
            "title": t_el.text.strip(),
            "link": l_el.attrib.get("href", "https://www.youtube.com/@sds.getrich") if l_el is not None else "https://www.youtube.com/@sds.getrich",
            "date": p_el.text[:10] if p_el is not None and p_el.text else "Recent"
          })
      if videos:
        break
    except Exception:
      continue
  if not videos:
    videos = [
      {"date": "2026-10-18", "title": "23-Hour US Trading & Stablecoin (USDT/USDC) Liquidity Siphon from Asian Markets", "link": "https://www.youtube.com/watch?v=XdN4xVmSNJ0"},
      {"date": "2026-08-16", "title": "Eurozone Crisis 2.0: Why Global Capital Is Fleeing Europe into US Treasuries & US Tech", "link": "https://www.youtube.com/watch?v=QzZPB7CLibw"},
      {"date": "2026-07-12", "title": "AI Debt & Private Credit Bubble: CoreWeave, Oracle & How to Ride the Wave with Trailing Stops", "link": "https://www.youtube.com/watch?v=Jod__0savaQ"},
      {"date": "2026-05-24", "title": "US Treasury Volatility & The Post-2008 Equity Melt-Up Playbook", "link": "https://www.youtube.com/watch?v=sJ-sz-QNbXc"}
    ]
  return videos

def get_gemini_api_key():
  try:
    if "GEMINI_API_KEY" in st.secrets:
      return str(st.secrets["GEMINI_API_KEY"]).strip()
  except Exception:
    pass
  return os.environ.get("GEMINI_API_KEY", "").strip() or str(settings.get("gemini_api_key", "")).strip()

def query_gemini_copilot(user_prompt, chat_history, portfolio_context):
  api_key = get_gemini_api_key()
  if not api_key:
    return "Please enter your **Gemini API Key** in the box above (or add `GEMINI_API_KEY` to your Streamlit Secrets) to activate live AI chat."
  url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
  sys_text = (
    "You are the user's personal AI Macro & Trading Co-Pilot embedded inside their Quality Momentum & Stage 2 Cockpit. "
    "Be direct, insightful, and practical. You have full knowledge of their live portfolio, watchlist signals, "
    "the 6-Phase Fed Interest Rate Cycle (Bull 1 Stop Cutting -> Bull 2 First Hike -> Bull 3 Hike Pause/Expansion -> Bear 1 First Cut), "
    "and the 3-month macro synthesis from @sds.getrich (1. AI capex & private-credit debt bubble in CoreWeave/Oracle; "
    "2. Eurozone Crisis 2.0 driving capital flight into USD assets; 3. Dec 2026 23-hour US trading & USDT/USDC stablecoins "
    "draining Asian liquidity into US stocks and T-bills; 4. Hit-and-run profit management: buying Stage 2 Higher Lows, "
    "selling 50% at +15%, and trailing stops).\n\n"
    f"LIVE DASHBOARD CONTEXT:\n{portfolio_context}"
  )
  contents = []
  for msg in chat_history[-8:]:
    role = "user" if msg["role"] == "user" else "model"
    contents.append({"role": role, "parts": [{"text": msg["content"]}]})
  contents.append({"role": "user", "parts": [{"text": user_prompt}]})
  payload = {
    "systemInstruction": {"parts": [{"text": sys_text}]},
    "contents": contents,
    "generationConfig": {"temperature": 0.4, "maxOutputTokens": 1200}
  }
  try:
    req = urllib.request.Request(
      url,
      data=json.dumps(payload).encode("utf-8"),
      headers={"Content-Type": "application/json"},
      method="POST"
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
      res_json = json.loads(resp.read().decode("utf-8"))
      return res_json["candidates"][0]["content"]["parts"][0]["text"]
  except Exception as e:
    return f"Gemini API Error: {str(e)[:180]}"

def render_ai_copilot_tab():
  st.markdown("<h1>AI Macro & Trade Co-Pilot</h1>", unsafe_allow_html=True)
  st.markdown(
    '<div style="background:#0f291e;color:#f4efe6;padding:12px 16px;border-radius:10px;margin-bottom:14px;">'
    '<div style="font-size:0.75rem;color:#c5a059;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;">'
    'INTEREST RATE CYCLE POSITION (BULL 1-2-3 / BEAR 1-2-3 FRAMEWORK)</div>'
    '<div style="font-size:0.95rem;font-weight:700;margin-top:4px;">'
    'Bull 1 (Stop Cutting: ON) Bull 2 (First HikeShakeout: OFF) '
    '<span style="background:#15803d;color:#fff;padding:2px 8px;border-radius:4px;">'
    'CURRENT: Late Bull 2 / Early Bull 3 (Hike Pause · Expansion Wave ON)</span> '
    'Bear 1 (First Rate Cut: OFF)</div>'
    '<div style="font-size:0.80rem;color:#cbd5e1;margin-top:6px;">'
    '<b>Playbook Alignment:</b> Following the Sept 2026 hike and Oct 2026 Fed pause, the market is transitioning from Bull 2 digestion into the Bull 3 expansion wave. '
    'Focus on <b>Stage 2 Higher Lows</b> in liquid US leaders & hard assets, scale out 50% on +15% surges, and trail stops above the 20-EMA.'
    '</div></div>',
    unsafe_allow_html=True
  )
  col_macro, col_chat = st.columns([1.15, 1.35])
  with col_macro:
    st.subheader("Sunday 8:30 PM HKT Macro Briefing")
    if st.button("Refresh Latest Sunday Video Feed", use_container_width=True):
      fetch_sds_latest_videos.clear()
      st.rerun()
    vids = fetch_sds_latest_videos()
    for v in vids[:5]:
      st.markdown(
        f'<div style="background:white;border:1px solid #e7e2d9;border-radius:8px;padding:8px 12px;margin-bottom:6px;font-size:0.84rem;">'
        f'<span class="age-badge" style="margin-left:0;margin-right:6px;">{v["date"]}</span>'
        f'<a href="{v["link"]}" target="_blank" style="color:#0f291e;font-weight:700;text-decoration:none;">{v["title"]}</a></div>',
        unsafe_allow_html=True
      )
    st.markdown("#### 3-Month Macro Thesis Synthesis")
    with st.expander("1. AI Capex & Private-Credit Debt Bubble (CoreWeave / Oracle)", expanded=True):
      st.write(
        "Unlike the 2000 dot-com equity bubble, Big Tech is locked in a Game Theory prisoner's dilemma—burning free cash flow on GPUs while AI data-center landlords (CoreWeave, Oracle) borrow at 10%–15% high-yield rates packaged into pension/insurance products. Watch credit spreads and debt rollovers, and never hold blindly without a trailing stop."
      )
    with st.expander("2. Eurozone Crisis 2.0 & Capital Flight to USD Assets", expanded=False):
      st.write(
        "Europe holds $8T in USD assets and pays €260B+/yr to US cloud/AI giants while facing high energy costs and sovereign debt strain (Italy/France). Pressure on the Euro forces global capital to flee into US Treasuries and US stocks—repeating the 2009–2010 Eurozone crisis rally."
      )
    with st.expander("3. Dec 2026 23-Hour US Trading & Stablecoin Liquidity Siphon", expanded=False):
      st.write(
        "23-hour US trading removes the Asian time-zone barrier, draining retail liquidity from Asian exchanges and shifting pricing power to US hours. As Asian investors use USD stablecoins (USDT/USDC) to buy US stocks, reserve laws force 1:1 US Treasury bill purchases—absorbing US debt while fueling US equity leaders."
      )
    st.markdown("**Quick Macro & Portfolio Prompts:**")
    qp1, qp2 = st.columns(2)
    prompt_to_send = None
    if qp1.button("Review My Open Positions", use_container_width=True):
      prompt_to_send = "Review my current active positions, unrealized P&L, and stop-losses. Which positions need stop adjustments or partial profit-taking right now?"
    if qp2.button("Macro & Bull 2/3 Strategy", use_container_width=True):
      prompt_to_send = "How should I position my portfolio right now given the Bull 2 to Bull 3 rate-cycle transition, the AI debt cycle, and 23-hour US trading liquidity flows?"
  with col_chat:
    st.subheader("Gemini Co-Pilot Chat")
    curr_key = get_gemini_api_key()
    with st.expander("Gemini API Key Settings" if curr_key else "Enter Gemini API Key to Enable Chat", expanded=not bool(curr_key)):
      in_key = st.text_input("Gemini API Key (from Google AI Studio)", value=curr_key, type="password", key="gem_key_in")
      if st.button("Save API Key", key="save_gem_key"):
        settings["gemini_api_key"] = in_key.strip()
        save_json(SETTINGS_FILE, settings)
        st.success("API Key saved!")
        st.rerun()
    pos_summary = []
    for p in positions:
      pos_summary.append(f"{p['Ticker']}: {p['Shares']} shs @ ${p['BuyPrice']:.2f}, Stop ${p['StopLoss']:.2f}, Remarks: {p.get('Remarks', '')}")
    port_ctx = "Active Positions: " + ("; ".join(pos_summary) if pos_summary else "None open.")
    chat_box = st.container(height=420)
    with chat_box:
      if not st.session_state.chat_messages:
        st.info("Ask me anything about your Active Positions, Watchlist setups, the Bull 1-2-3 / Bear 1-2-3 rate cycle, or the Sunday macro thesis!")
      for m in st.session_state.chat_messages:
        with st.chat_message(m["role"]):
          st.markdown(m["content"])
    user_q = st.chat_input("Ask about stocks, your portfolio stops, or macroeconomy...")
    active_prompt = prompt_to_send or user_q
    if active_prompt:
      st.session_state.chat_messages.append({"role": "user", "content": active_prompt})
      reply = query_gemini_copilot(active_prompt, st.session_state.chat_messages[:-1], port_ctx)
      st.session_state.chat_messages.append({"role": "assistant", "content": reply})
      st.rerun()
    if st.session_state.chat_messages:
      if st.button("Clear Chat History", key="clr_chat_btn"):
        st.session_state.chat_messages = []
        st.rerun()
MACRO_SYMBOLS = {
  "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
  "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
  "DXY (USD)": "DX-Y.NYB", "USD/JPY": "JPY=X", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"
}

@st.cache_data(ttl=300)
def fetch_macro_and_regime():
  ticks = list(MACRO_SYMBOLS.values())
  out = {}
  regime = {"label": "MARKET REGIME: BULLISH — S&P 500 Holding Trend · Favorable for New Setups", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
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
        regime = {"label": f"MARKET REGIME: BULLISH (S&P 500 Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for TCT, Swing & Momentum Buys", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
      elif sp_c < sp_ema50 or vix_c >= 25.0:
        regime = {"label": f"MARKET REGIME: RISK-OFF / CORRECTION (S&P Below 50 EMA or VIX Elevated at {vix_c:.1f}) — Protect Capital, Avoid Aggressive New Buys", "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"}
      else:
        regime = {"label": f"MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating · VIX {vix_c:.1f}) — Be Selective, Focus on 20-EMA Pullbacks & True TCT Bottoms", "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"}
  except Exception:
    pass
  return out, regime
st.sidebar.markdown(
  '<div style="padding:10px 0 20px 0;">'
  '<span style="display:inline-block;width:9px;height:9px;background:#22c55e;'
  'border-radius:50%;margin-right:6px;"></span>'
  '<span style="font-size:0.85rem;font-weight:600;letter-spacing:0.05em;color:#a1a1aa;">'
  'MULTI-PLAYBOOK LIVE ENGINE</span>'
  '<h2 style="color:#f4efe6 !important;margin:6px 0 0 0;font-size:1.4rem;">Ledger</h2>'
  '<span style="font-size:0.75rem;color:#c5a059;text-transform:uppercase;'
  'letter-spacing:0.1em;font-weight:600;">Momentum · Stage 2 · TCT v11.2</span></div>',
  unsafe_allow_html=True
)
navigation = st.sidebar.radio(
  "Navigation",
  [
    "Dashboard",
    "Active Positions",
    "Live Real-Time Quotes",
    "Screener",
    "Watchlist",
    "Precious Metals, Crypto & Currency",
    "AI Macro & Trade Co-Pilot",
    "News & Earnings",
    "Settings"
  ],
  key="nav_radio", label_visibility="collapsed", on_change=clear_inspection
)
st.sidebar.markdown("---")
sync_badge = "GitHub Auto-Sync Active" if get_github_token() else "Local Mode (Add GITHUB_TOKEN)"
st.sidebar.markdown(f"""<div style="position:fixed;bottom:18px;font-size:0.74rem;color:#a1a1aa;">{sync_badge}<br>Tap any <b>Stock Symbol</b> to open chart</div>""", unsafe_allow_html=True)

if navigation != "Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
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
    f'color:{regime_info["color"]}; padding:8px 14px; border-radius:8px; '
    f'font-size:0.82rem; font-weight:600; margin-bottom:16px;">{regime_info["label"]}</div>',
    unsafe_allow_html=True
  )

if st.session_state.inspect_symbol is not None:
  sym = st.session_state.inspect_symbol
  funds = fetch_ticker_fundamentals(sym)
  comp_name = funds.get("Company Name", sym)
  header_label = f"{sym} - {comp_name}" if comp_name and comp_name.upper() != sym.upper() else sym
  col_back, col_title = st.columns([1.2, 8.8])
  with col_back:
    if st.button("Back", type="primary"):
      clear_inspection()
      st.rerun()
  with col_title:
    st.markdown(f"<h1>{header_label}</h1>", unsafe_allow_html=True)
  c_ctrl, c_plot = st.columns([1.15, 3.85])
  with c_ctrl:
    st.markdown("### Chart Timeframe")
    chart_period = st.selectbox(
      "History Interval",
      ["6mo", "1y", "2y", "3y", "5y", "10y", "max"],
      index=4,
      format_func=lambda x: {
        "6mo": "6 Months",
        "1y": "1 Year",
        "2y": "2 Years",
        "3y": "3 Years",
        "5y": "5 Years (Default)",
        "10y": "10 Years",
        "max": "All-Time (Max)"
      }[x]
    )
    chart_bar_interval = st.radio(
      "Candle Bar Size",
      ["1d", "1wk"],
      index=0,
      format_func=lambda x: "Daily Bars (1D)" if x == "1d" else "Weekly Bars (1W)",
      horizontal=True
    )
    st.markdown("### Chart Overlays")
    show_tct_lines = st.checkbox("Target / Buy / Stop Lines", value=True)
    show_ema20 = st.checkbox("EMA 20 (Gold)", value=True)
    show_ema50 = st.checkbox("EMA 50 (Green)", value=True)
    show_ma150 = st.checkbox("150 Moving Average (Teal)", value=True)
    ma150_type = st.radio("150 MA Mode", ["SMA 150", "EMA 150"], index=0, horizontal=True, label_visibility="collapsed")
    show_ema200 = st.checkbox("EMA 200 (Purple)", value=False)
    show_bb = st.checkbox("Bollinger Bands (20, 2)", value=False)
  d = fetch_single_ticker_data(sym, account_size=settings["account_size"], period=chart_period, interval=chart_bar_interval)
  if d is not None:
    df_hist = d["History"]
    if "EMA150" not in df_hist.columns:
      df_hist["EMA150"] = df_hist["Close"].ewm(span=150, adjust=False).mean()
    if "SMA150" not in df_hist.columns:
      df_hist["SMA150"] = df_hist["Close"].rolling(150, min_periods=1).mean()
    raw_mcap = funds.get("Market Cap")
    mcap_text = f"${raw_mcap/1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"
    ma150_val = float(df_hist["SMA150"].iloc[-1]) if ma150_type == "SMA 150" else float(df_hist["EMA150"].iloc[-1])
    t_pe = funds.get("Trailing P/E", "N/A")
    f_pe = funds.get("Forward P/E", "N/A")
    pe_text = f"{t_pe:.1f}" if isinstance(t_pe, (int, float)) else str(t_pe)
    fpe_text = f"{f_pe:.1f}" if isinstance(f_pe, (int, float)) else str(f_pe)
    raw_tgt = funds.get("Target Price", "N/A")
    if isinstance(raw_tgt, (int, float)) and raw_tgt > 0:
      tgt_upside = ((raw_tgt - d["Price"]) / d["Price"]) * 100.0
      analyst_tgt_text = f"${raw_tgt:,.2f} ({tgt_upside:+.1f}%)"
    else:
      analyst_tgt_text = "N/A"
    w52_h = funds.get("52W High", "N/A")
    w52_l = funds.get("52W Low", "N/A")
    w52_text = (
      f"${w52_h:,.2f} / ${w52_l:,.2f}"
      if isinstance(w52_h, (int, float)) and isinstance(w52_l, (int, float))
      else f"{w52_h} / {w52_l}"
    )
    ath_raw = funds.get("All-Time High")
    atl_raw = funds.get("All-Time Low")
    ath_val = max(float(df_hist["High"].max()), float(ath_raw) if isinstance(ath_raw, (int, float)) else 0.0)
    atl_val = min(float(df_hist["Low"].min()), float(atl_raw) if isinstance(atl_raw, (int, float)) and atl_raw > 0 else float(df_hist["Low"].min()))
    hist_hl_text = f"${ath_val:,.2f} / ${atl_val:,.2f}"
    earn_text = funds.get("Earnings Date", "No upcoming (60d)")
    with c_ctrl:
      st.markdown("---")
      st.markdown("### Action Trade Ticket")
      st.markdown(f"**Playbook:** `{d['TCT_Model']}`")
      st.markdown(f"**Action:** `{d['TCT_Action']}`")
      st.markdown(f"**Buy Trigger:** `${d['BOS_Level']:,.2f}`")
      st.markdown(f"**Profit Target:** `${d['Target_Price']:,.2f}` (+{d['Target_Pct']:.1f}%)")
      st.markdown(f"**Stop-Loss:** `${d['Stop_Price']:,.2f}` ({d['Stop_Pct']:.1f}%)")
      st.markdown(f"**Reward/Risk:** `{d['R_Multiple']:.2f}R` ({'Pass ≥2R' if d['TCT_2R_Pass'] else 'Below 2R'})")
      st.markdown(f"**Suggested Shares:** `{d['Shares_05Pct']} shares` (${d['Pos_Value']:,.0f})")
      st.markdown(f"**{ma150_type}:** `${ma150_val:,.2f}`")
      st.markdown(f"**RSI(14) / RSI(2):** `{d['RSI']:.1f}` / `{d['RSI2']:.0f}`")
      st.markdown(f"*{d['TCT_Explain']}*")
      st.markdown("---")
      st.markdown(f"**Market Cap:** `{mcap_text}`")
      st.markdown(f"**P/E (Trail / Fwd):** `{pe_text}` / `{fpe_text}`")
      st.markdown(f"**Analyst Target:** `{analyst_tgt_text}`")
      st.markdown(f"**52W High / Low:** `{w52_text}`")
      st.markdown(f"**History High / Low:** `{hist_hl_text}`")
      st.markdown(f"**Earnings Day:** `{earn_text}`")
    with c_plot:
      f1, f2, f3, f4, f5, f6 = st.columns(6)
      f1.metric("Price", f"${d['Price']:,.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
      f2.metric("Action Signal", d["TCT_Action"])
      f3.metric("Buy Trigger (BOS)", f"${d['BOS_Level']:,.2f}")
      f4.metric("Take Profit Target", f"${d['Target_Price']:,.2f}", f"+{d['Target_Pct']:.1f}%")
      f5.metric("Safety Stop-Loss", f"${d['Stop_Price']:,.2f}", f"{d['Stop_Pct']:.1f}%", delta_color="inverse")
      f6.metric("0.5% Risk Size", f"{d['Shares_05Pct']} shs", f"{d['R_Multiple']:.1f}R Reward/Risk")
      fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.64, 0.18, 0.18])
      fig.add_trace(go.Candlestick(x=df_hist.index, open=df_hist['Open'], high=df_hist['High'], low=df_hist['Low'], close=df_hist['Close'], name="Candles"), row=1, col=1)
      if show_ema20:
        fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA20'], line=dict(color="#d4af37", width=1.5), name="EMA 20"), row=1, col=1)
      if show_ema50:
        fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA50'], line=dict(color="#15803d", width=1.5), name="EMA 50"), row=1, col=1)
      if show_ma150:
        col_150 = "SMA150" if ma150_type == "SMA 150" else "EMA150"
        fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist[col_150], line=dict(color="#0284c7", width=2.0), name=ma150_type), row=1, col=1)
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
      fig.update_xaxes(
        rangeselector=dict(
          buttons=list([
            dict(count=3, label="3M", step="month", stepmode="backward"),
            dict(count=6, label="6M", step="month", stepmode="backward"),
            dict(count=1, label="YTD", step="year", stepmode="todate"),
            dict(count=1, label="1Y", step="year", stepmode="backward"),
            dict(count=2, label="2Y", step="year", stepmode="backward"),
            dict(count=3, label="3Y", step="year", stepmode="backward"),
            dict(count=5, label="5Y", step="year", stepmode="backward"),
            dict(step="all", label="MAX")
          ]),
          bgcolor="#f4efe6",
          activecolor="#c5a059",
          font=dict(size=11)
        ),
        row=1, col=1
      )
      fig.update_layout(height=680, margin=dict(l=0, r=0, t=30, b=0), paper_bgcolor="white", plot_bgcolor="white", xaxis_rangeslider_visible=False)
      st.plotly_chart(fig, use_container_width=True)
    st.markdown("### Verified Recent Headlines (Last 72 Hours)")
    sym_news = _fetch_rss_raw(f'"{sym}" stock when:3d', max_per_query=8, ticker_tag=sym, max_age_hours=settings["max_news_age_hours"])
    if sym_news:
      for a in sym_news:
        st.markdown(f'- **[{a["age"]}]** <a href="{a["link"]}" target="_blank" style="color:#0f291e;font-weight:600;">{a["title"]}</a> *({a["publisher"]} · {a["date"]})*', unsafe_allow_html=True)
    else:
      st.caption("No verified headlines in the past 72 hours.")
    st.markdown("### Profile Summary")
    st.write(funds.get("Business Summary", "No business overview provided."))
  else:
    st.error(f"Unable to retrieve historical chart data for {sym}.")

else:
  if navigation == "Dashboard":
    st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
    all_monitored = get_all_monitored_tickers()
    stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])
    if stock_records:
      best_pick = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + (15 if x["RS_Leader"] else 0) + x["Score"])
      arr_b = "▲ +" if best_pick["Change"] >= 0 else "▼ -"
      st.markdown(
        f"""
<div style="background-color:#0f291e;border-radius:10px;padding:20px 24px;color:#fbf9f4;margin-bottom:20px;">
<div style="font-size:0.75rem;text-transform:uppercase;letter-spacing:0.12em;color:#c5a059;font-weight:700;">
TODAY'S STANDOUT SETUP · {best_pick['TCT_Action']} · {best_pick['TCT_Model']}
</div>
<div style="display:flex;justify-content:space-between;align-items:center;margin-top:6px;">
<div>
<a href="?inspect={best_pick['Ticker']}" target="_self" class="hero-ticker-link">{best_pick['Ticker']}</a>
<span style="font-size:1.25rem;color:#e2e8f0;margin-left:10px;font-weight:700;">${best_pick['Price']:,.2f}</span>
<span style="color:{'#4ade80' if best_pick['Change'] >= 0 else '#f87171'};font-weight:700;margin-left:8px;">
{arr_b}${abs(best_pick['Change']):.2f} ({best_pick['Change_Pct']:+.2f}%)
</span>
<div style="color:#cbd5e1;font-size:0.90rem;margin-top:6px;">
<b>Buy Trigger:</b> ${best_pick['BOS_Level']:,.2f} ·
<b>Take Profit:</b> ${best_pick['Target_Price']:,.2f} (+{best_pick['Target_Pct']:.1f}%) ·
<b>Stop-Loss:</b> ${best_pick['Stop_Price']:,.2f} ({best_pick['Stop_Pct']:.1f}%) ·
<b>Size (0.5% Risk):</b> {best_pick['Shares_05Pct']} shs ({best_pick['R_Multiple']:.1f}R)
</div>
</div>
<div style="text-align:right;">
<div style="font-size:2.2rem;font-weight:700;color:#c5a059;font-family:'Newsreader', serif;">{best_pick['Score']}</div>
<div style="font-size:0.70rem;color:#94a3b8;text-transform:uppercase;">Composite Score</div>
</div>
</div>
</div>
""", unsafe_allow_html=True
      )
    col_left, col_right = st.columns([2, 1])
    with col_left:
      tab_watch, tab_macro, tab_mcf = st.tabs([f"Watchlist News ({len(all_monitored)} Tickers)", "General Market", "Metals, Crypto & USD"])
      with tab_watch:
        wl_news = fetch_watchlist_news_pool(all_monitored, max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if wl_news:
          _render_news_box(wl_news, show_ticker=True)
      with tab_macro:
        market_news = fetch_google_news_rss("US stock market news", max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if market_news:
          _render_news_box(market_news, show_ticker=False)
      with tab_mcf:
        mcf_news = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if mcf_news:
          _render_news_box(mcf_news, show_ticker=True)
    with col_right:
      st.subheader("Action Signals Snapshot")
      for r in sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))[:10]:
        arr_s = "▲ +" if r["Change"] >= 0 else "▼ -"
        clr_s = "#15803d" if r["Change"] >= 0 else "#b91c1c"
        st.markdown(
          f"""
<div style="background:white;border:1px solid #e7e2d9;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
<div style="display:flex;justify-content:space-between;align-items:center;">
<div>
<a href="?inspect={r['Ticker']}" target="_self" class="ticker-link" style="font-size:1.05rem;">{r['Ticker']}</a>
<span class="badge {r['TCT_Badge']}" style="margin-left:6px;font-size:0.62rem;">{r['TCT_Action']}</span>
</div>
<div style="text-align:right;">
<span style="font-weight:700;font-size:0.92rem;">${r['Price']:,.2f}</span>
<span style="color:{clr_s};font-size:0.78rem;font-weight:700;margin-left:4px;">{arr_s}${abs(r['Change']):.2f} ({r['Change_Pct']:+.2f}%)</span>
</div>
</div>
<div style="font-size:0.74rem;color:#52525b;margin-top:5px;">
<b>{r['TCT_Model']}</b> · Buy: <b>${r['BOS_Level']:,.2f}</b> · Target: <b style="color:#15803d;">${r['Target_Price']:,.2f}</b> · Stop: <b style="color:#b91c1c;">${r['Stop_Price']:,.2f}</b>
</div>
</div>
""", unsafe_allow_html=True
        )
  elif navigation == "Active Positions":
    render_active_positions_manager(key_prefix="nav_ap")
  elif navigation == "AI Macro & Trade Co-Pilot":
    render_ai_copilot_tab()
  elif navigation == "Live Real-Time Quotes":
    st.markdown("""<style>.block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; padding-left: 1.2rem !important; padding-right: 1.2rem !important; }</style>""", unsafe_allow_html=True)
    folder_names = list(watchlists.keys())
    folder_options = folder_names + ["All Watchlists Combined"]
    ctrl1, ctrl2, ctrl3, ctrl4, ctrl5, ctrl6, ctrl7 = st.columns([1.8, 1.9, 1.9, 1.3, 1.3, 0.8, 1.1])
    with ctrl1:
      default_live_idx = folder_options.index(st.session_state.get("live_folder_sel")) if st.session_state.get("live_folder_sel") in folder_options else 0
      selected_live_folder = st.selectbox("Watchlist", folder_options, index=default_live_idx, label_visibility="collapsed")
      if selected_live_folder != st.session_state.get("live_folder_sel"):
        st.session_state.live_folder_sel = selected_live_folder
        persist_ui_state()
    with ctrl2:
      live_board_mode = st.selectbox("Board Mode", ["Custom Signal Board (Large Font)", "TradingView Streaming (Tick-by-Tick)"], index=0, label_visibility="collapsed")
    with ctrl3:
      live_sort = st.selectbox(
        "Rank / Sort",
        [
          "Rank: My Saved Order",
          "Rank: Action Signal (Buy First)",
          "Rank: Day % Change (Gainers)",
          "Rank: Day % Change (Losers)",
          "Rank: Relative Strength vs S&P",
          "Rank: Composite Score"
        ],
        index=1,
        label_visibility="collapsed"
      )
    with ctrl4:
      auto_refresh_choice = st.selectbox("Auto-Refresh Timer", ["Auto: Off", "Auto: 15s", "Auto: 30s", "Auto: 60s"], index=3, label_visibility="collapsed")
    with ctrl5:
      if selected_live_folder != "All Watchlists Combined" and selected_live_folder != "Active Positions":
        lv_add_key = f"lv_qadd_{selected_live_folder}"
        def _commit_lv_add():
          raw_v = st.session_state.get(lv_add_key, "").upper().strip()
          if raw_v:
            added_any = False
            for tk in [x.strip() for x in raw_v.replace(",", " ").split() if x.strip()]:
              if tk not in watchlists[selected_live_folder]:
                watchlists[selected_live_folder].append(tk)
                added_any = True
            if added_any:
              sync_file_to_github(watchlists, DATA_FILE)
              st.toast(f"Added {raw_v} to {selected_live_folder}")
            st.session_state[lv_add_key] = ""
        st.text_input(
          "Quick Add Ticker",
          placeholder=f"+ Add to {selected_live_folder}",
          label_visibility="collapsed",
          key=lv_add_key,
          on_change=_commit_lv_add
        )
      else:
        st.caption("All Combined Lists" if selected_live_folder == "All Watchlists Combined" else "Managed via Watchlist Tab")
    with ctrl6:
      if st.button("Refresh", help="Refresh Quotes Now", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    with ctrl7:
      if selected_live_folder != "Active Positions":
        edit_mode_live = st.checkbox("Edit List", value=False)
      else:
        edit_mode_live = False
    if edit_mode_live:
      render_watchlist_reorder_panel(selected_live_folder, key_prefix="lv")
    if selected_live_folder == "All Watchlists Combined":
      active_live_syms = get_all_monitored_tickers()
    elif selected_live_folder == "Active Positions":
      active_live_syms = [p["Ticker"] for p in positions]
    else:
      active_live_syms = list(watchlists.get(selected_live_folder, []))
    run_every_sec = {"Auto: Off": None, "Auto: 15s": 15, "Auto: 30s": 30, "Auto: 60s": 60}.get(auto_refresh_choice)
    def render_live_watchboard_content():
      bucket = int(time.time() // run_every_sec) if run_every_sec else int(time.time() // 120)
      live_records = fetch_batch_market_data(active_live_syms, account_size=settings["account_size"], refresh_bucket=bucket)
      ordered_syms = [s for s in active_live_syms if s in live_records]
      missing_syms = [s for s in active_live_syms if s not in live_records]
      if live_sort == "Rank: Action Signal (Buy First)":
        ordered_syms = sorted(ordered_syms, key=lambda s: (live_records[s]["TCT_Priority"], -live_records[s]["Score"]))
      elif live_sort == "Rank: Day % Change (Gainers)":
        ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Change_Pct"], reverse=True)
      elif live_sort == "Rank: Day % Change (Losers)":
        ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Change_Pct"])
      elif live_sort == "Rank: Relative Strength vs S&P":
        ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["RS_Diff"], reverse=True)
      elif live_sort == "Rank: Composite Score":
        ordered_syms = sorted(ordered_syms, key=lambda s: live_records[s]["Score"], reverse=True)
      if selected_live_folder == "Active Positions":
        st.markdown("### My Active Positions & Rule Enforcer")
        tot_invested = sum(p["Shares"] * p["BuyPrice"] for p in positions)
        tot_value = sum(p["Shares"] * live_records.get(p["Ticker"], {}).get("Price", p["BuyPrice"]) for p in positions)
        daily_pnl = sum(p["Shares"] * live_records.get(p["Ticker"], {}).get("Change", 0.0) for p in positions)
        prev_val = tot_value - daily_pnl
        daily_pct = (daily_pnl / prev_val * 100.0) if prev_val > 0 else 0.0
        unreal_pnl = tot_value - tot_invested
        unreal_pct = (unreal_pnl / tot_invested * 100) if tot_invested else 0.0
        c_m1, c_m2, c_m3, c_m4 = st.columns(4)
        c_m1.metric("Total Invested Cost", f"${tot_invested:,.2f}")
        c_m2.metric("Current Market Value", f"${tot_value:,.2f}")
        c_m3.metric("Today's Daily Gain/Loss", f"${daily_pnl:+,.2f}", f"{daily_pct:+.2f}%")
        c_m4.metric("Total Unrealized P&L", f"${unreal_pnl:+,.2f}", f"{unreal_pct:+.2f}%")
        st.markdown("<br>", unsafe_allow_html=True)
        if positions:
          rows_html = ""
          for p in positions:
            sym = p["Ticker"]
            if sym not in live_records: continue
            d = live_records[sym]
            price = d["Price"]
            bp = p["BuyPrice"]
            shares = p["Shares"]
            pnl = (price - bp) * shares
            pnl_pct = ((price - bp) / bp) * 100
            clr = "#15803d" if pnl >= 0 else "#b91c1c"
            sign = "+" if pnl >= 0 else ""
            arrow = "▲" if d["Change"] >= 0 else "▼"
            rule_status = f'<span class="badge {d["TCT_Badge"]}">{d["TCT_Action"]}</span>'
            if price <= p["StopLoss"]:
              rule_status = '<span class="badge badge-tct-sell" style="background:#dc2626;">STOP HIT</span>'
            elif price >= p["Target15"] and not p.get("HalfSold", False):
              rule_status = '<span class="badge badge-tct-buy" style="background:#059669;">UP +15% (SELL 50%)</span>'
            elif price < d["EMA20_Val"]:
              rule_status = '<span class="badge badge-caution">BROKE 20-EMA</span>'
            rows_html += (
              f'<tr>'
              f'<td>{rule_status}</td>'
              f'<td><a href="?inspect={sym}" target="_self" class="rt-sym-link" title="Open Full Dossier">{sym}</a></td>'
              f'<td style="font-weight:800;"><a href="?rt_chart={sym}" target="_self" class="rt-price-link" style="color:{"#15803d" if d["Change"]>=0 else "#b91c1c"};" title="Tap to open live streaming chart below">{arrow} ${price:,.2f}</a> <span style="font-size:0.75rem;font-weight:600;color:{"#15803d" if d["Change"]>=0 else "#b91c1c"};">({d["Change_Pct"]:+.2f}%)</span></td>'
              f'<td>${bp:,.2f} <span style="font-size:0.75rem;color:#71717a;">({shares} shs)</span></td>'
              f'<td style="color:{clr};font-weight:800;">{sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)</td>'
              f'<td style="color:#b91c1c;font-weight:700;">${p["StopLoss"]:,.2f}</td>'
              f'<td style="color:#15803d;font-weight:700;">${p["Target15"]:,.2f}</td>'
              f'<td style="font-size:0.85rem;color:#52525b;">${d["EMA20_Val"]:,.2f}</td>'
              f'</tr>'
            )
          st.markdown(
            f'<table class="live-quote-table">'
            f'<thead><tr><th>Rule Status</th><th>Ticker</th><th>Live Price & Day %</th><th>Buy Price & Size</th><th>Unrealized P&L</th><th>Stop-Loss</th><th>+15% Target</th><th>20-Day EMA</th></tr></thead>'
            f'<tbody>{rows_html}</tbody></table>',
            unsafe_allow_html=True
          )
        else:
          st.info("No active positions tracked. Manage your positions in the Watchlist tab.")
      elif live_board_mode.startswith("Custom Signal Board"):
        def build_half_table_html(sym_slice):
          rows_html = ""
          for sym in sym_slice:
            d = live_records[sym]
            chg, pct = d["Change"], d["Change_Pct"]
            color = "#15803d" if chg >= 0 else "#b91c1c"
            arrow = "▲" if chg >= 0 else "▼"
            sign = "+" if chg >= 0 else "-"
            short_sig = d.get("TCT_Short_Sig", "🔵 Uptrend")
            sig_clr = d.get("TCT_Sig_Color", "#1d4ed8")
            rows_html += (
              f'<tr>'
              f'<td style="color:{sig_clr};font-weight:800;">{short_sig}</td>'
              f'<td><a href="?inspect={sym}" target="_self" class="rt-sym-link" title="Open Full Dossier">{sym}</a></td>'
              f'<td style="font-weight:800;color:{color};"><a href="?rt_chart={sym}" target="_self" class="rt-price-link" style="color:{color};" title="Tap to open live streaming chart below">{arrow} {d["Price"]:,.2f}</a></td>'
              f'<td style="color:{color};font-weight:700;">{sign}{abs(chg):.2f} ({pct:+.2f}%)</td>'
              f'<td style="color:#15803d;font-weight:600;">{d["Day_High"]:,.2f}</td>'
              f'<td style="color:#b91c1c;font-weight:600;">{d["Day_Low"]:,.2f}</td>'
              f'</tr>'
            )
          return f'<table class="live-quote-table"><thead><tr><th>Signal</th><th>Symbol</th><th>Price</th><th>Day Chg ($ / %)</th><th>High</th><th>Low</th></tr></thead><tbody>{rows_html}</tbody></table>'
        if ordered_syms:
          mid = (len(ordered_syms) + 1) // 2
          left_table_html = build_half_table_html(ordered_syms[:mid])
          right_table_html = build_half_table_html(ordered_syms[mid:]) if ordered_syms[mid:] else ""
          st.markdown(f'<div class="live-board-grid"><div>{left_table_html}</div><div>{right_table_html}</div></div>', unsafe_allow_html=True)
          timer_status = f"Auto-refreshing every {run_every_sec}s (Instant ntfy Active)" if run_every_sec else "Manual refresh mode"
          st.caption(f"🔥 Momentum · 📈 Stage 2 HL · 🟢 Buy Now · 🎯 Swing Buy · 🔔 150MA Radar · 🪃 Oversold · 📐 TCT Box · 🔵 Uptrend  |  **Tap Symbol** for Full Dossier · **Tap Price** for Bottom Live Chart  |  *{timer_status} · Last updated: {datetime.now().strftime('%H:%M:%S')}*")
        else:
          st.info("No symbols found in this watchlist.")
      else:
        tv_all_syms = ordered_syms + missing_syms
        if tv_all_syms:
          tape_symbols = [
            {"proName": "FOREXCOM:SPXUSD", "title": "S&P 500"},
            {"proName": "FOREXCOM:NSXUSD", "title": "Nasdaq 100"},
            {"proName": "BITSTAMP:BTCUSD", "title": "Bitcoin"}
          ] + [{"proName": s, "title": s} for s in tv_all_syms[:25]]
          components.html(f"""
<div class="tradingview-widget-container">
<div class="tradingview-widget-container__widget"></div>
<script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-ticker-tape.js" async>
{{
"symbols": {json.dumps(tape_symbols)},
"showSymbolLogo": true,
"isTransparent": false,
"displayMode": "regular",
"colorTheme": "light",
"locale": "en"
}}
</script>
</div>
""", height=120)
          st.markdown("<div style='margin-top:24px;'></div>", unsafe_allow_html=True)
          mid = (len(tv_all_syms) + 1) // 2
          l_tv = [{"name": s, "displayName": f"{live_records[s]['TCT_Dot']} {s}" if s in live_records else s} for s in tv_all_syms[:mid]]
          r_tv = [{"name": s, "displayName": f"{live_records[s]['TCT_Dot']} {s}" if s in live_records else s} for s in tv_all_syms[mid:]]
          wh = max(460, min(820, mid * 38 + 100))
          tc1, tc2 = st.columns(2)
          g1_json = json.dumps([{"name": f"{selected_live_folder} (Col 1)", "symbols": l_tv}])
          g2_json = json.dumps([{"name": f"{selected_live_folder} (Col 2)", "symbols": r_tv}])
          with tc1:
            components.html(
              f'<div class="tradingview-widget-container">'
              f'<div class="tradingview-widget-container__widget"></div>'
              f'<script type="text/javascript" '
              f'src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>'
              f'{{"width": "100%", "height": {wh}, "symbolsGroups": {g1_json}, '
              f'"showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}'
              f'</script></div>',
              height=wh + 16
            )
          with tc2:
            if r_tv:
              components.html(
                f'<div class="tradingview-widget-container">'
                f'<div class="tradingview-widget-container__widget"></div>'
                f'<script type="text/javascript" '
                f'src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>'
                f'{{"width": "100%", "height": {wh}, "symbolsGroups": {g2_json}, '
                f'"showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}'
                f'</script></div>',
                height=wh + 16
              )
          pills_b = "".join([f'<a href="?rt_chart={s}" target="_self" class="pill" title="Open Bottom Live Chart">{live_records[s]["TCT_Dot"] if s in live_records else "📈"} {s}</a>' for s in tv_all_syms])
          st.markdown(f"<div style='margin-top:4px;'><b>Tap any symbol to open Bottom Live Chart:</b><br>{pills_b}</div>", unsafe_allow_html=True)
    if run_every_sec and hasattr(st, "fragment"):
      @st.fragment(run_every=run_every_sec)
      def _auto_refresh_fragment():
        render_live_watchboard_content()
      _auto_refresh_fragment()
    else:
      render_live_watchboard_content()
    if st.session_state.rt_chart_symbol:
      chart_sym = st.session_state.rt_chart_symbol
      st.markdown("---")
      ch_c1, ch_c2, ch_c3, ch_c4 = st.columns([3.5, 2.0, 2.0, 1.5])
      with ch_c1:
        st.markdown(f"### Live Streaming Chart: `{chart_sym}`")
      with ch_c2:
        rt_interval = st.selectbox("Timeframe", ["5", "15", "60", "240", "D"], format_func=lambda x: {"5": "5-Minute", "15": "15-Minute", "60": "1-Hour (BOS)", "240": "4-Hour", "D": "Daily"}[x], index=2, label_visibility="collapsed")
      with ch_c3:
        if st.button(f"Open {chart_sym} Full Dossier", use_container_width=True):
          st.session_state.inspect_symbol = chart_sym
          st.rerun()
      with ch_c4:
        if st.button("Close Chart", type="primary", use_container_width=True):
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
    st.markdown("<h1>Multi-Playbook & Stage 2 Market Screener</h1>", unsafe_allow_html=True)
    all_watchlist_syms = get_all_monitored_tickers()
    mcf_extra = GICS_SECTORS.get("Indexes, Precious Metals & Crypto", [])
    full_market_syms = list(dict.fromkeys([s for s_list in GICS_SECTORS.values() for s in s_list] + all_watchlist_syms))
    universe_mode = st.radio(
      "1. Choose Scan Universe",
      [
        f"Expanded Market + Indexes, Metals & Crypto (~{len(full_market_syms)} Assets)",
        f"My Watchlists + Indexes, Metals & Crypto ({len(list(dict.fromkeys(all_watchlist_syms + mcf_extra)))} Assets — Instant)",
        "Custom Sector Selection below"
      ],
      horizontal=True
    )
    def get_target_universe(selected_secs):
      if universe_mode.startswith("My Watchlists"):
        return list(dict.fromkeys(all_watchlist_syms + mcf_extra))
      elif universe_mode.startswith("Expanded Market"):
        return full_market_syms
      return list(dict.fromkeys([s for sc in selected_secs for s in GICS_SECTORS[sc]]))
    def _save_screener_results(match_list, title_str):
      st.session_state.screener_matches = match_list
      st.session_state.screener_tickers = [m["Ticker"] for m in match_list]
      st.session_state.screener_title = title_str
      persist_ui_state()
    st.markdown("### 2. One-Tap Strategy Preset Scans")
    r1_c1, r1_c2, r1_c3, r1_c4 = st.columns(4)
    r2_c1, r2_c2, r2_c3, r2_c4 = st.columns(4)
    if r1_c1.button("Stage 2 Higher Low", use_container_width=True, type="primary"):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d.get("Is_Stage2_Higher_Low")], key=lambda x: -x["Score"])
      _save_screener_results(res_l, "Stage 2 Higher Low")
    if r1_c2.button("150-MA Reversal Radar (Research)", use_container_width=True, type="primary"):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d.get("Is_150MA_Reversal_Radar")], key=lambda x: -x["Score"])
      _save_screener_results(res_l, "150-MA Reversal Radar")
    if r1_c3.button("Pure Momentum Leaders", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["Is_Pure_Momentum"]], key=lambda x: -x["RS_Diff"])
      _save_screener_results(res_l, "Pure Momentum Leaders (RS+, Price>20/50/200, RSI 55-75)")
    if r1_c4.button("All 'BUY NOW' Triggers", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["TCT_Priority"] == 0], key=lambda x: -x["Score"])
      _save_screener_results(res_l, "All Immediate 'BUY NOW' & 'SWING BUY' Triggers")
    if r2_c1.button("TCT Bottom Boxes", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["TCT_Valid_Range"]], key=lambda x: (x["TCT_Priority"], -x["R_Multiple"]))
      _save_screener_results(res_l, "Playbook 1: Valid 25+ Bar TCT Accumulation Boxes")
    if r2_c2.button("20-EMA Pullback & Coil", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["Playbook_Cat"] == "SWING_PULLBACK"], key=lambda x: -x["Score"])
      _save_screener_results(res_l, "Playbooks 3 & 4: 20-EMA Pullback & Volatility Squeeze Swings")
    if r2_c3.button("20D & Gap Breakouts", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["Playbook_Cat"] == "BREAKOUT"], key=lambda x: -x["Score"])
      _save_screener_results(res_l, "Playbooks 2 & 6: Momentum & High-Volume Gap Breakouts")
    if r2_c4.button("RSI-2 Oversold Bounce", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      res_l = sorted([d for d in s_data.values() if d["Is_Oversold_Swing"]], key=lambda x: x["RSI2"])
      _save_screener_results(res_l, "Playbook 5: RSI-2 Extreme Oversold Snapback Swings")
    with st.expander("Optional: Custom Sector & Technical Filter Builder", expanded=False):
      f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])
      with f_col1:
        selected_sectors = [sec for sec in GICS_SECTORS.keys() if st.checkbox(sec, value=True, key=f"sec_{sec}")]
      with f_col2:
        s_rs = st.checkbox("Outperforming S&P 500 (RS Leader)", value=False)
        s1 = st.checkbox("RSI Rising Above 55 (Momentum)", value=False)
        s4 = st.checkbox("20-Day High Breakout (Volume Confirmed)", value=False)
        s7 = st.checkbox("Pullback Near 20D or 50D EMA Support", value=False)
        s_st2 = st.checkbox("Stage 2 Higher Low Only", value=False)
      with f_col3:
        tct1 = st.checkbox("Action = 'BUY NOW' / 'SWING BUY'", value=False)
        tct2 = st.checkbox("True TCT Bottom Accumulation Box Only", value=False)
        tct4 = st.checkbox("Reward-to-Risk ≥ 2.0R to Target", value=False)
        tct5 = st.checkbox("Liquidity (20D Dollar Volume ≥ $50M)", value=False)
        s_rev150 = st.checkbox("Just Broke Back Above 150-Day MA (Radar)", value=False)
      if st.button("Run Custom Filter Scan", type="primary"):
        s_data = fetch_batch_market_data(get_target_universe(selected_sectors), account_size=settings["account_size"])
        matches = []
        for t, d in s_data.items():
          if s_rs and not d["RS_Leader"]: continue
          if s1 and d["RSI"] < 55: continue
          if s4 and not d["Is_Breakout"]: continue
          if s7 and not d["Pullback_EMA50"]: continue
          if s_st2 and not d.get("Is_Stage2_Higher_Low"): continue
          if s_rev150 and not d.get("Is_150MA_Reversal_Radar"): continue
          if tct1 and d["TCT_Priority"] != 0: continue
          if tct2 and not d["TCT_Valid_Range"]: continue
          if tct4 and not d["TCT_2R_Pass"]: continue
          if tct5 and not d["TCT_Liq_50M"]: continue
          matches.append(d)
        res_l = sorted(matches, key=lambda x: (x["TCT_Priority"], -x["Score"]))
        _save_screener_results(res_l, f"Custom Filter Scan ({len(res_l)} Matches)")
    if st.session_state.screener_matches is None and st.session_state.get("screener_tickers") is not None:
      saved_tks = st.session_state.get("screener_tickers", [])
      if saved_tks:
        restored_data = fetch_batch_market_data(saved_tks, account_size=settings["account_size"])
        st.session_state.screener_matches = [restored_data[tk] for tk in saved_tks if tk in restored_data]
      else:
        st.session_state.screener_matches = []
    if st.session_state.screener_matches is not None:
      st.markdown("---")
      matches = st.session_state.screener_matches
      st.markdown(f"### {st.session_state.screener_title or 'Scan Results'} ({len(matches)} Found)")
      target_add_folder = st.selectbox("Add selected stocks to folder:", list(watchlists.keys()), index=1, key="sc_target_folder")
      for m in matches:
        c1, c2, c3, c4 = st.columns([3.4, 2.7, 1.8, 1.0])
        arr_m = "▲ +" if m["Change"] >= 0 else "▼ -"
        with c1:
          st.markdown(
            f"""
<div><a href="?inspect={m['Ticker']}" target="_self" class="ticker-link">{m['Ticker']}</a>
<span class="badge {m['TCT_Badge']}">{m['TCT_Action']}</span></div>
<div style="font-size:0.85rem;color:#71717a;margin-top:3px;">
${m['Price']:,.2f} · <span style="color:{'#15803d' if m['Change']>=0 else '#b91c1c'};font-weight:700;">
{arr_m}${abs(m['Change']):.2f} ({m['Change_Pct']:+.2f}%)</span> · <b>{m['TCT_Model']}</b></div>
<div style="font-size:0.8rem;color:#475569;margin-top:4px;">{m['TCT_Explain']}</div>
""", unsafe_allow_html=True
          )
        with c2:
          st.markdown(
            f"""
<div style="font-size:0.82rem;line-height:1.5;">
<b>Buy Trigger:</b> ${m['BOS_Level']:,.2f}<br>
<b>Take Profit:</b> <span style="color:#15803d;font-weight:600;">${m['Target_Price']:,.2f} (+{m['Target_Pct']:.1f}%)</span><br>
<b>Stop-Loss:</b> <span style="color:#b91c1c;font-weight:600;">${m['Stop_Price']:,.2f} ({m['Stop_Pct']:.1f}%)</span> · <b>{m['R_Multiple']:.1f}R</b> · <b>{m['Shares_05Pct']} shs</b>
</div>
""", unsafe_allow_html=True
          )
        with c3:
          st.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
        with c4:
          if st.button("Add", key=f"add_sc_{m['Ticker']}"):
            if m["Ticker"] not in watchlists[target_add_folder]:
              watchlists[target_add_folder].append(m["Ticker"])
              sync_file_to_github(watchlists, DATA_FILE)
              st.success("Synced!")
  elif navigation == "Watchlist":
    st.markdown("<h1>Watchlists & Multi-Playbook Action Tickets</h1>", unsafe_allow_html=True)
    wl_keys = list(watchlists.keys())
    default_wl_idx = wl_keys.index(st.session_state.get("wl_folder_radio")) if st.session_state.get("wl_folder_radio") in wl_keys else 0
    folder = st.radio("Select Watchlist Folder", wl_keys, index=default_wl_idx, horizontal=True)
    if folder != st.session_state.get("wl_folder_radio"):
      st.session_state.wl_folder_radio = folder
      persist_ui_state()
    if folder == "Active Positions":
      render_active_positions_manager(key_prefix="wl_ap")
    else:
      symbols = watchlists.get(folder, [])
      col_add, col_sort, col_ed = st.columns([2.6, 2.2, 1.2])
      with col_add:
        c_in, c_btn = st.columns([3, 1])
        wl_in_key = f"wl_add_in_{folder}"
        def _commit_wl_add():
          raw_s = st.session_state.get(wl_in_key, "").upper().strip()
          if raw_s:
            added_any = False
            for tk in [x.strip() for x in raw_s.replace(",", " ").split() if x.strip()]:
              if tk not in watchlists[folder]:
                watchlists[folder].append(tk)
                added_any = True
            if added_any:
              sync_file_to_github(watchlists, DATA_FILE)
              st.toast(f"Added {raw_s} to {folder}")
            st.session_state[wl_in_key] = ""
        c_in.text_input(
          "Add symbol to folder",
          placeholder=f"Add to {folder} (e.g. AVGO)",
          label_visibility="collapsed",
          key=wl_in_key,
          on_change=_commit_wl_add
        )
        if c_btn.button("+ Add", use_container_width=True):
          _commit_wl_add()
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
            "Day % Change (High → Low)",
            "Alphabetical (A → Z)"
          ],
          index=0,
          label_visibility="collapsed"
        )
      with col_ed:
        show_reorder = st.checkbox("Edit / Reorder List", value=False)
      if show_reorder:
        render_watchlist_reorder_panel(folder, key_prefix="wl_ed")
      st.markdown("**One-Tap Strategy Playbook Filter:**")
      wf1, wf2, wf3, wf4, wf5, wf6, wf7, wf8 = st.columns(8)
      if wf1.button("Stage 2 HL", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "STAGE2_HL" else "secondary"):
        st.session_state.wl_preset_filter = "STAGE2_HL"; persist_ui_state(); st.rerun()
      if wf2.button("150MA Radar", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "REV150" else "secondary"):
        st.session_state.wl_preset_filter = "REV150"; persist_ui_state(); st.rerun()
      if wf3.button("Momentum", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "MOMENTUM" else "secondary"):
        st.session_state.wl_preset_filter = "MOMENTUM"; persist_ui_state(); st.rerun()
      if wf4.button("Buy Triggers", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "BUY" else "secondary"):
        st.session_state.wl_preset_filter = "BUY"; persist_ui_state(); st.rerun()
      if wf5.button("TCT Bottoms", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "TCT" else "secondary"):
        st.session_state.wl_preset_filter = "TCT"; persist_ui_state(); st.rerun()
      if wf6.button("Swings", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "SWING" else "secondary"):
        st.session_state.wl_preset_filter = "SWING"; persist_ui_state(); st.rerun()
      if wf7.button("<150MA Cut", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "CUT150" else "secondary"):
        st.session_state.wl_preset_filter = "CUT150"; persist_ui_state(); st.rerun()
      if wf8.button("Show All", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "ALL" else "secondary"):
        st.session_state.wl_preset_filter = "ALL"; persist_ui_state(); st.rerun()
      pills_html = "".join([f'<a href="?inspect={s}" target="_self" class="pill">{i+1}. {s}</a>' for i, s in enumerate(symbols)])
      st.markdown(f"<div style='margin:8px 0;'>{pills_html}</div>", unsafe_allow_html=True)
      st.markdown("---")
      data_dict = fetch_batch_market_data(symbols, account_size=settings["account_size"])
      earnings_map = fetch_upcoming_earnings_map(symbols)
      display_symbols = [s for s in symbols if s in data_dict]
      flt = st.session_state.wl_preset_filter
      if flt == "STAGE2_HL": display_symbols = [s for s in display_symbols if data_dict[s].get("Is_Stage2_Higher_Low")]
      elif flt == "REV150": display_symbols = [s for s in display_symbols if data_dict[s].get("Is_150MA_Reversal_Radar")]
      elif flt == "MOMENTUM": display_symbols = [s for s in display_symbols if data_dict[s]["Is_Pure_Momentum"]]
      elif flt == "BUY": display_symbols = [s for s in display_symbols if data_dict[s]["TCT_Priority"] == 0]
      elif flt == "TCT": display_symbols = [s for s in display_symbols if data_dict[s]["TCT_Valid_Range"]]
      elif flt == "SWING": display_symbols = [s for s in display_symbols if data_dict[s]["Playbook_Cat"] == "SWING_PULLBACK"]
      elif flt == "CUT150": display_symbols = [s for s in display_symbols if data_dict[s].get("Below_SMA150")]
      if sort_by == "Action Signal (Buy Now First)":
        display_symbols = sorted(display_symbols, key=lambda s: (data_dict[s]["TCT_Priority"], -data_dict[s]["Score"]))
      elif sort_by == "Relative Strength vs S&P 500":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["RS_Diff"], reverse=True)
      elif sort_by == "Composite Score (High → Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["Score"], reverse=True)
      elif sort_by == "Reward-to-Risk Ratio (High → Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["R_Multiple"], reverse=True)
      elif sort_by == "Day % Change (High → Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["Change_Pct"], reverse=True)
      elif sort_by == "Alphabetical (A → Z)":
        display_symbols = sorted(display_symbols)
      if not display_symbols:
        st.info("No stocks matched that filter in this folder. Tap 'Show All' above to reset.")
      left_c, right_c = st.columns(2)
      for idx, sym in enumerate(display_symbols):
        d = data_dict[sym]
        arr_w = "▲ +" if d["Change"] >= 0 else "▼ -"
        if d["RS_Leader"]:
          rs_html = f'<span class="badge badge-rs-lead" style="margin-left:4px;">Leading S&P ({d["RS_Diff"]:+.1f}%)</span>'
        else:
          rs_html = f'<span class="badge badge-rs-lag" style="margin-left:4px;">RS {d["RS_Diff"]:+.1f}%</span>'
        earn_html = ""
        if sym in earnings_map:
          days_left, dt_s = earnings_map[sym]
          if days_left <= 14:
            earn_html = (
              f'<div style="margin-top:6px;"><span class="badge badge-earn-warn">'
              f'EARNINGS IN {days_left}d ({dt_s}) — WATCH CATALYST RISK'
              f'</span></div>'
            )
        chg_clr = "#15803d" if d["Change"] >= 0 else "#b91c1c"
        with (left_c if idx % 2 == 0 else right_c):
          st.markdown(
            f'<div class="stock-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
            f'<div><a href="?inspect={d["Ticker"]}" target="_self" class="ticker-link">{d["Ticker"]}</a>'
            f'<span class="badge {d["TCT_Badge"]}" style="margin-left:8px;">{d["TCT_Action"]}</span>'
            f'{rs_html}{earn_html}'
            f'<div style="font-size:1.35rem;font-weight:700;margin-top:6px;">'
            f'${d["Price"]:,.2f} <span style="font-size:0.9rem;color:{chg_clr};font-weight:700;">'
            f'{arr_w}${abs(d["Change"]):.2f} ({d["Change_Pct"]:+.2f}%)</span></div></div>'
            f'<div style="text-align:right;">'
            f'<div style="font-size:1.6rem;font-weight:700;color:#c5a059;font-family:Newsreader, serif;">'
            f'{d["Score"]}</div>'
            f'<div style="font-size:0.7rem;color:#71717a;text-transform:uppercase;">Score</div>'
            f'</div></div>'
            f'<div class="trade-ticket">'
            f'<div style="display:flex;justify-content:space-between;font-weight:700;color:#0f291e;margin-bottom:4px;">'
            f'<span>{d["TCT_Model"]}</span><span>Reward/Risk: {d["R_Multiple"]:.1f}R</span></div>'
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span><b>Buy Trigger:</b> ${d["BOS_Level"]:,.2f}</span>'
            f'<span><b>Take Profit:</b> <span style="color:#15803d;font-weight:700;">'
            f'${d["Target_Price"]:,.2f}</span> (+{d["Target_Pct"]:.1f}%)</span></div>'
            f'<div style="margin-top:4px;display:flex;justify-content:space-between;">'
            f'<span><b>Stop-Loss:</b> <span style="color:#b91c1c;font-weight:700;">'
            f'${d["Stop_Price"]:,.2f}</span> ({d["Stop_Pct"]:.1f}%)</span>'
            f'<span><b>0.5% Size:</b> {d["Shares_05Pct"]} shs (${d["Pos_Value"]:,.0f})</span></div></div>'
            f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;font-size:0.78rem;color:#52525b;">'
            f'<div>Day High: <b>${d["Day_High"]:,.2f}</b></div>'
            f'<div>Day Low: <b>${d["Day_Low"]:,.2f}</b></div>'
            f'<div>RSI(14/2): <b>{d["RSI"]:.0f}/{d["RSI2"]:.0f}</b></div>'
            f'<div>EMA 50: <b>${d["EMA50_Val"]:,.2f}</b></div></div>'
            f'<div style="font-size:0.80rem;color:#475569;margin-top:6px;font-style:italic;">'
            f'"{d["TCT_Explain"]}"</div></div>',
            unsafe_allow_html=True
          )
  elif navigation == "Precious Metals, Crypto & Currency":
    st.markdown("<h1>Precious Metals, Crypto & Currency</h1>", unsafe_allow_html=True)
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
        if sym in mcf_data:
          m = mcf_data[sym]
          decimals = 4 if sym in ("EURUSD=X", "XRP-USD", "HG=F") else 2
          arr_m = "▲ +" if m["Change"] >= 0 else "▼ -"
          with (c1 if idx % 2 == 0 else c2):
            st.markdown(
              f'<div class="stock-card"><div style="display:flex;justify-content:space-between;align-items:center;">'
              f'<div style="font-size:0.76rem;color:#71717a;text-transform:uppercase;font-weight:700;">{title}</div>'
              f'<span class="badge {m["TCT_Badge"]}">{m["TCT_Action"]}</span></div>'
              f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-top:6px;">'
              f'<div><a href="?inspect={sym}" target="_self" class="ticker-link">{sym}</a>'
              f'<span style="font-size:1.45rem;font-weight:700;color:#0f291e;margin-left:10px;">${m["Price"]:,.{decimals}f}</span>'
              f'<span style="font-size:0.92rem;color:{"#15803d" if m["Change"]>=0 else "#b91c1c"}; font-weight: 700; margin-left: 6px;">'
              f'{arr_m}${abs(m["Change"]):.{decimals}f} ({m["Change_Pct"]:+.2f}%)</span></div>'
              f'<span class="badge {m["Badge"]}">{m["State"]}</span></div>'
              f'<div class="trade-ticket"><div style="display:flex;justify-content:space-between;">'
              f'<span><b>Buy Trigger:</b> ${m["BOS_Level"]:,.{decimals}f}</span><span><b>Reward/Risk:</b> {m["R_Multiple"]:.1f}R</span></div>'
              f'<div style="display:flex;justify-content:space-between;margin-top:3px;">'
              f'<span><b>Target:</b> <b style="color:#15803d;">${m["Target_Price"]:,.{decimals}f}</b> (+{m["Target_Pct"]:.1f}%)</span>'
              f'<span><b>Stop:</b> <b style="color:#b91c1c;">${m["Stop_Price"]:,.{decimals}f}</b> ({m["Stop_Pct"]:.1f}%)</span></div></div>'
              f'<div style="margin-top:8px;font-size:0.78rem;color:#52525b;display:flex;justify-content:space-between;">'
              f'<span>Day High: <b>${m["Day_High"]:,.{decimals}f}</b></span><span>Day Low: <b>${m["Day_Low"]:,.{decimals}f}</b></span>'
              f'<span>RSI: <b>{m["RSI"]:.1f}</b></span><span>EMA 50: <b>${m["EMA50_Val"]:,.{decimals}f}</b></span></div></div>',
              unsafe_allow_html=True
            )
    st.subheader("1. Precious & Industrial Metals")
    render_asset_group(METALS_GROUP)
    st.markdown("---")
    st.subheader("2. Cryptocurrencies")
    render_asset_group(CRYPTO_GROUP)
    st.markdown("---")
    st.subheader("3. Currencies & US Dollar Index")
    render_asset_group(FX_GROUP)
  elif navigation == "News & Earnings":
    st.markdown("<h1>News & Catalyst Monitor</h1>", unsafe_allow_html=True)
    n_col1, n_col2 = st.columns([2, 1])
    tracked_symbols = get_all_monitored_tickers()
    with n_col1:
      n_tab1, n_tab2 = st.tabs([f"Watchlist News ({len(tracked_symbols)} Stocks)", "Metals, Crypto & USD News"])
      with n_tab1:
        pool_articles = fetch_watchlist_news_pool(tracked_symbols, max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if pool_articles:
          _render_news_box(pool_articles, show_ticker=True)
      with n_tab2:
        mcf_articles = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
        if mcf_articles:
          _render_news_box(mcf_articles, show_ticker=True)
    with n_col2:
      st.subheader("Upcoming Earnings Calendar")
      earnings_map = fetch_upcoming_earnings_map(tracked_symbols)
      if earnings_map:
        rows = sorted(
          [
            {
              "Ticker": s,
              "Earnings Date": dt_str,
              "Countdown": f"{days_left}d" + (" " if days_left <= 7 else ""),
              "_sort": days_left
            }
            for s, (days_left, dt_str) in earnings_map.items()
          ],
          key=lambda x: x["_sort"]
        )
        st.table(pd.DataFrame([{"Ticker": r["Ticker"], "Earnings Date": r["Earnings Date"], "Countdown": r["Countdown"]} for r in rows]))
      else:
        st.info("No confirmed upcoming earnings within the next 60 days.")
  elif navigation == "Settings":
    st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
    s_col1, s_col2 = st.columns(2)
    with s_col1:
      acc_val = st.number_input("Total Trading Account Size ($ USD) — For 0.5% Risk Share Sizing", min_value=1000, max_value=50000000, value=int(settings.get("account_size", 100000)), step=5000)
      news_lim = st.slider("Max News Headlines in Scrollable Feed", 20, 100, int(settings.get("news_limit", 60)), 10)
      max_age_h = st.slider("Strict News Age Cutoff (Hours)", 24, 120, int(settings.get("max_news_age_hours", 72)), 12)
      w_f = st.slider("Fundamentals Weight", 0, 100, settings["w_fund"])
      w_t = st.slider("Technical Trend Weight", 0, 100, settings["w_tech"])
      w_m = st.slider("Momentum Weight", 0, 100, settings["w_mom"])
      if st.button("Save All Settings", type="primary"):
        settings.update({"account_size": acc_val, "news_limit": news_lim, "max_news_age_hours": max_age_h, "w_fund": w_f, "w_tech": w_t, "w_mom": w_m})
        save_json(SETTINGS_FILE, settings)
        st.cache_data.clear()
        st.success("Settings saved and cache refreshed!")
    with s_col2:
      st.subheader("Push Notifications (Live & Daily Briefing)")
      current_data = fetch_batch_market_data(get_all_monitored_tickers(), account_size=settings["account_size"])
      if st.button("Send Live 8-Playbook Briefing Ping to iPad Now", type="primary"):
        st2_hl = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v.get("Is_Stage2_Higher_Low")]
        rev_150 = [f"{k} (${v['Price']:.2f} > 150MA ${v.get('SMA150_Val', v['Price']):.2f})" for k, v in current_data.items() if v.get("Is_150MA_Reversal_Radar")]
        buys = [f"{k} ({v['TCT_Short_Sig']} @ ${v['Price']:.2f} -> Tgt ${v['Target_Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 0]
        tct_boxes = [f"{k} (BOS ${v['BOS_Level']:.2f})" for k, v in current_data.items() if v["TCT_Valid_Range"] and v["TCT_Priority"] != 0]
        sells = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 4]
        summary_msg = (
          f"STAGE 2 HIGHER LOW ({len(st2_hl)}): {', '.join(st2_hl[:6]) if st2_hl else 'None'}\n"
          f"150-MA REVERSAL RADAR ({len(rev_150)}): {', '.join(rev_150[:6]) if rev_150 else 'None'}\n"
          f"ALL BUY / SWING TRIGGERS ({len(buys)}): {', '.join(buys[:6]) if buys else 'None'}\n"
          f"In TCT Bottom Box ({len(tct_boxes)}): {', '.join(tct_boxes[:6]) if tct_boxes else 'None'}\n"
          f"Below 150/50 MA Avoid ({len(sells)}): {', '.join(sells[:8]) if sells else 'None'}"
        )
        ok, status_msg = send_ntfy_alert(summary_msg, "Daily Portfolio Briefing")
        if ok:
          st.success(f"{status_msg}")
        else:
          st.error(f"{status_msg}")
      st.markdown("---")
      if current_data:
        df_export = pd.DataFrame([{
          "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Ticker": sym_name,
          "Price": d["Price"], "Change": d["Change"], "Change_Pct": d["Change_Pct"],
          "Day_High": d["Day_High"], "Day_Low": d["Day_Low"], "Playbook": d["TCT_Model"],
          "Action_Signal": d["TCT_Action"], "Buy_Trigger": d["BOS_Level"],
          "Take_Profit_Target": d["Target_Price"], "Stop_Loss": d["Stop_Price"],
          "Reward_Risk_R": round(d["R_Multiple"], 2), "Suggested_Shares_05Pct": d["Shares_05Pct"]
        } for sym_name, d in current_data.items()])
        csv_bytes = df_export.to_csv(index=False).encode("utf-8")
        csv_fname = f"tct_swing_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv"
        st.download_button(
          "Download Full 8-Playbook Plan CSV",
          csv_bytes,
          csv_fname,
          "text/csv",
          type="primary"
        )

    st.markdown("---")
    st.subheader("8-Playbook Strategy & Technical Parameter Reference Guide")
    st.caption("Complete specification of the moving averages, volume multipliers, RSI thresholds, and stop/target formulas used across the dashboard.")
    playbook_ref_df = pd.DataFrame([
      {
        "Playbook / Filter": "Playbook 1: TCT Bottom Box",
        "Moving Averages Used": "150-SMA & 50-EMA context; 1H / 5D Swing High BOS",
        "Entry / Trigger Criteria": "Decline >= 8% from 130D peak over >= 25 bars (slow decline); horizontal box height 3%-38% with >= 2 support taps within 1.5% and no close < 30% below box floor. Trigger: Break of Structure (BOS) with >= 2.0R.",
        "Stop-Loss & Profit Target": "Stop: Tap 3 Low - 0.5x ATR(14) (capped 2%-7% below entry). Target: Box Range High."
      },
      {
        "Playbook / Filter": "Playbook 2: 20D Momentum Breakout",
        "Moving Averages Used": "50-Day EMA & 20-Day EMA",
        "Entry / Trigger Criteria": "Close >= prior 20-Day High, Price > 50-Day EMA, and time-paced Relative Volume (RVOL) >= 1.25x 20-Day average volume.",
        "Stop-Loss & Profit Target": "Stop: Max(min(20-EMA, Close - 1.5x ATR14), Close x 0.94). Target: Entry + 2.5R."
      },
      {
        "Playbook / Filter": "Playbook 3: 20-EMA Pullback Swing",
        "Moving Averages Used": "20-Day EMA & 50-Day EMA",
        "Entry / Trigger Criteria": "Confirmed uptrend (Price > 50-EMA and 20-EMA > 50-EMA); Low or Close pulls back within 2.2% of 20-EMA and prints a bullish turn bar (Close >= Open or Close > Prev Close).",
        "Stop-Loss & Profit Target": "Stop: Min(3-Day Low, 20-EMA) - 0.5x ATR14 (max 5% risk). Target: Max(20D High, Entry + 2.4R)."
      },
      {
        "Playbook / Filter": "Playbook 4: Volatility Squeeze Coil",
        "Moving Averages Used": "20-Day SMA (Bollinger Mid) & 50-Day EMA",
        "Entry / Trigger Criteria": "Bollinger Band Width (20, 2) compresses within 18% of its 25-day low (volatility squeeze), Price > 50-EMA, and Close >= prior 3-Day High.",
        "Stop-Loss & Profit Target": "Stop: 3-Day Low - 0.3x ATR14 (max 5% risk). Target: Entry + 2.8R."
      },
      {
        "Playbook / Filter": "Playbook 5: RSI-2 Oversold Bounce",
        "Moving Averages Used": "200-Day EMA & 20-Day EMA",
        "Entry / Trigger Criteria": "Long-term uptrend intact (Price >= 96% of 200-EMA) with extreme short-term washout: 2-period Wilder RSI <= 18 or Low touches Lower Bollinger Band (20, 2).",
        "Stop-Loss & Profit Target": "Stop: Close - 1.5x ATR14 (max 5.5% risk). Target: Max(20-EMA, Entry + 2.0R)."
      },
      {
        "Playbook / Filter": "Playbook 6: High-Vol Gap Ignition",
        "Moving Averages Used": "50-Day EMA",
        "Entry / Trigger Criteria": "Day gain >= +3.2% above 50-EMA on time-paced RVOL >= 1.7x 20-Day average volume, closing in the top 45% of the daily candle range.",
        "Stop-Loss & Profit Target": "Stop: Day Low - 0.2x ATR14 (max 6% risk). Target: Entry + 2.5R."
      },
      {
        "Playbook / Filter": "Playbook 7: Stage 2 Higher Low",
        "Moving Averages Used": "150-Day SMA, 50-Day EMA, 20-Day EMA, 5/10-Day SMA",
        "Entry / Trigger Criteria": "Stage 2 Uptrend (Price > 150-SMA + 1.5%, 150-SMA rising vs 20 bars ago, 50-EMA >= 150-SMA); 12-day pullback low > prior 12-to-38 day low (Higher Low); pulls back from 20D high into 20/50-EMA zone and turns up (Close >= Open, Close > Prev Close, or 5-SMA >= 10-SMA).",
        "Stop-Loss & Profit Target": "Stop: Max(min(12D Low - 0.35x ATR14, 150-SMA), Close x 0.935). Target: Max(20D High x 1.03, Entry + 2.5R)."
      },
      {
        "Playbook / Filter": "Playbook 8: 150-MA Reversal Radar",
        "Moving Averages Used": "150-Day SMA",
        "Entry / Trigger Criteria": "Early Stage 2 trend reversal alert: Stock traded below its 150-Day SMA for >= 3 of the last 30 bars and just crossed back above the 150-Day SMA (within 7.5% above 150-SMA). Use for early research to watch for the next Stage 2 Higher Low.",
        "Stop-Loss & Profit Target": "Stop: 150-SMA - 0.5x ATR14 (max 7% risk). Target: Entry + 2.5R."
      },
      {
        "Playbook / Filter": "Filter: Pure Momentum Leaders",
        "Moving Averages Used": "20-Day EMA, 50-Day EMA, 200-Day EMA",
        "Entry / Trigger Criteria": "Price > 20-EMA, 50-EMA, and 200-EMA simultaneously; 63-Day Relative Strength vs S&P 500 >= +2.0% (RS Leader); and 14-Day RSI between 55 and 75.",
        "Stop-Loss & Profit Target": "Follows active playbook stop or 20-Day EMA trailing stop."
      }
    ])
    st.dataframe(playbook_ref_df, use_container_width=True, hide_index=True)
