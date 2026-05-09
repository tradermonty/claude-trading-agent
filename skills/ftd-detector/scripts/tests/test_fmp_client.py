"""Tests for FMP client endpoint fallback (stable -> v3).

Tier A: Fallback logic (4 tests)
Tier B: Response normalization (4 tests)
Tier B+: Shape validation (2 tests)
Tier C: Caller regression (2 tests)
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Ensure scripts directory is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fmp_client import FMPClient


def _make_client():
    """Create an FMPClient with a fake API key and zero rate-limit delay."""
    client = FMPClient(api_key="test_key")
    client.RATE_LIMIT_DELAY = 0
    return client


def _mock_response(status_code, json_data=None):
    """Create a mock response object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = f"HTTP {status_code}"
    return resp


# =========================================================================
# Tier A — Fallback logic
# =========================================================================


class TestFallbackLogic:
    """Tier A: stable -> v3 fallback mechanics."""

    def test_quote_stable_success(self):
        """Stable 200 returns data; v3 not called."""
        client = _make_client()
        quote_data = [{"symbol": "^GSPC", "price": 5000.0}]
        stable_resp = _mock_response(200, quote_data)

        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return stable_resp

        client.session.get = MagicMock(side_effect=side_effect)
        result = client.get_quote("^GSPC")
        assert result == quote_data
        # Only stable endpoint called (1 call)
        assert call_count == 1

    def test_quote_stable_403_falls_back_to_v3(self):
        """Stable 403, v3 200 -> returns v3 data."""
        client = _make_client()
        quote_data = [{"symbol": "^GSPC", "price": 5000.0}]
        stable_resp = _mock_response(403)
        v3_resp = _mock_response(200, quote_data)

        responses = [stable_resp, v3_resp]
        client.session.get = MagicMock(side_effect=responses)

        result = client.get_quote("^GSPC")
        assert result == quote_data
        assert client.session.get.call_count == 2

    def test_quote_both_fail(self):
        """Both 403 -> returns None."""
        client = _make_client()
        stable_resp = _mock_response(403)
        v3_resp = _mock_response(403)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_quote("^GSPC")
        assert result is None

    def test_historical_fallback_to_v3(self):
        """Stable 403, v3 200 -> returns v3 historical data."""
        client = _make_client()
        hist_data = {
            "symbol": "^GSPC",
            "historical": [{"date": "2026-03-20", "close": 5000.0}],
        }
        stable_resp = _mock_response(403)
        v3_resp = _mock_response(200, hist_data)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_historical_prices("^GSPC", days=80)
        assert result == hist_data
        assert client.session.get.call_count == 2


# =========================================================================
# Tier B — Response normalization
# =========================================================================


class TestResponseNormalization:
    """Tier B: historicalStockList normalization and passthrough."""

    def test_historical_stable_v3_format_passthrough(self):
        """Stable 200 with {"historical": [...]} -> returned as-is."""
        client = _make_client()
        hist_data = {
            "symbol": "^GSPC",
            "historical": [{"date": "2026-03-20", "close": 5000.0}],
        }
        resp = _mock_response(200, hist_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_historical_prices("^GSPC", days=80)
        assert result == hist_data

    def test_historical_stable_batch_format_exact_match(self):
        """Stable 200 with historicalStockList matching symbol -> normalized."""
        client = _make_client()
        batch_data = {
            "historicalStockList": [
                {
                    "symbol": "^GSPC",
                    "historical": [{"date": "2026-03-20", "close": 5000.0}],
                }
            ]
        }
        resp = _mock_response(200, batch_data)
        client.session.get = MagicMock(return_value=resp)

        result = client.get_historical_prices("^GSPC", days=80)
        assert result is not None
        assert "historical" in result
        assert result["historical"] == [{"date": "2026-03-20", "close": 5000.0}]
        assert result["symbol"] == "^GSPC"

    def test_historical_stable_batch_no_match_falls_back_to_v3(self):
        """Stable batch no match -> continues to v3 200."""
        client = _make_client()
        # Stable returns batch with a different symbol
        batch_data = {
            "historicalStockList": [
                {
                    "symbol": "SPY",
                    "historical": [{"date": "2026-03-20", "close": 500.0}],
                }
            ]
        }
        v3_data = {
            "symbol": "^GSPC",
            "historical": [{"date": "2026-03-20", "close": 5000.0}],
        }
        stable_resp = _mock_response(200, batch_data)
        v3_resp = _mock_response(200, v3_data)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_historical_prices("^GSPC", days=80)
        assert result == v3_data
        assert client.session.get.call_count == 2

    def test_historical_batch_no_match_returns_none_when_v3_also_fails(self):
        """Stable batch no match + v3 403 -> None."""
        client = _make_client()
        batch_data = {
            "historicalStockList": [
                {
                    "symbol": "SPY",
                    "historical": [{"date": "2026-03-20", "close": 500.0}],
                }
            ]
        }
        stable_resp = _mock_response(200, batch_data)
        v3_resp = _mock_response(403)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_historical_prices("^GSPC", days=80)
        assert result is None


# =========================================================================
# Tier B+ — Shape validation
# =========================================================================


class TestShapeValidation:
    """Tier B+: Reject truthy-but-wrong-shape responses."""

    def test_quote_rejects_non_list_response(self):
        """Stable returns truthy dict -> skipped, falls back to v3."""
        client = _make_client()
        # Stable returns a dict (wrong shape for quote)
        error_data = {"Error Message": "Invalid API call"}
        v3_data = [{"symbol": "^GSPC", "price": 5000.0}]

        stable_resp = _mock_response(200, error_data)
        v3_resp = _mock_response(200, v3_data)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_quote("^GSPC")
        assert result == v3_data
        assert client.session.get.call_count == 2

    def test_historical_rejects_non_dict_response(self):
        """Stable returns truthy list -> skipped, falls back to v3."""
        client = _make_client()
        # Stable returns a list (wrong shape for historical)
        wrong_data = [1, 2, 3]
        v3_data = {
            "symbol": "^GSPC",
            "historical": [{"date": "2026-03-20", "close": 5000.0}],
        }

        stable_resp = _mock_response(200, wrong_data)
        v3_resp = _mock_response(200, v3_data)

        client.session.get = MagicMock(side_effect=[stable_resp, v3_resp])

        result = client.get_historical_prices("^GSPC", days=80)
        assert result == v3_data
        assert client.session.get.call_count == 2


# =========================================================================
# Tier B++ — Symbol mismatch protection
# =========================================================================


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


# =========================================================================
# Tier C — Caller regression
# =========================================================================


class TestCallerRegression:
    """Tier C: Verify ftd_detector.main() handles FMPClient failures correctly."""

    def test_ftd_detector_exits_on_historical_failure(self):
        """get_historical_prices -> None => main() calls sys.exit(1) (fatal)."""
        with (
            patch.dict(os.environ, {"FMP_API_KEY": "test_key"}),  # pragma: allowlist secret
            patch("sys.argv", ["ftd_detector.py"]),
        ):
            # Import inside patch to pick up env var
            import ftd_detector

            with (
                patch.object(ftd_detector.FMPClient, "get_historical_prices", return_value=None),
                patch.object(
                    ftd_detector.FMPClient,
                    "get_quote",
                    return_value=[{"symbol": "^GSPC", "price": 5000.0}],
                ),
            ):
                with pytest.raises(SystemExit) as exc_info:
                    ftd_detector.main()
                assert exc_info.value.code == 1

    def test_ftd_detector_continues_on_quote_failure(self):
        """get_quote -> None => main() continues with warning (non-fatal)."""
        with (
            patch.dict(os.environ, {"FMP_API_KEY": "test_key"}),  # pragma: allowlist secret
            patch("sys.argv", ["ftd_detector.py"]),
        ):
            import ftd_detector

            sp500_hist = {
                "historical": [
                    {
                        "date": f"2026-03-{20 - i:02d}",
                        "open": 5000.0,
                        "high": 5010.0,
                        "low": 4990.0,
                        "close": 5000.0 - i * 10,
                        "volume": 3_000_000_000,
                    }
                    for i in range(80)
                ]
            }
            qqq_hist = {
                "historical": [
                    {
                        "date": f"2026-03-{20 - i:02d}",
                        "open": 450.0,
                        "high": 455.0,
                        "low": 445.0,
                        "close": 450.0 - i,
                        "volume": 50_000_000,
                    }
                    for i in range(80)
                ]
            }

            def mock_hist(symbol, days=365):
                if symbol == "^GSPC":
                    return sp500_hist
                elif symbol == "QQQ":
                    return qqq_hist
                return None

            with (
                patch.object(
                    ftd_detector.FMPClient, "get_historical_prices", side_effect=mock_hist
                ),
                patch.object(ftd_detector.FMPClient, "get_quote", return_value=None),
                patch.object(ftd_detector, "generate_json_report"),
                patch.object(ftd_detector, "generate_markdown_report"),
            ):
                # Should NOT raise SystemExit — quote failure is non-fatal
                ftd_detector.main()


# =========================================================================
# Direct client helpers and wrapper behavior
# =========================================================================


class TestRateLimitedGet:
    def test_init_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("FMP" + "_API_KEY", raising=False)

        with pytest.raises(ValueError):
            FMPClient()

    def test_rate_limited_get_success_tracks_api_calls(self):
        client = _make_client()
        client.retry_count = 1
        client.session.get = MagicMock(return_value=_mock_response(200, {"ok": True}))

        assert client._rate_limited_get("https://example.test") == {"ok": True}
        assert client.retry_count == 0
        assert client.api_calls_made == 1

    def test_rate_limited_get_retries_429_then_succeeds(self):
        client = _make_client()
        client.session.get = MagicMock(
            side_effect=[
                _mock_response(429, None),
                _mock_response(200, {"ok": True}),
            ]
        )

        with patch("fmp_client.time.sleep") as sleep:
            assert client._rate_limited_get("https://example.test") == {"ok": True}

        sleep.assert_any_call(60)
        assert client.session.get.call_count == 2
        assert client.api_calls_made == 2

    def test_rate_limited_get_sets_circuit_on_repeated_429(self, capsys):
        client = _make_client()
        client.max_retries = 0
        client.session.get = MagicMock(return_value=_mock_response(429, None))

        assert client._rate_limited_get("https://example.test") is None
        assert client.rate_limit_reached is True
        assert "Daily API rate limit reached" in capsys.readouterr().err
        assert client._rate_limited_get("https://example.test") is None
        assert client.session.get.call_count == 1

    def test_rate_limited_get_non_200_respects_quiet_flag(self, capsys):
        client = _make_client()
        client.session.get = MagicMock(return_value=_mock_response(500, None))

        assert client._rate_limited_get("https://example.test", quiet=True) is None
        assert capsys.readouterr().err == ""

        assert client._rate_limited_get("https://example.test", quiet=False) is None
        assert "API request failed: 500" in capsys.readouterr().err

    def test_rate_limited_get_request_exception(self, capsys):
        import requests

        client = _make_client()
        client.session.get = MagicMock(side_effect=requests.exceptions.ConnectionError("down"))

        assert client._rate_limited_get("https://example.test") is None
        assert "Request exception" in capsys.readouterr().err


class TestBatchAndMathHelpers:
    def test_quote_and_historical_successes_are_cached(self):
        client = _make_client()
        client._request_with_fallback = MagicMock(
            side_effect=[
                [{"symbol": "SPY"}],
                {"symbol": "SPY", "historical": [{"close": 500}]},
            ]
        )

        assert client.get_quote("SPY") == [{"symbol": "SPY"}]
        assert client.get_quote("SPY") == [{"symbol": "SPY"}]
        assert client.get_historical_prices("SPY", days=20) == {
            "symbol": "SPY",
            "historical": [{"close": 500}],
        }
        assert client.get_historical_prices("SPY", days=20) == {
            "symbol": "SPY",
            "historical": [{"close": 500}],
        }
        assert client._request_with_fallback.call_count == 2

    def test_failed_quote_and_historical_results_are_not_cached(self):
        client = _make_client()
        client._request_with_fallback = MagicMock(return_value=None)

        assert client.get_quote("SPY") is None
        assert client.get_quote("SPY") is None
        assert client.get_historical_prices("SPY", days=20) is None
        assert client.get_historical_prices("SPY", days=20) is None
        assert client._request_with_fallback.call_count == 4

    def test_get_batch_quotes_batches_and_skips_failures(self):
        client = _make_client()

        def fake_get_quote(symbols):
            if symbols == "A,B,C,D,E":
                return [{"symbol": "A"}, {"symbol": "E"}]
            return None

        client.get_quote = MagicMock(side_effect=fake_get_quote)

        assert client.get_batch_quotes(["A", "B", "C", "D", "E", "F"]) == {
            "A": {"symbol": "A"},
            "E": {"symbol": "E"},
        }
        assert client.get_quote.call_args_list[0].args == ("A,B,C,D,E",)
        assert client.get_quote.call_args_list[1].args == ("F",)

    def test_get_batch_historical_collects_available_symbols(self):
        client = _make_client()

        def fake_get_historical(symbol, days):
            if symbol == "SPY":
                return {"historical": [{"close": 500}]}
            return None

        client.get_historical_prices = MagicMock(side_effect=fake_get_historical)

        assert client.get_batch_historical(["SPY", "QQQ"], days=10) == {"SPY": [{"close": 500}]}

    def test_calculate_ema_and_sma_short_and_full_series(self):
        client = _make_client()
        prices = [10.0, 9.0, 8.0, 7.0, 6.0]

        assert client.calculate_ema([10.0, 20.0], period=5) == 15.0
        assert round(client.calculate_ema(prices, period=3), 2) == 9.0
        assert client.calculate_sma([10.0, 20.0], period=5) == 15.0
        assert client.calculate_sma(prices, period=3) == 9.0

    def test_get_api_stats(self):
        client = _make_client()
        client.cache["x"] = {"ok": True}
        client.api_calls_made = 3
        client.rate_limit_reached = True

        assert client.get_api_stats() == {
            "cache_entries": 1,
            "api_calls_made": 3,
            "rate_limit_reached": True,
        }
