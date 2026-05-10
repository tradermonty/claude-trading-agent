"""Tests for Component 3: Peak/Trough Cycle Calculator."""

import pytest
from calculators.cycle_calculator import (
    _calculate_score,
    _generate_signal,
    calculate_cycle_position,
)


class TestDataAvailability:
    """Marker-not-found should yield data_available=False."""

    def test_no_marker_returns_data_available_false(self, make_rows):
        """120 rows with no peak/trough -> data_available False."""
        rows = make_rows(120)
        result = calculate_cycle_position(rows)
        assert result["data_available"] is False
        assert result["score"] == 50

    def test_marker_present_returns_data_available_true(self, make_rows):
        """A trough marker within lookback -> data_available True."""
        rows = make_rows(120)
        rows[-10]["Is_Trough"] = True
        # Make 8MA rising so we get a proper score
        rows[-1]["Breadth_Index_8MA"] = 0.55
        rows[-6]["Breadth_Index_8MA"] = 0.45
        result = calculate_cycle_position(rows)
        assert result["data_available"] is True
        assert result["score"] != 50  # Should be a real score

    def test_insufficient_data_returns_data_available_false(self, make_rows):
        """Fewer than 10 rows -> data_available False."""
        rows = make_rows(5)
        result = calculate_cycle_position(rows)
        assert result["data_available"] is False

    def test_peak_marker_returns_data_available_true(self, make_rows):
        """A peak marker within lookback -> data_available True."""
        rows = make_rows(30)
        rows[-5]["Is_Peak"] = True
        rows[-1]["Breadth_Index_8MA"] = 0.40
        rows[-6]["Breadth_Index_8MA"] = 0.50
        result = calculate_cycle_position(rows)
        assert result["data_available"] is True

    def test_unknown_marker_type_defaults_to_neutral(self):
        assert (
            _calculate_score("OTHER", days_since=12, ma8_trend="rising", extreme_trough=False) == 50
        )

    def test_unknown_marker_signal_is_neutral(self):
        assert _generate_signal(None, None, "unknown", 50) == (
            "NEUTRAL: No cycle marker in last 120 days"
        )


def _rows_with_marker(make_rows, marker_type: str, days_since: int, *, rising: bool, extreme=False):
    rows = make_rows(130)
    marker = rows[-(days_since + 1)]
    if marker_type == "TROUGH":
        marker["Is_Trough"] = True
        marker["Is_Trough_8MA_Below_04"] = extreme
    else:
        marker["Is_Peak"] = True

    rows[-1]["Breadth_Index_8MA"] = 0.60 if rising else 0.40
    rows[-6]["Breadth_Index_8MA"] = 0.50
    return rows


@pytest.mark.parametrize(
    ("days_since", "rising", "extreme", "expected_score", "expected_signal"),
    [
        (10, False, False, 30, "failed reversal attempt"),
        (40, True, False, 75, "sustained recovery"),
        (40, False, False, 35, "stalled recovery"),
        (90, True, True, 75, "mature recovery"),
        (90, False, False, 40, "weakening recovery"),
    ],
)
def test_trough_cycle_score_and_signal_branches(
    make_rows, days_since, rising, extreme, expected_score, expected_signal
):
    rows = _rows_with_marker(make_rows, "TROUGH", days_since, rising=rising, extreme=extreme)

    result = calculate_cycle_position(rows)

    assert result["latest_marker_type"] == "TROUGH"
    assert result["days_since_marker"] == days_since
    assert result["score"] == expected_score
    assert expected_signal in result["signal"]
    assert result["extreme_trough"] is extreme


@pytest.mark.parametrize(
    ("days_since", "rising", "expected_score", "expected_signal"),
    [
        (10, True, 60, "consolidation near highs"),
        (10, False, 20, "post-peak decline"),
        (40, True, 45, "recovery attempt"),
        (40, False, 15, "gradual decline"),
        (90, True, 50, "possible bottom formation"),
        (90, False, 10, "prolonged decline"),
    ],
)
def test_peak_cycle_score_and_signal_branches(
    make_rows, days_since, rising, expected_score, expected_signal
):
    rows = _rows_with_marker(make_rows, "PEAK", days_since, rising=rising)

    result = calculate_cycle_position(rows)

    assert result["latest_marker_type"] == "PEAK"
    assert result["days_since_marker"] == days_since
    assert result["score"] == expected_score
    assert expected_signal in result["signal"]
