from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "fmp_client.py"
SPEC = importlib.util.spec_from_file_location("macro_fmp_client", MODULE_PATH)
assert SPEC is not None
macro_fmp_client = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(macro_fmp_client)
FMPClient = macro_fmp_client.FMPClient

DUMMY_API_KEY = "dummy-key"  # pragma: allowlist secret
ENV_DUMMY_API_KEY = "env-dummy-key"  # pragma: allowlist secret


@pytest.fixture
def mock_session(monkeypatch):
    session = MagicMock()
    session.headers = {}
    session_cls = MagicMock(return_value=session)
    monkeypatch.setattr(macro_fmp_client.requests, "Session", session_cls)
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
        monkeypatch.setattr(macro_fmp_client.time, "time", MagicMock(side_effect=[100.0, 100.1]))
        mock_session.get.return_value = _response(200, payload={"historical": []})
        client = FMPClient(api_key=DUMMY_API_KEY)

        result = client._rate_limited_get("https://example.test/history", {"timeseries": 10})

        assert result == {"historical": []}
        assert client.api_calls_made == 1
        assert client.retry_count == 0
        mock_session.get.assert_called_once_with(
            "https://example.test/history",
            params={"timeseries": 10},
            timeout=30,
        )

    def test_enforces_short_interval_rate_limit(self, monkeypatch, mock_session):
        monkeypatch.setattr(macro_fmp_client.time, "time", MagicMock(side_effect=[100.1, 100.2]))
        sleep = MagicMock()
        monkeypatch.setattr(macro_fmp_client.time, "sleep", sleep)
        mock_session.get.return_value = _response(200, payload={"ok": True})
        client = FMPClient(api_key=DUMMY_API_KEY)
        client.last_call_time = 100.0

        assert client._rate_limited_get("https://example.test/data") == {"ok": True}

        assert sleep.call_count == 1
        assert sleep.call_args.args[0] == pytest.approx(0.2)

    def test_rate_limit_retry_then_success(self, monkeypatch, mock_session):
        monkeypatch.setattr(
            macro_fmp_client.time,
            "time",
            MagicMock(side_effect=[100.0, 100.1, 200.0, 200.1]),
        )
        sleep = MagicMock()
        monkeypatch.setattr(macro_fmp_client.time, "sleep", sleep)
        mock_session.get.side_effect = [
            _response(429, text="too many requests"),
            _response(200, payload=[{"date": "2026-05-09"}]),
        ]
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") == [{"date": "2026-05-09"}]
        assert client.api_calls_made == 2
        assert client.retry_count == 0
        sleep.assert_called_once_with(60)

    def test_rate_limit_failure_stops_future_requests(self, monkeypatch, mock_session):
        monkeypatch.setattr(
            macro_fmp_client.time,
            "time",
            MagicMock(side_effect=[100.0, 100.1, 200.0, 200.1]),
        )
        monkeypatch.setattr(macro_fmp_client.time, "sleep", MagicMock())
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
        mock_session.get.return_value = _response(503, text="unavailable")
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") is None

    def test_request_exception_returns_none(self, mock_session):
        mock_session.get.side_effect = macro_fmp_client.requests.exceptions.RequestException("boom")
        client = FMPClient(api_key=DUMMY_API_KEY)

        assert client._rate_limited_get("https://example.test/data") is None


class TestEndpointHelpers:
    def test_historical_prices_are_cached(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get = MagicMock(return_value={"historical": [{"close": 100}]})
        monkeypatch.setattr(client, "_rate_limited_get", get)

        assert client.get_historical_prices("SPY", days=20) == {"historical": [{"close": 100}]}
        assert client.get_historical_prices("SPY", days=20) == {"historical": [{"close": 100}]}
        get.assert_called_once_with(
            f"{client.BASE_URL}/historical-price-full/SPY",
            {"timeseries": 20},
        )

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

        result = client.get_batch_historical(["SPY", "TLT", "HYG"], days=30)

        assert result == {"SPY": [{"close": 100}]}
        assert get_prices.call_args_list[0].kwargs == {"days": 30}

    def test_treasury_rates_cache_only_valid_lists(self, monkeypatch, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        get = MagicMock(
            side_effect=[
                {"not": "a-list"},
                [{"date": "2026-05-09", "year10": 4.2}],
            ]
        )
        monkeypatch.setattr(client, "_rate_limited_get", get)

        assert client.get_treasury_rates(days=5) is None
        assert client.get_treasury_rates(days=5) == [{"date": "2026-05-09", "year10": 4.2}]
        assert client.get_treasury_rates(days=5) == [{"date": "2026-05-09", "year10": 4.2}]
        assert get.call_count == 2
        assert get.call_args_list[0].args == (
            f"{client.STABLE_URL}/treasury-rates",
            {"limit": 5},
        )

    def test_api_stats(self, mock_session):
        client = FMPClient(api_key=DUMMY_API_KEY)
        client.cache["treasury_5"] = [{"date": "2026-05-09"}]
        client.api_calls_made = 4
        client.rate_limit_reached = True

        assert client.get_api_stats() == {
            "cache_entries": 1,
            "api_calls_made": 4,
            "rate_limit_reached": True,
        }
