"""Central configuration: screen thresholds and filesystem paths."""
from __future__ import annotations

from pathlib import Path

# --- Paths ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
NIFTY500_CSV = DATA_DIR / "nifty500.csv"

CACHE_DIR.mkdir(parents=True, exist_ok=True)

# --- Universe ------------------------------------------------------------
# Official NSE Nifty 500 constituents (downloaded, with bundled fallback).
NIFTY500_URL = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
YF_SUFFIX = ".NS"  # yfinance ticker suffix for NSE-listed equities

# --- Screen thresholds (the user's "undervalued" definition) -------------
ROCE_MIN = 0.15        # Return on capital employed > 15%
DE_MAX = 0.50          # Debt / equity < 0.5
PIOTROSKI_MIN = 6      # Piotroski F-score >= 6
SALES_CAGR_MIN = 0.10  # 3-year sales CAGR > 10%
OCF_MIN = 0.0          # Operating cash flow strictly positive
# "Cheap vs sector" = EV/EBITDA OR P/E below the sector median.

# --- Data fetch ----------------------------------------------------------
CACHE_TTL_HOURS = 24   # re-fetch a ticker only if its cache is older than this
FETCH_WORKERS = 8      # thread pool size for batch fetching
FETCH_RETRIES = 3      # per-ticker retries with exponential backoff

# --- Data confidence -----------------------------------------------------
# Minimum annual reporting periods needed for the statement-derived metrics.
MIN_PERIODS_CAGR = 4       # 3Y CAGR needs t and t-3
MIN_PERIODS_PIOTROSKI = 2  # F-score compares current vs prior year
