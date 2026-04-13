# Trade Assistant — Claude Managed Agents Reference Implementation

## Overview

A reference implementation of a chat application using the Anthropic Managed Agents API.
Ships with 10 specialized trading analysis skills and runs on Streamlit UI, CLI, or Docker.

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
python -m pytest skills/ -v
```

## Key Files

| File | Purpose |
|------|---------|
| `bootstrap.py` | One-command provisioning (Skills/Agent/Environment registration) |
| `agent/client.py` | Managed Agents API wrapper — session management and SSE streaming |
| `skills/registry.py` | Skill command detection and dynamic system prompt building |
| `config/settings.py` | Centralized configuration (.env → Python constants) |
| `agent/sanitizer.py` | Hard-coded redaction of API keys and absolute paths |

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

1. **New Agent created per skill invocation**: `_create_skill_session()` calls `agents.create()` on every skill trigger. Could be improved with caching/reuse patterns for cost and latency.

2. **FMP_API_KEY embedded in system prompt**: `_build_system_prompt()` in `agent/client.py` writes the API key as plain text into the prompt. Should migrate to Environment Variables / Secrets when available.

3. **Managed Agents API is in beta**: Identifiers like `agent_toolset_20260401` and `betas=["skills-2025-10-02"]` may change.

## Conventions

- Tests live in each skill's `scripts/tests/` directory
- Code comments in English; UI text supports both `ja` and `en` (`APP_LOCALE`)
- Generated reports are saved to `reports/` (gitignored)
