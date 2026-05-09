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


# All default prompts MUST match the target skill via detect_skill(); otherwise
# the eval would silently degrade into a no-skill-context comparison and
# produce useless A/B numbers. validate_prompts() enforces this at startup.
DEFAULT_PROMPTS = {
    "market-breadth-analyzer": [
        "/breadth",
        "What is the current market breadth score?",  # "market breadth" kw
        "Show me the advance decline data",            # "advance decline" kw
        "市場幅の健全性を評価して",                       # "市場幅" kw
        "ブレッス指標を確認して",                          # "ブレッス" kw
    ],
}


def validate_prompts(prompts: list[str], expected_skill: str) -> None:
    """Fail fast if any prompt does not route to the expected skill.

    Without this gate, prompts that miss the trigger silently produce
    an A/B comparison of "no skill context" vs "no skill context" — i.e.,
    no signal — and skew the Phase 3 references-removal decision.
    """
    bad: list[tuple[int, str, str | None]] = []
    for i, p in enumerate(prompts):
        match = detect_skill(p)
        actual = match.skill_name if match else None
        if actual != expected_skill:
            bad.append((i, p, actual))
    if bad:
        print(
            f"ERROR: {len(bad)} prompt(s) do not route to '{expected_skill}':",
            file=sys.stderr,
        )
        for i, p, actual in bad:
            print(f"  [{i}] matched={actual!r}: {p!r}", file=sys.stderr)
        sys.exit(2)


def assert_no_legacy_env() -> None:
    """Refuse to run if LEGACY_SKILL_SESSION is set in the environment.

    The eval is meaningful only against the Phase 1 default path
    (session reuse + skill_hint). If LEGACY_SKILL_SESSION=1 is left
    over from a rollback test, every trial would fork a new
    skill-specific agent and the A/B numbers would conflate two
    independent variables (refs on/off + path A/legacy).
    """
    val = os.getenv("LEGACY_SKILL_SESSION", "").strip().lower()
    if val in {"1", "true", "yes"}:
        print(
            "ERROR: LEGACY_SKILL_SESSION is set; eval requires the default "
            "Phase 1 path. Unset it before running this script.",
            file=sys.stderr,
        )
        sys.exit(2)


def collect_response(
    client: ManagedAgentClient, prompt: str
) -> tuple[str, bool]:
    """Send a prompt through the same path as scripts/query_agent.py.

    Returns (response_text, had_error). ``had_error`` is True if the stream
    yielded any ``error``-type chunk. ManagedAgentClient.send_message_streaming
    catches internal exceptions and emits them as error chunks rather than
    re-raising, so an exception-only error counter would miss them and
    produce false "DONE with 0 errors" runs.
    """
    skill_match = detect_skill(prompt)
    parts: list[str] = []
    had_error = False
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
            had_error = True
            parts.append(f"\n[ERROR: {chunk.get('content', '')}]\n")
        elif ctype == "done":
            break
    return "".join(parts), had_error


def run_arm(
    arm: str,
    skill: str,
    prompts: list[str],
    trials: int,
    out_dir: Path,
) -> int:
    """Run one arm of the A/B and write each (prompt, trial) to disk.

    Returns the number of trials that raised a client/API exception. Errors
    are still written to disk for inspection but the count is bubbled up so
    main() can fail the run if any sample is unusable.

    Resets the client between trials so prompt cache state does not leak
    across runs (prompt cache hits would otherwise skew the comparison).
    """
    if arm == "B":
        os.environ["SKILLS_REFS_DISABLED"] = skill
    else:
        os.environ.pop("SKILLS_REFS_DISABLED", None)

    out_dir.mkdir(parents=True, exist_ok=True)
    errors = 0

    for p_idx, prompt in enumerate(prompts):
        for t in range(trials):
            client = ManagedAgentClient()
            print(f"  [{arm}] prompt {p_idx + 1}/{len(prompts)} trial {t + 1}/{trials}",
                  file=sys.stderr)
            try:
                resp, had_error = collect_response(client, prompt)
                if had_error:
                    errors += 1
            except Exception as e:
                errors += 1
                resp = f"[CLIENT ERROR: {e}]"
            fname = f"p{p_idx:02d}_t{t}.md"
            (out_dir / fname).write_text(
                f"# Arm {arm}\n\n## Prompt\n\n{prompt}\n\n## Response\n\n{resp}\n",
                encoding="utf-8",
            )

    return errors


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

    assert_no_legacy_env()

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

    # Fail fast: every prompt must route to the target skill, otherwise
    # the comparison degrades to no-skill vs no-skill (no signal).
    validate_prompts(prompts, args.skill)

    timestamp = dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    base = PROJECT_ROOT / "reports" / "eval" / args.skill / timestamp

    print(f"=== A/B eval: {args.skill} ===", file=sys.stderr)
    print(f"  output: {base}", file=sys.stderr)
    print(f"  prompts: {len(prompts)}, trials: {args.trials}", file=sys.stderr)

    print("\n--- Arm A (refs ENABLED, status quo) ---", file=sys.stderr)
    errors_a = run_arm("A", args.skill, prompts, args.trials, base / "A_refs_on")

    print("\n--- Arm B (refs DISABLED via SKILLS_REFS_DISABLED) ---", file=sys.stderr)
    errors_b = run_arm("B", args.skill, prompts, args.trials, base / "B_refs_off")

    total_errors = errors_a + errors_b
    print(f"\nFiles under {base}", file=sys.stderr)
    print(
        f"  Arm A errors: {errors_a}, Arm B errors: {errors_b}, "
        f"total: {total_errors}",
        file=sys.stderr,
    )

    if total_errors > 0:
        print(
            "ERROR: one or more trials raised exceptions; do NOT use these "
            "samples as a Phase 3 gate input. Inspect the [CLIENT ERROR: ...] "
            "files and re-run after fixing.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(
        "DONE. Recommended manual scoring: 10-point rubric per response covering "
        "(1) score completeness, (2) component coverage, (3) actionable takeaway. "
        "Compare A vs B mean per prompt; if B >= 90% of A, references can be "
        "dropped in Phase 3.",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
