"""M11.3 - the turn pipeline: one message, one turn, one decision.

What this module is
-------------------
The orchestration the product was missing: a dealer conversation that
**accumulates** a qualification state, reaches the **existing** decision
layer, and comes back with a validated reply, a route and a reason.

What this module is NOT
-----------------------
It is **not** a second intelligence engine. It decides nothing. It does
not read the approved master, it does not price anything, it does not
qualify anything and it does not phrase anything. Every decision comes
from the components that already exist and are unchanged:

* the **policy gate** (`app.policy`) - escalate, refuse or answer;
* the **lookup** (`market.price_lookup`) - the approved facts, or none;
* the **recommendation layer** (`market.recommend`) - the verified
  alternatives and the reason for each;
* the **qualification layer** (`market.qualify`) - the requirements, and
  the narrowing;
* the **decision layer** (`market.decision`) - the action;
* the **M5 numeric validator** and the **M6.1 claim guard** - the two
  final gates in front of every reply.

The pipeline
------------
::

    message
      -> normalizer              (market.normalize)
      -> the application        (app.pipeline.handle_message - UNCHANGED)
           policy -> lookup -> facts -> recommendation
                -> M9 qualification -> M9 decision
                -> M5 validator -> M6.1 claim guard
      -> lead state             (market.lead_state)
      -> route                  (read from the M9 decision - NOT decided here)
      -> unmet demand           (market.unmet_demand, only when nothing was answered)

The route is **read** from the application's own decision, never computed
by a new rule:

===========================================  ==============
the M9 action                                the route
===========================================  ==============
``quote_exact_match``                        ``exact``
``offer_verified_alternatives``              ``alternative``
``ask_clarifying_question``                  ``clarify``
``escalate_to_human``                        ``escalate``
===========================================  ==============

A turn in which the application reached **no** decision at all (the dealer
has not said enough yet) is a ``clarify``: the application has nothing
verified to say, and the next move is a question. A turn the policy
escalated or refused is an ``escalate``.

There is **no live model call** anywhere in this module: the reply is the
application's own deterministic template reply, already through both final
gates (owner default 3, H3).
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from app.pipeline import handle_message
from market import inventory_workspace as _workspace
from market import lead_state as _lead_state
from market import normalize as _normalize
from market import unmet_demand as _unmet_demand
from market.lead_state import LeadState, LeadStateStore
from market.qualify import extract_requirements

__all__ = [
    "ROUTE_ALTERNATIVE",
    "ROUTE_CLARIFY",
    "ROUTE_ESCALATE",
    "ROUTE_EXACT",
    "run_turn",
]


ROUTE_EXACT = "exact"
ROUTE_ALTERNATIVE = "alternative"
ROUTE_CLARIFY = "clarify"
ROUTE_ESCALATE = "escalate"

# The M9 decision action -> the route it means.
_ACTION_ROUTES = {
    "quote_exact_match": ROUTE_EXACT,
    "offer_verified_alternatives": ROUTE_ALTERNATIVE,
    "ask_clarifying_question": ROUTE_CLARIFY,
    "escalate_to_human": ROUTE_ESCALATE,
}


def _route_of(result: Dict[str, Any]) -> str:
    """The route of a turn, read from the application's own decision.

    The policy has the last word: an escalation or a refusal is always
    an ``escalate``, whatever the market layer decided.
    """
    decision = result.get("decision") or {}
    action = decision.get("action")
    if action in ("escalate", "refuse") or result.get("needs_human"):
        return ROUTE_ESCALATE

    next_best = result.get("next_best_action") or {}
    mapped = _ACTION_ROUTES.get(next_best.get("action"))
    if mapped:
        return mapped

    # The application reached no decision: the dealer has not said enough
    # yet, so the next move is a question.
    return ROUTE_CLARIFY


def _verified_options(result: Dict[str, Any], route: str) -> List[Dict[str, Any]]:
    """The options the application verified, with their reason.

    An **exact** route names the cell the reply priced. Any other route
    names the application's own verified alternatives - the ones the M8
    layer ranked from the approved master and the M9 layer then narrowed.

    No price and no plot number is carried here: the options are cells
    and the application's own explanation of each one.
    """
    options: List[Dict[str, Any]] = []

    if route == ROUTE_EXACT:
        market_facts = result.get("market_facts") or {}
        filters = market_facts.get("filters") or {}
        block = filters.get("block")
        size = filters.get("size_marla")
        if block and size is not None:
            next_best = result.get("next_best_action") or {}
            options.append({
                "block": str(block).strip().upper(),
                "size_marla": size,
                "reason": [next_best.get("reason") or ""],
                "verified": True,
            })
        return options

    for alternative in result.get("verified_alternatives") or []:
        if not isinstance(alternative, dict):
            continue
        if alternative.get("verified") is not True:
            continue
        options.append({
            "block": alternative.get("block"),
            "size_marla": alternative.get("size_marla"),
            "reason": list(alternative.get("reason") or []),
            "verified": True,
        })
    return options


def _reason_of(result: Dict[str, Any], route: str) -> str:
    """Why this route, in the application's own words."""
    next_best = result.get("next_best_action") or {}
    reason = next_best.get("reason")
    if reason:
        return str(reason)

    decision = result.get("decision") or {}
    policy_reasons = decision.get("reasons") or []
    if policy_reasons:
        return "; ".join(str(item) for item in policy_reasons)

    market_reason = result.get("market_reason")
    if market_reason:
        return str(market_reason)

    if route == ROUTE_ESCALATE:
        return "the application escalated this turn to a human"
    return "the application has no verified answer for this request yet"


def _next_action_of(result: Dict[str, Any], route: str,
                    state: LeadState) -> Dict[str, Any]:
    """The next action for the operator.

    When the application made a decision, its own ``next_best_action``
    is used - unchanged. When it made no decision at all (the dealer has
    not said enough yet), the operator is told **which requirement is
    still missing**, which is a reading of the lead state and nothing
    more. It never decides anything and never changes the reply.
    """
    next_best = result.get("next_best_action") or {}
    if next_best:
        return next_best

    missing = state.unknowns()
    if missing:
        return {
            "action": "ask_clarifying_question",
            "label": "Ask the dealer for: %s." % ", ".join(missing),
            "reason": "the application has no verified answer and the "
                      "conversation is still missing a requirement",
            "requires_human_approval": True,
        }

    return {
        "action": "confirm_with_team",
        "label": "Confirm the current market information with the team.",
        "reason": "the application has no verified answer for this request",
        "requires_human_approval": True,
    }


def run_turn(
    message: str,
    session_id: Optional[str] = None,
    *,
    state: Optional[LeadState] = None,
    store: Optional[LeadStateStore] = None,
    demand_store: Optional[_unmet_demand.UnmetDemandStore] = None,
    log_store: Optional[Any] = None,
) -> Dict[str, Any]:
    """Run one turn of a dealer conversation.

    Args:
        message: the dealer's own words.
        session_id: the conversation's id. When it is missing, one is
            generated and returned in the result.
        state: the state **before** this turn. When it is missing, the
            state is read from the store.
        store: where the lead state lives. Defaults to the M11 store.
        demand_store: where the unmet-demand log lives. Defaults to the
            M11 demand store.
        log_store: where the M12.2 conversation log lives. Defaults to
            the M12.2 log store. The turn is recorded **after** the
            reply was validated, and a log that cannot be written never
            fails the turn - the reply is the product, the log is the
            record.

    Returns:
        The turn result: the reply, the lead state, the route, the
        reason, the escalation flag, the verified options, the next
        action, the unmet-demand record and the corrections.
    """
    if not session_id:
        session_id = uuid.uuid4().hex

    state_store = store if store is not None else LeadStateStore()
    previous_state = state if state is not None else state_store.load(session_id)

    # 1. the normalizer - the canonical form of what the dealer said
    normalized = _normalize.normalize_message(message)

    # 2. the application - unchanged, and the only place a decision is made
    result = handle_message(normalized.text, lead_id=session_id)

    # 3. the lead state - a record with provenance, never a new rule
    current_requirements = extract_requirements(normalized.text)
    turn_number = int(previous_state.turn or 0) + 1
    new_state = _lead_state.state_from_requirements(
        current_requirements,
        previous=previous_state,
        turn=turn_number,
    )

    # 4. the route - read from the application's own decision
    route = _route_of(result)
    reason = _reason_of(result, route)
    options = _verified_options(result, route)

    # 5. the unmet demand - only when the application could not answer
    unmet = None
    if route != ROUTE_EXACT:
        unmet = _unmet_demand.record_unmet_demand(
            lead_state=new_state.to_dict(),
            route=route,
            store=demand_store if demand_store is not None
            else _unmet_demand.UnmetDemandStore(),
        )

    state_store.save(session_id, new_state)

    # 6. the M12.2 conversation log - the record of what was said and
    #    answered. The reply recorded here is the reply that already
    #    passed both final gates; a log that cannot be written never
    #    fails the turn.
    if log_store is None:
        from market.conversation_log import ConversationLogStore
        log_store = ConversationLogStore()
    escalation = bool(route == ROUTE_ESCALATE or result.get("needs_human"))
    try:
        log_store.record_turn(
            session_id, turn_number, message,
            result.get("draft_reply") or "", route, escalation,
            options=options,
        )
    except Exception:
        pass

    # 7. the lead pipeline - every conversation becomes a trackable
    #    lead. Only the two standing automatic flags exist: ESCALATED
    #    when a turn escalates (take-over is flagged by its own route).
    #    Every other stage change needs operator approval.
    try:
        from market.lead_pipeline import LeadPipelineStore
        pipeline = LeadPipelineStore()
        pipeline.ensure_lead(session_id)
        if escalation:
            pipeline.mark_escalated(session_id)
    except Exception:
        pass

    # 8. Stage 1: stamp the turn with the inventory version it was
    #    produced from (id + fingerprint + rows + observation range), and
    #    fire a one-shot change notice when the active version moved. The
    #    customer draft text above is untouched by this.
    stamp = _workspace.current_stamp()
    change_notice = _workspace.session_note_version(session_id, stamp,
                                                   turn_number)

    response = {
        "session_id": session_id,
        "turn": turn_number,
        "reply": result.get("draft_reply") or "",
        "lead_state": new_state.to_dict(),
        "route": route,
        "reason": reason,
        "escalation": escalation,
        "verified_options": options,
        "next_action": _next_action_of(result, route, new_state),
        "unmet_demand": unmet,
        "changes": [dict(change) for change in new_state.changes],
        "normalized": normalized.to_dict(),
        "policy": {
            "action": (result.get("decision") or {}).get("action"),
            "reasons": list(result.get("policy_reasons") or []),
        },
        "gates": {
            "traceability_ok": result.get("traceability_ok"),
            "claim_guard_ok": result.get("claim_guard_ok"),
        },
        "inventory_version": stamp,
    }

    if change_notice:
        response["version_change"] = change_notice
    return response
