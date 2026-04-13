"""Streamlit chat UI powered by Claude Managed Agents API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import streamlit as st
from agent.client import ManagedAgentClient
from agent.sanitizer import sanitize
from skills.registry import detect_skill
from config.settings import (
    APP_ICON,
    APP_LOG_FORMAT,
    APP_LOG_LEVEL,
    APP_TITLE,
    REQUESTS_PER_MINUTE_LIMIT,
    UI_LOCALE,
    get_auth_description,
    validate_runtime_environment,
)

logger = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False


_TOOL_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "write": "Writing file",
        "edit": "Editing file",
        "read": "Reading file",
        "bash": "Running command",
        "grep": "Searching code",
        "glob": "Finding files",
        "web_fetch": "Fetching web content",
        "web_search": "Searching the web",
    },
    "ja": {
        "write": "ファイル書き込み",
        "edit": "ファイル編集",
        "read": "ファイル読み取り",
        "bash": "コマンド実行",
        "grep": "コード検索",
        "glob": "ファイル探索",
        "web_fetch": "Web取得",
        "web_search": "Web検索",
    },
}

_TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "sidebar_title": "Session Info",
        "sidebar_model": "Model: `{model}`",
        "sidebar_auth": "Auth: `{auth}`",
        "sidebar_agent": "Agent: `{agent_id}`",
        "sidebar_session": "Session: `{session_id}`",
        "clear_chat": "New Session",
        "config_issue": "Configuration issue detected.",
        "prompt_placeholder": "Type your message...",
        "thinking": "Thinking...",
        "running_tool": "Running {label}...",
        "rate_limit_exceeded": "Rate limit exceeded ({limit}/min). Try again in about {seconds}s.",
        "chat_error": "Error: {details}",
        "no_response": "(No response)",
        "initializing": "Setting up agent session...",
    },
    "ja": {
        "sidebar_title": "セッション情報",
        "sidebar_model": "モデル: `{model}`",
        "sidebar_auth": "認証: `{auth}`",
        "sidebar_agent": "Agent: `{agent_id}`",
        "sidebar_session": "Session: `{session_id}`",
        "clear_chat": "新しいセッション",
        "config_issue": "設定エラーを検出しました。",
        "prompt_placeholder": "メッセージを入力...",
        "thinking": "考え中...",
        "running_tool": "{label} を実行中...",
        "rate_limit_exceeded": (
            "送信上限（1分あたり{limit}件）を超えました。約{seconds}秒後に再試行してください。"
        ),
        "chat_error": "エラー: {details}",
        "no_response": "(応答なし)",
        "initializing": "エージェントセッションを準備中...",
    },
}

_CUSTOM_CSS = """
<style>
[data-testid="stChatMessage"] h1 { font-size: 1.4rem !important; }
[data-testid="stChatMessage"] h2 { font-size: 1.2rem !important; }
[data-testid="stChatMessage"] h3 { font-size: 1.05rem !important; }
[data-testid="stChatMessage"] p { margin-bottom: 0.4em !important; }
.stMainBlockContainer { padding-top: 1.5rem !important; }
[data-testid="stStatusWidget"] { display: none !important; }
</style>
"""

_IME_FIX_JS = """
<script>
(function() {
    var VERSION = 4;
    var doc = window.parent.document;
    if (doc._imeFixCleanup) doc._imeFixCleanup();
    if (doc._imeFixVersion === VERSION) return;
    doc._imeFixVersion = VERSION;

    var composing = false;
    var compositionStartedAt = 0;
    var lastComposedAt = 0;
    var JUST_COMPOSED_WINDOW_MS = 320;
    var COMPOSITION_STALE_MS = 5000;

    function nowMs() {
        return (window.performance && window.performance.now)
            ? window.performance.now() : Date.now();
    }
    function isChatInput(e) {
        return e.target && e.target.closest &&
               e.target.closest('[data-testid="stChatInput"]');
    }
    function onCompositionStart(e) {
        if (!isChatInput(e)) return;
        composing = true;
        compositionStartedAt = nowMs();
    }
    function onCompositionEnd(e) {
        if (!isChatInput(e)) return;
        var text = (typeof e.data === 'string') ? e.data : '';
        if (text.length > 0) { lastComposedAt = nowMs(); }
        composing = false;
    }
    function onFocusout(e) {
        if (!isChatInput(e)) return;
        composing = false;
    }
    function onKeydown(e) {
        if (e.key !== 'Enter' || e.shiftKey || !isChatInput(e)) return;
        var now = nowMs();
        if (composing && (now - compositionStartedAt) > COMPOSITION_STALE_MS) {
            composing = false;
        }
        var keyCode = e.keyCode || e.which || 0;
        var imeProcessKey = keyCode === 229 || e.key === 'Process';
        var recentlyComposed = (now - lastComposedAt) < JUST_COMPOSED_WINDOW_MS;
        if (imeProcessKey || composing || recentlyComposed) {
            e.preventDefault();
            e.stopPropagation();
            e.stopImmediatePropagation();
            if (recentlyComposed) { lastComposedAt = 0; }
        }
    }

    doc.addEventListener('compositionstart', onCompositionStart, true);
    doc.addEventListener('compositionend', onCompositionEnd, true);
    doc.addEventListener('focusout', onFocusout, true);
    doc.addEventListener('keydown', onKeydown, true);

    doc._imeFixCleanup = function() {
        doc.removeEventListener('compositionstart', onCompositionStart, true);
        doc.removeEventListener('compositionend', onCompositionEnd, true);
        doc.removeEventListener('focusout', onFocusout, true);
        doc.removeEventListener('keydown', onKeydown, true);
        composing = false;
        lastComposedAt = 0;
        delete doc._imeFixVersion;
    };
})();
</script>
"""


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_logging() -> None:
    global _LOGGING_CONFIGURED
    root = logging.getLogger()
    if _LOGGING_CONFIGURED:
        return

    handler = logging.StreamHandler()
    if APP_LOG_FORMAT == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, APP_LOG_LEVEL, logging.INFO))
    _LOGGING_CONFIGURED = True


def _tool_status_label(tool_name: str) -> str:
    localized = _TOOL_LABELS.get(UI_LOCALE, _TOOL_LABELS["en"])
    return localized.get(tool_name, tool_name)


def _msg(key: str, **kwargs: Any) -> str:
    localized = _TEXTS.get(UI_LOCALE, _TEXTS["en"])
    template = localized.get(key, _TEXTS["en"].get(key, key))
    return template.format(**kwargs)


def _initialize_session_state() -> None:
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "agent_client" not in st.session_state:
        st.session_state.agent_client = ManagedAgentClient()
    if "request_timestamps" not in st.session_state:
        st.session_state.request_timestamps = []


def _stream_response(
    client: ManagedAgentClient,
    prompt: str,
    status_placeholder: Any,
    response_placeholder: Any,
    *,
    system_supplement: str = "",
    reference_context: str = "",
) -> tuple[str, list[dict[str, str]]]:
    """Fetch and progressively render a single assistant response.

    Returns (response_text, created_files).
    """
    final_text_parts: list[str] = []
    created_files: list[dict[str, str]] = []

    for chunk in client.send_message_streaming(
        prompt,
        system_supplement=system_supplement,
        reference_context=reference_context,
    ):
        ctype = chunk.get("type")
        content = sanitize(chunk.get("content", ""))

        if ctype == "text" and content:
            final_text_parts.append(content)
            status_placeholder.empty()
            response_placeholder.markdown("".join(final_text_parts) + " ▌")
        elif ctype == "tool_use":
            label = _tool_status_label(content)
            status_placeholder.status(_msg("running_tool", label=label), state="running")
        elif ctype == "file_created":
            fname = chunk.get("file_name", "file.txt")
            fcontent = sanitize(chunk.get("file_content", ""))
            if fname and fcontent:
                created_files.append({"name": fname, "content": fcontent})
        elif ctype == "tool_result":
            status_placeholder.status(_msg("thinking"), state="running")
        elif ctype == "error":
            final_text_parts.append(f"\n\n**Error:** {content}")
            status_placeholder.empty()
            response_placeholder.markdown("".join(final_text_parts))
        elif ctype == "done":
            break

    if not final_text_parts:
        final_text_parts.append(_msg("no_response"))

    status_placeholder.empty()
    return "".join(final_text_parts), created_files


def _consume_rate_limit(
    now_seconds: float,
    timestamps: list[float],
    *,
    limit: int,
    window_seconds: float = 60.0,
) -> tuple[list[float], bool, int]:
    recent = [ts for ts in timestamps if now_seconds - ts < window_seconds]
    if len(recent) >= limit:
        retry_after = max(1, int(window_seconds - (now_seconds - recent[0])))
        return recent, True, retry_after
    recent.append(now_seconds)
    return recent, False, 0


def _inject_static_assets() -> None:
    st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)
    # IME fix requires st.components.v1.html (iframe with parent access)
    # st.html does not allow window.parent.document access
    st.components.v1.html(_IME_FIX_JS, height=0)


def render_app() -> None:
    """Render the Streamlit chat app."""
    _configure_logging()
    st.set_page_config(page_title=APP_TITLE, page_icon=APP_ICON, layout="wide")
    _inject_static_assets()
    _initialize_session_state()

    client: ManagedAgentClient = st.session_state.agent_client

    with st.sidebar:
        st.subheader(_msg("sidebar_title"))
        st.caption(_msg("sidebar_auth", auth=get_auth_description()))

        from config.settings import DEFAULT_MODEL
        st.caption(_msg("sidebar_model", model=DEFAULT_MODEL))

        if client.agent_id:
            st.caption(_msg("sidebar_agent", agent_id=client.agent_id[:20] + "..."))
        if client.session_id:
            st.caption(_msg("sidebar_session", session_id=client.session_id[:20] + "..."))

        st.divider()
        st.caption("**Skills:**")
        from skills.registry import ALL_SKILLS as _all_skills
        for _sk in _all_skills:
            st.caption(f"`{_sk.command}` - {_sk.name}")

        if st.button(_msg("clear_chat"), use_container_width=True):
            st.session_state.messages = []
            st.session_state.request_timestamps = []
            st.session_state.agent_client = ManagedAgentClient()
            st.rerun()

    runtime_errors = validate_runtime_environment()
    if runtime_errors:
        st.error(_msg("config_issue"))
        for error in runtime_errors:
            st.caption(error)

    for idx, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
        for fi, f in enumerate(message.get("files", [])):
            st.download_button(
                label=f"📥 {f['name']}",
                data=f["content"],
                file_name=f["name"],
                mime="text/plain",
                key=f"dl_{idx}_{fi}",
            )

    submitted_input = st.chat_input(
        _msg("prompt_placeholder"),
        disabled=bool(runtime_errors),
    )
    if submitted_input is None:
        return

    prompt = submitted_input.strip()
    if not prompt:
        return

    updated_timestamps, is_limited, retry_after = _consume_rate_limit(
        now_seconds=datetime.now(UTC).timestamp(),
        timestamps=st.session_state.request_timestamps,
        limit=REQUESTS_PER_MINUTE_LIMIT,
    )
    st.session_state.request_timestamps = updated_timestamps
    if is_limited:
        st.warning(
            _msg(
                "rate_limit_exceeded",
                limit=REQUESTS_PER_MINUTE_LIMIT,
                seconds=retry_after,
            )
        )
        return

    # Detect skill triggers
    skill_match = detect_skill(prompt)
    system_supplement = ""
    reference_context = ""

    if skill_match:
        display_prompt = f"🔧 **{skill_match.skill_name}**: {skill_match.headline}"
        system_supplement = skill_match.system_supplement
        reference_context = skill_match.reference_context
    else:
        display_prompt = prompt

    st.session_state.messages.append({"role": "user", "content": display_prompt})
    with st.chat_message("user"):
        st.markdown(display_prompt)

    with st.chat_message("assistant"):
        status_placeholder = st.empty()
        response_placeholder = st.empty()

        if skill_match:
            status_placeholder.status(
                _msg("running_tool", label=skill_match.skill_name), state="running"
            )
        else:
            status_placeholder.status(_msg("thinking"), state="running")

        created_files: list[dict[str, str]] = []
        try:
            response_text, created_files = _stream_response(
                client=client,
                prompt=prompt,
                status_placeholder=status_placeholder,
                response_placeholder=response_placeholder,
                system_supplement=system_supplement,
                reference_context=reference_context,
            )
        except Exception as exc:
            logger.exception("Chat request failed")
            response_text = _msg("chat_error", details=exc)
        finally:
            status_placeholder.empty()

        response_placeholder.markdown(response_text)

    st.session_state.messages.append({
        "role": "assistant",
        "content": response_text,
        "files": created_files,
    })
    st.rerun()


if __name__ == "__main__":
    render_app()
