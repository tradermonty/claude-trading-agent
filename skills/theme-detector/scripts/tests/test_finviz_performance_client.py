"""Tests for finviz_performance_client parsing, fetch wrappers, and outlier handling."""

import math

import finviz_performance_client
from finviz_performance_client import (
    HARD_CAPS,
    _apply_hard_caps,
    _dataframe_to_dicts,
    _parse_perf_value,
    cap_outlier_performances,
    get_industry_performance,
    get_sector_performance,
)


class _Row(dict):
    @property
    def index(self):
        return self.keys()


class _DataFrame:
    def __init__(self, rows):
        self._rows = [_Row(row) for row in rows]

    def iterrows(self):
        return enumerate(self._rows)


class _Performance:
    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def screener_view(self, group):
        self.calls.append(group)
        if self.error:
            raise self.error
        return _DataFrame(
            [
                {
                    "Name": f"{group} A",
                    "Perf Week": "12.5%",
                    "Perf Month": "0.05",
                    "Perf Quart": None,
                    "Perf Half": 0.2,
                    "Perf Year": "bad",
                    "Perf YTD": "",
                }
            ]
        )


class TestParsePerformanceValues:
    def test_parse_perf_value_accepts_supported_shapes(self):
        assert _parse_perf_value(0.12) == 0.12
        assert _parse_perf_value(2) == 2.0
        assert _parse_perf_value("0.12%") == 0.12
        assert _parse_perf_value("12.5%") == 0.125
        assert _parse_perf_value(" 0.05 ") == 0.05

    def test_parse_perf_value_rejects_empty_invalid_and_nan(self):
        assert _parse_perf_value(None) is None
        assert _parse_perf_value("") is None
        assert _parse_perf_value("n/a") is None
        assert _parse_perf_value(math.nan) is None


class TestDataFrameConversion:
    def test_dataframe_to_dicts_maps_columns_and_skips_blank_names(self):
        df = _DataFrame(
            [
                {
                    "Name": " Technology ",
                    "Perf Week": "12.5%",
                    "Perf Month": "0.05",
                    "Perf Quart": "bad",
                },
                {"Name": "   ", "Perf Week": "1.0"},
            ]
        )

        rows = _dataframe_to_dicts(df)

        assert rows == [
            {
                "name": "Technology",
                "perf_1w": 0.125,
                "perf_1m": 0.05,
                "perf_3m": None,
                "perf_6m": None,
                "perf_1y": None,
                "perf_ytd": None,
            }
        ]


class TestFetchPerformance:
    def test_sector_performance_returns_empty_when_dependency_missing(self, monkeypatch, capsys):
        monkeypatch.setattr(finviz_performance_client, "HAS_FINVIZFINANCE", False)

        assert get_sector_performance() == []
        assert "finvizfinance not installed" in capsys.readouterr().err

    def test_industry_performance_returns_empty_when_dependency_missing(self, monkeypatch, capsys):
        monkeypatch.setattr(finviz_performance_client, "HAS_FINVIZFINANCE", False)

        assert get_industry_performance() == []
        assert "finvizfinance not installed" in capsys.readouterr().err

    def test_sector_performance_fetches_sector_group(self, monkeypatch):
        perf = _Performance()

        class FVPerf:
            @staticmethod
            def Performance():
                return perf

        monkeypatch.setattr(finviz_performance_client, "HAS_FINVIZFINANCE", True)
        monkeypatch.setattr(finviz_performance_client, "fvperf", FVPerf)

        rows = get_sector_performance()

        assert perf.calls == ["Sector"]
        assert rows[0]["name"] == "Sector A"
        assert rows[0]["perf_1w"] == 0.125

    def test_industry_performance_fetches_industry_group(self, monkeypatch):
        perf = _Performance()

        class FVPerf:
            @staticmethod
            def Performance():
                return perf

        monkeypatch.setattr(finviz_performance_client, "HAS_FINVIZFINANCE", True)
        monkeypatch.setattr(finviz_performance_client, "fvperf", FVPerf)

        rows = get_industry_performance()

        assert perf.calls == ["Industry"]
        assert rows[0]["name"] == "Industry A"

    def test_fetch_errors_return_empty_lists(self, monkeypatch, capsys):
        class FVPerf:
            @staticmethod
            def Performance():
                return _Performance(error=RuntimeError("bad response"))

        monkeypatch.setattr(finviz_performance_client, "HAS_FINVIZFINANCE", True)
        monkeypatch.setattr(finviz_performance_client, "fvperf", FVPerf)

        assert get_sector_performance() == []
        assert get_industry_performance() == []
        err = capsys.readouterr().err
        assert "Failed to fetch sector performance" in err
        assert "Failed to fetch industry performance" in err


class TestCapOutlierPerformances:
    def test_no_outliers(self):
        """Normal data should pass through unchanged."""
        data = [
            {"name": "A", "perf_1w": 2.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0},
            {"name": "B", "perf_1w": -1.0, "perf_1m": 3.0, "perf_3m": 8.0, "perf_6m": 12.0},
        ]
        result = cap_outlier_performances(data)
        assert result[0]["perf_1w"] == 2.0
        assert result[1]["perf_1w"] == -1.0

    def test_outlier_capped(self):
        """Extreme outlier should be capped to z_threshold boundary."""
        data = [
            {"name": f"I{i}", "perf_1w": 2.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0}
            for i in range(20)
        ]
        # Add extreme outlier
        data.append(
            {"name": "Outlier", "perf_1w": 99.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0}
        )
        result = cap_outlier_performances(data)
        outlier = next(r for r in result if r["name"] == "Outlier")
        # Should be capped and original preserved
        assert outlier["perf_1w"] < 99.0
        assert outlier.get("raw_perf_1w") == 99.0

    def test_raw_fields_preserved(self):
        """When an outlier is capped, raw_perf_* should store original value."""
        data = [
            {"name": f"I{i}", "perf_1w": 2.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0}
            for i in range(20)
        ]
        data.append(
            {"name": "Extreme", "perf_1w": -99.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0}
        )
        result = cap_outlier_performances(data)
        extreme = next(r for r in result if r["name"] == "Extreme")
        assert "raw_perf_1w" in extreme
        assert extreme["raw_perf_1w"] == -99.0

    def test_none_values_skipped(self):
        """None performance values should not cause errors."""
        data = [
            {"name": "A", "perf_1w": 2.0, "perf_1m": None, "perf_3m": 10.0, "perf_6m": 15.0},
            {"name": "B", "perf_1w": None, "perf_1m": 3.0, "perf_3m": 8.0, "perf_6m": 12.0},
        ]
        result = cap_outlier_performances(data)
        assert result[0]["perf_1m"] is None
        assert result[1]["perf_1w"] is None

    def test_empty_input(self):
        assert cap_outlier_performances([]) == []

    def test_small_dataset_skipped(self):
        """With fewer than 5 entries, z-score winsorization should not apply
        but hard caps still apply."""
        data = [
            {"name": "A", "perf_1w": 99.0, "perf_1m": 5.0, "perf_3m": 10.0, "perf_6m": 15.0},
        ]
        result = cap_outlier_performances(data)
        # Hard cap clips to 30.0 even for small datasets
        assert result[0]["perf_1w"] == HARD_CAPS["perf_1w"]


class TestApplyHardCaps:
    def test_perf_1w_capped_positive(self):
        """perf_1w exceeding +30% should be capped to +30%."""
        data = [{"name": "A", "perf_1w": 87.0}]
        _apply_hard_caps(data)
        assert data[0]["perf_1w"] == 30.0
        assert data[0]["raw_perf_1w"] == 87.0

    def test_perf_1w_capped_negative(self):
        """perf_1w below -30% should be capped to -30%."""
        data = [{"name": "A", "perf_1w": -100.0}]
        _apply_hard_caps(data)
        assert data[0]["perf_1w"] == -30.0
        assert data[0]["raw_perf_1w"] == -100.0

    def test_within_cap_unchanged(self):
        """Values within hard cap range should not be modified."""
        data = [{"name": "A", "perf_1w": 15.0, "perf_1m": -40.0, "perf_3m": 50.0}]
        _apply_hard_caps(data)
        assert data[0]["perf_1w"] == 15.0
        assert data[0]["perf_1m"] == -40.0
        assert data[0]["perf_3m"] == 50.0
        assert "raw_perf_1w" not in data[0]
        assert "raw_perf_1m" not in data[0]
        assert "raw_perf_3m" not in data[0]

    def test_raw_not_overwritten_by_second_stage(self):
        """raw_perf_* set by hard cap should not be overwritten by z-score stage."""
        data = [{"name": f"I{i}", "perf_1w": 5.0} for i in range(20)]
        # Add one that triggers hard cap
        data.append({"name": "Extreme", "perf_1w": 50.0})
        cap_outlier_performances(data)
        extreme = next(r for r in data if r["name"] == "Extreme")
        # raw_perf_1w should store original 50.0 (from hard cap), not 30.0
        assert extreme["raw_perf_1w"] == 50.0

    def test_none_values_skipped(self):
        """None perf values should be skipped without error."""
        data = [{"name": "A", "perf_1w": None, "perf_1m": 70.0}]
        _apply_hard_caps(data)
        assert data[0]["perf_1w"] is None
        assert data[0]["perf_1m"] == 60.0

    def test_all_perf_keys_capped(self):
        """All perf_* keys should be capped at their respective limits."""
        data = [
            {
                "name": "A",
                "perf_1w": 999.0,
                "perf_1m": 999.0,
                "perf_3m": 999.0,
                "perf_6m": 999.0,
                "perf_1y": 999.0,
                "perf_ytd": 999.0,
            }
        ]
        _apply_hard_caps(data)
        for key, cap in HARD_CAPS.items():
            assert data[0][key] == cap
