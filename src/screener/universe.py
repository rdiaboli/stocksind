"""Load the Nifty 500 constituent universe and map symbols to yfinance tickers.

Tries the official NSE CSV first; on any failure falls back to the bundled
snapshot in ``data/nifty500.csv``. The NSE CSV schema is:
``Company Name, Industry, Symbol, Series, ISIN Code``.
"""
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import List

import pandas as pd
import requests

import config

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "text/csv,application/csv,*/*",
}


@dataclass(frozen=True)
class Constituent:
    symbol: str          # NSE symbol, e.g. "TCS"
    name: str
    nse_industry: str    # NSE macro-industry label from the CSV
    ticker: str          # yfinance ticker, e.g. "TCS.NS"


def _parse(df: pd.DataFrame) -> List[Constituent]:
    df = df.rename(columns=lambda c: c.strip())
    out: List[Constituent] = []
    for _, row in df.iterrows():
        sym = str(row["Symbol"]).strip()
        if not sym or sym.lower() == "nan":
            continue
        out.append(
            Constituent(
                symbol=sym,
                name=str(row.get("Company Name", "")).strip(),
                nse_industry=str(row.get("Industry", "")).strip(),
                ticker=f"{sym}{config.YF_SUFFIX}",
            )
        )
    return out


def _from_url() -> List[Constituent]:
    r = requests.get(config.NIFTY500_URL, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    return _parse(pd.read_csv(io.StringIO(r.text)))


def _from_bundle() -> List[Constituent]:
    return _parse(pd.read_csv(config.NIFTY500_CSV))


def load_universe(prefer_remote: bool = True) -> List[Constituent]:
    """Return the Nifty 500 constituents (remote-first, bundled fallback)."""
    if prefer_remote:
        try:
            cons = _from_url()
            if cons:
                return cons
        except Exception:  # noqa: BLE001 - blocked/offline -> use bundle
            pass
    return _from_bundle()
