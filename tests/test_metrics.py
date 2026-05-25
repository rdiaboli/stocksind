"""Unit tests for the pure metric functions and sector classification.

No network access — all inputs are synthetic.
"""
import math

import pytest

from src.screener import metrics, sector


# --- ROCE ----------------------------------------------------------------

def test_roce_basic():
    val, ok = metrics.roce(ebit=200, total_assets=1000, current_liabilities=200)
    assert ok and math.isclose(val, 0.25)


def test_roce_negative_capital_employed_invalid():
    val, ok = metrics.roce(ebit=100, total_assets=300, current_liabilities=400)
    assert not ok and val is None


def test_roce_missing_input_invalid():
    assert metrics.roce(None, 1000, 200) == (None, False)


# --- Debt / equity -------------------------------------------------------

def test_debt_to_equity_basic():
    val, ok = metrics.debt_to_equity(total_debt=300, total_equity=1000)
    assert ok and math.isclose(val, 0.3)


def test_debt_to_equity_negative_equity_invalid():
    assert metrics.debt_to_equity(300, -50) == (None, False)


# --- EV / EBITDA ---------------------------------------------------------

def test_ev_ebitda_basic():
    # EV = 1000 + 200 - 100 = 1100; /110 = 10
    val, ok = metrics.ev_ebitda(market_cap=1000, total_debt=200, cash=100, ebitda=110)
    assert ok and math.isclose(val, 10.0)


def test_ev_ebitda_negative_ebitda_invalid():
    assert metrics.ev_ebitda(1000, 200, 100, -50) == (None, False)


# --- P/E -----------------------------------------------------------------

def test_pe_basic():
    val, ok = metrics.pe_ratio(price=150, eps=10)
    assert ok and math.isclose(val, 15.0)


def test_pe_negative_earnings_invalid():
    assert metrics.pe_ratio(150, -2) == (None, False)


# --- Sales CAGR ----------------------------------------------------------

def test_sales_cagr_basic():
    # 1331 / 1000 over 3 years -> 10%
    val, ok = metrics.sales_cagr(revenue_latest=1331, revenue_base=1000, years=3)
    assert ok and math.isclose(val, 0.10, abs_tol=1e-9)


def test_sales_cagr_zero_base_invalid():
    assert metrics.sales_cagr(1000, 0, 3) == (None, False)


# --- Operating cash flow -------------------------------------------------

def test_ocf_passthrough_and_missing():
    assert metrics.operating_cash_flow(500) == (500.0, True)
    assert metrics.operating_cash_flow(None) == (None, False)


# --- Piotroski F-score ---------------------------------------------------

def _strong_pair():
    """A company improving on all nine dimensions -> score 9."""
    prior = {
        "net_income": 80, "operating_cash_flow": 90, "total_assets": 1000,
        "long_term_debt": 300, "current_assets": 400, "current_liabilities": 200,
        "shares": 100, "gross_profit": 300, "revenue": 1000,
    }
    curr = {
        "net_income": 150, "operating_cash_flow": 200, "total_assets": 1100,
        "long_term_debt": 250, "current_assets": 600, "current_liabilities": 200,
        "shares": 100, "gross_profit": 450, "revenue": 1300,
    }
    return curr, prior


def test_piotroski_perfect_nine():
    curr, prior = _strong_pair()
    score, ok = metrics.piotroski_fscore(curr, prior)
    assert ok and score == 9


def test_piotroski_weak_company_low_score():
    # Deteriorating: losses, negative OCF, dilution, falling margins.
    prior = {
        "net_income": 100, "operating_cash_flow": 120, "total_assets": 1000,
        "long_term_debt": 200, "current_assets": 500, "current_liabilities": 200,
        "shares": 100, "gross_profit": 400, "revenue": 1000,
    }
    curr = {
        "net_income": -50, "operating_cash_flow": -30, "total_assets": 1200,
        "long_term_debt": 400, "current_assets": 300, "current_liabilities": 300,
        "shares": 130, "gross_profit": 200, "revenue": 900,
    }
    score, ok = metrics.piotroski_fscore(curr, prior)
    assert ok and score <= 2


def test_piotroski_missing_field_invalid():
    curr, prior = _strong_pair()
    curr = dict(curr)
    curr["revenue"] = None
    assert metrics.piotroski_fscore(curr, prior) == (None, False)


# --- Sector classification ----------------------------------------------

@pytest.mark.parametrize("s,ind", [
    ("Financial Services", "FINANCIAL SERVICES"),
    (None, "BANK"),
    ("Financial Services", ""),
    (None, "Insurance"),
])
def test_is_financial_true(s, ind):
    assert sector.is_financial(s, ind)


@pytest.mark.parametrize("s,ind", [
    ("Technology", "IT"),
    ("Consumer Defensive", "FMCG"),
    ("Healthcare", "PHARMA"),
])
def test_is_financial_false(s, ind):
    assert not sector.is_financial(s, ind)
