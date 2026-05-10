"""Focused tests for CANSLIM report generation output contracts."""

import json

from report_generator import (
    format_stock_entry,
    generate_json_report,
    generate_markdown_report,
    generate_summary_stats,
    get_rating_emoji,
)


def _stock(score=91.0, **overrides):
    stock = {
        "symbol": "NVDA",
        "company_name": "NVIDIA Corporation",
        "price": 495.5,
        "market_cap": 1_220_000_000_000,
        "sector": "Technology",
        "composite_score": score,
        "rating": "Exceptional+",
        "rating_description": "Rare multi-bagger setup",
        "guidance": "Immediate buy, aggressive sizing",
        "weakest_component": "M",
        "weakest_score": 70,
        "c_component": {
            "score": 88,
            "latest_qtr_eps_growth": 42.3,
            "latest_qtr_revenue_growth": 31.5,
        },
        "a_component": {"score": 86, "eps_cagr_3yr": 27.2, "stability": "stable"},
        "n_component": {"score": 82, "distance_from_high_pct": -4.4},
        "s_component": {"score": 78, "up_down_ratio": 1.45},
        "l_component": {
            "score": 92,
            "stock_52w_performance": 64.0,
            "relative_performance": 42.0,
            "rs_rank_estimate": 96,
        },
        "i_component": {"score": 74, "num_holders": 1800, "ownership_pct": 64.2},
        "m_component": {"score": 70, "trend": "confirmed_uptrend"},
    }
    stock.update(overrides)
    return stock


def _metadata(**overrides):
    metadata = {
        "generated_at": "2026-05-09 00:00:00 UTC",
        "phase": "3 (7 components - FULL CANSLIM)",
        "components_included": ["C", "A", "N", "S", "L", "I", "M"],
        "candidates_analyzed": 1,
        "market_condition": {
            "trend": "confirmed_uptrend",
            "M_score": 70,
            "warning": None,
        },
    }
    metadata.update(overrides)
    return metadata


def test_json_report_includes_summary_stats(tmp_path):
    output = tmp_path / "report.json"
    results = [_stock(95), _stock(84), _stock(72), _stock(63), _stock(42)]

    generate_json_report(results, _metadata(candidates_analyzed=5), str(output))

    report = json.loads(output.read_text())
    assert report["summary"] == {
        "total_stocks": 5,
        "exceptional": 1,
        "strong": 1,
        "above_average": 1,
        "average": 1,
        "below_average": 1,
    }
    assert report["results"][0]["symbol"] == "NVDA"


def test_markdown_report_includes_market_warning(tmp_path):
    output = tmp_path / "report.md"
    metadata = _metadata(
        market_condition={
            "trend": "downtrend",
            "M_score": 20,
            "warning": "Market under distribution",
        }
    )

    generate_markdown_report([_stock()], metadata, str(output))

    content = output.read_text()
    assert "Market Condition Summary" in content
    assert "Market under distribution" in content


def test_format_stock_entry_includes_component_warnings_and_signal_flags():
    stock = _stock(
        c_component={"score": 40, "quality_warning": "C warning"},
        a_component={"score": 45, "quality_warning": "A warning"},
        n_component={"score": 80, "breakout_detected": True},
        s_component={
            "score": 75,
            "up_down_ratio": 1.8,
            "accumulation_detected": True,
            "quality_warning": "S warning",
        },
        l_component={"score": 70, "quality_warning": "L warning"},
        i_component={
            "score": 85,
            "num_holders": 100,
            "ownership_pct": 55.0,
            "superinvestor_present": True,
            "quality_warning": "I warning",
        },
        m_component={"score": 35, "trend": "under_pressure", "warning": "M warning"},
    )

    content = "\n".join(format_stock_entry(1, stock))

    assert "Breakout" in content
    assert "Accumulation" in content
    assert "Superinvestor" in content
    for warning in ("C warning", "A warning", "S warning", "L warning", "I warning", "M warning"):
        assert warning in content


def test_format_stock_entry_handles_missing_optional_component_values():
    stock = _stock(
        c_component={"score": 0},
        a_component={"score": 0},
        n_component={"score": 0},
        s_component={"score": 0},
        l_component={"score": 0},
        i_component={"score": 0},
        m_component={"score": 0},
    )

    content = "\n".join(format_stock_entry(1, stock))

    assert "EPS: N/A" in content
    assert "3yr CAGR: N/A" in content
    assert "N/A from 52wk high" in content
    assert "Up/Down Volume Ratio: N/A" in content
    assert "52wk: N/A (N/A)" in content
    assert "N/A holders, N/A ownership" in content
    assert "Unknown" in content


def test_rating_emoji_boundaries():
    assert get_rating_emoji(90) == "⭐⭐⭐"
    assert get_rating_emoji(80) == "⭐⭐"
    assert get_rating_emoji(70) == "⭐"
    assert get_rating_emoji(60) == "✓"
    assert get_rating_emoji(59.9) == ""


def test_generate_summary_stats_empty_results():
    assert generate_summary_stats([]) == {
        "total_stocks": 0,
        "exceptional": 0,
        "strong": 0,
        "above_average": 0,
        "average": 0,
        "below_average": 0,
    }
