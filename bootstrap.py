#!/usr/bin/env python3
"""One-time setup — registers skills, agent, and environment with Managed Agents API.

Usage:
    1. Copy .env.example to .env and set ANTHROPIC_API_KEY (and optionally FMP_API_KEY)
    2. Run: python bootstrap.py
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
    "ibd-distribution-day-monitor": "IBD_DISTRIBUTION_DAY_MONITOR_SKILL_ID",
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


def _collect_skill_files(skill_dir: Path) -> list[tuple[str, bytes]]:
    """Read all relevant files in a skill directory for upload."""
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
    return files


def register_skill(
    client,
    skill_dir: Path,
    *,
    existing_skill_id: str = "",
) -> tuple[str, bool, str]:
    """Register a skill and return (skill_id_to_persist, was_newly_created, replaced_old_id).

    Behavior:
      - Path A: existing_skill_id provided and ``skills.versions.create``
        succeeds. Returns (existing_skill_id, False, "").
      - Path B: no existing_skill_id (pure addition). Returns
        (new_skill_id, True, "").
      - Path C: existing_skill_id was provided but ``skills.versions.create``
        failed (skill deleted on Anthropic side, beta change, etc.). A new
        skill is created and the **old skill_id is reported as replaced**
        so the caller can detach it from the agent. Returns
        (new_skill_id, True, existing_skill_id).

    The caller MUST detach the replaced_old_id from the agent and attach
    the new skill_id; otherwise the agent will keep referencing a deleted
    skill, causing future ``agents.update`` calls to fail with invalid skill.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    files = _collect_skill_files(skill_dir)

    if existing_skill_id:
        # Path A: append new version to existing skill_id.
        try:
            client.beta.skills.versions.create(
                existing_skill_id,
                files=files,
                betas=["skills-2025-10-02"],
            )
            return existing_skill_id, False, ""
        except Exception as exc:
            # Path C fallback: versions.create failed.
            print(
                f"  WARN versions.create failed for {existing_skill_id[:20]}... "
                f"({exc}); falling back to skills.create"
            )
            skill = client.beta.skills.create(
                display_title=skill_dir.name,
                files=files,
                betas=["skills-2025-10-02"],
            )
            return skill.id, True, existing_skill_id

    # Path B: pure new creation.
    skill = client.beta.skills.create(
        display_title=skill_dir.name,
        files=files,
        betas=["skills-2025-10-02"],
    )
    return skill.id, True, ""


def register_all_skills(
    client,
    *,
    force: bool = False,
    skills_only: bool = False,
) -> tuple[dict[str, str], list[str], dict[str, str]]:
    """Register skills.

    Modes:
      - default (no flags): skip skills with existing IDs in .env
      - force=True: re-create every skill (legacy behavior, rotates all IDs)
      - skills_only=True: append a new version to existing skill_ids;
        for skills without an existing ID, create new skills

    Returns:
      results: {env_key: skill_id} -- always the skill_id to persist in .env
      new_skill_ids: skill_ids freshly created with no prior counterpart
                     (Path B: pure additions to attach to the agent)
      replacements: {old_skill_id: new_skill_id} for Path C cases where a
                    stale existing_skill_id was replaced and must be
                    detached from the agent
    """
    results: dict[str, str] = {}
    new_skill_ids: list[str] = []
    replacements: dict[str, str] = {}
    failures: list[str] = []

    for skill_name, env_key in SKILL_ENV_KEYS.items():
        existing_id = read_env_value(env_key)
        skill_dir = SKILLS_DIR / skill_name
        if not skill_dir.exists():
            print(f"  SKIP {skill_name} (directory not found)")
            continue

        # Decide whether to (re)register
        if skills_only:
            mode = "version" if existing_id else "create"
        elif force:
            mode = "create"
            existing_id = ""
        else:
            if existing_id:
                print(f"  SKIP {skill_name} (already registered: {existing_id[:20]}...)")
                results[env_key] = existing_id
                continue
            mode = "create"

        try:
            skill_id, was_new, replaced_old = register_skill(
                client,
                skill_dir,
                existing_skill_id=existing_id if mode == "version" else "",
            )
            results[env_key] = skill_id
            if was_new and replaced_old:
                # Path C: old skill stale, new one replaces it.
                replacements[replaced_old] = skill_id
                print(f"  REPL {skill_name} → {skill_id} (replaces {replaced_old[:20]}...)")
            elif was_new:
                # Path B: pure addition.
                new_skill_ids.append(skill_id)
                print(f"  OK   {skill_name} → {skill_id}")
            else:
                # Path A: version bump.
                print(f"  VER  {skill_name} → new version on {skill_id[:20]}...")
        except Exception as e:
            print(f"  FAIL {skill_name} → {e}")
            failures.append(skill_name)
            if existing_id:
                results[env_key] = existing_id

    if failures:
        print(f"\nERROR: {len(failures)} skill(s) failed to register: {', '.join(failures)}")
        sys.exit(1)

    return results, new_skill_ids, replacements


def attach_new_skills_to_agent(
    client,
    agent_id: str,
    new_skill_ids: list[str],
    replacements: dict[str, str] | None = None,
) -> None:
    """Attach new skills and detach stale ones from an existing agent.

    Args:
      new_skill_ids: pure-addition skill_ids (Path B). Appended to the
                     agent's existing skill list.
      replacements: {old_skill_id: new_skill_id} for Path C. The old_skill_id
                    is removed from the agent's skill list and the
                    new_skill_id is added in its place.

    A single agents.update call applies all changes. Skill_ids are
    deduplicated by set so the same skill is never attached twice.
    """
    replacements = replacements or {}
    if not new_skill_ids and not replacements:
        return

    agent = client.beta.agents.retrieve(agent_id, betas=["skills-2025-10-02"])
    current_skills = list(getattr(agent, "skills", []) or [])

    seen: set[str] = set()
    merged_skills: list[dict[str, str]] = []

    # Carry over existing skills, but skip any that were replaced (Path C).
    for s in current_skills:
        sid = getattr(s, "skill_id", None) or (s.get("skill_id") if isinstance(s, dict) else None)
        if not sid or sid in seen:
            continue
        if sid in replacements:
            # Stale: drop it; the replacement is added below.
            continue
        seen.add(sid)
        merged_skills.append(
            {
                "type": "custom",
                "skill_id": sid,
                "version": "latest",
            }
        )

    # Append Path B additions.
    for sid in new_skill_ids:
        if sid and sid not in seen:
            seen.add(sid)
            merged_skills.append(
                {
                    "type": "custom",
                    "skill_id": sid,
                    "version": "latest",
                }
            )

    # Append Path C replacement targets.
    for new_sid in replacements.values():
        if new_sid and new_sid not in seen:
            seen.add(new_sid)
            merged_skills.append(
                {
                    "type": "custom",
                    "skill_id": new_sid,
                    "version": "latest",
                }
            )

    client.beta.agents.update(
        agent_id,
        version=agent.version,
        skills=merged_skills,
        betas=["skills-2025-10-02"],
    )
    summary = []
    if new_skill_ids:
        summary.append(f"{len(new_skill_ids)} added")
    if replacements:
        summary.append(f"{len(replacements)} replaced")
    print(f"  Updated agent {agent_id[:20]}... ({', '.join(summary)})")


def create_agent(client, skill_ids: list[str]) -> str:
    """Create an agent with skills attached."""
    from agent.client import _build_system_prompt
    from config.settings import AGENT_NAME, AGENT_SYSTEM_PROMPT, DEFAULT_MODEL

    system = _build_system_prompt(AGENT_SYSTEM_PROMPT)
    skills = [{"type": "custom", "skill_id": sid, "version": "latest"} for sid in skill_ids]

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
        "--force",
        action="store_true",
        help="Re-create all resources even if IDs already exist in .env "
        "(rotates skill_ids, agent_id, environment_id; orphans old resources)",
    )
    parser.add_argument(
        "--skills-only",
        action="store_true",
        help="Update only skill files, preserving agent/environment IDs. "
        "Existing skills get a new version (skill_ids preserved); "
        "missing skills are created and attached via agents.update.",
    )
    args = parser.parse_args()

    if args.force and args.skills_only:
        print("ERROR: --force and --skills-only are mutually exclusive")
        sys.exit(1)

    # Load .env first for ANTHROPIC_API_KEY
    from dotenv import load_dotenv

    load_dotenv(ENV_FILE, override=True)

    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY is not set in .env")
        print("  1. cp .env.example .env")
        print("  2. Set ANTHROPIC_API_KEY in .env")
        sys.exit(1)

    if args.skills_only:
        agent_id_check = read_env_value("MANAGED_AGENT_ID")
        env_id_check = read_env_value("MANAGED_ENVIRONMENT_ID")
        if not agent_id_check or not env_id_check:
            print(
                "ERROR: --skills-only requires MANAGED_AGENT_ID and "
                "MANAGED_ENVIRONMENT_ID to be set in .env"
            )
            print("  Run `python bootstrap.py` (without --skills-only) first")
            sys.exit(1)

    from anthropic import Anthropic

    client = Anthropic()

    print("=" * 50)
    print("Trade Assistant Setup")
    if args.force:
        print("  (--force: re-creating all resources)")
    elif args.skills_only:
        print("  (--skills-only: updating skills only, preserving agent/env)")
    print("=" * 50)

    # Step 1: Register skills
    print("\n[1/3] Registering skills...")
    skill_env_map, new_skill_ids, replacements = register_all_skills(
        client,
        force=args.force,
        skills_only=args.skills_only,
    )
    skill_ids = list(skill_env_map.values())
    print(f"  Total: {len(skill_ids)}/{len(SKILL_ENV_KEYS)} skills")

    # Step 2: Agent
    existing_agent = read_env_value("MANAGED_AGENT_ID")
    if args.skills_only:
        agent_id = existing_agent
        if new_skill_ids or replacements:
            actions = []
            if new_skill_ids:
                actions.append(f"{len(new_skill_ids)} new")
            if replacements:
                actions.append(f"{len(replacements)} replacement(s)")
            print(f"\n[2/3] Updating agent ({', '.join(actions)})...")
            attach_new_skills_to_agent(
                client,
                agent_id,
                new_skill_ids,
                replacements=replacements,
            )
        else:
            print(f"\n[2/3] Agent preserved: {agent_id[:20]}... (no skill changes)")
    elif existing_agent and not args.force:
        agent_id = existing_agent
        # Default mode can also produce new_skill_ids when a skill directory
        # was added since the last bootstrap (e.g., new SKILL_ENV_KEY entry).
        # If we don't attach, the new skill_id lands in .env but the existing
        # agent never sees it — silently broken.
        if new_skill_ids or replacements:
            print(f"\n[2/3] Agent exists ({existing_agent[:20]}...); attaching new skills...")
            attach_new_skills_to_agent(
                client,
                agent_id,
                new_skill_ids,
                replacements=replacements,
            )
        else:
            print(f"\n[2/3] Agent already exists: {existing_agent[:20]}...")
    else:
        print("\n[2/3] Creating agent...")
        agent_id = create_agent(client, skill_ids)
        print(f"  Agent: {agent_id}")

    # Step 3: Environment
    existing_env = read_env_value("MANAGED_ENVIRONMENT_ID")
    if args.skills_only:
        environment_id = existing_env
        print(f"\n[3/3] Environment preserved: {environment_id[:20]}...")
    elif existing_env and not args.force:
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
    print(f"  Updated {len(env_updates)} entries in .env")

    print("\n" + "=" * 50)
    print("Setup complete!")
    print("=" * 50)
    print("\nStart the app:")
    print("  streamlit run app.py")


if __name__ == "__main__":
    main()
