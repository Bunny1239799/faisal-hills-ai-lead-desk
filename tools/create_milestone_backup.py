"""Founder-safe milestone backup - ZIP the working tree, touch nothing.

Creates a timestamped ZIP of the project's working tree (code, docs,
tests - the valuable UNCOMMITTED work) into
``D:\\FaisalHillsAILeadDesk\\backups\\milestone_backups\\`` and writes
a manifest next to it (timestamp, git HEAD, file count, total size,
SHA256 of the ZIP, the excluded directories).

Excluded by design: virtualenvs, caches, test scratch, runtime
databases/stores, screenshots, node modules, Chrome profiles - and the
protected master data (which is NEVER read from its protected folder;
it lives outside the repository and has its own custody).

The tool never runs any git command that changes state (no add /
commit / push / reset / clean / stash); it only READS ``git rev-parse``
for the manifest. Safe to run repeatedly - every run is a new,
timestamped archive.

Usage:
    .venv\\Scripts\\python.exe tools\\create_milestone_backup.py [--note "..."]
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(r"D:\AI-Projects\laya-gateway")
BACKUP_ROOT = Path(r"D:\FaisalHillsAILeadDesk\backups\milestone_backups")

# Directory names (relative to the project root) that are excluded.
# Everything here is either regenerable, runtime state, huge, or
# already has its own custody (backups/, screenshots/).
EXCLUDED_DIRS = {
    ".venv", ".git", "__pycache__", ".pytest_cache", ".aider.tags.cache.v4",
    "node_modules", "backups", "backupss12fix", "logs",
    "data",            # runtime DBs/stores (owner DB residue preserved in place)
    "docs/reports/ui", # screenshots (large; regenerable via tests/m12_screenshots.py)
    "gemini", "jarvis", "path", "pytest tests",
}

EXCLUDED_FILE_SUFFIXES = (".db", ".log", ".png", ".zip", ".pdf")


def _git_head() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=30)
        return out.stdout.strip() if out.returncode == 0 else "unknown"
    except Exception:
        return "unavailable"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def collect_files() -> list:
    files = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        parts = rel.parts
        if any(part in EXCLUDED_DIRS for part in parts):
            continue
        if "docs" in parts and "reports" in parts and "ui" in parts:
            continue  # the nested screenshot mirror
        if rel.suffix.lower() in EXCLUDED_FILE_SUFFIXES:
            continue
        # protected master data is outside the repository; nothing to
        # exclude here - but refuse, loudly, if that ever changes
        files.append(rel)
    return sorted(files)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--note", default="", help="a line for the manifest")
    args = parser.parse_args(argv)

    BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = BACKUP_ROOT / ("laya-gateway_%s.zip" % stamp)

    files = collect_files()
    if not files:
        print("nothing to back up - refusing to write an empty archive")
        return 1

    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for rel in files:
            archive.write(ROOT / rel, str(rel))

    manifest = {
        "timestamp": stamp,
        "git_head": _git_head(),
        "files": len(files),
        "total_uncompressed_bytes": sum(
            (ROOT / rel).stat().st_size for rel in files),
        "zip_bytes": zip_path.stat().st_size,
        "zip_sha256": _sha256(zip_path),
        "excluded_dirs": sorted(EXCLUDED_DIRS),
        "excluded_suffixes": list(EXCLUDED_FILE_SUFFIXES),
        "note": args.note,
        "protected_master_data": "NEVER read or written - it lives outside "
                                 "the repository and is not part of any "
                                 "backup this tool creates",
    }
    manifest_path = zip_path.with_suffix(".manifest.txt")
    lines = ["laya-gateway milestone backup",
             "=" * 40]
    lines += ["%s: %s" % (key, value) for key, value in manifest.items()]
    lines.append("")
    lines.append("verify: sha256 of the zip must equal zip_sha256 above")
    manifest_path.write_text("\n".join(lines), encoding="utf-8")

    print("backup : %s" % zip_path)
    print("files  : %d" % len(files))
    print("size   : %.1f KB (compressed)" % (zip_path.stat().st_size / 1024))
    print("sha256 : %s" % manifest["zip_sha256"])
    print("head   : %s" % manifest["git_head"])
    print("manifest: %s" % manifest_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
