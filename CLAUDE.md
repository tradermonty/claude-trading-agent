# Trade Assistant — Claude Managed Agents Reference Implementation

## Overview

A reference implementation of a chat application using the Anthropic Managed Agents API.
Ships with 11 specialized trading analysis skills and runs on Streamlit UI, CLI, or Docker.

## Architecture

```
app.py (Streamlit UI)
  → skills/registry.py    Detect skill commands from user input
  → agent/client.py       Managed Agents API calls (Agent/Session/Event)
  → agent/sanitizer.py    Redact API keys & paths from output
  → config/settings.py    .env-based configuration management
```

**Design intent**: 4-layer separation — UI → Routing → API → Security.
Skill domain logic (`skills/*/scripts/`) is fully independent from the framework.

## Development Workflow

```bash
# Initial setup (one-time)
cp .env.example .env           # Set ANTHROPIC_API_KEY, FMP_API_KEY
pip install -r requirements.txt
python bootstrap.py            # Register Skills → Agent → Environment

# Run
streamlit run app.py           # Web UI
python scripts/query_agent.py  # CLI

# Test
python -m pytest -q

# Lint / type check
ruff check common/ skills/ agent/ config/ scripts/ app.py bootstrap.py
ruff format --check common/ skills/ agent/ config/ scripts/ app.py bootstrap.py
mypy common config agent
```

## Key Files

| File | Purpose |
|------|---------|
| `bootstrap.py` | One-command provisioning (Skills/Agent/Environment registration) |
| `agent/client.py` | Managed Agents API wrapper — session management and SSE streaming |
| `skills/registry.py` | Slash-command routing into Managed Skills auto-load |
| `config/settings.py` | Centralized configuration (.env → Python constants) |
| `agent/sanitizer.py` | Hard-coded redaction of API keys and absolute paths |

## Skill Routing

Skills are registered with the Managed Agents API by `bootstrap.py`
(`skills.create()` → attached to the Agent). Once attached, the
Anthropic platform auto-loads them based on each skill's SKILL.md
description (progressive disclosure).

`skills/registry.py` adds a thin client-side layer for **deterministic
routing**:

| Input | normalize_command output |
|-------|--------------------------|
| `/vcp-screener` | `("Use the vcp-screener skill for this request: vcp-screener", "vcp-screener")` |
| `/scenario-analyzer "Fed cuts 25bp"` | `("Use the scenario-analyzer skill for this request: Fed cuts 25bp", "scenario-analyzer")` |
| `フォロースルーデイを確認して` | `("Use the ftd-detector skill for this request: ...", "ftd-detector")` |
| `What's the weather?` | `("What's the weather?", None)` — passthrough |

The rewritten string is sent to the agent as a normal user message; the
existing session is reused so follow-up questions ("tell me more about
the 2nd stock") retain context. The original user input is preserved
in chat history so the user never sees the rewritten "Use the X skill
..." form.

Skill files (`SKILL.md`, `references/`, `scripts/`) live in the cloud
sandbox via API Skills. The registry does not load them into prompts.

## Skill Structure

Each skill follows this layout:

```
skills/<skill-name>/
  ├── SKILL.md          # Agent-facing execution instructions
  ├── references/       # Methodology reference documents
  └── scripts/
      ├── *.py          # Business logic
      └── tests/        # Unit tests
```

## Known Limitations

1. **FMP_API_KEY prompt exposure is opt-out**: `_build_system_prompt()` can still write the FMP key into the prompt for cloud script compatibility. Set `INJECT_FMP_API_KEY_IN_SYSTEM_PROMPT=0` to avoid raw-key prompt exposure. A proper Managed Environment secret store should replace this when available.

2. **datetime.now() in skill scripts vs. user timezone**: The system prompt instructs the agent to use the `[Current: ...]` header for the user's local date, but skill scripts internally use `datetime.now()` which reflects the container's clock (UTC in cloud). This can cause 1-day date mismatches for US users.

3. **Managed Agents API is in beta**: Identifiers like `agent_toolset_20260401` and `betas=["skills-2025-10-02"]` may change.

## Conventions

- Tests live in each skill's `scripts/tests/` directory
- Code comments in English; UI text supports both `ja` and `en` (`APP_LOCALE`)
- Generated reports are saved to `reports/` (gitignored)
