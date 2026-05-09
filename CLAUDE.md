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

## Dual Skill System — Why Two Mechanisms?

This project uses **two complementary skill mechanisms** that fire simultaneously:

| Layer | Mechanism | What It Does |
|-------|-----------|--------------|
| **API Skills** (`bootstrap.py`) | `skills.create()` → attached to Agent | Delivers skill files (scripts, references) into the cloud sandbox so the agent can execute them |
| **Local Registry** (`skills/registry.py`) | `detect_skill()` → prompt injection | Enriches the system prompt with `SKILL.md` instructions and `references/` content to guide the agent's analysis |

**How they cooperate on a skill trigger** (e.g., `/vcp-screener`):

1. `detect_skill()` matches the command → loads `SKILL.md` + `references/*.md`
2. `_create_skill_session()` creates a dedicated agent with the enriched system prompt **and** API Skills attached
3. The agent receives analysis methodology via the prompt (local registry) **and** has access to the Python scripts via the sandbox filesystem (API Skills)

**Why not just one?** API Skills deliver files but don't control the system prompt. The local registry controls the prompt but can't deliver files to the sandbox. Both are needed for the agent to know *what* to do (prompt) and *how* to do it (scripts).

**Default path (Phase 1+)**: Skill invocations now reuse the existing session. The local registry produces a lean `skill_hint` (`Use the {skill_name} skill for this request: ...`) prepended to the user message, and Managed Skills' description-based auto-load picks the right skill. Follow-up questions retain context. Set `LEGACY_SKILL_SESSION=1` to restore the pre-Phase-1 behavior of creating a fresh skill-specific agent/session per invocation (rollback path; loses follow-up context).

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

3. ~~**Skill follow-up context is lost**~~: **Resolved in Phase 1**. The default path now reuses the session across skill invocations, so "tell me more about the 2nd stock" works as expected. The legacy behavior is still reachable via `LEGACY_SKILL_SESSION=1` for rollback verification.

4. **datetime.now() in skill scripts vs. user timezone**: The system prompt instructs the agent to use the `[Current: ...]` header for the user's local date, but skill scripts internally use `datetime.now()` which reflects the container's clock (UTC in cloud). This can cause 1-day date mismatches for US users.

5. **Managed Agents API is in beta**: Identifiers like `agent_toolset_20260401` and `betas=["skills-2025-10-02"]` may change.

6. **Test collection conflicts**: Running `pytest skills/ -v` from the project root may fail due to same-named test files across skills (e.g., multiple `test_report_generator.py`). Run tests per-skill instead: `pytest skills/vcp-screener/scripts/tests/ -v`.

## Conventions

- Tests live in each skill's `scripts/tests/` directory
- Code comments in English; UI text supports both `ja` and `en` (`APP_LOCALE`)
- Generated reports are saved to `reports/` (gitignored)
