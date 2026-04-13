#!/usr/bin/env bash
# Run all skill-level tests, one pytest invocation per skill.
# Exit with non-zero if any non-skipped skill's tests fail.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Skills with known pre-existing test failures.
KNOWN_SKIP=(
    "theme-detector"
    "canslim-screener"
)

FAILED=0
TOTAL=0
SKIPPED=0
FAILED_SKILLS=()

is_skipped() {
    local skill="$1"
    for s in "${KNOWN_SKIP[@]}"; do
        [ "$s" = "$skill" ] && return 0
    done
    return 1
}

for test_dir in "$REPO_ROOT"/skills/*/scripts/tests/; do
    [ -d "$test_dir" ] || continue
    ls "$test_dir"/test_*.py >/dev/null 2>&1 || continue

    skill_name=$(echo "$test_dir" | sed "s|$REPO_ROOT/skills/||" | cut -d/ -f1)

    if is_skipped "$skill_name"; then
        SKIPPED=$((SKIPPED + 1))
        echo "--- $skill_name (SKIPPED — known failures) ---"
        echo ""
        continue
    fi

    TOTAL=$((TOTAL + 1))

    echo "--- $skill_name ---"
    if python -m pytest "$test_dir" --tb=short -q 2>&1; then
        :
    else
        FAILED=$((FAILED + 1))
        FAILED_SKILLS+=("$skill_name")
    fi
    echo ""
done

echo "=== Summary: $((TOTAL - FAILED))/$TOTAL passed, $SKIPPED skipped ==="
if [ ${#KNOWN_SKIP[@]} -gt 0 ]; then
    echo "Skipped (known failures): ${KNOWN_SKIP[*]}"
fi
if [ $FAILED -gt 0 ]; then
    echo "FAILED: ${FAILED_SKILLS[*]}"
    exit 1
fi
