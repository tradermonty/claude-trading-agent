"""Skill registry — slash-command routing and lean prompt normalization.

The Anthropic Managed Agents API auto-loads skills based on their
SKILL.md description (progressive disclosure). This registry only
needs to:

  1. Detect slash commands (/vcp-screener etc.) and trigger keywords
     from user input — for deterministic routing on top of the
     description-based auto-load.
  2. Build a lean instruction prefix ("Use the X skill for this
     request: ...") that the agent receives as the first content
     block of the user message.
  3. Expose ALL_SKILLS for UI listing (sidebar in Streamlit, /help
     in CLI).

It does NOT load SKILL.md files or `references/` blobs into the
prompt — that responsibility belongs to Managed Skills auto-load.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).resolve().parent


@dataclass
class SkillDefinition:
    """A registered skill with slash command and keyword triggers."""

    name: str
    command: str
    trigger_keywords: list[str] = field(default_factory=list)

    def matches(self, user_message: str) -> str | None:
        """Return the argument/headline if the message triggers this skill, else None.

        - Exact slash command (`/breadth`) → return ``self.name``
        - Slash command + space/tab + argument (`/breadth show me ...`) →
          return the trimmed argument
        - Any trigger keyword found anywhere in ``user_message`` → return
          the original message (treated as the argument/headline)

        Slash detection uses a strict boundary check: ``/breadthfoo`` will
        NOT match ``/breadth``.
        """
        msg = user_message.strip()

        if msg == self.command:
            return self.name
        if msg.startswith(self.command + " ") or msg.startswith(self.command + "\t"):
            arg = msg[len(self.command) :].strip().strip('"').strip("'").strip()
            return arg if arg else self.name

        # Both sides lowercased so uppercase keywords like "FOMC" or
        # "CPI発表" match natural input regardless of case.
        msg_lower = msg.lower()
        for kw in self.trigger_keywords:
            if kw.lower() in msg_lower:
                return msg

        return None


# --- Registry ---

SCENARIO_ANALYZER = SkillDefinition(
    name="scenario-analyzer",
    command="/scenario-analyzer",
    trigger_keywords=["ニュース分析", "シナリオ分析", "18ヶ月展望", "中長期投資戦略"],
)

FTD_DETECTOR = SkillDefinition(
    name="ftd-detector",
    command="/ftd-detector",
    trigger_keywords=[
        "ftd",
        "フォロースルーデイ",
        "市場底入れ",
        "follow-through day",
        "底入れ確認",
    ],
)

VCP_SCREENER = SkillDefinition(
    name="vcp-screener",
    command="/vcp-screener",
    trigger_keywords=[
        "vcp",
        "ボラティリティ収縮",
        "ミネルヴィニ",
        "ブレイクアウト候補",
        "volatility contraction",
    ],
)

MACRO_REGIME_DETECTOR = SkillDefinition(
    name="macro-regime-detector",
    command="/macro-regime",
    trigger_keywords=[
        "マクロレジーム",
        "レジーム検出",
        "マクロ環境",
        "regime detection",
        "macro regime",
    ],
)

CANSLIM_SCREENER = SkillDefinition(
    name="canslim-screener",
    command="/canslim",
    trigger_keywords=["canslim", "キャンスリム", "成長株スクリーニング", "growth stock screening"],
)

THEME_DETECTOR = SkillDefinition(
    name="theme-detector",
    command="/theme-detector",
    trigger_keywords=[
        "テーマ検出",
        "市場テーマ",
        "セクターローテーション",
        "trending themes",
        "theme detector",
    ],
)

MARKET_BREADTH_ANALYZER = SkillDefinition(
    name="market-breadth-analyzer",
    command="/breadth",
    trigger_keywords=["市場幅", "ブレッス", "参加率", "market breadth", "advance decline"],
)

EARNINGS_CALENDAR = SkillDefinition(
    name="earnings-calendar",
    command="/earnings",
    trigger_keywords=["決算カレンダー", "earnings calendar", "決算発表", "earnings report"],
)

ECONOMIC_CALENDAR = SkillDefinition(
    name="economic-calendar-fetcher",
    command="/econ-calendar",
    trigger_keywords=[
        "経済カレンダー",
        "economic calendar",
        "経済指標",
        "FOMC",
        "雇用統計",
        "CPI発表",
    ],
)

BREAKOUT_TRADE_PLANNER = SkillDefinition(
    name="breakout-trade-planner",
    command="/breakout-plan",
    trigger_keywords=[
        "ブレイクアウト計画",
        "トレードプラン",
        "breakout plan",
        "エントリー計画",
        "ポジションサイズ",
    ],
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


def normalize_command(user_message: str) -> tuple[str, str | None]:
    """Route a user message to a skill if applicable and return (send_text, skill_name).

    - On match: ``send_text`` is rewritten to
      ``"Use the {skill_name} skill for this request: {headline}"`` so
      Managed Skills auto-load can deterministically pick the right
      skill. ``skill_name`` is returned for UI display (e.g. status badge).
    - On no match: ``send_text`` is the original ``user_message`` and
      ``skill_name`` is ``None``.

    Caller is responsible for separately preserving the original input
    in chat history / display, so the user never sees the rewritten
    "Use the X skill ..." string.
    """
    for skill in ALL_SKILLS:
        headline = skill.matches(user_message)
        if headline is not None:
            logger.info("Skill matched: %s (headline: %s)", skill.name, headline[:80])
            send_text = f"Use the {skill.name} skill for this request: {headline}"
            return send_text, skill.name
    return user_message, None
