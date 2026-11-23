"""M11.2 - the input normalizer: the words a dealer actually writes.

Why this module exists
-----------------------
A dealer does not type clean English. They write "5 marla", "80 lakh",
"1 crore", "30x60", "5-marla", "5 marle", "block c", "FHC", "8 mn",
"3 month mein" and the occasional typo. The M9 extractor and the market
extractor already read most of that, but not all of it, and where they
differ the **qualification** layer and the **lookup** layer can read two
different conversations.

This module puts a small, tested normalizer in front of the existing
extractors, so that the whole product reads ONE canonical form of what
the dealer said. It is the smallest possible version of the idea in the
master file (section 7.2): "most real-world failures come from here,
not from the safety layers".

The rules, and where each one comes from
----------------------------------------
Every rule below uses a term that **already exists in this repository**.
No dealer term and no business definition was invented.

* the **dimension table** is DEC-10's own table - 25x50 = 5 marla,
  30x60 = 7 marla, 35x70 = 10 marla, 40x80 = 14 marla, 50x90 = 20 marla
  (1 kanal) and 75x120 = 40 marla (2 kanal). **30x50 is NOT mapped**:
  DEC-11 records it as unconfirmed, and an unconfirmed size is left
  alone.
* the **amount units** are the units `market.qualify` already
  understands - lakh, lac, crore, cr, million, M. The only unit it does
  not read is "mn", so that is the only one this module rewrites.
* the **block aliases** are `market.price_lookup`'s own alias table
  (FHA/FHB/FHC). The parked blocks (FHD, FHE) are deliberately **not**
  rewritten: the scope rule must see them exactly as the dealer wrote
  them.
* the **Urdu digits** are converted by `market.extract.normalize_urdu_digits`,
  the repository's own function - this module does not re-implement it.
* the **marla spellings** are the ones `market.extract` already accepts
  (marla, marlas, marle, marlay, marley).

The two guarantees
------------------
1. **The normalizer never invents.** A dimension it does not know, an
   amount it cannot read, a block it does not recognise - all are left
   exactly as they are. The extractor then reads the original text, and
   if it cannot, the requirement stays **unknown**. That is the correct
   outcome: an unknown requirement is a known unknown.
2. **The normalizer never loses.** Every rewrite is a *widening* of a
   form the extractor already understands. The tests assert that the
   normalized text yields **at least** the requirements of the original
   text, and that it never changes one that was already read.

The module is stdlib-only (RULES_SHORT #5), reads nothing, writes nothing
and never calls a model.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "DEC10_DIMENSIONS",
    "NormalizedMessage",
    "normalize_message",
]


# DEC-10's own size table. The value is the marla size.
#
# "30x50" is deliberately **absent**: DEC-11 records 30x50 = 6 marla as
# unconfirmed, and an unconfirmed size is not turned into a requirement.
DEC10_DIMENSIONS: Dict[Tuple[int, int], float] = {
    (25, 50): 5.0,
    (30, 60): 7.0,
    (35, 70): 10.0,
    (40, 80): 14.0,
    (50, 90): 20.0,
    (75, 120): 40.0,
}


class NormalizedMessage:
    """The canonical form of one dealer message.

    Attributes:
        text: the canonical text. This is what the extractors read and
            what the conversation stores.
        changes: the rewrites that were applied, each
            ``{"kind", "before", "after"}``. Empty when the message was
            already canonical.
    """

    __slots__ = ("text", "changes")

    def __init__(self, text: str, changes: Optional[List[Dict[str, str]]] = None) -> None:
        self.text = text
        self.changes = list(changes or [])

    @property
    def changed(self) -> bool:
        """Whether anything was rewritten."""
        return bool(self.changes)

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "changes": [dict(c) for c in self.changes]}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "NormalizedMessage(text=%r, changes=%d)" % (self.text,
                                                           len(self.changes))


# --- the rules ------------------------------------------------------------

_DIMENSION_RE = re.compile(r"(?<![\d.])(\d{2,3})\s*[xX*×]\s*(\d{2,3})(?![\d.])")

_MN_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*mn\b", re.IGNORECASE)

_HYPHEN_MARLA_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*-\s*marla\b", re.IGNORECASE)

_MARLA_SPELLING_RE = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(?:marle|marlay|marley)\b", re.IGNORECASE)

_MARLAS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*marlas\b", re.IGNORECASE)

_TYPOS = (
    (re.compile(r"\bmarala\b", re.IGNORECASE), "marla"),
    (re.compile(r"\bmlara\b", re.IGNORECASE), "marla"),
    (re.compile(r"\bblok\b", re.IGNORECASE), "block"),
    (re.compile(r"\bblk\b", re.IGNORECASE), "block"),
)

_MONTH_RE = re.compile(r"\b(\d+)\s*month\b", re.IGNORECASE)

_BLOCK_ALIASES = (
    (re.compile(r"\bfhc\b", re.IGNORECASE), "block c"),
    (re.compile(r"\bfhb\b", re.IGNORECASE), "block b"),
    (re.compile(r"\bfha\b", re.IGNORECASE), "block a"),
)


def _size_label(size: float) -> str:
    """The marla size as the rest of the product writes it."""
    if float(size).is_integer():
        return "%d marla" % int(size)
    return ("%s marla" % size)


def normalize_message(text: Optional[str]) -> NormalizedMessage:
    """Return the canonical form of a dealer message.

    The message is rewritten only where a form the existing extractors
    do not read would otherwise be lost. Anything the module does not
    recognise is left exactly as it is.

    Args:
        text: the dealer's own words.

    Returns:
        A :class:`NormalizedMessage`.
    """
    original = "" if text is None else str(text)
    changes: List[Dict[str, str]] = []
    current = original

    if not current.strip():
        return NormalizedMessage(current, changes)

    # --- Urdu digits (the repository's own function) --------------------
    try:
        from market.extract import normalize_urdu_digits

        converted = normalize_urdu_digits(current)
        if converted != current:
            changes.append({"kind": "urdu_digits", "before": current,
                            "after": converted})
            current = converted
    except Exception:  # pragma: no cover - the module is in this repo
        pass

    # --- dimension names (DEC-10's table only) --------------------------
    def _dimension(match: "re.Match") -> str:
        width = int(match.group(1))
        height = int(match.group(2))
        size = DEC10_DIMENSIONS.get((width, height))
        if size is None:
            # An unknown dimension is left exactly as it is: the
            # requirement stays unknown rather than being guessed.
            return match.group(0)
        return _size_label(size)

    replaced = _DIMENSION_RE.sub(_dimension, current)
    if replaced != current:
        changes.append({"kind": "dimension", "before": current,
                        "after": replaced})
        current = replaced

    # --- "8 mn" -> "8 million" ------------------------------------------
    replaced = _MN_RE.sub(r"\1 million", current)
    if replaced != current:
        changes.append({"kind": "amount", "before": current, "after": replaced})
        current = replaced

    # --- marla spellings -------------------------------------------------
    for pattern, replacement, kind in (
        (_HYPHEN_MARLA_RE, r"\1 marla", "marla_spelling"),
        (_MARLA_SPELLING_RE, r"\1 marla", "marla_spelling"),
        (_MARLAS_RE, r"\1 marla", "marla_spelling"),
    ):
        replaced = pattern.sub(replacement, current)
        if replaced != current:
            changes.append({"kind": kind, "before": current,
                            "after": replaced})
            current = replaced

    # --- simple typos ----------------------------------------------------
    for pattern, replacement in _TYPOS:
        replaced = pattern.sub(replacement, current)
        if replaced != current:
            changes.append({"kind": "typo", "before": current,
                            "after": replaced})
            current = replaced

    # --- a timeline in months -------------------------------------------
    replaced = _MONTH_RE.sub(r"\1 months", current)
    if replaced != current:
        changes.append({"kind": "timeline", "before": current,
                        "after": replaced})
        current = replaced

    # --- block aliases (the in-scope ones only) -------------------------
    for pattern, replacement in _BLOCK_ALIASES:
        replaced = pattern.sub(replacement, current)
        if replaced != current:
            changes.append({"kind": "block", "before": current,
                            "after": replaced})
            current = replaced

    return NormalizedMessage(current, changes)
