#!/usr/bin/env python3
"""One-time setup — registers skills, agent, and environment with Managed Agents API.

Usage:
    1. Copy .env.example to .env and set ANTHROPIC_API_KEY (and optionally FMP_API_KEY)
    2. Run: python setup.py
    3. The script writes all generated IDs back to .env automatically

If IDs already exist in .env, those steps are skipped. Use --force to re-create everything.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
SKILLS_DIR = PROJECT_ROOT / "skills"
ENV_FILE = PROJECT_ROOT / ".env"

# Mapping: skill directory name → .env variable name
SKILL_ENV_KEYS: dict[str, str] = {
    "scenario-analyzer": "SCENARIO_ANALYZER_SKILL_ID",
    "ftd-detector": "FTD_DETECTOR_SKILL_ID",
    "vcp-screener": "VCP_SCREENER_SKILL_ID",
    "macro-regime-detector": "MACRO_REGIME_DETECTOR_SKILL_ID",
    "canslim-screener": "CANSLIM_SCREENER_SKILL_ID",
    "theme-detector": "THEME_DETECTOR_SKILL_ID",
    "market-breadth-analyzer": "MARKET_BREADTH_ANALYZER_SKILL_ID",
    "earnings-calendar": "EARNINGS_CALENDAR_SKILL_ID",
    "economic-calendar-fetcher": "ECONOMIC_CALENDAR_SKILL_ID",
    "breakout-trade-planner": "BREAKOUT_TRADE_PLANNER_SKILL_ID",
}


def read_env_value(key: str) -> str:
    """Read a value from the current environment (already loaded via dotenv)."""
    return os.getenv(key, "").strip()


def update_env_file(updates: dict[str, str]) -> None:
    """Update .env file with new key=value pairs, preserving existing entries."""
    if ENV_FILE.exists():
        content = ENV_FILE.read_text()
    else:
        content = ""

    for key, value in updates.items():
        pattern = rf"^{re.escape(key)}=.*$"
        replacement = f"{key}={value}"
        if re.search(pattern, content, flags=re.MULTILINE):
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
        else:
            if content and not content.endswith("\n"):
                content += "\n"
            content += f"{replacement}\n"

    ENV_FILE.write_text(content)


def register_skill(client, skill_dir: Path) -> str:
    """Register a single skill and return its ID."""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    files: list[tuple[str, bytes]] = []
    skip_dirs = {"__pycache__", ".pytest_cache", "tests"}
    for f in sorted(skill_dir.rglob("*")):
        if not f.is_file():
            continue
        if any(d in f.parts for d in skip_dirs):
            continue
        if f.name == ".DS_Store":
            continue
        rel = f"{skill_dir.name}/{f.relative_to(skill_dir)}"
        files.append((rel, f.read_bytes()))

    skill = client.beta.skills.create(
        display_title=skill_dir.name,
        files=files,
        betas=["skills-2025-10-02"],
    )
    return skill.id


def register_all_skills(client, *, force: bool = False) -> dict[str, str]:
    """Register skills and return {env_key: skill_id} mapping.

    Skips skills that already have an ID in the environment unless force=True.
    """
    results: dict[str, str] = {}

    for skill_name, env_key in SKILL_ENV_KEYS.items():
        existing_id = read_env_value(env_key)
        if existing_id and not force:
            print(f"  SKIP {skill_name} (already registered: {existing_id[:20]}...)")
            results[env_key] = existing_id
            continue

        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            print(f"  SKIP {skill_name} (directory not found)")
            continue

        try:
            skill_id = register_skill(client, skill_dir)
            results[env_key] = skill_id
            print(f"  OK   {skill_name} → {skill_id}")
        except Exception as e:
            print(f"  FAIL {skill_name} → {e}")
            # Keep existing ID if registration fails
            if existing_id:
                results[env_key] = existing_id

    return results


def create_agent(client, skill_ids: list[str]) -> str:
    """Create an agent with skills attached."""
    from config.settings import AGENT_NAME, AGENT_SYSTEM_PROMPT, DEFAULT_MODEL
    from agent.client import _build_system_prompt

    system = _build_system_prompt(AGENT_SYSTEM_PROMPT)
    skills = [
        {"type": "custom", "skill_id": sid, "version": "latest"}
        for sid in skill_ids
    ]

    agent = client.beta.agents.create(
        name=AGENT_NAME,
        model=DEFAULT_MODEL,
        system=system,
        tools=[{"type": "agent_toolset_20260401"}],
        **({"skills": skills} if skills else {}),
    )
    return agent.id


def create_environment(client) -> str:
    """Create a cloud environment."""
    from config.settings import ENVIRONMENT_NAME

    environment = client.beta.environments.create(
        name=ENVIRONMENT_NAME,
        config={
            "type": "cloud",
            "networking": {"type": "unrestricted"},
        },
    )
    return environment.id


def main() -> None:
    parser = argparse.ArgumentParser(description="Trade Assistant Setup")
    parser.add_argument(
        "--force", action="store_true",
        help="Re-create all resources even if IDs already exist in .env",
    )
    args = parser.parse_args()

    # Load .env first for ANTHROPIC_API_KEY
    from dotenv import load_dotenv
    load_dotenv(ENV_FILE, override=True)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set in .env")
        print("  1. cp .env.example .env")
        print("  2. Set ANTHROPIC_API_KEY in .env")
        sys.exit(1)

    from anthropic import Anthropic
    client = Anthropic()

    print("=" * 50)
    print("Trade Assistant Setup")
    if args.force:
        print("  (--force: re-creating all resources)")
    print("=" * 50)

    # Step 1: Register skills
    print("\n[1/3] Registering skills...")
    skill_env_map = register_all_skills(client, force=args.force)
    skill_ids = list(skill_env_map.values())
    print(f"  Total: {len(skill_ids)}/{len(SKILL_ENV_KEYS)} skills")

    # Step 2: Create agent (or reuse existing)
    existing_agent = read_env_value("MANAGED_AGENT_ID")
    if existing_agent and not args.force:
        print(f"\n[2/3] Agent already exists: {existing_agent[:20]}...")
        agent_id = existing_agent
    else:
        print("\n[2/3] Creating agent...")
        agent_id = create_agent(client, skill_ids)
        print(f"  Agent: {agent_id}")

    # Step 3: Create environment (or reuse existing)
    existing_env = read_env_value("MANAGED_ENVIRONMENT_ID")
    if existing_env and not args.force:
        print(f"\n[3/3] Environment already exists: {existing_env[:20]}...")
        environment_id = existing_env
    else:
        print("\n[3/3] Creating environment...")
        environment_id = create_environment(client)
        print(f"  Environment: {environment_id}")

    # Step 4: Write all IDs to .env
    print("\nWriting IDs to .env...")
    env_updates = {
        "MANAGED_AGENT_ID": agent_id,
        "MANAGED_ENVIRONMENT_ID": environment_id,
        **skill_env_map,
    }
    update_env_file(env_updates)

    new_count = sum(
        1 for k, v in env_updates.items()
        if read_env_value(k) != v
    )
    print(f"  Updated {len(env_updates)} entries in .env")

    print("\n" + "=" * 50)
    print("Setup complete!")
    print("=" * 50)
    print("\nStart the app:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()
