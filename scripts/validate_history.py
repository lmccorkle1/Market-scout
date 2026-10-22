#!/usr/bin/env python3
"""Validate immutable Market Scout Top Five history snapshots and their index."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

TICKER = re.compile(r"^[A-Z0-9-]{1,12}$")


def fail(message: str) -> None:
    raise ValueError(message)


def validate_history(history_dir: Path) -> int:
    index_path = history_dir / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if not isinstance(index, dict) or index.get("history_schema_version") != 1:
        fail("history index schema is missing or unsupported")
    entries = index.get("snapshots")
    if not isinstance(entries, list) or not entries:
        fail("history index must contain at least one snapshot")
    dates: list[str] = []
    indexed_paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            fail("history index contains a non-object entry")
        selection_date = entry.get("date")
        try:
            parsed_date = date.fromisoformat(selection_date)
        except (TypeError, ValueError):
            fail("history index contains an invalid date")
        if parsed_date > datetime.now(timezone.utc).date():
            fail(f"history snapshot {selection_date} is future-dated")
        expected_path = f"{selection_date}.json"
        if entry.get("path") != expected_path:
            fail(f"history snapshot {selection_date} has an unsafe or inconsistent path")
        snapshot_path = history_dir / expected_path
        digest = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
        if entry.get("sha256") != digest:
            fail(f"history snapshot {selection_date} hash does not match the immutable index")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        if not isinstance(snapshot, dict) or snapshot.get("snapshot_schema_version") != 1:
            fail(f"history snapshot {selection_date} has an unsupported schema")
        if snapshot.get("score_version") != "quant-90-v1" or snapshot.get("selection_date") != selection_date:
            fail(f"history snapshot {selection_date} has inconsistent version or date")
        generated_at = snapshot.get("generated_at")
        try:
            generated = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            fail(f"history snapshot {selection_date} has an invalid generation timestamp")
        if generated.tzinfo is None or generated.astimezone(timezone.utc).date() < parsed_date:
            fail(f"history snapshot {selection_date} has an inconsistent generation timestamp")
        rows = snapshot.get("top_five")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
            fail(f"history snapshot {selection_date} has an invalid Top Five")
        tickers: list[str] = []
        previous_score = float("inf")
        for rank, row in enumerate(rows, start=1):
            if not isinstance(row, dict) or row.get("price_date") != selection_date:
                fail(f"history snapshot {selection_date} row {rank} has an invalid price date")
            ticker = row.get("ticker")
            if not isinstance(ticker, str) or not TICKER.fullmatch(ticker):
                fail(f"history snapshot {selection_date} row {rank} has an invalid ticker")
            price = row.get("price")
            research = row.get("research")
            if (
                isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0
                or not isinstance(research, dict)
            ):
                fail(f"history snapshot {selection_date} row {ticker} has invalid price or research data")
            score = research.get("quant_score_90")
            components = research.get("component_scores")
            if (
                isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score)
                or not isinstance(components, dict) or components.get("catalysts_10") is not None
            ):
                fail(f"history snapshot {selection_date} row {ticker} has invalid score data")
            component_total = sum(components.get(field, 0) for field in (
                "fundamentals_30", "valuation_25", "selloff_20", "financial_strength_15"
            ))
            if abs(score - component_total) > 0.21 or score > previous_score:
                fail(f"history snapshot {selection_date} row {ticker} has inconsistent ranking")
            previous_score = score
            tickers.append(ticker)
        if tickers != entry.get("top_tickers") or len(tickers) != len(set(tickers)):
            fail(f"history snapshot {selection_date} ticker index is inconsistent")
        dates.append(selection_date)
        indexed_paths.add(expected_path)
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        fail("history index dates must be unique and sorted")
    disk_paths = {path.name for path in history_dir.glob("*.json") if path.name != "index.json"}
    if disk_paths != indexed_paths:
        fail("history directory contains an unindexed or missing snapshot")
    return len(entries)


def main() -> int:
    history_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "data/history")
    try:
        count = validate_history(history_dir)
        print(f"Validated {count} immutable history snapshot{'s' if count != 1 else ''}")
        return 0
    except (OSError, ValueError, json.JSONDecodeError, TypeError) as error:
        print(f"HISTORY VALIDATION ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
