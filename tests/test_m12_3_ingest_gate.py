"""M12.3 - the inventory ingest gate.

The gate is the controlled staging process a new professional inventory
must pass: required fields, duplicate detection (inside the candidate
and against the approved master), block / size / price / availability
checks, a clear reject report, a founder-only promotion step and a
rollback plan - and it never writes to the approved master or the
protected master-data folder.

All candidate rows in these tests are FABRICATED (RULES_SHORT: tests
use fabricated lines only). The one real value read from the approved
master is a single (block, plot_number) identity for the
duplicate-against-master check, and it is never printed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market.fh_query import MASTER_PATH, load_inventory  # noqa: E402
from market.ingest_gate import run_gate, staging_root  # noqa: E402


def _row(**overrides):
    """One fabricated, fully valid candidate row."""
    row = {
        "block": "C",
        "plot_number": "T-0001",
        "size_marla": 5.0,
        "price_min_pkr": 3_000_000,
        "price_median_pkr": 3_500_000,
        "price_max_pkr": 4_000_000,
        "observation_count": 3,
        "latest_date": "2026-09-30",
    }
    row.update(overrides)
    return row


def _write(path: Path, rows):
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return path


@pytest.fixture()
def mini_master(tmp_path):
    """A fabricated approved master of three plots the gate compares
    against, so the duplicate checks are hermetic."""
    return _write(tmp_path / "approved.jsonl", [
        _row(plot_number="M-0001"),
        _row(plot_number="M-0002", block="A", size_marla=7.0),
        _row(plot_number="M-0003", block="B", size_marla=10.0),
    ])


def _run(tmp_path, rows, approved, name="candidate.jsonl"):
    candidate = _write(tmp_path / name, rows)
    out = staging_root() / ("test_%s" % name.replace(".jsonl", ""))
    return run_gate(candidate, approved_path=approved, out_dir=out), out


def test_a_clean_candidate_is_accepted(tmp_path, mini_master):
    report, out = _run(tmp_path, [
        _row(plot_number="N-0001"),
        _row(plot_number="N-0002", size_marla=7.0),
        _row(plot_number="N-0003", block="A"),
    ], mini_master)
    assert report.verdict == "ACCEPTED"
    assert report.rows == 3 and report.rejected == 0
    assert report.accepted + report.flagged == 3
    assert (out / "report.md").exists()
    assert (out / "report.json").exists()
    clean = [json.loads(line) for line in
             (out / "candidate_clean.jsonl").read_text(encoding="utf-8")
             .splitlines() if line.strip()]
    assert len(clean) == 3


def test_missing_required_fields_are_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number=None),          # missing plot_number
        _row(size_marla=None),           # missing size
        _row(block=None),                # missing block
    ], mini_master)
    assert report.verdict == "REJECTED" and report.rejected == 3
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert any(r.startswith("missing_field:plot_number") for r in reasons)
    assert any(r.startswith("missing_field:size_marla") for r in reasons)
    assert any(r.startswith("missing_field:block") for r in reasons)


def test_invalid_block_and_size_are_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0010", block="Zed"),     # unknown block
        _row(plot_number="N-0011", size_marla=-5),   # negative size
    ], mini_master)
    assert report.rejected == 2
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert "invalid_block" in reasons
    assert "invalid_size:not_positive" in reasons


def test_price_band_checks(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0020", price_min_pkr=5_000_000,
             price_max_pkr=4_000_000),                       # min > max
        _row(plot_number="N-0021", price_median_pkr=9_000_000),  # outside band
        _row(plot_number="N-0022", price_min_pkr=-1),        # negative price
    ], mini_master)
    assert report.rejected == 3
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert "bad_price:min_above_max" in reasons
    assert "bad_price:median_outside_band" in reasons
    assert "bad_price:price_min_pkr_not_positive" in reasons


def test_bad_observation_count_and_date(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0030", observation_count=0.5),
        _row(plot_number="N-0031", latest_date="31/09/2026"),
    ], mini_master)
    assert report.rejected == 2
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert "bad_observation_count" in reasons
    assert "bad_latest_date" in reasons


def test_availability_claims_are_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0040", status="available"),
        _row(plot_number="N-0041", availability="sold"),
    ], mini_master)
    assert report.rejected == 2
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert any(r.startswith("availability_claim_unsupported")
               for r in reasons)


def test_duplicates_inside_the_candidate_are_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0050"),
        _row(plot_number="N-0050"),      # same block + plot
        _row(plot_number="n-0050"),      # identity is case-insensitive
    ], mini_master)
    assert report.rejected == 2
    assert report.accepted + report.flagged == 1
    reasons = [r for item in report.rejects for r in item["reasons"]]
    assert all(r.startswith("duplicate_in_candidate") for r in reasons)


def test_duplicates_of_the_approved_master_are_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="M-0002", block="A", size_marla=7.0),
        _row(plot_number="N-0060"),
    ], mini_master)
    assert report.rejected == 1
    assert "duplicate_of_approved_master" in report.rejects[0]["reasons"]


def test_out_of_scope_blocks_are_flagged_not_rejected(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0070", block="D"),
        _row(plot_number="N-0071", block="Executive"),
        _row(plot_number="N-0072", block="A"),
    ], mini_master)
    assert report.verdict == "ACCEPTED" and report.rejected == 0
    assert report.flagged == 2
    flags = [f for item in report.flags for f in item["flags"]]
    assert sum(1 for f in flags if f.startswith("out_of_scope_block")) == 2


def test_unserved_sizes_and_private_fields_are_flagged(tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0080", size_marla=4.0),
        _row(plot_number="N-0081", notes="dealer words", source_chats=["x"]),
    ], mini_master)
    assert report.rejected == 0 and report.flagged == 2
    flags = [f for item in report.flags for f in item["flags"]]
    assert any(f.startswith("unserved_size") for f in flags)
    assert any(f.startswith("private_field_present:notes") for f in flags)


def test_malformed_lines_are_rejected_with_the_line_number(
        tmp_path, mini_master):
    candidate = tmp_path / "broken.jsonl"
    candidate.write_text(
        json.dumps(_row(plot_number="N-0090")) + "\n"
        "{not json}\n"
        "[1, 2, 3]\n", encoding="utf-8")
    out = staging_root() / "test_broken"
    report = run_gate(candidate, approved_path=mini_master, out_dir=out)
    assert report.rows == 3 and report.rejected == 2
    assert report.rejects[0]["line"] == 2
    assert report.rejects[0]["reasons"][0].startswith("bad_json")
    assert "not_a_json_object" in report.rejects[1]["reasons"]


def test_the_coverage_table_and_the_thin_cell_warning(
        tmp_path, mini_master):
    report, _ = _run(tmp_path, [
        _row(plot_number="N-0100"),
        _row(plot_number="N-0101", size_marla=7.0),  # a 1-row cell: thin
    ], mini_master)
    cells = {(c["block"], c["size_marla"]): c for c in report.coverage}
    assert cells[("C", 5.0)]["rows"] == 1
    thin = {(c["block"], c["size_marla"]) for c in report.thin_cells}
    # the threshold is 3 listings: both fabricated cells are thin here
    assert ("C", 5.0) in thin and ("C", 7.0) in thin


def test_the_gate_refuses_to_run_over_the_approved_master(
        tmp_path, mini_master):
    with pytest.raises(ValueError):
        run_gate(mini_master, approved_path=mini_master,
                 out_dir=staging_root() / "test_refuse")


def test_staging_output_must_stay_under_the_staging_root(
        tmp_path, mini_master):
    candidate = _write(tmp_path / "c.jsonl", [_row()])
    with pytest.raises(ValueError):
        run_gate(candidate, approved_path=mini_master,
                 out_dir=tmp_path / "elsewhere")


def test_the_gate_never_writes_the_approved_master(tmp_path, mini_master):
    before = mini_master.read_bytes()
    sibling = mini_master.with_name("approved.jsonl")
    _run(tmp_path, [_row(plot_number="N-0110")], mini_master,
         name="c2.jsonl")
    assert mini_master.read_bytes() == before
    # nothing appeared next to the approved file except the candidate
    assert sibling.read_bytes() == before


def test_the_real_master_copy_is_untouched_by_a_gate_run(tmp_path):
    """One read-only pass against the REAL approved master: the gate
    reads it, compares against it, and leaves it byte-identical."""
    before = MASTER_PATH.read_bytes()
    rows = load_inventory(MASTER_PATH)
    # the candidate reuses one REAL identity - the duplicate check must
    # fire against the real master without printing anything private
    real = rows[0]
    candidate = _write(tmp_path / "dup.jsonl", [
        _row(block=real.get("block"), plot_number=real.get("plot_number")),
        _row(plot_number="N-0200"),
    ])
    report = run_gate(candidate, out_dir=staging_root() / "test_real_master")
    assert MASTER_PATH.read_bytes() == before
    assert report.rejected == 1
    assert "duplicate_of_approved_master" in report.rejects[0]["reasons"]
    assert report.approved_records == len(rows)


def test_the_report_documents_promotion_and_rollback(
        tmp_path, mini_master):
    report, out = _run(tmp_path, [_row(plot_number="N-0300")], mini_master)
    text = (out / "report.md").read_text(encoding="utf-8")
    assert "FOUNDER-ONLY" in text
    assert "Rollback" in text
    assert report.approved_sha256 in text or \
        report.approved_sha256[:12] in text
