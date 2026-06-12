import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Stock Viewer",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif; box-sizing: border-box; }
html, body, [data-testid="stAppViewContainer"] { background: #000; color: #f5f5f7; }
[data-testid="stHeader"] { display: none; }
[data-testid="stSidebar"] { display: none; }
.block-container { padding: 16px 16px 60px !important; max-width: 900px; margin: auto; }
.stTextInput input {
    background: #1c1c1e !important; border: 1px solid #3a3a3c !important;
    border-radius: 12px !important; color: #f5f5f7 !important;
    font-size: 1rem !important; padding: 12px 16px !important;
}
.stTextInput input:focus { border-color: #0a84ff !important; outline: none !important; }
.metric-card {
    background: #1c1c1e; border-radius: 12px;
    padding: 14px 16px; margin-bottom: 8px;
}
.metric-label { font-size: 0.65rem; color: #8e8e93; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 4px; }
.metric-value { font-size: 1.1rem; font-weight: 600; color: #f5f5f7; }
.metric-value.green { color: #30d158; }
.metric-value.red { color: #ff453a; }
.metric-value.blue { color: #0a84ff; }
.metric-value.orange { color: #ff9f0a; }
.section-header { font-size: 0.75rem; font-weight: 700; color: #8e8e93;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin: 24px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #2c2c2e; }
.price-main { font-size: 2.6rem; font-weight: 700; line-height: 1; }
.company-name { font-size: 1rem; color: #8e8e93; margin-bottom: 4px; }
.ticker-badge { display: inline-block; background: #2c2c2e;
    border-radius: 6px; padding: 2px 8px; font-size: 0.75rem;
    font-weight: 600; color: #8e8e93; margin-right: 6px; }
.search-result {
    background: #1c1c1e; border: 1px solid #2c2c2e;
    border-radius: 10px; padding: 10px 14px; margin-bottom: 6px;
    cursor: pointer; transition: border-color 0.15s;
}
.search-result:hover { border-color: #0a84ff; }
.search-result-name { font-size: 0.9rem; font-weight: 600; color: #f5f5f7; }
.search-result-ticker { font-size: 0.75rem; color: #8e8e93; margin-top: 2px; }
.stButton button { background: #2c2c2e !important; color: #f5f5f7 !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.8rem !important; padding: 6px 12px !important; font-weight: 500 !important; }
.stButton button:hover { background: #3a3a3c !important; }
[data-testid="stTabs"] button { color: #8e8e93 !important; font-size: 0.85rem !important; font-weight: 500 !important; }
[data-testid="stTabs"] button[aria-selected="true"] { color: #f5f5f7 !important; border-bottom: 2px solid #0a84ff !important; }
footer { display: none !important; }
#MainMenu { display: none !important; }
.stDeployButton { display: none !important; }
[data-testid="stDataFrame"] { background: #1c1c1e !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────
def fmt_num(val, decimals=2, suffix=""):
    if val is None: return "N/A"
    try:
        v = float(val)
        if v != v: return "N/A"
        return f"{v:,.{decimals}f}{suffix}"
    except: return "N/A"

def fmt_pct(val, decimals=1):
    if val is None: return "N/A"
    try:
        v = float(val)
        if v != v: return "N/A"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except: return "N/A"

def fmt_large(val):
    if val is None: return "N/A"
    try:
        v = float(val)
        if v != v: return "N/A"
        if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
        if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
        if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
        return f"{v:,.0f}"
    except: return "N/A"

def to_pct(val):
    if val is None: return None
    try:
        v = float(val)
        if v != v: return None
        if abs(v) <= 5: return round(v * 100, 2)
        return round(v, 2)
    except: return None

def color_class(val):
    if val is None: return ""
    try:
        v = float(val)
        return "green" if v > 0 else "red" if v < 0 else ""
    except: return ""

def metric_card(label, value, color=""):
    c = f' {color}' if color else ''
    st.markdown(f"""<div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value{c}">{value}</div>
    </div>""", unsafe_allow_html=True)


# ── Data fetching (no cache on yfinance objects) ──────────────────────────────
@st.cache_data(ttl=300)
def fetch_info(ticker: str) -> dict:
    try:
        return yf.Ticker(ticker).info or {}
    except: return {}

@st.cache_data(ttl=300)
def fetch_hist(ticker: str, period: str) -> pd.DataFrame:
    try:
        return yf.Ticker(ticker).history(period=period)
    except: return pd.DataFrame()

@st.cache_data(ttl=300)
def fetch_financials(ticker: str) -> dict:
    try:
        t = yf.Ticker(ticker)
        return {
            "income":    t.financials,
            "balance":   t.balance_sheet,
            "cashflow":  t.cashflow,
        }
    except: return {}

@st.cache_data(ttl=600)
def search_tickers(query: str) -> list:
    try:
        results = yf.Search(query, max_results=8)
        quotes = results.quotes if hasattr(results, 'quotes') else []
        return [
            {
                "symbol":    q.get("symbol", ""),
                "shortname": q.get("shortname") or q.get("longname") or q.get("symbol", ""),
                "exchange":  q.get("exchange", ""),
                "type":      q.get("quoteType", ""),
            }
            for q in quotes if q.get("symbol")
        ]
    except: return []


# ── App ───────────────────────────────────────────────────────────────────────
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.markdown("## 📈 Stock Viewer")

# Session state
if "ticker" not in st.session_state:
    st.session_state.ticker = ""
if "period" not in st.session_state:
    st.session_state.period = "1y"

# ── Search ────────────────────────────────────────────────────────────────────
search_query = st.text_input(
    "", placeholder="Cerca per ticker o nome azienda (es: Apple, ENI, AAPL, ENI.MI...)",
    label_visibility="collapsed", key="search_input"
).strip()

# Show search results if typing a name (not a ticker pattern)
if search_query and len(search_query) >= 2:
    is_likely_ticker = (
        search_query.replace(".", "").replace("-", "").isupper() and
        len(search_query) <= 8
    )

    if not is_likely_ticker:
        # Search by name
        with st.spinner("Ricerca..."):
            results = search_tickers(search_query)
        if results:
            st.markdown("<div style='margin-bottom:8px;font-size:0.8rem;color:#8e8e93'>Seleziona un titolo:</div>", unsafe_allow_html=True)
            cols = st.columns(2)
            for i, r in enumerate(results[:6]):
                with cols[i % 2]:
                    label = f"**{r['symbol']}** — {r['shortname'][:35]}"
                    if r.get('exchange'):
                        label += f" _{r['exchange']}_"
                    if st.button(label, key=f"res_{i}_{r['symbol']}"):
                        st.session_state.ticker = r['symbol']
                        st.rerun()
        else:
            st.caption("Nessun risultato — prova il ticker diretto (es: AAPL)")
    else:
        # Direct ticker input
        st.session_state.ticker = search_query.upper()

# Period selector
ticker = st.session_state.ticker
if ticker:
    p_cols = st.columns(7)
    periods = {"1S": "5d", "1M": "1mo", "3M": "3mo",
               "6M": "6mo", "1A": "1y", "2A": "2y", "5A": "5y"}
    for i, (label, val) in enumerate(periods.items()):
        with p_cols[i]:
            if st.button(label, key=f"p_{val}"):
                st.session_state.period = val
                st.rerun()

# ── Load & display ────────────────────────────────────────────────────────────
if ticker:
    info = fetch_info(ticker)
    hist = fetch_hist(ticker, st.session_state.period)

    if hist.empty:
        st.error(f"❌ Nessun dato trovato per **{ticker}** — verifica il ticker e riprova.")
        st.stop()

    # ── Price header ──────────────────────────────────────────────────────────
    cur_price = (info.get("currentPrice") or info.get("regularMarketPrice") or
                 float(hist["Close"].iloc[-1]))
    prev_close = (info.get("previousClose") or info.get("regularMarketPreviousClose") or
                  float(hist["Close"].iloc[-2]) if len(hist) > 1 else cur_price)
    change = cur_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0
    currency = info.get("currency", "USD")
    name = info.get("longName") or info.get("shortName") or ticker
    exchange = info.get("exchange", "")
    sector = info.get("sector", "")
    industry = info.get("industry", "")
    change_color = "#30d158" if change >= 0 else "#ff453a"
    sign = "+" if change >= 0 else ""

    st.markdown(f"""
    <div class="company-name">
        <span class="ticker-badge">{ticker}</span>
        {'<span class="ticker-badge">' + exchange + '</span>' if exchange else ''}
        {name}
    </div>
    <div class="price-main">{fmt_num(cur_price, 2)} <span style='font-size:1rem;color:#8e8e93'>{currency}</span></div>
    <div style="font-size:1rem;font-weight:500;color:{change_color};margin-top:4px">
        {sign}{fmt_num(change, 2)} ({sign}{fmt_num(change_pct, 2)}%)
        <span style="color:#8e8e93;font-size:0.8rem"> oggi</span>
    </div>
    {'<div style="font-size:0.8rem;color:#8e8e93;margin-top:4px">' + sector + (' · ' + industry if industry else '') + '</div>' if sector else ''}
    <div style="height:16px"></div>
    """, unsafe_allow_html=True)

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        increasing_line_color="#30d158", decreasing_line_color="#ff453a",
        name="Prezzo"
    ))
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=["#30d158" if c >= o else "#ff453a"
                      for c, o in zip(hist["Close"], hist["Open"])],
        opacity=0.25, name="Volume", yaxis="y2"
    ))
    fig.update_layout(
        paper_bgcolor="#000", plot_bgcolor="#000",
        margin=dict(l=0, r=0, t=0, b=0), height=300,
        xaxis=dict(showgrid=False, color="#8e8e93", rangeslider_visible=False),
        yaxis=dict(showgrid=True, gridcolor="#1c1c1e", color="#8e8e93", side="right"),
        yaxis2=dict(overlaying="y", side="left", showgrid=False,
                    showticklabels=False, range=[0, hist["Volume"].max() * 5]),
        legend=dict(x=0, y=1, bgcolor="rgba(0,0,0,0)", font_color="#8e8e93"),
        font_color="#8e8e93",
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs(["Panoramica", "Fondamentali", "Tecnica", "Bilanci"])

    # ── TAB 1: Panoramica ─────────────────────────────────────────────────────
    with tab1:
        st.markdown("<div class='section-header'>Prezzi</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Prezzo attuale", f"{fmt_num(cur_price, 2)} {currency}")
            metric_card("Apertura", f"{fmt_num(info.get('open') or info.get('regularMarketOpen'), 2)} {currency}")
            metric_card("Chiusura precedente", f"{fmt_num(prev_close, 2)} {currency}")
        with c2:
            metric_card("Massimo giornaliero", f"{fmt_num(info.get('dayHigh') or info.get('regularMarketDayHigh'), 2)} {currency}")
            metric_card("Minimo giornaliero", f"{fmt_num(info.get('dayLow') or info.get('regularMarketDayLow'), 2)} {currency}")
            metric_card("Volume oggi", fmt_large(info.get('volume') or info.get('regularMarketVolume')))
        with c3:
            metric_card("Max 52 settimane", f"{fmt_num(info.get('fiftyTwoWeekHigh'), 2)} {currency}")
            metric_card("Min 52 settimane", f"{fmt_num(info.get('fiftyTwoWeekLow'), 2)} {currency}")
            metric_card("Volume medio (3M)", fmt_large(info.get('averageVolume') or info.get('averageVolume3Month')))

        st.markdown("<div class='section-header'>Azienda</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Market Cap", fmt_large(info.get('marketCap')))
            metric_card("Enterprise Value", fmt_large(info.get('enterpriseValue')))
        with c2:
            metric_card("Paese", info.get('country') or "N/A")
            metric_card("Dipendenti", fmt_large(info.get('fullTimeEmployees')))
        with c3:
            metric_card("Settore", info.get('sector') or "N/A")
            metric_card("Industria", info.get('industry') or "N/A")

        desc = info.get('longBusinessSummary')
        if desc:
            st.markdown("<div class='section-header'>Descrizione</div>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:#8e8e93;font-size:0.85rem;line-height:1.6'>{desc[:600]}{'...' if len(desc)>600 else ''}</p>", unsafe_allow_html=True)

    # ── TAB 2: Fondamentali ───────────────────────────────────────────────────
    with tab2:
        st.markdown("<div class='section-header'>Valutazione</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            pe = info.get('trailingPE')
            metric_card("P/E (trailing)", fmt_num(pe, 1) if pe and pe > 0 else "N/A")
            metric_card("P/E (forward)", fmt_num(info.get('forwardPE'), 1))
            metric_card("PEG Ratio", fmt_num(info.get('pegRatio'), 2))
        with c2:
            metric_card("P/B Ratio", fmt_num(info.get('priceToBook'), 2))
            metric_card("P/S Ratio", fmt_num(info.get('priceToSalesTrailing12Months'), 2))
            metric_card("EV/EBITDA", fmt_num(info.get('enterpriseToEbitda'), 1))
        with c3:
            metric_card("EV/Revenue", fmt_num(info.get('enterpriseToRevenue'), 2))
            metric_card("Market Cap", fmt_large(info.get('marketCap')))
            metric_card("Enterprise Value", fmt_large(info.get('enterpriseValue')))

        st.markdown("<div class='section-header'>Redditività</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        pm = to_pct(info.get('profitMargins'))
        gm = to_pct(info.get('grossMargins'))
        om = to_pct(info.get('operatingMargins'))
        roe = to_pct(info.get('returnOnEquity'))
        roa = to_pct(info.get('returnOnAssets'))
        rg = to_pct(info.get('revenueGrowth'))
        eg = to_pct(info.get('earningsGrowth'))
        with c1:
            metric_card("Margine netto", fmt_pct(pm) if pm else "N/A", color_class(pm))
            metric_card("Margine lordo", fmt_pct(gm) if gm else "N/A", color_class(gm))
            metric_card("Margine operativo", fmt_pct(om) if om else "N/A", color_class(om))
        with c2:
            metric_card("ROE", fmt_pct(roe) if roe else "N/A", color_class(roe))
            metric_card("ROA", fmt_pct(roa) if roa else "N/A", color_class(roa))
            metric_card("Revenue (TTM)", fmt_large(info.get('totalRevenue')))
        with c3:
            metric_card("Crescita ricavi (YoY)", fmt_pct(rg) if rg else "N/A", color_class(rg))
            metric_card("Crescita utili (YoY)", fmt_pct(eg) if eg else "N/A", color_class(eg))
            metric_card("EBITDA", fmt_large(info.get('ebitda')))

        st.markdown("<div class='section-header'>Struttura Finanziaria</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Debito totale", fmt_large(info.get('totalDebt')))
            metric_card("Cash & equivalenti", fmt_large(info.get('totalCash')))
            metric_card("Free Cash Flow", fmt_large(info.get('freeCashflow')))
        with c2:
            de = info.get('debtToEquity')
            metric_card("Debt/Equity", fmt_num(de/100 if de and de > 10 else de, 2) if de else "N/A")
            metric_card("Current Ratio", fmt_num(info.get('currentRatio'), 2))
            metric_card("Quick Ratio", fmt_num(info.get('quickRatio'), 2))
        with c3:
            metric_card("Operating Cash Flow", fmt_large(info.get('operatingCashflow')))
            metric_card("Cash per share", fmt_num(info.get('totalCashPerShare'), 2))
            metric_card("Book Value/share", fmt_num(info.get('bookValue'), 2))

        st.markdown("<div class='section-header'>Dividendo</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        dy = to_pct(info.get('dividendYield') or info.get('trailingAnnualDividendYield'))
        with c1:
            metric_card("Dividend Yield", fmt_pct(dy) if dy else "N/A", "blue" if dy and dy > 0 else "")
            metric_card("Dividendo annuo", fmt_num(info.get('dividendRate') or info.get('trailingAnnualDividendRate'), 3))
        with c2:
            metric_card("Payout Ratio", fmt_pct(to_pct(info.get('payoutRatio'))))
            metric_card("Ex-Dividend Date", str(info.get('exDividendDate', 'N/A'))[:10])
        with c3:
            metric_card("5Y Avg Yield", fmt_pct(to_pct(info.get('fiveYearAvgDividendYield'))))
            metric_card("EPS (trailing)", fmt_num(info.get('trailingEps'), 2))

        st.markdown("<div class='section-header'>Per Azione</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("EPS (trailing)", fmt_num(info.get('trailingEps'), 2))
            metric_card("EPS (forward)", fmt_num(info.get('forwardEps'), 2))
        with c2:
            metric_card("Revenue/share", fmt_num(info.get('revenuePerShare'), 2))
            metric_card("Book Value/share", fmt_num(info.get('bookValue'), 2))
        with c3:
            metric_card("Shares outstanding", fmt_large(info.get('sharesOutstanding')))
            metric_card("Float", fmt_large(info.get('floatShares')))

    # ── TAB 3: Tecnica ────────────────────────────────────────────────────────
    with tab3:
        close = hist["Close"].astype(float)
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rsi = (100 - (100 / (1 + gain / loss))).iloc[-1]
        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        macd_sig_line = macd_line.ewm(span=9).mean()
        macd_val = macd_line.iloc[-1]
        macd_sig_val = macd_sig_line.iloc[-1]
        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_up = (bb_mid + 2 * bb_std).iloc[-1]
        bb_lo = (bb_mid - 2 * bb_std).iloc[-1]
        atr = float((hist["High"] - hist["Low"]).tail(14).mean())
        vol_20 = float(close.pct_change().rolling(20).std().iloc[-1] * 100)

        def vs(ind):
            if not ind or ind != ind: return ""
            d = (cur_price - ind) / ind * 100
            c = "#30d158" if d >= 0 else "#ff453a"
            s = "+" if d >= 0 else ""
            return f" <small style='color:{c}'>{s}{d:.1f}%</small>"

        st.markdown("<div class='section-header'>Medie Mobili</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1: metric_card(f"MA20{vs(ma20)}", f"{fmt_num(ma20, 2)} {currency}", "green" if cur_price > ma20 else "red")
        with c2: metric_card(f"MA50{vs(ma50)}", f"{fmt_num(ma50, 2)} {currency}", "green" if cur_price > ma50 else "red")
        with c3: metric_card(f"MA200{vs(ma200)}", f"{fmt_num(ma200, 2)} {currency}", "green" if cur_price > ma200 else "red")

        st.markdown("<div class='section-header'>Oscillatori</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        if rsi >= 70: rl, rc = "Ipercomprato", "red"
        elif rsi <= 30: rl, rc = "Ipervenduto", "green"
        elif rsi >= 55: rl, rc = "Forza", "blue"
        elif rsi <= 45: rl, rc = "Debolezza", "orange"
        else: rl, rc = "Neutro", ""
        with c1: metric_card(f"RSI (14) — {rl}", fmt_num(rsi, 1), rc)
        with c2: metric_card(f"MACD {'▲' if macd_val > macd_sig_val else '▼'}", fmt_num(macd_val, 4), "green" if macd_val > macd_sig_val else "red")
        with c3: metric_card("MACD Signal", fmt_num(macd_sig_val, 4))

        st.markdown("<div class='section-header'>Volatilità & Bande di Bollinger</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        bb_pos = (cur_price - bb_lo) / (bb_up - bb_lo) * 100 if bb_up != bb_lo else 50
        with c1:
            metric_card("BB Superiore", f"{fmt_num(bb_up, 2)} {currency}")
            metric_card("BB Inferiore", f"{fmt_num(bb_lo, 2)} {currency}")
        with c2:
            metric_card("Posizione banda", f"{fmt_num(bb_pos, 0)}%", "red" if bb_pos > 80 else "green" if bb_pos < 20 else "")
            metric_card("ATR (14)", f"{fmt_num(atr, 2)} {currency}")
        with c3:
            metric_card("Volatilità 20gg", fmt_pct(vol_20))
            metric_card("Beta", fmt_num(info.get('beta'), 2))

        st.markdown("<div class='section-header'>Supporto & Resistenza (3 mesi)</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        recent = hist.tail(63)
        with c1: metric_card("Supporto (min 3M)", f"{fmt_num(float(recent['Low'].min()), 2)} {currency}", "green")
        with c2: metric_card("Resistenza (max 3M)", f"{fmt_num(float(recent['High'].max()), 2)} {currency}", "red")

        st.markdown("<div class='section-header'>Short Interest</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        sp = info.get('shortPercentOfFloat')
        sp_val = (sp * 100) if sp and sp < 1 else sp
        with c1: metric_card("Short % Float", fmt_pct(sp_val) if sp_val else "N/A", "red" if sp_val and sp_val > 15 else "")
        with c2: metric_card("Short Ratio (days)", fmt_num(info.get('shortRatio'), 1))

    # ── TAB 4: Bilanci ────────────────────────────────────────────────────────
    with tab4:
        fins = fetch_financials(ticker)

        def show_df(df, title):
            if df is None or df.empty:
                st.caption(f"{title}: non disponibile")
                return
            st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
            df_d = df.copy()
            for col in df_d.columns:
                df_d[col] = df_d[col].apply(
                    lambda x: f"{x/1e9:.2f}B" if pd.notna(x) and abs(x) >= 1e9 else
                              f"{x/1e6:.1f}M" if pd.notna(x) and abs(x) >= 1e6 else
                              (f"{x:.0f}" if pd.notna(x) else "N/A")
                )
            st.dataframe(df_d.head(20), use_container_width=True)

        show_df(fins.get("income"), "Conto Economico (annuale)")
        show_df(fins.get("balance"), "Stato Patrimoniale")
        show_df(fins.get("cashflow"), "Cash Flow")

else:
    # Empty state
    st.markdown("""
    <div style='text-align:center;padding:60px 20px;color:#48484a'>
        <div style='font-size:3rem'>📈</div>
        <div style='font-size:1.1rem;font-weight:600;margin-top:12px;color:#636366'>Cerca un'azione</div>
        <div style='font-size:0.85rem;margin-top:8px;color:#48484a'>
            Scrivi il nome dell'azienda o il ticker diretto<br><br>
            <span style='color:#3a3a3c'>AAPL · Apple · ENI.MI · Volkswagen · SIE.DE · 9984.T · BNP.PA</span>
        </div>
    </div>
    """, unsafe_allow_html=True)
