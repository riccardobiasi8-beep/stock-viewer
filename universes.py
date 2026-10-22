"""
Elenchi dei titoli degli indici, letti da Wikipedia (aggiornati dalla comunità).
Nessuna dipendenza da Streamlit: si può testare da solo.
"""
import io
import re

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
