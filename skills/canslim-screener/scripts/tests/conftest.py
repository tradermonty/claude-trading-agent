"""Shared fixtures for CANSLIM Screener tests."""

import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent

# Several skills expose a top-level namespace package named ``calculators``.
# When pytest collects all skills in one process, a previously imported
# ``calculators`` namespace can hide this skill's calculator modules. Clear
# that namespace before CANSLIM test modules import from ``calculators.*``.
for module_name in list(sys.modules):
    if module_name == "calculators" or module_name.startswith("calculators."):
        del sys.modules[module_name]

for path in (SCRIPTS_DIR, TESTS_DIR):
    path_str = str(path)
    while path_str in sys.path:
        sys.path.remove(path_str)
    sys.path.insert(0, path_str)
