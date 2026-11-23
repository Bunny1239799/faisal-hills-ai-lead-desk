import argparse
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from data.db import (
    get_db_connection,
    migrate_market_tables,
    recompute_market_stats,
)


def format_pkr(amount: int) -> str:
    """Format PKR into Lacs or Crores for readable terminal output."""
    if not amount or amount <= 0:
        return "N/A"
    if amount >= 10_000_000:
        val = amount / 10_000_000
        return f"{val:.2f} Cr"
    if amount >= 100_000:
        val = amount / 100_000
        return f"{val:.2f} Lac"
    return f"{amount:,} PKR"


def generate_market_report(db_path: str = None) -> None:
    conn = get_db_connection(db_path)
    migrate_market_tables(conn)
    recompute_market_stats(conn)

    # 1. Check total listings count
    cur = conn.execute("SELECT COUNT(*) AS total_count FROM market_listings;")
    total_listings = cur.fetchone()["total_count"]

    print("================================================================================")
    print("                      FAISAL HILLS MARKET INTELLIGENCE REPORT                   ")
    print("================================================================================")

    if total_listings == 0:
        print("\n[!] No market listings found in the database.")
        print("    Run the chat ingestion loader first to import dealer WhatsApp chat exports.")
        print("    Example: python -m tools.ingest_chat <chat_export_file.txt>\n")
        print("================================================================================")
        conn.close()
        return

    print(f"\nTotal Parsed Market Listings: {total_listings}")

    # Breakdown by side
    cur = conn.execute(
        "SELECT side, COUNT(*) AS cnt FROM market_listings GROUP BY side ORDER BY cnt DESC;"
    )
    side_breakdown = cur.fetchall()
    sides_str = ", ".join([f"{r['side']}: {r['cnt']}" for r in side_breakdown])
    print(f"Side Breakdown: {sides_str}")

    # 2. Market Aggregate Stats
    print("\n--------------------------------------------------------------------------------")
    print(" AGGREGATE PRICE RANGES (BY BLOCK, SIZE & SIDE)")
    print("--------------------------------------------------------------------------------")
    header = f"{'Block':<10} | {'Size':<10} | {'Side':<6} | {'Count':<6} | {'Min':<10} | {'Median':<10} | {'Max':<10}"
    print(header)
    print("-" * len(header))

    cur = conn.execute(
        """
        SELECT block_code, size_marla, side, sample_count,
               min_price_pkr, p25_price_pkr, median_price_pkr, p75_price_pkr, max_price_pkr
        FROM market_stats
        ORDER BY block_code ASC, size_marla ASC, side ASC;
        """
    )
    stats = cur.fetchall()

    if not stats:
        print("No priced statistics available yet (listings may be unpriced or inquiry only).")
    else:
        for s in stats:
            size_label = f"{s['size_marla']:.1f} Marla"
            min_str = format_pkr(s["min_price_pkr"])
            med_str = format_pkr(s["median_price_pkr"])
            max_str = format_pkr(s["max_price_pkr"])
            print(
                f"{s['block_code']:<10} | {size_label:<10} | {s['side']:<6} | {s['sample_count']:<6} | {min_str:<10} | {med_str:<10} | {max_str:<10}"
            )

    # 3. Recent 5 Listings Sample
    print("\n--------------------------------------------------------------------------------")
    print(" RECENT LISTINGS SAMPLE")
    print("--------------------------------------------------------------------------------")
    cur = conn.execute(
        """
        SELECT sender, block_code, size_marla, side, price_pkr, plot_no, raw_text
        FROM market_listings
        ORDER BY listing_id DESC
        LIMIT 5;
        """
    )
    recent = cur.fetchall()
    for idx, item in enumerate(recent, 1):
        price_str = format_pkr(item["price_pkr"]) if item["price_pkr"] else "Not mentioned"
        block_str = item["block_code"] or "Unknown"
        size_str = f"{item['size_marla']} Marla" if item["size_marla"] else "Unknown"
        plot_str = f"Plot #{item['plot_no']}" if item["plot_no"] else "General"
        print(f"[{idx}] {item['sender']} | {block_str} | {size_str} | {item['side']} | {price_str} | {plot_str}")
        print(f"    Raw: {item['raw_text'].strip()[:100]}")

    print("================================================================================\n")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate Faisal Hills Market Intelligence Report")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database file")
    args = parser.parse_args()

    generate_market_report(args.db)


if __name__ == "__main__":
    main()
