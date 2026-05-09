"""Tests for agent.client.ManagedAgentClient — verifies skill session handling and feature flag rollback path."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


@pytest.fixture
def patched_client(monkeypatch):
    """Build a ManagedAgentClient with all anthropic SDK calls mocked.

    Patches the symbols imported into ``agent.client`` (NOT the source modules)
    because client.py does ``from config.settings import AGENT_ID, ENVIRONMENT_ID``
    which binds those names locally — patching ``config.settings.AGENT_ID`` is a no-op.
    """
    import agent.client as client_module

    monkeypatch.setattr(client_module, "AGENT_ID", "agent_seeded_123")
    monkeypatch.setattr(client_module, "ENVIRONMENT_ID", "env_seeded_456")

    mock_anthropic_class = MagicMock()
    mock_sdk = MagicMock()
    mock_anthropic_class.return_value = mock_sdk
    monkeypatch.setattr(client_module, "Anthropic", mock_anthropic_class)

    # sessions.events.stream is a context manager that yields an iterable.
    # Build a stream context that yields a single session.status_idle event
    # so the for-loop terminates promptly.
    idle_event = MagicMock()
    idle_event.type = "session.status_idle"
    stream_ctx = MagicMock()
    stream_ctx.__enter__ = MagicMock(return_value=iter([idle_event]))
    stream_ctx.__exit__ = MagicMock(return_value=False)
    mock_sdk.beta.sessions.events.stream.return_value = stream_ctx

    # Default returns for the resource creators.
    mock_sdk.beta.sessions.create.return_value = MagicMock(id="session_seeded_789")
    mock_sdk.beta.agents.create.return_value = MagicMock(id="agent_skill_new_111", version=1)

    client = client_module.ManagedAgentClient()
    client._session_id = "session_seeded_789"  # bypass ensure_session
    return client, mock_sdk


def _drain(it: Iterator[Any]) -> list[Any]:
    return list(it)


def _events_send_args(mock_sdk: MagicMock) -> dict[str, Any]:
    """Return the kwargs of the latest beta.sessions.events.send call."""
    return mock_sdk.beta.sessions.events.send.call_args.kwargs


class TestDefaultPath:
    """Verify the default (Phase 1 new) path: session reuse + skill_hint prepend."""

    def test_skill_request_does_not_create_new_agent(self, patched_client):
        client, mock_sdk = patched_client
        before = mock_sdk.beta.agents.create.call_count

        _drain(client.send_message_streaming(
            "show me VCP setups",
            system_supplement="## Active Skill: vcp-screener ...",
            reference_context="### vcp_methodology.md ...",
            skill_hint="Use the vcp-screener skill for this request: show me VCP setups",
        ))

        after = mock_sdk.beta.agents.create.call_count
        assert after - before == 0, "default path must not call agents.create"

    def test_default_path_reuses_session(self, patched_client):
        client, mock_sdk = patched_client
        before_session = client._session_id

        _drain(client.send_message_streaming(
            "show me VCP setups",
            system_supplement="anything",
            skill_hint="Use the vcp-screener skill",
        ))

        assert client._session_id == before_session
        # events.stream should be called with the seeded session id.
        stream_call = mock_sdk.beta.sessions.events.stream.call_args
        assert stream_call.args[0] == "session_seeded_789"

    def test_user_message_includes_skill_hint(self, patched_client):
        client, mock_sdk = patched_client

        _drain(client.send_message_streaming(
            "AAPL",
            skill_hint="Use the vcp-screener skill: AAPL",
        ))

        events = _events_send_args(mock_sdk)["events"]
        first_block_text = events[0]["content"][0]["text"]
        assert "Use the vcp-screener skill" in first_block_text

    def test_followup_keeps_same_session(self, patched_client):
        client, mock_sdk = patched_client

        _drain(client.send_message_streaming("first", skill_hint=""))
        first_stream_session = mock_sdk.beta.sessions.events.stream.call_args.args[0]

        _drain(client.send_message_streaming("second", skill_hint=""))
        second_stream_session = mock_sdk.beta.sessions.events.stream.call_args.args[0]

        assert first_stream_session == second_stream_session == "session_seeded_789"


class TestLegacyPath:
    """Verify rollback path (LEGACY_SKILL_SESSION=1): skill-specific agent + fresh session."""

    def test_legacy_flag_creates_new_skill_session(self, patched_client, monkeypatch):
        client, mock_sdk = patched_client
        monkeypatch.setenv("LEGACY_SKILL_SESSION", "1")
        agents_before = mock_sdk.beta.agents.create.call_count
        sessions_before = mock_sdk.beta.sessions.create.call_count

        _drain(client.send_message_streaming(
            "show me VCP setups",
            system_supplement="## Active Skill: vcp-screener ...",
        ))

        agents_after = mock_sdk.beta.agents.create.call_count
        sessions_after = mock_sdk.beta.sessions.create.call_count
        assert agents_after - agents_before == 1, \
            "legacy path must call agents.create for the skill session"
        assert sessions_after - sessions_before == 1, \
            "legacy path must call sessions.create for the skill session"

    def test_legacy_flag_accepts_truthy_variants(self, patched_client, monkeypatch):
        # "TRUE" / "Yes" should also activate the legacy path.
        client, mock_sdk = patched_client
        monkeypatch.setenv("LEGACY_SKILL_SESSION", "TRUE")
        before = mock_sdk.beta.agents.create.call_count

        _drain(client.send_message_streaming(
            "show me VCP setups",
            system_supplement="## Active Skill: ...",
        ))

        assert mock_sdk.beta.agents.create.call_count - before == 1

    def test_legacy_path_receives_full_system_supplement(
        self, patched_client, monkeypatch
    ):
        # Rollback completeness: the legacy create_agent call must include the
        # full SKILL.md system_supplement that the pre-Phase-1 implementation
        # passed. Otherwise the feature flag wouldn't actually restore the
        # old behavior.
        client, mock_sdk = patched_client
        monkeypatch.setenv("LEGACY_SKILL_SESSION", "1")

        full_supplement = (
            "## Active Skill: vcp-screener\n\n"
            "Follow the workflow defined below to produce the analysis.\n\n"
            "# VCP Screener detailed instructions..."
        )

        _drain(client.send_message_streaming(
            "AAPL",
            system_supplement=full_supplement,
        ))

        agents_create_kwargs = mock_sdk.beta.agents.create.call_args.kwargs
        assert "Active Skill: vcp-screener" in agents_create_kwargs["system"]

    def test_no_skill_hint_in_legacy_path(self, patched_client, monkeypatch):
        # In legacy mode, skill_hint must NOT be prepended to the user message
        # because the legacy path conveys the skill via system prompt, not via
        # user-message hint.
        client, mock_sdk = patched_client
        monkeypatch.setenv("LEGACY_SKILL_SESSION", "1")

        _drain(client.send_message_streaming(
            "AAPL",
            system_supplement="## Active Skill: vcp-screener ...",
            skill_hint="Use the vcp-screener skill: AAPL",
        ))

        events = _events_send_args(mock_sdk)["events"]
        all_text = " ".join(b["text"] for b in events[0]["content"])
        assert "Use the vcp-screener skill" not in all_text


class TestSkillHintWithoutSystemSupplement:
    """If only skill_hint is provided (no legacy supplement), default path runs."""

    def test_skill_hint_only_uses_default_path(self, patched_client, monkeypatch):
        client, mock_sdk = patched_client
        # LEGACY env unset → default path
        before = mock_sdk.beta.agents.create.call_count

        _drain(client.send_message_streaming(
            "AAPL",
            skill_hint="Use the vcp-screener skill: AAPL",
        ))

        assert mock_sdk.beta.agents.create.call_count - before == 0
        events = _events_send_args(mock_sdk)["events"]
        assert "Use the vcp-screener skill" in events[0]["content"][0]["text"]
