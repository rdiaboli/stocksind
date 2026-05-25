"""Optional NSE last-traded-price client.

NSE has no official public API. The ``/api/quote-equity`` endpoint is the one
the website itself calls, and it only answers requests that carry the cookies
the homepage sets — so this client performs a browser-like handshake, keeps a
single shared session, refreshes cookies on an auth failure, and returns
``None`` on any problem so callers transparently fall back to Yahoo.

Only used when ``config.USE_NSE_PRICE`` (or an explicit flag) is enabled.
"""
from __future__ import annotations

import threading
from typing import Optional

import requests

import config

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": config.NSE_BASE + "/get-quotes/equity",
}

_lock = threading.Lock()
_session: Optional[requests.Session] = None


def _new_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    # Handshake: the homepage hands back the cookies the API requires.
    s.get(config.NSE_BASE, timeout=config.NSE_TIMEOUT)
    return s


def _get_session(force_new: bool = False) -> requests.Session:
    global _session
    with _lock:
        if _session is None or force_new:
            _session = _new_session()
        return _session


def _parse_price(data: dict) -> Optional[float]:
    """Extract a usable price from a quote-equity JSON payload (pure)."""
    price_info = (data or {}).get("priceInfo") or {}
    for key in ("lastPrice", "close", "previousClose"):
        v = price_info.get(key)
        if v in (None, "", 0, "0"):
            continue
        try:
            return float(str(v).replace(",", ""))
        except (TypeError, ValueError):
            continue
    return None


def last_price(symbol: str) -> Optional[float]:
    """Return NSE's last-traded price for an NSE symbol, or None on failure."""
    url = f"{config.NSE_BASE}/api/quote-equity"
    for attempt in range(2):
        try:
            s = _get_session(force_new=(attempt > 0))
            r = s.get(url, params={"symbol": symbol}, timeout=config.NSE_TIMEOUT)
            if r.status_code in (401, 403):
                continue  # stale/blocked cookies -> rehandshake and retry once
            r.raise_for_status()
            return _parse_price(r.json())
        except Exception:  # noqa: BLE001 - any failure -> caller falls back to Yahoo
            continue
    return None
