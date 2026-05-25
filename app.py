"""Streamlit UI for the Indian equity value screener.

Run with:  streamlit run app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

import config
from src.screener import screen
from src.screener.universe import load_universe

st.set_page_config(page_title="Indian Value Screener", layout="wide")

DISPLAY_COLS = [
    "rank", "symbol", "name", "sector", "price", "price_source", "pe", "ev_ebitda",
    "roce", "de", "piotroski", "cagr_3y", "cheap_reason", "data_confidence",
]


@st.cache_data(show_spinner="Fetching fundamentals (Nifty 500)…")
def _load_table(force: bool, use_nse_price: bool):
    cons = load_universe()
    df, medians, fin = screen.build_table(
        constituents=cons, force_refresh=force, use_nse_price=use_nse_price
    )
    return df, medians, fin, len(cons)


def _fmt(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    for c in ("roce", "cagr_3y"):
        if c in out:
            out[c] = (out[c] * 100).round(1)
    for c in ("pe", "ev_ebitda", "de", "price"):
        if c in out:
            out[c] = out[c].round(2)
    return out


def main():
    st.title("Indian Equity Value Screener")
    st.caption(
        "Undervalued + high-quality + improving picks from the Nifty 500. "
        "Data: free Yahoo Finance (yfinance) — known to have statement-quality quirks. "
        "**Research tool only, not investment advice.**"
    )

    sb = st.sidebar
    sb.header("Controls")
    force = sb.button("🔄 Refresh data (refetch)")
    use_nse_price = sb.checkbox(
        "Use NSE live price (slower)", value=bool(config.USE_NSE_PRICE),
        help="Last-traded price from NSE instead of Yahoo's delayed quote. "
             "Needs NSE to be network-reachable; falls back to Yahoo per stock on failure.",
    )
    sb.markdown("---")
    sb.subheader("Thresholds")
    roce_min = sb.slider("ROCE >", 0.0, 0.40, float(config.ROCE_MIN), 0.01, format="%.2f")
    de_max = sb.slider("Debt/Equity <", 0.0, 2.0, float(config.DE_MAX), 0.05)
    f_min = sb.slider("Piotroski F-score ≥", 0, 9, int(config.PIOTROSKI_MIN))
    cagr_min = sb.slider("3Y sales CAGR >", 0.0, 0.40, float(config.SALES_CAGR_MIN), 0.01, format="%.2f")

    thresholds = {
        "ROCE_MIN": roce_min, "DE_MAX": de_max,
        "PIOTROSKI_MIN": f_min, "SALES_CAGR_MIN": cagr_min, "OCF_MIN": 0.0,
    }

    if force:
        _load_table.clear()
    try:
        df, medians, fin, n = _load_table(force=force, use_nse_price=use_nse_price)
    except Exception as e:  # noqa: BLE001
        st.error(f"Failed to build table: {e}")
        return

    res = screen.apply_screen(df, medians, fin, thresholds)
    sb.markdown("---")
    sb.metric("Universe", n)
    sb.write(
        f"✅ {len(res.passed)} passed · ❌ {len(res.rejected)} rejected · "
        f"⚠️ {len(res.excluded)} excluded · 🏦 {len(res.financials)} financials"
    )

    t1, t2, t3, t4 = st.tabs([
        f"Undervalued picks ({len(res.passed)})",
        f"Rejected ({len(res.rejected)})",
        f"Excluded ({len(res.excluded)})",
        f"Financials ({len(res.financials)})",
    ])

    with t1:
        st.markdown("Ranked by within-sector cheapness (EV/EBITDA & P/E percentile). "
                    "ROCE and 3Y sales CAGR shown as %.")
        if res.passed.empty:
            st.info("No stocks pass all filters at the current thresholds.")
        else:
            cols = [c for c in DISPLAY_COLS if c in res.passed.columns]
            st.dataframe(_fmt(res.passed[cols]), width="stretch", hide_index=True)
            st.download_button(
                "⬇️ Download picks CSV",
                res.passed.to_csv(index=False).encode(),
                "undervalued_picks.csv", "text/csv",
            )

    with t2:
        st.markdown("Passed the data bar but failed a filter on trustworthy numbers.")
        if res.rejected.empty:
            st.info("Nothing here.")
        else:
            cols = [c for c in ["symbol", "name", "sector", "price", "pe", "ev_ebitda", "roce",
                                "de", "piotroski", "cagr_3y", "reject_reason"] if c in res.rejected.columns]
            st.dataframe(_fmt(res.rejected[cols]), width="stretch", hide_index=True)

    with t3:
        st.markdown("**Excluded — insufficient or unreliable data** (not labelled bad companies). "
                    "A required metric couldn't be computed or data confidence was low.")
        if res.excluded.empty:
            st.info("Nothing here.")
        else:
            cols = [c for c in ["symbol", "name", "sector", "data_confidence", "periods",
                                "fetch_error"] if c in res.excluded.columns]
            st.dataframe(res.excluded[cols], width="stretch", hide_index=True)

    with t4:
        st.markdown("**Financials (banks / NBFCs / insurers)** — excluded by design. EV/EBITDA and "
                    "ROCE don't apply; they need a P/B · ROE · NIM · asset-quality model (not in v1).")
        if res.financials.empty:
            st.info("Nothing here.")
        else:
            st.dataframe(res.financials, width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
