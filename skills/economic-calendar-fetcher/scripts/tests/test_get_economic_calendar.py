"""Tests for get_economic_calendar.py"""

import json
import os
import sys
import urllib.error
from datetime import datetime, timedelta

import pytest

# Add parent directory to path so we can import the script module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import get_economic_calendar as economic_calendar
from get_economic_calendar import (
    fetch_economic_calendar,
    format_event_output,
    get_api_key,
    validate_date_range,
)

DUMMY_API_KEY = "dummy-key"  # pragma: allowlist secret

# ---------------------------------------------------------------------------
# Sample fixtures
# ---------------------------------------------------------------------------

SAMPLE_EVENTS = [
    {
        "date": "2025-01-15 14:30:00",
        "country": "US",
        "event": "Consumer Price Index (CPI) YoY",
        "currency": "USD",
        "previous": 2.6,
        "estimate": 2.7,
        "actual": None,
        "change": None,
        "impact": "High",
        "changePercentage": None,
    },
    {
        "date": "2025-01-16 10:00:00",
        "country": "EU",
        "event": "ECB Interest Rate Decision",
        "currency": "EUR",
        "previous": 4.5,
        "estimate": 4.5,
        "actual": None,
        "change": None,
        "impact": "High",
        "changePercentage": None,
    },
]


# ---------------------------------------------------------------------------
# get_api_key tests
# ---------------------------------------------------------------------------


class TestGetApiKey:
    def test_returns_key_when_set(self, monkeypatch):
        monkeypatch.setenv("FMP_API_KEY", "test_key_123")
        assert get_api_key() == "test_key_123"

    def test_returns_none_when_not_set(self, monkeypatch):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        assert get_api_key() is None


# ---------------------------------------------------------------------------
# validate_date_range tests
# ---------------------------------------------------------------------------


class TestValidateDateRange:
    def test_valid_range(self):
        validate_date_range("2025-01-01", "2025-01-31")

    def test_same_day(self):
        validate_date_range("2025-06-15", "2025-06-15")

    def test_max_90_days(self):
        validate_date_range("2025-01-01", "2025-03-31")  # 89 days

    def test_exceeds_90_days(self):
        with pytest.raises(ValueError, match="exceeds maximum of 90 days"):
            validate_date_range("2025-01-01", "2025-06-01")

    def test_start_after_end(self):
        with pytest.raises(ValueError, match="after end date"):
            validate_date_range("2025-03-01", "2025-01-01")

    def test_invalid_date_format(self):
        with pytest.raises(ValueError, match="Invalid date format"):
            validate_date_range("01-01-2025", "2025-01-31")

    def test_invalid_date_value(self):
        with pytest.raises(ValueError, match="Invalid date format"):
            validate_date_range("2025-13-01", "2025-14-01")

    def test_past_dates_warns(self, capsys):
        past = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        past_end = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
        validate_date_range(past, past_end)
        captured = capsys.readouterr()
        assert "in the past" in captured.err


# ---------------------------------------------------------------------------
# format_event_output tests
# ---------------------------------------------------------------------------


class TestFormatEventOutput:
    def test_json_format_roundtrip(self):
        output = format_event_output(SAMPLE_EVENTS, "json")
        parsed = json.loads(output)
        assert len(parsed) == 2
        assert parsed[0]["event"] == "Consumer Price Index (CPI) YoY"

    def test_json_empty_list(self):
        output = format_event_output([], "json")
        assert json.loads(output) == []

    def test_text_format_header(self):
        output = format_event_output(SAMPLE_EVENTS, "text")
        assert "Total: 2" in output

    def test_text_format_contains_event_name(self):
        output = format_event_output(SAMPLE_EVENTS, "text")
        assert "Consumer Price Index (CPI) YoY" in output
        assert "ECB Interest Rate Decision" in output

    def test_text_format_shows_previous(self):
        output = format_event_output(SAMPLE_EVENTS, "text")
        assert "Previous: 2.6" in output

    def test_text_format_omits_none_actual(self):
        output = format_event_output(SAMPLE_EVENTS, "text")
        assert "Actual:" not in output

    def test_text_format_shows_actual_when_present(self):
        events = [
            {
                "date": "2025-01-10 14:30:00",
                "country": "US",
                "event": "NFP",
                "currency": "USD",
                "previous": 200,
                "estimate": 210,
                "actual": 256,
                "change": 56,
                "impact": "High",
                "changePercentage": 28.0,
            }
        ]
        output = format_event_output(events, "text")
        assert "Actual: 256" in output
        assert "Change: 56" in output
        assert "Change %: 28.0%" in output

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError, match="Unknown output format"):
            format_event_output([], "csv")


class FakeResponse:
    def __init__(self, status: int, payload):
        self.status = status
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self._payload).encode("utf-8")


class TestFetchEconomicCalendar:
    def test_fetch_success_builds_request_and_returns_events(self, monkeypatch):
        seen = {}

        def fake_urlopen(request):
            seen["url"] = request.full_url
            seen["headers"] = request.headers
            return FakeResponse(200, SAMPLE_EVENTS)

        monkeypatch.setattr(economic_calendar.urllib.request, "urlopen", fake_urlopen)

        result = fetch_economic_calendar("2026-05-09", "2026-05-10", DUMMY_API_KEY)

        assert result == SAMPLE_EVENTS
        assert seen["url"].endswith("from=2026-05-09&to=2026-05-10")
        assert seen["headers"]["Apikey"] == DUMMY_API_KEY

    def test_fetch_rejects_non_list_response(self, monkeypatch):
        monkeypatch.setattr(
            economic_calendar.urllib.request,
            "urlopen",
            lambda request: FakeResponse(200, {"unexpected": True}),
        )

        with pytest.raises(ValueError, match="Unexpected API response format"):
            fetch_economic_calendar("2026-05-09", "2026-05-10", DUMMY_API_KEY)

    def test_fetch_rejects_non_200_response(self, monkeypatch):
        monkeypatch.setattr(
            economic_calendar.urllib.request,
            "urlopen",
            lambda request: FakeResponse(503, []),
        )

        with pytest.raises(ValueError, match="status code 503"):
            fetch_economic_calendar("2026-05-09", "2026-05-10", DUMMY_API_KEY)

    def test_fetch_wraps_http_error_body(self, monkeypatch):
        class ErrorBody:
            def read(self):
                return b"quota exceeded"

            def close(self):
                pass

        def fake_urlopen(request):
            raise urllib.error.HTTPError(
                request.full_url,
                429,
                "Too Many Requests",
                hdrs={},
                fp=ErrorBody(),
            )

        monkeypatch.setattr(economic_calendar.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(urllib.error.HTTPError, match="quota exceeded"):
            fetch_economic_calendar("2026-05-09", "2026-05-10", DUMMY_API_KEY)

    def test_fetch_wraps_url_error(self, monkeypatch):
        def fake_urlopen(request):
            raise urllib.error.URLError("offline")

        monkeypatch.setattr(economic_calendar.urllib.request, "urlopen", fake_urlopen)

        with pytest.raises(ValueError, match="Network error: offline"):
            fetch_economic_calendar("2026-05-09", "2026-05-10", DUMMY_API_KEY)


class TestMain:
    def test_main_requires_api_key(self, monkeypatch, capsys):
        monkeypatch.delenv("FMP_API_KEY", raising=False)
        monkeypatch.setattr(sys, "argv", ["get_economic_calendar.py"])

        with pytest.raises(SystemExit) as exc:
            economic_calendar.main()

        assert exc.value.code == 1
        assert "FMP API key is required" in capsys.readouterr().err

    def test_main_prints_json_to_stdout(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "get_economic_calendar.py",
                "--from",
                "2026-05-09",
                "--to",
                "2026-05-10",
                "--api-key",
                DUMMY_API_KEY,
            ],
        )
        monkeypatch.setattr(economic_calendar, "fetch_economic_calendar", lambda *_: SAMPLE_EVENTS)

        with pytest.raises(SystemExit) as exc:
            economic_calendar.main()

        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out)[0]["event"] == "Consumer Price Index (CPI) YoY"

    def test_main_writes_text_output_file(self, monkeypatch, tmp_path, capsys):
        output_path = tmp_path / "calendar.txt"
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "get_economic_calendar.py",
                "--from",
                "2026-05-09",
                "--to",
                "2026-05-10",
                "--api-key",
                DUMMY_API_KEY,
                "--format",
                "text",
                "--output",
                str(output_path),
            ],
        )
        monkeypatch.setattr(economic_calendar, "fetch_economic_calendar", lambda *_: SAMPLE_EVENTS)

        with pytest.raises(SystemExit) as exc:
            economic_calendar.main()

        assert exc.value.code == 0
        assert "Consumer Price Index" in output_path.read_text()
        assert f"Output written to {output_path}" in capsys.readouterr().err

    def test_main_reports_validation_or_fetch_errors(self, monkeypatch, capsys):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "get_economic_calendar.py",
                "--from",
                "2026-05-10",
                "--to",
                "2026-05-09",
                "--api-key",
                DUMMY_API_KEY,
            ],
        )

        with pytest.raises(SystemExit) as exc:
            economic_calendar.main()

        assert exc.value.code == 1
        assert "after end date" in capsys.readouterr().err
