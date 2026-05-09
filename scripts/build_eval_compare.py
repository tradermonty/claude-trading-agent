#!/usr/bin/env python3
"""Generate comparison.md and scoring.csv from an A/B eval output directory.

Companion to scripts/eval_skill_refs.py. Reads the per-trial markdown files
written by eval_skill_refs.py (A_refs_on/ and B_refs_off/ subdirs) and
produces:

  - comparison.md: all 5 prompts × N trials × 2 arms in a single
    side-by-side document for human reviewer to read pair by pair
  - scoring.csv: empty rubric template (one row per arm per pair) with
    columns: pair, prompt, arm, score_completeness, component_coverage,
    actionable_takeaway, total, note

Usage:
    python scripts/build_eval_compare.py reports/eval/<skill>/<timestamp>/
    python scripts/build_eval_compare.py reports/eval/<skill>/<ts>/ --force

By default the script REFUSES to overwrite a scoring.csv that already
contains user-supplied scores (any non-empty value in the score columns).
Pass --force to overwrite. comparison.md is always regenerated since it's
deterministic from the raw eval markdown files.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path


def extract_response(path: Path) -> str:
    """Strip the leading metadata header and return just the response body."""
    text = path.read_text(encoding="utf-8")
    marker = "## Response\n"
    idx = text.find(marker)
    if idx >= 0:
        return text[idx + len(marker):].strip()
    return text


def extract_prompt(path: Path) -> str:
    """Pull the prompt back out of the eval markdown header."""
    text = path.read_text(encoding="utf-8")
    m = re.search(r"## Prompt\n+(.+?)\n+## Response", text, re.S)
    return m.group(1).strip() if m else "(prompt not found)"


def discover_trials(arm_dir: Path) -> list[tuple[int, int, Path]]:
    """Return [(prompt_idx, trial_idx, path), ...] sorted."""
    out: list[tuple[int, int, Path]] = []
    for f in sorted(arm_dir.glob("p*_t*.md")):
        m = re.match(r"p(\d+)_t(\d+)\.md", f.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), f))
    return out


def csv_has_user_scores(csv_path: Path) -> bool:
    """True if scoring.csv exists and has at least one non-empty score cell.

    Used to guard against blowing away a reviewer's manual scores when
    re-running build_eval_compare.py against the same eval directory.
    """
    if not csv_path.exists():
        return False
    score_cols = ("score_completeness", "component_coverage", "actionable_takeaway")
    with csv_path.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            for col in score_cols:
                if (row.get(col) or "").strip():
                    return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("eval_dir", help="Path to reports/eval/<skill>/<timestamp>/")
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite scoring.csv even if it contains existing scores",
    )
    args = parser.parse_args()

    base = Path(args.eval_dir).resolve()
    a_dir = base / "A_refs_on"
    b_dir = base / "B_refs_off"

    if not a_dir.is_dir() or not b_dir.is_dir():
        print(f"ERROR: expected A_refs_on/ and B_refs_off/ in {base}", file=sys.stderr)
        sys.exit(2)

    a_trials = discover_trials(a_dir)
    b_trials = discover_trials(b_dir)

    if not a_trials or not b_trials:
        print(f"ERROR: no trial files found in {base}", file=sys.stderr)
        sys.exit(2)

    a_keys = {(p, t) for p, t, _ in a_trials}
    b_keys = {(p, t) for p, t, _ in b_trials}
    common = sorted(a_keys & b_keys)
    if a_keys != b_keys:
        missing_a = sorted(b_keys - a_keys)
        missing_b = sorted(a_keys - b_keys)
        print(f"WARN: arm mismatch; using {len(common)} common pairs", file=sys.stderr)
        if missing_a:
            print(f"  Only in B: {missing_a}", file=sys.stderr)
        if missing_b:
            print(f"  Only in A: {missing_b}", file=sys.stderr)

    a_path = {(p, t): f for p, t, f in a_trials}
    b_path = {(p, t): f for p, t, f in b_trials}

    # Deduce prompt text from A side (should match B side; flag if not).
    prompt_by_idx: dict[int, str] = {}
    for (p, _), path in a_path.items():
        prompt_by_idx.setdefault(p, extract_prompt(path))

    # ---------- comparison.md ----------
    rubric_header = """# A/B Manual Rubric Scoring

## Rubric (10 points each, 30 max per response)

| Axis | What to score |
|---|---|
| **Score completeness** | Numerical outputs (composite + components) reported correctly |
| **Component coverage** | Each component's signal is clearly explained |
| **Actionable takeaway** | "What to do next" is clear (recommendations, warnings) |

## Scoring guideline

- 10: textbook quality, no issues
- 8-9: minor format/wording differences, no information loss
- 6-7: slight gaps but still usable
- 4-5: noticeable degradation, would re-prompt
- 0-3: unusable

Fill scores into `scoring.csv` (one row per arm).
Pass criterion: per-axis `B/A` mean ratio `>= 0.90`.

---
"""

    out_lines: list[str] = [rubric_header]
    prompt_indices = sorted({p for p, _ in common})

    for p in prompt_indices:
        out_lines.append(f"\n# Prompt #{p+1}: `{prompt_by_idx.get(p, '?')}`\n")
        for (pp, t) in [(pp, t) for pp, t in common if pp == p]:
            a_resp = extract_response(a_path[(pp, t)])
            b_resp = extract_response(b_path[(pp, t)])
            out_lines.append(f"\n## Pair p{pp:02d}_t{t}\n")
            out_lines.append(f"\n### 🅰️ Arm A (refs ON) — len={len(a_resp)} chars\n")
            out_lines.append(f"\n{a_resp}\n")
            out_lines.append("\n---\n")
            out_lines.append(f"\n### 🅱️ Arm B (refs OFF) — len={len(b_resp)} chars\n")
            out_lines.append(f"\n{b_resp}\n")
            out_lines.append("\n---\n")

    comparison_path = base / "comparison.md"
    comparison_path.write_text("\n".join(out_lines), encoding="utf-8")

    # ---------- scoring.csv (guarded against overwriting reviewer scores) ----------
    csv_path = base / "scoring.csv"
    if csv_has_user_scores(csv_path) and not args.force:
        print(
            f"SKIP: {csv_path} contains existing scores; not overwritten. "
            f"Use --force to regenerate (will erase scores).",
            file=sys.stderr,
        )
        csv_written = False
    else:
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "pair", "prompt", "arm",
                "score_completeness", "component_coverage", "actionable_takeaway",
                "total", "note",
            ])
            for (p, t) in common:
                label = f"p{p:02d}_t{t}"
                prompt_short = (prompt_by_idx.get(p, "")[:60] + f" (#{p+1})").strip()
                for arm in ("A", "B"):
                    writer.writerow([label, prompt_short, arm, "", "", "", "", ""])
        csv_written = True

    print(f"Wrote: {comparison_path}", file=sys.stderr)
    print(f"  ({comparison_path.stat().st_size:,} bytes, {len(common)} pairs)",
          file=sys.stderr)
    if csv_written:
        print(f"Wrote: {csv_path}", file=sys.stderr)
        print(f"  ({2 * len(common)} rubric rows)", file=sys.stderr)
    else:
        print(f"Kept:  {csv_path} (existing scores preserved)", file=sys.stderr)
    print("\nNext steps:", file=sys.stderr)
    print(f"  1. Open {comparison_path} and read each pair", file=sys.stderr)
    print(f"  2. Fill scores 0-10 into {csv_path}", file=sys.stderr)
    print(f"  3. Run: python scripts/aggregate_eval_scores.py {csv_path}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
