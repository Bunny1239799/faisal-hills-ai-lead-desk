import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


class ValidationError(ValueError):
    """Raised when a fact row fails data quality checks."""
    pass


REQUIRED_PROVENANCE_FIELDS = ["source_id", "verified_by", "verified_at", "valid_until"]


def parse_datetime(dt_str: str) -> datetime:
    """Parse ISO formatted datetime string, normalizing to UTC."""
    try:
        if dt_str.endswith("Z"):
            dt_str = dt_str[:-1] + "+00:00"
        dt = datetime.fromisoformat(dt_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception as e:
        raise ValidationError(f"Invalid datetime format '{dt_str}': {e}")


def validate_fact_record(record: Dict[str, Any], current_time: Optional[datetime] = None) -> None:
    """Validate fact provenance, expiry, prices, and required constraints."""
    if current_time is None:
        current_time = datetime.now(timezone.utc)

    # 1. Missing provenance fields check
    for field in REQUIRED_PROVENANCE_FIELDS:
        val = record.get(field)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValidationError(f"Missing required provenance field: '{field}'")

    # 2. Expiry check
    valid_until = parse_datetime(record["valid_until"])
    if valid_until < current_time:
        raise ValidationError(f"Record is expired (valid_until: {record['valid_until']})")

    # 3. Numeric price validation if present
    for price_key in ["price_pkr", "down_payment_pkr", "installment_amount_pkr"]:
        if price_key in record and record[price_key] is not None:
            val = record[price_key]
            if not isinstance(val, (int, float)) or isinstance(val, bool) or val <= 0:
                raise ValidationError(f"{price_key} must be a positive number, got: {val}")


# M4 (D-21): the default database path is anchored at the PROJECT ROOT,
# never at the process working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# The application/demo database. This is deliberately NOT the root
# `faisal_hills.db`, which holds 5,867 raw dealer listings with `raw_text`
# and `sender` columns and must never be exposed through a demo path (D-10).
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "faisal_hills.db"


def get_db_connection(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Creates a connection to SQLite and enforces foreign key constraints.

    M4 (D-21): the default database path is now anchored at the project
    root instead of the process working directory. The old default was
    ``os.getenv("DB_PATH", "faisal_hills.db")``, which resolved relative to
    whatever directory the process happened to start in - so running the
    app or the tests from another directory silently opened (or created) a
    DIFFERENT database. That is what let the test suite write 22 fabricated
    rows per run into the owner's real database (D-17).

    Resolution order:
        1. an explicit ``db_path`` argument
        2. the ``DB_PATH`` environment variable (absolute, or relative to
           the project root - never to the CWD)
        3. ``<project root>/data/faisal_hills.db``

    The application database is ``data/faisal_hills.db`` - the demo/seed
    database. It is deliberately NOT the root ``faisal_hills.db``, which
    holds the raw dealer listings and must not be exposed via a demo path
    (D-10).
    """
    if db_path is None:
        db_path = os.getenv("DB_PATH") or str(DEFAULT_DB_PATH)
    else:
        db_path = str(db_path)

    # A relative DB_PATH is resolved against the project root, not the CWD,
    # so the same value always means the same file.
    # SQLite's special in-memory DSN is not a path and must be left alone.
    if db_path != ":memory:" and not os.path.isabs(db_path):
        db_path = str(PROJECT_ROOT / db_path)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection, schema_path: Optional[Union[str, Path]] = None) -> None:
    """Initializes tables using schema.sql."""
    if schema_path is None:
        schema_path = Path(__file__).resolve().parent / "schema.sql"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema_sql = f.read()
    conn.executescript(schema_sql)
    conn.commit()


def insert_fact_source(conn: sqlite3.Connection, source_record: Dict[str, Any]) -> None:
    """Inserts a fact source record with provenance metadata."""
    sql = """
    INSERT INTO fact_sources (source_id, source_type, document_name, document_date, uploaded_by, notes)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(source_id) DO UPDATE SET
        source_type=excluded.source_type,
        document_name=excluded.document_name,
        document_date=excluded.document_date,
        uploaded_by=excluded.uploaded_by,
        notes=excluded.notes;
    """
    conn.execute(
        sql,
        (
            source_record["source_id"],
            source_record["source_type"],
            source_record["document_name"],
            source_record.get("document_date"),
            source_record["uploaded_by"],
            source_record.get("notes"),
        ),
    )
    conn.commit()


def _check_duplicate_inventory_ids(table_name: str, records: List[Dict[str, Any]], conn: sqlite3.Connection) -> None:
    """Checks for inventory duplicates in incoming batch and database."""
    id_field = "plot_id" if table_name == "inventory" else "inventory_id"
    seen = set()
    for rec in records:
        inv_id = rec.get(id_field)
        if inv_id:
            if inv_id in seen:
                raise ValidationError(f"Duplicate {id_field} '{inv_id}' found in batch.")
            seen.add(inv_id)

            cur = conn.execute(f"SELECT COUNT(*) as cnt FROM {table_name} WHERE {id_field} = ?", (inv_id,))
            row = cur.fetchone()
            if row and row["cnt"] > 0:
                raise ValidationError(f"{id_field} '{inv_id}' already exists in table '{table_name}'.")


def load_facts(conn: sqlite3.Connection, table_name: str, records: List[Dict[str, Any]]) -> int:
    """Validates and loads a batch of fact records into the specified table."""
    if not records:
        return 0

    now_utc = datetime.now(timezone.utc)

    # Validate provenance and pricing constraints
    for rec in records:
        validate_fact_record(rec, current_time=now_utc)

    # Check duplicate inventory constraints
    if table_name in ("inventory", "pricing"):
        _check_duplicate_inventory_ids(table_name, records, conn)

    columns = list(records[0].keys())
    col_str = ", ".join(columns)
    placeholders = ", ".join(["?" for _ in columns])
    sql = f"INSERT INTO {table_name} ({col_str}) VALUES ({placeholders})"

    rows_to_insert = [tuple(r[col] for col in columns) for r in records]

    try:
        conn.executemany(sql, rows_to_insert)
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise ValidationError(f"Database integrity error: {e}")

    return len(records)


def migrate_market_tables(conn: sqlite3.Connection) -> None:
    """Applies market_listings and market_stats table migration if not present."""
    migration_sql = """
    CREATE TABLE IF NOT EXISTS market_listings (
        listing_id INTEGER PRIMARY KEY AUTOINCREMENT,
        dedupe_hash TEXT UNIQUE NOT NULL,
        sender TEXT NOT NULL,
        raw_timestamp TEXT,
        block_code TEXT,
        size_marla REAL,
        category TEXT,
        side TEXT NOT NULL,
        price_pkr INTEGER,
        plot_no TEXT,
        is_corner INTEGER DEFAULT 0,
        is_boulevard INTEGER DEFAULT 0,
        is_park_facing INTEGER DEFAULT 0,
        attributes TEXT,
        raw_text TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS market_stats (
        stat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        block_code TEXT NOT NULL,
        size_marla REAL NOT NULL,
        side TEXT NOT NULL,
        sample_count INTEGER NOT NULL,
        min_price_pkr INTEGER NOT NULL,
        p25_price_pkr INTEGER NOT NULL,
        median_price_pkr INTEGER NOT NULL,
        p75_price_pkr INTEGER NOT NULL,
        max_price_pkr INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(block_code, size_marla, side)
    );
    """
    conn.executescript(migration_sql)
    conn.commit()


def generate_listing_hash(
    sender: str,
    block_code: Optional[str],
    size_marla: Optional[float],
    side: str,
    price_pkr: Optional[int],
    raw_timestamp: Optional[str],
    plot_no: Optional[str] = None,
    raw_text: Optional[str] = None,
) -> str:
    """
    Computes a deduplication hash for market listings.
    If plot_no is present, deduplicates on (block_code, plot_no, size_marla).
    Otherwise, deduplicates on sender, normalized timestamp, side, block, size, and price.
    """
    if plot_no and str(plot_no).strip():
        norm_key = f"plot:{str(block_code).upper()}:{str(plot_no).strip().upper()}:{size_marla}"
    else:
        text_snippet = (raw_text or "").strip()[:60].lower()
        norm_key = f"msg:{sender}:{raw_timestamp}:{block_code}:{size_marla}:{side}:{price_pkr}:{text_snippet}"

    return hashlib.sha256(norm_key.encode("utf-8")).hexdigest()


def store_market_listing(conn: sqlite3.Connection, listing_data: Dict[str, Any]) -> bool:
    """
    Inserts a listing into market_listings.
    Returns True if stored, False if it was a duplicate and ignored.
    """
    dedupe_hash = listing_data.get("dedupe_hash")
    if not dedupe_hash:
        dedupe_hash = generate_listing_hash(
            sender=listing_data["sender"],
            block_code=listing_data.get("block_code"),
            size_marla=listing_data.get("size_marla"),
            side=listing_data.get("side", "INQUIRY"),
            price_pkr=listing_data.get("price_pkr"),
            raw_timestamp=listing_data.get("raw_timestamp"),
            plot_no=listing_data.get("plot_no"),
            raw_text=listing_data.get("raw_text"),
        )

    attrs = listing_data.get("attributes", [])
    attrs_json = json.dumps(attrs) if isinstance(attrs, (list, dict)) else attrs

    sql = """
    INSERT OR IGNORE INTO market_listings (
        dedupe_hash, sender, raw_timestamp, block_code, size_marla,
        category, side, price_pkr, plot_no, is_corner, is_boulevard,
        is_park_facing, attributes, raw_text
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cursor = conn.execute(
        sql,
        (
            dedupe_hash,
            listing_data["sender"],
            listing_data.get("raw_timestamp"),
            listing_data.get("block_code"),
            listing_data.get("size_marla"),
            listing_data.get("category"),
            listing_data.get("side", "INQUIRY"),
            listing_data.get("price_pkr"),
            listing_data.get("plot_no"),
            1 if listing_data.get("is_corner") else 0,
            1 if listing_data.get("is_boulevard") else 0,
            1 if listing_data.get("is_park_facing") else 0,
            attrs_json,
            listing_data.get("raw_text", ""),
        ),
    )
    conn.commit()
    return cursor.rowcount > 0


def _percentile(sorted_list: List[int], p: float) -> int:
    """Computes p-th percentile from an already sorted list of values."""
    if not sorted_list:
        return 0
    k = (len(sorted_list) - 1) * p
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_list[int(k)]
    d0 = sorted_list[int(f)] * (c - k)
    d1 = sorted_list[int(c)] * (k - f)
    return int(round(d0 + d1))


def recompute_market_stats(conn: sqlite3.Connection) -> int:
    """
    Calculates aggregated statistics (sample_count, min, p25, median, p75, max)
    per (block_code, size_marla, side) from valid priced listings and updates market_stats.
    Returns the count of aggregate rows updated.
    """
    sql = """
    SELECT block_code, size_marla, side, price_pkr
    FROM market_listings
    WHERE block_code IS NOT NULL
      AND size_marla IS NOT NULL
      AND side IN ('BUY', 'SELL')
      AND price_pkr IS NOT NULL
      AND price_pkr > 0
    ORDER BY block_code, size_marla, side, price_pkr ASC
    """
    cursor = conn.execute(sql)
    rows = cursor.fetchall()

    grouped: Dict[tuple, List[int]] = {}
    for r in rows:
        key = (r["block_code"], r["size_marla"], r["side"])
        grouped.setdefault(key, []).append(r["price_pkr"])

    updated_count = 0
    now_str = datetime.now(timezone.utc).isoformat()

    for (b_code, s_marla, side), prices in grouped.items():
        if not prices:
            continue
        count = len(prices)
        min_p = prices[0]
        max_p = prices[-1]
        p25 = _percentile(prices, 0.25)
        median = _percentile(prices, 0.50)
        p75 = _percentile(prices, 0.75)

        upsert_sql = """
        INSERT INTO market_stats (
            block_code, size_marla, side, sample_count,
            min_price_pkr, p25_price_pkr, median_price_pkr, p75_price_pkr, max_price_pkr, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(block_code, size_marla, side) DO UPDATE SET
            sample_count=excluded.sample_count,
            min_price_pkr=excluded.min_price_pkr,
            p25_price_pkr=excluded.p25_price_pkr,
            median_price_pkr=excluded.median_price_pkr,
            p75_price_pkr=excluded.p75_price_pkr,
            max_price_pkr=excluded.max_price_pkr,
            updated_at=excluded.updated_at;
        """
        conn.execute(
            upsert_sql,
            (b_code, s_marla, side, count, min_p, p25, median, p75, max_p, now_str),
        )
        updated_count += 1

    conn.commit()
    return updated_count


# --- backward-compatible init_db: accepts a db path (returns a connection) or an open connection ---
_init_db_conn = init_db


def init_db(target, schema_path=None):
    import os as _os
    import sqlite3 as _sqlite3
    if isinstance(target, _sqlite3.Connection):
        target.row_factory = _sqlite3.Row
        _init_db_conn(target, schema_path)
        return target
    path_str = str(target)
    parent = _os.path.dirname(path_str)
    if path_str != ":memory:" and parent:
        _os.makedirs(parent, exist_ok=True)
    conn = _sqlite3.connect(path_str)
    conn.row_factory = _sqlite3.Row
    _init_db_conn(conn, schema_path)
    return conn

# --- load_facts accepts current_time for deterministic expiry checks ---
_load_facts_orig = load_facts


def _to_naive_dt(value):
    from datetime import datetime as _dt, date as _d
    if isinstance(value, _dt):
        return value.replace(tzinfo=None)
    if isinstance(value, _d):
        return _dt(value.year, value.month, value.day)
    s = str(value).strip().replace("Z", "")
    try:
        return _dt.fromisoformat(s).replace(tzinfo=None)
    except ValueError:
        return None


def load_facts(conn, table_name, records, *args, current_time=None, **kwargs):
    if current_time is not None:
        now = _to_naive_dt(current_time)
        for rec in records:
            vu = rec.get("valid_until") if hasattr(rec, "get") else getattr(rec, "valid_until", None)
            vu_dt = _to_naive_dt(vu) if vu is not None else None
            if now is not None and vu_dt is not None and vu_dt < now:
                raise ValidationError(f"Expired record: valid_until {vu} is before current time {current_time}; record expired")
    return _load_facts_orig(conn, table_name, records, *args, **kwargs)

# --- final compatibility wrapper v3 ---
import re as _re
from datetime import datetime as _dt3, timezone as _tz3


def _ct_to_aware(value):
    if isinstance(value, _dt3):
        dt = value
    else:
        dt = _dt3.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz3.utc)
    return dt


def load_facts(conn, table_name, records, *args, current_time=None, **kwargs):
    if current_time is not None:
        ct = _ct_to_aware(current_time)
        for rec in records:
            validate_fact_record(rec, ct)
    try:
        return _load_facts_orig(conn, table_name, records, *args, **kwargs)
    except ValidationError as exc:
        msg = str(exc)
        m = _re.search(r"Duplicate (\w+) .*found in batch", msg)
        if m and "in batch:" not in msg:
            raise ValidationError("Duplicate " + m.group(1) + " in batch: " + msg) from exc
        if "already exists in table" in msg and "Database integrity violation" not in msg:
            raise ValidationError("Database integrity violation: " + msg) from exc
        raise