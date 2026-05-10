#!/usr/bin/env python3
"""
Tests for FMP stable/v3 endpoint fallback in canslim-screener.

Tier A (4): Fallback logic
Tier B (4): Response normalization
Tier B+ (2): Shape validation
Caller regression (2): screen_canslim.py behavior on failure
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_client():
    """Create FMPClient with a fake API key."""
    with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):  # pragma: allowlist secret
        from fmp_client import FMPClient

        client = FMPClient(api_key="test_key")
    return client


def _mock_response(status_code=200, json_data=None, text=""):
    """Create a mock requests.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = text
    return resp


# ---------------------------------------------------------------------------
# Tier A — Fallback logic (4 tests)
# ---------------------------------------------------------------------------


class TestFallbackLogic:
    """Verify stable-first, v3-fallback behavior."""

    def test_quote_stable_success(self):
        """Stable 200 returns data; v3 is never called."""
        client = _make_client()
        stable_resp = _mock_response(200, [{"symbol": "^GSPC", "price": 5000}])

        call_count = {"n": 0}

        def fake_get(url, params=None, timeout=30):
            call_count["n"] += 1
            if "stable" in url:
                return stable_resp
            pytest.fail("v3 endpoint should not be called")

        client.session.get = fake_get
        result = client.get_quote("^GSPC")
        assert result == [{"symbol": "^GSPC", "price": 5000}]
        assert call_count["n"] == 1

    def test_quote_stable_403_falls_back_to_v3(self):
        """Stable 403 → v3 200 → returns v3 data."""
        client = _make_client()
        stable_resp = _mock_response(403, None, "Forbidden")
        v3_resp = _mock_response(200, [{"symbol": "^GSPC", "price": 5100}])

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_quote("^GSPC")
        assert result == [{"symbol": "^GSPC", "price": 5100}]

    def test_quote_both_fail(self):
        """Both endpoints 403 → returns None."""
        client = _make_client()
        resp_403 = _mock_response(403, None, "Forbidden")

        client.session.get = MagicMock(return_value=resp_403)
        result = client.get_quote("^GSPC")
        assert result is None

    def test_historical_fallback_to_v3(self):
        """Stable 403 → v3 200 → returns v3 historical data."""
        client = _make_client()
        stable_resp = _mock_response(403, None, "Forbidden")
        v3_data = {"symbol": "^GSPC", "historical": [{"date": "2026-03-20", "close": 5000}]}
        v3_resp = _mock_response(200, v3_data)

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_historical_prices("^GSPC", days=80)
        assert result is not None
        assert "historical" in result
        assert result["historical"][0]["close"] == 5000


# ---------------------------------------------------------------------------
# Tier B — Response normalization (4 tests)
# ---------------------------------------------------------------------------


class TestResponseNormalization:
    """Verify response shape handling for stable vs v3 formats."""

    def test_historical_stable_v3_format_passthrough(self):
        """Stable returns v3-like {"historical": [...]} → returned as-is."""
        client = _make_client()
        data = {"symbol": "^GSPC", "historical": [{"date": "2026-03-20", "close": 5000}]}
        resp = _mock_response(200, data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_historical_prices("^GSPC", days=80)
        assert result == data

    def test_historical_stable_batch_format_exact_match(self):
        """Stable returns historicalStockList with matching symbol → normalized."""
        client = _make_client()
        batch_data = {
            "historicalStockList": [
                {
                    "symbol": "^GSPC",
                    "historical": [{"date": "2026-03-20", "close": 5000}],
                }
            ]
        }
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_historical_prices("^GSPC", days=80)
        assert result is not None
        assert result["symbol"] == "^GSPC"
        assert result["historical"] == [{"date": "2026-03-20", "close": 5000}]

    def test_historical_stable_batch_no_match_falls_back_to_v3(self):
        """Stable batch has wrong symbol → continue to v3 → v3 200."""
        client = _make_client()
        batch_data = {"historicalStockList": [{"symbol": "SPY", "historical": [{"close": 500}]}]}
        stable_resp = _mock_response(200, batch_data)
        v3_data = {"symbol": "^GSPC", "historical": [{"close": 5000}]}
        v3_resp = _mock_response(200, v3_data)

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_historical_prices("^GSPC", days=80)
        assert result is not None
        assert result["historical"][0]["close"] == 5000

    def test_historical_batch_no_match_returns_none_when_v3_also_fails(self):
        """Stable batch no match + v3 403 → returns None."""
        client = _make_client()
        batch_data = {"historicalStockList": [{"symbol": "SPY", "historical": [{"close": 500}]}]}
        stable_resp = _mock_response(200, batch_data)
        v3_resp = _mock_response(403, None, "Forbidden")

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_historical_prices("^GSPC", days=80)
        assert result is None


# ---------------------------------------------------------------------------
# Tier B+ — Shape validation (2 tests)
# ---------------------------------------------------------------------------


class TestShapeValidation:
    """Reject truthy-but-wrong-shape responses."""

    def test_quote_rejects_non_list_response(self):
        """Stable returns truthy dict → skipped, falls back to v3."""
        client = _make_client()
        error_data = {"Error Message": "Invalid API KEY"}
        stable_resp = _mock_response(200, error_data)
        v3_data = [{"symbol": "^GSPC", "price": 5000}]
        v3_resp = _mock_response(200, v3_data)

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_quote("^GSPC")
        assert result == v3_data

    def test_historical_rejects_non_dict_response(self):
        """Stable returns truthy list → skipped, falls back to v3."""
        client = _make_client()
        stable_resp = _mock_response(200, [1, 2, 3])
        v3_data = {"symbol": "^GSPC", "historical": [{"close": 5000}]}
        v3_resp = _mock_response(200, v3_data)

        def fake_get(url, params=None, timeout=30):
            if "stable" in url:
                return stable_resp
            return v3_resp

        client.session.get = fake_get
        result = client.get_historical_prices("^GSPC", days=80)
        assert result == v3_data

    def test_historical_rejects_dict_without_historical_payload(self):
        """A truthy dict without historical data is skipped before fallback succeeds."""
        client = _make_client()
        stable_resp = _mock_response(200, {"symbol": "^GSPC", "note": "metadata only"})
        v3_data = {"symbol": "^GSPC", "historical": [{"close": 5000}]}
        v3_resp = _mock_response(200, v3_data)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_historical_prices("^GSPC", days=80)

        assert result == v3_data
        assert client.session.get.call_count == 2


# ---------------------------------------------------------------------------
# Symbol mismatch protection (3 tests)
# ---------------------------------------------------------------------------


class TestSymbolMismatch:
    """Reject responses where returned symbol doesn't match the request."""

    def test_quote_symbol_mismatch_falls_back(self):
        """Single-symbol quote returning wrong symbol is rejected."""
        client = _make_client()
        wrong = _mock_response(200, [{"symbol": "SPY", "price": 500.0}])
        correct = _mock_response(200, [{"symbol": "^GSPC", "price": 5000.0}])
        client.session.get = MagicMock(side_effect=[wrong, correct])

        result = client.get_quote("^GSPC")
        assert result == [{"symbol": "^GSPC", "price": 5000.0}]
        assert client.session.get.call_count == 2

    def test_historical_symbol_mismatch_falls_back(self):
        """Single-symbol historical returning wrong symbol is rejected."""
        client = _make_client()
        wrong = _mock_response(200, {"symbol": "SPY", "historical": [{"close": 500}]})
        correct = _mock_response(200, {"symbol": "^GSPC", "historical": [{"close": 5000}]})
        client.session.get = MagicMock(side_effect=[wrong, correct])

        result = client.get_historical_prices("^GSPC", days=80)
        assert result["symbol"] == "^GSPC"
        assert client.session.get.call_count == 2

    def test_batch_quote_skips_symbol_check(self):
        """Multi-symbol (batch) quote does not apply symbol mismatch check."""
        client = _make_client()
        batch_data = [{"symbol": "^GSPC", "price": 5000}, {"symbol": "^VIX", "price": 20}]
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_quote("^GSPC,^VIX")
        assert result == batch_data
        assert client.session.get.call_count == 1


# ---------------------------------------------------------------------------
# Circuit breaker behavior
# ---------------------------------------------------------------------------


class TestEndpointCircuitBreaker:
    """Verify repeated fallback failures disable endpoint attempts."""

    def test_repeated_endpoint_failures_disable_endpoint(self):
        client = _make_client()
        client._ENDPOINT_FAILURE_THRESHOLD = 2
        client._rate_limited_get = MagicMock(return_value=None)

        assert client._request_with_fallback("quote", "^GSPC") is None
        assert client._request_with_fallback("quote", "^GSPC") is None

        stable_url = "https://financialmodelingprep.com/stable/quote"
        v3_url = "https://financialmodelingprep.com/api/v3/quote"
        assert stable_url in client._disabled_endpoints
        assert v3_url in client._disabled_endpoints

    def test_disabled_endpoint_is_skipped_and_next_endpoint_can_succeed(self):
        client = _make_client()
        stable_url = "https://financialmodelingprep.com/stable/quote"
        client._disabled_endpoints.add(stable_url)
        client._rate_limited_get = MagicMock(return_value=[{"symbol": "^GSPC", "price": 5000}])

        result = client._request_with_fallback("quote", "^GSPC")

        assert result == [{"symbol": "^GSPC", "price": 5000}]
        called_url = client._rate_limited_get.call_args.args[0]
        assert called_url == "https://financialmodelingprep.com/api/v3/quote/^GSPC"


# ---------------------------------------------------------------------------
# Caller regression (2 tests)
# ---------------------------------------------------------------------------


class TestCallerRegression:
    """Verify screen_canslim.py behavior when FMP endpoints fail."""

    def test_canslim_exits_on_quote_failure(self, tmp_path):
        """get_quote("^GSPC") → None causes sys.exit(1)."""
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):  # pragma: allowlist secret
            import screen_canslim

            with patch.object(screen_canslim.FMPClient, "get_quote", return_value=None):
                with patch(
                    "sys.argv",
                    [
                        "screen_canslim.py",
                        "--max-candidates",
                        "1",
                        "--output-dir",
                        str(tmp_path),
                    ],
                ):
                    with pytest.raises(SystemExit) as exc_info:
                        screen_canslim.main()
                    assert exc_info.value.code == 1

    def test_canslim_continues_on_historical_failure(self, capsys, tmp_path):
        """get_historical_prices("^GSPC") → None prints EMA fallback warning and continues."""
        with patch.dict(os.environ, {"FMP_API_KEY": "test_key"}):  # pragma: allowlist secret
            import screen_canslim

            mock_quote = [
                {
                    "symbol": "^GSPC",
                    "price": 5000.0,
                    "yearHigh": 5200.0,
                    "yearLow": 4200.0,
                    "changesPercentage": 0.5,
                }
            ]
            mock_vix = [{"symbol": "^VIX", "price": 15.0}]

            def mock_get_quote(symbols):
                if "^GSPC" in symbols and "^VIX" not in symbols:
                    return mock_quote
                if "^VIX" in symbols:
                    return mock_vix
                return mock_quote

            with (
                patch.object(screen_canslim.FMPClient, "get_quote", side_effect=mock_get_quote),
                patch.object(screen_canslim.FMPClient, "get_historical_prices", return_value=None),
                patch.object(screen_canslim.FMPClient, "get_income_statement", return_value=None),
                patch.object(screen_canslim.FMPClient, "get_profile", return_value=None),
                patch.object(
                    screen_canslim.FMPClient, "get_institutional_holders", return_value=None
                ),
                patch(
                    "sys.argv",
                    [
                        "screen_canslim.py",
                        "--max-candidates",
                        "1",
                        "--universe",
                        "AAPL",
                        "--output-dir",
                        str(tmp_path),
                    ],
                ),
            ):
                # Should NOT raise SystemExit — historical failure is non-fatal
                try:
                    screen_canslim.main()
                except SystemExit:
                    pytest.fail("screen_canslim.main() should not exit when historical prices fail")

            captured = capsys.readouterr()
            assert "EMA fallback" in captured.out or "historical data unavailable" in captured.out


# ---------------------------------------------------------------------------
# Direct client helpers and endpoint wrappers
# ---------------------------------------------------------------------------


class TestRateLimitedGet:
    def test_init_requires_api_key(self, monkeypatch):
        from fmp_client import FMPClient

        monkeypatch.delenv("FMP" + "_API_KEY", raising=False)

        with pytest.raises(ValueError):
            FMPClient()

    def test_rate_limited_get_success_resets_retry_count(self):
        client = _make_client()
        client.retry_count = 1
        client.session.get = MagicMock(return_value=_mock_response(200, {"ok": True}))

        assert client._rate_limited_get("https://example.test") == {"ok": True}
        assert client.retry_count == 0

    def test_rate_limited_get_retries_429_then_succeeds(self):
        client = _make_client()
        rate_limited = _mock_response(429, None, "too many")
        ok = _mock_response(200, {"ok": True})
        client.session.get = MagicMock(side_effect=[rate_limited, ok])

        with patch("fmp_client.time.sleep") as sleep:
            assert client._rate_limited_get("https://example.test") == {"ok": True}

        sleep.assert_any_call(60)
        assert client.session.get.call_count == 2

    def test_rate_limited_get_sets_circuit_on_repeated_429(self, capsys):
        client = _make_client()
        client.max_retries = 0
        client.session.get = MagicMock(return_value=_mock_response(429, None, "too many"))

        assert client._rate_limited_get("https://example.test") is None
        assert client.rate_limit_reached is True
        assert "Daily API rate limit reached" in capsys.readouterr().err
        assert client._rate_limited_get("https://example.test") is None
        assert client.session.get.call_count == 1

    def test_rate_limited_get_non_200_respects_quiet_flag(self, capsys):
        client = _make_client()
        client.session.get = MagicMock(return_value=_mock_response(500, None, "server error"))

        assert client._rate_limited_get("https://example.test", quiet=True) is None
        assert capsys.readouterr().err == ""

        assert client._rate_limited_get("https://example.test", quiet=False) is None
        assert "API request failed: 500" in capsys.readouterr().err

    def test_rate_limited_get_request_exception(self, capsys):
        import requests

        client = _make_client()
        client.session.get = MagicMock(side_effect=requests.exceptions.Timeout("slow"))

        assert client._rate_limited_get("https://example.test") is None
        assert "Request exception" in capsys.readouterr().err


class TestDirectEndpointWrappers:
    def test_income_statement_profile_and_holders_cache_successes(self):
        client = _make_client()
        client._rate_limited_get = MagicMock(
            side_effect=[
                [{"date": "2026-01-01"}],
                [{"symbol": "AAPL"}],
                [{"holder": "Fund"}],
            ]
        )

        assert client.get_income_statement("AAPL") == [{"date": "2026-01-01"}]
        assert client.get_income_statement("AAPL") == [{"date": "2026-01-01"}]
        assert client.get_profile("AAPL") == [{"symbol": "AAPL"}]
        assert client.get_profile("AAPL") == [{"symbol": "AAPL"}]
        assert client.get_institutional_holders("AAPL") == [{"holder": "Fund"}]
        assert client.get_institutional_holders("AAPL") == [{"holder": "Fund"}]
        assert client._rate_limited_get.call_count == 3

    def test_failed_direct_endpoint_results_are_not_cached(self):
        client = _make_client()
        client._rate_limited_get = MagicMock(return_value=None)

        assert client.get_income_statement("AAPL") is None
        assert client.get_income_statement("AAPL") is None
        assert client.get_profile("AAPL") is None
        assert client.get_profile("AAPL") is None
        assert client.get_institutional_holders("AAPL") is None
        assert client.get_institutional_holders("AAPL") is None
        assert client._rate_limited_get.call_count == 6

    def test_quote_and_historical_cache_successes(self):
        client = _make_client()
        client._request_with_fallback = MagicMock(
            side_effect=[
                [{"symbol": "AAPL"}],
                {"symbol": "AAPL", "historical": [{"close": 100}]},
            ]
        )

        assert client.get_quote("AAPL") == [{"symbol": "AAPL"}]
        assert client.get_quote("AAPL") == [{"symbol": "AAPL"}]
        assert client.get_historical_prices("AAPL", days=80) == {
            "symbol": "AAPL",
            "historical": [{"close": 100}],
        }
        assert client.get_historical_prices("AAPL", days=80) == {
            "symbol": "AAPL",
            "historical": [{"close": 100}],
        }
        assert client._request_with_fallback.call_count == 2


class TestMathAndStatsHelpers:
    def test_calculate_ema_uses_simple_average_when_short(self):
        client = _make_client()

        assert client.calculate_ema([10.0, 20.0], period=5) == 15.0

    def test_calculate_ema_for_full_series(self):
        client = _make_client()
        prices = [float(i) for i in range(10, 0, -1)]

        assert round(client.calculate_ema(prices, period=3), 2) == 9.0

    def test_clear_cache_and_stats(self, capsys):
        client = _make_client()
        client.cache["x"] = {"ok": True}
        client.rate_limit_reached = True
        client.retry_count = 2

        assert client.get_api_stats() == {
            "cache_entries": 1,
            "rate_limit_reached": True,
            "retry_count": 2,
        }

        client.clear_cache()

        assert client.cache == {}
        assert "Cache cleared" in capsys.readouterr().err
