"""Tests for shared FMP fallback helpers."""

from common.fmp_fallback import (
    FMP_FALLBACK_ENDPOINTS,
    normalize_historical_response,
    quote_response_matches,
    symbols_match,
)


def test_endpoint_registry_contains_quote_and_historical_fallbacks():
    assert [base for base, _ in FMP_FALLBACK_ENDPOINTS["quote"]] == [
        "https://financialmodelingprep.com/stable/quote",
        "https://financialmodelingprep.com/api/v3/quote",
    ]
    assert [base for base, _ in FMP_FALLBACK_ENDPOINTS["historical"]] == [
        "https://financialmodelingprep.com/stable/historical-price-full",
        "https://financialmodelingprep.com/api/v3/historical-price-full",
    ]


def test_symbols_match_tolerates_dash_dot_variants():
    assert symbols_match("BRK-B", "BRK.B")
    assert symbols_match("BRK.B", "BRK-B")
    assert not symbols_match("SPY", "^GSPC")


def test_quote_response_matches_single_symbol():
    assert quote_response_matches([{"symbol": "^GSPC"}], "^GSPC", is_single=True)
    assert not quote_response_matches([{"symbol": "SPY"}], "^GSPC", is_single=True)
    assert quote_response_matches([{"symbol": "SPY"}], "^GSPC,SPY", is_single=False)
    assert not quote_response_matches({"symbol": "^GSPC"}, "^GSPC", is_single=True)


def test_normalize_historical_v3_shape():
    data = {"symbol": "^GSPC", "historical": [{"close": 5000}]}
    assert normalize_historical_response(data, "^GSPC", is_single=True) == data
    assert normalize_historical_response(data, "SPY", is_single=True) is None


def test_normalize_historical_stock_list_shape():
    data = {
        "historicalStockList": [
            {"symbol": "SPY", "historical": [{"close": 500}]},
            {"symbol": "^GSPC", "historical": [{"close": 5000}]},
        ]
    }
    assert normalize_historical_response(data, "^GSPC", is_single=True) == {
        "symbol": "^GSPC",
        "historical": [{"close": 5000}],
    }
    assert normalize_historical_response(data, "QQQ", is_single=True) is None
