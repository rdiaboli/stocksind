"""Data layer: fetch yfinance fundamentals with a local parquet/JSON cache.

This is the single seam through which all fundamental data flows. A future
key-based provider can be added by implementing ``fetch_fundamentals`` with the
same return shape; nothing downstream needs to change.
"""
from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd

import config


@dataclass
class Fundamentals:
    ticker: str
    info: dict = field(default_factory=dict)
    income: pd.DataFrame = field(default_factory=pd.DataFrame)
    balance: pd.DataFrame = field(default_factory=pd.DataFrame)
    cashflow: pd.DataFrame = field(default_factory=pd.DataFrame)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _safe(ticker: str) -> str:
    return ticker.replace("/", "_").replace("\\", "_")


def _paths(ticker: str):
    base = config.CACHE_DIR / _safe(ticker)
    return {
        "info": base.with_suffix(".info.json"),
        "income": base.with_suffix(".income.parquet"),
        "balance": base.with_suffix(".balance.parquet"),
        "cashflow": base.with_suffix(".cashflow.parquet"),
    }


def _cache_fresh(ticker: str) -> bool:
    p = _paths(ticker)["info"]
    if not p.exists():
        return False
    age_hours = (time.time() - p.stat().st_mtime) / 3600.0
    return age_hours < config.CACHE_TTL_HOURS


def _stmt_columns_to_str(df: pd.DataFrame) -> pd.DataFrame:
    """Parquet needs string column names; yfinance uses Timestamp columns."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out.columns = [str(c.date()) if hasattr(c, "date") else str(c) for c in out.columns]
    return out


def _save(f: Fundamentals) -> None:
    p = _paths(f.ticker)
    _stmt_columns_to_str(f.income).to_parquet(p["income"])
    _stmt_columns_to_str(f.balance).to_parquet(p["balance"])
    _stmt_columns_to_str(f.cashflow).to_parquet(p["cashflow"])
    # info last: its mtime is the freshness marker.
    p["info"].write_text(json.dumps(_json_safe(f.info)))


def _json_safe(info: dict) -> dict:
    out = {}
    for k, v in (info or {}).items():
        try:
            json.dumps(v)
            out[k] = v
        except (TypeError, ValueError):
            out[k] = str(v)
    return out


def _load(ticker: str) -> Fundamentals:
    p = _paths(ticker)
    info = json.loads(p["info"].read_text()) if p["info"].exists() else {}

    def _rd(path):
        return pd.read_parquet(path) if path.exists() else pd.DataFrame()

    return Fundamentals(
        ticker=ticker,
        info=info,
        income=_rd(p["income"]),
        balance=_rd(p["balance"]),
        cashflow=_rd(p["cashflow"]),
    )


def _fetch_remote(ticker: str) -> Fundamentals:
    import yfinance as yf

    last_err: Optional[Exception] = None
    for attempt in range(config.FETCH_RETRIES):
        try:
            t = yf.Ticker(ticker)
            info = dict(t.info or {})
            income = t.income_stmt if t.income_stmt is not None else pd.DataFrame()
            balance = t.balance_sheet if t.balance_sheet is not None else pd.DataFrame()
            cashflow = t.cashflow if t.cashflow is not None else pd.DataFrame()
            # A populated info dict is our signal that the fetch actually worked.
            if not info or info.get("symbol") is None and income.empty:
                raise ValueError("empty response from yfinance")
            return Fundamentals(ticker, info, income, balance, cashflow)
        except Exception as e:  # noqa: BLE001 - record and back off
            last_err = e
            time.sleep(2 ** attempt)
    return Fundamentals(ticker, error=f"{type(last_err).__name__}: {last_err}")


def fetch_fundamentals(ticker: str, force: bool = False) -> Fundamentals:
    """Return fundamentals for a ticker, using cache unless stale or ``force``."""
    if not force and _cache_fresh(ticker):
        try:
            return _load(ticker)
        except Exception:  # noqa: BLE001 - corrupt cache, refetch
            pass
    f = _fetch_remote(ticker)
    if f.ok:
        try:
            _save(f)
        except Exception:  # noqa: BLE001 - caching is best-effort
            pass
    return f


def batch_fetch(tickers: List[str], force: bool = False) -> Dict[str, Fundamentals]:
    """Fetch many tickers concurrently. Returns a ticker -> Fundamentals map."""
    results: Dict[str, Fundamentals] = {}
    with ThreadPoolExecutor(max_workers=config.FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_fundamentals, t, force): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                results[t] = fut.result()
            except Exception as e:  # noqa: BLE001
                results[t] = Fundamentals(t, error=f"{type(e).__name__}: {e}")
    return results
