"""Pure valuation / quality metric functions.

Every public function returns ``(value, ok)`` where ``ok`` is False when the
inputs are missing or mathematically invalid (zero/negative denominators,
non-positive bases, etc.). Invalid metrics never raise — they fail closed so
the screen can route the stock to the *excluded* bucket and drop it from
sector-median calculations.

These functions take plain floats / small dicts so they can be unit-tested
without any network access.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Tuple

Number = Optional[float]
Result = Tuple[Optional[float], bool]


def _num(x) -> Number:
    """Coerce to float, returning None for missing/NaN/non-numeric."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _positive(x: Number) -> bool:
    return x is not None and x > 0


# --- Valuation -----------------------------------------------------------

def roce(ebit: Number, total_assets: Number, current_liabilities: Number) -> Result:
    """Return on capital employed = EBIT / (Total Assets - Current Liabilities)."""
    ebit, ta, cl = _num(ebit), _num(total_assets), _num(current_liabilities)
    if ebit is None or ta is None or cl is None:
        return None, False
    capital_employed = ta - cl
    if capital_employed <= 0:  # negative/zero capital employed is not meaningful
        return None, False
    return ebit / capital_employed, True


def debt_to_equity(total_debt: Number, total_equity: Number) -> Result:
    """Debt / equity. Negative or zero equity is invalid."""
    td, eq = _num(total_debt), _num(total_equity)
    if td is None or eq is None:
        return None, False
    if eq <= 0:
        return None, False
    return td / eq, True


def ev_ebitda(market_cap: Number, total_debt: Number, cash: Number, ebitda: Number) -> Result:
    """Enterprise value / EBITDA. Non-positive EBITDA is undefined for screening."""
    mc, td, csh, eb = _num(market_cap), _num(total_debt), _num(cash), _num(ebitda)
    if mc is None or eb is None:
        return None, False
    if eb <= 0:
        return None, False
    ev = mc + (td or 0.0) - (csh or 0.0)
    return ev / eb, True


def pe_ratio(price: Number, eps: Number) -> Result:
    """Price / earnings. Non-positive EPS yields an undefined (loss-making) P/E."""
    p, e = _num(price), _num(eps)
    if p is None or e is None or e <= 0:
        return None, False
    return p / e, True


def sales_cagr(revenue_latest: Number, revenue_base: Number, years: int) -> Result:
    """Compound annual growth rate of revenue over ``years`` periods."""
    latest, base = _num(revenue_latest), _num(revenue_base)
    if latest is None or base is None or years <= 0:
        return None, False
    if base <= 0 or latest <= 0:  # can't take a real CAGR across a sign change / zero base
        return None, False
    return (latest / base) ** (1.0 / years) - 1.0, True


def operating_cash_flow(ocf: Number) -> Result:
    """Latest annual operating cash flow (pass-through with validity check)."""
    v = _num(ocf)
    if v is None:
        return None, False
    return v, True


# --- Piotroski F-score ---------------------------------------------------

# Fields required (per year) to compute a trustworthy F-score.
PIOTROSKI_FIELDS = (
    "net_income",
    "operating_cash_flow",
    "total_assets",
    "long_term_debt",
    "current_assets",
    "current_liabilities",
    "shares",
    "gross_profit",
    "revenue",
)


def piotroski_fscore(curr: Mapping[str, Number], prior: Mapping[str, Number]) -> Tuple[Optional[int], bool]:
    """Compute the 9-point Piotroski F-score from two consecutive years.

    ``curr`` and ``prior`` are mappings containing ``PIOTROSKI_FIELDS``. If any
    required field is missing/invalid the score is not trustworthy and we
    return ``(None, False)`` so the stock is excluded rather than mis-scored.
    """
    c = {k: _num(curr.get(k)) for k in PIOTROSKI_FIELDS}
    p = {k: _num(prior.get(k)) for k in PIOTROSKI_FIELDS}
    if any(v is None for v in c.values()) or any(v is None for v in p.values()):
        return None, False

    # Denominators that must be non-zero for the ratio-based tests.
    if c["total_assets"] <= 0 or p["total_assets"] <= 0:
        return None, False
    if c["current_liabilities"] <= 0 or p["current_liabilities"] <= 0:
        return None, False
    if c["revenue"] <= 0 or p["revenue"] <= 0:
        return None, False

    roa_c = c["net_income"] / c["total_assets"]
    roa_p = p["net_income"] / p["total_assets"]
    cr_c = c["current_assets"] / c["current_liabilities"]
    cr_p = p["current_assets"] / p["current_liabilities"]
    gm_c = c["gross_profit"] / c["revenue"]
    gm_p = p["gross_profit"] / p["revenue"]
    at_c = c["revenue"] / c["total_assets"]
    at_p = p["revenue"] / p["total_assets"]
    ltd_c = c["long_term_debt"] / c["total_assets"]
    ltd_p = p["long_term_debt"] / p["total_assets"]

    score = 0
    # Profitability
    score += 1 if c["net_income"] > 0 else 0                 # 1. positive net income
    score += 1 if c["operating_cash_flow"] > 0 else 0        # 2. positive OCF
    score += 1 if roa_c > roa_p else 0                       # 3. rising ROA
    score += 1 if c["operating_cash_flow"] > c["net_income"] else 0  # 4. accruals (OCF > NI)
    # Leverage, liquidity, source of funds
    score += 1 if ltd_c < ltd_p else 0                       # 5. falling long-term-debt ratio
    score += 1 if cr_c > cr_p else 0                         # 6. rising current ratio
    score += 1 if c["shares"] <= p["shares"] else 0          # 7. no dilution
    # Operating efficiency
    score += 1 if gm_c > gm_p else 0                         # 8. rising gross margin
    score += 1 if at_c > at_p else 0                         # 9. rising asset turnover

    return score, True
