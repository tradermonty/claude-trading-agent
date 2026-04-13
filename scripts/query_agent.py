#!/usr/bin/env python3
"""Query the Trade Assistant Managed Agent from the command line.

Uses the same agent/environment registered by bootstrap.py. Supports skill
commands (/vcp-screener, /ftd-detector, etc.) via the same detect_skill()
logic as the Streamlit UI.

Usage:
    python scripts/query_agent.py "今週のマーケット見通しを教えて"
    python scripts/query_agent.py "/ftd-detector"
    python scripts/query_agent.py --new-session "/vcp-screener"
    python scripts/query_agent.py  # interactive mode
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from anthropic import Anthropic

from agent.client import ManagedAgentClient
from agent.sanitizer import sanitize
from skills.registry import detect_skill


def stream_response(client: ManagedAgentClient, message: str) -> str:
    """Send a message and stream the sanitized response to stdout."""
    skill_match = detect_skill(message)

    system_supplement = ""
    reference_context = ""
    if skill_match:
        system_supplement = skill_match.system_supplement
        reference_context = skill_match.reference_context
        print(f"[Skill: {skill_match.skill_name}]", file=sys.stderr)

    result_parts: list[str] = []

    for chunk in client.send_message_streaming(
        message,
        system_supplement=system_supplement,
        reference_context=reference_context,
    ):
        ctype = chunk.get("type")
        content = chunk.get("content", "")

        if ctype in {"text_delta", "text"} and content:
            safe = sanitize(content)
            print(safe, end="", flush=True)
            result_parts.append(safe)

        elif ctype == "tool_use":
            print(f"\n  [{content}]", end="", flush=True, file=sys.stderr)

        elif ctype == "error":
            print(f"\nError: {content}", file=sys.stderr)

        elif ctype == "done":
            break

    print()  # final newline
    return "".join(result_parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Trade Assistant")
    parser.add_argument("message", nargs="?", help="Message to send")
    parser.add_argument("--new-session", action="store_true", help="Force new session")
    args = parser.parse_args()

    if args.message:
        message = args.message
    else:
        print("Trade Assistant (type 'quit' to exit)")
        print("=" * 40)
        message = input("\nYou: ").strip()
        if not message or message.lower() == "quit":
            return

    client = ManagedAgentClient()

    if args.new_session:
        client.reset_session()

    try:
        stream_response(client, message)
    except Exception as e:
        print(f"\n[Session error, retrying: {e}]", file=sys.stderr)
        client.reset_session()
        stream_response(client, message)


if __name__ == "__main__":
    main()
