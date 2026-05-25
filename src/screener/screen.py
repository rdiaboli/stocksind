"""Screen orchestration: fetch -> compute -> bucket -> rank.

Produces four buckets so a stock's outcome is never ambiguous:
  - passed    : meets every filter on trustworthy numbers
  - rejected  : failed a filter on trustworthy numbers (a "bad company")
  - excluded  : a required metric is missing or data confidence is low
  - financials: banks/NBFCs/insurers, excluded-by-design (no v1 model)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

import config
from . import metrics, sector
from .data import Fundamentals, batch_fetch
from .universe import Constituent, load_universe

# Line-item label fallbacks (yfinance label drift across versions/companies).
_REVENUE = ("Total Revenue", "Operating Revenue")
_EBIT = ("EBIT", "Operating Income")
_EBITDA = ("EBITDA", "Normalized EBITDA")
_NET_INCOME = ("Net Income", "Net Income Common Stockholders", "Net Income Continuous Operations")
_GROSS_PROFIT = ("Gross Profit",)
_TOTAL_ASSETS = ("Total Assets",)
_CURRENT_LIAB = ("Current Liabilities", "Total Current Liabilities")
_CURRENT_ASSETS = ("Current Assets", "Total Current Assets")
_TOTAL_DEBT = ("Total Debt",)
_LONG_TERM_DEBT = ("Long Term Debt", "Long Term Debt And Capital Lease Obligation")
_EQUITY = ("Stockholders Equity", "Common Stock Equity", "Total Equity Gross Minority Interest")
_CASH = ("Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments")
_SHARES = ("Ordinary Shares Number", "Share Issued")
_OCF = ("Operating Cash Flow", "Cash Flow From Continuing Operating Activities")


def _series(df: pd.DataFrame, labels) -> Optional[List[float]]:
    """Return a row's values most-recent-first, or None if the label is absent."""
    if df is None or df.empty:
        return None
    for lab in labels:
        if lab in df.index:
            s = df.loc[lab]
            cols = sorted(s.index, key=lambda c: str(c), reverse=True)
            return [s[c] for c in cols]
    return None


def _at(values: Optional[List[float]], i: int):
    if values is None or i >= len(values):
        return None
    return values[i]


def _norm_de_from_info(info: dict):
    """yfinance reports debtToEquity as a percentage (e.g. 45.3 == 0.453)."""
    v = info.get("debtToEquity")
    try:
        return float(v) / 100.0 if v is not None else None
    except (TypeError, ValueError):
        return None


def _periods(f: Fundamentals) -> int:
    return max(
        (df.shape[1] for df in (f.income, f.balance, f.cashflow) if df is not None and not df.empty),
        default=0,
    )


def _build_row(c: Constituent, f: Fundamentals) -> dict:
    info = f.info or {}
    inc, bal, cf = f.income, f.balance, f.cashflow

    revenue = _series(inc, _REVENUE)
    ebit = _series(inc, _EBIT)
    net_income = _series(inc, _NET_INCOME)
    gross_profit = _series(inc, _GROSS_PROFIT)
    total_assets = _series(bal, _TOTAL_ASSETS)
    current_liab = _series(bal, _CURRENT_LIAB)
    current_assets = _series(bal, _CURRENT_ASSETS)
    total_debt_s = _series(bal, _TOTAL_DEBT)
    long_term_debt = _series(bal, _LONG_TERM_DEBT)
    equity = _series(bal, _EQUITY)
    cash_s = _series(bal, _CASH)
    shares = _series(bal, _SHARES)
    ocf = _series(cf, _OCF)

    # --- EV/EBITDA: prefer info, fall back to computed -------------------
    ev_ebitda_val, ev_ok = metrics._num(info.get("enterpriseToEbitda")), False
    ev_ok = ev_ebitda_val is not None and ev_ebitda_val > 0
    if not ev_ok:
        ebitda = info.get("ebitda")
        if ebitda is None:
            ebitda = _at(_series(inc, _EBITDA), 0)
        ev_ebitda_val, ev_ok = metrics.ev_ebitda(
            info.get("marketCap"),
            info.get("totalDebt") if info.get("totalDebt") is not None else _at(total_debt_s, 0),
            info.get("totalCash") if info.get("totalCash") is not None else _at(cash_s, 0),
            ebitda,
        )

    # --- P/E: prefer info, fall back to price/EPS ------------------------
    pe_val, pe_ok = metrics._num(info.get("trailingPE")), False
    pe_ok = pe_val is not None and pe_val > 0
    if not pe_ok:
        pe_val, pe_ok = metrics.pe_ratio(info.get("currentPrice"), info.get("trailingEps"))

    # --- ROCE ------------------------------------------------------------
    roce_val, roce_ok = metrics.roce(_at(ebit, 0), _at(total_assets, 0), _at(current_liab, 0))

    # --- Debt / equity: compute from BS, fall back to info ---------------
    de_val, de_ok = metrics.debt_to_equity(_at(total_debt_s, 0), _at(equity, 0))
    if not de_ok:
        de_info = _norm_de_from_info(info)
        if de_info is not None:
            de_val, de_ok = de_info, True

    # --- Operating cash flow --------------------------------------------
    ocf_val, ocf_ok = metrics.operating_cash_flow(_at(ocf, 0))

    # --- 3Y sales CAGR ---------------------------------------------------
    cagr_val, cagr_ok = metrics.sales_cagr(_at(revenue, 0), _at(revenue, 3), 3)

    # --- Piotroski F-score ----------------------------------------------
    def _yr(i: int) -> dict:
        return {
            "net_income": _at(net_income, i),
            "operating_cash_flow": _at(ocf, i),
            "total_assets": _at(total_assets, i),
            "long_term_debt": _at(long_term_debt, i),
            "current_assets": _at(current_assets, i),
            "current_liabilities": _at(current_liab, i),
            "shares": _at(shares, i),
            "gross_profit": _at(gross_profit, i),
            "revenue": _at(revenue, i),
        }

    f_val, f_ok = metrics.piotroski_fscore(_yr(0), _yr(1))

    sec = sector.resolve_sector(info.get("sector"), c.nse_industry)

    return {
        "symbol": c.symbol,
        "ticker": c.ticker,
        "name": info.get("longName") or info.get("shortName") or c.name,
        "sector": sec,
        "pe": pe_val, "pe_ok": pe_ok,
        "ev_ebitda": ev_ebitda_val, "ev_ebitda_ok": ev_ok,
        "roce": roce_val, "roce_ok": roce_ok,
        "de": de_val, "de_ok": de_ok,
        "ocf": ocf_val, "ocf_ok": ocf_ok,
        "cagr_3y": cagr_val, "cagr_ok": cagr_ok,
        "piotroski": f_val, "piotroski_ok": f_ok,
        "periods": _periods(f),
        "fetch_error": f.error,
    }


# Metrics whose validity is required to evaluate the screen.
_REQUIRED_OK = ("roce_ok", "de_ok", "ocf_ok", "cagr_ok", "piotroski_ok")


def _data_confidence(row: dict) -> str:
    err = row["fetch_error"]
    has_error = isinstance(err, str) and err.strip() != ""
    if has_error or row["periods"] < config.MIN_PERIODS_PIOTROSKI:
        return "low"
    n_ok = sum(bool(row[k]) for k in _REQUIRED_OK)
    has_valuation = row["pe_ok"] or row["ev_ebitda_ok"]
    if not has_valuation or n_ok <= 3:
        return "low"
    if row["periods"] >= config.MIN_PERIODS_CAGR and n_ok == len(_REQUIRED_OK) and has_valuation:
        return "high"
    return "medium"


def _has_required_data(row: dict) -> bool:
    if not all(row[k] for k in _REQUIRED_OK):
        return False
    return row["pe_ok"] or row["ev_ebitda_ok"]


@dataclass
class ScreenResult:
    passed: pd.DataFrame
    rejected: pd.DataFrame
    excluded: pd.DataFrame
    financials: pd.DataFrame


def _empty() -> pd.DataFrame:
    return pd.DataFrame()


def default_thresholds() -> Dict[str, float]:
    return {
        "ROCE_MIN": config.ROCE_MIN,
        "DE_MAX": config.DE_MAX,
        "PIOTROSKI_MIN": config.PIOTROSKI_MIN,
        "SALES_CAGR_MIN": config.SALES_CAGR_MIN,
        "OCF_MIN": config.OCF_MIN,
    }


def build_table(
    constituents: Optional[List[Constituent]] = None,
    force_refresh: bool = False,
):
    """Expensive step: fetch fundamentals and build the metric table.

    Returns ``(df, medians, financials_df)``. Independent of thresholds, so the
    UI can cache this and re-filter cheaply when sliders move.
    """
    cons = constituents if constituents is not None else load_universe()
    fundamentals = batch_fetch([c.ticker for c in cons], force=force_refresh)

    fin_rows, rows = [], []
    for c in cons:
        f = fundamentals.get(c.ticker, Fundamentals(c.ticker, error="not fetched"))
        info = f.info or {}
        if sector.is_financial(info.get("sector"), c.nse_industry):
            fin_rows.append(
                {"symbol": c.symbol, "ticker": c.ticker, "name": info.get("longName") or c.name,
                 "sector": sector.resolve_sector(info.get("sector"), c.nse_industry),
                 "reason": "financials: needs sector-specific model (P/B, ROE, NIM, GNPA) — not in v1"}
            )
            continue
        rows.append(_build_row(c, f))

    financials_df = pd.DataFrame(fin_rows)
    if not rows:
        return _empty(), pd.DataFrame(), financials_df

    df = pd.DataFrame(rows)
    df["data_confidence"] = df.apply(_data_confidence, axis=1)

    # Sector medians over the FULL valid non-financial universe (any stock
    # with a positive, computable P/E or EV/EBITDA), then cheap-vs-sector.
    medians = sector.compute_sector_medians(df)
    df = sector.mark_cheap_vs_sector(df, medians)
    return df, medians, financials_df


def apply_screen(
    df: pd.DataFrame,
    medians: pd.DataFrame,
    financials_df: pd.DataFrame,
    thresholds: Optional[Dict[str, float]] = None,
) -> ScreenResult:
    """Cheap step: apply thresholds to a pre-built table -> four buckets."""
    th = default_thresholds()
    if thresholds:
        th.update(thresholds)

    if df is None or df.empty:
        return ScreenResult(_empty(), _empty(), _empty(), financials_df)

    # Excluded: required metric missing OR low confidence.
    excluded_mask = ~df.apply(_has_required_data, axis=1) | (df["data_confidence"] == "low")
    excluded_df = df[excluded_mask].copy()
    eligible = df[~excluded_mask].copy()

    # Hard AND filters on trustworthy data.
    passes = (
        eligible["cheap_vs_sector"]
        & (eligible["roce"] > th["ROCE_MIN"])
        & (eligible["de"] < th["DE_MAX"])
        & (eligible["ocf"] > th["OCF_MIN"])
        & (eligible["piotroski"] >= th["PIOTROSKI_MIN"])
        & (eligible["cagr_3y"] > th["SALES_CAGR_MIN"])
    )
    passed_df = eligible[passes].copy()
    rejected_df = eligible[~passes].copy()
    if not rejected_df.empty:
        rejected_df["reject_reason"] = rejected_df.apply(lambda r: _reject_reason(r, th), axis=1)

    passed_df = _rank(passed_df, medians)
    return ScreenResult(passed_df, rejected_df, excluded_df, financials_df)


def run_screen(
    constituents: Optional[List[Constituent]] = None,
    force_refresh: bool = False,
    thresholds: Optional[Dict[str, float]] = None,
) -> ScreenResult:
    """Full pipeline (build + apply). Used by the CLI and tests."""
    df, medians, financials_df = build_table(constituents, force_refresh)
    return apply_screen(df, medians, financials_df, thresholds)


def _reject_reason(r: pd.Series, th: Dict[str, float]) -> str:
    fails = []
    if not r["cheap_vs_sector"]:
        fails.append("not cheap vs sector")
    if not r["roce"] > th["ROCE_MIN"]:
        fails.append(f"ROCE {r['roce']:.0%}<={th['ROCE_MIN']:.0%}")
    if not r["de"] < th["DE_MAX"]:
        fails.append(f"D/E {r['de']:.2f}>={th['DE_MAX']:.2f}")
    if not r["ocf"] > th["OCF_MIN"]:
        fails.append("OCF<=0")
    if not r["piotroski"] >= th["PIOTROSKI_MIN"]:
        fails.append(f"F-score {int(r['piotroski'])}<{int(th['PIOTROSKI_MIN'])}")
    if not r["cagr_3y"] > th["SALES_CAGR_MIN"]:
        fails.append(f"sales CAGR {r['cagr_3y']:.0%}<={th['SALES_CAGR_MIN']:.0%}")
    return "; ".join(fails)


def _rank(passed: pd.DataFrame, medians: pd.DataFrame) -> pd.DataFrame:
    """Rank by within-sector cheapness; tie-break by F-score then ROCE."""
    if passed.empty:
        return passed
    out = passed.copy()
    # Lower EV/EBITDA and P/E percentile within sector = cheaper.
    out["ev_pct"] = out.groupby("sector")["ev_ebitda"].rank(pct=True)
    out["pe_pct"] = out.groupby("sector")["pe"].rank(pct=True)
    out["cheapness"] = out[["ev_pct", "pe_pct"]].mean(axis=1)
    out = out.sort_values(
        by=["cheapness", "piotroski", "roce"], ascending=[True, False, False]
    ).reset_index(drop=True)
    out.insert(0, "rank", out.index + 1)
    return out


if __name__ == "__main__":  # lightweight smoke entry point
    import argparse

    parser = argparse.ArgumentParser(description="Run the Indian value screener.")
    parser.add_argument("--tickers", nargs="*", help="NSE symbols to screen (default: full universe)")
    parser.add_argument("--force", action="store_true", help="ignore cache, refetch")
    args = parser.parse_args()

    if args.tickers:
        full = {c.symbol: c for c in load_universe()}
        cons = []
        for sym in args.tickers:
            cons.append(full.get(sym, Constituent(sym, sym, "", f"{sym}{config.YF_SUFFIX}")))
    else:
        cons = None

    res = run_screen(constituents=cons, force_refresh=args.force)
    print(f"passed={len(res.passed)} rejected={len(res.rejected)} "
          f"excluded={len(res.excluded)} financials={len(res.financials)}")
    if not res.passed.empty:
        cols = ["rank", "symbol", "sector", "pe", "ev_ebitda", "roce", "de", "piotroski", "cagr_3y"]
        print(res.passed[cols].to_string(index=False))
