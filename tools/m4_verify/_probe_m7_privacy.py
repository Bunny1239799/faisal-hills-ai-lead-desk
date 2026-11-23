"""Independent privacy + parity probe for the M7 evidence layer.

Measures, from the outside:
  1. does ANY raw dealer content (notes, dealer names, raw size strings,
     plot numbers) reach the evidence payload?
  2. does the evidence layer agree with the lookup it reads (no drift)?
  3. is a parked block refused before any row is counted?

Run:  python tools/m4_verify/_probe_m7_privacy.py
"""
from __future__ import annotations

import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from market import evidence as ev  # noqa: E402
from market import price_lookup  # noqa: E402
from market.fh_query import MASTER_PATH, load_inventory  # noqa: E402

CELLS = [
    ("A", 5), ("A", 7), ("A", 10), ("A", 14), ("A", 20), ("A", 40),
    ("B", 5), ("B", 7), ("B", 10), ("B", 14), ("B", 20),
    ("C", 5), ("C", 7), ("C", 10), ("C", 20),
]

failures = []


def main() -> int:
    rows = load_inventory(MASTER_PATH)
    print("master rows: %d" % len(rows))

    # Collect the raw dealer content that must NEVER leave.
    raw_notes = set()
    raw_dealers = set()
    raw_sizes = set()
    plot_numbers = set()
    for row in rows:
        note = (row.get("notes") or "").strip()
        if note:
            raw_notes.add(note)
        dealer = row.get("source_chats") or ""
        if isinstance(dealer, (list, tuple, set)):
            for item in dealer:
                text = str(item or "").strip()
                if text:
                    raw_dealers.add(text)
        else:
            text = str(dealer or "").strip()
            if text:
                raw_dealers.add(text)
        raw = (row.get("size_raw") or "").strip()
        if raw:
            raw_sizes.add(raw)
        pn = (row.get("plot_number") or "").strip()
        if pn:
            plot_numbers.add(pn)

    print("raw notes: %d  dealers: %d  raw sizes: %d  plot numbers: %d"
          % (len(raw_notes), len(raw_dealers), len(raw_sizes),
             len(plot_numbers)))

    total_listings = 0
    leaked = set()

    for block, size in CELLS:
        payload = ev.evidence_for_cell(block=block, size_marla=size)
        blob = json.dumps(payload, default=str)

        for note in raw_notes:
            # A one-word note ("asking") is a substring of the product's
            # own vocabulary, not a leak. Only a substantive note counts.
            if note and len(note) >= 12 and note in blob:
                leaked.add(("note", note))
        for dealer in raw_dealers:
            if dealer and dealer in blob:
                leaked.add(("dealer", dealer))
        for raw in raw_sizes:
            if raw and raw in blob:
                leaked.add(("size_raw", raw))

        listings = payload.get("listings") or []
        total_listings += len(listings)
        for item in listings:
            pn = item.get("plot_number")
            if pn:
                failures.append(
                    "%s/%s leaks a real plot_number in the redacted payload"
                    % (block, size))
            for banned in ("notes", "source_chats", "size_raw"):
                if banned in item:
                    failures.append(
                        "%s/%s leaks the raw master field %s"
                        % (block, size, banned))

        # -- parity with the lookup -----------------------------------
        result = price_lookup.lookup_price(block=block, size_marla=size)
        summary = result.get("summary") or {}
        ev_summary = payload.get("summary") or {}
        for key in ("observation_count", "price_min_pkr", "price_median_pkr",
                    "price_max_pkr"):
            lk = summary.get(key)
            evv = ev_summary.get(key)
            if lk is None and evv is None:
                continue
            if lk is None or evv is None:
                failures.append("%s/%s %s present in only one layer"
                                % (block, size, key))
            elif abs(float(lk) - float(evv)) > 0.01:
                failures.append("%s/%s %s drift: lookup=%s evidence=%s"
                                % (block, size, key, lk, evv))

    print("listings served: %d" % total_listings)

    # -- the identified mode is the only place a plot number may appear -
    ident = ev.evidence_for_cell(block="C", size_marla=7,
                                 include_plot_number=True)
    ident_blob = json.dumps(ident, default=str)
    ident_has = any(pn and pn in ident_blob for pn in plot_numbers)
    print("identified mode exposes a plot number: %s" % ident_has)
    if not ident_has:
        failures.append("the identified mode exposes no plot number")

    # -- a parked block must be refused before any row is counted ------
    try:
        ev.evidence_for_cell(block="D", size_marla=10)
        failures.append("a parked block was NOT refused")
        print("parked block: NOT refused (FAIL)")
    except ev.EvidenceError:
        print("parked block: refused (ok)")

    print("\nleaked raw values: %d" % len(leaked))
    for kind, value in sorted(leaked)[:10]:
        print("  - %s: %r" % (kind, value))
    print("failures: %d" % len(failures))
    for f in failures:
        print("  - %s" % f)
    return 1 if (leaked or failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
