"""Tests for agent.sanitizer — verifies secret redaction and path handling."""

import os
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def _reload_sanitizer():
    """Reload sanitizer module so _KNOWN_SECRETS picks up patched env vars."""
    import importlib
    import agent.sanitizer

    with mock.patch.dict(os.environ, {
        "FMP_API_KEY": "test_fmp_key_32chars_abcdefghij",
        "ANTHROPIC_API_KEY": "sk-ant-api03-testkey1234567890abcdef",
    }):
        importlib.reload(agent.sanitizer)
        yield
    importlib.reload(agent.sanitizer)


def test_redacts_anthropic_key():
    from agent.sanitizer import sanitize

    text = "Key is sk-ant-fake00-AAAAAAAAAAAAAAAAAAAABBBBBBBBBB"
    result = sanitize(text)
    assert "sk-ant-" not in result
    assert "[REDACTED" in result


def test_redacts_known_fmp_key():
    from agent.sanitizer import sanitize

    text = "export FMP_API_KEY='test_fmp_key_32chars_abcdefghij'"
    result = sanitize(text)
    assert "test_fmp_key_32chars_abcdefghij" not in result
    assert "[REDACTED_API_KEY]" in result


def test_redacts_long_tokens():
    from agent.sanitizer import sanitize

    token = "A" * 50
    text = f"token={token}"
    result = sanitize(text)
    assert token not in result
    assert "[REDACTED_TOKEN]" in result


def test_preserves_normal_text():
    from agent.sanitizer import sanitize

    text = "The VCP pattern shows a 15% contraction in AAPL."
    assert sanitize(text) == text


def test_redacts_absolute_paths():
    from agent.sanitizer import sanitize

    text = "File at /Users/johndoe/projects/secret/data.csv"
    result = sanitize(text)
    assert "/Users/johndoe" not in result


def test_project_paths_become_relative():
    from agent.sanitizer import sanitize

    cwd = os.getcwd()
    text = f"Reading {cwd}/app.py"
    result = sanitize(text)
    # Absolute project path should be stripped to relative
    assert cwd not in result
    assert "app.py" in result


def test_home_path_becomes_tilde():
    from agent.sanitizer import sanitize

    home = os.path.expanduser("~")
    text = f"Config at {home}/.config/app.json"
    result = sanitize(text)
    assert home not in result
    assert "~/.config/app.json" in result
