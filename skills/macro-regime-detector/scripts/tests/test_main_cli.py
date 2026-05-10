"""Tests for macro_regime_detector.py CLI - output directory auto-creation."""

import sys
from unittest.mock import MagicMock, patch

import macro_regime_detector


def test_output_dir_created_when_missing(tmp_path, monkeypatch):
    """--output-dir に存在しないパスを渡しても FileNotFoundError が出ないこと"""
    new_dir = tmp_path / "nonexistent"
    assert not new_dir.exists()

    _fake_comp = {
        "score": 10,
        "signal": "No data",
        "data_available": True,
        "direction": "stable",
        "roc_3m": 0.0,
        "roc_12m": 0.0,
        "crossover": {"type": "none", "bars_ago": None},
        "momentum_qualifier": "",
    }

    monkeypatch.setattr(
        sys,
        "argv",
        ["macro_regime_detector.py", "--api-key", "FAKE_KEY", "--output-dir", str(new_dir)],
    )

    mock_client = MagicMock()
    mock_client.get_historical_prices.return_value = {
        "historical": [{"date": "2026-01-01", "close": 100.0}]
    }
    mock_client.get_treasury_rates.return_value = None
    mock_client.get_api_stats.return_value = {"api_calls_made": 0, "cache_entries": 0}

    with (
        patch("macro_regime_detector.FMPClient", return_value=mock_client),
        patch("macro_regime_detector.calculate_concentration", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_yield_curve", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_credit_conditions", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_size_factor", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_equity_bond", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_sector_rotation", return_value=_fake_comp),
    ):
        macro_regime_detector.main()

    assert new_dir.exists()


def test_exits_when_client_initialization_fails(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["macro_regime_detector.py"])

    with (
        patch("macro_regime_detector.FMPClient", side_effect=ValueError("missing credentials")),
        patch("sys.exit", side_effect=SystemExit(1)) as exit_mock,
    ):
        try:
            macro_regime_detector.main()
        except SystemExit:
            pass

    assert "ERROR: missing credentials" in capsys.readouterr().err
    exit_mock.assert_called_once_with(1)


def test_exits_when_spy_data_missing(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["macro_regime_detector.py"])

    mock_client = MagicMock()
    mock_client.get_historical_prices.return_value = {"historical": []}

    with (
        patch("macro_regime_detector.FMPClient", return_value=mock_client),
        patch("sys.exit", side_effect=SystemExit(1)) as exit_mock,
    ):
        try:
            macro_regime_detector.main()
        except SystemExit:
            pass

    captured = capsys.readouterr()
    assert "Fetching SPY (600 days)... OK (0 bars)" in captured.out
    assert "ERROR: Cannot proceed without SPY data" in captured.err
    exit_mock.assert_called_once_with(1)


def test_treasury_data_available_path(tmp_path, monkeypatch, capsys):
    new_dir = tmp_path / "macro"
    monkeypatch.setattr(sys, "argv", ["macro_regime_detector.py", "--output-dir", str(new_dir)])

    _fake_comp = {
        "score": 10,
        "signal": "No data",
        "data_available": True,
        "direction": "stable",
        "roc_3m": 0.0,
        "roc_12m": 0.0,
        "crossover": {"type": "none", "bars_ago": None},
        "momentum_qualifier": "",
    }

    mock_client = MagicMock()

    def fake_history(symbol, days):
        if symbol == "RSP":
            return None
        return {"historical": [{"date": "2026-01-01", "close": 100.0}]}

    mock_client.get_historical_prices.side_effect = fake_history
    mock_client.get_treasury_rates.return_value = [{"date": "2026-01-01", "year10": 4.0}]
    mock_client.get_api_stats.return_value = {"api_calls_made": 0, "cache_entries": 0}

    with (
        patch("macro_regime_detector.FMPClient", return_value=mock_client),
        patch("macro_regime_detector.calculate_concentration", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_yield_curve", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_credit_conditions", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_size_factor", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_equity_bond", return_value=_fake_comp),
        patch("macro_regime_detector.calculate_sector_rotation", return_value=_fake_comp),
    ):
        macro_regime_detector.main()

    output = capsys.readouterr().out
    assert "Fetching RSP (600 days)... FAILED" in output
    assert "Fetching Treasury rates... OK (1 entries)" in output
    assert new_dir.exists()
