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
REQUIRED_ROW_FIELDS = {"ticker", "sector", "industry", "cik", "price", "drawdown_pct", "ma50", "average_dollar_volume_20d", "price_score", "price_date"}
COMPONENT_LIMITS = {
    "fundamentals_30": 30,
    "valuation_25": 25,
    "selloff_20": 20,
    "financial_strength_15": 15,
}
TREND_NUMERIC_FIELDS = {
    "revenue_yoy_pct", "operating_margin_pct", "operating_margin_change_pp",
    "net_income_latest", "net_income_year_ago", "free_cash_flow_latest",
    "free_cash_flow_yoy_pct", "debt_yoy_pct", "shares_yoy_pct",
}
ALLOWED_VALUE_TRAP_FLAGS = {
    "Revenue declined more than 5% year over year",
    "Operating margin contracted more than 3 percentage points",
    "Latest quarter reported a net loss",
    "Latest quarter reported negative free cash flow",
    "Total debt increased more than 20% year over year",
    "Share count increased more than 5% year over year",
}


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
    if not isinstance(data, dict) or data.get("schema_version") != 8:
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
    rows_by_ticker: dict[str, dict[str, object]] = {}
    for index, row in enumerate(stocks):
        if not isinstance(row, dict) or not REQUIRED_ROW_FIELDS.issubset(row):
            fail(f"row {index} is missing required fields")
        ticker = row["ticker"]
        if not isinstance(ticker, str) or not TICKER.fullmatch(ticker):
            fail(f"row {index} has invalid ticker")
        if ticker in seen or ticker in unique_failed:
            fail(f"ticker {ticker} is duplicated or also marked failed")
        seen.add(ticker)
        rows_by_ticker[ticker] = row
        for field in ("sector", "industry"):
            if not isinstance(row[field], str) or not row[field].strip() or len(row[field]) > 100:
                fail(f"{ticker}.{field} must be a non-empty classification")
        cik = row["cik"]
        if cik is not None and (isinstance(cik, bool) or not isinstance(cik, int) or not 1 <= cik <= 9_999_999_999):
            fail(f"{ticker}.cik must be a positive SEC identifier or null")
        for field in ("price", "drawdown_pct", "ma50", "price_score"):
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                fail(f"{ticker}.{field} must be a finite number")
        if row["price"] <= 0 or row["ma50"] <= 0:
            fail(f"{ticker} has a non-positive price")
        dollar_volume = row["average_dollar_volume_20d"]
        if dollar_volume is not None and (
            isinstance(dollar_volume, bool)
            or not isinstance(dollar_volume, (int, float))
            or not math.isfinite(dollar_volume)
            or dollar_volume <= 0
        ):
            fail(f"{ticker}.average_dollar_volume_20d must be positive or null")
        if row["drawdown_pct"] > 0.1 or not 0 <= row["price_score"] <= 100:
            fail(f"{ticker} has an out-of-range score or drawdown")
        signals = row.get("price_signals")
        if not isinstance(signals, dict) or signals.get("status") not in {"stabilizing", "improving", "mixed", "still_falling"}:
            fail(f"{ticker}.price_signals is missing or invalid")
        for field in (
            "return_5d_pct", "return_20d_pct", "versus_ma20_pct", "above_20d_low_pct",
            "return_63d_pct", "sector_return_63d_pct", "sector_relative_63d_pp",
        ):
            value = signals.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            ):
                fail(f"{ticker}.price_signals.{field} must be finite or null")
        sample_size = signals.get("sector_sample_size")
        if not isinstance(sample_size, int) or isinstance(sample_size, bool) or sample_size < 0:
            fail(f"{ticker}.price_signals.sector_sample_size is invalid")
        if sample_size and (
            signals.get("sector_return_63d_pct") is None or signals.get("sector_relative_63d_pp") is None
        ):
            fail(f"{ticker}.price_signals sector comparison is incomplete")
        relative = signals.get("sector_relative_63d_pp")
        if relative is not None:
            if signals.get("return_63d_pct") is None or signals.get("sector_return_63d_pct") is None:
                fail(f"{ticker}.price_signals sector-relative inputs are missing")
            if abs(signals["return_63d_pct"] - signals["sector_return_63d_pct"] - relative) > 0.02:
                fail(f"{ticker}.price_signals sector-relative calculation is inconsistent")
        try:
            price_date = date.fromisoformat(row["price_date"])
        except (TypeError, ValueError):
            fail(f"{ticker}.price_date is invalid")
        if price_date > now.date():
            fail(f"{ticker}.price_date is in the future")

        research = row.get("research")
        if research is not None:
            if not isinstance(research, dict):
                fail(f"{ticker}.research must be an object")
            components = research.get("component_scores")
            metrics = research.get("metrics")
            if not isinstance(components, dict) or not isinstance(metrics, dict):
                fail(f"{ticker}.research is missing score details")
            component_total = 0.0
            for name, maximum in COMPONENT_LIMITS.items():
                value = components.get(name)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum:
                    fail(f"{ticker}.{name} is invalid")
                component_total += value
            if components.get("catalysts_10") is not None:
                fail(f"{ticker} must not receive unverified catalyst points")
            score = research.get("quant_score_90")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 90:
                fail(f"{ticker}.quant_score_90 is invalid")
            if abs(score - component_total) > 0.21:
                fail(f"{ticker}.quant_score_90 does not match its components")
            available = research.get("data_fields_available")
            required = research.get("data_fields_required")
            if not isinstance(available, int) or not isinstance(required, int) or not 0 <= available <= 10 or not 1 <= required <= 10:
                fail(f"{ticker} has invalid data coverage")
            if research.get("eligible") is not (available >= required):
                fail(f"{ticker}.eligible conflicts with data coverage")
            market_cap = metrics.get("market_cap")
            if market_cap is not None and (
                isinstance(market_cap, bool)
                or not isinstance(market_cap, (int, float))
                or not math.isfinite(market_cap)
                or market_cap <= 0
            ):
                fail(f"{ticker}.market_cap must be positive or null")
            website = research.get("company_website")
            if website is not None and (
                not isinstance(website, str)
                or not website.startswith(("https://", "http://"))
                or len(website) > 500
            ):
                fail(f"{ticker}.company_website is invalid")
            earnings_date = research.get("next_earnings_date")
            if earnings_date is not None:
                try:
                    parsed_earnings = date.fromisoformat(earnings_date)
                except (TypeError, ValueError):
                    fail(f"{ticker}.next_earnings_date is invalid")
                if parsed_earnings < now.date() or parsed_earnings > now.date() + timedelta(days=550):
                    fail(f"{ticker}.next_earnings_date is outside the accepted range")
            trends = research.get("quarterly_trends")
            if not isinstance(trends, dict) or trends.get("status") not in {"available", "insufficient_history", "unavailable"}:
                fail(f"{ticker}.quarterly_trends is missing or invalid")
            trend_metrics = trends.get("metrics")
            flags = trends.get("value_trap_flags")
            fields_available = trends.get("fields_available")
            if not isinstance(trend_metrics, dict) or not isinstance(flags, list) or not isinstance(fields_available, int):
                fail(f"{ticker}.quarterly_trends has invalid fields")
            if not set(flags).issubset(ALLOWED_VALUE_TRAP_FLAGS) or len(flags) != len(set(flags)):
                fail(f"{ticker}.value_trap_flags contains an invalid or duplicate flag")
            for field in TREND_NUMERIC_FIELDS:
                value = trend_metrics.get(field)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
                ):
                    fail(f"{ticker}.quarterly_trends.{field} must be finite or null")
            actual_available = sum(trend_metrics.get(field) is not None for field in TREND_NUMERIC_FIELDS)
            if fields_available != actual_available:
                fail(f"{ticker}.quarterly_trends fields_available is inconsistent")
            for field in ("latest_period", "year_ago_period"):
                value = trend_metrics.get(field)
                if value is not None:
                    try:
                        trend_date = date.fromisoformat(value)
                    except (TypeError, ValueError):
                        fail(f"{ticker}.quarterly_trends.{field} is invalid")
                    if trend_date > now.date():
                        fail(f"{ticker}.quarterly_trends.{field} is in the future")
            if trends.get("status") == "available" and (
                trend_metrics.get("latest_period") is None or trend_metrics.get("year_ago_period") is None
            ):
                fail(f"{ticker}.quarterly_trends available status lacks comparison periods")
            valuation = research.get("sector_valuation")
            if not isinstance(valuation, dict) or valuation.get("status") not in {
                "cheaper", "near_median", "more_expensive", "unavailable"
            }:
                fail(f"{ticker}.sector_valuation is missing or invalid")
            comparisons = valuation.get("comparisons")
            metrics_available = valuation.get("metrics_available")
            if not isinstance(comparisons, dict) or not isinstance(metrics_available, int):
                fail(f"{ticker}.sector_valuation fields are invalid")
            if set(comparisons) - {"trailing_pe", "ev_to_ebitda", "fcf_yield_pct"}:
                fail(f"{ticker}.sector_valuation has an unknown metric")
            if metrics_available != len(comparisons):
                fail(f"{ticker}.sector_valuation metric count is inconsistent")
            percentiles = []
            for field, comparison in comparisons.items():
                if not isinstance(comparison, dict):
                    fail(f"{ticker}.sector_valuation.{field} is invalid")
                for number_field in ("value", "sector_median", "cheapness_percentile"):
                    number = comparison.get(number_field)
                    if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
                        fail(f"{ticker}.sector_valuation.{field}.{number_field} is invalid")
                if not 0 <= comparison["cheapness_percentile"] <= 100:
                    fail(f"{ticker}.sector_valuation.{field} percentile is out of range")
                if not isinstance(comparison.get("peer_count"), int) or comparison["peer_count"] < 3:
                    fail(f"{ticker}.sector_valuation.{field} has too few peers")
                percentiles.append(comparison["cheapness_percentile"])
            overall = valuation.get("cheapness_percentile")
            if valuation["status"] == "unavailable":
                if overall is not None or metrics_available >= 2:
                    fail(f"{ticker}.sector_valuation unavailable status is inconsistent")
            elif (
                metrics_available < 2
                or isinstance(overall, bool)
                or not isinstance(overall, (int, float))
                or not math.isfinite(overall)
                or abs(overall - sum(percentiles) / len(percentiles)) > 0.11
            ):
                fail(f"{ticker}.sector_valuation overall percentile is inconsistent")
            if valuation.get("history_status") != "unavailable" or not isinstance(valuation.get("history_reason"), str):
                fail(f"{ticker}.sector_valuation history status is invalid")

    method = data.get("research_method")
    top_five = data.get("top_five")
    if not isinstance(method, dict) or not isinstance(top_five, list):
        fail("research_method and top_five are required")
    if method.get("maximum_automated_score") != 90 or method.get("catalyst_points_reserved") != 10:
        fail("research scoring limits are invalid")
    if len(top_five) > 5:
        fail("top_five contains more than five rows")
    top_tickers: list[str] = []
    previous_score = float("inf")
    for item in top_five:
        if not isinstance(item, dict) or item.get("ticker") not in rows_by_ticker:
            fail("top_five contains an unknown row")
        ticker = str(item["ticker"])
        if item != rows_by_ticker[ticker]:
            fail(f"top_five row {ticker} does not match stocks")
        research = item.get("research")
        if not isinstance(research, dict) or research.get("eligible") is not True:
            fail(f"top_five row {ticker} is not eligible")
        confirmation = research.get("sec_xbrl_confirmation")
        if not isinstance(confirmation, dict) or confirmation.get("status") not in {"confirmed", "partial", "mismatch", "unavailable"}:
            fail(f"top_five row {ticker} has invalid SEC confirmation")
        sec_metrics = confirmation.get("metrics")
        if not isinstance(sec_metrics, dict):
            fail(f"top_five row {ticker} has invalid SEC metrics")
        for field in ("revenue_yoy_pct", "operating_margin_change_pp"):
            value = sec_metrics.get(field)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            ):
                fail(f"top_five row {ticker} has invalid SEC {field}")
        comparisons = confirmation.get("comparisons", {})
        if not isinstance(comparisons, dict) or any(
            key not in {"revenue_yoy", "operating_margin_change"} or not isinstance(value, bool)
            for key, value in comparisons.items()
        ):
            fail(f"top_five row {ticker} has invalid SEC comparisons")
        if confirmation.get("status") == "confirmed" and (len(comparisons) != 2 or not all(comparisons.values())):
            fail(f"top_five row {ticker} claims unsupported SEC confirmation")
        if confirmation.get("status") == "mismatch" and (not comparisons or all(comparisons.values())):
            fail(f"top_five row {ticker} has unsupported SEC mismatch")
        if confirmation.get("status") == "partial" and (len(comparisons) != 1 or not all(comparisons.values())):
            fail(f"top_five row {ticker} has unsupported partial SEC confirmation")
        if confirmation.get("status") == "unavailable" and comparisons:
            fail(f"top_five row {ticker} has comparisons despite unavailable SEC status")
        source = confirmation.get("source")
        if source is not None and (
            not isinstance(source, str)
            or not source.startswith("https://data.sec.gov/api/xbrl/companyfacts/CIK")
            or not source.endswith(".json")
            or len(source) > 100
        ):
            fail(f"top_five row {ticker} has invalid SEC source")
        score = float(research["quant_score_90"])
        if score > previous_score:
            fail("top_five is not sorted by score")
        previous_score = score
        top_tickers.append(ticker)
    if len(top_tickers) != len(set(top_tickers)):
        fail("top_five contains duplicates")
    if method.get("eligible_count", 0) >= 5 and len(top_five) != 5:
        fail("five eligible candidates exist but top_five is incomplete")

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
