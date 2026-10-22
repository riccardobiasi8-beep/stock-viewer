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
EXCHANGES = {
    "Milano":                  {"codes": ["MIL"], "fx": 1.0},
    "Francoforte (Xetra)":     {"codes": ["GER"], "fx": 1.0},
    "Parigi":                  {"codes": ["PAR"], "fx": 1.0},
    "Londra":                  {"codes": ["LSE"], "fx": 0.87},
    "Amsterdam":               {"codes": ["AMS"], "fx": 1.0},
    "Madrid":                  {"codes": ["MCE"], "fx": 1.0},
    "Zurigo":                  {"codes": ["EBS"], "fx": 0.94},
    "Bruxelles":               {"codes": ["BRU"], "fx": 1.0},
    "Lisbona":                 {"codes": ["LIS"], "fx": 1.0},
    "Vienna":                  {"codes": ["VIE"], "fx": 1.0},
    "Dublino":                 {"codes": ["ISE"], "fx": 1.0},
    "Stoccolma":               {"codes": ["STO"], "fx": 11.5},
    "Copenaghen":              {"codes": ["CPH"], "fx": 7.46},
    "Helsinki":                {"codes": ["HEL"], "fx": 1.0},
    "Oslo":                    {"codes": ["OSL"], "fx": 11.7},
    "Varsavia":                {"codes": ["WSE"], "fx": 4.3},
}
EUROPE_EXCHANGES = list(EXCHANGES)
PAGE_SIZE = 250            # massimo consentito da Yahoo per richiesta


def fetch_exchange(name: str, min_cap_eur_m: float = 1000, max_pages: int = 6, pause: float = 0.7):
    """
    Elenco dei titoli di una borsa con capitalizzazione sopra la soglia (milioni di euro).
    Ordinati dal più grande al più piccolo. Solleva un errore se la prima richiesta fallisce.
    """
    import yfinance as yf
    from yfinance import EquityQuery

    cfg = EXCHANGES[name]
    floor = float(min_cap_eur_m) * 1e6 * cfg["fx"]
    query = EquityQuery("and", [
        EquityQuery("is-in", ["exchange", *cfg["codes"]]),
        EquityQuery("gt", ["intradaymarketcap", floor]),
    ])

    symbols = []
    for page in range(max_pages):
        try:
            result = yf.screen(query, offset=page * PAGE_SIZE, size=PAGE_SIZE,
                               sortField="intradaymarketcap", sortAsc=False)
        except Exception:
            if page == 0:
                raise
            break                                   # pagine successive: teniamo quello che abbiamo
        quotes = result.get("quotes", []) if isinstance(result, dict) else []
        symbols += [q["symbol"].strip().upper() for q in quotes if q.get("symbol")]
        if len(quotes) < PAGE_SIZE:
            break
        time.sleep(pause)
    return list(dict.fromkeys(symbols))
