"""Tests for ftd_detector.py orchestration helpers."""

from unittest.mock import patch

import ftd_detector


class TestParseArguments:
    def test_parse_arguments_defaults_output_dir(self):
        with patch("sys.argv", ["ftd_detector.py"]):
            args = ftd_detector.parse_arguments()

        assert args.api_key is None
        assert args.output_dir == "."

    def test_parse_arguments_accepts_output_dir(self):
        with patch(
            "sys.argv",
            ["ftd_detector.py", "--output-dir", "reports/out"],
        ):
            args = ftd_detector.parse_arguments()

        assert args.api_key is None
        assert args.output_dir == "reports/out"


class TestSerializeIndex:
    def test_serialize_minimal_index(self):
        result = ftd_detector._serialize_index(
            {
                "state": "NO_SIGNAL",
                "current_price": 5000.0,
                "lookback_high": 5100.0,
                "correction_depth_pct": -1.9,
            }
        )

        assert result == {
            "state": "NO_SIGNAL",
            "current_price": 5000.0,
            "lookback_high": 5100.0,
            "correction_depth_pct": -1.9,
        }

    def test_serialize_full_index_removes_large_internal_fields(self):
        result = ftd_detector._serialize_index(
            {
                "state": "FTD_CONFIRMED",
                "current_price": 5100.0,
                "lookback_high": 5200.0,
                "correction_depth_pct": -5.1,
                "swing_low": {
                    "swing_low_date": "2026-05-01",
                    "swing_low_price": 4800.0,
                    "decline_pct": -7.7,
                    "down_days": 5,
                    "recent_high_date": "2026-04-20",
                    "recent_high_price": 5200.0,
                    "swing_low_idx": 12,
                },
                "rally_attempt": {
                    "day1_date": "2026-05-02",
                    "current_day_count": 5,
                    "invalidated": False,
                    "invalidation_reason": None,
                    "rally_days": [{"large": "internal payload"}],
                },
                "ftd": {
                    "ftd_detected": True,
                    "ftd_date": "2026-05-06",
                    "ftd_day_number": 4,
                    "ftd_low": 4900.0,
                    "gain_pct": 1.8,
                    "gain_tier": "qualified",
                    "volume_above_avg": True,
                    "raw_bar": {"large": "internal payload"},
                },
            }
        )

        assert result["swing_low"] == {
            "date": "2026-05-01",
            "price": 4800.0,
            "decline_pct": -7.7,
            "down_days": 5,
            "recent_high_date": "2026-04-20",
            "recent_high_price": 5200.0,
        }
        assert result["rally_attempt"] == {
            "day1_date": "2026-05-02",
            "current_day_count": 5,
            "invalidated": False,
            "invalidation_reason": None,
        }
        assert result["ftd"] == {
            "ftd_detected": True,
            "ftd_date": "2026-05-06",
            "ftd_day_number": 4,
            "ftd_low": 4900.0,
            "gain_pct": 1.8,
            "gain_tier": "qualified",
            "volume_above_avg": True,
        }
        assert "rally_days" not in result["rally_attempt"]
        assert "raw_bar" not in result["ftd"]


class TestMainSuccessPath:
    def test_main_prints_state_health_and_report_summary(self, capsys):
        client = _FakeClient()
        market_state = _market_state()

        with (
            patch("sys.argv", ["ftd_detector.py", "--output-dir", "reports/out"]),
            patch.object(ftd_detector, "FMPClient", return_value=client),
            patch.object(ftd_detector, "get_market_state", return_value=market_state),
            patch.object(ftd_detector, "assess_post_ftd_health", return_value=market_state),
            patch.object(ftd_detector, "generate_json_report") as json_report,
            patch.object(ftd_detector, "generate_markdown_report") as md_report,
        ):
            ftd_detector.main()

        output = capsys.readouterr().out

        assert "S&P 500 State: FTD_CONFIRMED" in output
        assert "NASDAQ State:  FTD_CONFIRMED" in output
        assert "S&P 500 Swing Low: 2026-05-01" in output
        assert "NASDAQ Rally Day 1: 2026-05-02 (Day 5)" in output
        assert "Power Trend: YES (3/3 conditions)" in output
        assert "Post-FTD Distribution Days: 2 (monitored 7 days)" in output
        assert "FTD INVALIDATED on 2026-05-08" in output
        assert "Quality Score: 82/100" in output
        assert "JSON Report: reports/out/ftd_detector_" in output
        assert "API calls made: 4" in output
        json_report.assert_called_once()
        md_report.assert_called_once()


class _FakeClient:
    def __init__(self):
        self.history = {
            "^GSPC": [{"date": "2026-05-10", "close": 5100.0}],
            "QQQ": [{"date": "2026-05-10", "close": 430.0}],
        }
        self.quotes = {
            "^GSPC": [{"price": 5110.0}],
            "QQQ": [{"price": 431.0}],
        }

    def get_historical_prices(self, symbol, days):
        assert days == 80
        return {"historical": self.history[symbol]}

    def get_quote(self, symbol):
        return self.quotes[symbol]

    def get_api_stats(self):
        return {"api_calls_made": 4, "cache_entries": 2}


def _index_state():
    return {
        "state": "FTD_CONFIRMED",
        "current_price": 5100.0,
        "lookback_high": 5200.0,
        "correction_depth_pct": -5.1,
        "swing_low": {
            "swing_low_date": "2026-05-01",
            "swing_low_price": 4800.0,
            "decline_pct": -7.7,
            "down_days": 5,
            "recent_high_date": "2026-04-20",
            "recent_high_price": 5200.0,
        },
        "rally_attempt": {
            "day1_date": "2026-05-02",
            "current_day_count": 5,
            "invalidated": False,
            "invalidation_reason": None,
        },
        "ftd": {
            "ftd_detected": True,
            "ftd_date": "2026-05-06",
            "ftd_day_number": 4,
            "ftd_low": 4900.0,
            "gain_pct": 1.8,
            "gain_tier": "qualified",
            "volume_above_avg": True,
        },
    }


def _market_state():
    return {
        "combined_state": "FTD_CONFIRMED",
        "dual_confirmation": True,
        "ftd_index": "sp500",
        "sp500": _index_state(),
        "nasdaq": _index_state(),
        "quality_score": {
            "total_score": 82,
            "signal": "Healthy",
            "guidance": "Increase exposure gradually",
            "exposure_range": "55-80%",
        },
        "power_trend": {"power_trend": True, "conditions_met": 3},
        "post_ftd_distribution": {"distribution_count": 2, "days_monitored": 7},
        "ftd_invalidation": {
            "invalidated": True,
            "invalidation_date": "2026-05-08",
            "days_after_ftd": 2,
        },
    }
