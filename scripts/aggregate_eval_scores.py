#!/usr/bin/env python3
"""Aggregate manually-filled scoring.csv from the A/B eval harness.

Reads scoring.csv (filled out by the human reviewer), computes per-axis
B/A ratio, and prints a pass/fail verdict against the 90% threshold.

Usage:
    python scripts/aggregate_eval_scores.py reports/eval/<skill>/<timestamp>/scoring.csv
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

AXES = ["score_completeness", "component_coverage", "actionable_takeaway"]
THRESHOLD = 0.90


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <scoring.csv>", file=sys.stderr)
        sys.exit(2)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        sys.exit(2)

    rows_a: list[dict[str, int]] = []
    rows_b: list[dict[str, int]] = []
    incomplete = 0

    with csv_path.open() as f:
        reader = csv.DictReader(f)
        for row in reader:
            scores: dict[str, int] = {}
            row_complete = True
            for axis in AXES:
                val = (row.get(axis) or "").strip()
                if not val:
                    row_complete = False
                    break
                try:
                    scores[axis] = int(val)
                except ValueError:
                    print(
                        f"  WARN: non-integer score in {row['pair']} {row['arm']} {axis}={val!r}",
                        file=sys.stderr,
                    )
                    row_complete = False
                    break
            if not row_complete:
                incomplete += 1
                continue
            (rows_a if row["arm"] == "A" else rows_b).append(scores)

    if incomplete:
        print(f"NOTICE: {incomplete} row(s) have empty/invalid scores; skipped.\n", file=sys.stderr)

    if not rows_a or not rows_b:
        print(
            f"ERROR: need at least 1 fully-scored row per arm "
            f"(have A={len(rows_a)}, B={len(rows_b)})",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"=== Aggregated scores ({len(rows_a)} A rows, {len(rows_b)} B rows) ===\n")

    fail_axes: list[str] = []
    print(f"{'Axis':<25} {'A mean':>10} {'B mean':>10} {'B/A':>10} {'Verdict':>10}")
    print("-" * 70)
    for axis in AXES:
        a_mean = sum(r[axis] for r in rows_a) / len(rows_a)
        b_mean = sum(r[axis] for r in rows_b) / len(rows_b)
        ratio = (b_mean / a_mean) if a_mean else 0.0
        verdict = "PASS" if ratio >= THRESHOLD else "FAIL"
        if verdict == "FAIL":
            fail_axes.append(axis)
        print(f"{axis:<25} {a_mean:>10.2f} {b_mean:>10.2f} {ratio:>10.1%} {verdict:>10}")

    # Total (sum of axes)
    a_total = sum(sum(r.values()) for r in rows_a) / len(rows_a)
    b_total = sum(sum(r.values()) for r in rows_b) / len(rows_b)
    total_ratio = (b_total / a_total) if a_total else 0.0
    total_verdict = "PASS" if total_ratio >= THRESHOLD else "FAIL"
    print("-" * 70)
    print(
        f"{'TOTAL (sum of axes)':<25} {a_total:>10.2f} {b_total:>10.2f} "
        f"{total_ratio:>10.1%} {total_verdict:>10}"
    )

    print()
    if not fail_axes and total_verdict == "PASS":
        print(f"✅ Overall: PASS (all axes ≥ {THRESHOLD:.0%})")
        print("   References injection can be dropped for this skill in Phase 3.")
        sys.exit(0)
    else:
        print(f"❌ Overall: FAIL (axes below threshold: {', '.join(fail_axes) or 'TOTAL'})")
        print("   Investigate B-arm samples before dropping references for this skill.")
        sys.exit(1)


if __name__ == "__main__":
    main()
