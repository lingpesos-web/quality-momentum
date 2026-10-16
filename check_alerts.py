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

def send_ntfy_alert(message, title="Daily Market Close Briefing"):
    try:
        # Strip emojis from HTTP header to prevent Python urllib ASCII encoding crash
        ascii_title = title.encode("ascii", "ignore").decode("ascii").strip() or "Daily Market Briefing"
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"ntfy delivered successfully: HTTP {resp.status}")
    except Exception as e:
        print(f"ntfy error: {e}")

tickers = list(dict.fromkeys(watchlists.get("Active Portfolio", []) + watchlists.get("Opportunity Radar", [])))
if not tickers:
    send_ntfy_alert("Watchlist is empty. Please check watchlists.json.", "Watchlist Alert")
    exit()

data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False)

buy_now_list = []
tct_box_list = []
mom_breakouts = []
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
        n = len(df)

        ema20 = float(df["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
        ema50 = float(df["Close"].ewm(span=50, adjust=False).mean().iloc[-1])
        vol20 = float(df["Volume"].rolling(20).mean().iloc[-1])
        rvol = float(df["Volume"].iloc[-1] / vol20) if vol20 > 0 else 1.0
        high20_prev = float(df["High"].rolling(20).max().iloc[-2])

        tr1 = df["High"] - df["Low"]
        tr2 = (df["High"] - df["Close"].shift(1)).abs()
        tr3 = (df["Low"] - df["Close"].shift(1)).abs()
        atr14 = float(pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
        if np.isnan(atr14) or atr14 <= 0:
            atr14 = curr_close * 0.025

        # Check 5-day high trigger & realistic 2.5R target
        high_5d_prev = float(np.max(high_arr[-6:-1])) if n >= 7 else curr_close
        bos_level = curr_close if curr_close >= high_5d_prev else high_5d_prev
        stop_price = max(min(ema20 - 0.5 * atr14, bos_level - 1.5 * atr14), bos_level * 0.935)
        stop_price = min(stop_price, bos_level * 0.978)
        target_price = bos_level + 2.5 * (bos_level - stop_price)

        just_crossed = (curr_close >= high_5d_prev) and (prev_close < high_5d_prev * 1.012)
        is_breakout = (curr_close >= high20_prev) and (rvol >= 1.3) and (curr_close > ema50)

        if curr_close < ema50 * 0.985:
            sell_stops.append(f"{t} (${curr_close:.2f})")
        elif just_crossed and curr_close > ema50 and curr_close > ema20:
            buy_now_list.append(f"{t} (Buy ${curr_close:.2f} -> Tgt ${target_price:.2f})")
        elif is_breakout:
            mom_breakouts.append(f"{t} (${curr_close:.2f}, {rvol:.1f}x Vol)")
    except Exception:
        continue

lines = [
    f"Scanned {len(tickers)} watchlist stocks at US Close:",
    f"🟢 BUY NOW Triggers ({len(buy_now_list)}): " + (", ".join(buy_now_list[:6]) if buy_now_list else "None today"),
    f"🚀 20D Momentum Breakouts ({len(mom_breakouts)}): " + (", ".join(mom_breakouts[:6]) if mom_breakouts else "None today"),
    f"🔴 Below 50 EMA / Caution ({len(sell_stops)}): " + (", ".join(sell_stops[:8]) if sell_stops else "None")
]

briefing_text = "\n".join(lines)
send_ntfy_alert(briefing_text, "Daily Market Close Briefing")
print(briefing_text)
