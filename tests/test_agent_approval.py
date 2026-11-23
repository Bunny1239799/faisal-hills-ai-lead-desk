import io
import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.agent import approval, loop
from jarvis.agent.approval import gated_execute, interactive_approver, needs_approval

REL = "jarvis/sandbox/stage42_tmp"
WORK = ROOT / "jarvis" / "sandbox" / "stage42_tmp"
BACKUPS = ROOT / "backups" / "jarvis"
PATCH = "--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma\n"


@pytest.fixture
def work(tmp_path, monkeypatch):
    monkeypatch.setattr(approval, "AUDIT_PATH", tmp_path / "audit.jsonl")
    WORK.mkdir(parents=True, exist_ok=True)
    yield WORK
    shutil.rmtree(WORK, ignore_errors=True)
    if BACKUPS.exists():
        for f in BACKUPS.glob("jarvis__sandbox__stage42_tmp__*"):
            f.unlink()


def _write(name, data):
    p = WORK / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return f"{REL}/{name}"


def _fake_model(tool_name, arguments):
    calls = {"n": 0}

    def fake_chat(messages, tools=None, timeout=0, model=None, num_predict=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"message": {"role": "assistant", "content": "",
                                "tool_calls": [{"function": {"name": tool_name, "arguments": arguments}}]}}
        last_tool = [m for m in messages if m.get("role") == "tool"][-1]
        return {"message": {"role": "assistant", "content": last_tool["content"]}}

    return fake_chat


class FakeTTY:
    def __init__(self, text):
        self._lines = io.StringIO(text)

    def isatty(self):
        return True

    def readline(self, *args):
        return self._lines.readline()


def test_policy_table():
    assert needs_approval("create_file", {"relative_path": "x", "content": "c"}) is None
    assert needs_approval("create_file", {"overwrite": True})
    assert needs_approval("create_file", {"overwrite": "true"})
    assert needs_approval("edit_file", {})
    assert needs_approval("apply_patch", {}) is None
    assert needs_approval("apply_patch", {"dry_run": True}) is None
    assert needs_approval("apply_patch", {"dry_run": False})
    assert needs_approval("apply_patch", {"dry_run": "false"})
    assert needs_approval("run_python", {})
    for name in ("create_backup", "run_tests", "list_directory", "read_file"):
        assert needs_approval(name, {}) is None


def test_denied_edit_changes_nothing(work):
    rel = _write("a.txt", "alpha beta\n")
    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "BETA"}
    out = gated_execute("edit_file", args, approver=lambda *a: False)
    assert out["success"] is False and "approval" in out["error"].lower()
    assert (ROOT / rel).read_bytes() == b"alpha beta\n"


def test_approved_edit_is_applied(work):
    rel = _write("b.txt", "alpha beta\n")
    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "BETA"}
    out = gated_execute("edit_file", args, approver=lambda *a: True)
    assert out["success"] is True
    text = (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == "alpha BETA\n"


def test_approver_exception_means_denied(work):
    rel = _write("c.txt", "alpha beta\n")

    def broken(*args):
        raise RuntimeError("approver crashed")

    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "BETA"}
    out = gated_execute("edit_file", args, approver=broken)
    assert out["success"] is False
    assert (ROOT / rel).read_bytes() == b"alpha beta\n"


def test_apply_patch_dry_run_needs_no_approval(work):
    rel = _write("d.txt", "alpha\nbeta\ngamma\n")
    called = []
    out = gated_execute("apply_patch", {"relative_path": rel, "patch_text": PATCH},
                        approver=lambda *a: called.append(1) or True)
    assert out["success"] is True and called == []
    assert (ROOT / rel).read_bytes() == b"alpha\nbeta\ngamma\n"


def test_apply_patch_real_write_requires_approval(work):
    rel = _write("e.txt", "alpha\nbeta\ngamma\n")
    args = {"relative_path": rel, "patch_text": PATCH, "dry_run": False}
    out = gated_execute("apply_patch", args, approver=lambda *a: False)
    assert out["success"] is False
    assert (ROOT / rel).read_bytes() == b"alpha\nbeta\ngamma\n"
    out = gated_execute("apply_patch", args, approver=lambda *a: True)
    assert out["success"] is True
    assert (ROOT / rel).read_bytes() == b"alpha\nBETA\ngamma\n"


def test_create_file_overwrite_requires_approval(work):
    rel = _write("o.txt", "one")
    calls = []

    def deny(*args):
        calls.append(args)
        return False

    out = gated_execute("create_file", {"relative_path": rel, "content": "two", "overwrite": True}, approver=deny)
    assert out["success"] is False and len(calls) == 1
    assert (ROOT / rel).read_bytes() == b"one"
    calls.clear()
    out = gated_execute("create_file", {"relative_path": f"{REL}/fresh.txt", "content": "x"}, approver=deny)
    assert out["success"] is True and calls == []


def test_audit_log_records_decisions_without_content(work):
    rel = _write("f.txt", "alpha beta\n")
    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "SECRETCONTENT"}
    gated_execute("edit_file", args, approver=lambda *a: False)
    gated_execute("edit_file", args, approver=lambda *a: True)
    text = approval.AUDIT_PATH.read_text(encoding="utf-8")
    records = [json.loads(line) for line in text.splitlines()]
    events = [r["event"] for r in records]
    for needed in ("TOOL_APPROVAL_REQUESTED", "TOOL_APPROVAL_DENIED", "TOOL_APPROVAL_GRANTED", "TOOL_EXECUTED"):
        assert needed in events
    assert "SECRETCONTENT" not in text
    assert all({"timestamp", "level", "event", "details"} <= set(r) for r in records)


def test_interactive_approver_denies_without_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("y\n"))
    assert interactive_approver("edit_file", {"relative_path": "x"}, "modifies an existing file") is False


def test_interactive_approver_accepts_y_on_terminal(monkeypatch):
    monkeypatch.setattr(sys, "stdin", FakeTTY("y\n"))
    assert interactive_approver("edit_file", {"relative_path": "x"}, "modifies an existing file") is True
    monkeypatch.setattr(sys, "stdin", FakeTTY("n\n"))
    assert interactive_approver("edit_file", {"relative_path": "x"}, "modifies an existing file") is False


def test_loop_denies_edit_through_agent_loop(work, monkeypatch):
    rel = _write("g.txt", "alpha beta\n")
    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "BETA"}
    monkeypatch.setattr(loop, "chat", _fake_model("edit_file", args))
    result = loop.run_agent("hello", timeout=5, approver=lambda *a: False)
    assert "approval" in result["content"].lower()
    assert (ROOT / rel).read_bytes() == b"alpha beta\n"


def test_loop_allows_edit_when_approved(work, monkeypatch):
    rel = _write("h.txt", "alpha beta\n")
    args = {"relative_path": rel, "expected_text": "beta", "replacement_text": "BETA"}
    monkeypatch.setattr(loop, "chat", _fake_model("edit_file", args))
    loop.run_agent("hello", timeout=5, approver=lambda *a: True)
    text = (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == "alpha BETA\n"


def test_edit_and_patch_exposed_run_python_hidden():
    names = {s["function"]["name"] for s in loop.build_tool_schemas()}
    assert "edit_file" in names and "apply_patch" in names
    assert "run_python" not in names