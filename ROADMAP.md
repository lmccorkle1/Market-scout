# Market Scout Roadmap

Market Scout is a free stock research dashboard for 3–24 month opportunities in fundamentally strong companies experiencing potential temporary selloffs. This roadmap records what is working, what comes next, and the safeguards that should remain in place as the project grows.

## Guiding principles

- Never present sample, missing, or fabricated values as live market data.
- Always show when the data was generated and the closing date for each symbol.
- Preserve the last verified scan when a new scan fails or is suspiciously incomplete.
- Keep the core scanner usable without paid data services or API keys.
- Treat scanner scores as research signals, not investment recommendations.

## Phase 1 — Working MVP (complete)

- [x] Publish the Market Scout dashboard with GitHub Pages.
- [x] Add the daily opportunity scanner page.
- [x] Scan the S&P 500 plus a disclosed group of selected growth symbols.
- [x] Calculate adjusted close, distance below the one-year high, 50-day average, and a transparent price-only score.
- [x] Publish verified results to `data/scanner.json`.
- [x] Run automatically after the U.S. market close on weekdays.
- [x] Allow manual runs through GitHub Actions.
- [x] Prevent failed or undersized downloads from replacing the last verified scan.

## Phase 2 — Reliability and clarity (substantially complete)

- [x] Add an obvious stale-data warning when the latest successful scan is older than expected.
- [x] Show partial-scan status and unavailable symbols on the scanner page.
- [x] Add automated checks for the JSON schema, duplicate tickers, invalid numbers, and future-dated prices.
- [x] Add a short README with setup, maintenance, and troubleshooting instructions.
- [ ] Update GitHub Actions dependencies when deprecation warnings appear.
- [x] Add a visible link to the workflow runs for troubleshooting.

## Phase 3 — Better research context

- [x] Add valuation and quality fields from a clearly attributed free data source.
- [x] Add revenue growth, earnings growth, debt, free cash flow, and profitability checks.
- [x] Add sector and industry filters.
- [x] Add liquidity and minimum-market-cap filters for the enriched candidate pool.
- [x] Separate price opportunity, business quality, valuation, and financial strength into distinct scores.
- [x] Explain every score component and its limitations.
- [x] Rank five research candidates only when enough verified fields are available.
- [x] Reserve catalyst scoring for manual research rather than fabricating conclusions.
- [x] Add direct SEC company, 10-K, and 10-Q research links when a CIK is available.
- [x] Show sourced earnings dates and company websites when available.

## Phase 4 — Personal workflow

- [x] Add a browser-saved watchlist without requiring an account.
- [x] Add notes and a research checklist for each watched ticker.
- [x] Add browser-saved configurable screen thresholds and a quality-selloff preset.
- [ ] Add CSV export for the current filtered results.
- [ ] Consider optional alerts only after data reliability is well tested.

## Phase 5 — User experience

- [x] Improve the scanner's responsive mobile layout.
- [x] Add loading, empty, stale, partial, and error states with clear language.
- [x] Add sortable columns and richer filters without slowing the page.
- [x] Add a methodology page describing sources, update timing, scoring thresholds, and known limitations.

## Phase 6 — Quality-at-a-discount research system (current focus)

- [x] Add minimum market-cap and dollar-volume investability controls.
- [x] Add same-quarter year-over-year revenue, operating-margin, free-cash-flow, debt, and share-count trends.
- [x] Display transparent value-trap warnings without silently changing the ranking.
- [x] Add a fail-safe SEC Company Facts cross-check for Top Five revenue growth and operating-margin trends.
- [ ] Expand point-in-time SEC XBRL confirmation across the full enriched candidate pool and additional quarterly fields.
- [x] Add price stabilization and sector-relative-strength signals without silently changing rankings.
- [x] Add sector-relative valuation comparisons with minimum peer coverage.
- [ ] Add company-history valuation comparisons from trustworthy point-in-time fundamentals.
- [x] Add filing freshness, dilution, leverage, cash-flow-quality, coverage, and SEC-verification risk gates.
- [ ] Add verified catalyst evidence from filings and company disclosures.

## Phase 7 — Measurement and learning

- [x] Save an immutable daily Top Five snapshot with its inputs, prices, warnings, and score version.
- [ ] Measure 1-, 3-, 6-, 12-, and 24-month total returns.
- [ ] Compare each candidate with SPY, its sector benchmark, and the screened universe.
- [ ] Report hit rate, excess return, maximum drawdown, and losing outcomes.
- [ ] Build point-in-time, survivorship-aware walk-forward tests before tuning weights.
- [ ] Version every scoring-rule change so historical results remain interpretable.

## Phase 8 — Portfolio and risk controls

- [ ] Add sector and position concentration limits.
- [ ] Add volatility-aware position-sizing guidance for research scenarios.
- [ ] Track thesis invalidation conditions separately from price movement.
- [ ] Keep ETFs and long-term allocations separate from individual-company opportunity rankings.

## Current operating schedule

The workflow is scheduled for **22:15 UTC, Monday through Friday**, after the regular U.S. market close in both daylight and standard time. GitHub Actions schedules can start later than the exact cron time during busy periods.

## Definition of done for new data features

A data feature is ready only when its source is documented, missing values are explicit, stale values are detectable, failure cannot masquerade as success, and the user interface does not describe the result as financial advice.
