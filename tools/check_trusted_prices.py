#!/usr/bin/env python3
"""
Tool to compare system-generated market prices with trusted price data.
Compares prices from the database with data/trusted_prices.csv.
Outputs a validation report showing match percentage and discrepancies.
"""
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

# Add the project root to the path so we can import data.db
sys.path.insert(0, str(Path(__file__).parent.parent))

from data.db import get_db_connection


def load_trusted_prices(file_path: Path) -> Dict[Tuple[str, float, str], int]:
    """
    Load trusted prices from CSV file.
    Expected format: block_code,size_marla,side,price_pkr
    Returns dict with key (block_code, size_marla, side) -> price_pkr
    """
    trusted_prices = {}
    if not file_path.exists():
        print(f"Warning: Trusted prices file {file_path} not found")
        return trusted_prices
    
    with file_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                block_code = row["block_code"].strip().upper()
                size_marla = float(row["size_marla"])
                side = row["side"].strip().upper()
                price_pkr = int(float(row["price_pkr"]))  # Handle potential float values
                trusted_prices[(block_code, size_marla, side)] = price_pkr
            except (KeyError, ValueError) as e:
                print(f"Warning: Skipping invalid row in trusted prices: {row}, error: {e}")
                continue
    return trusted_prices


def load_system_prices(conn) -> Dict[Tuple[str, float, str], List[int]]:
    """
    Load prices from the system's market_stats table.
    Returns dict with key (block_code, size_marla, side) -> list of prices (min, median, max)
    """
    system_prices = {}
    cursor = conn.execute(
        """
        SELECT block_code, size_marla, side, min_price_pkr, median_price_pkr, max_price_pkr
        FROM market_stats
        """
    )
    for row in cursor.fetchall():
        try:
            block_code = row["block_code"].strip().upper()
            size_marla = float(row["size_marla"])
            side = row["side"].strip().upper()
            key = (block_code, size_marla, side)
            system_prices[key] = [
                int(row["min_price_pkr"]) if row["min_price_pkr"] is not None else 0,
                int(row["median_price_pkr"]) if row["median_price_pkr"] is not None else 0,
                int(row["max_price_pkr"]) if row["max_price_pkr"] is not None else 0
            ]
        except (ValueError, TypeError) as e:
            print(f"Warning: Skipping invalid row in market_stats: {row}, error: {e}")
            continue
    return system_prices


def compare_prices(
    trusted: Dict[Tuple[str, float, str], int],
    system: Dict[Tuple[str, float, str], List[int]]
) -> Tuple[
    int,  # total trusted entries
    int,  # matches found
    List[Tuple],  # mismatches details
    List[Tuple]   # missing in system
]:
    """Compare trusted prices with system prices."""
    total_trusted = len(trusted)
    matches = 0
    mismatches = []
    missing_in_system = []
    
    for key, trusted_price in trusted.items():
        if key not in system:
            missing_in_system.append((key, trusted_price, None))
            continue
        
        system_prices = system[key]
        # Check if trusted price matches any of the system prices (min, median, max)
        # or falls within the range
        min_price, median_price, max_price = system_prices
        
        # Consider it a match if:
        # 1. Exact match with any of the three values, OR
        # 2. Trusted price falls within the min-max range
        if (trusted_price in system_prices or 
            (min_price <= trusted_price <= max_price)):
            matches += 1
        else:
            mismatches.append((key, trusted_price, system_prices))
    
    return total_trusted, matches, mismatches, missing_in_system


def main():
    """Main function to run the price validation."""
    # Set up paths
    base_dir = Path(__file__).parent.parent
    trusted_prices_path = base_dir / "data" / "trusted_prices.csv"
    
    # Load trusted prices
    print(f"Loading trusted prices from {trusted_prices_path}...")
    trusted_prices = load_trusted_prices(trusted_prices_path)
    
    if not trusted_prices:
        print("Error: No trusted prices loaded. Please check the file format and content.")
        sys.exit(1)
    
    print(f"Loaded {len(trusted_prices)} trusted price entries.")
    
    # Load system prices from database
    print("Loading system prices from database...")
    conn = get_db_connection()
    try:
        system_prices = load_system_prices(conn)
        print(f"Loaded {len(system_prices)} system price entries.")
    finally:
        conn.close()
    
    # Compare prices
    print("Comparing prices...")
    total_trusted, matches, mismatches, missing_in_system = compare_prices(
        trusted_prices, system_prices
    )
    
    # Calculate match percentage
    match_percentage = (matches / total_trusted * 100) if total_trusted > 0 else 0
    
    # Print report
    print("\n" + "="*60)
    print("TRUSTED PRICE VALIDATION REPORT")
    print("="*60)
    print(f"Total trusted price entries: {total_trusted}")
    print(f"Entries found in system: {len(system_prices)}")
    print(f"Matching entries: {matches}")
    print(f"Match percentage: {match_percentage:.2f}%")
    
    if missing_in_system:
        print(f"\nEntries missing in system ({len(missing_in_system)}):")
        for (block, size, side), trusted_price, _ in missing_in_system[:10]:  # Show first 10
            print(f"  {block} {size} Marla {side}: {trusted_price:,} PKR")
        if len(missing_in_system) > 10:
            print(f"  ... and {len(missing_in_system) - 10} more")
    
    if mismatches:
        print(f"\n\nPrice mismatches ({len(mismatches)}):")
        for (block, size, side), trusted_price, (min_p, med_p, max_p) in mismatches[:10]:  # Show first 10
            print(f"  {block} {size} Marla {side}:")
            print(f"    Trusted: {trusted_price:,} PKR")
            print(f"    System range: {min_p:,} - {med_p:,} - {max_p:,} PKR")
        if len(mismatches) > 10:
            print(f"  ... and {len(mismatches) - 10} more")
    
    # Determine if validation passes
    validation_passes = match_percentage >= 95.0
    print("\n" + "="*60)
    if validation_passes:
        print("✅ VALIDATION PASSED (match percentage >= 95%)")
    else:
        print("❌ VALIDATION FAILED (match percentage < 95%)")
    print("="*60)
    
    # Exit with appropriate code
    sys.exit(0 if validation_passes else 1)


if __name__ == "__main__":
    main()
