#!/usr/bin/env python3
"""
Ingest all chat files in data/raw_chats/ according to APP_MODE.
- In demo mode: process only demo files (demo__fake_*.txt)
- In pilot mode: skip demo files
- Skip files starting with '_'
- Idempotent: re-running does not duplicate rows
- Prints market report after processing
"""
import os
import sys
from pathlib import Path
from typing import List

# Add project root to sys.path to allow imports from market, data, etc.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from market.parse_chat import parse_whatsapp_chat
from market.extract import extract_market_entities
from data.db import (
    get_db_connection,
    init_db,
    store_market_listing,
    recompute_market_stats,
)
from tools.market_report import generate_market_report


def get_chat_files_to_process(raw_chats_dir: Path, app_mode: str) -> List[Path]:
    """
    Return list of .txt files to process based on APP_MODE and skip rules.
    - Skip files starting with '_'
    - In demo mode: only process files starting with 'demo__fake_'
    - In pilot mode: skip files starting with 'demo__fake_'
    """
    all_txt_files = sorted(raw_chats_dir.glob("*.txt"))
    files_to_process = []

    for file_path in all_txt_files:
        # Skip files starting with '_'
        if file_path.name.startswith('_'):
            continue

        # Check if it's a demo file (by naming convention)
        is_demo_file = file_path.name.startswith('demo__fake_')

        if app_mode == "demo":
            if is_demo_file:
                files_to_process.append(file_path)
        elif app_mode == "pilot":
            if not is_demo_file:
                files_to_process.append(file_path)
        else:
            raise ValueError(f"Invalid APP_MODE: {app_mode}. Expected 'demo' or 'pilot'.")

    return files_to_process


def process_chat_file(file_path: Path, conn) -> None:
    """
    Parse a single chat file, extract entities, and store listings.
    """
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Error reading {file_path}: {e}", file=sys.stderr)
        return

    try:
        chats = parse_whatsapp_chat(content, anonymize=True)
    except Exception as e:
        print(f"Error parsing {file_path}: {e}", file=sys.stderr)
        return

    for chat in chats:
        try:
            entities = extract_market_entities(chat.text)
        except Exception as e:
            print(f"Error extracting entities from message '{chat.text[:50]}...': {e}", file=sys.stderr)
            continue

        # Prepare listing data for storage
        listing_data = {
            "sender": chat.sender,
            "block_code": entities.block_code,
            "size_marla": entities.size_marla,
            "side": entities.side,
            "price_pkr": entities.price_pkr,
            "plot_no": None,  # Not extracted in current implementation
            "raw_timestamp": chat.raw_timestamp,
            "raw_text": chat.text,
            "category": entities.category,
            "is_corner": entities.is_corner,
            "is_boulevard": entities.is_boulevard,
            "is_park_facing": entities.is_park_facing,
            "attributes": entities.attributes,
        }

        try:
            store_market_listing(conn, listing_data)
        except Exception as e:
            print(f"Error storing listing for message '{chat.text[:50]}...': {e}", file=sys.stderr)
            continue


def main() -> None:
    # Determine APP_MODE from environment, default to 'pilot' as per project handoff
    app_mode = os.environ.get("APP_MODE", "pilot").lower()
    if app_mode not in ("demo", "pilot"):
        print(f"APP_MODE must be 'demo' or 'pilot', got '{app_mode}'", file=sys.stderr)
        sys.exit(1)

    raw_chats_dir = PROJECT_ROOT / "data" / "raw_chats"
    if not raw_chats_dir.is_dir():
        print(f"Directory not found: {raw_chats_dir}", file=sys.stderr)
        sys.exit(1)

    files_to_process = get_chat_files_to_process(raw_chats_dir, app_mode)
    if not files_to_process:
        print("No files to process.", file=sys.stderr)
        sys.exit(0)

    print(f"APP_MODE: {app_mode}")
    print(f"Found {len(files_to_process)} file(s) to process:")
    for f in files_to_process:
        print(f"  - {f.name}")

    # Database setup
    try:
        conn = get_db_connection()
        init_db(conn)  # Ensure tables exist
    except Exception as e:
        print(f"Failed to initialize database: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        # Process each file
        for file_path in files_to_process:
            print(f"Processing {file_path.name}...")
            process_chat_file(file_path, conn)

        # Recompute market statistics
        print("Recomputing market statistics...")
        updated_rows = recompute_market_stats(conn)
        print(f"Updated {updated_rows} rows.")

        # Generate and print market report
        print("\nMarket Report:")
        generate_market_report()

    finally:
        conn.close()


if __name__ == "__main__":
    main()
