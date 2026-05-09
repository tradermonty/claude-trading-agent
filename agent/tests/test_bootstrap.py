"""Tests for bootstrap.py — verifies skill registration logic and --skills-only fallback paths."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import bootstrap


@pytest.fixture
def fake_skill_dir(tmp_path: Path) -> Path:
    skill_dir = tmp_path / "fake-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("---\nname: fake-skill\ndescription: test\n---\n# Body\n")
    (skill_dir / "scripts").mkdir()
    (skill_dir / "scripts" / "main.py").write_text("print('hi')\n")
    return skill_dir


class TestRegisterSkill:
    """Verify register_skill returns the correct skill_id under each path."""

    def test_path_a_returns_existing_skill_id(self, fake_skill_dir: Path) -> None:
        # Path A: existing_skill_id provided, versions.create succeeds
        client = MagicMock()
        skill_id, was_new, replaced = bootstrap.register_skill(
            client, fake_skill_dir, existing_skill_id="skill_existing_123"
        )
        assert skill_id == "skill_existing_123"
        assert was_new is False
        assert replaced == ""
        client.beta.skills.versions.create.assert_called_once()
        client.beta.skills.create.assert_not_called()

    def test_path_b_returns_new_skill_id(self, fake_skill_dir: Path) -> None:
        # Path B: no existing_skill_id, fresh creation
        client = MagicMock()
        client.beta.skills.create.return_value = MagicMock(id="skill_new_456")
        skill_id, was_new, replaced = bootstrap.register_skill(
            client, fake_skill_dir, existing_skill_id=""
        )
        assert skill_id == "skill_new_456"
        assert was_new is True
        assert replaced == ""
        client.beta.skills.create.assert_called_once()
        client.beta.skills.versions.create.assert_not_called()

    def test_path_c_falls_back_and_reports_replaced_id(self, fake_skill_dir: Path) -> None:
        # Path C: existing ID present but versions.create fails (e.g., skill
        # was deleted on Anthropic side). Fall back to skills.create AND
        # report the stale ID so caller can detach it from the agent.
        client = MagicMock()
        client.beta.skills.versions.create.side_effect = RuntimeError("not found")
        client.beta.skills.create.return_value = MagicMock(id="skill_fallback_789")
        skill_id, was_new, replaced = bootstrap.register_skill(
            client, fake_skill_dir, existing_skill_id="skill_deleted_old"
        )
        assert skill_id == "skill_fallback_789"
        assert was_new is True
        assert replaced == "skill_deleted_old"  # stale ID reported for detach
        client.beta.skills.versions.create.assert_called_once()
        client.beta.skills.create.assert_called_once()

    def test_missing_skill_md_raises(self, tmp_path: Path) -> None:
        empty_dir = tmp_path / "empty-skill"
        empty_dir.mkdir()
        client = MagicMock()
        with pytest.raises(FileNotFoundError):
            bootstrap.register_skill(client, empty_dir, existing_skill_id="")


class TestRegisterAllSkills:
    """Verify register_all_skills aggregates results and tracks new IDs correctly."""

    def test_skills_only_with_existing_id_uses_versions_create(
        self, monkeypatch, fake_skill_dir: Path
    ) -> None:
        # All skills have existing IDs → versions.create only, no new attach needed
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.setenv("FAKE_SKILL_ID", "skill_pre_existing_111")

        client = MagicMock()
        results, new_ids, replacements = bootstrap.register_all_skills(client, skills_only=True)

        assert results == {"FAKE_SKILL_ID": "skill_pre_existing_111"}
        assert new_ids == []
        assert replacements == {}
        client.beta.skills.versions.create.assert_called_once()
        client.beta.skills.create.assert_not_called()

    def test_skills_only_with_missing_id_creates_and_tracks_for_attach(
        self, monkeypatch, fake_skill_dir: Path
    ) -> None:
        # Missing ID → skills.create, returned in new_skill_ids for agent attach
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.delenv("FAKE_SKILL_ID", raising=False)

        client = MagicMock()
        client.beta.skills.create.return_value = MagicMock(id="skill_brand_new_222")

        results, new_ids, replacements = bootstrap.register_all_skills(client, skills_only=True)

        assert results == {"FAKE_SKILL_ID": "skill_brand_new_222"}
        assert new_ids == ["skill_brand_new_222"]
        assert replacements == {}  # pure addition, not a replacement

    def test_skills_only_path_c_fallback_reports_replacement(
        self, monkeypatch, fake_skill_dir: Path
    ) -> None:
        # Existing ID but versions.create fails → fallback to skills.create.
        # The stale ID must be reported as a replacement so the caller can
        # detach it; otherwise the agent would keep referencing a deleted skill.
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.setenv("FAKE_SKILL_ID", "skill_stale_333")

        client = MagicMock()
        client.beta.skills.versions.create.side_effect = RuntimeError("404 not found")
        client.beta.skills.create.return_value = MagicMock(id="skill_recovered_444")

        results, new_ids, replacements = bootstrap.register_all_skills(client, skills_only=True)

        assert results == {"FAKE_SKILL_ID": "skill_recovered_444"}
        assert new_ids == []  # NOT a pure addition
        assert replacements == {"skill_stale_333": "skill_recovered_444"}

    def test_total_failure_exits_nonzero(self, monkeypatch, fake_skill_dir: Path) -> None:
        # If both versions.create AND skills.create fail, sys.exit(1) is called.
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.setenv("FAKE_SKILL_ID", "skill_pre_555")

        client = MagicMock()
        client.beta.skills.versions.create.side_effect = RuntimeError("API down")
        client.beta.skills.create.side_effect = RuntimeError("API still down")

        with pytest.raises(SystemExit) as exc_info:
            bootstrap.register_all_skills(client, skills_only=True)
        assert exc_info.value.code == 1

    def test_default_mode_skips_existing(self, monkeypatch, fake_skill_dir: Path) -> None:
        # Without flags, existing IDs are skipped (no API call)
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.setenv("FAKE_SKILL_ID", "skill_already_666")

        client = MagicMock()
        results, new_ids, replacements = bootstrap.register_all_skills(client)

        assert results == {"FAKE_SKILL_ID": "skill_already_666"}
        assert new_ids == []
        assert replacements == {}
        client.beta.skills.create.assert_not_called()
        client.beta.skills.versions.create.assert_not_called()

    def test_default_mode_creates_missing_skill_for_attach(
        self, monkeypatch, fake_skill_dir: Path
    ) -> None:
        # Without flags but with a missing skill_id in .env: skills.create
        # is called and the new skill_id MUST be reported in new_skill_ids
        # so main() can attach it to an existing agent. Regression guard
        # for the "registered but not attached" silent-broken scenario.
        monkeypatch.setattr(bootstrap, "SKILL_ENV_KEYS", {"fake-skill": "FAKE_SKILL_ID"})
        monkeypatch.setattr(bootstrap, "SKILLS_DIR", fake_skill_dir.parent)
        monkeypatch.delenv("FAKE_SKILL_ID", raising=False)

        client = MagicMock()
        client.beta.skills.create.return_value = MagicMock(id="skill_freshly_added_900")

        results, new_ids, replacements = bootstrap.register_all_skills(client)

        assert results == {"FAKE_SKILL_ID": "skill_freshly_added_900"}
        assert new_ids == ["skill_freshly_added_900"]
        assert replacements == {}


class TestAttachNewSkillsToAgent:
    """Verify agents.update is called with the correct merged skill list."""

    def test_attach_dedupes_skill_ids(self) -> None:
        # Existing agent already has skill_a; we add skill_a (dup) + skill_b
        client = MagicMock()
        existing_skill = MagicMock()
        existing_skill.skill_id = "skill_a"
        client.beta.agents.retrieve.return_value = MagicMock(version=5, skills=[existing_skill])

        bootstrap.attach_new_skills_to_agent(client, "agent_id_777", ["skill_a", "skill_b"])

        client.beta.agents.update.assert_called_once()
        kwargs = client.beta.agents.update.call_args.kwargs
        assert kwargs["version"] == 5
        skill_ids = [s["skill_id"] for s in kwargs["skills"]]
        assert skill_ids == ["skill_a", "skill_b"]  # no dup

    def test_replacement_drops_stale_id_and_adds_new(self) -> None:
        # Agent has skill_stale + skill_keep. Replacement maps stale → fresh.
        # After update: skill_keep + skill_fresh (skill_stale gone).
        client = MagicMock()
        stale = MagicMock()
        stale.skill_id = "skill_stale"
        keep = MagicMock()
        keep.skill_id = "skill_keep"
        client.beta.agents.retrieve.return_value = MagicMock(version=7, skills=[stale, keep])

        bootstrap.attach_new_skills_to_agent(
            client,
            "agent_id_999",
            new_skill_ids=[],
            replacements={"skill_stale": "skill_fresh"},
        )

        client.beta.agents.update.assert_called_once()
        kwargs = client.beta.agents.update.call_args.kwargs
        skill_ids = [s["skill_id"] for s in kwargs["skills"]]
        assert "skill_stale" not in skill_ids  # detached
        assert "skill_keep" in skill_ids  # preserved
        assert "skill_fresh" in skill_ids  # newly attached

    def test_replacement_and_addition_combined(self) -> None:
        # Agent has skill_stale + skill_keep. Replace stale → fresh AND
        # add new skill_added.
        client = MagicMock()
        stale = MagicMock()
        stale.skill_id = "skill_stale"
        keep = MagicMock()
        keep.skill_id = "skill_keep"
        client.beta.agents.retrieve.return_value = MagicMock(version=10, skills=[stale, keep])

        bootstrap.attach_new_skills_to_agent(
            client,
            "agent_id_combined",
            new_skill_ids=["skill_added"],
            replacements={"skill_stale": "skill_fresh"},
        )

        kwargs = client.beta.agents.update.call_args.kwargs
        skill_ids = [s["skill_id"] for s in kwargs["skills"]]
        assert "skill_stale" not in skill_ids
        assert set(skill_ids) == {"skill_keep", "skill_added", "skill_fresh"}

    def test_no_op_when_no_changes(self) -> None:
        client = MagicMock()
        bootstrap.attach_new_skills_to_agent(client, "agent_id_888", [])
        client.beta.agents.retrieve.assert_not_called()
        client.beta.agents.update.assert_not_called()

    def test_no_op_with_empty_replacements_dict(self) -> None:
        client = MagicMock()
        bootstrap.attach_new_skills_to_agent(client, "agent_id_888", [], replacements={})
        client.beta.agents.retrieve.assert_not_called()
        client.beta.agents.update.assert_not_called()
