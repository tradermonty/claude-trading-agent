"""Claude Managed Agents API client wrapper for Streamlit chat streaming."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Literal, NotRequired, TypedDict

from anthropic import Anthropic
from config.settings import (
    AGENT_ID,
    AGENT_NAME,
    AGENT_SYSTEM_PROMPT,
    CANSLIM_SCREENER_SKILL_ID,
    DEFAULT_MODEL,
    BREAKOUT_TRADE_PLANNER_SKILL_ID,
    EARNINGS_CALENDAR_SKILL_ID,
    ECONOMIC_CALENDAR_SKILL_ID,
    ENVIRONMENT_ID,
    ENVIRONMENT_NAME,
    FMP_API_KEY,
    FTD_DETECTOR_SKILL_ID,
    MACRO_REGIME_DETECTOR_SKILL_ID,
    MARKET_BREADTH_ANALYZER_SKILL_ID,
    SCENARIO_ANALYZER_SKILL_ID,
    THEME_DETECTOR_SKILL_ID,
    VCP_SCREENER_SKILL_ID,
)

logger = logging.getLogger(__name__)


class StreamChunk(TypedDict):
    """Normalized stream payload consumed by the Streamlit UI."""

    type: Literal["text_delta", "tool_use", "tool_result", "error", "done", "file_created"]
    content: NotRequired[str]
    file_name: NotRequired[str]
    file_content: NotRequired[str]


class ManagedAgentClient:
    """Manages Managed Agents resources (agent, environment) and streams sessions."""

    def __init__(self) -> None:
        self._client = Anthropic()
        self._agent_id: str = AGENT_ID
        self._environment_id: str = ENVIRONMENT_ID
        self._session_id: str | None = None

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def environment_id(self) -> str:
        return self._environment_id

    @property
    def session_id(self) -> str | None:
        return self._session_id

    def ensure_agent(self) -> str:
        """Return existing agent ID or create a new agent."""
        if self._agent_id:
            logger.info("Reusing existing agent: %s", self._agent_id)
            return self._agent_id

        logger.info("Creating new agent: %s", AGENT_NAME)
        skills = _build_skills_list()
        system = _build_system_prompt(AGENT_SYSTEM_PROMPT)
        agent = self._client.beta.agents.create(
            name=AGENT_NAME,
            model=DEFAULT_MODEL,
            system=system,
            tools=[{"type": "agent_toolset_20260401"}],
            **({"skills": skills} if skills else {}),
        )
        self._agent_id = agent.id
        logger.info("Agent created: %s (version %s)", agent.id, agent.version)
        return self._agent_id

    def ensure_environment(self) -> str:
        """Return existing environment ID or create a new environment."""
        if self._environment_id:
            logger.info("Reusing existing environment: %s", self._environment_id)
            return self._environment_id

        logger.info("Creating new environment: %s", ENVIRONMENT_NAME)
        environment = self._client.beta.environments.create(
            name=ENVIRONMENT_NAME,
            config={
                "type": "cloud",
                "networking": {"type": "unrestricted"},
            },
        )
        self._environment_id = environment.id
        logger.info("Environment created: %s", environment.id)
        return self._environment_id

    def create_session(self, title: str = "Chat session") -> str:
        """Create a new session tied to the current agent and environment."""
        agent_id = self.ensure_agent()
        env_id = self.ensure_environment()

        session = self._client.beta.sessions.create(
            agent=agent_id,
            environment_id=env_id,
            title=title,
        )
        self._session_id = session.id
        logger.info("Session created: %s", session.id)
        return self._session_id

    def ensure_session(self) -> str:
        """Return existing session ID or create a new one."""
        if self._session_id:
            return self._session_id
        return self.create_session()

    def send_message_streaming(
        self,
        user_message: str,
        *,
        system_supplement: str = "",
        reference_context: str = "",
    ) -> Iterator[StreamChunk]:
        """Send a user message and yield StreamChunk events.

        When a skill is triggered, system_supplement and reference_context
        are used to create a skill-specific agent and a fresh session.
        """
        if system_supplement:
            # Create a skill-specific agent with enriched system prompt
            session_id = self._create_skill_session(system_supplement)
        else:
            session_id = self.ensure_session()

        # Build message content blocks with local datetime context
        content_blocks: list[dict[str, str]] = []
        if reference_context:
            content_blocks.append({"type": "text", "text": reference_context})

        from datetime import datetime
        now = datetime.now().astimezone()
        date_ctx = now.strftime("[Current: %Y-%m-%d (%a) %H:%M %Z]")
        content_blocks.append({"type": "text", "text": f"{date_ctx}\n\n{user_message}"})

        try:
            with self._client.beta.sessions.events.stream(session_id) as stream:
                self._client.beta.sessions.events.send(
                    session_id,
                    events=[
                        {
                            "type": "user.message",
                            "content": content_blocks,
                        },
                    ],
                )

                for event in stream:
                    for chunk in self._process_event(event):
                        yield chunk
                        if chunk.get("type") == "done":
                            return

        except Exception as exc:
            logger.exception("Streaming failed for session %s", session_id)
            yield {"type": "error", "content": str(exc)}

    def _create_skill_session(self, system_supplement: str) -> str:
        """Create a dedicated agent + session for a skill invocation."""
        env_id = self.ensure_environment()

        base_system = f"{AGENT_SYSTEM_PROMPT}\n\n{system_supplement}"
        combined_system = _build_system_prompt(base_system)
        logger.info("Creating skill agent (system prompt: %d chars)", len(combined_system))

        skills = _build_skills_list()
        agent = self._client.beta.agents.create(
            name=f"{AGENT_NAME} (skill)",
            model=DEFAULT_MODEL,
            system=combined_system,
            tools=[{"type": "agent_toolset_20260401"}],
            **({"skills": skills} if skills else {}),
        )
        logger.info("Skill agent created: %s", agent.id)

        session = self._client.beta.sessions.create(
            agent=agent.id,
            environment_id=env_id,
            title="Skill session",
        )
        logger.info("Skill session created: %s", session.id)
        return session.id

    def _process_event(self, event: object) -> Iterator[StreamChunk]:
        """Convert a Managed Agents SSE event into StreamChunk(s)."""
        event_type = getattr(event, "type", "")
        logger.debug("SSE event: type=%s", event_type)

        if event_type == "agent.message":
            for block in getattr(event, "content", []):
                text = getattr(block, "text", "")
                if text:
                    yield {"type": "text_delta", "content": text}

        elif event_type == "agent.tool_use":
            tool_name = getattr(event, "name", "unknown")
            yield {"type": "tool_use", "content": tool_name}

            # Capture file content from write tool
            if tool_name == "write":
                tool_input = getattr(event, "input", {})
                if isinstance(tool_input, dict):
                    file_path = tool_input.get("file_path", "")
                    file_content = tool_input.get("content", "")
                    if file_path and file_content:
                        import os
                        from agent.sanitizer import sanitize as _sanitize_content
                        yield {
                            "type": "file_created",
                            "file_name": os.path.basename(file_path),
                            "file_content": _sanitize_content(file_content),
                        }

        elif event_type == "agent.tool_result":
            yield {"type": "tool_result", "content": "done"}

        elif event_type == "session.status_idle":
            yield {"type": "done", "content": self._session_id or ""}

        elif event_type == "agent.error":
            error_msg = getattr(event, "error", {})
            yield {"type": "error", "content": str(error_msg)}

    def reset_session(self) -> None:
        """Clear the current session so a new one is created on next message."""
        self._session_id = None


def _build_system_prompt(base_prompt: str) -> str:
    """Append API key instructions to the system prompt."""
    parts = [base_prompt]
    if FMP_API_KEY:
        parts.append(
            "\n\n## Available API Keys\n\n"
            "The following API keys are pre-configured. "
            "Use them when running scripts that require external API access. "
            "NEVER display these keys to the user.\n\n"
            f"- FMP (Financial Modeling Prep): "
            f"Set `export FMP_API_KEY='{FMP_API_KEY}'` before running scripts, "
            f"or pass via `--api-key {FMP_API_KEY}` flag."
        )
    return "\n".join(parts)


def _build_skills_list() -> list[dict[str, str]]:
    """Build the skills list from configured skill IDs."""
    skills: list[dict[str, str]] = []
    for skill_id in [
        SCENARIO_ANALYZER_SKILL_ID,
        FTD_DETECTOR_SKILL_ID,
        VCP_SCREENER_SKILL_ID,
        MACRO_REGIME_DETECTOR_SKILL_ID,
        CANSLIM_SCREENER_SKILL_ID,
        THEME_DETECTOR_SKILL_ID,
        MARKET_BREADTH_ANALYZER_SKILL_ID,
        EARNINGS_CALENDAR_SKILL_ID,
        ECONOMIC_CALENDAR_SKILL_ID,
        BREAKOUT_TRADE_PLANNER_SKILL_ID,
    ]:
        if skill_id:
            skills.append({
                "type": "custom",
                "skill_id": skill_id,
                "version": "latest",
            })
    return skills
