import json
import os
import urllib.request
import yfinance as yf
import pandas as pd
import numpy as np

def load_json(filepath, default):
    if os.path.exists(filepath):
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return default

watchlists = load_json("watchlists.json", {"Active Portfolio": [], "Opportunity Radar": []})

def send_ntfy_alert(message, title="📊 Daily Portfolio Briefing"):
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/2026_USstockspicks",
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "high"}
        )
        urllib.request.urlopen(req, timeout=8)
    except Exception as e:
        print(f"ntfy error: {e}")

tickers = list(dict.fromkeys(watchlists.get("Active Portfolio", []) + watchlists.get("Opportunity Radar", [])))
if not tickers:
    send_ntfy_alert("Watchlist is empty. Please check watchlists.json.", "⚠️ Watchlist Alert")
    exit()

data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False)

tct_buys = []
mom_breakouts = []
watching_box = []
sell_stops = []

for t in tickers:
    try:
        df = data[t].copy() if len(tickers) > 1 and t in data.columns.levels[0] else (data.copy() if len(tickers) == 1 else pd.DataFrame())
        df.dropna(subset=["Close", "High", "Low"], inplace=True)
        if len(df) < 35:
            continue

        close_arr = df["Close"].values.astype(float)
        high_arr = df["High"].values.astype(float)
        low_arr = df["Low"].values.astype(float)
        curr_close = float(close_arr[-1])
        prev_close = float(close_arr[-2])

        ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
        vol20 = float(df["Volume"].rolling(20).mean().iloc[-1])
        rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
        high20_prev = float(df["High"].rolling(20).max().iloc[-2])

        # Swing highs/lows (k=3) for TCT BOS & Stop levels
        n = len(df)
        swing_highs = [float(high_arr[i]) for i in range(max(3, n - 35), n - 3) if high_arr[i] == np.max(high_arr[i - 3:i + 4])]
        bos_level = swing_highs[-1] if swing_highs else high20_prev
        tap3_low = float(np.min(low_arr[-10:]))
        stop_price = min(tap3_low * 0.99, curr_close * 0.98)
        target_price = max(float(np.max(high_arr[-60:])), curr_close * 1.06)

        risk = max(curr_close - stop_price, 0.01)
        reward = max(target_price - curr_close, 0.0)
        r_mult = reward / risk

        just_crossed_bos = (curr_close >= bos_level) and (prev_close < bos_level * 1.015)
        is_breakout = (curr_close >= high20_prev) and (rvol >= 1.3) and (curr_close > ema50)

        if curr_close <= stop_price or curr_close < ema50 * 0.985:
            sell_stops.append(f"{t} (${curr_close:.2f} < Stop/EMA50)")
        elif just_crossed_bos and r_mult >= 2.0 and curr_close > ema50:
            tct_buys.append(f"{t} (Buy ${curr_close:.2f} -> Tgt ${target_price:.2f}, {r_mult:.1f}R)")
        elif is_breakout:
            mom_breakouts.append(f"{t} (${curr_close:.2f}, {rvol:.1f}x Vol)")
        elif abs(curr_close - bos_level) / bos_level <= 0.02 and r_mult >= 2.0:
            watching_box.append(f"{t} (Wait > ${bos_level:.2f})")
    except Exception:
        continue

lines = [
    f"Scanned {len(tickers)} watchlist stocks at US Close:",
    f"🟢 TCT BUY NOW ({len(tct_buys)}): " + (", ".join(tct_buys[:6]) if tct_buys else "None today"),
    f"🚀 Momentum Breakouts ({len(mom_breakouts)}): " + (", ".join(mom_breakouts[:6]) if mom_breakouts else "None today"),
    f"👀 Near BOS Trigger ({len(watching_box)}): " + (", ".join(watching_box[:6]) if watching_box else "None"),
    f"🔴 SELL / Below Support ({len(sell_stops)}): " + (", ".join(sell_stops[:8]) if sell_stops else "None")
]

briefing_text = "\n".join(lines)
send_ntfy_alert(briefing_text, "📊 Daily Market Close Briefing")
print(briefing_text)
