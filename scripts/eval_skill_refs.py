#!/usr/bin/env python3
"""A/B evaluation harness for SKILLS_REFS_DISABLED.

Runs the same prompts twice — once with reference_context injection (A,
status quo) and once with it suppressed via ``SKILLS_REFS_DISABLED`` (B).
Outputs are written to ``reports/eval/<skill>/<timestamp>/`` for manual
rubric scoring. The harness does not auto-score; it only collects samples.

Usage:
    python scripts/eval_skill_refs.py --skill market-breadth-analyzer --trials 3
    python scripts/eval_skill_refs.py --skill market-breadth-analyzer \
        --trials 3 --prompts-file scripts/eval_prompts.txt

Defaults: 3 trials per arm, 5 built-in prompts for market-breadth-analyzer.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from agent.client import ManagedAgentClient
from agent.sanitizer import sanitize
from skills.registry import detect_skill


DEFAULT_PROMPTS = {
    "market-breadth-analyzer": [
        "/breadth",
        "Is the rally broad-based right now?",
        "What is the current market breadth score?",
        "市場幅の健全性を評価して",
        "How healthy is participation across S&P 500?",
    ],
}


def collect_response(client: ManagedAgentClient, prompt: str) -> str:
    """Send a prompt through the same path as scripts/query_agent.py."""
    skill_match = detect_skill(prompt)
    parts: list[str] = []
    for chunk in client.send_message_streaming(
        prompt,
        system_supplement=skill_match.system_supplement if skill_match else "",
        reference_context=skill_match.reference_context if skill_match else "",
        skill_hint=skill_match.skill_hint if skill_match else "",
    ):
        ctype = chunk.get("type")
        if ctype == "text":
            parts.append(sanitize(chunk.get("content", "")))
        elif ctype == "error":
            parts.append(f"\n[ERROR: {chunk.get('content', '')}]\n")
        elif ctype == "done":
            break
    return "".join(parts)


def run_arm(
    arm: str,
    skill: str,
    prompts: list[str],
    trials: int,
    out_dir: Path,
) -> None:
    """Run one arm of the A/B and write each (prompt, trial) to disk.

    Resets the client between trials so prompt cache state does not leak
    across runs (prompt cache hits would otherwise skew the comparison).
    """
    if arm == "B":
        os.environ["SKILLS_REFS_DISABLED"] = skill
    else:
        os.environ.pop("SKILLS_REFS_DISABLED", None)

    out_dir.mkdir(parents=True, exist_ok=True)

    for p_idx, prompt in enumerate(prompts):
        for t in range(trials):
            client = ManagedAgentClient()
            print(f"  [{arm}] prompt {p_idx + 1}/{len(prompts)} trial {t + 1}/{trials}",
                  file=sys.stderr)
            try:
                resp = collect_response(client, prompt)
            except Exception as e:
                resp = f"[CLIENT ERROR: {e}]"
            fname = f"p{p_idx:02d}_t{t}.md"
            (out_dir / fname).write_text(
                f"# Arm {arm}\n\n## Prompt\n\n{prompt}\n\n## Response\n\n{resp}\n",
                encoding="utf-8",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--skill", required=True,
        help="Skill name to evaluate (e.g. market-breadth-analyzer)",
    )
    parser.add_argument(
        "--trials", type=int, default=3,
        help="Trials per (prompt, arm) pair (default: 3)",
    )
    parser.add_argument(
        "--prompts-file", type=Path,
        help="One prompt per line; falls back to DEFAULT_PROMPTS[skill] if omitted",
    )
    args = parser.parse_args()

    if args.prompts_file:
        prompts = [
            line.strip() for line in args.prompts_file.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    else:
        prompts = DEFAULT_PROMPTS.get(args.skill)
        if not prompts:
            print(
                f"ERROR: no DEFAULT_PROMPTS for skill '{args.skill}'. "
                f"Provide --prompts-file.",
                file=sys.stderr,
            )
            sys.exit(2)

    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    base = PROJECT_ROOT / "reports" / "eval" / args.skill / timestamp

    print(f"=== A/B eval: {args.skill} ===", file=sys.stderr)
    print(f"  output: {base}", file=sys.stderr)
    print(f"  prompts: {len(prompts)}, trials: {args.trials}", file=sys.stderr)

    print("\n--- Arm A (refs ENABLED, status quo) ---", file=sys.stderr)
    run_arm("A", args.skill, prompts, args.trials, base / "A_refs_on")

    print("\n--- Arm B (refs DISABLED via SKILLS_REFS_DISABLED) ---", file=sys.stderr)
    run_arm("B", args.skill, prompts, args.trials, base / "B_refs_off")

    print(f"\nDONE. Review files under {base}", file=sys.stderr)
    print(
        "Recommended manual scoring: 10-point rubric per response covering "
        "(1) score completeness, (2) component coverage, (3) actionable takeaway. "
        "Compare A vs B mean per prompt; if B >= 90% of A, references can be "
        "dropped in Phase 3.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
