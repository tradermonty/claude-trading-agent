"""Tests for Market Concentration Calculator (RSP/SPY)"""

import calculators.concentration_calculator as concentration
from calculators.concentration_calculator import calculate_concentration
from test_helpers import make_monthly_history


class TestCalculateConcentration:
    def test_insufficient_data_empty(self):
        result = calculate_concentration([], [])
        assert result["score"] == 0
        assert result["data_available"] is False

    def test_insufficient_data_too_short(self):
        rsp = make_monthly_history([100] * 6, start_year=2025)
        spy = make_monthly_history([100] * 6, start_year=2025)
        result = calculate_concentration(rsp, spy)
        assert result["data_available"] is False

    def test_insufficient_ratio_data_when_dates_do_not_overlap(self):
        rsp = make_monthly_history([100] * 12, start_year=2025)
        spy = make_monthly_history([100] * 12, start_year=2023)

        result = calculate_concentration(rsp, spy)

        assert result["data_available"] is False
        assert result["signal"] == "INSUFFICIENT DATA: Insufficient ratio data"

    def test_stable_ratio_low_score(self):
        # Flat ratio = no transition signal
        rsp = make_monthly_history([100] * 24, start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)
        result = calculate_concentration(rsp, spy)
        assert result["data_available"] is True
        assert result["score"] <= 30  # Small noise from daily variation is expected
        assert result["current_ratio"] is not None

    def test_rising_rsp_spy_broadening(self):
        # RSP rising faster than SPY = broadening
        # Create a clear uptrend in RSP relative to SPY
        rsp_closes = [100 + i * 2 for i in range(24)]  # Rises from 100 to 146
        spy_closes = [100 + i * 0.5 for i in range(24)]  # Rises from 100 to 111.5
        rsp = make_monthly_history(rsp_closes, start_year=2024)
        spy = make_monthly_history(spy_closes, start_year=2024)
        result = calculate_concentration(rsp, spy)
        assert result["data_available"] is True
        assert result["monthly_points"] >= 12

    def test_declining_rsp_spy_concentrating(self):
        # SPY rising faster than RSP = concentrating
        rsp_closes = [100 + i * 0.5 for i in range(24)]
        spy_closes = [100 + i * 2 for i in range(24)]
        rsp = make_monthly_history(rsp_closes, start_year=2024)
        spy = make_monthly_history(spy_closes, start_year=2024)
        result = calculate_concentration(rsp, spy)
        assert result["data_available"] is True

    def test_crossover_detected(self):
        # Create a ratio that crosses over (death_cross then reverses)
        # First 12 months: RSP/SPY declining, next 12 months: recovering
        rsp_closes = [120 - i for i in range(12)] + [108 + i * 2 for i in range(12)]
        spy_closes = [100] * 24
        rsp = make_monthly_history(rsp_closes, start_year=2024)
        spy = make_monthly_history(spy_closes, start_year=2024)
        result = calculate_concentration(rsp, spy)
        assert result["data_available"] is True
        assert result["crossover"]["type"] in ("golden_cross", "death_cross", "converging", "none")

    def test_output_structure(self):
        rsp = make_monthly_history([100 + i for i in range(24)], start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)
        result = calculate_concentration(rsp, spy)

        # Verify required keys
        assert "score" in result
        assert "signal" in result
        assert "data_available" in result
        assert "direction" in result
        assert "current_ratio" in result
        assert "sma_6m" in result
        assert "sma_12m" in result
        assert "roc_3m" in result
        assert "roc_12m" in result
        assert "percentile" in result
        assert "crossover" in result
        assert "monthly_points" in result

        assert 0 <= result["score"] <= 100

    def test_death_cross_direction_is_concentrating(self, monkeypatch):
        monkeypatch.setattr(
            concentration,
            "detect_crossover",
            lambda values, short_period, long_period: {
                "type": "death_cross",
                "bars_ago": 0,
                "gap_pct": -1.2,
            },
        )
        monkeypatch.setattr(
            concentration,
            "compute_roc",
            lambda values, period: -2.5 if period == 3 else -5.0,
        )

        rsp = make_monthly_history([100 + i for i in range(24)], start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)

        result = calculate_concentration(rsp, spy)

        assert result["direction"] == "concentrating"
        assert result["momentum_qualifier"] == "confirmed"

    def test_stale_crossover_uses_reversing_momentum_direction(self, monkeypatch):
        monkeypatch.setattr(
            concentration,
            "detect_crossover",
            lambda values, short_period, long_period: {
                "type": "golden_cross",
                "bars_ago": 4,
                "gap_pct": 1.2,
            },
        )
        monkeypatch.setattr(
            concentration,
            "compute_roc",
            lambda values, period: -2.5 if period == 3 else 5.0,
        )

        rsp = make_monthly_history([100 + i for i in range(24)], start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)

        result = calculate_concentration(rsp, spy)

        assert result["direction"] == "concentrating"
        assert result["momentum_qualifier"] == "reversing"

    def test_recent_crossover_with_contradicting_momentum_is_fading(self, monkeypatch):
        monkeypatch.setattr(
            concentration,
            "detect_crossover",
            lambda values, short_period, long_period: {
                "type": "golden_cross",
                "bars_ago": 1,
                "gap_pct": 1.2,
            },
        )
        monkeypatch.setattr(
            concentration,
            "compute_roc",
            lambda values, period: -2.5 if period == 3 else 5.0,
        )

        rsp = make_monthly_history([100 + i for i in range(24)], start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)

        result = calculate_concentration(rsp, spy)

        assert result["direction"] == "broadening"
        assert result["momentum_qualifier"] == "fading"

    def test_unknown_direction_when_smas_are_unavailable(self, monkeypatch):
        monkeypatch.setattr(
            concentration,
            "detect_crossover",
            lambda values, short_period, long_period: {
                "type": "none",
                "bars_ago": None,
                "gap_pct": None,
            },
        )
        monkeypatch.setattr(concentration, "compute_sma", lambda values, period: None)

        rsp = make_monthly_history([100 + i for i in range(24)], start_year=2024)
        spy = make_monthly_history([100] * 24, start_year=2024)

        result = calculate_concentration(rsp, spy)

        assert result["direction"] == "unknown"
        assert result["sma_6m"] is None
        assert result["sma_12m"] is None

    def test_signal_descriptions_cover_transition_score_bands(self):
        crossover = {"type": "golden_cross", "bars_ago": 0, "gap_pct": 1.2}

        assert concentration._describe_signal(80, crossover, 1.0, 2.0, 1.0).startswith(
            "STRONG TRANSITION"
        )
        assert concentration._describe_signal(60, crossover, 1.0, 2.0, 1.0).startswith(
            "TRANSITION SIGNAL"
        )
        assert concentration._describe_signal(40, crossover, 1.0, 2.0, 1.0).startswith(
            "TRANSITION ZONE"
        )
