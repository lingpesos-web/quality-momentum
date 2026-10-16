import json
import os
import urllib.request
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timezone

STATE_FILE = "alert_state.json"
DATA_FILE = "watchlists.json"

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

def send_ntfy_alert(message, title="Live Intraday Alert"):
    try:
        # Strip emojis from HTTP header so Python urllib never fails on ASCII encoding
        ascii_title = title.encode("ascii", "ignore").decode("ascii").strip()
        if not ascii_title:
            ascii_title = "Market Alert"
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

# 1. Load all Watchlist Folders (Active Portfolio, Opportunity Radar, Special Case Stocks, etc.)
watchlists = load_json(DATA_FILE, {"Active Portfolio": [], "Opportunity Radar": []})
tickers = []
for folder_syms in watchlists.values():
    if isinstance(folder_syms, list):
        tickers.extend(folder_syms)
tickers = list(dict.fromkeys(tickers))

if not tickers:
    print("Watchlist is empty. Exiting.")
    exit()

# 2. Load Intraday Anti-Spam Memory (Resets automatically each new UTC trading day)
now_utc = datetime.now(timezone.utc)
today_str = now_utc.strftime("%Y-%m-%d")
alert_state = load_json(STATE_FILE, {"date": today_str, "alerted": []})
if alert_state.get("date") != today_str:
    alert_state = {"date": today_str, "alerted": []}
already_alerted = set(alert_state.get("alerted", []))

# 3. Determine if this run is a Manual Test, Market-Close Briefing, or Live Intraday Check
event_name = os.environ.get("GITHUB_EVENT_NAME", "schedule")
is_manual_run = (event_name == "workflow_dispatch")
# 20:00 to 20:45 UTC is 4:00 PM to 4:45 PM US Eastern Time (Market Close)
is_market_close_window = (now_utc.hour == 20)

# 4. Download Latest Market Data (1Y Daily + Live Intraday Price)
data = yf.download(tickers, period="1y", interval="1d", group_by="ticker", progress=False)

new_intraday_buys = []
new_intraday_targets = []
new_intraday_stops = []

all_buys_today = []
all_tct_boxes = []
all_breakouts = []
all_stops_today = []

for t in tickers:
    try:
        if len(tickers) == 1:
            df = data.copy()
        else:
            if t in data.columns.levels[0]:
                df = data[t].copy()
            else:
                continue

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
        atr14_daily = float(pd.concat([tr1, tr2, tr3], axis=1).max(axis=1).rolling(14).mean().iloc[-1])
        if np.isnan(atr14_daily) or atr14_daily <= 0:
            atr14_daily = curr_close * 0.025
        atr14_1h_est = atr14_daily / 2.55

        # Confirmed Swing Points (k = 3)
        swing_highs = []
        swing_lows = []
        for i in range(3, n - 3):
            if high_arr[i] == np.max(high_arr[i - 3:i + 4]):
                swing_highs.append((i, float(high_arr[i])))
            if low_arr[i] == np.min(low_arr[i - 3:i + 4]):
                swing_lows.append((i, float(low_arr[i])))

        # Check for True TCT Bottom Accumulation Box (>= 25 bars slow decline)
        lookback = min(n, 130)
        start_idx = n - lookback
        peak_rel_idx = int(np.argmax(high_arr[start_idx:max(start_idx + 1, n - 20)]))
        peak_idx = start_idx + peak_rel_idx
        peak_price = float(high_arr[peak_idx])
        recent_lows = [(idx, val) for idx, val in swing_lows if idx > peak_idx]

        tct_valid_range = False
        range_high, bos_level, tap3_price = None, None, None

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
                        tap3_price = float(np.min(low_arr[t2_idx:]))
                        local_minor_high = float(np.max(high_arr[-5:-1])) if n >= 6 else curr_close * 1.015
                        bos_level = min(local_minor_high, tap3_price + 0.35 * rng_height)
                        bos_level = max(bos_level, tap3_price * 1.012)
                        range_high = r_high
                        death_low = t2_val - 0.30 * (range_high - t2_val)
                        if death_low <= curr_close <= range_high * 0.98:
                            tct_valid_range = True
                            break
                if tct_valid_range:
                    break

        # Dual-Playbook Trigger, Stop, and Target Calculation
        if tct_valid_range and range_high and bos_level and tap3_price:
            entry_ref = curr_close if curr_close >= bos_level else bos_level
            raw_stop = tap3_price - (0.5 * atr14_1h_est)
            effective_stop = max(min(raw_stop, entry_ref * 0.98), entry_ref * 0.93)
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
            effective_stop = max(min(raw_stop, entry_ref * 0.978), entry_ref * 0.935)
            target_price = entry_ref + 2.5 * (entry_ref - effective_stop)

        risk_per_share = max(entry_ref - effective_stop, 0.0001)
        reward_per_share = max(target_price - entry_ref, 0.0)
        r_multiple = reward_per_share / risk_per_share

        just_crossed_bos = (curr_close >= bos_level) and (prev_close < bos_level * 1.012)
        is_breakout = (curr_close >= high20_prev) and (rvol >= 1.3) and (curr_close > ema50)

        # Evaluate Triggers
        if tct_valid_range and curr_close >= bos_level and r_multiple >= 2.0:
            msg = f"{t} (${curr_close:.2f} > TCT BOS ${bos_level:.2f} -> Tgt ${target_price:.2f})"
            all_buys_today.append(msg)
            if f"{t}_BUY" not in already_alerted:
                new_intraday_buys.append(msg)
                already_alerted.add(f"{t}_BUY")
        elif not tct_valid_range and curr_close > ema50 and curr_close > ema20 and just_crossed_bos and r_multiple >= 2.0:
            msg = f"{t} (${curr_close:.2f} > Trigger ${bos_level:.2f} -> Tgt ${target_price:.2f})"
            all_buys_today.append(msg)
            if f"{t}_BUY" not in already_alerted:
                new_intraday_buys.append(msg)
                already_alerted.add(f"{t}_BUY")
        elif tct_valid_range and curr_close < bos_level:
            all_tct_boxes.append(f"{t} (Wait > ${bos_level:.2f})")

        if is_breakout:
            all_breakouts.append(f"{t} (${curr_close:.2f}, {rvol:.1f}x Vol)")
            if f"{t}_BRK" not in already_alerted and f"{t}_BUY" not in already_alerted:
                new_intraday_buys.append(f"{t} 20D Breakout (${curr_close:.2f}, {rvol:.1f}x Vol)")
                already_alerted.add(f"{t}_BRK")

        if curr_close >= target_price * 0.995:
            if f"{t}_TGT" not in already_alerted:
                new_intraday_targets.append(f"{t} Hit Target (${curr_close:.2f} >= ${target_price:.2f})")
                already_alerted.add(f"{t}_TGT")

        if curr_close <= effective_stop or (curr_close < ema50 * 0.985 and prev_close >= ema50 * 0.985):
            msg_stop = f"{t} (${curr_close:.2f} < Stop/EMA50 ${max(effective_stop, ema50):.2f})"
            all_stops_today.append(msg_stop)
            if f"{t}_STOP" not in already_alerted:
                new_intraday_stops.append(msg_stop)
                already_alerted.add(f"{t}_STOP")
        elif curr_close < ema50 * 0.985 and not tct_valid_range:
            all_stops_today.append(f"{t} (${curr_close:.2f})")

    except Exception:
        continue

# 5. Dispatch Notifications Based on Mode
if is_manual_run or is_market_close_window:
    # Full Summary Briefing (At Market Close or when manually tested on GitHub)
    lines = [
        f"Scanned {len(tickers)} watchlist stocks:",
        f"🟢 BUY NOW Triggers ({len(all_buys_today)}): " + (", ".join(all_buys_today[:6]) if all_buys_today else "None"),
        f"📐 In TCT Bottom Box ({len(all_tct_boxes)}): " + (", ".join(all_tct_boxes[:6]) if all_tct_boxes else "None"),
        f"🚀 20D Breakouts ({len(all_breakouts)}): " + (", ".join(all_breakouts[:6]) if all_breakouts else "None"),
        f"🔴 Below 50 EMA / Stop ({len(all_stops_today)}): " + (", ".join(all_stops_today[:8]) if all_stops_today else "None")
    ]
    briefing_text = "\n".join(lines)
    send_ntfy_alert(briefing_text, "Daily Portfolio Briefing")
    print("Sent Daily Briefing:\n" + briefing_text)
else:
    # Live Intraday Mode: Only ping if a NEW trigger just crossed!
    if new_intraday_buys or new_intraday_targets or new_intraday_stops:
        intraday_lines = []
        if new_intraday_buys:
            intraday_lines.append("🟢 NEW BUY TRIGGER: " + ", ".join(new_intraday_buys))
        if new_intraday_targets:
            intraday_lines.append("🎯 TAKE PROFIT HIT: " + ", ".join(new_intraday_targets))
        if new_intraday_stops:
            intraday_lines.append("🔴 STOP / SUPPORT BREAK: " + ", ".join(new_intraday_stops))
        alert_body = "\n".join(intraday_lines)
        send_ntfy_alert(alert_body, "Live Intraday Trigger Alert")
        print("Sent Live Intraday Alert:\n" + alert_body)
    else:
        print("Intraday check complete: No new triggers crossed in this window. Staying silent.")

# 6. Save updated anti-spam state
alert_state["alerted"] = sorted(list(already_alerted))
save_json(STATE_FILE, alert_state)
