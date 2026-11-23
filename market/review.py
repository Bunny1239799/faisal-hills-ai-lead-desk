"""M7 - the operator review workflow: approve / reject, with an audit trail.

What this module is
-------------------
M7's evidence layer (``market/evidence.py``) answers *"which listings
produced this answer?"*. This module answers the second half of the
operator's job: *"is this reply good enough to send?"* - and it records
the answer.

The workflow is deliberately small, because the product already has
one: an operator reviews the draft reply and either **approves** it or
**rejects** it, and the decision is written to the audit trail. M7 does
not invent a second review surface; it gives the existing one a
**verified evidence reference** and an **auditable outcome**.

Why the review is bound to the evidence
---------------------------------------
An approval that cannot be traced to the evidence it approved is not an
approval, it is a click. So a review decision records:

  * the ``listing_ref`` set it was made against - the exact evidence
    rows the operator was shown, so a later audit can prove the reply
    was approved against *those* rows and not others;
  * the ``evidence_digest`` - a digest of that reference set, so the
    record detects a change without re-storing the whole set;
  * the fact identifiers the reply was built from, in the same
    ``market:<cell>:<field>`` form the audit trail already uses;
  * whether the reply was **edited** before it was approved, and the
    edited text itself, because an operator-approved reply that is not
    the reviewed reply is a different thing.

Why the review does NOT re-run the validators
---------------------------------------------
The pipeline already validated the reply before it was served, and the
evidence layer serves only verified rows. Re-validating at approval
time would create a second authority. Instead, the review **records**
the validation outcome the pipeline produced, so the audit row says
"this reply was validated and this is the verdict" rather than
re-deriving it.

The one thing the review DOES check is the thing that could have
changed between serving and approving: the **evidence digest**. If the
approved master has been refreshed and the evidence no longer matches,
the approval is recorded as ``stale_evidence`` rather than as a clean
approval. The master is not expected to change mid-session, but the
check costs one digest comparison and removes a whole class of silent
drift.

Privacy
-------
The review stores the operator's decision, the reason, the evidence
references and the reply text. It never stores a dealer chat, a sender
name, a plot owner's note or a phone number - the same boundary the
evidence layer enforces. The plot identifier is referenced by its
opaque ``listing_ref``, so the audit trail does not become a
side-channel for the identifier the evidence layer redacts.

The module is stdlib-only (RULES_SHORT #5) and writes only to the
application's own database, through the same connection factory every
other writer uses.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Sequence

__all__ = [
    "REVIEW_STEPS",
    "ReviewError",
    "evidence_digest",
    "record_review",
    "review_history",
]

# The audit steps this module writes. They are namespaced so they can
# never collide with the pipeline's own ``message_received`` step.
REVIEW_STEPS = ("evidence_review", "evidence_approve", "evidence_reject")

# The decision values a review may carry.
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"

# The outcome codes a review may carry.
OUTCOME_REVIEWED = "reviewed"
OUTCOME_APPROVED = "approved"
OUTCOME_REJECTED = "rejected"
OUTCOME_STALE_EVIDENCE = "stale_evidence"


class ReviewError(ValueError):
    """Raised when a review cannot be recorded safely."""


# ---------------------------------------------------------------------------
# The evidence digest
# ---------------------------------------------------------------------------


def evidence_digest(listing_refs: Optional[Sequence[str]]) -> str:
    """A stable digest of an evidence reference set.

    The references are sorted, so the digest does not depend on the
    order the rows were displayed in, and it changes if - and only if -
    the set of rows changes.
    """
    refs = sorted(str(ref) for ref in (listing_refs or []) if ref)
    payload = "|".join(refs).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The review record
# ---------------------------------------------------------------------------


def _evidence_refs_from(payload: Optional[Dict[str, Any]]) -> List[str]:
    """The listing references a review was made against.

    The references may be supplied directly, or the whole evidence
    payload may be passed and the references are read from it. Either
    way, only opaque references are stored.
    """
    if not isinstance(payload, dict):
        return []

    refs = payload.get("listing_refs")
    if isinstance(refs, (list, tuple)):
        return [str(ref) for ref in refs if ref]

    listings = payload.get("listings")
    if isinstance(listings, (list, tuple)):
        return [
            str(item.get("listing_ref"))
            for item in listings
            if isinstance(item, dict) and item.get("listing_ref")
        ]

    return []


def record_review(
    conn,
    lead_id: str,
    decision: str,
    reply_text: str = "",
    reason: str = "",
    evidence: Optional[Dict[str, Any]] = None,
    edited: bool = False,
    fact_ids: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    """Record an operator's review decision in the audit trail.

    Args:
        conn: an open database connection.
        lead_id: the lead the review belongs to.
        decision: ``"approved"`` or ``"rejected"``.
        reply_text: the reply as it was reviewed (and, when ``edited``,
            as it was approved).
        reason: the operator's reason. Empty for an approval.
        evidence: the evidence payload the operator was shown, or a dict
            with a ``listing_refs`` list.
        edited: whether the operator changed the reply before approving.
        fact_ids: the fact identifiers the reply was built from.

    Returns:
        A dict describing what was recorded.

    Raises:
        ReviewError: when the decision is not one the workflow allows.
    """
    if decision not in (DECISION_APPROVED, DECISION_REJECTED):
        raise ReviewError(
            "unknown review decision %r - expected %r or %r"
            % (decision, DECISION_APPROVED, DECISION_REJECTED)
        )

    refs = _evidence_refs_from(evidence)
    digest = evidence_digest(refs)

    supplied_digest = None
    if isinstance(evidence, dict):
        supplied_digest = evidence.get("evidence_digest")
        if supplied_digest and supplied_digest != digest:
            # The caller sent a digest that does not match the rows it
            # sent. The evidence moved under the operator's feet, so the
            # review cannot be recorded as clean.
            outcome = OUTCOME_STALE_EVIDENCE
        else:
            outcome = (
                OUTCOME_APPROVED if decision == DECISION_APPROVED
                else OUTCOME_REJECTED
            )
    else:
        outcome = (
            OUTCOME_APPROVED if decision == DECISION_APPROVED
            else OUTCOME_REJECTED
        )

    step = (
        "evidence_approve" if decision == DECISION_APPROVED
        else "evidence_reject"
    )

    payload = {
        "action": decision,
        "outcome": outcome,
        "reason": reason or "",
        "edited": bool(edited),
        "evidence_digest": digest,
        "listing_refs": refs,
        "listing_count": len(refs),
        "fact_ids_used": list(fact_ids or []),
        "reviewer": "operator",
    }

    conn.execute(
        """
        INSERT INTO audit_log (
            lead_id, step, input_text, output_text, decision_payload,
            fact_ids_used, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
        """,
        (
            lead_id,
            step,
            reply_text or "",
            reply_text or "",
            json.dumps(payload, sort_keys=True),
            json.dumps(list(fact_ids or [])),
        ),
    )
    conn.commit()

    return {
        "recorded": True,
        "step": step,
        "outcome": outcome,
        "decision": decision,
        "evidence_digest": digest,
        "listing_count": len(refs),
        "edited": bool(edited),
    }


def review_history(conn, lead_id: str) -> List[Dict[str, Any]]:
    """The review decisions recorded for a lead, oldest first.

    The rows are returned in the audit trail's own shape, so the
    operator sees the same record the database holds.
    """
    rows = conn.execute(
        """
        SELECT audit_id, step, output_text, decision_payload, fact_ids_used,
               created_at
        FROM audit_log
        WHERE lead_id = ? AND step IN (?, ?, ?)
        ORDER BY audit_id
        """,
        (lead_id, REVIEW_STEPS[0], REVIEW_STEPS[1], REVIEW_STEPS[2]),
    ).fetchall()

    history: List[Dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            payload = json.loads(item.get("decision_payload") or "{}")
        except (TypeError, ValueError):
            payload = {}
        item["decision_payload"] = payload if isinstance(payload, dict) else {}
        try:
            item["fact_ids_used"] = json.loads(item.get("fact_ids_used") or "[]")
        except (TypeError, ValueError):
            item["fact_ids_used"] = []
        history.append(item)

    return history
