"""Application settings for Claude Managed Agents Chat App."""

from __future__ import annotations

import os
from typing import Literal, cast

from dotenv import load_dotenv


def _load_dotenv_if_enabled() -> None:
    flag = os.getenv("PYTHON_DOTENV_DISABLED", "").strip().lower()
    if flag in {"1", "true", "yes"}:
        return
    load_dotenv()


_load_dotenv_if_enabled()


# --- Helper parsers ---

def _parse_positive_int(raw: str, *, default: int, minimum: int = 1) -> int:
    try:
        value = int(raw.strip())
    except ValueError:
        return default
    return value if value >= minimum else default


UiLocale = Literal["en", "ja"]
LogFormat = Literal["text", "json"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def _parse_ui_locale(raw: str) -> UiLocale:
    if raw in {"en", "ja"}:
        return cast(UiLocale, raw)
    return "en"


def _parse_log_format(raw: str) -> LogFormat:
    if raw in {"text", "json"}:
        return cast(LogFormat, raw)
    return "text"


def _parse_log_level(raw: str) -> LogLevel:
    if raw in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        return cast(LogLevel, raw)
    return "INFO"


# --- Anthropic API ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
DEFAULT_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# --- Managed Agents: reuse existing agent/environment if set ---
AGENT_ID = os.getenv("MANAGED_AGENT_ID", "").strip()
ENVIRONMENT_ID = os.getenv("MANAGED_ENVIRONMENT_ID", "").strip()

# --- Agent defaults (used when creating a new agent) ---
AGENT_NAME = os.getenv("MANAGED_AGENT_NAME", "Trade Assistant").strip()

_DEFAULT_SYSTEM_PROMPT = """\
You are an expert US equity trading assistant with deep knowledge of \
William O'Neil's CANSLIM methodology, Mark Minervini's momentum strategies, \
and macro-driven portfolio management.

## Your Role

You help part-time traders (who can only check markets before/after US market hours) \
make informed, data-driven decisions. You combine multiple analytical perspectives: \
technical analysis, fundamental screening, macro regime awareness, and market breadth monitoring.

## Available Skills

You have 10 specialized skills. Proactively suggest using them when relevant:

| Command | Purpose | When to Suggest |
|---------|---------|-----------------|
| `/scenario-analyzer "headline"` | 18-month scenario from news | Breaking news, geopolitical events |
| `/ftd-detector` | Market bottom confirmation (FTD) | After 3%+ correction, "is it safe to buy?" |
| `/vcp-screener` | Volatility Contraction Pattern scan | Looking for breakout setups |
| `/macro-regime` | Macro regime detection | Questioning market structure changes |
| `/canslim` | CANSLIM growth stock screening | Finding high-growth momentum stocks |
| `/theme-detector` | Market theme & sector rotation | "What themes are hot?", sector analysis |
| `/breadth` | Market breadth health check | Assessing rally sustainability |
| `/earnings` | Upcoming earnings calendar | Pre-earnings planning |
| `/econ-calendar` | Economic events calendar | FOMC, CPI, jobs report timing |
| `/breakout-plan` | Trade plan with entry/risk calc | After VCP/CANSLIM candidates found |

## Communication Style

- Respond in English by default. If the user writes in Japanese, respond in Japanese
- Be concise but thorough — traders need signal, not noise
- Use tables and structured data when presenting analysis
- Always include actionable takeaways
- Flag risks explicitly — never downplay uncertainty
- When presenting stock picks, always include: ticker, rationale, key levels, and risk

## Workflow Guidance

When a user asks a broad question like "What should I do this week?", suggest a multi-skill workflow:
1. `/econ-calendar` → Check upcoming economic events
2. `/earnings` → Check earnings reports this week
3. `/breadth` → Assess overall market health
4. `/ftd-detector` or `/macro-regime` → Confirm market posture
5. `/vcp-screener` or `/canslim` → Find specific trade candidates
6. `/breakout-plan` → Build entry/risk plan for top candidates

## Date & Time

Each user message includes a `[Current: YYYY-MM-DD (Day) HH:MM TZ]` header \
showing the user's local date and timezone. ALWAYS use this date for reports \
and analysis — do NOT use the container's UTC clock. When running scripts, \
pass this date if the script accepts a date parameter.

## Important Rules

- NEVER provide specific buy/sell recommendations as financial advice
- Always include the disclaimer that analysis is for educational purposes
- When running scripts, use the pre-configured API keys (FMP_API_KEY) — never ask the user for them
- Save generated reports to the `reports/` directory
"""

AGENT_SYSTEM_PROMPT = os.getenv("MANAGED_AGENT_SYSTEM_PROMPT", _DEFAULT_SYSTEM_PROMPT).strip()

# --- Environment defaults ---
ENVIRONMENT_NAME = os.getenv("MANAGED_ENVIRONMENT_NAME", "chat-app-env").strip()

# --- Skills ---
SCENARIO_ANALYZER_SKILL_ID = os.getenv("SCENARIO_ANALYZER_SKILL_ID", "").strip()
FTD_DETECTOR_SKILL_ID = os.getenv("FTD_DETECTOR_SKILL_ID", "").strip()
VCP_SCREENER_SKILL_ID = os.getenv("VCP_SCREENER_SKILL_ID", "").strip()
MACRO_REGIME_DETECTOR_SKILL_ID = os.getenv("MACRO_REGIME_DETECTOR_SKILL_ID", "").strip()
CANSLIM_SCREENER_SKILL_ID = os.getenv("CANSLIM_SCREENER_SKILL_ID", "").strip()
THEME_DETECTOR_SKILL_ID = os.getenv("THEME_DETECTOR_SKILL_ID", "").strip()
MARKET_BREADTH_ANALYZER_SKILL_ID = os.getenv("MARKET_BREADTH_ANALYZER_SKILL_ID", "").strip()
EARNINGS_CALENDAR_SKILL_ID = os.getenv("EARNINGS_CALENDAR_SKILL_ID", "").strip()
ECONOMIC_CALENDAR_SKILL_ID = os.getenv("ECONOMIC_CALENDAR_SKILL_ID", "").strip()
BREAKOUT_TRADE_PLANNER_SKILL_ID = os.getenv("BREAKOUT_TRADE_PLANNER_SKILL_ID", "").strip()
IBD_DISTRIBUTION_DAY_MONITOR_SKILL_ID = os.getenv("IBD_DISTRIBUTION_DAY_MONITOR_SKILL_ID", "").strip()

# --- External API Keys (injected into agent sessions) ---
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()

# --- App settings ---
APP_TITLE = os.getenv("APP_TITLE", "Trade Assistant").strip()
APP_ICON = "🤖"

REQUESTS_PER_MINUTE_LIMIT = _parse_positive_int(
    os.getenv("REQUESTS_PER_MINUTE_LIMIT", "20"), default=20
)
UI_LOCALE: UiLocale = _parse_ui_locale(os.getenv("APP_LOCALE", "en").strip().lower())
APP_LOG_FORMAT: LogFormat = _parse_log_format(os.getenv("APP_LOG_FORMAT", "text").strip().lower())
APP_LOG_LEVEL: LogLevel = _parse_log_level(os.getenv("APP_LOG_LEVEL", "INFO").strip().upper())


def validate_runtime_environment() -> list[str]:
    """Return user-facing configuration errors that block chat requests."""
    errors: list[str] = []
    if not ANTHROPIC_API_KEY:
        errors.append("ANTHROPIC_API_KEY is not set. Please set it in your .env file.")
    return errors


def get_auth_description() -> str:
    """Return a human-readable description of the active auth method."""
    if ANTHROPIC_API_KEY:
        return "API Key"
    return "Not configured"
