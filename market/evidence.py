"""M7 - the matching-listings / evidence layer.

What this module is
-------------------
M1-M6 moved the product from "here are aggregated facts" to "here are
**facts**, and every number in the reply is traceable to the approved
master". M7 adds the missing half: the **evidence behind the facts**.

The operator can now ask *"which listings produced that median?"* and
get the actual matching rows - each with its block, size, verified
price, observation count, date and a matching reason - without ever
seeing a dealer's raw chat text, a sender identity, a plot owner or a
private note.

The layer is deliberately a **read-only, whitelisted projection** of the
approved master. It is not a second lookup, and it is not a new
authority: the scope rule, the answer threshold and the block aliases
all come from ``market/price_lookup.py``, so the evidence can never
disagree with the answer it explains.

Why a whitelist and not a filter
--------------------------------
The master row carries fourteen fields. Six of them are the evidence an
operator legitimately needs. The other eight are the reason a plain
"SELECT *" would be a privacy defect:

  * ``source_chats``  - a dealer organisation's name. The master holds
    only two distinct chat names, but a name is a name, and
    ``config/policies.json`` sets ``allow_sender_names: false``;
  * ``notes``         - free text lifted from a dealer's chat. 180 of
    the 339 in-scope rows carry one, and it contains phrases like
    "Direct owner" and "front open cash offer required" - dealer
    negotiation content;
  * ``plot_number``   - a plot identifier. It is the ONE field the
    operator layer is allowed to show, and only when the operator is
    authorised (see :func:`build_listing_evidence` and the
    ``include_plot_number`` argument);
  * ``size_raw``      - the raw dimension string ("30*60"). Useful, but
    it is a *string* the master stored, and the normalised
    ``size_marla`` is the fact the application computes from it.

So the layer has a **field whitelist**, not a blacklist: it builds each
output row from named fields only, and it can never pass through a
field it did not name. Adding a field to the master cannot leak it
here.

The plot identifier
-------------------
``plot_number`` is the only field that identifies a specific property,
and the handoff treats it as operator-only (handoff v2 section 7.6,
D-09). The layer therefore serves it **only** when the caller says the
operator is authorised for it, and the response records which mode it
served:

  * ``redacted``  - the default. The row carries an opaque, stable
    ``listing_ref`` derived from the row's own block and plot key, so
    the operator can still correlate two views of the same row without
    the identifier ever leaving the data layer;
  * ``identified`` - the operator is authorised. The real
    ``plot_number`` is served and ``plot_number_redacted`` is ``False``.

The redaction is **not** a security boundary against the master - the
master is an approved file on this machine. It is a **surface**
boundary: the value does not travel through the API, the console or
the audit trail unless authorisation was asserted. That is the same
distinction the customer-facing path makes between a fact and a raw
chat.

The module is stdlib-only (RULES_SHORT #5), reads the approved master
**read-only**, writes nothing, and never calls a model.
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Sequence, Tuple

from market.fh_query import (
    MASTER_PATH,
    load_inventory,
    query_inventory,
    summarize_matches,
)
from market import price_lookup

__all__ = [
    "LISTING_FIELDS",
    "EvidenceError",
    "build_listing_evidence",
    "evidence_for_cell",
    "listing_ref",
    "matching_reason",
    "matching_rows",
]


class EvidenceError(ValueError):
    """Raised when an evidence request cannot be served safely.

    The caller must treat this as a refusal, never as a reason to
    serve an unfiltered row set.
    """


_BASE26_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def base26(value: int) -> str:
    """Render a non-negative integer using LETTERS ONLY.

    Used only to render an opaque identifier without digits, so the
    identifier cannot be mistaken for a market figure by the numeric
    guard - or by a human.
    """
    if value < 0:
        raise ValueError("base26 requires a non-negative integer")
    if value == 0:
        return _BASE26_ALPHABET[0]
    digits: List[str] = []
    while value:
        value, remainder = divmod(value, 26)
        digits.append(_BASE26_ALPHABET[remainder])
    return "".join(reversed(digits))


# ---------------------------------------------------------------------------
# The whitelist
# ---------------------------------------------------------------------------

# The ONLY master fields that may leave the controlled data layer, and
# the ONLY facts the evidence row may carry. This tuple is the boundary:
# a field that is not named here cannot reach the API, the console or
# the audit trail, and adding a field to the master cannot leak it.
#
# ``source_chats``, ``notes`` and ``size_raw`` are deliberately absent.
LISTING_FIELDS: Tuple[str, ...] = (
    "block",
    "size_marla",
    "price_min_pkr",
    "price_median_pkr",
    "price_max_pkr",
    "price_latest_pkr",
    "latest_date",
    "observation_count",
    "corner",
    "sun_facing",
    "ndc_open",
)

# The master fields that are NEVER served, with the reason. The test
# suite asserts this list stays in step with the master, so a new
# master field cannot be added without a decision about it.
EXCLUDED_FIELDS: Dict[str, str] = {
    "source_chats": "dealer organisation names (privacy_policy.allow_sender_names)",
    "notes": "free text lifted from a dealer chat (privacy_policy.allow_raw_text)",
    "plot_number": "served only in the authorised 'identified' mode",
    "size_raw": "a raw string; the application computes size_marla from it",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _boolean(value: Any) -> Optional[bool]:
    """Normalise a master feature value to a real boolean.

    The query engine (``market/fh_query.py``) already normalises these
    for FILTERING, and the evidence layer must normalise them the same
    way for DISPLAY. Otherwise the layer would serve a feature as the
    raw string the master happens to hold - and the approved master
    holds the string ``"True"`` when it is derived from the in-repo
    CSV (which is what CI uses), while the JSONL master holds a real
    boolean. The two masters must produce the same evidence, so the
    same normalisation is used.

    The rule is the query engine's rule, and it is not re-implemented
    here: it is imported, so the two cannot drift.
    """
    from market.fh_query import _boolean as _query_boolean

    return _query_boolean(value)


def _iso_date(value: Any) -> Optional[str]:
    """The master's date in ISO form, or None.

    The master stores dates in two shapes ("9/26/26" and "2026-10-07").
    The lookup already normalises them; the evidence layer uses the
    same rule so a date in the evidence and a date in the answer can
    never disagree.
    """
    from datetime import datetime

    if value is None or value == "":
        return None
    text = str(value).strip()
    for fmt in ("%m/%d/%y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def listing_ref(row: Dict[str, Any]) -> str:
    """A stable, opaque reference for one master row.

    It is derived from the row's own block and plot key, so the same
    row always gets the same reference, and two different rows get
    different ones. It is **not** reversible to the plot number by a
    reader - it is a digest, not an encoding - but it lets an operator
    correlate the evidence with the other views of the same data.

    The digest is rendered in LETTERS ONLY, so the reference carries
    **no digits**. That matters: a reference is an identifier, not a
    fact, and a digit inside one would be read by the numeric guard as
    an untraceable number on a serving surface. An identifier must not
    look like a figure.
    """
    block = str(row.get("block") or "").strip().upper()
    key = str(row.get("plot_number") or "").strip()
    digest = hashlib.sha256(
        ("%s|%s" % (block, key)).encode("utf-8")
    ).digest()
    encoded = base26(int.from_bytes(digest, "big")).rjust(12, "A")
    return "L%s" % encoded[-12:]


def matching_reason(
    row: Dict[str, Any],
    filters: Dict[str, Any],
) -> List[str]:
    """Why this row matched the query.

    Each entry names one filter the row satisfied, in the operator's
    language. The reason is derived from the query and the row, never
    from the master, so it cannot carry an unsupported claim.
    """
    reasons: List[str] = []

    requested_block = filters.get("block")
    if requested_block:
        row_block = price_lookup.canonical_block(row.get("block"))
        if row_block == str(requested_block).strip().upper():
            reasons.append("block %s" % row_block)

    requested_size = _number(filters.get("size_marla"))
    if requested_size is not None:
        row_size = _number(row.get("size_marla"))
        if row_size is not None and abs(row_size - requested_size) <= 0.001:
            reasons.append("%g marla" % row_size)

    for field, label in (
        ("corner", "corner plot"),
        ("sun_facing", "sun facing"),
        ("ndc_open", "NDC open"),
    ):
        wanted = filters.get(field)
        if wanted is None:
            continue
        actual = _boolean(row.get(field))
        if actual is not None and actual == bool(wanted):
            reasons.append(label)

    if not reasons:
        reasons.append("matched the approved master cell")

    return reasons


# ---------------------------------------------------------------------------
# The evidence row
# ---------------------------------------------------------------------------


def _evidence_row(
    row: Dict[str, Any],
    filters: Dict[str, Any],
    identify: bool,
) -> Dict[str, Any]:
    """One whitelisted evidence row.

    The row is BUILT field by field from ``LISTING_FIELDS``. It is
    never a copy of the master row with fields removed - a copy would
    make a future master field leak the moment someone forgot to
    filter it.
    """
    evidence: Dict[str, Any] = {
        "listing_ref": listing_ref(row),
        "block": price_lookup.canonical_block(row.get("block")),
        "size_marla": _number(row.get("size_marla")),
        "price_min_pkr": _number(row.get("price_min_pkr")),
        "price_median_pkr": _number(row.get("price_median_pkr")),
        "price_max_pkr": _number(row.get("price_max_pkr")),
        "price_latest_pkr": _number(row.get("price_latest_pkr")),
        "latest_date": _iso_date(row.get("latest_date")),
        "observation_count": int(_number(row.get("observation_count")) or 0),
        "corner": _boolean(row.get("corner")),
        "sun_facing": _boolean(row.get("sun_facing")),
        "ndc_open": _boolean(row.get("ndc_open")),
        "matching_reason": matching_reason(row, filters),
    }

    # The plot identifier is the ONE conditional field. It is served only
    # when the caller asserts the operator is authorised for it, and the
    # response always records which mode was used.
    plot_number = row.get("plot_number")
    if identify:
        evidence["plot_number"] = plot_number
        evidence["plot_number_redacted"] = False
    else:
        evidence["plot_number"] = None
        evidence["plot_number_redacted"] = True

    return evidence


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def build_listing_evidence(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    include_plot_number: bool = False,
    limit: Optional[int] = None,
    policies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the matching-listings evidence for a query.

    The scope rule, the block aliases and the answer threshold all come
    from ``market/price_lookup.py`` and ``config/policies.json``, so the
    evidence and the answer it explains can never disagree.

    Args:
        block: the requested block. A block outside the active scope is
            refused **before** any row is counted.
        size_marla: the requested size.
        corner / sun_facing / ndc_open: the requested features.
        include_plot_number: whether the operator is authorised for the
            plot identifier. ``False`` (the default) serves the
            redacted form.
        limit: the maximum number of listings to return. The counts
            always describe the WHOLE cell, so a limited view can never
            be mistaken for the cell's full size.
        policies: the policy configuration, for tests.

    Returns:
        A dict with the shape::

            {
              "listings": [...],       # the whitelisted evidence rows
              "summary": {...},        # the cell's counts and coverage
              "filters": {...},        # the query as it was applied
              "answerable": bool,      # does the cell clear the threshold
              "cell": {...},           # the block/size cell that was used
              "evidence_source": str,  # the provenance string
              "plot_number_mode": "redacted" | "identified",
              "excluded_fields": [...],  # what the layer refused to serve
              "total_matched": int,    # before the limit
              "returned": int,         # after the limit
              "limited": bool,
            }

    Raises:
        EvidenceError: when the request is out of scope.
    """
    config = policies if policies is not None else price_lookup.load_policies()

    active_blocks = list(config.get("active_blocks", ["A", "B", "C"]))
    min_listings = int(config.get("min_listings_for_answer", 3))

    scope = price_lookup.classify_block(block, config)
    if scope["status"] == "out_of_scope":
        raise EvidenceError(
            "Block %s is outside the active scope (%s)."
            % (block, ", ".join(active_blocks))
        )

    filters: Dict[str, Any] = {
        "block": scope["block"] if scope["status"] == "active" else None,
        "size_marla": _number(size_marla),
        "corner": corner,
        "sun_facing": sun_facing,
        "ndc_open": ndc_open,
    }

    # The same scoped inventory the lookup uses - one authority for
    # "which rows are in scope".
    inventory = price_lookup._active_scope_inventory(active_blocks)
    rows = query_inventory(inventory=inventory, **filters)

    summary = summarize_matches(rows)
    priced = [
        row for row in rows
        if _number(row.get("price_median_pkr")) is not None
    ]
    answerable = bool(
        len(rows) >= min_listings and summary.get("price_median_pkr") is not None
    )

    ordered = sorted(
        rows,
        key=lambda row: (
            price_lookup.canonical_block(row.get("block")) or "",
            _number(row.get("size_marla")) or 0,
            listing_ref(row),
        ),
    )

    total = len(ordered)
    limited = False
    if limit is not None and limit >= 0 and total > limit:
        ordered = ordered[:limit]
        limited = True

    listings = [
        _evidence_row(row, filters, include_plot_number)
        for row in ordered
    ]

    return {
        "listings": listings,
        "summary": {
            "matched_plots": int(summary.get("matched_plots", 0)),
            "observation_count": int(summary.get("observation_count", 0)),
            "priced_plots": len(priced),
            "price_min_pkr": summary.get("price_min_pkr"),
            "price_median_pkr": summary.get("price_median_pkr"),
            "price_max_pkr": summary.get("price_max_pkr"),
            "latest_date": summary.get("latest_date"),
            "coverage_level": summary.get("coverage_level"),
            "trust_status": summary.get("trust_status"),
            "answerable_for_demo": answerable,
        },
        "filters": dict(filters),
        "answerable": answerable,
        "min_listings_for_answer": min_listings,
        "cell": {
            "block": filters.get("block"),
            "size_marla": filters.get("size_marla"),
        },
        "evidence_source": "FaisalHills verified partial master (read-only)",
        "price_basis": "dealer asking prices",
        "is_sold_price": False,
        "plot_number_mode": "identified" if include_plot_number else "redacted",
        "excluded_fields": sorted(EXCLUDED_FIELDS),
        "total_matched": total,
        "returned": len(listings),
        "limited": limited,
    }


def matching_rows(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    policies: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """The raw master rows a query matches, in scope.

    This is the function the surface guard uses to re-derive the
    row-level permitted numbers. It returns the master rows
    themselves - the guard reads the prices and dates from them and
    compares them against what was served. The rows never leave this
    module's callers; only the guard uses them.
    """
    config = policies if policies is not None else price_lookup.load_policies()
    active_blocks = list(config.get("active_blocks", ["A", "B", "C"]))

    scope = price_lookup.classify_block(block, config)
    if scope["status"] == "out_of_scope":
        return []

    filters: Dict[str, Any] = {
        "block": scope["block"] if scope["status"] == "active" else None,
        "size_marla": _number(size_marla),
        "corner": corner,
        "sun_facing": sun_facing,
        "ndc_open": ndc_open,
    }

    inventory = price_lookup._active_scope_inventory(active_blocks)
    return list(query_inventory(inventory=inventory, **filters))


def evidence_for_cell(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """The evidence for one cell - the shape the operator panel uses.

    A thin cell is served with its rows and no price, exactly like the
    customer-facing path: the operator can see WHY the product refused
    to answer, and no price is shown for a cell the product will not
    quote.
    """
    evidence = build_listing_evidence(block=block, size_marla=size_marla, **kwargs)

    if not evidence["answerable"]:
        for listing in evidence["listings"]:
            for key in (
                "price_min_pkr",
                "price_median_pkr",
                "price_max_pkr",
                "price_latest_pkr",
            ):
                listing[key] = None
        evidence["summary"]["price_min_pkr"] = None
        evidence["summary"]["price_median_pkr"] = None
        evidence["summary"]["price_max_pkr"] = None

    return evidence
