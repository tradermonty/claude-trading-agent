from __future__ import annotations

import json

from report_generator import (
    _state_emoji,
    _state_label,
    generate_json_report,
    generate_markdown_report,
)


def _base_analysis(state: str = "FTD_CONFIRMED", score: int = 82) -> dict:
    return {
        "metadata": {
            "generated_at": "2026-05-09T12:00:00Z",
            "index_prices": {"sp500": 5200.12, "qqq": 450.34},
        },
        "market_state": {
            "combined_state": state,
            "dual_confirmation": True,
            "ftd_index": "S&P 500",
        },
        "sp500": {
            "state": state,
            "current_price": 5200.12,
            "lookback_high": 5400.0,
            "correction_depth_pct": -5.4,
            "swing_low": {
                "date": "2026-05-01",
                "price": 5000.0,
                "decline_pct": -7.4,
            },
            "rally_attempt": {
                "day1_date": "2026-05-02",
                "current_day_count": 5,
                "invalidated": False,
            },
            "ftd": {
                "ftd_detected": True,
                "ftd_date": "2026-05-06",
                "ftd_day_number": 5,
                "gain_pct": 1.8,
                "gain_tier": "strong",
                "volume_above_avg": True,
                "ftd_low": 5050.0,
            },
        },
        "nasdaq": {
            "state": state,
            "current_price": 450.34,
            "lookback_high": 470.0,
            "correction_depth_pct": -4.2,
            "swing_low": {
                "date": "2026-05-01",
                "price": 430.0,
                "decline_pct": -8.5,
            },
            "rally_attempt": {
                "day1_date": "2026-05-02",
                "current_day_count": 5,
                "invalidated": True,
                "invalidation_reason": "closed below Day 1 low",
            },
            "ftd": {
                "ftd_detected": True,
                "ftd_date": "2026-05-06",
                "ftd_day_number": 5,
                "gain_pct": 1.4,
                "gain_tier": "moderate",
                "volume_above_avg": False,
                "ftd_low": 435.0,
            },
        },
        "quality_score": {
            "total_score": score,
            "signal": "BUYABLE_FTD",
            "exposure_range": "50-75%",
            "guidance": "Increase exposure selectively.",
            "breakdown": {
                "day_timing": "Day 5 FTD",
                "volume": "Mixed confirmation",
            },
        },
        "post_ftd_distribution": {
            "distribution_count": 1,
            "days_monitored": 4,
            "details": [
                {
                    "day": 3,
                    "date": "2026-05-08",
                    "change_pct": -0.9,
                    "volume_change_pct": 12.5,
                }
            ],
        },
        "ftd_invalidation": {
            "invalidated": False,
            "days_since_ftd": 3,
            "ftd_low": 5050.0,
        },
        "power_trend": {
            "power_trend": True,
            "conditions_met": 3,
            "ema_21": 5120.0,
            "sma_50": 5080.0,
            "ema_above_sma": True,
            "sma_50_rising": True,
            "price_above_21ema": True,
        },
    }


def test_generate_json_report_serializes_analysis(tmp_path):
    output = tmp_path / "ftd.json"
    analysis = _base_analysis()

    generate_json_report(analysis, str(output))

    assert json.loads(output.read_text())["quality_score"]["total_score"] == 82


def test_generate_markdown_report_contains_core_sections(tmp_path):
    output = tmp_path / "ftd.md"

    generate_markdown_report(_base_analysis(), str(output))

    text = output.read_text()
    assert "# FTD Detector Report" in text
    assert "**S&P 500:** $5200.12" in text
    assert "FTD Confirmed" in text
    assert "Dual Confirmation" in text
    assert "Rally Attempt Details" in text
    assert "S&P 500 FTD" in text
    assert "NASDAQ/QQQ FTD" in text
    assert "Quality Score Breakdown" in text
    assert "Distribution Days Since FTD" in text
    assert "Power Trend" in text
    assert "Recommended Exposure" in text
    assert "FTD Day Low" in text
    assert "Methodology" in text


def test_generate_markdown_report_invalidation_branch(tmp_path):
    output = tmp_path / "invalidated.md"
    analysis = _base_analysis("FTD_INVALIDATED", score=45)
    analysis["ftd_invalidation"] = {
        "invalidated": True,
        "invalidation_date": "2026-05-09",
        "days_after_ftd": 3,
        "invalidation_close": 5010.0,
        "ftd_low": 5050.0,
    }

    generate_markdown_report(analysis, str(output))

    text = output.read_text()
    assert "FTD INVALIDATED" in text
    assert "Reduce exposure back to defensive levels" in text


def test_generate_markdown_report_minimal_no_signal(tmp_path):
    output = tmp_path / "minimal.md"
    analysis = {
        "metadata": {"generated_at": "2026-05-09T12:00:00Z"},
        "market_state": {"combined_state": "NO_SIGNAL"},
        "quality_score": {"total_score": 10, "signal": "NONE"},
    }

    generate_markdown_report(analysis, str(output))

    text = output.read_text()
    assert "No Signal (Uptrend)" in text
    assert "FTD monitoring not applicable in uptrend" in text
    assert "Methodology" in text


def test_action_guidance_branches(tmp_path):
    cases = {
        "FTD_CONFIRMED": "Gradually increase exposure",
        "FTD_WINDOW": "WATCH MODE",
        "RALLY_ATTEMPT": "Too early to act",
        "CORRECTION": "Stay defensive",
        "RALLY_FAILED": "Rally attempt failed",
    }

    for state, expected in cases.items():
        output = tmp_path / f"{state}.md"
        generate_markdown_report(_base_analysis(state, score=70), str(output))
        assert expected in output.read_text()


def test_state_helpers_fallback_for_unknown_state():
    assert _state_emoji("CUSTOM") == "⚪"
    assert _state_label("CUSTOM") == "CUSTOM"
