"""Tests for agent.client.ManagedAgentClient — verifies session reuse semantics."""

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

    mock_sdk.beta.sessions.create.return_value = MagicMock(id="session_seeded_789")

    client = client_module.ManagedAgentClient()
    client._session_id = "session_seeded_789"  # bypass ensure_session
    return client, mock_sdk


def _drain(it: Iterator[Any]) -> list[Any]:
    return list(it)


def _events_send_args(mock_sdk: MagicMock) -> dict[str, Any]:
    """Return the kwargs of the latest beta.sessions.events.send call."""
    return mock_sdk.beta.sessions.events.send.call_args.kwargs


class TestSessionReuse:
    """Each call to send_message_streaming must reuse the existing session."""

    def test_does_not_create_new_agent(self, patched_client):
        client, mock_sdk = patched_client
        before = mock_sdk.beta.agents.create.call_count

        _drain(client.send_message_streaming("show me VCP setups"))

        after = mock_sdk.beta.agents.create.call_count
        assert after - before == 0, "skill routing must not call agents.create"

    def test_reuses_session_id(self, patched_client):
        client, mock_sdk = patched_client
        before_session = client._session_id

        _drain(client.send_message_streaming("show me VCP setups"))

        assert client._session_id == before_session
        stream_call = mock_sdk.beta.sessions.events.stream.call_args
        assert stream_call.args[0] == "session_seeded_789"

    def test_followup_keeps_same_session(self, patched_client):
        client, mock_sdk = patched_client

        _drain(client.send_message_streaming("first message"))
        first = mock_sdk.beta.sessions.events.stream.call_args.args[0]

        _drain(client.send_message_streaming("second message"))
        second = mock_sdk.beta.sessions.events.stream.call_args.args[0]

        assert first == second == "session_seeded_789"


class TestUserMessageContent:
    """User message content blocks are built consistently."""

    def test_user_message_is_first_content_block(self, patched_client):
        # The skill-routing prefix (when present) must be the FIRST content
        # block the agent sees, matching the Phase 2 A/B eval structure.
        client, mock_sdk = patched_client

        _drain(client.send_message_streaming(
            "Use the vcp-screener skill for this request: AAPL"
        ))

        events = _events_send_args(mock_sdk)["events"]
        assert events[0]["type"] == "user.message"
        first_block_text = events[0]["content"][0]["text"]
        assert first_block_text == "Use the vcp-screener skill for this request: AAPL"

    def test_date_context_is_second_block(self, patched_client):
        client, mock_sdk = patched_client

        _drain(client.send_message_streaming("plain message"))

        events = _events_send_args(mock_sdk)["events"]
        blocks = events[0]["content"]
        assert len(blocks) == 2
        assert blocks[0]["text"] == "plain message"
        assert blocks[1]["text"].startswith("[Current:")


class TestResetSession:
    """reset_session() must drop the session id and force a new create on next send."""

    def test_reset_clears_session_id(self, patched_client):
        client, _ = patched_client
        assert client._session_id == "session_seeded_789"
        client.reset_session()
        assert client._session_id is None
