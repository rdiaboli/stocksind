# Indian Equity Value Screener

A screener for **undervalued, high-quality, improving** companies in the
**Nifty 500**. It applies a conjunctive (hard-filter) screen and ranks the
survivors by how cheap they are relative to their sector.

> **Research tool only — not investment advice.** It runs on free Yahoo Finance
> data (`yfinance`), which has known financial-statement quirks. Always verify a
> pick against primary sources before acting on it.

## The screen

A stock is an "undervalued pick" when **all** of the following hold:

| Filter | Rule |
| --- | --- |
| Cheap vs sector | EV/EBITDA **or** P/E below the sector median |
| Quality | ROCE > 15% |
| Leverage | Debt / Equity < 0.5 |
| Cash | Positive operating cash flow |
| Financial strength | Piotroski F-score ≥ 6 |
| Growth | 3-year sales CAGR > 10% |

Survivors are ranked by within-sector cheapness (mean of EV/EBITDA and P/E
percentile), tie-broken by F-score then ROCE. Thresholds are adjustable in the
UI and in `config.py`.

### Why four output buckets

Every stock lands in exactly one bucket so an outcome is never ambiguous:

- **Passed** — meets every filter on trustworthy numbers.
- **Rejected** — failed a filter on trustworthy numbers (a genuine "no", with reason).
- **Excluded** — a required metric is missing or data confidence is **low**
  (insufficient/unreliable data — *not* labelled a bad company).
- **Financials** — banks / NBFCs / insurers, excluded **by design**: EV/EBITDA
  and ROCE are not meaningful for them; they need a P/B · ROE · NIM ·
  asset-quality model (a future extension, see `sector.screen_financials`).

Each stock also carries a `data_confidence` flag (high/medium/low) based on how
many annual reporting periods and required line items were available.

## Setup

```bash
pip install -r requirements.txt
```

## Run

Web UI (recommended):

```bash
streamlit run app.py
```

CLI (full universe or a subset):

```bash
python -m src.screener.screen                          # whole Nifty 500
python -m src.screener.screen --tickers TCS INFY ITC   # a few names
python -m src.screener.screen --force                  # ignore cache, refetch
python -m src.screener.screen --nse-price              # use NSE live price (see below)
```

Tests (no network required):

```bash
pytest tests/
```

## How it works

```
universe.py  -> Nifty 500 constituents (official NSE CSV, bundled fallback)
data.py      -> yfinance fetch + local parquet/JSON cache (24h TTL, threaded)
metrics.py   -> pure ROCE / D-E / EV-EBITDA / P-E / sales-CAGR / Piotroski funcs
sector.py    -> financial classification + sector medians + cheap-vs-sector
screen.py    -> build metric table + data_confidence -> filter -> rank -> buckets
app.py       -> Streamlit UI
```

- **Universe**: tries the live NSE CSV first, falls back to the bundled
  `data/nifty500.csv` snapshot when the network blocks it.
- **Caching**: each ticker's fundamentals are cached under `data/cache/` and
  reused for 24h, so re-runs and threshold tweaks are fast.
- **Sector medians** are computed over the **full valid non-financial universe**
  (every stock with a positive, computable value), never only over already-passing
  stocks, so the cheap-vs-sector benchmark is not self-referential.

## Data-quality caveats

`yfinance` (Yahoo Finance) is free but its annual statements have documented
issues (e.g. occasional year-misalignment, value mismatches vs. filings). The
screener mitigates this by:

1. failing **closed** — if a required metric can't be computed, the stock is
   *excluded*, never silently passed;
2. dropping invalid/negative values from sector-median calculations;
3. surfacing a per-stock `data_confidence` flag.

The `data.py` layer is the single seam for data; a paid/key-based fundamentals
provider can be dropped in behind the same interface if quality proves too thin.

## Optional: NSE live price

By default the current price comes from Yahoo (a delayed quote bundled into the
fundamentals fetch). You can instead use **NSE** as the price source for a more
authoritative, fresher last-traded price — fundamentals still come from yfinance:

- UI: tick **"Use NSE live price (slower)"** in the sidebar.
- CLI: pass `--nse-price`.
- Default: set `USE_NSE_PRICE = True` in `config.py`.

How it behaves: NSE has no official public API, so the client (`nse.py`) performs
a browser-like cookie handshake against `nseindia.com` and calls the same
`quote-equity` endpoint the site uses. The price is fetched **fresh** each run
(never pinned to the 24h fundamentals cache) and **falls back to Yahoo per stock**
if NSE is unreachable or throttled. Caveats: NSE must be network-reachable
(blocked on locked-down networks), it adds one request per ticker, and NSE
rate-limits bulk access — so it is slower and off by default. When NSE supplies
the price, P/E is recomputed as `NSE price / trailing EPS`, and the results table
shows a `price_source` column so you can see which source was used per stock.

## Not in v1

Backtesting, intraday data, broker integration, and a financials-specific
screen. The architecture leaves hooks for these.
