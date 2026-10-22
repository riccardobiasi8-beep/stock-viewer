import concurrent.futures as cf
import re
from collections import Counter

import pandas as pd
import streamlit as st
import yfinance as yf

from data_sources import enrich_info
from swing_model import (HORIZON_MAX_DAYS, MIN_RR, analyze, market_index_for,
                         sort_key, technical_precheck)
from universes import UNIVERSES, fetch_universe

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



# ── Dati ──────────────────────────────────────────────────────────────────────
def fetch_info(ticker: str, fmp_key: str) -> dict:
    """Nessuna chiamata Streamlit qui: la funzione gira anche nei thread."""
    t = yf.Ticker(ticker)
    try:
        info = t.info or {}
    except Exception:
        info = {}
    if info:
        try:
            info = enrich_info(t, ticker, info, fmp_key)
        except Exception as e:
            print(f"[Opportunità] enrich {ticker}: {e}")
    return info


def fetch_history(ticker: str) -> pd.DataFrame:
    try:
        return yf.Ticker(ticker).history(period="2y", auto_adjust=True)
    except Exception:
        return pd.DataFrame()


def bulk_history(tickers, chunk=100, on_progress=None) -> dict:
    """Scarica lo storico di molti titoli con poche richieste."""
    out = {}
    for start in range(0, len(tickers), chunk):
        batch = tickers[start:start + chunk]
        try:
            df = yf.download(batch, period="2y", auto_adjust=True, group_by="ticker",
                             threads=True, progress=False)
        except Exception as e:
            print(f"[Opportunità] download: {e}")
            df = None
        for t in batch:
            h = None
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    if t in df.columns.get_level_values(0):
                        h = df[t]
                elif len(batch) == 1:
                    h = df
            out[t] = h.dropna(how="all") if h is not None else pd.DataFrame()
        if on_progress:
            on_progress(min(start + chunk, len(tickers)), len(tickers))
    return out


def error_result(ticker: str, reason: str) -> dict:
    return {"ticker": ticker, "name": ticker, "verdict": "scartato",
            "verdict_label": "Scartato", "composite": None, "plan": None,
            "scores": {}, "labels": {}, "details": {}, "warnings": [],
            "exclusions": [reason], "currency": "", "price": None}


def analyze_with_history(ticker: str, hist, index_hist, fmp_key: str) -> dict:
    try:
        info = fetch_info(ticker, fmp_key)
        return analyze(ticker, info, hist, index_hist, market_index_for(ticker))
    except Exception as e:
        return error_result(ticker, f"Dati non recuperabili: {e}")


@st.cache_data(ttl=900, show_spinner=False)
def cached_index(symbol: str) -> pd.DataFrame:
    return fetch_history(symbol)


@st.cache_data(ttl=900, show_spinner=False)
def cached_analysis(ticker: str, fmp_key: str) -> dict:
    hist = fetch_history(ticker)
    if hist.empty:
        return error_result(ticker, "Ticker non trovato o senza quotazioni su Yahoo Finance")
    return analyze_with_history(ticker, hist, cached_index(market_index_for(ticker)), fmp_key)


@st.cache_data(ttl=86400, show_spinner=False)
def cached_universe(name: str):
    try:
        return fetch_universe(name), None
    except Exception as e:
        return [], str(e)


@st.cache_data(ttl=3600, show_spinner=False)
def search_companies(query: str):
    try:
        quotes = getattr(yf.Search(query, max_results=10), "quotes", []) or []
    except Exception:
        return []
    return [{"symbol": q["symbol"],
             "name": q.get("shortname") or q.get("longname") or q["symbol"],
             "exchange": q.get("exchDisp") or q.get("exchange") or ""}
            for q in quotes if q.get("symbol") and q.get("quoteType") == "EQUITY"]


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
    price_html = (f"<div style='font-size:2.2rem;font-weight:700;line-height:1.2'>{money(r['price'], cur)}</div>"
                  if r.get("price") is not None else "")
    st.markdown(f"""
    <div style='margin-top:8px'>
      <div style='color:#8e8e93;font-size:0.9rem'>{r['ticker']} — {r['name']}</div>
      {price_html}
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

tab_single, tab_scan = st.tabs(["Analizza un titolo", "Scansiona gli indici"])

with tab_single:
    query = st.text_input("Titolo", placeholder="Nome o ticker: Apple, Leonardo, AAPL, ENI.MI…",
                          label_visibility="collapsed").strip()
    ticker = None
    if query:
        looks_like_ticker = " " not in query and query == query.upper() and len(query) <= 12
        result = cached_analysis(query, get_fmp_key()) if looks_like_ticker else None
        not_found = result is not None and result.get("price") is None and \
            result["exclusions"][:1] == ["Ticker non trovato o senza quotazioni su Yahoo Finance"]
        if result is not None and not not_found:
            render_result(result)
        else:
            matches = search_companies(query)
            if matches:
                labels = [f"{m['name']} — {m['symbol']}" + (f" ({m['exchange']})" if m["exchange"] else "")
                          for m in matches]
                choice = st.selectbox("Scegli il titolo", labels)
                ticker = matches[labels.index(choice)]["symbol"]
                with st.spinner(f"Analizzo {ticker}…"):
                    render_result(cached_analysis(ticker, get_fmp_key()))
            else:
                st.caption("Nessun titolo trovato. Prova con il nome dell'azienda o con il ticker "
                           "completo di borsa, per esempio AAPL o ENI.MI.")
    else:
        st.caption("Scrivi il nome dell'azienda o il ticker.")

with tab_scan:
    chosen = st.multiselect("Indici da scansionare", list(UNIVERSES),
                            default=["FTSE MIB (Italia)", "S&P 500 (USA)"])
    extra = st.text_input("Altri ticker (facoltativo)",
                          placeholder="Separati da virgola, es. BC.MI, ASML.AS, NOVO-B.CO")

    if st.button("Scansiona"):
        tickers, failed = [], []
        for name in chosen:
            symbols, error = cached_universe(name)
            if error or not symbols:
                failed.append(name)
            tickers += symbols
        tickers += [t.strip().upper() for t in extra.split(",") if t.strip()]
        tickers = list(dict.fromkeys(tickers))
        if failed:
            st.warning("Elenco non disponibile per: " + ", ".join(failed) +
                       ". Riprova più tardi o aggiungi i ticker a mano.")

        if tickers:
            fmp_key = get_fmp_key()
            index_map = {sym: cached_index(sym) for sym in {market_index_for(t) for t in tickers}}
            progress = st.progress(0.0, text=f"Passaggio 1 di 2: scarico i prezzi di {len(tickers)} titoli…")
            hists = bulk_history(tickers, on_progress=lambda done, total: progress.progress(
                done / total * 0.5, text=f"Passaggio 1 di 2: prezzi scaricati per {done} di {total} titoli"))

            results, survivors = [], []
            for t in tickers:
                reasons = technical_precheck(t, hists.get(t), index_map[market_index_for(t)])
                if reasons:
                    results.append(error_result(t, reasons[0]) | {"exclusions": reasons})
                else:
                    survivors.append(t)

            if survivors:
                progress.progress(0.5, text=f"Passaggio 2 di 2: analizzo i fondamentali di {len(survivors)} titoli…")
                with cf.ThreadPoolExecutor(max_workers=6) as pool:
                    futures = [pool.submit(analyze_with_history, t, hists[t],
                                           index_map[market_index_for(t)], fmp_key) for t in survivors]
                    for i, fut in enumerate(cf.as_completed(futures), start=1):
                        results.append(fut.result())
                        progress.progress(0.5 + 0.5 * i / len(survivors),
                                          text=f"Passaggio 2 di 2: {i} di {len(survivors)} titoli")
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
                "Nome": (r["name"] or "")[:28],
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
            choice = st.selectbox("Vedi il dettaglio", [f"{r['ticker']} — {r['name']}" for r in selected])
            render_result(selected[[f"{r['ticker']} — {r['name']}" for r in selected].index(choice)])
        else:
            st.caption("Nessun titolo supera i filtri in questo momento.")

        if rejected:
            with st.expander(f"Scartati ({len(rejected)}): motivi principali"):
                main_reasons = Counter(re.sub(r"[-+]?\d[\d.,]*", "…", r["exclusions"][0])
                                       for r in rejected if r.get("exclusions"))
                st.dataframe(pd.DataFrame(main_reasons.most_common(), columns=["Motivo", "Titoli"]),
                             hide_index=True, width="stretch")
                st.dataframe(pd.DataFrame([{"Titolo": r["ticker"],
                                            "Motivo": r["exclusions"][0] if r.get("exclusions") else "—"}
                                           for r in rejected]),
                             hide_index=True, width="stretch")

st.markdown(
    "<div class='card-sub' style='margin-top:32px'>Stime basate sui dati storici, non garanzie. "
    "I pesi del modello vanno ancora verificati con un backtest.</div>",
    unsafe_allow_html=True)
