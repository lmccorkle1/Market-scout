#!/usr/bin/env python3
"""Validate Market Scout JSON before it can be published."""

from __future__ import annotations

import json
import math
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MIN_RESULTS = 350
TICKER = re.compile(r"^[A-Z0-9-]{1,12}$")
REQUIRED_ROW_FIELDS = {"ticker", "sector", "industry", "price", "drawdown_pct", "ma50", "price_score", "price_date"}


def fail(message: str) -> None:
    raise ValueError(message)


def parse_utc(value: object) -> datetime:
    if not isinstance(value, str):
        fail("generated_at must be an ISO timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        fail("generated_at must include a timezone")
    return parsed.astimezone(timezone.utc)


def validate(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        fail("unsupported or missing schema_version")

    stocks = data.get("stocks")
    failed_symbols = data.get("failed_symbols")
    if not isinstance(stocks, list) or not isinstance(failed_symbols, list):
        fail("stocks and failed_symbols must be arrays")
    if len(stocks) < MIN_RESULTS:
        fail(f"only {len(stocks)} results; minimum is {MIN_RESULTS}")
    if data.get("screened_count") != len(stocks):
        fail("screened_count does not match stocks length")
    unique_failed = set(failed_symbols)
    if len(unique_failed) != len(failed_symbols) or data.get("failed_count") != len(unique_failed):
        fail("failed symbol counts are inconsistent")
    if data.get("universe_count") != len(stocks) + len(unique_failed):
        fail("universe_count does not equal screened plus failed symbols")
    expected_status = "partial" if unique_failed else "ok"
    if data.get("status") != expected_status:
        fail(f"status must be {expected_status!r}")

    now = datetime.now(timezone.utc)
    generated = parse_utc(data.get("generated_at"))
    if generated > now + timedelta(minutes=5):
        fail("generated_at is in the future")
    if generated < now - timedelta(hours=24):
        fail("generated scan is already more than 24 hours old")

    seen: set[str] = set()
    for index, row in enumerate(stocks):
        if not isinstance(row, dict) or not REQUIRED_ROW_FIELDS.issubset(row):
            fail(f"row {index} is missing required fields")
        ticker = row["ticker"]
        if not isinstance(ticker, str) or not TICKER.fullmatch(ticker):
            fail(f"row {index} has invalid ticker")
        if ticker in seen or ticker in unique_failed:
            fail(f"ticker {ticker} is duplicated or also marked failed")
        seen.add(ticker)
        for field in ("sector", "industry"):
            if not isinstance(row[field], str) or not row[field].strip() or len(row[field]) > 100:
                fail(f"{ticker}.{field} must be a non-empty classification")
        for field in ("price", "drawdown_pct", "ma50", "price_score"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                fail(f"{ticker}.{field} must be a finite number")
        if row["price"] <= 0 or row["ma50"] <= 0:
            fail(f"{ticker} has a non-positive price")
        if row["drawdown_pct"] > 0.1 or not 0 <= row["price_score"] <= 100:
            fail(f"{ticker} has an out-of-range score or drawdown")
        try:
            price_date = date.fromisoformat(row["price_date"])
        except (TypeError, ValueError):
            fail(f"{ticker}.price_date is invalid")
        if price_date > now.date():
            fail(f"{ticker}.price_date is in the future")

    return data


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/scanner.json")
    try:
        data = validate(path)
        print(f"Validated {data['screened_count']} stocks; status={data['status']}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"VALIDATION ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
