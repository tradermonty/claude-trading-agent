"""Tests for agent.client.ManagedAgentClient — verifies session reuse semantics."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
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

    def test_exposes_configured_resource_ids(self, patched_client):
        client, _ = patched_client

        assert client.agent_id == "agent_seeded_123"
        assert client.environment_id == "env_seeded_456"

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

        _drain(client.send_message_streaming("Use the vcp-screener skill for this request: AAPL"))

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


class TestResourceCreation:
    """Agent, environment, and session creation paths use the configured SDK calls."""

    def test_ensure_agent_reuses_existing_id(self, patched_client):
        client, mock_sdk = patched_client

        assert client.ensure_agent() == "agent_seeded_123"
        mock_sdk.beta.agents.create.assert_not_called()

    def test_ensure_agent_creates_when_missing(self, monkeypatch):
        import agent.client as client_module

        monkeypatch.setattr(client_module, "AGENT_ID", "")
        monkeypatch.setattr(client_module, "ENVIRONMENT_ID", "env_seeded_456")
        monkeypatch.setattr(client_module, "AGENT_NAME", "Test Agent")
        monkeypatch.setattr(client_module, "DEFAULT_MODEL", "claude-test")
        monkeypatch.setattr(client_module, "FMP_API_KEY", "")
        monkeypatch.setattr(client_module, "SCENARIO_ANALYZER_SKILL_ID", "skill_scenario")
        monkeypatch.setattr(client_module, "FTD_DETECTOR_SKILL_ID", "")
        monkeypatch.setattr(client_module, "VCP_SCREENER_SKILL_ID", "skill_vcp")
        monkeypatch.setattr(client_module, "MACRO_REGIME_DETECTOR_SKILL_ID", "")
        monkeypatch.setattr(client_module, "CANSLIM_SCREENER_SKILL_ID", "")
        monkeypatch.setattr(client_module, "THEME_DETECTOR_SKILL_ID", "")
        monkeypatch.setattr(client_module, "MARKET_BREADTH_ANALYZER_SKILL_ID", "")
        monkeypatch.setattr(client_module, "EARNINGS_CALENDAR_SKILL_ID", "")
        monkeypatch.setattr(client_module, "ECONOMIC_CALENDAR_SKILL_ID", "")
        monkeypatch.setattr(client_module, "BREAKOUT_TRADE_PLANNER_SKILL_ID", "")
        monkeypatch.setattr(client_module, "IBD_DISTRIBUTION_DAY_MONITOR_SKILL_ID", "")

        mock_sdk = MagicMock()
        mock_sdk.beta.agents.create.return_value = SimpleNamespace(
            id="agent_created_123",
            version="v1",
        )
        mock_anthropic_class = MagicMock(return_value=mock_sdk)
        monkeypatch.setattr(client_module, "Anthropic", mock_anthropic_class)

        client = client_module.ManagedAgentClient()

        assert client.ensure_agent() == "agent_created_123"
        mock_sdk.beta.agents.create.assert_called_once()
        kwargs = mock_sdk.beta.agents.create.call_args.kwargs
        assert kwargs["name"] == "Test Agent"
        assert kwargs["model"] == "claude-test"
        assert kwargs["skills"] == [
            {"type": "custom", "skill_id": "skill_scenario", "version": "latest"},
            {"type": "custom", "skill_id": "skill_vcp", "version": "latest"},
        ]

    def test_ensure_environment_creates_when_missing(self, monkeypatch):
        import agent.client as client_module

        monkeypatch.setattr(client_module, "AGENT_ID", "agent_seeded_123")
        monkeypatch.setattr(client_module, "ENVIRONMENT_ID", "")
        monkeypatch.setattr(client_module, "ENVIRONMENT_NAME", "Test Env")

        mock_sdk = MagicMock()
        mock_sdk.beta.environments.create.return_value = SimpleNamespace(id="env_created_123")
        monkeypatch.setattr(client_module, "Anthropic", MagicMock(return_value=mock_sdk))

        client = client_module.ManagedAgentClient()

        assert client.ensure_environment() == "env_created_123"
        mock_sdk.beta.environments.create.assert_called_once_with(
            name="Test Env",
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )

    def test_create_session_uses_current_agent_and_environment(self, patched_client):
        client, mock_sdk = patched_client
        client._session_id = None
        mock_sdk.beta.sessions.create.return_value = SimpleNamespace(id="session_created_123")

        assert client.create_session(title="Regression") == "session_created_123"
        mock_sdk.beta.sessions.create.assert_called_once_with(
            agent="agent_seeded_123",
            environment_id="env_seeded_456",
            title="Regression",
        )
        assert client.session_id == "session_created_123"

    def test_ensure_session_creates_when_missing(self, patched_client):
        client, mock_sdk = patched_client
        client._session_id = None
        mock_sdk.beta.sessions.create.return_value = SimpleNamespace(id="session_created_456")

        assert client.ensure_session() == "session_created_456"
        assert client.session_id == "session_created_456"


class TestEventProcessing:
    """Managed Agents SSE events are converted into UI-facing stream chunks."""

    def test_agent_message_yields_text_blocks(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(
            type="agent.message",
            content=[
                SimpleNamespace(text="first"),
                SimpleNamespace(text=""),
                SimpleNamespace(text="second"),
            ],
        )

        assert list(client._process_event(event)) == [
            {"type": "text", "content": "first"},
            {"type": "text", "content": "second"},
        ]

    def test_write_tool_use_yields_sanitized_file(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(
            type="agent.tool_use",
            name="write",
            input={
                "file_path": "reports/report.md",
                "content": "saved to /private/tmp/report-source.csv",
            },
        )

        chunks = list(client._process_event(event))

        assert chunks[0] == {"type": "tool_use", "content": "write"}
        assert chunks[1]["type"] == "file_created"
        assert chunks[1]["file_name"] == "report.md"
        assert "/private/tmp/report-source.csv" not in chunks[1]["file_content"]
        assert "[redacted-path]" in chunks[1]["file_content"]

    def test_non_write_tool_use_only_reports_tool_name(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(type="agent.tool_use", name="bash", input={"command": "date"})

        assert list(client._process_event(event)) == [{"type": "tool_use", "content": "bash"}]

    def test_tool_result_yields_done_marker(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(type="agent.tool_result")

        assert list(client._process_event(event)) == [{"type": "tool_result", "content": "done"}]

    def test_status_idle_yields_session_done(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(type="session.status_idle")

        assert list(client._process_event(event)) == [
            {"type": "done", "content": "session_seeded_789"}
        ]

    def test_agent_error_yields_error_chunk(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(type="agent.error", error={"message": "boom"})

        assert list(client._process_event(event)) == [
            {"type": "error", "content": "{'message': 'boom'}"}
        ]

    def test_unknown_event_yields_no_chunks(self, patched_client):
        client, _ = patched_client
        event = SimpleNamespace(type="session.unknown")

        assert list(client._process_event(event)) == []


class TestStreamingErrors:
    """SDK failures are surfaced as error chunks instead of escaping."""

    def test_streaming_exception_yields_error_chunk(self, patched_client):
        client, mock_sdk = patched_client
        mock_sdk.beta.sessions.events.stream.side_effect = RuntimeError("network down")

        assert list(client.send_message_streaming("hello")) == [
            {"type": "error", "content": "network down"}
        ]


class TestPromptAndSkillHelpers:
    """Module-level helpers include configured runtime context."""

    def test_build_system_prompt_adds_fmp_key_when_configured(self, monkeypatch):
        import agent.client as client_module

        monkeypatch.setattr(
            client_module, "FMP_API_KEY", "fmp_test_key"
        )  # pragma: allowlist secret

        prompt = client_module._build_system_prompt("base")

        assert prompt.startswith("base")
        assert "Available API Keys" in prompt
        assert "fmp_test_key" in prompt

    def test_build_system_prompt_without_fmp_key_is_base_prompt(self, monkeypatch):
        import agent.client as client_module

        monkeypatch.setattr(client_module, "FMP_API_KEY", "")

        assert client_module._build_system_prompt("base") == "base"
