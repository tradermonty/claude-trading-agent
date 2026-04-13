---
name: trade-assistant
description: |
  Send queries to the Trade Assistant running on Managed Agents.
  10 trading skills (FTD detection, VCP screening, CANSLIM, macro regime,
  scenario analysis, theme detection, market breadth, earnings/economic
  calendar, breakout trade planner) for comprehensive market analysis.
  Triggers: /trade-assistant, trade analysis, market analysis, weekly review
---

# Trade Assistant (Managed Agents)

## Overview

Query the Trade Assistant running on cloud-based Managed Agents.
Invoked from local Claude Code; results are displayed in the terminal.

## When to Use

- Requesting comprehensive market analysis
- Running specific skills (FTD, VCP, CANSLIM, etc.) in the cloud
- Weekly trade strategy planning
- News headline scenario analysis

## Usage

```
/trade-assistant What's the market outlook this week?
/trade-assistant Run /ftd-detector
/trade-assistant Find breakout candidates with /vcp-screener
/trade-assistant /scenario-analyzer "Fed cuts rates by 25bp"
```

## Workflow

### Step 1: Run script

Execute the query script with the user's query as an argument:

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)"
python scripts/query_agent.py "user's query"
```

If no argument is provided, prompt the user for input.

### Step 2: Display results

Display the script output directly to the user.
If report files were generated, provide the file paths.

## Available Sub-Skills

Send these commands to the agent to run specific skills:

| Command | Function |
|---------|----------|
| `/ftd-detector` | Follow-Through Day detection |
| `/vcp-screener` | VCP breakout candidate scan |
| `/canslim` | CANSLIM growth stock screening |
| `/macro-regime` | Macro regime (structural shift) detection |
| `/scenario-analyzer "headline"` | News scenario analysis (18-month) |
| `/theme-detector` | Market theme & sector rotation detection |
| `/breadth` | Market breadth (participation rate) analysis |
| `/earnings` | This week's earnings calendar |
| `/econ-calendar` | Economic events calendar |
| `/breakout-plan` | Entry/risk trade plan generation |

## Notes

- API keys (ANTHROPIC_API_KEY, FMP_API_KEY) are loaded automatically from `.env`
- Agent and session management is handled internally by the script
- Results may also be saved to the `reports/` directory
