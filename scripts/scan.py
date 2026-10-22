#!/usr/bin/env python3
"""Build data/scanner.json from free, delayed Yahoo Finance market data.

The script exits non-zero before replacing an existing scan when the market-data
download is unusable or suspiciously incomplete. It never emits sample prices.
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "scanner.json"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
SEC_USER_AGENT = "MarketScout/1.0 lmccorkle1@users.noreply.github.com"
EXTRA_SYMBOLS = {
    "ARM", "COIN", "CRWD", "DDOG", "DUOL", "HIMS", "HOOD", "IBIT",
    "MELI", "NBIS", "NET", "PLTR", "RDDT", "SHOP", "SNOW", "SOFI",
    "TEM", "TSM", "UBER",
}
MIN_RESULTS = 350
CHUNK_SIZE = 75
ENRICH_CANDIDATES = 40
MIN_FUNDAMENTAL_FIELDS = 7
INFO_WORKERS = 5


def get_universe() -> tuple[list[str], dict[str, tuple[str, str, int | None]], str]:
    """Return actual S&P 500 constituents plus a small disclosed growth list."""
    request = Request(
        WIKIPEDIA_URL,
        headers={"User-Agent": "MarketScout/1.0 (public GitHub Actions market research tool)"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    tables = pd.read_html(StringIO(html))
    classifications: dict[str, tuple[str, str, int | None]] = {}
    for _, row in tables[0].iterrows():
        symbol = str(row["Symbol"]).strip().replace(".", "-")
        sector = row.get("GICS Sector")
        industry = row.get("GICS Sub-Industry")
        cik_value = finite(row.get("CIK"))
        classifications[symbol] = (
            "Unknown" if pd.isna(sector) else str(sector).strip(),
            "Unknown" if pd.isna(industry) else str(industry).strip(),
            None if cik_value is None else int(cik_value),
        )
    symbols = set(classifications)
    if len(symbols) < 450:
        raise RuntimeError(f"Constituent list unexpectedly contained only {len(symbols)} symbols")
    for symbol in EXTRA_SYMBOLS:
        classifications.setdefault(symbol, ("Unknown", "Unknown", None))
    return sorted(symbols | EXTRA_SYMBOLS), classifications, "Wikipedia S&P 500 list + disclosed selected growth/ETF symbols"


def finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def download_chunk(symbols: list[str]) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            data = yf.download(
                symbols,
                period="1y",
                interval="1d",
                auto_adjust=True,
                progress=False,
                group_by="column",
                threads=True,
                timeout=30,
            )
            if not data.empty:
                return data
        except Exception as error:  # yfinance can raise several network exceptions
            last_error = error
        time.sleep(2 ** attempt)
    raise RuntimeError(f"Price download failed after retries: {last_error or 'empty response'}")


def extract_close(frame: pd.DataFrame, symbol: str, multiple: bool) -> pd.Series:
    try:
        series = frame[("Close", symbol)] if multiple else frame["Close"]
    except (KeyError, TypeError):
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def extract_volume(frame: pd.DataFrame, symbol: str, multiple: bool) -> pd.Series:
    try:
        series = frame[("Volume", symbol)] if multiple else frame["Volume"]
    except (KeyError, TypeError):
        return pd.Series(dtype=float)
    return pd.to_numeric(series, errors="coerce").dropna()


def bounded_score(value: float | None, low: float, high: float, points: float) -> float | None:
    """Linearly score a metric, returning None rather than guessing missing values."""
    if value is None:
        return None
    if high == low:
        return points if value >= high else 0.0
    return round(max(0.0, min(points, (value - low) / (high - low) * points)), 2)


def inverse_score(value: float | None, good: float, bad: float, points: float) -> float | None:
    if value is None or value <= 0:
        return None
    return bounded_score(bad - value, 0, bad - good, points)


def safe_website(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value.startswith(("https://", "http://")) and len(value) <= 500 else None


def upcoming_earnings_date(info: dict[str, object]) -> str | None:
    """Return a sourced future earnings date, or None when Yahoo does not provide one."""
    now = datetime.now(timezone.utc)
    for key in ("earningsTimestampStart", "earningsTimestamp", "earningsTimestampEnd"):
        timestamp = finite(info.get(key))
        if timestamp is None:
            continue
        try:
            value = datetime.fromtimestamp(timestamp, timezone.utc)
        except (OSError, OverflowError, ValueError):
            continue
        if value.date() >= now.date():
            return value.date().isoformat()
    return None


def statement_value(frame: pd.DataFrame, row: str, position: int) -> float | None:
    if row not in frame.index or len(frame.columns) <= position:
        return None
    return finite(frame.loc[row].iloc[position])


def percent_change(current: float | None, prior: float | None) -> float | None:
    if current is None or prior is None or prior <= 0:
        return None
    return (current / prior - 1) * 100


def quarterly_trends(ticker: yf.Ticker) -> dict[str, object]:
    """Calculate same-quarter year-over-year trends without filling missing facts."""
    income = ticker.get_income_stmt(freq="quarterly")
    cash = ticker.get_cash_flow(freq="quarterly")
    balance = ticker.get_balance_sheet(freq="quarterly")
    frames = (income, cash, balance)
    if any(not isinstance(frame, pd.DataFrame) for frame in frames):
        income = cash = balance = pd.DataFrame()
        frames = (income, cash, balance)
    for frame in frames:
        if not frame.empty:
            frame.sort_index(axis=1, ascending=False, inplace=True)

    latest_period = None if income.empty else pd.Timestamp(income.columns[0]).date().isoformat()
    year_ago_period = None if len(income.columns) < 5 else pd.Timestamp(income.columns[4]).date().isoformat()
    revenue = statement_value(income, "TotalRevenue", 0)
    revenue_prior = statement_value(income, "TotalRevenue", 4)
    operating_income = statement_value(income, "OperatingIncome", 0)
    operating_income_prior = statement_value(income, "OperatingIncome", 4)
    net_income = statement_value(income, "NetIncome", 0)
    net_income_prior = statement_value(income, "NetIncome", 4)
    free_cash_flow = statement_value(cash, "FreeCashFlow", 0)
    free_cash_flow_prior = statement_value(cash, "FreeCashFlow", 4)
    total_debt = statement_value(balance, "TotalDebt", 0)
    total_debt_prior = statement_value(balance, "TotalDebt", 4)
    shares = statement_value(balance, "OrdinarySharesNumber", 0)
    shares_prior = statement_value(balance, "OrdinarySharesNumber", 4)
    margin = None if revenue in (None, 0) or operating_income is None else operating_income / revenue * 100
    margin_prior = None if revenue_prior in (None, 0) or operating_income_prior is None else operating_income_prior / revenue_prior * 100
    margin_change = None if margin is None or margin_prior is None else margin - margin_prior
    metrics = {
        "latest_period": latest_period,
        "year_ago_period": year_ago_period,
        "revenue_yoy_pct": percent_change(revenue, revenue_prior),
        "operating_margin_pct": margin,
        "operating_margin_change_pp": margin_change,
        "net_income_latest": net_income,
        "net_income_year_ago": net_income_prior,
        "free_cash_flow_latest": free_cash_flow,
        "free_cash_flow_yoy_pct": percent_change(free_cash_flow, free_cash_flow_prior),
        "debt_yoy_pct": percent_change(total_debt, total_debt_prior),
        "shares_yoy_pct": percent_change(shares, shares_prior),
    }
    metrics = {key: (None if value is None else round(value, 2)) if not isinstance(value, str) else value for key, value in metrics.items()}
    flags: list[str] = []
    if metrics["revenue_yoy_pct"] is not None and metrics["revenue_yoy_pct"] < -5:
        flags.append("Revenue declined more than 5% year over year")
    if metrics["operating_margin_change_pp"] is not None and metrics["operating_margin_change_pp"] < -3:
        flags.append("Operating margin contracted more than 3 percentage points")
    if metrics["net_income_latest"] is not None and metrics["net_income_latest"] < 0:
        flags.append("Latest quarter reported a net loss")
    if metrics["free_cash_flow_latest"] is not None and metrics["free_cash_flow_latest"] < 0:
        flags.append("Latest quarter reported negative free cash flow")
    if metrics["debt_yoy_pct"] is not None and metrics["debt_yoy_pct"] > 20:
        flags.append("Total debt increased more than 20% year over year")
    if metrics["shares_yoy_pct"] is not None and metrics["shares_yoy_pct"] > 5:
        flags.append("Share count increased more than 5% year over year")
    numeric_fields = [key for key, value in metrics.items() if key not in ("latest_period", "year_ago_period") and value is not None]
    return {
        "metrics": metrics,
        "fields_available": len(numeric_fields),
        "value_trap_flags": flags,
        "status": "available" if latest_period and year_ago_period else "insufficient_history",
        "source": "Yahoo Finance quarterly statements accessed through yfinance; verify against SEC filings.",
    }


def sec_duration_fact(companyfacts: dict[str, object], tags: tuple[str, ...], end: str) -> float | None:
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        values = facts.get(tag, {}).get("units", {}).get("USD", [])
        candidates = []
        for item in values:
            if item.get("end") != end or item.get("form") not in ("10-Q", "10-K") or not item.get("start"):
                continue
            try:
                days = (datetime.fromisoformat(end) - datetime.fromisoformat(item["start"])).days
            except (TypeError, ValueError):
                continue
            if 70 <= days <= 110 and finite(item.get("val")) is not None:
                candidates.append(item)
        if candidates:
            candidates.sort(key=lambda item: (item.get("filed", ""), item.get("accn", "")), reverse=True)
            return finite(candidates[0].get("val"))
    return None


def sec_confirmation(row: dict[str, object]) -> dict[str, object]:
    cik = row.get("cik")
    trends = row.get("research", {}).get("quarterly_trends", {})
    metrics = trends.get("metrics", {})
    if not isinstance(cik, int) or not metrics.get("latest_period") or not metrics.get("year_ago_period"):
        return {"status": "unavailable", "reason": "CIK or comparable quarterly periods unavailable", "metrics": {}}
    request = Request(
        SEC_COMPANYFACTS_URL.format(cik=cik),
        headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            companyfacts = json.load(response)
    except Exception as error:
        return {"status": "unavailable", "reason": f"SEC request failed: {type(error).__name__}", "metrics": {}}
    revenue_tags = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
    operating_tags = ("OperatingIncomeLoss",)
    latest = metrics["latest_period"]
    prior = metrics["year_ago_period"]
    revenue = sec_duration_fact(companyfacts, revenue_tags, latest)
    revenue_prior = sec_duration_fact(companyfacts, revenue_tags, prior)
    operating = sec_duration_fact(companyfacts, operating_tags, latest)
    operating_prior = sec_duration_fact(companyfacts, operating_tags, prior)
    revenue_yoy = percent_change(revenue, revenue_prior)
    margin = None if revenue in (None, 0) or operating is None else operating / revenue * 100
    margin_prior = None if revenue_prior in (None, 0) or operating_prior is None else operating_prior / revenue_prior * 100
    margin_change = None if margin is None or margin_prior is None else margin - margin_prior
    comparisons: dict[str, bool] = {}
    if revenue_yoy is not None and metrics.get("revenue_yoy_pct") is not None:
        comparisons["revenue_yoy"] = abs(revenue_yoy - metrics["revenue_yoy_pct"]) <= 2
    if margin_change is not None and metrics.get("operating_margin_change_pp") is not None:
        comparisons["operating_margin_change"] = abs(margin_change - metrics["operating_margin_change_pp"]) <= 2
    if not comparisons:
        status, reason = "unavailable", "Comparable standardized SEC quarterly facts were not available"
    elif all(comparisons.values()):
        status, reason = ("confirmed" if len(comparisons) == 2 else "partial"), "Available SEC comparisons were within 2 percentage points"
    else:
        status, reason = "mismatch", "At least one SEC comparison differed by more than 2 percentage points"
    return {
        "status": status,
        "reason": reason,
        "metrics": {
            "revenue_yoy_pct": None if revenue_yoy is None else round(revenue_yoy, 2),
            "operating_margin_change_pp": None if margin_change is None else round(margin_change, 2),
        },
        "comparisons": comparisons,
        "source": SEC_COMPANYFACTS_URL.format(cik=cik),
    }


def score_company(info: dict[str, object], price_score: float) -> dict[str, object]:
    """Return an auditable 90-point score; catalysts deliberately remain manual."""
    market_cap = finite(info.get("marketCap"))
    free_cash_flow = finite(info.get("freeCashflow"))
    metrics = {
        "revenue_growth_pct": None if finite(info.get("revenueGrowth")) is None else finite(info.get("revenueGrowth")) * 100,
        "earnings_growth_pct": None if finite(info.get("earningsGrowth")) is None else finite(info.get("earningsGrowth")) * 100,
        "profit_margin_pct": None if finite(info.get("profitMargins")) is None else finite(info.get("profitMargins")) * 100,
        "return_on_equity_pct": None if finite(info.get("returnOnEquity")) is None else finite(info.get("returnOnEquity")) * 100,
        "trailing_pe": finite(info.get("trailingPE")),
        "ev_to_ebitda": finite(info.get("enterpriseToEbitda")),
        "fcf_yield_pct": None if not market_cap or free_cash_flow is None else free_cash_flow / market_cap * 100,
        "debt_to_equity": finite(info.get("debtToEquity")),
        "current_ratio": finite(info.get("currentRatio")),
        "free_cash_flow": free_cash_flow,
        "market_cap": market_cap,
    }
    parts = {
        "revenue_growth": bounded_score(metrics["revenue_growth_pct"], -5, 20, 10),
        "earnings_growth": bounded_score(metrics["earnings_growth_pct"], -10, 25, 10),
        "profit_margin": bounded_score(metrics["profit_margin_pct"], 0, 20, 5),
        "return_on_equity": bounded_score(metrics["return_on_equity_pct"], 0, 25, 5),
        "trailing_pe": inverse_score(metrics["trailing_pe"], 12, 40, 10),
        "fcf_yield": bounded_score(metrics["fcf_yield_pct"], 0, 8, 10),
        "ev_to_ebitda": inverse_score(metrics["ev_to_ebitda"], 8, 25, 5),
        "debt_to_equity": inverse_score(metrics["debt_to_equity"], 40, 200, 6),
        "current_ratio": bounded_score(metrics["current_ratio"], 0.7, 2.0, 4),
        "positive_fcf": None if free_cash_flow is None else (5.0 if free_cash_flow > 0 else 0.0),
    }
    fundamentals = sum(value or 0 for value in (parts[k] for k in ("revenue_growth", "earnings_growth", "profit_margin", "return_on_equity")))
    valuation = sum(value or 0 for value in (parts[k] for k in ("trailing_pe", "fcf_yield", "ev_to_ebitda")))
    strength = sum(value or 0 for value in (parts[k] for k in ("debt_to_equity", "current_ratio", "positive_fcf")))
    selloff = round(max(0.0, min(20.0, price_score / 5)), 2)
    available = sum(value is not None for value in parts.values())
    return {
        "metrics": {key: None if value is None else round(value, 2) for key, value in metrics.items()},
        "component_scores": {
            "fundamentals_30": round(fundamentals, 1),
            "valuation_25": round(valuation, 1),
            "selloff_20": round(selloff, 1),
            "financial_strength_15": round(strength, 1),
            "catalysts_10": None,
        },
        "quant_score_90": round(fundamentals + valuation + selloff + strength, 1),
        "data_fields_available": available,
        "data_fields_required": MIN_FUNDAMENTAL_FIELDS,
        "eligible": available >= MIN_FUNDAMENTAL_FIELDS,
        "catalyst_status": "Manual research required; no automated catalyst points awarded.",
        "company_website": safe_website(info.get("website")),
        "next_earnings_date": upcoming_earnings_date(info),
    }


def enrich_one(row: dict[str, object]) -> tuple[str, dict[str, object] | None, str | None]:
    symbol = str(row["ticker"])
    for attempt in range(2):
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.get_info()
            if isinstance(info, dict) and info:
                result = score_company(info, float(row["price_score"]))
                try:
                    result["quarterly_trends"] = quarterly_trends(ticker)
                except Exception as error:
                    result["quarterly_trends"] = {
                        "metrics": {},
                        "fields_available": 0,
                        "value_trap_flags": [],
                        "status": "unavailable",
                        "source": f"Quarterly statement request failed: {type(error).__name__}",
                    }
                return symbol, result, None
        except Exception as error:
            last_error = type(error).__name__
        time.sleep(1 + attempt)
    return symbol, None, locals().get("last_error", "empty response")


def scan() -> dict[str, object]:
    symbols, classifications, universe_source = get_universe()
    rows: list[dict[str, object]] = []
    failures: list[str] = []

    for start in range(0, len(symbols), CHUNK_SIZE):
        chunk = symbols[start : start + CHUNK_SIZE]
        try:
            frame = download_chunk(chunk)
        except RuntimeError:
            failures.extend(chunk)
            continue
        for symbol in chunk:
            close = extract_close(frame, symbol, len(chunk) > 1)
            volume = extract_volume(frame, symbol, len(chunk) > 1)
            if len(close) < 50:
                failures.append(symbol)
                continue
            price = finite(close.iloc[-1])
            high = finite(close.max())
            ma50 = finite(close.tail(50).mean())
            if price is None or high is None or ma50 is None or high <= 0:
                failures.append(symbol)
                continue
            drawdown = (price / high - 1) * 100
            below_ma50 = (price / ma50 - 1) * 100 if ma50 > 0 else 0
            # Transparent price-only heuristic, capped to avoid extreme outliers.
            score = min(100.0, max(0.0, -drawdown * 1.5 + max(0.0, -below_ma50)))
            price_date = pd.Timestamp(close.index[-1]).date().isoformat()
            aligned_volume = volume.reindex(close.index)
            average_dollar_volume = finite((close * aligned_volume).dropna().tail(20).mean())
            rows.append({
                "ticker": symbol,
                "sector": classifications[symbol][0],
                "industry": classifications[symbol][1],
                "cik": classifications[symbol][2],
                "price": round(price, 2),
                "drawdown_pct": round(drawdown, 1),
                "ma50": round(ma50, 2),
                "average_dollar_volume_20d": None if average_dollar_volume is None else round(average_dollar_volume, 2),
                "price_score": round(score, 1),
                "price_date": price_date,
            })

    if len(rows) < MIN_RESULTS:
        raise RuntimeError(
            f"Only {len(rows)} of {len(symbols)} symbols had verified data; "
            f"minimum is {MIN_RESULTS}. Preserving the previous published scan."
        )

    rows.sort(key=lambda row: (-float(row["price_score"]), str(row["ticker"])))
    enrichment_failures: list[str] = []
    candidates = rows[:ENRICH_CANDIDATES]
    by_symbol = {str(row["ticker"]): row for row in candidates}
    with ThreadPoolExecutor(max_workers=INFO_WORKERS) as pool:
        futures = [pool.submit(enrich_one, row) for row in candidates]
        for future in as_completed(futures):
            symbol, result, error = future.result()
            if result is None:
                enrichment_failures.append(symbol)
            else:
                by_symbol[symbol]["research"] = result

    ranked = [row for row in candidates if row.get("research", {}).get("eligible")]
    ranked.sort(key=lambda row: (-float(row["research"]["quant_score_90"]), str(row["ticker"])))
    top_five = ranked[:5]
    for row in top_five:
        row["research"]["sec_xbrl_confirmation"] = sec_confirmation(row)
        time.sleep(0.15)
    return {
        "schema_version": 6,
        "status": "ok" if not failures else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "universe_source": universe_source,
        "universe_count": len(symbols),
        "screened_count": len(rows),
        "failed_count": len(set(failures)),
        "failed_symbols": sorted(set(failures)),
        "score_explanation": "Price score screens the full universe. The research shortlist scores verified fundamentals (30), valuation (25), selloff (20), and financial strength (15). Catalysts (10) require manual research and are not awarded automatically.",
        "research_method": {
            "candidate_pool": ENRICH_CANDIDATES,
            "eligible_count": len(ranked),
            "enrichment_failed_symbols": sorted(enrichment_failures),
            "maximum_automated_score": 90,
            "catalyst_points_reserved": 10,
            "minimum_fundamental_fields": MIN_FUNDAMENTAL_FIELDS,
            "fundamental_source": "Yahoo Finance data accessed through yfinance; fields may be delayed or unavailable.",
            "filing_source": "SEC EDGAR company filings, linked by CIK when available.",
        },
        "top_five": top_five,
        "stocks": rows,
    }


def main() -> int:
    try:
        payload = scan()
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, allow_nan=False)
            handle.write("\n")
            temporary = Path(handle.name)
        os.replace(temporary, OUTPUT)
        print(f"Published {payload['screened_count']} verified symbols to {OUTPUT}")
        return 0
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
