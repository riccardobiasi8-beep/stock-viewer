import concurrent.futures as cf
import html
import json
import random
import re
import time
from collections import Counter

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

from backtest import breakdown, regime_frame, run_backtest, score_bucket, summarize
from data_sources import enrich_info, fundamentals_from_statements
from swing_model import (FUND_REASON, HORIZON_MAX_DAYS, MIN_RR, WEIGHTS, analyze, canonical_sector,
                         guess_currency, looks_like_fund,
                         index_candidates_for, peer_average, region_for, sector_benchmark,
                         sort_key, technical_precheck)
from ui import (BLUE, CHART_DOWN, CHART_UP, GREEN, LABEL, LABEL2, LABEL3, ORANGE, RED, SEPARATOR, apply_style, badge, esc, footnote,
                html_table, large_title, list_rows, score_rows, section, tiles)
from universes import (EUROPE_EXCHANGES, EXCHANGES, US_UNIVERSES, fetch_universe_full,
                       indices_for_ticker)

st.set_page_config(page_title="Opportunità", page_icon="🎯", layout="wide",
                   initial_sidebar_state="collapsed")

apply_style()

VERDICT_COLORS = {"valido": GREEN, "osservazione": ORANGE, "scartato": RED}



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
    return "—" if value is None else f"{value:,.2f} {cur}".strip()


def pct(value):
    return "—" if value is None else f"{value:+.2f}%"


def tone_color(tone):
    return CHART_UP if tone >= 0.15 else CHART_DOWN if tone <= -0.15 else LABEL3


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


def months_text(plan) -> str:
    return (f"{plan['months_low']}–{plan['months_high']} mesi"
            if plan and plan.get("months_low") is not None else "—")


STAGE_NAMES = {"2-iniziale": "Stadio 2 iniziale", "2-in-corso": "Stadio 2 in corso",
               "2-esteso": "Stadio 2 esteso", "2-pausa": "Stadio 2 in pausa",
               "2-correzione": "Stadio 2 in correzione", "1-uscita": "Stadio 1 in uscita",
               "1-base": "Stadio 1 base"}
# Titoli indicativi per borsa: servono solo a stimare la durata della ricerca
APPROX_COUNTS = {"Milano": 40, "Francoforte (Xetra)": 140, "Parigi": 40, "Londra": 350, "Amsterdam": 50,
                 "Madrid": 35, "Zurigo": 20, "Bruxelles": 20, "Lisbona": 18, "Vienna": 20, "Dublino": 20,
                 "Stoccolma": 30, "Copenaghen": 25, "Helsinki": 25, "Oslo": 25, "Varsavia": 21,
                 "S&P 500 (USA)": 503}


# ── Scheda di un titolo ───────────────────────────────────────────────────────
def render_result(r: dict):
    cur = r.get("currency") or ""
    color = VERDICT_COLORS.get(r["verdict"], LABEL2)
    price = (f"<div class='ios-hero-price'>{r['price']:,.2f} <span class='ios-hero-cur'>{esc(cur)}</span></div>"
             if r.get("price") is not None else "")
    score = (f"<span style='color:{LABEL2};font-size:15px;margin-left:10px'>Punteggio {r['composite']:.0f}</span>"
             if r.get("composite") is not None else "")
    st.markdown(f"<div class='ios-card'><div style='margin-bottom:6px'><span class='ios-chip'>{esc(r['ticker'])}</span>"
                f"<span style='color:{LABEL2};font-size:15px'>{esc(r['name'])}</span></div>{price}"
                f"<div style='margin-top:10px'>{badge(r['verdict_label'], color)}{score}</div></div>",
                unsafe_allow_html=True)

    plan = r.get("plan")
    if plan:
        operative = r["verdict"] != "scartato"
        section("Piano" if operative else "Piano indicativo",
                plan["setup"] if operative else "Il titolo non supera i filtri: livelli mostrati solo per trasparenza.")
        exit_date = (f"Uscita a tempo entro il {pd.Timestamp(plan['time_stop_date']).strftime('%d/%m/%Y')}"
                     if plan.get("time_stop_date") else "")
        tiles([
            ("Entrata", money(plan["entry"], cur), plan["order"], LABEL),
            ("Stop", money(plan["stop"], cur), f"Perdita massima {pct(plan['max_loss_pct'])}", RED),
            ("Target", money(plan["target"], cur), plan["target_basis"], GREEN),
            ("Ritorno netto", pct(plan["net_pct"]), f"Lordo {pct(plan['gross_pct'])}",
             GREEN if plan["net_pct"] > 0 else RED),
            ("Tempo stimato", months_text(plan), exit_date, LABEL),
            ("Rendimento/rischio", f"{plan['rr']:.1f}", f"Minimo richiesto {MIN_RR:.0f}",
             GREEN if plan["rr"] >= MIN_RR else RED),
        ])

    if r.get("exclusions"):
        section("Perché è scartato")
        list_rows([(x, "", RED) for x in r["exclusions"]])
    if r.get("warnings"):
        section("Da sapere")
        list_rows([(x, "", ORANGE) for x in r["warnings"]])

    s, lab = r.get("scores") or {}, r.get("labels") or {}
    if s:
        section("Punteggi", "Da 0 a 100, con il peso di ciascuno nel punteggio finale")
        sector_note = ((f"{lab.get('sector')}: {lab.get('sector_regime', '')}"
                        + (f" · {lab.get('sector_source')}" if lab.get("sector_source") else ""))
                       if lab.get("sector") else "Settore non disponibile")
        score_rows([
            ("Grafico", int(WEIGHTS["chart"] * 100), s.get("chart"), lab.get("stage", "")),
            ("Fondamentali", int(WEIGHTS["fundamentals"] * 100), s.get("fundamentals"), lab.get("valuation", "")),
            ("Trend di mercato", int(WEIGHTS["trend"] * 100), s.get("trend"),
             f"{lab.get('index', '')}: {lab.get('regime', '')}"),
            ("Trend di settore", int(WEIGHTS["sector"] * 100), s.get("sector"), sector_note),
            ("Sentiment", int(WEIGHTS["sentiment"] * 100), s.get("sentiment"), sentiment_note(r)),
        ])

    d = r.get("details") or {}
    if d.get("headlines"):
        section("Notizie recenti", "Il tono di ogni titolo è valutato automaticamente")
        list_rows([(h["title"], h.get("publisher") or "", tone_color(h["tone"])) for h in d["headlines"]])
    if r.get("polymarket"):
        section("Polymarket", "Solo informativo: non entra nel punteggio")
        list_rows([(m["question"],
                    " · ".join(f"{o} {p * 100:.0f}%" for o, p in m["outcomes"])
                    + f" · scadenza {m['end'] or 'n.d.'} · volume {m['volume']:,.0f} $", BLUE)
                   for m in r["polymarket"]])

    if d:
        with st.expander("Come è stato calcolato"):
            def num(v, dec=2, suffix=""):
                return "n.d." if v is None else f"{v:,.{dec}f}{suffix}"
            rows = [
                ("Settore", d.get("sector", "n.d."), d.get("sector_raw") or ""),
                ("P/E", num(d.get("pe"), 1), f"riferimento di settore {num(d.get('pe_ref'), 0)}"),
                ("EV/EBITDA", num(d.get("ev_ebitda"), 1), f"riferimento di settore {num(d.get('ev_ebitda_ref'), 0)}"),
                ("P/B", num(d.get("pb"), 2), f"riferimento di settore {num(d.get('pb_ref'), 1)}"),
                ("Rendimento del free cash flow", num(d.get("fcf_yield"), 1, "%"), ""),
                ("Margine netto", num(d.get("margin"), 1, "%"), ""),
                ("ROE", num(d.get("roe"), 1, "%"), ""),
                ("Crescita dei ricavi", num(d.get("growth"), 1, "%"), ""),
                ("Debito/patrimonio", num(d.get("debt_equity"), 2), ""),
                ("Target medio analisti", num(d.get("analyst_target"), 2), f"{d.get('n_analysts', 0)} analisti"),
                ("Giudizio medio analisti", num(d.get("recommendation_mean"), 2), "1 = acquisto forte, 5 = vendita"),
                ("Short interest", num(d.get("short_pct"), 1, "%"), "azioni vendute allo scoperto"),
                ("Tono delle notizie", num(d.get("news_tone"), 2), f"{d.get('news_count', 0)} titoli, da -1 a +1"),
                ("Forza relativa vs indice", num(d.get("relative_strength"), 1, " punti"), "ultimi 3 mesi"),
                ("Forza relativa vs settore", num(d.get("sector_relative_strength"), 1, " punti"), "ultimi 3 mesi"),
                ("RSI 14", num(d.get("rsi"), 0), ""),
                ("ATR 14", num(d.get("atr"), 2), "oscillazione media giornaliera"),
                ("Media a 20 giorni", num(d.get("ma20"), 2), ""),
                ("Media a 150 giorni", num(d.get("ma150"), 2), f"pendenza {num(d.get('ma150_slope'), 1, '%')} in 20 sedute"),
                ("Base recente", f"{num(d.get('base_low'))} – {num(d.get('base_high'))}", "ultime 40 sedute"),
                ("Massimo a 52 settimane", num(d.get("high_52w"), 2), ""),
            ]
            list_rows([(f"{name}: {value}", note, None) for name, value, note in rows])


# ── Selezione dei mercati (pillole) ──────────────────────────────────────────
def _set_state(key, value):
    st.session_state[key] = value


def market_picker(prefix: str, default_eu, default_us):
    for key, default in ((f"{prefix}_eu", default_eu), (f"{prefix}_us", default_us)):
        if key not in st.session_state:
            st.session_state[key] = list(default)
    st.pills("Europa", EUROPE_EXCHANGES, selection_mode="multi", key=f"{prefix}_eu")
    c1, c2, _ = st.columns([1.2, 1, 2.5])
    c1.button("Tutta l'Europa", key=f"{prefix}_all", on_click=_set_state,
              args=(f"{prefix}_eu", list(EUROPE_EXCHANGES)), width="stretch")
    c2.button("Nessuna", key=f"{prefix}_none", on_click=_set_state, args=(f"{prefix}_eu", []), width="stretch")
    st.pills("Stati Uniti", US_UNIVERSES, selection_mode="multi", key=f"{prefix}_us",
             format_func=lambda x: x.replace(" (USA)", ""))
    eu = st.session_state.get(f"{prefix}_eu") or []
    us = st.session_state.get(f"{prefix}_us") or []
    return eu, us, sum(APPROX_COUNTS.get(x, 0) for x in eu + us)


def segmented(label: str, options, default, key: str, **kw):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.segmented_control(label, options, key=key, required=True, **kw) or default


# ── Pagina ────────────────────────────────────────────────────────────────────
try:
    st.page_link("app.py", label="Stock Viewer", icon=":material/chevron_left:")
except Exception:
    st.markdown("[‹ Stock Viewer](/)")
large_title("Opportunità", "Titoli sottovalutati con un grafico favorevole, per operazioni da 1 a 6 mesi.")
view = segmented("Sezione", ["Cerca", "Analizza", "Backtest"], "Cerca", "view", label_visibility="collapsed")


if view == "Analizza":
    query = st.text_input("Titolo", placeholder="Cerca un'azienda o un ticker",
                          label_visibility="collapsed", key="single_q").strip()
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
                choice = st.selectbox("Risultati", labels)
                ticker = matches[labels.index(choice)]["symbol"]
                with st.spinner(f"Analizzo {ticker}…"):
                    render_result(cached_analysis(ticker, get_fmp_key()))
            else:
                footnote("Nessun titolo trovato. Prova con il nome dell'azienda o con il ticker completo di borsa, "
                         "per esempio AAPL o ENI.MI.")
    else:
        footnote("Scrivi il nome di un'azienda, per esempio Ferrari, oppure il ticker, per esempio RACE.MI.")


elif view == "Cerca":
    with st.container(border=True, key="scan_box"):
        eu, us, approx = market_picker("scan", [], ["S&P 500 (USA)"])
        extra = st.text_input("Altri ticker (facoltativo)", placeholder="Es. BC.MI, ASML.AS",
                              key="scan_extra")
        n_markets = len(eu) + len(us)
        footnote(f"{n_markets} {'mercato selezionato' if n_markets == 1 else 'mercati selezionati'} · circa {approx} titoli"
                 + (" · qualche minuto" if approx > 300 else "") if n_markets else "Scegli almeno un mercato.")
        run = st.button("Cerca opportunità", type="primary", key="scan_run", width="stretch",
                        disabled=not (n_markets or extra.strip()))

    if run:
        tickers, failed, sources, raw_sectors = [], {}, {}, {}
        status = st.empty()
        jobs = [(n, lambda n=n: load_exchange(n)) for n in eu]
        jobs += [(n, lambda n=n: load_universe(n)) for n in us]
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
            st.warning("Elenco non disponibile per: " + ", ".join(failed) + ". Riprova tra qualche minuto.")
            with st.expander("Dettagli dell'errore"):
                list_rows([(name, error, RED) for name, error in failed.items()])

        if tickers:
            fmp_key = get_fmp_key()
            groups = {tuple(index_candidates_for(t)) for t in tickers}
            index_map = {g: cached_resolved_index(g) for g in groups}
            progress = st.progress(0.0, text=f"Scarico i prezzi di {len(tickers)} titoli…")
            hists = bulk_history(tickers, on_progress=lambda done, total: progress.progress(
                done / total * 0.5, text=f"Prezzi scaricati per {done} di {total} titoli"))

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
                etfs = sorted({b["etf"] for t in survivors if (b := sector_benchmark(t, raw_sectors.get(t)))})
                if etfs:
                    progress.progress(0.5, text=f"Scarico l'andamento di {len(etfs)} settori…")
                    for symbol, etf_hist in bulk_history(etfs).items():
                        _SECTOR_HISTORY[symbol] = (time.time(), etf_hist)
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

                progress.progress(0.5, text=f"Analizzo {len(survivors)} titoli promettenti…")
                with cf.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = []
                    for t in survivors:
                        idx_symbol, idx_hist = index_map[tuple(index_candidates_for(t))]
                        futures.append(pool.submit(analyze_with_history, t, hists[t], idx_hist, idx_symbol,
                                                   fmp_key, raw_sectors.get(t), peers))
                    for i, fut in enumerate(cf.as_completed(futures), start=1):
                        results.append(fut.result())
                        progress.progress(0.5 + 0.5 * i / len(survivors),
                                          text=f"Analizzati {i} di {len(survivors)} titoli promettenti")
            progress.empty()
            st.session_state["scan_results"] = sorted(results, key=sort_key)
            st.session_state["scan_sources"] = sources

    results = st.session_state.get("scan_results")
    if results:
        not_loaded = [r for r in results if r.get("exclusions", [None])[:1] == [DOWNLOAD_FAILED]]
        selected = [r for r in results if r["verdict"] != "scartato"]
        rejected = [r for r in results if r["verdict"] == "scartato" and r not in not_loaded]
        section(f"{len(selected)} opportunità",
                f"Su {len(results) - len(not_loaded)} titoli analizzati, dal punteggio più alto.")
        if not_loaded:
            st.warning(f"{len(not_loaded)} titoli non analizzati perché Yahoo ha limitato le richieste: "
                       "rilancia la ricerca tra qualche minuto.")
        if selected:
            mode = segmented("Vista", ["Elenco", "Tabella"], "Elenco", "res_mode", label_visibility="collapsed")
            if mode == "Elenco":
                rows = ""
                for r in selected:
                    p = r["plan"]
                    net_color = GREEN if p["net_pct"] > 0 else RED
                    rows += (f"<div class='ios-row' style='display:flex;justify-content:space-between;gap:12px'>"
                             f"<div><span class='ios-dot' style='background:{VERDICT_COLORS[r['verdict']]}'></span>"
                             f"<b>{esc(r['ticker'])}</b> <span style='color:{LABEL2}'>{esc((r['name'] or '')[:30])}</span>"
                             f"<span class='sub'>Entrata {p['entry']:,.2f} · Target {p['target']:,.2f} · "
                             f"{months_text(p)} · punteggio {r['composite']:.0f}</span></div>"
                             f"<div style='text-align:right;white-space:nowrap'><span style='color:{net_color};"
                             f"font-weight:600'>{p['net_pct']:+.1f}%</span><span class='sub'>netto</span></div></div>")
                st.markdown(f"<div class='ios-list'>{rows}</div>", unsafe_allow_html=True)
            else:
                html_table(pd.DataFrame([{
                    "Titolo": r["ticker"], "Esito": r["verdict_label"], "Punteggio": r["composite"],
                    "Entrata": r["plan"]["entry"], "Stop": r["plan"]["stop"], "Target": r["plan"]["target"],
                    "Netto %": r["plan"]["net_pct"], "Tempo": months_text(r["plan"]), "R/R": r["plan"]["rr"],
                } for r in selected]), formats={
                    "Punteggio": lambda v: f"{v:.0f}", "Entrata": lambda v: f"{v:,.2f}",
                    "Stop": lambda v: f"{v:,.2f}", "Target": lambda v: f"{v:,.2f}",
                    "Netto %": lambda v: f"{v:+.2f}%", "R/R": lambda v: f"{v:.1f}"},
                    colors={"Netto %": lambda v: GREEN if v > 0 else RED})

            section("Dettaglio")
            options = [f"{r['ticker']} — {r['name']}" for r in selected]
            choice = st.selectbox("Titolo", options, label_visibility="collapsed", key="detail_pick")
            render_result(selected[options.index(choice)])
        else:
            footnote("Nessun titolo supera tutti i filtri in questo momento.")

        if st.session_state.get("scan_sources"):
            footnote("Elenchi letti: " + " · ".join(f"{k} {v}" for k, v in st.session_state["scan_sources"].items()))
        if rejected:
            with st.expander(f"Titoli scartati ({len(rejected)}) e motivi"):
                reasons = Counter(re.sub(r"[-+]?\d[\d.,]*", "…", r["exclusions"][0])
                                  for r in rejected if r.get("exclusions"))
                html_table(pd.DataFrame(reasons.most_common(), columns=["Motivo", "Titoli"]))
                list_rows([(r["ticker"], r["exclusions"][0] if r.get("exclusions") else "", None)
                           for r in rejected])


# ── Backtest ──────────────────────────────────────────────────────────────────
def render_backtest(bt: dict):
    trades, counts = bt["trades"], bt["counts"]
    caption = (f"{bt['n_tickers']} titoli, {bt['years']} {'anno' if bt['years'] == 1 else 'anni'} · "
               f"{counts['segnali']} segnali, {counts['non_eseguiti']} ordini mai eseguiti · "
               f"trend di settore per {bt['sector_coverage']} titoli")
    if counts.get("saltati"):
        caption += f" · {counts['saltati']} controlli saltati per dati anomali"
    section("Risultati", caption)
    summary = summarize(trades) if not trades.empty else {"chiuse": 0}
    if summary["chiuse"] == 0:
        st.info("Nessuna operazione chiusa nel periodo: prova con più mercati o un periodo più lungo.")
        return

    extra = summary["extra_vs_indice"]
    good = summary["media_netta"] > 0 and (extra is None or extra > 0)
    verdict = (f"In media ogni operazione ha reso <b style='color:{GREEN if summary['media_netta'] > 0 else RED}'>"
               f"{summary['media_netta']:+.2f}%</b> netto"
               + (f", <b>{extra:+.2f} punti</b> rispetto all'indice negli stessi giorni" if extra is not None else "")
               + (". Risultato in linea con l'indice: nessun vantaggio chiaro." if extra is not None and abs(extra) <= 0.5
                  else ". Il modello ha aggiunto valore." if good
                  else ". Così com'è, il modello non ha aggiunto valore."))
    st.markdown(f"<div class='ios-callout'>{verdict}</div>", unsafe_allow_html=True)

    in_time, early = summary["target_nei_tempi_pct"], summary["target_prima_pct"]
    tiles([
        ("Operazioni chiuse", f"{summary['chiuse']}", f"{summary['in_corso']} ancora aperte", LABEL),
        ("In guadagno", f"{summary['win_pct']:.0f}%", f"operazione tipica {summary['mediana_lorda']:+.2f}% lordo", LABEL),
        ("Netto medio", f"{summary['media_netta']:+.2f}%",
         f"lordo {summary['media_lorda']:+.2f}%, tasse sul risultato complessivo",
         GREEN if summary["media_netta"] > 0 else RED),
        ("Rispetto all'indice", f"{extra:+.2f}" if extra is not None else "n.d.", "punti, a parità di giorni",
         GREEN if (extra or 0) > 0 else RED),
        ("Chiuse al target", f"{summary['target_pct']:.0f}%", "", GREEN),
        ("Chiuse allo stop", f"{summary['stop_pct']:.0f}%", "", RED),
        ("Uscite a tempo", f"{summary['scadenza_pct']:.0f}%", "", LABEL),
        ("Durata media", f"{summary['giorni_medi']:.0f} sedute",
         (f"target nei tempi stimati {in_time:.0f}%, prima del previsto {early:.0f}%"
          if in_time is not None else ""), LABEL),
    ], per_row=4)

    closed = trades[trades["outcome"] != "in corso"].sort_values("exit_date")
    section("Andamento cumulato", "Somma dei rendimenti delle operazioni chiuse prima delle tasse, a importo uguale")
    curve = closed.set_index("exit_date")["gross_pct"].cumsum()
    fig = go.Figure(go.Scatter(x=curve.index, y=curve.values, mode="lines",
                               line=dict(color=BLUE, width=2.5), fill="tozeroy",
                               fillcolor="rgba(0,122,255,0.10)"))
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", height=260,
                      margin=dict(l=0, r=0, t=6, b=0), font=dict(color=LABEL2),
                      xaxis=dict(showgrid=False), yaxis=dict(gridcolor=SEPARATOR, ticksuffix="%", side="right"))
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    section("Cosa funziona", "Scegli come scomporre i risultati")
    closed = closed.assign(fascia=closed["score"].apply(score_bucket),
                           fase=closed["stage"].map(STAGE_NAMES).fillna("altro"))
    by = segmented("Scomposizione", ["Punteggio", "Settore", "Grafico", "Entrata"], "Punteggio", "bt_by",
                   label_visibility="collapsed")
    column = {"Punteggio": "fascia", "Settore": "sector_regime", "Grafico": "fase", "Entrata": "order"}[by]
    table = breakdown(closed, column)
    table.index.name = {"fascia": "Punteggio", "sector_regime": "Tendenza del settore",
                        "fase": "Fase del grafico", "order": "Tipo di entrata"}[column]
    percent = lambda v: f"{v:.0f}%"
    signed = lambda v: f"{v:+.2f}%"
    html_table(table, index=True,
               formats={"Operazioni": lambda v: f"{v:.0f}", "Target %": percent, "Stop %": percent,
                        "In guadagno %": percent, "Netto medio %": signed, "Extra vs indice %": signed},
               colors={"Netto medio %": lambda v: GREEN if v > 0 else RED,
                       "Extra vs indice %": lambda v: GREEN if v > 0 else RED})

    with st.expander("Tutte le operazioni"):
        view_df = trades.copy()
        for col in ("signal_date", "fill_date", "exit_date"):
            view_df[col] = pd.to_datetime(view_df[col]).dt.strftime("%d/%m/%Y")
        st.dataframe(view_df[["ticker", "signal_date", "fill_date", "exit_date", "outcome", "fill_price",
                              "exit_price", "gross_pct", "excess_pct", "days", "score",
                              "sector_regime"]].round(2), hide_index=True, width="stretch")
    footnote("Limiti: gli elenchi dei titoli sono quelli di oggi, quindi mancano le società uscite dagli indici "
             "o fallite (risultati un po' ottimistici); i settori sono quelli attuali; costi ipotizzati 0,15% per "
             "lato; imposta del 26% sul risultato complessivo, con le perdite che compensano i guadagni (verifica "
             "il regime fiscale del tuo conto). Fondamentali e sentiment non sono verificabili sul passato.")


if view == "Backtest":
    with st.container(border=True, key="bt_box"):
        footnote("Il modello rigioca le sue regole sul passato, con i soli dati disponibili in ogni data, e segue "
                 "ogni operazione fino a target, stop o uscita a tempo.")
        bt_eu, bt_us, bt_approx = market_picker("bt", ["Milano"], [])
        c1, c2 = st.columns(2)
        with c1:
            period = segmented("Periodo", ["1 anno", "2 anni", "3 anni"], "2 anni", "bt_period")
        with c2:
            frequency = segmented("Controlli", ["Ogni mese", "Ogni 2 settimane"], "Ogni mese", "bt_freq")
        footnote(f"Circa {bt_approx} titoli" + (" · può richiedere diversi minuti" if bt_approx > 300 else ""))
        run_bt = st.button("Avvia backtest", type="primary", key="bt_run", width="stretch",
                           disabled=not (bt_eu or bt_us))

    if run_bt:
        bt_years = int(period.split()[0])
        bt_step = 21 if frequency == "Ogni mese" else 10
        tickers, raw_sectors = [], {}
        for name in bt_eu:
            symbols, _, _, sectors = load_exchange(name)
            tickers += symbols; raw_sectors.update(sectors)
        for name in bt_us:
            symbols, _, _, sectors = load_universe(name)
            tickers += symbols; raw_sectors.update(sectors)
        tickers = [t for t in dict.fromkeys(tickers) if not looks_like_fund(raw_sectors.get(t))]
        if not tickers:
            st.warning("Nessun titolo da analizzare.")
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

st.markdown("<div class='ios-caption' style='margin-top:36px;text-align:center'>"
            "Stime basate sui dati storici, non garanzie.</div>", unsafe_allow_html=True)
