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
from datetime import datetime

# --- PAGE SETUP ---
st.set_page_config(
    page_title="Quality Momentum Cockpit",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- INITIALIZE SESSION STATE ---
if "inspect_symbol" not in st.session_state:
    st.session_state.inspect_symbol = None
if "screener_matches" not in st.session_state:
    st.session_state.screener_matches = None

def clear_inspection():
    st.session_state.inspect_symbol = None

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
</style>
""", unsafe_allow_html=True)

# --- FILE PERSISTENCE ---
DATA_FILE = "watchlists.json"
SETTINGS_FILE = "settings.json"

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception: pass
    return default

def save_json(filepath, data):
    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

watchlists = load_json(DATA_FILE, {
    "Active Portfolio": ["NVDA", "CRDO", "SLV"],
    "Opportunity Radar": ["PLTR", "MU", "HOOD", "LRCX", "UGL", "SOFI", "MRVL", "AVGO", "COST"]
})

settings = load_json(SETTINGS_FILE, {
    "w_fund": 40, "w_tech": 40, "w_mom": 20,
    "alert_breakout": True, "alert_support": True, "alert_earnings": True,
    "email": "cashmiles@gmail.com"
})

# --- UNIVERSE DEFINITION ---
GICS_SECTORS = {
    "Information Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ADBE", "CRM", "AMD", "INTC", "CSCO", "QCOM", "TXN", "AMAT", "LRCX", "MU", "PANW", "CRWD", "CRDO"],
    "Communication Services": ["GOOGL", "META", "NFLX", "TMUS", "CMCSA", "DIS", "CHTR"],
    "Consumer Discretionary": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "BKNG", "LULU", "EBAY"],
    "Consumer Staples": ["WMT", "COST", "PG", "KO", "PEP", "PM", "MDLZ", "KDP"],
    "Health Care": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "TMO", "AMGN", "GILD", "ISRG", "VRTX"],
    "Financials": ["JPM", "V", "MA", "BAC", "WFC", "MS", "GS", "AXP", "BLK", "HOOD", "SOFI"],
    "Industrials": ["GE", "CAT", "UNP", "HON", "BA", "RTX", "DE", "LMT", "ADP", "FAST"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "EOG", "BKR"],
    "Materials": ["LIN", "SHW", "FCX", "NEM", "APD", "ECL"],
    "Utilities": ["NEE", "SO", "DUK", "CEG", "AEP", "EXC"],
    "Real Estate": ["PLD", "AMT", "EQIX", "PSA", "O"]
}

# --- GOOGLE NEWS RSS FETCHER ---
@st.cache_data(ttl=600)
def fetch_google_news_rss(query, max_items=5):
    encoded_query = urllib.parse.quote(query)
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    articles = []
    try:
        with urllib.request.urlopen(req, timeout=6) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        for item in root.findall(".//item")[:max_items]:
            raw_title = item.find("title").text if item.find("title") is not None else "Financial Update"
            link = item.find("link").text if item.find("link") is not None else "#"
            pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
            source = item.find("source").text if item.find("source") is not None else "News"
            
            # Format clean title and publisher
            clean_title = raw_title.rsplit(" - ", 1)[0] if " - " in raw_title else raw_title
            clean_date = pub_date[:16] if len(pub_date) >= 16 else pub_date
            
            articles.append({
                "title": clean_title,
                "link": link,
                "publisher": source,
                "date": clean_date
            })
    except Exception:
        pass
    return articles

# --- DATA ENGINE 1: BATCH INGESTION (MULTI-TICKER SCREENER & WATCHLIST) ---
@st.cache_data(ttl=900)
def fetch_batch_market_data(tickers):
    if not tickers: return {}
    results = {}
    try:
        data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False)
    except Exception: return {}

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
            if len(df) < 40: continue

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

            results[t] = {
                "Ticker": t, "Price": close, "Change": change, "Change_Pct": change_pct,
                "RSI": rsi, "RVOL": rvol, "ADX": adx, "MACD_Above_Zero": macd_above_zero,
                "MACD_Cross": macd_cross, "Stoch_Bullish": stoch_bullish, "OBV_Rising": obv_rising,
                "Above_EMA50": above_ema50, "Above_EMA200": above_ema200, "Is_Breakout": is_breakout,
                "BB_Upper_Break": bb_upper_break, "BB_Lower_Touch": bb_lower_touch,
                "Pullback_EMA50": pullback_ema50, "Within_52W": within_52w,
                "State": state, "Badge": badge_class, "Reason": reason, "Score": composite,
                "Sparkline": df["Close"].iloc[-15:].tolist(), "History": df
            }
        except Exception: continue
    return results

# --- DATA ENGINE 2: ISOLATED SINGLE-TICKER ENGINE (FOR INSPECT VIEW) ---
@st.cache_data(ttl=300)
def fetch_single_ticker_data(sym):
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

        return {
            "Ticker": sym, "Price": close, "Change": change, "Change_Pct": change_pct,
            "RSI": rsi, "RVOL": rvol, "State": state, "Badge": badge_class,
            "Reason": reason, "Score": composite, "History": df
        }
    except Exception:
        return None

@st.cache_data(ttl=3600)
def fetch_ticker_fundamentals(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        info = t.info
        return {
            "Market Cap": info.get("marketCap", "N/A"), "Trailing P/E": info.get("trailingPE", "N/A"),
            "Forward P/E": info.get("forwardPE", "N/A"), "EPS (TTM)": info.get("trailingEps", "N/A"),
            "Target Price": info.get("targetMeanPrice", "N/A"), "52W High": info.get("fiftyTwoWeekHigh", "N/A"),
            "52W Low": info.get("fiftyTwoWeekLow", "N/A"), "Debt/Equity": info.get("debtToEquity", "N/A"),
            "Business Summary": info.get("longBusinessSummary", "No corporate overview provided.")
        }
    except Exception: return {}

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
    except Exception: return {}


# ==============================================================================
# 1. PRIMARY SIDEBAR NAVIGATION (ALWAYS RENDERS FIRST)
# ==============================================================================
st.sidebar.markdown(
    """
    <div style="padding: 10px 0 20px 0;">
        <span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span>
        <span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">MARKET OPEN · 15M DELAY</span>
        <h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2>
        <span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Quality Momentum</span>
    </div>
    """, unsafe_allow_html=True
)

navigation = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Screener", "Watchlist", "Precious Metals", "News & Earnings", "Settings"],
    label_visibility="collapsed",
    on_change=clear_inspection
)

st.sidebar.markdown("---")
st.sidebar.markdown(
    """<div style="position: fixed; bottom: 20px; font-size: 0.75rem; color: #71717a;">Quality Momentum v5.0<br>Provider: Yahoo Finance / Google RSS</div>""", 
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
# 3. CONTENT ROUTING: DETAIL VIEW vs. TAB VIEWS
# ==============================================================================
if st.session_state.inspect_symbol is not None:
    # --------------------------------------------------------------------------
    # ISOLATED DETAIL DOSSIER VIEW
    # --------------------------------------------------------------------------
    sym = st.session_state.inspect_symbol
    col_back, col_title = st.columns([1, 6])
    with col_back:
        if st.button("⬅ Back", type="primary"):
            st.session_state.inspect_symbol = None
            st.rerun()

    with col_title:
        st.markdown(f"<h1>{sym} · Technical & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym)
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]

        f1, f2, f3, f4, f5, f6 = st.columns(6)
        mcap = f"${funds.get('Market Cap', 0)/1e9:.1f}B" if isinstance(funds.get('Market Cap'), (int, float)) else "N/A"
        f1.metric("Price", f"${d['Price']:.2f}", f"{'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%")
        f2.metric("Market Cap", mcap)
        f3.metric("Trailing P/E", f"{funds.get('Trailing P/E', 'N/A')}")
        f4.metric("EPS (TTM)", f"${funds.get('EPS (TTM)', 'N/A')}")
        f5.metric("Analyst Target", f"${funds.get('Target Price', 'N/A')}")
        f6.metric("52W Range", f"${funds.get('52W Low', 0):.0f} - ${funds.get('52W High', 0):.0f}" if isinstance(funds.get('52W Low'), (int, float)) else "N/A")

        st.markdown("---")

        c_ctrl, c_plot = st.columns([1, 4])
        with c_ctrl:
            st.markdown("### Chart Overlays")
            show_ema20 = st.checkbox("EMA 20 (Gold)", value=True)
            show_ema50 = st.checkbox("EMA 50 (Green)", value=True)
            show_ema200 = st.checkbox("EMA 200 (Purple)", value=False)
            show_bb = st.checkbox("Bollinger Bands (20, 2)", value=True)

            st.markdown("---")
            st.markdown("### Signal Summary")
            st.markdown(f"**State:** `{d['State']}`")
            st.markdown(f"**Score:** `{d['Score']}/100`")
            st.markdown(f"**RSI (14):** `{d['RSI']:.1f}`")
            st.markdown(f"**RVOL:** `{d['RVOL']:.1f}x`")
            st.markdown(f"**Reason:** *{d['Reason']}*")

        with c_plot:
            fig = make_subplots(rows=3, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.6, 0.2, 0.2])
            fig.add_trace(go.Candlestick(x=df_hist.index, open=df_hist['Open'], high=df_hist['High'], low=df_hist['Low'], close=df_hist['Close'], name="Candles"), row=1, col=1)

            if show_ema20: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA20'], line=dict(color="#d4af37", width=1.5), name="EMA 20"), row=1, col=1)
            if show_ema50: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA50'], line=dict(color="#15803d", width=1.5), name="EMA 50"), row=1, col=1)
            if show_ema200: fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['EMA200'], line=dict(color="#7c3aed", width=1.5), name="EMA 200"), row=1, col=1)
            if show_bb:
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Upper'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Upper"), row=1, col=1)
                fig.add_trace(go.Scatter(x=df_hist.index, y=df_hist['BB_Lower'], line=dict(color="#94a3b8", width=1, dash="dot"), name="BB Lower"), row=1, col=1)

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
    # --------------------------------------------------------------------------
    # NORMAL TAB VIEWS
    # --------------------------------------------------------------------------
    if navigation == "Dashboard":
        st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Find the names holding their trend. A focused read on quality, momentum, and context.</p>", unsafe_allow_html=True)

        all_monitored = list(set(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))
        stock_records = fetch_batch_market_data(all_monitored)

        if stock_records:
            best_pick = max(stock_records.values(), key=lambda x: x["Score"])
            h_col1, h_col2 = st.columns([5, 1])
            with h_col1:
                st.markdown(
                    f"""
                    <div style="background-color: #0f291e; border-radius: 10px; padding: 22px 28px; color: #fbf9f4;">
                        <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.12em; color: #c5a059; font-weight: 700;">
                            TODAY'S STANDOUT SETUP
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                            <div>
                                <span style="font-size: 1.8rem; font-weight: 700; color: #ffffff;">{best_pick['Ticker']}</span>
                                <span style="font-size: 1.2rem; color: #e2e8f0; margin-left: 8px;">${best_pick['Price']:.2f}</span>
                                <span style="color: {'#4ade80' if best_pick['Change'] >= 0 else '#f87171'}; font-weight: 600; margin-left: 6px;">
                                    {'+' if best_pick['Change'] >= 0 else ''}{best_pick['Change_Pct']:.2f}%
                                </span>
                                <div style="color: #cbd5e1; font-size: 0.95rem; margin-top: 6px;">{best_pick['Reason']}</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 2.4rem; font-weight: 700; color: #c5a059; font-family: 'Newsreader', serif;">
                                    {best_pick['Score']}
                                </div>
                                <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase;">Composite Score</div>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True
                )
            with h_col2:
                st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)
                if st.button(f"🔍 Inspect {best_pick['Ticker']}", key="btn_hero_inspect"):
                    st.session_state.inspect_symbol = best_pick['Ticker']
                    st.rerun()

        st.markdown("<div style='margin-bottom: 20px;'></div>", unsafe_allow_html=True)

        col_left, col_right = st.columns([2, 1])
        with col_left:
            st.subheader("Major Market Stories (Google News)")
            market_news = fetch_google_news_rss("US stock market news", max_items=4)
            if market_news:
                for n in market_news:
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;">
                                <span style="font-weight: 600;">{n['publisher']}</span>
                                <span>{n['date']}</span>
                            </div>
                            <div style="font-weight: 600; font-size: 0.95rem; margin-top: 3px;">
                                <a href="{n['link']}" target="_blank" style="color: #0f291e; text-decoration: none;">{n['title']}</a>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
            else:
                st.info("Market headlines feed currently refreshing.")

        with col_right:
            st.subheader("Radar Snapshot")
            for s in watchlists["Opportunity Radar"][:5]:
                if s in stock_records:
                    r = stock_records[s]
                    c_card, c_btn = st.columns([3, 1])
                    with c_card:
                        st.markdown(
                            f"""
                            <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 8px 12px; margin-bottom: 8px; display: flex; justify-content: space-between;">
                                <div>
                                    <span style="font-weight: 700; color: #0f291e;">{r['Ticker']}</span>
                                    <div style="font-size: 0.75rem; color: #71717a;">Score {r['Score']}</div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-weight: 600;">${r['Price']:.2f}</div>
                                    <div style="font-size: 0.78rem; color: {'#15803d' if r['Change']>=0 else '#b91c1c'};">
                                        {'+' if r['Change']>=0 else ''}{r['Change_Pct']:.2f}%
                                    </div>
                                </div>
                            </div>
                            """, unsafe_allow_html=True
                        )
                    with c_btn:
                        if st.button("Inspect", key=f"insp_dash_{s}"):
                            st.session_state.inspect_symbol = s
                            st.rerun()

    elif navigation == "Screener":
        st.markdown("<h1>Find the Next Quality Leader</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>A calm, structured view of large-cap leaders with healthy fundamentals and measurable momentum.</p>", unsafe_allow_html=True)

        st.markdown(
            """
            <div style="background: white; border: 1px solid #e7e2d9; border-radius: 10px; padding: 18px 24px; margin-bottom: 24px;">
                <div style="font-size: 0.75rem; color: #71717a; text-transform: uppercase; font-weight: 700; letter-spacing: 0.08em; margin-bottom: 12px;">
                    FILTER BUILDER (DEFAULT: UNCHECKED)
                </div>
            """, unsafe_allow_html=True
        )

        f_col1, f_col2, f_col3 = st.columns([1.3, 1.6, 1.1])

        with f_col1:
            st.markdown("**1. GICS Sectors (Pick Any)**")
            selected_sectors = []
            for sec in list(GICS_SECTORS.keys()):
                if st.checkbox(sec, value=False, key=f"sec_{sec}"):
                    selected_sectors.append(sec)

        with f_col2:
            st.markdown("**2. Technical Signals (11 Filters)**")
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
            s11 = st.checkbox("ADX > 25 (Strong Trend)", value=False)
            s12 = st.checkbox("Stochastic Bullish (%K > %D)", value=False)
            s13 = st.checkbox("OBV Rising (Accumulation)", value=False)

        with f_col3:
            st.markdown("**3. Baseline Filters**")
            st.markdown(
                """
                <div style="font-size: 0.85rem; color: #52525b; line-height: 1.6;">
                    ✓ Large-Cap Liquid Universe<br>
                    ✓ Positive EPS Growth Baseline<br>
                    ✓ Low Debt-to-Equity Quality<br>
                    ✓ Positive Cash Flow Filter
                </div>
                </div>
                """, unsafe_allow_html=True
            )

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
                        screener_data = fetch_batch_market_data(scan_universe)
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
                            if s11 and d["ADX"] < 25: continue
                            if s12 and not d["Stoch_Bullish"]: continue
                            if s13 and not d["OBV_Rising"]: continue
                            matches.append(d)
                        st.session_state.screener_matches = sorted(matches, key=lambda x: x["Score"], reverse=True)

        with c_clear:
            if st.session_state.screener_matches is not None:
                if st.button("Clear Results"):
                    st.session_state.screener_matches = None
                    st.rerun()

        if st.session_state.screener_matches is not None:
            matches = st.session_state.screener_matches
            st.markdown(f"### Results: {len(matches)} Matches Found")
            for m in matches:
                c1, c2, c3, c4 = st.columns([3, 2, 2, 1.5])
                with c1:
                    st.markdown(
                        f"""
                        <div style="font-size: 1.15rem; font-weight: 700; color: #0f291e;">{m['Ticker']}</div>
                        <div style="font-size: 0.85rem; color: #71717a;">${m['Price']:.2f} · <span style="color: {'#15803d' if m['Change']>=0 else '#b91c1c'}; font-weight: 600;">{'+' if m['Change']>=0 else ''}{m['Change_Pct']:.2f}%</span></div>
                        <div style="font-size: 0.8rem; color: #475569; margin-top: 4px;">{m['Reason']}</div>
                        """, unsafe_allow_html=True
                    )
                with c2:
                    st.markdown(f"**Score:** `{m['Score']}/100`")
                    st.markdown(f"**RSI:** `{m['RSI']:.1f}` | **RVOL:** `{m['RVOL']:.1f}x`")
                with c3:
                    st.plotly_chart(render_sparkline(m["Sparkline"], m["Change"] >= 0), use_container_width=False)
                with c4:
                    if st.button("Inspect Chart", key=f"insp_sc_{m['Ticker']}"):
                        st.session_state.inspect_symbol = m['Ticker']
                        st.rerun()
                    if st.button("+ Add Radar", key=f"add_sc_{m['Ticker']}"):
                        if m["Ticker"] not in watchlists["Opportunity Radar"]:
                            watchlists["Opportunity Radar"].append(m["Ticker"])
                            save_json(DATA_FILE, watchlists)
                            st.success("Added!")

    elif navigation == "Watchlist":
        st.markdown("<h1>Watchlist</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Monitor your research universe with context, signals, and transparent scoring.</p>", unsafe_allow_html=True)

        folder = st.radio("Folder View", ["Opportunity Radar", "Active Portfolio"], horizontal=True)
        symbols = watchlists[folder]

        col_add, col_space = st.columns([2, 3])
        with col_add:
            c_in, c_btn = st.columns([3, 1])
            new_sym = c_in.text_input("Add symbol to folder", placeholder="e.g. AVGO", label_visibility="collapsed").upper().strip()
            if c_btn.button("+ Add") and new_sym:
                if new_sym not in symbols:
                    watchlists[folder].append(new_sym)
                    save_json(DATA_FILE, watchlists)
                    st.rerun()

        pills_html = "".join([f"<span class='pill'>{s}</span>" for s in symbols])
        st.markdown(f"<div style='margin-bottom: 16px;'>{pills_html}</div>", unsafe_allow_html=True)

        if st.checkbox("Manage / Remove Tickers"):
            del_sym = st.selectbox("Select symbol to remove", ["-- Select --"] + symbols)
            if st.button("Confirm Removal") and del_sym != "-- Select --":
                watchlists[folder].remove(del_sym)
                save_json(DATA_FILE, watchlists)
                st.rerun()

        st.markdown("---")

        data_dict = fetch_batch_market_data(symbols)
        left_c, right_c = st.columns(2)

        for idx, sym in enumerate(symbols):
            target_c = left_c if idx % 2 == 0 else right_c
            if sym in data_dict:
                d = data_dict[sym]
                with target_c:
                    st.markdown(
                        f"""
                        <div class="stock-card">
                            <div style="display: flex; justify-content: space-between; align-items: flex-start;">
                                <div>
                                    <span style="font-size: 1.25rem; font-weight: 700; color: #0f291e;">{d['Ticker']}</span>
                                    <span class="badge {d['Badge']}" style="margin-left: 8px;">{d['State']}</span>
                                    <div style="font-size: 1.35rem; font-weight: 700; margin-top: 4px;">
                                        ${d['Price']:.2f}
                                        <span style="font-size: 0.9rem; color: {'#15803d' if d['Change']>=0 else '#b91c1c'}; font-weight: 600;">
                                            {'+' if d['Change']>=0 else ''}{d['Change_Pct']:.2f}%
                                        </span>
                                    </div>
                                </div>
                                <div style="text-align: right;">
                                    <div style="font-size: 1.6rem; font-weight: 700; color: #c5a059; font-family: 'Newsreader', serif;">{d['Score']}</div>
                                    <div style="font-size: 0.7rem; color: #71717a; text-transform: uppercase;">Composite Score</div>
                                </div>
                            </div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 10px; font-size: 0.8rem; color: #52525b; border-top: 1px solid #f1ece4; padding-top: 8px;">
                                <div>RSI: <b>{d['RSI']:.1f}</b></div>
                                <div>RVOL: <b>{d['RVOL']:.1f}x</b></div>
                                <div>EMA 50: <b>${d['History']['EMA50'].iloc[-1]:.2f}</b></div>
                            </div>
                            <div style="font-size: 0.82rem; color: #475569; margin-top: 8px; font-style: italic;">
                                "{d['Reason']}"
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
                    if st.button(f"🔍 Inspect {sym} Detail Chart", key=f"insp_wl_{sym}"):
                        st.session_state.inspect_symbol = sym
                        st.rerun()

    elif navigation == "Precious Metals":
        st.markdown("<h1>Precious Metals & Commodities</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Real-time Spot Gold, Spot Silver, and core commodity mining proxies.</p>", unsafe_allow_html=True)

        METALS_UNIVERSE = {
            "Spot Gold (USD/oz)": "XAUUSD=X", "Spot Silver (USD/oz)": "XAGUSD=X",
            "Platinum Futures": "PL=F", "Gold ETF (GLD)": "GLD",
            "Silver ETF (SLV)": "SLV", "ProShares Ultra Gold 2x (UGL)": "UGL"
        }

        metals_data = fetch_batch_market_data(list(METALS_UNIVERSE.values()))

        m_col1, m_col2 = st.columns(2)
        for idx, (title, sym) in enumerate(METALS_UNIVERSE.items()):
            col = m_col1 if idx % 2 == 0 else m_col2
            if sym in metals_data:
                m = metals_data[sym]
                with col:
                    st.markdown(
                        f"""
                        <div class="stock-card">
                            <div style="font-size: 0.75rem; color: #71717a; text-transform: uppercase; font-weight: 600;">{title}</div>
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 4px;">
                                <div style="font-size: 1.5rem; font-weight: 700; color: #0f291e;">
                                    ${m['Price']:,.2f}
                                    <span style="font-size: 0.95rem; color: {'#15803d' if m['Change']>=0 else '#b91c1c'}; font-weight: 600;">
                                        {'+' if m['Change']>=0 else ''}{m['Change_Pct']:.2f}%
                                    </span>
                                </div>
                                <span class="badge {m['Badge']}">{m['State']}</span>
                            </div>
                            <div style="margin-top: 10px; font-size: 0.82rem; color: #52525b;">
                                RSI: <b>{m['RSI']:.1f}</b> · EMA 50: <b>${m['History']['EMA50'].iloc[-1]:,.2f}</b>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
                    if st.button(f"Inspect {title}", key=f"btn_metal_{sym}"):
                        st.session_state.inspect_symbol = sym
                        st.rerun()

    elif navigation == "News & Earnings":
        st.markdown("<h1>News & Catalyst Monitor</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Automated Google News RSS stream and earnings calendar for your pinned positions.</p>", unsafe_allow_html=True)

        n_col1, n_col2 = st.columns([2, 1])

        with n_col1:
            st.subheader("Watchlist News Feed (Google RSS)")
            tracked_symbols = watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]
            
            # Combine queries into targeted groups
            queries = [f"{s} stock" for s in tracked_symbols[:6]]
            found_any = False
            for q in queries:
                articles = fetch_google_news_rss(q, max_items=2)
                for a in articles:
                    found_any = True
                    st.markdown(
                        f"""
                        <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 10px;">
                            <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;">
                                <span style="font-weight: 700; color: #0f291e;">{q.replace(' stock', '')}</span>
                                <span>{a['publisher']} · {a['date']}</span>
                            </div>
                            <div style="font-weight: 600; font-size: 0.95rem; margin-top: 4px;">
                                <a href="{a['link']}" target="_blank" style="color: #0f291e; text-decoration: none;">{a['title']}</a>
                            </div>
                        </div>
                        """, unsafe_allow_html=True
                    )
            if not found_any:
                st.info("Watchlist news feed refreshing.")

        with n_col2:
            st.subheader("Upcoming Earnings Calendar")
            earnings_rows = []
            for s in tracked_symbols:
                try:
                    cal = yf.Ticker(s).calendar
                    if isinstance(cal, dict) and "Earnings Date" in cal:
                        dates = cal["Earnings Date"]
                        dt_str = str(dates[0]) if isinstance(dates, list) and dates else str(dates)
                        earnings_rows.append({"Ticker": s, "Earnings Date": dt_str})
                except Exception: continue

            if earnings_rows:
                st.table(pd.DataFrame(earnings_rows))
            else:
                st.info("No immediate earnings announcements confirmed in the next 14 days.")

    elif navigation == "Settings":
        st.markdown("<h1>Settings & Strategy Calibration</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Calibrate scoring weights, configure notifications, and export signal history.</p>", unsafe_allow_html=True)

        s_col1, s_col2 = st.columns(2)

        with s_col1:
            st.subheader("Score Weighting Defaults")
            w_f = st.slider("Fundamentals Weight", 0, 100, settings["w_fund"])
            w_t = st.slider("Technical Trend Weight", 0, 100, settings["w_tech"])
            w_m = st.slider("Momentum Weight", 0, 100, settings["w_mom"])

            if st.button("Save Weight Configuration"):
                settings["w_fund"] = w_f
                settings["w_tech"] = w_t
                settings["w_mom"] = w_m
                save_json(SETTINGS_FILE, settings)
                st.success("Weights saved.")

            st.markdown("---")
            st.subheader("Email Digest Settings")
            st.text_input("Destination Email", value=settings["email"])
            st.checkbox("Alert on Confirmed Breakouts", value=settings["alert_breakout"])
            st.checkbox("Alert on EMA 50 Support Breaks", value=settings["alert_support"])
            st.checkbox("Alert on Upcoming Earnings", value=settings["alert_earnings"])

        with s_col2:
            st.subheader("Export Strategy Review CSV")
            all_syms = list(set(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))
            current_data = fetch_batch_market_data(all_syms)

            if current_data:
                export_rows = []
                for sym_name, d in current_data.items():
                    export_rows.append({
                        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Ticker": sym_name, "Price": d["Price"], "Change_Pct": d["Change_Pct"],
                        "Composite_Score": d["Score"], "Signal_State": d["State"],
                        "RSI_14": d["RSI"], "RVOL": d["RVOL"], "Reason": d["Reason"]
                    })
                df_export = pd.DataFrame(export_rows)

                st.download_button(
                    label="📥 Download Strategy Snapshot CSV",
                    data=df_export.to_csv(index=False).encode("utf-8"),
                    file_name=f"momentum_review_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    mime="text/csv", type="primary"
                )