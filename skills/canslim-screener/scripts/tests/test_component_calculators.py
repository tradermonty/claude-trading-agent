"""Focused coverage for pure CANSLIM component calculators."""

from __future__ import annotations

import os
import sys

SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), "..")
CALCULATORS_DIR = os.path.join(SCRIPTS_DIR, "calculators")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, CALCULATORS_DIR)

from earnings_calculator import (  # noqa: E402
    calculate_quarterly_growth,
    detect_earnings_acceleration,
    interpret_earnings_score,
    score_current_earnings,
)
from growth_calculator import (  # noqa: E402
    calculate_annual_growth,
    check_consistency,
    interpret_growth_score,
    score_annual_growth,
)
from leadership_calculator import (  # noqa: E402
    calculate_leadership,
    calculate_sector_relative_strength,
    score_leadership,
)
from new_highs_calculator import calculate_newness, score_newness  # noqa: E402
from scorer import (  # noqa: E402
    calculate_composite_score,
    calculate_composite_score_phase2,
    calculate_composite_score_phase3,
    check_minimum_thresholds,
    check_minimum_thresholds_phase2,
    check_minimum_thresholds_phase3,
    compare_to_full_canslim,
    interpret_composite_score,
)
from supply_demand_calculator import (  # noqa: E402
    calculate_supply_demand,
    interpret_supply_demand,
    score_supply_demand,
)


def _quarters(latest_eps: float, year_ago_eps: float, latest_revenue: int, year_ago_revenue: int):
    return [
        {"date": "2025-03-31", "eps": latest_eps, "revenue": latest_revenue},
        {"date": "2024-12-31", "eps": 1.2, "revenue": 110},
        {"date": "2024-09-30", "eps": 1.1, "revenue": 105},
        {"date": "2024-06-30", "eps": 1.0, "revenue": 100},
        {"date": "2024-03-31", "eps": year_ago_eps, "revenue": year_ago_revenue},
        {"date": "2023-12-31", "eps": 0.9, "revenue": 90},
    ]


def test_quarterly_growth_scores_success_and_quality_warning():
    result = calculate_quarterly_growth(_quarters(2.0, 1.0, 130, 100))

    assert result["score"] == 100
    assert result["latest_qtr_eps_growth"] == 100.0
    assert result["latest_qtr_revenue_growth"] == 30.0
    assert result["quality_warning"] is not None
    assert "Exceptional" in result["interpretation"]


def test_quarterly_growth_handles_missing_and_zero_denominators():
    assert calculate_quarterly_growth([])["error"].startswith("Insufficient")
    assert (
        calculate_quarterly_growth([{}, {}, {}, {}, {}])["error"] == "EPS data missing or invalid"
    )
    missing_revenue = _quarters(1.2, 1.0, 120, 0)
    assert calculate_quarterly_growth(missing_revenue)["error"] == "Revenue data missing or invalid"

    turnaround = calculate_quarterly_growth(_quarters(0.5, -1.0, 130, 100))
    assert turnaround["latest_qtr_eps_growth"] == 150.0
    assert turnaround["score"] == 100


def test_current_earnings_score_and_interpretation_bands():
    assert score_current_earnings(35, 20) == 80
    assert score_current_earnings(20, 12) == 60
    assert score_current_earnings(12, 2) == 40
    assert score_current_earnings(5, 20) == 0
    assert "Strong" in interpret_earnings_score(80, 35, 20)
    assert "Acceptable" in interpret_earnings_score(60, 20, 12)
    assert "Below threshold" in interpret_earnings_score(40, 12, 2)
    assert "Weak" in interpret_earnings_score(0, -5, 1)


def test_earnings_acceleration_branches():
    assert detect_earnings_acceleration([])["trend"] == "unknown"

    accelerating = _quarters(2.0, 1.0, 130, 100)
    assert detect_earnings_acceleration(accelerating)["trend"] == "accelerating"

    decelerating = _quarters(1.1, 1.0, 130, 100)
    decelerating[1]["eps"] = 2.0
    decelerating[5]["eps"] = 1.0
    assert detect_earnings_acceleration(decelerating)["trend"] == "decelerating"

    stable = _quarters(1.1, 1.0, 130, 100)
    stable[1]["eps"] = 1.08
    stable[5]["eps"] = 1.0
    assert detect_earnings_acceleration(stable)["trend"] == "stable"


def _annual(eps_values: list[float], revenues: list[int] | None = None):
    revenues = revenues or [160, 140, 120, 100]
    return [
        {"date": f"{2025 - i}-12-31", "eps": eps, "revenue": revenue}
        for i, (eps, revenue) in enumerate(zip(eps_values, revenues, strict=True))
    ]


def test_annual_growth_success_erratic_and_error_paths():
    result = calculate_annual_growth(_annual([3.5, 2.4, 1.7, 1.0], [400, 250, 160, 100]))
    assert result["score"] == 100
    assert result["stability"] == "stable"

    erratic = calculate_annual_growth(_annual([2.5, 1.8, 2.0, 1.6]))
    assert erratic["stability"] == "erratic"

    assert calculate_annual_growth([])["score"] == 50
    assert calculate_annual_growth([{}, {}, {}, {}])["error"].startswith("Missing EPS")
    assert calculate_annual_growth(_annual([2.0, 1.0, -1.0, 1.0]))["score"] == 0


def test_annual_growth_score_consistency_and_interpretation_bands():
    assert score_annual_growth(35, 30, True) == 80
    assert score_annual_growth(26, 20, True) == 60
    assert score_annual_growth(20, 15, False) == 30
    assert score_annual_growth(10, 8, True) == 10
    assert score_annual_growth(40, 5, False) == 72

    assert "Exceptional" in interpret_growth_score(95, 45, True)
    assert "Strong" in interpret_growth_score(75, 35, True)
    assert "Acceptable" in interpret_growth_score(55, 26, True)
    assert "Below threshold" in interpret_growth_score(35, 20, False)
    assert "Weak" in interpret_growth_score(0, 5, False)

    assert check_consistency([])["interpretation"] == "Insufficient data"
    consistency = check_consistency(_annual([3.0, 2.0, 2.5, 1.0]))
    assert consistency["down_years"] == 1
    assert consistency["consecutive_growth_years"] == 1


def test_newness_calculator_and_score_bands():
    breakout = calculate_newness(
        {"price": 99.8, "yearHigh": 100.0, "yearLow": 50.0, "volume": 150, "avgVolume": 100}
    )
    assert breakout["score"] == 100
    assert breakout["breakout_detected"] is True
    assert calculate_newness({})["error"] == "Quote data missing"
    assert calculate_newness({"price": 10})["error"] == "Price or 52-week high data missing"

    assert score_newness(-8, True) == 80
    assert score_newness(-12, False) == 60
    assert score_newness(-20, False) == 40
    assert score_newness(-30, False) == 20


def _volume_days(up_volume: int, down_volume: int) -> dict:
    historical = []
    close = 100.0
    for i in range(60):
        close += 1 if i % 2 == 0 else -1
        historical.append(
            {
                "date": f"2025-02-{(i % 28) + 1:02d}",
                "close": close,
                "volume": up_volume if i % 2 == 0 else down_volume,
            }
        )
    return {"historical": list(reversed(historical))}


def test_supply_demand_success_errors_and_bands():
    result = calculate_supply_demand(_volume_days(up_volume=200, down_volume=100))
    assert result["score"] == 100
    assert result["accumulation_detected"] is True

    assert calculate_supply_demand({})["error"] == "No historical price data provided"
    assert calculate_supply_demand({"historical": []})["error"].startswith("Insufficient data")
    flat = {"historical": [{"close": 100, "volume": 100} for _ in range(60)]}
    assert calculate_supply_demand(flat)["error"] == "Insufficient up/down days for analysis"

    assert score_supply_demand(1.7) == 80
    assert score_supply_demand(1.2) == 60
    assert score_supply_demand(0.8) == 40
    assert score_supply_demand(0.6) == 20
    assert score_supply_demand(0.4) == 0
    assert "Distribution" in interpret_supply_demand(0.6, False)


def _price_series(start: float, end: float, days: int = 60, *, descending: bool = False):
    step = (end - start) / (days - 1)
    prices = [
        {"date": f"2025-01-{(i % 28) + 1:02d}", "close": start + step * i} for i in range(days)
    ]
    return list(reversed(prices)) if descending else prices


def test_leadership_success_fallback_errors_and_sector_rank():
    stock = _price_series(100, 180)
    benchmark = _price_series(100, 120)
    result = calculate_leadership(stock, benchmark)
    assert result["score"] == 100
    assert result["relative_performance"] == 60.0

    descending = calculate_leadership(
        _price_series(100, 120, descending=True), sp500_performance=10
    )
    assert descending["relative_performance"] == 10.0

    fallback = calculate_leadership(stock)
    assert fallback["quality_warning"] is not None
    assert fallback["score"] < 100

    assert calculate_leadership([])["error"].startswith("Insufficient")
    invalid = [{"date": f"2025-01-{i:02d}", "close": 0} for i in range(1, 61)]
    assert calculate_leadership(invalid)["error"].startswith("Invalid start price")

    assert score_leadership(35, True) == (95, 95)
    assert score_leadership(15, True) == (80, 80)
    assert score_leadership(7, True) == (70, 70)
    assert score_leadership(-7, True) == (40, 40)
    assert score_leadership(-15, True) == (20, 25)
    assert score_leadership(-25, True) == (0, 10)

    no_sector = calculate_sector_relative_strength(10, [])
    assert no_sector["error"] == "No sector data available"
    sector = calculate_sector_relative_strength(50, [10, 20, 30, 40])
    assert sector["sector_rank"] == 1
    assert sector["is_sector_leader"] is True


def test_scorer_phase1_phase2_phase3_and_interpretation_bands():
    assert interpret_composite_score(95)["rating"] == "Exceptional+"
    assert interpret_composite_score(85)["rating"] == "Exceptional"
    assert interpret_composite_score(75)["rating"] == "Strong"
    assert interpret_composite_score(65)["rating"] == "Above Average"
    assert interpret_composite_score(55)["rating"] == "Average"
    assert interpret_composite_score(45)["rating"] == "Below Average"
    assert interpret_composite_score(35)["rating"] == "Weak"

    phase1 = calculate_composite_score(100, 80, 60, 40)
    assert phase1["weakest_component"] == "M"
    assert phase1["component_scores"]["C"] == 100

    phase2 = calculate_composite_score_phase2(100, 90, 80, 70, 60, 50)
    assert phase2["weakest_component"] == "M"
    assert phase2["component_scores"]["I"] == 60

    phase3 = calculate_composite_score_phase3(100, 90, 80, 70, 60, 50, 40)
    assert phase3["weakest_component"] == "M"
    assert phase3["component_scores"]["L"] == 60


def test_scorer_threshold_and_full_canslim_branches():
    assert check_minimum_thresholds(60, 50, 40, 40)["recommendation"] == "buy"
    assert check_minimum_thresholds(50, 50, 40, 40)["recommendation"] == "watchlist"
    assert check_minimum_thresholds(50, 40, 30, 40)["recommendation"] == "avoid"
    assert check_minimum_thresholds(90, 90, 90, 0)["failed_components"] == ["M"]

    assert check_minimum_thresholds_phase2(60, 50, 40, 40, 40, 40)["recommendation"] == "buy"
    assert check_minimum_thresholds_phase2(50, 50, 40, 40, 40, 40)["recommendation"] == "watchlist"
    assert check_minimum_thresholds_phase2(50, 40, 30, 40, 40, 40)["recommendation"] == "avoid"
    assert check_minimum_thresholds_phase2(90, 90, 90, 90, 90, 0)["failed_components"] == ["M"]

    assert check_minimum_thresholds_phase3(60, 50, 40, 40, 50, 40, 40)["recommendation"] == "buy"
    assert (
        check_minimum_thresholds_phase3(50, 50, 40, 40, 50, 40, 40)["recommendation"] == "watchlist"
    )
    assert check_minimum_thresholds_phase3(50, 40, 30, 40, 50, 40, 40)["recommendation"] == "avoid"
    assert check_minimum_thresholds_phase3(90, 90, 90, 90, 90, 90, 0)["failed_components"] == ["M"]
    leadership_fail = check_minimum_thresholds_phase3(90, 90, 90, 90, 35, 90, 90)
    assert leadership_fail["recommendation"] == "avoid"
    assert "L" in leadership_fail["failed_components"]

    assert compare_to_full_canslim(95)["equivalent_rating"] == "Exceptional"
    assert compare_to_full_canslim(85)["equivalent_rating"] == "Strong"
    assert compare_to_full_canslim(75)["equivalent_rating"] == "Above Average"
    assert compare_to_full_canslim(65)["equivalent_rating"] == "Average"
    assert compare_to_full_canslim(55)["equivalent_rating"] == "Below Average"
