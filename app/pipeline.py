import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.policy import evaluate_policy, PolicyDecision
from market.llm_extract import extract_entities_with_fallback, ExtractedEntity
from data.db import get_db_connection
from market import price_lookup as _price_lookup
from market import fact_validator as _fact_validator
from market import reply_guard as _reply_guard
from market import recommend as _recommend
from market import qualify as _qualify
from market import decision as _decision
from market import property_matcher as _property_matcher
from market import lead_qualification as _lead_qualification
from market import site_visit as _site_visit
from market import conversation as _conversation
from app import customer_model as _customer_model
from app import decision_model as _decision_model


def _fh_decision_signals(message: str):
    """Ask the decision-layer port for Laya's signals.

    M6 (FH-02 section 6 M6). Three properties:

    1. **Default = no signal.** The port's default implementation is the
       application's own rules, so on the default path the policy sees
       exactly what it saw before M6.
    2. **Tightening only.** `evaluate_policy()` raises `needs_human` and
       escalates when the `needs_human` probability reaches the threshold;
       it has no path that de-escalates because of a signal.
    3. **No PII leaves the machine.** An external decision service receives
       the PII-scrubbed message, never the original (RULES_SHORT #6).

    A failure of the decision service is a fall back to **no signal** - the
    application's own policy then decides alone, which is always safe.
    """
    try:
        signals = _decision_model.get_decision_signals(message)
    except Exception:  # pragma: no cover - the port already falls back
        return None

    if not signals:
        return None

    return signals


def generate_lead_brief(message: str, entities: ExtractedEntity, decision: PolicyDecision) -> Dict[str, Any]:
    """Generate a lead brief from the message and extracted entities."""
    # Detect language: simple check for Urdu characters
    urdu_chars = set("آأإئبتثجحخدذرزسشصضطظعغفقكلمنهوىيئؤة")
    has_urdu = any(c in urdu_chars for c in message)
    language = "ur" if has_urdu else "en"

    # Determine intent based on entities and message
    if entities.side == "BUY":
        intent = "buying_intent"
    elif entities.side == "SELL":
        intent = "selling_intent"
    else:
        intent = "general_inquiry"

    # Block and size interest
    block_size_parts = []
    if entities.block_code:
        block_size_parts.append(f"Block {entities.block_code}")
    if entities.size_marla is not None:
        block_size_parts.append(f"{entities.size_marla} marla")
    block_and_size_interest = " ".join(block_size_parts) if block_size_parts else "unspecified"

    # Budget
    budget = entities.price_pkr

    # Timeline: not extracted, set to None
    timeline = None

    # Intent level: based on completeness of information
    if entities.price_pkr is not None and entities.size_marla is not None and entities.block_code is not None:
        intent_level = "high"
    elif entities.block_code is not None or entities.size_marla is not None:
        intent_level = "medium"
    else:
        intent_level = "low"

    # Suggested next action
    if decision.needs_human:
        suggested_next_action = "escalate to human agent"
    elif entities.side == "BUY":
        suggested_next_action = "arrange site visit"
    elif entities.side == "SELL":
        suggested_next_action = "verify ownership and prepare documents"
    else:
        suggested_next_action = "provide general information"

    # Last message time
    last_message_time = datetime.now(timezone.utc).isoformat()

    return {
        "language": language,
        "intent": intent,
        "block_and_size_interest": block_and_size_interest,
        "budget": budget,
        "timeline": timeline,
        "intent_level": intent_level,
        "needs_human": decision.needs_human,
        "suggested_next_action": suggested_next_action,
        "last_message_time": last_message_time,
    }


def generate_draft_reply(
    message: str, entities: ExtractedEntity, decision: PolicyDecision, lead_brief: Dict[str, Any]
) -> str:
    """Generate a draft reply based on the message and extracted entities."""
    # --- deterministically updated hold message ---
    if decision.needs_human or decision.action in ("escalate", "refuse"):
        if decision.action == "refuse":
            return "I can only help with Faisal Hills property enquiries. A member of our team will follow up if needed."
        return "Thank you for your message. A member of our team will review it and reply personally."

    else:
        if entities.side == "BUY" and entities.size_marla and entities.block_code:
            return (
                f"Thank you for your interest in a {entities.size_marla} marla plot in Block {entities.block_code}. "
                f"Our current market rates for similar properties are available upon request."
            )
        elif entities.side == "SELL" and entities.size_marla and entities.block_code:
            return (
                f"Thank you for offering to sell a {entities.size_marla} marla plot in Block {entities.block_code}. "
                f"We will review your property and get back to you with a valuation."
            )
        else:
            return "Thank you for your message. We will get back to you shortly."


def _base_handle_message(
    message: str, lead_id: Optional[str] = None, channel: Optional[str] = None
) -> Dict[str, Any]:
    """
    Handle an incoming message: evaluate policy, extract entities, generate lead brief and draft reply,
    and store lead, message, and audit entries.
    Returns a dictionary with decision, policy reasons, facts used, draft reply, lead brief, and demo flag.
    """
    if not lead_id:
        lead_id = str(uuid.uuid4())

    if not channel:
        channel = "web"

    # Evaluate policy.
    #
    # M6: the decision-layer port (Laya) may contribute a signal, but the
    # signal can only make the decision STRICTER - `evaluate_policy` never
    # de-escalates because of it. On the default path the port returns no
    # signal at all, so this is exactly the pre-M6 behaviour.
    decision = evaluate_policy(message, laya_signals=_fh_decision_signals(message))

    # Stricter: If decision.needs_human is True or action != 'answer',
    # do NOT run market lookup.
    if decision.needs_human or decision.action != 'answer':
        # Need to re-implement the original handle_message logic here
        # or call a safe version of it.
        # Since I can't easily call _original_handle_message directly
        # because I redefined handle_message to be that function,
        # I need to refactor.

        # Insert or update lead
        conn = get_db_connection()
        try:
            # Need to get entities to be able to store the lead correctly
            entities = extract_entities_with_fallback(message)
            # Insert or update lead
            conn.execute(
                """
                INSERT INTO leads (
                    lead_id, channel, phone_hash, language, lead_type, high_intent, needs_human,
                    assigned_agent, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(lead_id) DO UPDATE SET
                    channel=excluded.channel,
                    language=excluded.language,
                    lead_type=excluded.lead_type,
                    high_intent=excluded.high_intent,
                    needs_human=excluded.needs_human,
                    updated_at=datetime('now')
                """,
                (
                    lead_id,
                    channel,
                    "",  # phone_hash (not available)
                    "en", # Simplified language detection for now
                    "buyer" if entities.side == "BUY" else "seller" if entities.side == "SELL" else "other",
                    1 if (entities.price_pkr is not None and entities.size_marla is not None) else 0,
                    1 if decision.needs_human else 0,
                    "",  # assigned_agent
                    "new",
                ),
            )

            # Insert message
            conn.execute(
                """
                INSERT INTO messages (lead_id, message_text, message_timestamp)
                VALUES (?, ?, datetime('now'))
                """,
                (lead_id, message),
            )

            # Insert audit entry
            draft_reply = "Thank you for your message. A member of our team will review it and reply personally."
            if decision.action == "refuse":
                draft_reply = "I can only help with Faisal Hills property enquiries. A member of our team will follow up if needed."

            conn.execute(
                """
                INSERT INTO audit_log (
                    lead_id, step, input_text, output_text, decision_payload, fact_ids_used, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (
                    lead_id,
                    "message_received",
                    message,
                    draft_reply,
                    json.dumps(
                        {
                            "action": decision.action,
                            "reasons": decision.reasons,
                            "risk_tags": decision.risk_tags,
                            "needs_human": decision.needs_human,
                        }
                    ),
                    "[]",  # fact_ids_used
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return {
            "decision": {
                "action": decision.action,
                "reasons": decision.reasons,
                "risk_tags": decision.risk_tags,
                "needs_human": decision.needs_human,
            },
            "policy_reasons": decision.reasons,
            "facts_used": [],
            "draft_reply": draft_reply,
            "lead_brief": {}, # Simplified for now
            "demo": False,
            "needs_human": decision.needs_human,
            # M5 (D-32): the lead_id, so the market layer can correct the
            # audit row the base handler just wrote with the FINAL
            # validated reply.
            "lead_id": lead_id,
        }

    # Extract entities
    entities = extract_entities_with_fallback(message)

    # Generate lead brief and draft reply
    lead_brief = generate_lead_brief(message, entities, decision)
    draft_reply = generate_draft_reply(message, entities, decision, lead_brief)

    # Store lead, message, and audit
    conn = get_db_connection()
    try:
        # Insert or update lead
        conn.execute(
            """
            INSERT INTO leads (
                lead_id, channel, phone_hash, language, lead_type, high_intent, needs_human,
                assigned_agent, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(lead_id) DO UPDATE SET
                channel=excluded.channel,
                language=excluded.language,
                lead_type=excluded.lead_type,
                high_intent=excluded.high_intent,
                needs_human=excluded.needs_human,
                updated_at=datetime('now')
            """,
            (
                lead_id,
                channel,
                "",  # phone_hash (not available)
                lead_brief["language"],
                "buyer" if entities.side == "BUY" else "seller" if entities.side == "SELL" else "other",
                1 if (entities.price_pkr is not None and entities.size_marla is not None) else 0,
                1 if decision.needs_human else 0,
                "",  # assigned_agent
                "new",
            ),
        )

        # Insert message
        conn.execute(
            """
            INSERT INTO messages (lead_id, message_text, message_timestamp)
            VALUES (?, ?, datetime('now'))
            """,
            (lead_id, message),
        )

        # Insert audit entry for message received
        conn.execute(
            """
            INSERT INTO audit_log (
                lead_id, step, input_text, output_text, decision_payload, fact_ids_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                lead_id,
                "message_received",
                message,
                draft_reply,
                json.dumps(
                    {
                        "action": decision.action,
                        "reasons": decision.reasons,
                        "risk_tags": decision.risk_tags,
                        "needs_human": decision.needs_human,
                    }
                ),
                "[]",  # fact_ids_used (empty for now)
            ),
        )

        conn.commit()
    finally:
        conn.close()

    # Prepare response
    return {
        "decision": {
            "action": decision.action,
            "reasons": decision.reasons,
            "risk_tags": decision.risk_tags,
            "needs_human": decision.needs_human,
        },
        "policy_reasons": decision.reasons,
        "needs_human": decision.needs_human,
        "facts_used": [],  # Placeholder for facts used (to be implemented later)
        "draft_reply": draft_reply,
        "lead_brief": lead_brief,
        "demo": False,  # Placeholder for demo flag (to be implemented later)
        # M5 (D-32): the lead_id, so the market layer can correct the
        # audit row the base handler just wrote with the FINAL validated
        # reply.
        "lead_id": lead_id,
        # M4: the extracted entities are returned so that the deterministic
        # market layer can read the size and feature filters from them.
        # Without this the market layer saw `entities = None`, so every
        # filter that is not recoverable from the raw message text (for
        # example "1 kanal", which the extractor resolves to 20 marla) was
        # silently dropped and the question could not be answered.
        "entities": entities,
    }

# FAISAL_HILLS_MARKET_INTEGRATION_V1
#
# Deterministic bridge from the existing production pipeline to the
# privacy-clean Faisal Hills market adapter.
# Qwen is never used as the source of market facts.

import re
from dataclasses import asdict, is_dataclass


def _fh_entity_values(entities):
    if entities is None:
        return {}

    try:
        if is_dataclass(entities):
            data = asdict(entities)
        elif isinstance(entities, dict):
            data = dict(entities)
        else:
            data = dict(vars(entities))
    except Exception:
        return {}

    output = {}

    for key, value in data.items():
        output[str(key).lower()] = value

    return output


def _fh_pick(data, names):
    for name in names:
        key = str(name).lower()
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def _fh_extract_market_filters(message, entities):
    data = _fh_entity_values(entities)

    block = _fh_pick(
        data,
        [
            "block",
            "block_code",
            "block_letter",
            "society_block",
        ],
    )

    size_marla = _fh_pick(
        data,
        [
            "size_marla",
            "marla",
            "plot_size_marla",
            "size",
        ],
    )

    corner = _fh_pick(
        data,
        [
            "corner",
            "is_corner",
        ],
    )

    sun_facing = _fh_pick(
        data,
        [
            "sun_facing",
            "sunface",
            "sun_face",
            "is_sun_facing",
        ],
    )

    ndc_open = _fh_pick(
        data,
        [
            "ndc_open",
            "ndc",
            "is_ndc_open",
        ],
    )

    text = str(message or "").lower()

    # Block fallback from message.
    if block in (None, ""):
        match = re.search(
            r"\bfh[a-z]\b",
            text,
            re.IGNORECASE,
        )
        if match:
            block = match.group(0)

        if block in (None, ""):
            match = re.search(
                r"\bblock\s*([a-z])\b",
                text,
                re.IGNORECASE,
            )
            if match:
                block = match.group(1).upper()

        if block in (None, ""):
            match = re.search(
                r"\b([a-z])\s+block\b",
                text,
                re.IGNORECASE,
            )
            if match:
                block = match.group(1).upper()

    # Size fallback from message.
    if size_marla in (None, ""):
        match = re.search(
            r"\b(\d+(?:\.\d+)?)\s*(?:marla|marlas)\b",
            text,
            re.IGNORECASE,
        )
        if match:
            size_marla = float(match.group(1))

    # Common confirmed dimension mappings.
    if size_marla in (None, ""):
        dimension_map = {
            "25x50": 5,
            "25*50": 5,
            "25-50": 5,
            "30x60": 7,
            "30*60": 7,
            "30-60": 7,
            "35x70": 10,
            "35*70": 10,
            "35-70": 10,
            "40x80": 14,
            "40*80": 14,
            "40-80": 14,
            "50x90": 20,
            "50*90": 20,
            "50-90": 20,
            "75x120": 40,
            "75*120": 40,
            "75-120": 40,
        }

        compact = re.sub(r"\s+", "", text)

        for dimensions, marla in dimension_map.items():
            if dimensions in compact:
                size_marla = marla
                break

    # Feature fallback.
    #
    # A False from the entity extractor is its DEFAULT for "not mentioned",
    # not a request to exclude that feature. The approved master stores
    # `corner` as null (340/374 rows) or True - never False - so passing
    # False through as a filter matched zero rows and made every ordinary
    # price question unanswerable. A feature filter is therefore applied
    # only when the entity says True, or when the message text mentions
    # the feature.
    if corner is False:
        corner = None
    if sun_facing is False:
        sun_facing = None
    if ndc_open is False:
        ndc_open = None

    if corner in (None, ""):
        corner = bool(
            re.search(r"\bcorner\b|\bcomer\b", text)
        ) if re.search(r"\bcorner\b|\bcomer\b", text) else None

    if sun_facing in (None, ""):
        sun_facing = bool(
            re.search(r"\bsun[\s-]?fac(?:e|ing)\b|\bsunface\b", text)
        ) if re.search(
            r"\bsun[\s-]?fac(?:e|ing)\b|\bsunface\b",
            text,
        ) else None

    if ndc_open in (None, ""):
        if re.search(r"\bndc\s+open\b", text):
            ndc_open = True
        elif re.search(r"\bndc\s+(?:close|closed)\b", text):
            ndc_open = False

    if size_marla not in (None, ""):
        try:
            size_marla = float(size_marla)
        except (TypeError, ValueError):
            size_marla = None

    return {
        "block": block,
        "size_marla": size_marla,
        "corner": corner,
        "sun_facing": sun_facing,
        "ndc_open": ndc_open,
    }




def _fh_market_facts_via_lookup(filters):
    """Market facts for the active scope, via the M4 policy-driven lookup.

    M4 replaced the hand-rolled scope filter with a single call into
    ``market.price_lookup``, which owns:
      * the active-block restriction (config/policies.json -> active_blocks)
      * the "not enough data" threshold (min_listings_for_answer)
      * the answer template and the escalation/refusal wording
      * the rule that a parked or unknown block is refused before any row
        is counted

    There is now ONE implementation of the lookup, so the pipeline, the
    console API, the 20-question check and the handoff's price_lookup.py
    wrapper can never drift apart.
    """
    result = _price_lookup.lookup_price(
        block=filters.get("block"),
        size_marla=filters.get("size_marla"),
        corner=filters.get("corner"),
        sun_facing=filters.get("sun_facing"),
        ndc_open=filters.get("ndc_open"),
    )
    return result


def _fh_m9_requirements(message, lead_id=None):
    """The dealer's requirements for this conversation (M9).

    The requirements are the **dealer's own words**, read from the
    messages this lead has already sent, plus the message being handled
    now. They are re-derived from the stored messages on every read
    rather than kept in a separate store, so the state can never drift
    from what the dealer actually said.

    A requirement that was never stated stays ``None``. It is never
    guessed, defaulted, or inferred from the absence of other
    information.

    The read is fail-closed: a lead that cannot be read, a database
    that cannot be opened, or a message table that does not exist all
    produce the same result - no stated requirements, and therefore no
    narrowing. That is the safe direction: an unknown state may not
    remove a verified option.
    """
    try:
        history = _conversation.conversation_requirements(lead_id)
    except Exception:
        history = _qualify.requirements_from_messages([])

    current = _qualify.extract_requirements(message)
    return _qualify.merge_requirements(history, current)


def _fh_m9_decide(message, lead_id=None, filters=None, recommendation=None,
                  policy_action=None, needs_human=False, requirements=None):
    """The next best action for this request (M9).

    The M8 recommendation is the **input**: it is the set of cells the
    approved master covers and that clear the evidence threshold. M9
    narrows that set by what the dealer stated, and then chooses the
    action from the ladder:

        1. an exact verified match       -> quote it
        2. strong verified alternatives  -> offer them
        3. closest verified alternatives -> offer them
        4. a targeted clarifying question -> ask it
        5. human escalation              -> hand it over

    The decision is **application-owned**. The model never chooses the
    action, and the policy is never softened: an escalation or a refusal
    from the policy is the answer, whatever the market layer found.

    Args:
        requirements: the requirements already read for this turn. The
            caller passes the SAME dict the gate used, so the decision
            and the gate that admitted the turn can never see two
            different conversations (M10.1 D-64). When it is ``None`` the
            requirements are read here, exactly as before.

    Returns:
        The decision dict (see ``market.decision.decide``), or ``None``
        when the market layer could not run at all - in which case the
        caller keeps the M8 behaviour unchanged.
    """
    filters = filters or {}
    if requirements is None:
        requirements = _fh_m9_requirements(message, lead_id=lead_id)

    if recommendation is None:
        try:
            recommendation = _recommend.build_recommendations(
                block=filters.get("block"),
                size_marla=filters.get("size_marla"),
                corner=filters.get("corner"),
                sun_facing=filters.get("sun_facing"),
                ndc_open=filters.get("ndc_open"),
                limit=3,
                include_listings=False,
            )
        except Exception:
            # A refusal to recommend, never a reason to invent one.
            return None

    try:
        decision = _decision.decide(
            recommendation,
            requirements,
            policy_action=policy_action,
            needs_human=needs_human,
            # M13: on the conversation path, an intent with nothing
            # stated asks the next most useful question instead of
            # offering cells the dealer never qualified.
            ask_when_nothing_stated=True,
        )
    except Exception:
        return None

    decision["requirements_stated"] = {
        key: value for key, value in (requirements or {}).items()
        if key != "source" and value is not None
    }
    return decision


def _fh_m9_alternatives(decision):
    """The verified alternatives a qualified decision carries.

    Only the options the application verified AND that survived the
    qualification are returned, and each one is marked ``verified: True``
    exactly as M8 marked it. The M6.1 guard and the M5 numeric validator
    read that marker, so a reply may WORD a qualified alternative and
    may never CREATE one.

    A qualified decision that removed an option narrows the reply: an
    option the dealer ruled out is no longer a permitted claim, so
    naming it would be refused by the guard.
    """
    if not isinstance(decision, dict):
        return []

    # M9 D-57: an ANSWERABLE cell needs no alternatives. The dealer
    # asked for a cell the master covers and that clears the threshold,
    # so the reply quotes the price for it. M8 established that rule and
    # the M8 test enforces it, so M9 must not turn the quoted cell into
    # a second "alternative" - the reply would then name the same cell
    # twice, and the fact set would carry a permitted claim the reply
    # never makes.
    if decision.get("action") == _decision.ACTION_QUOTE:
        return []

    options = decision.get("options") or []
    alternatives = []
    for option in options:
        if not isinstance(option, dict):
            continue
        block = option.get("block")
        size = option.get("size_marla")
        if block is None or size is None:
            continue
        alternatives.append({
            "block": block,
            "size_marla": size,
            "reason": option.get("reason"),
            "verified": True,
        })
    return alternatives


def _fh_verified_alternatives(filters, facts):
    """The application's VERIFIED alternatives for a request (M8).

    The alternatives are ranked by ``market/recommend.py`` from the
    approved master, and only cells that clear the same evidence
    threshold the lookup uses are returned. A cell that did not clear
    the threshold is never an alternative - it is a gap, and the gap is
    reported as a thin cell instead.

    The list is attached to the fact set as ``verified_alternatives``,
    each entry marked ``verified: True``. The M6.1 claim guard reads
    that list to decide which (block, size) pairs a reply may name, so
    a reply may mention a verified alternative and may **not** mention
    anything else. The reply never contributes to the list.

    Returns:
        The list of alternatives, or an empty list. A failure is a
        refusal to recommend, never a reason to invent one.
    """
    if not isinstance(facts, dict):
        return []

    # An exact, answerable match needs no alternatives: the dealer
    # gets the price they asked for.
    if facts.get("answerable_for_demo"):
        return []
    try:
        recommendation = _recommend.build_recommendations(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
            limit=3,
            include_listings=False,
        )
    except Exception:
        # The recommendation layer is an enhancement. If it cannot run,
        # the reply simply keeps the current closest-match wording.
        return []

    alternatives = []
    for option in recommendation.get("options") or []:
        alternatives.append({
            "block": option.get("block"),
            "size_marla": option.get("size_marla"),
            "score": option.get("score"),
            "reason": option.get("reason"),
            "verified": True,
        })

    return alternatives


def _fh_active_block_codes():
    """The active block codes, from the single policy configuration.

    M4: the scope used to be hard-coded twice - once in `app/policy.py` and
    once here - while the lookup read `config/policies.json`. A change to
    the configured scope therefore did NOT change what the customer-facing
    path did, which made the configuration misleading. All three now read
    the same file.
    """
    try:
        policies = _price_lookup.load_policies()
        codes = set()
        for configured in policies.get("active_blocks", []):
            canonical = _price_lookup.canonical_block(configured)
            if canonical:
                codes.add(canonical)
        if codes:
            return codes
    except Exception:  # pragma: no cover - config is present in this repo
        pass

    return {"A", "B", "C"}


def _fh_classify_block(value):
    """Classify a requested block against the configured active scope.

    Returns (status, canonical_block):
      ("none", None)        -> no block was named; the answer may span the
                              active blocks
      ("active", "<code>")  -> the named block is inside scope
      ("out_of_scope", None) -> a block was named but it is parked (D,
                             Executive) or unknown, so no lookup may run
    """
    if value is None:
        return ("none", None)

    text = str(value).strip().upper()
    if not text:
        return ("none", None)

    active = _fh_active_block_codes()

    # The ONE alias table lives in the lookup module, so the policy gate,
    # the lookup and this classifier cannot disagree about a block.
    code = _price_lookup.canonical_block(text)

    if code and code in active:
        return ("active", code)

    return ("out_of_scope", None)

def _fh_protected_market_case(message):
    """Whether the message is about a subject the market layer must not touch.

    A payment plan, a booking, an availability claim, a legal question and
    an ownership question are all escalated by the policy, and none of them
    is ever answered with a market figure.

    The check lives here, ONCE, so the price-question test and the
    requirement test (D-64) cannot disagree about what a protected case
    is. Two copies of this list would be two chances to drift.
    """
    text = str(message or "").lower()

    return bool(re.search(
        r"\b(installment|installments|payment|booking|"
        r"availability|available|legal|noc|title|ownership)\b",
        text,
    ))


def _fh_is_market_price_question(message):
    text = str(message or "").lower()

    property_hit = re.search(
        r"\b(plot|marla|kanal|block|fha|fhb|fhc|fhd|fhe|"
        r"corner|sunface|sun-facing|ndc)\b",
        text,
    )

    price_hit = re.search(
        r"\b(price|rate|rates|demand|dem|qeemat|keemat|"
        r"bhao|bhaao|cost|lac|lakh|crore)\b",
        text,
    )

    # M13: a property REQUEST with no price word ("I need a plot") is a
    # market question too - the dealer stated intent, and the next best
    # action for an intent with no requirement is a clarifying question,
    # not a silent hold.
    intent_hit = re.search(
        r"\b(need|needs|want|looking|required|require|searching|"
        r"interested|chahiye)\b",
        text,
    )

    return bool(property_hit and (price_hit or intent_hit)
                and not _fh_protected_market_case(message))


def _fh_format_market_reply(facts):
    if not facts.get("answerable_for_demo"):
        return (
            "I need to confirm the current market information with our team "
            "before giving you a price."
        )

    minimum = facts.get("price_min_pkr")
    median = facts.get("price_median_pkr")
    maximum = facts.get("price_max_pkr")
    count = facts.get("matched_plots")
    observations = facts.get("observation_count")
    latest = facts.get("latest_date")

    parts = [
        (
            f"Based on {count} matching listing"
            f"{'' if count == 1 else 's'}"
            f" and {observations} recorded observation"
            f"{'' if observations == 1 else 's'}"
            " in the current partial Faisal Hills market data, "
        )
    ]

    if minimum is not None and maximum is not None:
        parts.append(
            f"the asking-price range is PKR {minimum:,.0f} to "
            f"PKR {maximum:,.0f}"
        )

    if median is not None:
        parts.append(f", with a median of PKR {median:,.0f}")

    if latest:
        parts.append(f". Latest observation date: {latest}")

    parts.append(
        ". These are dealer asking prices, not confirmed sold prices. "
        "Human approval is required before sending."
    )

    return "".join(parts)


_original_handle_message = _base_handle_message


def handle_message(message: str, lead_id=None, channel=None):
    """Handle one customer message and return the final, validated result.

    M5 (D-32): the reply is validated on EVERY path, not only the market
    path. The market layer runs first; the final step then validates
    whatever reply is about to be returned and records it in the audit
    trail.
    """
    result = _fh_handle_message_market(
        message,
        lead_id=lead_id,
        channel=channel,
    )

    result = _fh_finalize_reply(result, message)

    return result


def _fh_handle_message_market(message: str, lead_id=None, channel=None):
    """The market layer: base pipeline, then the deterministic lookup."""
    result = _original_handle_message(
        message,
        lead_id=lead_id,
        channel=channel,
    )

    result = dict(result)

    # Preserve all existing pipeline behavior first.
    # Then add the deterministic market layer.
    result["needs_human_approval"] = True

    # SAFETY GUARD: if the policy already decided that a human must handle
    # this message (escalate/refuse), the market layer must not attach or
    # render any market facts. The escalated draft reply is kept as-is so
    # no price figure can leak into a reply that a human will answer.
    _policy_action = (result.get("decision") or {}).get("action")
    if result.get("needs_human") or _policy_action in ("escalate", "refuse"):
        result["market_facts"] = None
        result["facts_used"] = []
        result["n"] = 0
        result["level"] = "insufficient"
        return result

    # M10 D-63: the market layer used to be gated on the QUESTION TYPE
    # alone - the sentence needed a price word. A dealer who said "Need
    # 5 marla in Block C." or "My budget is 5 million." never reached
    # the M9 layer, so the requirement in the sentence was silently
    # discarded and no decision was made. The product's own dealer flow
    # starts with a REQUIREMENT, not a price question, so the layer must
    # run whenever the message yields usable market filters.
    #
    # The lookup itself is UNCHANGED: the same scope rules, the same
    # evidence threshold, the same thin-cell protection. A message that
    # yields no filter still runs no lookup, exactly as before.
    #
    # M10.1 D-64: the gate was still too narrow. It asked "does this
    # message yield usable market FILTERS?", and a filter is a block, a
    # size or a feature - a BUDGET IS NOT A FILTER. So "Actually my
    # budget is 12 million." carried a requirement, changed the
    # qualification of the whole conversation, and still never reached
    # the decision layer: no `next_best_action`, no `requirements_stated`,
    # and a generic hold wording the dealer could not act on. The
    # requirement was read from the dealer's own words and then thrown
    # away.
    #
    # The rule now: the layer runs when the message yields usable market
    # FILTERS **or** the CONVERSATION holds a stated requirement that
    # the filters depend on. A budget narrows the same cells a block and
    # a size select, so it is part of the same qualification.
    #
    # The lookup is still untouched: it runs only on the filters, so a
    # requirement-only turn still prices nothing. What the turn now gets
    # is the DECISION, and a reply that agrees with it.
    _market_requirements = _fh_m9_requirements(message, lead_id=lead_id)
    _has_requirement = any(
        _market_requirements.get(key) is not None
        for key in ("budget_min_pkr", "budget_max_pkr", "purpose",
                    "size_marla", "timeline")
    )

    if not _fh_is_market_price_question(message):
        _probe_filters = _fh_extract_market_filters(
            message,
            result.get("entities"),
        )
        _has_filters = any(
            _probe_filters.get(key) not in (None, "")
            for key in ("block", "size_marla", "corner", "sun_facing",
                        "ndc_open")
        )
        if not _has_filters and not _has_requirement:
            result.setdefault("market_facts", None)
            result.setdefault("facts_used", [])
            return result
    # The extracted entities carry the size and feature filters. If the
    # base path did not return them (older code path, or a policy that
    # short-circuits before extraction), fall back to extracting them here
    # so a filter is never silently lost.
    entities = result.get("entities")
    if entities is None:
        try:
            entities = extract_entities_with_fallback(message)
        except Exception:  # pragma: no cover - extraction is best effort
            entities = None

    filters = _fh_extract_market_filters(
        message,
        entities,
    )

    # M10.1 D-64: a turn that states a REQUIREMENT but names no cell of
    # its own still has to be qualified against the conversation it is
    # part of. The block and the size the dealer gave earlier are
    # requirements too - they select the cell the budget is compared
    # with - so they fill the gap when the current message names none.
    #
    # The current message always wins: a turn that names its own block
    # or its own size is the more specific one, and the conversation
    # only fills what the turn left unsaid.
    if _has_requirement:
        if filters.get("block") in (None, ""):
            filters["block"] = _market_requirements.get("block")
        if filters.get("size_marla") in (None, ""):
            filters["size_marla"] = _market_requirements.get("size_marla")

    # M13: a bare property request ("I need a plot") states intent with
    # no requirement yet. The lookup has nothing to search, but the M9
    # decision must still run: its next best action for an intent with
    # no requirement is a clarifying question over the strongest
    # verified cells, not a silent hold.
    _property_request = bool(re.search(
        r"\b(plot|marla|kanal|block)\b", str(message or ""), re.IGNORECASE))
    if not any(
        value not in (None, "")
        for value in filters.values()
    ) and not _has_requirement and not _property_request:
        result["market_facts"] = None
        result["facts_used"] = []
        return result

    # Active-block restriction (v1 scope = Blocks A, B, C). A named block
    # outside A/B/C must not reach the lookup at all, so no parked-block
    # row can be counted, priced, or aggregated.
    _block_status, _requested_block = _fh_classify_block(filters.get("block"))
    if _block_status == "out_of_scope":
        result["market_facts"] = None
        result["facts_used"] = []
        result["n"] = 0
        result["level"] = "insufficient"
        return result

    if _block_status == "active":
        filters["block"] = _requested_block

    # M4: one deterministic lookup, policy-driven, LLM-free.
    market_result = _fh_market_facts_via_lookup(filters)
    facts = market_result.get("facts")

    result["market_facts"] = market_result

    # The lookup returns ``facts = None`` when it declined to run a lookup
    # at all (reply_mode "no_lookup": no block, size or feature filter was
    # usable). There is then nothing to attach, and the customer must not
    # receive a price figure. Before this guard the pipeline raised
    # "TypeError: 'NoneType' object is not subscriptable" on questions such
    # as "What is the price in Block C?" and
    # "What is the price of a 1 kanal plot in Block C?".
    if not facts:
        result["facts_used"] = []
        result["n"] = 0
        result["level"] = "insufficient"
        result["market_answerable"] = False
        result["market_reason"] = market_result.get("reason", "")
        result["draft_reply"] = market_result.get("reply") or (
            "I need to confirm the current market information with our team "
            "before giving you a price."
        )
        # M8: a thin cell has no fact set (M5 D-34 withholds it), so the
        # alternatives are carried in a fact set of their OWN. It holds
        # only the alternative cells the application verified - no price,
        # no count, no raw content - so it cannot become a way to leak
        # a figure the customer path withholds.
        alternatives = _fh_verified_alternatives(filters, {"answerable_for_demo": False})

        # M9: the dealer's requirements narrow the alternatives, and the
        # narrowing decides the NEXT BEST ACTION. The qualified set is
        # what the reply may name, so a cell the dealer's budget ruled
        # out is no longer a permitted claim.
        m9_decision = _fh_m9_decide(
            message,
            lead_id=lead_id,
            filters=filters,
            policy_action=(result.get("decision") or {}).get("action"),
            needs_human=bool(result.get("needs_human")),
            requirements=_market_requirements,
        )
        if m9_decision is not None:
            qualified = _fh_m9_alternatives(m9_decision)
            if qualified:
                alternatives = qualified
            if m9_decision.get("action") == _decision.ACTION_CLARIFY:
                # D-58 / M13: a clarify turn exposes NO option cells -
                # the question is the answer, and the verified cells
                # wait for the turn when the dealer qualified them.
                alternatives = []
            result["next_best_action"] = {
                "action": m9_decision.get("action"),
                "label": m9_decision.get("label"),
                "reason": m9_decision.get("reason"),
                "requires_human_approval": True,
            }
            result["requirements_stated"] = m9_decision.get(
                "requirements_stated") or {}
            # The finalizer needs the decision itself, so the reply can be
            # brought into line with it (M9 D-58).
            result["_fh_m9_decision"] = m9_decision

            # M9 D-61 / D-62: the fact set follows the decision on this
            # path too, so a question is never judged as an answer.
            facts, market_result = _fh_m9_apply_decision_to_facts(
                facts, market_result, m9_decision)
            result["market_facts"] = market_result

        if alternatives:
            result["_fh_market_facts"] = {
                "facts_source": _reply_guard.APPROVED_SOURCE,
                "answerable_for_demo": False,
                "verified_alternatives": alternatives,
            }
            result["verified_alternatives"] = alternatives
        else:
            result["_fh_market_facts"] = None
            result["verified_alternatives"] = []
        # M5 (D-32): the reply changed, so the audit row must be corrected
        # to record the final reply rather than the base hold wording.
        result["_fh_market_filters"] = filters
        result["_fh_reply_changed"] = True
        return result

    result["facts_used"] = [
        {
            "source": facts["facts_source"],
            "type": facts["facts_type"],
            "matched_plots": facts["matched_plots"],
            "observation_count": facts["observation_count"],
            "price_min_pkr": facts["price_min_pkr"],
            "price_median_pkr": facts["price_median_pkr"],
            "price_max_pkr": facts["price_max_pkr"],
            "latest_date": facts["latest_date"],
            "coverage_level": facts["coverage_level"],
            "price_basis": facts.get("price_basis"),
            "is_sold_price": facts.get("is_sold_price"),
        }
    ]

    result["n"] = facts["matched_plots"]
    result["level"] = facts["coverage_level"]

    # M8: the application's VERIFIED alternatives. They are ranked from
    # the approved master by `market/recommend.py`, and only cells that
    # clear the same evidence threshold the lookup uses are included.
    # They are attached to the fact set so the M6.1 claim guard knows
    # which (block, size) pairs a reply is allowed to name.
    alternatives = _fh_verified_alternatives(filters, facts)

    # M9: the requirements narrow the alternatives, and the decision
    # records what the product should do next. The exact cell the dealer
    # asked for is quoted when it clears the threshold and satisfies
    # their stated requirements; otherwise the qualified alternatives
    # are what the reply may name.
    m9_decision = _fh_m9_decide(
        message,
        lead_id=lead_id,
        filters=filters,
        policy_action=(result.get("decision") or {}).get("action"),
        needs_human=bool(result.get("needs_human")),
        requirements=_market_requirements,
    )
    if m9_decision is not None:
        qualified = _fh_m9_alternatives(m9_decision)
        if qualified:
            alternatives = qualified
        if m9_decision.get("action") == _decision.ACTION_CLARIFY:
            # D-58 / M13: a clarify turn exposes NO option cells.
            alternatives = []
        result["next_best_action"] = {
            "action": m9_decision.get("action"),
            "label": m9_decision.get("label"),
            "reason": m9_decision.get("reason"),
            "requires_human_approval": True,
        }
        result["requirements_stated"] = m9_decision.get(
            "requirements_stated") or {}
        # The finalizer needs the decision itself, so the reply can be
        # brought into line with it (M9 D-58).
        result["_fh_m9_decision"] = m9_decision

        # M9 D-61 / D-62: the fact set is brought into line with the
        # decision BEFORE the reply is worded and BEFORE the two final
        # gates run. A cell the dealer's own budget excluded must not
        # be quoted, and a question must not be judged as an answer.
        facts, market_result = _fh_m9_apply_decision_to_facts(
            facts, market_result, m9_decision)
        result["market_facts"] = market_result

    if alternatives:
        facts["verified_alternatives"] = alternatives
        result["verified_alternatives"] = alternatives
    else:
        result["verified_alternatives"] = []

    # M4: the reply comes from the policy template, so every number in it
    # comes from the lookup result and never from the LLM.
    #
    # M9 D-61: the reply is taken from the market result, which the M9
    # decision may have re-rendered. The lookup's own wording is used
    # when there is no result, so the M4 behaviour is unchanged.
    result["draft_reply"] = market_result.get("reply") or _fh_format_market_reply(facts)
    result["market_answerable"] = market_result.get("answerable", False)
    result["market_reason"] = market_result.get("reason", "")

    # M5 (D-32): the reply is validated in ONE place - `_fh_finalize_reply`
    # - so that every customer-facing path is covered, not only this one.
    # The market layer only records WHAT it did, so the finalizer knows
    # that the audit row must be corrected.
    result["_fh_market_facts"] = facts
    result["_fh_market_filters"] = filters
    result["_fh_reply_changed"] = True

    return result


def _fh_m9_apply_decision_to_facts(facts, market_result, decision):
    """Bring the fact set into line with the M9 decision (D-61, D-62).

    M9 D-61: the decision removed the exact cell because it conflicted
    with a stated requirement, but the reply still quoted that cell's
    price. The decision and the reply disagreed, and the reply is the
    part the dealer reads.

    The cause was that the M9 decision narrowed the ALTERNATIVES while
    the answerable path kept the lookup's own price wording. The
    numbers still traced to the master and the claims still matched the
    evidence - so both final gates passed it. Neither gate can see a
    *policy* conflict, because a budget is not a fact: only the
    application knows the cell is outside what the dealer said they
    could pay.

    So the application withdraws the price itself. When the decision
    excluded the exact cell, the fact set stops being answerable: the
    price fields are withheld and the cell is reported the way a THIN
    cell is reported - with no price, and with the verified
    alternatives the decision kept. The reply then carries the
    decision's answer (the alternatives, or the question) instead of a
    price for a cell the dealer ruled out.

    M9 D-62: the same applies to a question. A clarifying question
    carries no price and no count, so it must not be judged as an
    ANSWERABLE reply - the M6.1 guard would demand the three
    answerable provenance markers and refuse it for "losing"
    provenance it never had. The fact set is put into the insufficient
    state, which is the state a question belongs to.

    Returns the updated (facts, market_result) pair. The facts are
    updated IN PLACE, because the pipeline, the validator and the guard
    all read the same dict.
    """
    if not isinstance(facts, dict):
        return facts, market_result
    if not isinstance(decision, dict):
        return facts, market_result

    action = decision.get("action")

    # -- D-62: a question is not an answer ------------------------------
    # The question carries no figure, so the fact set must not be in
    # the answerable state when the guard judges it.
    if action == _decision.ACTION_CLARIFY:
        facts["answerable_for_demo"] = False
        facts["trust_status"] = "requirements_unmet"
        facts["reply_mode"] = "insufficient_data"
        for key in (
            "price_min_pkr",
            "price_median_pkr",
            "price_max_pkr",
        ):
            facts[key] = None
        if isinstance(market_result, dict):
            market_result["answerable"] = False
            market_result["reply_mode"] = "insufficient_data"
            summary = market_result.get("summary")
            if isinstance(summary, dict):
                summary["answerable_for_demo"] = False
                summary["trust_status"] = "requirements_unmet"
                for key in (
                    "price_min_pkr",
                    "price_median_pkr",
                    "price_max_pkr",
                ):
                    summary[key] = None
        return facts, market_result

    # -- D-61: a cell the dealer ruled out is not answerable ------------
    if not decision.get("exact_excluded"):
        return facts, market_result

    facts["answerable_for_demo"] = False
    facts["trust_status"] = "requirements_unmet"
    facts["reply_mode"] = "insufficient_data"
    for key in (
        "price_min_pkr",
        "price_median_pkr",
        "price_max_pkr",
    ):
        facts[key] = None
    # The counts belong to the cell that is no longer answerable, so
    # they are withheld with it.
    facts["matched_plots"] = 0
    facts["observation_count"] = 0

    if isinstance(market_result, dict):
        market_result["answerable"] = False
        market_result["reply_mode"] = "insufficient_data"
        summary = market_result.get("summary")
        if isinstance(summary, dict):
            summary["answerable_for_demo"] = False
            summary["trust_status"] = "requirements_unmet"
            summary["matched_plots"] = 0
            summary["observation_count"] = 0
            for key in (
                "price_min_pkr",
                "price_median_pkr",
                "price_max_pkr",
            ):
                summary[key] = None

    # The reply is re-rendered from the updated fact set. The lookup owns
    # that wording (``price_lookup.render_reply``), so re-rendering it
    # here produces EXACTLY the wording the product uses for a cell that
    # is not answerable: the deferral, the closest match, and no price.
    # Without this the reply kept the price wording rendered BEFORE the
    # withdrawal, and the M5 validator - correctly - blocked it.
    if isinstance(market_result, dict):
        try:
            market_result["reply"] = _price_lookup.render_reply(
                False,
                facts,
                reason="the stated requirements exclude this cell",
                answer_policy=_price_lookup.load_policies().get(
                    "answer_policy"),
            )
        except Exception:
            # A failure to re-render is never a reason to keep a price
            # the dealer's own requirement excluded. The fact set has
            # already been withdrawn, so the worst case is a reply the
            # validator blocks - which is the safe direction.
            market_result["reply"] = (
                "I need to confirm the current market information with our "
                "team before giving you a price."
            )

    return facts, market_result


def _fh_m9_clarifying_reply(decision, base_reply):
    """The reply that ASKS the clarifying question (M9).

    M9 D-58: the decision chose ``ask_clarifying_question`` but the
    reply was still the M8 "here are the alternatives" wording, so the
    product asked a question and then immediately offered the very
    options the question was meant to narrow - including the options
    the dealer's own budget had already ruled out. The decision and the
    reply disagreed, and the reply was the one the dealer read.

    The wording is the APPLICATION's own. The question text comes from
    the M9 decision, which comes from the requirements the DEALER
    stated. No figure is introduced: a question carries no price, no
    count and no size, so the M5 numeric validator and the M6.1 claim
    guard both still hold.

    The hand-off is kept, because a clarifying question is never the
    end of the conversation - a member of the team still reviews every
    reply.
    """
    if not isinstance(decision, dict):
        return base_reply
    if decision.get("action") != _decision.ACTION_CLARIFY:
        return base_reply

    question = decision.get("clarifying_question")
    if not isinstance(question, dict):
        return base_reply
    text = (question.get("question") or "").strip()
    if not text:
        return base_reply

    return (
        "I need to confirm the current market information with our team "
        "before giving you a price. %s Human approval is required before "
        "sending." % text
    )


def _fh_finalize_reply(result, message):
    """Validate the final reply and record it in the audit trail.

    This is the single point through which every customer-facing reply
    passes. It:

    1. works out which numbers are permitted - the market fact set when
       the market layer produced one, plus the customer's own parsed
       figures (their size in marla) as the context;
    2. validates the reply against them;
    3. blocks the reply and escalates to a human when a number does not
       trace (RULES_SHORT #2, RULES_SHORT #3);
    4. records the FINAL validated reply - with its validation outcome -
       in the audit trail.
    """
    facts = result.get("_fh_market_facts")
    filters = result.get("_fh_market_filters") or {}

    context = _fh_reply_context(result, filters)

    # M6: the customer-model port phrases the reply. It runs AFTER the
    # application has decided and calculated, and BEFORE the M5 validation
    # below, so a model reply is validated exactly like any other reply.
    # The port may only change the WORDING; it can never supply a fact.
    result = _fh_phrase_reply(result, facts, filters)

    # M9: when the decision is to ASK, the reply must ask - and it must
    # ask INSTEAD of offering the options, not on top of them.
    #
    # This runs AFTER the port, because the port appends the verified
    # alternatives to the reply. Applying the question before the port
    # left the alternatives attached to it, so the dealer read a
    # question immediately followed by the very options the question
    # was meant to narrow - including options the dealer's own budget
    # had already ruled out (D-59).
    #
    # The application's decision is the LAST word on the wording, which
    # is the correct authority order: the model may only word what the
    # application decided. The wording carries no figure, so both final
    # gates still apply to it.
    m9_decision = result.get("_fh_m9_decision")
    if m9_decision is not None:
        asking = _fh_m9_clarifying_reply(
            m9_decision, result.get("draft_reply") or "")
        if asking != (result.get("draft_reply") or ""):
            result["draft_reply"] = asking
            result["_fh_reply_changed"] = True

        # M13: the conversational property-options layer. When the
        # decision is to QUOTE or to OFFER, the draft gains the
        # professional options section - the closest recorded option,
        # up to three alternatives with reasons and trade-offs, and the
        # next clarifying question. The section names only the
        # (block, size) pairs this decision verified and carries no
        # figure >= 1000, so the M5 validator and the M6.1 guard judge
        # the whole reply with unchanged rules. A CLARIFY decision keeps
        # D-58's question-only wording, and an escalated or refused turn
        # never reaches this layer.
        if m9_decision.get("action") in (
                _decision.ACTION_QUOTE, _decision.ACTION_OFFER):
            try:
                _fh_attach_property_options(
                    result, message, m9_decision, facts, filters)
            except Exception:
                # The conversational layer is an enhancement: a failure
                # never changes a reply the application already decided.
                pass

    result.update(
        _fh_enforce_traceability(result, facts, filters, context=context)
    )

    # M6.1: the claim guard is the SECOND final gate. The M5 validator
    # checks the NUMBERS; this one checks the CLAIM SHAPE - scope,
    # availability, certainty, sold prices and provenance markers. A
    # reply can pass the numeric validator and still assert something
    # the approved master does not support ("Yes, we have 5 marla plots
    # in Block C" on a cell the application already refused to answer).
    # The guard runs on every path, exactly like the numeric validator,
    # and it is authoritative: a reply it rejects never reaches the
    # customer.
    result.update(
        _fh_enforce_claim_guard(result, facts, filters, context=context)
    )

    # The audit trail must record the FINAL reply, not the pre-market
    # hold wording the base handler wrote. It is corrected whenever the
    # market layer changed the reply, and whenever the reply was blocked
    # (a blocked reply is also a final reply, and the operator needs to
    # see that it was withheld and why).
    reply_changed = bool(result.get("_fh_reply_changed"))
    blocked = bool(result.get("traceability_blocked"))

    if reply_changed or blocked:
        result["audit"] = _fh_record_validated_reply(result, facts, filters)

    # The internal keys are not part of the public result.
    result.pop("_fh_market_facts", None)
    result.pop("_fh_market_filters", None)
    result.pop("_fh_reply_changed", None)
    result.pop("_fh_m9_decision", None)

    return result


def _fh_phrase_reply(result, facts, filters):
    """Run the reply through the replaceable customer-model port.

    M6 (FH-02 section 6 M6). The port is a **phrasing** port: the
    application has already decided, looked up and calculated, and the fact
    set is handed to the port read-only. The port may choose how the facts
    are worded; it may not supply, alter or invent a number, may not widen
    the scope, and may not skip validation - the M5 validator is still the
    final gate and still runs on every path.

    The default implementation is the deterministic template, which
    reproduces the existing wording exactly, so the default path's
    behaviour is unchanged. Any other implementation is selected by
    environment variables alone.

    A failure of a non-default implementation falls back to the
    deterministic template; the fallback is reported, never hidden.
    """
    base_reply = result.get("draft_reply") or ""

    # A message that the policy escalated or refused must keep the
    # application's own hold wording. The port does not get to soften a
    # refusal into something that reads like an answer.
    decision = result.get("decision")
    action = decision.get("action") if isinstance(decision, dict) else None
    if action in ("escalate", "refuse") or result.get("needs_human"):
        return result

    # Only a market reply is phrased. A non-market reply is the base
    # pipeline's own wording, which is already validated.
    if not facts:
        return result

    filters = filters or {}
    outcome = _customer_model.phrase_reply(
        facts=facts,
        base_reply=base_reply,
        block=filters.get("block"),
        size_marla=filters.get("size_marla"),
    )

    reply = outcome.get("reply")
    if reply:
        result["draft_reply"] = reply
        result["_fh_reply_changed"] = True

    result["reply_source"] = outcome.get("reply_source")
    result["customer_model"] = {
        "implementation": outcome.get("implementation"),
        "reply_source": outcome.get("reply_source"),
        "fell_back": bool(outcome.get("fell_back")),
    }
    if outcome.get("error"):
        result["customer_model"]["error"] = outcome.get("error")

    return result


def _fh_attach_property_options(result, message, decision, facts, filters):
    """M13: attach the conversational property-options layer.

    The customer draft gains the professional options section - the
    closest recorded option, up to three alternatives with the reasons
    and trade-offs, and the next clarifying question - built ONLY from
    the approved inventory rows and phrased within what this turn's
    decision already verified (the quoted cell plus the decision's
    alternative cells). The operator additionally receives the full
    plot-level structure - plot numbers, price bands, scores, per-option
    reasons and trade-offs - as ``property_options``, so the reasoning
    behind every recommendation is visible and nothing is hidden behind
    a score.
    """
    if not isinstance(facts, dict):
        return

    requirements = decision.get("requirements_stated") or {}
    intent = _property_matcher.extract_intent(
        message, requirements=requirements)
    # The filters the lookup actually ran on are authoritative for the
    # cell this turn is about; the conversation fills only the gaps.
    if not intent.get("block"):
        intent["block"] = filters.get("block")
    if intent.get("size_marla") is None:
        intent["size_marla"] = filters.get("size_marla")

    match = _property_matcher.match_properties(
        intent,
        cells=[(a.get("block"), a.get("size_marla"))
               for a in facts.get("verified_alternatives") or []],
    )

    permitted = []
    if (decision.get("action") == _decision.ACTION_QUOTE
            and filters.get("block")):
        permitted.append((filters.get("block"), filters.get("size_marla")))
    for alternative in facts.get("verified_alternatives") or []:
        permitted.append((alternative.get("block"),
                          alternative.get("size_marla")))

    section = _property_matcher.conversational_section(match, permitted)

    # --- pilot features: qualification + founder-controlled site visits
    result["lead_qualification"] = _fh_qualification_view(
        result, message, intent, decision)
    section, visit = _fh_site_visit_step(result, message, section, intent)
    result["site_visit"] = visit
    if section:
        base = result.get("draft_reply") or ""
        # P1 (M12.4 review): one question per reply. When the M13
        # section carries the targeted clarifying question, the base
        # template's own trailing ask is stale - it asks for what the
        # dealer may have just stated - so it is suppressed and the M13
        # question is the reply's single ask. When the section carries
        # NO question, the base ask stays exactly as before. The
        # site-visit flow has the same rule: its offer or its request
        # confirmation carries the reply's single ask, so the base ask
        # yields to it as well.
        if ("To narrow this down:" in section or visit.get("offered")
                or visit.get("requested")):
            base = _property_matcher.suppress_base_question(base)
        result["draft_reply"] = base + ("\n" if base else "") + section
        result["_fh_reply_changed"] = True
    result["property_options"] = match


def _fh_qualification_view(result, message, intent, decision):
    """Pilot feature 1: the lead qualification view for this turn.

    Deterministic and transparent: the score, temperature, stage
    suggestion, known/missing requirements and the recommended next
    action, all computed by ``market.lead_qualification`` from what the
    dealer actually stated. Attached as ``lead_qualification`` for the
    operator and the founder pipeline report.
    """
    lead_key = str(result.get("lead_id") or result.get("session_id") or "")
    turns = 0
    if lead_key:
        try:
            from market import conversation_log as _clog
            turns = len(_clog.ConversationLog().transcript(lead_key))
        except Exception:
            turns = 0
    return _lead_qualification.qualification_view(
        requirements=intent,
        message=message,
        turns=turns,
        escalated=bool(result.get("needs_human")),
        has_visit_request=_site_visit.has_request_for_lead(lead_key),
    )


def _fh_site_visit_step(result, message, section, intent):
    """Pilot feature 2: the founder-controlled site-visit flow.

    HOT lead or an explicit visit ask -> propose the founder-approved
    slots (digits-free customer text; one ask per reply). A clear slot
    choice -> record the request for founder approval. The reply never
    confirms a visit, never claims plot availability and never shares a
    contact.
    """
    visit = {"offered": False, "requested": False, "request_id": None,
             "slots_offered": 0}
    lead_key = str(result.get("lead_id") or result.get("session_id") or "")
    qual = result.get("lead_qualification") or {}
    temperature = qual.get("temperature") or "COLD"
    if not lead_key:
        return section, visit

    chosen = _site_visit.detect_choice(message)
    if chosen is not None:
        summary = (
            "Requirements: %s; lead score %s (%s); the dealer selected "
            "this visit slot." % (
                json.dumps(qual.get("known_requirements") or {},
                           ensure_ascii=False),
                qual.get("score"), temperature))
        request = _site_visit.create_request(
            lead_key, chosen, intent, temperature,
            int(qual.get("score") or 0), summary)
        visit.update({"requested": True,
                      "request_id": request["request_id"]})
        qual["stage_suggestion"] = "SITE_VISIT_REQUESTED"
        day = _site_visit._weekday(request.get("selected_slot_date", ""))
        appendix = (
            "I have recorded your site-visit request for %s; the founder "
            "will approve it and the team will confirm the details with "
            "you personally." % (day or "the day you chose"))
        return _strip_section_question(section) + "\n" + appendix, visit

    if ((temperature == "HOT"
         or _lead_qualification.visit_interest_in(message))
            and not _site_visit.has_request_for_lead(lead_key)):
        offer = _site_visit.offer_sentence()
        if offer:
            visit["offered"] = True
            visit["slots_offered"] = len(_site_visit.available_slots())
            return _strip_section_question(section) + "\n" + offer, visit
    return section, visit


def _strip_section_question(section: str) -> str:
    """One ask per reply: when the visit offer or the request
    confirmation carries the reply's single ask, the section's own
    clarifying question is removed."""
    return re.sub(r"\s*To narrow this down:.*?(?=These are recorded)",
                  " ", section, flags=re.DOTALL).strip()


def _fh_reply_context(result, filters):
    """The numbers the customer supplied, which a reply may echo back.

    The dealer's own size in marla is a stored fact (it was parsed out of
    their message), so a reply that repeats it is not inventing anything.
    Two sizes are collected, because the base pipeline and the market
    layer can resolve a size differently - "1 kanal" is 20 marla to the
    market layer, and the entity extractor may have produced a different
    figure - and a legitimate reply must not be blocked over it.
    """
    context = {}

    size = filters.get("size_marla")
    if size is not None:
        context["size_marla"] = size

    entities = result.get("entities")
    if entities is not None:
        entity_size = getattr(entities, "size_marla", None)
        if entity_size is None and isinstance(entities, dict):
            entity_size = entities.get("size_marla")
        if entity_size is not None and entity_size not in (None, ""):
            try:
                context.setdefault("size_marla", float(entity_size))
            except (TypeError, ValueError):
                pass
            try:
                context["entity_size_marla"] = float(entity_size)
            except (TypeError, ValueError):
                pass

    return context


def _fh_record_validated_reply(result, facts, filters):
    """Correct the audit row so it records the final validated reply.

    The base handler wrote one `audit_log` row for this message with the
    PRE-market hold wording. This updates that row so that:

      * ``output_text`` is the reply the customer actually received (or
        the hold wording, if the reply was blocked);
      * ``decision_payload`` keeps the base decision fields and gains the
        M5 evidence (traceability outcome, reply mode, answerability, the
        filter, the fact provenance);
      * ``fact_ids_used`` names the facts the reply was built from.

    Returns a small dict describing what was recorded. A write failure is
    reported, never raised: losing the audit correction must not lose
    the reply.
    """
    reply = result.get("draft_reply") or ""
    traceability = result.get("traceability") or {}
    filters = filters or {}

    fact_ids = []
    if facts:
        cell = "%s/%s" % (filters.get("block"), filters.get("size_marla"))
        for name in (
            "matched_plots",
            "observation_count",
            "price_min_pkr",
            "price_median_pkr",
            "price_max_pkr",
            "latest_date",
        ):
            fact_ids.append("market:%s:%s" % (cell, name))

    market_facts = result.get("market_facts")
    reply_mode = (
        market_facts.get("reply_mode")
        if isinstance(market_facts, dict)
        else None
    )

    evidence = {
        "reply_validated": True,
        "traceability_ok": traceability.get("ok"),
        "traceability_blocked": bool(result.get("traceability_blocked")),
        "traceability_numbers_found": traceability.get("numbers_found"),
        "traceability_allowed_count": traceability.get("allowed_count"),
        "traceability_reason": traceability.get("reason"),
        # M6.1: the claim guard's verdict is recorded next to the numeric
        # validator's, so the audit trail shows that BOTH final gates ran
        # and what each of them decided.
        "claim_guard_ok": result.get("claim_guard_ok"),
        "claim_guard_blocked": bool(result.get("claim_guard_blocked")),
        "claim_guard_state": (result.get("claim_guard") or {}).get("state"),
        "claim_guard_violations": (result.get("claim_guard") or {}).get("violations"),
        "reply_mode": reply_mode,
        "market_answerable": result.get("market_answerable"),
        # M6: which customer-model implementation produced the wording.
        "reply_source": result.get("reply_source") or "deterministic_template",
        "customer_model": result.get("customer_model"),
        "market_filters": {
            "block": filters.get("block"),
            "size_marla": filters.get("size_marla"),
            "corner": filters.get("corner"),
            "sun_facing": filters.get("sun_facing"),
            "ndc_open": filters.get("ndc_open"),
        },
        "facts_source": (facts or {}).get("facts_source"),
        "matched_plots": (facts or {}).get("matched_plots"),
        "observation_count": (facts or {}).get("observation_count"),
        "latest_date": (facts or {}).get("latest_date"),
    }

    lead_id = result.get("lead_id")

    try:
        conn = get_db_connection()
    except Exception as exc:  # pragma: no cover - the DB is always present
        return {"recorded": False, "error": str(exc)}

    try:
        row = conn.execute(
            """
            SELECT audit_id, decision_payload FROM audit_log
            WHERE lead_id = ? AND step = 'message_received'
            ORDER BY audit_id DESC LIMIT 1
            """,
            (lead_id,),
        ).fetchone()

        if row is None:
            return {
                "recorded": False,
                "error": "no audit row found for this message",
            }

        try:
            payload = json.loads(row["decision_payload"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        # The base decision fields are PRESERVED; the M5 evidence is
        # ADDED. The row records the whole decision, not just its last
        # step.
        payload.update(evidence)

        conn.execute(
            """
            UPDATE audit_log
            SET output_text = ?, decision_payload = ?, fact_ids_used = ?
            WHERE audit_id = ?
            """,
            (
                reply,
                json.dumps(payload, sort_keys=True),
                json.dumps(fact_ids),
                row["audit_id"],
            ),
        )
        conn.commit()
    except Exception as exc:  # pragma: no cover - best effort by design
        return {"recorded": False, "error": str(exc)}
    finally:
        conn.close()

    return {
        "recorded": True,
        "step": "message_received",
        "traceability_ok": evidence["traceability_ok"],
        "fact_ids_used": len(fact_ids),
    }


def _fh_enforce_claim_guard(result, facts, filters, context=None):
    """Check the reply's CLAIM SHAPE against the approved fact set.

    M6.1. The M5 validator (``market/fact_validator.py``) checks the
    NUMBERS in a reply. This checks the CLAIMS: the scope the reply
    names, the sizes it asserts, whether it claims stock exists, whether
    it claims certainty or a sold price, and whether it kept the
    provenance markers the product depends on.

    The two gates are complementary, and the second one is not
    redundant. Measured against the approved master before this function
    was written, these replies all passed the M5 numeric validator:

      * "Yes, we have 5 marla plots in Block C." - the only number (5) is
        the customer's own size, which the validator deliberately
        permits;
      * "we also have 10 marla plots" - 10 is a permitted number
        because the approved observation date is 2026-10-07;
      * "we also have plots in Block D" - no number at all, so the
        numeric validator cannot see the scope violation.

    Returns the fields to merge into the pipeline result:

    * ``claim_guard`` - the guard's report, so the console and the audit
      trail can show *why* a reply was allowed or blocked;
    * ``claim_guard_ok`` - ``True`` when every claim is supported;
    * ``claim_guard_blocked`` - ``True`` when the reply was blocked.

    When a claim is not supported the reply is replaced with the same
    human-hold wording the numeric validator uses, the market facts are
    detached, and ``needs_human`` is raised with the reason
    ``unsupported_claim_in_draft``. A blocked claim and a blocked number
    are indistinguishable to the customer, which is the intended
    outcome.
    """
    reply = result.get("draft_reply") or ""
    filters = filters or {}

    decision = result.get("decision")
    action = decision.get("action") if isinstance(decision, dict) else None

    market_facts = result.get("market_facts")
    reply_mode = (
        market_facts.get("reply_mode") if isinstance(market_facts, dict) else None
    )

    report = _reply_guard.guard_reply(
        reply,
        facts,
        filters=filters,
        context=context or {},
        action=action,
        reply_mode=reply_mode,
    )

    payload = {
        "ok": report.ok,
        "state": report.state,
        "action": report.action,
        "violations": report.violations,
    }

    if report.ok:
        return {
            "claim_guard": payload,
            "claim_guard_ok": True,
            "claim_guard_blocked": False,
        }

    # The reply carries a claim the approved data does not support.
    # Block it and hand the message to a human.
    result["draft_reply"] = (
        "Thank you for your message. A member of our team will review it "
        "and reply personally."
    )
    result["market_facts"] = None
    result["facts_used"] = []
    result["n"] = 0
    result["level"] = "insufficient"
    result["market_answerable"] = False
    result["market_reason"] = (
        "The reply made a claim the approved market data does not support."
    )
    result["needs_human"] = True
    result["needs_human_approval"] = True
    if isinstance(decision, dict):
        decision["needs_human"] = True
        reasons = list(decision.get("reasons") or [])
        if "unsupported_claim_in_draft" not in reasons:
            reasons.append("unsupported_claim_in_draft")
        decision["reasons"] = reasons
        decision["action"] = "escalate"

    return {
        "claim_guard": payload,
        "claim_guard_ok": False,
        "claim_guard_blocked": True,
    }


def _fh_enforce_traceability(result, facts, filters, context=None):
    """Validate the draft reply's numbers against the fact set.

    Returns the fields to merge into the pipeline result:

    * ``traceability`` - the validator's report, so the console and the audit
      trail can show *why* a reply was allowed or blocked.
    * ``traceability_ok`` - ``True`` when every number traces to a fact.
    * ``traceability_blocked`` - ``True`` when the reply was blocked.

    When a number does not trace, the customer-facing reply is replaced with
    the existing human-hold wording, the market facts are detached, and
    ``needs_human`` is raised. The reply is never sent with an unsupported
    number in it.

    M5 (D-32): the reply is validated on every path, so ``facts`` may be
    ``None`` (a non-market question). In that case the validator is
    **fail-closed**: only the numbers the customer supplied are permitted,
    and any other number is blocked.
    """
    reply = result.get("draft_reply") or ""
    if context is None:
        context = {}
        if filters:
            size = filters.get("size_marla")
            if size is not None:
                context["size_marla"] = size

    validation = _fact_validator.validate_reply(reply, facts, context=context)

    report = {
        "ok": validation.ok,
        "untraceable": [
            {"text": raw, "value": value} for raw, value in validation.untraceable
        ],
        "numbers_found": len(validation.numbers),
        "allowed_count": validation.allowed_count,
        "reason": validation.reason,
    }

    if validation.ok:
        return {
            "traceability": report,
            "traceability_ok": True,
            "traceability_blocked": False,
        }

    # The reply carries a number that does not trace to an approved fact.
    # Block it and hand the message to a human.
    result["draft_reply"] = (
        "Thank you for your message. A member of our team will review it "
        "and reply personally."
    )
    result["market_facts"] = None
    result["facts_used"] = []
    result["n"] = 0
    result["level"] = "insufficient"
    result["market_answerable"] = False
    result["market_reason"] = validation.reason
    result["needs_human"] = True
    result["needs_human_approval"] = True
    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["needs_human"] = True
        reasons = list(decision.get("reasons") or [])
        reasons.append("untraceable_number_in_draft")
        decision["reasons"] = reasons
        decision["action"] = "escalate"

    return {
        "traceability": report,
        "traceability_ok": False,
        "traceability_blocked": True,
    }

