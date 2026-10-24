"""
Modello swing — orizzonte da 1 a 6 mesi.

Scopo: trovare titoli sottovalutati rispetto al settore che hanno anche un
setup tecnico favorevole, e proporre entrata, stop, target, ritorno e tempo.

Tutti i numeri sono calcolati qui in modo deterministico. Nessuna AI.
Questo file non usa Streamlit: si può testare da solo.

Livelli:
  1. Fondamentali  → filtro qualità + valutazione rispetto al settore
  2. Trend mercato → regime dell'indice di riferimento + forza relativa
  3. Grafico       → stadio di Weinstein + RSI
  4. Piano         → entrata, stop, target, rapporto R/R, tempo stimato
  (5. Sentiment    → fase successiva: Polymarket, revisioni analisti, insider)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ══════════════════════════════════════════════════════════════════════════════
# PARAMETRI — tutti qui, modificabili
# ══════════════════════════════════════════════════════════════════════════════
HORIZON_MAX_DAYS = 126          # ~6 mesi di sedute
MIN_RR = 2.0                    # guadagno potenziale almeno 2 volte la perdita
TAX_RATE = 0.26                 # imposta sulle plusvalenze
STOP_MIN_PCT = 0.05             # stop almeno al -5% dall'entrata
STOP_MAX_PCT = 0.10             # stop al massimo al -10% dall'entrata
ATR_STOP_MULT = 2.0             # stop = entrata - 2 × ATR (entro i limiti sopra)
TARGET_MAX_PCT = 0.35           # target al massimo +35% (orizzonte di pochi mesi)
BASE_WINDOW = 40                # sedute usate per definire la base recente
MIN_HISTORY = 260               # sedute minime di storico (~13 mesi)
MIN_LIQUIDITY_EUR = 500_000     # controvalore medio giornaliero minimo
EARNINGS_WARNING_DAYS = 14      # avviso se la trimestrale è entro 14 giorni
SLOPE_FLAT_PCT = 0.3            # media 150 gg 'piatta' se varia meno dello 0,3% in 20 sedute
NEAR_HIGH_PCT = 0.95            # 'vicino ai massimi' = entro il 5% dal massimo a 52 settimane
WEIGHTS = {"fundamentals": 0.25, "trend": 0.15, "sector": 0.20, "chart": 0.40}
VALID_THRESHOLD = 65
WATCH_THRESHOLD = 50

# Multipli di riferimento per settore (valori indicativi di lungo periodo).
# Servono a dire se un titolo è caro o economico rispetto ai suoi simili.
SECTOR_REF = {
    "Technology":             {"pe": 25, "ev_ebitda": 18},
    "Healthcare":             {"pe": 22, "ev_ebitda": 15},
    "Financial Services":     {"pe": 12, "pb": 1.3},
    "Consumer Cyclical":      {"pe": 18, "ev_ebitda": 11},
    "Consumer Defensive":     {"pe": 20, "ev_ebitda": 13},
    "Industrials":            {"pe": 20, "ev_ebitda": 13},
    "Energy":                 {"pe": 11, "ev_ebitda": 6},
    "Utilities":              {"pe": 16, "ev_ebitda": 10},
    "Real Estate":            {"pe": 30, "ev_ebitda": 18},
    "Basic Materials":        {"pe": 14, "ev_ebitda": 8},
    "Communication Services": {"pe": 18, "ev_ebitda": 10},
}
DEFAULT_REF = {"pe": 17, "ev_ebitda": 11}
LEVERAGE_OK_SECTORS = {"Financial Services", "Real Estate", "Utilities"}

# Indici di riferimento per il regime di mercato, in ordine di preferenza.
# Se quello nazionale non è disponibile su Yahoo si ripiega sull'Euro Stoxx 50.
EUROPE_FALLBACK_INDEX = "^STOXX50E"
INDEX_BY_SUFFIX = {
    ".MI": ["FTSEMIB.MI"], ".DE": ["^GDAXI"], ".F": ["^GDAXI"], ".PA": ["^FCHI"],
    ".L": ["^FTSE"], ".AS": ["^AEX"], ".MC": ["^IBEX"], ".SW": ["^SSMI"],
    ".BR": ["^BFX"], ".LS": ["PSI20.LS"], ".VI": ["^ATX"], ".IR": ["^ISEQ"],
    ".ST": ["^OMX"], ".CO": ["^OMXC25"], ".HE": ["^OMXH25"], ".OL": ["OSEBX.OL"],
    ".WA": ["WIG20.WA"],
    ".T": ["^N225"], ".HK": ["^HSI"], ".TO": ["^GSPTSE"], ".KS": ["^KS11"], ".AX": ["^AXJO"],
}
EUROPEAN_SUFFIXES = {".MI", ".DE", ".F", ".PA", ".L", ".AS", ".MC", ".SW", ".BR", ".LS",
                     ".VI", ".IR", ".ST", ".CO", ".HE", ".OL", ".WA"}
INDEX_NAMES = {
    "^GSPC": "S&P 500", "FTSEMIB.MI": "FTSE MIB", "^GDAXI": "DAX",
    "^FCHI": "CAC 40", "^FTSE": "FTSE 100", "^AEX": "AEX", "^IBEX": "IBEX 35",
    "^SSMI": "SMI", "^BFX": "BEL 20", "^N225": "Nikkei 225", "^HSI": "Hang Seng",
    "^GSPTSE": "TSX", "^KS11": "KOSPI", "^AXJO": "ASX 200",
    "PSI20.LS": "PSI 20", "^ATX": "ATX", "^ISEQ": "ISEQ", "^OMX": "OMX Stockholm 30",
    "^OMXC25": "OMX Copenhagen 25", "^OMXH25": "OMX Helsinki 25", "OSEBX.OL": "Oslo Børs",
    "WIG20.WA": "WIG20", "^STOXX50E": "Euro Stoxx 50",
}

# Cambi approssimati, usati solo per il filtro di liquidità
FX_TO_EUR_APPROX = {
    "EUR": 1.0, "USD": 0.9, "GBP": 1.15, "GBp": 0.0115, "CHF": 1.05,
    "CAD": 0.65, "AUD": 0.6, "JPY": 0.006, "HKD": 0.115, "KRW": 0.00066,
    "SEK": 0.087, "NOK": 0.085, "DKK": 0.134, "PLN": 0.23,
}

CURRENCY_BY_SUFFIX = {
    ".MI": "EUR", ".DE": "EUR", ".F": "EUR", ".PA": "EUR", ".AS": "EUR", ".MC": "EUR",
    ".BR": "EUR", ".LS": "EUR", ".VI": "EUR", ".HE": "EUR", ".IR": "EUR",
    ".L": "GBp", ".SW": "CHF", ".T": "JPY", ".HK": "HKD", ".TO": "CAD",
    ".KS": "KRW", ".AX": "AUD", ".ST": "SEK", ".CO": "DKK", ".OL": "NOK", ".WA": "PLN",
}

VERDICT_LABELS = {
    "valido": "Setup valido",
    "osservazione": "Da tenere d'occhio",
    "scartato": "Scartato",
}


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════
def _f(value):
    """Float sicuro: None per valori mancanti, NaN o infiniti."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(x) or math.isinf(x):
        return None
    return x


def _clamp(x, lo=0.0, hi=100.0):
    return max(lo, min(hi, x))


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def index_candidates_for(ticker: str) -> list:
    """Indici da provare, in ordine: prima quello nazionale, poi quello europeo."""
    if "." not in ticker:
        return ["^GSPC"]
    suffix = "." + ticker.rsplit(".", 1)[1].upper()
    candidates = list(INDEX_BY_SUFFIX.get(suffix, ["^GSPC"]))
    if suffix in EUROPEAN_SUFFIXES:
        candidates.append(EUROPE_FALLBACK_INDEX)
    return candidates


def market_index_for(ticker: str) -> str:
    return index_candidates_for(ticker)[0]


def guess_currency(ticker: str) -> str:
    if "." not in ticker:
        return "USD"
    return CURRENCY_BY_SUFFIX.get("." + ticker.rsplit(".", 1)[1].upper(), "USD")


def history_problem(hist) -> str:
    """Messaggio chiaro quando lo storico non basta."""
    if hist is None or hist.empty or hist["Close"].dropna().empty:
        return "Ticker non trovato o senza quotazioni su Yahoo Finance"
    sessions = int(hist["Close"].dropna().shape[0])
    return (f"Storico troppo corto: {sessions} sedute, ne servono almeno {MIN_HISTORY} "
            "(titolo quotato da poco?)")


# ══════════════════════════════════════════════════════════════════════════════
# SETTORI — classificazione comune ed ETF di riferimento
# ══════════════════════════════════════════════════════════════════════════════
SECTOR_IT = {
    "Technology": "Tecnologia", "Financials": "Finanza", "Health Care": "Salute",
    "Energy": "Energia", "Industrials": "Industria",
    "Consumer Discretionary": "Beni di consumo discrezionali",
    "Consumer Staples": "Beni di prima necessità", "Utilities": "Servizi di pubblica utilità",
    "Materials": "Materie prime", "Real Estate": "Immobiliare",
    "Communication Services": "Comunicazioni",
}
# Nome del settore come lo usa Yahoo (serve ai multipli di riferimento SECTOR_REF)
YAHOO_SECTOR_NAME = {
    "Technology": "Technology", "Financials": "Financial Services", "Health Care": "Healthcare",
    "Energy": "Energy", "Industrials": "Industrials", "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive", "Utilities": "Utilities",
    "Materials": "Basic Materials", "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
}
# Parole chiave → settore, in ordine (le prime regole hanno la precedenza)
SECTOR_RULES = [
    (("utilit", "electric", "water", "power gen"), "Utilities"),
    (("real estate", "reit", "propert"), "Real Estate"),
    (("bank", "insur", "financ", "capital market", "asset manag", "brokerage"), "Financials"),
    (("health", "pharma", "biotech", "medical", "life science"), "Health Care"),
    (("semiconductor", "software", "information technology", "technology", "tech hardware",
      "electronic"), "Technology"),
    (("telecom", "communication", "media", "entertainment", "interactive"), "Communication Services"),
    (("oil", "gas", "energy", "coal"), "Energy"),
    (("staples", "consumer defensive", "food", "beverage", "tobacco", "household",
      "personal care", "grocer", "drug retail"), "Consumer Staples"),
    (("discretionary", "consumer cyclical", "retail", "automobile", "auto ", "autos",
      "apparel", "luxury", "travel", "leisure", "hotel", "restaurant", "textile",
      "consumer products", "personal goods", "footwear"), "Consumer Discretionary"),
    (("industrial", "aerospace", "defen", "construction", "transport", "machinery",
      "engineering", "airline", "logistic", "capital goods", "business services",
      "commercial services"), "Industrials"),
    (("material", "chemical", "mining", "metal", "steel", "basic resource", "paper",
      "forest", "basic industr"), "Materials"),
]
US_SECTOR_ETF = {
    "Technology": ("XLK", "ETF tecnologia USA"), "Financials": ("XLF", "ETF finanza USA"),
    "Health Care": ("XLV", "ETF salute USA"), "Energy": ("XLE", "ETF energia USA"),
    "Industrials": ("XLI", "ETF industria USA"),
    "Consumer Discretionary": ("XLY", "ETF consumi discrezionali USA"),
    "Consumer Staples": ("XLP", "ETF beni di prima necessità USA"),
    "Utilities": ("XLU", "ETF utility USA"), "Materials": ("XLB", "ETF materie prime USA"),
    "Real Estate": ("XLRE", "ETF immobiliare USA"),
    "Communication Services": ("XLC", "ETF comunicazioni USA"),
}
# Europa: ETF iShares STOXX Europe 600 (Xetra). Prima i settori fini, poi quelli generali.
EU_SECTOR_ETF_FINE = [
    (("utilit",), "EXH9.DE", "ETF utility europee"),
    (("bank",), "EXV1.DE", "ETF banche europee"),
    (("insur",), "EXH5.DE", "ETF assicurazioni europee"),
    (("financial serv", "capital market", "asset manag"), "EXH2.DE", "ETF servizi finanziari europei"),
    (("automobile", "auto ", "autos"), "EXV5.DE", "ETF auto europee"),
    (("retail",), "EXH8.DE", "ETF distribuzione europea"),
    (("travel", "leisure", "hotel", "airline", "restaurant"), "EXV9.DE", "ETF viaggi e tempo libero europei"),
    (("media",), "EXH6.DE", "ETF media europei"),
    (("chemical",), "EXV7.DE", "ETF chimica europea"),
    (("construction",), "EXV8.DE", "ETF costruzioni europee"),
    (("telecom",), "EXV2.DE", "ETF telecomunicazioni europee"),
    (("food", "beverage"), "EXH3.DE", "ETF alimentari e bevande europei"),
    (("oil", "gas"), "EXH1.DE", "ETF petrolio e gas europei"),
    (("real estate", "propert"), "EXI5.DE", "ETF immobiliare europeo"),
]
EU_SECTOR_ETF = {
    "Technology": ("EXV3.DE", "ETF tecnologia europea"), "Financials": ("EXV1.DE", "ETF banche europee"),
    "Health Care": ("EXV4.DE", "ETF salute europea"), "Energy": ("EXH1.DE", "ETF petrolio e gas europei"),
    "Industrials": ("EXH4.DE", "ETF industria europea"),
    "Consumer Discretionary": ("EXH7.DE", "ETF beni personali e per la casa europei"),
    "Consumer Staples": ("EXH3.DE", "ETF alimentari e bevande europei"),
    "Utilities": ("EXH9.DE", "ETF utility europee"), "Materials": ("EXV6.DE", "ETF materie prime europee"),
    "Real Estate": ("EXI5.DE", "ETF immobiliare europeo"),
    "Communication Services": ("EXV2.DE", "ETF telecomunicazioni europee"),
}


def canonical_sector(raw):
    """Riconduce le diverse classificazioni (GICS, ICB, Yahoo) a 11 settori comuni."""
    if not raw:
        return None
    text = " " + str(raw).lower() + " "
    for keywords, sector in SECTOR_RULES:
        if any(k in text for k in keywords):
            return sector
    return None


def region_for(ticker: str):
    if "." not in ticker:
        return "us"
    suffix = "." + ticker.rsplit(".", 1)[1].upper()
    return "eu" if suffix in EUROPEAN_SUFFIXES else None


def sector_benchmark(ticker: str, raw_sector):
    """Settore comune, regione ed ETF di riferimento per un titolo; None se sconosciuto."""
    canonical = canonical_sector(raw_sector)
    region = region_for(ticker)
    if not canonical or not region:
        return None
    if region == "us":
        etf, label = US_SECTOR_ETF[canonical]
    else:
        text = " " + str(raw_sector).lower() + " "
        etf, label = EU_SECTOR_ETF[canonical]
        for keywords, fine_etf, fine_label in EU_SECTOR_ETF_FINE:
            if any(k in text for k in keywords):
                etf, label = fine_etf, fine_label
                break
    return {"canonical": canonical, "region": region, "etf": etf, "etf_label": label,
            "raw": str(raw_sector)}


def peer_average(histories) -> pd.DataFrame:
    """Andamento medio (pesi uguali) di un gruppo di titoli, come riserva quando manca l'ETF."""
    series = []
    for h in histories:
        if h is None or h.empty:
            continue
        close = h["Close"].dropna().astype(float)
        if len(close) >= MIN_HISTORY:
            close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
            series.append(close / close.iloc[0])
    if not series:
        return pd.DataFrame()
    avg = pd.concat(series, axis=1).sort_index().ffill().mean(axis=1).dropna()
    return pd.DataFrame({"Close": avg})


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORI
# ══════════════════════════════════════════════════════════════════════════════
def compute_indicators(hist: pd.DataFrame):
    """Indicatori calcolati sempre su tutto lo storico disponibile."""
    if hist is None or hist.empty:
        return None
    h = hist.dropna(subset=["Close", "High", "Low"])
    if len(h) < MIN_HISTORY:
        return None

    close = h["Close"].astype(float)
    high = h["High"].astype(float)
    low = h["Low"].astype(float)
    volume = h["Volume"].astype(float) if "Volume" in h else pd.Series(0.0, index=h.index)

    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    atr = true_range.ewm(alpha=1 / 14, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    last_loss = float(loss.iloc[-1])
    rsi = 100.0 if last_loss == 0 else 100 - 100 / (1 + float(gain.iloc[-1]) / last_loss)

    ma20 = close.rolling(20).mean()
    ma150 = close.rolling(150).mean()
    log_ret = np.log(close).diff().dropna()

    return {
        "close": close,
        "ma150_series": ma150,
        "price": float(close.iloc[-1]),
        "ma20": float(ma20.iloc[-1]),
        "ma150": float(ma150.iloc[-1]),
        "atr": float(atr.iloc[-1]),
        "rsi": float(rsi),
        # base = ultime 40 sedute escluso oggi, così una rottura di oggi conta
        "base_high": float(high.iloc[-BASE_WINDOW - 1:-1].max()),
        "base_low": float(low.iloc[-BASE_WINDOW - 1:-1].min()),
        "high_52w": float(high.tail(252).max()),
        "sigma": float(log_ret.tail(63).std()),
        "mu": float(log_ret.tail(126).mean()),
        "ret_63": float(close.iloc[-1] / close.iloc[-64] - 1) * 100,
        "liquidity": float((close * volume).tail(20).mean()),
    }


# ══════════════════════════════════════════════════════════════════════════════
# LIVELLO 1 — FONDAMENTALI
# ══════════════════════════════════════════════════════════════════════════════
def _relative_cheapness(reference, value):
    """60 = in linea col settore; >60 più economico; <60 più caro."""
    if value is None or value <= 0 or not reference:
        return None
    ratio = reference / value
    return _clamp(60 + (ratio - 1) * 133)


def fundamentals_layer(info: dict, price: float) -> dict:
    out = {"score": None, "value_score": None, "quality_score": None,
           "label": "Dati insufficienti", "exclusions": [], "warnings": [], "details": {}}

    sector = info.get("sector") or ""
    ref = SECTOR_REF.get(sector, DEFAULT_REF)

    forward_pe = _f(info.get("forwardPE"))
    trailing_pe = _f(info.get("trailingPE"))
    pe = forward_pe if forward_pe and forward_pe > 0 else trailing_pe
    ev_ebitda = _f(info.get("enterpriseToEbitda"))
    pb = _f(info.get("priceToBook"))
    fcf = _f(info.get("freeCashflow"))
    market_cap = _f(info.get("marketCap"))
    margin = _f(info.get("profitMargins"))
    roe = _f(info.get("returnOnEquity"))
    growth = _f(info.get("revenueGrowth"))
    debt_equity = _f(info.get("debtToEquity"))   # Yahoo: 150 = 1,5
    n_analysts = int(_f(info.get("numberOfAnalystOpinions")) or 0)
    analyst_target = _f(info.get("targetMeanPrice"))

    out["details"] = {
        "sector": sector or "n.d.", "pe": pe, "pe_ref": ref.get("pe"),
        "ev_ebitda": ev_ebitda, "ev_ebitda_ref": ref.get("ev_ebitda"),
        "pb": pb, "pb_ref": ref.get("pb"),
        "fcf_yield": (fcf / market_cap * 100) if fcf is not None and market_cap else None,
        "margin": margin * 100 if margin is not None else None,
        "roe": roe * 100 if roe is not None else None,
        "growth": growth * 100 if growth is not None else None,
        "debt_equity": debt_equity / 100 if debt_equity is not None else None,
        "n_analysts": n_analysts, "analyst_target": analyst_target,
    }

    available = sum(v is not None for v in [pe, ev_ebitda, margin, roe, fcf])
    if available < 3:
        out["exclusions"].append("Dati fondamentali insufficienti per valutare l'azienda")
        return out

    # Filtro qualità: evita le aziende economiche perché stanno peggiorando
    if margin is not None and margin <= 0:
        out["exclusions"].append("Azienda in perdita (margine netto negativo)")
    if fcf is not None and fcf < 0:
        out["exclusions"].append("Free cash flow negativo: l'azienda brucia cassa")
    if debt_equity is not None and debt_equity > 200 and sector not in LEVERAGE_OK_SECTORS:
        out["exclusions"].append("Debito elevato (debito/patrimonio sopra 2)")

    # Valutazione rispetto al settore
    value_parts = [_relative_cheapness(ref.get("pe"), pe)]
    if "ev_ebitda" in ref:
        value_parts.append(_relative_cheapness(ref["ev_ebitda"], ev_ebitda))
    if "pb" in ref:
        value_parts.append(_relative_cheapness(ref["pb"], pb))
    if out["details"]["fcf_yield"] is not None:
        value_parts.append(_clamp(20 + out["details"]["fcf_yield"] * 10))
    if n_analysts >= 3 and analyst_target and price:
        upside = (analyst_target / price - 1) * 100
        value_parts.append(_clamp(50 + upside * 2))
    value_score = _mean(value_parts)

    # Qualità
    quality_parts = []
    if roe is not None:
        quality_parts.append(_clamp(roe * 100 * 4))
    if margin is not None:
        quality_parts.append(_clamp(margin * 100 * 5))
    if growth is not None:
        quality_parts.append(_clamp(50 + growth * 100 * 2.5))
    quality_score = _mean(quality_parts)

    if value_score is not None and quality_score is not None:
        score = 0.6 * value_score + 0.4 * quality_score
    else:
        score = value_score if value_score is not None else quality_score

    out["value_score"] = value_score
    out["quality_score"] = quality_score
    out["score"] = score

    if value_score is None:
        out["label"] = "Valutazione non calcolabile"
    elif value_score >= 60:
        out["label"] = "Sottovalutato rispetto al settore"
    elif value_score >= 45:
        out["label"] = "In linea con il settore"
    else:
        out["label"] = "Caro rispetto al settore"
        out["exclusions"].append("Valutazione cara rispetto al settore")

    return out


# ══════════════════════════════════════════════════════════════════════════════
# LIVELLO 2 — TREND DI MERCATO
# ══════════════════════════════════════════════════════════════════════════════
def trend_layer(ind: dict, index_hist, index_symbol: str) -> dict:
    out = {"score": None, "regime": None, "regime_label": "Indice non disponibile",
           "relative_strength": None, "exclusions": [], "warnings": [],
           "index_name": INDEX_NAMES.get(index_symbol, index_symbol)}

    index_return = None
    regime_score = None
    if index_hist is not None and not index_hist.empty:
        idx = index_hist.dropna(subset=["Close"])["Close"].astype(float)
        if len(idx) >= 221:
            ma200 = idx.rolling(200).mean()
            slope = float(ma200.iloc[-1] / ma200.iloc[-21] - 1)
            above = float(idx.iloc[-1]) > float(ma200.iloc[-1])
            if above and slope > 0:
                out["regime"], out["regime_label"], regime_score = "rialzista", "Mercato in tendenza rialzista", 100
            elif not above and slope < 0:
                out["regime"], out["regime_label"], regime_score = "ribassista", "Mercato in tendenza ribassista", 0
                out["exclusions"].append(
                    f"{out['index_name']} in tendenza ribassista: si sospendono gli acquisti")
            else:
                out["regime"], out["regime_label"], regime_score = "neutro", "Mercato senza una tendenza chiara", 50
            index_return = float(idx.iloc[-1] / idx.iloc[-64] - 1) * 100

    if index_return is not None:
        out["relative_strength"] = ind["ret_63"] - index_return
        rs_score = _clamp(50 + out["relative_strength"] * 2.5)
        out["score"] = 0.6 * regime_score + 0.4 * rs_score
    else:
        out["warnings"].append("Indice di riferimento non disponibile: trend di mercato non valutato")

    return out


# ══════════════════════════════════════════════════════════════════════════════
# LIVELLO 2B — TREND DI SETTORE
# ══════════════════════════════════════════════════════════════════════════════
def sector_layer(ind: dict, sector) -> dict:
    """
    sector = {"canonical", "hist" (DataFrame con Close), "source" (descrizione della fonte)}.
    Regime del settore (come per l'indice) + forza del titolo rispetto al settore in 3 mesi.
    """
    out = {"score": None, "name": None, "source": None, "regime": None,
           "regime_label": "Settore non disponibile", "relative_strength": None,
           "exclusions": [], "warnings": []}
    if not sector or not sector.get("canonical"):
        out["warnings"].append("Settore non disponibile: trend di settore non valutato")
        return out
    out["name"] = SECTOR_IT.get(sector["canonical"], sector["canonical"])
    out["source"] = sector.get("source")
    hist = sector.get("hist")
    if hist is None or hist.empty or hist["Close"].dropna().shape[0] < 221:
        out["warnings"].append(f"Andamento del settore {out['name']} non disponibile: "
                               "trend di settore non valutato")
        return out

    close = hist["Close"].dropna().astype(float)
    ma200 = close.rolling(200).mean()
    slope = float(ma200.iloc[-1] / ma200.iloc[-21] - 1)
    above = float(close.iloc[-1]) > float(ma200.iloc[-1])
    if above and slope > 0:
        regime, label, regime_score = "rialzista", "Settore in tendenza rialzista", 100
    elif not above and slope < 0:
        regime, label, regime_score = "ribassista", "Settore in tendenza ribassista", 0
        out["warnings"].append(f"Settore {out['name']} in tendenza ribassista: "
                               "il titolo si muove controcorrente")
    else:
        regime, label, regime_score = "neutro", "Settore senza una tendenza chiara", 50
    sector_return = float(close.iloc[-1] / close.iloc[-64] - 1) * 100
    relative = ind["ret_63"] - sector_return
    out.update(regime=regime, regime_label=label, relative_strength=relative,
               score=0.6 * regime_score + 0.4 * _clamp(50 + relative * 2.5))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LIVELLO 3 — GRAFICO (stadi di Weinstein)
# ══════════════════════════════════════════════════════════════════════════════
def weinstein_stage(close: pd.Series, ma150: pd.Series, high_52w: float | None = None):
    """Stadio 1 base, 2 rialzo, 3 distribuzione, 4 declino."""
    if ma150.dropna().shape[0] < 101:
        return None
    price = float(close.iloc[-1])
    ma_now = float(ma150.iloc[-1])
    slope = (ma_now / float(ma150.iloc[-21]) - 1) * 100      # % su 20 sedute
    distance = (price / ma_now - 1) * 100
    came_from_decline = ma_now < float(ma150.iloc[-101])
    near_high = high_52w is not None and price >= high_52w * NEAR_HIGH_PCT
    rising, falling = slope > SLOPE_FLAT_PCT, slope < -SLOPE_FLAT_PCT

    if price > ma_now and rising:
        if distance <= 12:
            code, label, score = "2-iniziale", "Stadio 2 iniziale: rialzo appena partito", 100
        elif distance <= 20:
            code, label, score = "2-in-corso", "Stadio 2: rialzo in corso", 80
        else:
            code, label, score = "2-esteso", "Stadio 2 esteso: prezzo lontano dalla media", 45
    elif price < ma_now and falling:
        code, label, score = "4", "Stadio 4: declino", 0
    elif price > ma_now:
        if came_from_decline:
            code, label, score = "1-uscita", "Stadio 1 in uscita: sta rompendo la base", 75
        elif near_high:
            code, label, score = "2-pausa", "Stadio 2 in pausa: media piatta ma prezzo vicino ai massimi", 70
        else:
            code, label, score = "3", "Stadio 3: distribuzione, il rialzo si sta esaurendo", 20
    else:
        if rising:
            code, label, score = "2-correzione", "Stadio 2 in correzione", 40
        elif came_from_decline:
            code, label, score = "1-base", "Stadio 1: base laterale dopo un calo", 55
        else:
            code, label, score = "3", "Stadio 3: distribuzione, il rialzo si sta esaurendo", 20

    return {"code": code, "label": label, "score": score,
            "ma150_slope": slope, "distance_ma150": distance}


def chart_layer(ind: dict) -> dict:
    out = {"score": None, "stage": None, "stage_label": "Non calcolabile",
           "exclusions": [], "warnings": []}
    stage = weinstein_stage(ind["close"], ind["ma150_series"], ind["high_52w"])
    if stage is None:
        out["exclusions"].append("Storico insufficiente per determinare la fase del grafico")
        return out

    score = stage["score"]
    if ind["rsi"] > 75:
        score -= 15
        out["warnings"].append(
            f"RSI a {ind['rsi']:.0f}: titolo ipercomprato, meglio attendere un ritracciamento")
    if stage["code"] == "4":
        out["exclusions"].append("Titolo in declino (stadio 4): rischio di comprare mentre scende")
    elif stage["code"] == "3":
        out["exclusions"].append("Titolo in distribuzione (stadio 3): il rialzo si sta esaurendo")

    out.update(score=_clamp(score), stage=stage, stage_label=stage["label"])
    return out


# ══════════════════════════════════════════════════════════════════════════════
# LIVELLO 4 — PIANO DI ENTRATA E USCITA
# ══════════════════════════════════════════════════════════════════════════════
def trade_plan(ind: dict, info: dict, today: pd.Timestamp) -> dict:
    out = {"exclusions": [], "warnings": []}
    price, ma20, atr = ind["price"], ind["ma20"], ind["atr"]
    base_high, base_low = ind["base_high"], ind["base_low"]

    # Tipo di entrata
    if price < base_high * 0.97:
        setup, order, entry = ("Attendi la rottura della resistenza",
                               "Ordine stop di acquisto", base_high * 1.005)
    elif price > ma20 * 1.06:
        setup, order, entry = ("Attendi il ritracciamento verso la media a 20 giorni",
                               "Ordine limite", ma20)
    else:
        setup, order, entry = "Entrata ora", "Ordine al mercato", price

    # Stop: 2 × ATR sotto l'entrata, ma tra il -5% e il -10%
    stop = entry - ATR_STOP_MULT * atr
    stop = max(stop, entry * (1 - STOP_MAX_PCT))
    stop = min(stop, entry * (1 - STOP_MIN_PCT))

    # Target tecnico: ampiezza della base proiettata, o resistenza a 52 settimane
    target = base_high + (base_high - base_low)
    target_basis = "Proiezione dell'ampiezza della base recente"
    if entry * 1.03 < ind["high_52w"] < target:
        target = ind["high_52w"]
        target_basis = "Massimo a 52 settimane (resistenza)"
    if target > entry * (1 + TARGET_MAX_PCT):
        target = entry * (1 + TARGET_MAX_PCT)
        target_basis = f"Tetto massimo +{TARGET_MAX_PCT * 100:.0f}% per un orizzonte di pochi mesi"
    n_analysts = int(_f(info.get("numberOfAnalystOpinions")) or 0)
    analyst_target = _f(info.get("targetMeanPrice"))
    if n_analysts >= 3 and analyst_target and analyst_target < target:
        target = analyst_target
        target_basis = f"Prezzo obiettivo medio degli analisti ({n_analysts})"

    entry, stop, target = round(entry, 2), round(stop, 2), round(target, 2)
    risk = entry - stop
    reward = target - entry
    rr = reward / risk if risk > 0 else 0.0

    gross_pct = round((target / entry - 1) * 100, 2)
    net_pct = round(gross_pct * (1 - TAX_RATE), 2)
    max_loss_pct = round((stop / entry - 1) * 100, 2)

    if reward <= entry * 0.01:
        out["exclusions"].append("Nessuno spazio di rialzo: il target è sotto o vicino all'entrata")

    # Tempo stimato: media tra
    #  - orologio della volatilità: sedute perché una oscillazione tipica copra la distanza
    #  - ritmo del trend: sedute al ritmo medio degli ultimi 6 mesi
    days_low = days_high = days_central = None
    if reward > 0:
        distance = math.log(target / entry)
        t_vol = (distance / ind["sigma"]) ** 2 if ind["sigma"] > 0 else None
        t_trend = distance / ind["mu"] if ind["mu"] > 0 else None
        days_central = _mean([t_vol, t_trend])
        if days_central is not None:
            days_central = max(days_central, 5.0)
            days_low, days_high = days_central * 0.7, days_central * 1.5
            if days_central > HORIZON_MAX_DAYS:
                out["exclusions"].append("Tempo stimato oltre l'orizzonte di 6 mesi")

    if rr < MIN_RR:
        out["exclusions"].append(
            f"Rendimento/rischio {rr:.1f} sotto il minimo di {MIN_RR:.0f}")

    time_stop_date = None
    if days_high is not None:
        time_stop_date = (today + pd.tseries.offsets.BDay(int(round(days_high)))).date().isoformat()

    out.update({
        "setup": setup, "order": order,
        "entry": entry, "stop": stop, "target": target, "target_basis": target_basis,
        "rr": round(rr, 2), "gross_pct": gross_pct, "net_pct": net_pct,
        "max_loss_pct": max_loss_pct,
        "days_low": round(days_low) if days_low else None,
        "days_high": round(days_high) if days_high else None,
        "months_low": round(days_low / 21, 1) if days_low else None,
        "months_high": round(days_high / 21, 1) if days_high else None,
        "time_stop_date": time_stop_date,
    })
    return out


def earnings_warning(info: dict, today: pd.Timestamp):
    ts = _f(info.get("earningsTimestamp")) or _f(info.get("earningsTimestampStart"))
    if not ts:
        return None
    date = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    days = (date - today.date()).days
    if 0 <= days <= EARNINGS_WARNING_DAYS:
        return (f"Trimestrale il {date.strftime('%d/%m/%Y')}: possibile salto di prezzo, "
                f"valuta di entrare dopo la pubblicazione")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# ANALISI COMPLETA
# ══════════════════════════════════════════════════════════════════════════════
def analyze(ticker: str, info: dict, hist: pd.DataFrame, index_hist,
            index_symbol: str | None = None, today: pd.Timestamp | None = None,
            sector: dict | None = None) -> dict:
    today = (today or pd.Timestamp.today()).normalize()
    info = dict(info or {})
    # Il settore letto dagli indici permette i multipli di settore anche senza il riepilogo Yahoo
    if sector and sector.get("canonical") and not info.get("sector"):
        info["sector"] = YAHOO_SECTOR_NAME.get(sector["canonical"])
    index_symbol = index_symbol or market_index_for(ticker)

    result = {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "currency": info.get("currency") or guess_currency(ticker),
        "price": None, "verdict": "scartato", "verdict_label": VERDICT_LABELS["scartato"],
        "composite": None, "scores": {}, "labels": {}, "plan": None,
        "exclusions": [], "warnings": [], "details": {},
    }

    ind = compute_indicators(hist)
    if ind is None:
        result["exclusions"].append(history_problem(hist))
        return result
    result["price"] = round(ind["price"], 2)

    liquidity_eur = ind["liquidity"] * FX_TO_EUR_APPROX.get(result["currency"], 1.0)
    if liquidity_eur < MIN_LIQUIDITY_EUR:
        result["exclusions"].append(
            "Scambi troppo bassi per entrare e uscire velocemente dal titolo")

    fund = fundamentals_layer(info, ind["price"])
    trend = trend_layer(ind, index_hist, index_symbol)
    sector_res = sector_layer(ind, sector)
    chart = chart_layer(ind)
    plan = trade_plan(ind, info, today)

    for layer in (fund, trend, sector_res, chart, plan):
        result["exclusions"].extend(layer["exclusions"])
        result["warnings"].extend(layer["warnings"])
    earnings = earnings_warning(info, today)
    if earnings:
        result["warnings"].append(earnings)
    if info.get("_source") == "statements":
        if info.get("sector"):
            result["warnings"].append(
                "Fondamentali calcolati dagli ultimi bilanci annuali, perché Yahoo non ha fornito "
                "il riepilogo: mancano il target degli analisti e la data della trimestrale")
        else:
            result["warnings"].append(
                "Fondamentali calcolati dagli ultimi bilanci annuali, perché Yahoo non ha fornito "
                "il riepilogo: mancano settore, target degli analisti e data della trimestrale, "
                "e la valutazione è confrontata con i multipli medi di mercato")

    scores = {"fundamentals": fund["score"], "trend": trend["score"],
              "sector": sector_res["score"], "chart": chart["score"]}
    weights = {k: w for k, w in WEIGHTS.items() if scores[k] is not None}
    composite = None
    if weights:
        total = sum(weights.values())
        composite = sum(scores[k] * w for k, w in weights.items()) / total

    plan_public = {k: v for k, v in plan.items() if k not in ("exclusions", "warnings")}
    result.update({
        "composite": round(composite, 1) if composite is not None else None,
        "scores": {
            "fundamentals": round(fund["score"], 1) if fund["score"] is not None else None,
            "value": round(fund["value_score"], 1) if fund["value_score"] is not None else None,
            "quality": round(fund["quality_score"], 1) if fund["quality_score"] is not None else None,
            "trend": round(trend["score"], 1) if trend["score"] is not None else None,
            "sector": round(sector_res["score"], 1) if sector_res["score"] is not None else None,
            "chart": round(chart["score"], 1) if chart["score"] is not None else None,
        },
        "labels": {
            "valuation": fund["label"],
            "regime": trend["regime_label"],
            "index": trend["index_name"],
            "sector": sector_res["name"],
            "sector_regime": sector_res["regime_label"],
            "sector_source": sector_res["source"],
            "stage": chart["stage_label"],
        },
        "plan": plan_public,
        "details": {
            **fund["details"],
            "relative_strength": trend["relative_strength"],
            "sector_relative_strength": sector_res["relative_strength"],
            "sector_raw": (sector or {}).get("raw"),
            "rsi": ind["rsi"], "atr": ind["atr"], "ma20": ind["ma20"], "ma150": ind["ma150"],
            "ma150_slope": chart["stage"]["ma150_slope"] if chart["stage"] else None,
            "base_high": ind["base_high"], "base_low": ind["base_low"],
            "high_52w": ind["high_52w"], "liquidity_eur": liquidity_eur,
        },
    })

    if result["exclusions"] or composite is None:
        result["verdict"] = "scartato"
    elif composite >= VALID_THRESHOLD:
        result["verdict"] = "valido"
    elif composite >= WATCH_THRESHOLD:
        result["verdict"] = "osservazione"
    else:
        result["verdict"] = "scartato"
        result["exclusions"].append(f"Punteggio complessivo {composite:.0f} sotto la soglia di {WATCH_THRESHOLD}")
    result["verdict_label"] = VERDICT_LABELS[result["verdict"]]
    return result


def technical_precheck(ticker: str, hist, index_hist, index_symbol: str | None = None,
                       today: pd.Timestamp | None = None) -> list:
    """
    Primo passaggio veloce della scansione, senza fondamentali.
    Restituisce i motivi di esclusione: lista vuota = il titolo passa al secondo passaggio.
    Usa solo controlli che i fondamentali non possono ribaltare.
    """
    today = (today or pd.Timestamp.today()).normalize()
    ind = compute_indicators(hist)
    if ind is None:
        return [history_problem(hist)]
    exclusions = []
    liquidity_eur = ind["liquidity"] * FX_TO_EUR_APPROX.get(guess_currency(ticker), 1.0)
    if liquidity_eur < MIN_LIQUIDITY_EUR:
        exclusions.append("Scambi troppo bassi per entrare e uscire velocemente dal titolo")
    exclusions += chart_layer(ind)["exclusions"]
    exclusions += trend_layer(ind, index_hist, index_symbol or market_index_for(ticker))["exclusions"]
    # Senza il target degli analisti il target può solo essere più alto:
    # se il rendimento/rischio non basta adesso, non basterà nemmeno dopo.
    plan = trade_plan(ind, {}, today)
    exclusions += [e for e in plan["exclusions"] if not e.startswith("Tempo stimato")]
    return exclusions


def sort_key(result: dict):
    """Ordinamento della scansione: prima i setup validi, poi punteggio e R/R."""
    order = {"valido": 0, "osservazione": 1, "scartato": 2}
    plan = result.get("plan") or {}
    return (order.get(result.get("verdict"), 3),
            -(result.get("composite") or 0),
            -(plan.get("rr") or 0))
