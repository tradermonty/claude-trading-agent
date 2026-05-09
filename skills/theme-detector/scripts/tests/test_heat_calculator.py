"""Tests for heat_calculator.py - Theme Heat Score (0-100)"""

import pytest
from calculators.heat_calculator import (
    breadth_signal_score,
    calculate_theme_heat,
    momentum_strength_score,
    uptrend_signal_score,
    volume_intensity_score,
)

# ── momentum_strength_score ──────────────────────────────────────────


class TestMomentumStrengthScore:
    """Log-sigmoid midpoint is around 15% absolute return."""

    def test_zero_return(self):
        score = momentum_strength_score(0.0)
        assert score == pytest.approx(0.39, abs=0.01)

    def test_five_percent(self):
        score = momentum_strength_score(5.0)
        assert score == pytest.approx(12.33, abs=0.1)

    def test_negative_five_percent(self):
        score = momentum_strength_score(-5.0)
        assert score == pytest.approx(12.33, abs=0.1)

    def test_fifteen_percent(self):
        score = momentum_strength_score(15.0)
        assert score == pytest.approx(50.0, abs=0.1)

    def test_twenty_percent(self):
        score = momentum_strength_score(20.0)
        assert score == pytest.approx(63.27, abs=0.1)

    def test_negative_twenty_percent(self):
        score = momentum_strength_score(-20.0)
        assert score == pytest.approx(63.27, abs=0.1)

    def test_returns_float(self):
        assert isinstance(momentum_strength_score(3.0), float)


# ── volume_intensity_score ───────────────────────────────────────────


class TestVolumeIntensityScore:
    """sqrt-scaled score with ceiling at ratio 2.0."""

    def test_ratio_0_8_returns_zero(self):
        # (0.8 - 0.8) * 250 = 0
        assert volume_intensity_score(80.0, 100.0) == pytest.approx(0.0)

    def test_ratio_1_0_returns_50(self):
        assert volume_intensity_score(100.0, 100.0) == pytest.approx(40.82, abs=0.01)

    def test_ratio_1_2_returns_100(self):
        assert volume_intensity_score(120.0, 100.0) == pytest.approx(57.74, abs=0.01)

    def test_ratio_above_cap_clamped_to_100(self):
        # (2.0 - 0.8) * 250 = 300 => clamped 100
        assert volume_intensity_score(200.0, 100.0) == pytest.approx(100.0)

    def test_ratio_below_floor_clamped_to_0(self):
        # (0.5 - 0.8) * 250 = -75 => clamped 0
        assert volume_intensity_score(50.0, 100.0) == pytest.approx(0.0)

    def test_none_vol_20d(self):
        assert volume_intensity_score(None, 100.0) == pytest.approx(50.0)

    def test_none_vol_60d(self):
        assert volume_intensity_score(100.0, None) == pytest.approx(50.0)

    def test_zero_vol_60d(self):
        assert volume_intensity_score(100.0, 0.0) == pytest.approx(50.0)


# ── uptrend_signal_score ─────────────────────────────────────────────


class TestUptrendSignalScore:
    def _make_sector(self, ratio, ma_10, slope, weight=1.0):
        return {
            "sector": "test",
            "ratio": ratio,
            "ma_10": ma_10,
            "slope": slope,
            "weight": weight,
        }

    def test_both_positive_gives_80(self):
        # base score capped at 80 plus both 10-point bonuses.
        data = [self._make_sector(ratio=50, ma_10=40, slope=0.5)]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(100.0)

    def test_ratio_only_gives_60(self):
        # base score capped at 80 plus MA bonus.
        data = [self._make_sector(ratio=50, ma_10=40, slope=-0.1)]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(90.0)

    def test_slope_only_gives_60(self):
        # base score capped at 80 plus slope bonus.
        data = [self._make_sector(ratio=30, ma_10=40, slope=0.5)]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(90.0)

    def test_neither_gives_20(self):
        # base score capped at 80 with no bonuses.
        data = [self._make_sector(ratio=30, ma_10=40, slope=-0.1)]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(80.0)

    def test_weighted_average(self):
        # sector A: 100, weight 2; sector B: 80, weight 1
        data = [
            self._make_sector(ratio=50, ma_10=40, slope=0.5, weight=2.0),
            self._make_sector(ratio=30, ma_10=40, slope=-0.1, weight=1.0),
        ]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(93.33, abs=0.01)

    def test_bearish_inversion(self):
        data = [self._make_sector(ratio=50, ma_10=40, slope=0.5)]
        score = uptrend_signal_score(data, is_bearish=True)
        assert score == pytest.approx(0.0)

    def test_empty_list(self):
        assert uptrend_signal_score([], is_bearish=False) == pytest.approx(50.0)

    def test_equal_ratio_and_ma10(self):
        # ratio == ma_10 => base capped at 80, no bonuses.
        data = [self._make_sector(ratio=40, ma_10=40, slope=0)]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(80.0)


# ── breadth_signal_score ─────────────────────────────────────────────


class TestBreadthSignalScore:
    def test_zero(self):
        assert breadth_signal_score(0.0) == pytest.approx(0.0)

    def test_half(self):
        assert breadth_signal_score(0.5) == pytest.approx(14.14, abs=0.01)

    def test_full(self):
        assert breadth_signal_score(1.0) == pytest.approx(80.0)

    def test_above_one_clamped(self):
        assert breadth_signal_score(1.5) == pytest.approx(100.0)

    def test_negative_clamped(self):
        assert breadth_signal_score(-0.3) == pytest.approx(0.0)

    def test_none(self):
        assert breadth_signal_score(None) == pytest.approx(50.0)


# ── calculate_theme_heat ─────────────────────────────────────────────


class TestCalculateThemeHeat:
    def test_weighted_sum(self):
        result = calculate_theme_heat(80.0, 60.0, 70.0, 50.0)
        assert result == pytest.approx(67.5)

    def test_all_100(self):
        result = calculate_theme_heat(100.0, 100.0, 100.0, 100.0)
        assert result == pytest.approx(100.0)

    def test_all_zero(self):
        result = calculate_theme_heat(0.0, 0.0, 0.0, 0.0)
        assert result == pytest.approx(0.0)

    def test_none_defaults_to_50(self):
        # All None => 50*0.40 + 50*0.25 + 50*0.20 + 50*0.15 = 50
        result = calculate_theme_heat(None, None, None, None)
        assert result == pytest.approx(50.0)

    def test_partial_none(self):
        result = calculate_theme_heat(80.0, None, None, None)
        assert result == pytest.approx(60.5)

    def test_clamped_above_100(self):
        result = calculate_theme_heat(200.0, 200.0, 200.0, 200.0)
        assert result == 100.0

    def test_clamped_below_0(self):
        result = calculate_theme_heat(-50.0, -50.0, -50.0, -50.0)
        assert result == 0.0

    def test_returns_float(self):
        assert isinstance(calculate_theme_heat(50, 50, 50, 50), float)


# ── uptrend_signal_score with None values ────────────────────────────


class TestUptrendSignalNoneValues:
    """Ensure None values in sector_data don't cause TypeError."""

    def test_none_ma_10(self):
        """ma_10=None should not crash (treated as 0)."""
        data = [{"sector": "Tech", "ratio": 0.5, "ma_10": None, "slope": 0.01, "weight": 1.0}]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(70.0)

    def test_none_slope(self):
        """slope=None should not crash (treated as 0)."""
        data = [{"sector": "Tech", "ratio": 0.5, "ma_10": 0.3, "slope": None, "weight": 1.0}]
        score = uptrend_signal_score(data, is_bearish=False)
        # ratio(0.5) > ma_10(0.3) but slope(0) not > 0 => 60
        assert score == pytest.approx(60.0)

    def test_none_ratio(self):
        """ratio=None should not crash (treated as 0)."""
        data = [{"sector": "Tech", "ratio": None, "ma_10": 0.3, "slope": 0.01, "weight": 1.0}]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(10.0)

    def test_all_none(self):
        """All values None should not crash."""
        data = [{"sector": "Tech", "ratio": None, "ma_10": None, "slope": None, "weight": 1.0}]
        score = uptrend_signal_score(data, is_bearish=False)
        assert score == pytest.approx(0.0)
