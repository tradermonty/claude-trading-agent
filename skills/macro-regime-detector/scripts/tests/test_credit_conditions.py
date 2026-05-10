"""Tests for Credit Conditions Calculator (HYG/LQD)"""

import calculators.credit_conditions_calculator as credit_conditions
from calculators.credit_conditions_calculator import calculate_credit_conditions
from test_helpers import make_monthly_history


class TestCalculateCreditConditions:
    def test_insufficient_data_empty(self):
        result = calculate_credit_conditions([], [])
        assert result["score"] == 0
        assert result["data_available"] is False

    def test_insufficient_monthly_data(self):
        hyg = make_monthly_history([75] * 6, start_year=2025)
        lqd = make_monthly_history([105] * 6, start_year=2025)

        result = calculate_credit_conditions(hyg, lqd)

        assert result["data_available"] is False
        assert (
            result["signal"] == "INSUFFICIENT DATA: Insufficient monthly data (need >= 12 months)"
        )

    def test_insufficient_ratio_data_when_dates_do_not_overlap(self):
        hyg = make_monthly_history([75] * 12, start_year=2025)
        lqd = make_monthly_history([105] * 12, start_year=2023)

        result = calculate_credit_conditions(hyg, lqd)

        assert result["data_available"] is False
        assert result["signal"] == "INSUFFICIENT DATA: Insufficient ratio data"

    def test_stable_ratio_low_score(self):
        hyg = make_monthly_history([75] * 24, start_year=2024)
        lqd = make_monthly_history([105] * 24, start_year=2024)
        result = calculate_credit_conditions(hyg, lqd)
        assert result["data_available"] is True
        assert result["score"] <= 30  # Small noise from daily variation is expected

    def test_easing_conditions(self):
        # HYG rising relative to LQD = easing
        hyg_closes = [70 + i * 0.5 for i in range(24)]
        lqd_closes = [105] * 24
        hyg = make_monthly_history(hyg_closes, start_year=2024)
        lqd = make_monthly_history(lqd_closes, start_year=2024)
        result = calculate_credit_conditions(hyg, lqd)
        assert result["data_available"] is True

    def test_tightening_conditions(self):
        # HYG falling relative to LQD = tightening
        hyg_closes = [80 - i * 0.5 for i in range(24)]
        lqd_closes = [105] * 24
        hyg = make_monthly_history(hyg_closes, start_year=2024)
        lqd = make_monthly_history(lqd_closes, start_year=2024)
        result = calculate_credit_conditions(hyg, lqd)
        assert result["data_available"] is True

    def test_output_structure(self):
        hyg = make_monthly_history([75 + i * 0.1 for i in range(24)], start_year=2024)
        lqd = make_monthly_history([105] * 24, start_year=2024)
        result = calculate_credit_conditions(hyg, lqd)

        required_keys = [
            "score",
            "signal",
            "data_available",
            "direction",
            "current_ratio",
            "sma_6m",
            "sma_12m",
            "roc_3m",
            "roc_12m",
            "percentile",
            "crossover",
            "monthly_points",
        ]
        for key in required_keys:
            assert key in result
        assert 0 <= result["score"] <= 100

    def test_signal_descriptions_cover_score_bands(self):
        assert credit_conditions._describe_signal(60, "easing", 0.75).startswith("TRANSITION")
        assert credit_conditions._describe_signal(40, "tightening", 0.75).startswith("SHIFTING")
        assert credit_conditions._describe_signal(10, "stable", 0.75).startswith("STABLE")
