"""Shared Financial Modeling Prep endpoint fallback helpers.

Several skill scripts need to support both the newer ``/stable`` endpoints
and the legacy ``/api/v3`` endpoints. This module centralizes the endpoint
builders and response-shape validation so skill-specific clients can keep
their own caching/rate-limit behavior while sharing the provider routing
rules.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

EndpointBuilder = Callable[[str, str, dict[str, Any]], tuple[str, dict[str, Any]]]
Endpoint = tuple[str, EndpointBuilder]


def stable_quote_url(
    base: str, symbols_str: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Build ``stable/quote?symbol=A,B``."""
    params["symbol"] = symbols_str
    return base, params


def v3_quote_url(base: str, symbols_str: str, params: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Build ``api/v3/quote/A,B``."""
    return f"{base}/{symbols_str}", params


def stable_historical_url(
    base: str, symbols_str: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Build ``stable/historical-price-full?symbol=A&timeseries=N``."""
    params["symbol"] = symbols_str
    return base, params


def v3_historical_url(
    base: str, symbols_str: str, params: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Build ``api/v3/historical-price-full/A?timeseries=N``."""
    return f"{base}/{symbols_str}", params


FMP_FALLBACK_ENDPOINTS: dict[str, list[Endpoint]] = {
    "quote": [
        ("https://financialmodelingprep.com/stable/quote", stable_quote_url),
        ("https://financialmodelingprep.com/api/v3/quote", v3_quote_url),
    ],
    "historical": [
        (
            "https://financialmodelingprep.com/stable/historical-price-full",
            stable_historical_url,
        ),
        (
            "https://financialmodelingprep.com/api/v3/historical-price-full",
            v3_historical_url,
        ),
    ],
}


def symbols_match(returned_symbol: str, requested_symbol: str) -> bool:
    """Compare FMP symbols while tolerating dash/dot variants."""
    return returned_symbol.replace("-", ".") == requested_symbol.replace("-", ".")


def normalize_historical_response(data: Any, symbols_str: str, *, is_single: bool) -> dict | None:
    """Normalize supported FMP historical response shapes.

    Returns ``None`` when the response is truthy but has the wrong shape or
    does not contain the requested symbol, allowing callers to continue to the
    next fallback endpoint.
    """
    if not isinstance(data, dict):
        return None

    if "historicalStockList" in data:
        for entry in data["historicalStockList"]:
            if symbols_match(entry.get("symbol", ""), symbols_str):
                return {
                    "symbol": entry.get("symbol"),
                    "historical": entry.get("historical", []),
                }
        return None

    if "historical" not in data:
        return None

    if is_single and data.get("symbol") and not symbols_match(data["symbol"], symbols_str):
        return None

    return data


def quote_response_matches(data: Any, symbols_str: str, *, is_single: bool) -> bool:
    """Return True when an FMP quote response has a usable shape."""
    if not isinstance(data, list) or len(data) == 0:
        return False
    if is_single and not any(symbols_match(q.get("symbol", ""), symbols_str) for q in data):
        return False
    return True
