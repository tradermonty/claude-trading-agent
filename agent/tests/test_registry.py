"""Tests for skills.registry — verifies normalize_command routing."""

import sys
from pathlib import Path

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from skills.registry import ALL_SKILLS, normalize_command


class TestNormalizeCommandSlash:
    """Slash command routing: exact match, with argument, and boundary edge cases."""

    def test_exact_slash_command_routes(self):
        send, name = normalize_command("/vcp-screener")
        assert name == "vcp-screener"
        assert send == "Use the vcp-screener skill for this request: vcp-screener"

    def test_slash_command_with_argument(self):
        send, name = normalize_command('/scenario-analyzer "Fed cuts rates by 25bp"')
        assert name == "scenario-analyzer"
        assert "Fed cuts rates" in send
        assert send.startswith("Use the scenario-analyzer skill for this request:")

    def test_slash_command_with_tab_argument(self):
        send, name = normalize_command("/scenario-analyzer\tFed cuts rates")
        assert name == "scenario-analyzer"
        assert "Fed cuts rates" in send

    def test_partial_slash_does_not_match(self):
        # "/breadthfoo" must NOT match the "/breadth" command.
        send, name = normalize_command("/breadthfoo")
        assert name is None
        assert send == "/breadthfoo"  # passthrough


class TestNormalizeCommandKeyword:
    """Keyword-based routing for natural-language input."""

    def test_japanese_keyword_match(self):
        send, name = normalize_command("フォロースルーデイを確認して")
        assert name == "ftd-detector"
        assert send.startswith("Use the ftd-detector skill for this request:")

    def test_english_keyword_match(self):
        send, name = normalize_command("Check the market breadth")
        assert name == "market-breadth-analyzer"
        assert "Check the market breadth" in send

    def test_no_match_returns_passthrough(self):
        send, name = normalize_command("What's the weather today?")
        assert name is None
        assert send == "What's the weather today?"

    def test_uppercase_keyword_matches_case_insensitively(self):
        # "FOMC" is a registered trigger keyword for the economic-calendar-fetcher.
        # Natural input "FOMC予定を教えて" should still route there.
        send, name = normalize_command("FOMC予定を教えて")
        assert name == "economic-calendar-fetcher"
        assert "FOMC予定を教えて" in send


class TestSkillRegistry:
    """Verify registry integrity (skill count, uniqueness)."""

    def test_all_skills_count(self):
        assert len(ALL_SKILLS) == 14

    def test_all_skills_have_unique_commands(self):
        commands = [s.command for s in ALL_SKILLS]
        assert len(commands) == len(set(commands))

    def test_all_skills_have_unique_names(self):
        names = [s.name for s in ALL_SKILLS]
        assert len(names) == len(set(names))

    def test_every_skill_has_at_least_one_keyword(self):
        for skill in ALL_SKILLS:
            assert skill.trigger_keywords, f"{skill.name} has no trigger_keywords"
