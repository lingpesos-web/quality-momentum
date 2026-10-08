import json
import os
import urllib.request
import yfinance as yf
import pandas as pd
import numpy as np

# Load Data
def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception: pass
    return default

watchlists = load_json("watchlists.json", {
    "Active Portfolio": ["NVDA", "CRDO", "SLV"],
    "Opportunity Radar": ["PLTR", "MU", "HOOD", "LRCX", "UGL", "SOFI", "MRVL", "AVGO", "COST"]
})
settings = load_json("settings.json", {"alert_breakout": True, "alert_support": True})

def send_ntfy_alert(message, title):
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/2026_USstockspicks",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"}
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

# Scan Universe
tickers = list(set(watchlists["Active Portfolio"] + watchlists["Opportunity Radar"]))
if not tickers:
    exit()

data = yf.download(tickers, period="6mo", interval="1d", group_by="ticker", progress=False)
alerts_triggered = 0

for t in tickers:
    try:
        df = data[t].copy() if len(tickers) > 1 else data.copy()
        df.dropna(inplace=True)
        if len(df) < 40: continue

        close = float(df["Close"].iloc[-1])
        ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
        vol20 = float(df["Volume"].rolling(20).mean().iloc[-1])
        rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
        high20_prev = float(df["High"].rolling(20).max().iloc[-2])

        is_breakout = (close >= high20_prev) and (rvol >= 1.4)
        above_ema50 = close > ema50

        if is_breakout and above_ema50 and settings.get("alert_breakout", True):
            send_ntfy_alert(f"{t} confirmed a breakout above its 20-day high (${high20_prev:.2f}) with {rvol:.1f}x volume.", f"🚀 {t} Breakout!")
            alerts_triggered += 1
        elif close < ema50 and settings.get("alert_support", True):
            send_ntfy_alert(f"{t} broke below its 50-day EMA support line (${ema50:.2f}).", f"⚠️ {t} Support Break")
            alerts_triggered += 1
    except Exception:
        continue

print(f"Check complete. {alerts_triggered} alerts dispatched.")
