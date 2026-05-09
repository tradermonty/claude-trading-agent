"""Skill registry — detects skill commands and builds enriched prompts."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent


def _refs_disabled_skills() -> set[str]:
    """Parse SKILLS_REFS_DISABLED env into a set of skill names.

    Strips whitespace and drops empty entries so values like
    " market-breadth-analyzer ,vcp-screener" parse cleanly. Phase 2 evaluation
    aid: per-skill suppression of the (large) reference_context blob to
    measure whether Managed Skills auto-load alone is sufficient.
    """
    raw = os.getenv("SKILLS_REFS_DISABLED", "")
    return {x.strip() for x in raw.split(",") if x.strip()}


@dataclass
class SkillMatch:
    """Result of matching a user message to a skill.

    system_supplement and reference_context are consumed by the legacy
    skill-session path (LEGACY_SKILL_SESSION=1). skill_hint is the lean
    user-message prefix used by the default path that reuses the existing
    session and lets Managed Skills auto-load.
    """

    skill_name: str
    headline: str
    system_supplement: str
    reference_context: str
    skill_hint: str = ""


@dataclass
class SkillDefinition:
    """A registered skill with trigger detection and reference loading."""

    name: str
    command: str
    trigger_keywords: list[str]
    skill_dir: Path
    reference_files: list[str] = field(default_factory=list)

    def matches(self, user_message: str) -> str | None:
        """Return the headline/argument if the message triggers this skill, else None."""
        msg = user_message.strip()

        # Explicit command: exact match or command followed by whitespace/argument.
        # Prevents partial matches like "/breadthfoo" matching "/breadth".
        if msg == self.command:
            return self.name
        if msg.startswith(self.command + " ") or msg.startswith(self.command + "\t"):
            arg = msg[len(self.command):].strip().strip('"').strip("'").strip()
            return arg if arg else self.name

        # Keyword trigger
        msg_lower = msg.lower()
        for kw in self.trigger_keywords:
            if kw in msg_lower:
                return msg

        return None

    def load_references(self) -> str:
        """Load reference files and return concatenated content."""
        parts: list[str] = []
        refs_dir = self.skill_dir / "references"
        for filename in self.reference_files:
            path = refs_dir / filename
            if path.exists():
                content = path.read_text(encoding="utf-8")
                parts.append(f"### {filename}\n\n{content}")
            else:
                logger.warning("Reference file not found: %s", path)
        return "\n\n---\n\n".join(parts)

    def load_skill_instructions(self) -> str:
        """Load the SKILL.md content."""
        skill_md = self.skill_dir / "SKILL.md"
        if skill_md.exists():
            return skill_md.read_text(encoding="utf-8")
        return ""


# --- Registry ---

SCENARIO_ANALYZER = SkillDefinition(
    name="scenario-analyzer",
    command="/scenario-analyzer",
    trigger_keywords=["ニュース分析", "シナリオ分析", "18ヶ月展望", "中長期投資戦略"],
    skill_dir=SKILLS_DIR / "scenario-analyzer",
    reference_files=[
        "headline_event_patterns.md",
        "sector_sensitivity_matrix.md",
        "scenario_playbooks.md",
    ],
)

FTD_DETECTOR = SkillDefinition(
    name="ftd-detector",
    command="/ftd-detector",
    trigger_keywords=["ftd", "フォロースルーデイ", "市場底入れ", "follow-through day", "底入れ確認"],
    skill_dir=SKILLS_DIR / "ftd-detector",
    reference_files=[
        "ftd_methodology.md",
        "post_ftd_guide.md",
    ],
)

VCP_SCREENER = SkillDefinition(
    name="vcp-screener",
    command="/vcp-screener",
    trigger_keywords=["vcp", "ボラティリティ収縮", "ミネルヴィニ", "ブレイクアウト候補", "volatility contraction"],
    skill_dir=SKILLS_DIR / "vcp-screener",
    reference_files=[
        "vcp_methodology.md",
        "scoring_system.md",
        "fmp_api_endpoints.md",
    ],
)

MACRO_REGIME_DETECTOR = SkillDefinition(
    name="macro-regime-detector",
    command="/macro-regime",
    trigger_keywords=["マクロレジーム", "レジーム検出", "マクロ環境", "regime detection", "macro regime"],
    skill_dir=SKILLS_DIR / "macro-regime-detector",
    reference_files=[
        "regime_detection_methodology.md",
        "indicator_interpretation_guide.md",
        "historical_regimes.md",
    ],
)

CANSLIM_SCREENER = SkillDefinition(
    name="canslim-screener",
    command="/canslim",
    trigger_keywords=["canslim", "キャンスリム", "成長株スクリーニング", "growth stock screening"],
    skill_dir=SKILLS_DIR / "canslim-screener",
    reference_files=[
        "canslim_methodology.md",
        "scoring_system.md",
        "fmp_api_endpoints.md",
        "interpretation_guide.md",
    ],
)

THEME_DETECTOR = SkillDefinition(
    name="theme-detector",
    command="/theme-detector",
    trigger_keywords=["テーマ検出", "市場テーマ", "セクターローテーション", "trending themes", "theme detector"],
    skill_dir=SKILLS_DIR / "theme-detector",
    reference_files=[
        "theme_detection_methodology.md",
        "thematic_etf_catalog.md",
        "cross_sector_themes.md",
        "finviz_industry_codes.md",
    ],
)

MARKET_BREADTH_ANALYZER = SkillDefinition(
    name="market-breadth-analyzer",
    command="/breadth",
    trigger_keywords=["市場幅", "ブレッス", "参加率", "market breadth", "advance decline"],
    skill_dir=SKILLS_DIR / "market-breadth-analyzer",
    reference_files=[
        "breadth_analysis_methodology.md",
    ],
)

EARNINGS_CALENDAR = SkillDefinition(
    name="earnings-calendar",
    command="/earnings",
    trigger_keywords=["決算カレンダー", "earnings calendar", "決算発表", "earnings report"],
    skill_dir=SKILLS_DIR / "earnings-calendar",
    reference_files=["fmp_api_guide.md"],
)

ECONOMIC_CALENDAR = SkillDefinition(
    name="economic-calendar-fetcher",
    command="/econ-calendar",
    trigger_keywords=["経済カレンダー", "economic calendar", "経済指標", "FOMC", "雇用統計", "CPI発表"],
    skill_dir=SKILLS_DIR / "economic-calendar-fetcher",
    reference_files=["fmp_api_documentation.md"],
)

BREAKOUT_TRADE_PLANNER = SkillDefinition(
    name="breakout-trade-planner",
    command="/breakout-plan",
    trigger_keywords=["ブレイクアウト計画", "トレードプラン", "breakout plan", "エントリー計画", "ポジションサイズ"],
    skill_dir=SKILLS_DIR / "breakout-trade-planner",
    reference_files=["minervini_entry_rules.md"],
)

IBD_DISTRIBUTION_DAY_MONITOR = SkillDefinition(
    name="ibd-distribution-day-monitor",
    command="/ibd-dd",
    trigger_keywords=[
        "distribution day",
        "ディストリビューションデイ",
        "ディストリビューション・デイ",
        "ibd distribution",
        "tqqq exposure",
        "tqqqエクスポージャー",
    ],
    skill_dir=SKILLS_DIR / "ibd-distribution-day-monitor",
    reference_files=[
        "ibd_distribution_methodology.md",
        "tqqq_exposure_policy.md",
    ],
)

ALL_SKILLS: list[SkillDefinition] = [
    SCENARIO_ANALYZER,
    FTD_DETECTOR,
    VCP_SCREENER,
    MACRO_REGIME_DETECTOR,
    CANSLIM_SCREENER,
    THEME_DETECTOR,
    MARKET_BREADTH_ANALYZER,
    EARNINGS_CALENDAR,
    ECONOMIC_CALENDAR,
    BREAKOUT_TRADE_PLANNER,
    IBD_DISTRIBUTION_DAY_MONITOR,
]


def detect_skill(user_message: str) -> SkillMatch | None:
    """Check if a user message triggers any registered skill."""
    refs_disabled = _refs_disabled_skills()

    for skill in ALL_SKILLS:
        headline = skill.matches(user_message)
        if headline is not None:
            logger.info("Skill matched: %s (headline: %s)", skill.name, headline[:80])
            instructions = skill.load_skill_instructions()

            if skill.name in refs_disabled:
                logger.info("References disabled for %s via SKILLS_REFS_DISABLED", skill.name)
                references = ""
            else:
                references = skill.load_references()

            system_supplement = (
                f"## Active Skill: {skill.name}\n\n"
                f"The user has triggered the '{skill.name}' skill. "
                f"Follow the workflow defined below to produce the analysis.\n\n"
                f"{instructions}"
            )

            reference_context = (
                f"## Reference Materials for {skill.name}\n\n{references}"
                if references
                else ""
            )

            skill_hint = (
                f"Use the {skill.name} skill for this request: {headline}"
            )

            return SkillMatch(
                skill_name=skill.name,
                headline=headline,
                system_supplement=system_supplement,
                reference_context=reference_context,
                skill_hint=skill_hint,
            )
    return None
