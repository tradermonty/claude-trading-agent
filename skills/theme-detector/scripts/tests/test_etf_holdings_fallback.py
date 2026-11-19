"""ETF-holdings fallback regressions found in the #106 cloud verification (#108).

- Unscored ETF rows with the same symbol must merge without KeyError.
- FMP ``marketValue`` is the ETF's position value, never issuer market cap.
- Non-US listings (exchange suffix such as ``.TO``) are not representative
  stocks for this US-equity app.
"""

from unittest.mock import MagicMock, patch

from representative_stock_selector import RepresentativeStockSelector


def _etf_row(symbol, etf):
    return {
        "symbol": symbol,
        "source": "etf_holdings",
        "market_cap": 0,
        "change": None,
        "volume": None,
        "matched_industries": [],
        "reasons": [f"Held by {etf}"],
    }


def _holdings_response(items):
    resp = MagicMock(status_code=200)
    resp.json.return_value = items
    return resp


class TestMergeUnscoredDuplicates:
    def test_duplicate_etf_symbols_merge_without_error(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        result = sel._merge_and_rank([_etf_row("NEM", "GDX"), _etf_row("NEM", "GDXJ")], 10)
        assert [r["symbol"] for r in result] == ["NEM"]
        assert result[0]["reasons"] == ["Held by GDX", "Held by GDXJ"]
        assert result[0]["composite_score"] == 0

    def test_scored_row_supplies_identity_when_unscored_duplicate_comes_first(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        etf = dict(_etf_row("NEM", "GDX"), holding_value=2_879_514_497)
        scored = dict(
            _etf_row("NEM", "x"),
            source="finviz_public",
            market_cap=60_000_000_000,
            change=1.5,
            composite_score=0.7,
        )
        result = sel._merge_and_rank([etf, scored], 10)
        assert result[0]["composite_score"] == 0.7
        assert result[0]["source"] == "finviz_public"
        assert result[0]["market_cap"] == 60_000_000_000
        assert result[0]["change"] == 1.5
        assert "holding_value" not in result[0]

    def test_lower_scored_duplicate_does_not_override_identity(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        scored = dict(
            _etf_row("NEM", "x"), source="finviz_public", market_cap=5, composite_score=0.7
        )
        result = sel._merge_and_rank([scored, _etf_row("NEM", "GDX")], 10)
        assert result[0]["source"] == "finviz_public"
        assert result[0]["market_cap"] == 5

    def test_merge_does_not_mutate_cached_rows(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        sel._etf_cache = {
            "GDX": [_etf_row("NEM", "GDX")],
            "GDXJ": [_etf_row("NEM", "GDXJ")],
        }
        theme = {"direction": "bullish", "matching_industries": [], "proxy_etfs": ["GDX", "GDXJ"]}
        first = sel.select_stocks(theme, max_stocks=10)
        second = sel.select_stocks(theme, max_stocks=10)
        assert sel._etf_cache["GDX"][0]["reasons"] == ["Held by GDX"]
        assert sel._etf_cache["GDXJ"][0]["reasons"] == ["Held by GDXJ"]
        assert first[0]["reasons"] == second[0]["reasons"] == ["Held by GDX", "Held by GDXJ"]

    def test_select_stocks_with_overlapping_etfs_does_not_raise(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        holdings = {
            "GDX": [_etf_row("NEM", "GDX"), _etf_row("AEM", "GDX")],
            "GDXJ": [_etf_row("NEM", "GDXJ"), _etf_row("KGC", "GDXJ")],
        }
        theme = {"direction": "bullish", "matching_industries": [], "proxy_etfs": ["GDX", "GDXJ"]}
        with patch.object(sel, "_fetch_etf_holdings", side_effect=lambda etf, limit: holdings[etf]):
            result = sel.select_stocks(theme, max_stocks=10)
        assert sorted(r["symbol"] for r in result) == ["AEM", "KGC", "NEM"]
        assert {r["source"] for r in result} == {"etf_holdings"}


class TestEtfHoldingsFields:
    def _fetch(self, items):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        with patch(
            "representative_stock_selector.requests.get",
            return_value=_holdings_response(items),
        ):
            return sel._fetch_etf_holdings("GDX", limit=10)

    def test_market_value_is_holding_value_not_market_cap(self):
        rows = self._fetch([{"asset": "NEM", "marketValue": 2879514497}])
        assert rows[0]["market_cap"] == 0  # unknown sentinel
        assert rows[0]["holding_value"] == 2879514497
        assert rows[0]["composite_score"] == 0
        assert rows[0]["source"] == "etf_holdings"

    def test_non_us_listings_are_skipped(self):
        foreign = ["CCO.TO", "U-U.TO", "KAP.IL", "BP.L", "7203.T", "ABC.V", "ABC.F", "700", "BRK.B"]
        us = ["OKLO", "BRK-B", "GOOGL", "F", "BAC-PL"]
        rows = self._fetch([{"asset": t, "marketValue": 1} for t in foreign + us])
        assert [r["symbol"] for r in rows] == us

    def test_null_or_blank_asset_is_skipped_without_failing_the_etf(self):
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        items = [{"asset": None}, {"asset": "  "}, {"marketValue": 1}, {"asset": "NEM"}]
        with patch(
            "representative_stock_selector.requests.get",
            return_value=_holdings_response(items),
        ):
            rows = sel._fetch_etf_holdings("GDX", limit=10)
        assert [r["symbol"] for r in rows] == ["NEM"]
        assert rows[0]["holding_value"] == 0
        assert sel._source_states["fmp"].consecutive_failures == 0

    def test_limit_counts_only_kept_rows(self):
        items = [{"asset": f"X{i}.TO", "marketValue": 1} for i in range(5)]
        items += [{"asset": "NEM", "marketValue": 1}, {"asset": "AEM", "marketValue": 1}]
        sel = RepresentativeStockSelector(fmp_api_key="test_key", rate_limit_sec=0)
        with patch(
            "representative_stock_selector.requests.get",
            return_value=_holdings_response(items),
        ):
            rows = sel._fetch_etf_holdings("GDX", limit=1)
        assert [r["symbol"] for r in rows] == ["NEM"]
