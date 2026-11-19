"""How the Managed Agent runs the skill (#108-#110).

The agent follows SKILL.md literally inside a sandbox where API keys arrive
only through the system prompt, so blank keys and doc examples are contracts.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import theme_detector

SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"


@pytest.mark.parametrize("flag", ["--fmp-api-key", "--finviz-api-key"])
def test_blank_cli_key_is_treated_as_absent(monkeypatch, flag):
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    monkeypatch.delenv("FINVIZ_API_KEY", raising=False)
    monkeypatch.setattr("sys.argv", ["theme_detector.py", flag, ""])
    args = theme_detector.parse_args()
    assert args.fmp_api_key is None
    assert args.finviz_api_key is None


def test_blank_env_key_is_treated_as_absent(monkeypatch):
    monkeypatch.setenv("FMP_API_KEY", "  ")
    monkeypatch.setenv("FINVIZ_API_KEY", "")
    monkeypatch.setattr("sys.argv", ["theme_detector.py"])
    args = theme_detector.parse_args()
    assert args.fmp_api_key is None
    assert args.finviz_api_key is None


def _skill_commands() -> list[str]:
    text = SKILL_MD.read_text()
    blocks = re.findall(r"```bash\n(.*?)```", text, flags=re.S)
    commands = []
    for block in blocks:
        joined = block.replace("\\\n", " ")
        commands += [line for line in joined.splitlines() if "theme_detector.py" in line]
    return commands


def test_every_skill_example_uses_dynamic_stocks_except_the_static_one():
    commands = _skill_commands()
    assert len(commands) >= 5
    without = [c for c in commands if "--dynamic-stocks" not in c]
    # Exactly one deliberate static example remains, preceded by its label.
    assert len(without) == 1
    assert "# Static representative stocks only" in SKILL_MD.read_text()


def test_skill_never_prints_or_passes_keys_on_the_command_line():
    text = SKILL_MD.read_text()
    assert not re.search(r"echo \$\w*API_KEY", text)
    for command in _skill_commands():
        assert "--fmp-api-key" not in command
        assert "--finviz-api-key" not in command
