
def check_and_fire_active_position_alerts(records):
    """Monitors logged positions in positions.json and sends live alerts if rules trigger."""
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
                lines.append(f"🚨 STOP HIT: {sym} dropped to ${live_price:,.2f} (Stop was ${stop_price:,.2f})")
                alerted.add(f"{pos_id}_STOP")
            if live_price >= target15 and not pos.get("HalfSold", False) and f"{pos_id}_TGT15" not in alerted:
                lines.append(f"💰 +15% GAIN: {sym} reached ${live_price:,.2f}! Sell 50% ({int(pos['Shares']*0.5)} shs) and raise stop.")
                alerted.add(f"{pos_id}_TGT15")
            if live_price < ema20 and d["Change"] < 0 and f"{pos_id}_EMA20" not in alerted:
                lines.append(f"⚠️ BROKE 20-EMA: {sym} dropped to ${live_price:,.2f} (EMA20: ${ema20:,.2f}). Trailing Exit Triggered.")
                alerted.add(f"{pos_id}_EMA20")

        if lines:
            send_ntfy_alert("\n".join(lines), "Active Position Rule Alert")
            state["alerted"] = sorted(list(alerted))
            save_json(STATE_FILE, state)
    except Exception:
        pass

# --- DATA ENGINE 1: FAST BATCH INGESTION + TARGETED 8:00 AM HKT SETTLEMENT PATCH ---
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
    # Add active position tickers to fetch list
    pos_tickers = [str(p["Ticker"]).strip().upper() for p in positions if str(p.get("Ticker")).strip()]
    clean_tickers = list(dict.fromkeys(clean_tickers + pos_tickers))
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
        check_and_fire_active_position_alerts(results)
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
    data = {"Market Cap": "N/A", "Trailing P/E": "N/A", "Forward P/E": "N/A", "EPS (TTM)": "N/A", "Target Price": "N/A", "52W High": "N/A", "52W Low": "N/A", "Debt/Equity": "N/A", "Business Summary": "No corporate overview provided."}
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
    fig.update_layout(height=45, width=120, margin=dict(l=0, r=0, t=0, b=0), xaxis=dict(visible=False), yaxis=dict(visible=False), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
    return fig

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
    regime = {"label": "🟢 MARKET REGIME: BULLISH — S&P 500 Holding Trend · Favorable for New Setups", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
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
                regime = {"label": f"🟢 MARKET REGIME: BULLISH (S&P 500 Above 20 & 50 EMA · VIX {vix_c:.1f}) — Green Light for TCT, Swing & Momentum Buys", "bg": "#dcfce7", "border": "#86efac", "color": "#14532d"}
            elif sp_c < sp_ema50 or vix_c >= 25.0:
                regime = {"label": f"🔴 MARKET REGIME: RISK-OFF / CORRECTION (S&P Below 50 EMA or VIX Elevated at {vix_c:.1f}) — Protect Capital, Avoid Aggressive New Buys", "bg": "#fee2e2", "border": "#fca5a5", "color": "#7f1d1d"}
            else:
                regime = {"label": f"🟡 MARKET REGIME: CHOPPY / CAUTION (S&P Consolidating · VIX {vix_c:.1f}) — Be Selective, Focus on 20-EMA Pullbacks & True TCT Bottoms", "bg": "#fef9c3", "border": "#fde047", "color": "#713f12"}
    except Exception:
        pass
    return out, regime

# --- PRIMARY SIDEBAR NAVIGATION ---
st.sidebar.markdown(
    """<div style="padding: 10px 0 20px 0;"><span style="display: inline-block; width: 9px; height: 9px; background: #22c55e; border-radius: 50%; margin-right: 6px;"></span><span style="font-size: 0.85rem; font-weight: 600; letter-spacing: 0.05em; color: #a1a1aa;">6-PLAYBOOK LIVE ENGINE</span><h2 style="color: #f4efe6 !important; margin: 6px 0 0 0; font-size: 1.4rem;">Ledger</h2><span style="font-size: 0.75rem; color: #c5a059; text-transform: uppercase; letter-spacing: 0.1em; font-weight: 600;">Momentum · Swing · TCT v11.1</span></div>""",
    unsafe_allow_html=True
)

navigation = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "⚡ Live Real-Time Quotes", "Screener", "Watchlist", "Precious Metals, Crypto & Currency", "News & Earnings", "Settings"],
    key="nav_radio", label_visibility="collapsed", on_change=clear_inspection
)

st.sidebar.markdown("---")
sync_badge = "🟢 GitHub Auto-Sync Active" if get_github_token() else "🟡 Local Mode (Add GITHUB_TOKEN)"
st.sidebar.markdown(f"""<div style="position: fixed; bottom: 18px; font-size: 0.74rem; color: #a1a1aa;">{sync_badge}<br>Tap any <b>Stock Symbol</b> to open chart</div>""", unsafe_allow_html=True)

# --- MACRO BANNER & MARKET REGIME (HIDDEN ON FULL-SCREEN LIVE QUOTES PAGE) ---
if navigation != "⚡ Live Real-Time Quotes" or st.session_state.inspect_symbol is not None:
    macro_data, regime_info = fetch_macro_and_regime()
    if macro_data:
        cards_html = "".join([
            f'<div class="macro-card"><div class="macro-title">{name}</div><div class="macro-price">{price:,.2f}</div><div class="{"tick-pos" if chg >= 0 else "tick-neg"}">{"▲ +" if chg >= 0 else "▼ "}{chg:.2f} ({"+" if chg >= 0 else ""}{pct:.2f}%)</div></div>'
            for name, (price, chg, pct) in macro_data.items()
        ])
        st.markdown(f'<div class="macro-container">{cards_html}</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="background:{regime_info["bg"]}; border:1px solid {regime_info["border"]}; color:{regime_info["color"]}; padding:8px 14px; border-radius:8px; font-size:0.82rem; font-weight:600; margin-bottom:16px;">{regime_info["label"]}</div>', unsafe_allow_html=True)

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
        st.markdown(f"<h1>{sym} · 6-Playbook Technical & Fundamental Dossier</h1>", unsafe_allow_html=True)

    d = fetch_single_ticker_data(sym, account_size=settings["account_size"])
    funds = fetch_ticker_fundamentals(sym)

    if d is not None:
        df_hist = d["History"]
        f1, f2, f3, f4, f5, f6 = st.columns(6)
        raw_mcap = funds.get("Market Cap")
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
            st.markdown(f"**RSI(14) / RSI(2):** `{d['RSI']:.1f}` / `{d['RSI2']:.0f}`")
            st.markdown(f"*{d['TCT_Explain']}*")
            st.markdown("---")
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
        st.error(f"Unable to retrieve historical chart data for {sym}.")

else:
    if navigation == "Dashboard":
        st.markdown("<h1>Market Cockpit</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Tap any stock symbol to open its interactive chart & 6-Playbook Trade Ticket.</p>", unsafe_allow_html=True)

        all_monitored = get_all_monitored_tickers()
        stock_records = fetch_batch_market_data(all_monitored, account_size=settings["account_size"])

        if stock_records:
            best_pick = max(stock_records.values(), key=lambda x: (100 if x["TCT_Priority"] == 0 else 0) + (15 if x["RS_Leader"] else 0) + x["Score"])
            arr_b = "▲ +" if best_pick["Change"] >= 0 else "▼ -"
            st.markdown(
                f"""
                <div style="background-color: #0f291e; border-radius: 10px; padding: 20px 24px; color: #fbf9f4; margin-bottom: 20px;">
                    <div style="font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.12em; color: #c5a059; font-weight: 700;">
                        TODAY'S STANDOUT SETUP · {best_pick['TCT_Action']} · {best_pick['TCT_Model']}
                    </div>
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                        <div>
                            <a href="?inspect={best_pick['Ticker']}" target="_self" class="hero-ticker-link">📊 {best_pick['Ticker']}</a>
                            <span style="font-size: 1.25rem; color: #e2e8f0; margin-left: 10px; font-weight: 700;">${best_pick['Price']:,.2f}</span>
                            <span style="color: {'#4ade80' if best_pick['Change'] >= 0 else '#f87171'}; font-weight: 700; margin-left: 8px;">
                                {arr_b}${abs(best_pick['Change']):.2f} ({best_pick['Change_Pct']:+.2f}%)
                            </span>
                            <div style="color: #cbd5e1; font-size: 0.90rem; margin-top: 6px;">
                                <b>Buy Trigger:</b> ${best_pick['BOS_Level']:,.2f} · <b>Take Profit:</b> ${best_pick['Target_Price']:,.2f} (+{best_pick['Target_Pct']:.1f}%) · <b>Stop-Loss:</b> ${best_pick['Stop_Price']:,.2f} ({best_pick['Stop_Pct']:.1f}%) · <b>Size (0.5% Risk):</b> {best_pick['Shares_05Pct']} shs ({best_pick['R_Multiple']:.1f}R)
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-size: 2.2rem; font-weight: 700; color: #c5a059; font-family: 'Newsreader', serif;">{best_pick['Score']}</div>
                            <div style="font-size: 0.70rem; color: #94a3b8; text-transform: uppercase;">Composite Score</div>
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
                    news_html = '<div class="scroll-news-box">' + "".join([f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;"><span class="ticker-news-badge">[{a.get("ticker", "NEWS")}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>' for a in wl_news]) + '</div>'
                    st.markdown(news_html, unsafe_allow_html=True)
            with tab_macro:
                market_news = fetch_google_news_rss("US stock market news", max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if market_news:
                    m_html = '<div class="scroll-news-box">' + "".join([f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;">{n["publisher"]}<span class="age-badge">{n["age"]}</span></span><span>{n["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 3px;"><a href="{n["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{n["title"]}</a></div></div>' for n in market_news]) + '</div>'
                    st.markdown(m_html, unsafe_allow_html=True)
            with tab_mcf:
                mcf_news = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if mcf_news:
                    c_html = '<div class="scroll-news-box">' + "".join([f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 600;"><span class="ticker-news-badge">[{a["ticker"]}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>' for a in mcf_news]) + '</div>'
                    st.markdown(c_html, unsafe_allow_html=True)

        with col_right:
            st.subheader("Action Signals Snapshot")
            for r in sorted(stock_records.values(), key=lambda x: (x["TCT_Priority"], -x["Score"]))[:10]:
                arr_s = "▲ +" if r["Change"] >= 0 else "▼ -"
                clr_s = "#15803d" if r["Change"] >= 0 else "#b91c1c"
                st.markdown(
                    f"""
                    <div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;">
                        <div style="display: flex; justify-content: space-between; align-items: center;">
                            <div>
                                <a href="?inspect={r['Ticker']}" target="_self" class="ticker-link" style="font-size: 1.05rem;">📊 {r['Ticker']}</a>
                                <span class="badge {r['TCT_Badge']}" style="margin-left: 6px; font-size: 0.62rem;">{r['TCT_Action']}</span>
                            </div>
                            <div style="text-align: right;">
                                <span style="font-weight: 700; font-size: 0.92rem;">${r['Price']:,.2f}</span>
                                <span style="color:{clr_s}; font-size:0.78rem; font-weight:700; margin-left:4px;">{arr_s}${abs(r['Change']):.2f} ({r['Change_Pct']:+.2f}%)</span>
                            </div>
                        </div>
                        <div style="font-size: 0.74rem; color: #52525b; margin-top: 5px;">
                            <b>{r['TCT_Model']}</b> · Buy: <b>${r['BOS_Level']:,.2f}</b> · Target: <b style="color:#15803d;">${r['Target_Price']:,.2f}</b> · Stop: <b style="color:#b91c1c;">${r['Stop_Price']:,.2f}</b>
                        </div>
                    </div>
                    """, unsafe_allow_html=True
                )

    elif navigation == "⚡ Live Real-Time Quotes":
        st.markdown("""<style>.block-container { padding-top: 2.8rem !important; padding-bottom: 1rem !important; padding-left: 1.2rem !important; padding-right: 1.2rem !important; }</style>""", unsafe_allow_html=True)

        folder_names = list(watchlists.keys())
        folder_options = folder_names + ["All Watchlists Combined"]

        ctrl1, ctrl2, ctrl3, ctrl4, ctrl5, ctrl6, ctrl7 = st.columns([1.8, 1.9, 1.9, 1.3, 1.3, 0.8, 1.1])
        with ctrl1:
            selected_live_folder = st.selectbox("Watchlist", folder_options, index=0, label_visibility="collapsed")
        with ctrl2:
            live_board_mode = st.selectbox("Board Mode", ["📊 Custom Signal Board (Large Font)", "⚡ TradingView Streaming (Tick-by-Tick)"], index=0, label_visibility="collapsed")
        with ctrl3:
            live_sort = st.selectbox("Rank / Sort", ["Rank: My Saved Order", "Rank: 🟢 Action Signal (Buy First)", "Rank: 📈 Day % Change (Gainers)", "Rank: 📉 Day % Change (Losers)", "Rank: 🔥 Relative Strength vs S&P", "Rank: 💯 Composite Score"], index=0, label_visibility="collapsed")
        with ctrl4:
            auto_refresh_choice = st.selectbox("Auto-Refresh Timer", ["⏱️ Auto: Off", "⏱️ Auto: 15s", "⏱️ Auto: 30s", "⏱️ Auto: 60s"], index=0, label_visibility="collapsed")
        with ctrl5:
            if selected_live_folder != "All Watchlists Combined" and selected_live_folder != "Active Positions":
                quick_add = st.text_input("Quick Add Ticker", placeholder=f"+ Add to {selected_live_folder}", label_visibility="collapsed").upper().strip()
                if quick_add and quick_add not in watchlists[selected_live_folder]:
                    watchlists[selected_live_folder].append(quick_add)
                    sync_file_to_github(watchlists, DATA_FILE)
                    st.rerun()
            else:
                st.caption("All Combined Lists" if selected_live_folder == "All Watchlists Combined" else "Managed via Watchlist Tab")
        with ctrl6:
            if st.button("🔄", help="Refresh Quotes Now", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        with ctrl7:
            if selected_live_folder != "Active Positions":
                edit_mode_live = st.checkbox("✏️ Edit List", value=False)
            else:
                edit_mode_live = False

        if edit_mode_live:
            st.markdown('<div style="background:#ffffff; border:1px solid #dcd6cb; border-radius:8px; padding:12px 16px; margin-bottom:12px;">', unsafe_allow_html=True)
            c_top1, c_top2, c_top3 = st.columns([2.2, 2.2, 1.6])
            with c_top1:
                st.markdown(f"**✏️ Editing Watchlist: `{selected_live_folder}`**")
            with c_top2:
                new_list_name = st.text_input("Create New Watchlist Folder", placeholder="e.g. AI & Semis", key="live_new_folder_in", label_visibility="collapsed")
                if st.button("➕ Create New Watchlist", key="live_btn_new_folder") and new_list_name.strip():
                    if new_list_name.strip() not in watchlists:
                        watchlists[new_list_name.strip()] = []
                        sync_file_to_github(watchlists, DATA_FILE)
                        st.rerun()
            with c_top3:
                if st.button("💾 Save & Sync Order to GitHub", type="primary", use_container_width=True, key="live_sync_gh"):
                    sync_file_to_github(watchlists, DATA_FILE)
                    st.success("Synced!")
            
            syms_ed = watchlists.get(selected_live_folder, [])
            if syms_ed:
                e_col1, e_col2 = st.columns(2)
                half = (len(syms_ed) + 1) // 2
                for i, s in enumerate(syms_ed):
                    with (e_col1 if i < half else e_col2):
                        r1, r2, r3, r4, r5 = st.columns([2.4, 1, 1, 1, 1])
                        r1.markdown(f"**{i+1}. {s}**")
                        if r2.button("⏫", key=f"lv_t_{s}_{i}", disabled=(i == 0)):
                            syms_ed.pop(i); syms_ed.insert(0, s); save_json(DATA_FILE, watchlists); st.rerun()
                        if r3.button("⬆️", key=f"lv_u_{s}_{i}", disabled=(i == 0)):
                            syms_ed[i-1], syms_ed[i] = syms_ed[i], syms_ed[i-1]; save_json(DATA_FILE, watchlists); st.rerun()
                        if r4.button("⬇️", key=f"lv_d_{s}_{i}", disabled=(i == len(syms_ed)-1)):
                            syms_ed[i+1], syms_ed[i] = syms_ed[i], syms_ed[i+1]; save_json(DATA_FILE, watchlists); st.rerun()
                        if r5.button("🗑️", key=f"lv_x_{s}_{i}"):
                            syms_ed.pop(i); sync_file_to_github(watchlists, DATA_FILE); st.rerun()
            st.markdown('</div>', unsafe_allow_html=True)

        active_live_syms = get_all_monitored_tickers() if selected_live_folder == "All Watchlists Combined" else ([p["Ticker"] for p in positions] if selected_live_folder == "Active Positions" else list(watchlists.get(selected_live_folder, [])))
        run_every_sec = {"⏱️ Auto: Off": None, "⏱️ Auto: 15s": 15, "⏱️ Auto: 30s": 30, "⏱️ Auto: 60s": 60}.get(auto_refresh_choice)

        def render_live_watchboard_content():
            bucket = int(time.time() // run_every_sec) if run_every_sec else int(time.time() // 120)
            live_records = fetch_batch_market_data(active_live_syms, account_size=settings["account_size"], refresh_bucket=bucket)

            ordered_syms = [s for s in active_live_syms if s in live_records]
            missing_syms = [s for s in active_live_syms if s not in live_records]

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

            if selected_live_folder == "Active Positions":
                st.markdown("### 💼 My Active Positions & Rule Enforcer")
                
                tot_invested = sum(p["Shares"] * p["BuyPrice"] for p in positions)
                tot_value = sum(p["Shares"] * live_records.get(p["Ticker"], {}).get("Price", p["BuyPrice"]) for p in positions)
                unreal_pnl = tot_value - tot_invested
                unreal_pct = (unreal_pnl / tot_invested * 100) if tot_invested else 0.0
                
                c_m1, c_m2, c_m3 = st.columns(3)
                c_m1.metric("Total Invested Cost", f"${tot_invested:,.2f}")
                c_m2.metric("Current Market Value", f"${tot_value:,.2f}")
                c_m3.metric("Total Unrealized P&L", f"${unreal_pnl:,.2f}", f"{unreal_pct:+.2f}%")
                
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
                            rule_status = '<span class="badge badge-tct-sell" style="background:#dc2626;">🚨 STOP HIT</span>'
                        elif price >= p["Target15"] and not p.get("HalfSold", False):
                            rule_status = '<span class="badge badge-tct-buy" style="background:#059669;">💰 UP +15% (SELL 50%)</span>'
                        elif price < d["EMA20_Val"]:
                            rule_status = '<span class="badge badge-caution">⚠️ BROKE 20-EMA</span>'
                            
                        rows_html += (
                            f'<tr>'
                            f'<td>{rule_status}</td>'
                            f'<td><a href="?rt_chart={sym}" target="_self" class="rt-sym-link">{sym}</a></td>'
                            f'<td style="font-weight:800;">{arrow} ${price:,.2f} <span style="font-size:0.75rem;font-weight:600;color:{"#15803d" if d["Change"]>=0 else "#b91c1c"};">({d["Change_Pct"]:+.2f}%)</span></td>'
                            f'<td>${bp:,.2f} <span style="font-size:0.75rem;color:#71717a;">({shares} shs)</span></td>'
                            f'<td style="color:{clr}; font-weight:800;">{sign}${pnl:,.2f} ({sign}{pnl_pct:.2f}%)</td>'
                            f'<td style="color:#b91c1c; font-weight:700;">${p["StopLoss"]:,.2f}</td>'
                            f'<td style="color:#15803d; font-weight:700;">${p["Target15"]:,.2f}</td>'
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
                    
            elif live_board_mode.startswith("📊 Custom Signal Board"):
                def build_half_table_html(sym_slice):
                    rows_html = ""
                    for sym in sym_slice:
                        d = live_records[sym]
                        chg, pct = d["Change"], d["Change_Pct"]
                        color = "#15803d" if chg >= 0 else "#b91c1c"
                        arrow = "▲" if chg >= 0 else "▼"
                        sign = "+" if chg >= 0 else "-"
                        short_sig = d.get("TCT_Short_Sig", "🔵 Uptrend")
                        rows_html += (
                            f'<tr>'
                            f'<td>{short_sig}</td>'
                            f'<td><a href="?rt_chart={sym}" target="_self" class="rt-sym-link" title="Tap to open live chart below">{sym}</a>'
                            f'<a href="?inspect={sym}" target="_self" class="rt-dossier-link" title="Open Full TCT Dossier">📋</a></td>'
                            f'<td style="font-weight:800; color:{color};">{arrow} {d["Price"]:,.2f}</td>'
                            f'<td style="color:{color}; font-weight:700;">{sign}{abs(chg):.2f} ({pct:+.2f}%)</td>'
                            f'<td style="color:#15803d; font-weight:600;">{d["Day_High"]:,.2f}</td>'
                            f'<td style="color:#b91c1c; font-weight:600;">{d["Day_Low"]:,.2f}</td>'
                            f'</tr>'
                        )
                    return f'<table class="live-quote-table"><thead><tr><th>Signal</th><th>Symbol</th><th>Price</th><th>Day Chg ($ / %)</th><th>High</th><th>Low</th></tr></thead><tbody>{rows_html}</tbody></table>'

                if ordered_syms:
                    mid = (len(ordered_syms) + 1) // 2
                    left_table_html = build_half_table_html(ordered_syms[:mid])
                    right_table_html = build_half_table_html(ordered_syms[mid:]) if ordered_syms[mid:] else ""
                    st.markdown(f'<div class="live-board-grid"><div>{left_table_html}</div><div>{right_table_html}</div></div>', unsafe_allow_html=True)
                    timer_status = f"Auto-refreshing every {run_every_sec}s (Instant ntfy Active)" if run_every_sec else "Manual refresh mode"
                    st.caption(f"🔥 Momentum · 🟢 Buy Now · 🎯 Swing Buy · 🪃 Oversold · 📐 TCT Box · 🔵 Uptrend  |  **Tap Symbol** for Bottom Live Chart · Tap **📋** for Dossier  |  *{timer_status} · Last updated: {datetime.now().strftime('%H:%M:%S')}*")
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

                    st.markdown("<div style='margin-top: 24px;'></div>", unsafe_allow_html=True)

                    mid = (len(tv_all_syms) + 1) // 2
                    l_tv = [{"name": s, "displayName": f"{live_records[s]['TCT_Dot']} {s}" if s in live_records else s} for s in tv_all_syms[:mid]]
                    r_tv = [{"name": s, "displayName": f"{live_records[s]['TCT_Dot']} {s}" if s in live_records else s} for s in tv_all_syms[mid:]]
                    wh = max(460, min(820, mid * 38 + 100))

                    tc1, tc2 = st.columns(2)
                    with tc1:
                        components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>{{"width": "100%", "height": {wh}, "symbolsGroups": {json.dumps([{"name": f"{selected_live_folder} (Col 1)", "symbols": l_tv}])}, "showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}</script></div>""", height=wh + 16)
                    with tc2:
                        if r_tv:
                            components.html(f"""<div class="tradingview-widget-container"><div class="tradingview-widget-container__widget"></div><script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-market-quotes.js" async>{{"width": "100%", "height": {wh}, "symbolsGroups": {json.dumps([{"name": f"{selected_live_folder} (Col 2)", "symbols": r_tv}])}, "showSymbolLogo": true, "colorTheme": "light", "locale": "en"}}</script></div>""", height=wh + 16)

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
                st.markdown(f"### 📈 Live Streaming Chart: `{chart_sym}`")
            with ch_c2:
                rt_interval = st.selectbox("Timeframe", ["5", "15", "60", "240", "D"], format_func=lambda x: {"5": "5-Minute", "15": "15-Minute", "60": "1-Hour (BOS)", "240": "4-Hour", "D": "Daily"}[x], index=2, label_visibility="collapsed")
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
        st.markdown("<h1>6-Playbook Market Screener</h1>", unsafe_allow_html=True)
        st.markdown("<p style='color: #52525b; margin-top: -12px;'>Use the One-Tap Strategy Presets below or build a custom scan across ~220 liquid US stocks.</p>", unsafe_allow_html=True)

        all_watchlist_syms = get_all_monitored_tickers()
        full_market_syms = list(dict.fromkeys([s for s_list in GICS_SECTORS.values() for s in s_list] + all_watchlist_syms))

        universe_mode = st.radio(
            "1. Choose Scan Universe",
            [f"Expanded Liquid Market (~{len(full_market_syms)} Top US Stocks)", f"My Watchlists Only ({len(all_watchlist_syms)} Stocks — Instant)", "Custom Sector Selection below"],
            horizontal=True
        )

        def get_target_universe(selected_secs):
            if universe_mode.startswith("My Watchlists"):
                return all_watchlist_syms
            elif universe_mode.startswith("Expanded Liquid"):
                return full_market_syms
            return list(dict.fromkeys([s for sc in selected_secs for s in GICS_SECTORS[sc]]))

        st.markdown("### 2. One-Tap 6-Playbook Strategy Preset Scans")
        p_col1, p_col2, p_col3, p_col4, p_col5 = st.columns(5)

        if p_col1.button("🔥 Pure Momentum Leaders", use_container_width=True, type="primary"):
            s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
            st.session_state.screener_matches = sorted([d for d in s_data.values() if d["Is_Pure_Momentum"]], key=lambda x: -x["RS_Diff"])
            st.session_state.screener_title = "🔥 Pure Momentum Leaders (RS+, Price>20/50/200, RSI 55-75)"
        if p_col2.button("🟢 All 'BUY NOW'", use_container_width=True):
            s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
            st.session_state.screener_matches = sorted([d for d in s_data.values() if d["TCT_Priority"] == 0], key=lambda x: -x["Score"])
            st.session_state.screener_title = "🟢 All Immediate 'BUY NOW' & 'SWING BUY' Triggers"
        if p_col3.button("📐 TCT Bottoms", use_container_width=True):
            s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
            st.session_state.screener_matches = sorted([d for d in s_data.values() if d["TCT_Valid_Range"]], key=lambda x: (x["TCT_Priority"], -x["R_Multiple"]))
            st.session_state.screener_title = "📐 Playbook 1: Valid 25+ Bar TCT Accumulation Boxes"
        if p_col4.button("🎯 Pullback & Coil", use_container_width=True):
            s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
            st.session_state.screener_matches = sorted([d for d in s_data.values() if d["Playbook_Cat"] == "SWING_PULLBACK"], key=lambda x: -x["Score"])
            st.session_state.screener_title = "🎯 Playbooks 3 & 4: 20-EMA Pullback & Volatility Squeeze Swings"
        if p_col5.button("🚀 20D Breakouts", use_container_width=True):
            s_data = fetch_batch_market_data(get_target_universe(list(GICS_SECTORS.keys())), account_size=settings["account_size"])
            st.session_state.screener_matches = sorted([d for d in s_data.values() if d["Playbook_Cat"] == "BREAKOUT"], key=lambda x: -x["Score"])
            st.session_state.screener_title = "🚀 Playbooks 2 & 6: Momentum & High-Volume Gap Breakouts"

        with st.expander("Optional: Custom Sector & Technical Filter Builder", expanded=False):
            f_col1, f_col2, f_col3 = st.columns([1.2, 1.4, 1.4])
            with f_col1:
                selected_sectors = [sec for sec in GICS_SECTORS.keys() if st.checkbox(sec, value=True, key=f"sec_{sec}")]
            with f_col2:
                s_rs = st.checkbox("🔥 Outperforming S&P 500 (RS Leader)", value=False)
                s1 = st.checkbox("RSI Rising Above 55 (Momentum)", value=False)
                s4 = st.checkbox("20-Day High Breakout (Volume Confirmed)", value=False)
                s7 = st.checkbox("Pullback Near 20D or 50D EMA Support", value=False)
            with f_col3:
                tct1 = st.checkbox("🟢 Action = 'BUY NOW' / 'SWING BUY'", value=False)
                tct2 = st.checkbox("📐 True TCT Bottom Accumulation Box Only", value=False)
                tct4 = st.checkbox("Reward-to-Risk ≥ 2.0R to Target", value=False)
                tct5 = st.checkbox("Liquidity (20D Dollar Volume ≥ $50M)", value=False)

            if st.button("Run Custom Filter Scan", type="primary"):
                s_data = fetch_batch_market_data(get_target_universe(selected_sectors), account_size=settings["account_size"])
                matches = []
                for t, d in s_data.items():
                    if s_rs and not d["RS_Leader"]: continue
                    if s1 and d["RSI"] < 55: continue
                    if s4 and not d["Is_Breakout"]: continue
                    if s7 and not d["Pullback_EMA50"]: continue
                    if tct1 and d["TCT_Priority"] != 0: continue
                    if tct2 and not d["TCT_Valid_Range"]: continue
                    if tct4 and not d["TCT_2R_Pass"]: continue
                    if tct5 and not d["TCT_Liq_50M"]: continue
                    matches.append(d)
                st.session_state.screener_matches = sorted(matches, key=lambda x: (x["TCT_Priority"], -x["Score"]))
                st.session_state.screener_title = f"Custom Filter Scan ({len(matches)} Matches)"

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
                        <div><a href="?inspect={m['Ticker']}" target="_self" class="ticker-link">📊 {m['Ticker']}</a> <span class="badge {m['TCT_Badge']}">{m['TCT_Action']}</span></div>
                        <div style="font-size: 0.85rem; color: #71717a; margin-top: 3px;">${m['Price']:,.2f} · <span style="color: {'#15803d' if m['Change']>=0 else '#b91c1c'}; font-weight: 700;">{arr_m}${abs(m['Change']):.2f} ({m['Change_Pct']:+.2f}%)</span> · <b>{m['TCT_Model']}</b></div>
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
                            sync_file_to_github(watchlists, DATA_FILE)
                            st.success("Synced!")

    elif navigation == "Watchlist":
        st.markdown("<h1>Watchlists & 6-Playbook Action Tickets</h1>", unsafe_allow_html=True)

        folder = st.radio("Select Watchlist Folder", list(watchlists.keys()), horizontal=True)
        
        if folder == "Active Positions":
            st.markdown("### 💼 My Active Positions & Rule Enforcer")
            
            # Position Entry Form
            with st.expander("➕ Log a New Position", expanded=False):
                c_in1, c_in2, c_in3, c_in4, c_in5 = st.columns(5)
                new_pos_sym = c_in1.text_input("Ticker", placeholder="e.g. NVDA").upper().strip()
                new_pos_px = c_in2.number_input("Buy Price ($)", min_value=0.01, value=100.0, step=1.0)
                new_pos_shs = c_in3.number_input("Shares", min_value=1, value=100, step=10)
                new_pos_dt = c_in4.date_input("Buy Date")
                if c_in5.button("💾 Save Trade", use_container_width=True):
                    if new_pos_sym:
                        new_trade = {
                            "id": f"{new_pos_sym}_{int(time.time())}",
                            "Ticker": new_pos_sym,
                            "BuyPrice": new_pos_px,
                            "Shares": new_pos_shs,
                            "BuyDate": new_pos_dt.strftime("%Y-%m-%d"),
                            "StopLoss": new_pos_px * 0.90,  # 10% default stop
                            "Target15": new_pos_px * 1.15,  # +15% profit target
                            "HalfSold": False
                        }
                        positions.append(new_trade)
                        sync_file_to_github(positions, POSITIONS_FILE)
                        if new_pos_sym not in watchlists["Active Positions"]:
                            watchlists["Active Positions"].append(new_pos_sym)
                            sync_file_to_github(watchlists, DATA_FILE)
                        st.success("Position Logged!")
                        st.rerun()
            
            st.markdown("---")
            pos_syms = [p["Ticker"] for p in positions]
            data_dict = fetch_batch_market_data(pos_syms, account_size=settings["account_size"])
            
            if positions:
                for idx, p in enumerate(positions):
                    sym = p["Ticker"]
                    bp = p["BuyPrice"]
                    shares = p["Shares"]
                    live_price = data_dict.get(sym, {}).get("Price", bp)
                    chg_pct = data_dict.get(sym, {}).get("Change_Pct", 0.0)
                    ema20 = data_dict.get(sym, {}).get("EMA20_Val", bp)
                    
                    pnl = (live_price - bp) * shares
                    pnl_pct = ((live_price - bp) / bp) * 100.0
                    clr_pnl = "#15803d" if pnl >= 0 else "#b91c1c"
                    
                    c_p1, c_p2, c_p3 = st.columns([1.5, 4.5, 2.0])
                    with c_p1:
                        st.markdown(f"**<a href='?inspect={sym}' target='_self' class='ticker-link'>{sym}</a>**<br><span style='font-size:1.4rem;font-weight:800;'>${live_price:,.2f}</span>", unsafe_allow_html=True)
                    with c_p2:
                        st.markdown(
                            f"<div style='display:flex; justify-content:space-between; padding:8px 12px; background:#f8f9fa; border-radius:8px; border:1px solid #e2e8f0;'>"
                            f"<div><span style='font-size:0.75rem;color:#64748b;'>Cost Basis</span><br><b>${bp:,.2f}</b> <span style='font-size:0.8rem;'>({shares} shs)</span></div>"
                            f"<div><span style='font-size:0.75rem;color:#64748b;'>Stop-Loss</span><br><b style='color:#dc2626;'>${p['StopLoss']:,.2f}</b></div>"
                            f"<div><span style='font-size:0.75rem;color:#64748b;'>+15% Target</span><br><b style='color:#059669;'>${p['Target15']:,.2f}</b></div>"
                            f"<div><span style='font-size:0.75rem;color:#64748b;'>Unrealized P&L</span><br><b style='color:{clr_pnl};'>${pnl:,.2f} ({pnl_pct:+.2f}%)</b></div>"
                            f"</div>",
                            unsafe_allow_html=True
                        )
                        if live_price >= p["Target15"] and not p.get("HalfSold", False):
                            st.warning(f"💰 Target Reached! Stock is up +15%. Time to sell 50% ({int(shares/2)} shs) and raise stop to breakeven (${bp:,.2f}).")
                        if live_price < ema20:
                            st.error(f"⚠️ Trailing Exit Warning: {sym} has dropped below its 20-day EMA (${ema20:,.2f}).")
                            
                    with c_p3:
                        with st.popover("⚙️ Manage Trade", use_container_width=True):
                            new_stop = st.number_input("Raise Stop-Loss ($)", value=float(p["StopLoss"]), key=f"stop_{p['id']}")
                            if st.button("Update Stop", key=f"upd_{p['id']}"):
                                positions[idx]["StopLoss"] = new_stop
                                sync_file_to_github(positions, POSITIONS_FILE)
                                st.rerun()
                                
                            if not p.get("HalfSold", False):
                                if st.button("✅ Mark 50% Sold & Raise Stop to Breakeven", key=f"sold_{p['id']}"):
                                    positions[idx]["Shares"] = int(shares / 2)
                                    positions[idx]["HalfSold"] = True
                                    positions[idx]["StopLoss"] = max(p["StopLoss"], bp)
                                    sync_file_to_github(positions, POSITIONS_FILE)
                                    st.rerun()
                                    
                            if st.button("🗑️ Close / Remove Position", key=f"del_{p['id']}"):
                                positions.pop(idx)
                                sync_file_to_github(positions, POSITIONS_FILE)
                                st.rerun()
                    st.markdown("<hr style='margin:10px 0;'>", unsafe_allow_html=True)
            else:
                st.info("No active positions tracked. Log a trade above to enable 24/7 rule monitoring.")

        else:
            symbols = watchlists.get(folder, [])
            col_add, col_sort, col_ed = st.columns([2.6, 2.2, 1.2])
            with col_add:
                c_in, c_btn = st.columns([3, 1])
                new_sym = c_in.text_input("Add symbol to folder", placeholder=f"Add to {folder} (e.g. AVGO)", label_visibility="collapsed").upper().strip()
                if c_btn.button("+ Add") and new_sym:
                    if new_sym not in symbols:
                        watchlists[folder].append(new_sym)
                        sync_file_to_github(watchlists, DATA_FILE)
                        st.toast("Added")
                        st.rerun()
            with col_sort:
                sort_by = st.selectbox("Sort By", ["Saved Order (My Custom Sequence)", "Action Signal (Buy Now First)", "Relative Strength vs S&P 500", "Composite Score (High → Low)", "Reward-to-Risk Ratio (High → Low)", "Day % Change (High → Low)", "Alphabetical (A → Z)"], index=0, label_visibility="collapsed")
            with col_ed:
                show_reorder = st.checkbox("✏️ Edit / Reorder List", value=False)

            if show_reorder:
                render_watchlist_reorder_panel(folder, key_prefix="wl_ed")

            st.markdown("**One-Tap Strategy Playbook Filter:**")
            wf1, wf2, wf3, wf4, wf5, wf6 = st.columns(6)
            if wf1.button("🔥 Momentum", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "MOMENTUM" else "secondary"):
                st.session_state.wl_preset_filter = "MOMENTUM"; st.rerun()
            if wf2.button("🟢 Buy Triggers", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "BUY" else "secondary"):
                st.session_state.wl_preset_filter = "BUY"; st.rerun()
            if wf3.button("📐 TCT Bottoms", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "TCT" else "secondary"):
                st.session_state.wl_preset_filter = "TCT"; st.rerun()
            if wf4.button("🎯 Swings", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "SWING" else "secondary"):
                st.session_state.wl_preset_filter = "SWING"; st.rerun()
            if wf5.button("🪃 Oversold", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "OVERSOLD" else "secondary"):
                st.session_state.wl_preset_filter = "OVERSOLD"; st.rerun()
            if wf6.button("📋 Show All", use_container_width=True, type="primary" if st.session_state.wl_preset_filter == "ALL" else "secondary"):
                st.session_state.wl_preset_filter = "ALL"; st.rerun()

            pills_html = "".join([f'<a href="?inspect={s}" target="_self" class="pill">{i+1}. {s}</a>' for i, s in enumerate(symbols)])
            st.markdown(f"<div style='margin: 8px 0;'>{pills_html}</div>", unsafe_allow_html=True)
            st.markdown("---")

            data_dict = fetch_batch_market_data(symbols, account_size=settings["account_size"])
            earnings_map = fetch_upcoming_earnings_map(symbols)

            display_symbols = [s for s in symbols if s in data_dict]
            flt = st.session_state.wl_preset_filter
            if flt == "MOMENTUM": display_symbols = [s for s in display_symbols if data_dict[s]["Is_Pure_Momentum"]]
            elif flt == "BUY": display_symbols = [s for s in display_symbols if data_dict[s]["TCT_Priority"] == 0]
            elif flt == "TCT": display_symbols = [s for s in display_symbols if data_dict[s]["TCT_Valid_Range"]]
            elif flt == "SWING": display_symbols = [s for s in display_symbols if data_dict[s]["Playbook_Cat"] == "SWING_PULLBACK"]
            elif flt == "OVERSOLD": display_symbols = [s for s in display_symbols if data_dict[s]["Is_Oversold_Swing"]]

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
                st.info("No stocks matched that filter in this folder. Tap '📋 Show All' above to reset.")

            left_c, right_c = st.columns(2)
            for idx, sym in enumerate(display_symbols):
                d = data_dict[sym]
                arr_w = "▲ +" if d["Change"] >= 0 else "▼ -"
                rs_html = f'<span class="badge badge-rs-lead" style="margin-left: 4px;">🔥 Leading S&P ({d["RS_Diff"]:+.1f}%)</span>' if d["RS_Leader"] else f'<span class="badge badge-rs-lag" style="margin-left: 4px;">RS {d["RS_Diff"]:+.1f}%</span>'
                earn_html = ""
                if sym in earnings_map:
                    days_left, dt_s = earnings_map[sym]
                    if days_left <= 14:
                        earn_html = f'<div style="margin-top:6px;"><span class="badge badge-earn-warn">⚠️ EARNINGS IN {days_left}d ({dt_s}) — WATCH CATALYST RISK</span></div>'

                with (left_c if idx % 2 == 0 else right_c):
                    st.markdown(
                        f'<div class="stock-card"><div style="display: flex; justify-content: space-between; align-items: flex-start;"><div><a href="?inspect={d["Ticker"]}" target="_self" class="ticker-link">📊 {d["Ticker"]}</a><span class="badge {d["TCT_Badge"]}" style="margin-left: 8px;">{d["TCT_Action"]}</span>{rs_html}{earn_html}<div style="font-size: 1.35rem; font-weight: 700; margin-top: 6px;">${d["Price"]:,.2f} <span style="font-size: 0.9rem; color: {"#15803d" if d["Change"]>=0 else "#b91c1c"}; font-weight: 700;">{arr_w}${abs(d["Change"]):.2f} ({d["Change_Pct"]:+.2f}%)</span></div></div><div style="text-align: right;"><div style="font-size: 1.6rem; font-weight: 700; color: #c5a059; font-family: 'Newsreader', serif;">{d["Score"]}</div><div style="font-size: 0.7rem; color: #71717a; text-transform: uppercase;">Score</div></div></div><div class="trade-ticket"><div style="display: flex; justify-content: space-between; font-weight: 700; color: #0f291e; margin-bottom: 4px;"><span>{d["TCT_Model"]}</span><span>📐 Reward/Risk: {d["R_Multiple"]:.1f}R</span></div><div style="display: flex; justify-content: space-between;"><span>🎯 <b>Buy Trigger:</b> ${d["BOS_Level"]:,.2f}</span><span>🟢 <b>Take Profit:</b> <span style="color:#15803d; font-weight:700;">${d["Target_Price"]:,.2f}</span> (+{d["Target_Pct"]:.1f}%)</span></div><div style="margin-top: 4px; display: flex; justify-content: space-between;"><span>🔴 <b>Stop-Loss:</b> <span style="color:#b91c1c; font-weight:700;">${d["Stop_Price"]:,.2f}</span> ({d["Stop_Pct"]:.1f}%)</span><span><b>0.5% Size:</b> {d["Shares_05Pct"]} shs (${d["Pos_Value"]:,.0f})</span></div></div><div style="display: flex; justify-content: space-between; align-items: center; margin-top: 8px; font-size: 0.78rem; color: #52525b;"><div>Day High: <b>${d["Day_High"]:,.2f}</b></div><div>Day Low: <b>${d["Day_Low"]:,.2f}</b></div><div>RSI(14/2): <b>{d["RSI"]:.0f}/{d["RSI2"]:.0f}</b></div><div>EMA 50: <b>${d["EMA50_Val"]:,.2f}</b></div></div><div style="font-size: 0.80rem; color: #475569; margin-top: 6px; font-style: italic;">"{d["TCT_Explain"]}"</div></div>',
                        unsafe_allow_html=True
                    )

    elif navigation == "Precious Metals, Crypto & Currency":
        st.markdown("<h1>Precious Metals, Crypto & Currency</h1>", unsafe_allow_html=True)
        METALS_GROUP = {"Gold Futures / Spot (USD/oz)": "GC=F", "Silver Futures / Spot (USD/oz)": "SI=F", "Copper Futures (USD/lb)": "HG=F", "Platinum Futures (USD/oz)": "PL=F", "SPDR Gold Trust ETF (GLD)": "GLD", "iShares Silver Trust ETF (SLV)": "SLV"}
        CRYPTO_GROUP = {"Bitcoin (BTC/USD)": "BTC-USD", "Ethereum (ETH/USD)": "ETH-USD", "XRP (XRP/USD)": "XRP-USD", "Solana (SOL/USD)": "SOL-USD"}
        FX_GROUP = {"US Dollar Index (DXY)": "DX-Y.NYB", "USD / JPY": "JPY=X", "EUR / USD": "EURUSD=X"}

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
                            f'<div class="stock-card"><div style="display:flex; justify-content:space-between; align-items:center;">'
                            f'<div style="font-size: 0.76rem; color: #71717a; text-transform: uppercase; font-weight: 700;">{title}</div>'
                            f'<span class="badge {m["TCT_Badge"]}">{m["TCT_Action"]}</span></div>'
                            f'<div style="display: flex; justify-content: space-between; align-items: baseline; margin-top: 6px;">'
                            f'<div><a href="?inspect={sym}" target="_self" class="ticker-link">📊 {sym}</a>'
                            f'<span style="font-size: 1.45rem; font-weight: 700; color: #0f291e; margin-left: 10px;">${m["Price"]:,.{decimals}f}</span>'
                            f'<span style="font-size: 0.92rem; color: {"#15803d" if m["Change"]>=0 else "#b91c1c"}; font-weight: 700; margin-left: 6px;">'
                            f'{arr_m}${abs(m["Change"]):.{decimals}f} ({m["Change_Pct"]:+.2f}%)</span></div>'
                            f'<span class="badge {m["Badge"]}">{m["State"]}</span></div>'
                            f'<div class="trade-ticket"><div style="display:flex; justify-content:space-between;">'
                            f'<span>🎯 <b>Buy Trigger:</b> ${m["BOS_Level"]:,.{decimals}f}</span><span>📐 <b>Reward/Risk:</b> {m["R_Multiple"]:.1f}R</span></div>'
                            f'<div style="display:flex; justify-content:space-between; margin-top:3px;">'
                            f'<span>🟢 <b>Target:</b> <b style="color:#15803d;">${m["Target_Price"]:,.{decimals}f}</b> (+{m["Target_Pct"]:.1f}%)</span>'
                            f'<span>🔴 <b>Stop:</b> <b style="color:#b91c1c;">${m["Stop_Price"]:,.{decimals}f}</b> ({m["Stop_Pct"]:.1f}%)</span></div></div>'
                            f'<div style="margin-top: 8px; font-size: 0.78rem; color: #52525b; display:flex; justify-content:space-between;">'
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
                    news_html = '<div class="scroll-news-box">' + "".join([f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{a.get("ticker", "ALERT")}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>' for a in pool_articles]) + '</div>'
                    st.markdown(news_html, unsafe_allow_html=True)
            with n_tab2:
                mcf_articles = fetch_metals_crypto_fx_news(max_items=settings["news_limit"], max_age_hours=settings["max_news_age_hours"])
                if mcf_articles:
                    c_html = '<div class="scroll-news-box">' + "".join([f'<div style="background: white; border: 1px solid #e7e2d9; border-radius: 8px; padding: 12px 16px; margin-bottom: 8px;"><div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: #71717a;"><span style="font-weight: 700; color: #0f291e;"><span class="ticker-news-badge">[{a["ticker"]}]</span> {a["publisher"]}<span class="age-badge">{a["age"]}</span></span><span>{a["date"]}</span></div><div style="font-weight: 600; font-size: 0.92rem; margin-top: 4px;"><a href="{a["link"]}" target="_blank" style="color: #0f291e; text-decoration: none;">{a["title"]}</a></div></div>' for a in mcf_articles]) + '</div>'
                    st.markdown(c_html, unsafe_allow_html=True)

        with n_col2:
            st.subheader("Upcoming Earnings Calendar")
            earnings_map = fetch_upcoming_earnings_map(tracked_symbols)
            if earnings_map:
                rows = sorted([{"Ticker": s, "Earnings Date": dt_str, "Countdown": f"{days_left}d" + (" ⚠️" if days_left <= 7 else ""), "_sort": days_left} for s, (days_left, dt_str) in earnings_map.items()], key=lambda x: x["_sort"])
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
            if st.button("🔔 Send Live 6-Playbook Briefing Ping to iPad Now", type="primary"):
                buys = [f"{k} ({v['TCT_Short_Sig']} @ ${v['Price']:.2f} -> Tgt ${v['Target_Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 0]
                tct_boxes = [f"{k} (BOS ${v['BOS_Level']:.2f})" for k, v in current_data.items() if v["TCT_Valid_Range"] and v["TCT_Priority"] != 0]
                sells = [f"{k} (${v['Price']:.2f})" for k, v in current_data.items() if v["TCT_Priority"] == 4]
                summary_msg = (
                    f"🟢 BUY / SWING TRIGGERS ({len(buys)}): {', '.join(buys[:6]) if buys else 'None'}\n"
                    f"📐 In TCT Bottom Box ({len(tct_boxes)}): {', '.join(tct_boxes[:6]) if tct_boxes else 'None'}\n"
                    f"🔴 Below 50 EMA / Avoid ({len(sells)}): {', '.join(sells[:8]) if sells else 'None'}"
                )
                ok, status_msg = send_ntfy_alert(summary_msg, "Daily Portfolio Briefing")
                st.success(f"✅ {status_msg}") if ok else st.error(f"❌ {status_msg}")

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
                st.download_button("📥 Download Full 6-Playbook Plan CSV", df_export.to_csv(index=False).encode("utf-8"), f"tct_swing_plan_{datetime.now().strftime('%Y%m%d_%H%M')}.csv", "text/csv", type="primary")
