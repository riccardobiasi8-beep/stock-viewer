import concurrent.futures as cf
import html
import json
import random
import re
import time
from collections import Counter

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

from backtest import breakdown, regime_frame, run_backtest, score_bucket, summarize
from data_sources import enrich_info, fundamentals_from_statements
from swing_model import (FUND_REASON, HORIZON_MAX_DAYS, MIN_RR, analyze, canonical_sector,
                         guess_currency, looks_like_fund,
                         index_candidates_for, peer_average, region_for, sector_benchmark,
                         sort_key, technical_precheck)
from universes import (EUROPE_EXCHANGES, EXCHANGES, US_UNIVERSES, fetch_universe_full,
                       indices_for_ticker)

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
KEY_FIELDS = ("trailingPE", "forwardPE", "enterpriseToEbitda", "profitMargins",
              "returnOnEquity", "freeCashflow")
_INFO_CACHE = {}          # ticker -> (istante, info): evita di riscaricare entro 30 minuti
# Se Yahoo rifiuta il riepilogo (errore 401) o fallisce più volte di fila, per 15 minuti
# si passa direttamente ai bilanci invece di insistere e far sembrare ferma la scansione.
_SUMMARY = {"blocked_until": 0.0, "fails": 0}
DOWNLOAD_FAILED = ("Fondamentali non scaricati: Yahoo ha rifiutato le richieste "
                   "e i bilanci non sono disponibili")


def _has_fundamentals(info: dict) -> bool:
    return bool(info) and any(info.get(k) is not None for k in KEY_FIELDS + ("marketCap",))


def _is_auth_error(error) -> bool:
    return any(k in str(error) for k in ("401", "Unauthorized", "Invalid Crumb"))


def _summary_info(t, ticker: str, retries: int = 2) -> dict:
    """Riepilogo Yahoo (ticker.info), con uscita rapida se Yahoo lo rifiuta."""
    if time.time() < _SUMMARY["blocked_until"]:
        return {}
    for attempt in range(retries):
        try:
            info = t.info or {}
        except Exception as e:
            print(f"[Opportunità] info {ticker}: {str(e)[:80]}")
            if _is_auth_error(e):
                _SUMMARY["blocked_until"] = time.time() + 900
                return {}
            info = {}
        if _has_fundamentals(info):
            _SUMMARY["fails"] = 0
            return info
        if attempt < retries - 1:
            time.sleep(1.5 + random.random())
    _SUMMARY["fails"] += 1
    if _SUMMARY["fails"] >= 5:
        _SUMMARY["blocked_until"] = time.time() + 900
    return {}


def fetch_info(ticker: str, fmp_key: str, hist=None) -> dict | None:
    """
    Fondamentali: prima il riepilogo di Yahoo, altrimenti calcolati dai bilanci.
    Restituisce None solo se non si ottiene nulla da nessuna delle due fonti.
    Nessuna chiamata Streamlit qui: la funzione gira anche nei thread.
    """
    cached = _INFO_CACHE.get(ticker)
    if cached and time.time() - cached[0] < 1800:
        return cached[1]

    t = yf.Ticker(ticker)
    info = _summary_info(t, ticker)
    if _has_fundamentals(info):
        if sum(info.get(k) is not None for k in KEY_FIELDS) < 3:
            try:
                info = enrich_info(t, ticker, info, fmp_key)
            except Exception as e:
                print(f"[Opportunità] enrich {ticker}: {e}")
    else:
        close = hist["Close"].dropna() if hist is not None and not hist.empty else None
        if close is None or close.empty:
            return None
        try:
            info = fundamentals_from_statements(t, float(close.iloc[-1]), guess_currency(ticker))
        except Exception as e:
            print(f"[Opportunità] bilanci {ticker}: {str(e)[:80]}")
            info = {}
        if not _has_fundamentals(info):
            return None

    _INFO_CACHE[ticker] = (time.time(), info)
    return info


def fetch_history(ticker: str, period: str = "2y") -> pd.DataFrame:
    try:
        return yf.Ticker(ticker).history(period=period, auto_adjust=True)
    except Exception:
        return pd.DataFrame()


def bulk_history(tickers, chunk=100, on_progress=None, period="2y") -> dict:
    """Scarica lo storico di molti titoli con poche richieste."""
    out = {}
    for start in range(0, len(tickers), chunk):
        batch = tickers[start:start + chunk]
        try:
            df = yf.download(batch, period=period, auto_adjust=True, group_by="ticker",
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


_SECTOR_HISTORY = {}      # simbolo ETF -> (istante, storico): condiviso tra i thread della scansione


def get_sector_history(symbol: str) -> pd.DataFrame:
    cached = _SECTOR_HISTORY.get(symbol)
    if cached and time.time() - cached[0] < 1800:
        return cached[1]
    hist = fetch_history(symbol)
    _SECTOR_HISTORY[symbol] = (time.time(), hist)
    return hist


_YAHOO_SEARCH = {}        # ticker -> {"sector", "news"} dalla ricerca Yahoo


def yahoo_search(ticker: str) -> dict:
    """
    Una sola richiesta alla ricerca di Yahoo (funziona anche quando il riepilogo è bloccato):
    settore/industria del titolo e notizie recenti. Fondi ed ETF → 'Closed End Investments'.
    """
    if ticker in _YAHOO_SEARCH:
        return _YAHOO_SEARCH[ticker]
    out = {"sector": None, "news": []}
    try:
        search = yf.Search(ticker, max_results=5, news_count=10)
        for q in getattr(search, "quotes", []) or []:
            if str(q.get("symbol", "")).upper() != ticker.upper():
                continue
            if q.get("quoteType") in ("ETF", "MUTUALFUND", "CLOSEDENDFUND"):
                out["sector"] = "Closed End Investments"
            else:
                parts = [q.get("industry") or q.get("industryDisp"), q.get("sector") or q.get("sectorDisp")]
                out["sector"] = " · ".join(p for p in parts if p) or None
            break
        out["news"] = [{"title": n.get("title"), "publisher": n.get("publisher", ""),
                        "time": n.get("providerPublishTime")}
                       for n in getattr(search, "news", []) or [] if n.get("title")]
    except Exception as e:
        print(f"[Opportunità] ricerca {ticker}: {str(e)[:80]}")
    _YAHOO_SEARCH[ticker] = out
    return out


def yahoo_sector(ticker: str):
    return yahoo_search(ticker)["sector"]


_POLYMARKET = {}
COMPANY_SUFFIXES = r"\b(inc|corp|corporation|company|co|holdings?|group|plc|ag|se|sa|s\.a|spa|s\.p\.a|nv|n\.v|ltd|limited|class [abc])\b\.?"


def polymarket_markets(name: str, ticker: str) -> list:
    """Mercati aperti di Polymarket che citano la società (solo informativi, fuori dal punteggio)."""
    if ticker in _POLYMARKET:
        return _POLYMARKET[ticker]
    company = re.sub(COMPANY_SUFFIXES, " ", str(name or ""), flags=re.I)
    company = " ".join(re.sub(r"[^\w&' -]", " ", company).split()[:2]).strip()
    root = ticker.split(".")[0]
    found = []
    if len(company) >= 3:
        try:
            response = requests.get("https://gamma-api.polymarket.com/public-search",
                                    params={"q": company}, timeout=8)
            for event in (response.json() or {}).get("events", []) or []:
                if event.get("closed"):
                    continue
                for market in event.get("markets", []) or []:
                    if market.get("closed") or market.get("active") is False:
                        continue
                    text = f"{event.get('title', '')} {market.get('question', '')}"
                    mentions = re.search(rf"\b{re.escape(company)}\b", text, re.I) or \
                        (len(root) >= 3 and re.search(rf"\b{re.escape(root)}\b", text))
                    if not mentions:
                        continue
                    outcomes = json.loads(market.get("outcomes") or "[]")
                    prices = [float(p) for p in json.loads(market.get("outcomePrices") or "[]")]
                    if not outcomes or len(outcomes) != len(prices):
                        continue
                    found.append({"question": market.get("question") or event.get("title"),
                                  "outcomes": list(zip(outcomes, prices)),
                                  "volume": float(market.get("volume") or 0),
                                  "end": str(market.get("endDate") or "")[:10]})
        except Exception as e:
            print(f"[Opportunità] Polymarket {ticker}: {str(e)[:80]}")
    found = sorted(found, key=lambda m: -m["volume"])[:3]
    _POLYMARKET[ticker] = found
    return found


def sector_context(ticker: str, raw_sector, peers=None):
    """Settore del titolo con l'andamento di riferimento: ETF, oppure media dei concorrenti."""
    if not raw_sector:
        return None
    canonical = canonical_sector(raw_sector)
    if not canonical:
        return {"canonical": None, "raw": str(raw_sector), "hist": None, "source": None}
    sector = {"canonical": canonical, "raw": str(raw_sector), "hist": None, "source": None}
    bench = sector_benchmark(ticker, raw_sector)
    if bench:
        hist = get_sector_history(bench["etf"])
        if not hist.empty and hist["Close"].dropna().shape[0] >= 221:
            sector.update(hist=hist, source=f"{bench['etf_label']} ({bench['etf']})")
            return sector
    group = (region_for(ticker), canonical)
    if peers and group in peers:
        hist, count = peers[group]
        sector.update(hist=hist, source=f"media di {count} titoli dello stesso settore")
    return sector


def analyze_with_history(ticker: str, hist, index_hist, index_symbol: str, fmp_key: str,
                         raw_sector=None, peers=None) -> dict:
    try:
        info = fetch_info(ticker, fmp_key, hist)
        if info is None:
            return error_result(ticker, DOWNLOAD_FAILED)
        raw = raw_sector or info.get("sector") or yahoo_sector(ticker)
        if not canonical_sector(raw) and not looks_like_fund(raw):
            raw = yahoo_sector(ticker) or raw          # settore di Wikipedia non riconosciuto
        sector = sector_context(ticker, raw, peers)
        result = analyze(ticker, info, hist, index_hist, index_symbol, sector=sector,
                         news=yahoo_search(ticker)["news"])
        if result["verdict"] != "scartato":
            result["polymarket"] = polymarket_markets(result["name"], ticker)
        return result
    except Exception as e:
        return error_result(ticker, f"Dati non recuperabili: {e}")


@st.cache_data(ttl=900, show_spinner=False)
def cached_resolved_index(candidates: tuple):
    """Primo indice della lista con storico sufficiente (nazionale, poi Euro Stoxx 50)."""
    for symbol in candidates:
        hist = fetch_history(symbol)
        if not hist.empty and hist["Close"].dropna().shape[0] >= 221:
            return symbol, hist
    return candidates[0], pd.DataFrame()


@st.cache_data(ttl=900, show_spinner=False)
def cached_analysis(ticker: str, fmp_key: str) -> dict:
    hist = fetch_history(ticker)
    if hist.empty:
        return error_result(ticker, "Ticker non trovato o senza quotazioni su Yahoo Finance")
    symbol, index_hist = cached_resolved_index(tuple(index_candidates_for(ticker)))
    return analyze_with_history(ticker, hist, index_hist, symbol, fmp_key,
                                raw_sector=lookup_sector(ticker))


def lookup_sector(ticker: str):
    """Settore del titolo dalle tabelle degli indici della sua borsa (se presente)."""
    for name in indices_for_ticker(ticker):
        _, _, _, sectors = load_universe(name)
        if ticker in sectors:
            return sectors[ticker]
    return None


@st.cache_data(ttl=86400, show_spinner=False)
def _universe_ok(name: str):
    symbols, sectors = fetch_universe_full(name)
    if not symbols:
        raise RuntimeError("tabella dei titoli non trovata")
    return symbols, sectors


def load_universe(name: str):
    """(ticker, fonte, errore, settori). Gli errori non vengono memorizzati: si riprova davvero."""
    try:
        symbols, sectors = _universe_ok(name)
        return symbols, "Wikipedia", None, sectors
    except Exception as e:
        return [], None, f"{type(e).__name__}: {str(e)[:150]}", {}


def load_exchange(name: str):
    """Unisce gli indici di una borsa; segnala quelli che non si sono potuti leggere."""
    symbols, sectors, loaded, errors = [], {}, [], []
    for index_name in EXCHANGES[name]:
        short = index_name.split(" (")[0]
        index_symbols, _, error, index_sectors = load_universe(index_name)
        if index_symbols:
            symbols += index_symbols
            sectors.update(index_sectors)
            loaded.append(short)
        else:
            errors.append((short, error))
    if not symbols:
        return [], None, " | ".join(f"{n}: {e}" for n, e in errors), {}
    label = " + ".join(loaded)
    if errors:
        label += "; non letto: " + ", ".join(n for n, _ in errors)
    return list(dict.fromkeys(symbols)), label, None, sectors


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


def tone_color(tone):
    return "#30d158" if tone >= 0.15 else "#ff453a" if tone <= -0.15 else "#8e8e93"


def sentiment_note(r: dict) -> str:
    d, lab = r.get("details") or {}, r.get("labels") or {}
    parts = []
    tone = d.get("news_tone")
    if tone is not None:
        mood = "positive" if tone >= 0.15 else "negative" if tone <= -0.15 else "neutre"
        parts.append(f"Notizie {mood} ({d.get('news_count', 0)})")
    if lab.get("analysts"):
        parts.append(f"Analisti: {lab['analysts']}")
    if d.get("short_pct") is not None:
        parts.append(f"Short {d['short_pct']:.0f}%")
    return " · ".join(parts) or "Dati di sentiment non disponibili"


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
            score_bar("Fondamentali (peso 20%)", s.get("fundamentals"), lab.get("valuation", ""))
            + score_bar("Trend di mercato (peso 15%)", s.get("trend"),
                        f"{lab.get('index', '')}: {lab.get('regime', '')}")
            + score_bar("Trend di settore (peso 15%)", s.get("sector"),
                        (f"{lab.get('sector')}: {lab.get('sector_regime', '')}"
                         + (f" · {lab.get('sector_source')}" if lab.get("sector_source") else ""))
                        if lab.get("sector") else "Settore non disponibile")
            + score_bar("Grafico (peso 40%)", s.get("chart"), lab.get("stage", ""))
            + score_bar("Sentiment (peso 10%)", s.get("sentiment"), sentiment_note(r)),
            unsafe_allow_html=True)

    d = r.get("details") or {}
    if d.get("headlines"):
        st.markdown("<div class='sec'>Notizie recenti analizzate</div>", unsafe_allow_html=True)
        st.markdown("".join(
            f"<div class='reason'><span style='color:{tone_color(h['tone'])}'>●</span> "
            f"{html.escape(h['title'])} <span class='card-sub'>{html.escape(h.get('publisher') or '')}</span></div>"
            for h in d["headlines"]), unsafe_allow_html=True)
    if r.get("polymarket"):
        st.markdown("<div class='sec'>Polymarket (solo informativo, non entra nel punteggio)</div>",
                    unsafe_allow_html=True)
        for m in r["polymarket"]:
            odds = " · ".join(f"{html.escape(str(o))} {p * 100:.0f}%" for o, p in m["outcomes"])
            st.markdown(f"<div class='reason'>{html.escape(m['question'])}<br><span class='card-sub'>"
                        f"{odds} · scadenza {m['end'] or 'n.d.'} · volume {m['volume']:,.0f} $</span></div>",
                        unsafe_allow_html=True)
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
                ("Settore (fonte indice)", d.get("sector_raw") or "n.d.", ""),
                ("Tono delle notizie", num(d.get("news_tone"), 2),
                 f"{d.get('news_count', 0)} titoli, scala da -1 a +1"),
                ("Giudizio medio analisti", num(d.get("recommendation_mean"), 2), "1 = acquisto forte, 5 = vendita"),
                ("Short interest", num(d.get("short_pct"), 1, "%"), "quota di azioni vendute allo scoperto"),
                ("Forza relativa vs settore 3 mesi", num(d.get("sector_relative_strength"), 1, " punti %"),
                 "rendimento del titolo meno quello del settore"),
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

tab_single, tab_scan, tab_backtest = st.tabs(["Analizza un titolo", "Scansiona gli indici", "Backtest"])

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
    st.markdown("<div class='card-sub' style='margin-bottom:6px'>Per ogni borsa europea si usano "
                "i titoli dei suoi indici principali, letti da Wikipedia.</div>",
                unsafe_allow_html=True)
    all_europe = st.checkbox("Tutta l'Europa (16 borse)")
    exchanges = st.multiselect("Borse europee", list(EXCHANGES), default=[],
                               disabled=all_europe, placeholder="Scegli una o più borse")
    chosen = st.multiselect("Indici USA", US_UNIVERSES, default=["S&P 500 (USA)"])
    extra = st.text_input("Altri ticker (facoltativo)",
                          placeholder="Separati da virgola, es. BC.MI, ASML.AS, NOVO-B.CO")
    if all_europe:
        st.caption("Tutta l'Europa sono circa 800 titoli: la scansione richiede alcuni minuti.")

    if st.button("Scansiona"):
        tickers, failed, sources, raw_sectors = [], {}, {}, {}
        status = st.empty()
        jobs = [(n, lambda n=n: load_exchange(n)) for n in (EUROPE_EXCHANGES if all_europe else exchanges)]
        jobs += [(n, lambda n=n: load_universe(n)) for n in chosen]
        for name, load in jobs:
            status.caption(f"Leggo l'elenco di {name}…")
            symbols, source, error, sectors = load()
            raw_sectors.update(sectors)
            if symbols:
                sources[name] = f"{len(symbols)}" + (f" ({source})" if source != "Wikipedia" else "")
                tickers += symbols
            else:
                failed[name] = error or "elenco vuoto"
        status.empty()
        tickers += [t.strip().upper() for t in extra.split(",") if t.strip()]
        tickers = list(dict.fromkeys(tickers))
        if failed:
            st.warning("Elenco non disponibile per: " + ", ".join(failed) +
                       ". Riprova tra qualche minuto, oppure aggiungi i ticker a mano.")
            with st.expander("Dettagli tecnici dell'errore"):
                for name, error in failed.items():
                    st.markdown(f"<div class='reason'><b>{name}</b>: {error}</div>",
                                unsafe_allow_html=True)

        if tickers:
            fmp_key = get_fmp_key()
            groups = {tuple(index_candidates_for(t)) for t in tickers}
            index_map = {g: cached_resolved_index(g) for g in groups}
            progress = st.progress(0.0, text=f"Passaggio 1 di 2: scarico i prezzi di {len(tickers)} titoli…")
            hists = bulk_history(tickers, on_progress=lambda done, total: progress.progress(
                done / total * 0.5, text=f"Passaggio 1 di 2: prezzi scaricati per {done} di {total} titoli"))

            results, survivors = [], []
            for t in tickers:
                if looks_like_fund(raw_sectors.get(t)):
                    results.append(error_result(t, FUND_REASON))
                    continue
                idx_symbol, idx_hist = index_map[tuple(index_candidates_for(t))]
                reasons = technical_precheck(t, hists.get(t), idx_hist, idx_symbol)
                if reasons:
                    results.append(error_result(t, reasons[0]) | {"exclusions": reasons})
                else:
                    survivors.append(t)

            if survivors:
                # Trend di settore: ETF di riferimento scaricati in blocco...
                etfs = sorted({b["etf"] for t in survivors
                               if (b := sector_benchmark(t, raw_sectors.get(t)))})
                if etfs:
                    progress.progress(0.5, text=f"Scarico l'andamento di {len(etfs)} settori…")
                    for symbol, etf_hist in bulk_history(etfs).items():
                        _SECTOR_HISTORY[symbol] = (time.time(), etf_hist)
                # ...e, come riserva, la media dei titoli dello stesso settore (almeno 5)
                groups_hist = {}
                for t, h in hists.items():
                    canonical = canonical_sector(raw_sectors.get(t))
                    if canonical and region_for(t) and h is not None and not h.empty:
                        groups_hist.setdefault((region_for(t), canonical), []).append(h)
                peers = {}
                for group, members in groups_hist.items():
                    if len(members) >= 5:
                        avg = peer_average(members)
                        if not avg.empty:
                            peers[group] = (avg, len(members))

                progress.progress(0.5, text=f"Passaggio 2 di 2: analizzo i fondamentali di {len(survivors)} titoli…")
                with cf.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = []
                    for t in survivors:
                        idx_symbol, idx_hist = index_map[tuple(index_candidates_for(t))]
                        futures.append(pool.submit(analyze_with_history, t, hists[t],
                                                   idx_hist, idx_symbol, fmp_key,
                                                   raw_sectors.get(t), peers))
                    for i, fut in enumerate(cf.as_completed(futures), start=1):
                        results.append(fut.result())
                        progress.progress(0.5 + 0.5 * i / len(survivors),
                                          text=f"Passaggio 2 di 2: {i} di {len(survivors)} titoli")
            progress.empty()
            st.session_state["scan_results"] = sorted(results, key=sort_key)
            st.session_state["scan_sources"] = sources

    sources = st.session_state.get("scan_sources")
    if sources:
        st.caption("Elenchi caricati: " + " · ".join(f"{k} {v}" for k, v in sources.items()))

    results = st.session_state.get("scan_results")
    if results:
        not_loaded = [r for r in results if r.get("exclusions", [None])[:1] == [DOWNLOAD_FAILED]]
        selected = [r for r in results if r["verdict"] != "scartato"]
        rejected = [r for r in results if r["verdict"] == "scartato" and r not in not_loaded]
        if not_loaded:
            st.warning(f"{len(not_loaded)} titoli non analizzati perché Yahoo ha limitato le richieste. "
                       "Rilancia la scansione tra qualche minuto: i titoli già scaricati restano in memoria "
                       "e la seconda volta è più veloce.")
        st.markdown(f"<div class='sec'>{len(selected)} titoli selezionati su {len(results) - len(not_loaded)} analizzati</div>",
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

STAGE_NAMES = {"2-iniziale": "Stadio 2 iniziale", "2-in-corso": "Stadio 2 in corso",
               "2-esteso": "Stadio 2 esteso", "2-pausa": "Stadio 2 in pausa",
               "2-correzione": "Stadio 2 in correzione", "1-uscita": "Stadio 1 in uscita",
               "1-base": "Stadio 1 base"}


def render_backtest(bt: dict):
    trades, counts = bt["trades"], bt["counts"]
    st.markdown("<div class='sec'>Risultati</div>", unsafe_allow_html=True)
    st.caption(f"{bt['n_tickers']} titoli, ultimi {bt['years']} anni · {counts['segnali']} segnali, "
               f"{counts['non_eseguiti']} ordini mai eseguiti · trend di settore disponibile per "
               f"{bt['sector_coverage']} titoli")
    summary = summarize(trades) if not trades.empty else {"chiuse": 0}
    if summary["chiuse"] == 0:
        st.info("Nessuna operazione chiusa nel periodo: prova con più borse o un periodo più lungo.")
        return

    extra = summary["extra_vs_indice"]
    if summary["media_netta"] > 0 and (extra is None or extra > 0):
        verdict = (f"Nel periodo il modello ha guadagnato in media **{summary['media_netta']:+.2f}%** netto "
                   "per operazione" + (f", **{extra:+.2f} punti** meglio dell'indice negli stessi giorni." if extra is not None else "."))
    else:
        verdict = (f"Nel periodo il modello ha reso in media **{summary['media_netta']:+.2f}%** netto per operazione"
                   + (f", {extra:+.2f} punti rispetto all'indice negli stessi giorni" if extra is not None else "")
                   + ": così com'è non avrebbe aggiunto valore.")
    st.markdown(verdict)

    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(card("Operazioni chiuse", f"{summary['chiuse']}", f"{summary['in_corso']} ancora aperte"), unsafe_allow_html=True)
    c2.markdown(card("In guadagno", f"{summary['win_pct']:.0f}%", f"mediana {summary['mediana_netta']:+.2f}%"), unsafe_allow_html=True)
    c3.markdown(card("Netto medio", f"{summary['media_netta']:+.2f}%", f"lordo {summary['media_lorda']:+.2f}%",
                     "#30d158" if summary["media_netta"] > 0 else "#ff453a"), unsafe_allow_html=True)
    c4.markdown(card("Rispetto all'indice", f"{extra:+.2f} punti" if extra is not None else "n.d.",
                     "a parità di giorni", "#30d158" if (extra or 0) > 0 else "#ff453a"), unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(card("Chiuse al target", f"{summary['target_pct']:.0f}%"), unsafe_allow_html=True)
    c2.markdown(card("Chiuse allo stop", f"{summary['stop_pct']:.0f}%"), unsafe_allow_html=True)
    c3.markdown(card("Uscite a tempo", f"{summary['scadenza_pct']:.0f}%"), unsafe_allow_html=True)
    in_time = summary["target_nei_tempi_pct"]
    c4.markdown(card("Durata media", f"{summary['giorni_medi']:.0f} sedute",
                     f"target entro il tempo stimato: {in_time:.0f}%" if in_time is not None else ""),
                unsafe_allow_html=True)

    closed = trades[trades["outcome"] != "in corso"].sort_values("exit_date")
    st.markdown("<div class='sec'>Andamento cumulato</div>", unsafe_allow_html=True)
    st.caption("Somma dei rendimenti netti delle operazioni chiuse, a importo uguale per operazione")
    st.line_chart(closed.set_index("exit_date")["net_pct"].cumsum().rename("Rendimento netto cumulato %"))

    closed = closed.assign(fascia=closed["score"].apply(score_bucket),
                           fase=closed["stage"].map(STAGE_NAMES).fillna("altro"))
    for title, column in (("Per fascia di punteggio: i punteggi alti rendono di più?", "fascia"),
                          ("Per tendenza del settore: il filtro del settore aiuta?", "sector_regime"),
                          ("Per fase del grafico", "fase"), ("Per tipo di entrata", "order")):
        st.markdown(f"<div class='sec'>{title}</div>", unsafe_allow_html=True)
        st.dataframe(breakdown(closed, column), width="stretch")

    with st.expander("Tutte le operazioni"):
        view = trades.copy()
        for col in ("signal_date", "fill_date", "exit_date"):
            view[col] = pd.to_datetime(view[col]).dt.date
        st.dataframe(view[["ticker", "signal_date", "fill_date", "exit_date", "outcome", "fill_price",
                           "exit_price", "gross_pct", "net_pct", "excess_pct", "days", "score",
                           "sector_regime"]].round(2), hide_index=True, width="stretch")
    st.markdown(
        "<div class='card-sub'>Limiti da tenere presenti: gli elenchi sono quelli di oggi, quindi mancano le società "
        "uscite dagli indici o fallite nel frattempo (i risultati sono un po' ottimistici); i settori sono quelli "
        f"attuali; costi ipotizzati {0.15:.2f}% per lato; imposta del 26% applicata ai soli guadagni, operazione per "
        "operazione. Fondamentali e sentiment non sono verificati, perché non esiste uno storico gratuito.</div>",
        unsafe_allow_html=True)


with tab_backtest:
    st.markdown("<div class='card-sub' style='margin-bottom:8px'>Applica le regole del modello alle date passate, "
                "con i soli dati disponibili in quel momento, e segue ogni operazione fino a target, stop o "
                "uscita a tempo. Verifica grafico, trend di mercato, trend di settore e piano di uscita.</div>",
                unsafe_allow_html=True)
    bt_all_europe = st.checkbox("Tutta l'Europa (16 borse)", key="bt_all_europe")
    bt_exchanges = st.multiselect("Borse europee", list(EXCHANGES), default=["Milano"],
                                  disabled=bt_all_europe, key="bt_exchanges")
    bt_us = st.multiselect("Indici USA", US_UNIVERSES, default=[], key="bt_us")
    c1, c2 = st.columns(2)
    bt_years = c1.selectbox("Periodo", [1, 2, 3], index=1, key="bt_years",
                            format_func=lambda y: "Ultimo anno" if y == 1 else f"Ultimi {y} anni")
    bt_step = c2.selectbox("Controlli", [21, 10], key="bt_step",
                           format_func=lambda d: "Una volta al mese" if d == 21 else "Ogni due settimane")
    if st.button("Avvia backtest", key="bt_run"):
        tickers, raw_sectors = [], {}
        for name in (EUROPE_EXCHANGES if bt_all_europe else bt_exchanges):
            symbols, _, _, sectors = load_exchange(name)
            tickers += symbols; raw_sectors.update(sectors)
        for name in bt_us:
            symbols, _, _, sectors = load_universe(name)
            tickers += symbols; raw_sectors.update(sectors)
        tickers = [t for t in dict.fromkeys(tickers) if not looks_like_fund(raw_sectors.get(t))]
        if not tickers:
            st.warning("Nessun titolo da analizzare: scegli almeno una borsa o un indice.")
        else:
            progress = st.progress(0.0, text=f"Scarico 5 anni di prezzi per {len(tickers)} titoli…")
            hists = bulk_history(tickers, period="5y", on_progress=lambda done, total: progress.progress(
                done / total * 0.4, text=f"Prezzi scaricati per {done} di {total} titoli"))
            hists = {t: h for t, h in hists.items() if h is not None and not h.empty}

            progress.progress(0.4, text="Scarico indici ed ETF di settore…")
            candidates = sorted({c for t in hists for c in index_candidates_for(t)})
            index_hists = bulk_history(candidates, period="5y")
            market_of = {}
            for t in hists:
                for c in index_candidates_for(t):
                    h = index_hists.get(c)
                    if h is not None and not h.empty and h["Close"].dropna().shape[0] >= 221:
                        market_of[t] = c
                        break
            market_states = {c: regime_frame(index_hists[c]) for c in set(market_of.values())}
            sector_of = {t: (b["etf"] if (b := sector_benchmark(t, raw_sectors.get(t))) else None) for t in hists}
            etfs = sorted({e for e in sector_of.values() if e})
            etf_hists = bulk_history(etfs, period="5y") if etfs else {}
            sector_states = {e: regime_frame(h) for e, h in etf_hists.items()
                             if h is not None and not h.empty and h["Close"].dropna().shape[0] >= 221}

            trades, counts = run_backtest(
                hists, market_of, sector_of, market_states, sector_states, years=bt_years, step_days=bt_step,
                on_progress=lambda k, n: progress.progress(0.5 + 0.5 * k / n, text=f"Simulo le operazioni: {k} di {n} titoli"))
            progress.empty()
            st.session_state["bt"] = {"trades": trades, "counts": counts, "years": bt_years,
                                      "n_tickers": len(hists),
                                      "sector_coverage": sum(1 for t in hists if sector_of.get(t) in sector_states)}
    if st.session_state.get("bt"):
        render_backtest(st.session_state["bt"])

st.markdown(
    "<div class='card-sub' style='margin-top:32px'>Stime basate sui dati storici, non garanzie.</div>",
    unsafe_allow_html=True)
