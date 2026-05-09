#!/usr/bin/env python3
"""
FMP API Client for FTD Detector

Provides rate-limited access to Financial Modeling Prep API endpoints
for follow-through day detection analysis.

Features:
- Rate limiting (0.3s between requests)
- Automatic retry on 429 errors
- Session caching for duplicate requests
- Batch quote support for ETF baskets
"""

import os
import sys
import time

try:
    import requests
except ImportError:
    print("ERROR: requests library not found. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

try:
    from common.fmp_fallback import (
        FMP_FALLBACK_ENDPOINTS,
        normalize_historical_response,
        quote_response_matches,
    )
except ImportError:
    # Keep the skill script self-contained when uploaded/executed without the
    # repository-level common/ package.
    def _stable_quote_url(base, symbols_str, params):
        params["symbol"] = symbols_str
        return base, params

    def _v3_quote_url(base, symbols_str, params):
        return f"{base}/{symbols_str}", params

    def _stable_historical_url(base, symbols_str, params):
        params["symbol"] = symbols_str
        return base, params

    def _v3_historical_url(base, symbols_str, params):
        return f"{base}/{symbols_str}", params

    FMP_FALLBACK_ENDPOINTS = {
        "quote": [
            ("https://financialmodelingprep.com/stable/quote", _stable_quote_url),
            ("https://financialmodelingprep.com/api/v3/quote", _v3_quote_url),
        ],
        "historical": [
            (
                "https://financialmodelingprep.com/stable/historical-price-full",
                _stable_historical_url,
            ),
            (
                "https://financialmodelingprep.com/api/v3/historical-price-full",
                _v3_historical_url,
            ),
        ],
    }

    def _symbols_match(returned_symbol, requested_symbol):
        return returned_symbol.replace("-", ".") == requested_symbol.replace("-", ".")

    def normalize_historical_response(data, symbols_str, *, is_single):
        if not isinstance(data, dict):
            return None
        if "historicalStockList" in data:
            for entry in data["historicalStockList"]:
                if _symbols_match(entry.get("symbol", ""), symbols_str):
                    return {
                        "symbol": entry.get("symbol"),
                        "historical": entry.get("historical", []),
                    }
            return None
        if "historical" not in data:
            return None
        if is_single and data.get("symbol") and not _symbols_match(data["symbol"], symbols_str):
            return None
        return data

    def quote_response_matches(data, symbols_str, *, is_single):
        if not isinstance(data, list) or len(data) == 0:
            return False
        if is_single and not any(_symbols_match(q.get("symbol", ""), symbols_str) for q in data):
            return False
        return True


class FMPClient:
    """Client for Financial Modeling Prep API with rate limiting and caching"""

    BASE_URL = "https://financialmodelingprep.com/api/v3"
    RATE_LIMIT_DELAY = 0.3  # 300ms between requests

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise ValueError(
                "FMP API key required. Set FMP_API_KEY environment variable "
                "or pass api_key parameter."
            )
        self.session = requests.Session()
        self.session.headers.update({"apikey": self.api_key})
        self.cache = {}
        self.last_call_time = 0
        self.rate_limit_reached = False
        self.retry_count = 0
        self.max_retries = 1
        self.api_calls_made = 0
        # Circuit breaker: disable endpoints after consecutive failures
        self._endpoint_failures: dict[str, int] = {}
        self._disabled_endpoints: set[str] = set()
        self._ENDPOINT_FAILURE_THRESHOLD = 3

    def _rate_limited_get(
        self, url: str, params: dict | None = None, quiet: bool = False
    ) -> dict | None:
        if self.rate_limit_reached:
            return None

        if params is None:
            params = {}

        elapsed = time.time() - self.last_call_time
        if elapsed < self.RATE_LIMIT_DELAY:
            time.sleep(self.RATE_LIMIT_DELAY - elapsed)

        try:
            response = self.session.get(url, params=params, timeout=30)
            self.last_call_time = time.time()
            self.api_calls_made += 1

            if response.status_code == 200:
                self.retry_count = 0
                return response.json()
            elif response.status_code == 429:
                self.retry_count += 1
                if self.retry_count <= self.max_retries:
                    print("WARNING: Rate limit exceeded. Waiting 60 seconds...", file=sys.stderr)
                    time.sleep(60)
                    return self._rate_limited_get(url, params, quiet=quiet)
                else:
                    print("ERROR: Daily API rate limit reached.", file=sys.stderr)
                    self.rate_limit_reached = True
                    return None
            else:
                if not quiet:
                    print(
                        f"ERROR: API request failed: {response.status_code} - {response.text[:200]}",
                        file=sys.stderr,
                    )
                return None
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Request exception: {e}", file=sys.stderr)
            return None

    def _request_with_fallback(self, endpoint_key, symbols_str, extra_params=None):
        """Try stable endpoint first, fall back to v3. Circuit breaker skips failing endpoints."""
        params = dict(extra_params) if extra_params else {}
        endpoints = FMP_FALLBACK_ENDPOINTS[endpoint_key]
        is_single = "," not in symbols_str

        for i, (base_url, url_builder) in enumerate(endpoints):
            if base_url in self._disabled_endpoints:
                continue
            url, final_params = url_builder(base_url, symbols_str, dict(params))
            is_last = i == len(endpoints) - 1
            data = self._rate_limited_get(url, final_params, quiet=not is_last)
            if not data:
                failures = self._endpoint_failures.get(base_url, 0) + 1
                self._endpoint_failures[base_url] = failures
                if failures >= self._ENDPOINT_FAILURE_THRESHOLD:
                    self._disabled_endpoints.add(base_url)
                continue

            if endpoint_key == "quote":
                if not quote_response_matches(data, symbols_str, is_single=is_single):
                    continue

            if endpoint_key == "historical":
                normalized = normalize_historical_response(data, symbols_str, is_single=is_single)
                if normalized is None:
                    continue
                data = normalized

            self._endpoint_failures[base_url] = 0  # Reset on success
            return data
        return None

    def get_quote(self, symbols: str) -> list[dict] | None:
        """Fetch real-time quote data for one or more symbols (comma-separated)"""
        cache_key = f"quote_{symbols}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = self._request_with_fallback("quote", symbols)
        if data:
            self.cache[cache_key] = data
        return data

    def get_historical_prices(self, symbol: str, days: int = 365) -> dict | None:
        """Fetch historical daily OHLCV data"""
        cache_key = f"prices_{symbol}_{days}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        data = self._request_with_fallback("historical", symbol, {"timeseries": days})
        if data:
            self.cache[cache_key] = data
        return data

    def get_batch_quotes(self, symbols: list[str]) -> dict[str, dict]:
        """Fetch quotes for a list of symbols, batching up to 5 per request"""
        results = {}
        # FMP supports comma-separated symbols in quote endpoint
        batch_size = 5
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i : i + batch_size]
            batch_str = ",".join(batch)
            quotes = self.get_quote(batch_str)
            if quotes:
                for q in quotes:
                    results[q["symbol"]] = q
        return results

    def get_batch_historical(self, symbols: list[str], days: int = 50) -> dict[str, list[dict]]:
        """Fetch historical prices for multiple symbols"""
        results = {}
        for symbol in symbols:
            data = self.get_historical_prices(symbol, days=days)
            if data and "historical" in data:
                results[symbol] = data["historical"]
        return results

    def calculate_ema(self, prices: list[float], period: int) -> float:
        """Calculate Exponential Moving Average from a list of prices (most recent first)"""
        if len(prices) < period:
            return sum(prices) / len(prices)

        prices_reversed = prices[::-1]
        sma = sum(prices_reversed[:period]) / period
        ema = sma
        k = 2 / (period + 1)
        for price in prices_reversed[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def calculate_sma(self, prices: list[float], period: int) -> float:
        """Calculate Simple Moving Average from a list of prices (most recent first)"""
        if len(prices) < period:
            return sum(prices) / len(prices)
        return sum(prices[:period]) / period

    def get_api_stats(self) -> dict:
        return {
            "cache_entries": len(self.cache),
            "api_calls_made": self.api_calls_made,
            "rate_limit_reached": self.rate_limit_reached,
        }
