import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

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
[data-testid="stAppViewContainer"] { padding: 0; }
[data-testid="stHeader"] { display: none; }
[data-testid="stSidebar"] { display: none; }
.block-container { padding: 16px 16px 40px !important; max-width: 900px; margin: auto; }

/* Search */
.stTextInput input {
    background: #1c1c1e !important; border: 1px solid #3a3a3c !important;
    border-radius: 12px !important; color: #f5f5f7 !important;
    font-size: 1rem !important; padding: 12px 16px !important;
}
.stTextInput input:focus { border-color: #0a84ff !important; }

/* Metric cards */
.metric-card {
    background: #1c1c1e; border-radius: 12px;
    padding: 14px 16px; margin-bottom: 8px;
}
.metric-label {
    font-size: 0.65rem; color: #8e8e93;
    font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 4px;
}
.metric-value {
    font-size: 1.1rem; font-weight: 600; color: #f5f5f7;
}
.metric-value.green { color: #30d158; }
.metric-value.red { color: #ff453a; }
.metric-value.blue { color: #0a84ff; }
.metric-value.orange { color: #ff9f0a; }

/* Section headers */
.section-header {
    font-size: 0.75rem; font-weight: 700; color: #8e8e93;
    text-transform: uppercase; letter-spacing: 0.1em;
    margin: 24px 0 12px; padding-bottom: 6px;
    border-bottom: 1px solid #2c2c2e;
}

/* Price display */
.price-main { font-size: 2.8rem; font-weight: 700; line-height: 1; }
.price-change { font-size: 1rem; font-weight: 500; margin-top: 4px; }
.company-name { font-size: 1rem; color: #8e8e93; margin-bottom: 4px; }
.ticker-badge {
    display: inline-block; background: #2c2c2e;
    border-radius: 6px; padding: 2px 8px;
    font-size: 0.75rem; font-weight: 600; color: #8e8e93;
    margin-right: 6px;
}

/* Period buttons */
.stButton button {
    background: #2c2c2e !important; color: #f5f5f7 !important;
    border: none !important; border-radius: 8px !important;
    font-size: 0.8rem !important; padding: 6px 12px !important;
    font-weight: 500 !important;
}
.stButton button:hover { background: #3a3a3c !important; }

/* Tabs */
[data-testid="stTabs"] button {
    color: #8e8e93 !important; font-size: 0.85rem !important;
    font-weight: 500 !important;
}
[data-testid="stTabs"] button[aria-selected="true"] {
    color: #f5f5f7 !important; border-bottom: 2px solid #0a84ff !important;
}
[data-testid="stTabs"] { border-bottom: 1px solid #2c2c2e !important; }

/* Divider */
hr { border-color: #2c2c2e !important; margin: 16px 0 !important; }

/* Hide streamlit default elements */
footer { display: none !important; }
.stDeployButton { display: none !important; }
#MainMenu { display: none !important; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_num(val, decimals=2, suffix=""):
    """Format number safely."""
    if val is None: return "N/A"
    try:
        v = float(val)
        if v != v: return "N/A"  # NaN
        return f"{v:,.{decimals}f}{suffix}"
    except: return "N/A"

def fmt_pct(val, decimals=2):
    if val is None: return "N/A"
    try:
        v = float(val)
        if v != v: return "N/A"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.{decimals}f}%"
    except: return "N/A"

def fmt_large(val):
    """Format large numbers (market cap etc)."""
    if val is None: return "N/A"
    try:
        v = float(val)
        if v >= 1e12: return f"{v/1e12:.2f}T"
        if v >= 1e9: return f"{v/1e9:.2f}B"
        if v >= 1e6: return f"{v/1e6:.2f}M"
        return f"{v:,.0f}"
    except: return "N/A"

def color_class(val, positive_good=True):
    """Return CSS class based on value sign."""
    if val is None: return ""
    try:
        v = float(val)
        if v > 0: return "green" if positive_good else "red"
        if v < 0: return "red" if positive_good else "green"
        return ""
    except: return ""

def metric_card(label, value, color=""):
    color_attr = f' {color}' if color else ''
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">{label}</div>
        <div class="metric-value{color_attr}">{value}</div>
    </div>
    """, unsafe_allow_html=True)

def safe_pct(val):
    """Yahoo returns many fields as decimals (0.15 = 15%) — convert."""
    if val is None: return None
    try:
        v = float(val)
        if v != v: return None
        return v
    except: return None

def to_pct(val):
    """Convert decimal to percentage if needed."""
    if val is None: return None
    try:
        v = float(val)
        if abs(v) <= 5:  # likely decimal (0.15 → 15%)
            return round(v * 100, 2)
        return round(v, 2)  # already percentage
    except: return None


# ── Fetch data ────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def fetch_stock(ticker: str, period: str = "1y"):
    """Fetch all data for a ticker."""
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period)
        if hist.empty:
            return None, None, None, "Nessun dato trovato per questo ticker"
        info = stock.info or {}
        return stock, hist, info, None
    except Exception as e:
        return None, None, None, str(e)

@st.cache_data(ttl=300)
def fetch_financials(ticker: str):
    """Fetch financial statements."""
    try:
        stock = yf.Ticker(ticker)
        return {
            "income": stock.financials,
            "balance": stock.balance_sheet,
            "cashflow": stock.cashflow,
            "quarterly": stock.quarterly_financials,
        }
    except:
        return {}

@st.cache_data(ttl=3600)
def search_tickers(query: str):
    """Search for tickers by name."""
    try:
        results = yf.Search(query, max_results=8)
        return results.quotes if hasattr(results, 'quotes') else []
    except:
        return []


# ── Main app ──────────────────────────────────────────────────────────────────

# Header
st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
st.markdown("## 📈 Stock Viewer")

# Search
col_search, col_btn = st.columns([5, 1])
with col_search:
    ticker_input = st.text_input(
        "", placeholder="Cerca ticker o nome (es. AAPL, ENI.MI, MSFT...)",
        label_visibility="collapsed",
        key="ticker_search"
    ).strip().upper()

# Period selector
if ticker_input:
    p_cols = st.columns(7)
    periods = {"1S": "5d", "1M": "1mo", "3M": "3mo",
               "6M": "6mo", "1A": "1y", "2A": "2y", "5A": "5y"}
    if "period" not in st.session_state:
        st.session_state.period = "1y"
    for i, (label, val) in enumerate(periods.items()):
        with p_cols[i]:
            if st.button(label, key=f"p_{val}"):
                st.session_state.period = val

# ── Load data ─────────────────────────────────────────────────────────────────
if ticker_input:
    stock, hist, info, error = fetch_stock(ticker_input, st.session_state.get("period", "1y"))

    if error:
        st.error(f"❌ {error}")
        st.stop()

    # ── Price header ──────────────────────────────────────────────────────────
    cur_price = info.get("currentPrice") or info.get("regularMarketPrice") or float(hist["Close"].iloc[-1])
    prev_close = info.get("previousClose") or float(hist["Close"].iloc[-2]) if len(hist) > 1 else cur_price
    change = cur_price - prev_close
    change_pct = (change / prev_close * 100) if prev_close else 0
    currency = info.get("currency", "USD")
    name = info.get("longName") or info.get("shortName") or ticker_input
    exchange = info.get("exchange", "")
    sector = info.get("sector", "")
    industry = info.get("industry", "")

    change_color = "#30d158" if change >= 0 else "#ff453a"
    sign = "+" if change >= 0 else ""

    st.markdown(f"""
    <div class="company-name">
        <span class="ticker-badge">{ticker_input}</span>
        {'<span class="ticker-badge">' + exchange + '</span>' if exchange else ''}
        {name}
    </div>
    <div class="price-main">{fmt_num(cur_price, 2)} <span style='font-size:1rem;color:#8e8e93'>{currency}</span></div>
    <div class="price-change" style="color:{change_color}">
        {sign}{fmt_num(change, 2)} ({sign}{fmt_num(change_pct, 2)}%)
        <span style="color:#8e8e93;font-size:0.8rem"> oggi</span>
    </div>
    {'<div style="font-size:0.8rem;color:#8e8e93;margin-top:4px">' + sector + (' · ' + industry if industry else '') + '</div>' if sector else ''}
    """, unsafe_allow_html=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Chart ─────────────────────────────────────────────────────────────────
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=hist.index, open=hist["Open"], high=hist["High"],
        low=hist["Low"], close=hist["Close"],
        increasing_line_color="#30d158", decreasing_line_color="#ff453a",
        name="Prezzo"
    ))
    # Volume bars
    fig.add_trace(go.Bar(
        x=hist.index, y=hist["Volume"],
        marker_color=["#30d158" if c >= o else "#ff453a"
                      for c, o in zip(hist["Close"], hist["Open"])],
        opacity=0.3, name="Volume", yaxis="y2"
    ))
    fig.update_layout(
        paper_bgcolor="#000", plot_bgcolor="#000",
        margin=dict(l=0, r=0, t=0, b=0), height=320,
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
            metric_card("Volume", fmt_large(info.get('volume') or info.get('regularMarketVolume')))
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
            metric_card("Dipendenti", fmt_large(info.get('fullTimeEmployees')))
            metric_card("Paese", info.get('country') or "N/A")
        with c3:
            metric_card("Settore", info.get('sector') or "N/A")
            metric_card("Industria", info.get('industry') or "N/A")

        # Description
        desc = info.get('longBusinessSummary') or info.get('description')
        if desc:
            st.markdown("<div class='section-header'>Descrizione</div>", unsafe_allow_html=True)
            st.markdown(f"<p style='color:#8e8e93;font-size:0.85rem;line-height:1.6'>{desc[:500]}{'...' if len(desc)>500 else ''}</p>", unsafe_allow_html=True)

    # ── TAB 2: Fondamentali ───────────────────────────────────────────────────
    with tab2:
        st.markdown("<div class='section-header'>Valutazione</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)

        pe = info.get('trailingPE') or info.get('forwardPE')
        pb = info.get('priceToBook')
        ps = info.get('priceToSalesTrailing12Months')
        ev_ebitda = info.get('enterpriseToEbitda')
        ev_revenue = info.get('enterpriseToRevenue')
        peg = info.get('pegRatio')

        with c1:
            metric_card("P/E (trailing)", fmt_num(pe, 1) if pe and pe > 0 else "N/A")
            metric_card("P/E (forward)", fmt_num(info.get('forwardPE'), 1))
            metric_card("PEG Ratio", fmt_num(peg, 2))
        with c2:
            metric_card("P/B Ratio", fmt_num(pb, 2))
            metric_card("P/S Ratio", fmt_num(ps, 2))
            metric_card("EV/EBITDA", fmt_num(ev_ebitda, 1))
        with c3:
            metric_card("EV/Revenue", fmt_num(ev_revenue, 2))
            metric_card("Enterprise Value", fmt_large(info.get('enterpriseValue')))
            metric_card("Market Cap", fmt_large(info.get('marketCap')))

        st.markdown("<div class='section-header'>Redditività</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)

        profit_margin = info.get('profitMargins')
        gross_margin = info.get('grossMargins')
        op_margin = info.get('operatingMargins')
        roe = info.get('returnOnEquity')
        roa = info.get('returnOnAssets')
        rev_growth = info.get('revenueGrowth')
        earn_growth = info.get('earningsGrowth')

        with c1:
            pm_val = to_pct(profit_margin)
            metric_card("Margine netto", fmt_pct(pm_val, 1) if pm_val else "N/A",
                       color_class(pm_val))
            gm_val = to_pct(gross_margin)
            metric_card("Margine lordo", fmt_pct(gm_val, 1) if gm_val else "N/A",
                       color_class(gm_val))
            om_val = to_pct(op_margin)
            metric_card("Margine operativo", fmt_pct(om_val, 1) if om_val else "N/A",
                       color_class(om_val))
        with c2:
            roe_val = to_pct(roe)
            metric_card("ROE", fmt_pct(roe_val, 1) if roe_val else "N/A",
                       color_class(roe_val))
            roa_val = to_pct(roa)
            metric_card("ROA", fmt_pct(roa_val, 1) if roa_val else "N/A",
                       color_class(roa_val))
            rg_val = to_pct(rev_growth)
            metric_card("Crescita ricavi (YoY)", fmt_pct(rg_val, 1) if rg_val else "N/A",
                       color_class(rg_val))
        with c3:
            eg_val = to_pct(earn_growth)
            metric_card("Crescita utili (YoY)", fmt_pct(eg_val, 1) if eg_val else "N/A",
                       color_class(eg_val))
            metric_card("Revenue (TTM)", fmt_large(info.get('totalRevenue')))
            metric_card("EBITDA", fmt_large(info.get('ebitda')))

        st.markdown("<div class='section-header'>Struttura Finanziaria</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("Debito totale", fmt_large(info.get('totalDebt')))
            metric_card("Cash & equivalenti", fmt_large(info.get('totalCash')))
            de = info.get('debtToEquity')
            metric_card("Debt/Equity", fmt_num(de/100 if de and de > 10 else de, 2) if de else "N/A")
        with c2:
            metric_card("Current Ratio", fmt_num(info.get('currentRatio'), 2))
            metric_card("Quick Ratio", fmt_num(info.get('quickRatio'), 2))
            metric_card("Cash per share", fmt_num(info.get('totalCashPerShare'), 2))
        with c3:
            metric_card("Free Cash Flow", fmt_large(info.get('freeCashflow')))
            metric_card("Operating Cash Flow", fmt_large(info.get('operatingCashflow')))
            metric_card("Book Value/share", fmt_num(info.get('bookValue'), 2))

        st.markdown("<div class='section-header'>Dividendo</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        dy = to_pct(info.get('dividendYield') or info.get('trailingAnnualDividendYield'))
        with c1:
            metric_card("Dividend Yield", fmt_pct(dy, 2) if dy else "N/A",
                       "blue" if dy and dy > 0 else "")
            metric_card("Dividendo annuo", fmt_num(info.get('dividendRate') or info.get('trailingAnnualDividendRate'), 2))
        with c2:
            metric_card("Payout Ratio", fmt_pct(to_pct(info.get('payoutRatio')), 1))
            metric_card("Ex-Dividend Date", str(info.get('exDividendDate', 'N/A'))[:10])
        with c3:
            metric_card("5Y Avg Yield", fmt_pct(to_pct(info.get('fiveYearAvgDividendYield')), 2))
            metric_card("Ultima cedola", fmt_num(info.get('lastDividendValue'), 4))

        st.markdown("<div class='section-header'>Per Azione (EPS)</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            metric_card("EPS (trailing)", fmt_num(info.get('trailingEps'), 2))
            metric_card("EPS (forward)", fmt_num(info.get('forwardEps'), 2))
        with c2:
            metric_card("EPS crescita (5Y)", fmt_pct(to_pct(info.get('earningsQuarterlyGrowth')), 1))
            metric_card("Revenue/share", fmt_num(info.get('revenuePerShare'), 2))
        with c3:
            metric_card("Shares outstanding", fmt_large(info.get('sharesOutstanding')))
            metric_card("Float", fmt_large(info.get('floatShares')))

    # ── TAB 3: Tecnica ────────────────────────────────────────────────────────
    with tab3:
        # Calculate indicators
        close = hist["Close"].astype(float)
        ma20 = close.rolling(20).mean().iloc[-1]
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1]

        delta = close.diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = (-delta.clip(upper=0)).rolling(14).mean()
        rs = gain / loss
        rsi_series = 100 - (100 / (1 + rs))
        rsi = rsi_series.iloc[-1]

        ema12 = close.ewm(span=12).mean()
        ema26 = close.ewm(span=26).mean()
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9).mean()
        macd_val = macd_line.iloc[-1]
        macd_sig = macd_signal.iloc[-1]
        macd_hist = macd_val - macd_sig

        bb_mid = close.rolling(20).mean()
        bb_std = close.rolling(20).std()
        bb_upper = (bb_mid + 2 * bb_std).iloc[-1]
        bb_lower = (bb_mid - 2 * bb_std).iloc[-1]

        atr = (hist["High"] - hist["Low"]).tail(14).mean()
        vol_20 = close.pct_change().rolling(20).std().iloc[-1] * 100

        def vs_price(indicator):
            if indicator is None or indicator != indicator: return ""
            diff = (cur_price - indicator) / indicator * 100
            c = "green" if diff >= 0 else "red"
            sign = "+" if diff >= 0 else ""
            return f" <span style='font-size:0.7rem;color:{'#30d158' if c=='green' else '#ff453a'}'>{sign}{diff:.1f}%</span>"

        st.markdown("<div class='section-header'>Medie Mobili</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            above = "green" if cur_price > ma20 else "red"
            metric_card(f"MA20 {vs_price(ma20)}", f"{fmt_num(ma20, 2)} {currency}", above)
        with c2:
            above = "green" if cur_price > ma50 else "red"
            metric_card(f"MA50 {vs_price(ma50)}", f"{fmt_num(ma50, 2)} {currency}", above)
        with c3:
            above = "green" if cur_price > ma200 else "red"
            metric_card(f"MA200 {vs_price(ma200)}", f"{fmt_num(ma200, 2)} {currency}", above)

        st.markdown("<div class='section-header'>Oscillatori</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        if rsi >= 70: rsi_label, rsi_color = "Ipercomprato", "red"
        elif rsi <= 30: rsi_label, rsi_color = "Ipervenduto", "green"
        elif rsi >= 55: rsi_label, rsi_color = "Forza", "blue"
        elif rsi <= 45: rsi_label, rsi_color = "Debolezza", "orange"
        else: rsi_label, rsi_color = "Neutro", ""
        with c1:
            metric_card(f"RSI (14) — {rsi_label}", fmt_num(rsi, 1), rsi_color)
        with c2:
            macd_color = "green" if macd_val > macd_sig else "red"
            metric_card(f"MACD {'▲ Rialzista' if macd_val > macd_sig else '▼ Ribassista'}",
                       f"{fmt_num(macd_val, 4)}", macd_color)
        with c3:
            metric_card("MACD Signal", fmt_num(macd_sig, 4))

        st.markdown("<div class='section-header'>Volatilità & Bande</div>", unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            bb_pos = (cur_price - bb_lower) / (bb_upper - bb_lower) * 100 if bb_upper != bb_lower else 50
            metric_card("Banda Bollinger superiore", f"{fmt_num(bb_upper, 2)} {currency}")
            metric_card("Banda Bollinger inferiore", f"{fmt_num(bb_lower, 2)} {currency}")
        with c2:
            metric_card("Posizione in banda", f"{fmt_num(bb_pos, 0)}%",
                       "red" if bb_pos > 80 else "green" if bb_pos < 20 else "")
            metric_card("ATR (14)", f"{fmt_num(atr, 2)} {currency}")
        with c3:
            metric_card("Volatilità 20gg", fmt_pct(vol_20, 2))
            metric_card("Beta", fmt_num(info.get('beta'), 2))

        st.markdown("<div class='section-header'>Supporto & Resistenza (3 mesi)</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        recent = hist.tail(63)
        support = float(recent["Low"].min())
        resistance = float(recent["High"].max())
        with c1:
            metric_card("Supporto (min 3M)", f"{fmt_num(support, 2)} {currency}", "green")
        with c2:
            metric_card("Resistenza (max 3M)", f"{fmt_num(resistance, 2)} {currency}", "red")

        st.markdown("<div class='section-header'>Short Interest</div>", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            sp = info.get('shortPercentOfFloat')
            sp_val = sp * 100 if sp and sp < 1 else sp
            metric_card("Short % Float", fmt_pct(sp_val, 1) if sp_val else "N/A",
                       "red" if sp_val and sp_val > 15 else "")
        with c2:
            metric_card("Short Ratio (days)", fmt_num(info.get('shortRatio'), 1))

    # ── TAB 4: Bilanci ────────────────────────────────────────────────────────
    with tab4:
        fins = fetch_financials(ticker_input)

        def show_statement(df, title):
            if df is None or df.empty:
                st.caption(f"{title}: dati non disponibili")
                return
            st.markdown(f"<div class='section-header'>{title}</div>", unsafe_allow_html=True)
            # Format numbers in billions
            df_display = df.copy()
            for col in df_display.columns:
                df_display[col] = df_display[col].apply(
                    lambda x: f"{x/1e9:.2f}B" if pd.notna(x) and abs(x) >= 1e6 else
                              (f"{x:.0f}" if pd.notna(x) else "N/A")
                )
            st.dataframe(df_display.head(20), use_container_width=True)

        show_statement(fins.get("income"), "Conto Economico (annuale)")
        show_statement(fins.get("balance"), "Stato Patrimoniale")
        show_statement(fins.get("cashflow"), "Cash Flow")

else:
    # Empty state
    st.markdown("""
    <div style='text-align:center;padding:60px 20px;color:#48484a'>
        <div style='font-size:3rem'>📈</div>
        <div style='font-size:1.1rem;font-weight:600;margin-top:12px'>Cerca un'azione</div>
        <div style='font-size:0.85rem;margin-top:8px'>
            Inserisci il ticker o il nome dell'azienda<br>
            <span style='color:#636366'>Es: AAPL · MSFT · ENI.MI · SIE.DE · BNP.PA · 9984.T</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

