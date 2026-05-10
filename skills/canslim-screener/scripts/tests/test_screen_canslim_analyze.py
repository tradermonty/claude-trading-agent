"""Focused tests for screen_canslim.analyze_stock orchestration."""

from unittest.mock import MagicMock, patch

import screen_canslim


def _client(
    *,
    profile=None,
    quote=None,
    quarterly=None,
    annual=None,
    historical_90=None,
    historical_365=None,
    holders=None,
):
    client = MagicMock()
    client.get_profile.return_value = profile
    client.get_quote.return_value = quote
    client.get_income_statement.side_effect = [quarterly, annual]

    def get_historical_prices(_symbol, days):
        if days == 90:
            return historical_90
        if days == 365:
            return historical_365
        raise AssertionError(f"unexpected days={days}")

    client.get_historical_prices.side_effect = get_historical_prices
    client.get_institutional_holders.return_value = holders
    return client


def _market_data():
    return {"score": 70, "trend": "confirmed_uptrend"}


def _composite():
    return {
        "composite_score": 73.5,
        "rating": "Strong",
        "rating_description": "Solid setup",
        "guidance": "Watchlist candidate",
        "weakest_component": "C",
        "weakest_score": 0,
    }


def test_analyze_stock_returns_none_when_profile_missing(capsys):
    client = _client(profile=None)

    assert screen_canslim.analyze_stock("AAPL", client, _market_data()) is None
    assert "Profile unavailable" in capsys.readouterr().out
    client.get_quote.assert_not_called()


def test_analyze_stock_returns_none_when_quote_missing(capsys):
    client = _client(profile=[{"companyName": "Apple Inc."}], quote=None)

    assert screen_canslim.analyze_stock("AAPL", client, _market_data()) is None
    assert "Quote unavailable" in capsys.readouterr().out
    client.get_income_statement.assert_not_called()


def test_analyze_stock_uses_fallback_components_when_optional_data_missing():
    client = _client(
        profile=[{"companyName": "Apple Inc.", "sector": "Technology", "mktCap": 1_000_000}],
        quote=[{"symbol": "AAPL", "price": 180.0, "yearHigh": 200.0, "yearLow": 120.0}],
        quarterly=None,
        annual=None,
        historical_90=None,
        historical_365=None,
        holders=None,
    )

    with (
        patch.object(screen_canslim, "calculate_newness", return_value={"score": 55}),
        patch.object(
            screen_canslim,
            "calculate_composite_score_phase3",
            return_value=_composite(),
        ) as composite,
        patch.object(
            screen_canslim,
            "check_minimum_thresholds_phase3",
            return_value={"passed": False},
        ) as thresholds,
    ):
        result = screen_canslim.analyze_stock("AAPL", client, _market_data())

    assert result is not None
    assert result["symbol"] == "AAPL"
    assert result["company_name"] == "Apple Inc."
    assert result["sector"] == "Technology"
    assert result["price"] == 180.0
    assert result["market_cap"] == 1_000_000
    assert result["c_component"] == {"score": 0, "error": "No quarterly data"}
    assert result["a_component"] == {"score": 50, "error": "No annual data"}
    assert result["s_component"] == {"score": 0, "error": "No price history data"}
    assert result["l_component"] == {"score": 0, "error": "No 52-week price history"}
    assert result["i_component"] == {"score": 0, "error": "No institutional holder data"}
    assert result["threshold_check"] == {"passed": False}
    composite.assert_called_once()
    thresholds.assert_called_once()


def test_analyze_stock_calls_all_component_calculators_with_available_data():
    quarterly = [{"eps": 2.1}]
    annual = [{"eps": 8.4}]
    historical_90 = {"historical": [{"close": 100.0}]}
    historical_365 = {"historical": [{"close": 90.0}, {"close": 100.0}]}
    holders = [{"holder": "Fund", "shares": 1000}]
    profile = [{"companyName": "NVIDIA", "sector": "Technology", "mktCap": 2_000_000}]
    quote = [{"symbol": "NVDA", "price": 500.0}]
    market_data = _market_data()
    client = _client(
        profile=profile,
        quote=quote,
        quarterly=quarterly,
        annual=annual,
        historical_90=historical_90,
        historical_365=historical_365,
        holders=holders,
    )

    with (
        patch.object(
            screen_canslim, "calculate_quarterly_growth", return_value={"score": 81}
        ) as calc_c,
        patch.object(
            screen_canslim, "calculate_annual_growth", return_value={"score": 82}
        ) as calc_a,
        patch.object(screen_canslim, "calculate_newness", return_value={"score": 83}) as calc_n,
        patch.object(
            screen_canslim, "calculate_supply_demand", return_value={"score": 84}
        ) as calc_s,
        patch.object(screen_canslim, "calculate_leadership", return_value={"score": 85}) as calc_l,
        patch.object(
            screen_canslim,
            "calculate_institutional_sponsorship",
            return_value={"score": 86},
        ) as calc_i,
        patch.object(screen_canslim, "calculate_composite_score_phase3", return_value=_composite()),
        patch.object(
            screen_canslim,
            "check_minimum_thresholds_phase3",
            return_value={"passed": True},
        ),
    ):
        result = screen_canslim.analyze_stock(
            "NVDA",
            client,
            market_data,
            sp500_historical={"historical": [{"close": 80.0}, {"close": 90.0}]},
        )

    assert result is not None
    assert result["c_component"] == {"score": 81}
    assert result["a_component"] == {"score": 82}
    assert result["n_component"] == {"score": 83}
    assert result["s_component"] == {"score": 84}
    assert result["l_component"] == {"score": 85}
    assert result["i_component"] == {"score": 86}
    assert result["m_component"] == market_data
    calc_c.assert_called_once_with(quarterly)
    calc_a.assert_called_once_with(annual)
    calc_n.assert_called_once_with(quote[0])
    calc_s.assert_called_once_with(historical_90)
    calc_l.assert_called_once_with(
        historical_365["historical"],
        sp500_historical=[{"close": 80.0}, {"close": 90.0}],
    )
    calc_i.assert_called_once_with(holders, profile[0], symbol="NVDA", use_finviz_fallback=True)


def test_analyze_stock_returns_none_on_unexpected_exception(capsys):
    client = _client(profile=[{"companyName": "Broken"}], quote=[{"price": 10.0}])
    client.get_income_statement.side_effect = RuntimeError("boom")

    assert screen_canslim.analyze_stock("BAD", client, _market_data()) is None
    assert "Error: boom" in capsys.readouterr().out
