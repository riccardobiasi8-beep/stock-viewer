"""
Backtest del modello swing.

Per ogni data di controllo nel passato applica le regole del modello usando SOLO i dati
disponibili fino a quel giorno, poi segue l'operazione nei giorni successivi:
entrata (al mercato, su rottura o su ritracciamento), stop, target o uscita a tempo.

Livelli verificabili con dati gratuiti: grafico, trend di mercato, trend di settore e piano
di entrata/uscita. Fondamentali e sentiment non hanno uno storico gratuito: restano fuori.
Nessuna dipendenza da Streamlit: si può testare da solo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from swing_model import (BASE_WINDOW, FX_TO_EUR_APPROX, HORIZON_MAX_DAYS, MIN_HISTORY,
                         MIN_LIQUIDITY_EUR, TAX_RATE, VALID_THRESHOLD, WEIGHTS, _clamp,
                         chart_layer, guess_currency, trade_plan)

FILL_WINDOW = 10        # sedute in cui un ordine di rottura o di ritracciamento resta valido
COST_PCT = 0.15         # costi per lato (commissioni + slittamento), in %
BT_LAYERS = ("trend", "sector", "chart")


# ══════════════════════════════════════════════════════════════════════════════
# INDICATORI SU TUTTO LO STORICO (stesse definizioni di compute_indicators)
# ══════════════════════════════════════════════════════════════════════════════
def _naive_index(index) -> pd.DatetimeIndex:
    idx = pd.to_datetime(index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    return idx.normalize()


def indicator_frame(hist: pd.DataFrame):
    """Tutti gli indicatori giorno per giorno, calcolati solo con dati passati (finestre mobili)."""
    if hist is None or hist.empty:
        return None
    h = hist.dropna(subset=["Close", "High", "Low"])
    if len(h) < MIN_HISTORY:
        return None
    close, high, low = (h[c].astype(float) for c in ("Close", "High", "Low"))
    open_ = h["Open"].astype(float).fillna(close) if "Open" in h else close
    volume = h["Volume"].astype(float).fillna(0) if "Volume" in h else pd.Series(0.0, index=h.index)

    prev = close.shift(1)
    true_range = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    rsi = (100 - 100 / (1 + gain / loss.replace(0, np.nan))).fillna(100.0)
    log_ret = np.log(close).diff()

    frame = pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close,
        "ma20": close.rolling(20).mean(),
        "ma150": close.rolling(150).mean(),
        "atr": true_range.ewm(alpha=1 / 14, adjust=False).mean(),
        "rsi": rsi,
        "base_high": high.shift(1).rolling(BASE_WINDOW).max(),
        "base_low": low.shift(1).rolling(BASE_WINDOW).min(),
        "high_52w": high.rolling(252, min_periods=1).max(),
        "sigma": log_ret.rolling(63).std(),
        "mu": log_ret.rolling(126).mean(),
        "ret_63": (close / close.shift(63) - 1) * 100,
        "liquidity": (close * volume).rolling(20).mean(),
    })
    frame.index = _naive_index(frame.index)
    return frame


def ind_at(frame: pd.DataFrame, i: int) -> dict | None:
    """Gli indicatori del giorno i nel formato di compute_indicators."""
    row = frame.iloc[i]
    needed = ("ma20", "ma150", "atr", "base_high", "base_low", "sigma", "mu", "ret_63", "liquidity")
    if any(pd.isna(row[k]) for k in needed):
        return None
    return {
        "close": frame["close"].iloc[:i + 1], "ma150_series": frame["ma150"].iloc[:i + 1],
        "price": float(row["close"]), "ma20": float(row["ma20"]), "ma150": float(row["ma150"]),
        "atr": float(row["atr"]), "rsi": float(row["rsi"]),
        "base_high": float(row["base_high"]), "base_low": float(row["base_low"]),
        "high_52w": float(row["high_52w"]), "sigma": float(row["sigma"]), "mu": float(row["mu"]),
        "ret_63": float(row["ret_63"]), "liquidity": float(row["liquidity"]),
    }


def regime_frame(hist: pd.DataFrame):
    """Regime giorno per giorno di un indice o di un ETF (stesse regole del modello)."""
    if hist is None or hist.empty:
        return None
    close = hist["Close"].dropna().astype(float)
    close.index = _naive_index(close.index)
    ma200 = close.rolling(200).mean()
    slope = ma200 / ma200.shift(20) - 1
    above = close > ma200
    regime = np.select([above & (slope > 0), (~above) & (slope < 0)], ["rialzista", "ribassista"], "neutro")
    out = pd.DataFrame({"regime": regime, "ret_63": (close / close.shift(63) - 1) * 100,
                        "close": close}, index=close.index)
    out.loc[slope.isna(), "regime"] = None
    return out


def _state_at(states: pd.DataFrame | None, date) -> dict | None:
    if states is None or states.empty:
        return None
    pos = states.index.searchsorted(date, side="right") - 1
    if pos < 0:
        return None
    row = states.iloc[pos]
    if row["regime"] is None or pd.isna(row["ret_63"]):
        return None
    return {"regime": row["regime"], "ret_63": float(row["ret_63"])}


# ══════════════════════════════════════════════════════════════════════════════
# SEGNALE IN UNA DATA PASSATA
# ══════════════════════════════════════════════════════════════════════════════
REGIME_SCORE = {"rialzista": 100, "neutro": 50, "ribassista": 0}


def evaluate(ticker: str, frame: pd.DataFrame, i: int, date, market, sector) -> dict | None:
    """Stesse regole del modello (senza fondamentali e sentiment) con i dati fino al giorno i."""
    ind = ind_at(frame, i)
    if ind is None:
        return None
    exclusions = []
    if ind["liquidity"] * FX_TO_EUR_APPROX.get(guess_currency(ticker), 1.0) < MIN_LIQUIDITY_EUR:
        exclusions.append("liquidità")

    chart = chart_layer(ind)
    exclusions += chart["exclusions"]

    trend_score = None
    if market:
        if market["regime"] == "ribassista":
            exclusions.append("mercato ribassista")
        trend_score = (0.6 * REGIME_SCORE[market["regime"]]
                       + 0.4 * _clamp(50 + (ind["ret_63"] - market["ret_63"]) * 2.5))
    sector_score = None
    if sector:
        sector_score = (0.6 * REGIME_SCORE[sector["regime"]]
                        + 0.4 * _clamp(50 + (ind["ret_63"] - sector["ret_63"]) * 2.5))

    plan = trade_plan(ind, {}, pd.Timestamp(date))
    exclusions += plan["exclusions"]

    scores = {"trend": trend_score, "sector": sector_score, "chart": chart["score"]}
    weights = {k: WEIGHTS[k] for k in BT_LAYERS if scores[k] is not None}
    if not weights:
        return None
    composite = sum(scores[k] * w for k, w in weights.items()) / sum(weights.values())
    return {
        "composite": composite, "plan": plan, "exclusions": exclusions,
        "stage": chart["stage"]["code"] if chart["stage"] else None,
        "market_regime": market["regime"] if market else None,
        "sector_regime": sector["regime"] if sector else None,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SIMULAZIONE DI UN'OPERAZIONE
# ══════════════════════════════════════════════════════════════════════════════
def simulate(frame: pd.DataFrame, i: int, plan: dict, fill_window: int = FILL_WINDOW) -> dict:
    """
    Ordine piazzato a fine giornata i, eseguibile dalla seduta successiva.
    Stop prima del target se nella stessa seduta si toccano entrambi (ipotesi prudente).
    Un'apertura oltre lo stop o il target esce al prezzo di apertura, non al livello.
    """
    o, h, l, c = (frame[k].to_numpy() for k in ("open", "high", "low", "close"))
    n = len(frame)
    entry, stop, target = plan["entry"], plan["stop"], plan["target"]
    start = i + 1
    if start >= n:
        return {"filled": False, "reason": "dati futuri assenti"}

    fill_j, fill_price = None, None
    if plan["order"] == "Ordine al mercato":
        fill_j, fill_price = start, o[start]
    else:
        for j in range(start, min(start + fill_window, n)):
            if plan["order"] == "Ordine stop di acquisto" and h[j] >= entry:
                fill_j, fill_price = j, max(o[j], entry)
                break
            if plan["order"] == "Ordine limite" and l[j] <= entry:
                fill_j, fill_price = j, min(o[j], entry)
                break
    if fill_j is None:
        return {"filled": False, "reason": "ordine non eseguito"}

    max_days = min(int(plan.get("days_high") or HORIZON_MAX_DAYS), HORIZON_MAX_DAYS)
    exit_j, exit_price, outcome = n - 1, c[n - 1], "in corso"
    for j in range(fill_j, n):
        first_day = j == fill_j
        if l[j] <= stop:
            exit_price = min(o[j], stop) if (not first_day or plan["order"] == "Ordine al mercato") else stop
            exit_j, outcome = j, "stop"
            break
        if h[j] >= target:
            exit_price = max(o[j], target) if not first_day else target
            exit_j, outcome = j, "target"
            break
        if j - fill_j >= max_days:
            exit_j, exit_price, outcome = j, c[j], "scadenza"
            break

    gross = (exit_price / fill_price - 1) * 100 - 2 * COST_PCT
    return {
        "filled": True, "outcome": outcome,
        "fill_date": frame.index[fill_j], "exit_date": frame.index[exit_j], "exit_index": exit_j,
        "fill_price": float(fill_price), "exit_price": float(exit_price),
        "gross_pct": float(gross), "net_pct": float(gross * (1 - TAX_RATE) if gross > 0 else gross),
        "days": int(exit_j - fill_j), "days_low": plan.get("days_low"), "days_high": plan.get("days_high"),
    }


# ══════════════════════════════════════════════════════════════════════════════
# BACKTEST COMPLETO
# ══════════════════════════════════════════════════════════════════════════════
def snapshot_dates(end, years: float, step_days: int):
    start = pd.Timestamp(end) - pd.DateOffset(days=int(round(years * 365)))
    return list(pd.bdate_range(start, end, freq=f"{step_days}B"))


def run_backtest(histories: dict, market_of: dict, sector_of: dict, market_states: dict,
                 sector_states: dict, years: float = 2, step_days: int = 21,
                 min_score: float = VALID_THRESHOLD, on_progress=None) -> tuple[pd.DataFrame, dict]:
    """
    histories: {ticker: storico}; market_of: {ticker: simbolo indice}; sector_of: {ticker: simbolo ETF o None}
    market_states / sector_states: {simbolo: regime_frame}
    Restituisce (operazioni, conteggi). Un titolo non apre una nuova operazione finché la precedente è aperta.
    """
    last_dates = [_naive_index(h.index)[-1] for h in histories.values() if h is not None and not h.empty]
    if not last_dates:
        return pd.DataFrame(), {"segnali": 0, "non_eseguiti": 0, "titoli": 0, "saltati": 0}
    dates = snapshot_dates(max(last_dates), years, step_days)
    trades, counts = [], {"segnali": 0, "non_eseguiti": 0, "titoli": 0, "saltati": 0}

    tickers = list(histories)
    for k, ticker in enumerate(tickers, start=1):
        frame = indicator_frame(histories[ticker])
        if on_progress:
            on_progress(k, len(tickers))
        if frame is None:
            continue
        counts["titoli"] += 1
        market_states_t = market_states.get(market_of.get(ticker))
        sector_states_t = sector_states.get(sector_of.get(ticker)) if sector_of.get(ticker) else None
        busy_until = -1
        for date in dates:
            i = frame.index.searchsorted(date, side="right") - 1
            if i < MIN_HISTORY - 1 or i <= busy_until or i >= len(frame) - 1:
                continue
            try:
                signal = evaluate(ticker, frame, i, frame.index[i],
                                  _state_at(market_states_t, frame.index[i]),
                                  _state_at(sector_states_t, frame.index[i]))
                if not signal or signal["exclusions"] or signal["composite"] < min_score:
                    continue
                result = simulate(frame, i, signal["plan"])
            except Exception as e:          # un dato anomalo non deve fermare tutta la simulazione
                counts["saltati"] += 1
                print(f"[Backtest] {ticker} {frame.index[i].date()}: {type(e).__name__}: {str(e)[:80]}")
                continue
            counts["segnali"] += 1
            if not result["filled"]:
                counts["non_eseguiti"] += 1
                continue
            busy_until = result["exit_index"]
            bench = market_states_t
            bench_ret = None
            if bench is not None and not bench.empty:
                b = bench["close"]
                p0 = b.iloc[b.index.searchsorted(result["fill_date"], side="right") - 1]
                p1 = b.iloc[b.index.searchsorted(result["exit_date"], side="right") - 1]
                bench_ret = (p1 / p0 - 1) * 100
            trades.append({
                "ticker": ticker, "signal_date": frame.index[i], **{k: v for k, v in result.items()
                                                                    if k not in ("filled", "exit_index")},
                "score": signal["composite"], "stage": signal["stage"],
                "market_regime": signal["market_regime"], "sector_regime": signal["sector_regime"] or "n.d.",
                "order": signal["plan"]["order"], "planned_gross_pct": signal["plan"]["gross_pct"],
                "index_pct": bench_ret,
                "excess_pct": (result["gross_pct"] - bench_ret) if bench_ret is not None else None,
            })
    return pd.DataFrame(trades), counts


def summarize(trades: pd.DataFrame) -> dict:
    """Statistiche delle sole operazioni chiuse."""
    closed = trades[trades["outcome"] != "in corso"] if not trades.empty else trades
    if closed.empty:
        return {"chiuse": 0}
    targets = closed[closed["outcome"] == "target"]
    in_time = targets[(targets["days_high"].notna()) & (targets["days"] <= targets["days_high"])]
    return {
        "chiuse": len(closed),
        "in_corso": int((trades["outcome"] == "in corso").sum()),
        "target_pct": (closed["outcome"] == "target").mean() * 100,
        "stop_pct": (closed["outcome"] == "stop").mean() * 100,
        "scadenza_pct": (closed["outcome"] == "scadenza").mean() * 100,
        "win_pct": (closed["gross_pct"] > 0).mean() * 100,
        "media_netta": closed["net_pct"].mean(),
        "mediana_netta": closed["net_pct"].median(),
        "media_lorda": closed["gross_pct"].mean(),
        "extra_vs_indice": closed["excess_pct"].dropna().mean() if closed["excess_pct"].notna().any() else None,
        "giorni_medi": closed["days"].mean(),
        "target_nei_tempi_pct": (len(in_time) / len(targets) * 100) if len(targets) else None,
    }


def breakdown(trades: pd.DataFrame, by: str) -> pd.DataFrame:
    """Risultati raggruppati (per fascia di punteggio, regime del settore, fase del grafico…)."""
    closed = trades[trades["outcome"] != "in corso"]
    if closed.empty:
        return pd.DataFrame()
    g = closed.groupby(by, dropna=False)
    return pd.DataFrame({
        "Operazioni": g.size(),
        "Target %": g.apply(lambda x: (x["outcome"] == "target").mean() * 100),
        "Stop %": g.apply(lambda x: (x["outcome"] == "stop").mean() * 100),
        "In guadagno %": g.apply(lambda x: (x["gross_pct"] > 0).mean() * 100),
        "Netto medio %": g["net_pct"].mean(),
        "Extra vs indice %": g["excess_pct"].mean(),
    }).round(2)


def score_bucket(score: float) -> str:
    if score >= 85:
        return "85 e oltre"
    if score >= 75:
        return "75–84"
    return "65–74"
