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
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd
import yfinance as yf

OUTPUT = Path(__file__).resolve().parents[1] / "data" / "scanner.json"
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
EXTRA_SYMBOLS = {
    "ARM", "COIN", "CRWD", "DDOG", "DUOL", "HIMS", "HOOD", "IBIT",
    "MELI", "NBIS", "NET", "PLTR", "RDDT", "SHOP", "SNOW", "SOFI",
    "TEM", "TSM", "UBER",
}
MIN_RESULTS = 350
CHUNK_SIZE = 75


def get_universe() -> tuple[list[str], str]:
    """Return actual S&P 500 constituents plus a small disclosed growth list."""
    request = Request(
        WIKIPEDIA_URL,
        headers={"User-Agent": "MarketScout/1.0 (public GitHub Actions market research tool)"},
    )
    with urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8")
    tables = pd.read_html(StringIO(html))
    symbols = {
        str(symbol).strip().replace(".", "-")
        for symbol in tables[0]["Symbol"].dropna()
    }
    if len(symbols) < 450:
        raise RuntimeError(f"Constituent list unexpectedly contained only {len(symbols)} symbols")
    return sorted(symbols | EXTRA_SYMBOLS), "Wikipedia S&P 500 list + disclosed selected growth/ETF symbols"


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


def scan() -> dict[str, object]:
    symbols, universe_source = get_universe()
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
            rows.append({
                "ticker": symbol,
                "price": round(price, 2),
                "drawdown_pct": round(drawdown, 1),
                "ma50": round(ma50, 2),
                "price_score": round(score, 1),
                "price_date": price_date,
            })

    if len(rows) < MIN_RESULTS:
        raise RuntimeError(
            f"Only {len(rows)} of {len(symbols)} symbols had verified data; "
            f"minimum is {MIN_RESULTS}. Preserving the previous published scan."
        )

    rows.sort(key=lambda row: (-float(row["price_score"]), str(row["ticker"])))
    return {
        "schema_version": 1,
        "status": "ok" if not failures else "partial",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "universe_source": universe_source,
        "universe_count": len(symbols),
        "screened_count": len(rows),
        "failed_count": len(set(failures)),
        "failed_symbols": sorted(set(failures)),
        "score_explanation": "Price-only score based on distance below the 1-year adjusted high and 50-day average; it is not an investment rating.",
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
