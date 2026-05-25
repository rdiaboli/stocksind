"""Sector classification and relative-valuation benchmarking.

EV/EBITDA and ROCE are not meaningful for banks/NBFCs/insurers, so financials
are routed to a dedicated bucket and excluded from the v1 screen. Sector
medians for the "cheap vs sector" test are computed over the *full valid
non-financial universe* (every stock with a positive, computable value), not
just stocks that already pass other filters.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# yfinance `sector` values and NSE industry labels that denote financials.
_FINANCIAL_SECTORS = {"financial services", "financial"}
_FINANCIAL_KEYWORDS = ("financial", "bank", "insurance", "nbfc", "capital market")


def is_financial(sector: Optional[str], nse_industry: Optional[str]) -> bool:
    s = (sector or "").strip().lower()
    ind = (nse_industry or "").strip().lower()
    if s in _FINANCIAL_SECTORS:
        return True
    return any(k in s or k in ind for k in _FINANCIAL_KEYWORDS)


def resolve_sector(sector: Optional[str], nse_industry: Optional[str]) -> str:
    """Best-available sector label for grouping (yfinance first, NSE fallback)."""
    s = (sector or "").strip()
    if s:
        return s
    ind = (nse_industry or "").strip()
    return ind or "Unknown"


def compute_sector_medians(df: pd.DataFrame) -> pd.DataFrame:
    """Median P/E and EV/EBITDA per sector, using only valid positive values.

    Expects columns: ``sector``, ``pe``, ``pe_ok``, ``ev_ebitda``,
    ``ev_ebitda_ok``. Returns a frame indexed by sector with
    ``pe_median`` and ``ev_ebitda_median``.
    """
    def _median(group: pd.DataFrame, value: str, ok: str) -> float:
        valid = group.loc[group[ok] & (group[value] > 0), value]
        return float(valid.median()) if len(valid) else np.nan

    rows = []
    for sector, g in df.groupby("sector"):
        rows.append(
            {
                "sector": sector,
                "pe_median": _median(g, "pe", "pe_ok"),
                "ev_ebitda_median": _median(g, "ev_ebitda", "ev_ebitda_ok"),
            }
        )
    return pd.DataFrame(rows).set_index("sector")


def mark_cheap_vs_sector(df: pd.DataFrame, medians: pd.DataFrame) -> pd.DataFrame:
    """Add ``cheap_vs_sector`` (bool) and ``cheap_reason`` (str) columns.

    A stock is cheap if its EV/EBITDA OR its P/E is below the sector median.
    """
    out = df.copy()
    cheap = []
    reason = []
    for _, r in out.iterrows():
        sec = r["sector"]
        med = medians.loc[sec] if sec in medians.index else None
        reasons = []
        if med is not None:
            if r["ev_ebitda_ok"] and r["ev_ebitda"] > 0 and not np.isnan(med["ev_ebitda_median"]) \
                    and r["ev_ebitda"] < med["ev_ebitda_median"]:
                reasons.append("EV/EBITDA<sector")
            if r["pe_ok"] and r["pe"] > 0 and not np.isnan(med["pe_median"]) \
                    and r["pe"] < med["pe_median"]:
                reasons.append("P/E<sector")
        cheap.append(bool(reasons))
        reason.append(", ".join(reasons))
    out["cheap_vs_sector"] = cheap
    out["cheap_reason"] = reason
    return out


def screen_financials(df: pd.DataFrame) -> pd.DataFrame:
    """Extension hook for a future financials-specific screen.

    Banks/NBFCs/insurers need P/B, ROE, ROA, NIM and asset-quality (GNPA)
    rather than EV/EBITDA + ROCE. Not implemented in v1 — financials are
    surfaced as excluded-by-design.
    """
    raise NotImplementedError("Financials screen (P/B, ROE, NIM, GNPA) is not part of v1.")
