"""Output sanitizer for agent responses.

Applies hard code-level redaction that cannot be bypassed by prompt
injection.  Every text chunk passes through ``sanitize()`` before
reaching the Streamlit UI.
"""

from __future__ import annotations

import os
import re

_HOME = os.path.expanduser("~")

_RE_ANTHROPIC_KEY = re.compile(r"sk-ant-[A-Za-z0-9\-_]{20,}")
_RE_LONG_TOKEN = re.compile(r"(?<![A-Za-z0-9/])[A-Za-z0-9+/\-_]{40,}(?:={0,2})(?![A-Za-z0-9/])")
_RE_ABS_PATH = re.compile(
    r"(?:/Users|/home|/tmp|/var|/private|/opt|/etc)"
    r"(?:/[^\s`\"')\]}>,:;]+)+"
)

# Collect known API keys from environment for exact-match redaction.
# This catches keys shorter than the generic 40-char token pattern.
_KNOWN_SECRETS: list[str] = []
for _env_key in ("FMP_API_KEY", "ANTHROPIC_API_KEY"):
    _val = os.getenv(_env_key, "").strip()
    if _val and len(_val) >= 8:
        _KNOWN_SECRETS.append(_val)


def sanitize(text: str) -> str:
    """Redact secrets and system paths from agent output."""
    for secret in _KNOWN_SECRETS:
        text = text.replace(secret, "[REDACTED_API_KEY]")
    text = _RE_ANTHROPIC_KEY.sub("[REDACTED_API_KEY]", text)
    # Paths first — otherwise the long-token regex swallows path strings
    text = _RE_ABS_PATH.sub(_redact_abs_path, text)
    text = _RE_LONG_TOKEN.sub("[REDACTED_TOKEN]", text)
    return text


def _redact_abs_path(match: re.Match[str]) -> str:
    """Replace absolute path with project-relative or redacted form."""
    path = match.group(0)
    project_root = os.getcwd()
    if path.startswith(project_root + "/"):
        return path[len(project_root) + 1:]
    if path.startswith(_HOME):
        return "~" + path[len(_HOME):]
    return "[redacted-path]"
