"""
Elenchi dei titoli per indice e per borsa, letti da Wikipedia.
Nessuna dipendenza da Streamlit: si può testare da solo.
(Lo screener di Yahoo rifiuta le richieste dall'app con errore 401, quindi non si usa.)
"""
import io
import re

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StockViewer/1.0)"}


def _wiki(page: str) -> str:
    return "https://en.wikipedia.org/wiki/" + page


# suffix = suffisso Yahoo della borsa; min = righe minime perché la tabella sia
# credibile come elenco dei componenti (evita di leggere la tabella sbagliata)
UNIVERSES = {
    "S&P 500 (USA)":                 {"url": _wiki("List_of_S%26P_500_companies"), "suffix": "",    "min": 400, "region": "us"},
    "Nasdaq 100 (USA)":              {"url": _wiki("Nasdaq-100"),                  "suffix": "",    "min": 80,  "region": "us"},
    "FTSE MIB (Italia)":             {"url": _wiki("FTSE_MIB"),                    "suffix": ".MI", "min": 30,  "region": "eu"},
    "DAX (Germania)":                {"url": _wiki("DAX"),                         "suffix": ".DE", "min": 30,  "region": "eu"},
    "MDAX (Germania)":               {"url": _wiki("MDAX"),                        "suffix": ".DE", "min": 30,  "region": "eu"},
    "SDAX (Germania)":               {"url": _wiki("SDAX"),                        "suffix": ".DE", "min": 30,  "region": "eu"},
    "CAC 40 (Francia)":              {"url": _wiki("CAC_40"),                      "suffix": ".PA", "min": 30,  "region": "eu"},
    "FTSE 100 (Regno Unito)":        {"url": _wiki("FTSE_100_Index"),              "suffix": ".L",  "min": 80,  "region": "eu"},
    "FTSE 250 (Regno Unito)":        {"url": _wiki("FTSE_250_Index"),              "suffix": ".L",  "min": 150, "region": "eu"},
    "AEX (Paesi Bassi)":             {"url": _wiki("AEX_index"),                   "suffix": ".AS", "min": 15,  "region": "eu"},
    "AMX (Paesi Bassi)":             {"url": _wiki("AMX_index"),                   "suffix": ".AS", "min": 15,  "region": "eu"},
    "IBEX 35 (Spagna)":              {"url": _wiki("IBEX_35"),                     "suffix": ".MC", "min": 25,  "region": "eu"},
    "SMI (Svizzera)":                {"url": _wiki("Swiss_Market_Index"),          "suffix": ".SW", "min": 15,  "region": "eu"},
    "BEL 20 (Belgio)":               {"url": _wiki("BEL_20"),                      "suffix": ".BR", "min": 15,  "region": "eu"},
    "PSI (Portogallo)":              {"url": _wiki("PSI-20"),                      "suffix": ".LS", "min": 10,  "region": "eu"},
    # Wikipedia elenca solo i nomi delle società: ticker trascritti dalla composizione di aprile 2026
    "ATX (Austria)":                 {"region": "eu", "as_of": "aprile 2026", "tickers": [
        "EBS.VI", "VER.VI", "OMV.VI", "BG.VI", "ANDR.VI", "WIE.VI", "VOE.VI", "RBI.VI", "POS.VI",
        "CAI.VI", "EVN.VI", "ATS.VI", "POST.VI", "VIG.VI", "LNZ.VI", "UQA.VI", "SBO.VI", "IIA.VI",
        "STR.VI", "DOC.VI"]},
    "ISEQ 20 (Irlanda)":             {"url": _wiki("ISEQ_20"),                     "suffix": ".IR", "min": 15,  "region": "eu"},
    "OMX Stockholm 30 (Svezia)":     {"url": _wiki("OMX_Stockholm_30"),            "suffix": ".ST", "min": 25,  "region": "eu"},
    "OMX Copenhagen 25 (Danimarca)": {"url": _wiki("OMX_Copenhagen_25"),           "suffix": ".CO", "min": 20,  "region": "eu"},
    "OMX Helsinki 25 (Finlandia)":   {"url": _wiki("OMX_Helsinki_25"),             "suffix": ".HE", "min": 20,  "region": "eu"},
    "OBX (Norvegia)":                {"url": _wiki("OBX_Index"),                   "suffix": ".OL", "min": 20,  "region": "eu"},
    # Wikipedia non ha una tabella dei componenti: principali titoli di Varsavia, elenco curato
    "Varsavia, principali titoli (Polonia)": {"region": "eu", "as_of": "elenco curato", "tickers": [
        "PKO.WA", "PKN.WA", "PEO.WA", "PZU.WA", "KGH.WA", "LPP.WA", "ALE.WA", "CDR.WA", "DNP.WA",
        "MBK.WA", "SPL.WA", "ALR.WA", "BDX.WA", "KRU.WA", "PGE.WA", "OPL.WA", "KTY.WA", "PCO.WA",
        "CCC.WA", "ZAB.WA", "JSW.WA"]},
}

# Per ogni borsa, gli indici che ne coprono i titoli principali
EXCHANGES = {
    "Milano":              ["FTSE MIB (Italia)"],
    "Francoforte (Xetra)": ["DAX (Germania)", "MDAX (Germania)", "SDAX (Germania)"],
    "Parigi":              ["CAC 40 (Francia)"],
    "Londra":              ["FTSE 100 (Regno Unito)", "FTSE 250 (Regno Unito)"],
    "Amsterdam":           ["AEX (Paesi Bassi)", "AMX (Paesi Bassi)"],
    "Madrid":              ["IBEX 35 (Spagna)"],
    "Zurigo":              ["SMI (Svizzera)"],
    "Bruxelles":           ["BEL 20 (Belgio)"],
    "Lisbona":             ["PSI (Portogallo)"],
    "Vienna":              ["ATX (Austria)"],
    "Dublino":             ["ISEQ 20 (Irlanda)"],
    "Stoccolma":           ["OMX Stockholm 30 (Svezia)"],
    "Copenaghen":          ["OMX Copenhagen 25 (Danimarca)"],
    "Helsinki":            ["OMX Helsinki 25 (Finlandia)"],
    "Oslo":                ["OBX (Norvegia)"],
    "Varsavia":            ["Varsavia, principali titoli (Polonia)"],
}
EUROPE_EXCHANGES = list(EXCHANGES)
US_UNIVERSES = [k for k, v in UNIVERSES.items() if v["region"] == "us"]

TICKER_COLUMNS = ["Ticker", "Symbol", "Ticker symbol", "EPIC", "TIDM", "MNEM code", "Mnemonic",
                  "Code", "Stock symbol", "Trading symbol"]
TICKER_WORDS = ("ticker", "symbol", "mnem", "epic", "tidm")   # per nomi di colonna non previsti
EXCHANGE_CODES = {"MI", "DE", "F", "PA", "L", "AS", "MC", "BR", "SW", "LS", "VI",
                  "HE", "IR", "ST", "CO", "OL", "WA"}
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9&\-]{0,11}(\.[A-Z]{1,3})?$")


def clean_symbol(raw, suffix: str):
    """Trasforma il ticker di Wikipedia nel formato di Yahoo Finance; None se non valido."""
    s = re.sub(r"\[.*?\]", "", str(raw)).strip()           # note a piè di pagina
    if not s or s.lower() in ("nan", "-", "—"):
        return None
    if ":" in s:                                            # "BIT:ENI", "BME: SAN"
        s = s.split(":")[-1].strip()
    tokens = s.upper().split()
    if not tokens:
        return None
    if len(tokens) >= 2 and re.fullmatch(r"[A-Z]{1,2}", tokens[1]):
        s = f"{tokens[0]}-{tokens[1]}"                      # "VOLV B" → "VOLV-B"
    else:
        s = tokens[0]
    s = s.rstrip(".")                                       # "RR." → "RR"
    if not s:
        return None
    if not suffix:
        s = s.replace(".", "-")                             # BRK.B → BRK-B
    elif "." in s and s.rsplit(".", 1)[1] in EXCHANGE_CODES:
        pass                                                # già nel formato Yahoo
    else:
        s = s.replace(".", "-") + suffix                    # BT.A → BT-A.L
    return s if TICKER_RE.match(s) and re.search(r"[A-Z]", s) else None


def _clean_column(series, suffix):
    symbols = [clean_symbol(v, suffix) for v in series.tolist()]
    return [s for s in dict.fromkeys(symbols) if s]


def parse_constituents(html: str, suffix: str, min_size: int = 10, columns=None):
    """Cerca la tabella dei componenti e ne estrae i ticker."""
    tables = [t for t in pd.read_html(io.StringIO(html)) if len(t) >= min_size]
    names = columns or TICKER_COLUMNS
    # 1) colonne con un nome da ticker
    for table in tables:
        labels = {}
        for col in table.columns:
            label = col[-1] if isinstance(col, tuple) else col
            labels.setdefault(str(label).strip(), col)
        candidates = [n for n in names if n in labels]
        candidates += [l for l in labels if l not in candidates and "isin" not in l.lower()
                       and any(w in l.lower() for w in TICKER_WORDS)]
        for name in candidates:
            symbols = _clean_column(table[labels[name]], suffix)
            if len(symbols) >= min_size:
                return symbols
    # 2) riconoscimento automatico: colonna di valori brevi in maiuscolo
    isin = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")
    for table in tables:
        for col in table.columns:
            label = str(col[-1] if isinstance(col, tuple) else col).lower()
            raw = [str(v).strip() for v in table[col].dropna().tolist()]
            if not raw or "isin" in label or sum(bool(isin.match(v)) for v in raw) > len(raw) / 2:
                continue
            uppercase = sum(v == v.upper() and re.search(r"[A-Z]", v) is not None for v in raw)
            symbols = _clean_column(table[col], suffix)
            if uppercase >= 0.8 * len(raw) and len(symbols) >= max(min_size, 0.8 * len(raw)):
                return symbols
    return []


def fetch_universe(name: str):
    cfg = UNIVERSES[name]
    if "tickers" in cfg:
        return list(cfg["tickers"])
    response = requests.get(cfg["url"], headers=HEADERS, timeout=20)
    response.raise_for_status()
    return parse_constituents(response.text, cfg["suffix"], cfg["min"])
