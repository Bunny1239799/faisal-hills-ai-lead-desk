"""Stage 1 - the versioned inventory workspace.

Covers the card's acceptance surface:

* template download (explicit units, formula-injection escaping)
* happy path upload -> validate -> approve -> activate
* A/B swap: the same question answers from the ACTIVE version and carries
  that version's stamp
* inactive invariant: with no pointer the product serves the configured
  master, exactly as before
* failed uploads (malformed, oversized, traversal name, binary)
* interrupted activation leaves the previous active version intact
* rollback A -> B -> A with the full audit sequence
* version stamps on every turn + the one-shot version-change notice
* protected master files untouched by the whole cycle

The workspace is pointed at ``tmp_path`` in every test, so the founder's
real agency_workspace and the pilot stores are never touched.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.server import app
from app.turn_pipeline import run_turn
from tests.asgi_client import call_asgi, post_json

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures"

MASTER_CANDIDATES = (
    Path(r"D:\AI-Projects\real-estate-agent\approved_data\master_inventory.jsonl"),
    Path(r"D:\FaisalHills_Master_Data\07_MASTER\master_inventory.jsonl"),
)

PROTECTED_FILES = (
    Path(r"D:\FaisalHills_Master_Data\07_MASTER\master_inventory.jsonl"),
    Path(r"D:\AI-Projects\real-estate-agent\approved_data\master_inventory.jsonl"),
    ROOT / "evaluation" / "datasets" / "production" / "real_dealer_questions_v1.jsonl",
    ROOT / "evaluation" / "datasets" / "production"
    / "real_dealer_questions_v1.manifest.json",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """An isolated workspace + isolated stores for one test."""
    from market import inventory_workspace as ws

    ws_dir = tmp_path / "workspace"
    monkeypatch.setenv("FH_INVENTORY_WORKSPACE_DIR", str(ws_dir))
    monkeypatch.setenv("M11_STATE_DB", str(tmp_path / "state.db"))
    monkeypatch.setenv("M11_DEMAND_DB", str(tmp_path / "demand.db"))
    monkeypatch.setenv("M12_LOG_DB", str(tmp_path / "log.db"))
    monkeypatch.setenv("LEAD_PIPELINE_DB", str(tmp_path / "pipeline.db"))
    ws._clear_cache()
    ws._SESSION_LAST.clear()
    ws._SESSION_LOADED[0] = False
    yield ws
    ws._clear_cache()


def _upload(ws, fixture_name: str, actor: str = "tester"):
    data = (FIXTURES / fixture_name).read_bytes()
    return ws.create_upload(data, fixture_name, actor=actor)


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def test_template_download_has_explicit_units_and_escapes_cells(workspace):
    status, body = call_asgi(app, "GET", "/api/inventory/template.csv")
    assert status == 200
    text = body.decode("utf-8")
    header = [line for line in text.splitlines()
              if line and not line.startswith("#")][0]
    assert header.split(",") == ["block", "size_marla", "asking_price_pkr",
                                 "observation_date", "source_note", "features"]
    # the format is stated, never implied
    assert "marla" in text and "PKR" in text and "YYYY-MM-DD" in text
    # CSV formula injection guard, unit-tested on the helper itself
    assert workspace.escape_cell("=1+1") == "'=1+1"
    assert workspace.escape_cell("@SUM(A1)") == "'@SUM(A1)"
    assert workspace.escape_cell("Block C") == "Block C"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_upload_validate_approve_activate_happy_path(workspace):
    created = _upload(workspace, "synthetic_inventory_a.csv")
    version_id = created["version_id"]
    validation = created["validation"]

    assert validation["rows_read"] == 28
    assert validation["accepted"] == 28
    assert validation["rejected"] == 0
    assert validation["verdict"] == "ACCEPTED"

    preview = workspace.preview(version_id)
    assert preview["version_id"] == version_id
    assert preview["columns"]["template"][0] == "block"
    assert len(preview["rows_preview"]) == 28

    manifest = workspace.approve(version_id, actor="founder")
    assert manifest["status"] == "approved"
    assert manifest["approved_by"] == "founder"
    assert manifest["approved_at"]

    pointer = workspace.activate(version_id, actor="founder")
    assert pointer["version_id"] == version_id
    assert len(pointer["sha256"]) == 64

    current = workspace.current()
    assert current["active"]["version_id"] == version_id
    assert current["stamp"]["mode"] == "version"
    assert current["stamp"]["version_id"] == version_id


def test_upload_rejects_bad_rows_but_keeps_good_ones(workspace):
    csv_bytes = (
        b"# SYNTHETIC TEST DATA - mixed validity\n"
        b"block,size_marla,asking_price_pkr,observation_date,source_note,features\n"
        b"C,5,5600000,2026-10-07,good row,corner\n"
        b"C,5,5650000,2026-10-07,good row,\n"
        b"C,5,5700000,2026-10-07,good row,\n"
        b",5,5600000,2026-10-07,missing block,\n"
        b"Z,5,5600000,2026-10-07,unknown block,\n"
        b"C,-5,5600000,2026-10-07,negative size,\n"
    )
    created = workspace.create_upload(csv_bytes, "mixed.csv", actor="tester")
    validation = created["validation"]
    assert validation["accepted"] == 3
    assert validation["rejected"] == 3
    reasons = " ".join(" ".join(item["reasons"])
                       for item in validation["errors"])
    assert "missing_field" in reasons
    assert "invalid_block" in reasons
    assert "invalid_size" in reasons
    # the rejected rows never reach the stored inventory
    assert validation["blocks"] == {"C": 3}


def test_unparsed_date_is_a_warning_not_a_rejection(workspace):
    """Unknown stays unknown: a missing date must not disqualify a row."""
    csv_bytes = (
        b"block,size_marla,asking_price_pkr,observation_date,source_note,features\n"
        b"C,5,5600000,not-a-date,undated row,\n"
        b"C,5,5650000,2026-10-07,dated row,\n"
        b"C,5,5700000,2026-10-07,dated row,\n"
    )
    created = workspace.create_upload(csv_bytes, "undated.csv")
    validation = created["validation"]
    assert validation["accepted"] == 3
    assert validation["rejected"] == 0
    warnings = " ".join(" ".join(item["warnings"])
                        for item in validation["warnings"])
    assert "observation_date_unparsed" in warnings


# ---------------------------------------------------------------------------
# A/B swap - the heart of the card
# ---------------------------------------------------------------------------


def _activate(ws, fixture_name: str, actor: str = "founder") -> str:
    created = _upload(ws, fixture_name)
    version_id = created["version_id"]
    ws.approve(version_id, actor=actor)
    ws.activate(version_id, actor=actor)
    return version_id


def test_ab_swap_answers_from_the_active_version(workspace):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    result_a = run_turn("what is the price of a 5 marla plot in block b",
                        session_id="swap-a")

    assert result_a["inventory_version"]["version_id"] == version_a
    assert result_a["inventory_version"]["mode"] == "version"
    # the A fixture's Block B band is 5,200,000 - 5,740,000
    assert "5,200,000" in result_a["reply"]
    assert "5,740,000" in result_a["reply"]

    version_b = _activate(workspace, "synthetic_inventory_b.csv")
    result_b = run_turn("what is the price of a 5 marla plot in block c",
                        session_id="swap-b")

    assert result_b["inventory_version"]["version_id"] == version_b
    # the B fixture's Block C band is 4,400,000 - 6,900,000
    assert "4,400,000" in result_b["reply"]
    assert "6,900,000" in result_b["reply"]

    # cross-check: each version's reply carries only its own band
    assert "5,740,000" not in result_b["reply"]
    assert "6,900,000" not in result_a["reply"]


def test_version_change_notice_fires_once_per_change(workspace):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    first = run_turn("5 marla in block b", session_id="notice-1")
    assert first["inventory_version"]["version_id"] == version_a
    assert "version_change" not in first

    version_b = _activate(workspace, "synthetic_inventory_b.csv")
    changed = run_turn("5 marla in block c", session_id="notice-1")
    assert "version_change" in changed
    assert changed["version_change"]["previous"]["version_id"] == version_a
    assert changed["version_change"]["current"]["version_id"] == version_b
    # the customer draft text is not altered by the notice
    assert "the active inventory changed" not in changed["reply"]

    again = run_turn("5 marla in block c", session_id="notice-1")
    assert "version_change" not in again


# ---------------------------------------------------------------------------
# Inactive invariant
# ---------------------------------------------------------------------------


def test_inactive_workspace_serves_the_configured_master(workspace):
    from market import fh_query

    assert workspace.resolve_active_source() is None
    configured = Path(fh_query.MASTER_PATH)
    assert configured.exists(), "the configured master must exist on this machine"

    rows = fh_query.load_inventory()
    assert len(rows) == len(fh_query.load_inventory(configured))

    stamp = workspace.current_stamp()
    assert stamp["mode"] == "configured"
    assert stamp["version_id"] is None
    assert stamp["fingerprint"] == _sha256(configured)
    assert stamp["rows"] == len(rows)

    result = run_turn("what is the price of a 5 marla plot in block c",
                      session_id="invariant-1")
    assert result["inventory_version"]["mode"] == "configured"
    assert result["inventory_version"]["fingerprint"] == _sha256(configured)


def test_removing_the_pointer_restores_configured_behavior(workspace):
    from market import fh_query

    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    assert workspace.current_stamp()["version_id"] == version_a

    pointer = workspace.active_pointer_path()
    pointer.unlink()

    workspace._clear_cache()
    stamp = workspace.current_stamp()
    assert stamp["mode"] == "configured"
    assert workspace.resolve_active_source() is None
    assert len(fh_query.load_inventory()) == stamp["rows"]


def test_second_upload_is_not_mistaken_for_a_duplicate(workspace):
    """Generated identities must be scoped to their source file.

    Regression: a per-row-only scheme (CSV0001...) made the second upload
    look like a duplicate of the first active version.
    """
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    assert version_a

    created = _upload(workspace, "synthetic_inventory_b.csv")
    validation = created["validation"]
    assert validation["accepted"] == 30
    assert validation["rejected"] == 0

    # the same file uploaded twice IS a duplicate, by design: every row
    # collides with the active version, so the upload is refused outright
    with pytest.raises(workspace.WorkspaceError) as excinfo:
        _upload(workspace, "synthetic_inventory_a.csv")
    assert "duplicate_of_approved_master" in str(excinfo.value)
    actions = [record["action"] for record in workspace.audit_records(20)]
    assert "upload_rejected" in actions


# ---------------------------------------------------------------------------
# Failure safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("filename", [
    "../evil.csv", "..\\evil.csv", "/etc/passwd.csv", r"C:\temp\evil.csv",
    "notes.txt", "",
])
def test_upload_refuses_unsafe_names_and_types(workspace, filename):
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_upload(b"block,size_marla\nC,5\n", filename)


def test_upload_refuses_oversized_and_binary(workspace):
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_upload(b"a" * (workspace.MAX_UPLOAD_BYTES + 1),
                                "big.csv")
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_upload(b"block,size_marla\n\x00\x01\x02", "bin.csv")


def test_upload_refuses_csv_with_no_valid_rows(workspace):
    with pytest.raises(workspace.WorkspaceError):
        workspace.create_upload(b"foo,bar\n1,2\n", "useless.csv")


def test_failed_activation_keeps_the_previous_version_serving(workspace,
                                                              monkeypatch):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    created = _upload(workspace, "synthetic_inventory_b.csv")
    workspace.approve(created["version_id"])

    real_replace = os.replace

    def _explode(src, dst):
        raise OSError("simulated interrupted activation")

    monkeypatch.setattr(os, "replace", _explode)
    with pytest.raises(OSError):
        workspace.activate(created["version_id"])
    monkeypatch.setattr(os, "replace", real_replace)

    workspace._clear_cache()
    resolved = workspace.resolve_active_source()
    assert resolved is not None
    assert resolved["version_id"] == version_a


def test_corrupt_pointer_is_loud_and_falls_back_to_configured(workspace):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    assert workspace.resolve_active_source()["version_id"] == version_a

    workspace.active_pointer_path().write_text("{not json", encoding="utf-8")
    workspace._clear_cache()

    assert workspace.resolve_active_source() is None
    assert workspace.current_stamp()["mode"] == "configured"
    actions = [record["action"] for record in workspace.audit_records(20)]
    assert "pointer_unreadable" in actions


def test_transcript_keeps_each_turns_own_stamp(workspace):
    """Older turns keep the stamp they were answered with."""
    from tests.asgi_client import call_asgi

    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    run_turn("5 marla in block b", session_id="hist-1")

    version_b = _activate(workspace, "synthetic_inventory_b.csv")
    run_turn("5 marla in block c", session_id="hist-1")

    status, raw = call_asgi(
        app, "GET", "/api/conversation/hist-1/transcript")
    assert status == 200
    turns = json.loads(raw)["turns"]
    assert len(turns) == 2
    assert turns[0]["inventory_version"]["version_id"] == version_a
    assert turns[1]["inventory_version"]["version_id"] == version_b
    assert turns[0]["inventory_version"]["rows"] == 28
    assert turns[1]["inventory_version"]["rows"] == 30


# ---------------------------------------------------------------------------
# Rollback + audit
# ---------------------------------------------------------------------------


def test_rollback_sequence_and_audit(workspace):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    version_b = _activate(workspace, "synthetic_inventory_b.csv")
    assert workspace.resolve_active_source()["version_id"] == version_b

    pointer = workspace.rollback()
    assert pointer["version_id"] == version_a

    workspace._clear_cache()
    assert workspace.resolve_active_source()["version_id"] == version_a

    actions = [record["action"] for record in workspace.audit_records(50)]
    assert actions.count("activate") >= 2
    assert "rollback" in actions
    rollback_record = [record for record in workspace.audit_records(50)
                       if record["action"] == "rollback"][-1]
    assert rollback_record["version_id"] == version_a
    assert rollback_record["detail"]["from"] == version_b


def test_versions_listing_reports_statuses(workspace):
    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    created_b = _upload(workspace, "synthetic_inventory_b.csv")

    versions = {item["version_id"]: item for item in workspace.list_versions()}
    assert versions[version_a]["status"] == "active"
    assert versions[created_b["version_id"]]["status"] == "pending_review"


# ---------------------------------------------------------------------------
# Preview escaping + API surface
# ---------------------------------------------------------------------------


def test_preview_escapes_formula_cells(workspace):
    csv_bytes = (
        "block,size_marla,asking_price_pkr,observation_date,source_note,features\n"
        "C,5,5600000,2026-10-07,=cmd|'/C calc'!A0,\n"
        "C,5,5700000,2026-10-07,+1+1,\n"
        "C,5,5800000,2026-10-07,@SUM(A1),\n"
    ).encode("utf-8")
    created = workspace.create_upload(csv_bytes, "formula.csv")
    preview = workspace.preview(created["version_id"])
    notes = [row["source_note"] for row in preview["rows_preview"]]
    assert notes[0].startswith("'=")
    assert notes[1].startswith("'+")
    assert notes[2].startswith("'@")


def test_api_endpoints_round_trip(workspace):
    status, body = call_asgi(app, "GET", "/api/inventory/current")
    assert status == 200
    current = json.loads(body)
    assert current["stamp"]["mode"] == "configured"

    data = (FIXTURES / "synthetic_inventory_a.csv").read_bytes()
    status, raw = call_asgi(
        app, "POST", "/api/inventory/upload",
        query=b"filename=synthetic_inventory_a.csv",
        body=data, content_type="application/octet-stream")
    assert status == 200, raw[:300]
    created = json.loads(raw)

    status, preview_raw = call_asgi(
        app, "GET", "/api/inventory/preview/%s" % created["version_id"])
    assert status == 200
    assert json.loads(preview_raw)["validation"]["accepted"] == 28

    status, _ = post_json(app, "/api/inventory/approve",
                          {"version_id": created["version_id"]})
    assert status == 200
    status, _ = post_json(app, "/api/inventory/activate",
                          {"version_id": created["version_id"]})
    assert status == 200

    status, body = call_asgi(app, "GET", "/api/inventory/current")
    assert status == 200
    assert json.loads(body)["stamp"]["version_id"] == created["version_id"]

    status, body = call_asgi(app, "GET", "/api/inventory/versions")
    assert status == 200
    assert json.loads(body)["versions"]


# ---------------------------------------------------------------------------
# Protected files
# ---------------------------------------------------------------------------


def test_protected_files_are_untouched_by_the_whole_cycle(workspace):
    existing = [path for path in PROTECTED_FILES if path.exists()]
    before = {str(path): _sha256(path) for path in existing}

    version_a = _activate(workspace, "synthetic_inventory_a.csv")
    run_turn("5 marla in block b", session_id="protect-1")
    _activate(workspace, "synthetic_inventory_b.csv")
    workspace.rollback(version_a)

    after = {str(path): _sha256(path) for path in existing}
    assert before == after
