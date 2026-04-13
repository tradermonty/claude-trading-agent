# Trade Assistant

**A sample project demonstrating how to build a full-featured AI agent using [Claude Managed Agents](https://docs.anthropic.com/en/docs/agents-and-tools/managed-agents)** — Anthropic's cloud-hosted agent runtime with built-in code execution, web access, and file management.

This reference implementation pairs a Streamlit chat UI with 10 specialized trading analysis skills to show how to wire up Skills, Agents, Environments, and Sessions into a working application. Use it as a starting point for your own Managed Agents project — the trading domain is just one example.

[日本語版 README はこちら](README.ja.md)

> **Disclaimer**: This tool is for educational purposes only. It does not constitute financial advice.

> **Note**: The Managed Agents API is in beta. Identifiers such as `agent_toolset_20260401` and `betas=["skills-2025-10-02"]` may change.

## Features

| Command | Skill | Description |
|---------|-------|-------------|
| `/scenario-analyzer "headline"` | Scenario Analyzer | Build 18-month scenarios from news headlines |
| `/ftd-detector` | FTD Detector | Confirm market bottoms via Follow-Through Days |
| `/vcp-screener` | VCP Screener | Scan for Minervini Volatility Contraction Patterns |
| `/macro-regime` | Macro Regime Detector | Detect macro regime shifts using cross-asset ratios |
| `/canslim` | CANSLIM Screener | Screen growth stocks with O'Neil's CANSLIM method |
| `/theme-detector` | Theme Detector | Analyze market themes and sector rotation |
| `/breadth` | Market Breadth Analyzer | Check market health via breadth indicators |
| `/earnings` | Earnings Calendar | Fetch upcoming earnings announcements |
| `/econ-calendar` | Economic Calendar | Fetch FOMC, CPI, jobs report schedules |
| `/breakout-plan` | Breakout Trade Planner | Generate entry/risk trade plans from VCP candidates |

## Architecture

```
Streamlit UI (app.py)
  ├── agent/client.py      — Managed Agents API wrapper (Agent/Environment/Session)
  ├── agent/sanitizer.py   — Redacts API keys & system paths from output
  ├── config/settings.py   — Environment-variable-based configuration
  └── skills/
       ├── registry.py     — Skill command detection & system prompt builder
       ├── scenario-analyzer/
       ├── ftd-detector/
       ├── vcp-screener/
       ├── macro-regime-detector/
       ├── canslim-screener/
       ├── theme-detector/
       ├── market-breadth-analyzer/
       ├── earnings-calendar/
       ├── economic-calendar-fetcher/
       └── breakout-trade-planner/
```

Each skill contains `SKILL.md` (agent instructions), `references/` (methodology docs), and `scripts/` (Python code + tests).

## Learning Guide — Managed Agents API

To learn the **Managed Agents API patterns** without trading domain knowledge, read these 3 files in order:

### 1. `bootstrap.py` — Resource provisioning

Managed Agents has 3 core resources:

| Resource | Role | Lifecycle |
|----------|------|-----------|
| **Skill** | Specialized scripts the agent can use | Register via `skills.create()`, attach to Agent |
| **Agent** | Model + system prompt + skills | Create via `agents.create()`, reusable |
| **Environment** | Cloud sandbox for code execution | Create via `environments.create()`, reusable |

`bootstrap.py` creates all three in sequence and saves their IDs to `.env`.

### 2. `agent/client.py` — Sessions and streaming

Once Agent + Environment exist, create a **Session** to chat:

```
Session = running instance of Agent + Environment
  → events.stream()  opens an SSE connection
  → events.send()    sends user messages
  → receives agent.message / agent.tool_use / session.status_idle events
```

The `ManagedAgentClient.send_message_streaming()` method implements this pattern.

### 3. `skills/registry.py` — Skill routing pattern

Detects skill commands in user input and dynamically extends the agent's system prompt. When `detect_skill()` matches a command (`/vcp-screener`) or keyword, it loads the corresponding `SKILL.md` and `references/` files and injects them into the prompt.

### Why two skill mechanisms?

This project uses **API Skills** (file delivery to the sandbox) and a **local registry** (prompt injection) together. API Skills make scripts available in the cloud environment; the local registry tells the agent *how* to use them by enriching the system prompt. See `CLAUDE.md` for the full explanation.

## Prerequisites

- Python 3.12+
- [Anthropic API Key](https://console.anthropic.com/) (with Managed Agents API access)
- [FMP API Key](https://financialmodelingprep.com/) (for fundamental/price data)

## Setup

```bash
# Clone
git clone https://github.com/<your-username>/claude-trading-agent.git
cd claude-trading-agent

# Virtual environment
python -m venv .venv
source .venv/bin/activate

# Dependencies
pip install -e .

# Environment variables
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY, FMP_API_KEY

# Register skills, agent, and environment with Managed Agents API
python bootstrap.py
```

`bootstrap.py` automatically:

1. Registers 10 skills with the Skills API
2. Creates an Agent (with skills attached + system prompt)
3. Creates an Environment (cloud sandbox)
4. Writes all generated IDs back to `.env`

If IDs already exist in `.env`, those steps are skipped. Use `python bootstrap.py --force` to re-create everything.

## Usage

### Streamlit UI

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser and type skill commands in the chat.

### CLI

```bash
python scripts/query_agent.py "What's the market outlook this week?"
python scripts/query_agent.py "/vcp-screener"
python scripts/query_agent.py  # interactive mode
```

The CLI uses the same Agent/Environment and skill routing as the Streamlit UI.

### Docker

```bash
docker compose up --build
```

## Testing

Each skill includes unit tests. Run per-skill to avoid cross-skill test name collisions:

```bash
# Install dev dependencies (includes pytest)
pip install -r requirements-dev.txt

# Run tests for a specific skill
python -m pytest skills/vcp-screener/scripts/tests/ -v
python -m pytest skills/ftd-detector/scripts/tests/ -v
```

## CI/CD

GitHub Actions runs 3 jobs on every PR and push to `main`:

| Job | Tools | What it checks |
|-----|-------|----------------|
| **Lint** | ruff, codespell | Code style, formatting, spelling |
| **Test** | pytest, coverage | Per-skill unit tests with coverage report |
| **Security** | bandit, detect-secrets | SAST scan + secret leak detection |

### Local development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Set up pre-commit hooks (lint on commit, test on push)
pre-commit install && pre-commit install --hook-type pre-push

# Run all skill tests
bash scripts/run_all_tests.sh
```

## Configuration

See `.env.example` for all available variables.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `FMP_API_KEY` | No | Financial Modeling Prep API key |
| `CLAUDE_MODEL` | No | Model to use (default: `claude-sonnet-4-6`) |
| `MANAGED_AGENT_ID` | No | Existing Agent ID (auto-set by `bootstrap.py`) |
| `MANAGED_ENVIRONMENT_ID` | No | Existing Environment ID (auto-set by `bootstrap.py`) |
| `APP_LOCALE` | No | UI language `ja` / `en` (default: `ja`) |

## License

MIT
