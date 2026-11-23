import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(r"D:\AI-Projects\laya-gateway")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from jarvis.agent import loop
from jarvis.agent.core import available_tools, execute_tool
from jarvis.agent.engineering_tools import apply_patch, create_backup, create_file, edit_file
from jarvis.agent.tools import ToolError

REL = "jarvis/sandbox/stage4_tmp"
WORK = ROOT / "jarvis" / "sandbox" / "stage4_tmp"
BACKUPS = ROOT / "backups" / "jarvis"
PATCH = "--- a/f.txt\n+++ b/f.txt\n@@ -1,3 +1,3 @@\n alpha\n-beta\n+BETA\n gamma\n"


@pytest.fixture
def work():
    WORK.mkdir(parents=True, exist_ok=True)
    yield WORK
    shutil.rmtree(WORK, ignore_errors=True)
    if BACKUPS.exists():
        for f in BACKUPS.glob("jarvis__sandbox__stage4_tmp__*"):
            f.unlink()


def _write(name, data):
    p = WORK / name
    p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    return f"{REL}/{name}"


def test_four_stage4_tools_registered_yellow():
    perms = {t["name"]: t["permission"] for t in available_tools()}
    for name in ("create_file", "edit_file", "create_backup", "apply_patch"):
        assert perms.get(name) == "YELLOW", name


def test_exposure_stage4_tools_visible_run_python_hidden():
    names = {s["function"]["name"] for s in loop.build_tool_schemas()}
    assert "create_backup" in names
    assert "edit_file" in names and "apply_patch" in names
    assert "run_python" not in names


def test_create_backup_copies_file(work):
    rel = _write("a.txt", "hello")
    result = create_backup(rel)
    assert (ROOT / result["backup"]).read_text(encoding="utf-8") == "hello"


def test_create_backup_blocks_protected_file():
    with pytest.raises(ToolError):
        create_backup("jarvis/agent/loop.py")


def test_create_file_refuses_overwrite_by_default(work):
    rel = f"{REL}/new.txt"
    create_file(rel, "one")
    with pytest.raises(ToolError):
        create_file(rel, "two")
    assert (ROOT / rel).read_text(encoding="utf-8") == "one"
    create_file(rel, "two", overwrite=True)
    assert (ROOT / rel).read_text(encoding="utf-8") == "two"


def test_edit_file_unique_replacement(work):
    rel = _write("e.txt", "alpha\nbeta\ngamma\n")
    edit_file(rel, "beta", "BETA")
    text = (ROOT / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == "alpha\nBETA\ngamma\n"


def test_edit_file_rejects_missing_and_ambiguous(work):
    rel = _write("e2.txt", "x\nx\ny\n")
    with pytest.raises(ToolError):
        edit_file(rel, "x", "z")
    with pytest.raises(ToolError):
        edit_file(rel, "nope", "z")
    assert (ROOT / rel).read_bytes() == b"x\nx\ny\n"


def test_apply_patch_dry_run_leaves_file_unchanged(work):
    rel = _write("p1.txt", "alpha\nbeta\ngamma\n")
    result = apply_patch(rel, PATCH)
    assert result["dry_run"] and result["would_change"] and result["backup"] is None
    assert (ROOT / rel).read_bytes() == b"alpha\nbeta\ngamma\n"


def test_apply_patch_applies_and_backs_up(work):
    rel = _write("p2.txt", "alpha\nbeta\ngamma\n")
    result = apply_patch(rel, PATCH, dry_run=False)
    assert (ROOT / rel).read_bytes() == b"alpha\nBETA\ngamma\n"
    assert (ROOT / result["backup"]["backup"]).read_bytes() == b"alpha\nbeta\ngamma\n"


def test_apply_patch_rejects_ambiguous_context(work):
    rel = _write("p3.txt", "x\nsame\ny\nsame\nz\n")
    with pytest.raises(ToolError):
        apply_patch(rel, "@@\n-same\n+SAME\n", dry_run=False)
    assert (ROOT / rel).read_bytes() == b"x\nsame\ny\nsame\nz\n"


def test_apply_patch_rejects_missing_context(work):
    rel = _write("p4.txt", "alpha\nbeta\n")
    with pytest.raises(ToolError):
        apply_patch(rel, "@@\n-absent\n+x\n", dry_run=False)
    assert (ROOT / rel).read_bytes() == b"alpha\nbeta\n"


def test_apply_patch_preserves_crlf(work):
    rel = _write("p5.txt", b"alpha\r\nbeta\r\ngamma\r\n")
    apply_patch(rel, PATCH, dry_run=False)
    assert (ROOT / rel).read_bytes() == b"alpha\r\nBETA\r\ngamma\r\n"


def test_apply_patch_blocks_protected_and_escape():
    with pytest.raises(ToolError):
        apply_patch("jarvis/agent/loop.py", PATCH)
    with pytest.raises(ToolError):
        apply_patch("../outside.txt", PATCH)


def test_apply_patch_works_through_core_execute_tool(work):
    rel = _write("p6.txt", "alpha\nbeta\ngamma\n")
    out = execute_tool("apply_patch", {"relative_path": rel, "patch_text": PATCH})
    assert out["success"] and out["permission"] == "YELLOW"
    assert out["result"]["dry_run"] is True
    assert (ROOT / rel).read_bytes() == b"alpha\nbeta\ngamma\n"