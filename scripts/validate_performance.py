#!/usr/bin/env python3
"""Validate Market Scout forward-return measurement states."""

from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HORIZONS = {"1m": 21, "3m": 63, "6m": 126, "12m": 252, "24m": 504}
RETURN_FIELDS = {
    "stock_return_pct", "spy_return_pct", "excess_vs_spy_pp", "sector_return_pct",
    "excess_vs_sector_pp", "universe_return_pct", "excess_vs_universe_pp", "universe_coverage_pct",
}


def fail(message: str) -> None:
    raise ValueError(message)


def validate(path: Path) -> dict[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("performance_schema_version") != 1 or data.get("horizons") != HORIZONS:
        fail("performance schema or horizons are invalid")
    generated = datetime.fromisoformat(data["generated_at"].replace("Z", "+00:00"))
    if generated.tzinfo is None or generated > datetime.now(timezone.utc):
        fail("performance generation timestamp is invalid")
    results = data.get("results")
    if not isinstance(results, list):
        fail("performance results must be an array")
    seen_dates: set[str] = set()
    for result in results:
        selection_date = result.get("selection_date")
        try:
            selected = date.fromisoformat(selection_date)
        except (TypeError, ValueError):
            fail("performance result has an invalid selection date")
        if selection_date in seen_dates:
            fail(f"performance result duplicates {selection_date}")
        seen_dates.add(selection_date)
        candidates = result.get("candidates")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 5:
            fail(f"performance result {selection_date} has invalid candidates")
        tickers: set[str] = set()
        for candidate in candidates:
            ticker = candidate.get("ticker")
            if not isinstance(ticker, str) or ticker in tickers:
                fail(f"performance result {selection_date} has duplicate or invalid ticker")
            tickers.add(ticker)
            if isinstance(candidate.get("selection_price"), bool) or not isinstance(candidate.get("selection_price"), (int, float)) or candidate["selection_price"] <= 0:
                fail(f"performance result {selection_date}/{ticker} has invalid selection price")
            horizons = candidate.get("horizons")
            if not isinstance(horizons, dict) or set(horizons) != set(HORIZONS):
                fail(f"performance result {selection_date}/{ticker} has invalid horizons")
            for label, expected_sessions in HORIZONS.items():
                outcome = horizons[label]
                if not isinstance(outcome, dict) or outcome.get("status") not in {"pending", "measured", "unavailable"}:
                    fail(f"performance result {selection_date}/{ticker}/{label} has invalid status")
                if outcome.get("trading_sessions_required") != expected_sessions:
                    fail(f"performance result {selection_date}/{ticker}/{label} has invalid session count")
                if outcome["status"] == "pending":
                    if RETURN_FIELDS & set(outcome):
                        fail(f"pending result {selection_date}/{ticker}/{label} contains fabricated returns")
                    continue
                try:
                    target = date.fromisoformat(outcome["target_date"])
                except (KeyError, TypeError, ValueError):
                    fail(f"performance result {selection_date}/{ticker}/{label} has invalid target date")
                if target <= selected or target > datetime.now(timezone.utc).date():
                    fail(f"performance result {selection_date}/{ticker}/{label} target date is invalid")
                if outcome["status"] == "unavailable":
                    if not isinstance(outcome.get("reason"), str) or RETURN_FIELDS & set(outcome):
                        fail(f"unavailable result {selection_date}/{ticker}/{label} is invalid")
                    continue
                for field in RETURN_FIELDS:
                    value = outcome.get(field)
                    if value is not None and (
                        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                    ):
                        fail(f"measured result {selection_date}/{ticker}/{label}/{field} is invalid")
                if outcome.get("stock_return_pct") is None or outcome.get("spy_return_pct") is None:
                    fail(f"measured result {selection_date}/{ticker}/{label} lacks required returns")
                if abs(outcome["stock_return_pct"] - outcome["spy_return_pct"] - outcome["excess_vs_spy_pp"]) > 0.02:
                    fail(f"measured result {selection_date}/{ticker}/{label} has inconsistent SPY excess return")
                sector_return = outcome.get("sector_return_pct")
                sector_excess = outcome.get("excess_vs_sector_pp")
                if (sector_return is None) != (sector_excess is None) or (
                    sector_return is not None and abs(outcome["stock_return_pct"] - sector_return - sector_excess) > 0.02
                ):
                    fail(f"measured result {selection_date}/{ticker}/{label} has inconsistent sector excess return")
                universe_return = outcome.get("universe_return_pct")
                universe_excess = outcome.get("excess_vs_universe_pp")
                coverage = outcome.get("universe_coverage_pct")
                if coverage is not None and not 0 <= coverage <= 100:
                    fail(f"measured result {selection_date}/{ticker}/{label} has invalid universe coverage")
                if (universe_return is None) != (universe_excess is None) or (
                    universe_return is not None and (
                        coverage is None or coverage < 80
                        or abs(outcome["stock_return_pct"] - universe_return - universe_excess) > 0.02
                    )
                ):
                    fail(f"measured result {selection_date}/{ticker}/{label} has inconsistent universe excess return")
    return data


def main() -> int:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "data/performance.json")
    try:
        data = validate(path)
        print(f"Validated performance states for {len(data['results'])} snapshots")
        return 0
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        print(f"PERFORMANCE VALIDATION ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
