import concurrent.futures as cf

import pandas as pd
import streamlit as st
import yfinance as yf

from data_sources import enrich_info
from swing_model import (HORIZON_MAX_DAYS, MIN_RR, analyze, market_index_for,
                         sort_key)

st.set_page_config(page_title="Opportunità", page_icon="🎯", layout="wide",
                   initial_sidebar_state="collapsed")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
* { font-family: 'Inter', sans-serif; }
html, body, [data-testid="stAppViewContainer"] { background: #000; color: #f5f5f7; }
[data-testid="stHeader"], [data-testid="stSidebar"], footer, #MainMenu { display: none !important; }
.block-container { padding: 16px 16px 60px !important; max-width: 900px; margin: auto; }
.stTextInput input, .stTextArea textarea {
    background: #1c1c1e !important; border: 1px solid #3a3a3c !important;
    border-radius: 12px !important; color: #f5f5f7 !important;
}
.card { background: #1c1c1e; border-radius: 12px; padding: 14px 16px; margin-bottom: 8px; }
.card-label { font-size: 0.75rem; color: #8e8e93; margin-bottom: 4px; }
.card-value { font-size: 1.15rem; font-weight: 600; color: #f5f5f7; }
.card-sub { font-size: 0.75rem; color: #8e8e93; margin-top: 2px; }
.pill { display: inline-block; border-radius: 999px; padding: 4px 12px;
        font-size: 0.85rem; font-weight: 600; }
.sec { font-size: 0.95rem; font-weight: 600; color: #f5f5f7; margin: 22px 0 10px; }
.sb { margin-bottom: 12px; }
.sb-top { display: flex; justify-content: space-between; font-size: 0.85rem; }
.sb-track { height: 6px; background: #2c2c2e; border-radius: 3px; margin-top: 5px; }
.sb-fill { height: 6px; border-radius: 3px; }
.sb-note { font-size: 0.75rem; color: #8e8e93; margin-top: 4px; }
.reason { font-size: 0.85rem; color: #ebebf5; padding: 6px 0; border-bottom: 1px solid #2c2c2e; }
.stButton button { background: #0a84ff !important; color: #fff !important; border: none !important;
                   border-radius: 10px !important; font-weight: 600 !important; }
</style>
""", unsafe_allow_html=True)

VERDICT_COLORS = {"valido": "#30d158", "osservazione": "#ff9f0a", "scartato": "#ff453a"}

DEFAULT_LIST = (
    "AAPL, MSFT, GOOGL, AMZN, META, NVDA, JPM, V, JNJ, PG, KO, XOM, CVX, PFE, CSCO, ORCL, MCD, NKE,\n"
    "ENI.MI, ENEL.MI, ISP.MI, UCG.MI, STLAM.MI, RACE.MI, G.MI, PST.MI, LDO.MI,\n"
    "SAP.DE, SIE.DE, ALV.DE, BAS.DE, BMW.DE, DTE.DE,\n"
    "MC.PA, TTE.PA, BNP.PA, SAN.PA, AIR.PA"
)


# ── Dati ──────────────────────────────────────────────────────────────────────
def fetch_ticker(ticker: str, fmp_key: str):
    """Nessuna chiamata Streamlit qui: la funzione gira anche nei thread."""
    t = yf.Ticker(ticker)
    hist = t.history(period="2y", auto_adjust=True)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if info:
        try:
            info = enrich_info(t, ticker, info, fmp_key)
        except Exception as e:
            print(f"[Opportunità] enrich {ticker}: {e}")
    return info, hist


def fetch_index(symbol: str) -> pd.DataFrame:
    try:
        return yf.Ticker(symbol).history(period="2y", auto_adjust=True)
    except Exception:
        return pd.DataFrame()


def analyze_ticker(ticker: str, index_hist: pd.DataFrame, fmp_key: str) -> dict:
    try:
        info, hist = fetch_ticker(ticker, fmp_key)
        return analyze(ticker, info, hist, index_hist, market_index_for(ticker))
    except Exception as e:
        return {"ticker": ticker, "name": ticker, "verdict": "scartato",
                "verdict_label": "Scartato", "composite": None, "plan": None,
                "scores": {}, "labels": {}, "details": {}, "warnings": [],
                "exclusions": [f"Dati non recuperabili: {e}"], "currency": "", "price": None}


@st.cache_data(ttl=900, show_spinner=False)
def cached_index(symbol: str) -> pd.DataFrame:
    return fetch_index(symbol)


@st.cache_data(ttl=900, show_spinner=False)
def cached_analysis(ticker: str, fmp_key: str) -> dict:
    return analyze_ticker(ticker, cached_index(market_index_for(ticker)), fmp_key)


def get_fmp_key() -> str:
    try:
        return st.secrets.get("FMP_API_KEY", "")
    except Exception:
        return ""


# ── Formattazione ─────────────────────────────────────────────────────────────
def money(value, cur):
    return "—" if value is None else f"{value:,.2f} {cur}"


def pct(value):
    return "—" if value is None else f"{value:+.2f}%"


def card(label, value, sub="", color="#f5f5f7"):
    sub_html = f"<div class='card-sub'>{sub}</div>" if sub else ""
    return (f"<div class='card'><div class='card-label'>{label}</div>"
            f"<div class='card-value' style='color:{color}'>{value}</div>{sub_html}</div>")


def score_bar(label, score, note):
    if score is None:
        value, width, color = "n.d.", 0, "#3a3a3c"
    else:
        value, width = f"{score:.0f}/100", score
        color = "#30d158" if score >= 65 else "#ff9f0a" if score >= 50 else "#ff453a"
    return (f"<div class='sb'><div class='sb-top'><span>{label}</span><span>{value}</span></div>"
            f"<div class='sb-track'><div class='sb-fill' style='width:{width}%;background:{color}'></div></div>"
            f"<div class='sb-note'>{note}</div></div>")


def render_result(r: dict):
    cur = r.get("currency", "")
    color = VERDICT_COLORS.get(r["verdict"], "#8e8e93")
    composite = f"Punteggio {r['composite']:.0f}/100" if r.get("composite") is not None else ""
    st.markdown(f"""
    <div style='margin-top:8px'>
      <div style='color:#8e8e93;font-size:0.9rem'>{r['ticker']} — {r['name']}</div>
      <div style='font-size:2.2rem;font-weight:700;line-height:1.2'>{money(r.get('price'), cur)}</div>
      <div style='margin-top:8px'>
        <span class='pill' style='background:{color}22;color:{color};border:1px solid {color}66'>{r['verdict_label']}</span>
        <span style='color:#8e8e93;font-size:0.85rem;margin-left:8px'>{composite}</span>
      </div>
    </div>""", unsafe_allow_html=True)

    plan = r.get("plan")
    if plan:
        operative = r["verdict"] != "scartato"
        st.markdown("<div class='sec'>Piano operativo</div>" if operative else
                    "<div class='sec'>Piano indicativo</div><div class='card-sub'>"
                    "Il titolo non supera i filtri: i livelli sono mostrati solo per trasparenza.</div>",
                    unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.markdown(card("Entrata", money(plan["entry"], cur), plan["order"]), unsafe_allow_html=True)
        c2.markdown(card("Stop", money(plan["stop"], cur), f"Perdita massima {pct(plan['max_loss_pct'])}",
                         "#ff453a"), unsafe_allow_html=True)
        c3.markdown(card("Target", money(plan["target"], cur), plan["target_basis"], "#30d158"),
                    unsafe_allow_html=True)
        c1, c2, c3 = st.columns(3)
        c1.markdown(card("Ritorno lordo", pct(plan["gross_pct"]),
                         f"Netto dopo il 26%: {pct(plan['net_pct'])}"), unsafe_allow_html=True)
        months = (f"{plan['months_low']}–{plan['months_high']} mesi"
                  if plan.get("months_low") is not None else "—")
        exit_date = (f"Esci comunque entro il {pd.Timestamp(plan['time_stop_date']).strftime('%d/%m/%Y')}"
                     if plan.get("time_stop_date") else "")
        c2.markdown(card("Tempo stimato", months, exit_date), unsafe_allow_html=True)
        rr_color = "#30d158" if plan["rr"] >= MIN_RR else "#ff453a"
        c3.markdown(card("Rendimento/rischio", f"{plan['rr']:.1f}",
                         f"Minimo richiesto {MIN_RR:.0f}", rr_color), unsafe_allow_html=True)
        st.markdown(f"<div class='card-sub'>Tipo di entrata: {plan['setup']}</div>",
                    unsafe_allow_html=True)

    if r.get("exclusions"):
        st.markdown("<div class='sec'>Perché è scartato</div>", unsafe_allow_html=True)
        st.markdown("".join(f"<div class='reason'>{x}</div>" for x in r["exclusions"]),
                    unsafe_allow_html=True)
    if r.get("warnings"):
        st.markdown("<div class='sec'>Da sapere</div>", unsafe_allow_html=True)
        st.markdown("".join(f"<div class='reason'>{x}</div>" for x in r["warnings"]),
                    unsafe_allow_html=True)

    s, lab = r.get("scores", {}), r.get("labels", {})
    if s:
        st.markdown("<div class='sec'>Punteggi</div>", unsafe_allow_html=True)
        st.markdown(
            score_bar("Fondamentali (peso 30%)", s.get("fundamentals"), lab.get("valuation", ""))
            + score_bar("Trend di mercato (peso 30%)", s.get("trend"),
                        f"{lab.get('index', '')}: {lab.get('regime', '')}")
            + score_bar("Grafico (peso 40%)", s.get("chart"), lab.get("stage", "")),
            unsafe_allow_html=True)

    d = r.get("details") or {}
    if d:
        with st.expander("Come è stato calcolato"):
            def num(v, dec=2, suffix=""):
                return "n.d." if v is None else f"{v:,.{dec}f}{suffix}"
            rows = [
                ("Settore", d.get("sector", "n.d."), ""),
                ("P/E", num(d.get("pe"), 1), f"riferimento settore {num(d.get('pe_ref'), 0)}"),
                ("EV/EBITDA", num(d.get("ev_ebitda"), 1), f"riferimento settore {num(d.get('ev_ebitda_ref'), 0)}"),
                ("P/B", num(d.get("pb"), 2), f"riferimento settore {num(d.get('pb_ref'), 1)}"),
                ("Rendimento free cash flow", num(d.get("fcf_yield"), 1, "%"), ""),
                ("Margine netto", num(d.get("margin"), 1, "%"), ""),
                ("ROE", num(d.get("roe"), 1, "%"), ""),
                ("Crescita ricavi", num(d.get("growth"), 1, "%"), ""),
                ("Debito/patrimonio", num(d.get("debt_equity"), 2), ""),
                ("Target medio analisti", num(d.get("analyst_target"), 2),
                 f"{d.get('n_analysts', 0)} analisti"),
                ("Forza relativa 3 mesi", num(d.get("relative_strength"), 1, " punti %"),
                 "rendimento del titolo meno quello dell'indice"),
                ("RSI 14", num(d.get("rsi"), 0), ""),
                ("ATR 14", num(d.get("atr"), 2), "oscillazione media giornaliera"),
                ("Media 20 giorni", num(d.get("ma20"), 2), ""),
                ("Media 150 giorni", num(d.get("ma150"), 2),
                 f"pendenza {num(d.get('ma150_slope'), 1, '%')} in 20 sedute"),
                ("Base recente", f"{num(d.get('base_low'))} – {num(d.get('base_high'))}", "ultime 40 sedute"),
                ("Massimo 52 settimane", num(d.get("high_52w"), 2), ""),
            ]
            st.dataframe(pd.DataFrame(rows, columns=["Dato", "Valore", "Nota"]),
                         hide_index=True, width="stretch")


# ── Pagina ────────────────────────────────────────────────────────────────────
try:
    st.page_link("app.py", label="Torna a Stock Viewer", icon="📈")
except Exception:
    st.markdown("[📈 Torna a Stock Viewer](/)")
st.markdown("## 🎯 Opportunità")
st.markdown(
    "<div style='color:#8e8e93;font-size:0.9rem;margin-bottom:12px'>"
    "Titoli sottovalutati rispetto al settore con un grafico favorevole, "
    f"per operazioni da 1 a {HORIZON_MAX_DAYS // 21} mesi.</div>",
    unsafe_allow_html=True)

tab_single, tab_scan = st.tabs(["Analizza un titolo", "Scansiona una lista"])

with tab_single:
    ticker = st.text_input("Ticker", placeholder="Es. ENI.MI, AAPL, SAP.DE",
                           label_visibility="collapsed").strip().upper()
    if ticker:
        with st.spinner(f"Analizzo {ticker}…"):
            render_result(cached_analysis(ticker, get_fmp_key()))
    else:
        st.caption("Scrivi il ticker esatto, con il suffisso della borsa per i titoli non americani.")

with tab_scan:
    raw_list = st.text_area("Titoli da analizzare", value=DEFAULT_LIST, height=130,
                            help="Ticker separati da virgola o a capo")
    if st.button("Scansiona"):
        tickers = list(dict.fromkeys(
            t.strip().upper() for t in raw_list.replace("\n", ",").split(",") if t.strip()))
        fmp_key = get_fmp_key()
        index_map = {sym: cached_index(sym) for sym in {market_index_for(t) for t in tickers}}
        progress = st.progress(0.0, text=f"Analizzo {len(tickers)} titoli…")
        results = []
        with cf.ThreadPoolExecutor(max_workers=6) as pool:
            futures = [pool.submit(analyze_ticker, t, index_map[market_index_for(t)], fmp_key)
                       for t in tickers]
            for i, fut in enumerate(cf.as_completed(futures), start=1):
                results.append(fut.result())
                progress.progress(i / len(tickers), text=f"Analizzati {i} di {len(tickers)}")
        progress.empty()
        st.session_state["scan_results"] = sorted(results, key=sort_key)

    results = st.session_state.get("scan_results")
    if results:
        selected = [r for r in results if r["verdict"] != "scartato"]
        rejected = [r for r in results if r["verdict"] == "scartato"]
        st.markdown(f"<div class='sec'>{len(selected)} titoli selezionati su {len(results)}</div>",
                    unsafe_allow_html=True)
        if selected:
            table = pd.DataFrame([{
                "Titolo": r["ticker"],
                "Esito": r["verdict_label"],
                "Punteggio": r["composite"],
                "Entrata": r["plan"]["entry"],
                "Stop": r["plan"]["stop"],
                "Target": r["plan"]["target"],
                "Netto %": r["plan"]["net_pct"],
                "Mesi": (f"{r['plan']['months_low']}–{r['plan']['months_high']}"
                         if r["plan"].get("months_low") is not None else "—"),
                "R/R": r["plan"]["rr"],
            } for r in selected])
            st.dataframe(table, hide_index=True, width="stretch", column_config={
                "Punteggio": st.column_config.NumberColumn(format="%.0f"),
                "Entrata": st.column_config.NumberColumn(format="%.2f"),
                "Stop": st.column_config.NumberColumn(format="%.2f"),
                "Target": st.column_config.NumberColumn(format="%.2f"),
                "Netto %": st.column_config.NumberColumn(format="%+.2f"),
                "R/R": st.column_config.NumberColumn(format="%.1f"),
            })
            choice = st.selectbox("Vedi il dettaglio", [r["ticker"] for r in selected])
            render_result(next(r for r in selected if r["ticker"] == choice))
        else:
            st.caption("Nessun titolo della lista supera i filtri in questo momento.")

        if rejected:
            with st.expander(f"Scartati ({len(rejected)})"):
                for r in rejected:
                    reason = r["exclusions"][0] if r.get("exclusions") else "—"
                    st.markdown(f"<div class='reason'><b>{r['ticker']}</b> — {reason}</div>",
                                unsafe_allow_html=True)

st.markdown(
    "<div class='card-sub' style='margin-top:32px'>Stime basate sui dati storici, non garanzie. "
    "I pesi del modello vanno ancora verificati con un backtest.</div>",
    unsafe_allow_html=True)
