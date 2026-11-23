"""Deterministic property lookup for the Faisal Hills AI Lead Desk.

This is the module the handoff calls ``price_lookup.py`` (section 8, step 4).
It is a thin, LLM-free layer over the already-proven query engine in
``market/fh_query.py`` — it does NOT duplicate that logic, so there is one
implementation of the lookup and no drift between two copies.

What this module adds on top of ``fh_query``:

* **Scope enforcement.** Only blocks listed in ``config/policies.json`` ->
   ``active_blocks`` may produce a price. A parked block (D, Executive) or an
   unknown block is refused *before* any row is counted.
* **Policy-driven answerability.** The "not enough data" threshold, the
   answer template, the escalation/refusal wording and the privacy flags all
   come from ``config/policies.json`` rather than being hard-coded, so the
   owner can change them without touching Python.
* **A single, explicit result shape** that the customer-facing flow, the
   console API and the 20-question check all consume.

Hard rules this module keeps (handoff section 2, section 7, DEC-03):

* It never calls an LLM and never invents a price.
* It reads the approved master **read-only** and never writes to it.
* It returns no phone number, no sender name and no raw dealer text.

The thin wrapper required by the handoff's directory layout lives at
``D:\\AI-Projects\\real-estate-agent\\scripts\\price_lookup.py`` and imports
this module. That directory is not a git repository, so the version
controlled implementation deliberately lives here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from market.fh_query import (
    MASTER_PATH,
    load_inventory,
    query_inventory,
    summarize_matches,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
POLICIES_PATH = CONFIG_DIR / "policies.json"
QUESTIONS_PATH = CONFIG_DIR / "questions.json"

# The v1 scope as hard-coded fallback, used only if config/policies.json is
# unreadable. The config file is the source of truth (see load_policies).
_FALLBACK_ACTIVE_BLOCKS = ("A", "B", "C")
_FALLBACK_MIN_LISTINGS = 3


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_policies(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the policy configuration.

    Falls back to the hard-coded v1 scope if the file is missing or
    malformed, so the lookup never fails closed by accident.
    """
    target = Path(path) if path is not None else POLICIES_PATH
    try:
        policies = _read_json(target)
    except (OSError, ValueError):
        return {
            "active_blocks": list(_FALLBACK_ACTIVE_BLOCKS),
            "min_listings_for_answer": _FALLBACK_MIN_LISTINGS,
            "price_policy": {},
            "answer_policy": {},
            "privacy_policy": {},
            "lookup_policy": {},
            "escalation_policy": {},
        }
    policies.setdefault("active_blocks", list(_FALLBACK_ACTIVE_BLOCKS))
    policies.setdefault("min_listings_for_answer", _FALLBACK_MIN_LISTINGS)
    return policies


def load_questions(path: Optional[Path] = None) -> Dict[str, Any]:
    """Load the hand-checked question set (handoff section 7 rule 5)."""
    target = Path(path) if path is not None else QUESTIONS_PATH
    return _read_json(target)


# The ONE alias table for block spellings.
#
# The project used three spellings for the same blocks:
#   * "E"                       - app/policy.py's tokenizer
#   * "EXECUTIVE" / "Executive" - the approved master's `block` column
#   * "EXEC"                    - market/blocks.json and the entity
#                                extractor (market/extract.py)
#
# Every layer that has to recognise a block uses this table, so a block
# that is in scope is in scope for all of them.
_BLOCK_ALIASES = {
    "A": "A", "FHA": "A", "BLOCK A": "A",
    "B": "B", "FHB": "B", "BLOCK B": "B",
    "C": "C", "FHC": "C", "BLOCK C": "C",
    "D": "D", "FHD": "D", "BLOCK D": "D",
    "E": "E", "FHE": "E", "BLOCK E": "E",
    "EXEC": "E", "EXEC BLOCK": "E", "BLOCK EXEC": "E",
    "EXECUTIVE": "E", "EXECUTIVE BLOCK": "E", "BLOCK EXECUTIVE": "E",
}


def _normalize_block(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    if text in _BLOCK_ALIASES:
        return _BLOCK_ALIASES[text]
    return text


def canonical_block(value: Any) -> Optional[str]:
    """The canonical block code for any spelling, or None if unknown.

    This is the single entry point every layer uses to compare blocks.
    """
    return _normalize_block(value)


def _number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> Optional[int]:
    number = _number(value)
    return None if number is None else int(number)


def classify_block(
    block: Any,
    policies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Classify a requested block against the configured active scope.

    Returns a dict with:
      ``status``  one of ``active`` | ``out_of_scope`` | ``not_specified``
      ``block``   the canonical block code, or None
    """
    config = policies if policies is not None else load_policies()

    # Canonicalise the CONFIGURED codes exactly like the requested block.
    # Without this, a config that says "EXECUTIVE" would never match a
    # question that says "Executive", because the requested block is
    # canonicalised to "E" and the configured one was not.
    active = set()
    for configured in config.get("active_blocks", []):
        code = _normalize_block(configured)
        if code:
            active.add(code)

    normalized = _normalize_block(block)

    if normalized is None:
        return {"status": "not_specified", "block": None}

    if normalized in active:
        return {"status": "active", "block": normalized}

    return {"status": "out_of_scope", "block": None}


def _active_scope_inventory(active_blocks: List[str]) -> List[Dict[str, Any]]:
    """Master rows restricted to the configured active blocks.

    A question that names no block still must not be answered from a parked
    block, so the scope restriction is applied to the row set itself rather
    than only to the block filter.

    The configured codes and the master rows are canonicalised the same way,
    so a configuration that names a block by a different spelling still
    matches the rows.
    """
    rows = load_inventory(MASTER_PATH)
    wanted = set()
    for code in active_blocks:
        canonical = _normalize_block(code)
        if canonical:
            wanted.add(canonical)
    return [
        row for row in rows
        if _normalize_block(row.get("block")) in wanted
    ]


def closest_match(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    policies: Optional[Dict[str, Any]] = None,
    inventory: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Find the closest available alternative for a thin (not-answerable) set.

    Handoff v2 section 7.4 and FH-02 R17 require that a question with too
    few listings shows "the closest match instead of a number". The closest
    match is a *different* block/size cell that does have enough listings,
    so the dealer can be pointed at something real.

    The ranking is deliberately simple and explainable:

    1. the same block with the nearest size that is answerable;
    2. otherwise the nearest size in the same block;
    3. otherwise the nearest size in any active block.

    "Nearest" is the absolute difference in marla. "Answerable" is the
    same rule the lookup itself uses: at least ``min_listings_for_answer``
    matching rows AND a usable price. The result carries **no price**:
    the point is to show the dealer where to look, not to quote a figure
    for a cell that failed the evidence threshold (M5).

    M5 (D-32): ``matched_plots`` counts **every** matching row in the
    cell - the same rule the normal lookup uses for its own
    ``matched_plots`` - so the operator sees one sample size per cell.
    ``priced_plots`` reports how many of those rows carry a price, which
    is the evidence-quality figure the old count was really measuring.

    Returns ``None`` when nothing in scope is answerable.
    """
    config = policies if policies is not None else load_policies()
    active_blocks = list(config.get("active_blocks", _FALLBACK_ACTIVE_BLOCKS))
    min_listings = int(config.get("min_listings_for_answer", _FALLBACK_MIN_LISTINGS))

    rows = inventory if inventory is not None else _active_scope_inventory(active_blocks)

    requested_block = canonical_block(block)
    requested_size = _number(size_marla)

    if not rows:
        return None

    # Group the in-scope inventory by (block, size) and count the rows of
    # each cell, plus how many of them carry a usable price.
    cells: Dict[Tuple[Any, Any], Dict[str, int]] = {}
    for row in rows:
        key = (canonical_block(row.get("block")), _number(row.get("size_marla")))
        cell = cells.setdefault(key, {"count": 0, "priced": 0})
        cell["count"] += 1
        if _number(row.get("price_median_pkr")) is not None:
            cell["priced"] += 1

    if not cells:
        return None

    def _distance(key):
        _block, size = key
        if requested_size is None or size is None:
            return float("inf")
        return abs(size - requested_size)

    def _answerable(key):
        cell = cells.get(key, {"count": 0, "priced": 0})
        return cell["count"] >= min_listings and cell["priced"] > 0

    ordered = sorted(
        cells.keys(),
        key=lambda k: (_distance(k), str(k[0]), k[1] if k[1] is not None else 0),
    )

    chosen = None
    for key in ordered:
        if requested_block and key[0] == requested_block and _answerable(key):
            chosen = key
            break
    if chosen is None:
        for key in ordered:
            if requested_block and key[0] == requested_block:
                chosen = key
                break
    if chosen is None:
        for key in ordered:
            if _answerable(key):
                chosen = key
                break
    if chosen is None and ordered:
        chosen = ordered[0]

    if chosen is None:
        return None

    chosen_block, chosen_size = chosen
    cell = cells.get(chosen, {"count": 0, "priced": 0})
    return {
        "block": chosen_block,
        "size_marla": chosen_size,
        "matched_plots": cell["count"],
        "priced_plots": cell["priced"],
        "same_block": bool(requested_block and chosen_block == requested_block),
        "size_difference_marla": (
            None
            if (requested_size is None or chosen_size is None)
            else abs(chosen_size - requested_size)
        ),
        "note": "Closest available alternative with more data - no price shown.",
    }


def lookup_price(
    block: Optional[Any] = None,
    size_marla: Optional[Any] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
    policies: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Look up a price range for a block/size question.

    Returns a dict with the shape:

        {
          "answerable": bool,
          "reply_mode": "verified_market_facts" | "insufficient_data"
                        | "out_of_scope" | "no_lookup",
          "filters": {...},
          "facts": {...},          # same shape as app.market_adapter
          "summary": {...},        # count/min/median/max/date/coverage
          "human_action": str,
          "reason": str,           # why it is not answerable, when it is not
        }

    ``facts`` never contains a sender name, a phone number or raw dealer
    text, and never claims a sender count.
    """
    config = policies if policies is not None else load_policies()
    active_blocks = list(config.get("active_blocks", _FALLBACK_ACTIVE_BLOCKS))
    min_listings = int(
        config.get("min_listings_for_answer", _FALLBACK_MIN_LISTINGS)
    )
    price_policy = config.get("price_policy", {}) or {}
    answer_policy = config.get("answer_policy", {}) or {}

    filters = {
        "block": None,
        "size_marla": _number(size_marla),
        "corner": corner,
        "sun_facing": sun_facing,
        "ndc_open": ndc_open,
    }

    scope = classify_block(block, config)

    if scope["status"] == "out_of_scope":
        return {
            "answerable": False,
            "reply_mode": "out_of_scope",
            "filters": {"block": block, "size_marla": filters["size_marla"]},
            "facts": None,
            "summary": {
                "matched_plots": 0,
                "observation_count": 0,
                "price_min_pkr": None,
                "price_median_pkr": None,
                "price_max_pkr": None,
                "latest_date": None,
                "coverage_level": "insufficient",
                "trust_status": "out_of_scope",
                "answerable_for_demo": False,
            },
            "human_action": "confirm_with_team",
            "reason": (
                "Block %s is outside the active scope (%s)."
                % (block, ", ".join(active_blocks))
            ),
            "reply": render_reply(
                False, None,
                answer_policy=answer_policy,
            ),
        }

    if scope["status"] == "active":
        filters["block"] = scope["block"]

    if filters["size_marla"] is None and not any(
        filters[key] is not None for key in ("corner", "sun_facing", "ndc_open")
    ):
        return {
            "answerable": False,
            "reply_mode": "no_lookup",
            "filters": {"block": filters["block"], "size_marla": None},
            "facts": None,
            "summary": {
                "matched_plots": 0,
                "observation_count": 0,
                "price_min_pkr": None,
                "price_median_pkr": None,
                "price_max_pkr": None,
                "latest_date": None,
                "coverage_level": "insufficient",
                "trust_status": "no_filters",
                "answerable_for_demo": False,
            },
            "human_action": "confirm_with_team",
            "reason": "No block, size or feature filter was supplied.",
            "reply": render_reply(
                False, None,
                answer_policy=answer_policy,
            ),
        }

    inventory = _active_scope_inventory(active_blocks)
    rows = query_inventory(inventory=inventory, **filters)
    result = summarize_matches(rows)

    matched = int(result["matched_plots"])
    median = _number(result["price_median_pkr"])

    has_price = median is not None
    enough = matched >= min_listings
    answerable = bool(enough and has_price)

    facts = {
        "facts_source": "FaisalHills verified partial master",
        "facts_type": "dealer asking-price observations",
        "matched_plots": matched,
        "observation_count": int(result["observation_count"]),
        "price_min_pkr": _number(result["price_min_pkr"]),
        "price_median_pkr": median,
        "price_max_pkr": _number(result["price_max_pkr"]),
        "latest_date": result["latest_date"],
        "coverage_level": result["coverage_level"],
        "trust_status": result["trust_status"],
        "answerable_for_demo": answerable,
        "distinct_source_chats": int(result["distinct_source_chats"]),
        "sender_count_available": False,
        "price_basis": price_policy.get("price_basis", "dealer_asking_price"),
        "is_sold_price": bool(price_policy.get("is_sold_price", False)),
        "min_listings_for_answer": min_listings,
    }

    if answerable:
        facts["human_action"] = "human_approval_required"
        facts["reply_mode"] = "verified_market_facts"
        reason = ""
    elif not enough:
        facts["human_action"] = "confirm_with_team"
        facts["reply_mode"] = "insufficient_data"
        reason = (
            "Only %d matching listing(s); at least %d are required."
            % (matched, min_listings)
        )
    else:
        facts["human_action"] = "confirm_with_team"
        facts["reply_mode"] = "insufficient_data"
        reason = "The matching listings carry no usable price."

    # M5 (D-34): a not-answerable result must not carry a price figure in
    # ANY customer- or operator-visible field. The rendered reply already
    # omits it, but `facts` and `summary` did not - so the console API and
    # `facts_used` exposed the median for a question the product had just
    # refused ("7 marla Block B" leaked PKR 7,750,000). The counts, the
    # date and the coverage stay, because the product must still be able to
    # say *how much* data it found; the prices do not.
    closest = None
    if not answerable:
        for key in ("price_min_pkr", "price_median_pkr", "price_max_pkr"):
            facts[key] = None
        closest = closest_match(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
            policies=config,
            inventory=inventory,
        )
        facts["closest_match"] = closest
    else:
        facts["closest_match"] = None

    summary = {
        "matched_plots": matched,
        "observation_count": int(result["observation_count"]),
        "price_min_pkr": facts["price_min_pkr"],
        "price_median_pkr": facts["price_median_pkr"],
        "price_max_pkr": facts["price_max_pkr"],
        "latest_date": result["latest_date"],
        "coverage_level": result["coverage_level"],
        "trust_status": result["trust_status"],
        "answerable_for_demo": answerable,
    }
    if not answerable:
        summary["closest_match"] = closest

    return {
        "answerable": answerable,
        "reply_mode": facts["reply_mode"],
        "filters": dict(filters),
        "facts": facts,
        "summary": summary,
        "human_action": facts["human_action"],
        "reason": reason,
        "reply": render_reply(
            answerable,
            facts,
            reason,
            answer_policy,
        ),
    }


def render_reply(
    answerable: bool,
    facts: Optional[Dict[str, Any]],
    reason: str = "",
    answer_policy: Optional[Dict[str, Any]] = None,
) -> str:
    """Build the customer-facing reply from a template.

    Every number in the reply comes from ``facts`` — the template is a
    format string, so the LLM never computes or supplies a figure.
    """
    policy = answer_policy if answer_policy is not None else load_policies().get("answer_policy", {})

    if not answerable or not facts:
        base = policy.get(
            "insufficient_data_reply",
            "I need to confirm the current market information with our team "
            "before giving you a price.",
        )
        # Handoff v2 section 7.4 / FH-02 R17: show the closest match
        # instead of a number. The closest match carries no price either -
        # it points the dealer at a cell that DOES have enough data.
        closest = facts.get("closest_match") if facts else None
        if closest:
            block = closest.get("block")
            size = closest.get("size_marla")
            size_text = ""
            if size is not None:
                try:
                    size_text = " %s marla" % (int(size) if float(size).is_integer() else size)
                except (TypeError, ValueError):
                    size_text = ""
            if block and size_text:
                extra = (
                    " The closest match with more data is a %s%s plot in Block %s."
                    % (size_text.strip(), "", block)
                )
            elif block:
                extra = " The closest match with more data is in Block %s." % block
            else:
                extra = ""
            return base + extra
        return base

    template = policy.get(
        "answerable_reply_template",
        "Based on {matched_plots} matching listing{s} and {observation_count} "
        "recorded observation{s} in the current partial Faisal Hills market "
        "data, the asking-price range is PKR {price_min} to PKR {price_max}, "
        "with a median of PKR {price_median}. Latest observation date: "
        "{latest_date}. These are dealer asking prices, not confirmed sold "
        "prices. Human approval is required before sending.",
    )

    count = int(facts.get("matched_plots", 0))
    observations = int(facts.get("observation_count", 0))

    def _money(value: Any) -> str:
        number = _number(value)
        if number is None:
            return "n/a"
        return "{:,.0f}".format(number)

    # The template carries "{s}" (plural suffix for "listing") and
    # "{s_observations}" (plural suffix for "observation"). A format string
    # cannot express a conditional suffix, so the template is split on those
    # placeholders and each section is pluralised on its own.
    sections = template.split("{s_observations}")
    rendered = sections[0]
    for index, section in enumerate(sections[1:]):
        rendered += ("s" if observations != 1 else "") + section
    rendered = rendered.replace("{s}", "" if count == 1 else "s")

    return rendered.format(
        matched_plots=count,
        observation_count=observations,
        price_min=_money(facts.get("price_min_pkr")),
        price_max=_money(facts.get("price_max_pkr")),
        price_median=_money(facts.get("price_median_pkr")),
        latest_date=facts.get("latest_date") or "unknown",
    )


def _reply_has_price(text: str) -> bool:
    """True when the rendered reply contains a number that looks like a price.

    Used to prove that a not-answerable lookup never leaks a figure to the
    customer. A number of 1000 or more is treated as a price figure, which
    is the same rule the M2/M3 regression tests use.
    """
    import re

    for number in re.findall(r"\d+", text or ""):
        try:
            if int(number) >= 1000:
                return True
        except ValueError:
            continue
    return False


def answer_question(question: Dict[str, Any]) -> Dict[str, Any]:
    """Run one entry of ``config/questions.json`` through the lookup."""
    filters = question.get("filters", {}) or {}
    result = lookup_price(
        block=filters.get("block"),
        size_marla=filters.get("size_marla"),
        corner=filters.get("corner"),
        sun_facing=filters.get("sun_facing"),
        ndc_open=filters.get("ndc_open"),
    )
    return {
        "id": question.get("id"),
        "question": question.get("question"),
        "result": result,
    }


def check_questions(path: Optional[Path] = None) -> Dict[str, Any]:
    """Verify the hand-checked question set against the approved master.

    Returns a report dict with per-question results and a pass/fail count.
    """
    config = load_questions(path)
    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []

    for question in config.get("questions", []):
        filters = question.get("filters", {}) or {}
        lookup = lookup_price(
            block=filters.get("block"),
            size_marla=filters.get("size_marla"),
            corner=filters.get("corner"),
            sun_facing=filters.get("sun_facing"),
            ndc_open=filters.get("ndc_open"),
        )
        summary = lookup["summary"]

        checks: Dict[str, bool] = {}

        if "expect_matched_plots" in question:
            checks["matched_plots"] = (
                summary["matched_plots"] == question["expect_matched_plots"]
            )
        if "expect_observation_count" in question:
            checks["observation_count"] = (
                summary["observation_count"] == question["expect_observation_count"]
            )
        if "expect_median_pkr" in question:
            checks["median_pkr"] = (
                summary["price_median_pkr"] == question["expect_median_pkr"]
            )
        if "expect_min_pkr" in question:
            checks["min_pkr"] = summary["price_min_pkr"] == question["expect_min_pkr"]
        if "expect_max_pkr" in question:
            checks["max_pkr"] = summary["price_max_pkr"] == question["expect_max_pkr"]

        if question.get("must_answer"):
            checks["answerable"] = lookup["answerable"] is True
            checks["has_median"] = summary["price_median_pkr"] is not None

        if question.get("must_not_answer"):
            # The lookup may legitimately REPORT a median for a thin set -
            # that is internal information. What must never happen is a
            # price figure reaching the customer. So the check is on the
            # rendered reply, not on the internal summary.
            checks["not_answerable"] = lookup["answerable"] is False
            checks["reply_has_no_price"] = not _reply_has_price(
                lookup.get("reply", "")
            )

        passed = all(checks.values())

        entry = {
            "id": question.get("id"),
            "question": question.get("question"),
            "filters": filters,
            "expected": {
                key: question[key]
                for key in question
                if key.startswith("expect_") or key in ("must_answer", "must_not_answer")
            },
            "actual": {
                "matched_plots": summary["matched_plots"],
                "observation_count": summary["observation_count"],
                "price_min_pkr": summary["price_min_pkr"],
                "price_median_pkr": summary["price_median_pkr"],
                "price_max_pkr": summary["price_max_pkr"],
                "answerable": lookup["answerable"],
                "reply_mode": lookup["reply_mode"],
            },
            "checks": checks,
            "passed": passed,
        }
        results.append(entry)

        if not passed:
            failures.append(entry)

    return {
        "question_count": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "failed": len(failures),
        "failures": failures,
        "results": results,
    }


def main(argv: Optional[List[str]] = None) -> int:
    r"""Command line entry point.

    With no arguments (or with ``--check-questions``) the 20-question
    check against the approved master is printed. With a block and/or size
    filter the single lookup is performed and printed.

    This mirrors the thin wrapper at
    ``real-estate-agent\scripts\price_lookup.py`` exactly, so the two
    entry points cannot drift apart.
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Faisal Hills deterministic property lookup.",
    )
    parser.add_argument("--block", default=None, help="Block letter, e.g. C")
    parser.add_argument("--size-marla", default=None, help="Size in marla, e.g. 7")
    parser.add_argument("--corner", action="store_true", help="Corner plots only")
    parser.add_argument("--sun-facing", action="store_true", help="Sun-facing only")
    parser.add_argument("--ndc-open", action="store_true", help="NDC open only")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument(
        "--check-questions",
        action="store_true",
        help="Run the 20 hand-checked questions and report pass/fail",
    )

    args = parser.parse_args(argv)

    if args.check_questions or (
        args.block is None
        and args.size_marla is None
        and not args.corner
        and not args.sun_facing
        and not args.ndc_open
    ):
        report = check_questions()

        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print("QUESTIONS=%d" % report["question_count"])
            print("PASSED=%d" % report["passed"])
            print("FAILED=%d" % report["failed"])

            for entry in report["results"]:
                actual = entry["actual"]
                print(
                    "%02d | %-58s | matches=%-4d median=%-12s answerable=%s"
                    % (
                        entry["id"] or 0,
                        (entry["question"] or "")[:58],
                        actual["matched_plots"],
                        actual["price_median_pkr"],
                        actual["answerable"],
                    )
                )

        return 1 if report["failed"] else 0

    size = None
    if args.size_marla is not None:
        try:
            size = float(args.size_marla)
        except (TypeError, ValueError):
            parser.error("--size-marla must be a number")

    result = lookup_price(
        block=args.block,
        size_marla=size,
        corner=True if args.corner else None,
        sun_facing=True if args.sun_facing else None,
        ndc_open=True if args.ndc_open else None,
    )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["answerable"] else 1

    print(result["reply"])
    print()
    print("matched_plots=%s" % result["summary"]["matched_plots"])
    print("observation_count=%s" % result["summary"]["observation_count"])
    print("price_median_pkr=%s" % result["summary"]["price_median_pkr"])
    print("latest_date=%s" % result["summary"]["latest_date"])
    print("answerable=%s" % result["answerable"])
    if result.get("reason"):
        print("reason=%s" % result["reason"])
    return 0 if result["answerable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
