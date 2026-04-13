"""Tests for config.settings — verifies parser helpers and validation."""

import os
from unittest import mock

from config.settings import (
    _parse_log_format,
    _parse_log_level,
    _parse_positive_int,
    _parse_ui_locale,
    validate_runtime_environment,
)


class TestParsePositiveInt:
    def test_valid_int(self):
        assert _parse_positive_int("10", default=5) == 10

    def test_below_minimum_returns_default(self):
        assert _parse_positive_int("0", default=5, minimum=1) == 5

    def test_invalid_string_returns_default(self):
        assert _parse_positive_int("abc", default=5) == 5

    def test_whitespace_stripped(self):
        assert _parse_positive_int("  20  ", default=5) == 20


class TestParseUiLocale:
    def test_en(self):
        assert _parse_ui_locale("en") == "en"

    def test_ja(self):
        assert _parse_ui_locale("ja") == "ja"

    def test_unknown_defaults_to_en(self):
        assert _parse_ui_locale("fr") == "en"


class TestParseLogFormat:
    def test_text(self):
        assert _parse_log_format("text") == "text"

    def test_json(self):
        assert _parse_log_format("json") == "json"

    def test_unknown_defaults_to_text(self):
        assert _parse_log_format("xml") == "text"


class TestParseLogLevel:
    def test_valid_levels(self):
        for level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            assert _parse_log_level(level) == level

    def test_unknown_defaults_to_info(self):
        assert _parse_log_level("TRACE") == "INFO"


class TestValidateRuntimeEnvironment:
    def test_missing_api_key_returns_error(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False):
            # Need to reload to pick up the patched env
            import importlib
            import config.settings
            importlib.reload(config.settings)
            errors = config.settings.validate_runtime_environment()
            assert len(errors) > 0
            assert "ANTHROPIC_API_KEY" in errors[0]
            importlib.reload(config.settings)
