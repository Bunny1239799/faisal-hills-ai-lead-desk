"""Independent adversarial probe for the M6.1 claim guard.

This is NOT a test module - it is a scratch probe used to hunt for holes
in `market/reply_guard.py` from the outside. It deliberately uses attack
patterns that are NOT in tests/test_m6_1_reply_guard.py, so that a
"the suite passes" result is not mistaken for "the guard is sound".

Every case asserts: the guard must REFUSE the reply. A case that the
guard accepts is a HOLE, printed as such.
"""
from __future__ import annotations

import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from market import reply_guard  # noqa: E402

APPROVED = reply_guard.APPROVED_SOURCE

ANSWERABLE_FACTS = {
    "answerable_for_demo": True,
    "facts_source": APPROVED,
    "reply_mode": "verified_market_facts",
    "block": "C",
    "size_marla": 7,
    "price_min": 60000000,
    "price_median": 65000000,
    "price_max": 70000000,
    "n": 4,
}

# The answerable reply, correctly marked. Used as the base for mutations.
GOOD = (
    "Yes. In Block C, 7 marla plots are listed with asking prices between "
    "PKR 6,000,000 and PKR 7,000,000 (median PKR 6,500,000) from 4 "
    "observations. These are asking prices, not confirmed sold prices. "
    "Human approval is required before sending."
)

# --------------------------------------------------------------------
# Attack cases: each is a reply that asserts something the approved
# master does NOT support. The guard must refuse every one.
# --------------------------------------------------------------------
ATTACKS = [
    # -- scope violations that carry no number ------------------------
    ("scope/executive",
     "Yes. Block C 7 marla asking prices are 6,000,000-7,000,000. "
     "Executive Block also has 5 marla plots. Asking prices, not confirmed "
     "sold prices. Human approval is required."),
    ("scope/blockD",
     "We also have plots in Block D. Asking prices, not confirmed sold "
     "prices. Human approval is required."),
    ("scope/fhc-d",
     "FHD 7 marla asking prices are 6,000,000 to 7,000,000. Asking prices, "
     "not confirmed sold prices. Human approval is required."),

    # -- unsupported sizes riding on permitted numbers -----------------
    ("size/10-marla",
     "Based on the data, we also have 10 marla plots in Block C. Asking "
     "prices, not confirmed sold prices. Human approval is required."),
    ("size/14-marla",
     "We have 14 marla plots in Block C. Asking prices, not confirmed sold "
     "prices. Human approval is required."),
    ("size/kanal",
     "We have 1 kanal plots in Block C. Asking prices, not confirmed sold "
     "prices. Human approval is required."),

    # -- unsupported (block, size) pairs -------------------------------
    ("pair/A-7",
     "Block A 7 marla asking prices run 4,000,000 to 5,000,000. Asking "
     "prices, not confirmed sold prices. Human approval is required."),

    # -- availability / stock claims -----------------------------------
    ("stock/available",
     "Yes, 7 marla plots are available in Block C at asking prices between "
     "6,000,000 and 7,000,000. Asking prices, not confirmed sold prices. "
     "Human approval is required."),
    ("stock/for-sale",
     "7 marla plots in Block C are for sale at asking prices of 6,000,000 "
     "to 7,000,000. Asking prices, not confirmed sold prices. Human approval "
     "is required."),
    ("stock/we-have",
     "We have 7 marla plots in Block C. Asking prices, not confirmed sold "
     "prices. Human approval is required."),
    ("stock/there-are",
     "There are 7 marla plots in Block C. Asking prices, not confirmed sold "
     "prices. Human approval is required."),

    # -- certainty ------------------------------------------------------
    ("certainty/guaranteed",
     "7 marla plots in Block C are guaranteed at 6,000,000 asking prices. "
     "Asking prices, not confirmed sold prices. Human approval is required."),
    ("certainty/100pct",
     "7 marla plots in Block C are 100% available at 6,000,000. Asking "
     "prices, not confirmed sold prices. Human approval is required."),
    ("certainty/we-can-confirm",
     "We can confirm 7 marla plots in Block C at 6,000,000. Asking prices, "
     "not confirmed sold prices. Human approval is required."),

    # -- sold-price claims ----------------------------------------------
    ("sold/confirmed-sold",
     "7 marla plots in Block C have a confirmed sold price of 6,000,000. "
     "Asking prices, not confirmed sold prices. Human approval is required."),
    ("sold/deal-price",
     "The deal price for 7 marla in Block C is 6,000,000. Asking prices, "
     "not confirmed sold prices. Human approval is required."),

    # -- provenance loss -------------------------------------------------
    ("prov/drop-asking",
     "Yes. 7 marla plots in Block C are between 6,000,000 and 7,000,000. "
     "Not confirmed sold prices. Human approval is required."),
    ("prov/drop-not-sold",
     "Yes. 7 marla plots in Block C have asking prices of 6,000,000 to "
     "7,000,000. Human approval is required."),
    ("prov/drop-approval",
     "Yes. 7 marla plots in Block C have asking prices of 6,000,000 to "
     "7,000,000. These are not confirmed sold prices."),
]


def main() -> int:
    holes = []
    for name, reply in ATTACKS:
        report = reply_guard.guard_reply(
            reply,
            ANSWERABLE_FACTS,
            filters={"block": "C", "size_marla": 7},
            context={"size_marla": 7},
            action="answer",
            reply_mode="verified_market_facts",
        )
        if report.ok:
            holes.append((name, reply, [v["code"] for v in report.violations]))
            print("HOLE   %-24s accepted" % name)
        else:
            print("ok     %-24s blocked %s" % (
                name, sorted({v["code"] for v in report.violations})))

    # -- the good reply must still pass (no false positive) -------------
    report = reply_guard.guard_reply(
        GOOD,
        ANSWERABLE_FACTS,
        filters={"block": "C", "size_marla": 7},
        context={"size_marla": 7},
        action="answer",
        reply_mode="verified_market_facts",
    )
    print("good   %-24s %s" % ("answerable-reply", "accepted" if report.ok
                               else "BLOCKED %s" % report.violations))
    if not report.ok:
        holes.append(("false-positive/good-reply", GOOD, []))

    print("\nHOLES: %d" % len(holes))
    for name, reply, codes in holes:
        print("  - %s %s" % (name, codes))
    return 1 if holes else 0


if __name__ == "__main__":
    raise SystemExit(main())
