"""Main-orchestrator smoke tests for theme_detector without network I/O."""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path

import pytest
import theme_detector


def test_parse_args_reads_cli_flags(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "sys.argv",
        [
            "theme_detector.py",
            "--fmp-api-key",
            "fmp",
            "--finviz-api-key",
            "finviz",
            "--finviz-mode",
            "elite",
            "--output-dir",
            str(tmp_path),
            "--top",
            "4",
            "--max-themes",
            "7",
            "--max-stocks-per-theme",
            "6",
            "--themes-config",
            "themes.yaml",
            "--discover-themes",
            "--dynamic-stocks",
            "--dynamic-min-cap",
            "mid",
        ],
    )

    args = theme_detector.parse_args()

    assert args.fmp_api_key == "".join(["f", "mp"])
    assert args.finviz_api_key == "".join(["fin", "viz"])
    assert args.finviz_mode == "elite"
    assert args.output_dir == str(tmp_path)
    assert args.top == 4
    assert args.max_themes == 7
    assert args.max_stocks_per_theme == 6
    assert args.themes_config == "themes.yaml"
    assert args.discover_themes is True
    assert args.dynamic_stocks is True
    assert args.dynamic_min_cap == "mid"


def _args(tmp_path: Path, **overrides):
    values = {
        "fmp_api_key": None,
        "finviz_api_key": None,
        "finviz_mode": "public",
        "output_dir": str(tmp_path),
        "top": 2,
        "max_themes": 3,
        "max_stocks_per_theme": 2,
        "themes_config": None,
        "discover_themes": False,
        "dynamic_stocks": False,
        "dynamic_min_cap": "small",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class _FakeScanner:
    def __init__(self, fmp_api_key=None):
        self.fmp_api_key = fmp_api_key

    def batch_stock_metrics(self, symbols):
        return [
            {
                "symbol": symbol,
                "rsi_14": 62,
                "price_vs_52w_high_pct": -4,
                "pe": 32,
            }
            for symbol in symbols
        ]

    def batch_etf_volume_ratios(self, symbols):
        return {symbol: {"vol_20d": 2_000_000, "vol_60d": 1_000_000} for symbol in symbols}

    def backend_stats(self):
        return {
            "stock": {"fmp_calls": 1, "fmp_failures": 0, "yf_calls": 0, "yf_fallbacks": 0},
            "etf": {"fmp_calls": 1, "fmp_failures": 0, "yf_calls": 0, "yf_fallbacks": 0},
        }


def _patch_runtime(monkeypatch, tmp_path: Path, *, discover=False, dynamic=False):
    monkeypatch.setattr(
        theme_detector,
        "parse_args",
        lambda: _args(tmp_path, discover_themes=discover, dynamic_stocks=dynamic),
    )

    config_loader = importlib.import_module("config_loader")
    monkeypatch.setattr(
        config_loader,
        "load_themes_config",
        lambda _: (
            {
                "cross_sector_min_matches": 1,
                "vertical_min_industries": 2,
                "cross_sector": [],
            },
            {"AI Infrastructure": 3},
        ),
    )

    finviz_client = importlib.import_module("finviz_performance_client")
    monkeypatch.setattr(
        finviz_client,
        "get_industry_performance",
        lambda: [
            {
                "name": "Semiconductors",
                "perf_1w": 0.04,
                "perf_1m": 0.10,
                "perf_3m": 0.20,
                "perf_6m": 0.30,
                "perf_1y": 0.40,
                "perf_ytd": 0.15,
            },
            {
                "name": "Software - Infrastructure",
                "perf_1w": 0.03,
                "perf_1m": 0.08,
                "perf_3m": 0.18,
                "perf_6m": 0.25,
                "perf_1y": 0.35,
                "perf_ytd": 0.12,
            },
        ],
    )
    monkeypatch.setattr(finviz_client, "cap_outlier_performances", lambda industries: industries)

    monkeypatch.setattr(
        theme_detector,
        "classify_themes",
        lambda ranked, config: [
            {
                "theme_name": "AI Infrastructure",
                "direction": "bullish",
                "matching_industries": ranked,
                "proxy_etfs": ["SMH"],
                "static_stocks": ["NVDA", "AVGO"],
                "sector_weights": {"Technology": 1.0},
                "theme_origin": "seed",
                "name_confidence": "high",
            }
        ],
    )

    classifier = importlib.import_module("calculators.theme_classifier")
    monkeypatch.setattr(classifier, "enrich_vertical_themes", lambda themes: None)
    monkeypatch.setattr(classifier, "deduplicate_themes", lambda themes: themes)
    monkeypatch.setattr(classifier, "get_matched_industry_names", lambda themes: {"Semiconductors"})

    discoverer = importlib.import_module("calculators.theme_discoverer")
    monkeypatch.setattr(
        discoverer,
        "discover_themes",
        lambda ranked, matched, existing, top_n=30: [
            {
                "theme_name": "Cybersecurity",
                "direction": "bullish",
                "matching_industries": ranked[:1],
                "proxy_etfs": [],
                "static_stocks": ["PANW"],
                "sector_weights": {"Technology": 1.0},
                "theme_origin": "discovered",
                "name_confidence": "medium",
            }
        ],
    )

    etf_scanner = importlib.import_module("etf_scanner")
    monkeypatch.setattr(etf_scanner, "ETFScanner", _FakeScanner)

    uptrend_client = importlib.import_module("uptrend_client")
    monkeypatch.setattr(
        uptrend_client,
        "fetch_sector_uptrend_data",
        lambda: {
            "Technology": {"ratio": 0.72, "ma_10": 0.68, "slope": 0.02, "latest_date": "2026-05-08"}
        },
    )
    monkeypatch.setattr(
        uptrend_client, "is_data_stale", lambda latest_date, threshold_bdays=2: False
    )

    monkeypatch.setattr(
        theme_detector,
        "save_reports",
        lambda json_report, md_report, output_dir: {
            "json": str(Path(output_dir) / "theme_report.json"),
            "markdown": str(Path(output_dir) / "theme_report.md"),
        },
    )


def test_main_orchestrates_static_theme_pipeline(monkeypatch, tmp_path, capsys):
    _patch_runtime(monkeypatch, tmp_path)

    theme_detector.main()

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["report_type"] == "theme_detector"
    assert payload["summary"]["total_themes"] == 1
    theme = payload["themes"]["all"][0]
    assert theme["name"] == "AI Infrastructure"
    assert theme["representative_stocks"] == ["AVGO", "NVDA"] or theme["representative_stocks"] == [
        "NVDA",
        "AVGO",
    ]
    assert theme["stock_data"] == "available"
    assert payload["metadata"]["data_sources"]["scanner_backend"]["stock"]["fmp_calls"] == 1


def test_main_orchestrates_discovery_and_dynamic_stock_metadata(monkeypatch, tmp_path, capsys):
    _patch_runtime(monkeypatch, tmp_path, discover=True, dynamic=True)

    selector_module = importlib.import_module("representative_stock_selector")

    class FakeSelector:
        def __init__(self, **kwargs):
            self.query_count = 1
            self.failure_count = 0
            self.status = "ok"
            self.source_states = {}

        def select_stocks(self, theme, max_stocks):
            return [
                {
                    "symbol": theme["static_stocks"][0],
                    "source": "fake",
                    "market_cap": 1_000_000_000,
                    "matched_industries": [i["name"] for i in theme["matching_industries"]],
                    "reasons": ["unit test"],
                    "composite_score": 0.9,
                }
            ]

    monkeypatch.setattr(selector_module, "RepresentativeStockSelector", FakeSelector)

    theme_detector.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"]["total_themes"] == 2
    assert payload["metadata"]["data_sources"]["discovered_themes"] == 1
    assert payload["metadata"]["data_sources"]["dynamic_stocks_queries"] == 1
    assert all(theme["stock_details"][0]["source"] == "fake" for theme in payload["themes"]["all"])


def test_main_exits_when_finviz_returns_no_industries(monkeypatch, tmp_path):
    _patch_runtime(monkeypatch, tmp_path)
    finviz_client = importlib.import_module("finviz_performance_client")
    monkeypatch.setattr(finviz_client, "get_industry_performance", lambda: [])

    with pytest.raises(SystemExit) as exc:
        theme_detector.main()

    assert exc.value.code == 1
