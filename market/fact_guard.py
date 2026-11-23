"""M5 (D-32) - the surface guard for every customer/operator numeric field.

Why this module exists
----------------------
M5 task 1 added `market/fact_validator.py` and enforced it in
`app/pipeline.py` **for the customer-facing reply**. That closed D-31.
D-32 is the rest of the same control: the console also serves factual
numbers through `/api/lookup`, `/api/market`, `/api/questions` and
`/api/audit`, and the pipeline serves the raw fact set through
`/api/message`. None of those were guarded.

The instruction that governs this work is: *"Do not let unvalidated
factual numbers reach the UI or API response."* A template reply is
currently safe **by construction** - the placeholders are filled from the
lookup result - but that is an assumption about the code, not a control.
The next person who adds a derived figure (a per-marla price, a
percentile, a growth rate) to any of those payloads would ship it
unvalidated. This module makes the control explicit and mechanical.

How the guard is independent (and therefore meaningful)
--------------------------------------------------------
A guard that validates a payload against the payload's own sibling values
proves nothing. So the permitted numbers are **re-derived from the
approved master**, not read out of the served payload:

* the *rows* come from the read-only approved master
  (`market.fh_query.load_inventory`), restricted to the configured active
  scope (`config/policies.json` -> `active_blocks`);
* the *numbers* come from the proven query engine applied to those rows -
  the same engine the lookup uses, so the two cannot disagree about what
  the master says, but the **payload's own claims are never trusted**;
* the *rules* (the active scope, the answer threshold) come from the
  policy configuration, not from the payload.

The guard is therefore a check on the **served** numbers, not a restating
of them: a tampered `price_median_pkr`, a derived figure the master does
not support, a stale expectation in the hand-checked question set, and a
recorded reply that no longer matches the master are all detectable.

Two rules that are stronger than plain traceability
---------------------------------------------------
1. **No price for a thin cell.** Handoff v2 section 7.4 and FH-02 R17:
   below the threshold the system says "not enough data" and shows the
   closest match *instead of a number*. The guard therefore refuses the
   price figures of a non-answerable cell - and of its closest-match
   cell - so a leaked median is caught rather than tolerated.
2. **Unknown stays unknown.** A fact that is `None` contributes nothing
   to the permitted set, and a cell with no rows permits only the zero
   counts the empty summary carries.

Blocking behaviour is identical on every surface:

* the offending numbers are **not** echoed back (a count and a reason are
  reported instead - re-publishing a number the guard just refused to
  serve would defeat the control);
* the numbers are removed from the response (the reply is replaced with
  the hold wording, the fact set is detached, the row is emptied);
* the customer-facing path escalates to a human, exactly as the pipeline
   already does for an untraceable reply (RULES_SHORT #3).

The module is stdlib-only and side-effect free: no network, no model, no
writes, and the master is only ever **read** (RULES_SHORT #1, #5).
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from market import fact_validator
from market.fh_query import (
    MASTER_PATH,
    load_inventory,
    query_inventory,
    summarize_matches,
)

__all__ = [
    "APPROVED_SOURCE",
    "HOLD_REPLY",
    "approved_cell",
    "allowed_numbers_for",
    "closest_cell",
    "guard_payload",
    "guard_text",
    "public_report",
    "blocked_lookup_payload",
    "blocked_market_row",
    "approved_numbers_from_rows",
    "approved_row_numbers",
]


# The provenance string the fact set carries. A constant, not a fact.
APPROVED_SOURCE = "FaisalHills verified partial master"

# The wording used when an answer is withheld. It is the wording the
# policy already uses for a "not enough data" answer and the wording the
# pipeline uses when it blocks an untraceable reply, so a blocked answer
# and a thin-data answer are indistinguishable to a customer - which is
# the intended outcome.
HOLD_REPLY = (
    "Thank you for your message. A member of our team will review it "
    "and reply personally."
)


# ---------------------------------------------------------------------------
# The approved master, read once per (file, mtime, size, scope)
# ---------------------------------------------------------------------------

_ROW_CACHE: Dict[str, Any] = {"key": None, "rows": []}


def _scoped_rows(policies: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The approved-master rows inside the configured active scope.

    The scope comes from `config/policies.json` (`active_blocks`) - a
    policy, not a fact - and the rows come from the read-only approved
    master. The block spellings are canonicalised with the project's ONE
    alias table (`market.price_lookup.canonical_block`), so the guard and
    the lookup can never disagree about *which* rows are in scope.
    """
    from market import price_lookup
    from market import fh_query as _fhq

    active_blocks = list(policies.get("active_blocks", []))
    # Stage 1: the cache key is the file that is ACTUALLY served - the
    # active workspace version when one exists, otherwise the configured
    # master. Keying on the configured path alone would let the guard
    # serve stale rows for one turn after a version change.
    try:
        served_path = _fhq._serving_path(_fhq.MASTER_PATH)
    except Exception:
        served_path = MASTER_PATH
    master_path = str(served_path)

    try:
        stat = os.stat(master_path)
        key = (master_path, stat.st_mtime_ns, stat.st_size, tuple(active_blocks))
    except OSError:
        key = None

    if _ROW_CACHE["key"] == key:
        return _ROW_CACHE["rows"]

    wanted = set()
    for configured in active_blocks:
        canonical = price_lookup.canonical_block(configured)
        if canonical:
            wanted.add(canonical)

    rows = [
        row
        for row in load_inventory(MASTER_PATH)
        if price_lookup.canonical_block(row.get("block")) in wanted
    ]

    _ROW_CACHE["key"] = key
    _ROW_CACHE["rows"] = rows
    return rows


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _percentile(sorted_values: Sequence[float], fraction: float) -> Optional[float]:
    """A p-th percentile, computed the way `data/db.py` computes one.

    The guard needs this so that a *future* reply which shows a p25/p75
    band (RULES_SHORT #4) can be verified rather than blocked. Nothing
    serves such a band today, so this is verifier capability, not a
    product feature.
    """
    if not sorted_values:
        return None
    k = (len(sorted_values) - 1) * fraction
    low = math.floor(k)
    high = math.ceil(k)
    if low == high:
        return float(sorted_values[int(k)])
    d0 = sorted_values[int(low)] * (high - k)
    d1 = sorted_values[int(high)] * (k - low)
    return float(round(d0 + d1))


# ---------------------------------------------------------------------------
# Re-deriving the approved facts for one cell
# ---------------------------------------------------------------------------


def approved_numbers_from_rows(rows: Sequence[Dict[str, Any]]) -> Set[float]:
    """Every number the approved master supports for a set of rows.

    Prices, the sample sizes, the observation date and the p25/p75 band.
    A `None` fact contributes nothing: unknown means unknown.
    """
    allowed: Set[float] = set()

    summary = summarize_matches(list(rows))
    for key in (
        "matched_plots",
        "observation_count",
        "distinct_source_chats",
        "price_min_pkr",
        "price_median_pkr",
        "price_max_pkr",
    ):
        value = summary.get(key)
        if value is None:
            continue
        allowed.add(float(value))

    allowed |= fact_validator._date_parts(summary.get("latest_date"))

    medians = sorted(
        value
        for value in (_number(row.get("price_median_pkr")) for row in rows)
        if value is not None
    )
    for fraction in (0.25, 0.75):
        value = _percentile(medians, fraction)
        if value is not None:
            allowed.add(value)

    return allowed


def approved_row_numbers(
    rows: Sequence[Dict[str, Any]],
) -> Set[float]:
    """Every number the approved master supports for a set of ROWS.

    M7: the evidence layer serves the matching listings, and each row
    carries its own price and its own date. Those are real approved
    facts - the same values the master holds - but they are not the
    cell's AGGREGATE figures, so the cell-level permitted set does not
    contain them.

    This function re-derives the permitted set for the row level from
    the same read-only master rows the evidence was built from. It
    therefore still proves the served value against the master, and it
    does not widen the surface: a row value that the master does not
    hold is still untraceable.

    A ``None`` value contributes nothing: unknown means unknown.
    """
    allowed: Set[float] = set()

    for row in rows:
        for key in (
            "price_min_pkr",
            "price_median_pkr",
            "price_max_pkr",
            "price_latest_pkr",
        ):
            value = _number(row.get(key))
            if value is not None:
                allowed.add(value)

        size = _number(row.get("size_marla"))
        if size is not None:
            allowed.add(size)

        observations = _number(row.get("observation_count"))
        if observations is not None:
            allowed.add(observations)

        allowed |= fact_validator._date_parts(row.get("latest_date"))

    return allowed


def approved_cell(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    policies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Re-derive the approved-master facts for one block/size cell.

    The result is produced by the proven query engine over the scoped
    rows of the read-only master. It deliberately does **not** go through
    `market.price_lookup.lookup_price`, because the guard has to be able
    to catch a served payload that the lookup itself got wrong.
    """
    from market import price_lookup

    config = policies if policies is not None else price_lookup.load_policies()
    rows = _scoped_rows(config)

    matches = query_inventory(
        inventory=rows,
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
    )
    summary = summarize_matches(matches)

    medians = sorted(
        value
        for value in (_number(row.get("price_median_pkr")) for row in matches)
        if value is not None
    )

    return {
        "facts_source": APPROVED_SOURCE,
        "facts_type": "dealer asking-price observations",
        "matched_plots": int(summary.get("matched_plots", 0)),
        "observation_count": int(summary.get("observation_count", 0)),
        "price_min_pkr": summary.get("price_min_pkr"),
        "price_median_pkr": summary.get("price_median_pkr"),
        "price_max_pkr": summary.get("price_max_pkr"),
        "price_p25_pkr": _percentile(medians, 0.25),
        "price_p75_pkr": _percentile(medians, 0.75),
        "latest_date": summary.get("latest_date"),
        "distinct_source_chats": int(summary.get("distinct_source_chats", 0)),
        "answerable_for_demo": bool(summary.get("answerable_for_demo", False)),
        "has_price": any(
            row.get("price_median_pkr") not in (None, "") for row in matches
        ),
        "priced_plots": sum(
            1
            for row in matches
            if row.get("price_median_pkr") not in (None, "")
        ),
    }


def closest_cell(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    policies: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Re-derive the closest alternative cell for a thin query.

    The ranking rule is the ONE implementation the lookup documents
    (`market.price_lookup.closest_match`). Calling it here - instead of
    re-implementing it - means there is a single ranking rule in the
    project, so the guard and the served payload cannot disagree about
    which cell is the closest one.

    The guard still does not *trust* the served payload: it recomputes the
    closest match and therefore detects a payload that names a different
    cell, a different size, a different sample size or a different size
    difference.
    """
    from market import price_lookup

    config = policies if policies is not None else price_lookup.load_policies()
    return price_lookup.closest_match(
        block=block,
        size_marla=size_marla,
        policies=config,
    )


def allowed_numbers_for(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    policies: Optional[Dict[str, Any]] = None,
    extra: Optional[Iterable[Any]] = None,
    rows: Optional[Sequence[Dict[str, Any]]] = None,
) -> Set[float]:
    """The set of numbers that may legitimately appear for one query.

    It contains:

    * the cell's own approved facts (prices, sample sizes, the
      observation date) - but **only when the cell is answerable**;
    * the size the customer asked about (their own figure, echoed back);
    * the answer threshold from the policy (a configuration constant, not
      a market fact);
    * for a thin query, the closest-match cell's size, listing count and
      size difference (handoff v2 section 7.4 / FH-02 R17).

    A thin query permits **no price at all** - not the requested cell's
    and not the closest-match cell's - because the product must not show
    a price for a query it has refused to answer.
    """
    from market import price_lookup

    config = policies if policies is not None else price_lookup.load_policies()
    threshold = config.get("min_listings_for_answer")

    allowed: Set[float] = set()

    # The customer's own figure.
    context: Dict[str, Any] = {}
    size_number = _number(size_marla)
    if size_number is not None:
        context["size_marla"] = size_number
        allowed.add(size_number)

    scope = price_lookup.classify_block(block, config)

    # A parked or unknown block is refused before any row is counted, and
    # the refusal summary carries only zeros.
    if scope["status"] == "out_of_scope":
        allowed.add(0.0)
        if threshold is not None:
            allowed.add(float(threshold))
        return allowed

    cell_block = scope["block"] if scope["status"] == "active" else None

    has_filters = size_number is not None or any(
        value is not None for value in (corner, sun_facing, ndc_open)
    )
    if not has_filters:
        # "no_lookup": the summary carries only zeros and the reply has
        # no number at all.
        allowed.add(0.0)
        if threshold is not None:
            allowed.add(float(threshold))
        return allowed

    cell = approved_cell(
        block=cell_block,
        size_marla=size_number,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
        policies=config,
    )

    counts = {
        "matched_plots": cell["matched_plots"],
        "observation_count": cell["observation_count"],
        "distinct_source_chats": cell["distinct_source_chats"],
    }

    if cell["answerable_for_demo"]:
        facts_for_whitelist = dict(cell)
    else:
        # A thin cell must not show a price - so no price is permitted.
        facts_for_whitelist = {
            "matched_plots": cell["matched_plots"],
            "observation_count": cell["observation_count"],
            "distinct_source_chats": cell["distinct_source_chats"],
            "priced_plots": cell["priced_plots"],
            "latest_date": cell["latest_date"],
        }

    allowed |= fact_validator.build_allowed_numbers(
        facts_for_whitelist, context=context
    )

    if not cell["answerable_for_demo"]:
        closest = closest_cell(
            block=cell_block,
            size_marla=size_number,
            policies=config,
        )
        if closest:
            closest_facts = approved_cell(
                block=closest.get("block"),
                size_marla=closest.get("size_marla"),
                policies=config,
            )
            closest_size = _number(closest.get("size_marla"))
            closest_context: Dict[str, Any] = {}
            if closest_size is not None:
                closest_context["size_marla"] = closest_size
            allowed |= fact_validator.build_allowed_numbers(
                {
                    "matched_plots": closest_facts["matched_plots"],
                    "observation_count": closest_facts["observation_count"],
                    "priced_plots": closest_facts["priced_plots"],
                },
                context=closest_context,
            )
            difference = closest.get("size_difference_marla")
            if difference is not None:
                allowed.add(float(difference))

    # The answer threshold is a POLICY constant, not a market fact. It
    # appears in the fact set and in the "not enough data" reason text
    # ("at least 3 are required"), so it has to be a permitted number -
    # but it is never presented as a market figure.
    if threshold is not None:
        allowed.add(float(threshold))

    if extra:
        for value in extra:
            number = _number(value)
            if number is not None:
                allowed.add(number)

    # M7: when the caller supplies the matching ROWS, the row-level
    # facts (each listing's own price and date) are permitted too. They
    # are re-derived from the read-only master, so a value the master
    # does not hold is still untraceable - the check is not weakened,
    # it is applied at the row level.
    if rows is not None:
        allowed |= approved_row_numbers(rows)

    return allowed


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------


def _walk_numbers(
    value: Any,
    path: str = "",
    skip_keys: Tuple[str, ...] = (),
) -> List[Tuple[str, float]]:
    """Every number inside a JSON-able payload.

    Booleans are not numbers (a policy flag is not a fact). Numbers
    embedded in strings are included, because the served payload carries
    its prose in strings - the reply, the reason text and the "not enough
    data" wording all carry figures.

    A key named in ``skip_keys`` is not descended into: its contents are
    identifiers, not figures (see :func:`guard_payload`).
    """
    found: List[Tuple[str, float]] = []

    if isinstance(value, bool) or value is None:
        return found

    if isinstance(value, (int, float)):
        found.append((path, float(value)))
        return found

    if isinstance(value, str):
        for raw, number in fact_validator.extract_numbers(value):
            found.append(("%s[%r]" % (path, raw), number))
        return found

    if isinstance(value, dict):
        for key, item in value.items():
            if key in skip_keys:
                continue
            found.extend(
                _walk_numbers(item, "%s.%s" % (path, key), skip_keys=skip_keys)
            )
        return found

    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(
                _walk_numbers(item, "%s[%d]" % (path, index), skip_keys=skip_keys)
            )
        return found

    return found


def _offending_numbers(
    payload: Any,
    allowed: Set[float],
    skip_keys: Tuple[str, ...] = (),
) -> List[Tuple[str, float]]:
    offenders: List[Tuple[str, float]] = []
    seen: Set[float] = set()

    for path, number in _walk_numbers(payload, skip_keys=skip_keys):
        if number in allowed or number in seen:
            continue
        seen.add(number)
        offenders.append((path, number))

    return offenders


def guard_payload(
    payload: Any,
    allowed: Set[float],
    label: str = "payload",
    context: Optional[Dict[str, Any]] = None,
    skip_keys: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Check every number in ``payload`` against the permitted set.

    Returns the uniform guard report (see :func:`public_report`). The
    offending values are never included in the report - only their count.

    ``context`` carries the numbers the CUSTOMER supplied (their stated
    size, their stated budget) and any system fact that is not a market
    fact (the reply's timestamp). Those are permitted on the same
    grounds as the size already was: they are the customer's own figures
    and the system's own record, not an invented market figure.

    ``skip_keys`` names payload keys whose contents are **identifiers**
    rather than figures. M7's evidence layer serves the plot identifier
    in its authorised mode, and a plot number such as "2160 series"
    contains digits that are part of a NAME, not a market figure. The
    identifier is not a fact the application asserts about the market,
    so it is not checked as one - exactly as the guard report's own
    counters are not checked as one. The identifier is still bounded by
    the evidence layer's own rules: it is served only in the authorised
    mode, and only for rows the approved master holds.
    """
    if context:
        allowed = allowed | fact_validator.build_allowed_numbers(None, context=context)

    numbers = _walk_numbers(payload, skip_keys=tuple(skip_keys or ()))
    offenders = _offending_numbers(payload, allowed, skip_keys=tuple(skip_keys or ()))

    if offenders:
        return public_report(
            ok=False,
            numbers_found=len(numbers),
            allowed_count=len(allowed),
            untraceable_count=len(offenders),
            label=label,
            reason=(
                "%d number(s) in the %s do not trace to the approved master."
                % (len(offenders), label)
            ),
        )

    return public_report(
        ok=True,
        numbers_found=len(numbers),
        allowed_count=len(allowed),
        untraceable_count=0,
        label=label,
        reason="",
    )


def guard_text(
    text: Optional[str],
    allowed: Set[float],
    label: str = "reply",
) -> Dict[str, Any]:
    """Check every number in a piece of prose against the permitted set."""
    numbers = fact_validator.extract_numbers(text)

    untraceable = 0
    seen: Set[float] = set()
    for _raw, number in numbers:
        if number in allowed or number in seen:
            continue
        seen.add(number)
        untraceable += 1

    if untraceable:
        return public_report(
            ok=False,
            numbers_found=len(numbers),
            allowed_count=len(allowed),
            untraceable_count=untraceable,
            label=label,
            reason=(
                "%d number(s) in the %s do not trace to the approved master."
                % (untraceable, label)
            ),
        )

    return public_report(
        ok=True,
        numbers_found=len(numbers),
        allowed_count=len(allowed),
        untraceable_count=0,
        label=label,
        reason="",
    )


# ---------------------------------------------------------------------------
# The one report shape
# ---------------------------------------------------------------------------


def public_report(
    ok: bool,
    numbers_found: int = 0,
    allowed_count: int = 0,
    untraceable_count: int = 0,
    label: str = "payload",
    reason: str = "",
    action: Optional[str] = None,
) -> Dict[str, Any]:
    """The uniform guard report every surface returns.

    ``untraceable`` is a list of **redacted** markers, never the values:
    re-publishing a number the guard just refused to serve would defeat
    the control. ``untraceable_count`` carries the number itself.
    """
    return {
        "ok": bool(ok),
        "action": action or ("allowed" if ok else "blocked"),
        "label": label,
        "untraceable": [] if ok else [{"redacted": True} for _ in range(untraceable_count)],
        "untraceable_count": int(untraceable_count),
        "numbers_found": int(numbers_found),
        "allowed_count": int(allowed_count),
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# The blocked payloads
# ---------------------------------------------------------------------------


def blocked_lookup_payload(
    filters: Optional[Dict[str, Any]] = None,
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The number-free answer a guarded lookup endpoint returns.

    It keeps the endpoint's shape so the console does not have to special
    case it, but it carries no price, no sample size and no date - only
    the hold wording and the guard report.
    """
    return {
        "answerable": False,
        "reply_mode": "blocked_unverified_numbers",
        "reply": HOLD_REPLY,
        "reason": (
            "The market data for this query could not be verified against "
            "the approved master, so no figures are shown."
        ),
        "filters": dict(filters or {}),
        "facts": None,
        "summary": None,
        "guard": report or public_report(
            ok=False,
            label="lookup",
            untraceable_count=1,
            reason="The market data for this query could not be verified.",
        ),
    }


def blocked_market_row(
    row: Dict[str, Any],
    report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """One `/api/market` row with every number removed.

    The row keeps its shape (block, size, coverage) so the console can
    show that a cell exists and that its numbers were withheld.
    """
    return {
        "block": row.get("block"),
        "size_marla": row.get("size_marla"),
        "matched_plots": None,
        "observation_count": None,
        "price_min_pkr": None,
        "price_median_pkr": None,
        "price_max_pkr": None,
        "price_p25_pkr": None,
        "price_p75_pkr": None,
        "latest_date": None,
        "coverage_level": row.get("coverage_level"),
        "trust_status": row.get("trust_status"),
        "answerable_for_demo": False,
        "guard": report or public_report(
            ok=False,
            label="market",
            untraceable_count=1,
            reason="The figures for this cell could not be verified.",
        ),
    }
