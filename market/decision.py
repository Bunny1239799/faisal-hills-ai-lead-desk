"""M9 - the decision layer: qualify the options, then choose the action.

Why this module exists
-----------------------
M8 ranks the **verified** alternatives. M9's qualification layer narrows
them by what the dealer actually said. This module is where the two
meet and the product decides what to do next.

The decision ladder
-------------------
The product's ladder is strict, and this module walks it in order:

    1. an exact verified match          -> ``quote_exact_match``
    2. strong verified alternatives      -> ``offer_verified_alternatives``
    3. closest verified alternatives     -> ``offer_verified_alternatives``
    4. a targeted clarifying question    -> ``ask_clarifying_question``
    5. human escalation                  -> ``escalate_to_human``

The ladder is walked **downward**, and each rung is only reached when
the rung above it is genuinely unavailable. A clarifying question is
asked only when the answer would materially improve the match; a human
is asked only when the evidence, the policy or the ambiguity requires
one. The product never manufactures an answer to avoid asking.

The narrowing-only rule
-----------------------
The options this module reasons about are the ones M8 already
**verified** against the approved master. Qualification may remove
some of them and re-rank the rest. It may **never**:

  * add an option M8 did not produce;
  * lower the evidence threshold, so a thin cell can never become an
    option;
  * invent a price, a block, a size or a property attribute;
  * turn a missing requirement into a guessed one.

Every option this module returns carries a ``verified`` marker and its
own provenance, so the M6.1 guard and the M5 numeric validator can
check the reply exactly as they check any other.

The module is stdlib-only (RULES_SHORT #5), reads nothing, writes
nothing, and never calls a model.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from market import qualify as _qualify

__all__ = [
    "ACTION_CLARIFY",
    "ACTION_ESCALATE",
    "ACTION_OFFER",
    "ACTION_QUOTE",
    "decide",
]


# The four actions the decision layer can take.
ACTION_QUOTE = "quote_exact_match"
ACTION_OFFER = "offer_verified_alternatives"
ACTION_CLARIFY = "ask_clarifying_question"
ACTION_ESCALATE = "escalate_to_human"

# The actions that require a human to approve the reply. Every action
# does - the product's rule is that a human approves every reply - but
# the escalate action is the one where the human *must* do the work.
_ACTIONS_REQUIRING_APPROVAL = (ACTION_QUOTE, ACTION_OFFER, ACTION_CLARIFY,
                               ACTION_ESCALATE)


def decide(
    recommendation: Optional[Dict[str, Any]] = None,
    requirements: Optional[Dict[str, Any]] = None,
    options: Optional[Sequence[Dict[str, Any]]] = None,
    policy_action: Optional[str] = None,
    needs_human: bool = False,
    ask_when_nothing_stated: bool = False,
) -> Dict[str, Any]:
    """Decide what to do with a request, given the verified options.

    Args:
        recommendation: the M8 result. It supplies the exact match, the
            ranked options and the thin cells.
        requirements: the dealer's stated requirements (M9). Every
            field is optional; a field that is ``None`` was not
            stated.
        options: an explicit option list, when the caller has already
            built one. When omitted, the recommendation's own options
            are used.
        policy_action: the policy's action (``answer`` / ``escalate`` /
            ``refuse``). An escalation or a refusal is never overridden
            by the recommendation layer.
        needs_human: whether the policy or the decision model already
            requires a human.
        ask_when_nothing_stated: M13. When True, an intent with NO
            requirement at all asks the single most useful question
            instead of offering cells the dealer never qualified. The
            conversation path sets it; a direct cell query (the
            next-best-action endpoint) keeps the OFFER semantics.

    Returns:
        A dict with the shape::

            {
              "action": "quote_exact_match" | "offer_verified_alternatives"
                        | "ask_clarifying_question" | "escalate_to_human",
              "label": str,                 # what the operator/dealer does
              "reason": str,                # why this action
              "options": [...],             # the verified options, best first
              "exact_match": {...} | None,
              "removed": [...],             # what qualification excluded
              "exact_excluded": bool,       # the EXACT cell was excluded
                                            # by a stated requirement, so
                                            # it must not be quoted (D-61)
              "requirements": {...},        # the requirements that were used
              "clarifying_question": {...} | None,
              "thin_cells": [...],
              "requires_human_approval": True,
              "availability_claimed": False,
            }
    """
    recommendation = recommendation or {}
    requirements = requirements or {}

    # -- the policy always wins ---------------------------------------
    # A refusal or an escalation is never softened by the
    # recommendation layer. That is the tightening-only rule applied in
    # the other direction: the market layer may only ever make the
    # product *more* careful, never less.
    if policy_action in ("escalate", "refuse"):
        return {
            "action": ACTION_ESCALATE,
            "label": "Hand the conversation to a member of the team.",
            "reason": "the policy escalated or refused this message",
            "options": [],
            "exact_match": None,
            "removed": [],
            "exact_excluded": False,
            "requirements": dict(requirements),
            "clarifying_question": None,
            "thin_cells": list(recommendation.get("thin_cells") or []),
            "requires_human_approval": True,
            "availability_claimed": False,
        }

    exact = recommendation.get("exact_match")
    candidate_options = (
        list(options) if options is not None
        else list(recommendation.get("options") or [])
    )
    thin_cells = list(recommendation.get("thin_cells") or [])

    # -- the exact match, when the requirements allow it --------------
    if exact is not None:
        qualified = _qualify.apply_requirements([exact], requirements)
        if qualified["options"]:
            return {
                "action": ACTION_QUOTE,
                "label": "Answer with the verified price for the requested "
                         "cell.",
                "reason": "the requested cell clears the evidence threshold "
                          "and satisfies the stated requirements",
                "options": qualified["options"],
                "exact_match": exact,
                "removed": [],
                # The cell was quoted, so it was NOT excluded.
                "exact_excluded": False,
                "requirements": dict(requirements),
                "clarifying_question": None,
                "thin_cells": thin_cells,
                "requires_human_approval": True,
                "availability_claimed": False,
            }
        # The exact cell conflicts with a stated requirement, so it is
        # not quoted. The alternatives below may still serve.
        excluded_exact = qualified["removed"]

    # -- the alternatives, narrowed by the requirements ----------------
    qualified = _qualify.apply_requirements(candidate_options, requirements)
    kept = qualified["options"]
    removed = list(qualified["removed"])
    if exact is not None and not any(
        item.get("block") == exact.get("block")
        and _same_size(item.get("size_marla"), exact.get("size_marla"))
        for item in removed
    ):
        # The exact cell was excluded by the requirements.
        #
        # M10 D-61: the comparison is on the (block, size) PAIR, not on
        # the block alone. Comparing the block alone meant that the
        # removal of one cell in a block stopped the removal of the
        # exact cell in that SAME block from ever being recorded - so a
        # cell the dealer's own floor had excluded was not recorded as
        # excluded, and the reply went on quoting its price.
        exact_removed = _qualify.apply_requirements([exact], requirements)
        removed.extend(exact_removed["removed"])

    if kept:
        # -- M13: an intent with NOTHING stated asks first --------------
        # The ladder's clarifying step exists exactly for this case.
        # Options offered to a dealer whose requirements are all unknown
        # cannot be matched to anything they actually said, so the next
        # best action is the single most useful question - with the
        # verified cells still on record for the next turn. A dealer who
        # stated ANY requirement keeps the OFFER path below.
        if ask_when_nothing_stated and all(
            requirements.get(key) is None
            for key in ("budget_min_pkr", "budget_max_pkr", "purpose",
                        "block", "size_marla", "timeline")
        ) and not needs_human:
            question = _qualify.clarifying_question(requirements, [])
            if question is not None:
                return {
                    "action": ACTION_CLARIFY,
                    "label": question["question"],
                    "reason": question["reason"],
                    # a clarify turn exposes NO option cells: the question
                    # is the answer, and the verified cells wait for the
                    # turn when the dealer has actually qualified them
                    "options": [],
                    "exact_match": None,
                    "removed": [],
                    "exact_excluded": exact is not None,
                    "requirements": dict(requirements),
                    "clarifying_question": question,
                    "thin_cells": thin_cells,
                    "requires_human_approval": True,
                    "availability_claimed": False,
                }

        # M9 D-61: was the EXACT cell removed by a requirement? The
        # alternatives being offered is not the same thing: a dealer
        # whose budget excluded the cell they asked about must not be
        # shown that cell's price in the same reply. The pipeline reads
        # this flag to withdraw the price.
        exact_excluded = bool(
            exact is not None
            and any(
                item.get("block") == exact.get("block")
                and _same_size(item.get("size_marla"), exact.get("size_marla"))
                for item in removed
            )
        )
        return {
            "action": ACTION_OFFER,
            "label": "Offer the verified alternatives: %s."
                     % _first_option_label(kept),
            "reason": "the request is covered by verified alternatives"
                      + (" that satisfy the stated requirements"
                         if qualified["applied"] else ""),
            "options": kept,
            "exact_match": None,
            "removed": removed,
            "exact_excluded": exact_excluded,
            "requirements": dict(requirements),
            "clarifying_question": None,
            "thin_cells": thin_cells,
            "requires_human_approval": True,
            "availability_claimed": False,
        }

    # -- no option survived: ask, or escalate -------------------------
    question = _qualify.clarifying_question(requirements, [])

    if question is not None and not needs_human:
        return {
            "action": ACTION_CLARIFY,
            "label": question["question"],
            "reason": question["reason"],
            "options": [],
            "exact_match": None,
            "removed": removed,
            # Nothing is quoted, so nothing is excluded - but the cell
            # is certainly not quoted, and the pipeline must treat the
            # fact set as NOT answerable (D-62).
            "exact_excluded": exact is not None,
            "requirements": dict(requirements),
            "clarifying_question": question,
            "thin_cells": thin_cells,
            "requires_human_approval": True,
            "availability_claimed": False,
        }

    return {
        "action": ACTION_ESCALATE,
        "label": "Hand the conversation to a member of the team.",
        "reason": ("the policy requires a human"
                   if needs_human else
                   "the approved data does not cover this request"),
        "options": [],
        "exact_match": None,
        "removed": removed,
        "exact_excluded": exact is not None,
        "requirements": dict(requirements),
        "clarifying_question": None,
        "thin_cells": thin_cells,
        "requires_human_approval": True,
        "availability_claimed": False,
    }


def _same_size(left: Any, right: Any) -> bool:
    """Whether two sizes are the same, within the master's precision."""
    try:
        return abs(float(left) - float(right)) <= 0.001
    except (TypeError, ValueError):
        return False


def _first_option_label(options: Sequence[Dict[str, Any]]) -> str:
    """A short label for the best option, for the operator's action line."""
    if not options:
        return "none"
    option = options[0]
    block = option.get("block")
    size = option.get("size_marla")
    if size is None:
        return str(block)
    if float(size).is_integer():
        return "%d marla in Block %s" % (int(size), block)
    return "%g marla in Block %s" % (size, block)
