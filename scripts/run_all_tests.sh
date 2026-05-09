#!/usr/bin/env bash
# Run the full pytest suite using pyproject.toml testpaths.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [ -n "${PYTHON:-}" ]; then
    PYTHON_BIN="$PYTHON"
elif [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
else
    PYTHON_BIN="python3"
fi

"$PYTHON_BIN" -m pytest -q
