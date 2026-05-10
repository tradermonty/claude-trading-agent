"""Unit tests for ETFScanner FMP API migration.

Tests FMP backend, symbol normalization, caching, batching,
per-symbol retry, symbol-level fallback, and backend stats.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from etf_scanner import ETFScanner


# ---------------------------------------------------------------------------
# TestCalculateRSI
# ---------------------------------------------------------------------------
class TestCalculateRSI:
    """Tests for the static _calculate_rsi method."""

    def test_known_sequence_rsi(self):
        """RSI of a known oscillating sequence returns a value in (0, 100)."""
        # 20 data points with alternating gains and losses
        prices = pd.Series(
            [
                44.0,
                44.34,
                44.09,
                44.15,
                43.61,
                44.33,
                44.83,
                45.10,
                45.42,
                45.84,
                46.08,
                45.89,
                46.03,
                45.61,
                46.28,
                46.28,
                46.00,
                46.03,
                46.41,
                46.22,
            ]
        )
        rsi = ETFScanner._calculate_rsi(prices, period=14)
        assert rsi is not None
        assert 0 < rsi < 100

    def test_insufficient_data_returns_none(self):
        """Fewer than period+1 data points returns None."""
        prices = pd.Series([10.0, 11.0, 12.0])
        assert ETFScanner._calculate_rsi(prices, period=14) is None

    def test_all_gains_returns_100(self):
        """Monotonically increasing prices produce RSI = 100."""
        prices = pd.Series([float(i) for i in range(1, 20)])
        rsi = ETFScanner._calculate_rsi(prices, period=14)
        assert rsi == 100.0


# ---------------------------------------------------------------------------
# TestCalculate52wDistances
# ---------------------------------------------------------------------------
class TestCalculate52wDistances:
    """Tests for the static _calculate_52w_distances method."""

    def test_at_52w_high_returns_zero(self):
        """When current price equals 52w high, dist_from_52w_high is 0."""
        close = pd.Series([90.0, 95.0, 100.0])
        high = pd.Series([92.0, 97.0, 100.0])
        low = pd.Series([88.0, 93.0, 98.0])
        result = ETFScanner._calculate_52w_distances(close, high, low)
        assert result["dist_from_52w_high"] == 0.0

    def test_at_52w_low_returns_zero(self):
        """When current price equals 52w low, dist_from_52w_low is 0."""
        close = pd.Series([100.0, 95.0, 88.0])
        high = pd.Series([102.0, 97.0, 90.0])
        low = pd.Series([98.0, 93.0, 88.0])
        result = ETFScanner._calculate_52w_distances(close, high, low)
        assert result["dist_from_52w_low"] == 0.0

    def test_midpoint_values(self):
        """Midpoint values produce non-zero distances for both."""
        close = pd.Series([50.0, 100.0, 75.0])
        high = pd.Series([52.0, 102.0, 77.0])
        low = pd.Series([48.0, 98.0, 73.0])
        result = ETFScanner._calculate_52w_distances(close, high, low)
        assert result["dist_from_52w_high"] is not None
        assert result["dist_from_52w_low"] is not None
        assert result["dist_from_52w_high"] > 0
        assert result["dist_from_52w_low"] > 0


# ---------------------------------------------------------------------------
# TestNormalizeSymbol
# ---------------------------------------------------------------------------
class TestNormalizeSymbol:
    """Tests for symbol normalization (dash to dot)."""

    def test_dash_to_dot(self):
        assert ETFScanner._normalize_symbol_for_fmp("BRK-B") == "BRK.B"

    def test_normal_symbol_unchanged(self):
        assert ETFScanner._normalize_symbol_for_fmp("AAPL") == "AAPL"

    def test_already_dot_unchanged(self):
        assert ETFScanner._normalize_symbol_for_fmp("BRK.B") == "BRK.B"


# ---------------------------------------------------------------------------
# TestFMPEndpointFallback
# ---------------------------------------------------------------------------
class TestFMPEndpointFallback:
    """Tests for _fmp_request stable -> v3 fallback."""

    def _make_scanner(self):
        return ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)  # pragma: allowlist secret

    @patch("etf_scanner._requests_lib")
    def test_stable_success_uses_stable_url_format(self, mock_requests):
        """Stable endpoint uses ?symbol= query param format."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"symbol": "AAPL", "pe": 30}]
        mock_requests.get.return_value = mock_resp

        result = scanner._fmp_request("quote", "AAPL,MSFT")
        assert result is not None

        # Verify stable URL was called (base URL without symbols in path)
        called_url = mock_requests.get.call_args[0][0]
        assert "stable/quote" in called_url
        assert "AAPL,MSFT" not in called_url  # symbols in params, not path
        called_params = mock_requests.get.call_args[1]["params"]
        assert called_params["symbol"] == "AAPL,MSFT"

    @patch("etf_scanner._requests_lib")
    def test_stable_fails_falls_back_to_v3_path_format(self, mock_requests):
        """When stable fails, v3 endpoint uses /SYMBOLS path format."""
        scanner = self._make_scanner()

        # First call (stable) fails
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        # Second call (v3) succeeds
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = [{"symbol": "AAPL"}]
        mock_requests.get.side_effect = [fail_resp, ok_resp]

        result = scanner._fmp_request("quote", "AAPL,MSFT")
        assert result is not None

        # Verify v3 call uses path-based symbols
        v3_call = mock_requests.get.call_args_list[1]
        called_url = v3_call[0][0]
        assert "/api/v3/quote/AAPL,MSFT" in called_url
        # Symbols should NOT be in params for v3
        assert "symbol" not in v3_call[1]["params"]

    @patch("etf_scanner._requests_lib")
    def test_both_fail_returns_none(self, mock_requests):
        """When both stable and v3 fail, returns None."""
        scanner = self._make_scanner()
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        mock_requests.get.return_value = fail_resp

        result = scanner._fmp_request("quote", "AAPL")
        assert result is None
        assert scanner.backend_stats()["fmp_failures"] == 2

    @patch("etf_scanner.HAS_REQUESTS", False)
    def test_no_requests_library_returns_none(self):
        scanner = self._make_scanner()
        assert scanner._fmp_request("quote", "AAPL") is None

    def test_missing_api_key_returns_none(self):
        scanner = ETFScanner(rate_limit_sec=0)
        assert scanner._fmp_request("quote", "AAPL") is None

    @patch("etf_scanner._requests_lib")
    def test_disabled_stable_endpoint_is_skipped(self, mock_requests):
        scanner = self._make_scanner()
        stable_url = "https://financialmodelingprep.com/stable/quote"
        scanner._disabled_endpoints.add(stable_url)
        ok_resp = MagicMock(status_code=200)
        ok_resp.json.return_value = [{"symbol": "AAPL"}]
        mock_requests.get.return_value = ok_resp

        result = scanner._fmp_request("quote", "AAPL")

        assert result == [{"symbol": "AAPL"}]
        assert "/api/v3/quote/AAPL" in mock_requests.get.call_args.args[0]

    @patch("etf_scanner._requests_lib")
    def test_endpoint_disabled_after_consecutive_failures(self, mock_requests):
        scanner = self._make_scanner()
        fail_resp = MagicMock(status_code=500)
        mock_requests.get.return_value = fail_resp

        for _ in range(scanner._ENDPOINT_FAILURE_THRESHOLD):
            scanner._fmp_request("quote", "AAPL")

        assert "https://financialmodelingprep.com/stable/quote" in scanner._disabled_endpoints

    def test_rate_limit_sleeps_for_remaining_interval(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0.5)
        scanner._last_request_time = 100.0
        with (
            patch("etf_scanner.time.time", side_effect=[100.2, 100.5]),
            patch("etf_scanner.time.sleep") as sleep_mock,
        ):
            scanner._fmp_rate_limit()
        assert sleep_mock.call_args.args[0] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# TestFMPQuoteFetch
# ---------------------------------------------------------------------------
class TestFMPQuoteFetch:
    """Tests for _fetch_fmp_quotes."""

    def _make_scanner(self):
        return ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)  # pragma: allowlist secret

    @patch("etf_scanner._requests_lib")
    def test_batch_returns_mapped_dict(self, mock_requests):
        """Quote fetch returns {symbol: quote_dict} mapping."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150},
            {"symbol": "MSFT", "pe": 35, "price": 400},
        ]
        mock_requests.get.return_value = mock_resp

        result = scanner._fetch_fmp_quotes(["AAPL", "MSFT"])
        assert "AAPL" in result
        assert "MSFT" in result
        assert result["AAPL"]["pe"] == 30

    @patch("etf_scanner._requests_lib")
    def test_splits_large_batch_by_quote_batch_size(self, mock_requests):
        """Symbols exceeding FMP_QUOTE_BATCH_SIZE are split into batches."""
        scanner = self._make_scanner()
        scanner.FMP_QUOTE_BATCH_SIZE = 3  # small batch for testing

        symbols = ["A", "B", "C", "D", "E"]
        # Return non-empty data so stable succeeds (no v3 fallback)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"symbol": "X"}]
        mock_requests.get.return_value = mock_resp

        scanner._fetch_fmp_quotes(symbols)
        # 5 symbols / batch_size 3 = 2 batches, stable succeeds = 2 API calls
        assert mock_requests.get.call_count == 2

    @patch("etf_scanner._requests_lib")
    def test_cache_uses_normalized_key(self, mock_requests):
        """BRK-B is cached as BRK.B (normalized)."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"symbol": "BRK.B", "pe": 10, "price": 400},
        ]
        mock_requests.get.return_value = mock_resp

        result = scanner._fetch_fmp_quotes(["BRK-B"])
        # Cached under normalized key
        assert "BRK.B" in scanner._fmp_quote_cache
        # But result maps back to original symbol
        assert "BRK-B" in result

    @patch("etf_scanner._requests_lib")
    def test_cache_hit_prevents_duplicate_call(self, mock_requests):
        """Second call for same symbol uses cache, no API call."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30},
        ]
        mock_requests.get.return_value = mock_resp

        scanner._fetch_fmp_quotes(["AAPL"])
        call_count_1 = mock_requests.get.call_count

        scanner._fetch_fmp_quotes(["AAPL"])
        call_count_2 = mock_requests.get.call_count

        # No additional API call for cached symbol
        assert call_count_2 == call_count_1

    @patch("etf_scanner._requests_lib")
    def test_api_error_returns_empty(self, mock_requests):
        """API error returns empty dict."""
        scanner = self._make_scanner()
        mock_requests.get.side_effect = Exception("Connection error")

        result = scanner._fetch_fmp_quotes(["AAPL"])
        assert result == {}

    @patch("etf_scanner._requests_lib")
    def test_original_symbol_retry_normalizes_cache_key(self, mock_requests):
        """When retry returns BRK-B, it is cached under normalized BRK.B."""
        scanner = self._make_scanner()

        # Batch call with normalized BRK.B: stable fails, v3 fails
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        # Retry with original BRK-B: stable returns data with BRK-B symbol
        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.json.return_value = [{"symbol": "BRK-B", "pe": 10}]
        mock_requests.get.side_effect = [fail_resp, fail_resp, retry_resp]

        result = scanner._fetch_fmp_quotes(["BRK-B"])
        # Cache key is normalized to BRK.B despite API returning BRK-B
        assert "BRK.B" in scanner._fmp_quote_cache
        # Result maps back to original symbol
        assert "BRK-B" in result
        assert result["BRK-B"]["pe"] == 10


# ---------------------------------------------------------------------------
# TestFMPHistoricalFetch
# ---------------------------------------------------------------------------
class TestFMPHistoricalFetch:
    """Tests for _fetch_fmp_historical."""

    def _make_scanner(self):
        return ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)  # pragma: allowlist secret

    @patch("etf_scanner._requests_lib")
    def test_multi_symbol_parses_historicalStockList(self, mock_requests):
        """Multi-symbol response uses historicalStockList format."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "historicalStockList": [
                {
                    "symbol": "AAPL",
                    "historical": [
                        {"date": "2026-02-14", "close": 150},
                        {"date": "2026-02-13", "close": 148},
                    ],
                },
                {
                    "symbol": "MSFT",
                    "historical": [
                        {"date": "2026-02-14", "close": 400},
                    ],
                },
            ]
        }
        mock_requests.get.return_value = mock_resp

        result = scanner._fetch_fmp_historical(["AAPL", "MSFT"], timeseries=20)
        assert "AAPL" in result
        assert "MSFT" in result
        assert len(result["AAPL"]) == 2

    @patch("etf_scanner._requests_lib")
    def test_single_symbol_parses_historical(self, mock_requests):
        """Single-symbol response uses {symbol, historical} format."""
        scanner = self._make_scanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "symbol": "AAPL",
            "historical": [
                {"date": "2026-02-14", "close": 150},
            ],
        }
        mock_requests.get.return_value = mock_resp

        result = scanner._fetch_fmp_historical(["AAPL"], timeseries=20)
        assert "AAPL" in result

    @patch("etf_scanner._requests_lib")
    def test_batches_in_groups_of_5(self, mock_requests):
        """Historical fetch batches symbols in groups of FMP_HIST_BATCH_SIZE."""
        scanner = self._make_scanner()
        scanner.FMP_HIST_BATCH_SIZE = 2  # small batch for testing

        # Each batch returns empty but valid response
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"historicalStockList": []}
        mock_requests.get.return_value = mock_resp

        scanner._fetch_fmp_historical(["A", "B", "C", "D", "E"], timeseries=20)
        # 5 symbols / batch_size 2 = 3 batch calls
        # No per-symbol retry since all symbols missing -> 5 more calls
        # But with empty data, all symbols are missing -> retry each
        assert mock_requests.get.call_count == 3 + 5

    @patch("etf_scanner._requests_lib")
    def test_batch_incomplete_retries_missing_per_symbol(self, mock_requests):
        """Missing symbols from batch get retried individually."""
        scanner = self._make_scanner()

        # First batch call returns only AAPL (MSFT missing)
        batch_resp = MagicMock()
        batch_resp.status_code = 200
        batch_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": 150}]},
            ]
        }
        # Per-symbol retry for MSFT succeeds
        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.json.return_value = {
            "symbol": "MSFT",
            "historical": [{"close": 400}],
        }
        mock_requests.get.side_effect = [batch_resp, retry_resp]

        result = scanner._fetch_fmp_historical(["AAPL", "MSFT"], timeseries=20)
        assert "AAPL" in result
        assert "MSFT" in result

    @patch("etf_scanner._requests_lib")
    def test_api_error_returns_empty(self, mock_requests):
        """Total failure returns empty dict."""
        scanner = self._make_scanner()
        mock_requests.get.side_effect = Exception("Timeout")

        result = scanner._fetch_fmp_historical(["AAPL"], timeseries=20)
        assert result == {}

    @patch("etf_scanner._requests_lib")
    def test_original_symbol_retry_normalizes_result_key(self, mock_requests):
        """When retry returns BRK-B, result key is normalized to BRK.B."""
        scanner = self._make_scanner()

        # Batch with normalized BRK.B: stable+v3 both fail
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        # Per-symbol retry with normalized BRK.B: fails
        # Per-symbol retry with original BRK-B: returns data
        retry_resp = MagicMock()
        retry_resp.status_code = 200
        retry_resp.json.return_value = {
            "symbol": "BRK-B",
            "historical": [{"close": 400}],
        }
        mock_requests.get.side_effect = [
            fail_resp,
            fail_resp,  # batch stable+v3
            fail_resp,
            fail_resp,  # per-symbol BRK.B stable+v3
            retry_resp,  # per-symbol BRK-B stable succeeds
        ]

        result = scanner._fetch_fmp_historical(["BRK-B"], timeseries=20)
        # Result maps to original symbol despite API returning BRK-B
        assert "BRK-B" in result
        assert result["BRK-B"][0]["close"] == 400


# ---------------------------------------------------------------------------
# TestBatchStockMetricsFMP
# ---------------------------------------------------------------------------
class TestBatchStockMetricsFMP:
    """Tests for FMP-based batch_stock_metrics internal path."""

    def _make_scanner(self):
        return ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)  # pragma: allowlist secret

    @patch("etf_scanner._requests_lib")
    def test_pe_from_quote(self, mock_requests):
        """PE ratio is extracted from FMP quote data."""
        scanner = self._make_scanner()

        # Quote response
        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30.5, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        # Historical response for RSI
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": 150 - i * 0.5} for i in range(20)]},
            ]
        }
        mock_requests.get.side_effect = [quote_resp, hist_resp]

        results = scanner._batch_stock_metrics_fmp(["AAPL"])
        assert len(results) == 1
        assert results[0]["pe_ratio"] == 30.5

    @patch("etf_scanner._requests_lib")
    def test_52w_distances_from_quote(self, mock_requests):
        """52-week distances come from yearHigh/yearLow in quote."""
        scanner = self._make_scanner()

        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 200, "yearLow": 100},
        ]
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {"historicalStockList": []}
        mock_requests.get.side_effect = [quote_resp, hist_resp]

        results = scanner._batch_stock_metrics_fmp(["AAPL"])
        assert results[0]["dist_from_52w_high"] == round((200 - 150) / 200, 4)
        assert results[0]["dist_from_52w_low"] == round((150 - 100) / 150, 4)

    @patch("etf_scanner._requests_lib")
    def test_rsi_from_historical_close(self, mock_requests):
        """RSI is calculated from historical close prices."""
        scanner = self._make_scanner()

        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        # FMP returns newest-first; code reverses to oldest-first for RSI.
        # Decreasing close here -> reversed = increasing -> RSI=100
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": float(150 - i)} for i in range(20)]},
            ]
        }
        mock_requests.get.side_effect = [quote_resp, hist_resp]

        results = scanner._batch_stock_metrics_fmp(["AAPL"])
        # After reversal: monotonic increase -> RSI = 100
        assert results[0]["rsi_14"] is not None
        assert results[0]["rsi_14"] == 100.0

    @patch("etf_scanner._requests_lib")
    def test_missing_fields_return_none(self, mock_requests):
        """Missing quote fields produce None for those metrics."""
        scanner = self._make_scanner()

        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL"},  # No pe, price, yearHigh, yearLow
        ]
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {"historicalStockList": []}
        mock_requests.get.side_effect = [quote_resp, hist_resp]

        results = scanner._batch_stock_metrics_fmp(["AAPL"])
        assert results[0]["pe_ratio"] is None
        assert results[0]["dist_from_52w_high"] is None
        assert results[0]["rsi_14"] is None

    def test_empty_symbols_returns_empty(self):
        """Empty input returns empty list."""
        scanner = self._make_scanner()
        results = scanner.batch_stock_metrics([])
        assert results == []


# ---------------------------------------------------------------------------
# TestETFVolumeRatioFMP
# ---------------------------------------------------------------------------
class TestETFVolumeRatioFMP:
    """Tests for FMP-based ETF volume ratio calculation."""

    def _make_scanner(self):
        return ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)  # pragma: allowlist secret

    @patch("etf_scanner._requests_lib")
    def test_20d_60d_from_historical(self, mock_requests):
        """Volume ratio is calculated from 20d/60d averages."""
        scanner = self._make_scanner()

        # 60 days of volume data
        hist_data = [
            {
                "date": f"2026-02-{14 - i:02d}" if i < 14 else f"2026-01-{31 - (i - 14):02d}",
                "volume": 1_000_000 + i * 10_000,
            }
            for i in range(60)
        ]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "XLK", "historical": hist_data},
            ]
        }
        mock_requests.get.return_value = mock_resp

        result = scanner._batch_etf_volume_ratios_fmp(["XLK"])
        assert "XLK" in result
        assert result["XLK"]["vol_20d"] is not None
        assert result["XLK"]["vol_60d"] is not None
        assert result["XLK"]["vol_ratio"] is not None

    @patch("etf_scanner._requests_lib")
    def test_insufficient_data_returns_none(self, mock_requests):
        """Fewer than 20 data points returns None values."""
        scanner = self._make_scanner()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "historicalStockList": [
                {
                    "symbol": "XLK",
                    "historical": [
                        {"date": "2026-02-14", "volume": 1000000},
                    ],
                },
            ]
        }
        mock_requests.get.return_value = mock_resp

        result = scanner._batch_etf_volume_ratios_fmp(["XLK"])
        assert result["XLK"]["vol_20d"] is None


# ---------------------------------------------------------------------------
# TestBatchETFVolumeRatios
# ---------------------------------------------------------------------------
class TestBatchETFVolumeRatios:
    """Tests for the public batch_etf_volume_ratios method."""

    def test_get_etf_volume_ratio_returns_fmp_result_when_available(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)
        fmp_result = {
            "XLK": {"symbol": "XLK", "vol_20d": 100.0, "vol_60d": 80.0, "vol_ratio": 1.25}
        }

        with (
            patch.object(scanner, "_batch_etf_volume_ratios_fmp", return_value=fmp_result),
            patch.object(scanner, "_get_etf_volume_ratio_yfinance") as yf_mock,
        ):
            result = scanner.get_etf_volume_ratio("XLK")

        assert result["vol_ratio"] == 1.25
        yf_mock.assert_not_called()

    def test_get_etf_volume_ratio_falls_back_when_fmp_missing(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)
        yf_result = {"symbol": "XLK", "vol_20d": None, "vol_60d": None, "vol_ratio": None}

        with (
            patch.object(scanner, "_batch_etf_volume_ratios_fmp", return_value={"XLK": {}}),
            patch.object(
                scanner, "_get_etf_volume_ratio_yfinance", return_value=yf_result
            ) as yf_mock,
        ):
            result = scanner.get_etf_volume_ratio("XLK")

        assert result is yf_result
        yf_mock.assert_called_once_with("XLK")

    @patch("etf_scanner._requests_lib")
    def test_batch_returns_all_etfs(self, mock_requests):
        """Batch fetches volume ratios for multiple ETFs."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        hist_data = [{"volume": 1_000_000} for _ in range(60)]
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "XLK", "historical": hist_data},
                {"symbol": "SMH", "historical": hist_data},
            ]
        }
        mock_requests.get.return_value = mock_resp

        result = scanner.batch_etf_volume_ratios(["XLK", "SMH"])
        assert "XLK" in result
        assert "SMH" in result

    def test_empty_symbols_returns_empty_dict(self):
        assert ETFScanner().batch_etf_volume_ratios([]) == {}

    @patch("etf_scanner.HAS_YFINANCE", False)
    def test_yfinance_unavailable_etf_volume_ratio_returns_empty_shape(self):
        scanner = ETFScanner()
        result = scanner._get_etf_volume_ratio_yfinance("XLK")
        assert result == {"symbol": "XLK", "vol_20d": None, "vol_60d": None, "vol_ratio": None}

    @patch("etf_scanner.HAS_YFINANCE", True)
    def test_yfinance_etf_volume_ratio_handles_missing_or_short_data(self):
        scanner = ETFScanner()
        missing = pd.DataFrame({"Close": [1.0, 2.0]})
        short = pd.DataFrame({"Volume": [1_000_000] * 10})

        with patch.object(scanner, "_get_cached", side_effect=[missing, short]):
            assert scanner._get_etf_volume_ratio_yfinance("NO_VOLUME")["vol_ratio"] is None
            assert scanner._get_etf_volume_ratio_yfinance("SHORT")["vol_ratio"] is None

    @patch("etf_scanner.HAS_YFINANCE", True)
    def test_yfinance_etf_volume_ratio_computes_and_handles_exceptions(self):
        scanner = ETFScanner()
        data = pd.DataFrame({"Volume": [1_000_000 + i for i in range(60)]})
        with patch.object(scanner, "_get_cached", return_value=data):
            result = scanner._get_etf_volume_ratio_yfinance("XLK")
        assert result["vol_20d"] is not None
        assert result["vol_ratio"] is not None

        with patch.object(scanner, "_get_cached", side_effect=Exception("boom")):
            assert scanner._get_etf_volume_ratio_yfinance("ERR")["vol_ratio"] is None

    @patch("etf_scanner.HAS_YFINANCE", True)
    def test_batch_etf_volume_ratios_falls_back_to_yfinance_for_missing(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)
        fmp_ok = {"XLK": {"symbol": "XLK", "vol_20d": 100.0, "vol_60d": 80.0, "vol_ratio": 1.25}}
        yf_data = {"symbol": "SMH", "vol_20d": 50.0, "vol_60d": 50.0, "vol_ratio": 1.0}

        with (
            patch.object(scanner, "_batch_etf_volume_ratios_fmp", return_value=fmp_ok),
            patch.object(scanner, "_get_etf_volume_ratio_yfinance", return_value=yf_data),
        ):
            result = scanner.batch_etf_volume_ratios(["XLK", "SMH"])

        assert result["XLK"]["vol_ratio"] == 1.25
        assert result["SMH"]["vol_ratio"] == 1.0
        assert scanner.backend_stats()["etf"]["yf_fallbacks"] == 1
        assert scanner.backend_stats()["etf"]["yf_calls"] == 1


# ---------------------------------------------------------------------------
# TestSymbolLevelFallback
# ---------------------------------------------------------------------------
class TestSymbolLevelFallback:
    """Tests for symbol-level FMP -> yfinance fallback."""

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner._requests_lib")
    @patch("etf_scanner.yf")
    def test_partial_fmp_success_fills_missing_from_yfinance(self, mock_yf, mock_requests):
        """Partial FMP success -> missing symbols fall back to yfinance."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        # FMP: only AAPL succeeds
        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        # Historical with enough data for RSI (newest-first from FMP)
        hist_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": float(150 - i)} for i in range(20)]},
            ]
        }
        mock_requests.get.side_effect = [
            quote_resp,
            hist_resp,
            # Per-symbol retry for MSFT (fails)
            MagicMock(status_code=500),
            MagicMock(status_code=500),
        ]

        # yfinance fallback: download for MSFT
        mock_df = pd.DataFrame(
            {
                "Close": np.linspace(300, 400, 20),
                "High": np.linspace(305, 405, 20),
                "Low": np.linspace(295, 395, 20),
                "Volume": [1_000_000] * 20,
            }
        )
        mock_yf.download.return_value = mock_df
        mock_ticker = MagicMock()
        mock_ticker.info = {"trailingPE": 35.0}
        mock_yf.Ticker.return_value = mock_ticker

        results = scanner.batch_stock_metrics(["AAPL", "MSFT"])
        assert len(results) == 2
        # AAPL from FMP
        aapl = [r for r in results if r["symbol"] == "AAPL"][0]
        assert aapl["pe_ratio"] == 30
        # MSFT from yfinance fallback
        msft = [r for r in results if r["symbol"] == "MSFT"][0]
        assert msft["pe_ratio"] == 35.0
        # Stats show fallback occurred
        assert scanner.backend_stats()["yf_fallbacks"] >= 1

    @patch("etf_scanner._requests_lib")
    def test_all_fmp_success_no_yfinance_calls(self, mock_requests):
        """When FMP succeeds for all symbols, yfinance is not called."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": float(150 - i)} for i in range(20)]},
            ]
        }
        mock_requests.get.side_effect = [quote_resp, hist_resp]

        with patch("etf_scanner.yf") as mock_yf:
            scanner.batch_stock_metrics(["AAPL"])
            mock_yf.download.assert_not_called()

        assert scanner.backend_stats()["yf_calls"] == 0

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner.HAS_REQUESTS", False)
    @patch("etf_scanner.yf")
    def test_all_fmp_fail_falls_back_entirely(self, mock_yf):
        """Without requests library, falls back entirely to yfinance."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        mock_df = pd.DataFrame(
            {
                "Close": np.linspace(100, 150, 20),
                "High": np.linspace(105, 155, 20),
                "Low": np.linspace(95, 145, 20),
                "Volume": [1_000_000] * 20,
            }
        )
        mock_yf.download.return_value = mock_df
        mock_ticker = MagicMock()
        mock_ticker.info = {"trailingPE": 25.0}
        mock_yf.Ticker.return_value = mock_ticker

        results = scanner.batch_stock_metrics(["AAPL"])
        assert len(results) == 1
        assert scanner.backend_stats()["yf_calls"] == 1

    @patch("etf_scanner.HAS_YFINANCE", False)
    def test_yfinance_unavailable_stock_metrics_returns_empty_shapes(self):
        scanner = ETFScanner()
        result = scanner._batch_stock_metrics_yfinance(["AAPL", "MSFT"])
        assert [row["symbol"] for row in result] == ["AAPL", "MSFT"]
        assert all(row["rsi_14"] is None for row in result)

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner.yf")
    def test_yfinance_batch_download_exception_returns_empty_shapes(self, mock_yf):
        scanner = ETFScanner()
        mock_yf.download.side_effect = Exception("download failed")
        result = scanner._batch_stock_metrics_yfinance(["AAPL"])
        assert result == [
            {
                "symbol": "AAPL",
                "rsi_14": None,
                "dist_from_52w_high": None,
                "dist_from_52w_low": None,
                "pe_ratio": None,
            }
        ]

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner.yf")
    def test_yfinance_multi_symbol_handles_empty_short_and_exception_paths(self, mock_yf):
        scanner = ETFScanner()
        frames = {
            "EMPTY": pd.DataFrame(),
            "SHORT": pd.DataFrame({"Close": [1.0], "High": [1.0], "Low": [1.0]}),
            "ERR": pd.DataFrame({"Open": [1.0, 2.0]}),
        }
        mock_yf.download.return_value = frames

        result = scanner._batch_stock_metrics_yfinance(["EMPTY", "SHORT", "ERR"])

        assert [row["symbol"] for row in result] == ["EMPTY", "SHORT", "ERR"]
        assert all(row["rsi_14"] is None for row in result)

    def test_batch_stock_metrics_merges_yfinance_fields_into_partial_fmp_result(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)
        fmp_result = [
            {
                "symbol": "AAPL",
                "rsi_14": None,
                "dist_from_52w_high": 0.1,
                "dist_from_52w_low": None,
                "pe_ratio": 30.0,
            }
        ]
        yf_result = [
            {
                "symbol": "AAPL",
                "rsi_14": 55.0,
                "dist_from_52w_high": 0.2,
                "dist_from_52w_low": 0.4,
                "pe_ratio": 99.0,
            }
        ]

        with (
            patch.object(scanner, "_batch_stock_metrics_fmp", return_value=fmp_result),
            patch.object(scanner, "_batch_stock_metrics_yfinance", return_value=yf_result),
        ):
            result = scanner.batch_stock_metrics(["AAPL"])

        assert result[0]["rsi_14"] == 55.0
        assert result[0]["dist_from_52w_high"] == 0.1
        assert result[0]["dist_from_52w_low"] == 0.4
        assert result[0]["pe_ratio"] == 30.0

    def test_batch_stock_metrics_returns_empty_shape_when_all_backends_missing(self):
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)
        with (
            patch.object(scanner, "_batch_stock_metrics_fmp", return_value=[]),
            patch.object(scanner, "_batch_stock_metrics_yfinance", return_value=[]),
        ):
            result = scanner.batch_stock_metrics(["AAPL"])

        assert result == [
            {
                "symbol": "AAPL",
                "rsi_14": None,
                "dist_from_52w_high": None,
                "dist_from_52w_low": None,
                "pe_ratio": None,
            }
        ]


class TestSharedUtilityFallbacks:
    def test_calculate_52w_distances_handles_empty_and_non_positive_close(self):
        assert ETFScanner._calculate_52w_distances(
            pd.Series([], dtype=float), pd.Series([], dtype=float), pd.Series([], dtype=float)
        ) == {
            "dist_from_52w_high": None,
            "dist_from_52w_low": None,
        }
        assert ETFScanner._calculate_52w_distances(
            pd.Series([0.0]),
            pd.Series([10.0]),
            pd.Series([0.0]),
        ) == {"dist_from_52w_high": None, "dist_from_52w_low": None}

    @patch("etf_scanner.yf")
    def test_get_pe_ratio_handles_missing_and_exception(self, mock_yf):
        scanner = ETFScanner()
        ticker = MagicMock()
        ticker.info = {}
        mock_yf.Ticker.return_value = ticker
        assert scanner._get_pe_ratio("AAPL") is None

        mock_yf.Ticker.side_effect = Exception("ticker failed")
        assert scanner._get_pe_ratio("MSFT") is None

    @patch("etf_scanner.yf")
    def test_get_cached_uses_cache_and_handles_download_failure(self, mock_yf):
        scanner = ETFScanner()
        data = pd.DataFrame({"Close": [1.0, 2.0]})
        mock_yf.download.return_value = data

        first = scanner._get_cached("AAPL", period="1mo")
        second = scanner._get_cached("AAPL", period="1mo")

        assert first is data
        assert second is data
        assert mock_yf.download.call_count == 1

        mock_yf.download.side_effect = Exception("download failed")
        assert scanner._get_cached("MSFT", period="1mo") is None


# ---------------------------------------------------------------------------
# TestBackendStats
# ---------------------------------------------------------------------------
class TestBackendStats:
    """Tests for backend_stats() tracking."""

    def test_initial_stats_all_zero(self):
        scanner = ETFScanner(fmp_api_key="test_key")
        stats = scanner.backend_stats()
        assert stats["fmp_calls"] == 0
        assert stats["fmp_failures"] == 0
        assert stats["yf_calls"] == 0
        assert stats["yf_fallbacks"] == 0

    @patch("etf_scanner._requests_lib")
    def test_stats_after_fmp_success(self, mock_requests):
        """FMP calls are counted after successful requests."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        mock_requests.get.return_value = mock_resp

        scanner._fmp_request("quote", "AAPL")
        stats = scanner.backend_stats()
        assert stats["fmp_calls"] == 1
        assert stats["fmp_failures"] == 0

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner._requests_lib")
    @patch("etf_scanner.yf")
    def test_stats_after_yfinance_fallback(self, mock_yf, mock_requests):
        """yf_calls and yf_fallbacks are counted after fallback."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        # FMP fails for everything
        fail_resp = MagicMock()
        fail_resp.status_code = 500
        mock_requests.get.return_value = fail_resp

        # yfinance works
        mock_df = pd.DataFrame(
            {
                "Close": np.linspace(100, 150, 20),
                "High": np.linspace(105, 155, 20),
                "Low": np.linspace(95, 145, 20),
                "Volume": [1_000_000] * 20,
            }
        )
        mock_yf.download.return_value = mock_df
        mock_ticker = MagicMock()
        mock_ticker.info = {"trailingPE": 25.0}
        mock_yf.Ticker.return_value = mock_ticker

        scanner.batch_stock_metrics(["AAPL"])
        stats = scanner.backend_stats()
        assert stats["yf_calls"] == 1
        assert stats["yf_fallbacks"] == 1  # FMP attempted but failed entirely
        assert stats["fmp_failures"] > 0

    @patch("etf_scanner.HAS_YFINANCE", True)
    @patch("etf_scanner._requests_lib")
    @patch("etf_scanner.yf")
    def test_yf_calls_and_yf_fallbacks_increment(self, mock_yf, mock_requests):
        """yf_fallbacks increments when partial FMP data triggers fallback."""
        scanner = ETFScanner(fmp_api_key="test_key", rate_limit_sec=0)

        # FMP: AAPL succeeds, MSFT missing
        quote_resp = MagicMock()
        quote_resp.status_code = 200
        quote_resp.json.return_value = [
            {"symbol": "AAPL", "pe": 30, "price": 150, "yearHigh": 180, "yearLow": 120},
        ]
        hist_resp = MagicMock()
        hist_resp.status_code = 200
        hist_resp.json.return_value = {
            "historicalStockList": [
                {"symbol": "AAPL", "historical": [{"close": float(150 - i)} for i in range(20)]},
            ]
        }
        mock_requests.get.side_effect = [
            quote_resp,
            hist_resp,
            # Per-symbol retry for MSFT fails
            MagicMock(status_code=500),
            MagicMock(status_code=500),
        ]

        mock_df = pd.DataFrame(
            {
                "Close": np.linspace(300, 400, 20),
                "High": np.linspace(305, 405, 20),
                "Low": np.linspace(295, 395, 20),
                "Volume": [1_000_000] * 20,
            }
        )
        mock_yf.download.return_value = mock_df
        mock_ticker = MagicMock()
        mock_ticker.info = {"trailingPE": 35.0}
        mock_yf.Ticker.return_value = mock_ticker

        scanner.batch_stock_metrics(["AAPL", "MSFT"])
        stats = scanner.backend_stats()
        assert stats["yf_fallbacks"] == 1
        assert stats["yf_calls"] == 1
