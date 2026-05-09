#!/usr/bin/env bash
# Backward-compatible wrapper for the production quality gate.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
"$SCRIPT_DIR/check_quality.sh"
