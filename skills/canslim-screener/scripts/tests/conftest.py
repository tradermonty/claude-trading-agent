"""Shared fixtures for CANSLIM Screener tests"""

import os
import sys

# Add scripts directory to path so modules can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
# Add calculators subdirectory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "calculators"))
# Add tests directory to path so helpers can be imported
sys.path.insert(0, os.path.dirname(__file__))

# The skill scripts are intentionally runnable as standalone files and several
# skills use the same top-level module names (calculators, fmp_client,
# report_generator). When pytest collects all skills in one process, modules
# imported by earlier skill suites can leak through sys.modules. Clear the
# names this suite imports so they resolve from the CANSLIM scripts directory.
for module_name in list(sys.modules):
    if (
        module_name == "calculators"
        or module_name.startswith("calculators.")
        or module_name in {"fmp_client", "report_generator", "screen_canslim"}
    ):
        sys.modules.pop(module_name, None)
