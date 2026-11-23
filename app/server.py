import os
import json
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Request, status, Body
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from app.pipeline import handle_message
from data.db import get_db_connection, init_db
from market import price_lookup
from market import fact_guard
from market import evidence as _evidence
from market import review as _review
from market import recommend as _recommend
from market import qualify as _qualify
from market import decision as _decision
from market import conversation as _conversation

# Initialize the database on startup
def init_app_db():
    conn = get_db_connection()
    try:
        init_db(conn)
    finally:
        conn.close()

# Create the FastAPI app
app = FastAPI(title="Faisal Hills AI Lead Desk Console")

# Security: HTTP Basic for optional password
security = HTTPBasic(auto_error=False)

# Optional password from environment variable
CONSOLE_PASSWORD = os.getenv("CONSOLE_PASSWORD")

def get_current_username(credentials: Optional[HTTPBasicCredentials] = Depends(security)):
    if CONSOLE_PASSWORD is None:
        # If no password set, allow access without credentials
        return "user"
    if credentials.username == "admin" and credentials.password == CONSOLE_PASSWORD:
        return credentials.username
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Basic"},
    )

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Health check endpoint
@app.get("/health")
def health_check():
    return {"status": "ok"}

# Message handling endpoint
@app.post("/api/message")
def handle_message_endpoint(
    message: str,
    lead_id: Optional[str] = None,
    channel: Optional[str] = None,
    username: str = Depends(get_current_username)
):
    # Process the message through the pipeline
    result = handle_message(message, lead_id=lead_id, channel=channel)

    # M5 (D-32): the pipeline already validated the REPLY (M5 task 1).
    # The response also carries the raw fact sets, which are factual
    # numbers on a customer-facing surface, so they are guarded here
    # too. A fact set that does not match the approved master is
    # detached and the message is escalated - the same behaviour the
    # pipeline applies to an untraceable reply.
    guard_report = _guard_market_facts(result)

    return {
        "decision": result["decision"],
        "policy_reasons": result["policy_reasons"],
        "facts_used": result["facts_used"],
        "draft_reply": result["draft_reply"],
        "lead_brief": result["lead_brief"],
        "demo": result["demo"],
        # M4: the deterministic market result, so the console can show
        # the evidence behind the answer.
        "market_facts": result.get("market_facts"),
        "market_answerable": result.get("market_answerable"),
        "market_reason": result.get("market_reason"),
        # M5: the traceability report, so the console can show *why* a
        # reply was allowed (every number traces to an approved fact) or
        # blocked (a number did not trace, so a human takes over).
        "traceability": result.get("traceability"),
        "traceability_ok": result.get("traceability_ok"),
        "traceability_blocked": result.get("traceability_blocked"),
        # M6.1: the claim guard's report, so the console can show *why*
        # a reply was allowed (every claim traces to the approved data)
        # or blocked (a claim was not supported, so a human takes over).
        "claim_guard": result.get("claim_guard"),
        "claim_guard_ok": result.get("claim_guard_ok"),
        "claim_guard_blocked": result.get("claim_guard_blocked"),
        "needs_human": result.get("needs_human"),
        "needs_human_approval": result.get("needs_human_approval"),
        # M5 (D-32): the guard report for the served fact set.
        "guard": guard_report,
    }


def _guard_market_facts(result):
    """Validate the served fact set against the approved master.

    Returns the guard report. When the fact set does not verify, the
    fact set is detached from the response, the reply becomes the hold
    wording, and the message is escalated to a human - the identical
    behaviour the pipeline applies to an untraceable reply, so a
    customer can never be shown a figure the master does not support.
    """
    market_facts = result.get("market_facts")
    if not isinstance(market_facts, dict):
        return fact_guard.public_report(
            ok=True,
            label="message",
            reason="No market fact set was served.",
        )

    facts = market_facts.get("facts")
    filters = market_facts.get("filters") or {}

    allowed = fact_guard.allowed_numbers_for(
        block=filters.get("block"),
        size_marla=filters.get("size_marla"),
        corner=filters.get("corner"),
        sun_facing=filters.get("sun_facing"),
        ndc_open=filters.get("ndc_open"),
    )

    # The lead brief carries the customer's OWN figures (their stated
    # budget, their size) and the system timestamp. They are not market
    # facts, so they are permitted through the validator's context
    # mechanism - the same one that lets a reply echo the size back.
    # Nothing here widens the market-fact set: a wrong market figure is
    # still blocked.
    context = {}
    entities = result.get("entities")
    entity_size = getattr(entities, "size_marla", None)
    if entity_size is not None:
        try:
            context["size_marla"] = float(entity_size)
        except (TypeError, ValueError):
            pass
    entity_budget = getattr(entities, "price_pkr", None)
    if entity_budget is not None:
        context["budget"] = entity_budget
    brief = result.get("lead_brief") or {}
    if brief.get("last_message_time"):
        context["timestamp"] = brief["last_message_time"]

    report = fact_guard.guard_payload(
        {
            "facts": facts,
            "summary": market_facts.get("summary"),
            "facts_used": result.get("facts_used"),
            "lead_brief": brief,
        },
        allowed,
        label="message",
        context=context,
    )

    if report["ok"]:
        return report

    # The fact set does not verify: withhold it and hand over to a human.
    result["market_facts"] = None
    result["facts_used"] = []
    result["draft_reply"] = fact_guard.HOLD_REPLY
    result["market_answerable"] = False
    result["market_reason"] = report["reason"]
    result["needs_human"] = True
    result["needs_human_approval"] = True

    decision = result.get("decision")
    if isinstance(decision, dict):
        decision["needs_human"] = True
        reasons = list(decision.get("reasons") or [])
        if "unverified_fact_set" not in reasons:
            reasons.append("unverified_fact_set")
        decision["reasons"] = reasons
        decision["action"] = "escalate"

    return report

# Leads endpoints
@app.get("/api/leads")
def get_leads(username: str = Depends(get_current_username)):
    conn = get_db_connection()
    try:
        leads = conn.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        return [dict(lead) for lead in leads]
    finally:
        conn.close()

@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str, username: str = Depends(get_current_username)):
    conn = get_db_connection()
    try:
        lead = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        return dict(lead)
    finally:
        conn.close()

# Approve endpoint
@app.post("/api/leads/{lead_id}/approve")
def approve_lead(
    lead_id: str,
    edited_text: str,
    username: str = Depends(get_current_username)
):
    conn = get_db_connection()
    try:
        # Update the lead's message? Or store the approved reply?
        # The task says: approval is required and recorded.
        # We'll store the approved reply in the audit log.
        # First, get the lead to ensure it exists.
        lead = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Insert an audit entry for the approval
        conn.execute(
            """
            INSERT INTO audit_log (
                lead_id, step, input_text, output_text, decision_payload, fact_ids_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                lead_id,
                "approve",
                edited_text,  # input_text is the edited text that was approved
                edited_text,  # output_text is the same as the approved reply
                json.dumps({"action": "approve", "edited_text": edited_text}),
                "[]",  # fact_ids_used
            ),
        )
        conn.commit()
        return {"status": "approved"}
    finally:
        conn.close()

# Reject endpoint
@app.post("/api/leads/{lead_id}/reject")
def reject_lead(
    lead_id: str,
    reason: str,
    username: str = Depends(get_current_username)
):
    conn = get_db_connection()
    try:
        lead = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # Insert an audit entry for the rejection
        conn.execute(
            """
            INSERT INTO audit_log (
                lead_id, step, input_text, output_text, decision_payload, fact_ids_used, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            (
                lead_id,
                "reject",
                reason,  # input_text is the reason for rejection
                reason,  # output_text is the same as the reason
                json.dumps({"action": "reject", "reason": reason}),
                "[]",
            ),
        )
        conn.commit()
        return {"status": "rejected"}
    finally:
        conn.close()

# State endpoint (to update lead state, e.g., status)
@app.post("/api/leads/{lead_id}/state")
def update_lead_state(
    lead_id: str,
    state: Dict[str, Any],
    username: str = Depends(get_current_username)
):
    conn = get_db_connection()
    try:
        lead = conn.execute("SELECT * FROM leads WHERE lead_id = ?", (lead_id,)).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")
        
        # We'll update the lead's status if provided
        if "status" in state:
            conn.execute(
                "UPDATE leads SET status = ?, updated_at = datetime('now') WHERE lead_id = ?",
                (state["status"], lead_id),
            )
        
        conn.commit()
        return {"status": "updated"}
    finally:
        conn.close()

# Audit endpoint
#
# M5 (D-32): the audit trail is the operator's record of what the system
# said, so it carries numbers in prose - and a recorded reply can stop
# matching the master once the master is refreshed. Each row is
# therefore checked against the approved master, using the filter the M5
# audit record stores.
#
# The row's own content is never rewritten or removed - it is the
# operator's historical record, and hiding it would destroy the audit
# trail's value. What the guard adds is the truth about it:
# `verified` is True, False, or None ("not checkable", for a row that
# predates the M5 record and therefore carries no filter).
@app.get("/api/audit")
def get_audit(lead_id: Optional[str] = None, username: str = Depends(get_current_username)):
    conn = get_db_connection()
    try:
        if lead_id:
            audit = conn.execute(
                "SELECT * FROM audit_log WHERE lead_id = ? ORDER BY created_at",
                (lead_id,)
            ).fetchall()
        else:
            audit = conn.execute("SELECT * FROM audit_log ORDER BY created_at").fetchall()
        return [_guard_audit_row(dict(row)) for row in audit]
    finally:
        conn.close()


def _guard_audit_row(row):
    """Check one audit row's recorded reply against the approved master.

    Returns the row with a `guard` report and a `verified` flag added.
    The row's content is unchanged.
    """
    try:
        payload = json.loads(row.get("decision_payload") or "{}")
    except (TypeError, ValueError):
        payload = {}

    filters = payload.get("market_filters") if isinstance(payload, dict) else None

    if not isinstance(filters, dict):
        # A row that predates the M5 audit record: there is nothing to
        # check it against, and "not checkable" must never be presented
        # as "verified".
        row["verified"] = None
        row["guard"] = fact_guard.public_report(
            ok=True,
            label="audit",
            reason="This record carries no market filter, so it cannot be checked.",
        )
        return row

    allowed = fact_guard.allowed_numbers_for(
        block=filters.get("block"),
        size_marla=filters.get("size_marla"),
        corner=filters.get("corner"),
        sun_facing=filters.get("sun_facing"),
        ndc_open=filters.get("ndc_open"),
    )

    report = fact_guard.guard_text(
        row.get("output_text") or "",
        allowed,
        label="audit",
    )

    row["verified"] = bool(report["ok"])
    row["guard"] = report
    return row

# Market summary endpoint.
#
# M4 (D-10): this used to return every row of the `market_listings`
# table, which in the root database is 5,867 dealer posts carrying
# `raw_text` (dealer business names) and a `sender` column. Serving
# that from a console endpoint would expose dealer identities, so the
# endpoint now returns the approved-master summary only: counts, price
# ranges and dates, with no raw text and no sender.
@app.get("/api/market")
def get_market_stats(username: str = Depends(get_current_username)):
    policies = price_lookup.load_policies()
    active_blocks = list(policies.get("active_blocks", []))
    sizes = [5, 7, 10, 14, 20, 40]
    summary = []
    for block in active_blocks:
        for size in sizes:
            result = price_lookup.lookup_price(
                block=block, size_marla=size, policies=policies
            )
            facts = result.get("facts") or {}
            row = {
                "block": block,
                "size_marla": size,
                "matched_plots": facts.get("matched_plots", 0),
                "observation_count": facts.get("observation_count", 0),
                "price_min_pkr": facts.get("price_min_pkr"),
                "price_median_pkr": facts.get("price_median_pkr"),
                "price_max_pkr": facts.get("price_max_pkr"),
                "latest_date": facts.get("latest_date"),
                "coverage_level": facts.get("coverage_level"),
                "trust_status": facts.get("trust_status"),
                "answerable_for_demo": facts.get("answerable_for_demo", False),
            }

            # M5 (D-32): every cell of the market table is checked
            # against the approved master before it is served. A cell
            # whose figures do not match the master is served with its
            # numbers removed and a per-row guard report, so a
            # tampered or unsupported figure can never reach the
            # console.
            allowed = fact_guard.allowed_numbers_for(
                block=block,
                size_marla=size,
            )
            report = fact_guard.guard_payload(row, allowed, label="market")
            if not report["ok"]:
                row = fact_guard.blocked_market_row(row, report=report)
            else:
                row = dict(row)
                row["guard"] = report

            summary.append(row)

    # The table as a whole is checked too, so a number that somehow
    # escaped the per-row check is still caught.
    allowed_all = fact_guard.allowed_numbers_for()
    table_report = fact_guard.guard_payload(
        {
            "min_listings_for_answer": policies.get("min_listings_for_answer"),
        },
        allowed_all,
        label="market",
    )

    return {
        "source": "FaisalHills verified partial master (read-only)",
        "price_basis": "dealer asking prices",
        "is_sold_price": False,
        "active_blocks": active_blocks,
        "min_listings_for_answer": policies.get("min_listings_for_answer"),
        "results": summary,
        "guard": table_report,
    }


# Deterministic lookup endpoint (M4).
#
# M5 (D-32): this endpoint serves the fact set, the summary and the
# rendered reply - i.e. every number a dealer or an operator can see
# from a single lookup. It is now guarded by `market.fact_guard`, which
# re-derives the permitted numbers from the approved master. A payload
# whose figures do not match the master (tampered, derived, stale or
# simply wrong) is blocked: the numbers are removed, the reply becomes
# the hold wording, and the `guard` report says what happened.
@app.get("/api/lookup")
def lookup_endpoint(
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    username: str = Depends(get_current_username),
):
    result = price_lookup.lookup_price(block=block, size_marla=size_marla)

    allowed = fact_guard.allowed_numbers_for(
        block=block,
        size_marla=size_marla,
    )

    facts = result.get("facts")
    summary = result.get("summary")
    reply = result.get("reply")

    report = fact_guard.guard_payload(
        {
            "facts": facts,
            "summary": summary,
            "reply": reply,
            "reason": result.get("reason", ""),
        },
        allowed,
        label="lookup",
    )

    if not report["ok"]:
        # The figures could not be verified. Withhold them.
        blocked = fact_guard.blocked_lookup_payload(
            filters=result.get("filters"),
            report=report,
        )
        return blocked

    return {
        "answerable": result["answerable"],
        "reply_mode": result["reply_mode"],
        "reply": reply,
        "reason": result.get("reason", ""),
        "filters": result["filters"],
        "facts": facts,
        "summary": summary,
        "guard": report,
    }


# The hand-checked question set (M4).
#
# M5 (D-32): the question set carries EXPECTED match counts, medians,
# minimums and maximums - factual numbers, recorded by hand. They are
# guarded like every other numeric surface: each case's expectations are
# checked against the approved master, so a stale or wrong expectation
# cannot be served as if it were the master's answer.
@app.get("/api/questions")
def questions_endpoint(username: str = Depends(get_current_username)):
    config = price_lookup.load_questions()

    questions = []
    blocked = 0

    for case in config.get("questions", []):
        filters = case.get("filters", {}) or {}
        allowed = fact_guard.allowed_numbers_for(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
        )

        # Only the EXPECTATION fields are factual numbers the endpoint
        # serves: the hand-recorded match count, observation count,
        # median, minimum and maximum. The case `id` is a sequence
        # number and the `question` / `note` fields are prose - neither
        # is a market fact, so neither is guarded.
        expectations = {
            key: value
            for key, value in case.items()
            if key.startswith("expect_")
        }

        report = fact_guard.guard_payload(
            expectations, allowed, label="questions"
        )
        case = dict(case)
        if not report["ok"]:
            blocked += 1
            case["expectations_verified"] = False
            case["guard"] = report
            # The expectation figures are withheld when they do not
            # match the master.
            for key in expectations:
                case[key] = None
        else:
            case["expectations_verified"] = True
            case["guard"] = report
        questions.append(case)

    checked = sum(
        1
        for case in questions
        if case.get("guard", {}).get("numbers_found")
    )

    return {
        "version": config.get("version"),
        "min_listings_for_answer": config.get("min_listings_for_answer"),
        "questions": questions,
        "guard": fact_guard.public_report(
            ok=(blocked == 0),
            label="questions",
            numbers_found=checked,
            untraceable_count=blocked,
            reason=(
                "" if blocked == 0
                else "%d question(s) carry an expectation the approved master "
                     "does not support." % blocked
            ),
        ),
    }

# M7 - the matching-listings / evidence layer.
#
# The operator panel's job is "which listings produced this answer?".
# This endpoint serves the evidence BEHIND an answer, from the approved
# master, through the whitelist in `market/evidence.py`.
#
# Two properties matter more than the feature itself:
#
#  * **The scope rule is the lookup's rule.** A block outside the
#    active scope is refused before any row is counted, so the evidence
#    can never show a parked block the answer would not price.
#  * **The plot identifier is served only on request.** The default
#    serves the REDACTED form - an opaque, stable `listing_ref` per
#    row. The identifier itself is served only when the operator
#    asserts authorisation, and the response always records which mode
#    was used.
#
# A thin cell is served with its rows and NO price - the operator can
# see exactly why the product refused to answer, without the operator
# panel becoming a way to quote a figure the customer path withholds.
@app.get("/api/evidence")
def evidence_endpoint(
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    include_plot_number: bool = False,
    limit: Optional[int] = None,
    username: str = Depends(get_current_username),
):
    try:
        payload = _evidence.evidence_for_cell(
            block=block,
            size_marla=size_marla,
            corner=corner,
            sun_facing=sun_facing,
            ndc_open=ndc_open,
            include_plot_number=include_plot_number,
            limit=limit,
        )
    except _evidence.EvidenceError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # The evidence carries factual numbers, so it is guarded by the same
    # M5 surface guard as every other numeric surface. The guard
    # re-derives the permitted numbers from the approved master, so a
    # tampered or stale figure cannot reach the operator panel.
    #
    # The evidence rows carry each listing's OWN price and date, so the
    # permitted set is derived at the row level as well as the cell
    # level. The row numbers are re-derived from the read-only approved
    # master, so a value the master does not hold is still untraceable
    # - the check is applied at the row level, not weakened.
    rows = _evidence.matching_rows(
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
    )
    allowed = fact_guard.allowed_numbers_for(
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
        rows=rows,
    )
    report = fact_guard.guard_payload(
        payload, allowed, label="evidence",
        # The plot identifier is a NAME, not a figure. It is served only
        # in the authorised mode and only for rows the approved master
        # holds, so it is not checked as a market fact.
        skip_keys=("plot_number",),
    )
    if not report["ok"]:
        return {
            "listings": [],
            "summary": None,
            "answerable": False,
            "plot_number_mode": payload.get("plot_number_mode"),
            "excluded_fields": payload.get("excluded_fields"),
            "guard": report,
        }
    payload["guard"] = report
    return payload


# M8 - the recommendation layer.
#
# The operator panel's question is "what CAN this dealer be shown?".
# The endpoint serves the ranked, VERIFIED alternatives for a cell -
# the options the approved master actually supports, each with the
# reason it was proposed and the next best action.
#
# Two properties matter more than the feature itself:
#
#  * **Only verified cells are served.** An option is a cell that
#    clears the same evidence threshold the lookup uses. A cell below
#    the threshold is reported as a thin cell, with no price.
#  * **The scope rule is the lookup's rule.** A block outside the
#    active scope is refused before any row is counted.
@app.get("/api/recommendations")
def recommendations_endpoint(
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    limit: int = 3,
    include_listings: bool = True,
    username: str = Depends(get_current_username),
):
    try:
        payload = _recommend.build_recommendations(
            block=block,
            size_marla=size_marla,
            corner=corner,
            sun_facing=sun_facing,
            ndc_open=ndc_open,
            limit=limit,
            include_listings=include_listings,
        )
    except _recommend.RecommendationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # The options carry each cell's own price and counts, so the payload
    # is guarded by the same M5 surface guard as every other numeric
    # surface. The permitted numbers are re-derived from the approved
    # master, so a figure the master does not hold cannot be served.
    #
    # Each option is a cell of its own, so each cell's approved facts
    # are permitted - re-derived from the read-only master through the
    # guard, not taken from the recommendation. The row-level numbers
    # (each listing's own price and date) are permitted too.
    rows = []
    for option in payload.get("options") or []:
        rows.extend(_evidence.matching_rows(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
            corner=corner,
            sun_facing=sun_facing,
            ndc_open=ndc_open,
        ))

    allowed = fact_guard.allowed_numbers_for(
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
        rows=rows,
    )

    # Each option cell's own approved facts.
    for option in payload.get("options") or []:
        allowed |= fact_guard.allowed_numbers_for(
            block=option.get("block"),
            size_marla=option.get("size_marla"),
            corner=corner,
            sun_facing=sun_facing,
            ndc_open=ndc_open,
        )

    report = fact_guard.guard_payload(
        payload, allowed, label="recommendations",
        # The ranking score and its components are DERIVED values the
        # application computes, not market facts. They are skipped for
        # the same reason the plot identifier is: they are not claims
        # about the market, they are the application's own ranking.
        skip_keys=("plot_number", "score", "score_components"),
    )
    if not report["ok"]:
        return {
            "options": [],
            "thin_cells": [],
            "answerable": False,
            "next_best_action": {
                "action": "escalate_to_human",
                "label": "Hand the conversation to a member of the team.",
                "requires_human_approval": True,
                "reason": "the recommendation could not be validated",
            },
            "guard": report,
        }
    payload["guard"] = report
    return payload


# M9 - the qualification and next-best-action surface.
#
# This is the operator's view of what the product decided and why. It
# takes the same request M8 takes (a block and a size), adds the
# requirements the dealer stated, and returns:
#
#   * the requirements, exactly as stated - and the ones that were
#     NEVER stated stay absent, so an operator can see what is unknown;
#   * the verified options, narrowed by those requirements;
#   * the NEXT BEST ACTION, chosen by the application from the ladder.
#
# The surface carries NO price and NO count. It is a decision surface,
# not a market surface, so it needs no price guard - and it exposes
# nothing the M7 evidence whitelist does not already allow. The blocks
# and the sizes it names are the cells the application already
# verified, and nothing else.
@app.get("/api/next-best-action")
def next_best_action_endpoint(
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    message: str = "",
    lead_id: Optional[str] = None,
    limit: int = 3,
    username: str = Depends(get_current_username),
):
    try:
        payload = _recommend.build_recommendations(
            block=block,
            size_marla=size_marla,
            limit=limit,
            include_listings=False,
        )
    except _recommend.RecommendationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # The requirements. The message the dealer sent is read, and the
    # lead's own earlier messages are read back, so a requirement
    # stated over several turns is assembled. A requirement that was
    # never stated stays absent - it is never guessed.
    try:
        history = _conversation.conversation_requirements(lead_id)
    except Exception:
        history = _qualify.requirements_from_messages([])
    current = _qualify.extract_requirements(message)
    requirements = _qualify.merge_requirements(history, current)

    decision = _decision.decide(payload, requirements)

    # The operator sees what the dealer stated and what the product
    # decided. The requirements are echoed as a flat map of the
    # SUPPORTED keys only, with the unstated ones absent.
    stated = {
        key: value
        for key, value in requirements.items()
        if key != "source" and value is not None
    }

    return {
        "action": decision.get("action"),
        "label": decision.get("label"),
        "reason": decision.get("reason"),
        "requirements_stated": stated,
        "requirements_unknown": [
            key for key, value in requirements.items()
            if key != "source" and value is None
        ],
        "options": [
            {
                "block": option.get("block"),
                "size_marla": option.get("size_marla"),
                "reason": option.get("reason"),
            }
            for option in (decision.get("options") or [])
        ],
        "removed": decision.get("removed") or [],
        "clarifying_question": decision.get("clarifying_question"),
        "thin_cells": payload.get("thin_cells") or [],
        "requires_human_approval": True,
        "availability_claimed": False,
    }


# M7 - the operator review workflow.
#
# An approval that cannot be traced to the evidence it approved is not
# an approval, it is a click. The review therefore records the
# `listing_ref` set it was made against, a digest of that set, the fact
# identifiers the reply was built from, and whether the reply was
# edited before it was approved.
#
# The review does NOT re-run the validators: the pipeline already
# validated the reply, and re-deriving the verdict here would create a
# second authority. It records the verdict instead.
@app.post("/api/leads/{lead_id}/review")
def review_lead(
    lead_id: str,
    decision: str,
    edited_text: str = "",
    reason: str = "",
    listing_refs: Optional[List[str]] = None,
    fact_ids: Optional[List[str]] = None,
    username: str = Depends(get_current_username),
):
    conn = get_db_connection()
    try:
        lead = conn.execute(
            "SELECT lead_id FROM leads WHERE lead_id = ?", (lead_id,)
        ).fetchone()
        if lead is None:
            raise HTTPException(status_code=404, detail="Lead not found")

        try:
            recorded = _review.record_review(
                conn,
                lead_id=lead_id,
                decision=decision,
                reply_text=edited_text,
                reason=reason,
                evidence={"listing_refs": list(listing_refs or [])},
                fact_ids=list(fact_ids or []),
            )
        except _review.ReviewError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    finally:
        conn.close()

    return recorded


@app.get("/api/leads/{lead_id}/reviews")
def review_history_endpoint(
    lead_id: str, username: str = Depends(get_current_username)
):
    """The review decisions recorded for a lead, oldest first."""
    conn = get_db_connection()
    try:
        history = _review.review_history(conn, lead_id)
    finally:
        conn.close()
    return {"lead_id": lead_id, "reviews": history}


# ---------------------------------------------------------------------------
# M11 - the conversation endpoint and the operator desk.
#
# One route takes a session id and a message and returns the reply, the
# lead state, the route, the reason, the escalation flag and the unmet
# demand record. It is a thin shell over `app.turn_pipeline.run_turn`,
# which is the application: the policy, the lookup, the qualification,
# the decision, the M5 numeric validator and the M6.1 claim guard all ran
# before this route saw anything.
#
# What this route never returns: a raw plot number, a dealer name, a
# note, a raw size, a sender identity or another lead's data. The reply
# is the application's own validated reply, and the state carries only
# the five qualification fields with their provenance.
# ---------------------------------------------------------------------------


def _m11_stores():
    """The M11 stores, in files of their own.

    The owner's `faisal_hills.db` is never touched: the lead state and
    the unmet-demand log each live in a SQLite file of their own.
    """
    from market.lead_state import LeadStateStore
    from market.unmet_demand import UnmetDemandStore

    return LeadStateStore(), UnmetDemandStore()


@app.post("/api/conversation")
def conversation_endpoint(
    message: str = "",
    session_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Run one turn of a dealer conversation.

    The message may be sent either way:

    * in the **query string** (``?message=...&session_id=...``) - the
      original form, still supported;
    * in a **JSON body** (``{"session_id": "...", "message": "..."}``) -
      the form the operator desk uses, so the dealer's own words never
      appear in a URL or in an access log.

    A body wins over the query string. Nothing else about the turn
    changes: the same `app.turn_pipeline.run_turn` runs, with the same
    policy, the same lookup, the same validation and the same privacy
    boundary.

    Returns the reply, the lead state, the route, the reason, the
    escalation flag, the verified options, the next action and the
    unmet-demand record.
    """
    from app.turn_pipeline import run_turn

    if isinstance(payload, dict):
        body_message = payload.get("message")
        body_session = payload.get("session_id")
        if body_message is not None:
            message = str(body_message)
        if body_session is not None:
            session_id = str(body_session)

    if not message:
        raise HTTPException(
            status_code=422,
            detail=[{"type": "missing", "loc": ["body", "message"],
                     "msg": "Field required", "input": None}],
        )

    state_store, demand_store = _m11_stores()

    try:
        result = run_turn(
            message,
            session_id,
            store=state_store,
            demand_store=demand_store,
        )
    except Exception as exc:  # pragma: no cover - the pipeline is guarded
        raise HTTPException(status_code=500, detail=str(exc))

    result["taken_over_at"] = state_store.taken_over(result["session_id"])
    return result


@app.get("/api/conversation/{session_id}")
def conversation_state_endpoint(
    session_id: str,
    username: str = Depends(get_current_username),
):
    """The state of a conversation, without running a new turn."""
    from market.lead_state import LeadStateStore

    state = LeadStateStore().load(session_id)

    return {
        "session_id": session_id,
        "turn": state.turn,
        "lead_state": state.to_dict(),
        "unknowns": state.unknowns(),
        "corrections": state.corrections(),
        "taken_over_at": LeadStateStore().taken_over(session_id),
    }


@app.post("/api/conversation/{session_id}/take-over")
def conversation_take_over_endpoint(
    session_id: str,
    operator: Optional[str] = None,
    username: str = Depends(get_current_username),
):
    """Record that a human has taken this conversation over.

    The take-over is a flag on the session, nothing more. It does not
    change the lead state, it does not change any decision, and it does
    not send anything to a dealer: the operator still reads the draft
    and sends it.
    """
    from market.lead_state import LeadStateStore

    store = LeadStateStore()
    recorded = store.mark_taken_over(session_id, operator=operator)

    # M12.2: the take-over is also one operator action in the activity
    # log, so the activity view can count it.
    if recorded:
        from market.conversation_log import ConversationLogStore
        ConversationLogStore().record_action(session_id, "taken_over")
        # the lead pipeline's second automatic flag
        try:
            from market.lead_pipeline import LeadPipelineStore
            LeadPipelineStore().mark_taken_over(session_id)
        except Exception:
            pass

    return {
        "session_id": session_id,
        "taken_over": bool(recorded),
        "taken_over_at": store.taken_over(session_id),
    }


# ---------------------------------------------------------------------------
# M12.2 - persistence: the conversation list, the transcript, the draft
# actions and the activity view.
#
# What these routes never return: a market figure the application did not
# already serve for that turn, a raw plot number, a dealer name, a note,
# a phone number or another lead's data. The transcript replays the
# replies the pipeline already validated and already served; the list
# carries the dealer's own words as a short preview, the same words the
# operator typed and already sees in the thread; the activity view
# carries counts, action names, session ids and times - no message text.
# ---------------------------------------------------------------------------


@app.get("/api/conversations")
def conversations_endpoint(
    limit: int = 100,
    username: str = Depends(get_current_username),
):
    """The conversations the application has handled, newest first.

    Each item carries the session id, the turn count, the last route,
    the last escalation flag, the last activity time, the take-over
    stamp and a short preview of the last dealer message. Nothing is
    derived here - every field is a record of a turn that already ran.
    """
    from market.conversation_log import ConversationLogStore
    from market.lead_state import LeadStateStore

    log = ConversationLogStore()
    state_store = LeadStateStore()
    conversations = []
    for item in log.list_conversations(limit=limit):
        item["taken_over_at"] = state_store.taken_over(item["session_id"])
        conversations.append(item)
    return {"conversations": conversations}


@app.get("/api/conversation/{session_id}/transcript")
def conversation_transcript_endpoint(
    session_id: str,
    username: str = Depends(get_current_username),
):
    """The recorded turns of a conversation, oldest first.

    This is a **replay**, not a new answer: each turn carries the
    dealer's message exactly as the operator typed it and the reply the
    application validated for that turn, unchanged.
    """
    from market.conversation_log import ConversationLogStore
    from market.inventory_workspace import stamps_for_session
    from market.lead_state import LeadStateStore

    turns = ConversationLogStore().transcript(session_id)
    stamps = stamps_for_session(session_id)
    for turn in turns:
        try:
            turn_number = int(turn.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        record = stamps.get(turn_number)
        if record:
            turn["inventory_version"] = {
                "mode": record.get("mode"),
                "version_id": record.get("version_id"),
                "fingerprint": record.get("fingerprint"),
                "rows": record.get("rows"),
            }

    return {
        "session_id": session_id,
        "turns": turns,
        "taken_over_at": LeadStateStore().taken_over(session_id),
    }


@app.post("/api/conversation/{session_id}/draft-action")
def conversation_draft_action_endpoint(
    session_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Record one operator action on a draft.

    The action is a record, nothing more: it does not change the lead
    state, it does not change any decision, and it sends nothing to a
    dealer. The valid actions are ``sent``, ``edited``, ``rejected`` and
    ``operator_reply``; the take-over has its own route.
    """
    from market.conversation_log import ConversationLogStore

    action = None
    if isinstance(payload, dict):
        action = payload.get("action")

    if action not in ("sent", "edited", "rejected", "copied",
                      "operator_reply", "followup_approved",
                      "followup_edited", "followup_rejected",
                      "followup_copied"):
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["body", "action"],
                     "msg": "Action must be one of: sent, edited, "
                            "rejected, copied, operator_reply, "
                            "followup_approved, followup_edited, "
                            "followup_rejected, followup_copied",
                     "input": action}],
        )

    recorded = ConversationLogStore().record_action(session_id, str(action))
    if not recorded:
        raise HTTPException(
            status_code=500,
            detail="The action could not be recorded",
        )
    return {"session_id": session_id, "action": action, "recorded": True}


@app.get("/api/operator-activity")
def operator_activity_endpoint(
    limit: int = 20,
    username: str = Depends(get_current_username),
):
    """The operator activity view: a count per action, the recent events,
    and the M12.5 pilot-metric totals (conversations, AI drafts,
    escalations, unmet demand).

    No message text is served here - the counts, the action names, the
    session ids and the times are the whole response.
    """
    from market.conversation_log import ConversationLogStore
    from market.unmet_demand import UnmetDemandStore

    activity = ConversationLogStore().activity(limit=limit)
    activity["totals"]["unmet_demand"] = UnmetDemandStore().count()
    return activity


# ---------------------------------------------------------------------------
# The lead pipeline: every conversation as a trackable lead, a follow-up
# queue, transparent scoring and routing, and deterministic follow-up
# DRAFTS. The application owns lead truth: stages change only by
# operator approval (plus the two standing automatic flags, escalated
# and taken-over), the score and temperature are displayed arithmetic -
# never predictions - and a draft is a draft: nothing is ever sent, no
# price, availability or private data appears in one.
# ---------------------------------------------------------------------------


def _pipeline_view(lead_id: str):
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LeadPipelineStore, lead_view
    from market.lead_state import LeadStateStore

    return lead_view(lead_id,
                     pipeline=LeadPipelineStore(),
                     conversation_log=ConversationLogStore(),
                     lead_state_store=LeadStateStore())


@app.get("/api/leads-pipeline")
def leads_pipeline_endpoint(
    username: str = Depends(get_current_username),
):
    """The pipeline list: every conversation as a lead with stage,
    history, transparent temperature and score, routing suggestion,
    follow-up state, summary and badges - all derived from recorded
    data, nothing invented."""
    from market.lead_pipeline import LeadPipelineStore

    views = []
    for lead_id in LeadPipelineStore().list_ids():
        view = _pipeline_view(lead_id)
        if view:
            views.append(view)
    return {"leads": views}


@app.get("/api/lead-pipeline/founder-view")
def lead_pipeline_founder_view_endpoint(
    username: str = Depends(get_current_username),
):
    """Pilot feature 1 - the founder-only lead-pipeline view.

    Per lead: temperature, score (with the transparent breakdown),
    stage + stage suggestion, known and missing requirements, the
    recommended next action and the site-visit state. Privacy-safe by
    construction: no dealer contacts, no raw WhatsApp messages, no
    private notes."""
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LeadPipelineStore
    from market.lead_state import LeadStateStore
    from market import lead_qualification as _lq
    from market import site_visit as _site_visit

    pipeline = LeadPipelineStore()
    clog = ConversationLogStore()
    state_store = LeadStateStore()
    mapping = {"block": "block", "size": "size_marla",
               "budget": "budget_max_pkr", "purpose": "purpose",
               "timeline": "timeline"}
    view = []
    for lead_id in pipeline.list_ids():
        base = _pipeline_view(lead_id)
        if not base:
            continue
        fields = (base.get("requirements") or {})
        requirements = {}
        for key, target in mapping.items():
            entry = fields.get(key) or {}
            if entry.get("value") not in (None, "", {}):
                requirements[target] = entry.get("value")
        qual = _lq.qualification_view(
            requirements=requirements,
            message="",
            turns=len(clog.transcript(lead_id)),
            escalated=base.get("stage") == "ESCALATED",
            has_visit_request=_site_visit.has_request_for_lead(lead_id),
        )
        view.append({
            "lead_id": lead_id,
            "label": base.get("label"),
            "temperature": qual["temperature"],
            "score": qual["score"],
            "score_breakdown": qual["score_breakdown"],
            "stage": base.get("stage"),
            "stage_suggestion": qual["stage_suggestion"],
            "known_requirements": qual["known_requirements"],
            "missing_requirements": qual["missing_requirements"],
            "recommended_next_action": qual["recommended_next_action"],
            "verified_options": base.get("verified_options") or [],
            "requires_founder_approval": True,
            "conversation_summary": base.get("conversation_summary") or "",
            "last_activity_at": base.get("last_activity_at"),
        })
    return {"leads": view,
            "site_visit_requests": _site_visit.requests()}


@app.get("/api/site-visit/requests")
def site_visit_requests_endpoint(
    username: str = Depends(get_current_username),
):
    """Pilot feature 2 - the site-visit flow state: every request and
    the founder-approved slot calendar. Privacy-safe by construction."""
    from market import site_visit as _site_visit
    return {"requests": _site_visit.requests(),
            "slots": _site_visit.load_slots()}


@app.post("/api/site-visit/approve")
def site_visit_approve_endpoint(
    request_id: str,
    username: str = Depends(get_current_username),
):
    """Pilot feature 2 - the founder approval. The request moves to
    FOUNDER_APPROVED and the slot to PENDING_CONFIRMATION; a
    confirmation DRAFT is returned for MANUAL sending. Nothing is sent
    automatically and no code path ever sets CONFIRMED."""
    from market import site_visit as _site_visit
    request, draft = _site_visit.approve_request(request_id, username)
    if request is None:
        raise HTTPException(status_code=404,
                            detail="unknown site-visit request")
    return {"request": request, "confirmation_draft": draft,
            "requires_manual_send": True}


@app.get("/api/leads-pipeline/{lead_id}")
def lead_pipeline_detail_endpoint(
    lead_id: str,
    username: str = Depends(get_current_username),
):
    """One lead's full view (timeline, summary, score reasons, notes)."""
    view = _pipeline_view(lead_id)
    if not view:
        raise HTTPException(status_code=404, detail="unknown lead")
    return view


@app.post("/api/leads-pipeline/{lead_id}/stage")
def lead_stage_endpoint(
    lead_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Operator-approved stage change. CLOSED_* stages exist only here:
    nothing in the system closes a lead by itself."""
    from market.lead_pipeline import LEAD_STAGES, LeadPipelineStore

    stage = payload.get("stage") if isinstance(payload, dict) else None
    if stage not in LEAD_STAGES:
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["body", "stage"],
                     "msg": "Stage must be one of: %s"
                            % ", ".join(LEAD_STAGES),
                     "input": stage}],
        )
    store = LeadPipelineStore()
    if not store.get(lead_id):
        raise HTTPException(status_code=404, detail="unknown lead")
    if not store.operator_set_stage(lead_id, str(stage),
                                    operator=username):
        raise HTTPException(status_code=500,
                            detail="the stage change was not recorded")
    return _pipeline_view(lead_id)


@app.post("/api/leads-pipeline/{lead_id}/follow-up")
def lead_follow_up_endpoint(
    lead_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Operator sets (or clears) the follow-up date for a lead."""
    from market.lead_pipeline import LeadPipelineStore

    store = LeadPipelineStore()
    if not store.get(lead_id):
        raise HTTPException(status_code=404, detail="unknown lead")
    due_at = payload.get("due_at") if isinstance(payload, dict) else None
    if not store.set_follow_up(lead_id,
                               str(due_at) if due_at else None):
        raise HTTPException(status_code=500,
                            detail="the follow-up date was not recorded")
    return _pipeline_view(lead_id)


@app.post("/api/leads-pipeline/{lead_id}/note")
def lead_note_endpoint(
    lead_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """An operator note on the lead record."""
    from market.lead_pipeline import LeadPipelineStore

    store = LeadPipelineStore()
    if not store.get(lead_id):
        raise HTTPException(status_code=404, detail="unknown lead")
    text = payload.get("text") if isinstance(payload, dict) else None
    if not text or not str(text).strip():
        raise HTTPException(
            status_code=422,
            detail=[{"type": "missing", "loc": ["body", "text"],
                     "msg": "Field required", "input": None}],
        )
    if not store.add_note(lead_id, str(text), author=username):
        raise HTTPException(status_code=500,
                            detail="the note was not recorded")
    return _pipeline_view(lead_id)


@app.get("/api/follow-ups")
def follow_ups_endpoint(    username: str = Depends(get_current_username),
):
    """The follow-up queue: today, overdue, this week, no recent
    activity, escalated, and unmet demand - each item with the
    transparent lead view and a deterministic follow-up DRAFT (human
    approval required; nothing is ever sent)."""
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import (LeadPipelineStore,
                                      draft_follow_up, lead_view)
    from market.lead_state import LeadStateStore
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    sections = {"today": [], "overdue": [], "this_week": [],
                "no_activity": [], "escalated": [], "unmet": []}
    pipeline = LeadPipelineStore()
    conversation_log = ConversationLogStore()
    state_store = LeadStateStore()

    for lead_id in pipeline.list_ids():
        view = lead_view(lead_id, pipeline=pipeline,
                         conversation_log=conversation_log,
                         lead_state_store=state_store)
        if not view:
            continue
        item = dict(view)
        item["follow_up_draft"] = draft_follow_up(view)
        days = view.get("days_since_activity")
        if view["stage"] == "ESCALATED":
            sections["escalated"].append(item)
        if view.get("follow_up", {}).get("overdue"):
            sections["overdue"].append(item)
        elif view.get("follow_up", {}).get("due_today"):
            sections["today"].append(item)
        elif view.get("follow_up", {}).get("due_this_week"):
            sections["this_week"].append(item)
        if days is not None and days >= 7:
            sections["no_activity"].append(item)
        if view.get("unmet_demand"):
            if not item.get("follow_up_reason"):
                item["follow_up_reason"] = \
                    "unmet demand recorded for this lead"
            sections["unmet"].append(item)

    return {"sections": sections}


# ---------------------------------------------------------------------------
# Pilot reporting (2026-10-24): lead sources, structured operator
# feedback and the weekly owner report. All of it records or aggregates
# OPERATOR-entered and application-recorded data; nothing sends
# anything anywhere, and the reports carry counts and shapes - never
# customer/dealer message text, names, phones or plot identifiers.
# ---------------------------------------------------------------------------


@app.post("/api/leads-pipeline/{lead_id}/source")
def lead_source_endpoint(
    lead_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Operator sets the lead source (fixed vocabulary, journaled)."""
    from market.lead_pipeline import LEAD_SOURCES, LeadPipelineStore

    store = LeadPipelineStore()
    if not store.get(lead_id):
        raise HTTPException(status_code=404, detail="unknown lead")
    source = payload.get("source") if isinstance(payload, dict) else None
    if source not in LEAD_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["body", "source"],
                     "msg": "Source must be one of: %s"
                            % ", ".join(LEAD_SOURCES),
                     "input": source}],
        )
    if not store.set_source(lead_id, str(source), operator=username):
        raise HTTPException(status_code=500,
                            detail="the source change was not recorded")
    return _pipeline_view(lead_id)


@app.get("/api/pilot-feedback/{lead_id}")
def pilot_feedback_get_endpoint(
    lead_id: str,
    username: str = Depends(get_current_username),
):
    """The operator feedback recorded for one lead."""
    from market.pilot_feedback import PilotFeedbackStore

    return {"lead_id": lead_id,
            "feedback": PilotFeedbackStore().for_lead(lead_id)}


@app.post("/api/pilot-feedback/{lead_id}")
def pilot_feedback_post_endpoint(
    lead_id: str,
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    """Record one structured feedback submission (operator-entered).

    Every field is validated against its fixed vocabulary; a missing or
    unknown value is a 422, never a silent default."""
    from market.conversation_log import ConversationLogStore
    from market.pilot_feedback import (FEEDBACK_GROUNDING,
                                       FEEDBACK_ISSUES, FEEDBACK_QUALITY,
                                       FEEDBACK_TIME, FEEDBACK_WOULD_SEND,
                                       PilotFeedbackStore)

    body = payload if isinstance(payload, dict) else {}
    required = {
        "quality": FEEDBACK_QUALITY, "grounding": FEEDBACK_GROUNDING,
        "time_saved": FEEDBACK_TIME, "would_send": FEEDBACK_WOULD_SEND,
        "issue": FEEDBACK_ISSUES,
    }
    for field, allowed in required.items():
        value = body.get(field)
        if value not in allowed:
            raise HTTPException(
                status_code=422,
                detail=[{"type": "value_error", "loc": ["body", field],
                         "msg": "%s must be one of: %s"
                                % (field, ", ".join(allowed)),
                         "input": value}],
            )

    # the conversation-context REFERENCE: counts and the last route -
    # never message text
    turns = ConversationLogStore().transcript(lead_id)
    context_ref = "conversation:turns=%d" % len(turns)
    if turns:
        context_ref += ";last_route=%s" % turns[-1]["route"]

    row = PilotFeedbackStore().record(
        lead_id, operator=username, quality=body["quality"],
        grounding=body["grounding"], time_saved=body["time_saved"],
        would_send=body["would_send"], issue=body["issue"],
        note=body.get("note"), context_ref=context_ref)
    if not row:
        raise HTTPException(status_code=500,
                            detail="the feedback was not recorded")
    return {"lead_id": lead_id, "recorded": True, "feedback": row}


@app.get("/api/weekly-report")
def weekly_report_endpoint(
    days: int = 7,
    source: Optional[str] = None,
    username: str = Depends(get_current_username),
):
    """The weekly owner report, aggregated from recorded pilot data
    only. Every section is a count or a shape - never private text."""
    from market.conversation_log import ConversationLogStore
    from market.lead_pipeline import LEAD_SOURCES, LeadPipelineStore
    from market.pilot_feedback import (PilotFeedbackStore,
                                       build_weekly_report)
    from market.unmet_demand import UnmetDemandStore

    if source is not None and source != "" and source not in LEAD_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=[{"type": "value_error", "loc": ["query", "source"],
                     "msg": "Source must be one of: %s"
                            % ", ".join(LEAD_SOURCES),
                     "input": source}],
        )
    report = build_weekly_report(
        pipeline=LeadPipelineStore(),
        conversation_log=ConversationLogStore(),
        feedback_store=PilotFeedbackStore(),
        demand_store=UnmetDemandStore(),
        days=days, source=source or None)
    return report


@app.get("/api/weekly-report/markdown")
def weekly_report_markdown_endpoint(
    days: int = 7,
    source: Optional[str] = None,
    username: str = Depends(get_current_username),
):
    from fastapi.responses import PlainTextResponse
    from market.pilot_feedback import report_markdown

    report = weekly_report_endpoint(days=days, source=source,
                                    username=username)
    return PlainTextResponse(report_markdown(report),
                             media_type="text/markdown")


@app.get("/api/weekly-report/csv")
def weekly_report_csv_endpoint(
    days: int = 7,
    source: Optional[str] = None,
    username: str = Depends(get_current_username),
):
    from fastapi.responses import PlainTextResponse
    from market.pilot_feedback import report_csv

    report = weekly_report_endpoint(days=days, source=source,
                                    username=username)
    return PlainTextResponse(report_csv(report),
                             media_type="text/csv")


@app.get("/api/unmet-demand")
def unmet_demand_endpoint(
    limit: int = 20,
    username: str = Depends(get_current_username),
):
    """The unmet-demand log: the count and the distinct demand shapes.

    A shape is a size, a block and a budget band. There is no message
    text, no lead id and no identifier in this response.
    """
    from market.unmet_demand import UnmetDemandStore

    store = UnmetDemandStore()
    return {
        "count": store.count(),
        "shapes": store.shapes(limit=limit),
    }


# Serve the main HTML page
@app.get("/", response_class=HTMLResponse)
def read_root(username: str = Depends(get_current_username)):
    with open("app/static/index.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    return HTMLResponse(content=html_content, status_code=200)


# M11.5 - the operator desk. One plain page, served by this same server.
# No new framework, no new dependency, no build step.
@app.get("/operator", response_class=HTMLResponse)
def operator_page(username: str = Depends(get_current_username)):
    """The operator page: conversation, qualification state, options.

    The environment chip is filled from the server's own truth about the
    inventory it would ACTUALLY serve: the active workspace version when
    one exists, otherwise the configured master - always with the real
    fingerprint, row count and observation-date range of that file. The
    page never guesses this for itself.
    """
    from market.inventory_workspace import current_stamp

    chip = current_stamp()["label"]
    with open("app/static/operator.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    html_content = html_content.replace("__ENV_BADGE__", chip)
    return HTMLResponse(content=html_content, status_code=200)


# ---------------------------------------------------------------------------
# Stage 1 - versioned inventory workspace (PROVISIONAL UI + API)
#
# Upload -> preview/column-map -> validate -> review -> approve -> activate
# -> rollback -> audit. Purely additive: with no active_version.json the
# serving path keeps using the configured master exactly as before.
# ---------------------------------------------------------------------------
@app.get("/inventory", response_class=HTMLResponse)
def inventory_page(username: str = Depends(get_current_username)):
    """The provisional inventory workspace page."""
    from market.inventory_workspace import current_stamp

    with open("app/static/inventory.html", "r", encoding="utf-8") as f:
        html_content = f.read()
    html_content = html_content.replace("__INV_CHIP__", current_stamp()["label"])
    return HTMLResponse(content=html_content, status_code=200)


@app.get("/api/inventory/current")
def inventory_current_endpoint(username: str = Depends(get_current_username)):
    """Active version, truthful stamp, version list and audit tail."""
    from market import inventory_workspace as _ws

    return _ws.current()


@app.get("/api/inventory/versions")
def inventory_versions_endpoint(username: str = Depends(get_current_username)):
    from market import inventory_workspace as _ws

    return {"versions": _ws.list_versions()}


@app.get("/api/inventory/template.csv")
def inventory_template_endpoint(username: str = Depends(get_current_username)):
    """The CSV template download (explicit units, formula-escaped)."""
    from market import inventory_workspace as _ws

    return Response(
        content=_ws.template_csv(),
        media_type="text/csv",
        headers={"Content-Disposition":
                 'attachment; filename="inventory_template.csv"'},
    )


@app.post("/api/inventory/upload")
async def inventory_upload_endpoint(
    request: Request,
    filename: str = "",
    username: str = Depends(get_current_username),
):
    """Upload a CSV/JSONL inventory (raw body; no multipart dependency)."""
    from market import inventory_workspace as _ws

    data = await request.body()
    try:
        return _ws.create_upload(data, filename, actor=username or "operator")
    except _ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/inventory/preview/{version_id}")
def inventory_preview_endpoint(
    version_id: str,
    limit: int = 50,
    username: str = Depends(get_current_username),
):
    """Column map, validation report and an escaped row preview."""
    from market import inventory_workspace as _ws

    try:
        return _ws.preview(version_id, limit=max(1, min(limit, 200)))
    except _ws.WorkspaceError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/api/inventory/approve")
def inventory_approve_endpoint(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    from market import inventory_workspace as _ws

    body = payload or {}
    try:
        return _ws.approve(str(body.get("version_id") or ""),
                           actor=username or "operator")
    except _ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/inventory/activate")
def inventory_activate_endpoint(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    from market import inventory_workspace as _ws

    body = payload or {}
    try:
        return _ws.activate(str(body.get("version_id") or ""),
                            actor=username or "operator")
    except _ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.post("/api/inventory/rollback")
def inventory_rollback_endpoint(
    payload: Optional[Dict[str, Any]] = Body(default=None),
    username: str = Depends(get_current_username),
):
    from market import inventory_workspace as _ws

    body = payload or {}
    target = body.get("version_id") or None
    try:
        return _ws.rollback(str(target) if target else None,
                            actor=username or "operator")
    except _ws.WorkspaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

# ---------------------------------------------------------------------------
# Showcase readiness (2026-11-21): one live, truthful system-status surface
# for the owner dashboard. It serves INFRASTRUCTURE truth only: that the
# server is up, that the databases open, how many rows the desk's own
# stores hold, which inventory source is active (the MODE - never the
# master's figures) and the recorded test evidence. No market figure,
# no customer text and no filesystem path is served here. The numbers are
# the desk's own counters - the same class the operator-activity route
# already serves. Registered in tests/test_m5_surface_completeness.py;
# the surface itself is checked in tests/test_system_status.py.
# ---------------------------------------------------------------------------
import time as _time
import sqlite3 as _sqlite3

APP_VERSION = "1.0.0"
_APP_STARTED_AT = _time.time()
_STATUS_EVIDENCE_DEFAULT = "evaluation/reports/system_status_evidence.json"


def _table_counts(db_path: str) -> Dict[str, int]:
    """Row counts of every table in one SQLite file, opened READ-ONLY.

    A missing or unreadable file yields {} - the route answers with what
    it can see instead of failing the whole page. Nothing here writes.
    """
    counts: Dict[str, int] = {}
    try:
        uri = "file:" + str(db_path).replace("\\", "/") + "?mode=ro"
        conn = _sqlite3.connect(uri, uri=True)
        try:
            names = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for name in names:
                try:
                    counts[str(name)] = int(conn.execute(
                        'SELECT COUNT(*) FROM "%s"' % name).fetchone()[0])
                except Exception:  # per-table best effort, never fatal
                    pass
        finally:
            conn.close()
    except Exception:
        pass
    return counts


@app.get("/api/system-status")
def system_status_endpoint(username: str = Depends(get_current_username)):
    """Live infrastructure truth for the System status view.

    Every value is computed at request time from the running server.
    Nothing is cached and nothing is a market figure: the inventory MODE
    only (master vs workspace) - the guarded /api/inventory/current route
    remains the one place that serves the master's fingerprint, row count
    and date range.
    """
    from datetime import datetime, timezone

    from data.db import DEFAULT_DB_PATH
    from market.conversation_log import default_log_path
    from market.inventory_workspace import resolve_active_source
    from market.lead_pipeline import default_pipeline_path
    from market.lead_state import default_store_path as _state_path
    from market.pilot_feedback import default_feedback_path
    from market.unmet_demand import default_store_path as _demand_path

    payload: Dict[str, Any] = {
        "status": "ok",
        "app": {"name": "Faisal Hills AI Lead Desk", "version": APP_VERSION},
        "runtime": {
            "started_at": datetime.fromtimestamp(
                _APP_STARTED_AT, tz=timezone.utc).isoformat(),
            "uptime_seconds": int(_time.time() - _APP_STARTED_AT),
        },
        "database": {"reachable": False, "tables": {}},
        "stores": {
            "conversation_log": {},
            "lead_state": {},
            "unmet_demand": {},
            "lead_pipeline": {},
            "pilot_feedback": {},
        },
        "inventory": {"mode": None, "serving": False},
        "guards": {
            "fact_guard": (hasattr(fact_guard, "public_report")
                           and hasattr(fact_guard, "guard_payload")),
            "evidence": hasattr(_evidence, "build_listing_evidence"),
            "pipeline": callable(handle_message),
        },
        "tests": None,
    }

    payload["database"]["reachable"] = os.path.isfile(str(DEFAULT_DB_PATH))
    payload["database"]["tables"] = _table_counts(str(DEFAULT_DB_PATH))

    payload["stores"]["conversation_log"] = _table_counts(default_log_path())
    payload["stores"]["lead_state"] = _table_counts(_state_path())
    payload["stores"]["unmet_demand"] = _table_counts(_demand_path())
    payload["stores"]["lead_pipeline"] = _table_counts(default_pipeline_path())
    payload["stores"]["pilot_feedback"] = _table_counts(default_feedback_path())

    try:
        active = resolve_active_source()
        payload["inventory"]["mode"] = "workspace" if active else "master"
        payload["inventory"]["serving"] = True
    except Exception:
        payload["inventory"]["serving"] = False

    # The recorded test evidence (written by the verification run, never
    # by this route). A missing file -> no claim is made (tests: None)
    # and the page says so, instead of inventing a number.
    evidence_path = os.environ.get("FH_STATUS_EVIDENCE") or _STATUS_EVIDENCE_DEFAULT
    try:
        with open(evidence_path, "r", encoding="utf-8") as _fh:
            evidence_file = json.load(_fh)
        if isinstance(evidence_file, dict):
            payload["tests"] = {
                "collected": int(evidence_file.get("tests_collected", 0)) or None,
                "failed": int(evidence_file.get("tests_failed", 0)),
                "ran_at": str(evidence_file.get("ran_at", "")),
                "command": str(evidence_file.get("command", "")),
            }
    except Exception:
        payload["tests"] = None

    return payload


# Run the app if this file is executed directly
if __name__ == "__main__":
    init_app_db()
    uvicorn.run(app, host="127.0.0.1", port=8080)

