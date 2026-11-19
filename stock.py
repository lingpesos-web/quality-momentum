import streamlit as st
import streamlit.components.v1 as components
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import json
import os
import re
import io
import math
import time
import base64
import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET
import email.utils
import imaplib
import smtplib
from email.header import decode_header
from email.message import EmailMessage
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor

try:
  from google import genai
  from google.genai import types as genai_types
  HAS_GOOGLE_GENAI = True
except Exception:
  genai = None
  genai_types = None
  HAS_GOOGLE_GENAI = False

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
OPTIONS_RADAR_FILE = f"options_radar{USER_SUFFIX}.json"
OPTIONS_POSITIONS_FILE = f"options_positions{USER_SUFFIX}.json"
OPTIONS_LEDGER_FILE = f"options_ledger{USER_SUFFIX}.json"
SETTINGS_FILE = f"settings{USER_SUFFIX}.json"
UI_STATE_FILE = f"ui_state{USER_SUFFIX}.json"
REPORT_CACHE_FILE = f"strategist_report{USER_SUFFIX}.json"


def get_target_repo():
  try:
    if "TARGET_REPO" in st.secrets:
      val = str(st.secrets["TARGET_REPO"]).strip()
      if val:
        return val
  except Exception:
    pass
  return os.environ.get("TARGET_REPO", "lingpesos-web/quality-momentum").strip()


GITHUB_REPO = get_target_repo()
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

# --- INITIALIZE SESSION STATE & URL ROUTING ---
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
  ("dossier_chats", {}),
  ("sds_videos", []),
  ("strategist_report", ""),
  ("strategist_report_title", ""),
  ("opt_scan_results", None),
  ("opt_scan_label", ""),
  ("live_sort_sel", "Rank: Action Signal (Buy First)"),
  ("live_auto_ref_sel", "Auto: 60s"),
  ("live_edit_mode", False)
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


# --- STYLE A: REFINED EDITORIAL TERMINAL (ZERO-EMOJI INSTITUTIONAL TYPOGRAPHY) ---
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,600;1,6..72,400&family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@500;600;700&display=swap');
.stApp{background-color:#fbf9f4 !important;color:#1a1a1a !important;font-family:'Inter', sans-serif;}
[data-testid="stSidebar"]{background-color:#0f291e !important;border-right:1px solid #1c3d2f;}
[data-testid="stSidebar"] *{color:#e2e8f0 !important;}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label{padding:6px 10px;border-radius:5px;margin-bottom:2px;font-size:0.86rem;transition:all 0.15s;}
[data-testid="stSidebar"] .stRadio div[role="radiogroup"] > label:hover{background-color:#183d2e;}
h1, h2, h3{font-family:'Newsreader', Georgia, serif !important;font-weight:600 !important;color:#0f291e !important;letter-spacing:-0.01em;}
h1{font-size:1.65rem !important;margin-bottom:0.45rem !important;}
h2{font-size:1.30rem !important;margin-bottom:0.35rem !important;}
h3{font-size:1.08rem !important;margin-bottom:0.30rem !important;}
.num{font-family:'JetBrains Mono','Inter',monospace;font-variant-numeric:tabular-nums;}
.macro-container{display:flex;flex-wrap:nowrap;gap:6px;overflow-x:auto;padding-bottom:4px;margin-bottom:8px;}
.macro-card{flex:1 1 0px;min-width:96px;background:#ffffff;border:1px solid #e2dcd0;border-radius:6px;padding:6px 5px;text-align:center;box-shadow:0 1px 2px rgba(0,0,0,0.02);}
.macro-title{font-size:0.64rem;color:#64748b;text-transform:uppercase;font-weight:700;letter-spacing:0.04em;white-space:nowrap;}
.macro-price{font-size:0.84rem;font-weight:700;color:#111827;margin:1px 0;white-space:nowrap;font-variant-numeric:tabular-nums;}
.tick-pos{color:#15803d;font-size:0.70rem;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums;}
.tick-neg{color:#b91c1c;font-size:0.70rem;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums;}
.risk-strip{display:grid;grid-template-columns:repeat(5, minmax(0, 1fr));gap:8px;background:#0f291e;color:#f4efe6;border-radius:8px;padding:9px 14px;margin-bottom:12px;border:1px solid #1e4232;}
@media (max-width:900px){.risk-strip{grid-template-columns:repeat(2, minmax(0, 1fr));}}
.risk-item-lbl{font-size:0.64rem;text-transform:uppercase;letter-spacing:0.07em;color:#c5a059;font-weight:700;}
.risk-item-val{font-size:0.98rem;font-weight:700;color:#ffffff;font-variant-numeric:tabular-nums;margin-top:2px;}
.risk-item-sub{font-size:0.70rem;color:#cbd5e1;font-variant-numeric:tabular-nums;}
.stock-card{background:#ffffff;border:1px solid #e2dcd0;border-radius:8px;padding:10px 13px;margin-bottom:9px;box-shadow:0 1px 3px rgba(0,0,0,0.02);}
.ticker-link{font-size:1.08rem;font-weight:800;color:#0f291e !important;text-decoration:none !important;border-bottom:2px solid #c5a059;padding-bottom:1px;letter-spacing:0.01em;}
.ticker-link:hover{color:#15803d !important;border-bottom-color:#15803d;background-color:#f0fdf4;border-radius:3px;padding:1px 4px;}
.hero-ticker-link{font-size:1.65rem;font-weight:800;color:#ffffff !important;text-decoration:none !important;border-bottom:2px solid #c5a059;padding-bottom:1px;}
.badge{display:inline-block;padding:1px 7px;border-radius:3px;font-size:0.65rem;font-weight:700;text-transform:uppercase;letter-spacing:0.04em;line-height:1.45;vertical-align:middle;}
.badge-breakout{background:#dcfce7;color:#14532d;border:1px solid #86efac;}
.badge-trend{background:#dbeafe;color:#1e3a8a;border:1px solid #93c5fd;}
.badge-candidate{background:#fef9c3;color:#854d0e;border:1px solid #fde047;}
.badge-caution{background:#fee2e2;color:#991b1b;border:1px solid #fca5a5;}
.badge-tct-buy{background:#0f5132;color:#ffffff;}
.badge-tct-watch{background:#fef3c7;color:#92400e;border:1px solid #f59e0b;}
.badge-tct-sell{background:#991b1b;color:#ffffff;}
.badge-rs-lead{background:#ecfdf5;color:#065f46;border:1px solid #6ee7b7;}
.badge-rs-lag{background:#f4f4f5;color:#52525b;border:1px solid #e4e4e7;}
.badge-earn-warn{background:#fff7ed;color:#c2410c;border:1px solid #fb923c;font-weight:700;}
.badge-pill-sig{display:inline-block;padding:2px 6px;border-radius:3px;font-size:0.66rem;font-weight:800;letter-spacing:0.03em;text-transform:uppercase;white-space:nowrap;}
.pill{display:inline-flex;align-items:center;background:#ebe6dc;color:#0f291e !important;text-decoration:none !important;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700;margin-right:4px;margin-bottom:4px;border:1px solid #d6cfc2;}
.pill:hover{background:#d6cfc2;}
.scroll-news-box{max-height:520px;overflow-y:auto;padding-right:4px;}
.ticker-news-badge{background:#ecfdf5;color:#065f46;border:1px solid #a7f3d0;padding:1px 5px;border-radius:3px;font-weight:700;font-size:0.68rem;margin-right:5px;}
.age-badge{background:#f1f5f9;color:#334155;padding:1px 5px;border-radius:3px;font-weight:600;font-size:0.66rem;margin-left:5px;}
.trade-ticket{background:#f7f4ec;border:1px solid #e2dcd0;border-radius:6px;padding:7px 10px;margin-top:6px;font-size:0.76rem;font-variant-numeric:tabular-nums;}
.live-status-bar{display:flex;align-items:center;gap:10px;font-size:0.80rem;color:#334155;font-weight:600;padding:4px 0;}
.live-dot{display:inline-block;width:7px;height:7px;border-radius:50%;background:#15803d;}
/* DENSE 2-COLUMN LIVE WATCHBOARD TABLE */
.live-board-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px;width:100%;margin-top:2px;}
@media (max-width:900px){.live-board-grid{grid-template-columns:1fr;}}
.live-quote-table{width:100%;border-collapse:collapse;background:#ffffff;border:1px solid #d4cec3;border-radius:6px;overflow:hidden;font-size:1.02rem;table-layout:auto;}
.live-quote-table thead th{background:#0f291e;color:#f4efe6;font-weight:700;font-size:0.74rem;text-transform:uppercase;letter-spacing:0.04em;padding:5px 6px;text-align:right;white-space:nowrap;}
.live-quote-table thead th:nth-child(1), .live-quote-table thead th:nth-child(2){text-align:left;}
.live-quote-table tbody tr{border-bottom:1px solid #eae5dc;line-height:1.22;}
.live-quote-table tbody tr:nth-child(even){background-color:#faf8f5;}
.live-quote-table tbody tr:hover{background-color:#ecfdf5;}
.live-quote-table td{padding:4px 6px;text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}
.live-quote-table td:nth-child(1){text-align:left;padding-left:6px;padding-right:4px;}
.live-quote-table td:nth-child(2){text-align:left;font-weight:800;padding-left:4px;padding-right:4px;}
.rt-sym-link{color:#0f291e !important;text-decoration:none !important;font-weight:800;font-size:1.06rem;border-bottom:2px solid #c5a059;}
.rt-sym-link:hover{color:#15803d !important;background:#dcfce7;padding:1px 4px;border-radius:3px;}
.rt-price-link{text-decoration:none !important;font-weight:800;border-bottom:1px dashed rgba(15,41,30,0.35);padding-bottom:1px;}
.rt-price-link:hover{background:#dcfce7;padding:1px 4px;border-radius:3px;}
.chat-bubble-user{background:#0f291e;color:#f8fafc;border-radius:8px;padding:8px 12px;margin:5px 0 5px 12%;font-size:0.84rem;line-height:1.45;}
.chat-bubble-ai{background:#ffffff;color:#1a1a1a;border:1px solid #dcd6cb;border-left:3px solid #c5a059;border-radius:8px;padding:9px 12px;margin:5px 4% 8px 0;font-size:0.84rem;line-height:1.50;}
[data-testid="InputInstructions"]{display:none !important;}
[data-testid="stToolbarActions"],[data-testid="stActionButtonIcon"],[data-testid="stHeaderActionElements"],[data-testid="manage-app-button"],[data-testid="stMainMenu"],.stDeployButton,.stAppDeployButton,header a[href*="github.com"],div[class*="viewerBadge"],a[class*="viewerBadge"],div[class*="StatusWidget"]{display:none !important;visibility:hidden !important;}
</style>
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
  "Options Radar": ["MSFT", "NVDA", "APP", "AXP", "ABBV", "AMD", "MU", "PLTR", "AVGO", "COHR", "VRT", "HOOD", "ADPT"],
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
  target_repo = get_target_repo()
  if not token:
    return False, f"Saved locally (Add GITHUB_TOKEN in Streamlit Secrets for permanent cloud sync of {filename})."
  api_url = f"https://api.github.com/repos/{target_repo}/contents/{filename}"
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
        return True, f"Permanently synced to GitHub {filename}."
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
options_positions = load_json(OPTIONS_POSITIONS_FILE, [])
if not isinstance(options_positions, list):
  options_positions = []
options_ledger = load_json(OPTIONS_LEDGER_FILE, [])
if not isinstance(options_ledger, list):
  options_ledger = []


def get_all_monitored_tickers():
  combined = []
  for folder_syms in watchlists.values():
    if isinstance(folder_syms, list):
      combined.extend([str(s).strip().upper() for s in folder_syms if str(s).strip()])
  return list(dict.fromkeys(combined))


DEFAULT_NTFY_TOPIC = "2026_USstockspicks" if not ACTIVE_USER else f"stocks_{ACTIVE_USER}"
settings = load_json(SETTINGS_FILE, {
  "w_fund": 40, "w_tech": 40, "w_mom": 20, "account_size": 100000,
  "news_limit": 60, "max_news_age_hours": 72, "alert_breakout": True, "alert_support": True,
  "notif_channel": "ntfy Push", "ntfy_topic": DEFAULT_NTFY_TOPIC,
  "tg_bot_token": "", "tg_chat_id": ""
})
for k_s, v_s in [
  ("account_size", 100000), ("news_limit", 60), ("max_news_age_hours", 72),
  ("w_fund", 40), ("w_tech", 40), ("w_mom", 20),
  ("notif_channel", "ntfy Push"), ("ntfy_topic", DEFAULT_NTFY_TOPIC),
  ("tg_bot_token", ""), ("tg_chat_id", "")
]:
  if k_s not in settings:
    settings[k_s] = v_s


def send_ntfy_alert(message, title="Daily Portfolio Briefing"):
  ch = settings.get("notif_channel", "ntfy Push")
  if ch == "Disabled (In-App Toast Only)":
    return True, "External push disabled (In-App Toast Only mode)."
  statuses = []
  any_ok = False
  ascii_title = title.encode("ascii", "ignore").decode("ascii").strip() or "Market Alert"

  if ch in ("ntfy Push", "Both ntfy & Telegram"):
    topic = str(settings.get("ntfy_topic", "")).strip()
    if topic:
      try:
        req = urllib.request.Request(
          f"https://ntfy.sh/{urllib.parse.quote(topic)}",
          data=message.encode("utf-8"),
          headers={
            "Title": ascii_title,
            "Priority": "high",
            "Content-Type": "text/plain; charset=utf-8"
          },
          method="POST"
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
          any_ok = True
          statuses.append(f"ntfy '{topic}' (HTTP {resp.status})")
      except Exception as e:
        statuses.append(f"ntfy error: {str(e)[:60]}")
    else:
      statuses.append("ntfy topic is empty")

  if ch in ("Telegram Bot", "Both ntfy & Telegram"):
    tg_token = str(settings.get("tg_bot_token", "")).strip()
    tg_chat = str(settings.get("tg_chat_id", "")).strip()
    if tg_token and tg_chat:
      try:
        tg_url = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        tg_payload = json.dumps({
          "chat_id": tg_chat,
          "text": f"*{title}*\n{message}",
          "parse_mode": "Markdown"
        }).encode("utf-8")
        req_tg = urllib.request.Request(
          tg_url,
          data=tg_payload,
          headers={"Content-Type": "application/json"},
          method="POST"
        )
        with urllib.request.urlopen(req_tg, timeout=8) as resp_tg:
          any_ok = True
          statuses.append(f"Telegram (HTTP {resp_tg.status})")
      except Exception as e:
        statuses.append(f"Telegram error: {str(e)[:60]}")
    else:
      statuses.append("Telegram Bot Token or Chat ID missing")

  return any_ok, " | ".join(statuses) if statuses else "No notification channel configured."


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

NON_EQUITY_ETFS = {
  "SLV", "GLD", "SOXL", "SPCX", "DRAM", "SPY", "QQQ", "IWM", "DIA", "TQQQ",
  "XLE", "XLI", "ITA", "XLF", "XLV", "XLU", "URA", "EWJ", "EWY", "FXI",
  "VGK", "EEM", "USO", "TLT", "UUP"
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


def _safe_parallel_map(fn, items, max_workers=4):
  if not items:
    return []
  try:
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
      return list(executor.map(fn, items))
  except Exception:
    return [fn(x) for x in items]


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


@st.cache_data(ttl=600, show_spinner=False)
def fetch_google_news_rss(query, max_items=60, max_age_hours=72):
  queries = [
    f"{query} when:3d",
    "S&P 500 Nasdaq stock market today when:3d",
    "Wall Street stocks earnings Federal Reserve when:3d",
    "US tech stocks semiconductors market news when:3d"
  ]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(lambda q: _fetch_rss_raw(q, 25, "MARKET", max_age_hours), queries, max_workers=2)
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]


@st.cache_data(ttl=600, show_spinner=False)
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


@st.cache_data(ttl=600, show_spinner=False)
def fetch_metals_crypto_fx_news(max_items=50, max_age_hours=72):
  queries = [
    ("gold silver copper prices commodities market when:3d", "METALS"),
    ("Bitcoin Ethereum Solana XRP crypto market when:3d", "CRYPTO"),
    ("US Dollar Index DXY USD JPY EUR USD forex when:3d", "FX/USD")
  ]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(lambda qt: _fetch_rss_raw(qt[0], 22, qt[1], max_age_hours), queries, max_workers=2)
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]


@st.cache_data(ttl=14400, show_spinner=False)
def fetch_upcoming_earnings_map(tickers):
  if not tickers:
    return {}
  out = {}
  now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

  def _check_one(sym):
    if any(ch in sym for ch in ["=X", "=F", "-USD", "^", "."]) or sym in NON_EQUITY_ETFS:
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

  for sym, res in _safe_parallel_map(_check_one, list(dict.fromkeys(tickers))[:35], max_workers=6):
    if res is not None:
      out[sym] = res
  return out


@st.cache_data(ttl=14400, show_spinner=False)
def fetch_batch_fundamental_scores(tickers_tuple):
  """Cached real fundamental quality scoring (0-100): Valuation vs Growth, ROE/Margins, Debt/Equity."""
  tickers_list = list(dict.fromkeys([str(t).strip().upper() for t in tickers_tuple if str(t).strip()]))
  if not tickers_list:
    return {}

  def _score_one(sym):
    if any(ch in sym for ch in ["=X", "=F", "-USD", "^", "."]) or sym in NON_EQUITY_ETFS:
      return sym, (75, "ETF/Macro Neutral")
    try:
      info = yf.Ticker(sym).info or {}
      q_type = str(info.get("quoteType", "")).upper()
      if q_type in ("ETF", "INDEX", "CRYPTOCURRENCY", "FUTURE", "CURRENCY"):
        return sym, (75, f"{q_type} Neutral")
      f_pe = info.get("forwardPE") or info.get("forwardPe")
      rev_g = info.get("revenueGrowth")
      earn_g = info.get("earningsGrowth")
      roe = info.get("returnOnEquity")
      op_m = info.get("operatingMargins")
      d_e = info.get("debtToEquity")

      # 1. Valuation vs Growth (0-35 pts)
      val_pts = 18
      growth_ref = earn_g if isinstance(earn_g, (int, float)) else (rev_g if isinstance(rev_g, (int, float)) else None)
      if isinstance(f_pe, (int, float)) and f_pe > 0:
        if growth_ref is not None and growth_ref > 0.02:
          peg_est = f_pe / (growth_ref * 100.0)
          if peg_est <= 1.2:
            val_pts = 35
          elif peg_est <= 2.0:
            val_pts = 28
          elif peg_est <= 3.2:
            val_pts = 20
          else:
            val_pts = 12
        else:
          if f_pe <= 18:
            val_pts = 28
          elif f_pe <= 30:
            val_pts = 22
          elif f_pe <= 50:
            val_pts = 14
          else:
            val_pts = 8
      elif isinstance(f_pe, (int, float)) and f_pe < 0:
        val_pts = 6
      elif isinstance(rev_g, (int, float)) and rev_g >= 0.25:
        val_pts = 22

      # 2. Profitability: ROE & Operating Margins (0-35 pts)
      prof_pts = 18
      sub_p = []
      if isinstance(roe, (int, float)):
        if roe >= 0.22:
          sub_p.append(35)
        elif roe >= 0.12:
          sub_p.append(27)
        elif roe >= 0.05:
          sub_p.append(18)
        elif roe >= 0.0:
          sub_p.append(12)
        else:
          sub_p.append(4)
      if isinstance(op_m, (int, float)):
        if op_m >= 0.22:
          sub_p.append(35)
        elif op_m >= 0.12:
          sub_p.append(27)
        elif op_m >= 0.04:
          sub_p.append(18)
        elif op_m >= 0.0:
          sub_p.append(11)
        else:
          sub_p.append(4)
      if sub_p:
        prof_pts = int(round(sum(sub_p) / len(sub_p)))

      # 3. Balance Sheet: Debt/Equity (0-30 pts)
      bs_pts = 18
      if isinstance(d_e, (int, float)):
        if d_e < 40:
          bs_pts = 30
        elif d_e < 90:
          bs_pts = 24
        elif d_e < 160:
          bs_pts = 15
        elif d_e < 250:
          bs_pts = 9
        else:
          bs_pts = 4

      total_sc = max(15, min(100, int(val_pts + prof_pts + bs_pts)))
      parts = []
      if isinstance(f_pe, (int, float)) and f_pe > 0:
        parts.append(f"FwdPE {f_pe:.1f}")
      if isinstance(op_m, (int, float)):
        parts.append(f"OpM {op_m*100:.0f}%")
      if isinstance(roe, (int, float)):
        parts.append(f"ROE {roe*100:.0f}%")
      if isinstance(d_e, (int, float)):
        parts.append(f"D/E {d_e:.0f}")
      note = " | ".join(parts) if parts else "Limited filings"
      return sym, (total_sc, note)
    except Exception:
      return sym, (65, "Fallback")

  out = {}
  for sym, val in _safe_parallel_map(_score_one, tickers_list[:60], max_workers=6):
    out[sym] = val
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

  # 30-Day Realized Volatility (annualized)
  try:
    rv_slice = close_arr[-31:] if n >= 31 else close_arr
    rv_slice = rv_slice[rv_slice > 0]
    if len(rv_slice) >= 10:
      log_rets = np.diff(np.log(rv_slice))
      rv30 = float(np.std(log_rets, ddof=1) * math.sqrt(252.0))
      rv30 = min(max(rv30, 0.08), 2.50)
    else:
      rv30 = 0.35
  except Exception:
    rv30 = 0.35

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
  g2 = delta.where(delta > 0, 0.0).ewm(alpha=1 / 2, adjust=False).mean()
  l2 = (-delta.where(delta < 0, 0.0)).ewm(alpha=1 / 2, adjust=False).mean()
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
    entry_ref = float(bos_level)
    effective_stop = max(min(tap3_price - (0.5 * atr14_1h_est), entry_ref * 0.98), entry_ref * 0.93)
    target_price = max(float(range_high), entry_ref + 2.0 * (entry_ref - effective_stop))
  elif is_stage2_higher_low:
    playbook_name = "Playbook 7: Stage 2 Higher Low"
    playbook_cat = "STAGE2_HL"
    bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
    entry_ref = float(bos_level)
    effective_stop = max(min(recent_pb_low - 0.35 * atr14_daily, sma150), entry_ref * 0.935)
    target_price = max(high_20d_curr * 1.03, entry_ref + 2.5 * (entry_ref - effective_stop))
  elif is_150ma_reversal_radar:
    playbook_name = "Playbook 8: 150-MA Reversal Radar"
    playbook_cat = "REVERSAL_150"
    bos_level = high_5d_prev if curr_close < high_5d_prev else curr_close
    entry_ref = float(bos_level)
    effective_stop = max(min(sma150 - 0.5 * atr14_daily, entry_ref * 0.975), entry_ref * 0.93)
    target_price = max(high_20d_curr * 1.02, entry_ref + 2.5 * (entry_ref - effective_stop))
  elif is_20d_breakout:
    playbook_name = "Playbook 2: 20D Momentum Breakout"
    playbook_cat = "BREAKOUT"
    bos_level = curr_close if curr_close >= high_20d_prev else high_20d_prev
    entry_ref = float(bos_level)
    effective_stop = max(min(ema20, entry_ref - 1.5 * atr14_daily), entry_ref * 0.94)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  elif is_gap_ignition:
    playbook_name = "Playbook 6: High-Vol Gap Ignition"
    playbook_cat = "BREAKOUT"
    bos_level = float(high_arr[-1]) if curr_close < high_arr[-1] else curr_close
    entry_ref = float(bos_level)
    effective_stop = max(float(low_arr[-1]) - 0.2 * atr14_daily, entry_ref * 0.94)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)
  elif is_squeeze_breakout:
    playbook_name = "Playbook 4: Volatility Squeeze Coil"
    playbook_cat = "SWING_PULLBACK"
    bos_level = curr_close if curr_close >= high_3d_prev else high_3d_prev
    entry_ref = float(bos_level)
    effective_stop = max(low_3d - 0.3 * atr14_daily, entry_ref * 0.95)
    target_price = entry_ref + 2.8 * (entry_ref - effective_stop)
  elif is_holy_grail_pullback:
    playbook_name = "Playbook 3: 20-EMA Pullback Swing"
    playbook_cat = "SWING_PULLBACK"
    bos_level = max(float(high_arr[-2]), curr_close) if curr_close < prev_close else curr_close
    entry_ref = float(bos_level)
    effective_stop = max(min(low_3d, ema20) - 0.5 * atr14_daily, entry_ref * 0.95)
    target_price = max(high_20d_prev * 1.02, entry_ref + 2.4 * (entry_ref - effective_stop))
  elif is_rsi2_snapback:
    playbook_name = f"Playbook 5: RSI-2 Oversold Bounce (RSI2={rsi2:.0f})"
    playbook_cat = "OVERSOLD"
    bos_level = curr_close
    entry_ref = float(bos_level)
    effective_stop = max(entry_ref - 1.5 * atr14_daily, entry_ref * 0.945)
    target_price = max(ema20, entry_ref + 2.0 * (entry_ref - effective_stop))
  else:
    playbook_name = "Standard Trend Swing"
    bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
    entry_ref = float(bos_level)
    effective_stop = max(min(entry_ref - 1.5 * atr14_daily, entry_ref * 0.978), entry_ref * 0.935)
    target_price = entry_ref + 2.5 * (entry_ref - effective_stop)

  risk_per_share = max(entry_ref - effective_stop, 0.0001)
  reward_per_share = max(target_price - entry_ref, 0.0)
  r_multiple = reward_per_share / risk_per_share
  bos_2d = round(float(bos_level), 2)
  tgt_2d = round(float(target_price), 2)
  stp_2d = round(float(effective_stop), 2)
  pot_reward = max(tgt_2d - bos_2d, 0.0)
  pot_risk = max(bos_2d - stp_2d, 0.01)
  potential_rr = int(((pot_reward / pot_risk) + 1e-9) * 100) / 100.0
  suggested_shares = max(1, int((account_size * 0.005) / risk_per_share))
  position_value = suggested_shares * entry_ref
  target_gain_pct = ((target_price - entry_ref) / entry_ref) * 100.0
  stop_loss_pct = ((effective_stop - entry_ref) / entry_ref) * 100.0
  crossed_5d = (curr_close >= high_5d_prev) and (prev_close < high_5d_prev)

  # Zero-emoji institutional signal pills
  if tct_valid_range and curr_close >= bos_level and r_multiple >= 1.9:
    act, badge, short_s, sig_bg, sig_fg, prio = "BUY NOW (TCT BOS)", "badge-tct-buy", "BUY TCT", "#0f5132", "#ffffff", 0
    expl = f"TCT accumulation breakout above BOS (${bos_level:,.2f}) targeting Range High (${target_price:,.2f})."
  elif is_stage2_higher_low:
    act, badge, short_s, sig_bg, sig_fg, prio = "STAGE 2 HIGHER LOW", "badge-tct-buy", "STAGE 2 HL", "#0f5132", "#ffffff", 0
    expl = f"Stage 2 Higher Low above rising 150-MA (${sma150:,.2f}); higher low at ${recent_pb_low:,.2f} > prior low (${prior_pb_low:,.2f})."
  elif is_20d_breakout or is_gap_ignition:
    act, badge, short_s, sig_bg, sig_fg, prio = "BUY NOW (BREAKOUT)", "badge-tct-buy", "BREAKOUT", "#0f5132", "#ffffff", 0
    expl = f"{playbook_name}: Breakout above ${bos_level:,.2f} on {paced_rvol:.1f}x pace volume."
  elif is_squeeze_breakout or is_holy_grail_pullback:
    act, badge, short_s, sig_bg, sig_fg, prio = "SWING BUY (PULLBACK/COIL)", "badge-tct-buy", "SWING BUY", "#047857", "#ffffff", 0
    expl = f"{playbook_name}: High-probability swing entry near ${entry_ref:,.2f}, stop ${effective_stop:,.2f}."
  elif is_150ma_reversal_radar:
    act, badge, short_s, sig_bg, sig_fg, prio = "150-MA REVERSAL RADAR", "badge-tct-watch", "150MA RADAR", "#fef3c7", "#92400e", 1
    expl = f"Reclaimed 150-Day MA (${sma150:,.2f}). Early trend reversal radar — monitor for Stage 2 Higher Low."
  elif is_rsi2_snapback:
    act, badge, short_s, sig_bg, sig_fg, prio = "OVERSOLD BOUNCE", "badge-tct-watch", "OVERSOLD", "#fef3c7", "#92400e", 1
    expl = f"RSI-2 extreme oversold ({rsi2:.0f}) above 200-EMA. Target bounce to ${target_price:,.2f}."
  elif tct_valid_range and curr_close < bos_level:
    act, badge, short_s, sig_bg, sig_fg, prio = "WATCHING TCT BOX", "badge-tct-watch", "TCT BOX", "#fef3c7", "#854d0e", 1
    expl = f"Valid 25+ bar TCT bottom box formed. Buy if price closes above BOS ${bos_level:,.2f}."
  elif is_pure_momentum:
    act, badge, short_s, sig_bg, sig_fg, prio = "MOMENTUM LEADER", "badge-rs-lead", "MOMENTUM", "#ecfdf5", "#065f46", 2
    expl = f"Institutional momentum leader (RS+, Price>20/50/200 EMA). Trailing stop ${effective_stop:,.2f}."
  elif curr_close > ema50 and (curr_close >= ema20 * 0.99 or crossed_5d):
    act, badge, short_s, sig_bg, sig_fg, prio = "HOLD / BUY DIP", "badge-trend", "UPTREND", "#dbeafe", "#1e3a8a", 2
    expl = f"Uptrend above 20 & 50 EMA. Swing target ${target_price:,.2f}, stop ${effective_stop:,.2f}."
  elif below_sma150 and not tct_valid_range and not is_rsi2_snapback:
    act, badge, short_s, sig_bg, sig_fg, prio = "CUT <150-MA", "badge-tct-sell", "CUT <150MA", "#991b1b", "#ffffff", 4
    expl = f"Stage 4 Warning: Below 150-day MA (${sma150:,.2f}). Cut loss / avoid until price reclaims 150-MA."
  elif curr_close < ema50 and not tct_valid_range and not is_rsi2_snapback:
    act, badge, short_s, sig_bg, sig_fg, prio = "BELOW 50-MA", "badge-tct-sell", "BELOW 50MA", "#fee2e2", "#991b1b", 4
    expl = f"Below 50-day EMA (${ema50:,.2f}) without a valid TCT bottom box. Protect capital."
  else:
    act, badge, short_s, sig_bg, sig_fg, prio = "WAIT FOR TRIGGER", "badge-candidate", "WAIT", "#fef9c3", "#854d0e", 3
    expl = f"Consolidating. Wait for a clean move above ${bos_level:,.2f} before entering."

  return {
    "TCT_Valid_Range": tct_valid_range, "TCT_Model": playbook_name, "Playbook_Cat": playbook_cat,
    "TCT_Slow_25": slow_decline_25, "TCT_Liq_50M": liq_pass, "TCT_2R_Pass": bool(r_multiple >= 2.0),
    "TCT_Action": act, "TCT_Badge": badge, "TCT_Short_Sig": short_s,
    "TCT_Sig_Bg": sig_bg, "TCT_Sig_Color": sig_fg,
    "TCT_Explain": expl, "TCT_Priority": prio, "BOS_Entry": entry_ref, "BOS_Level": bos_level,
    "Target_Price": target_price, "Stop_Price": effective_stop, "R_Multiple": r_multiple,
    "Potential_RR": potential_rr, "Pot_Reward": pot_reward, "Pot_Risk": pot_risk,
    "Target_Pct": target_gain_pct, "Stop_Pct": stop_loss_pct, "Shares_05Pct": suggested_shares,
    "Pos_Value": position_value, "Dollar_Vol_M": dollar_vol_20 / 1e6, "RS_Diff": rs_diff,
    "RS_Leader": rs_leader, "RSI2": rsi2, "Paced_RVOL": paced_rvol,
    "ATR14": atr14_daily, "RV30": rv30, "RV30_Pct": round(rv30 * 100.0, 1),
    "Is_Oversold_Swing": is_rsi2_snapback, "Is_Pure_Momentum": is_pure_momentum,
    "Is_Stage2_Higher_Low": is_stage2_higher_low, "Is_150MA_Reversal_Radar": is_150ma_reversal_radar,
    "Below_SMA150": below_sma150, "Is_BB_Squeeze": is_bb_squeeze
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
      if sym not in records:
        continue
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
        lines.append(f"+15% GAIN: {sym} reached ${live_price:,.2f}. Sell 50% ({int(pos['Shares'] * 0.5)} shs) and raise stop.")
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
        lines.append("150-MA REVERSAL RADAR: " + ", ".join(new_reversals[:6]))
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


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_batch_market_data_cached(clean_tickers_tuple, account_size=100000, w_fund_pct=40, w_tech_pct=40, w_mom_pct=20, refresh_bucket=0):
  clean_tickers = list(clean_tickers_tuple)
  if not clean_tickers:
    return {}
  download_list = list(dict.fromkeys(clean_tickers + ["^GSPC"]))
  try:
    data = yf.download(download_list, period="1y", interval="1d", group_by="ticker", progress=False)
    now_utc = datetime.now(timezone.utc)
    data_intraday = None
    if now_utc.hour in (13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 0, 1, 2, 3, 4, 5, 6):
      try:
        data_intraday = yf.download(clean_tickers[:60], period="5d", interval="15m", group_by="ticker", progress=False)
      except Exception:
        data_intraday = None
  except Exception:
    return {}

  fund_scores_map = fetch_batch_fundamental_scores(tuple(clean_tickers[:60]))

  spy_ret_63d = 0.0
  try:
    spy_df = _extract_ticker_df(data, "^GSPC", len(download_list)).dropna(subset=["Close"])
    if len(spy_df) >= 64:
      spy_ret_63d = ((float(spy_df["Close"].iloc[-1]) - float(spy_df["Close"].iloc[-64])) / float(spy_df["Close"].iloc[-64])) * 100.0
  except Exception:
    pass

  w_fund, w_tech, w_mom = w_fund_pct / 100.0, w_tech_pct / 100.0, w_mom_pct / 100.0
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
        state, badge_class, reason = "Confirmed Breakout", "badge-breakout", f"Closed above 20D high (${high20_prev:,.2f}) on {pb_info['Paced_RVOL']:.1f}x volume"
      elif above_ema50 and close > ema20_val:
        state, badge_class, reason = "Active Trend", "badge-trend", "Holding above 20-day & 50-day EMA support"
      elif close < ema50_val:
        state, badge_class, reason = "Support Break", "badge-caution", "Violated 50-day EMA support level"
      else:
        state, badge_class, reason = "Entry Candidate", "badge-candidate", "Consolidating below resistance"
      fund_score, fund_note = fund_scores_map.get(t, (70, "Cached"))
      tech_score = (30 if above_ema50 else 0) + (40 if 45 <= rsi <= 70 else 10) + (30 if pb_info["Paced_RVOL"] >= 1.2 else 10)
      mom_score = (50 if is_breakout else 15) + (50 if within_52w else 20)
      composite = int((fund_score * w_fund) + (tech_score * w_tech) + (mom_score * w_mom))
      record = {
        "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
        "Day_High": day_high, "Day_Low": day_low, "RSI": rsi, "RVOL": rvol,
        "EMA20_Val": ema20_val, "EMA50_Val": ema50_val, "EMA150_Val": ema150_val, "SMA150_Val": sma150_val,
        "MACD_Above_Zero": macd_above_zero, "MACD_Cross": macd_cross,
        "Above_EMA50": above_ema50, "Above_EMA200": above_ema200,
        "Is_Breakout": is_breakout, "Pullback_EMA50": pullback_ema,
        "Within_52W": within_52w, "State": state, "Badge": badge_class,
        "Reason": reason, "Score": composite,
        "Fund_Score": fund_score, "Fund_Note": fund_note,
        "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
      }
      record.update(pb_info)
      results[t] = record
    except Exception:
      continue
  return results


def fetch_batch_market_data(tickers, account_size=100000, refresh_bucket=0):
  clean_tickers = [str(t).strip().upper() for t in tickers if str(t).strip()]
  pos_tickers = [str(p["Ticker"]).strip().upper() for p in positions if str(p.get("Ticker")).strip()]
  opt_tickers = [str(op["Ticker"]).strip().upper() for op in options_positions if str(op.get("Ticker")).strip()]
  clean_tickers = list(dict.fromkeys(clean_tickers + pos_tickers + opt_tickers))
  if not clean_tickers:
    return {}
  results = _fetch_batch_market_data_cached(
    tuple(clean_tickers),
    account_size=account_size,
    w_fund_pct=int(settings.get("w_fund", 40)),
    w_tech_pct=int(settings.get("w_tech", 40)),
    w_mom_pct=int(settings.get("w_mom", 20)),
    refresh_bucket=refresh_bucket
  )
  if results:
    if "last_good_data" in st.session_state:
      st.session_state.last_good_data.update(results)
    check_and_fire_live_ntfy(results)
    check_and_fire_active_position_alerts(results)
    return results
  return {k: v for k, v in st.session_state.get("last_good_data", {}).items() if k in clean_tickers}


@st.cache_data(ttl=180, show_spinner=False)
def _fetch_single_ticker_history_cached(sym, period="5y", interval="1d"):
  try:
    t = yf.Ticker(sym)
    df = t.history(period=period, interval=interval)
    if df is None or df.empty or len(df) < 10:
      return None, None
    try:
      df_1h = t.history(period="1mo", interval="1h")
    except Exception:
      df_1h = None
    return df, df_1h
  except Exception:
    return None, None


def fetch_single_ticker_data(sym, account_size=100000, period="5y", interval="1d"):
  res = fetch_batch_market_data([sym], account_size=account_size)
  base_rec = res.get(sym) if sym in res else None
  if period == "1y" and interval == "1d" and base_rec is not None and "EMA150" in base_rec["History"].columns:
    return base_rec
  df_raw, df_1h = _fetch_single_ticker_history_cached(sym, period=period, interval=interval)
  if (df_raw is None or df_raw.empty or len(df_raw) < 20) and base_rec is not None:
    return base_rec
  if df_raw is None or df_raw.empty or len(df_raw) < 10:
    return None
  try:
    df = df_raw.copy()
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
    f_map = fetch_batch_fundamental_scores((sym,))
    f_sc, f_nt = f_map.get(sym, (70, "Cached"))
    rec = {
      "Ticker": sym, "Price": close, "Change": close - prev_close,
      "Change_Pct": ((close - prev_close) / prev_close) * 100 if prev_close else 0,
      "Day_High": float(df["High"].iloc[-1]), "Day_Low": float(df["Low"].iloc[-1]),
      "RSI": float(df["RSI"].iloc[-1]), "RVOL": 1.0,
      "EMA20_Val": float(df["EMA20"].iloc[-1]), "EMA50_Val": float(df["EMA50"].iloc[-1]),
      "EMA150_Val": float(df["EMA150"].iloc[-1]), "SMA150_Val": float(df["SMA150"].iloc[-1]),
      "State": "Active Trend", "Badge": "badge-trend", "Reason": pb_info["TCT_Explain"],
      "Score": int(f_sc * 0.4 + 48), "Fund_Score": f_sc, "Fund_Note": f_nt, "History": df
    }
    rec.update(pb_info)
    return rec
  except Exception:
    return base_rec


@st.cache_data(ttl=14400, show_spinner=False)
def fetch_ticker_fundamentals(ticker_symbol):
  data = {
    "Company Name": ticker_symbol, "Market Cap": "N/A", "Trailing P/E": "N/A",
    "Forward P/E": "N/A", "EPS (TTM)": "N/A", "Target Price": "N/A",
    "52W High": "N/A", "52W Low": "N/A", "All-Time High": "N/A", "All-Time Low": "N/A",
    "Earnings Date": "No upcoming (60d)", "Debt/Equity": "N/A",
    "ROE": "N/A", "Operating Margin": "N/A",
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
    data["ROE"] = info.get("returnOnEquity", "N/A")
    data["Operating Margin"] = info.get("operatingMargins", "N/A")
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
  fig.update_layout(height=40, width=110, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
  return fig


def _render_news_box(articles, show_ticker=True):
  items_html = []
  for a in articles:
    t_badge = f'<span class="ticker-news-badge">{a.get("ticker", "NEWS")}</span>' if show_ticker else ''
    items_html.append(
      f'<div style="background:white;border:1px solid #e2dcd0;border-radius:6px;padding:8px 12px;margin-bottom:6px;">'
      f'<div style="display:flex;justify-content:space-between;font-size:0.70rem;color:#64748b;">'
      f'<span style="font-weight:600;color:#0f291e;">{t_badge}{a["publisher"]}'
      f'<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div>'
      f'<div style="font-weight:600;font-size:0.86rem;margin-top:3px;">'
      f'<a href="{a["link"]}" target="_blank" style="color:#0f291e;text-decoration:none;">'
      f'{a["title"]}</a></div></div>'
    )
  st.markdown('<div class="scroll-news-box">' + "".join(items_html) + '</div>', unsafe_allow_html=True)


def render_watchlist_reorder_panel(folder_name, key_prefix="wl"):
  st.markdown('<div style="background:#ffffff;border:1px solid #dcd6cb;border-radius:6px;padding:10px 14px;margin-bottom:10px;">', unsafe_allow_html=True)
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
    st.info("This watchlist is currently empty. Add a stock symbol above.")
  else:
    e_col1, e_col2 = st.columns(2)
    half = (len(syms) + 1) // 2
    for i, s in enumerate(syms):
      with (e_col1 if i < half else e_col2):
        r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
        r1.markdown(f"**{i + 1}. {s}**")
        if r2.button("Top", key=f"{key_prefix}_top_{folder_name}_{s}_{i}", disabled=(i == 0)):
          syms.pop(i); syms.insert(0, s); save_json(DATA_FILE, watchlists); st.rerun()
        if r3.button("Up", key=f"{key_prefix}_up_{folder_name}_{s}_{i}", disabled=(i == 0)):
          syms[i - 1], syms[i] = syms[i], syms[i - 1]; save_json(DATA_FILE, watchlists); st.rerun()
        if r4.button("Dn", key=f"{key_prefix}_dn_{folder_name}_{s}_{i}", disabled=(i == len(syms) - 1)):
          syms[i + 1], syms[i] = syms[i], syms[i + 1]; save_json(DATA_FILE, watchlists); st.rerun()
        if r5.button("Del", key=f"{key_prefix}_del_{folder_name}_{s}_{i}"):
          syms.pop(i); sync_file_to_github(watchlists, DATA_FILE); st.rerun()
  st.markdown('</div>', unsafe_allow_html=True)


# --- COMPLETE BLACK-SCHOLES GREEKS (DELTA, GAMMA, THETA, VEGA) & OPTIONS ANALYTICS ---
def _norm_cdf(x):
  return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
  return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_greeks(S, K, T_years, r=0.045, sigma=0.40, opt_type="CALL"):
  S = max(float(S), 0.01)
  K = max(float(K), 0.01)
  T = max(float(T_years), 1.0 / 365.0)
  iv = float(sigma) if (sigma and not np.isnan(sigma) and float(sigma) > 0.05) else 0.40
  iv = min(max(iv, 0.08), 3.00)
  sqrt_T = math.sqrt(T)
  d1 = (math.log(S / K) + (r + 0.5 * iv * iv) * T) / (iv * sqrt_T)
  d2 = d1 - iv * sqrt_T
  pdf_d1 = _norm_pdf(d1)
  gamma = pdf_d1 / (S * iv * sqrt_T)
  vega_1pct = (S * pdf_d1 * sqrt_T) / 100.0
  is_put = str(opt_type).upper().startswith("P")
  if is_put:
    delta = _norm_cdf(d1) - 1.0
    theo = K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)
    theta_annual = -(S * pdf_d1 * iv) / (2.0 * sqrt_T) + r * K * math.exp(-r * T) * _norm_cdf(-d2)
    intrinsic = max(K - S, 0.0)
  else:
    delta = _norm_cdf(d1)
    theo = S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    theta_annual = -(S * pdf_d1 * iv) / (2.0 * sqrt_T) - r * K * math.exp(-r * T) * _norm_cdf(d2)
    intrinsic = max(S - K, 0.0)
  theta_daily = theta_annual / 365.0
  return {
    "price": max(theo, intrinsic, 0.01),
    "delta": float(delta),
    "gamma": float(gamma),
    "theta": float(theta_daily),
    "vega": float(vega_1pct),
    "intrinsic": float(intrinsic)
  }


def _extract_contract_metrics(row, S, K, T_years, opt_type="CALL", rv30=0.38):
  bid = float(row.get("bid", 0.0) or 0.0)
  ask = float(row.get("ask", 0.0) or 0.0)
  last_p = float(row.get("lastPrice", 0.0) or 0.0)
  raw_iv = float(row.get("impliedVolatility", 0.0) or 0.0)
  fallback_iv = float(rv30) if (rv30 and 0.08 <= float(rv30) <= 2.50) else 0.38
  iv = raw_iv if (0.06 <= raw_iv <= 3.5) else fallback_iv
  gk = _bs_greeks(S, K, T_years, r=0.045, sigma=iv, opt_type=opt_type)
  if bid > 0 and ask > 0:
    mid = 0.5 * (bid + ask)
    spread_pct = ((ask - bid) / max(mid, 0.01)) * 100.0
  elif last_p > 0:
    mid = last_p
    spread_pct = 99.0 if (bid <= 0 or ask <= 0) else ((ask - bid) / max(mid, 0.01)) * 100.0
  else:
    mid = gk["price"]
    spread_pct = 99.0
  intrinsic = gk["intrinsic"]
  mid = max(mid, intrinsic, 0.05)
  extrinsic = max(mid - intrinsic, 0.0)
  raw_vol = row.get("volume", 0)
  raw_oi = row.get("openInterest", 0)
  vol = int(raw_vol) if (raw_vol is not None and not np.isnan(raw_vol)) else 0
  oi = int(raw_oi) if (raw_oi is not None and not np.isnan(raw_oi)) else 0
  vol_oi = round(vol / max(oi, 1), 2) if vol > 0 else 0.0
  iv_rv_ratio = round(iv / max(fallback_iv, 0.08), 2)
  return {
    "Bid": round(bid, 2),
    "Ask": round(ask, 2),
    "Last": round(last_p, 2),
    "Mid": round(mid, 2),
    "Spread_Pct": round(spread_pct, 1),
    "IV_Pct": round(iv * 100.0, 1),
    "IV_Raw": iv,
    "RV30_Pct": round(fallback_iv * 100.0, 1),
    "IV_RV": iv_rv_ratio,
    "Delta": round(gk["delta"], 3),
    "Gamma": round(gk["gamma"], 4),
    "Theta": round(gk["theta"], 3),
    "Vega": round(gk["vega"], 3),
    "Intrinsic": round(intrinsic, 2),
    "Extrinsic": round(extrinsic, 2),
    "Extrinsic_Pct": round((extrinsic / S) * 100.0, 2) if S > 0 else 0.0,
    "Volume": vol,
    "OpenInterest": oi,
    "Vol_OI": vol_oi
  }


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_live_option_contract_quote_cached(sym, exp_str, strike_val, opt_type, stock_price, rv30=0.38, refresh_bucket=0):
  now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
  try:
    dt_e = datetime.strptime(str(exp_str)[:10], "%Y-%m-%d")
    dte = max(0, (dt_e - now_dt).days)
  except Exception:
    dte = 30
  T_yrs = max(dte / 365.0, 1.0 / 365.0)
  K = float(strike_val)
  S = float(stock_price)
  try:
    tk = yf.Ticker(sym)
    if str(exp_str)[:10] in (tk.options or []):
      ch = tk.option_chain(str(exp_str)[:10])
      df_side = ch.puts if str(opt_type).upper().startswith("P") else ch.calls
      if df_side is not None and not df_side.empty:
        sub = df_side.iloc[(df_side["strike"] - K).abs().argsort()[:1]]
        if not sub.empty:
          row = sub.iloc[0]
          m_info = _extract_contract_metrics(row, S, float(row["strike"]), T_yrs, opt_type, rv30=rv30)
          m_info["DTE"] = dte
          return m_info
  except Exception:
    pass
  iv_use = float(rv30) if (rv30 and 0.08 <= float(rv30) <= 2.50) else 0.38
  gk = _bs_greeks(S, K, T_yrs, r=0.045, sigma=iv_use, opt_type=opt_type)
  return {
    "Bid": round(gk["price"] * 0.97, 2),
    "Ask": round(gk["price"] * 1.03, 2),
    "Last": round(gk["price"], 2),
    "Mid": round(gk["price"], 2),
    "Spread_Pct": 6.0,
    "IV_Pct": round(iv_use * 100.0, 1),
    "IV_Raw": iv_use,
    "RV30_Pct": round(iv_use * 100.0, 1),
    "IV_RV": 1.0,
    "Delta": round(gk["delta"], 3),
    "Gamma": round(gk["gamma"], 4),
    "Theta": round(gk["theta"], 3),
    "Vega": round(gk["vega"], 3),
    "DTE": dte
  }


def compute_unified_portfolio_risk(stock_data_map):
  """Computes combined Stocks + Options Net Delta Exposure ($) and Daily Options Theta Bleed ($/day)."""
  stock_delta_usd = 0.0
  for p in positions:
    sym = p["Ticker"]
    px = float(stock_data_map.get(sym, {}).get("Price", p["BuyPrice"]))
    stock_delta_usd += int(p["Shares"]) * px

  opt_delta_usd = 0.0
  opt_theta_daily_usd = 0.0
  opt_vega_usd = 0.0
  opt_quotes = {}
  bucket_120 = int(time.time() // 120)

  def _q_one(op):
    s_tk = op["Ticker"]
    s_rec = stock_data_map.get(s_tk, {})
    s_px = float(s_rec.get("Price", op.get("Stock_Entry", 100.0)))
    rv30 = float(s_rec.get("RV30", 0.38))
    q = _fetch_live_option_contract_quote_cached(
      s_tk, op["Expiration"], op["Strike"], op["Option_Type"], s_px, rv30=rv30, refresh_bucket=bucket_120
    )
    return op["id"], s_px, op, q

  for op_id, s_px, op, q in _safe_parallel_map(_q_one, options_positions, max_workers=6):
    opt_quotes[op_id] = q
    qty = int(op.get("Contracts", 1))
    opt_delta_usd += qty * 100.0 * float(q.get("Delta", 0.0)) * s_px
    opt_theta_daily_usd += qty * 100.0 * float(q.get("Theta", 0.0))
    opt_vega_usd += qty * 100.0 * float(q.get("Vega", 0.0))

  return {
    "stock_delta_usd": stock_delta_usd,
    "opt_delta_usd": opt_delta_usd,
    "net_delta_usd": stock_delta_usd + opt_delta_usd,
    "opt_theta_daily_usd": opt_theta_daily_usd,
    "opt_vega_usd": opt_vega_usd,
    "opt_quotes": opt_quotes
  }


def render_unified_portfolio_risk_strip(stock_data_map):
  risk = compute_unified_portfolio_risk(stock_data_map)
  net_d = risk["net_delta_usd"]
  st_d = risk["stock_delta_usd"]
  op_d = risk["opt_delta_usd"]
  th_d = risk["opt_theta_daily_usd"]
  vg_d = risk["opt_vega_usd"]
  acc_sz = max(float(settings.get("account_size", 100000)), 1.0)
  net_lev = net_d / acc_sz
  th_clr = "#f87171" if th_d < 0 else "#4ade80"
  op_d_clr = "#4ade80" if op_d >= 0 else "#f87171"
  st.markdown(
    f'<div class="risk-strip">'
    f'<div><div class="risk-item-lbl">Combined Net Delta ($)</div>'
    f'<div class="risk-item-val">${net_d:+,.0f}</div>'
    f'<div class="risk-item-sub">{net_lev:.2f}x Account Size</div></div>'
    f'<div><div class="risk-item-lbl">Stocks Delta ($)</div>'
    f'<div class="risk-item-val">${st_d:,.0f}</div>'
    f'<div class="risk-item-sub">{len(positions)} Open Stock Positions</div></div>'
    f'<div><div class="risk-item-lbl">Options Net Delta ($)</div>'
    f'<div class="risk-item-val" style="color:{op_d_clr};">${op_d:+,.0f}</div>'
    f'<div class="risk-item-sub">{len(options_positions)} Open Option Contracts</div></div>'
    f'<div><div class="risk-item-lbl">Daily Theta Bleed</div>'
    f'<div class="risk-item-val" style="color:{th_clr};">${th_d:+,.2f} / day</div>'
    f'<div class="risk-item-sub">Weekly est: ${th_d * 7:+,.0f}</div></div>'
    f'<div><div class="risk-item-lbl">Options Net Vega</div>'
    f'<div class="risk-item-val">${vg_d:+,.1f} / 1% IV</div>'
    f'<div class="risk-item-sub">Portfolio IV Sensitivity</div></div>'
    f'</div>',
    unsafe_allow_html=True
  )
  return risk


# --- ACTIVE POSITIONS MANAGER ---
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
  opt_syms = [op["Ticker"] for op in options_positions]
  all_syms = list(dict.fromkeys(pos_syms + opt_syms))
  data_dict = fetch_batch_market_data(all_syms, account_size=settings["account_size"]) if all_syms else {}
  render_unified_portfolio_risk_strip(data_dict)

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
        st.success(f"Logged {new_pos_shs} shs of {new_pos_sym} @ ${new_pos_px:,.2f}.")
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
      c_p1, c_p2, c_p3 = st.columns([1.5, 4.7, 1.8])
      with c_p1:
        st.markdown(
          f"**<a href='?inspect={sym}' target='_self' class='ticker-link'>{sym}</a>**<br>"
          f"<span class='num' style='font-size:1.2rem;font-weight:800;'>${live_price:,.2f}</span> "
          f"<span class='num' style='font-size:0.78rem;color:{clr_day};font-weight:700;'>({day_pct:+.2f}%)</span><br>"
          f"<span style='font-size:0.72rem;color:#64748b;'>Bought: {p.get('BuyDate', 'N/A')}</span>",
          unsafe_allow_html=True
        )
      with c_p2:
        st.markdown(
          f"<div style='display:flex;justify-content:space-between;padding:6px 10px;background:#ffffff;border-radius:6px;border:1px solid #e2dcd0;font-variant-numeric:tabular-nums;'>"
          f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Avg Cost & Size</span><br><b>${bp:,.2f}</b> <span style='font-size:0.74rem;'>({shares} shs)</span></div>"
          f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Stop-Loss</span><br><b style='color:#dc2626;'>${p['StopLoss']:,.2f}</b></div>"
          f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>+15% Target</span><br><b style='color:#059669;'>${p['Target15']:,.2f}</b></div>"
          f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Today's Gain</span><br><b style='color:{clr_day};'>${pos_day_pnl:+,.2f}</b></div>"
          f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Unrealized P&L</span><br><b style='color:{clr_pnl};'>${pnl:+,.2f} ({pnl_pct:+.2f}%)</b></div>"
          f"</div>"
          f"<div style='font-size:0.76rem;color:#334155;margin-top:4px;'><b>Thesis:</b> <i>{rmk_str}</i> | <b>20-EMA:</b> ${ema20:,.2f}</div>",
          unsafe_allow_html=True
        )
        if live_price <= p["StopLoss"]:
          st.error(f"STOP-LOSS HIT: {sym} (${live_price:,.2f}) is at/below your stop (${p['StopLoss']:,.2f}).")
        elif live_price >= p["Target15"] and not p.get("HalfSold", False):
          st.warning(f"+15% Target Reached. Open Manage Trade to Sell 50% ({max(1, shares // 2)} shs), lock profit stop, or add.")
        elif live_price < ema20:
          st.error(f"Trailing Warning: {sym} dropped below its 20-day EMA (${ema20:,.2f}).")
      with c_p3:
        with st.popover("Manage Trade", use_container_width=True):
          st.markdown(f"**Manage `{sym}` ({shares} shs @ ${bp:,.2f})**")
          t_sell, t_trail, t_add, t_close = st.tabs(["Sell/Trim", "Trail Stop", "Add Batch", "Note/Close"])
          with t_sell:
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
            add_shs = st.number_input("Added Shares", min_value=1, value=max(10, shares // 2), step=5, key=f"{key_prefix}_ashs_{p['id']}")
            add_px = st.number_input("Add Buy Price ($)", min_value=0.01, value=float(round(live_price, 2)), step=0.5, key=f"{key_prefix}_apx_{p['id']}")
            new_tot_shs = shares + add_shs
            new_avg_bp = ((shares * bp) + (add_shs * add_px)) / new_tot_shs
            st.info(f"New Blended Cost: `${new_avg_bp:,.2f}` ({new_tot_shs} total shs)")
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
      st.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)
  else:
    st.info("No active positions currently open. Use Log a New Position above to start tracking.")

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


# --- 5 OPTION SAMURAI PRESETS (PARALLEL ENGINE + SCENARIO OPTIMIZER + EARNINGS GUARD) ---
def log_options_ledger_entry(action_type, ticker, opt_type, exp_str, strike, contracts, buy_prem, sell_prem, pnl_dollar, pnl_pct, opt_stop, stock_stop, remarks, dt_str=None):
  entry = {
    "Date": dt_str or datetime.now().strftime("%Y-%m-%d"),
    "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
    "Action": action_type,
    "Ticker": ticker,
    "Option_Type": opt_type,
    "Expiration": str(exp_str)[:10],
    "Strike": round(float(strike), 2),
    "Contracts": int(contracts),
    "Buy_Premium": round(float(buy_prem), 2),
    "Sell_Or_Live_Premium": round(float(sell_prem), 2) if sell_prem is not None else round(float(buy_prem), 2),
    "Gain_Loss_USD": round(float(pnl_dollar), 2) if pnl_dollar is not None else 0.0,
    "Gain_Loss_Pct": round(float(pnl_pct), 2) if pnl_pct is not None else 0.0,
    "Option_Stop": round(float(opt_stop), 2) if opt_stop is not None else 0.0,
    "Stock_Stop": round(float(stock_stop), 2) if stock_stop is not None else 0.0,
    "Remarks": str(remarks or "").strip()
  }
  options_ledger.append(entry)
  sync_file_to_github(options_ledger, OPTIONS_LEDGER_FILE)


@st.cache_data(ttl=300, show_spinner=False)
def _scan_single_ticker_option_presets(
  sym, stock_price, target_price, stop_price, sma150, ema50, atr14, rv30,
  playbook_cat, tct_action, below_sma150, is_stage2_hl, is_squeeze,
  earnings_days=None, scenario_days=14, custom_target=None
):
  """Scans a single ticker's liquid option chains across all 5 Option Samurai presets (no put-selling/wheel)."""
  candidates = []
  try:
    tk = yf.Ticker(sym)
    exp_list = list(tk.options or [])
    if not exp_list:
      return candidates
    now_dt = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    exp_with_dte = []
    for e_str in exp_list:
      try:
        dte = (datetime.strptime(e_str, "%Y-%m-%d") - now_dt).days
        if dte >= 4:
          exp_with_dte.append((dte, e_str))
      except Exception:
        continue
    if not exp_with_dte:
      return candidates

    # Pick targeted expirations: 1 LEAPS (270-540 DTE), 2 short/medium (14-45 DTE & ~60-90 DTE)
    chosen_exps = []
    leaps_pool = [x for x in exp_with_dte if 270 <= x[0] <= 540]
    if not leaps_pool:
      leaps_pool = [x for x in exp_with_dte if x[0] >= 180]
    if leaps_pool:
      chosen_exps.append(sorted(leaps_pool, key=lambda x: abs(x[0] - 365))[0])

    short_pool = [x for x in exp_with_dte if 14 <= x[0] <= 45]
    if not short_pool:
      short_pool = [x for x in exp_with_dte if 7 <= x[0] <= 60]
    if short_pool:
      s1 = sorted(short_pool, key=lambda x: abs(x[0] - 25))[0]
      chosen_exps.append(s1)
      s2_pool = [x for x in short_pool if x[1] != s1[1]]
      if s2_pool:
        chosen_exps.append(sorted(s2_pool, key=lambda x: abs(x[0] - 42))[0])

    med_pool = [x for x in exp_with_dte if 50 <= x[0] <= 120]
    if med_pool:
      chosen_exps.append(sorted(med_pool, key=lambda x: abs(x[0] - 75))[0])

    seen_e = set()
    uniq_exps = []
    for dte, e_s in chosen_exps:
      if e_s not in seen_e:
        seen_e.add(e_s)
        uniq_exps.append((dte, e_s))

    eff_target = float(custom_target) if (custom_target and float(custom_target) > 0) else float(target_price)
    bear_target = min(float(stop_price) * 0.94, stock_price * 0.90)
    bear_stop = max(float(ema50) * 1.02, stock_price * 1.04)

    for dte, e_str in uniq_exps:
      try:
        ch = tk.option_chain(e_str)
      except Exception:
        continue
      T_yr = max(dte / 365.0, 2.0 / 365.0)
      calls_df = ch.calls if (ch and ch.calls is not None) else pd.DataFrame()
      puts_df = ch.puts if (ch and ch.puts is not None) else pd.DataFrame()

      # Preset 5: Earnings Expected-Move Guard (ATM Straddle Implied Move)
      earn_in_dte = (earnings_days is not None and 0 <= int(earnings_days) <= dte)
      implied_move_pct = None
      if earn_in_dte and not calls_df.empty and not puts_df.empty:
        try:
          ac = calls_df.iloc[(calls_df["strike"] - stock_price).abs().argsort()[:1]].iloc[0]
          ap = puts_df.iloc[(puts_df["strike"] - stock_price).abs().argsort()[:1]].iloc[0]
          cm = _extract_contract_metrics(ac, stock_price, float(ac["strike"]), T_yr, "CALL", rv30=rv30)["Mid"]
          pm = _extract_contract_metrics(ap, stock_price, float(ap["strike"]), T_yr, "PUT", rv30=rv30)["Mid"]
          implied_move_pct = round(((cm + pm) / stock_price) * 100.0, 1)
        except Exception:
          pass
      earn_guard_str = f"EARN {int(earnings_days)}d (+/-{implied_move_pct:.1f}%)" if (earn_in_dte and implied_move_pct) else (f"EARN {int(earnings_days)}d" if earn_in_dte else "Clear")

      # Helper to build candidate row
      def _eval_side(df_side, opt_type):
        if df_side is None or df_side.empty:
          return
        is_call = (opt_type == "CALL")
        k_min = stock_price * (0.40 if dte >= 180 and is_call else 0.84)
        k_max = stock_price * (1.16 if is_call else 1.14)
        sub_df = df_side[(df_side["strike"] >= k_min) & (df_side["strike"] <= k_max)]
        for _, rw in sub_df.iterrows():
          K = float(rw.get("strike", 0.0) or 0.0)
          if K <= 0:
            continue
          m = _extract_contract_metrics(rw, stock_price, K, T_yr, opt_type, rv30=rv30)
          abs_d = abs(m["Delta"])
          if abs_d < 0.25 or abs_d > 0.94:
            continue
          mid = m["Mid"]
          be = round(K + mid, 2) if is_call else round(K - mid, 2)
          be_dist = abs(be - stock_price)
          ann_fin_cost = round(((m["Extrinsic"] / max(K, 0.01)) * (365.0 / max(dte, 1))) * 100.0, 2) if is_call else 0.0

          # Scenario P/L Projection (Preset 4)
          hold_d = min(max(int(scenario_days), 2), max(dte - 1, 1))
          T_scen = max((dte - hold_d) / 365.0, 1.0 / 365.0)
          scen_tgt_s = eff_target if is_call else bear_target
          scen_stp_s = float(stop_price) if is_call else bear_stop
          proj_tgt = _bs_greeks(scen_tgt_s, K, T_scen, r=0.045, sigma=m["IV_Raw"], opt_type=opt_type)["price"]
          proj_stp = _bs_greeks(scen_stp_s, K, max((dte - min(hold_d, 5)) / 365.0, 1.0 / 365.0), r=0.045, sigma=m["IV_Raw"], opt_type=opt_type)["price"]
          if dte <= 60:
            proj_stp = min(proj_stp, mid * 0.72)
          proj_ret_pct = round(((proj_tgt - mid) / max(mid, 0.05)) * 100.0, 1)
          opt_risk = max(mid - proj_stp, mid * 0.10, 0.05)
          opt_reward = max(proj_tgt - mid, 0.01)
          opt_rr = round(opt_reward / opt_risk, 2)
          share_ret_pct = abs((scen_tgt_s - stock_price) / max(stock_price, 0.01)) * 100.0
          lev_vs_shares = round(proj_ret_pct / max(share_ret_pct, 0.5), 2)

          # Classify into the 5 Option Samurai Presets
          presets_hit = []

          # 1. LEAPS Stock Replacement
          if (
            is_call and (270 <= dte <= 540) and (0.83 <= m["Delta"] <= 0.91)
            and (m["Extrinsic_Pct"] <= 6.5) and (m["Spread_Pct"] <= 5.5)
            and (m["OpenInterest"] >= 100) and (not below_sma150)
          ):
            presets_hit.append("LEAPS Stock Replacement")

          # 2. Cheap Volatility Directional (IV < RV)
          bull_dir = (not below_sma150) and (is_stage2_hl or is_squeeze or playbook_cat in ("STAGE2_HL", "SWING_PULLBACK", "BREAKOUT", "TCT"))
          bear_dir = below_sma150 or (stock_price < ema50)
          if (
            (14 <= dte <= 45) and (0.45 <= abs_d <= 0.65)
            and (m["IV_RV"] < 1.0) and (m["Spread_Pct"] <= 10.0)
            and ((is_call and bull_dir) or ((not is_call) and bear_dir))
          ):
            presets_hit.append("Cheap Vol Directional (IV<RV)")

          # 3. Unusual Options Volume / Smart Money
          if (
            (m["Volume"] > 500) and (m["Vol_OI"] > 1.5)
            and (be_dist <= max(1.5 * atr14, stock_price * 0.03))
          ):
            presets_hit.append("Unusual Volume / Smart Money")

          # 4. Stock Scenario Optimizer (liquid directional contracts)
          if (
            (m["Spread_Pct"] <= 12.0) and (m["OpenInterest"] >= 20 or m["Volume"] >= 20)
            and (proj_ret_pct >= 15.0) and (opt_rr >= 1.5)
            and ((is_call and not below_sma150) or ((not is_call) and bear_dir))
          ):
            presets_hit.append("Scenario Optimizer")

          # 5. Earnings Expected-Move Guard (flags liquid short-term contracts straddling earnings)
          if earn_in_dte and (0.40 <= abs_d <= 0.65) and (m["Spread_Pct"] <= 12.0):
            presets_hit.append("Earnings Guard")

          if not presets_hit:
            continue

          # Composite rank score per preset
          rank_score = (
            (30.0 if "LEAPS Stock Replacement" in presets_hit else 0.0)
            + (26.0 if "Cheap Vol Directional (IV<RV)" in presets_hit else 0.0)
            + (24.0 if "Unusual Volume / Smart Money" in presets_hit else 0.0)
            + min(opt_rr, 6.0) * 6.0
            + min(max(proj_ret_pct, 0.0), 150.0) * 0.15
            - min(m["Spread_Pct"], 20.0) * 1.2
            - (12.0 if (earn_in_dte and dte <= 45 and "LEAPS Stock Replacement" not in presets_hit) else 0.0)
          )
          candidates.append({
            "Ticker": sym,
            "Preset": " | ".join([p for p in presets_hit if p != "Earnings Guard"][:2]) or "Earnings Guard",
            "Presets_List": presets_hit,
            "Type": opt_type,
            "Exp": e_str,
            "DTE": dte,
            "Strike": round(K, 2),
            "Stock_Px": round(stock_price, 2),
            "Mid": m["Mid"],
            "Bid": m["Bid"],
            "Ask": m["Ask"],
            "Spread_%": m["Spread_Pct"],
            "Cost_1x": round(m["Mid"] * 100.0, 0),
            "Delta": m["Delta"],
            "Gamma": m["Gamma"],
            "Theta/d": m["Theta"],
            "Vega": m["Vega"],
            "IV_%": m["IV_Pct"],
            "RV30_%": m["RV30_Pct"],
            "IV/RV": m["IV_RV"],
            "Ext_%": m["Extrinsic_Pct"],
            "AnnFin_%": ann_fin_cost,
            "Vol": m["Volume"],
            "OI": m["OpenInterest"],
            "Vol/OI": m["Vol_OI"],
            "BE": be,
            "Target_S": round(scen_tgt_s, 2),
            "Stop_S": round(scen_stp_s, 2),
            "Proj_Opt": round(proj_tgt, 2),
            "Stop_Opt": round(proj_stp, 2),
            "Proj_%": proj_ret_pct,
            "Opt_RR": opt_rr,
            "vs_Shares": lev_vs_shares,
            "Earn_Guard": earn_guard_str,
            "Implied_Move": implied_move_pct,
            "IV_Raw": m["IV_Raw"],
            "Hold_Days": hold_d,
            "Playbook": tct_action,
            "Rank_Score": round(rank_score, 2)
          })

      _eval_side(calls_df, "CALL")
      _eval_side(puts_df, "PUT")
  except Exception:
    pass
  return candidates


def run_parallel_options_scanner(symbols, stock_data_map, earnings_map, scenario_days=14, custom_target_map=None):
  custom_target_map = custom_target_map or {}
  valid_syms = [s for s in symbols if s in stock_data_map and not any(c in s for c in ["=X", "=F", "-USD", "^"])]

  def _worker(sym):
    d = stock_data_map[sym]
    e_days = earnings_map[sym][0] if sym in earnings_map else None
    return _scan_single_ticker_option_presets(
      sym,
      float(d["Price"]),
      float(d["Target_Price"]),
      float(d["Stop_Price"]),
      float(d["SMA150_Val"]),
      float(d["EMA50_Val"]),
      float(d.get("ATR14", d["Price"] * 0.025)),
      float(d.get("RV30", 0.38)),
      str(d.get("Playbook_Cat", "TREND")),
      str(d.get("TCT_Action", "WAIT")),
      bool(d.get("Below_SMA150", False)),
      bool(d.get("Is_Stage2_Higher_Low", False)),
      bool(d.get("Is_BB_Squeeze", False)),
      earnings_days=e_days,
      scenario_days=scenario_days,
      custom_target=custom_target_map.get(sym)
    )

  all_rows = []
  for batch in _safe_parallel_map(_worker, valid_syms, max_workers=6):
    if batch:
      all_rows.extend(batch)
  return all_rows


def render_option_scenario_pl_chart(row_dict):
  """Interactive Plotly P/L Scenario Curve for any selected contract row."""
  sym = row_dict["Ticker"]
  opt_type = row_dict["Type"]
  K = float(row_dict["Strike"])
  S0 = float(row_dict["Stock_Px"])
  mid = float(row_dict["Mid"])
  dte = int(row_dict["DTE"])
  iv = float(row_dict.get("IV_Raw", row_dict["IV_%"] / 100.0))
  hold_d = int(row_dict.get("Hold_Days", min(14, max(dte - 1, 1))))
  tgt_s = float(row_dict["Target_S"])
  stp_s = float(row_dict["Stop_S"])
  be = float(row_dict["BE"])

  s_min = max(0.5, min(S0 * 0.78, stp_s * 0.94))
  s_max = max(S0 * 1.25, tgt_s * 1.08)
  s_grid = np.linspace(s_min, s_max, 80)
  T_hold = max((dte - hold_d) / 365.0, 1.0 / 365.0)
  T_half = max((dte * 0.5) / 365.0, 1.0 / 365.0)

  pnl_hold_pct, pnl_half_pct, pnl_exp_pct = [], [], []
  pnl_hold_usd = []
  for s_val in s_grid:
    p_h = _bs_greeks(s_val, K, T_hold, r=0.045, sigma=iv, opt_type=opt_type)["price"]
    p_m = _bs_greeks(s_val, K, T_half, r=0.045, sigma=iv, opt_type=opt_type)["price"]
    p_e = max(s_val - K, 0.0) if opt_type == "CALL" else max(K - s_val, 0.0)
    pnl_hold_pct.append(((p_h - mid) / max(mid, 0.05)) * 100.0)
    pnl_half_pct.append(((p_m - mid) / max(mid, 0.05)) * 100.0)
    pnl_exp_pct.append(((p_e - mid) / max(mid, 0.05)) * 100.0)
    pnl_hold_usd.append((p_h - mid) * 100.0)

  fig = go.Figure()
  fig.add_trace(go.Scatter(
    x=s_grid, y=pnl_hold_pct, mode="lines",
    name=f"Projected P&L in {hold_d}d (%)",
    line=dict(color="#0f5132", width=2.6),
    customdata=np.array(pnl_hold_usd),
    hovertemplate="Stock: $%{x:.2f}<br>Option Return: %{y:+.1f}%<br>P&L / Contract: $%{customdata:+,.0f}<extra></extra>"
  ))
  fig.add_trace(go.Scatter(
    x=s_grid, y=pnl_half_pct, mode="lines",
    name=f"Mid-Life ({int(dte * 0.5)} DTE rem)",
    line=dict(color="#c5a059", width=1.6, dash="dot")
  ))
  fig.add_trace(go.Scatter(
    x=s_grid, y=pnl_exp_pct, mode="lines",
    name="At Expiration",
    line=dict(color="#64748b", width=1.5, dash="dash")
  ))
  fig.add_hline(y=0, line_color="#1a1a1a", line_width=1)
  fig.add_vline(x=S0, line_color="#334155", line_dash="dot", annotation_text=f"Now ${S0:.2f}", annotation_position="top")
  fig.add_vline(x=tgt_s, line_color="#15803d", line_dash="dash", annotation_text=f"Target ${tgt_s:.2f}", annotation_position="top right")
  fig.add_vline(x=stp_s, line_color="#b91c1c", line_dash="dash", annotation_text=f"Stop ${stp_s:.2f}", annotation_position="bottom left")
  fig.add_vline(x=be, line_color="#2563eb", line_dash="dot", annotation_text=f"BE ${be:.2f}", annotation_position="bottom right")
  fig.update_layout(
    title=dict(text=f"Scenario P&L Curve: {sym} {row_dict['Exp']} ${K:g} {opt_type} (Entry ${mid:.2f} | {dte} DTE | IV {row_dict['IV_%']:.1f}%)", font=dict(size=13, color="#0f291e")),
    height=330,
    margin=dict(l=12, r=18, t=42, b=16),
    xaxis_title=f"{sym} Underlying Price ($)",
    yaxis_title="Option Return (%)",
    paper_bgcolor="#ffffff",
    plot_bgcolor="#fbf9f4",
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=10))
  )
  st.plotly_chart(fig, use_container_width=True)


def render_options_cockpit_tab():
  st.markdown("<h1>Options Cockpit: Quantitative Presets & Active Ledger</h1>", unsafe_allow_html=True)
  if "Options Radar" not in watchlists or not isinstance(watchlists["Options Radar"], list):
    watchlists["Options Radar"] = ["MSFT", "NVDA", "APP", "AXP", "ABBV", "AMD", "MU", "PLTR", "AVGO", "COHR", "VRT", "HOOD", "ADPT"]

  radar_syms = list(watchlists["Options Radar"])
  active_wl_syms = list(watchlists.get("Active Portfolio", []))
  pos_opt_syms = [str(p.get("Ticker", "")).strip().upper() for p in options_positions if p.get("Ticker")]
  pos_stk_syms = [str(p.get("Ticker", "")).strip().upper() for p in positions if p.get("Ticker")]
  all_opt_syms = list(dict.fromkeys(radar_syms + active_wl_syms + pos_opt_syms + pos_stk_syms))
  stock_data_map = fetch_batch_market_data(all_opt_syms, account_size=settings["account_size"]) if all_opt_syms else {}
  earnings_map = fetch_upcoming_earnings_map(all_opt_syms) if all_opt_syms else {}

  risk_data = render_unified_portfolio_risk_strip(stock_data_map)

  opt_tab1, opt_tab2, opt_tab3 = st.tabs([
    f"1. Quantitative Preset Matrix ({len(radar_syms)} Radar)",
    "2. Stock Scenario Optimizer & Deep Chain",
    f"3. Active Options Portfolio & Ledger ({len(options_positions)} Open)"
  ])

  with opt_tab1:
    c_p1, c_p2, c_p3, c_p4, c_p5 = st.columns([1.8, 1.5, 1.5, 1.1, 0.9])
    with c_p1:
      preset_filter = st.selectbox(
        "Preset Model",
        [
          "All 5 Presets (Top Ranked)",
          "1. LEAPS Stock Replacement",
          "2. Cheap Vol Directional (IV < RV)",
          "3. Unusual Volume / Smart Money",
          "4. Scenario Optimizer (Playbook Target)",
          "5. Earnings Expected-Move Guard"
        ],
        index=0,
        label_visibility="collapsed"
      )
    with c_p2:
      scan_universe_choice = st.selectbox(
        "Scan Source",
        ["Options Radar", "Active Portfolio", "All Watchlists Combined"],
        index=0,
        label_visibility="collapsed"
      )
    with c_p3:
      opt_add_key = "opt_radar_add_in"
      def _commit_opt_radar_add():
        raw_s = st.session_state.get(opt_add_key, "").upper().strip()
        if raw_s:
          added_any = False
          for tk in [x.strip() for x in raw_s.replace(",", " ").split() if x.strip()]:
            if tk not in watchlists["Options Radar"]:
              watchlists["Options Radar"].insert(0, tk)
              added_any = True
          if added_any:
            sync_file_to_github(watchlists, DATA_FILE)
            st.toast(f"Added {raw_s} to Options Radar")
          try:
            st.session_state[opt_add_key] = ""
          except Exception:
            pass
      st.text_input(
        "Add Ticker",
        placeholder="+ Add Ticker to Radar (e.g. NVDA, MU)",
        label_visibility="collapsed",
        key=opt_add_key,
        on_change=_commit_opt_radar_add
      )
    with c_p4:
      run_parallel_btn = st.button("Scan Top 10 Now", type="primary", use_container_width=True)
    with c_p5:
      manage_radar_list = st.checkbox("Edit List", value=False)

    if manage_radar_list:
      render_watchlist_reorder_panel("Options Radar", key_prefix="opt_rad")

    target_scan_syms = (
      radar_syms if scan_universe_choice == "Options Radar"
      else (active_wl_syms if scan_universe_choice == "Active Portfolio" else get_all_monitored_tickers()[:30])
    )

    if run_parallel_btn or st.session_state.opt_scan_results is None:
      with st.spinner(f"Parallel scanning {len(target_scan_syms)} tickers across 5 quantitative presets..."):
        scanned_rows = run_parallel_options_scanner(target_scan_syms, stock_data_map, earnings_map, scenario_days=14)
        st.session_state.opt_scan_results = scanned_rows
        st.session_state.opt_scan_label = f"{scan_universe_choice} ({len(target_scan_syms)} tickers)"

    raw_rows = st.session_state.opt_scan_results or []
    filtered_rows = list(raw_rows)
    if preset_filter.startswith("1."):
      filtered_rows = [r for r in raw_rows if "LEAPS Stock Replacement" in r["Presets_List"]]
      filtered_rows.sort(key=lambda x: x["AnnFin_%"])
    elif preset_filter.startswith("2."):
      filtered_rows = [r for r in raw_rows if "Cheap Vol Directional (IV<RV)" in r["Presets_List"]]
      filtered_rows.sort(key=lambda x: (x["IV/RV"], -x["Opt_RR"]))
    elif preset_filter.startswith("3."):
      filtered_rows = [r for r in raw_rows if "Unusual Volume / Smart Money" in r["Presets_List"]]
      filtered_rows.sort(key=lambda x: (-x["Vol/OI"], -x["Vol"]))
    elif preset_filter.startswith("4."):
      filtered_rows = [r for r in raw_rows if "Scenario Optimizer" in r["Presets_List"]]
      filtered_rows.sort(key=lambda x: (-x["Opt_RR"], -x["Proj_%"]))
    elif preset_filter.startswith("5."):
      filtered_rows = [r for r in raw_rows if "Earnings Guard" in r["Presets_List"]]
      filtered_rows.sort(key=lambda x: (x["DTE"], -x["IV_%"]))
    else:
      # Top 10 deduplicated by (Ticker, Type, DTE bucket)
      sorted_all = sorted(raw_rows, key=lambda x: -x["Rank_Score"])
      dedup, seen_k = [], set()
      for r in sorted_all:
        k = (r["Ticker"], r["Type"], "LEAPS" if r["DTE"] >= 180 else "SHORT")
        if k not in seen_k:
          seen_k.add(k)
          dedup.append(r)
      filtered_rows = dedup[:10] if run_parallel_btn else dedup[:25]

    st.caption(f"Source: {st.session_state.opt_scan_label} | Showing {len(filtered_rows)} ranked contracts (single-leg Calls & Puts only). Click any row to open its interactive P/L Scenario Curve & Log button.")

    if filtered_rows:
      disp_cols = [
        "Ticker", "Preset", "Type", "Exp", "DTE", "Strike", "Mid", "Spread_%",
        "Delta", "Theta/d", "IV_%", "RV30_%", "IV/RV", "Ext_%", "AnnFin_%",
        "Vol", "OI", "Vol/OI", "Proj_%", "Opt_RR", "Earn_Guard"
      ]
      df_matrix = pd.DataFrame([{k: r[k] for k in disp_cols} for r in filtered_rows])
      sel_event = st.dataframe(
        df_matrix,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        key="opt_matrix_df"
      )
      sel_idx = sel_event.selection.rows[0] if (sel_event and sel_event.selection and sel_event.selection.rows) else 0
      chosen_row = filtered_rows[min(sel_idx, len(filtered_rows) - 1)]

      st.markdown("---")
      sc_c1, sc_c2 = st.columns([2.2, 1.1])
      with sc_c1:
        render_option_scenario_pl_chart(chosen_row)
      with sc_c2:
        st.markdown(
          f'<div class="stock-card">'
          f'<div style="font-size:0.70rem;font-weight:700;color:#c5a059;text-transform:uppercase;letter-spacing:0.06em;">SELECTED CONTRACT TICKET</div>'
          f'<div style="font-size:1.05rem;font-weight:800;color:#0f291e;margin-top:3px;">'
          f'<a href="?inspect={chosen_row["Ticker"]}" target="_self" class="ticker-link">{chosen_row["Ticker"]}</a> '
          f'{chosen_row["Exp"]} ${chosen_row["Strike"]:g} {chosen_row["Type"]}</div>'
          f'<div class="trade-ticket">'
          f'<b>Mid:</b> ${chosen_row["Mid"]:.2f} (Bid ${chosen_row["Bid"]:.2f} / Ask ${chosen_row["Ask"]:.2f} | Spr {chosen_row["Spread_%"]:.1f}%)<br>'
          f'<b>1x Cost:</b> ${chosen_row["Cost_1x"]:,.0f} | <b>BE:</b> ${chosen_row["BE"]:,.2f}<br>'
          f'<b>Greeks:</b> Delta {chosen_row["Delta"]:.3f} | Gamma {chosen_row["Gamma"]:.4f}<br>'
          f'<b>Theta:</b> ${chosen_row["Theta/d"]:.3f}/sh (${chosen_row["Theta/d"]*100:.1f}/d) | <b>Vega:</b> ${chosen_row["Vega"]:.2f}<br>'
          f'<b>Vol Edge:</b> IV {chosen_row["IV_%"]:.1f}% vs 30D RV {chosen_row["RV30_%"]:.1f}% (Ratio {chosen_row["IV/RV"]:.2f})<br>'
          f'<b>Scenario ({chosen_row["Hold_Days"]}d):</b> Target ${chosen_row["Target_S"]:.2f} -> Opt ${chosen_row["Proj_Opt"]:.2f} ({chosen_row["Proj_%"]:+.1f}%) | {chosen_row["Opt_RR"]:.2f}R ({chosen_row["vs_Shares"]:.1f}x vs Shares)<br>'
          f'<b>Earnings Guard:</b> {chosen_row["Earn_Guard"]}'
          f'</div></div>',
          unsafe_allow_html=True
        )
        if st.button(f"Log {chosen_row['Ticker']} ${chosen_row['Strike']:g} {chosen_row['Type']} to Active Options", type="primary", use_container_width=True, key="log_sel_matrix_opt"):
          new_opt = {
            "id": f"{chosen_row['Ticker']}_{chosen_row['Type']}_{int(time.time())}",
            "Ticker": chosen_row["Ticker"],
            "Option_Type": chosen_row["Type"],
            "Strategy": chosen_row["Preset"],
            "Expiration": chosen_row["Exp"],
            "Strike": float(chosen_row["Strike"]),
            "Contracts": 1,
            "Buy_Premium": float(chosen_row["Mid"]),
            "Buy_Date": datetime.now().strftime("%Y-%m-%d"),
            "Stock_Entry": float(chosen_row["Stock_Px"]),
            "Stock_Stop": float(chosen_row["Stop_S"]),
            "Stock_Target": float(chosen_row["Target_S"]),
            "Option_Stop": float(chosen_row["Stop_Opt"]),
            "Option_Target": float(chosen_row["Proj_Opt"]),
            "HalfSold": False,
            "Remarks": f"{chosen_row['Preset']} | {chosen_row['Delta']:.2f}D | IV/RV {chosen_row['IV/RV']:.2f}"
          }
          options_positions.append(new_opt)
          sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
          log_options_ledger_entry("BUY OPEN", chosen_row["Ticker"], chosen_row["Type"], chosen_row["Exp"], chosen_row["Strike"], 1, chosen_row["Mid"], chosen_row["Mid"], 0.0, 0.0, chosen_row["Stop_Opt"], chosen_row["Stop_S"], new_opt["Remarks"])
          st.success(f"Logged {chosen_row['Ticker']} {chosen_row['Exp']} ${chosen_row['Strike']:g} {chosen_row['Type']}.")
          st.rerun()
    else:
      st.info("No contracts matched that strict preset filter right now. Switch to All 5 Presets or use the Stock Scenario Optimizer tab to customize target price and days.")

  with opt_tab2:
    st.markdown("### Stock Scenario Optimizer (Rank Best Strike & Expiry for Your Price Target)")
    all_choices = sorted(list(dict.fromkeys(radar_syms + active_wl_syms))) or ["NVDA"]
    sc1, sc2, sc3, sc4 = st.columns([1.3, 1.3, 1.2, 1.2])
    scen_sym = sc1.selectbox("Ticker", all_choices, key="scen_opt_sym")
    sd_scen = stock_data_map.get(scen_sym)
    def_tgt = round(float(sd_scen["Target_Price"]), 2) if sd_scen else 150.0
    def_px = round(float(sd_scen["Price"]), 2) if sd_scen else 120.0
    scen_tgt_in = sc2.number_input(f"Target Price ($) [Now ${def_px:.2f}]", min_value=0.5, value=def_tgt, step=1.0, key="scen_tgt_px")
    scen_days_in = sc3.number_input("Target Holding Days", min_value=2, max_value=365, value=14, step=2, key="scen_hold_d")
    scen_dir = sc4.radio("Direction", ["CALL", "PUT"], index=(0 if scen_tgt_in >= def_px else 1), horizontal=True, key="scen_dir_rad")

    if sd_scen:
      scen_rows = run_parallel_options_scanner([scen_sym], stock_data_map, earnings_map, scenario_days=int(scen_days_in), custom_target_map={scen_sym: float(scen_tgt_in)})
      scen_rows = [r for r in scen_rows if r["Type"] == scen_dir]
      scen_rows.sort(key=lambda x: (-x["Proj_%"], -x["Opt_RR"]))
      if scen_rows:
        df_sc = pd.DataFrame([{
          "Exp": r["Exp"], "DTE": r["DTE"], "Strike": r["Strike"], "Mid": r["Mid"],
          "Spread_%": r["Spread_%"], "Delta": r["Delta"], "Theta/d": r["Theta/d"],
          "IV_%": r["IV_%"], "IV/RV": r["IV/RV"], "Proj_Opt": r["Proj_Opt"],
          "Proj_%": r["Proj_%"], "Opt_RR": r["Opt_RR"], "vs_Shares": r["vs_Shares"],
          "Earn_Guard": r["Earn_Guard"]
        } for r in scen_rows[:15]])
        ev_sc = st.dataframe(df_sc, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row", key="scen_opt_df")
        s_idx = ev_sc.selection.rows[0] if (ev_sc and ev_sc.selection and ev_sc.selection.rows) else 0
        render_option_scenario_pl_chart(scen_rows[min(s_idx, len(scen_rows) - 1)])
      else:
        st.caption(f"No liquid {scen_dir} contracts passed liquidity/return criteria for {scen_sym} at target ${scen_tgt_in:.2f}.")

    st.markdown("---")
    with st.expander("Deep Single-Ticker Option Chain Explorer (Full Greeks & IV/RV)", expanded=False):
      dc1, dc2, dc3, dc4 = st.columns([1.3, 1.1, 1.4, 1.6])
      deep_sym = dc1.selectbox("Select Stock", all_choices, key="deep_opt_sym")
      deep_type = dc2.radio("Type", ["CALL", "PUT"], horizontal=True, key="deep_opt_type")
      deep_dte_mode = dc3.selectbox("Expiration Window", ["LEAPS (240-600 DTE)", "Short-Term (5-45 DTE)", "Medium-Term (46-239 DTE)"], key="deep_opt_dte")
      deep_delta_rng = dc4.slider("Target |Delta| Range", 0.15, 0.98, (0.80, 0.92) if deep_dte_mode.startswith("LEAPS") else (0.35, 0.65), 0.05, key="deep_opt_delta")
      if deep_sym in stock_data_map:
        sd = stock_data_map[deep_sym]
        try:
          tk_d = yf.Ticker(deep_sym)
          all_exps = list(tk_d.options or [])
          now_d = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
          valid_exps = []
          for e_s in all_exps:
            d_left = (datetime.strptime(e_s, "%Y-%m-%d") - now_d).days
            if deep_dte_mode.startswith("LEAPS") and d_left >= 180:
              valid_exps.append((d_left, e_s))
            elif deep_dte_mode.startswith("Short-Term") and 3 <= d_left <= 55:
              valid_exps.append((d_left, e_s))
            elif deep_dte_mode.startswith("Medium-Term") and 45 <= d_left <= 240:
              valid_exps.append((d_left, e_s))
          if not valid_exps and all_exps:
            valid_exps = [((datetime.strptime(e_s, "%Y-%m-%d") - now_d).days, e_s) for e_s in all_exps[:4]]
          if valid_exps:
            chosen_dte, chosen_exp = st.selectbox("Expiration Date", valid_exps, format_func=lambda x: f"{x[1]} ({x[0]} DTE)", key="deep_exp_sel")
            ch_d = tk_d.option_chain(chosen_exp)
            df_s = ch_d.calls if deep_type == "CALL" else ch_d.puts
            rows_deep = []
            T_y = max(chosen_dte / 365.0, 1.0 / 365.0)
            for _, rw in df_s.iterrows():
              K_v = float(rw.get("strike", 0.0) or 0.0)
              mi = _extract_contract_metrics(rw, sd["Price"], K_v, T_y, deep_type, rv30=sd.get("RV30", 0.38))
              if deep_delta_rng[0] <= abs(mi["Delta"]) <= deep_delta_rng[1]:
                be_px = K_v + mi["Mid"] if deep_type == "CALL" else K_v - mi["Mid"]
                rows_deep.append({
                  "Exp": chosen_exp, "DTE": chosen_dte, "Type": deep_type, "Strike": K_v,
                  "Mid": mi["Mid"], "Bid": mi["Bid"], "Ask": mi["Ask"], "Spread_%": mi["Spread_Pct"],
                  "Delta": mi["Delta"], "Gamma": mi["Gamma"], "Theta/d": mi["Theta"], "Vega": mi["Vega"],
                  "IV_%": mi["IV_Pct"], "IV/RV": mi["IV_RV"], "Ext_%": mi["Extrinsic_Pct"],
                  "BE": round(be_px, 2), "Vol": mi["Volume"], "OI": mi["OpenInterest"], "Vol/OI": mi["Vol_OI"]
                })
            if rows_deep:
              st.dataframe(pd.DataFrame(rows_deep), use_container_width=True, hide_index=True)
            else:
              st.caption("No strikes matched that Delta filter on this expiration.")
        except Exception as e:
          st.caption(f"Chain note: {str(e)[:80]}")

  with opt_tab3:
    st.markdown("### Active Options Positions & Rule Enforcer")
    tot_opt_cost = 0.0
    tot_opt_val = 0.0
    live_opt_quotes = risk_data["opt_quotes"]
    for op in options_positions:
      q_info = live_opt_quotes.get(op["id"], {"Mid": op.get("Buy_Premium", 1.0)})
      qty = int(op.get("Contracts", 1))
      b_prem = float(op.get("Buy_Premium", 1.0))
      lv_prem = float(q_info.get("Mid", b_prem))
      tot_opt_cost += qty * b_prem * 100.0
      tot_opt_val += qty * lv_prem * 100.0

    opt_unreal_pnl = tot_opt_val - tot_opt_cost
    opt_unreal_pct = (opt_unreal_pnl / tot_opt_cost * 100.0) if tot_opt_cost > 0 else 0.0
    opt_realized_tot = sum(float(x.get("Gain_Loss_USD", 0.0)) for x in options_ledger if x.get("Action") in ("SELL PARTIAL", "CLOSE"))

    om1, om2, om3, om4 = st.columns(4)
    om1.metric("Total Options Cost Basis", f"${tot_opt_cost:,.2f}")
    om2.metric("Current Options Market Value", f"${tot_opt_val:,.2f}")
    om3.metric("Open Options Unrealized P&L", f"${opt_unreal_pnl:+,.2f}", f"{opt_unreal_pct:+.2f}%")
    om4.metric("Closed Options Realized P&L", f"${opt_realized_tot:+,.2f}")

    with st.expander("Log a New Option Trade Manually", expanded=not bool(options_positions)):
      oc1, oc2, oc3, oc4, oc5, oc6 = st.columns([1.1, 1.0, 1.4, 1.2, 1.0, 1.2])
      m_sym = oc1.text_input("Ticker", placeholder="e.g. NVDA", key="m_opt_sym").upper().strip()
      m_type = oc2.selectbox("Type", ["CALL", "PUT"], key="m_opt_type")
      m_strat = oc3.selectbox("Strategy", ["LEAPS Stock Replacement", "Cheap Vol Directional", "Unusual Volume Sweep", "Short-Term Tactical Bet"], key="m_opt_strat")
      m_exp = oc4.text_input("Expiration (YYYY-MM-DD)", value="2027-09-17", key="m_opt_exp").strip()
      m_strk = oc5.number_input("Strike ($)", min_value=0.5, value=150.0, step=2.5, key="m_opt_strk")
      m_qty = oc6.number_input("Contracts", min_value=1, value=1, step=1, key="m_opt_qty")

      oc7, oc8, oc9, oc10, oc11 = st.columns([1.2, 1.2, 1.2, 1.2, 2.2])
      m_bprem = oc7.number_input("Buy Premium ($/sh)", min_value=0.05, value=15.0, step=0.5, key="m_opt_bprem")
      default_opt_stp = round(m_bprem * (0.78 if m_strat.startswith("LEAPS") else 0.65), 2)
      default_opt_tgt = round(m_bprem * (1.40 if m_strat.startswith("LEAPS") else 1.80), 2)
      m_ostp = oc8.number_input("Option Stop ($/sh)", min_value=0.01, value=default_opt_stp, step=0.5, key="m_opt_ostp")
      m_otgt = oc9.number_input("Option Target ($/sh)", min_value=0.05, value=default_opt_tgt, step=0.5, key="m_opt_otgt")
      m_sstp = oc10.number_input("Stock Stop ($)", min_value=0.01, value=100.0, step=1.0, key="m_opt_sstp")
      m_rmk = oc11.text_input("Remarks / Thesis", placeholder="e.g. 0.88 Delta LEAPS on Stage 2 pullback", key="m_opt_rmk")

      if st.button("Save Option Contract to Portfolio", type="primary", key="m_opt_save_btn"):
        if m_sym:
          s_curr = float(stock_data_map.get(m_sym, {}).get("Price", m_strk))
          new_op = {
            "id": f"{m_sym}_{m_type}_{int(time.time())}",
            "Ticker": m_sym,
            "Option_Type": m_type,
            "Strategy": m_strat,
            "Expiration": m_exp,
            "Strike": float(m_strk),
            "Contracts": int(m_qty),
            "Buy_Premium": float(m_bprem),
            "Buy_Date": datetime.now().strftime("%Y-%m-%d"),
            "Stock_Entry": s_curr,
            "Stock_Stop": float(m_sstp),
            "Stock_Target": round(s_curr * (1.15 if m_type == "CALL" else 0.88), 2),
            "Option_Stop": float(m_ostp),
            "Option_Target": float(m_otgt),
            "HalfSold": False,
            "Remarks": m_rmk.strip()
          }
          options_positions.append(new_op)
          sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
          log_options_ledger_entry("BUY OPEN", m_sym, m_type, m_exp, m_strk, m_qty, m_bprem, m_bprem, 0.0, 0.0, m_ostp, m_sstp, m_rmk)
          if m_sym not in watchlists["Options Radar"]:
            watchlists["Options Radar"].append(m_sym)
            sync_file_to_github(watchlists, DATA_FILE)
          st.success(f"Logged {m_qty}x {m_sym} {m_exp} ${m_strk:g} {m_type} @ ${m_bprem:.2f}.")
          st.rerun()

    st.markdown("---")
    if options_positions:
      for idx_o, op in enumerate(options_positions):
        sym = op["Ticker"]
        o_type = op.get("Option_Type", "CALL")
        exp_s = op.get("Expiration", "N/A")
        strk = float(op.get("Strike", 0.0))
        qty = int(op.get("Contracts", 1))
        b_prem = float(op.get("Buy_Premium", 1.0))
        o_stp = float(op.get("Option_Stop", b_prem * 0.70))
        o_tgt = float(op.get("Option_Target", b_prem * 1.50))
        s_stp = float(op.get("Stock_Stop", 0.0))
        s_live = float(stock_data_map.get(sym, {}).get("Price", op.get("Stock_Entry", strk)))
        q_live = live_opt_quotes.get(op["id"], {"Mid": b_prem, "Delta": 0.50, "Theta": -0.05, "DTE": 30, "IV_Pct": 40.0})
        lv_prem = float(q_live.get("Mid", b_prem))
        dte_rem = int(q_live.get("DTE", 30))
        lv_delta = float(q_live.get("Delta", 0.50))
        lv_theta_d = float(q_live.get("Theta", 0.0)) * qty * 100.0
        cost_usd = qty * b_prem * 100.0
        mkt_usd = qty * lv_prem * 100.0
        pnl_usd = mkt_usd - cost_usd
        pnl_pct = ((lv_prem - b_prem) / b_prem) * 100.0 if b_prem > 0 else 0.0
        clr_p = "#15803d" if pnl_usd >= 0 else "#b91c1c"
        rmk_o = op.get("Remarks", "") or op.get("Strategy", "")

        cp1, cp2, cp3 = st.columns([1.7, 4.5, 1.8])
        with cp1:
          st.markdown(
            f"**<a href='?inspect={sym}' target='_self' class='ticker-link'>{sym}</a> "
            f"<span class='badge {'badge-tct-buy' if o_type == 'CALL' else 'badge-tct-sell'}'>{o_type}</span>**<br>"
            f"<span class='num' style='font-size:0.95rem;font-weight:800;color:#0f291e;'>{exp_s} | ${strk:,.2f}</span><br>"
            f"<span class='num' style='font-size:0.74rem;color:#475569;'>DTE {dte_rem}d | Delta {lv_delta:.2f} | Theta ${lv_theta_d:+.1f}/d</span>",
            unsafe_allow_html=True
          )
        with cp2:
          st.markdown(
            f"<div style='display:flex;justify-content:space-between;padding:6px 10px;background:#ffffff;border-radius:6px;border:1px solid #e2dcd0;font-variant-numeric:tabular-nums;'>"
            f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Buy Prem</span><br><b>${b_prem:,.2f}</b> <span style='font-size:0.72rem;'>({qty}x=${cost_usd:,.0f})</span></div>"
            f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Live Mid</span><br><b>${lv_prem:,.2f}</b> <span style='font-size:0.72rem;'>(${mkt_usd:,.0f})</span></div>"
            f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Opt Stop</span><br><b style='color:#dc2626;'>${o_stp:,.2f}</b></div>"
            f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Opt Target</span><br><b style='color:#059669;'>${o_tgt:,.2f}</b></div>"
            f"<div><span style='font-size:0.68rem;color:#64748b;text-transform:uppercase;'>Unrealized P&L</span><br><b style='color:{clr_p};'>${pnl_usd:+,.2f} ({pnl_pct:+.1f}%)</b></div>"
            f"</div>"
            f"<div style='font-size:0.75rem;color:#334155;margin-top:4px;'><b>Stock:</b> ${s_live:,.2f} (Stop ${s_stp:,.2f}) | <b>Thesis:</b> <i>{rmk_o}</i></div>",
            unsafe_allow_html=True
          )
          stock_stop_hit = (o_type == "CALL" and s_stp > 0 and s_live <= s_stp) or (o_type == "PUT" and s_stp > 0 and s_live >= s_stp)
          if lv_prem <= o_stp:
            st.error(f"OPTION STOP HIT: {sym} ${strk:g} {o_type} (${lv_prem:,.2f}) <= Stop (${o_stp:,.2f}).")
          elif stock_stop_hit:
            st.error(f"STOCK STOP HIT: {sym} (${s_live:,.2f}) crossed Stock Stop (${s_stp:,.2f}).")
          elif lv_prem >= o_tgt and not op.get("HalfSold", False):
            st.warning(f"TARGET HIT (${lv_prem:,.2f} >= ${o_tgt:,.2f}). Trim 50% or raise stop in Manage Option.")
          elif "LEAPS" in str(op.get("Strategy", "")) and dte_rem <= 120:
            st.warning(f"LEAPS ROLL ALERT: {dte_rem} DTE remaining. Roll out to 9-12 months.")
          elif dte_rem <= 4:
            st.warning(f"EXPIRATION ALERT: {dte_rem} DTE remaining.")
        with cp3:
          with st.popover("Manage Option", use_container_width=True):
            st.markdown(f"**Manage `{sym} {exp_s} ${strk:g} {o_type}` ({qty}x)**")
            ot1, ot2, ot3 = st.tabs(["Sell/Trim", "Trail Stop", "Close/Delete"])
            with ot1:
              trim_qty = st.number_input("Contracts to Sell", min_value=1, max_value=max(1, qty), value=max(1, qty // 2), key=f"otrim_q_{op['id']}")
              trim_px = st.number_input("Sell Premium ($/sh)", min_value=0.01, value=float(round(lv_prem, 2)), step=0.25, key=f"otrim_px_{op['id']}")
              new_ostp_after = st.number_input("Raise Option Stop ($/sh)", min_value=0.01, value=float(round(b_prem, 2)), step=0.25, key=f"otrim_stp_{op['id']}")
              if st.button("Execute Partial Option Sale", type="primary", use_container_width=True, key=f"otrim_btn_{op['id']}"):
                r_usd = (trim_px - b_prem) * trim_qty * 100.0
                r_pct = ((trim_px - b_prem) / b_prem) * 100.0 if b_prem > 0 else 0.0
                log_options_ledger_entry("SELL PARTIAL", sym, o_type, exp_s, strk, trim_qty, b_prem, trim_px, r_usd, r_pct, new_ostp_after, s_stp, f"Trimmed {trim_qty}x @ ${trim_px:.2f}")
                rem_q = qty - trim_qty
                if rem_q <= 0:
                  options_positions.pop(idx_o)
                else:
                  options_positions[idx_o]["Contracts"] = rem_q
                  options_positions[idx_o]["HalfSold"] = True
                  options_positions[idx_o]["Option_Stop"] = round(float(new_ostp_after), 2)
                sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
                st.rerun()
            with ot2:
              upd_ostp = st.number_input("New Option Stop ($/sh)", min_value=0.01, value=float(round(o_stp, 2)), step=0.25, key=f"otrail_ostp_{op['id']}")
              upd_otgt = st.number_input("New Option Target ($/sh)", min_value=0.05, value=float(round(o_tgt, 2)), step=0.5, key=f"otrail_otgt_{op['id']}")
              upd_sstp = st.number_input("New Stock Stop ($)", min_value=0.01, value=float(round(s_stp, 2)), step=0.5, key=f"otrail_sstp_{op['id']}")
              if st.button("Save Updated Stops & Target", type="primary", use_container_width=True, key=f"otrail_btn_{op['id']}"):
                options_positions[idx_o]["Option_Stop"] = round(float(upd_ostp), 2)
                options_positions[idx_o]["Option_Target"] = round(float(upd_otgt), 2)
                options_positions[idx_o]["Stock_Stop"] = round(float(upd_sstp), 2)
                sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
                st.rerun()
            with ot3:
              close_prem = st.number_input("Full Exit Sell Premium ($/sh)", min_value=0.01, value=float(round(lv_prem, 2)), step=0.25, key=f"oclose_px_{op['id']}")
              close_note = st.text_input("Exit Note", value="Closed option position", key=f"oclose_rmk_{op['id']}")
              if st.button("Close Option Position & Log", type="primary", use_container_width=True, key=f"oclose_btn_{op['id']}"):
                r_usd = (close_prem - b_prem) * qty * 100.0
                r_pct = ((close_prem - b_prem) / b_prem) * 100.0 if b_prem > 0 else 0.0
                log_options_ledger_entry("CLOSE", sym, o_type, exp_s, strk, qty, b_prem, close_prem, r_usd, r_pct, o_stp, s_stp, f"{rmk_o} | {close_note}".strip(" |"))
                options_positions.pop(idx_o)
                sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
                st.rerun()
              if st.button("Delete Without Logging", use_container_width=True, key=f"odel_btn_{op['id']}"):
                options_positions.pop(idx_o)
                sync_file_to_github(options_positions, OPTIONS_POSITIONS_FILE)
                st.rerun()
        st.markdown("<hr style='margin:6px 0;'>", unsafe_allow_html=True)
    else:
      st.info("No open option contracts tracked yet. Select any contract in Tab 1 and click Log, or add manually above.")

    st.markdown("### Complete Options Trade Ledger & Excel Export")
    if options_ledger:
      df_oledger = pd.DataFrame(list(reversed(options_ledger)))
      st.dataframe(df_oledger, use_container_width=True, hide_index=True)
      oc_dl1, oc_dl2 = st.columns(2)
      try:
        obuf = io.BytesIO()
        with pd.ExcelWriter(obuf, engine="openpyxl") as writer:
          df_oledger.to_excel(writer, sheet_name="Options_Ledger", index=False)
        oc_dl1.download_button(
          "Download Options Ledger Excel (.xlsx)",
          data=obuf.getvalue(),
          file_name=f"options_ledger_{datetime.now().strftime('%Y%m%d')}.xlsx",
          mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
          type="primary",
          use_container_width=True,
          key="dl_opt_xlsx"
        )
      except Exception:
        pass
      oc_dl2.download_button(
        "Download Options Ledger CSV (.csv)",
        data=df_oledger.to_csv(index=False).encode("utf-8"),
        file_name=f"options_ledger_{datetime.now().strftime('%Y%m%d')}.csv",
        mime="text/csv",
        use_container_width=True,
        key="dl_opt_csv"
      )
    else:
      st.caption("No historical option ledger entries recorded yet.")


# --- YOUTUBE LIVE FEED & CAPTION EXTRACTOR (NO STATIC TRANSCRIPT BLOAT) ---
def _extract_yt_video_id(url_or_id):
  s = str(url_or_id or "").strip()
  m = re.search(r"(?:v=|youtu\.be/|shorts/|embed/)([A-Za-z0-9_-]{11})", s)
  if m:
    return m.group(1)
  if len(s) == 11 and all(c.isalnum() or c in "_-" for c in s):
    return s
  return ""


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_youtube_video_transcript_and_context(video_url, fallback_title=""):
  vid_id = _extract_yt_video_id(video_url)
  blocks = []
  if vid_id:
    try:
      watch_url = f"https://www.youtube.com/watch?v={vid_id}&hl=en"
      req = urllib.request.Request(
        watch_url,
        headers={
          "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
          "Accept-Language": "en-US,en;q=0.9,zh-TW;q=0.8,zh;q=0.7"
        }
      )
      with urllib.request.urlopen(req, timeout=6) as resp:
        html_txt = resp.read().decode("utf-8", errors="ignore")
      m_desc = re.search(r'"shortDescription":"((?:\\.|[^"\\])*)"', html_txt)
      if m_desc:
        raw_desc = bytes(m_desc.group(1), "utf-8").decode("unicode_escape", errors="ignore")
        clean_desc = " ".join(raw_desc.split())[:2500]
        if clean_desc:
          blocks.append(f"=== VIDEO DESCRIPTION ===\n{clean_desc}")
      m_cap = re.search(r'"captionTracks":\[\{"baseUrl":"([^"]+)"', html_txt)
      if m_cap:
        cap_url = m_cap.group(1).replace("\\u0026", "&")
        with urllib.request.urlopen(urllib.request.Request(cap_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=5) as c_resp:
          cap_xml = c_resp.read().decode("utf-8", errors="ignore")
        c_root = ET.fromstring(cap_xml)
        cap_lines = [(el.text or "").strip() for el in c_root.findall(".//text") if el.text]
        if cap_lines:
          blocks.append(f"=== LIVE YOUTUBE CAPTIONS ===\n{' '.join(cap_lines)[:9000]}")
    except Exception:
      pass
  if not blocks:
    blocks.append(
      f"Video Title: {fallback_title} ({video_url})\n"
      "Use live Google Search grounding to retrieve current context and verify the macro/stock thesis implied by this video against live candlestick data."
    )
  return "\n\n".join(blocks)


def _scrape_youtube_channel_videos(handle_or_url, max_vids=6):
  out = []
  try:
    url = handle_or_url if handle_or_url.startswith("http") else f"https://www.youtube.com/{handle_or_url}/videos"
    req = urllib.request.Request(
      url,
      headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept-Language": "zh-HK,zh-TW;q=0.9,en-US;q=0.8,en;q=0.7"
      }
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
      html_s = resp.read().decode("utf-8", errors="ignore")
    m_cid = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', html_s)
    if m_cid:
      cid = m_cid.group(1)
      rss_u = f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
      with urllib.request.urlopen(urllib.request.Request(rss_u, headers={"User-Agent": "Mozilla/5.0"}), timeout=4.5) as r_resp:
        root = ET.fromstring(r_resp.read())
      ns = {"atom": "http://www.w3.org/2005/Atom"}
      for ent in root.findall("atom:entry", ns)[:max_vids]:
        t_el = ent.find("atom:title", ns)
        l_el = ent.find("atom:link", ns)
        p_el = ent.find("atom:published", ns)
        if t_el is not None and t_el.text:
          lnk = l_el.attrib.get("href", "") if l_el is not None else ""
          vid_id = _extract_yt_video_id(lnk)
          out.append({
            "id": vid_id,
            "title": t_el.text.strip(),
            "link": lnk,
            "date": p_el.text[:10] if p_el is not None and p_el.text else "Recent"
          })
  except Exception:
    pass
  return out


@st.cache_data(ttl=900, show_spinner=False)
def fetch_ryan_latest_videos():
  fallback = [
    {"id": "8YeWNhktU1c", "date": "2026-11-14", "title": "Stock Market Warning | My QQQ Hedge + 5 Stocks I'm Looking To Add (Options With Ryan)", "link": "https://www.youtube.com/watch?v=8YeWNhktU1c"},
    {"id": "vdhKw6ywg1Y", "date": "2026-11-12", "title": "AI Stocks Rallying | More Upside Ahead? VXN Study + TQQQ Update (Options With Ryan)", "link": "https://www.youtube.com/watch?v=vdhKw6ywg1Y"}
  ]
  live_vids = _scrape_youtube_channel_videos("@OptionsWithRyan", max_vids=6)
  merged, seen_ids = [], set()
  for v in (live_vids + fallback):
    vid = v.get("id") or _extract_yt_video_id(v.get("link", ""))
    if vid and vid not in seen_ids:
      seen_ids.add(vid)
      v["id"] = vid
      merged.append(v)
  return sorted(merged, key=lambda x: str(x.get("date", "")), reverse=True)[:6]


@st.cache_data(ttl=900, show_spinner=False)
def fetch_sds_latest_videos():
  fallback = [
    {"id": "14NkjY9NbKI", "date": "2026-11-15", "title": "@sds.getrich Latest Macro Commentary", "link": "https://www.youtube.com/watch?v=14NkjY9NbKI"},
    {"id": "u7XIeJEMuuI", "date": "2026-11-08", "title": "@sds.getrich AI Capex & Asian FX Analysis", "link": "https://www.youtube.com/watch?v=u7XIeJEMuuI"}
  ]
  live_videos = []
  try:
    req = urllib.request.Request("https://www.youtube.com/feeds/videos.xml?channel_id=UCWMxmoBhchU3swFAciqagnw", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=4.5) as resp:
      root = ET.fromstring(resp.read())
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for ent in root.findall("atom:entry", ns)[:8]:
      t_el = ent.find("atom:title", ns)
      l_el = ent.find("atom:link", ns)
      p_el = ent.find("atom:published", ns)
      if t_el is not None and t_el.text:
        lnk = l_el.attrib.get("href", "https://www.youtube.com/@sds.getrich") if l_el is not None else "https://www.youtube.com/@sds.getrich"
        live_videos.append({
          "id": _extract_yt_video_id(lnk),
          "title": t_el.text.strip(),
          "link": lnk,
          "date": p_el.text[:10] if p_el is not None and p_el.text else "Recent"
        })
  except Exception:
    pass
  if not live_videos:
    live_videos = _scrape_youtube_channel_videos("@sds.getrich", max_vids=6)
  merged, seen_ids = [], set()
  for v in (live_videos + fallback):
    vid = v.get("id") or _extract_yt_video_id(v.get("link", ""))
    if vid and vid not in seen_ids:
      seen_ids.add(vid)
      v["id"] = vid
      merged.append(v)
  return sorted(merged, key=lambda x: str(x.get("date", "")), reverse=True)[:6]


# --- LIVE MACRO & REGIME ENGINE (SUPPORTS LIVE AUTO-REFRESH BUCKETS) ---
MACRO_SYMBOLS = {
  "S&P 500": "^GSPC", "Dow Jones": "^DJI", "Nasdaq": "^IXIC", "VIX": "^VIX",
  "Gold": "GC=F", "Silver": "SI=F", "Copper": "HG=F",
  "DXY (USD)": "DX-Y.NYB", "USD/JPY": "JPY=X", "Bitcoin": "BTC-USD", "Ethereum": "ETH-USD"
}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_macro_and_regime(refresh_bucket=0):
  ticks = list(MACRO_SYMBOLS.values())
  out = {}
  regime = {
    "label": "MARKET REGIME: BULLISH — S&P 500 Holding Trend | Favorable for New Setups",
    "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
  }
  try:
    df = yf.download(ticks, period="3mo", interval="1d", group_by="ticker", progress=False)
    df_intra = None
    try:
      df_intra = yf.download(ticks, period="2d", interval="5m", group_by="ticker", progress=False)
    except Exception:
      df_intra = None

    for name, sym in MACRO_SYMBOLS.items():
      sub = _extract_ticker_df(df, sym, len(ticks)).dropna(subset=["Close"])
      if len(sub) >= 2:
        c = float(sub["Close"].iloc[-1])
        pc = float(sub["Close"].iloc[-2])
        if df_intra is not None:
          try:
            sub_i = _extract_ticker_df(df_intra, sym, len(ticks)).dropna(subset=["Close"])
            if not sub_i.empty:
              c = float(sub_i["Close"].iloc[-1])
          except Exception:
            pass
        out[name] = (c, c - pc, ((c - pc) / pc) * 100.0 if pc != 0 else 0.0)

    sp = _extract_ticker_df(df, "^GSPC", len(ticks)).dropna(subset=["Close"])
    if len(sp) >= 50:
      sp_c = out.get("S&P 500", (float(sp["Close"].iloc[-1]), 0, 0))[0]
      sp_ema20 = float(sp["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
      sp_ema50 = float(sp["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
      vix_c = out.get("VIX", (18.0, 0, 0))[0]
      if sp_c > sp_ema50 and sp_c > sp_ema20 and vix_c < 21.0:
        regime = {
          "label": f"MARKET REGIME: BULLISH (S&P 500 > 20 & 50 EMA | VIX {vix_c:.1f}) — Green Light for Stage 2, Swing & Momentum Buys",
          "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"
        }
      elif sp_c < sp_ema50 or vix_c >= 25.0:
        regime = {
          "label": f"MARKET REGIME: RISK-OFF (S&P < 50 EMA or VIX {vix_c:.1f}) — Protect Capital, Avoid Aggressive Longs",
          "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"
        }
      else:
        regime = {
          "label": f"MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating | VIX {vix_c:.1f}) — Selective 20-EMA Pullbacks & TCT Boxes Only",
          "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"
        }
  except Exception:
    pass
  return out, regime


def render_macro_bar_html(macro_data, regime_info, compact=False):
  if macro_data:
    cards_html = "".join([
      f'<div class="macro-card"><div class="macro-title">{name}</div>'
      f'<div class="macro-price">{price:,.2f}</div>'
      f'<div class="{"tick-pos" if chg >= 0 else "tick-neg"}">'
      f'{"+" if chg >= 0 else ""}{chg:.2f} ({"+" if chg >= 0 else ""}{pct:.2f}%)</div></div>'
      for name, (price, chg, pct) in macro_data.items()
    ])
    st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)
  if regime_info and not compact:
    st.markdown(
      f'<div style="background:{regime_info["bg"]}; border:1px solid {regime_info["border"]}; '
      f'color:{regime_info["color"]}; padding:6px 12px; border-radius:6px; '
      f'font-size:0.78rem; font-weight:700; margin-bottom:12px;">{regime_info["label"]}</div>',
      unsafe_allow_html=True
    )


# --- GEMINI AI CO-PILOT WITH NATIVE GOOGLE SEARCH GROUNDING (google-genai SDK + REST FALLBACK) ---
def get_gemini_api_key():
  try:
    if "GEMINI_API_KEY" in st.secrets:
      return str(st.secrets["GEMINI_API_KEY"]).strip()
  except Exception:
    pass
  return os.environ.get("GEMINI_API_KEY", "").strip() or str(settings.get("gemini_api_key", "")).strip()


def fetch_gmail_newsletters_imap(max_chars=4500):
  gmail_user = ""
  gmail_pass = ""
  try:
    if "GMAIL_USER" in st.secrets:
      gmail_user = str(st.secrets["GMAIL_USER"]).strip()
    if "GMAIL_APP_PASSWORD" in st.secrets:
      gmail_pass = str(st.secrets["GMAIL_APP_PASSWORD"]).strip()
  except Exception:
    pass
  if not gmail_user:
    gmail_user = str(settings.get("gmail_user", "ling.angels@gmail.com")).strip()
  if not gmail_pass:
    gmail_pass = str(settings.get("gmail_app_password", "")).strip()
  if not gmail_user or not gmail_pass:
    return None, "Gmail App Password not set (using live Google Search & RSS fallback)."

  out_blocks = []
  try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    mail.login(gmail_user, gmail_pass)
    mail.select("inbox")
    for label, sender_q in [
      ("STOCKTWITS DAILY RIP", 'FROM "thedailyrip.stocktwits.com"'),
      ("ARK TRADING DESK", 'FROM "arkfunds.com"')
    ]:
      typ, data = mail.search(None, f'({sender_q})')
      if typ != "OK" or not data or not data[0]:
        typ, data = mail.search(None, f'(TEXT "{label.split()[0]}")')
      if typ == "OK" and data and data[0]:
        msg_ids = data[0].split()
        latest_id = msg_ids[-1]
        typ_f, msg_data = mail.fetch(latest_id, "(RFC822)")
        if typ_f == "OK" and msg_data and msg_data[0]:
          raw_email = msg_data[0][1]
          msg_obj = email.message_from_bytes(raw_email)
          subj_raw = msg_obj.get("Subject", "")
          subj_parts = decode_header(subj_raw)
          subj_str = "".join([
            (p.decode(enc or "utf-8", errors="ignore") if isinstance(p, bytes) else str(p))
            for p, enc in subj_parts
          ])
          body_txt = ""
          if msg_obj.is_multipart():
            for part in msg_obj.walk():
              if part.get_content_type() == "text/plain":
                payload_b = part.get_payload(decode=True)
                if payload_b:
                  body_txt += payload_b.decode("utf-8", errors="ignore")
          else:
            payload_b = msg_obj.get_payload(decode=True)
            if payload_b:
              body_txt = payload_b.decode("utf-8", errors="ignore")
          clean_body = " ".join(body_txt.split())[:max_chars]
          out_blocks.append(f"[{label} — Subject: {subj_str}]\n{clean_body}")
    mail.logout()
    if out_blocks:
      return "\n\n".join(out_blocks), f"Loaded {len(out_blocks)} newsletter(s) from {gmail_user}"
    return None, f"Connected to {gmail_user}, no recent Stocktwits/ARK emails found."
  except Exception as e:
    return None, f"IMAP note: {str(e)[:80]}"


def send_strategist_email_report(subject_str, markdown_body):
  gmail_user = ""
  gmail_pass = ""
  try:
    if "GMAIL_USER" in st.secrets:
      gmail_user = str(st.secrets["GMAIL_USER"]).strip()
    if "GMAIL_APP_PASSWORD" in st.secrets:
      gmail_pass = str(st.secrets["GMAIL_APP_PASSWORD"]).strip()
  except Exception:
    pass
  if not gmail_user:
    gmail_user = str(settings.get("gmail_user", "ling.angels@gmail.com")).strip()
  if not gmail_pass:
    gmail_pass = str(settings.get("gmail_app_password", "")).strip()
  recipient = str(settings.get("report_email_to", gmail_user or "ling.angels@gmail.com")).strip()
  if not gmail_user or not gmail_pass:
    return False, "Add GMAIL_APP_PASSWORD in Settings or Streamlit Secrets to enable direct Gmail SMTP delivery."
  try:
    msg = EmailMessage()
    msg["Subject"] = subject_str
    msg["From"] = gmail_user
    msg["To"] = recipient
    msg.set_content(markdown_body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=12) as server:
      server.login(gmail_user, gmail_pass)
      server.send_message(msg)
    return True, f"Emailed report to {recipient}"
  except Exception as e:
    return False, f"SMTP error: {str(e)[:80]}"


@st.cache_data(ttl=600, show_spinner=False)
def fetch_global_cross_sector_news(max_items=24, max_age_hours=72):
  queries = [
    ("oil prices inflation currency depreciation Asia Europe emerging markets economy when:3d", "GLOBAL MACRO"),
    ("Federal Reserve Treasury yields sovereign debt geopolitics war supply chain when:3d", "GEOPOLITICS/RATES"),
    ("defense energy industrials financials healthcare biotech stocks earnings catalyst when:3d", "CROSS-SECTOR"),
    ("ARK Invest Cathie Wood Stocktwits market rotation institutional flows when:3d", "FLOWS/SENTIMENT")
  ]
  pool, seen_links, seen_titles = [], set(), set()
  results = _safe_parallel_map(lambda qt: _fetch_rss_raw(qt[0], 10, qt[1], max_age_hours), queries, max_workers=2)
  for batch in results:
    for item in batch:
      norm_t = item["title"][:45].lower()
      if item["link"] not in seen_links and norm_t not in seen_titles:
        seen_links.add(item["link"]); seen_titles.add(norm_t); pool.append(item)
  return sorted(pool, key=lambda x: x["timestamp"], reverse=True)[:max_items]


SCHEDULE_PROMPT_0615 = (
  "Every day (Monday to Sunday) at 06:15 AM HKT, generate my Daily Chief Strategist Report in English using "
  "Independent Second-Order Anticipation and Chart Confirmation. Do not merely repeat headlines—anticipate lagged "
  "chain reactions before they are priced in. Treat any external commentary (including @sds.getrich) as just one "
  "optional perspective to critically evaluate or challenge, never as gospel. Structure the report into 4 sections:\n"
  "1. LAGGED MACRO, GEOPOLITICAL & CURRENCY CHAIN REACTIONS (GLOBAL SCOPE): Analyze the second- and third-order impact "
  "of current geopolitical conflicts, energy/oil price trajectories, sticky inflation, sovereign debt strain, and "
  "currency depreciation across Asia, Europe, the Middle East, and the US.\n"
  "2. CROSS-SECTOR ANTICIPATION (ALL 11 SECTORS, BEYOND JUST TECH/AI): Trace where capital, pricing power, and orders "
  "are rotating across Energy, Defense, Industrials, Utilities/Power, Financials, Healthcare/Biotech, Materials/Metals, "
  "Consumer, and Tech/AI.\n"
  "3. STRICT CHART & TECHNICAL CONFIRMATION (SEPARATING ANTICIPATION FROM VALUE TRAPS): Cross-check every thesis "
  "against daily candlestick structure (Price vs. 20-EMA, 50-EMA, 150-SMA, RSI, and Volume).\n"
  "4. ACTIONABLE PORTFOLIO & WATCHLIST GAME PLAN: Provide exact Buy Trigger, Stop-Loss, Profit Target, and Potential R/R."
)

SCHEDULE_PROMPT_0915 = (
  "Every day (Monday to Sunday) at 09:15 AM HKT, search my Gmail inbox for the latest emails from "
  "newsletter@thedailyrip.stocktwits.com (including weekend editions) and tradingdesk@arkfunds.com, and generate my "
  "Morning Newsletter & Institutional Flows Audit in English:\n"
  "1. STOCKTWITS 'THE DAILY RIP' CRITIQUE & SECOND-ORDER ANTICIPATION.\n"
  "2. ARK TRADING DESK AUDIT VS. CHART STRUCTURE (Price vs. 20-EMA, 50-EMA, 150-SMA, RVOL, valuation).\n"
  "3. TOP 3 HIGH-CONVICTION ACTION ITEMS with exact Buy Trigger, Stop-Loss, Profit Target, and Potential R/R."
)


@st.cache_data(ttl=1800, show_spinner=False)
def _discover_available_gemini_models(api_key):
  """Queries Gemini API /v1beta/models to find active generateContent text models for this key."""
  if not api_key:
    return []
  excluded_tokens = (
    "vision", "tts", "live", "image", "transcribe", "embedding",
    "robotics", "omni", "decision", "nano-banana", "lyria", "veo", "aqa", "learnlm"
  )
  found = []
  try:
    list_url = f"https://generativelanguage.googleapis.com/v1beta/models?key={urllib.parse.quote(api_key)}"
    req = urllib.request.Request(list_url, headers={"User-Agent": "Quality-Momentum-Cockpit"})
    with urllib.request.urlopen(req, timeout=8) as resp:
      models_data = json.loads(resp.read().decode("utf-8")).get("models", [])
    for m_info in models_data:
      m_name = str(m_info.get("name", "")).replace("models/", "").strip()
      methods = m_info.get("supportedGenerationMethods", [])
      ml = m_name.lower()
      if "generateContent" in methods and "gemini" in ml and not any(tok in ml for tok in excluded_tokens):
        found.append(m_name)
  except Exception:
    pass

  def _rank_model(m_str):
    ml = m_str.lower()
    if ml == "gemini-4-hydrogen": return 1
    if ml == "gemini-4-argon": return 2
    if ml == "gemini-4-carbon": return 3
    if ml == "gemini-3.8-flash": return 4
    if ml == "gemini-3.6-flash": return 5
    if ml == "gemini-3.1-pro-preview": return 6
    if ml == "gemini-3.5-flash-lite": return 7
    if ml == "gemini-3-flash-preview": return 8
    if ml == "gemini-3.1-flash-lite": return 9
    if ml.startswith("gemini-4"): return 10
    if ml.startswith("gemini-3."): return 15
    if ml == "gemini-2.5-pro": return 25
    if ml == "gemini-2.5-flash": return 26
    if "lite" in ml: return 40
    return 50

  return sorted(list(dict.fromkeys(found)), key=_rank_model)


def _format_http_err(exc):
  if isinstance(exc, urllib.error.HTTPError):
    body = ""
    try:
      raw_b = exc.read().decode("utf-8", errors="ignore")
      parsed = json.loads(raw_b)
      body = parsed.get("error", {}).get("message", raw_b[:140])
    except Exception:
      body = str(exc.reason)
    return f"HTTP {exc.code}: {str(body)[:140]}"
  return str(exc)[:140]


def query_gemini_copilot(user_prompt, chat_history, portfolio_context, model_pref="auto", thinking_level="MEDIUM", enable_search=True, system_override=None):
  api_key = get_gemini_api_key()
  if not api_key:
    return "Please enter your **Gemini API Key** in Settings or the AI Co-Pilot tab (or set `GEMINI_API_KEY` in Streamlit Secrets) to enable live chat."

  today_str = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M HKT")
  sys_text = system_override or (
    f"You are an institutional-grade Chief Investment Strategist & Quantitative Trading Co-Pilot (Current date/time: {today_str}). "
    "Use Google Search grounding whenever real-time news, earnings prints, Fed commentary, analyst revisions, or current macro events are relevant—never rely on stale pre-cutoff memory. "
    "Prioritize second-order anticipation and strict daily candlestick confirmation (20-EMA, 50-EMA, 150-SMA, RVOL, 8 Playbooks). "
    "For options suggestions, only recommend directional long Calls/Puts (0.85-0.90 Delta LEAPS Calls or tactical 14-45 DTE single-leg Calls/Puts)—never suggest put-selling or wheel strategies. "
    "Keep formatting crisp, data-dense, and free of decorative emojis. Always include exact price levels, stop-loss, target, and R/R.\n\n"
    f"LIVE DASHBOARD & TECHNICAL CONTEXT:\n{portfolio_context}"
  )

  discovered = _discover_available_gemini_models(api_key)
  verified_active_defaults = [
    "gemini-4-hydrogen",
    "gemini-4-argon",
    "gemini-3.8-flash",
    "gemini-4-carbon",
    "gemini-3.5-flash-lite",
    "gemini-3.1-pro-preview",
    "gemini-2.5-flash",
    "gemini-2.5-pro"
  ]

  if model_pref and model_pref != "auto":
    # Try user's exact selection first, then discovered models available to their key, then active defaults
    candidate_models = list(dict.fromkeys([model_pref] + discovered + verified_active_defaults))
  else:
    candidate_models = list(dict.fromkeys(discovered + verified_active_defaults))

  # Cap attempts to top 6 distinct candidates so UI stays snappy
  candidate_models = candidate_models[:6]
  lvl_upper = str(thinking_level or "MEDIUM").upper()
  if lvl_upper not in ("LOW", "MEDIUM", "HIGH"):
    lvl_upper = "MEDIUM"
  budget_map = {"HIGH": 4096, "MEDIUM": 1536, "LOW": 256}
  t_budget = budget_map.get(lvl_upper, 1536)

  errors_log = []

  # --- PRIMARY PATH: OFFICIAL google-genai SDK WITH NATIVE GOOGLE SEARCH GROUNDING ---
  if HAS_GOOGLE_GENAI:
    try:
      client = genai.Client(api_key=api_key)
      sdk_contents = []
      for msg in chat_history[-10:]:
        role = "user" if msg["role"] == "user" else "model"
        sdk_contents.append(genai_types.Content(role=role, parts=[genai_types.Part.from_text(text=msg["content"])]))
      sdk_contents.append(genai_types.Content(role="user", parts=[genai_types.Part.from_text(text=user_prompt)]))

      search_tools = [genai_types.Tool(google_search=genai_types.GoogleSearch())] if enable_search else None

      for model_name in candidate_models:
        ml = model_name.lower()
        cfg_variants = []
        if any(k in ml for k in ("gemini-4", "gemini-3")):
          try:
            cfg_variants.append((True, genai_types.GenerateContentConfig(
              system_instruction=sys_text,
              temperature=0.35,
              max_output_tokens=8192,
              tools=search_tools,
              thinking_config=genai_types.ThinkingConfig(thinking_level=lvl_upper)
            )))
          except Exception:
            pass
        elif "2.5" in ml:
          try:
            cfg_variants.append((True, genai_types.GenerateContentConfig(
              system_instruction=sys_text,
              temperature=0.35,
              max_output_tokens=8192,
              tools=search_tools,
              thinking_config=genai_types.ThinkingConfig(thinking_budget=t_budget)
            )))
          except Exception:
            pass
        cfg_variants.append((True, genai_types.GenerateContentConfig(
          system_instruction=sys_text,
          temperature=0.35,
          max_output_tokens=8192,
          tools=search_tools
        )))

        for used_search, cfg in cfg_variants:
          try:
            resp = client.models.generate_content(
              model=model_name,
              contents=sdk_contents,
              config=cfg
            )
            final_text = (resp.text or "").strip()
            if not final_text and resp.candidates:
              parts = resp.candidates[0].content.parts or []
              final_text = "\n".join([getattr(p, "text", "") for p in parts if getattr(p, "text", "") and not getattr(p, "thought", False)]).strip()
            if not final_text:
              continue
            sources_md = ""
            try:
              gm = resp.candidates[0].grounding_metadata
              if gm and getattr(gm, "grounding_chunks", None):
                links, seen_u = [], set()
                for ch in gm.grounding_chunks:
                  web = getattr(ch, "web", None)
                  if web and getattr(web, "uri", None) and web.uri not in seen_u:
                    seen_u.add(web.uri)
                    title = getattr(web, "title", None) or web.uri
                    links.append(f"[{title}]({web.uri})")
                if links:
                  sources_md = "\n\n**Web Sources:** " + " | ".join(links[:6])
            except Exception:
              pass
            g_tag = "Google Search: ON" if (enable_search and used_search) else "Google Search: OFF"
            return f"{final_text}{sources_md}\n\n---\n*Engine: `{model_name}` (google-genai SDK) | {g_tag} | Thinking: {lvl_upper}*"
          except Exception as e:
            errors_log.append(f"SDK/{model_name}: {str(e)[:110]}")
            if "404" in str(e) or "NOT_FOUND" in str(e).upper():
              break
            continue
    except Exception as e:
      errors_log.append(f"SDK init: {str(e)[:110]}")

  # --- FALLBACK PATH: DIRECT REST API WITH NATIVE GOOGLE SEARCH GROUNDING ---
  rest_contents = []
  for msg in chat_history[-10:]:
    role = "user" if msg["role"] == "user" else "model"
    rest_contents.append({"role": role, "parts": [{"text": msg["content"]}]})
  rest_contents.append({"role": "user", "parts": [{"text": user_prompt}]})

  for model_name in candidate_models:
    ml = model_name.lower()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model_name)}:generateContent?key={urllib.parse.quote(api_key)}"
    gen_variants = []
    if any(k in ml for k in ("gemini-4", "gemini-3")):
      gen_variants.append((True, {"temperature": 0.35, "maxOutputTokens": 8192, "thinkingConfig": {"thinkingLevel": lvl_upper}}))
    elif "2.5" in ml:
      gen_variants.append((True, {"temperature": 0.35, "maxOutputTokens": 8192, "thinkingConfig": {"thinkingBudget": t_budget}}))
    gen_variants.append((True, {"temperature": 0.35, "maxOutputTokens": 8192}))
    if enable_search:
      gen_variants.append((False, {"temperature": 0.35, "maxOutputTokens": 8192}))

    for use_search_flag, g_cfg in gen_variants:
      payload = {
        "systemInstruction": {"parts": [{"text": sys_text}]},
        "contents": rest_contents,
        "generationConfig": g_cfg
      }
      if enable_search and use_search_flag:
        payload["tools"] = [{"google_search": {}}]
      try:
        req = urllib.request.Request(
          url,
          data=json.dumps(payload).encode("utf-8"),
          headers={"Content-Type": "application/json"},
          method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
          res_json = json.loads(resp.read().decode("utf-8"))
          cand = res_json["candidates"][0]
          parts = cand.get("content", {}).get("parts", [])
          ans_chunks = [p.get("text", "") for p in parts if not p.get("thought", False) and p.get("text")]
          final_text = "\n".join(ans_chunks).strip() if ans_chunks else (parts[-1].get("text", "") if parts else "")
          if not final_text:
            continue
          sources_md = ""
          gm = cand.get("groundingMetadata", {})
          chunks = gm.get("groundingChunks", [])
          if chunks:
            links, seen_u = [], set()
            for ch in chunks:
              w = ch.get("web", {})
              u = w.get("uri")
              if u and u not in seen_u:
                seen_u.add(u)
                links.append(f"[{w.get('title', u)}]({u})")
            if links:
              sources_md = "\n\n**Web Sources:** " + " | ".join(links[:6])
          g_tag = "Google Search: ON" if (enable_search and use_search_flag) else "Google Search: OFF (fallback)"
          return f"{final_text}{sources_md}\n\n---\n*Engine: `{model_name}` (REST Grounded) | {g_tag} | Thinking: {lvl_upper}*"
      except Exception as e:
        err_msg = _format_http_err(e)
        errors_log.append(f"REST/{model_name}: {err_msg}")
        if "HTTP 404" in err_msg or "NOT_FOUND" in err_msg.upper():
          break
        continue

  disc_note = f"Discovered models for your key: `{', '.join(discovered[:8])}`" if discovered else "Model discovery returned 0 models (verify your GEMINI_API_KEY in Google AI Studio)."
  err_summary = " | ".join(errors_log[:4]) if errors_log else "Unknown error"
  return f"Gemini API Error — {err_summary}\n\n{disc_note}"


def build_second_order_strategist_prompt(report_mode="0615_MAIN", custom_newsletters_text=""):
  all_tks = get_all_monitored_tickers()
  global_cross_sector_bench = [
    "EWJ", "EWY", "FXI", "VGK", "EEM", "USO", "GLD", "SLV", "TLT", "UUP",
    "XLE", "XLI", "ITA", "XLF", "XLV", "XLU", "URA", "CCJ", "GE", "RTX",
    "LLY", "JPM", "COST", "NVDA", "AMD", "MU", "INTC", "AVGO", "TSM", "VRT", "COHR", "LITE", "PLTR"
  ]
  combined_tks = list(dict.fromkeys(all_tks + global_cross_sector_bench))[:50]
  snap = fetch_batch_market_data(combined_tks, account_size=settings["account_size"])
  t_lines = []
  for sym_k in combined_tks:
    if sym_k not in snap:
      continue
    r = snap[sym_k]
    t_lines.append(
      f"{sym_k}: Close=${r['Price']:.2f} ({r['Change_Pct']:+.2f}%), Playbook={r['TCT_Model']}, Action={r['TCT_Action']}, "
      f"Trigger=${r['BOS_Level']:.2f}, Target=${r['Target_Price']:.2f}, Stop=${r['Stop_Price']:.2f}, "
      f"Pot_RR={r.get('Potential_RR', r['R_Multiple']):.2f}R, EMA20=${r['EMA20_Val']:.2f}, EMA50=${r['EMA50_Val']:.2f}, "
      f"SMA150=${r['SMA150_Val']:.2f}, RSI14={r['RSI']:.1f}, RVOL={r['Paced_RVOL']:.2f}x, FundScore={r.get('Fund_Score', 70)}"
    )
  pos_lines = [
    f"{p['Ticker']}: {p['Shares']} shs @ ${p['BuyPrice']:.2f}, Stop ${p['StopLoss']:.2f}, +15% Target ${p['Target15']:.2f}, Thesis: {p.get('Remarks', '')}"
    for p in positions
  ]
  vids = fetch_sds_latest_videos()
  vid_lines = [f"- [{v['date']}] {v['title']} ({v['link']})" for v in vids[:5]]
  wl_news = fetch_watchlist_news_pool(all_tks[:18], max_items=14, max_age_hours=72)
  macro_sec_news = fetch_global_cross_sector_news(max_items=16, max_age_hours=72)
  mcf_news = fetch_metals_crypto_fx_news(max_items=8, max_age_hours=72)
  news_lines = [f"- [{a.get('ticker', 'MACRO')} | {a['age']}] {a['title']} ({a['publisher']})" for a in (macro_sec_news[:12] + wl_news[:10] + mcf_news[:6])]

  imap_text, imap_status = fetch_gmail_newsletters_imap()
  nl_block = custom_newsletters_text.strip() or imap_text or "No direct IMAP newsletter body loaded; use Google Search grounding to retrieve the latest Stocktwits Daily Rip and ARK Trading Desk activity."

  if report_mode == "0915_SUPPLEMENT":
    task_instructions = (
      "Write the 09:15 AM HKT Morning Newsletter & Institutional Flows Audit (Stocktwits + ARK Cross-Check) in crisp, zero-emoji English.\n"
      "1. Stocktwits 'The Daily Rip' Critique & Second-Order Anticipation.\n"
      "2. ARK Trading Desk Audit vs. Daily Candlestick Structure (20-EMA, 50-EMA, 150-SMA, RVOL, Fundamental Score).\n"
      "3. Top 3 High-Conviction Action Items with exact Trigger, Stop-Loss, Target, and Potential R/R."
    )
  else:
    task_instructions = (
      "Write the 06:15 AM HKT Chief Strategist Global Anticipation & Cross-Sector Report in crisp, zero-emoji English.\n"
      "Use Google Search grounding for real-time macro/geopolitical verification.\n"
      "1. Lagged Macro, Geopolitical & Currency Chain Reactions (US, Europe, Asia, Middle East).\n"
      "2. Cross-Sector Second-Order Winners & Losers (All 11 Sectors).\n"
      "3. Strict Chart & Technical Confirmation (20-EMA, 50-EMA, 150-SMA, RSI, RVOL, Fundamental Score).\n"
      "4. Actionable Portfolio & Watchlist Game Plan (Top 5 Setups with Trigger, Stop-Loss, Target, Share Size, R/R)."
    )

  return (
    f"{task_instructions}\n\n"
    f"=== OPEN POSITIONS ===\n" + ("\n".join(pos_lines) if pos_lines else "None open.") + "\n\n"
    f"=== RECENT HEADLINES ===\n" + "\n".join(news_lines) + "\n\n"
    f"=== @sds.getrich RECENT VIDEOS ===\n" + "\n".join(vid_lines) + "\n\n"
    f"=== NEWSLETTERS ({imap_status}) ===\n{nl_block}\n\n"
    f"=== LIVE TECHNICAL & FUNDAMENTAL DATA ===\n" + "\n".join(t_lines)
  )


def build_video_anticipation_prompt(channel_tag, video_obj):
  v_url = video_obj.get("link", "")
  v_title = video_obj.get("title", "")
  v_date = video_obj.get("date", "")
  vid_transcript_ctx = fetch_youtube_video_transcript_and_context(v_url, fallback_title=v_title)

  all_tks = get_all_monitored_tickers()
  extra_tks = ["NVDA", "TSLA", "GOOGL", "MSFT", "AAPL", "AMD", "MU", "AVGO", "VRT", "COHR", "LITE", "CRDO", "PLTR", "APP", "ABBV", "AXP", "COST", "WMT", "GLD", "SLV", "TLT"]
  combined_tks = list(dict.fromkeys(all_tks + extra_tks))[:45]
  snap = fetch_batch_market_data(combined_tks, account_size=settings["account_size"])
  t_lines = [
    f"{k}: Close=${r['Price']:.2f} ({r['Change_Pct']:+.2f}%), {r['TCT_Action']}, Trigger=${r['BOS_Level']:.2f}, Target=${r['Target_Price']:.2f}, Stop=${r['Stop_Price']:.2f}, EMA20=${r['EMA20_Val']:.2f}, EMA50=${r['EMA50_Val']:.2f}, SMA150=${r['SMA150_Val']:.2f}, Fund={r.get('Fund_Score', 70)}"
    for k, r in snap.items()
  ]

  if "ryan" in channel_tag.lower():
    instructions = (
      f"Audit @OptionsWithRyan video ({v_date} — {v_title}) in crisp, zero-emoji English.\n"
      "Reject all put-selling/wheel trades; convert valid Stage 2 stock ideas into 0.85-0.90 Delta LEAPS Calls (>9M DTE) or tactical 14-45 DTE directional Calls/Puts.\n"
      "1. Summary of Macro Stance & Tickers Mentioned.\n"
      "2. Stock-by-Stock Candlestick & Fundamental Audit.\n"
      "3. Directional Options Execution Plan (LEAPS vs Tactical Calls/Puts).\n"
      "4. Exact Trade Tickets (Trigger, Stop-Loss, Target, R/R)."
    )
  else:
    instructions = (
      f"Synthesize and critically audit @sds.getrich video ({v_date} — {v_title}) in crisp, zero-emoji English.\n"
      "Use live Google Search grounding to fact-check claims and trace second-order sector winners/losers.\n"
      "1. Core Thesis Summary.\n"
      "2. Independent Critique (Where We Agree vs Disagree).\n"
      "3. Second-Order Sector Rotation & Beneficiaries.\n"
      "4. Chart-Confirmed Stock & Directional Options Game Plan."
    )

  return f"{instructions}\n\n{vid_transcript_ctx}\n\n=== LIVE TECHNICAL DATA ===\n" + "\n".join(t_lines)


def render_ai_copilot_tab():
  st.markdown("<h1>AI Macro & Chief Strategist Cockpit</h1>", unsafe_allow_html=True)
  if not st.session_state.get("strategist_report"):
    saved_rep = load_json(REPORT_CACHE_FILE, {})
    if isinstance(saved_rep, dict) and saved_rep.get("body"):
      st.session_state["strategist_report"] = saved_rep.get("body", "")
      st.session_state["strategist_report_title"] = saved_rep.get("title", "Daily Chief Strategist Report")

  ctl1, ctl2, ctl3 = st.columns([1.6, 1.0, 1.0])
  model_choice = ctl1.selectbox(
    "AI Model Engine",
    [
      "auto",
      "gemini-4-hydrogen",
      "gemini-4-argon",
      "gemini-4-carbon",
      "gemini-3.8-flash",
      "gemini-3.5-flash-lite",
      "gemini-3.1-pro-preview"
    ],
    index=0,
    format_func=lambda x: {
      "auto": "Auto (Best Active Grounded Model)",
      "gemini-4-hydrogen": "Gemini 4 Hydrogen (Fast · General Default)",
      "gemini-4-argon": "Gemini 4 Argon (Frontier Reasoning)",
      "gemini-4-carbon": "Gemini 4 Carbon (Max Reasoning)",
      "gemini-3.8-flash": "Gemini 3.8 Flash (Fast · Low Cost)",
      "gemini-3.5-flash-lite": "Gemini 3.5 Flash-Lite (Ultra-Fast)",
      "gemini-3.1-pro-preview": "Gemini 3.1 Pro Preview"
    }[x]
  )
  thinking_choice = ctl2.selectbox(
    "Thinking Depth",
    ["HIGH", "MEDIUM", "LOW"],
    index=1,
    format_func=lambda x: {"HIGH": "High Thinking", "MEDIUM": "Medium Thinking", "LOW": "Low Thinking (Fast)"}[x]
  )
  enable_web_search = ctl3.checkbox("Live Google Search Grounding", value=True, key="copilot_web_grounding")

  btn_r1, btn_r2, btn_r3, btn_r4 = st.columns(4)
  run_main_btn = btn_r1.button("1. Run 06:15 AM Global Anticipation", type="primary", use_container_width=True)
  run_supp_btn = btn_r2.button("2. Run 09:15 AM Stocktwits & ARK Audit", type="primary", use_container_width=True)
  run_sds_latest_btn = btn_r3.button("3. Anticipate Latest @sds.getrich Video", type="primary", use_container_width=True)
  run_ryan_latest_btn = btn_r4.button("4. Audit @OptionsWithRyan Latest Picks", type="primary", use_container_width=True)

  monitored_tks = get_all_monitored_tickers()[:35]
  live_snap = fetch_batch_market_data(monitored_tks, account_size=settings["account_size"])
  macro_now, regime_now = fetch_macro_and_regime(refresh_bucket=int(time.time() // 60))
  risk_now = compute_unified_portfolio_risk(live_snap)

  macro_lines = [f"{k}: {v[0]:,.2f} ({v[2]:+.2f}%)" for k, v in macro_now.items()]
  pos_summary = [
    f"{p['Ticker']}: {p['Shares']} shs @ ${p['BuyPrice']:.2f}, Stop ${p['StopLoss']:.2f}, +15% Target ${p['Target15']:.2f}, Remarks: {p.get('Remarks', '')}"
    for p in positions
  ]
  opt_pos_summary = [
    f"{op['Ticker']} {op['Expiration']} ${op['Strike']:g} {op['Option_Type']} ({op.get('Contracts', 1)}x @ ${op.get('Buy_Premium', 0):.2f}, OptStop ${op.get('Option_Stop', 0):.2f}, StockStop ${op.get('Stock_Stop', 0):.2f})"
    for op in options_positions
  ]
  tech_lines = [
    f"{k}: ${r['Price']:.2f} ({r['Change_Pct']:+.2f}%), {r['TCT_Action']}, Trigger=${r['BOS_Level']:.2f}, Target=${r['Target_Price']:.2f}, Stop=${r['Stop_Price']:.2f}, SMA150=${r['SMA150_Val']:.2f}, EMA20=${r['EMA20_Val']:.2f}, RSI={r['RSI']:.1f}, RV30={r.get('RV30_Pct', 38):.1f}%, Fund={r.get('Fund_Score', 70)}"
    for k, r in list(live_snap.items())[:30]
  ]
  port_ctx = (
    f"LIVE MACRO STRIP: {' | '.join(macro_lines)}\nREGIME: {regime_now['label']}\n\n"
    f"UNIFIED PORTFOLIO RISK: Combined Net Delta=${risk_now['net_delta_usd']:+,.0f} (Stocks=${risk_now['stock_delta_usd']:,.0f}, Options=${risk_now['opt_delta_usd']:+,.0f}) | Daily Options Theta=${risk_now['opt_theta_daily_usd']:+,.2f}/day | Net Vega=${risk_now['opt_vega_usd']:+,.1f}\n\n"
    "OPEN STOCK POSITIONS:\n" + ("\n".join(pos_summary) if pos_summary else "None open.") +
    "\n\nOPEN OPTIONS POSITIONS:\n" + ("\n".join(opt_pos_summary) if opt_pos_summary else "None open.") +
    "\n\nWATCHLIST LIVE TECHNICALS:\n" + ("\n".join(tech_lines) if tech_lines else "No watchlist data loaded.")
  )

  def _execute_and_open_full_width(prompt_text, report_heading):
    with st.spinner(f"Running Google-Grounded Analysis: {report_heading}..."):
      generated_rep = query_gemini_copilot(
        prompt_text, [], port_ctx,
        model_pref=model_choice, thinking_level=thinking_choice, enable_search=enable_web_search
      )
      st.session_state["strategist_report"] = generated_rep
      st.session_state["strategist_report_title"] = report_heading
      save_json(REPORT_CACHE_FILE, {"title": report_heading, "body": generated_rep})
      st.session_state.chat_messages.append({"role": "assistant", "content": f"**{report_heading}**\n\n{generated_rep}"})
      if settings.get("auto_email_report", False):
        ok_auto, msg_auto = send_strategist_email_report(report_heading, generated_rep)
        if ok_auto:
          st.toast(f"Auto-emailed report: {msg_auto}")
      st.rerun()

  if run_main_btn:
    _execute_and_open_full_width(
      build_second_order_strategist_prompt(report_mode="0615_MAIN"),
      f"06:15 AM Global Anticipation & Cross-Sector Report ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
  if run_supp_btn:
    _execute_and_open_full_width(
      build_second_order_strategist_prompt(report_mode="0915_SUPPLEMENT"),
      f"09:15 AM Stocktwits & ARK Institutional Audit ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
    )
  if run_sds_latest_btn:
    latest_sds = fetch_sds_latest_videos()[0]
    _execute_and_open_full_width(
      build_video_anticipation_prompt("sds", latest_sds),
      f"@sds.getrich Forward Anticipation ({latest_sds['date']}): {latest_sds['title'][:55]}"
    )
  if run_ryan_latest_btn:
    latest_ryan = fetch_ryan_latest_videos()[0]
    _execute_and_open_full_width(
      build_video_anticipation_prompt("ryan", latest_ryan),
      f"@OptionsWithRyan Stock & Options Audit ({latest_ryan['date']}): {latest_ryan['title'][:55]}"
    )

  if st.session_state.get("strategist_report"):
    rep_title = st.session_state.get("strategist_report_title", "Daily Chief Strategist Report")
    rep_body = st.session_state["strategist_report"]
    st.markdown(
      f'<div style="background:#ffffff;border:2px solid #0f291e;border-radius:10px;padding:18px 24px;margin:10px 0 16px 0;">'
      f'<div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #e2dcd0;padding-bottom:8px;margin-bottom:12px;">'
      f'<span style="font-family:Newsreader,serif;font-size:1.3rem;font-weight:700;color:#0f291e;">{rep_title}</span>'
      f'<span class="badge badge-tct-buy">FULL-WIDTH READER</span></div>',
      unsafe_allow_html=True
    )
    st.markdown(rep_body)
    st.markdown('</div>', unsafe_allow_html=True)

    rb1, rb2, rb3, rb4 = st.columns(4)
    if rb1.button("Email Report to Gmail", type="primary", use_container_width=True, key="fw_email_btn"):
      ok_e, msg_e = send_strategist_email_report(rep_title, rep_body)
      st.success(msg_e) if ok_e else st.warning(msg_e)
    if rb2.button("Push Report to ntfy / Telegram", use_container_width=True, key="fw_push_btn"):
      ok_p, msg_p = send_ntfy_alert(rep_body[:3800], rep_title)
      st.success(f"Pushed: {msg_p}") if ok_p else st.error(msg_p)
    rb3.download_button(
      "Download Report (.md)",
      data=f"# {rep_title}\n\n{rep_body}".encode("utf-8"),
      file_name=f"chief_strategist_report_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
      mime="text/markdown",
      use_container_width=True,
      key="fw_dl_md"
    )
    if rb4.button("Close Full-Width Report", use_container_width=True, key="fw_close_btn"):
      st.session_state["strategist_report"] = ""
      save_json(REPORT_CACHE_FILE, {})
      st.rerun()

  with st.expander("Copy-Ready Gemini Scheduled Action Prompts (06:15 AM & 09:15 AM HKT) + Gmail Auto-Delivery Setup", expanded=False):
    st.markdown("**Schedule 1 — 06:15 AM HKT Daily Global Anticipation Prompt:**")
    st.code(SCHEDULE_PROMPT_0615, language="text")
    st.markdown("**Schedule 2 — 09:15 AM HKT Daily Stocktwits & ARK Newsletter Audit Prompt:**")
    st.code(SCHEDULE_PROMPT_0915, language="text")
    st.markdown("---")
    em_c1, em_c2, em_c3 = st.columns([1.4, 1.4, 1.2])
    g_usr = em_c1.text_input("Gmail Address", value=str(settings.get("gmail_user", "ling.angels@gmail.com")), key="cfg_g_usr")
    g_app_pw = em_c2.text_input("Gmail 16-Char App Password", value=str(settings.get("gmail_app_password", "")), type="password", placeholder="xxxx xxxx xxxx xxxx", key="cfg_g_pw")
    auto_em_chk = em_c3.checkbox("Auto-Email When Generated", value=bool(settings.get("auto_email_report", False)), key="cfg_auto_em")
    if st.button("Save Gmail Delivery Settings", key="save_gmail_cfg"):
      settings["gmail_user"] = g_usr.strip()
      settings["gmail_app_password"] = g_app_pw.strip()
      settings["report_email_to"] = g_usr.strip()
      settings["auto_email_report"] = bool(auto_em_chk)
      sync_file_to_github(settings, SETTINGS_FILE)
      st.success("Saved Gmail delivery settings.")

  st.markdown("---")
  col_macro, col_chat = st.columns([1.1, 1.4])
  with col_macro:
    st.subheader("Video Feed & Quick Audits")
    feed_tab_sds, feed_tab_ryan = st.tabs(["@sds.getrich (Macro)", "@OptionsWithRyan (Picks)"])
    with feed_tab_sds:
      if st.button("Refresh @sds.getrich Feed", use_container_width=True, key="ref_sds_btn"):
        fetch_sds_latest_videos.clear(); fetch_youtube_video_transcript_and_context.clear(); st.rerun()
      vids = fetch_sds_latest_videos()
      sel_sds_v = st.selectbox("Select @sds.getrich Video", vids, index=0, format_func=lambda v: f"[{v['date']}] {v['title']}", key="sel_sds_video_box")
      if sel_sds_v:
        if st.button(f"Analyze Video ({sel_sds_v['date']})", type="primary", use_container_width=True, key="btn_an_sds_sel"):
          _execute_and_open_full_width(
            build_video_anticipation_prompt("sds", sel_sds_v),
            f"@sds.getrich Forward Anticipation ({sel_sds_v['date']}): {sel_sds_v['title'][:55]}"
          )
        st.markdown(f"[Open video on YouTube]({sel_sds_v['link']})")

    with feed_tab_ryan:
      if st.button("Refresh @OptionsWithRyan Feed", use_container_width=True, key="ref_ryan_btn"):
        fetch_ryan_latest_videos.clear(); fetch_youtube_video_transcript_and_context.clear(); st.rerun()
      ryan_vids = fetch_ryan_latest_videos()
      sel_ryan_v = st.selectbox("Select @OptionsWithRyan Video", ryan_vids, index=0, format_func=lambda v: f"[{v['date']}] {v['title']}", key="sel_ryan_video_box")
      if sel_ryan_v:
        if st.button(f"Audit Ryan Video ({sel_ryan_v['date']})", type="primary", use_container_width=True, key="btn_an_ryan_sel"):
          _execute_and_open_full_width(
            build_video_anticipation_prompt("ryan", sel_ryan_v),
            f"@OptionsWithRyan Stock & Options Audit ({sel_ryan_v['date']}): {sel_ryan_v['title'][:55]}"
          )
        st.markdown(f"[Open video on YouTube]({sel_ryan_v['link']})")

    st.markdown("**Quick Portfolio Audits:**")
    qp1, qp2 = st.columns(2)
    if qp1.button("Audit Open Stock & Options Risk", use_container_width=True):
      _execute_and_open_full_width(
        "Audit my current open stock and option positions, combined Net Delta exposure, daily Theta bleed, and stop-losses. Identify urgent risk adjustments.",
        f"Portfolio Risk & Delta/Theta Audit ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
      )
    if qp2.button("Macro & Sector Rotation Scan", use_container_width=True):
      _execute_and_open_full_width(
        "Using live Google Search and my current macro strip, identify where institutional capital is rotating across the 11 sectors and which watchlist tickers have Stage 2 confirmation for LEAPS or tactical options.",
        f"Global Macro & 11-Sector Rotation ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
      )

  with col_chat:
    st.subheader("Portfolio AI Co-Pilot (Google Search Grounded)")
    curr_key = get_gemini_api_key()
    with st.expander("Gemini API Key Settings" if curr_key else "Enter Gemini API Key to Enable Chat", expanded=not bool(curr_key)):
      in_key = st.text_input("Gemini API Key (Google AI Studio)", value=curr_key, type="password", key="gem_key_in")
      kc1, kc2 = st.columns(2)
      if kc1.button("Save API Key", type="primary", use_container_width=True, key="save_gem_key"):
        settings["gemini_api_key"] = in_key.strip()
        save_json(SETTINGS_FILE, settings)
        _discover_available_gemini_models.clear()
        st.success("API Key saved.")
        st.rerun()
      if kc2.button("Check Available Models", use_container_width=True, key="chk_gem_models"):
        _discover_available_gemini_models.clear()
        avail = _discover_available_gemini_models(in_key.strip() or curr_key)
        if avail:
          st.success(f"Connected. Active models for your key: {', '.join(avail[:10])}")
        else:
          st.error("No models returned. Confirm your GEMINI_API_KEY is active in Google AI Studio.")
    chat_box = st.container(height=440)
    with chat_box:
      if not st.session_state.chat_messages:
        sdk_status = "google-genai SDK active" if HAS_GOOGLE_GENAI else "REST Google Search fallback active"
        st.info(f"Connected ({sdk_status}). Ask about live macro headlines, sector rotations, portfolio Delta/Theta exposure, or compare multiple tickers.")
      for m in st.session_state.chat_messages:
        with st.chat_message(m["role"]):
          st.markdown(m["content"])
    user_q = st.chat_input("Ask about macro regime, cross-sector rotations, or portfolio trades...")
    if user_q:
      st.session_state.chat_messages.append({"role": "user", "content": user_q})
      with st.spinner("Searching live web & analyzing..."):
        reply = query_gemini_copilot(
          user_q, st.session_state.chat_messages[:-1], port_ctx,
          model_pref=model_choice, thinking_level=thinking_choice, enable_search=enable_web_search
        )
      st.session_state.chat_messages.append({"role": "assistant", "content": reply})
      st.rerun()
    if st.session_state.chat_messages:
      act_c1, act_c2, act_c3 = st.columns(3)
      if act_c1.button("Open Last Reply Full-Width", use_container_width=True, key="expand_last_rep"):
        last_assist = [m["content"] for m in st.session_state.chat_messages if m["role"] == "assistant"]
        if last_assist:
          st.session_state["strategist_report"] = last_assist[-1]
          st.session_state["strategist_report_title"] = f"Co-Pilot Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M')})"
          save_json(REPORT_CACHE_FILE, {"title": st.session_state["strategist_report_title"], "body": last_assist[-1]})
          st.rerun()
      if act_c2.button("Email Last Reply", use_container_width=True, key="email_last_rep"):
        last_assist = [m["content"] for m in st.session_state.chat_messages if m["role"] == "assistant"]
        if last_assist:
          ok_e, msg_e = send_strategist_email_report(f"AI Co-Pilot Analysis ({datetime.now().strftime('%Y-%m-%d %H:%M')})", last_assist[-1])
          st.success(msg_e) if ok_e else st.warning(msg_e)
      if act_c3.button("Clear Chat", use_container_width=True, key="clr_chat_btn"):
        st.session_state.chat_messages = []
        st.rerun()


def render_inline_dossier_chat(sym, d, funds):
  """Stock-aware Google-Search-grounded chatbot embedded directly beneath the Dossier candlestick chart."""
  if sym not in st.session_state.dossier_chats:
    st.session_state.dossier_chats[sym] = []
  history = st.session_state.dossier_chats[sym]

  # Build rich live ticker snapshot silently
  held_stocks = [p for p in positions if p.get("Ticker") == sym]
  held_opts = [op for op in options_positions if op.get("Ticker") == sym]
  pos_str = "None"
  if held_stocks or held_opts:
    parts = []
    for p in held_stocks:
      parts.append(f"STOCK {p['Shares']} shs @ ${p['BuyPrice']:.2f} (Stop ${p['StopLoss']:.2f})")
    for op in held_opts:
      parts.append(f"OPT {op.get('Contracts', 1)}x {op['Expiration']} ${op['Strike']:g} {op['Option_Type']} @ ${op['Buy_Premium']:.2f} (OptStop ${op.get('Option_Stop', 0):.2f})")
    pos_str = " | ".join(parts)

  ticker_ctx = (
    f"ACTIVE TICKER: {sym} ({funds.get('Company Name', sym)})\n"
    f"LIVE PRICE: ${d['Price']:,.2f} ({d['Change_Pct']:+.2f}%) | Day Range: ${d['Day_Low']:,.2f} - ${d['Day_High']:,.2f}\n"
    f"MOVING AVERAGES: 20-EMA=${d['EMA20_Val']:,.2f} | 50-EMA=${d['EMA50_Val']:,.2f} | 150-SMA=${d['SMA150_Val']:,.2f}\n"
    f"MOMENTUM & VOLATILITY: RSI(14)={d['RSI']:.1f} | RSI(2)={d['RSI2']:.0f} | Paced RVOL={d['Paced_RVOL']:.2f}x | 63D RS vs SPY={d['RS_Diff']:+.1f}% | 30D RV={d.get('RV30_Pct', 38):.1f}% | ATR14=${d.get('ATR14', 0):.2f}\n"
    f"PLAYBOOK ENGINE: {d['TCT_Model']} | Action={d['TCT_Action']} | Trigger=${d['BOS_Level']:,.2f} | Target=${d['Target_Price']:,.2f} (+{d['Target_Pct']:.1f}%) | Stop=${d['Stop_Price']:,.2f} ({d['Stop_Pct']:.1f}%) | Potential R/R={d.get('Potential_RR', d['R_Multiple']):.2f}R\n"
    f"FUNDAMENTALS: Score={d.get('Fund_Score', 70)}/100 ({d.get('Fund_Note', '')}) | Market Cap={funds.get('Market Cap')} | Trail/Fwd P/E={funds.get('Trailing P/E')}/{funds.get('Forward P/E')} | D/E={funds.get('Debt/Equity')} | Analyst Target={funds.get('Target Price')} | Earnings={funds.get('Earnings Date')}\n"
    f"USER OPEN POSITION IN {sym}: {pos_str}"
  )

  # Compact controls + 3 one-tap iPad prompt buttons
  qc1, qc2, qc3, qc4 = st.columns([1.4, 1.4, 1.4, 0.9])
  prompt_clicked = None
  if qc1.button("Audit Catalysts & News", use_container_width=True, key=f"dos_q1_{sym}"):
    prompt_clicked = f"Search the latest real-time news, earnings prints, guidance, and analyst revisions for {sym}. Separate material catalysts from noise and assess whether the current price action (${d['Price']:,.2f}) confirms institutional accumulation."
  if qc2.button("Check Bear Case / Traps", use_container_width=True, key=f"dos_q2_{sym}"):
    prompt_clicked = f"Give me the sharpest bear case and hidden traps for {sym} right now (balance sheet, valuation, margin pressure, earnings IV risk, or technical failure levels relative to its 50-EMA ${d['EMA50_Val']:,.2f} and 150-SMA ${d['SMA150_Val']:,.2f})."
  if qc3.button("Suggest Options Play", use_container_width=True, key=f"dos_q3_{sym}"):
    prompt_clicked = f"Based on {sym}'s live chart (${d['Price']:,.2f}, {d['TCT_Action']}, 30D RV {d.get('RV30_Pct', 38):.1f}%, earnings {funds.get('Earnings Date')}), recommend whether a 0.85-0.90 Delta LEAPS Call (>9M DTE), a tactical 14-45 DTE directional Call/Put, or staying in cash makes the most sense. Specify strike zone, expiry window, stock stop-loss, and earnings IV risk. No put-selling."
  if qc4.button("Clear Chat", use_container_width=True, key=f"dos_clr_{sym}"):
    st.session_state.dossier_chats[sym] = []
    st.rerun()

  # Inline compact form input right below the 3 buttons (iPad friendly — stays close to chart)
  with st.form(key=f"dos_chat_form_{sym}", clear_on_submit=True):
    ic1, ic2, ic3 = st.columns([4.8, 1.1, 0.9])
    user_text = ic1.text_input(
      f"Ask about {sym}",
      placeholder=f"Ask about {sym} (e.g. Is this pullback safe before earnings? Which LEAPS strike fits?)",
      label_visibility="collapsed"
    )
    dos_model = ic2.selectbox(
      "Model",
      ["auto", "gemini-4-hydrogen", "gemini-4-argon", "gemini-3.8-flash", "gemini-3.5-flash-lite"],
      index=0,
      format_func=lambda x: {
        "auto": "Auto (Fast)",
        "gemini-4-hydrogen": "Hydrogen",
        "gemini-4-argon": "Argon (Deep)",
        "gemini-3.8-flash": "3.8 Flash",
        "gemini-3.5-flash-lite": "3.5 Lite"
      }[x],
      label_visibility="collapsed"
    )
    send_clicked = ic3.form_submit_button("Send", type="primary", use_container_width=True)

  active_q = prompt_clicked or (user_text.strip() if send_clicked and user_text.strip() else None)
  if active_q:
    history.append({"role": "user", "content": active_q})
    with st.spinner(f"Searching live web & analyzing {sym}..."):
      ans = query_gemini_copilot(
        active_q, history[:-1], ticker_ctx,
        model_pref=dos_model, thinking_level="HIGH" if "argon" in dos_model else "LOW", enable_search=True
      )
    history.append({"role": "assistant", "content": ans})
    st.session_state.dossier_chats[sym] = history
    st.rerun()

  if history:
    chat_view = st.container(height=360)
    with chat_view:
      for m in history:
        if m["role"] == "user":
          st.markdown(f'<div class="chat-bubble-user"><b>You:</b> {m["content"]}</div>', unsafe_allow_html=True)
        else:
          st.markdown(m["content"])
          st.markdown("<hr style='margin:6px 0;border-color:#e2dcd0;'>", unsafe_allow_html=True)
  else:
    st.caption(f"Auto-loaded live snapshot for {sym} (Price ${d['Price']:,.2f} | {d['TCT_Action']} | Fund {d.get('Fund_Score', 70)}/100 | Position: {pos_str}). Google Search grounding is active.")


# --- SIDEBAR NAVIGATION ---
st.sidebar.markdown(
  '<div style="padding:8px 0 16px 0;">'
  '<span style="display:inline-block;width:8px;height:8px;background:#22c55e;'
  'border-radius:50%;margin-right:6px;"></span>'
  '<span style="font-size:0.78rem;font-weight:700;letter-spacing:0.06em;color:#a1a1aa;">'
  'EDITORIAL TERMINAL ENGINE</span>'
  '<h2 style="color:#f4efe6 !important;margin:5px 0 0 0;font-size:1.35rem;">Ledger</h2>'
  '<span style="font-size:0.70rem;color:#c5a059;text-transform:uppercase;'
  'letter-spacing:0.1em;font-weight:700;">Momentum | Stage 2 | Options v12</span></div>',
  unsafe_allow_html=True
)
navigation = st.sidebar.radio(
  "Navigation",
  [
    "Dashboard",
    "Active Positions",
    "Options",
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
ai_badge = "Web Grounding: google-genai" if HAS_GOOGLE_GENAI else "Web Grounding: REST Fallback"
st.sidebar.markdown(
  f'<div style="position:fixed;bottom:14px;font-size:0.70rem;color:#a1a1aa;line-height:1.45;">'
  f'{sync_badge}<br>{ai_badge}<br>Tap any <b>Ticker</b> for Dossier + AI Chat</div>',
  unsafe_allow_html=True
)

# Global Macro Strip (Shown everywhere except Live Real-Time Quotes, where it runs INSIDE the live auto-refresh loop)
if navigation != "Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
  macro_data, regime_info = fetch_macro_and_regime(refresh_bucket=int(time.time() // 120))
  render_macro_bar_html(macro_data, regime_info, compact=False)

# --- STOCK DOSSIER VIEW (WITH INLINE GOOGLE-GROUNDED AI CHAT DIRECTLY UNDER CHART) ---
if st.session_state.inspect_symbol is not None:
  sym = st.session_state.inspect_symbol
  funds = fetch_ticker_fundamentals(sym)
  comp_name = funds.get("Company Name", sym)
  header_label = f"{sym} — {comp_name}" if comp_name and comp_name.upper() != sym.upper() else sym
  col_back, col_title = st.columns([1.0, 9.0])
  with col_back:
    if st.button("Back", type="primary", use_container_width=True):
      clear_inspection()
      st.rerun()
  with col_title:
    st.markdown(f"<h1>{header_label}</h1>", unsafe_allow_html=True)

  c_ctrl, c_plot = st.columns([1.15, 3.85])
  with c_ctrl:
    st.markdown("### Chart Timeframe")
    chart_period = st.selectbox(
      "Visible Window",
      ["3mo", "6mo", "9mo", "1y", "2y", "3y", "5y", "max"],
      index=2,
      format_func=lambda x: {
        "3mo": "3 Months", "6mo": "6 Months", "9mo": "9 Months (Default)",
        "1y": "1 Year", "2y": "2 Years", "3y": "3 Years", "5y": "5 Years", "max": "All-Time (Max)"
      }[x]
    )
    chart_bar_interval = st.radio(
      "Candle Bar Size", ["1d", "1wk"], index=0,
      format_func=lambda x: "Daily (1D)" if x == "1d" else "Weekly (1W)",
      horizontal=True
    )
    st.markdown("### Overlays")
    show_rr_box = st.checkbox("Risk/Reward Zone Box", value=True)
    show_trendline = st.checkbox("Auto Swing Trendline", value=True)
    show_tct_lines = st.checkbox("Full-Width Target/Stop Lines", value=False)
    show_ema20 = st.checkbox("EMA 20 (Gold)", value=True)
    show_ema50 = st.checkbox("EMA 50 (Green)", value=True)
    show_ma150 = st.checkbox("150 MA (Teal)", value=True)
    ma150_type = st.radio("150 MA Mode", ["SMA 150", "EMA 150"], index=0, horizontal=True, label_visibility="collapsed")
    show_ema200 = st.checkbox("EMA 200 (Purple)", value=False)
    show_bb = st.checkbox("Bollinger Bands (20, 2)", value=False)

  fetch_period = "5y" if chart_period in ("3mo", "6mo", "9mo", "1y", "2y", "3y", "5y") else "max"
  d = fetch_single_ticker_data(sym, account_size=settings["account_size"], period=fetch_period, interval=chart_bar_interval)

  if d is not None:
    df_hist = d["History"].copy()
    if "EMA150" not in df_hist.columns:
      df_hist["EMA150"] = df_hist["Close"].ewm(span=150, adjust=False).mean()
    if "SMA150" not in df_hist.columns:
      df_hist["SMA150"] = df_hist["Close"].rolling(150, min_periods=1).mean()
    last_dt_full = pd.to_datetime(df_hist.index[-1])
    window_days_map = {"3mo": 92, "6mo": 183, "9mo": 275, "1y": 366, "2y": 731, "3y": 1096, "5y": 1826}
    if chart_period in window_days_map:
      cutoff_dt = last_dt_full - pd.Timedelta(days=window_days_map[chart_period])
      df_view = df_hist[pd.to_datetime(df_hist.index) >= cutoff_dt].copy()
      if len(df_view) < 15:
        df_view = df_hist.tail(min(len(df_hist), 60)).copy()
    else:
      df_view = df_hist.copy()

    raw_mcap = funds.get("Market Cap")
    mcap_text = f"${raw_mcap / 1e9:.1f}B" if isinstance(raw_mcap, (int, float)) and raw_mcap > 0 else "N/A"
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
    w52_h, w52_l = funds.get("52W High", "N/A"), funds.get("52W Low", "N/A")
    w52_text = f"${w52_h:,.2f} / ${w52_l:,.2f}" if isinstance(w52_h, (int, float)) and isinstance(w52_l, (int, float)) else f"{w52_h} / {w52_l}"
    ath_raw, atl_raw = funds.get("All-Time High"), funds.get("All-Time Low")
    ath_val = max(float(df_hist["High"].max()), float(ath_raw) if isinstance(ath_raw, (int, float)) else 0.0)
    atl_val = min(float(df_hist["Low"].min()), float(atl_raw) if isinstance(atl_raw, (int, float)) and atl_raw > 0 else float(df_hist["Low"].min()))
    hist_hl_text = f"${ath_val:,.2f} / ${atl_val:,.2f}"
    earn_text = funds.get("Earnings Date", "No upcoming (60d)")

    with c_ctrl:
      st.markdown("---")
      st.markdown("### Trade Ticket")
      st.markdown(f"**Playbook:** `{d['TCT_Model']}`")
      st.markdown(f"**Signal:** `{d['TCT_Action']}`")
      st.markdown(f"**Buy Trigger:** `${d['BOS_Level']:,.2f}`")
      st.markdown(f"**Target:** `${d['Target_Price']:,.2f}` (+{d['Target_Pct']:.1f}%)")
      st.markdown(f"**Stop-Loss:** `${d['Stop_Price']:,.2f}` ({d['Stop_Pct']:.1f}%)")
      st.markdown(f"**Potential R/R:** `{d.get('Potential_RR', d['R_Multiple']):.2f}R`")
      st.markdown(f"**0.5% Size:** `{d['Shares_05Pct']} shs` (${d['Pos_Value']:,.0f})")
      st.markdown(f"**{ma150_type}:** `${ma150_val:,.2f}`")
      st.markdown(f"**RSI(14/2):** `{d['RSI']:.1f}` / `{d['RSI2']:.0f}` | **30D RV:** `{d.get('RV30_Pct', 38):.1f}%`")
      st.markdown(f"*{d['TCT_Explain']}*")
      st.markdown("---")
      st.markdown(f"**Fund Score:** `{d.get('Fund_Score', 70)}/100` ({d.get('Fund_Note', '')})")
      st.markdown(f"**Market Cap:** `{mcap_text}`")
      st.markdown(f"**P/E (Trl/Fwd):** `{pe_text}` / `{fpe_text}`")
      st.markdown(f"**Analyst Target:** `{analyst_tgt_text}`")
      st.markdown(f"**52W H/L:** `{w52_text}`")
      st.markdown(f"**All-Time H/L:** `{hist_hl_text}`")
      st.markdown(f"**Earnings:** `{earn_text}`")
      if st.button(f"+ Send {sym} to Options Radar", use_container_width=True, key=f"dos_opt_{sym}"):
        if "Options Radar" not in watchlists:
          watchlists["Options Radar"] = []
        if sym not in watchlists["Options Radar"]:
          watchlists["Options Radar"].insert(0, sym)
          sync_file_to_github(watchlists, DATA_FILE)
        st.success(f"Added {sym} to Options Radar.")

    with c_plot:
      f1, f2, f3, f4, f5, f6 = st.columns(6)
      f1.metric("Price", f"${d['Price']:,.2f}", f"{'+' if d['Change'] >= 0 else ''}{d['Change_Pct']:.2f}%")
      f2.metric("Signal", d["TCT_Short_Sig"])
      f3.metric("Buy Trigger", f"${d['BOS_Level']:,.2f}")
      f4.metric("Target", f"${d['Target_Price']:,.2f}", f"+{d['Target_Pct']:.1f}%")
      f5.metric("Stop-Loss", f"${d['Stop_Price']:,.2f}", f"{d['Stop_Pct']:.1f}%", delta_color="inverse")
      f6.metric("Fund / Comp", f"{d.get('Fund_Score', 70)} / {d['Score']}", f"{d.get('Potential_RR', d['R_Multiple']):.2f}R")

      fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.66, 0.17, 0.17])
      fig.add_trace(
        go.Candlestick(
          x=df_view.index, open=df_view['Open'], high=df_view['High'],
          low=df_view['Low'], close=df_view['Close'],
          increasing_line_color="#089981", increasing_fillcolor="#089981",
          decreasing_line_color="#f23645", decreasing_fillcolor="#f23645",
          name="Candles"
        ),
        row=1, col=1
      )
      if show_ema20:
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view['EMA20'], line=dict(color="#d4af37", width=1.5), name="EMA 20"), row=1, col=1)
      if show_ema50:
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view['EMA50'], line=dict(color="#15803d", width=1.6), name="EMA 50"), row=1, col=1)
      if show_ma150:
        col_150 = "SMA150" if ma150_type == "SMA 150" else "EMA150"
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view[col_150], line=dict(color="#0284c7", width=2.0), name=ma150_type), row=1, col=1)
      if show_ema200:
        fig.add_trace(go.Scatter(x=df_view.index, y=df_hist.loc[df_view.index, 'EMA200'], line=dict(color="#7c3aed", width=1.5), name="EMA 200"), row=1, col=1)
      if show_bb:
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view['BB_Upper'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Upper"), row=1, col=1)
        fig.add_trace(go.Scatter(x=df_view.index, y=df_view['BB_Lower'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Lower"), row=1, col=1)

      first_dt = pd.to_datetime(df_view.index[0])
      last_dt = pd.to_datetime(df_view.index[-1])
      vis_span_days = max(30, int((last_dt - first_dt).total_seconds() / 86400.0))
      step_days = 7 if chart_bar_interval == "1wk" else 1
      box_span_days = max(step_days * 12, int(vis_span_days * 0.24))
      box_start_dt = last_dt + pd.Timedelta(days=step_days * 2)
      box_end_dt = box_start_dt + pd.Timedelta(days=box_span_days)

      entry_px = float(d["BOS_Level"])
      tgt_px = float(d["Target_Price"])
      stp_px = float(d["Stop_Price"])
      pot_rr_val = float(d.get("Potential_RR", d["R_Multiple"]))
      pot_tgt_pct = ((tgt_px - entry_px) / entry_px * 100.0) if entry_px > 0 else d["Target_Pct"]
      pot_stp_pct = ((stp_px - entry_px) / entry_px * 100.0) if entry_px > 0 else d["Stop_Pct"]

      if show_rr_box:
        fig.add_shape(type="rect", x0=box_start_dt, x1=box_end_dt, y0=entry_px, y1=tgt_px, fillcolor="rgba(8, 153, 129, 0.18)", line=dict(color="rgba(8, 153, 129, 0.65)", width=1.2), layer="below", row=1, col=1)
        fig.add_shape(type="rect", x0=box_start_dt, x1=box_end_dt, y0=stp_px, y1=entry_px, fillcolor="rgba(242, 54, 69, 0.20)", line=dict(color="rgba(242, 54, 69, 0.65)", width=1.2), layer="below", row=1, col=1)
        fig.add_shape(type="line", x0=last_dt, x1=box_end_dt, y0=entry_px, y1=entry_px, line=dict(color="#475569", width=1.4, dash="dot"), row=1, col=1)
        fig.add_annotation(x=box_end_dt, y=tgt_px, xanchor="left", xshift=4, text=f"<b>{tgt_px:,.2f} (+{pot_tgt_pct:.1f}%)</b>", showarrow=False, font=dict(size=10, color="#ffffff"), bgcolor="#089981", borderpad=3, row=1, col=1)
        fig.add_annotation(x=box_end_dt, y=entry_px, xanchor="left", xshift=4, text=f"<b>{entry_px:,.2f} ({pot_rr_val:.2f}R)</b>", showarrow=False, font=dict(size=10, color="#ffffff"), bgcolor="#334155", borderpad=3, row=1, col=1)
        fig.add_annotation(x=box_end_dt, y=stp_px, xanchor="left", xshift=4, text=f"<b>{stp_px:,.2f} ({pot_stp_pct:.1f}%)</b>", showarrow=False, font=dict(size=10, color="#ffffff"), bgcolor="#f23645", borderpad=3, row=1, col=1)

      if show_trendline and len(df_view) >= 30:
        try:
          sub_w = df_view.iloc[-min(len(df_view), 140):]
          h_vals = sub_w["High"].values.astype(float)
          h_idx = sub_w.index
          half_w = max(8, len(h_vals) // 2)
          p1_pos = int(np.argmax(h_vals[:half_w]))
          p2_pos = half_w + int(np.argmax(h_vals[half_w:]))
          if p2_pos > p1_pos + 4:
            x_p1, y_p1 = pd.to_datetime(h_idx[p1_pos]), float(h_vals[p1_pos])
            x_p2, y_p2 = pd.to_datetime(h_idx[p2_pos]), float(h_vals[p2_pos])
            days_12 = max(1.0, (x_p2 - x_p1).total_seconds() / 86400.0)
            slope_per_day = (y_p2 - y_p1) / days_12
            x_ext = box_start_dt + pd.Timedelta(days=int(box_span_days * 0.25))
            y_ext = y_p2 + slope_per_day * ((x_ext - x_p2).total_seconds() / 86400.0)
            fig.add_trace(go.Scatter(x=[x_p1, x_p2, x_ext], y=[y_p1, y_p2, y_ext], mode="lines", line=dict(color="#2563eb", width=2.0), name="Swing Trendline"), row=1, col=1)
        except Exception:
          pass

      if show_tct_lines:
        fig.add_hline(y=d["Target_Price"], line_dash="dash", line_color="#089981", line_width=1.5, annotation_text=f"TARGET ${d['Target_Price']:,.2f}", annotation_position="top left", row=1, col=1)
        fig.add_hline(y=d["BOS_Level"], line_dash="dot", line_color="#2563eb", line_width=1.4, annotation_text=f"TRIGGER ${d['BOS_Level']:,.2f}", annotation_position="bottom left", row=1, col=1)
        fig.add_hline(y=d["Stop_Price"], line_dash="dash", line_color="#f23645", line_width=1.5, annotation_text=f"STOP ${d['Stop_Price']:,.2f}", annotation_position="bottom right", row=1, col=1)

      vol_colors = ['#089981' if c >= o else '#f23645' for c, o in zip(df_view['Close'], df_view['Open'])]
      fig.add_trace(go.Bar(x=df_view.index, y=df_view['Volume'], marker_color=vol_colors, name="Volume"), row=2, col=1)
      fig.add_trace(go.Scatter(x=df_view.index, y=df_view['MACD'], line=dict(color="#2563eb", width=1.2), name="MACD"), row=3, col=1)
      fig.add_trace(go.Scatter(x=df_view.index, y=df_view['MACD_Signal'], line=dict(color="#ea580c", width=1.2), name="Signal"), row=3, col=1)
      fig.add_trace(go.Bar(x=df_view.index, y=df_view['MACD_Hist'], marker_color="#cbd5e1", name="Histogram"), row=3, col=1)

      vis_low = float(df_view["Low"].min())
      vis_high = float(df_view["High"].max())
      if show_rr_box:
        vis_low = min(vis_low, stp_px)
        vis_high = max(vis_high, tgt_px)
      y_span = max(vis_high - vis_low, vis_high * 0.05)
      x_right_limit = box_end_dt + pd.Timedelta(days=int(box_span_days * 0.55)) if show_rr_box else last_dt + pd.Timedelta(days=step_days * 6)
      for r_i in (1, 2, 3):
        fig.update_xaxes(range=[first_dt, x_right_limit], row=r_i, col=1)
        fig.update_yaxes(side="right", row=r_i, col=1)
      fig.update_yaxes(range=[max(0.0, vis_low - y_span * 0.06), vis_high + y_span * 0.08], row=1, col=1)
      fig.update_layout(
        height=610,
        margin=dict(l=8, r=36, t=34, b=8),
        paper_bgcolor="white", plot_bgcolor="white",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0, font=dict(size=10))
      )
      st.plotly_chart(fig, use_container_width=True)

      # Compact Tab Pair directly beneath the Candlestick Chart: Inline AI Stock Chat | News & Profile
      dos_tab_ai, dos_tab_news = st.tabs([
        f"AI Stock Chat — {sym} (Live Web Grounded)",
        f"News & Company Profile — {sym}"
      ])
      with dos_tab_ai:
        render_inline_dossier_chat(sym, d, funds)
      with dos_tab_news:
        st.markdown("#### Verified Recent Headlines (Last 72 Hours)")
        sym_news = _fetch_rss_raw(f'"{sym}" stock when:3d', max_per_query=8, ticker_tag=sym, max_age_hours=settings["max_news_age_hours"])
        if sym_news:
          for a in sym_news:
            st.markdown(f'- **[{a["age"]}]** <a href="{a["link"]}" target="_blank" style="color:#0f291e;font-weight:600;">{a["title"]}</a> *({a["publisher"]} | {a["date"]})*', unsafe_allow_html=True)
        else:
          st.caption("No verified headlines in the past 72 hours.")
        st.markdown("#### Corporate Profile")
        st.write(funds.get("Business Summary", "No business overview provided."))
  else:
    st.error(f"Unable to retrieve historical chart data for {sym}.")

# --- MAIN NAVIGATION VIEWS ---
else:
  if navigation == "Dashboard":
    st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
    all_monitored = get_all_monitored_tickers()
    stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])
    if stock_records:
      best_pick = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + (15 if x["RS_Leader"] else 0) + x["Score"])
      sign_b = "+" if best_pick["Change"] >= 0 else "-"
      st.markdown(
        f'<div style="background-color:#0f291e;border-radius:8px;padding:14px 18px;color:#fbf9f4;margin-bottom:14px;">'
        f'<div style="font-size:0.70rem;text-transform:uppercase;letter-spacing:0.10em;color:#c5a059;font-weight:700;">'
        f'STANDOUT SETUP | {best_pick["TCT_Action"]} | {best_pick["TCT_Model"]}</div>'
        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">'
        f'<div><a href="?inspect={best_pick["Ticker"]}" target="_self" class="hero-ticker-link">{best_pick["Ticker"]}</a>'
        f'<span class="num" style="font-size:1.18rem;color:#e2e8f0;margin-left:10px;font-weight:700;">${best_pick["Price"]:,.2f}</span>'
        f'<span class="num" style="color:{"#4ade80" if best_pick["Change"] >= 0 else "#f87171"};font-weight:700;margin-left:8px;">'
        f'{sign_b}${abs(best_pick["Change"]):.2f} ({best_pick["Change_Pct"]:+.2f}%)</span>'
        f'<div class="num" style="color:#cbd5e1;font-size:0.84rem;margin-top:5px;">'
        f'<b>Trigger:</b> ${best_pick["BOS_Level"]:,.2f} | '
        f'<b>Target:</b> ${best_pick["Target_Price"]:,.2f} (+{best_pick["Target_Pct"]:.1f}%) | '
        f'<b>Stop:</b> ${best_pick["Stop_Price"]:,.2f} ({best_pick["Stop_Pct"]:.1f}%) | '
        f'<b>Size:</b> {best_pick["Shares_05Pct"]} shs ({best_pick["R_Multiple"]:.1f}R) | '
        f'<b>Fund:</b> {best_pick.get("Fund_Score", 70)}/100</div></div>'
        f'<div style="text-align:right;">'
        f'<div style="font-size:1.9rem;font-weight:700;color:#c5a059;font-family:Newsreader,serif;line-height:1;">{best_pick["Score"]}</div>'
        f'<div style="font-size:0.65rem;color:#94a3b8;text-transform:uppercase;">Composite</div></div></div></div>',
        unsafe_allow_html=True
      )
    col_left, col_right = st.columns([1.9, 1.1])
    with col_left:
      tab_watch, tab_macro, tab_mcf = st.tabs([f"Watchlist News ({len(all_monitored)})", "General Market", "Metals, Crypto & USD"])
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
      for r in sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))[:12]:
        sign_s = "+" if r["Change"] >= 0 else "-"
        clr_s = "#15803d" if r["Change"] >= 0 else "#b91c1c"
        st.markdown(
          f'<div style="background:white;border:1px solid #e2dcd0;border-radius:6px;padding:7px 11px;margin-bottom:6px;font-variant-numeric:tabular-nums;">'
          f'<div style="display:flex;justify-content:space-between;align-items:center;">'
          f'<div><a href="?inspect={r["Ticker"]}" target="_self" class="ticker-link" style="font-size:0.96rem;">{r["Ticker"]}</a>'
          f'<span class="badge {r["TCT_Badge"]}" style="margin-left:5px;font-size:0.60rem;">{r["TCT_Short_Sig"]}</span></div>'
          f'<div style="text-align:right;"><span style="font-weight:700;font-size:0.86rem;">${r["Price"]:,.2f}</span>'
          f'<span style="color:{clr_s};font-size:0.74rem;font-weight:700;margin-left:4px;">{sign_s}${abs(r["Change"]):.2f} ({r["Change_Pct"]:+.2f}%)</span></div></div>'
          f'<div style="font-size:0.71rem;color:#52525b;margin-top:3px;">'
          f'Trig <b>${r["BOS_Level"]:,.2f}</b> | Tgt <b style="color:#15803d;">${r["Target_Price"]:,.2f}</b> | Stp <b style="color:#b91c1c;">${r["Stop_Price"]:,.2f}</b> | Sc <b>{r["Score"]}</b></div></div>',
          unsafe_allow_html=True
        )

  elif navigation == "Active Positions":
    render_active_positions_manager(key_prefix="nav_ap")

  elif navigation == "Options":
    render_options_cockpit_tab()

  elif navigation == "AI Macro & Trade Co-Pilot":
    render_ai_copilot_tab()

  elif navigation == "Live Real-Time Quotes":
    st.markdown("""<style>.block-container { padding-top: 2.2rem !important; padding-bottom: 0.8rem !important; padding-left: 1.0rem !important; padding-right: 1.0rem !important; }</style>""", unsafe_allow_html=True)
    folder_names = list(watchlists.keys())
    folder_options = folder_names + ["All Watchlists Combined"]

    selected_live_folder = st.session_state.get("live_folder_sel", folder_options[0])
    if selected_live_folder not in folder_options:
      selected_live_folder = folder_options[0]
      st.session_state.live_folder_sel = selected_live_folder

    live_sort = st.session_state.get("live_sort_sel", "Rank: Action Signal (Buy First)")
    auto_refresh_choice = st.session_state.get("live_auto_ref_sel", "Auto: 60s")
    edit_mode_live = bool(st.session_state.get("live_edit_mode", False))

    # De-cluttered Single Top Bar: Status Line Left + Single Top-Right Controls Popover
    top_l, top_r = st.columns([6.2, 1.3])
    with top_r:
      with st.popover("Controls", use_container_width=True):
        sel_f_new = st.selectbox(
          "Watchlist", folder_options,
          index=folder_options.index(selected_live_folder),
          key="pop_live_folder"
        )
        if sel_f_new != selected_live_folder:
          st.session_state.live_folder_sel = sel_f_new
          selected_live_folder = sel_f_new
          persist_ui_state()
          st.rerun()

        sort_opts = [
          "Rank: My Saved Order",
          "Rank: Action Signal (Buy First)",
          "Rank: Day % Change (Gainers)",
          "Rank: Day % Change (Losers)",
          "Rank: Relative Strength vs S&P",
          "Rank: Composite Score"
        ]
        sel_sort_new = st.selectbox(
          "Sort Order", sort_opts,
          index=sort_opts.index(live_sort) if live_sort in sort_opts else 1,
          key="pop_live_sort"
        )
        if sel_sort_new != live_sort:
          st.session_state.live_sort_sel = sel_sort_new
          live_sort = sel_sort_new
          st.rerun()

        ref_opts = ["Auto: Off", "Auto: 15s", "Auto: 30s", "Auto: 60s"]
        sel_ref_new = st.selectbox(
          "Auto-Refresh Timer", ref_opts,
          index=ref_opts.index(auto_refresh_choice) if auto_refresh_choice in ref_opts else 3,
          key="pop_live_ref"
        )
        if sel_ref_new != auto_refresh_choice:
          st.session_state.live_auto_ref_sel = sel_ref_new
          auto_refresh_choice = sel_ref_new
          st.rerun()

        if selected_live_folder not in ("All Watchlists Combined", "Active Positions"):
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
              try:
                st.session_state[lv_add_key] = ""
              except Exception:
                pass
          st.text_input(
            f"Quick Add to {selected_live_folder}",
            placeholder="e.g. AVGO, MU",
            key=lv_add_key,
            on_change=_commit_lv_add
          )

        b_pop1, b_pop2 = st.columns(2)
        if b_pop1.button("Refresh Now", type="primary", use_container_width=True, key="pop_ref_now"):
          st.cache_data.clear()
          st.rerun()
        if selected_live_folder != "Active Positions":
          ed_chk = b_pop2.checkbox("Edit List", value=edit_mode_live, key="pop_edit_chk")
          if ed_chk != edit_mode_live:
            st.session_state.live_edit_mode = ed_chk
            edit_mode_live = ed_chk
            st.rerun()

    if selected_live_folder == "All Watchlists Combined":
      active_live_syms = get_all_monitored_tickers()
    elif selected_live_folder == "Active Positions":
      active_live_syms = [p["Ticker"] for p in positions]
    else:
      active_live_syms = list(watchlists.get(selected_live_folder, []))

    run_every_sec = {"Auto: Off": None, "Auto: 15s": 15, "Auto: 30s": 30, "Auto: 60s": 60}.get(auto_refresh_choice)
    ref_tag = f"{run_every_sec}s Live" if run_every_sec else "Manual"
    with top_l:
      st.markdown(
        f'<div class="live-status-bar">'
        f'<span class="live-dot"></span>'
        f'<span>{selected_live_folder}</span>'
        f'<span style="color:#94a3b8;">|</span>'
        f'<span>{ref_tag}</span>'
        f'<span style="color:#94a3b8;">|</span>'
        f'<span>{len(active_live_syms)} Tickers</span>'
        f'<span style="color:#94a3b8;">|</span>'
        f'<span style="color:#64748b;font-weight:500;">{live_sort.replace("Rank: ", "")}</span>'
        f'</div>',
        unsafe_allow_html=True
      )

    if edit_mode_live and selected_live_folder not in ("Active Positions", "All Watchlists Combined"):
      render_watchlist_reorder_panel(selected_live_folder, key_prefix="lv")

    def render_live_watchboard_content():
      bucket = int(time.time() // run_every_sec) if run_every_sec else int(time.time() // 60)
      # Live Macro Strip inside the auto-refresh container so macro cards & stock quotes tick together
      live_macro, live_regime = fetch_macro_and_regime(refresh_bucket=bucket)
      render_macro_bar_html(live_macro, live_regime, compact=True)

      live_records = fetch_batch_market_data(active_live_syms, account_size=settings["account_size"], refresh_bucket=bucket)
      ordered_syms = [s for s in active_live_syms if s in live_records]
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
        tot_invested = sum(p["Shares"] * p["BuyPrice"] for p in positions)
        tot_value = sum(p["Shares"] * live_records.get(p["Ticker"], {}).get("Price", p["BuyPrice"]) for p in positions)
        daily_pnl = sum(p["Shares"] * live_records.get(p["Ticker"], {}).get("Change", 0.0) for p in positions)
        prev_val = tot_value - daily_pnl
        daily_pct = (daily_pnl / prev_val * 100.0) if prev_val > 0 else 0.0
        unreal_pnl = tot_value - tot_invested
        unreal_pct = (unreal_pnl / tot_invested * 100) if tot_invested else 0.0
        c_m1, c_m2, c_m3, c_m4 = st.columns(4)
        c_m1.metric("Invested Cost", f"${tot_invested:,.2f}")
        c_m2.metric("Market Value", f"${tot_value:,.2f}")
        c_m3.metric("Today P&L", f"${daily_pnl:+,.2f}", f"{daily_pct:+.2f}%")
        c_m4.metric("Unrealized P&L", f"${unreal_pnl:+,.2f}", f"{unreal_pct:+.2f}%")
        if positions:
          rows_html = ""
          for p in positions:
            sym = p["Ticker"]
            if sym not in live_records:
              continue
            d = live_records[sym]
            price, bp, shares = d["Price"], p["BuyPrice"], p["Shares"]
            pnl = (price - bp) * shares
            pnl_pct = ((price - bp) / bp) * 100
            clr = "#15803d" if pnl >= 0 else "#b91c1c"
            px_clr = "#15803d" if d["Change"] >= 0 else "#b91c1c"
            rule_status = f'<span class="badge {d["TCT_Badge"]}">{d["TCT_Short_Sig"]}</span>'
            if price <= p["StopLoss"]:
              rule_status = '<span class="badge badge-tct-sell">STOP HIT</span>'
            elif price >= p["Target15"] and not p.get("HalfSold", False):
              rule_status = '<span class="badge badge-tct-buy">+15% TRIM 50%</span>'
            elif price < d["EMA20_Val"]:
              rule_status = '<span class="badge badge-caution">< 20-EMA</span>'
            rows_html += (
              f'<tr><td>{rule_status}</td>'
              f'<td><a href="?inspect={sym}" target="_self" class="rt-sym-link">{sym}</a></td>'
              f'<td style="font-weight:800;"><a href="?rt_chart={sym}" target="_self" class="rt-price-link" style="color:{px_clr};">${price:,.2f}</a> <span style="font-size:0.74rem;color:{px_clr};">({d["Change_Pct"]:+.2f}%)</span></td>'
              f'<td>${bp:,.2f} <span style="font-size:0.72rem;color:#71717a;">({shares})</span></td>'
              f'<td style="color:{clr};font-weight:800;">${pnl:+,.2f} ({pnl_pct:+.2f}%)</td>'
              f'<td style="color:#b91c1c;font-weight:700;">${p["StopLoss"]:,.2f}</td>'
              f'<td style="color:#15803d;font-weight:700;">${p["Target15"]:,.2f}</td>'
              f'<td style="font-size:0.84rem;color:#52525b;">${d["EMA20_Val"]:,.2f}</td></tr>'
            )
          st.markdown(
            f'<table class="live-quote-table"><thead><tr><th>Status</th><th>Ticker</th><th>Price & Day %</th><th>Cost (Shs)</th><th>Unrealized P&L</th><th>Stop</th><th>+15% Tgt</th><th>20-EMA</th></tr></thead><tbody>{rows_html}</tbody></table>',
            unsafe_allow_html=True
          )
        else:
          st.info("No active positions tracked.")
      else:
        def build_half_table_html(sym_slice):
          rows_html = ""
          for sym in sym_slice:
            d = live_records[sym]
            chg, pct = d["Change"], d["Change_Pct"]
            color = "#15803d" if chg >= 0 else "#b91c1c"
            sign = "+" if chg >= 0 else "-"
            short_sig = d.get("TCT_Short_Sig", "UPTREND")
            sig_bg = d.get("TCT_Sig_Bg", "#dbeafe")
            sig_fg = d.get("TCT_Sig_Color", "#1e3a8a")
            rows_html += (
              f'<tr>'
              f'<td><span class="badge-pill-sig" style="background:{sig_bg};color:{sig_fg};">{short_sig}</span></td>'
              f'<td><a href="?inspect={sym}" target="_self" class="rt-sym-link" title="Open Dossier & AI Chat">{sym}</a></td>'
              f'<td style="font-weight:800;color:{color};"><a href="?rt_chart={sym}" target="_self" class="rt-price-link" style="color:{color};" title="Open Live Chart">{d["Price"]:,.2f}</a></td>'
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
          now_hkt = datetime.now(ZoneInfo("Asia/Hong_Kong")).strftime("%H:%M:%S HKT")
          st.caption(f"Tap Symbol for Full Dossier + AI Chat | Tap Price for Live Chart | Updated {now_hkt} | {live_regime['label']}")
        else:
          st.info("No symbols found in this watchlist.")

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
      ch_c1, ch_c2, ch_c3, ch_c4 = st.columns([4.0, 1.5, 1.6, 1.1])
      with ch_c1:
        st.markdown(f"### Live Chart: `{chart_sym}`")
      with ch_c2:
        with st.popover("Timeframe", use_container_width=True):
          rt_interval = st.radio(
            "Bar Interval", ["5", "15", "60", "240", "D"],
            format_func=lambda x: {"5": "5-Min", "15": "15-Min", "60": "1-Hour (BOS)", "240": "4-Hour", "D": "Daily"}[x],
            index=2, key="rt_tv_interval"
          )
      with ch_c3:
        if st.button(f"Open {chart_sym} Dossier", use_container_width=True):
          st.session_state.inspect_symbol = chart_sym
          st.rerun()
      with ch_c4:
        if st.button("Close", type="primary", use_container_width=True):
          st.session_state.rt_chart_symbol = None
          st.rerun()
      components.html(f"""
<div class="tradingview-widget-container" style="height:460px;width:100%;">
<div id="tradingview_rt_chart" style="height:448px;width:100%;"></div>
<script type="text/javascript" src="https://s3.tradingview.com/tv.js"></script>
<script type="text/javascript">
new TradingView.widget({{
"autosize": true, "symbol": "{chart_sym}", "interval": "{rt_interval}",
"timezone": "America/New_York", "theme": "light", "style": "1", "locale": "en",
"enable_publishing": false, "hide_top_toolbar": false, "save_image": false,
"studies": ["EMA@tv-basicstudies", "RSI@tv-basicstudies"],
"container_id": "tradingview_rt_chart"
}});
</script>
</div>
""", height=465)

  elif navigation == "Screener":
    st.markdown("<h1>Multi-Playbook & Stage 2 Market Screener</h1>", unsafe_allow_html=True)
    all_watchlist_syms = get_all_monitored_tickers()
    mcf_extra = GICS_SECTORS.get("Indexes, Precious Metals & Crypto", [])
    full_market_syms = list(dict.fromkeys([s for s_list in GICS_SECTORS.values() for s in s_list] + all_watchlist_syms))
    universe_mode = st.radio(
      "1. Scan Universe",
      [
        f"Expanded Market + Macro ({len(full_market_syms)} Assets)",
        f"My Watchlists + Macro ({len(list(dict.fromkeys(all_watchlist_syms + mcf_extra)))} Assets)",
        "Custom Sector Selection"
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
      _save_screener_results(sorted([d for d in s_data.values() if d.get("Is_Stage2_Higher_Low")], key=lambda x: -x["Score"]), "Stage 2 Higher Low")
    if r1_c2.button("150-MA Reversal Radar", use_container_width=True, type="primary"):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d.get("Is_150MA_Reversal_Radar")], key=lambda x: -x["Score"]), "150-MA Reversal Radar")
    if r1_c3.button("Pure Momentum Leaders", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["Is_Pure_Momentum"]], key=lambda x: -x["RS_Diff"]), "Pure Momentum Leaders")
    if r1_c4.button("All BUY Triggers", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["TCT_Priority"] == 0], key=lambda x: -x["Score"]), "All Immediate BUY Triggers")
    if r2_c1.button("TCT Bottom Boxes", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["TCT_Valid_Range"]], key=lambda x: (x["TCT_Priority"], -x["R_Multiple"])), "TCT Bottom Boxes")
    if r2_c2.button("20-EMA Pullback & Coil", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["Playbook_Cat"] == "SWING_PULLBACK"], key=lambda x: -x["Score"]), "20-EMA Pullback & Squeeze Coils")
    if r2_c3.button("20D & Gap Breakouts", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["Playbook_Cat"] == "BREAKOUT"], key=lambda x: -x["Score"]), "20D & Gap Breakouts")
    if r2_c4.button("RSI-2 Oversold Bounce", use_container_width=True):
      s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
      _save_screener_results(sorted([d for d in s_data.values() if d["Is_Oversold_Swing"]], key=lambda x: x["RSI2"]), "RSI-2 Oversold Bounce")

    with st.expander("Custom Sector & Technical Filter Builder", expanded=False):
      f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])
      with f_col1:
        selected_sectors = [sec for sec in GICS_SECTORS.keys() if st.checkbox(sec, value=True, key=f"sec_{sec}")]
      with f_col2:
        s_rs = st.checkbox("Outperforming S&P 500 (RS Leader)", value=False)
        s1 = st.checkbox("RSI >= 55", value=False)
        s4 = st.checkbox("20-Day High Breakout (Volume Confirmed)", value=False)
        s7 = st.checkbox("Pullback Near 20D/50D EMA", value=False)
        s_st2 = st.checkbox("Stage 2 Higher Low Only", value=False)
      with f_col3:
        tct1 = st.checkbox("Action = BUY / SWING BUY", value=False)
        tct2 = st.checkbox("TCT Bottom Box Only", value=False)
        tct4 = st.checkbox("Reward-to-Risk >= 2.0R", value=False)
        tct5 = st.checkbox("Liquidity >= $50M/day", value=False)
        s_rev150 = st.checkbox("150-MA Reversal Radar", value=False)
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
        c1, c2, c3, c4 = st.columns([3.4, 2.7, 1.7, 1.1])
        sign_m = "+" if m["Change"] >= 0 else "-"
        with c1:
          st.markdown(
            f'<div><a href="?inspect={m["Ticker"]}" target="_self" class="ticker-link">{m["Ticker"]}</a> '
            f'<span class="badge {m["TCT_Badge"]}">{m["TCT_Short_Sig"]}</span> '
            f'<span class="badge badge-rs-lag">Fund {m.get("Fund_Score", 70)} | Comp {m["Score"]}</span></div>'
            f'<div class="num" style="font-size:0.82rem;color:#52525b;margin-top:2px;">'
            f'${m["Price"]:,.2f} (<span style="color:{"#15803d" if m["Change"] >= 0 else "#b91c1c"};font-weight:700;">'
            f'{sign_m}${abs(m["Change"]):.2f} / {m["Change_Pct"]:+.2f}%</span>) | {m["TCT_Model"]}</div>'
            f'<div style="font-size:0.75rem;color:#475569;margin-top:2px;">{m["TCT_Explain"]}</div>',
            unsafe_allow_html=True
          )
        with c2:
          st.markdown(
            f'<div class="num" style="font-size:0.78rem;line-height:1.45;">'
            f'<b>Trigger:</b> ${m["BOS_Level"]:,.2f}<br>'
            f'<b>Target:</b> <span style="color:#15803d;font-weight:700;">${m["Target_Price"]:,.2f} (+{m["Target_Pct"]:.1f}%)</span><br>'
            f'<b>Stop:</b> <span style="color:#b91c1c;font-weight:700;">${m["Stop_Price"]:,.2f} ({m["Stop_Pct"]:.1f}%)</span> | <b>{m["R_Multiple"]:.1f}R</b> | {m["Shares_05Pct"]} shs</div>',
            unsafe_allow_html=True
          )
        with c3:
          st.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
        with c4:
          if st.button("Add", use_container_width=True, key=f"add_sc_{m['Ticker']}"):
            if m["Ticker"] not in watchlists[target_add_folder]:
              watchlists[target_add_folder].append(m["Ticker"])
              sync_file_to_github(watchlists, DATA_FILE)
              st.success("Synced.")
          if st.button("+ Options", use_container_width=True, key=f"opt_sc_{m['Ticker']}"):
            if "Options Radar" not in watchlists:
              watchlists["Options Radar"] = []
            if m["Ticker"] not in watchlists["Options Radar"]:
              watchlists["Options Radar"].insert(0, m["Ticker"])
              sync_file_to_github(watchlists, DATA_FILE)
            st.toast(f"Added {m['Ticker']} to Options Radar")

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
            try:
              st.session_state[wl_in_key] = ""
            except Exception:
              pass
        c_in.text_input("Add symbol", placeholder=f"Add to {folder} (e.g. AVGO)", label_visibility="collapsed", key=wl_in_key, on_change=_commit_wl_add)
        c_btn.button("+ Add", use_container_width=True, key=f"wl_add_btn_{folder}", on_click=_commit_wl_add)
      with col_sort:
        sort_by = st.selectbox(
          "Sort By",
          [
            "Saved Order (My Custom Sequence)",
            "Action Signal (Buy Now First)",
            "Relative Strength vs S&P 500",
            "Composite Score (High -> Low)",
            "Fundamental Score (High -> Low)",
            "Reward-to-Risk Ratio (High -> Low)",
            "Day % Change (High -> Low)",
            "Alphabetical (A -> Z)"
          ],
          index=0, label_visibility="collapsed"
        )
      with col_ed:
        show_reorder = st.checkbox("Edit / Reorder", value=False)
      if show_reorder:
        render_watchlist_reorder_panel(folder, key_prefix="wl_ed")

      wf1, wf2, wf3, wf4, wf5, wf6, wf7, wf8 = st.columns(8)
      for btn_c, lbl, code in [
        (wf1, "Stage 2 HL", "STAGE2_HL"), (wf2, "150MA Radar", "REV150"),
        (wf3, "Momentum", "MOMENTUM"), (wf4, "Buy Triggers", "BUY"),
        (wf5, "TCT Bottoms", "TCT"), (wf6, "Swings", "SWING"),
        (wf7, "<150MA Cut", "CUT150"), (wf8, "Show All", "ALL")
      ]:
        if btn_c.button(lbl, use_container_width=True, type="primary" if st.session_state.wl_preset_filter == code else "secondary"):
          st.session_state.wl_preset_filter = code; persist_ui_state(); st.rerun()

      pills_html = "".join([f'<a href="?inspect={s}" target="_self" class="pill">{i + 1}. {s}</a>' for i, s in enumerate(symbols)])
      st.markdown(f"<div style='margin:6px 0;'>{pills_html}</div>", unsafe_allow_html=True)

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
      elif sort_by == "Composite Score (High -> Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["Score"], reverse=True)
      elif sort_by == "Fundamental Score (High -> Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s].get("Fund_Score", 70), reverse=True)
      elif sort_by == "Reward-to-Risk Ratio (High -> Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["R_Multiple"], reverse=True)
      elif sort_by == "Day % Change (High -> Low)":
        display_symbols = sorted(display_symbols, key=lambda s: data_dict[s]["Change_Pct"], reverse=True)
      elif sort_by == "Alphabetical (A -> Z)":
        display_symbols = sorted(display_symbols)

      if not display_symbols:
        st.info("No stocks matched that filter in this folder. Tap Show All above to reset.")

      # Tight Style A 2-Column Editorial Cards (~35% tighter vertical height)
      left_c, right_c = st.columns(2)
      for idx, sym in enumerate(display_symbols):
        d = data_dict[sym]
        sign_w = "+" if d["Change"] >= 0 else "-"
        rs_html = (
          f'<span class="badge badge-rs-lead" style="margin-left:4px;">RS {d["RS_Diff"]:+.1f}%</span>'
          if d["RS_Leader"]
          else f'<span class="badge badge-rs-lag" style="margin-left:4px;">RS {d["RS_Diff"]:+.1f}%</span>'
        )
        earn_html = ""
        if sym in earnings_map:
          days_left, dt_s = earnings_map[sym]
          if days_left <= 14:
            earn_html = f'<span class="badge badge-earn-warn" style="margin-left:4px;">EARN {days_left}d ({dt_s})</span>'
        chg_clr = "#15803d" if d["Change"] >= 0 else "#b91c1c"
        with (left_c if idx % 2 == 0 else right_c):
          st.markdown(
            f'<div class="stock-card">'
            f'<div style="display:flex;justify-content:space-between;align-items:center;">'
            f'<div><a href="?inspect={d["Ticker"]}" target="_self" class="ticker-link">{d["Ticker"]}</a> '
            f'<span class="badge {d["TCT_Badge"]}" style="margin-left:4px;">{d["TCT_Short_Sig"]}</span>'
            f'{rs_html}{earn_html}</div>'
            f'<div class="num" style="text-align:right;">'
            f'<span style="font-size:1.10rem;font-weight:800;">${d["Price"]:,.2f}</span> '
            f'<span style="font-size:0.78rem;color:{chg_clr};font-weight:700;">{sign_w}${abs(d["Change"]):.2f} ({d["Change_Pct"]:+.2f}%)</span> '
            f'<span style="font-size:0.86rem;font-weight:800;color:#c5a059;margin-left:6px;">SC {d["Score"]}</span>'
            f'</div></div>'
            f'<div class="trade-ticket">'
            f'<div style="display:flex;justify-content:space-between;color:#0f291e;font-weight:700;margin-bottom:2px;">'
            f'<span>{d["TCT_Model"]}</span><span>R/R {d["R_Multiple"]:.1f}R | Fund {d.get("Fund_Score", 70)}/100</span></div>'
            f'<div style="display:flex;justify-content:space-between;">'
            f'<span><b>Trig:</b> ${d["BOS_Level"]:,.2f}</span>'
            f'<span><b>Tgt:</b> <span style="color:#15803d;font-weight:700;">${d["Target_Price"]:,.2f}</span> (+{d["Target_Pct"]:.1f}%)</span>'
            f'<span><b>Stp:</b> <span style="color:#b91c1c;font-weight:700;">${d["Stop_Price"]:,.2f}</span> ({d["Stop_Pct"]:.1f}%)</span>'
            f'<span><b>Size:</b> {d["Shares_05Pct"]} shs</span></div></div>'
            f'<div class="num" style="display:flex;justify-content:space-between;margin-top:5px;font-size:0.71rem;color:#52525b;">'
            f'<span>H/L ${d["Day_High"]:,.2f}/${d["Day_Low"]:,.2f}</span>'
            f'<span>RSI {d["RSI"]:.0f}/{d["RSI2"]:.0f}</span>'
            f'<span>RV30 {d.get("RV30_Pct", 38):.0f}%</span>'
            f'<span>EMA50 ${d["EMA50_Val"]:,.2f}</span></div></div>',
            unsafe_allow_html=True
          )

  elif navigation == "Precious Metals, Crypto & Currency":
    st.markdown("<h1>Precious Metals, Crypto & Currency</h1>", unsafe_allow_html=True)
    METALS_GROUP = {
      "Gold Futures (USD/oz)": "GC=F", "Silver Futures (USD/oz)": "SI=F",
      "Copper Futures (USD/lb)": "HG=F", "Platinum Futures (USD/oz)": "PL=F",
      "SPDR Gold Trust (GLD)": "GLD", "iShares Silver Trust (SLV)": "SLV"
    }
    CRYPTO_GROUP = {
      "Bitcoin (BTC/USD)": "BTC-USD", "Ethereum (ETH/USD)": "ETH-USD",
      "XRP (XRP/USD)": "XRP-USD", "Solana (SOL/USD)": "SOL-USD"
    }
    FX_GROUP = {
      "US Dollar Index (DXY)": "DX-Y.NYB", "USD / JPY": "JPY=X", "EUR / USD": "EURUSD=X"
    }
    all_mcf_syms = list(METALS_GROUP.values()) + list(CRYPTO_GROUP.values()) + list(FX_GROUP.values())
    mcf_data = fetch_batch_market_data(all_mcf_syms, account_size=settings["account_size"])

    def render_asset_group(group_dict):
      c1, c2 = st.columns(2)
      for idx, (title, sym) in enumerate(group_dict.items()):
        if sym in mcf_data:
          m = mcf_data[sym]
          decimals = 4 if sym in ("EURUSD=X", "XRP-USD", "HG=F") else 2
          sign_m = "+" if m["Change"] >= 0 else "-"
          with (c1 if idx % 2 == 0 else c2):
            st.markdown(
              f'<div class="stock-card"><div style="display:flex;justify-content:space-between;align-items:center;">'
              f'<div style="font-size:0.72rem;color:#64748b;text-transform:uppercase;font-weight:700;">{title}</div>'
              f'<span class="badge {m["TCT_Badge"]}">{m["TCT_Short_Sig"]}</span></div>'
              f'<div class="num" style="display:flex;justify-content:space-between;align-items:baseline;margin-top:4px;">'
              f'<div><a href="?inspect={sym}" target="_self" class="ticker-link">{sym}</a>'
              f'<span style="font-size:1.22rem;font-weight:800;color:#0f291e;margin-left:8px;">${m["Price"]:,.{decimals}f}</span>'
              f'<span style="font-size:0.84rem;color:{"#15803d" if m["Change"] >= 0 else "#b91c1c"};font-weight:700;margin-left:5px;">'
              f'{sign_m}${abs(m["Change"]):.{decimals}f} ({m["Change_Pct"]:+.2f}%)</span></div>'
              f'<span class="badge {m["Badge"]}">{m["State"]}</span></div>'
              f'<div class="trade-ticket"><div style="display:flex;justify-content:space-between;">'
              f'<span><b>Trig:</b> ${m["BOS_Level"]:,.{decimals}f}</span>'
              f'<span><b>Tgt:</b> <b style="color:#15803d;">${m["Target_Price"]:,.{decimals}f}</b> (+{m["Target_Pct"]:.1f}%)</span>'
              f'<span><b>Stp:</b> <b style="color:#b91c1c;">${m["Stop_Price"]:,.{decimals}f}</b> ({m["Stop_Pct"]:.1f}%)</span>'
              f'<span><b>{m["R_Multiple"]:.1f}R</b></span></div></div></div>',
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
      n_tab1, n_tab2 = st.tabs([f"Watchlist News ({len(tracked_symbols)})", "Metals, Crypto & USD News"])
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
          [{"Ticker": s, "Earnings Date": dt_str, "Countdown": f"{days_left}d", "_sort": days_left} for s, (days_left, dt_str) in earnings_map.items()],
          key=lambda x: x["_sort"]
        )
        st.dataframe(pd.DataFrame([{"Ticker": r["Ticker"], "Earnings Date": r["Earnings Date"], "Countdown": r["Countdown"]} for r in rows]), use_container_width=True, hide_index=True)
      else:
        st.info("No confirmed upcoming earnings within the next 60 days.")

  elif navigation == "Settings":
    st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
    s_col1, s_col2 = st.columns(2)
    with s_col1:
      st.subheader("1. Account Risk & Composite Score Weights")
      acc_val = st.number_input("Total Trading Account Size ($ USD) — For 0.5% Risk Share Sizing", min_value=1000, max_value=50000000, value=int(settings.get("account_size", 100000)), step=5000)
      news_lim = st.slider("Max News Headlines in Scrollable Feed", 20, 100, int(settings.get("news_limit", 60)), 10)
      max_age_h = st.slider("Strict News Age Cutoff (Hours)", 24, 120, int(settings.get("max_news_age_hours", 72)), 12)
      w_f = st.slider("Real Fundamentals Weight (%)", 0, 100, int(settings.get("w_fund", 40)))
      w_t = st.slider("Technical Trend Weight (%)", 0, 100, int(settings.get("w_tech", 40)))
      w_m = st.slider("Momentum & Breakout Weight (%)", 0, 100, int(settings.get("w_mom", 20)))
      if st.button("Save Account & Scoring Settings", type="primary", use_container_width=True):
        settings.update({"account_size": acc_val, "news_limit": news_lim, "max_news_age_hours": max_age_h, "w_fund": w_f, "w_tech": w_t, "w_mom": w_m})
        ok_s, msg_s = sync_file_to_github(settings, SETTINGS_FILE)
        st.cache_data.clear()
        st.success(f"Settings saved ({msg_s})")

    with s_col2:
      st.subheader("2. Notification Channel Setup (ntfy / Telegram)")
      ch_options = ["ntfy Push", "Telegram Bot", "Both ntfy & Telegram", "Disabled (In-App Toast Only)"]
      curr_ch = settings.get("notif_channel", "ntfy Push")
      sel_ch = st.selectbox("Active Notification Channel", ch_options, index=ch_options.index(curr_ch) if curr_ch in ch_options else 0)
      ntfy_val = st.text_input("ntfy Topic Name", value=str(settings.get("ntfy_topic", DEFAULT_NTFY_TOPIC)), placeholder="e.g. 2026_USstockspicks")
      tg_c1, tg_c2 = st.columns(2)
      tg_tok_val = tg_c1.text_input("Telegram Bot Token (Optional)", value=str(settings.get("tg_bot_token", "")), type="password")
      tg_chat_val = tg_c2.text_input("Telegram Chat ID (Optional)", value=str(settings.get("tg_chat_id", "")))

      btn_n1, btn_n2 = st.columns(2)
      if btn_n1.button("Save Notification Channel", type="primary", use_container_width=True):
        settings.update({"notif_channel": sel_ch, "ntfy_topic": ntfy_val.strip(), "tg_bot_token": tg_tok_val.strip(), "tg_chat_id": tg_chat_val.strip()})
        ok_n, msg_n = sync_file_to_github(settings, SETTINGS_FILE)
        st.success(f"Notification channel saved ({msg_n})")

      current_data = fetch_batch_market_data(get_all_monitored_tickers(), account_size=settings["account_size"])
      if btn_n2.button("Send Live 8-Playbook Briefing Now", use_container_width=True):
        settings.update({"notif_channel": sel_ch, "ntfy_topic": ntfy_val.strip(), "tg_bot_token": tg_tok_val.strip(), "tg_chat_id": tg_chat_val.strip()})
        st2_hl = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v.get("Is_Stage2_Higher_Low")]
        rev_150 = [f"{k} (${v['Price']:.2f} > 150MA ${v.get('SMA150_Val', v['Price']):.2f})" for k, v in current_data.items() if v.get("Is_150MA_Reversal_Radar")]
        buys = [f"{k} ({v['TCT_Short_Sig']} @ ${v['Price']:.2f} -> Tgt ${v['Target_Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 0]
        tct_boxes = [f"{k} (BOS ${v['BOS_Level']:.2f})" for k, v in current_data.items() if v["TCT_Valid_Range"] and v["TCT_Priority"] != 0]
        sells = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 4]
        summary_msg = (
          f"STAGE 2 HIGHER LOW ({len(st2_hl)}): {', '.join(st2_hl[:6]) if st2_hl else 'None'}\n"
          f"150-MA REVERSAL RADAR ({len(rev_150)}): {', '.join(rev_150[:6]) if rev_150 else 'None'}\n"
          f"ALL BUY TRIGGERS ({len(buys)}): {', '.join(buys[:6]) if buys else 'None'}\n"
          f"TCT BOTTOM BOX ({len(tct_boxes)}): {', '.join(tct_boxes[:6]) if tct_boxes else 'None'}\n"
          f"BELOW 150/50 MA ({len(sells)}): {', '.join(sells[:8]) if sells else 'None'}"
        )
        ok, status_msg = send_ntfy_alert(summary_msg, "Daily Portfolio Briefing")
        st.success(f"Sent: {status_msg}") if ok else st.error(f"Failed: {status_msg}")

      st.markdown("---")
      if current_data:
        df_export = pd.DataFrame([{
          "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "Ticker": sym_name,
          "Price": d["Price"], "Change_Pct": d["Change_Pct"],
          "Fund_Score": d.get("Fund_Score", 70), "Composite_Score": d["Score"],
          "Playbook": d["TCT_Model"], "Action": d["TCT_Action"],
          "Buy_Trigger": d["BOS_Level"], "Target": d["Target_Price"], "Stop_Loss": d["Stop_Price"],
          "RR": round(d["R_Multiple"], 2), "RV30_Pct": d.get("RV30_Pct", 38)
        } for sym_name, d in current_data.items()])
        st.download_button(
          "Download Full 8-Playbook Plan CSV",
          df_export.to_csv(index=False).encode("utf-8"),
          f"tct_swing_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
          "text/csv", type="primary", use_container_width=True
        )

    st.markdown("---")
    st.subheader("3. Composite Score, Real Fundamentals & 8-Playbook Reference")
    with st.expander("Composite Score (0-100) — Real Fundamental + Technical + Momentum Formula", expanded=False):
      st.markdown(
        f"**Master Formula:** `int(Fund_Score * {settings['w_fund']}% + Tech_Score * {settings['w_tech']}% + Mom_Score * {settings['w_mom']}%)`\n\n"
        "- **1. Real Fundamental Score (15-100 pts, 4h cached):**\n"
        "  - **Valuation vs. Growth (0-35 pts):** Forward P/E relative to earnings/revenue growth (PEG proxy).\n"
        "  - **Profitability (0-35 pts):** Average score of Return on Equity (ROE) and Operating Margins.\n"
        "  - **Balance Sheet Strength (0-30 pts):** Debt-to-Equity ratio (<40 scores 30 pts; >250 scores 4 pts, penalizing highly leveraged balance sheets).\n"
        "  - Non-corporate assets (ETFs, futures, crypto, FX) receive a neutral 75/100 baseline.\n"
        "- **2. Technical Trend Sub-Score (0-100 pts):** Close > 50-EMA (+30), RSI(14) 45-70 (+40), Paced RVOL >= 1.2x (+30).\n"
        "- **3. Momentum Sub-Score (0-100 pts):** 20D High Breakout (+50), Within 10% of 52W High (+50)."
      )
