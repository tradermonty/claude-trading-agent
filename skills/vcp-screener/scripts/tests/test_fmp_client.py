from __future__ import annotations

from unittest.mock import MagicMock

import fmp_client
import pytest
from fmp_client import FMPClient

DUMMY_API_KEY = "dummy-key"  # pragma: allowlist secret
ENV_DUMMY_API_KEY = "env-dummy-key"  # pragma: allowlist secret


@pytest.fixture
def mock_session(monkeypatch):
    session = MagicMock()
    session.headers = {}
    session_cls = MagicMock(return_value=session)
    monkeypatch.setattr(fmp_client.requests, "Session", session_cls)
    return session


def _response(status_code: int, payload=None, text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    response.text = text
    response.json.return_value = payload
    return response


class TestFMPClientInit:
    def test_requires_api_key(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)

        with pytest.raises(ValueError, match="FMP API key required"):
            FMPClient()

    def test_uses_explicit_api_key_and_sets_header(self, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client.api_key == DUMMY_API_KEY
        assert mock_session.headers["apikey"] == DUMMY_API_KEY

    def test_uses_environment_api_key(self, monkeypatch, mock_session):
        monkeypatch.setenv("FMP_API_KEY", ENV_DUMMY_API_KEY)

        client = FMPClient()

        assert client.api_key == ENV_DUMMY_API_KEY
        assert mock_session.headers["apikey"] == ENV_DUMMY_API_KEY


class TestRateLimitedGet:
    def test_success_returns_json_and_tracks_api_call(self, monkeypatch, mock_session):
        monkeypatch.setattr(fmp_client.time, "time", MagicMock(side_effect=[100.0, 100.1]))
        mock_session.get.return_value = _response(200, payload=[{"symbol": "AAPL"}])
        client = FMPClient(api_key=DUMMY_API_KEY)

        result = client._rate_limited_get("https://example.test/quote", {"symbol": "AAPL"})

        assert result == [{"symbol": "AAPL"}]
        assert client.api_calls_made == 1
        assert client.retry_count == 0
        mock_session.get.assert_called_once_with(
            "https://example.test/quote",
            params={"symbol": "AAPL"},
            timeout=30,
        )

    def test_enforces_short_interval_rate_limit(self, monkeypatch, mock_session):
        monkeypatch.setattr(fmp_client.time, "time", MagicMock(side_effect=[100.1, 100.2]))
        sleep = MagicMock()
        monkeypatch.setattr(fmp_client.time, "sleep", sleep)
        mock_session.get.return_value = _response(200, payload={"ok": True})
        client = FMPClient(api_key=DUMMY_API_KEY)
        client.last_call_time = 100.0

        assert client._rate_limited_get("https://example.test/data") == {"ok": True}

        assert sleep.call_count == 1
        assert sleep.call_args.args[0] == pytest.approx(0.2)

    def test_rate_limit_retry_then_success(self, monkeypatch, mock_session):
        monkeypatch.setattr(
            fmp_client.time, "time", MagicMock(side_effect=[100.0, 100.1, 200.0, 200.1])
        )
        sleep = MagicMock()
        monkeypatch.setattr(fmp_client.time, "sleep", sleep)
        mock_session.get.side_effect = [
            _response(429, text="too many requests"),
            _response(200, payload={"ok": True}),
        ]
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") == {"ok": True}
        assert client.api_calls_made == 2
        assert client.retry_count == 0
        sleep.assert_called_once_with(60)

    def test_rate_limit_failure_stops_future_requests(self, monkeypatch, mock_session):
        monkeypatch.setattr(
            fmp_client.time, "time", MagicMock(side_effect=[100.0, 100.1, 200.0, 200.1])
        )
        monkeypatch.setattr(fmp_client.time, "sleep", MagicMock())
        mock_session.get.side_effect = [
            _response(429, text="too many requests"),
            _response(429, text="too many requests"),
        ]
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") is None
        assert client.rate_limit_reached is True
        assert client._rate_limited_get("https://example.test/data") is None
        assert mock_session.get.call_count == 2

    def test_non_200_non_429_returns_none(self, mock_session):
        mock_session.get.return_value = _response(500, text="server failed")
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") is None

    def test_request_exception_returns_none(self, mock_session):
        mock_session.get.side_effect = fmp_client.requests.exceptions.RequestException("boom")
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") is None


class TestEndpointHelpers:
    def test_sp500_constituents_are_cached(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get = MagicMock(return_value=[{"symbol": "AAPL"}])
        monkeypatch.setattr(client, "_rate_limited_get", get)

        assert client.get_sp500_constituents() == [{"symbol": "AAPL"}]
        assert client.get_sp500_constituents() == [{"symbol": "AAPL"}]
        get.assert_called_once_with(f"{client.BASE_URL}/sp500_constituent")

    def test_quote_and_historical_are_cached(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get = MagicMock(
            side_effect=[
                [{"symbol": "AAPL", "price": 100}],
                {"historical": [{"close": 99}]},
            ]
        )
        monkeypatch.setattr(client, "_rate_limited_get", get)

        assert client.get_quote("AAPL") == [{"symbol": "AAPL", "price": 100}]
        assert client.get_quote("AAPL") == [{"symbol": "AAPL", "price": 100}]
        assert client.get_historical_prices("AAPL", days=10) == {"historical": [{"close": 99}]}
        assert client.get_historical_prices("AAPL", days=10) == {"historical": [{"close": 99}]}
        assert get.call_count == 2

    def test_batch_quotes_maps_symbol_to_quote(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get_quote = MagicMock(
            side_effect=[
                [
                    {"symbol": "AAPL"},
                    {"symbol": "MSFT"},
                    {"symbol": "NVDA"},
                    {"symbol": "META"},
                    {"symbol": "GOOGL"},
                ],
                [{"symbol": "TSLA"}],
            ]
        )
        monkeypatch.setattr(client, "get_quote", get_quote)

        result = client.get_batch_quotes(["AAPL", "MSFT", "NVDA", "META", "GOOGL", "TSLA"])

        assert list(result) == ["AAPL", "MSFT", "NVDA", "META", "GOOGL", "TSLA"]
        assert get_quote.call_args_list[0].args == ("AAPL,MSFT,NVDA,META,GOOGL",)
        assert get_quote.call_args_list[1].args == ("TSLA",)

    def test_batch_historical_skips_empty_payloads(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get_prices = MagicMock(
            side_effect=[
                {"historical": [{"close": 100}]},
                {},
                None,
            ]
        )
        monkeypatch.setattr(client, "get_historical_prices", get_prices)

        result = client.get_batch_historical(["AAPL", "MSFT", "TSLA"], days=20)

        assert result == {"AAPL": [{"close": 100}]}

    def test_calculate_sma_uses_available_prices_when_shorter_than_period(self, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client.calculate_sma([10, 20], period=5) == 15
        assert client.calculate_sma([10, 20, 30], period=2) == 15

    def test_api_stats(self, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        client.cache["quote_AAPL"] = [{"symbol": "AAPL"}]
        client.api_calls_made = 3
        client.rate_limit_reached = True

        assert client.get_api_stats() == {
            "cache_entries": 1,
            "api_calls_made": 3,
            "rate_limit_reached": True,
        }
