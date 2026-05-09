"""Tests for the eval harness gates: prompt validation and legacy-env refusal."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_eval_module():
    spec = importlib.util.spec_from_file_location(
        "eval_skill_refs",
        PROJECT_ROOT / "scripts" / "eval_skill_refs.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


eval_mod = _load_eval_module()


class TestValidatePrompts:
    """validate_prompts must fail fast when prompts miss the target skill."""

    def test_all_prompts_routing_correctly_passes(self):
        # Every default market-breadth prompt should route to its skill.
        prompts = eval_mod.DEFAULT_PROMPTS["market-breadth-analyzer"]
        eval_mod.validate_prompts(prompts, "market-breadth-analyzer")

    def test_unmatched_prompt_exits(self):
        with pytest.raises(SystemExit) as exc:
            eval_mod.validate_prompts(
                ["What's the weather?"], "market-breadth-analyzer"
            )
        assert exc.value.code == 2

    def test_wrong_skill_match_exits(self):
        # "/vcp-screener" matches vcp-screener, not market-breadth-analyzer.
        with pytest.raises(SystemExit) as exc:
            eval_mod.validate_prompts(
                ["/vcp-screener"], "market-breadth-analyzer"
            )
        assert exc.value.code == 2


class TestLegacyEnvGate:
    """assert_no_legacy_env must refuse when LEGACY_SKILL_SESSION is set."""

    def test_unset_passes(self, monkeypatch):
        monkeypatch.delenv("LEGACY_SKILL_SESSION", raising=False)
        eval_mod.assert_no_legacy_env()  # no exception

    def test_truthy_exits(self, monkeypatch):
        for val in ["1", "true", "TRUE", "Yes"]:
            monkeypatch.setenv("LEGACY_SKILL_SESSION", val)
            with pytest.raises(SystemExit) as exc:
                eval_mod.assert_no_legacy_env()
            assert exc.value.code == 2

    def test_falsy_passes(self, monkeypatch):
        # "0", "", "false" should not trip the gate.
        for val in ["0", "", "false", "no"]:
            monkeypatch.setenv("LEGACY_SKILL_SESSION", val)
            eval_mod.assert_no_legacy_env()  # no exception


class TestCollectResponseErrorHandling:
    """Verify error-type chunks bubble up via had_error rather than being silently absorbed."""

    def test_error_chunk_sets_had_error_true(self, monkeypatch):
        # ManagedAgentClient catches internal exceptions and yields them as
        # {"type": "error", ...}. The eval harness must treat that as an error.
        client = MagicMock()
        client.send_message_streaming.return_value = iter([
            {"type": "text", "content": "partial output "},
            {"type": "error", "content": "rate limited"},
            {"type": "done"},
        ])
        # detect_skill is fine; we just want to drive the chunk loop.
        text, had_error = eval_mod.collect_response(client, "/breadth")
        assert had_error is True
        assert "rate limited" in text  # ERROR is also written into response file

    def test_clean_run_returns_had_error_false(self):
        client = MagicMock()
        client.send_message_streaming.return_value = iter([
            {"type": "text", "content": "score 75 across 6 components"},
            {"type": "done"},
        ])
        text, had_error = eval_mod.collect_response(client, "/breadth")
        assert had_error is False
        assert "score 75" in text

    def test_run_arm_counts_error_chunks(self, monkeypatch, tmp_path):
        # End-to-end: run_arm() must increment its error counter when the
        # client yields an error chunk, not just when it raises.
        captured: list[MagicMock] = []

        def fake_client_factory():
            c = MagicMock()
            c.send_message_streaming.return_value = iter([
                {"type": "error", "content": "stream failed"},
                {"type": "done"},
            ])
            captured.append(c)
            return c

        monkeypatch.setattr(eval_mod, "ManagedAgentClient", fake_client_factory)
        monkeypatch.delenv("SKILLS_REFS_DISABLED", raising=False)

        prompts = ["/breadth"]
        errors = eval_mod.run_arm("A", "market-breadth-analyzer", prompts, 2, tmp_path)
        # 1 prompt × 2 trials, both yielding error chunks → errors == 2
        assert errors == 2
