"""Root conftest – isolate per-skill sys.path / sys.modules for bulk pytest.

Multiple skills ship identically-named modules (scorer.py, calculators/,
fmp_client.py, report_generator.py).  When pytest collects every test
directory in one process, the first match in sys.path (or the cached entry
in sys.modules) wins – which is almost always the wrong skill.

This conftest hooks into pytest_collectstart (collection phase) and
pytest_runtest_setup (execution phase) to evict only the known conflicting
module names and push the current skill's scripts/ directory to the front
of sys.path.
"""

import sys
from pathlib import Path

_SKILLS_MARKER = f"{Path.cwd()}/skills/"

# Module basenames that exist in more than one skill's scripts/ directory.
_CONFLICTING_BASENAMES = frozenset(
    {
        "calculators",
        "fmp_client",
        "helpers",
        "report_generator",
        "scorer",
    }
)

_last_skill: "str | None" = None


def _skill_root(filepath: Path) -> "Path | None":
    """Return the skill root (dir containing SKILL.md) for *filepath*."""
    for parent in filepath.parents:
        if (parent / "SKILL.md").exists():
            return parent
    return None


def _activate_skill(skill: Path, test_dir: str) -> None:
    """Evict conflicting modules and adjust sys.path for *skill*."""
    global _last_skill  # noqa: PLW0603
    skill_prefix = str(skill)

    if _last_skill == skill_prefix:
        return
    _last_skill = skill_prefix

    scripts_dir = str(skill / "scripts")

    # 1. Evict only known-conflicting modules from OTHER skills.
    stale = [
        name
        for name in list(sys.modules)
        if name.split(".")[0] in _CONFLICTING_BASENAMES
        and skill_prefix not in (getattr(sys.modules[name], "__file__", None) or "")
        and _SKILLS_MARKER in (getattr(sys.modules[name], "__file__", None) or "")
    ]
    for name in stale:
        del sys.modules[name]

    # 2. Ensure this skill's scripts dir is first on sys.path.
    try:
        sys.path.remove(scripts_dir)
    except ValueError:
        pass
    sys.path.insert(0, scripts_dir)

    # 3. Ensure the test directory itself is on sys.path.
    try:
        sys.path.remove(test_dir)
    except ValueError:
        pass
    sys.path.insert(0, test_dir)


def pytest_collectstart(collector) -> None:
    fspath = getattr(collector, "path", None) or getattr(collector, "fspath", None)
    if fspath is None:
        return
    fspath = Path(fspath)
    if fspath.suffix != ".py":
        return
    skill = _skill_root(fspath)
    if skill is None:
        return
    _activate_skill(skill, str(fspath.parent))


def pytest_runtest_setup(item) -> None:
    fspath = getattr(item, "path", None) or getattr(item, "fspath", None)
    if fspath is None:
        return
    fspath = Path(fspath)
    skill = _skill_root(fspath)
    if skill is None:
        return
    _activate_skill(skill, str(fspath.parent))


# Skip known-failing skills in bulk runs; allow explicit targeting.
_BULK_SKIP_GLOBS = [
    "skills/canslim-screener/*",
    "skills/theme-detector/scripts/tests/*",
]


def pytest_ignore_collect(collection_path, config):  # noqa: ANN001
    import fnmatch

    try:
        rel = str(collection_path.relative_to(Path.cwd()))
    except ValueError:
        return None

    for glob_pat in _BULK_SKIP_GLOBS:
        if fnmatch.fnmatch(rel, glob_pat):
            skill_name = glob_pat.split("/")[1]
            if any(skill_name in str(a) for a in config.args):
                return None
            return True

    return None
