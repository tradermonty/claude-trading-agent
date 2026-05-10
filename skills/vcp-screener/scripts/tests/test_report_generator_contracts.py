"""Focused report-generator output contract tests for the VCP screener."""

from report_generator import _format_stock_entry, _rating_indicator, generate_markdown_report


def _stock(**overrides):
    stock = {
        "symbol": "AAPL",
        "company_name": "Apple Inc.",
        "sector": "Technology",
        "price": 195.0,
        "market_cap": 3_000_000_000_000,
        "composite_score": 84,
        "quality_rating": "Strong VCP",
        "rating": "Strong VCP",
        "execution_state": "PRE_BREAKOUT",
        "pattern_type": "VCP",
        "entry_ready": True,
        "guidance": "Watch for breakout confirmation.",
        "trend_template": {
            "score": 80,
            "criteria_passed": 6,
            "extended_penalty": -10,
            "raw_score": 90,
        },
        "vcp_pattern": {
            "score": 85,
            "num_contractions": 3,
            "contractions": [
                {"label": "C1", "depth_pct": 18.2},
                {"label": "C2", "depth_pct": 10.4},
                {"label": "C3", "depth_pct": 5.1},
                {"label": "C4", "depth_pct": 2.4},
                {"label": "C5", "depth_pct": 1.2},
            ],
            "pivot_price": 200.0,
        },
        "volume_pattern": {"score": 78, "dry_up_ratio": 0.42},
        "pivot_proximity": {
            "score": 82,
            "distance_from_pivot_pct": -1.5,
            "trade_status": "IN BUY ZONE",
            "stop_loss_price": 184.0,
            "risk_pct": 5.5,
        },
        "relative_strength": {
            "score": 88,
            "rs_percentile": 94,
            "weighted_rs": 22.4,
        },
    }
    stock.update(overrides)
    return stock


def _metadata(**overrides):
    metadata = {
        "generated_at": "2026-05-09 00:00:00 UTC",
        "universe_description": "Unit Test Universe",
        "funnel": {
            "universe": 20,
            "pre_filter_passed": 10,
            "trend_template_passed": 6,
            "vcp_candidates": 3,
        },
    }
    metadata.update(overrides)
    return metadata


def test_markdown_report_includes_api_usage_and_all_results_summary(tmp_path):
    output = tmp_path / "vcp.md"
    top_results = [_stock(symbol="AAPL", sector="Technology")]
    all_results = [
        _stock(symbol="AAPL", sector="Technology", rating="Strong VCP"),
        _stock(symbol="MSFT", sector="Technology", rating="Good VCP", entry_ready=False),
        _stock(symbol="XOM", sector="Energy", rating="Weak VCP", entry_ready=False),
    ]
    metadata = _metadata(api_stats={"api_calls_made": 42, "cache_entries": 7})

    generate_markdown_report(top_results, metadata, str(output), all_results=all_results)

    content = output.read_text()
    assert "Showing top 1 of 3 candidates" in content
    assert "### API Usage" in content
    assert "API Calls Made:** 42" in content
    assert "Cache Entries:** 7" in content
    assert "| Technology | 2 |" in content
    assert "| Energy | 1 |" in content
    assert "**Total VCP Candidates:** 3" in content


def test_format_stock_entry_includes_state_cap_and_extension_penalty():
    stock = _stock(state_cap_applied=True, rating="Developing VCP")

    content = "\n".join(_format_stock_entry(1, stock))

    assert "Strong VCP" in content
    assert "Developing VCP" in content
    assert "raw 90, ext -10" in content
    assert "C1=18.2%" in content
    assert "C4=2.4%" in content
    assert "C5=1.2%" not in content
    assert "RS Percentile: 94, Weighted RS: +22.4%" in content


def test_format_stock_entry_stop_violated_overrides_guidance():
    stock = _stock(
        pivot_proximity={
            "score": 10,
            "distance_from_pivot_pct": -9.0,
            "trade_status": "BELOW STOP LEVEL",
            "stop_loss_price": 184.0,
            "risk_pct": 2.0,
        }
    )

    content = "\n".join(_format_stock_entry(1, stock))

    assert "STOP VIOLATED" in content
    assert "setup invalidated" in content
    assert "Do not enter" in content


def test_format_stock_entry_overextended_trade_missed_messages():
    with_risk = _stock(
        pivot_proximity={
            "score": 20,
            "distance_from_pivot_pct": 12.5,
            "trade_status": "OVEREXTENDED",
            "risk_pct": 13.2,
        }
    )
    without_risk = _stock(
        vcp_pattern={"score": 85, "num_contractions": 0, "pivot_price": None},
        pivot_proximity={
            "score": 20,
            "distance_from_pivot_pct": 14.0,
            "trade_status": "EXTENDED",
        },
    )

    content_with_risk = "\n".join(_format_stock_entry(1, with_risk))
    content_without_risk = "\n".join(_format_stock_entry(2, without_risk))

    assert "requires 13.2% stop distance" in content_with_risk
    assert "Minervini advises against chasing >5% above pivot" in content_with_risk
    assert "Too far above pivot" in content_without_risk
    assert "Pivot: N/A" in content_without_risk


def test_format_stock_entry_chase_warning_and_missing_values():
    stock = _stock(
        market_cap=500_000_000,
        volume_pattern={"score": 0},
        relative_strength={"score": 50, "rs_rank_estimate": 72},
        pivot_proximity={
            "score": 50,
            "distance_from_pivot_pct": 7.0,
            "trade_status": "ABOVE BUY ZONE",
        },
    )

    content = "\n".join(_format_stock_entry(1, stock))

    assert "Market Cap:** $500M" in content
    assert "| Volume Pattern | 0/100 | N/A |" in content
    assert "RS Rank ~72" in content
    assert "Risk: N/A" in content
    assert "consider waiting for pullback to pivot" in content


def test_rating_indicator_boundaries():
    assert _rating_indicator(95) == "[TEXTBOOK]"
    assert _rating_indicator(85) == "[STRONG]"
    assert _rating_indicator(75) == "[GOOD]"
    assert _rating_indicator(65) == "[DEVELOPING]"
    assert _rating_indicator(55) == ""
    assert _rating_indicator(95, valid_vcp=False) == "[PATTERN NOT CONFIRMED]"
