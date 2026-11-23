"""M12.3 - the inventory ingest gate.

What this module is
-------------------
The controlled staging process a new professional inventory must pass
before anyone may even propose it as the approved master. A candidate
JSONL file is validated row by row against the rules the product
already enforces - required fields, a known block, a usable size, a
coherent asking-price band, a positive observation count - duplicates
are detected both inside the candidate and against the CURRENT approved
master, out-of-scope blocks are flagged as parked (exactly how the
approved master itself carries them), and everything the gate produces
lands in a staging directory of its own.

What this module is NOT
-----------------------
It is **not** a promotion path. It never writes to the approved master,
to the protected master-data folder, or to any production location: the
only outputs are a machine report, a human reject report and a cleaned
candidate copy, all inside ``data/ingest_staging/``. Promoting a
staged candidate to the approved master is a founder decision and a
manual copy, documented in the report and executed by nobody else.

The gate is deterministic, stdlib-only, and reads its scope and its
evidence threshold from ``config/policies.json`` - the same values the
serving path obeys, so the gate can never be stricter or looser than
the product.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "GATE_VERSION",
    "IngestReport",
    "run_gate",
    "staging_root",
]


GATE_VERSION = "m12.3.1"

ROOT = Path(__file__).resolve().parent.parent
POLICIES_PATH = ROOT / "config" / "policies.json"
STAGING_ROOT = ROOT / "data" / "ingest_staging"

# The identity of an approved plot: the block it sits in and the plot
# number the master already carries.
REQUIRED_FIELDS = ("block", "plot_number", "size_marla")

# The sizes the serving path currently knows how to answer for. A row
# with another size is not broken data - it is a cell the product cannot
# serve yet, so it is FLAGGED, never silently dropped.
SERVED_SIZES = (5.0, 7.0, 10.0, 14.0, 20.0, 40.0)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")

# Fields the approved master carries but the serving surfaces NEVER
# serve. A candidate may carry them; the report says so plainly.
PRIVATE_FIELDS = ("notes", "source_chats", "size_raw")

# Availability: the product may attest an asking price, never that a
# plot is available or sold. A definite claim is rejected; the word
# alone in free text the gate cannot judge is the reply guard's job.
_AVAILABILITY_CLAIM = re.compile(
    r"\b(available|sold|booked|reserved)\b", re.IGNORECASE)


def staging_root() -> Path:
    return STAGING_ROOT


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_policies() -> Dict[str, Any]:
    try:
        with POLICIES_PATH.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_block(value: Any) -> Optional[str]:
    """The block codes the product itself understands (A-E)."""
    text = str(value or "").strip().upper()
    aliases = {
        "BLOCK A": "A", "BLOCK B": "B", "BLOCK C": "C", "BLOCK D": "D",
        "BLOCK E": "E", "EXEC": "E", "EXECUTIVE": "E",
        "EXECUTIVE BLOCK": "E",
    }
    if text in aliases:
        return aliases[text]
    match = re.fullmatch(r"F?H?([A-E])", text)
    if match:
        return match.group(1)
    if text in {"A", "B", "C", "D", "E"}:
        return text
    return None


def _row_identity(row: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    block = _normalize_block(row.get("block"))
    plot = str(row.get("plot_number") or "").strip()
    if not block or not plot:
        return None
    return (block, plot.upper())


class IngestReport:
    """The result of one gate run."""

    def __init__(self) -> None:
        self.candidate_path: str = ""
        self.candidate_sha256: str = ""
        self.approved_sha256: str = ""
        self.approved_records: int = 0
        self.lines: int = 0
        self.rows: int = 0
        self.accepted: int = 0
        self.flagged: int = 0
        self.rejected: int = 0
        self.rejects: List[Dict[str, Any]] = []
        self.flags: List[Dict[str, Any]] = []
        self.coverage: List[Dict[str, Any]] = []
        self.thin_cells: List[Dict[str, Any]] = []
        self.out_dir: str = ""

    @property
    def verdict(self) -> str:
        return "ACCEPTED" if self.rejected == 0 and self.rows > 0 else "REJECTED"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_version": GATE_VERSION,
            "verdict": self.verdict,
            "candidate_path": self.candidate_path,
            "candidate_sha256": self.candidate_sha256,
            "approved_master_sha256": self.approved_sha256,
            "approved_master_records": self.approved_records,
            "lines": self.lines,
            "rows": self.rows,
            "accepted": self.accepted,
            "flagged": self.flagged,
            "rejected": self.rejected,
            "rejects": self.rejects,
            "flags": self.flags,
            "coverage": self.coverage,
            "thin_cells": self.thin_cells,
            "out_dir": self.out_dir,
        }


def _check_row(row: Dict[str, Any], line: int,
               seen_in_candidate: Dict[Tuple[str, str], int],
               approved_ids: set) -> Tuple[List[str], List[str], List[str]]:
    """One row -> (rejects, flags, notes). Rejects are fatal for the row;
    flags keep the row but record what the founder must know."""
    rejects: List[str] = []
    flags: List[str] = []
    notes: List[str] = []

    for field in REQUIRED_FIELDS:
        value = row.get(field)
        if value is None or str(value).strip() == "":
            rejects.append("missing_field:%s" % field)

    block = _normalize_block(row.get("block"))
    if block is None and not rejects:
        rejects.append("invalid_block")

    size = _number(row.get("size_marla"))
    if size is not None and size <= 0:
        rejects.append("invalid_size:not_positive")
    elif size is not None and size not in SERVED_SIZES:
        flags.append("unserved_size:%g" % size)

    # the asking-price band: min <= median <= max, all positive when present
    p_min = _number(row.get("price_min_pkr"))
    p_med = _number(row.get("price_median_pkr"))
    p_max = _number(row.get("price_max_pkr"))
    prices = {"price_min_pkr": p_min, "price_median_pkr": p_med,
              "price_max_pkr": p_max}
    for name, value in prices.items():
        if value is not None and value <= 0:
            rejects.append("bad_price:%s_not_positive" % name)
    present = [v for v in (p_min, p_med, p_max) if v is not None]
    if len(present) == 3 and p_min > p_max:
        rejects.append("bad_price:min_above_max")
    if len(present) == 3 and not (p_min <= p_med <= p_max):
        rejects.append("bad_price:median_outside_band")

    observations = row.get("observation_count")
    obs = _number(observations)
    if obs is not None and (obs < 0 or int(obs) != obs):
        rejects.append("bad_observation_count")
    if obs is not None and int(obs) == 0 and p_med is not None:
        flags.append("priced_but_zero_observations")

    latest = row.get("latest_date")
    if latest is not None and not _DATE_RE.match(str(latest).strip()):
        rejects.append("bad_latest_date")

    # availability: the product never attests it
    for field in ("status", "availability", "available"):
        value = row.get(field)
        if value is not None and _AVAILABILITY_CLAIM.search(str(value)):
            rejects.append("availability_claim_unsupported:%s" % field)

    # privacy: the private fields may be present, but are called out
    for field in PRIVATE_FIELDS:
        if row.get(field) not in (None, "", []):
            notes.append("private_field_present:%s" % field)

    # scope: the active blocks come from the policies the product reads
    policies = _load_policies()
    active = set(policies.get("active_blocks") or ["A", "B", "C"])
    if block is not None and block not in active:
        flags.append("out_of_scope_block:%s" % block)

    # duplicates
    identity = _row_identity(row)
    if identity is not None:
        if identity in approved_ids:
            rejects.append("duplicate_of_approved_master")
        elif identity in seen_in_candidate:
            rejects.append(
                "duplicate_in_candidate:line_%d" % seen_in_candidate[identity])
        else:
            seen_in_candidate[identity] = line

    return rejects, flags, notes


def _coverage_table(rows: List[Dict[str, Any]],
                    min_listings: int) -> Tuple[List[Dict[str, Any]],
                                                List[Dict[str, Any]]]:
    """Cells (block, size) the candidate would add, and the ones still
    below the evidence threshold - the same threshold the serving path
    enforces, read from the same policies file."""
    cells: Dict[Tuple[str, float], int] = {}
    for row in rows:
        block = _normalize_block(row.get("block"))
        size = _number(row.get("size_marla"))
        if block is None or size is None:
            continue
        cells[(block, size)] = cells.get((block, size), 0) + 1

    table = []
    thin = []
    for (block, size), count in sorted(cells.items()):
        entry = {"block": block, "size_marla": size, "rows": count}
        table.append(entry)
        if count < min_listings:
            entry["below_threshold"] = True
            thin.append(entry)
    return table, thin


def _markdown_report(report: IngestReport, clean_rows: int) -> str:
    lines = [
        "# Inventory ingest gate - reject report",
        "",
        "* gate version: %s" % GATE_VERSION,
        "* candidate: `%s` (sha256 %s)" % (report.candidate_path,
                                           report.candidate_sha256[:12]),
        "* current approved master: sha256 %s, %d records (unchanged)"
        % (report.approved_sha256[:12], report.approved_records),
        "* verdict: **%s** - %d rows read, %d accepted, %d flagged, "
        "%d rejected" % (report.verdict, report.rows, report.accepted,
                         report.flagged, report.rejected),
        "",
    ]
    if report.rejects:
        lines.append("## Rejected rows")
        lines.append("")
        lines.append("| line | identity | reasons |")
        lines.append("|---|---|---|")
        for item in report.rejects:
            lines.append("| %d | %s | %s |" % (
                item["line"], item["identity"], "; ".join(item["reasons"])))
        lines.append("")
    if report.flags:
        lines.append("## Flagged rows (kept, but the founder must know)")
        lines.append("")
        for item in report.flags:
            lines.append("* line %d (%s): %s" % (
                item["line"], item["identity"], "; ".join(item["flags"])))
        lines.append("")
    if report.coverage:
        lines.append("## Coverage the candidate would add")
        lines.append("")
        lines.append("| block | size (marla) | rows | below threshold |")
        lines.append("|---|---|---|---|")
        for cell in report.coverage:
            lines.append("| %s | %g | %d | %s |" % (
                cell["block"], cell["size_marla"], cell["rows"],
                "YES" if cell.get("below_threshold") else ""))
        lines.append("")
    if report.thin_cells:
        lines.append(
            "Cells below the %d-listing evidence threshold would answer "
            "`not enough data` exactly as the product does today."
            % len(report.thin_cells))
        lines.append("")

    lines += [
        "## Promotion (FOUNDER-ONLY, manual)",
        "",
        "The gate has staged %d clean rows in this folder. NOTHING has" % clean_rows,
        "been copied to the approved master. To promote after review, the",
        "founder manually copies `candidate_clean.jsonl` onto the approved",
        "master path recorded above (both master copies must stay",
        "identical), then re-runs the verification gates.",
        "",
        "## Rollback",
        "",
        "The approved master's sha256 before this run is recorded above.",
        "Rollback = restore the previous master file from the founder's",
        "own backup and re-verify the hash. The staging folder can be",
        "deleted at any time; it feeds nothing.",
        "",
    ]
    return "\n".join(lines)


def run_gate(candidate: Any, approved_path: Optional[Any] = None,
             out_dir: Optional[Any] = None) -> IngestReport:
    """Run the gate over a candidate inventory file.

    Args:
        candidate: path to the candidate JSONL file.
        approved_path: the approved master to compare against. Defaults
            to the master the product itself reads. Never written.
        out_dir: where the staging outputs go. Defaults to a new
            timestamped folder under ``data/ingest_staging``. Must stay
            inside the staging root.

    Returns:
        The :class:`IngestReport`. The verdict is ACCEPTED only when at
        least one row was read and no row was rejected.
    """
    from market.fh_query import MASTER_PATH, load_inventory

    candidate = Path(candidate)
    approved = Path(approved_path) if approved_path else MASTER_PATH

    # hard boundary: the approved master is never a candidate. A control
    # run goes over a COPY in a scratch directory. The gate only READS
    # the candidate; every write goes to the staging root, guarded below.
    if candidate.resolve() == approved.resolve():
        raise ValueError(
            "the gate does not run over the approved master itself; "
            "run it over a copy if you need a control")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(out_dir) if out_dir else STAGING_ROOT / timestamp
    out = out.resolve()
    if STAGING_ROOT.resolve() not in out.parents:
        raise ValueError(
            "staging output must live under %s" % STAGING_ROOT)
    out.mkdir(parents=True, exist_ok=True)

    policies = _load_policies()
    min_listings = int(policies.get("min_listings_for_answer") or 3)

    approved_rows = load_inventory(Path(approved))
    approved_ids = set()
    for row in approved_rows:
        identity = _row_identity(row)
        if identity:
            approved_ids.add(identity)

    report = IngestReport()
    report.candidate_path = str(candidate)
    report.candidate_sha256 = _sha256(candidate)
    report.approved_sha256 = _sha256(Path(approved))
    report.approved_records = len(approved_rows)
    report.out_dir = str(out)

    accepted_rows: List[Dict[str, Any]] = []
    seen_in_candidate: Dict[Tuple[str, str], int] = {}

    with candidate.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            report.lines = line_number
            text = line.strip()
            if not text:
                continue
            report.rows += 1
            try:
                row = json.loads(text)
            except json.JSONDecodeError as exc:
                report.rejected += 1
                report.rejects.append({
                    "line": line_number, "identity": "-",
                    "reasons": ["bad_json:%s" % exc.msg],
                })
                continue
            if not isinstance(row, dict):
                report.rejected += 1
                report.rejects.append({
                    "line": line_number, "identity": "-",
                    "reasons": ["not_a_json_object"],
                })
                continue

            rejects, flags, notes = _check_row(
                row, line_number, seen_in_candidate, approved_ids)
            identity = _row_identity(row)
            label = "%s/%s" % identity if identity else "-"

            if rejects:
                report.rejected += 1
                report.rejects.append({
                    "line": line_number, "identity": label,
                    "reasons": rejects,
                })
                continue

            accepted_rows.append(row)
            if flags or notes:
                report.flagged += 1
                report.flags.append({
                    "line": line_number, "identity": label,
                    "flags": flags + notes,
                })
            else:
                report.accepted += 1

    # the clean candidate: only rows that passed, in file order
    clean_path = out / "candidate_clean.jsonl"
    with clean_path.open("w", encoding="utf-8") as handle:
        for row in accepted_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    report.coverage, report.thin_cells = _coverage_table(
        accepted_rows, min_listings)

    with (out / "report.json").open("w", encoding="utf-8") as handle:
        json.dump(report.to_dict(), handle, ensure_ascii=False, indent=2)
    (out / "report.md").write_text(
        _markdown_report(report, len(accepted_rows)), encoding="utf-8")

    return report
