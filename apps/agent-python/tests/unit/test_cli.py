"""Smoke tests for the CLI available in the w1.4 scaffold."""

import subprocess
import sys

import pytest

from agent_app.cli import main


@pytest.mark.parametrize("args", [[], ["-h"], ["--help"]])
def test_help(args, capsys):
    assert main(args) == 0

    captured = capsys.readouterr()
    assert "agent-cli" in captured.out
    assert "chat" in captured.out
    assert "replay" in captured.out
    assert captured.err == ""


def test_unknown_command(capsys):
    assert main(["not-a-command"]) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not-a-command" in captured.err


def test_module_reports_invalid_command_with_nonzero_exit_status():
    result = subprocess.run(
        [sys.executable, "-m", "agent_app.cli", "not-a-command"],
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    assert result.stdout == b""
    assert b"not-a-command" in result.stderr
