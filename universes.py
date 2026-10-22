"""
Elenchi dei titoli degli indici, letti da Wikipedia (aggiornati dalla comunità).
Nessuna dipendenza da Streamlit: si può testare da solo.
"""
import io
import re
import time

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockViewer/1.0)"}

UNIVERSES = {
    "S&P 500 (USA)": {
        "url": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
        "suffix": "", "columns": ["Symbol", "Ticker"]},
    "Nasdaq 100 (USA)": {
        "url": "https://en.wikipedia.org/wiki/Nasdaq-100",
        "suffix": "", "columns": ["Ticker", "Symbol"]},
    "FTSE MIB (Italia)": {
        "url": "https://en.wikipedia.org/wiki/FTSE_MIB",
        "suffix": ".MI", "columns": ["Ticker"]},
    "DAX (Germania)": {
        "url": "https://en.wikipedia.org/wiki/DAX",
        "suffix": ".DE", "columns": ["Ticker", "Ticker symbol"]},
    "CAC 40 (Francia)": {
        "url": "https://en.wikipedia.org/wiki/CAC_40",
        "suffix": ".PA", "columns": ["Ticker"]},
    "FTSE 100 (Regno Unito)": {
        "url": "https://en.wikipedia.org/wiki/FTSE_100_Index",
        "suffix": ".L", "columns": ["Ticker", "EPIC"]},
}

EXCHANGE_CODES = {"MI", "DE", "F", "PA", "L", "AS", "MC", "BR", "SW", "LS", "VI", "HE", "IR"}


def clean_symbol(raw, suffix: str):
    """Trasforma il ticker di Wikipedia nel formato di Yahoo Finance."""
    s = re.sub(r"\[.*?\]", "", str(raw)).strip()     # note a piè di pagina
    if not s or s.lower() == "nan":
        return None
    s = s.split()[0]
    if ":" in s:                                      # es. "BIT:ENI"
        s = s.split(":")[-1]
    s = s.upper().rstrip(".")                           # es. "RR." → "RR"
    if not suffix:
        return s.replace(".", "-")                    # BRK.B → BRK-B
    if "." in s and s.rsplit(".", 1)[1] in EXCHANGE_CODES:
        return s                                      # suffisso già presente
    return s.replace(".", "-") + suffix               # BT.A → BT-A.L


def parse_constituents(html: str, columns, suffix: str):
    """Cerca nella pagina la tabella dei componenti e ne estrae i ticker."""
    for table in pd.read_html(io.StringIO(html)):
        if len(table) < 20:
            continue
        labels = {}
        for col in table.columns:
            label = col[-1] if isinstance(col, tuple) else col
            labels[str(label).strip()] = col
        for name in columns:
            if name in labels:
                symbols = [clean_symbol(v, suffix) for v in table[labels[name]].tolist()]
                symbols = [s for s in dict.fromkeys(symbols) if s]
                if len(symbols) >= 20:
                    return symbols
    return []


def fetch_universe(name: str):
    cfg = UNIVERSES[name]
    response = requests.get(cfg["url"], headers=HEADERS, timeout=20)
    response.raise_for_status()
    return parse_constituents(response.text, cfg["columns"], cfg["suffix"])


# ══════════════════════════════════════════════════════════════════════════════
# BORSE INTERE — tutte le società quotate, lette dallo screener di Yahoo Finance
# ══════════════════════════════════════════════════════════════════════════════
# fx = unità di valuta locale per 1 euro (approssimata): serve a tradurre la
# capitalizzazione minima in euro nella valuta in cui Yahoo la esprime.
# fallback = indice Wikipedia usato se lo screener di Yahoo non risponde.
EXCHANGES = {
    "Milano":              {"codes": ["MIL"], "region": "it", "suffix": ".MI", "fx": 1.0,  "fallback": "FTSE MIB (Italia)"},
    "Francoforte (Xetra)": {"codes": ["GER"], "region": "de", "suffix": ".DE", "fx": 1.0,  "fallback": "DAX (Germania)"},
    "Parigi":              {"codes": ["PAR"], "region": "fr", "suffix": ".PA", "fx": 1.0,  "fallback": "CAC 40 (Francia)"},
    "Londra":              {"codes": ["LSE"], "region": "gb", "suffix": ".L",  "fx": 0.87, "fallback": "FTSE 100 (Regno Unito)"},
    "Amsterdam":           {"codes": ["AMS"], "region": "nl", "suffix": ".AS", "fx": 1.0},
    "Madrid":              {"codes": ["MCE"], "region": "es", "suffix": ".MC", "fx": 1.0},
    "Zurigo":              {"codes": ["EBS"], "region": "ch", "suffix": ".SW", "fx": 0.94},
    "Bruxelles":           {"codes": ["BRU"], "region": "be", "suffix": ".BR", "fx": 1.0},
    "Lisbona":             {"codes": ["LIS"], "region": "pt", "suffix": ".LS", "fx": 1.0},
    "Vienna":              {"codes": ["VIE"], "region": "at", "suffix": ".VI", "fx": 1.0},
    "Dublino":             {"codes": ["ISE"], "region": "ie", "suffix": ".IR", "fx": 1.0},
    "Stoccolma":           {"codes": ["STO"], "region": "se", "suffix": ".ST", "fx": 11.5},
    "Copenaghen":          {"codes": ["CPH"], "region": "dk", "suffix": ".CO", "fx": 7.46},
    "Helsinki":            {"codes": ["HEL"], "region": "fi", "suffix": ".HE", "fx": 1.0},
    "Oslo":                {"codes": ["OSL"], "region": "no", "suffix": ".OL", "fx": 11.7},
    "Varsavia":            {"codes": ["WSE"], "region": "pl", "suffix": ".WA", "fx": 4.3},
}
EUROPE_EXCHANGES = list(EXCHANGES)
PAGE_SIZE = 250            # massimo consentito da Yahoo per richiesta


def _screen_symbols(query, sort_field, max_pages: int, pause: float):
    import yfinance as yf
    symbols = []
    for page in range(max_pages):
        kwargs = {"offset": page * PAGE_SIZE, "size": PAGE_SIZE}
        if sort_field:
            kwargs.update(sortField=sort_field, sortAsc=False)
        try:
            result = yf.screen(query, **kwargs)
        except Exception:
            if page == 0:
                raise
            break                                   # pagine successive: teniamo quello che abbiamo
        quotes = result.get("quotes", []) if isinstance(result, dict) else []
        symbols += [q["symbol"].strip().upper() for q in quotes if q.get("symbol")]
        if len(quotes) < PAGE_SIZE:
            break
        time.sleep(pause)
    return symbols


def fetch_exchange(name: str, min_cap_eur_m: float = 1000, max_pages: int = 6, pause: float = 0.7,
                   use_fallback: bool = True):
    """
    Titoli di una borsa sopra la capitalizzazione minima (milioni di euro).
    Prova più richieste a Yahoo, poi l'indice di Wikipedia. Restituisce (ticker, fonte).
    Se tutto fallisce solleva RuntimeError con il dettaglio di ogni tentativo.
    """
    from yfinance import EquityQuery

    cfg = EXCHANGES[name]
    cap = EquityQuery("gt", ["intradaymarketcap", float(min_cap_eur_m) * 1e6 * cfg["fx"]])
    region = EquityQuery("eq", ["region", cfg["region"]])
    exchange = EquityQuery("is-in", ["exchange", *cfg["codes"]])
    attempts = [
        ("Yahoo, borsa", EquityQuery("and", [region, exchange, cap]), "intradaymarketcap"),
        ("Yahoo, paese", EquityQuery("and", [region, cap]), "intradaymarketcap"),
        ("Yahoo, paese", EquityQuery("and", [region, cap]), None),
    ]
    errors = []
    for label, query, sort_field in attempts:
        try:
            symbols = [s for s in _screen_symbols(query, sort_field, max_pages, pause)
                       if s.endswith(cfg["suffix"])]
        except Exception as e:
            errors.append(f"{label}: {type(e).__name__}: {str(e)[:150]}")
            continue
        if symbols:
            return list(dict.fromkeys(symbols)), label
        errors.append(f"{label}: elenco vuoto")

    if use_fallback and cfg.get("fallback"):
        try:
            symbols = fetch_universe(cfg["fallback"])
            if symbols:
                return symbols, f"Wikipedia, solo {cfg['fallback'].split(' (')[0]}"
            errors.append("Wikipedia: elenco vuoto")
        except Exception as e:
            errors.append(f"Wikipedia: {type(e).__name__}: {str(e)[:150]}")
    raise RuntimeError(" | ".join(errors))
