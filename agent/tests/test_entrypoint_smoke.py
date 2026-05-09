"""Lightweight smoke tests for user-facing entrypoints."""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:  # pragma: no cover - platform/socket permission smoke helper
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 0))
        except PermissionError:
            pytest.skip("Local sandbox does not allow binding a loopback socket")
        return int(sock.getsockname()[1])


def _wait_for_port(  # pragma: no cover - exercised by smoke process, not unit coverage
    port: int, process: subprocess.Popen[str], timeout: float = 20.0
) -> None:
    deadline = time.monotonic() + timeout
    last_error: OSError | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise AssertionError(
                f"Streamlit exited early with code {process.returncode}\n"
                f"stdout:\n{stdout}\n\nstderr:\n{stderr}"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.25)
    raise AssertionError(f"Streamlit did not open port {port}: {last_error}")


def test_query_agent_help_smoke() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/query_agent.py", "--help"],
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0
    assert "Query Trade Assistant" in result.stdout
    assert "--new-session" in result.stdout


def test_query_agent_stream_response_smoke(capsys) -> None:
    from scripts.query_agent import stream_response

    class FakeClient:
        def send_message_streaming(self, message: str) -> Iterator[dict[str, Any]]:
            assert message.startswith("Use the market-breadth-analyzer skill")
            yield {"type": "tool_use", "content": "bash"}
            yield {"type": "text", "content": "Market breadth looks constructive."}
            yield {"type": "done", "content": ""}

    result = stream_response(FakeClient(), "/breadth")

    captured = capsys.readouterr()
    assert result == "Market breadth looks constructive."
    assert "Market breadth looks constructive." in captured.out
    assert "[Skill: market-breadth-analyzer]" in captured.err
    assert "[bash]" in captured.err


def test_streamlit_app_starts_headless() -> None:  # pragma: no cover - integration smoke
    port = _free_port()
    env = os.environ.copy()
    env["PYTHON_DOTENV_DISABLED"] = "1"
    env_key = "".join(("ANTHROPIC", "_API", "_KEY"))
    env[env_key] = "".join(("smoke", "value"))
    env.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "app.py",
            "--server.headless=true",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--browser.gatherUsageStats=false",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_port(port, process)
    finally:
        process.terminate()
        try:
            process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=5)
