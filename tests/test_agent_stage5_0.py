import pytest
from pathlib import Path
from jarvis.agent import engineering_tools
from jarvis.agent.engineering_tools import update_state_file
from jarvis.agent.approval import gated_execute, needs_approval
from jarvis.agent.tools import ToolError

def test_update_state_file_needs_approval():
    reason = needs_approval("update_state_file", {"filename": "TASKS.md"})
    assert reason is not None
    assert "modifies a project state file" in reason

def test_update_state_file_disallowed():
    with pytest.raises(ToolError, match="Access denied"):
        update_state_file("secrets.md", "content")

def test_update_state_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(engineering_tools, "JARVIS_CORE_DIR", tmp_path / "Core")
    # Directory exists but file doesn't
    (tmp_path / "Core").mkdir()
    with pytest.raises(ToolError, match="State file missing"):
        update_state_file("TASKS.md", "content")

def test_update_state_file_success(tmp_path, monkeypatch):
    core = tmp_path / "Core"
    backups = tmp_path / "Backups"
    core.mkdir()

    target = core / "TASKS.md"
    target.write_text("old", encoding="ascii")

    monkeypatch.setattr(engineering_tools, "JARVIS_CORE_DIR", core)
    monkeypatch.setattr(engineering_tools, "JARVIS_BACKUP_DIR", backups)

    res = update_state_file("TASKS.md", "new content")

    assert res["success"] is True
    assert target.read_text(encoding="ascii") == "new content"

    # Check backup
    backup_files = list(backups.glob("TASKS.md.*.bak"))
    assert len(backup_files) == 1
    assert backup_files[0].read_text(encoding="ascii") == "old"

def test_gated_execute_update_state_file_denied(tmp_path, monkeypatch):
    # Even if the file exists, it should fail if approval is denied
    core = tmp_path / "Core"
    core.mkdir()
    target = core / "TASKS.md"
    target.write_text("old", encoding="ascii")

    monkeypatch.setattr(engineering_tools, "JARVIS_CORE_DIR", core)
    monkeypatch.setattr(engineering_tools, "JARVIS_BACKUP_DIR", tmp_path / "Backups")

    # Redirect audit log during test
    monkeypatch.setattr("jarvis.agent.approval.AUDIT_PATH", tmp_path / "audit.jsonl")

    res = gated_execute("update_state_file", {"filename": "TASKS.md", "content": "new"},
                        approver=lambda *a: False)

    assert res["success"] is False
    assert "approval was denied" in res["error"]
    assert target.read_text(encoding="ascii") == "old"
