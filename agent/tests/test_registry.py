"""Tests for skills.registry — verifies skill detection and prompt building."""

import sys
from pathlib import Path

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.registry import ALL_SKILLS, detect_skill


class TestSkillDetection:
    """Verify skill command matching and keyword matching."""

    def test_explicit_command_matches(self):
        result = detect_skill("/vcp-screener")
        assert result is not None
        assert result.skill_name == "vcp-screener"

    def test_explicit_command_with_argument(self):
        result = detect_skill('/scenario-analyzer "Fed cuts rates by 25bp"')
        assert result is not None
        assert result.skill_name == "scenario-analyzer"
        assert "Fed cuts rates" in result.headline

    def test_keyword_match_japanese(self):
        result = detect_skill("フォロースルーデイを確認して")
        assert result is not None
        assert result.skill_name == "ftd-detector"

    def test_keyword_match_english(self):
        result = detect_skill("Check the market breadth")
        assert result is not None
        assert result.skill_name == "market-breadth-analyzer"

    def test_no_match_returns_none(self):
        result = detect_skill("What's the weather today?")
        assert result is None

    def test_system_supplement_contains_skill_instructions(self):
        result = detect_skill("/ftd-detector")
        assert result is not None
        assert "Active Skill: ftd-detector" in result.system_supplement

    def test_reference_context_loaded(self):
        result = detect_skill("/ftd-detector")
        assert result is not None
        assert result.reference_context != ""
        assert "ftd_methodology.md" in result.reference_context


class TestSkillRegistry:
    """Verify registry integrity."""

    def test_all_skills_count(self):
        assert len(ALL_SKILLS) == 10

    def test_all_skills_have_unique_commands(self):
        commands = [s.command for s in ALL_SKILLS]
        assert len(commands) == len(set(commands))

    def test_all_skills_have_skill_dir(self):
        for skill in ALL_SKILLS:
            assert skill.skill_dir.exists(), f"{skill.name}: {skill.skill_dir} not found"

    def test_all_skills_have_skill_md(self):
        for skill in ALL_SKILLS:
            skill_md = skill.skill_dir / "SKILL.md"
            assert skill_md.exists(), f"{skill.name}: SKILL.md not found"
