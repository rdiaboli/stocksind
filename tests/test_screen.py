"""Integration test for the extraction + bucketing + ranking pipeline.

Feeds synthetic yfinance-shaped statements through ``build_table`` /
``apply_screen`` (no network) to prove a strong-cheap stock passes, an
expensive peer is rejected, a financial is bucketed, and a data-starved name
is excluded.
"""
import pandas as pd

from src.screener import screen
from src.screener.data import Fundamentals
from src.screener.universe import Constituent

COLS4 = [pd.Timestamp(f"{y}-03-31") for y in (2024, 2023, 2022, 2021)]
COLS2 = COLS4[:2]


def _statements():
    income = pd.DataFrame(
        {
            "Total Revenue": [1500, 1300, 1150, 1000],
            "EBIT": [300, 240, 200, 150],
            "Net Income": [200, 150, 130, 100],
            "Gross Profit": [600, 500, 440, 380],
        },
        index=COLS4,
    ).T
    balance = pd.DataFrame(
        {
            "Total Assets": [1000, 950],
            "Current Liabilities": [200, 200],
            "Current Assets": [600, 400],
            "Total Debt": [300, 320],
            "Long Term Debt": [200, 250],
            "Stockholders Equity": [1000, 900],
            "Cash And Cash Equivalents": [100, 80],
            "Ordinary Shares Number": [100, 100],
        },
        index=COLS2,
    ).T
    cashflow = pd.DataFrame(
        {"Operating Cash Flow": [250, 160]}, index=COLS2
    ).T
    return income, balance, cashflow


def _fund(ticker, ev, pe, sector="Technology"):
    income, balance, cashflow = _statements()
    info = {
        "longName": ticker, "sector": sector,
        "enterpriseToEbitda": ev, "trailingPE": pe,
        "marketCap": 5000, "ebitda": 350, "totalDebt": 300, "totalCash": 100,
    }
    return Fundamentals(ticker, info, income, balance, cashflow)


def test_pipeline_buckets(monkeypatch):
    cons = [
        Constituent("GOOD", "Good Co", "IT", "GOOD.NS"),
        Constituent("EXP", "Expensive Co", "IT", "EXP.NS"),
        Constituent("HDFCBANK", "HDFC Bank", "FINANCIAL SERVICES", "HDFCBANK.NS"),
        Constituent("NODATA", "No Data Co", "IT", "NODATA.NS"),
    ]
    fake = {
        "GOOD.NS": _fund("GOOD.NS", ev=8, pe=12),
        "EXP.NS": _fund("EXP.NS", ev=20, pe=30),
        "HDFCBANK.NS": Fundamentals("HDFCBANK.NS", {"sector": "Financial Services"}),
        "NODATA.NS": Fundamentals("NODATA.NS", error="blocked"),
    }
    monkeypatch.setattr(screen, "batch_fetch", lambda tickers, force=False: fake)

    res = screen.run_screen(constituents=cons)

    assert list(res.passed["symbol"]) == ["GOOD"]
    assert res.passed.iloc[0]["piotroski"] == 9
    assert "EXP" in set(res.rejected["symbol"])
    assert "not cheap vs sector" in res.rejected.iloc[0]["reject_reason"]
    assert "HDFCBANK" in set(res.financials["symbol"])
    assert "NODATA" in set(res.excluded["symbol"])


def test_threshold_override_can_exclude_pick(monkeypatch):
    cons = [
        Constituent("GOOD", "Good Co", "IT", "GOOD.NS"),
        Constituent("EXP", "Expensive Co", "IT", "EXP.NS"),
    ]
    fake = {
        "GOOD.NS": _fund("GOOD.NS", ev=8, pe=12),
        "EXP.NS": _fund("EXP.NS", ev=20, pe=30),
    }
    monkeypatch.setattr(screen, "batch_fetch", lambda tickers, force=False: fake)

    # Demand a 50% CAGR that GOOD's ~14.5% can't meet -> no picks.
    res = screen.run_screen(constituents=cons, thresholds={"SALES_CAGR_MIN": 0.50})
    assert res.passed.empty
