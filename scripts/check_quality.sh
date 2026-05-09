#!/usr/bin/env bash
# Run the local production-quality gate.

set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"
PYTHON_DIR="$(dirname "$PYTHON_BIN")"
if [ -x "$PYTHON_DIR/codespell" ]; then
  CODESPELL_BIN="${CODESPELL_BIN:-$PYTHON_DIR/codespell}"
else
  CODESPELL_BIN="${CODESPELL_BIN:-codespell}"
fi

"$PYTHON_BIN" -m ruff check .
"$PYTHON_BIN" -m ruff format --check agent config skills scripts app.py bootstrap.py
"$CODESPELL_BIN" --toml pyproject.toml skills agent config scripts app.py bootstrap.py README.md README.ja.md CLAUDE.md
"$PYTHON_BIN" -m bandit -q -r agent config skills scripts app.py bootstrap.py -c pyproject.toml
"$PYTHON_BIN" -m pytest --cov=agent --cov=config --cov=skills --cov-report=term-missing -q
"$PYTHON_BIN" -m compileall -q agent config skills scripts app.py bootstrap.py
