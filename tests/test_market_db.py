import sqlite3
import pytest
from data.db import (
    get_db_connection,
    init_db,
    migrate_market_tables,
    generate_listing_hash,
    store_market_listing,
    recompute_market_stats,
)


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def test_migrate_market_tables_creates_tables(memory_db):
    migrate_market_tables(memory_db)

    # Check market_listings table
    cur = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='market_listings';"
    )
    assert cur.fetchone() is not None

    # Check market_stats table
    cur = memory_db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='market_stats';"
    )
    assert cur.fetchone() is not None


def test_plot_level_deduplication_hash():
    # Identical plot in same block and size should have identical hash regardless of message text/sender
    h1 = generate_listing_hash(
        sender="Dealer_1",
        block_code="A",
        size_marla=5.0,
        side="SELL",
        price_pkr=4500000,
        raw_timestamp="10/04/2026, 10:00 am",
        plot_no="145",
        raw_text="Plot 145 block A available",
    )
    h2 = generate_listing_hash(
        sender="Dealer_2",
        block_code="a",
        size_marla=5.0,
        side="SELL",
        price_pkr=4800000,
        raw_timestamp="10/04/2026, 11:30 am",
        plot_no=" 145 ",
        raw_text="Direct deal 145 Block A",
    )
    assert h1 == h2

    # Different plot number should produce different hash
    h3 = generate_listing_hash(
        sender="Dealer_1",
        block_code="A",
        size_marla=5.0,
        side="SELL",
        price_pkr=4500000,
        raw_timestamp="10/04/2026, 10:00 am",
        plot_no="146",
    )
    assert h1 != h3


def test_store_market_listing_and_dedupe(memory_db):
    migrate_market_tables(memory_db)

    listing_1 = {
        "sender": "Agent_1",
        "raw_timestamp": "10/04/2026, 10:00 am",
        "block_code": "A",
        "size_marla": 5.0,
        "category": "residential",
        "side": "SELL",
        "price_pkr": 4500000,
        "plot_no": "201",
        "is_corner": 1,
        "is_boulevard": 0,
        "is_park_facing": 0,
        "attributes": ["residential", "corner"],
        "raw_text": "Block A plot 201 5 marla corner for sale 45 lac",
    }

    # First insert should succeed
    stored_first = store_market_listing(memory_db, listing_1)
    assert stored_first is True

    # Duplicate insert on same plot should be ignored
    listing_duplicate = {
        "sender": "Agent_2",
        "raw_timestamp": "10/04/2026, 11:00 am",
        "block_code": "A",
        "size_marla": 5.0,
        "category": "residential",
        "side": "SELL",
        "price_pkr": 4600000,
        "plot_no": "201",
        "raw_text": "Another agent listing plot 201 in Block A",
    }
    stored_dup = store_market_listing(memory_db, listing_duplicate)
    assert stored_dup is False

    # Check total count in DB is 1
    cur = memory_db.execute("SELECT count(*) as cnt FROM market_listings;")
    assert cur.fetchone()["cnt"] == 1


def test_recompute_market_stats(memory_db):
    migrate_market_tables(memory_db)

    # Insert sample prices for Block A, 5 Marla, SELL side: [40L, 42L, 45L, 48L, 50L]
    prices = [4000000, 4200000, 4500000, 4800000, 5000000]
    for idx, p in enumerate(prices):
        store_market_listing(
            memory_db,
            {
                "sender": f"Agent_{idx}",
                "raw_timestamp": f"10/04/2026, 10:0{idx} am",
                "block_code": "A",
                "size_marla": 5.0,
                "category": "residential",
                "side": "SELL",
                "price_pkr": p,
                "plot_no": str(500 + idx),
                "raw_text": f"Plot {500 + idx} 5 marla block A",
            },
        )

    # Also add an INQUIRY / unpriced record that should not distort stats
    store_market_listing(
        memory_db,
        {
            "sender": "Customer_1",
            "block_code": "A",
            "size_marla": 5.0,
            "side": "INQUIRY",
            "price_pkr": None,
            "raw_text": "Block A rate inquiry",
        },
    )

    updated_count = recompute_market_stats(memory_db)
    assert updated_count == 1

    cur = memory_db.execute(
        "SELECT * FROM market_stats WHERE block_code='A' AND size_marla=5.0 AND side='SELL';"
    )
    stat = cur.fetchone()
    assert stat is not None
    assert stat["sample_count"] == 5
    assert stat["min_price_pkr"] == 4000000
    assert stat["max_price_pkr"] == 5000000
    assert stat["median_price_pkr"] == 4500000


def test_policy_to_entities_to_market_flow():
    # Step 1: Policy check
    from app.policy import evaluate_policy
    message = "I want to buy 5 marla in Block A"
    decision = evaluate_policy(message)
    # This message should be safe: it's a buying inquiry, no discount, booking, etc.
    assert decision.action == "answer"
    assert decision.needs_human == False

    # Step 2: Entity extraction
    from market.llm_extract import extract_entities_with_fallback
    entities = extract_entities_with_fallback(message)
    # We expect: 
    #   size_marla = 5.0
    #   block_code = "A"
    #   side = "BUY"
    #   price_pkr = None (because no price mentioned)
    assert entities.size_marla == 5.0
    assert entities.block_code == "A"
    assert entities.side == "BUY"
    assert entities.price_pkr is None

    # Step 3: Store in market_listings
    from data.db import get_db_connection, store_market_listing
    from data.db import init_db, migrate_market_tables
    conn = get_db_connection(":memory:")
    init_db(conn)
    migrate_market_tables(conn)

    # Prepare listing data
    listing_data = {
        "sender": "test_user",
        "raw_timestamp": "10/04/2026, 10:00 am",
        "block_code": entities.block_code,
        "size_marla": entities.size_marla,
        "category": entities.category,  # might be None
        "side": entities.side,
        "price_pkr": entities.price_pkr,
        "plot_no": None,
        "is_corner": getattr(entities, 'is_corner', False),
        "is_boulevard": getattr(entities, 'is_boulevard', False),
        "is_park_facing": getattr(entities, 'is_park_facing', False),
        "attributes": getattr(entities, 'attributes', []),
        "raw_text": message
    }

    stored = store_market_listing(conn, listing_data)
    assert stored is True  # first time should succeed

    # Try to store again -> should be duplicate and return False
    stored_dup = store_market_listing(conn, listing_data)
    assert stored_dup is False

    # Check that we have one record
    cur = conn.execute("SELECT COUNT(*) as cnt FROM market_listings")
    assert cur.fetchone()["cnt"] == 1

    conn.close()
