"""Tests for Earnings Calendar scripts.

Covers:
- FMPEarningsCalendar helper methods (no API calls)
- Date validation
- Report generation (generate_report.py pure functions)
"""

import json
import sys

import pytest
import requests
from fetch_earnings_fmp import FMPEarningsCalendar, get_api_key, validate_date
from fetch_earnings_fmp import main as fetch_main
from generate_report import (
    calculate_summary_stats,
    format_revenue,
    generate_report,
    get_day_name,
    group_by_date,
    load_earnings_data,
)
from generate_report import (
    main as report_main,
)

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def client():
    """FMP client with dummy API key (no API calls made)."""
    return FMPEarningsCalendar(api_key="dummy-key")  # pragma: allowlist secret


@pytest.fixture
def sample_earnings():
    """Sample earnings data for testing."""
    return [
        {
            "symbol": "AAPL",
            "companyName": "Apple Inc.",
            "date": "2025-11-05",
            "timing": "AMC",
            "marketCap": 3_000_000_000_000,
            "marketCapFormatted": "$3.0T",
            "sector": "Technology",
            "industry": "Consumer Electronics",
            "epsEstimated": 1.55,
            "revenueEstimated": 89_500_000_000,
            "exchange": "NASDAQ",
        },
        {
            "symbol": "MSFT",
            "companyName": "Microsoft Corp",
            "date": "2025-11-04",
            "timing": "BMO",
            "marketCap": 2_500_000_000_000,
            "marketCapFormatted": "$2.5T",
            "sector": "Technology",
            "industry": "Software",
            "epsEstimated": 2.80,
            "revenueEstimated": 60_000_000_000,
            "exchange": "NASDAQ",
        },
        {
            "symbol": "JNJ",
            "companyName": "Johnson & Johnson",
            "date": "2025-11-04",
            "timing": "BMO",
            "marketCap": 400_000_000_000,
            "marketCapFormatted": "$400.0B",
            "sector": "Healthcare",
            "industry": "Drug Manufacturers",
            "epsEstimated": 2.60,
            "revenueEstimated": 22_000_000_000,
            "exchange": "NYSE",
        },
    ]


# ── normalize_timing ──────────────────────────────────────────────────


class TestNormalizeTiming:
    def test_bmo_variants(self, client):
        assert client.normalize_timing("bmo") == "BMO"
        assert client.normalize_timing("pre-market") == "BMO"
        assert client.normalize_timing("before market open") == "BMO"

    def test_amc_variants(self, client):
        assert client.normalize_timing("amc") == "AMC"
        assert client.normalize_timing("after-market") == "AMC"
        assert client.normalize_timing("after market close") == "AMC"

    def test_none_returns_tas(self, client):
        assert client.normalize_timing(None) == "TAS"

    def test_unknown_returns_tas(self, client):
        assert client.normalize_timing("unknown") == "TAS"
        assert client.normalize_timing("") == "TAS"


# ── format_market_cap ─────────────────────────────────────────────────


class TestFormatMarketCap:
    def test_trillion(self, client):
        assert client.format_market_cap(3_000_000_000_000) == "$3.0T"
        assert client.format_market_cap(1_500_000_000_000) == "$1.5T"

    def test_billion(self, client):
        assert client.format_market_cap(150_000_000_000) == "$150.0B"
        assert client.format_market_cap(2_000_000_000) == "$2.0B"

    def test_million(self, client):
        assert client.format_market_cap(500_000_000) == "$500M"

    def test_small(self, client):
        assert client.format_market_cap(999_999) == "$999,999"


# ── filter_by_market_cap ──────────────────────────────────────────────


class TestFilterByMarketCap:
    def test_filters_below_2b(self, client):
        earnings = [
            {"symbol": "BIG"},
            {"symbol": "SMALL"},
        ]
        profiles = {
            "BIG": {"mktCap": 10_000_000_000, "exchangeShortName": "NYSE"},
            "SMALL": {"mktCap": 500_000_000, "exchangeShortName": "NYSE"},
        }
        result = client.filter_by_market_cap(earnings, profiles)
        assert len(result) == 1
        assert result[0]["symbol"] == "BIG"

    def test_filters_non_us_exchanges(self, client):
        earnings = [{"symbol": "US"}, {"symbol": "UK"}]
        profiles = {
            "US": {"mktCap": 5_000_000_000, "exchangeShortName": "NYSE"},
            "UK": {"mktCap": 5_000_000_000, "exchangeShortName": "LSE"},
        }
        result = client.filter_by_market_cap(earnings, profiles)
        assert len(result) == 1
        assert result[0]["symbol"] == "US"

    def test_no_profile_excluded(self, client):
        earnings = [{"symbol": "NOPROFILE"}]
        profiles = {}
        result = client.filter_by_market_cap(earnings, profiles)
        assert len(result) == 0

    def test_enriches_with_profile_data(self, client):
        earnings = [{"symbol": "AAPL"}]
        profiles = {
            "AAPL": {
                "mktCap": 3_000_000_000_000,
                "companyName": "Apple Inc.",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "exchangeShortName": "NASDAQ",
            },
        }
        result = client.filter_by_market_cap(earnings, profiles)
        assert result[0]["companyName"] == "Apple Inc."
        assert result[0]["sector"] == "Technology"


# ── sort_earnings ─────────────────────────────────────────────────────


class TestSortEarnings:
    def test_sorted_by_date_then_timing_then_mcap(self, client):
        earnings = [
            {"date": "2025-11-05", "timing": "AMC", "marketCap": 100},
            {"date": "2025-11-04", "timing": "BMO", "marketCap": 200},
            {"date": "2025-11-04", "timing": "AMC", "marketCap": 300},
            {"date": "2025-11-04", "timing": "BMO", "marketCap": 500},
        ]
        result = client.sort_earnings(earnings)
        # 2025-11-04 first, BMO before AMC, higher mcap first within BMO
        assert result[0]["date"] == "2025-11-04"
        assert result[0]["timing"] == "BMO"
        assert result[0]["marketCap"] == 500
        assert result[1]["timing"] == "BMO"
        assert result[1]["marketCap"] == 200
        assert result[2]["timing"] == "AMC"


# ── validate_date ─────────────────────────────────────────────────────


class TestValidateDate:
    def test_valid_date(self):
        assert validate_date("2025-11-04") is True

    def test_invalid_format(self):
        assert validate_date("11-04-2025") is False
        assert validate_date("2025/11/04") is False

    def test_invalid_date(self):
        assert validate_date("2025-13-01") is False
        assert validate_date("not-a-date") is False


# ── Report generation helpers ─────────────────────────────────────────


class TestGroupByDate:
    def test_groups_correctly(self, sample_earnings):
        result = group_by_date(sample_earnings)
        assert "2025-11-04" in result
        assert "2025-11-05" in result
        assert len(result["2025-11-04"]["BMO"]) == 2
        assert len(result["2025-11-05"]["AMC"]) == 1

    def test_empty_input(self):
        assert group_by_date([]) == {}


class TestFormatRevenue:
    def test_trillion(self):
        assert format_revenue(1_500_000_000_000) == "$1.5T"

    def test_billion(self):
        assert format_revenue(89_500_000_000) == "$89.5B"

    def test_million(self):
        assert format_revenue(500_000_000) == "$500M"


class TestGetDayName:
    def test_known_date(self):
        result = get_day_name("2025-11-04")
        assert "Tuesday" in result
        assert "November" in result


class TestCalculateSummaryStats:
    def test_stats(self, sample_earnings):
        stats = calculate_summary_stats(sample_earnings)
        assert stats["total"] == 3
        assert stats["large_cap"] == 3  # all > $10B
        assert stats["mid_cap"] == 0
        assert stats["sectors"]["Technology"] == 2
        assert stats["sectors"]["Healthcare"] == 1
        assert stats["peak_count"] == 2  # Nov 4 has 2 entries


class TestGenerateReport:
    def test_report_contains_companies(self, sample_earnings):
        report = generate_report(sample_earnings)
        assert "AAPL" in report
        assert "MSFT" in report
        assert "JNJ" in report

    def test_empty_earnings(self):
        report = generate_report([])
        assert "No earnings data available" in report

    def test_report_has_sections(self, sample_earnings):
        report = generate_report(sample_earnings)
        assert "Executive Summary" in report
        assert "Key Observations" in report
        assert "Sector Distribution" in report


# ── FMP API client paths ───────────────────────────────────────────────


class _Response:
    def __init__(self, status_code=200, payload=None, *, raise_error=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else []
        self._raise_error = raise_error

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self._raise_error:
            raise self._raise_error


class TestFetchEarningsCalendar:
    def test_fetch_success(self, client, monkeypatch):
        monkeypatch.setattr(
            "fetch_earnings_fmp.requests.get",
            lambda *args, **kwargs: _Response(payload=[{"symbol": "AAPL"}]),
        )

        result = client.fetch_earnings_calendar("2025-11-01", "2025-11-07")

        assert result == [{"symbol": "AAPL"}]

    @pytest.mark.parametrize(
        ("response", "expected"),
        [
            (_Response(status_code=401), None),
            (_Response(status_code=429), None),
            (_Response(payload={"Error Message": "bad request"}), None),
        ],
    )
    def test_fetch_api_error_responses(self, client, monkeypatch, response, expected):
        monkeypatch.setattr("fetch_earnings_fmp.requests.get", lambda *args, **kwargs: response)

        assert client.fetch_earnings_calendar("2025-11-01", "2025-11-07") is expected

    @pytest.mark.parametrize(
        "exc",
        [
            requests.exceptions.Timeout(),
            requests.exceptions.ConnectionError(),
            RuntimeError("boom"),
        ],
    )
    def test_fetch_request_exceptions(self, client, monkeypatch, exc):
        def raise_exc(*args, **kwargs):
            raise exc

        monkeypatch.setattr("fetch_earnings_fmp.requests.get", raise_exc)

        assert client.fetch_earnings_calendar("2025-11-01", "2025-11-07") is None


class TestFetchCompanyProfiles:
    def test_fetch_profiles_batches_and_skips_failed_batch(self, client, monkeypatch):
        calls = []

        def fake_get(url, params, headers, timeout):
            calls.append(url)
            if len(calls) == 2:
                raise RuntimeError("temporary failure")
            return _Response(
                payload=[
                    {"symbol": "SYM0", "companyName": "Company 0"},
                    {"symbol": "SYM1", "companyName": "Company 1"},
                ]
            )

        monkeypatch.setattr("fetch_earnings_fmp.requests.get", fake_get)
        symbols = [f"SYM{i}" for i in range(101)]

        profiles = client.fetch_company_profiles(symbols)

        assert len(calls) == 2
        assert profiles["SYM0"]["companyName"] == "Company 0"
        assert "SYM100" not in profiles


class TestProcessEarnings:
    def test_process_standardizes_fields(self, client):
        result = client.process_earnings(
            [
                {
                    "symbol": "AAPL",
                    "companyName": "Apple Inc.",
                    "date": "2025-11-05",
                    "time": "before market open",
                    "marketCap": 3_000_000_000_000,
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "epsEstimated": 1.55,
                    "revenueEstimated": 89_500_000_000,
                    "fiscalDateEnding": "2025-09-30",
                    "exchange": "NASDAQ",
                }
            ]
        )

        assert result == [
            {
                "symbol": "AAPL",
                "companyName": "Apple Inc.",
                "date": "2025-11-05",
                "timing": "BMO",
                "marketCap": 3_000_000_000_000,
                "marketCapFormatted": "$3.0T",
                "sector": "Technology",
                "industry": "Consumer Electronics",
                "epsEstimated": 1.55,
                "revenueEstimated": 89_500_000_000,
                "fiscalDateEnding": "2025-09-30",
                "exchange": "NASDAQ",
            }
        ]


# ── CLI helpers and main paths ─────────────────────────────────────────


class TestFetchCli:
    def test_get_api_key_from_argv(self, monkeypatch):
        monkeypatch.setattr(
            sys, "argv", ["fetch_earnings_fmp.py", "2025-11-01", "2025-11-07", "demo"]
        )

        assert get_api_key() == "demo"

    def test_get_api_key_from_env(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fetch_earnings_fmp.py", "2025-11-01", "2025-11-07"])
        monkeypatch.setenv("FMP" + "_API_KEY", "demo")

        assert get_api_key() == "demo"

    def test_get_api_key_missing(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fetch_earnings_fmp.py", "2025-11-01", "2025-11-07"])
        monkeypatch.delenv("FMP" + "_API_KEY", raising=False)

        assert get_api_key() is None

    def test_main_help_and_invalid_args_exit(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fetch_earnings_fmp.py", "--help"])
        with pytest.raises(SystemExit) as help_exit:
            fetch_main()
        assert help_exit.value.code == 0

        monkeypatch.setattr(sys, "argv", ["fetch_earnings_fmp.py"])
        with pytest.raises(SystemExit) as missing_exit:
            fetch_main()
        assert missing_exit.value.code == 1

        monkeypatch.setattr(sys, "argv", ["fetch_earnings_fmp.py", "bad", "2025-11-07"])
        with pytest.raises(SystemExit) as invalid_exit:
            fetch_main()
        assert invalid_exit.value.code == 1

    def test_main_outputs_empty_json_when_no_earnings(self, monkeypatch, capsys):
        class FakeClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def fetch_earnings_calendar(self, start_date, end_date):
                return []

        monkeypatch.setattr(
            sys, "argv", ["fetch_earnings_fmp.py", "2025-11-01", "2025-11-07", "demo"]
        )
        monkeypatch.setattr("fetch_earnings_fmp.FMPEarningsCalendar", FakeClient)

        with pytest.raises(SystemExit) as exc:
            fetch_main()

        assert exc.value.code == 0
        assert json.loads(capsys.readouterr().out) == []

    def test_main_success_path(self, monkeypatch, capsys):
        class FakeClient:
            def __init__(self, api_key):
                self.api_key = api_key

            def fetch_earnings_calendar(self, start_date, end_date):
                return [{"symbol": "AAPL", "date": "2025-11-05", "time": "amc"}]

            def fetch_company_profiles(self, symbols):
                return {
                    "AAPL": {
                        "mktCap": 3_000_000_000_000,
                        "exchangeShortName": "NASDAQ",
                        "companyName": "Apple Inc.",
                        "sector": "Technology",
                        "industry": "Consumer Electronics",
                    }
                }

            def filter_by_market_cap(self, earnings, profiles):
                earnings[0].update(
                    {
                        "marketCap": profiles["AAPL"]["mktCap"],
                        "companyName": "Apple Inc.",
                        "sector": "Technology",
                        "industry": "Consumer Electronics",
                        "exchange": "NASDAQ",
                    }
                )
                return earnings

            def process_earnings(self, earnings):
                return [{"symbol": "AAPL", "date": "2025-11-05", "timing": "AMC", "marketCap": 1}]

            def sort_earnings(self, earnings):
                return earnings

        monkeypatch.setattr(
            sys, "argv", ["fetch_earnings_fmp.py", "2025-11-01", "2025-11-07", "demo"]
        )
        monkeypatch.setattr("fetch_earnings_fmp.FMPEarningsCalendar", FakeClient)

        fetch_main()

        assert json.loads(capsys.readouterr().out)[0]["symbol"] == "AAPL"


class TestReportCliAndLoaders:
    def test_load_earnings_data_accepts_progress_prefix(self, tmp_path):
        path = tmp_path / "earnings.json"
        path.write_text('progress...\n[{"symbol": "AAPL"}]\n')

        assert load_earnings_data(str(path)) == [{"symbol": "AAPL"}]

    @pytest.mark.parametrize(
        "content",
        [
            '{"symbol": "AAPL"}',
            "{not json",
        ],
    )
    def test_load_earnings_data_rejects_invalid_content(self, tmp_path, content):
        path = tmp_path / "earnings.json"
        path.write_text(content)

        with pytest.raises(SystemExit) as exc:
            load_earnings_data(str(path))

        assert exc.value.code == 1

    def test_load_earnings_data_missing_file(self, tmp_path):
        with pytest.raises(SystemExit) as exc:
            load_earnings_data(str(tmp_path / "does-not-exist-earnings.json"))

        assert exc.value.code == 1

    def test_report_main_writes_file(self, monkeypatch, tmp_path):
        input_path = tmp_path / "earnings.json"
        output_path = tmp_path / "report.md"
        input_path.write_text(
            json.dumps(
                [
                    {
                        "symbol": "AAPL",
                        "companyName": "Apple Inc.",
                        "date": "2025-11-05",
                        "timing": "AMC",
                        "marketCap": 3_000_000_000_000,
                        "marketCapFormatted": "$3.0T",
                        "sector": "Technology",
                    }
                ]
            )
        )

        monkeypatch.setattr(sys, "argv", ["generate_report.py", str(input_path), str(output_path)])

        report_main()

        assert output_path.exists()
        assert "AAPL" in output_path.read_text()

    def test_report_main_help_and_missing_arg_exit(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["generate_report.py", "--help"])
        with pytest.raises(SystemExit) as help_exit:
            report_main()
        assert help_exit.value.code == 0

        monkeypatch.setattr(sys, "argv", ["generate_report.py"])
        with pytest.raises(SystemExit) as missing_exit:
            report_main()
        assert missing_exit.value.code == 1
