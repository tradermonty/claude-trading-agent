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
