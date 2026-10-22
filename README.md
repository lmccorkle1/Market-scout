# Market Scout

Market Scout is a free, browser-based stock research dashboard with an automated daily opportunity scanner. It screens price behavior across the S&P 500 and a disclosed set of selected growth stocks.

**Live site:** [Market Scout dashboard](https://lmccorkle1.github.io/Market-scout/)  
**Scanner:** [Daily opportunity scanner](https://lmccorkle1.github.io/Market-scout/scanner.html)  
**Plans:** [Project roadmap](ROADMAP.md)

## What the scanner shows

For every symbol with sufficient verified data, the scanner publishes:

- Latest adjusted closing price
- Percentage below its one-year adjusted high
- 50-trading-day average
- Latest closing date
- A transparent price-only opportunity score

The score increases when a stock is farther below its one-year high or below its 50-day average. It is a screening heuristic—not a prediction, quality rating, or recommendation. A high score can reflect genuine business deterioration.

## Data and schedule

- S&P 500 constituents are obtained from Wikipedia at run time.
- Delayed historical prices are retrieved through `yfinance` from Yahoo Finance.
- Selected growth symbols are listed explicitly in `scripts/scan.py`.
- GitHub Actions runs the scan at **22:15 UTC, Monday through Friday**.
- Scheduled workflows may start later during busy periods.
- No paid market-data API or secret API key is required.

The generated results are stored in `data/scanner.json` and served through GitHub Pages.

## Status indicators

- **Current scan (green):** Fresh results and every requested symbol returned usable data.
- **Partial scan (yellow):** Fresh verified results are available, but one or more symbols were unavailable.
- **Stale data (red):** The most recent verified scan is more than four days old.
- **No current data (red):** Results are missing, malformed, or have never been published.

The interface never substitutes sample prices for missing live results.

## Safety and validation

Before publishing, `scripts/validate_scan.py` checks:

- JSON schema version and required fields
- Minimum result count
- Screened, failed, and universe counts
- Duplicate or conflicting tickers
- Finite, positive prices and moving averages
- Score and drawdown ranges
- Future-dated prices
- Missing, stale, or future generation timestamps

The workflow also saves the first verified Top Five for each market date under `data/history/`. Each complete candidate record is preserved with its selection-date price, score inputs, warnings, and `quant-90-v1` score version. Existing dates are never overwritten. `scripts/validate_history.py` verifies the chronological index, snapshot hashes, unique tickers, prices, component totals, and ranking before anything is committed.

`scripts/update_performance.py` publishes forward-return states for 21, 63, 126, 252, and 504 trading sessions. A result stays pending until its session exists, becomes measured only from verified adjusted closes, and becomes unavailable when required price coverage is missing. Measured results include comparisons with SPY, the corresponding sector ETF, and—where snapshot schema 2 preserved membership—an equal-weight point-in-time screened universe with at least 80% price coverage.

If downloading, scanning, or validation fails, the workflow exits with an error and preserves the last verified published scan.

## Run the scanner manually

1. Open the repository's [Actions page](https://github.com/lmccorkle1/Market-scout/actions/workflows/daily-scan.yml).
2. Select **Run workflow**.
3. Keep the branch set to `main` and confirm the run.
4. Wait for the green check.
5. Refresh the live scanner after GitHub Pages finishes rebuilding.

The workflow can also be triggered by changes to `scripts/scan.py` or `.github/workflows/daily-scan.yml`.

## Troubleshooting

If the scanner shows old or missing data:

1. Open the latest **Market Scout Daily Scan** run under GitHub Actions.
2. Expand the first failed step and read its error message.
3. Do not manually invent or paste replacement market values.
4. Keep the previous verified `data/scanner.json` until a complete run passes.
5. After a successful run, allow a minute or two for GitHub Pages to rebuild.

An unavailable symbol can be normal after a ticker change, index addition, delisting, or insufficient trading history. Partial status makes this visible without discarding the other verified results.

## Repository structure

```text
index.html                         Main dashboard
scanner.html                       Daily scanner interface
performance.html                   Forward-return status and results
data/scanner.json                  Generated verified results
data/performance.json              Pending and measured forward returns
data/history/index.json            Chronological immutable snapshot index
data/history/YYYY-MM-DD.json       First verified Top Five for a market date
scripts/scan.py                    Market-data scanner
scripts/validate_scan.py           Pre-publication validation
scripts/validate_history.py        Snapshot and immutable-hash validation
scripts/update_performance.py      Forward-return measurement engine
scripts/validate_performance.py    Performance-state validation
.github/workflows/daily-scan.yml   Scheduled automation
ROADMAP.md                         Planned improvements
```

## Local use

The website is static, but browsers usually block `fetch()` from local `file://` pages. Serve the repository through a small local web server instead:

```bash
python -m http.server 8000
```

Then open `http://localhost:8000/scanner.html`.

## Disclaimer

Market Scout is an educational research tool, not financial advice. Market and fundamental data can be delayed, incomplete, adjusted, or incorrect. Its broad quantitative checks do not establish intrinsic value, verify catalysts, or account for an individual's portfolio, taxes, suitability, or risk tolerance. Verify information independently before making any investment decision.
