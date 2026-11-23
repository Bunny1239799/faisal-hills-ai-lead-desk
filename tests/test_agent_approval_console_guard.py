"""M11.7 - the approver must survive a broken console handle.

The owner's console raised `OSError: [WinError 6] The handle is
invalid` from `print(..., file=sys.__stdout__)` inside
`jarvis.agent.approval.interactive_approver`, and the approval test
failed with it.

The rules this file protects:

* a broken console handle never crashes the approver;
* the prompt falls back to `sys.stdout`, and is skipped silently when
  no stream works;
* the approval SEMANTICS are unchanged: the human's own answer decides,
  and when the human cannot be asked at all the answer is **denied**
  (``False``).
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.agent.approval import interactive_approver


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


class InvalidHandle:
    """A console whose handle is not valid any more (WinError 6)."""

    closed = False

    def write(self, text):
        raise OSError(6, "The handle is invalid")

    def flush(self):
        raise OSError(6, "The handle is invalid")

    def isatty(self):
        return False


def test_a_broken_stdout_does_not_crash_and_the_answer_is_honoured(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeTTY("y\n"))
    monkeypatch.setattr(sys, "__stdout__", InvalidHandle())

    # no exception, and the human's "y" is still an approval
    assert interactive_approver("edit_file", {"relative_path": "x"},
                                "modifies an existing file") is True


def test_a_broken_stdout_falls_back_to_sys_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", FakeTTY("y\n"))
    monkeypatch.setattr(sys, "__stdout__", InvalidHandle())

    interactive_approver("edit_file", {"relative_path": "x"},
                         "modifies an existing file")

    captured = capsys.readouterr()
    assert "APPROVAL REQUIRED" in captured.out
    assert "Type y then Enter to approve" in captured.out


def test_no_console_at_all_denies(monkeypatch):
    """When the human cannot be asked, nothing is approved."""
    monkeypatch.setattr(sys, "stdin", FakeTTY("y\n"))
    monkeypatch.setattr(sys, "__stdout__", InvalidHandle())
    monkeypatch.setattr(sys, "stdout", InvalidHandle())

    assert interactive_approver("edit_file", {"relative_path": "x"},
                                "modifies an existing file") is False


def test_an_unreadable_answer_denies(monkeypatch):
    class BrokenInput:
        def isatty(self):
            return True

        def readline(self, *args):
            raise OSError(6, "The handle is invalid")

    monkeypatch.setattr(sys, "stdin", BrokenInput())
    assert interactive_approver("edit_file", {"relative_path": "x"},
                                "modifies an existing file") is False


def test_no_terminal_still_denies(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    assert interactive_approver("edit_file", {"relative_path": "x"},
                                "modifies an existing file") is False
