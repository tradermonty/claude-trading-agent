"""Tests for Equity-Bond Relationship Calculator (SPY/TLT + correlation)"""

import calculators.equity_bond_calculator as equity_bond
from calculators.equity_bond_calculator import calculate_equity_bond
from test_helpers import make_monthly_history


class TestCalculateEquityBond:
    def test_insufficient_data_empty(self):
        result = calculate_equity_bond([], [])
        assert result["score"] == 0
        assert result["data_available"] is False

    def test_insufficient_monthly_data(self):
        spy = make_monthly_history([500] * 6, start_year=2025)
        tlt = make_monthly_history([90] * 6, start_year=2025)

        result = calculate_equity_bond(spy, tlt)

        assert result["data_available"] is False
        assert (
            result["signal"] == "INSUFFICIENT DATA: Insufficient monthly data (need >= 12 months)"
        )

    def test_insufficient_ratio_data_when_dates_do_not_overlap(self):
        spy = make_monthly_history([500] * 12, start_year=2025)
        tlt = make_monthly_history([90] * 12, start_year=2023)

        result = calculate_equity_bond(spy, tlt)

        assert result["data_available"] is False
        assert result["signal"] == "INSUFFICIENT DATA: Insufficient ratio data"

    def test_stable_ratio_low_score(self):
        spy = make_monthly_history([500] * 24, start_year=2024)
        tlt = make_monthly_history([90] * 24, start_year=2024)
        result = calculate_equity_bond(spy, tlt)
        assert result["data_available"] is True
        assert result["score"] <= 30  # Small noise from daily variation is expected

    def test_risk_on_shift(self):
        # SPY rising, TLT flat = risk-on
        spy_closes = [500 + i * 5 for i in range(24)]
        tlt_closes = [90] * 24
        spy = make_monthly_history(spy_closes, start_year=2024)
        tlt = make_monthly_history(tlt_closes, start_year=2024)
        result = calculate_equity_bond(spy, tlt)
        assert result["data_available"] is True

    def test_risk_off_shift(self):
        # SPY falling, TLT rising = risk-off
        spy_closes = [600 - i * 5 for i in range(24)]
        tlt_closes = [80 + i * 2 for i in range(24)]
        spy = make_monthly_history(spy_closes, start_year=2024)
        tlt = make_monthly_history(tlt_closes, start_year=2024)
        result = calculate_equity_bond(spy, tlt)
        assert result["data_available"] is True

    def test_correlation_regime_present(self):
        spy = make_monthly_history([500 + i * 2 for i in range(24)], start_year=2024)
        tlt = make_monthly_history([90 - i * 0.5 for i in range(24)], start_year=2024)
        result = calculate_equity_bond(spy, tlt)
        assert result["correlation_regime"] in (
            "negative_strong",
            "negative_mild",
            "near_zero",
            "positive",
            "unknown",
        )

    def test_output_structure(self):
        spy = make_monthly_history([500 + i for i in range(24)], start_year=2024)
        tlt = make_monthly_history([90] * 24, start_year=2024)
        result = calculate_equity_bond(spy, tlt)

        required_keys = [
            "score",
            "signal",
            "data_available",
            "direction",
            "correlation_regime",
            "current_ratio",
            "sma_6m",
            "sma_12m",
            "roc_3m",
            "roc_12m",
            "percentile",
            "correlation_6m",
            "correlation_12m",
            "crossover",
            "monthly_points",
        ]
        for key in required_keys:
            assert key in result
        assert 0 <= result["score"] <= 100

    def test_sign_change_correlation_adds_full_bonus(self, monkeypatch):
        monkeypatch.setattr(
            equity_bond,
            "compute_rolling_correlation",
            lambda spy_returns, tlt_returns, window: 0.2 if window == 6 else -0.2,
        )
        monkeypatch.setattr(equity_bond, "score_transition_signal", lambda **kwargs: 25)

        spy = make_monthly_history([500 + i for i in range(24)], start_year=2024)
        tlt = make_monthly_history([90] * 24, start_year=2024)

        result = calculate_equity_bond(spy, tlt)

        assert result["score"] == 45
        assert result["correlation_regime"] == "near_zero"

    def test_large_correlation_delta_adds_partial_bonus(self, monkeypatch):
        monkeypatch.setattr(
            equity_bond,
            "compute_rolling_correlation",
            lambda spy_returns, tlt_returns, window: 0.7 if window == 6 else 0.2,
        )
        monkeypatch.setattr(equity_bond, "score_transition_signal", lambda **kwargs: 25)

        spy = make_monthly_history([500 + i for i in range(24)], start_year=2024)
        tlt = make_monthly_history([90] * 24, start_year=2024)

        result = calculate_equity_bond(spy, tlt)

        assert result["score"] == 35
        assert result["correlation_regime"] == "positive"

    def test_compute_monthly_returns_handles_short_and_zero_prior_close(self):
        assert equity_bond._compute_monthly_returns([100]) == []
        assert equity_bond._compute_monthly_returns([110, 0, 100]) == [-1.0]

    def test_classifies_correlation_regimes(self):
        assert equity_bond._classify_correlation_regime(None, None) == "unknown"
        assert equity_bond._classify_correlation_regime(-0.5, -0.4) == "negative_strong"
        assert equity_bond._classify_correlation_regime(-0.1, -0.2) == "negative_mild"
        assert equity_bond._classify_correlation_regime(0.1, 0.2) == "near_zero"
        assert equity_bond._classify_correlation_regime(0.5, 0.4) == "positive"

    def test_signal_descriptions_cover_transition_score_bands_and_unknown_label(self):
        assert equity_bond._describe_signal(60, "risk_on", "positive", 5.5).startswith("TRANSITION")
        assert equity_bond._describe_signal(40, "risk_off", "negative_mild", 5.5).startswith(
            "SHIFTING"
        )
        assert "custom_regime" in equity_bond._describe_signal(10, "neutral", "custom_regime", 5.5)
