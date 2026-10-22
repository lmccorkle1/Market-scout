#!/usr/bin/env python3
"""Measure saved Market Scout selections only after each trading horizon matures."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = ROOT / "data" / "history"
OUTPUT = ROOT / "data" / "performance.json"
HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252, "24m": 504}
SECTOR_ETFS = {
    "Communication Services": "XLC", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Energy": "XLE", "Financials": "XLF",
    "Health Care": "XLV", "Industrials": "XLI", "Information Technology": "XLK",
    "Materials": "XLB", "Real Estate": "XLRE", "Utilities": "XLU",
}


def atomic_write(payload: dict[str, object]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, OUTPUT)


def finite(value: object) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def download_closes(symbols: list[str], start: date) -> dict[str, pd.Series]:
    closes: dict[str, pd.Series] = {}
    end = datetime.now(timezone.utc).date() + timedelta(days=1)
    for offset in range(0, len(symbols), 75):
        chunk = symbols[offset : offset + 75]
        frame = yf.download(
            chunk, start=(start - timedelta(days=7)).isoformat(), end=end.isoformat(),
            auto_adjust=True, progress=False, group_by="column", threads=True, timeout=30,
        )
        if frame.empty:
            continue
        multiple = len(chunk) > 1
        for symbol in chunk:
            try:
                series = frame[("Close", symbol)] if multiple else frame["Close"]
            except (KeyError, TypeError):
                continue
            series = pd.to_numeric(series, errors="coerce").dropna()
            if not series.empty:
                closes[symbol] = series
    return closes


def close_on(series: pd.Series | None, target: date) -> float | None:
    if series is None:
        return None
    matches = series[pd.to_datetime(series.index).date == target]
    return None if matches.empty else finite(matches.iloc[-1])


def total_return(series: pd.Series | None, start: date, end: date) -> float | None:
    beginning = close_on(series, start)
    ending = close_on(series, end)
    if beginning in (None, 0) or ending is None:
        return None
    return round((ending / beginning - 1) * 100, 2)


def build_performance() -> dict[str, object]:
    index = json.loads((HISTORY_DIR / "index.json").read_text(encoding="utf-8"))
    snapshots = [json.loads((HISTORY_DIR / entry["path"]).read_text(encoding="utf-8")) for entry in index["snapshots"]]
    today = datetime.now(timezone.utc).date()
    results = []
    for snapshot in snapshots:
        selection_date = date.fromisoformat(snapshot["selection_date"])
        # Waiting this minimum avoids network calls while even the shortest horizon cannot be mature.
        needs_prices = (today - selection_date).days >= 28
        top_rows = snapshot["top_five"]
        sectors = {row["ticker"]: row.get("sector", "Unknown") for row in top_rows}
        universe = snapshot.get("universe_tickers", [])
        symbols = {row["ticker"] for row in top_rows} | {"SPY"}
        symbols |= {SECTOR_ETFS[sector] for sector in sectors.values() if sector in SECTOR_ETFS}
        if universe:
            symbols |= set(universe)
        closes = download_closes(sorted(symbols), selection_date) if needs_prices else {}
        spy_dates: list[date] = []
        if "SPY" in closes:
            spy_dates = [timestamp.date() for timestamp in pd.to_datetime(closes["SPY"].index) if timestamp.date() >= selection_date]
        candidates = []
        for row in top_rows:
            ticker = row["ticker"]
            horizons = {}
            for label, sessions in HORIZONS.items():
                if len(spy_dates) <= sessions:
                    horizons[label] = {"status": "pending", "trading_sessions_required": sessions}
                    continue
                target_date = spy_dates[sessions]
                stock_return = total_return(closes.get(ticker), selection_date, target_date)
                spy_return = total_return(closes.get("SPY"), selection_date, target_date)
                sector_etf = SECTOR_ETFS.get(sectors[ticker])
                sector_return = total_return(closes.get(sector_etf), selection_date, target_date) if sector_etf else None
                universe_returns = [total_return(closes.get(symbol), selection_date, target_date) for symbol in universe]
                available_universe = [value for value in universe_returns if value is not None]
                coverage = None if not universe else len(available_universe) / len(universe) * 100
                universe_return = (
                    round(sum(available_universe) / len(available_universe), 2)
                    if coverage is not None and coverage >= 80 else None
                )
                if stock_return is None or spy_return is None:
                    horizons[label] = {
                        "status": "unavailable", "trading_sessions_required": sessions,
                        "target_date": target_date.isoformat(), "reason": "Candidate or SPY adjusted close was unavailable",
                    }
                    continue
                horizons[label] = {
                    "status": "measured", "trading_sessions_required": sessions,
                    "target_date": target_date.isoformat(), "stock_return_pct": stock_return,
                    "spy_return_pct": spy_return, "excess_vs_spy_pp": round(stock_return - spy_return, 2),
                    "sector_benchmark": sector_etf, "sector_return_pct": sector_return,
                    "excess_vs_sector_pp": None if sector_return is None else round(stock_return - sector_return, 2),
                    "universe_return_pct": universe_return,
                    "excess_vs_universe_pp": None if universe_return is None else round(stock_return - universe_return, 2),
                    "universe_coverage_pct": None if coverage is None else round(coverage, 1),
                }
            candidates.append({
                "ticker": ticker, "sector": sectors[ticker], "selection_price": row["price"],
                "selection_score": row["research"]["quant_score_90"], "horizons": horizons,
            })
        results.append({
            "selection_date": snapshot["selection_date"], "score_version": snapshot["score_version"],
            "snapshot_schema_version": snapshot["snapshot_schema_version"], "candidates": candidates,
        })
    return {
        "performance_schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "price_source": "Yahoo Finance adjusted daily closes accessed through yfinance",
        "horizons": HORIZONS,
        "results": results,
    }


def main() -> int:
    try:
        payload = build_performance()
        atomic_write(payload)
        print(f"Updated performance states for {len(payload['results'])} snapshots")
        return 0
    except Exception as error:
        print(f"PERFORMANCE ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
