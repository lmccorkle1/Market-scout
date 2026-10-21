# Market Scout Roadmap

Market Scout is a free, price-based stock research dashboard. This roadmap records what is working, what comes next, and the safeguards that should remain in place as the project grows.

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

## Phase 2 — Reliability and clarity (next)

- [ ] Add an obvious stale-data warning when the latest successful scan is older than expected.
- [ ] Show partial-scan status and unavailable symbols on the scanner page.
- [ ] Add automated checks for the JSON schema, duplicate tickers, invalid numbers, and future-dated prices.
- [ ] Add a short README with setup, maintenance, and troubleshooting instructions.
- [ ] Update GitHub Actions dependencies when deprecation warnings appear.
- [ ] Add a visible link to the latest workflow run for troubleshooting.

## Phase 3 — Better research context

- [ ] Add valuation and quality fields from a reliable, clearly attributed data source.
- [ ] Add revenue growth, earnings growth, debt, free cash flow, and profitability checks.
- [ ] Add sector and industry filters.
- [ ] Add liquidity and minimum-market-cap filters.
- [ ] Separate price opportunity, business quality, and valuation into distinct scores.
- [ ] Explain every score component and its limitations.

## Phase 4 — Personal workflow

- [ ] Add a browser-saved watchlist without requiring an account.
- [ ] Add notes and a research checklist for each watched ticker.
- [ ] Add configurable screen thresholds.
- [ ] Add CSV export for the current filtered results.
- [ ] Consider optional alerts only after data reliability is well tested.

## Phase 5 — User experience

- [ ] Improve mobile layout and accessibility.
- [ ] Add loading, empty, stale, partial, and error states with clear language.
- [ ] Add sortable columns and richer filters without slowing the page.
- [ ] Add a methodology page describing sources, update timing, and known limitations.

## Current operating schedule

The workflow is scheduled for **22:15 UTC, Monday through Friday**, after the regular U.S. market close in both daylight and standard time. GitHub Actions schedules can start later than the exact cron time during busy periods.

## Definition of done for new data features

A data feature is ready only when its source is documented, missing values are explicit, stale values are detectable, failure cannot masquerade as success, and the user interface does not describe the result as financial advice.
