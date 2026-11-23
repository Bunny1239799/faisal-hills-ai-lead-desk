"""M8 - the recommendation layer: ranked VERIFIED alternatives.

Why this module exists
-----------------------
M7 gives the operator the **listings** behind an answer. M8 gives the
dealer the **choice** behind an unavailable answer.

The product rule (handoff v2 section 7.4, and the M6/M7 milestone
records) is a strict ladder:

    Exact match
      -> Strong verified alternatives
        -> Closest verified alternatives
          -> Clarifying question
            -> Human escalation

and never a speculative alternative. This module implements the middle
of that ladder, and only the middle: it proposes cells and listings
that the **approved master actually supports**.

What a recommendation may be
-----------------------------
A recommendation is **one (block, size) cell** that the approved master
covers, with enough evidence to be quoted, plus the listings inside
it. It is never a plot that does not exist, never a size the master
does not hold, and never a price the master does not support.

The ranking is deterministic and explainable
--------------------------------------------
The score is built from named, weighted components, so a dealer can be
told *why* a cell was proposed and an operator can audit the ranking:

  * ``size_fit``     - how close the cell's size is to what was asked
    for. A cell of exactly the requested size scores highest.
  * ``block_fit``    - whether the cell is in the block that was asked
    for. The same block beats a different block at equal size fit.
  * ``evidence``     - how much support the cell has: the number of
    listings and the number of observations behind it.
  * ``recency``      - how recent the cell's latest observation is.

Only cells that clear the **same** evidence threshold the lookup uses
(``min_listings_for_answer``) and carry a usable price may be
recommended. A cell that failed the threshold is exactly the thing the
product must not sell, so it is never proposed as an option - it is
reported as a *thin* cell so the operator can see the gap.

The rules this module never breaks
----------------------------------
* **The application owns truth.** Every number here comes from
  ``market.price_lookup`` / ``market.evidence``, which read the approved
  master. The module computes no new market fact.
* **The scope is the lookup's scope.** A block outside
  ``config/policies.json -> active_blocks`` is refused before any row is
  counted, exactly as the lookup and the evidence layer refuse it.
* **A thin cell carries no price.** A cell below the threshold is
  reported with its listing count and no price, so the recommendation
  layer can never become a way to quote a figure the customer path
  withholds.
* **No dealer content.** The module reads the **whitelisted** evidence
  rows, never the raw master rows, so ``notes``, ``source_chats`` and
  ``size_raw`` cannot reach the recommendation by construction.
* **The recommendation is a proposal, not an answer.** It never claims
  availability ("available", "in stock", "for sale") - the approved
  master is a partial snapshot of asking prices, not a live feed. The
  M6.1 claim guard would refuse such a reply, so the module does not
  produce one.

The module is stdlib-only (RULES_SHORT #5), reads the approved master
**read-only**, writes nothing, and never calls a model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from market import evidence as _evidence
from market import price_lookup

__all__ = [
    "RECOMMENDATION_SOURCE",
    "RecommendationError",
    "build_recommendations",
    "next_best_action",
    "rank_cells",
    "recommendation_reason",
]


# The provenance string every recommendation carries. It names the
# approved master and says the prices are asking prices, so a
# recommendation can never be quoted as a confirmed market fact.
RECOMMENDATION_SOURCE = (
    "FaisalHills verified partial master - dealer asking prices"
)


class RecommendationError(ValueError):
    """Raised when a recommendation request cannot be served safely.

    The caller must treat this as a refusal, never as a reason to serve
    an unfiltered result.
    """


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


def _size_label(size: Optional[float]) -> str:
    """A human label for a size, in marla."""
    if size is None:
        return "an unspecified size"
    if abs(size - round(size)) < 0.001:
        return "%d marla" % int(round(size))
    return "%g marla" % size


# ---------------------------------------------------------------------------
# The candidate cells
# ---------------------------------------------------------------------------


def _candidate_cells(
    requested_block: Optional[str],
    requested_size: Optional[float],
    active_blocks: Sequence[str],
) -> List[Tuple[str, float]]:
    """Every (block, size) cell the approved master actually holds.

    The cells are read from the **scoped** inventory - the same rows the
    lookup and the evidence layer use - so a parked block can never
    produce a candidate, and a size the master does not hold can never
    be proposed.

    Returns:
        A list of ``(block, size)`` tuples, sorted.
    """
    inventory = price_lookup._active_scope_inventory(list(active_blocks))

    cells: Dict[Tuple[str, float], None] = {}
    for row in inventory:
        block = price_lookup.canonical_block(row.get("block"))
        size = _number(row.get("size_marla"))
        if not block or size is None:
            continue
        cells[(block, size)] = None

    return sorted(cells.keys(), key=lambda k: (k[0], k[1]))


def _cell_evidence(
    block: str,
    size: float,
    min_listings: int,
) -> Dict[str, Any]:
    """The whitelisted evidence for one cell.

    The evidence layer is asked for the cell, so the recommendation
    layer never touches a raw master row. A cell below the threshold
    comes back with its rows and **no price**, which is exactly the
    shape the recommendation layer needs to report it as thin.
    """
    return _evidence.evidence_for_cell(block=block, size_marla=size)


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _size_fit(requested: Optional[float], candidate: Optional[float]) -> float:
    """How close the candidate's size is to the requested size.

    ``1.0`` is an exact size match. The score decays with the
    difference in marla, so a neighbouring size outranks a distant one.

    A candidate of a size the dealer did **not** ask for still gets a
    real score - that is the point of an alternative - but it can never
    reach the score of an exact match.
    """
    if requested is None or candidate is None:
        return 0.0
    difference = abs(candidate - requested)
    if difference <= 0.001:
        return 1.0
    # A one-marla difference is a very close alternative; the score
    # halves for every marla of distance from there.
    return max(0.0, 1.0 - (difference / 2.0))


def _block_fit(requested_block: Optional[str], candidate_block: str) -> float:
    """Whether the candidate is in the block that was asked for."""
    if not requested_block:
        return 0.5
    if str(requested_block).strip().upper() == candidate_block:
        return 1.0
    return 0.0


def _evidence_fit(summary: Dict[str, Any], min_listings: int) -> float:
    """How well supported the cell is.

    A cell that only just clears the threshold scores lower than a cell
    with a deep sample, so the recommendation prefers the better
    evidenced option when the fit is otherwise equal.
    """
    listings = int(summary.get("matched_plots") or 0)
    if listings <= 0:
        return 0.0
    return min(1.0, listings / float(max(min_listings * 2, 1)))


def _recency_fit(latest_date: Optional[str], newest_date: Optional[str]) -> float:
    """How recent the cell's latest observation is, against the newest.

    Dates are ISO strings, so they compare lexicographically. A cell
    whose latest observation is the newest in the dataset scores 1.0.
    """
    if not latest_date or not newest_date:
        return 0.0
    if latest_date >= newest_date:
        return 1.0
    return 0.5


# ---------------------------------------------------------------------------
# The reason
# ---------------------------------------------------------------------------


def recommendation_reason(
    requested_block: Optional[str],
    requested_size: Optional[float],
    candidate_block: str,
    candidate_size: float,
    summary: Dict[str, Any],
) -> List[str]:
    """Why this cell was proposed.

    Each entry names one reason in the operator's language. The reasons
    are derived from the request and the approved fact set, never from a
    model, so they cannot carry an unsupported claim.
    """
    reasons: List[str] = []

    if requested_size is not None and abs(candidate_size - requested_size) <= 0.001:
        reasons.append("the requested %s" % _size_label(candidate_size))
    elif requested_size is not None:
        reasons.append(
            "%s, closest available size to the %s requested"
            % (_size_label(candidate_size), _size_label(requested_size))
        )
    else:
        reasons.append("%s in Block %s" % (_size_label(candidate_size),
                                           candidate_block))

    if requested_block:
        if str(requested_block).strip().upper() == candidate_block:
            reasons.append("in the requested Block %s" % candidate_block)
        else:
            reasons.append("the nearest size in another active block")

    listings = int(summary.get("matched_plots") or 0)
    observations = int(summary.get("observation_count") or 0)
    if listings:
        reasons.append(
            "%d verified listing%s with %d observation%s"
            % (listings, "" if listings == 1 else "s",
               observations, "" if observations == 1 else "s")
        )

    return reasons


# ---------------------------------------------------------------------------
# The ranking
# ---------------------------------------------------------------------------


def _all_cell_summaries(
    active_blocks: Sequence[str],
) -> Tuple[Dict[Tuple[str, float], Dict[str, Any]], Optional[str]]:
    """The whitelisted summary of every cell in scope, and the newest date.

    Every cell is read once, through the evidence layer, so the
    recommendation layer never touches a raw master row and the
    thin-cell detection and the ranking see exactly the same facts.
    """
    candidates = _candidate_cells(None, None, active_blocks)

    summaries: Dict[Tuple[str, float], Dict[str, Any]] = {}
    newest: Optional[str] = None
    for block, size in candidates:
        evidence = _cell_evidence(block, size, 1)
        summary = evidence.get("summary") or {}
        summaries[(block, size)] = summary
        latest = summary.get("latest_date")
        if latest and (newest is None or latest > newest):
            newest = latest

    return summaries, newest


def rank_cells(
    requested_block: Optional[str],
    requested_size: Optional[float],
    active_blocks: Sequence[str],
    min_listings: int,
    limit: int = 3,
    cell_summaries: Optional[Dict[Tuple[str, float], Dict[str, Any]]] = None,
    newest_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Rank the candidate cells for a request.

    Returns:
        A list of cell summaries, best first. Each summary is the
        **whitelisted** evidence summary for the cell plus the ranking
        score and the reason. Only cells that clear the threshold
        appear in the ranked list; a cell that does not clear it is
        reported separately as a thin cell.
    """
    requested_block = (
        str(requested_block).strip().upper() if requested_block else None
    )

    if cell_summaries is None:
        cell_summaries, newest_date = _all_cell_summaries(active_blocks)
    if newest_date is None:
        newest_date = max(
            [s.get("latest_date") for s in cell_summaries.values()
             if s.get("latest_date")] or [None]
        )

    scored: List[Dict[str, Any]] = []
    for (block, size), summary in sorted(cell_summaries.items()):
        listings = int(summary.get("matched_plots") or 0)
        if listings < min_listings:
            # Below the evidence threshold: a thin cell. It is never
            # ranked as an option and never carries a price.
            continue
        if summary.get("price_median_pkr") is None:
            # No usable price: nothing to recommend.
            continue

        size_score = _size_fit(requested_size, size)
        block_score = _block_fit(requested_block, block)
        evidence_score = _evidence_fit(summary, min_listings)
        recency_score = _recency_fit(summary.get("latest_date"), newest_date)

        score = (
            (0.50 * size_score)
            + (0.20 * block_score)
            + (0.20 * evidence_score)
            + (0.10 * recency_score)
        )

        scored.append({
            "block": block,
            "size_marla": size,
            "score": round(score, 6),
            "score_components": {
                "size_fit": round(size_score, 6),
                "block_fit": round(block_score, 6),
                "evidence_fit": round(evidence_score, 6),
                "recency_fit": round(recency_score, 6),
            },
            "summary": summary,
            "reason": recommendation_reason(
                requested_block, requested_size, block, size, summary),
        })

    # Deterministic ordering: score first, then the tie-breakers that
    # make the order stable across runs.
    scored.sort(key=lambda item: (
        -item["score"],
        abs(item["size_marla"] - requested_size)
        if requested_size is not None else 0,
        item["block"],
        item["size_marla"],
    ))

    if limit is not None and limit >= 0:
        scored = scored[:limit]

    return scored


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def build_recommendations(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    limit: int = 3,
    include_listings: bool = True,
    policies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ranked, verified alternatives for a request.

    The result is a **proposal list**, never a claim of availability.
    Every option is a cell the approved master covers and that clears
    the same evidence threshold the lookup uses.

    Args:
        block: the requested block. A block outside the active scope is
            refused **before** any row is counted.
        size_marla: the requested size.
        corner / sun_facing / ndc_open: the requested features.
        limit: the maximum number of options to return.
        include_listings: whether the whitelisted listings of each
            option are included. The listings are the M7 evidence rows
            - redacted, and free of dealer content.
        policies: the policy configuration, for tests.

    Returns:
        A dict with the shape::

            {
              "options": [...],          # the ranked alternatives
              "thin_cells": [...],       # cells that did NOT clear the threshold
              "requested": {...},        # what was asked for
              "answerable": bool,        # is the requested cell itself answerable
              "exact_match": {...} | None,
              "evidence_source": str,
              "price_basis": str,
              "is_sold_price": False,
              "availability_claimed": False,
              "next_best_action": {...},
            }

    Raises:
        RecommendationError: when the request is out of scope.
    """
    config = policies if policies is not None else price_lookup.load_policies()

    active_blocks = list(config.get("active_blocks", ["A", "B", "C"]))
    min_listings = int(config.get("min_listings_for_answer", 3))

    scope = price_lookup.classify_block(block, config)
    if scope["status"] == "out_of_scope":
        raise RecommendationError(
            "Block %s is outside the active scope (%s)."
            % (block, ", ".join(active_blocks))
        )

    requested_block = scope["block"] if scope["status"] == "active" else None
    requested_size = _number(size_marla)

    # The requested cell itself, through the evidence layer.
    exact: Optional[Dict[str, Any]] = None
    if requested_block and requested_size is not None:
        requested_evidence = _cell_evidence(
            requested_block, requested_size, min_listings)
        requested_summary = requested_evidence.get("summary") or {}
        if requested_evidence.get("answerable"):
            exact = {
                "block": requested_block,
                "size_marla": requested_size,
                "summary": requested_summary,
                "reason": [
                    "the exact requested cell",
                    "%d verified listing%s with %d observation%s"
                    % (int(requested_summary.get("matched_plots") or 0), "",
                       int(requested_summary.get("observation_count") or 0), ""),
                ],
            }

    cell_summaries, newest_date = _all_cell_summaries(active_blocks)

    ranked = rank_cells(
        requested_block,
        requested_size,
        active_blocks,
        min_listings,
        limit=limit,
        cell_summaries=cell_summaries,
        newest_date=newest_date,
    )

    # The exact cell is never repeated as an "alternative".
    options: List[Dict[str, Any]] = []
    for item in ranked:
        if (exact is not None
                and item["block"] == exact["block"]
                and abs(item["size_marla"] - exact["size_marla"]) <= 0.001):
            continue

        option = {
            "block": item["block"],
            "size_marla": item["size_marla"],
            "score": item["score"],
            "score_components": item["score_components"],
            "reason": item["reason"],
            "summary": item["summary"],
        }

        if include_listings:
            evidence = _cell_evidence(
                item["block"], item["size_marla"], min_listings)
            option["listings"] = evidence.get("listings") or []
            option["listing_count"] = len(option["listings"])

        options.append(option)

    # -- the thin cells: the gaps, reported honestly -------------------
    thin_cells: List[Dict[str, Any]] = []
    for (cell_block, cell_size), summary in sorted(cell_summaries.items()):
        listings = int(summary.get("matched_plots") or 0)
        if listings == 0 or listings >= min_listings:
            continue
        if requested_block and cell_block != requested_block:
            continue
        if requested_size is not None and abs(cell_size - requested_size) > 0.001:
            continue
        thin_cells.append({
            "block": cell_block,
            "size_marla": cell_size,
            "listing_count": listings,
            "min_listings_for_answer": min_listings,
            "reason": [
                "%d listing%s, below the %d-listing evidence threshold"
                % (listings, "" if listings == 1 else "s", min_listings)
            ],
        })

    result: Dict[str, Any] = {
        "requested": {
            "block": requested_block,
            "size_marla": requested_size,
        },
        "exact_match": exact,
        "options": options,
        "thin_cells": thin_cells,
        "answerable": exact is not None,
        "evidence_source": RECOMMENDATION_SOURCE,
        "price_basis": "dealer asking prices",
        "is_sold_price": False,
        # The approved master is a partial snapshot of asking prices, not
        # a live availability feed. A recommendation therefore never
        # claims that a plot is available, in stock or for sale.
        "availability_claimed": False,
        "min_listings_for_answer": min_listings,
    }

    result["next_best_action"] = next_best_action(result)
    return result


# ---------------------------------------------------------------------------
# The next best action
# ---------------------------------------------------------------------------


def next_best_action(recommendation: Dict[str, Any]) -> Dict[str, Any]:
    """What the dealer should do next, given the recommendation.

    The ladder is strict and every rung is **verified**:

    * an exact match exists -> quote it (the price path already does);
    * there are strong alternatives -> offer them with their reason;
    * there are only thin cells -> ask the clarifying question that
      would resolve the gap, and keep the human hand-off;
    * there is nothing at all -> escalate to a human.

    A speculative option is never produced. When the data cannot
    support a recommendation, the action is a **question** or a
    **human**, never a guess.
    """
    exact = recommendation.get("exact_match")
    options = recommendation.get("options") or []
    thin = recommendation.get("thin_cells") or []

    if exact is not None:
        return {
            "action": "quote_exact_match",
            "label": "Answer with the verified price for the requested cell.",
            "requires_human_approval": True,
            "reason": "the requested cell clears the evidence threshold",
        }

    if options:
        strongest = options[0]
        return {
            "action": "offer_verified_alternatives",
            "label": (
                "Offer the verified alternative%s: %s in Block %s."
                % ("" if len(options) == 1 else "s",
                   _size_label(strongest.get("size_marla")),
                   strongest.get("block"))
            ),
            "option_count": len(options),
            "requires_human_approval": True,
            "reason": "the requested cell is not covered, but verified "
                      "alternatives are",
        }

    if thin:
        return {
            "action": "ask_clarifying_question",
            "label": (
                "Ask the dealer which size or block would work, and keep "
                "the human hand-off."
            ),
            "requires_human_approval": True,
            "reason": "no cell clears the evidence threshold for this request",
        }

    return {
        "action": "escalate_to_human",
        "label": "Hand the conversation to a member of the team.",
        "requires_human_approval": True,
        "reason": "the approved data does not cover this request",
    }
