"""M9 - the conversation state: the requirements stated so far.

Why this module exists
-----------------------
A dealer rarely states everything in one message. The requirement may
arrive over three turns:

    "I need a plot in Block C"          -> block C
    "around 10 marla"                    -> size 10 marla
    "budget is 60 lakh"                  -> budget 6,000,000

Qualification needs all three at once. This module keeps them.

Where the state lives
---------------------
In the **existing** ``messages`` table, read back for the lead. No new
table, no schema change, no migration - the conversation is already
stored, and re-deriving the requirements from it means the state can
never drift from what the dealer actually said. The requirements are
re-extracted from the dealer's own words on every read, so a change to
the extractor changes the state consistently rather than leaving a
stale copy behind.

Why re-derive rather than store
-------------------------------
A stored copy has to be trusted. A re-derived one is checked: it comes
from the messages the application itself wrote, and the extractor is
the same code the current message goes through. There is no second
authority and no way for the state to contain something the dealer
never said.

The narrowing of the history
----------------------------
Only the **most recent** message per requirement counts. A dealer who
says "7 marla" and then "actually 10 marla" has changed their mind;
the later statement wins. The merge is done by
:func:`market.qualify.merge_requirements`, which is the single rule
for how a new statement replaces an old one.

The module is stdlib-only (RULES_SHORT #5). It reads the application's
own database and writes nothing.
"""

from __future__ import annotations

import sqlite3
from typing import Any, Dict, List, Optional

from market import qualify as _qualify

__all__ = [
    "conversation_requirements",
    "requirements_from_messages",
]


def requirements_from_messages(
    messages: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Merge the requirements stated across a list of messages.

    The messages are read in the order they were sent, oldest first,
    and each one is merged over the previous state. A requirement
    stated later wins; a requirement not restated is kept.

    Returns:
        The merged requirements. Every field is ``None`` when it was
        never stated.
    """
    merged: Dict[str, Any] = {
        "budget_min_pkr": None,
        "budget_max_pkr": None,
        "purpose": None,
        "block": None,
        "size_marla": None,
        "timeline": None,
        "source": "none",
    }

    for text in messages or []:
        if not text or not str(text).strip():
            continue
        current = _qualify.extract_requirements(text)
        merged = _qualify.merge_requirements(merged, current)

    return merged


def conversation_requirements(
    lead_id: Optional[str] = None,
    conn: Optional[sqlite3.Connection] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """The requirements stated so far in this lead's conversation.

    The lead's own messages are read back from the database, oldest
    first, and the requirements are re-derived from them. A lead with
    no messages, or a lead id that is not known, has **no** stated
    requirements - every field is ``None``.

    The current message is **not** included: the caller passes the
    current message separately, so a message is never counted twice.

    A database that cannot be read is not an error - it means the
    conversation state is unknown, and an unknown state is the same as
    no stated requirements. That is fail-closed: it can never invent a
    requirement.
    """
    if not lead_id:
        return requirements_from_messages([])

    owns_connection = False
    if conn is None:
        try:
            from data.db import get_db_connection

            conn = get_db_connection(db_path)
            owns_connection = True
        except Exception:
            return requirements_from_messages([])

    try:
        rows = conn.execute(
            "SELECT message_text FROM messages WHERE lead_id = ? "
            "ORDER BY id ASC",
            (lead_id,),
        ).fetchall()
    except Exception:
        # A database without the messages table, or a locked one, means
        # the state is unknown - never a guessed one.
        if owns_connection:
            try:
                conn.close()
            except Exception:
                pass
        return requirements_from_messages([])
    finally:
        if owns_connection:
            try:
                conn.close()
            except Exception:
                pass

    return requirements_from_messages([row[0] for row in rows])
