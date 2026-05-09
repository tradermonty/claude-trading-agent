"""Tests for uptrend_client helpers and CSV fetch logic."""

from datetime import datetime
from unittest.mock import patch

import uptrend_client
from uptrend_client import (
    _calculate_slope,
    _safe_float,
    build_summary_from_timeseries,
    fetch_sector_uptrend_data,
    get_sector_uptrend_3point,
    is_data_stale,
)


class _Response:
    def __init__(self, text="", *, raise_error=None):
        self.text = text
        self._raise_error = raise_error

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error


class TestNumericHelpers:
    def test_safe_float_handles_valid_and_invalid_values(self):
        assert _safe_float("1.25") == 1.25
        assert _safe_float(2) == 2.0
        assert _safe_float("") is None
        assert _safe_float(None) is None
        assert _safe_float("not-a-number") is None

    def test_calculate_slope(self):
        assert _calculate_slope([1.0]) is None
        assert _calculate_slope([1.0, 2.0, 3.0]) == 1.0
        assert _calculate_slope([3.0, 2.0, 1.0]) == -1.0


class TestFetchSectorUptrendData:
    def test_returns_empty_when_requests_missing(self, monkeypatch, capsys):
        monkeypatch.setattr(uptrend_client, "HAS_REQUESTS", False)

        assert fetch_sector_uptrend_data() == {}
        assert "requests library not installed" in capsys.readouterr().err

    def test_returns_empty_on_request_error(self, monkeypatch, capsys):
        monkeypatch.setattr(uptrend_client, "HAS_REQUESTS", True)

        def fake_get(*args, **kwargs):
            raise RuntimeError("network down")

        monkeypatch.setattr(uptrend_client.requests, "get", fake_get)

        assert fetch_sector_uptrend_data() == {}
        assert "Failed to fetch uptrend timeseries" in capsys.readouterr().err

    def test_parses_latest_sector_rows_and_calculates_fallback_slope(self, monkeypatch):
        monkeypatch.setattr(uptrend_client, "HAS_REQUESTS", True)
        csv_text = "\n".join(
            [
                "date,worksheet,ratio,ma_10,slope,trend",
                "2026-01-01,all,0.50,0.40,0.01,up",
                "2026-01-01,sec_technology,0.10,0.12,,down",
                "2026-01-02,sec_technology,0.20,0.14,,up",
                "2026-01-03,sec_technology,0.30,0.16,,up",
                "2026-01-04,sec_technology,0.40,0.18,,up",
                "2026-01-05,sec_technology,0.50,0.20,,up",
                "2026-01-06,sec_healthcare,0.08,0.10,-0.02,down",
                "2026-01-07,unknown,0.99,0.99,0.00,up",
                "2026-01-08,sec_energy,,0.20,0.00,up",
            ]
        )

        monkeypatch.setattr(
            uptrend_client.requests,
            "get",
            lambda *args, **kwargs: _Response(csv_text),
        )

        result = fetch_sector_uptrend_data()

        assert result["Technology"] == {
            "ratio": 0.5,
            "ma_10": 0.2,
            "slope": 0.1,
            "trend": "up",
            "latest_date": "2026-01-05",
        }
        assert result["Healthcare"]["slope"] == -0.02
        assert result["Healthcare"]["trend"] == "down"
        assert "Energy" not in result


class TestSummaryHelpers:
    def test_build_summary_from_timeseries_assigns_statuses(self):
        rows = build_summary_from_timeseries(
            {
                "Hot": {"ratio": 0.5, "ma_10": 0.4, "trend": "up", "slope": 0.1},
                "Cold": {"ratio": 0.05, "ma_10": 0.1, "trend": "down", "slope": -0.1},
                "Neutral": {"ratio": 0.2, "ma_10": None, "trend": "", "slope": None},
            }
        )

        by_sector = {row["Sector"]: row for row in rows}
        assert by_sector["Hot"]["Status"] == "Overbought"
        assert by_sector["Cold"]["Status"] == "Oversold"
        assert by_sector["Neutral"]["Status"] == "Normal"
        assert by_sector["Neutral"]["Trend"] == ""

    def test_get_sector_uptrend_3point(self):
        data = {"Technology": {"ratio": 0.42}}

        assert get_sector_uptrend_3point("Technology", data) == {"ratio": 0.42}
        assert get_sector_uptrend_3point("Utilities", data) is None


class TestIsDataStale:
    """is_data_stale should count business days, not calendar days."""

    def _mock_now(self, year, month, day, hour=12):
        return datetime(year, month, day, hour, 0, 0)

    def test_friday_to_sunday_not_stale(self):
        """Friday data checked on Sunday: 0 business days -> not stale."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 15)  # Sunday
            assert is_data_stale("2026-02-13") is False  # Friday

    def test_friday_to_monday_not_stale(self):
        """Friday data checked on Monday: 1 business day -> not stale (threshold=2)."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 16)  # Monday
            assert is_data_stale("2026-02-13") is False  # Friday

    def test_friday_to_tuesday_not_stale(self):
        """Friday data checked on Tuesday: 2 business days -> not stale (threshold=2)."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 17)  # Tuesday
            assert is_data_stale("2026-02-13") is False  # Friday

    def test_friday_to_wednesday_stale(self):
        """Friday data checked on Wednesday: 3 business days -> stale (threshold=2)."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 18)  # Wednesday
            assert is_data_stale("2026-02-13") is True  # Friday

    def test_monday_to_wednesday_not_stale(self):
        """Monday data checked on Wednesday: 2 business days -> not stale."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 18)  # Wednesday
            assert is_data_stale("2026-02-16") is False  # Monday

    def test_monday_to_thursday_stale(self):
        """Monday data checked on Thursday: 3 business days -> stale."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 19)  # Thursday
            assert is_data_stale("2026-02-16") is True  # Monday

    def test_same_day_not_stale(self):
        """Same day data -> 0 business days -> not stale."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 16)  # Monday
            assert is_data_stale("2026-02-16") is False

    def test_invalid_date_returns_true(self):
        """Invalid date string -> stale (safe default)."""
        assert is_data_stale("not-a-date") is True

    def test_custom_threshold(self):
        """Custom threshold_bdays works correctly."""
        with patch("uptrend_client.datetime") as mock_dt:
            mock_dt.strptime = datetime.strptime
            mock_dt.now.return_value = self._mock_now(2026, 2, 17)  # Tuesday
            # Friday to Tuesday = 2 bdays, threshold=1 -> stale
            assert is_data_stale("2026-02-13", threshold_bdays=1) is True
