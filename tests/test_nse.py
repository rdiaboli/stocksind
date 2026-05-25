"""Unit tests for NSE price parsing (pure, no network)."""
from src.screener import nse


def test_parse_price_last_price_with_commas():
    assert nse._parse_price({"priceInfo": {"lastPrice": "3,456.70"}}) == 3456.70


def test_parse_price_skips_zero_and_falls_back_to_close():
    assert nse._parse_price({"priceInfo": {"lastPrice": 0, "close": 123.4}}) == 123.4


def test_parse_price_falls_back_to_previous_close():
    assert nse._parse_price(
        {"priceInfo": {"lastPrice": "", "close": None, "previousClose": 99.5}}
    ) == 99.5


def test_parse_price_missing_returns_none():
    assert nse._parse_price({}) is None
    assert nse._parse_price({"priceInfo": {}}) is None
    assert nse._parse_price({"priceInfo": {"lastPrice": "n/a"}}) is None
