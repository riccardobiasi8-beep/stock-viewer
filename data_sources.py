"""
Data Sources — cascata per completare dati mancanti da Yahoo Finance.
Tier 1: yfinance bilanci grezzi (sempre gratis, nessun limite)
Tier 2: Financial Modeling Prep (250 req/giorno gratis)
"""
import requests
import pandas as pd


def _safe_float(val):
    try:
        v = float(val)
        return None if v != v else v
    except:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# TIER 1 — yfinance bilanci grezzi
# ══════════════════════════════════════════════════════════════════════════════

def enrich_from_statements(ticker_obj, info: dict) -> dict:
    """
    Calcola fondamentali direttamente dai bilanci yfinance.
    Restituisce un dict con i campi trovati (solo quelli non già presenti in info).
    """
    result = {}
    try:
        fin = ticker_obj.financials       # conto economico annuale
        bal = ticker_obj.balance_sheet    # stato patrimoniale
        price = _safe_float(info.get('currentPrice') or info.get('regularMarketPrice'))

        def _get(df, *keys):
            if df is None or df.empty:
                return None
            for k in keys:
                try:
                    row = df.loc[k]
                    val = _safe_float(row.iloc[0])
                    if val is not None:
                        return val
                except:
                    continue
            return None

        net_income   = _get(fin, 'Net Income', 'NetIncome')
        revenue      = _get(fin, 'Total Revenue', 'TotalRevenue')
        equity       = _get(bal, 'Stockholders Equity', 'StockholdersEquity',
                            'Total Stockholder Equity')
        total_assets = _get(bal, 'Total Assets', 'TotalAssets')
        total_debt   = _get(bal, 'Total Debt', 'TotalDebt',
                            'Long Term Debt', 'LongTermDebt')

        # Profit Margin
        if info.get('profitMargins') is None and net_income and revenue and revenue != 0:
            result['profitMargins'] = round(net_income / revenue, 4)  # decimal

        # Revenue Growth YoY
        if info.get('revenueGrowth') is None:
            try:
                if fin is not None and not fin.empty and fin.shape[1] >= 2:
                    r0 = _safe_float(fin.loc['Total Revenue'].iloc[0])
                    r1 = _safe_float(fin.loc['Total Revenue'].iloc[1])
                    if r0 and r1 and r1 != 0:
                        result['revenueGrowth'] = round((r0 - r1) / abs(r1), 4)
            except:
                pass

        # ROE (con guardrail per equity negativo/buyback)
        if info.get('returnOnEquity') is None and net_income:
            if equity and equity > 0 and total_assets:
                equity_ratio = equity / total_assets
                if equity_ratio >= 0.10:
                    result['returnOnEquity'] = round(net_income / equity, 4)
                else:
                    # Equity troppo bassa (buyback) → usa ROA
                    if total_assets > 0:
                        result['returnOnEquity'] = round(net_income / total_assets, 4)
                        result['_roe_is_roa'] = True
            elif equity and equity < 0 and total_assets:
                # Equity negativa → ROA
                result['returnOnEquity'] = round(net_income / total_assets, 4)
                result['_roe_is_roa'] = True

        # ROA
        if info.get('returnOnAssets') is None and net_income and total_assets and total_assets > 0:
            result['returnOnAssets'] = round(net_income / total_assets, 4)

        # Debt/Equity
        if info.get('debtToEquity') is None and total_debt is not None and equity and equity > 0:
            result['debtToEquity'] = round(total_debt / equity * 100, 2)  # Yahoo format ×100

        # P/E da EPS
        if info.get('trailingPE') is None and price:
            eps = _safe_float(info.get('trailingEps') or info.get('forwardEps'))
            if eps and eps > 0:
                result['trailingPE'] = round(price / eps, 1)

        # P/B
        if info.get('priceToBook') is None and price:
            bvps = _safe_float(info.get('bookValue'))
            if bvps and bvps > 0:
                result['priceToBook'] = round(price / bvps, 2)

        # Gross Margin
        if info.get('grossMargins') is None:
            gross_profit = _get(fin, 'Gross Profit', 'GrossProfit')
            if gross_profit and revenue and revenue != 0:
                result['grossMargins'] = round(gross_profit / revenue, 4)

        # Operating Margin
        if info.get('operatingMargins') is None:
            op_income = _get(fin, 'Operating Income', 'OperatingIncome',
                            'Total Operating Income As Reported')
            if op_income and revenue and revenue != 0:
                result['operatingMargins'] = round(op_income / revenue, 4)

        filled = [k for k in result if not k.startswith('_')]
        if filled:
            print(f"[T1 bilanci] Filled: {filled}")

    except Exception as e:
        print(f"[T1 bilanci] Error: {e}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# TIER 2 — Financial Modeling Prep
# ══════════════════════════════════════════════════════════════════════════════

FMP_BASE = "https://financialmodelingprep.com/api/v3"

def enrich_from_fmp(ticker_sym: str, info: dict, fmp_key: str) -> dict:
    """Fill missing fields from FMP API (250 req/day free)."""
    if not fmp_key:
        return {}

    missing = [k for k in ['trailingPE', 'priceToBook', 'enterpriseToEbitda',
                            'returnOnEquity', 'profitMargins', 'grossMargins',
                            'operatingMargins', 'revenueGrowth', 'debtToEquity',
                            'beta', 'dividendYield']
               if info.get(k) is None]
    if not missing:
        return {}

    result = {}
    # Remove exchange suffix for FMP
    sym = ticker_sym.split('.')[0]

    try:
        # Key metrics TTM
        r = requests.get(f"{FMP_BASE}/key-metrics-ttm/{sym}?apikey={fmp_key}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                m = data[0]
                fmp_map = {
                    'trailingPE':          ('peRatioTTM',         None),
                    'priceToBook':         ('pbRatioTTM',         None),
                    'enterpriseToEbitda':  ('evToEbitdaTTM',      None),
                    'returnOnEquity':      ('roeTTM',             0.01),   # FMP gives decimal
                    'debtToEquity':        ('debtToEquityTTM',    100),    # Yahoo format ×100
                    'dividendYield':       ('dividendYieldTTM',   None),
                }
                for yahoo_key, (fmp_key_name, multiplier) in fmp_map.items():
                    if info.get(yahoo_key) is None:
                        val = _safe_float(m.get(fmp_key_name))
                        if val is not None:
                            if multiplier:
                                val = val * multiplier
                            result[yahoo_key] = round(val, 4)
    except Exception as e:
        print(f"[T2 FMP metrics] Error: {e}")

    try:
        # Ratios for margins
        r2 = requests.get(f"{FMP_BASE}/ratios-ttm/{sym}?apikey={fmp_key}", timeout=10)
        if r2.status_code == 200:
            data2 = r2.json()
            if data2 and isinstance(data2, list):
                m2 = data2[0]
                margin_map = {
                    'profitMargins':    'netProfitMarginTTM',
                    'grossMargins':     'grossProfitMarginTTM',
                    'operatingMargins': 'operatingProfitMarginTTM',
                }
                for yahoo_key, fmp_key_name in margin_map.items():
                    if info.get(yahoo_key) is None:
                        val = _safe_float(m2.get(fmp_key_name))
                        if val is not None:
                            result[yahoo_key] = round(val, 4)
    except Exception as e:
        print(f"[T2 FMP ratios] Error: {e}")

    try:
        # Revenue growth from income statements
        if info.get('revenueGrowth') is None:
            r3 = requests.get(f"{FMP_BASE}/income-statement/{sym}?limit=2&apikey={fmp_key}", timeout=10)
            if r3.status_code == 200:
                stmts = r3.json()
                if stmts and len(stmts) >= 2:
                    r0 = _safe_float(stmts[0].get('revenue'))
                    r1 = _safe_float(stmts[1].get('revenue'))
                    if r0 and r1 and r1 != 0:
                        result['revenueGrowth'] = round((r0 - r1) / abs(r1), 4)
    except Exception as e:
        print(f"[T2 FMP growth] Error: {e}")

    filled = list(result.keys())
    if filled:
        print(f"[T2 FMP] Filled: {filled}")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# MAIN — merge all sources
# ══════════════════════════════════════════════════════════════════════════════

def enrich_info(ticker_obj, ticker_sym: str, info: dict, fmp_key: str = "") -> dict:
    """
    Enrich info dict with data from all available sources.
    Returns merged dict — original info takes precedence over enriched values.
    """
    enriched = dict(info)

    # Fields we want to fill
    target_fields = ['trailingPE', 'priceToBook', 'enterpriseToEbitda',
                     'returnOnEquity', 'returnOnAssets', 'profitMargins',
                     'grossMargins', 'operatingMargins', 'revenueGrowth',
                     'earningsGrowth', 'debtToEquity', 'beta', 'dividendYield']

    missing_before = [f for f in target_fields if enriched.get(f) is None]
    if not missing_before:
        return enriched

    print(f"[Enricher] {ticker_sym} — missing: {missing_before}")

    # Tier 1: yfinance statements
    t1 = enrich_from_statements(ticker_obj, enriched)
    for k, v in t1.items():
        if enriched.get(k) is None:
            enriched[k] = v

    # Tier 2: FMP (only if still missing and key available)
    missing_after_t1 = [f for f in target_fields if enriched.get(f) is None]
    if missing_after_t1 and fmp_key:
        t2 = enrich_from_fmp(ticker_sym, enriched, fmp_key)
        for k, v in t2.items():
            if enriched.get(k) is None:
                enriched[k] = v

    missing_after = [f for f in target_fields if enriched.get(f) is None]
    if len(missing_after) < len(missing_before):
        print(f"[Enricher] Filled {len(missing_before)-len(missing_after)} fields. Still missing: {missing_after}")

    return enriched


# ══════════════════════════════════════════════════════════════════════════════
# FONDAMENTALI SOLO DAI BILANCI — quando Yahoo rifiuta il riepilogo (errore 401)
# ══════════════════════════════════════════════════════════════════════════════
def _row(df, *names):
    """Valore più recente della prima riga trovata tra i nomi indicati."""
    if df is None or getattr(df, "empty", True):
        return None
    for name in names:
        if name in df.index:
            for value in df.loc[name].tolist():
                v = _safe_float(value)
                if v is not None:
                    return v
    return None


def fundamentals_from_statements(ticker_obj, price: float, currency: str) -> dict:
    """
    Ricostruisce i fondamentali dagli ultimi bilanci annuali e dal prezzo.
    Prezzo e valuta arrivano dallo storico già scaricato: nessuna chiamata al riepilogo.
    Restituisce {} se i bilanci non sono disponibili.
    """
    inc = ticker_obj.income_stmt
    bal = ticker_obj.balance_sheet
    cf = ticker_obj.cashflow
    if (inc is None or inc.empty) and (bal is None or bal.empty):
        return {}

    net_income = _row(inc, "Net Income", "Net Income Common Stockholders")
    revenue = _row(inc, "Total Revenue", "Operating Revenue")
    ebitda = _row(inc, "EBITDA", "Normalized EBITDA")
    gross = _row(inc, "Gross Profit")
    operating = _row(inc, "Operating Income", "Total Operating Income As Reported")
    equity = _row(bal, "Stockholders Equity", "Common Stock Equity")
    assets = _row(bal, "Total Assets")
    debt = _row(bal, "Total Debt")
    cash = _row(bal, "Cash And Cash Equivalents",
                "Cash Cash Equivalents And Short Term Investments")
    shares = _row(bal, "Ordinary Shares Number", "Share Issued")
    fcf = _row(cf, "Free Cash Flow")

    # Le azioni di Londra sono quotate in pence: la capitalizzazione va in sterline
    price_major = price / 100 if currency == "GBp" else price
    market_cap = shares * price_major if shares and price_major else None

    out = {"currentPrice": price, "currency": currency, "_source": "statements"}
    if market_cap:
        out["marketCap"] = market_cap
    if market_cap and net_income and net_income > 0:
        pe = market_cap / net_income
        if 1 <= pe <= 300:
            out["trailingPE"] = round(pe, 1)
    if market_cap and ebitda and ebitda > 0:
        ev_ebitda = (market_cap + (debt or 0) - (cash or 0)) / ebitda
        if 0 < ev_ebitda <= 100:
            out["enterpriseToEbitda"] = round(ev_ebitda, 1)
    if market_cap and equity and equity > 0:
        out["priceToBook"] = round(market_cap / equity, 2)
    if net_income is not None and revenue:
        out["profitMargins"] = round(net_income / revenue, 4)
    if gross is not None and revenue:
        out["grossMargins"] = round(gross / revenue, 4)
    if operating is not None and revenue:
        out["operatingMargins"] = round(operating / revenue, 4)
    if net_income is not None and equity and assets:
        if equity > 0 and equity / assets >= 0.10:
            out["returnOnEquity"] = round(net_income / equity, 4)
        else:                                   # patrimonio quasi nullo (riacquisti): ROA
            out["returnOnEquity"] = round(net_income / assets, 4)
            out["_roe_is_roa"] = True
    if net_income is not None and assets:
        out["returnOnAssets"] = round(net_income / assets, 4)
    if debt is not None and equity and equity > 0:
        out["debtToEquity"] = round(debt / equity * 100, 2)
    if fcf is not None:
        out["freeCashflow"] = fcf
    try:
        revenues = [_safe_float(v) for v in inc.loc["Total Revenue"].tolist()]
        revenues = [v for v in revenues if v]
        if len(revenues) >= 2:
            out["revenueGrowth"] = round((revenues[0] - revenues[1]) / abs(revenues[1]), 4)
    except Exception:
        pass
    return out
