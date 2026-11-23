"""Stage 1 - the versioned inventory workspace.

What this module is
-------------------
The founder-controlled inventory cycle the pilot was missing:

    upload -> preview/column-map -> validate -> review -> approve
           -> activate -> rollback -> audit

A version lives in its own folder (``versions/<version_id>/``) with the
normalised ``inventory.jsonl`` and a ``manifest.json`` that records what
was uploaded, what was produced and who approved/activated it. The
**active** version is named by a single pointer file
(``active_version.json``) that is replaced atomically - so an
interrupted activation leaves the previous version serving.

What this module is NOT
-----------------------
It is **not** a promotion path to the approved master. The protected
master files are never written, and the workspace is purely additive:
with no valid pointer present, the serving path keeps using exactly the
configured master (``FH_MASTER_PATH`` / the module default), byte for
byte as before.

The validation core is the existing ingest gate
(:mod:`market.ingest_gate`); this module only adds the CSV/JSONL parser,
the column mapping, the version store and the audit trail on top of it.
Stdlib only - no new dependency, no XLSX.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "WORKSPACE_DIR",
    "WorkspaceError",
    "activate",
    "active_inventory_path",
    "approve",
    "audit_records",
    "configured_stamp",
    "create_upload",
    "current",
    "current_stamp",
    "list_versions",
    "preview",
    "resolve_active_source",
    "rollback",
    "session_note_version",
    "template_csv",
]

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

_DEFAULT_DIR = r"D:\FaisalHillsAILeadDesk\agency_workspace"


def workspace_dir() -> Path:
    """The workspace root; relocatable through FH_INVENTORY_WORKSPACE_DIR."""
    raw = (os.environ.get("FH_INVENTORY_WORKSPACE_DIR") or "").strip()
    return Path(raw) if raw else Path(_DEFAULT_DIR)


def versions_dir() -> Path:
    return workspace_dir() / "versions"


def active_pointer_path() -> Path:
    return workspace_dir() / "active_version.json"


def audit_log_path() -> Path:
    return workspace_dir() / "audit_log.jsonl"


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = (".csv", ".jsonl")

# Template columns carry EXPLICIT units. Optional extras the parser
# understands are listed separately so the template stays minimal.
TEMPLATE_COLUMNS = (
    "block",
    "size_marla",
    "asking_price_pkr",
    "observation_date",
    "source_note",
    "features",
)
OPTIONAL_COLUMNS = (
    "plot_number",
    "corner",
    "sun_facing",
    "park_facing",
    "ndc_open",
    "main_boulevard",
    "observation_count",
    "price_min_pkr",
    "price_median_pkr",
    "price_max_pkr",
)
FEATURE_FIELDS = ("corner", "sun_facing", "park_facing", "ndc_open",
                  "main_boulevard")

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_FORMULA_PREFIX = ("=", "+", "-", "@")


class WorkspaceError(ValueError):
    """A refusal from the workspace. The message is safe to show."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` atomically (same directory, os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                    dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _audit(action: str, version_id: Optional[str], actor: str,
           detail: Optional[Dict[str, Any]] = None) -> None:
    """Append one audit record. Best effort: never fails a request."""
    record = {
        "ts": _now(),
        "action": action,
        "version_id": version_id,
        "actor": actor or "operator",
        "detail": detail or {},
    }
    try:
        audit_log_path().parent.mkdir(parents=True, exist_ok=True)
        with audit_log_path().open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def audit_records(limit: int = 50) -> List[Dict[str, Any]]:
    path = audit_log_path()
    if not path.exists():
        return []
    records: List[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    records.append(json.loads(text))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return records[-limit:]


def sanitize_filename(name: str) -> str:
    """Reduce an uploaded name to a safe basename, or refuse it.

    Traversal (``..``), absolute paths, drive letters and separators are
    refused outright rather than silently repaired.
    """
    raw = str(name or "")
    if not raw.strip():
        raise WorkspaceError("a file name is required")
    if "\x00" in raw:
        raise WorkspaceError("the file name contains a NUL byte")
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise WorkspaceError("absolute paths are not accepted")
    if raw != os.path.basename(raw) or ".." in raw or "/" in raw or "\\" in raw:
        raise WorkspaceError("path traversal is not accepted")
    cleaned = _CONTROL_RE.sub("", raw).strip()
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "_", cleaned)
    if not cleaned or cleaned in (".", ".."):
        raise WorkspaceError("the file name is not usable")
    return cleaned[:120]


def _file_tag(data: bytes) -> str:
    """A short, deterministic tag scoping generated plot numbers to one file."""
    return "U" + _sha256_bytes(data)[:5].upper()


def _validate_upload(data: bytes, filename: str) -> str:
    """Check size, type and content; return the sanitized filename."""
    safe = sanitize_filename(filename)
    suffix = Path(safe).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise WorkspaceError("only .csv and .jsonl uploads are accepted")
    if not data:
        raise WorkspaceError("the uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise WorkspaceError(
            "the upload is larger than the 5 MB limit")
    if b"\x00" in data[:65536] or b"\x00" in data[-65536:]:
        raise WorkspaceError("binary content is not accepted")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise WorkspaceError("the upload is not valid UTF-8 text")
    printable = sum(1 for ch in text[:5000]
                    if ch.isprintable() or ch in "\r\n\t")
    if printable < len(text[:5000]) * 0.85:
        raise WorkspaceError("binary content is not accepted")
    return safe


def _strip_control(value: Any) -> str:
    return _CONTROL_RE.sub("", str(value if value is not None else ""))


def escape_cell(value: Any) -> str:
    """Escape one cell for CSV/preview: CSV formula injection guard."""
    text = _strip_control(value)
    if text.startswith(_FORMULA_PREFIX):
        return "'" + text
    return text


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


def _truthy(value: Any) -> Optional[bool]:
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "y", "open"}:
        return True
    if text in {"false", "0", "no", "n", "close", "closed"}:
        return False
    return None


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d")


def _normalize_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Parsing + column mapping
# ---------------------------------------------------------------------------


def _read_records(data: bytes, suffix: str) -> Tuple[List[Dict[str, Any]],
                                                    List[str]]:
    """Parse the upload into raw string rows + the columns seen."""
    text = data.decode("utf-8")
    records: List[Dict[str, Any]] = []
    columns: List[str] = []

    if suffix == ".jsonl":
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise WorkspaceError("invalid JSONL: %s" % exc.msg)
            if not isinstance(obj, dict):
                raise WorkspaceError("each JSONL line must be an object")
            records.append(obj)
            for key in obj:
                if key not in columns:
                    columns.append(str(key))
        return records, columns

    # CSV: '#' comment lines are skipped before the header.
    lines = [line for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(io.StringIO("\n".join(lines)))
    if not reader.fieldnames:
        raise WorkspaceError("the CSV has no header row")
    columns = [(_strip_control(name) or "").strip().lower()
               for name in reader.fieldnames]
    for raw_row in reader:
        row: Dict[str, Any] = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            row[(_strip_control(key) or "").strip().lower()] = value
        records.append(row)
    return records, columns


def _features_of(row: Dict[str, Any]) -> Tuple[Dict[str, bool], List[str]]:
    """Map the optional feature columns and the ``features`` list."""
    values: Dict[str, bool] = {}
    warnings: List[str] = []
    for field in FEATURE_FIELDS:
        parsed = _truthy(row.get(field))
        if parsed is not None:
            values[field] = parsed
    raw = _strip_control(row.get("features") or "")
    for token in re.split(r"[;|,]", raw):
        name = token.strip().lower().replace(" ", "_").replace("-", "_")
        if not name:
            continue
        if name not in FEATURE_FIELDS:
            warnings.append("unknown_feature:%s" % name)
            continue
        values[name] = True
    return values, warnings


def _normalize_row(row: Dict[str, Any], index: int, tag: str = "UPL") -> Tuple[Dict[str, Any], List[str]]:
    """One raw upload row -> the master row shape + mapping warnings.

    ``tag`` scopes a GENERATED plot number to its source file, so two
    different uploads can never collide on a synthetic identity (a
    per-row-only scheme made every second upload look like a duplicate
    of the first one).
    """
    from market.ingest_gate import _normalize_block

    warnings: List[str] = []
    block = _normalize_block(row.get("block"))
    size = _number(row.get("size_marla"))

    plot = _strip_control(row.get("plot_number") or "").strip()
    if not plot:
        plot = "%s%04d" % (tag, index)
        warnings.append("plot_number_generated")

    latest = _normalize_date(row.get("observation_date")
                             or row.get("latest_date"))
    if row.get("observation_date") and not latest:
        warnings.append("observation_date_unparsed")

    asking = _number(row.get("asking_price_pkr") or row.get("price_pkr"))
    p_min = _number(row.get("price_min_pkr"))
    p_med = _number(row.get("price_median_pkr"))
    p_max = _number(row.get("price_max_pkr"))
    if asking is not None:
        p_min = asking if p_min is None else p_min
        p_med = asking if p_med is None else p_med
        p_max = asking if p_max is None else p_max
    elif p_min is None and p_med is None and p_max is None:
        warnings.append("no_price_provided")

    observations = _number(row.get("observation_count"))
    if observations is None:
        observations = 1
        warnings.append("observation_count_defaulted")

    features, feature_warnings = _features_of(row)
    warnings.extend(feature_warnings)

    built: Dict[str, Any] = {
        "block": block if block is not None else _strip_control(row.get("block")),
        "plot_number": plot,
        "size_marla": size if size is not None else _strip_control(row.get("size_marla")),
        "price_min_pkr": p_min,
        "price_median_pkr": p_med,
        "price_max_pkr": p_max,
        "price_type": "ASKING",
        "latest_date": latest,
        "observation_count": observations,
        "category": _strip_control(row.get("category") or "RESIDENTIAL"),
        "source_note": _strip_control(row.get("source_note") or "")[:300],
        "inventory_origin": "workspace-upload",
    }
    for field in FEATURE_FIELDS:
        built[field] = features.get(field)
    return built, warnings


# ---------------------------------------------------------------------------
# Validation (reuses the ingest gate)
# ---------------------------------------------------------------------------


def validate_records(records: List[Dict[str, Any]],
                     approved_path: Optional[Path] = None,
                     tag: str = "UPL"
                     ) -> Dict[str, Any]:
    """Validate upload rows with the existing ingest-gate rules.

    Returns the report shape the API and the UI both use: row-level
    errors (line + reason), duplicates, price/scope/missing warnings,
    plus the block/size histogram and the observation date range.
    """
    from market import fh_query
    from market import ingest_gate

    approved = approved_path
    if approved is None:
        resolved = resolve_active_source()
        approved = Path(resolved["path"]) if resolved else Path(fh_query.MASTER_PATH)

    approved_ids = set()
    try:
        if Path(approved).exists():
            for row in fh_query.load_inventory(Path(approved)):
                identity = ingest_gate._row_identity(row)
                if identity:
                    approved_ids.add(identity)
    except Exception:
        approved_ids = set()

    accepted: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, str], int] = {}
    blocks: Dict[str, int] = {}
    sizes: Dict[str, int] = {}

    for index, record in enumerate(records, start=1):
        row, map_warnings = _normalize_row(record, index, tag)
        rejects, flags, notes = ingest_gate._check_row(
            row, index, seen, approved_ids)
        identity = ingest_gate._row_identity(row)
        label = "%s/%s" % identity if identity else "-"

        if rejects:
            errors.append({"row": index, "identity": label,
                           "reasons": rejects})
            continue

        accepted.append(row)
        row_warnings = list(map_warnings) + list(flags) + [
            note for note in notes if not note.startswith("private_field_present")]
        if row_warnings:
            warnings.append({"row": index, "identity": label,
                             "warnings": row_warnings})
        block = str(row.get("block") or "")
        blocks[block] = blocks.get(block, 0) + 1
        size = _number(row.get("size_marla"))
        if size is not None:
            key = ("%g" % size)
            sizes[key] = sizes.get(key, 0) + 1

    dates = sorted(str(row.get("latest_date")) for row in accepted
                   if row.get("latest_date"))
    policies = {}
    try:
        with (Path(__file__).resolve().parent.parent / "config"
              / "policies.json").open("r", encoding="utf-8") as handle:
            policies = json.load(handle)
    except Exception:
        policies = {}
    threshold = int(policies.get("min_listings_for_answer") or 3)

    cells: Dict[Tuple[str, float], int] = {}
    for row in accepted:
        block = str(row.get("block") or "")
        size = _number(row.get("size_marla"))
        if size is None:
            continue
        cells[(block, size)] = cells.get((block, size), 0) + 1
    thin = [{"block": block, "size_marla": size, "rows": count,
             "below_threshold": True}
            for (block, size), count in sorted(cells.items())
            if count < threshold]

    return {
        "rows_read": len(records),
        "accepted": len(accepted),
        "rejected": len(errors),
        "flagged": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "blocks": blocks,
        "sizes": sizes,
        "matrix_rows": len(accepted),
        "observation_range": {
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
        },
        "thin_cells": thin,
        "min_listings_for_answer": threshold,
        "verdict": "ACCEPTED" if accepted and not errors else (
            "PARTIAL" if accepted else "REJECTED"),
    }


# ---------------------------------------------------------------------------
# Version store
# ---------------------------------------------------------------------------


def _version_dir(version_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]", "", str(version_id))
    if not safe or safe != str(version_id):
        raise WorkspaceError("invalid version id")
    return versions_dir() / safe


def _manifest_path(version_id: str) -> Path:
    return _version_dir(version_id) / "manifest.json"


def _load_manifest(version_id: str) -> Dict[str, Any]:
    path = _manifest_path(version_id)
    if not path.exists():
        raise WorkspaceError("unknown inventory version")
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _save_manifest(manifest: Dict[str, Any]) -> None:
    path = _manifest_path(manifest["version_id"])
    _atomic_write(path, json.dumps(manifest, ensure_ascii=False,
                                   indent=2).encode("utf-8"))


def create_upload(data: bytes, filename: str, actor: str = "operator",
                  source_note: str = "") -> Dict[str, Any]:
    """Validate an upload and store it as a pending version."""
    safe_name = _validate_upload(data, filename)
    suffix = Path(safe_name).suffix.lower()
    records, columns = _read_records(data, suffix)
    if not records:
        raise WorkspaceError("the upload has no data rows")

    report = validate_records(records, tag=_file_tag(data))
    if not report["accepted"]:
        _audit("upload_rejected", None, actor,
               {"filename": safe_name, "errors": len(report["errors"])})
        raise WorkspaceError(
            "no row passed validation: %s"
            % (report["errors"][0]["reasons"][0] if report["errors"] else "empty"))

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    version_id = "v%s_%s" % (stamp, _sha256_bytes(data)[:6])
    target = _version_dir(version_id)
    if target.exists():
        raise WorkspaceError("a version with this id already exists")
    target.mkdir(parents=True, exist_ok=False)

    accepted_rows: List[Dict[str, Any]] = []
    rejected_rows = {item["row"] for item in report["errors"]}
    for index, record in enumerate(records, start=1):
        if index in rejected_rows:
            continue
        row, _warnings = _normalize_row(record, index, _file_tag(data))
        accepted_rows.append(row)

    payload = "".join(json.dumps(row, ensure_ascii=False) + "\n"
                      for row in accepted_rows)
    inventory_path = target / "inventory.jsonl"
    _atomic_write(inventory_path, payload.encode("utf-8"))
    _atomic_write(target / ("upload" + suffix), data)

    manifest = {
        "version_id": version_id,
        "created_at": _now(),
        "status": "pending_review",
        "source_filename": safe_name,
        "source_sha256": _sha256_bytes(data),
        "source_bytes": len(data),
        "source_note": _strip_control(source_note)[:300],
        "inventory_sha256": _sha256_path(inventory_path),
        "rows": len(accepted_rows),
        "rows_read": report["rows_read"],
        "validation": report,
        "columns": columns,
        "blocks": report["blocks"],
        "sizes": report["sizes"],
        "observation_range": report["observation_range"],
        "approved_by": None,
        "approved_at": None,
        "activated_at": None,
        "label": "AGENCY-UPLOAD",
    }
    _save_manifest(manifest)
    _audit("upload", version_id, actor,
           {"filename": safe_name, "rows": len(accepted_rows),
            "rejected": report["rejected"]})
    return {"version_id": version_id, "manifest": manifest,
            "validation": report}


def preview(version_id: str, limit: int = 50) -> Dict[str, Any]:
    """The preview + validation report for one version."""
    manifest = _load_manifest(version_id)
    path = _version_dir(version_id) / "inventory.jsonl"
    rows: List[Dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                if len(rows) >= limit:
                    break
                rows.append(json.loads(text))
    preview_rows = [
        {key: escape_cell(value) if isinstance(value, str) else value
         for key, value in row.items()}
        for row in rows
    ]
    return {
        "version_id": version_id,
        "manifest": manifest,
        "columns": {
            "template": list(TEMPLATE_COLUMNS),
            "optional": list(OPTIONAL_COLUMNS),
            "seen": manifest.get("columns", []),
        },
        "validation": manifest.get("validation", {}),
        "rows_preview": preview_rows,
    }


def approve(version_id: str, actor: str = "founder") -> Dict[str, Any]:
    manifest = _load_manifest(version_id)
    if manifest.get("status") == "active":
        raise WorkspaceError("the active version is already approved")
    if not manifest.get("rows"):
        raise WorkspaceError("an empty version cannot be approved")
    manifest["status"] = "approved"
    manifest["approved_by"] = actor or "founder"
    manifest["approved_at"] = _now()
    _save_manifest(manifest)
    _audit("approve", version_id, actor,
           {"inventory_sha256": manifest.get("inventory_sha256")})
    return manifest


def activate(version_id: str, actor: str = "founder") -> Dict[str, Any]:
    manifest = _load_manifest(version_id)
    if manifest.get("status") not in ("approved", "active"):
        raise WorkspaceError("only an approved version can be activated")
    inventory_path = _version_dir(version_id) / "inventory.jsonl"
    if not inventory_path.exists():
        raise WorkspaceError("the version inventory file is missing")
    fingerprint = _sha256_path(inventory_path)

    previous = None
    current_manifest = _read_pointer()
    if current_manifest:
        previous = current_manifest.get("version_id")

    pointer = {
        "version_id": version_id,
        "path": "versions/%s/inventory.jsonl" % version_id,
        "sha256": fingerprint,
        "rows": manifest.get("rows"),
        "observation_range": manifest.get("observation_range"),
        "source_sha256": manifest.get("source_sha256"),
        "activated_at": _now(),
        "activated_by": actor or "founder",
        "previous_version_id": previous,
    }
    # Atomic: a reader sees either the old pointer or the new one.
    _atomic_write(active_pointer_path(),
                  json.dumps(pointer, ensure_ascii=False,
                             indent=2).encode("utf-8"))

    manifest["status"] = "active"
    manifest["activated_at"] = pointer["activated_at"]
    _save_manifest(manifest)
    if previous and previous != version_id:
        try:
            old = _load_manifest(previous)
            old["status"] = "approved"
            _save_manifest(old)
        except Exception:
            pass
    _clear_cache()
    _audit("activate", version_id, actor,
           {"previous": previous, "inventory_sha256": fingerprint})
    return pointer


def rollback(version_id: Optional[str] = None, actor: str = "founder"
             ) -> Dict[str, Any]:
    """Re-point the workspace at a previous approved version."""
    pointer = _read_pointer()
    if not pointer:
        raise WorkspaceError("no active version to roll back from")
    target = version_id or pointer.get("previous_version_id")
    if not target:
        raise WorkspaceError("no previous version is recorded")
    manifest = _load_manifest(target)
    if manifest.get("status") not in ("approved", "active"):
        raise WorkspaceError("the rollback target is not approved")
    inventory_path = _version_dir(target) / "inventory.jsonl"
    if not inventory_path.exists():
        raise WorkspaceError("the rollback target inventory is missing")

    new_pointer = {
        "version_id": target,
        "path": "versions/%s/inventory.jsonl" % target,
        "sha256": _sha256_path(inventory_path),
        "rows": manifest.get("rows"),
        "observation_range": manifest.get("observation_range"),
        "source_sha256": manifest.get("source_sha256"),
        "activated_at": _now(),
        "activated_by": actor or "founder",
        "previous_version_id": pointer.get("version_id"),
    }
    _atomic_write(active_pointer_path(),
                  json.dumps(new_pointer, ensure_ascii=False,
                             indent=2).encode("utf-8"))
    manifest["status"] = "active"
    manifest["activated_at"] = new_pointer["activated_at"]
    _save_manifest(manifest)
    try:
        old = _load_manifest(pointer.get("version_id"))
        old["status"] = "approved"
        _save_manifest(old)
    except Exception:
        pass
    _clear_cache()
    _audit("rollback", target, actor,
           {"from": pointer.get("version_id"),
            "inventory_sha256": new_pointer["sha256"]})
    return new_pointer


def _read_pointer() -> Optional[Dict[str, Any]]:
    path = active_pointer_path()
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        _audit("pointer_unreadable", None, "system", {"path": str(path)})
        return None
    if not isinstance(data, dict) or not data.get("version_id"):
        _audit("pointer_invalid", None, "system", {"path": str(path)})
        return None
    return data


def resolve_active_source() -> Optional[Dict[str, Any]]:
    """The active version as a served source, or None.

    A pointer that names a missing file, or whose fingerprint no longer
    matches, is treated as absent - loudly in the audit log, never as a
    silent switch of data.
    """
    pointer = _read_pointer()
    if not pointer:
        return None
    version_id = str(pointer.get("version_id"))
    try:
        path = _version_dir(version_id) / "inventory.jsonl"
    except WorkspaceError:
        return None
    if not path.exists():
        _audit("pointer_missing_inventory", version_id, "system", {})
        return None
    fingerprint = _sha256_path(path)
    expected = pointer.get("sha256")
    if expected and fingerprint.lower() != str(expected).lower():
        _audit("pointer_fingerprint_mismatch", version_id, "system",
               {"expected": expected, "actual": fingerprint})
        return None
    return {
        "version_id": version_id,
        "path": str(path),
        "sha256": fingerprint,
        "rows": pointer.get("rows"),
        "observation_range": pointer.get("observation_range"),
    }


def active_inventory_path() -> Optional[Path]:
    resolved = resolve_active_source()
    return Path(resolved["path"]) if resolved else None


def current() -> Dict[str, Any]:
    active = resolve_active_source()
    return {
        "active": active,
        "stamp": current_stamp(),
        "versions": list_versions(),
        "audit": audit_records(20),
    }


def list_versions() -> List[Dict[str, Any]]:
    root = versions_dir()
    if not root.exists():
        return []
    active = (resolve_active_source() or {}).get("version_id")
    items: List[Dict[str, Any]] = []
    for folder in sorted(root.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        manifest_path = folder / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            with manifest_path.open("r", encoding="utf-8") as handle:
                manifest = json.load(handle)
        except Exception:
            continue
        items.append({
            "version_id": manifest.get("version_id", folder.name),
            "status": "active" if manifest.get("version_id") == active
            else manifest.get("status"),
            "rows": manifest.get("rows"),
            "created_at": manifest.get("created_at"),
            "source_filename": manifest.get("source_filename"),
            "observation_range": manifest.get("observation_range"),
            "approved_by": manifest.get("approved_by"),
            "activated_at": manifest.get("activated_at"),
        })
    return items


# ---------------------------------------------------------------------------
# Stamps (the truthful chip + per-draft stamping)
# ---------------------------------------------------------------------------

_STAMP_CACHE: Dict[Tuple[str, float, int], Dict[str, Any]] = {}


def _clear_cache() -> None:
    _STAMP_CACHE.clear()


def _parse_date(value: Any) -> Optional[str]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _digest_file(path: Path) -> Dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"fingerprint": None, "rows": 0, "range": {"start": None,
                                                          "end": None}}
    key = (str(path), stat.st_mtime, stat.st_size)
    cached = _STAMP_CACHE.get(key)
    if cached:
        return cached
    fingerprint = _sha256_path(path)
    rows = 0
    dates: List[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            rows += 1
            if len(dates) < 20000:
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                value = record.get("latest_date")
                if value:
                    parsed = _parse_date(value)
                    if parsed:
                        dates.append(parsed)
    result = {
        "fingerprint": fingerprint,
        "rows": rows,
        "range": {"start": min(dates) if dates else None,
                  "end": max(dates) if dates else None},
    }
    _STAMP_CACHE[key] = result
    return result


def _configured_path() -> Path:
    from market import fh_query
    return Path(fh_query.MASTER_PATH)


def configured_stamp() -> Dict[str, Any]:
    path = _configured_path()
    digest = _digest_file(path)
    return {
        "mode": "configured",
        "version_id": None,
        "fingerprint": digest["fingerprint"],
        "rows": digest["rows"],
        "observation_range": digest["range"],
        "source": str(path),
        "label": "MASTER %s · %s rows · %s→%s" % (
            (digest["fingerprint"] or "missing")[:8],
            digest["rows"],
            (digest["range"]["start"] or "?"),
            (digest["range"]["end"] or "?")),
    }


def current_stamp() -> Dict[str, Any]:
    active = resolve_active_source()
    if not active:
        return configured_stamp()
    digest = _digest_file(Path(active["path"]))
    return {
        "mode": "version",
        "version_id": active["version_id"],
        "fingerprint": digest["fingerprint"],
        "rows": digest["rows"],
        "observation_range": digest["range"],
        "source": active["path"],
        "label": "INVENTORY %s · %s · %s rows · %s→%s" % (
            active["version_id"],
            (digest["fingerprint"] or "missing")[:8],
            digest["rows"],
            (digest["range"]["start"] or "?"),
            (digest["range"]["end"] or "?")),
    }


_SESSION_LAST: Dict[str, Dict[str, Any]] = {}
_SESSION_LOADED = [False]


def _load_session_index() -> None:
    if _SESSION_LOADED[0]:
        return
    _SESSION_LOADED[0] = True
    path = workspace_dir() / "session_stamps.jsonl"
    if not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                session = record.get("session_id")
                if session:
                    _SESSION_LAST[session] = record
    except OSError:
        pass


def session_note_version(session_id: str,
                         stamp: Dict[str, Any],
                         turn: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """Record the stamp a session now sees; return a change notice.

    The notice fires once per change (previous -> new) and never touches
    the customer draft text. Storing is best effort and O(1) per turn.
    """
    if not session_id:
        return None
    _load_session_index()
    previous = _SESSION_LAST.get(session_id)

    changed = bool(previous) and (
        previous.get("version_id") != stamp.get("version_id")
        or previous.get("fingerprint") != stamp.get("fingerprint"))

    _SESSION_LAST[session_id] = {
        "session_id": session_id,
        "version_id": stamp.get("version_id"),
        "fingerprint": stamp.get("fingerprint"),
        "mode": stamp.get("mode"),
        "rows": stamp.get("rows"),
        "turn": turn,
        "at": _now(),
    }
    try:
        workspace_dir().mkdir(parents=True, exist_ok=True)
        with (workspace_dir() / "session_stamps.jsonl").open(
                "a", encoding="utf-8") as handle:
            handle.write(json.dumps(_SESSION_LAST[session_id],
                                   ensure_ascii=False) + "\n")
    except Exception:
        pass

    if not changed:
        return None
    return {
        "previous": {
            "mode": previous.get("mode"),
            "version_id": previous.get("version_id"),
            "fingerprint": previous.get("fingerprint"),
        },
        "current": {
            "mode": stamp.get("mode"),
            "version_id": stamp.get("version_id"),
            "fingerprint": stamp.get("fingerprint"),
        },
        "note": "the active inventory changed; this turn was answered "
                "against the new version",
    }


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------


def stamps_for_session(session_id: str) -> Dict[int, Dict[str, Any]]:
    """The stamp recorded for each turn of one conversation.

    Older turns keep the stamp they were answered with, even after a
    different version is activated.
    """
    path = workspace_dir() / "session_stamps.jsonl"
    found: Dict[int, Dict[str, Any]] = {}
    if not path.exists():
        return found
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                try:
                    record = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if record.get("session_id") != session_id:
                    continue
                turn = record.get("turn")
                if isinstance(turn, int):
                    found[turn] = record
    except OSError:
        return found
    return found


def template_csv() -> bytes:
    """The downloadable CSV template with EXPLICIT units."""
    lines = [
        "# Faisal Hills AI Lead Desk - inventory upload template",
        "# One row per plot observation. Units: size_marla = marla; "
        "asking_price_pkr = PKR (whole rupees); observation_date = YYYY-MM-DD.",
        "# features: semicolon list from corner;sun_facing;park_facing;"
        "ndc_open;main_boulevard",
        ",".join(TEMPLATE_COLUMNS),
        "C,5,5600000,2026-10-07,Dealer ask,corner;park_facing",
        "C,5,5800000,2026-10-07,Dealer ask,",
        "B,10,9200000,2026-10-05,Dealer ask,sun_facing",
    ]
    escaped = []
    for line in lines:
        if line.startswith("#"):
            escaped.append(line)
            continue
        escaped.append(",".join(escape_cell(part) for part in line.split(",")))
    return ("\n".join(escaped) + "\n").encode("utf-8")
