"""Tests for the CANSLIM Finviz stock client."""

from finviz_stock_client import FinvizStockClient


class _Response:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Session:
    def __init__(self, response=None, *, error=None):
        self.response = response or _Response()
        self.error = error
        self.calls = []
        self.headers = {}

    def get(self, url, timeout):
        self.calls.append((url, timeout))
        if self.error:
            raise self.error
        return self.response


def _snapshot_html():
    return """
    <html>
      <body>
        <table class="snapshot-table2">
          <tr>
            <td>Inst Own</td><td>60.50%</td>
            <td>Inst Trans</td><td>-1.25%</td>
          </tr>
          <tr>
            <td>Market Cap</td><td>3.0T</td>
            <td>RSI</td><td>55.0</td>
          </tr>
        </table>
      </body>
    </html>
    """


class TestFinvizStockClientParsing:
    def test_init_sets_user_agent_header(self):
        client = FinvizStockClient(rate_limit_seconds=0)

        assert "User-Agent" in client.session.headers

    def test_parse_percentage(self):
        assert FinvizStockClient._parse_percentage("60.50%") == 60.5
        assert FinvizStockClient._parse_percentage("-1.25%") == -1.25
        assert FinvizStockClient._parse_percentage("-") is None
        assert FinvizStockClient._parse_percentage("") is None
        assert FinvizStockClient._parse_percentage(None) is None
        assert FinvizStockClient._parse_percentage("bad") is None

    def test_parse_finviz_page_extracts_snapshot_pairs(self):
        client = FinvizStockClient(rate_limit_seconds=0)

        data = client._parse_finviz_page(_snapshot_html())

        assert data["Inst Own"] == "60.50%"
        assert data["Inst Trans"] == "-1.25%"
        assert data["Market Cap"] == "3.0T"
        assert data["RSI"] == "55.0"


class TestRateLimitedFetch:
    def test_fetch_success_parses_page(self):
        client = FinvizStockClient(rate_limit_seconds=0)
        session = _Session(_Response(status_code=200, text=_snapshot_html()))
        client.session = session

        data = client._rate_limited_fetch("AAPL")

        assert data["Inst Own"] == "60.50%"
        assert session.calls == [(f"{client.BASE_URL}?t=AAPL", 15)]
        assert client.last_request_time > 0

    def test_fetch_non_200_returns_none(self, capsys):
        client = FinvizStockClient(rate_limit_seconds=0)
        client.session = _Session(_Response(status_code=503, text="unavailable"))

        assert client._rate_limited_fetch("AAPL") is None
        assert "Finviz request failed with status 503" in capsys.readouterr().err

    def test_fetch_exception_returns_none(self, capsys):
        client = FinvizStockClient(rate_limit_seconds=0)
        client.session = _Session(error=RuntimeError("network down"))

        assert client._rate_limited_fetch("AAPL") is None
        assert "Failed to fetch Finviz data for AAPL" in capsys.readouterr().err
        assert client.last_request_time > 0


class TestInstitutionalOwnership:
    def test_get_institutional_ownership_success_and_cache(self):
        client = FinvizStockClient(rate_limit_seconds=0)
        calls = []

        def fake_fetch(symbol):
            calls.append(symbol)
            return {"Inst Own": "60.50%", "Inst Trans": "-1.25%"}

        client._rate_limited_fetch = fake_fetch

        first = client.get_institutional_ownership("AAPL")
        second = client.get_institutional_ownership("AAPL")

        assert first == {"inst_own_pct": 60.5, "inst_trans_pct": -1.25, "error": None}
        assert second == first
        assert calls == ["AAPL"]

    def test_get_institutional_ownership_error_is_cached(self):
        client = FinvizStockClient(rate_limit_seconds=0)
        calls = []

        def fake_fetch(symbol):
            calls.append(symbol)
            return None

        client._rate_limited_fetch = fake_fetch

        first = client.get_institutional_ownership("MSFT")
        second = client.get_institutional_ownership("MSFT")

        assert first["inst_own_pct"] is None
        assert first["inst_trans_pct"] is None
        assert "Failed to fetch data from Finviz for MSFT" == first["error"]
        assert second == first
        assert calls == ["MSFT"]


class TestStockData:
    def test_get_stock_data_success_and_cache(self):
        client = FinvizStockClient(rate_limit_seconds=0)
        calls = []

        def fake_fetch(symbol):
            calls.append(symbol)
            return {"Inst Own": "60.50%"}

        client._rate_limited_fetch = fake_fetch

        first = client.get_stock_data("NVDA")
        second = client.get_stock_data("NVDA")

        assert first == {"Inst Own": "60.50%"}
        assert second == first
        assert calls == ["NVDA"]

    def test_get_stock_data_returns_none_without_caching_failures(self):
        client = FinvizStockClient(rate_limit_seconds=0)
        calls = []

        def fake_fetch(symbol):
            calls.append(symbol)
            return None

        client._rate_limited_fetch = fake_fetch

        assert client.get_stock_data("TSLA") is None
        assert client.get_stock_data("TSLA") is None
        assert calls == ["TSLA", "TSLA"]
