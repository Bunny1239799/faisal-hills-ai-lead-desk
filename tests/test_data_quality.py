import sqlite3
from datetime import datetime, timezone
import pytest

from data.db import init_db, insert_fact_source, load_facts, ValidationError
from data.demo_seed import seed_demo_data


@pytest.fixture
def db_conn():
    """Create an in-memory SQLite database connection for testing."""
    conn = init_db(":memory:")
    # Insert a valid source for FK constraints
    insert_fact_source(
        conn,
        {
            "source_id": "SRC-TEST-001",
            "source_type": "test_doc",
            "document_name": "Test Document",
            "uploaded_by": "Tester",
        },
    )
    yield conn
    conn.close()


def valid_pricing_record(**overrides):
    base = {
        "fact_id": "FACT-TEST-PRC-1",
        "inventory_id": "FH-TEST-001",
        "block_name": "Block A",
        "size_marla": 5.0,
        "plot_type": "Residential",
        "price_pkr": 5000000.0,
        "value": "PKR 5,000,000",
        "currency": "PKR",
        "source_id": "SRC-TEST-001",
        "verified_by": "Quality Lead",
        "verified_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "demo": 1,
    }
    base.update(overrides)
    return base


def test_reject_missing_source_id(db_conn):
    rec = valid_pricing_record(source_id=None)
    with pytest.raises(ValidationError, match="Missing required provenance field: 'source_id'"):
        load_facts(db_conn, "pricing", [rec])


def test_reject_missing_verified_by(db_conn):
    rec = valid_pricing_record(verified_by="")
    with pytest.raises(ValidationError, match="Missing required provenance field: 'verified_by'"):
        load_facts(db_conn, "pricing", [rec])


def test_reject_missing_verified_at(db_conn):
    rec = valid_pricing_record(verified_at=None)
    with pytest.raises(ValidationError, match="Missing required provenance field: 'verified_at'"):
        load_facts(db_conn, "pricing", [rec])


def test_reject_missing_valid_until(db_conn):
    rec = valid_pricing_record(valid_until="")
    with pytest.raises(ValidationError, match="Missing required provenance field: 'valid_until'"):
        load_facts(db_conn, "pricing", [rec])


def test_reject_expired_valid_until(db_conn):
    rec = valid_pricing_record(valid_until="2025-12-31T23:59:59Z")
    current_time = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValidationError, match="Record is expired"):
        load_facts(db_conn, "pricing", [rec], current_time=current_time)


def test_reject_duplicate_inventory_ids_in_batch(db_conn):
    inv1 = {
        "fact_id": "FACT-INV-001",
        "plot_id": "FH-A-100",
        "block_name": "Block A",
        "size_marla": 5.0,
        "category": "Residential",
        "status": "Available",
        "value": "Plot FH-A-100 available",
        "currency": "PKR",
        "source_id": "SRC-TEST-001",
        "verified_by": "Agent A",
        "verified_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "demo": 1,
    }
    inv2 = {
        "fact_id": "FACT-INV-002",
        "plot_id": "FH-A-100",  # Duplicate plot_id
        "block_name": "Block A",
        "size_marla": 5.0,
        "category": "Residential",
        "status": "Available",
        "value": "Plot FH-A-100 duplicate",
        "currency": "PKR",
        "source_id": "SRC-TEST-001",
        "verified_by": "Agent A",
        "verified_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "demo": 1,
    }
    with pytest.raises(ValidationError, match="Duplicate plot_id in batch"):
        load_facts(db_conn, "inventory", [inv1, inv2])


def test_reject_duplicate_inventory_id_in_database(db_conn):
    inv1 = {
        "fact_id": "FACT-INV-001",
        "plot_id": "FH-A-100",
        "block_name": "Block A",
        "size_marla": 5.0,
        "category": "Residential",
        "status": "Available",
        "value": "Plot FH-A-100 available",
        "currency": "PKR",
        "source_id": "SRC-TEST-001",
        "verified_by": "Agent A",
        "verified_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "demo": 1,
    }
    inv2 = {
        "fact_id": "FACT-INV-002",
        "plot_id": "FH-A-100",  # Same plot_id
        "block_name": "Block A",
        "size_marla": 5.0,
        "category": "Residential",
        "status": "Available",
        "value": "Plot FH-A-100 duplicate",
        "currency": "PKR",
        "source_id": "SRC-TEST-001",
        "verified_by": "Agent A",
        "verified_at": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
        "demo": 1,
    }
    load_facts(db_conn, "inventory", [inv1])
    with pytest.raises(ValidationError, match="Database integrity violation"):
        load_facts(db_conn, "inventory", [inv2])


@pytest.mark.parametrize("invalid_price", [0, -100, -0.01, "invalid_number"])
def test_reject_non_positive_price(db_conn, invalid_price):
    rec = valid_pricing_record(price_pkr=invalid_price)
    with pytest.raises(ValidationError, match="price_pkr must be"):
        load_facts(db_conn, "pricing", [rec])


def test_demo_seed_execution(tmp_path):
    db_file = tmp_path / "test_demo.db"
    conn = seed_demo_data(db_file)

    cursor = conn.cursor()
    # Check that demo records were inserted
    cursor.execute("SELECT COUNT(*) FROM society_master WHERE demo = 1")
    assert cursor.fetchone()[0] == 1

    cursor.execute("SELECT COUNT(*) FROM blocks WHERE demo = 1")
    assert cursor.fetchone()[0] == 2

    cursor.execute("SELECT COUNT(*) FROM inventory WHERE demo = 1")
    assert cursor.fetchone()[0] == 4

    cursor.execute("SELECT COUNT(*) FROM pricing WHERE demo = 1")
    assert cursor.fetchone()[0] == 4

    conn.close()
