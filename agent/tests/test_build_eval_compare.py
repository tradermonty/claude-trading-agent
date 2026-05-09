"""Tests for scripts/build_eval_compare.py — verifies the scoring.csv overwrite guard."""

from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "build_eval_compare",
        PROJECT_ROOT / "scripts" / "build_eval_compare.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bec = _load_module()


def _make_eval_dir(tmp_path: Path) -> Path:
    """Build a minimal A/B output directory matching eval_skill_refs.py format."""
    a = tmp_path / "A_refs_on"
    b = tmp_path / "B_refs_off"
    a.mkdir()
    b.mkdir()
    sample = "# Arm X\n\n## Prompt\n\n/test\n\n## Response\n\nresult body\n"
    (a / "p00_t0.md").write_text(sample.replace("Arm X", "Arm A"))
    (b / "p00_t0.md").write_text(sample.replace("Arm X", "Arm B"))
    return tmp_path


class TestCsvOverwriteGuard:
    """csv_has_user_scores must distinguish empty templates from filled ones."""

    def test_no_csv_returns_false(self, tmp_path):
        assert bec.csv_has_user_scores(tmp_path / "missing.csv") is False

    def test_empty_template_returns_false(self, tmp_path):
        p = tmp_path / "empty.csv"
        p.write_text(
            "pair,prompt,arm,score_completeness,component_coverage,"
            "actionable_takeaway,total,note\n"
            "p00_t0,/test,A,,,,,\n"
            "p00_t0,/test,B,,,,,\n"
        )
        assert bec.csv_has_user_scores(p) is False

    def test_any_filled_score_returns_true(self, tmp_path):
        p = tmp_path / "filled.csv"
        p.write_text(
            "pair,prompt,arm,score_completeness,component_coverage,"
            "actionable_takeaway,total,note\n"
            "p00_t0,/test,A,10,,,,\n"  # one cell filled
            "p00_t0,/test,B,,,,,\n"
        )
        assert bec.csv_has_user_scores(p) is True


class TestBuildE2E:
    """End-to-end: invoke main() via sys.argv and verify outputs."""

    def test_creates_comparison_and_scoring_csv(self, tmp_path, monkeypatch):
        eval_dir = _make_eval_dir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["build_eval_compare.py", str(eval_dir)])
        bec.main()
        assert (eval_dir / "comparison.md").exists()
        assert (eval_dir / "scoring.csv").exists()
        # csv has header + 2 arm rows for the single pair
        with (eval_dir / "scoring.csv").open() as f:
            rows = list(csv.reader(f))
        assert len(rows) == 3  # header + A + B
        assert rows[1][2] == "A"
        assert rows[2][2] == "B"

    def test_refuses_to_overwrite_scored_csv_without_force(
        self, tmp_path, monkeypatch
    ):
        eval_dir = _make_eval_dir(tmp_path)
        # First build, then fill in scores
        monkeypatch.setattr(sys, "argv", ["build_eval_compare.py", str(eval_dir)])
        bec.main()
        scoring = eval_dir / "scoring.csv"
        scoring.write_text(
            scoring.read_text().replace(
                "p00_t0,/test (#1),A,,,,,\n",
                "p00_t0,/test (#1),A,10,9,8,27,looks good\n",
            )
        )
        before = scoring.read_text()

        # Re-run without --force
        monkeypatch.setattr(sys, "argv", ["build_eval_compare.py", str(eval_dir)])
        bec.main()
        # Scores must be preserved
        assert scoring.read_text() == before

    def test_force_overwrites_scored_csv(self, tmp_path, monkeypatch):
        eval_dir = _make_eval_dir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["build_eval_compare.py", str(eval_dir)])
        bec.main()
        scoring = eval_dir / "scoring.csv"
        scoring.write_text(
            scoring.read_text().replace(
                "p00_t0,/test (#1),A,,,,,\n",
                "p00_t0,/test (#1),A,10,9,8,27,prior\n",
            )
        )

        monkeypatch.setattr(sys, "argv",
                            ["build_eval_compare.py", str(eval_dir), "--force"])
        bec.main()
        # After --force, the row should be empty again
        with scoring.open() as f:
            rows = list(csv.DictReader(f))
        a_rows = [r for r in rows if r["arm"] == "A"]
        assert a_rows[0]["score_completeness"] == ""

    def test_missing_arm_dirs_exits(self, tmp_path, monkeypatch):
        # No A_refs_on / B_refs_off → should exit 2
        monkeypatch.setattr(sys, "argv", ["build_eval_compare.py", str(tmp_path)])
        with pytest.raises(SystemExit) as exc:
            bec.main()
        assert exc.value.code == 2
