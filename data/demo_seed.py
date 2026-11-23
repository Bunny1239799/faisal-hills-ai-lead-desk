from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from typing import Optional, Union

from data.db import init_db, insert_fact_source, load_facts


def seed_demo_data(db_path: Optional[Union[str, Path]] = None) -> sqlite3.Connection:
    """Seed the database with ~10 demo rows (demo=1) for 5 marla and 10 marla plots."""
    if db_path is None:
        # M4 (D-10): the demo/seed database is data/faisal_hills.db.
        # The root faisal_hills.db holds 5,867 raw dealer listings with
        # `raw_text` and `sender` columns and must never be written by a
        # demo/seed path, so it is explicitly NOT the default here.
        db_path = Path(__file__).resolve().parent / "faisal_hills.db"

    conn = init_db(db_path)
    # Delete existing demo data to make seed idempotent - delete in reverse dependency order
    conn.execute("DELETE FROM pricing WHERE demo = 1")
    conn.execute("DELETE FROM inventory WHERE demo = 1")
    conn.execute("DELETE FROM blocks WHERE demo = 1")
    conn.execute("DELETE FROM society_master WHERE demo = 1")
    conn.commit()

    # 1. Insert Demo Fact Source
    source = {
        "source_id": "SRC-DEMO-2026-001",
        "source_type": "official_rate_sheet",
        "document_name": "Faisal Hills Demo Master Sheet Q1 2026",
        "document_date": "2026-01-01",
        "uploaded_by": "System Admin",
        "notes": "Demo seed data with demo=1",
    }
    insert_fact_source(conn, source)

    verified_at = "2026-01-01T00:00:00Z"
    valid_until = "2028-12-31T23:59:59Z"
    verified_by = "Estate Lead Evaluator"

    # 2. Seed Society Master (1 row)
    society_facts = [
        {
            "fact_id": "FACT-SOC-001",
            "society_name": "Faisal Hills",
            "location": "N-5 National Highway, near Taxila / MPCHS G-T Road",
            "developer": "Zedem International",
            "total_area": "11891 Kanals",
            "value": "Faisal Hills is a premium housing society by Zedem International located on Grand Trunk Road near Taxila.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        }
    ]
    load_facts(conn, "society_master", society_facts)

    # 3. Seed Blocks (2 rows: Block A and Block B)
    block_facts = [
        {
            "fact_id": "FACT-BLK-A",
            "block_name": "Block A",
            "status": "Developed with possession",
            "features": "Main boulevard access, central commercial area",
            "value": "Block A is fully developed with possession available and rapid house construction underway.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-BLK-B",
            "block_name": "Block B",
            "status": "Development nearing completion",
            "features": "Scenic park facing plots, quiet residential sector",
            "value": "Block B offers scenic views with ongoing possession handovers.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
    ]
    load_facts(conn, "blocks", block_facts)

    # 4. Seed Inventory (4 rows: 5 Marla and 10 Marla in Block A & B)
    inventory_facts = [
        {
            "fact_id": "FACT-INV-A-5M-101",
            "plot_id": "FH-A-5M-101",
            "block_name": "Block A",
            "size_marla": 5.0,
            "category": "Residential",
            "status": "Available",
            "value": "Plot FH-A-5M-101 is an available 5 Marla residential plot in Block A.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-INV-A-10M-202",
            "plot_id": "FH-A-10M-202",
            "block_name": "Block A",
            "size_marla": 10.0,
            "category": "Residential",
            "status": "Available",
            "value": "Plot FH-A-10M-202 is an available 10 Marla residential plot on a 40ft road in Block A.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-INV-B-5M-303",
            "plot_id": "FH-B-5M-303",
            "block_name": "Block B",
            "size_marla": 5.0,
            "category": "Residential",
            "status": "Available",
            "value": "Plot FH-B-5M-303 is an available 5 Marla residential plot in Block B.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-INV-B-10M-404",
            "plot_id": "FH-B-10M-404",
            "block_name": "Block B",
            "size_marla": 10.0,
            "category": "Residential",
            "status": "Available",
            "value": "Plot FH-B-10M-404 is an available 10 Marla residential plot in Block B.",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
    ]
    load_facts(conn, "inventory", inventory_facts)

    # 5. Seed Pricing (4 rows corresponding to inventory/standard rates)
    pricing_facts = [
        {
            "fact_id": "FACT-PRC-A-5M",
            "inventory_id": "FH-A-5M-101",
            "block_name": "Block A",
            "size_marla": 5.0,
            "plot_type": "Residential",
            "price_pkr": 4500000.0,
            "value": "PKR 45 Lakhs (4,500,000 PKR)",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-PRC-A-10M",
            "inventory_id": "FH-A-10M-202",
            "block_name": "Block A",
            "size_marla": 10.0,
            "plot_type": "Residential",
            "price_pkr": 8200000.0,
            "value": "PKR 82 Lakhs (8,200,000 PKR)",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-PRC-B-5M",
            "inventory_id": "FH-B-5M-303",
            "block_name": "Block B",
            "size_marla": 5.0,
            "plot_type": "Residential",
            "price_pkr": 3800000.0,
            "value": "PKR 38 Lakhs (3,800,000 PKR)",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
        {
            "fact_id": "FACT-PRC-B-10M",
            "inventory_id": "FH-B-10M-404",
            "block_name": "Block B",
            "size_marla": 10.0,
            "plot_type": "Residential",
            "price_pkr": 7200000.0,
            "value": "PKR 72 Lakhs (7,200,000 PKR)",
            "currency": "PKR",
            "source_id": "SRC-DEMO-2026-001",
            "verified_by": verified_by,
            "verified_at": verified_at,
            "valid_until": valid_until,
            "demo": 1,
        },
    ]
    load_facts(conn, "pricing", pricing_facts)

    return conn


if __name__ == "__main__":
    # M4 (D-10): seed the demo database, never the root database.
    db_file = Path(__file__).resolve().parent / "faisal_hills.db"
    conn = seed_demo_data(db_file)
    print(f"Successfully seeded demo data in {db_file}")
    conn.close()
