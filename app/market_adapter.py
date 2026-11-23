from __future__ import annotations

from typing import Any, Dict, Optional

from market import fact_guard
from market import price_lookup


def get_verified_market_facts(
    *,
    block: Optional[str] = None,
    size_marla: Optional[float] = None,
    corner: Optional[bool] = None,
    sun_facing: Optional[bool] = None,
    ndc_open: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    Deterministic bridge between the application gateway and the
    privacy-clean Faisal Hills market query layer.

    This function never calls an LLM and never generates a price.

    M4 (D-02): the v1 scope restriction now lives HERE as well as in the
    lookup, so this public function can no longer answer a question about
    a parked block. It used to call the query engine directly, and the
    engine knows nothing about the scope, so "Block E / 5 marla" was
    priced with a median of PKR 8,850,000. Any future consumer of this
    function would have inherited that hole.

    The scope comes from the SAME configuration the lookup uses
    (`config/policies.json` -> `active_blocks`) and the block is
    canonicalised with the SAME alias table, so there is one scope rule
    and one set of block spellings across the whole project.
    """

    policies = price_lookup.load_policies()

    scope = price_lookup.classify_block(block, policies)

    if scope["status"] == "active":
        block = scope["block"]

    # M5 (D-32): the adapter is now a thin, guarded facade over the ONE
    # lookup (`market.price_lookup.lookup_price`), exactly as the
    # handoff's own `real-estate-agent\scripts\price_lookup.py` wrapper
    # is. It used to call the query engine directly, so it was a second
    # implementation that could drift from the customer path - and it
    # returned the price of a THIN cell, so a consumer that showed the
    # facts would show a price for a query the product had refused to
    # answer.
    result = price_lookup.lookup_price(
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
        policies=policies,
    )

    facts = result.get("facts")

    if facts is None:
        # The lookup declined to run (a parked block, or no usable
        # filter). The zero-valued fact record keeps the shape of the
        # answer stable for every caller.
        facts = {
            "facts_source": "FaisalHills verified partial master",
            "facts_type": "dealer asking-price observations",
            "matched_plots": 0,
            "observation_count": 0,
            "price_min_pkr": None,
            "price_median_pkr": None,
            "price_max_pkr": None,
            "latest_date": None,
            "coverage_level": "insufficient",
            "trust_status": "insufficient_data",
            "answerable_for_demo": False,
            "distinct_source_chats": 0,
            "sender_count_available": False,
            "human_action": "confirm_with_team",
            "reply_mode": "insufficient_data",
        }

    # M5 (D-32): the fact set is validated against the approved master
    # before it is handed to any consumer. A fact set that does not
    # verify is replaced with a number-free one, so no consumer can
    # serve an unsupported figure through this public function.
    allowed = fact_guard.allowed_numbers_for(
        block=block,
        size_marla=size_marla,
        corner=corner,
        sun_facing=sun_facing,
        ndc_open=ndc_open,
        policies=policies,
    )
    report = fact_guard.guard_payload(facts, allowed, label="adapter")

    if not report["ok"]:
        facts = dict(facts)
        for key in (
            "price_min_pkr",
            "price_median_pkr",
            "price_max_pkr",
            "matched_plots",
            "observation_count",
            "latest_date",
        ):
            facts[key] = None
        facts["answerable_for_demo"] = False
        facts["human_action"] = "confirm_with_team"
        facts["reply_mode"] = "insufficient_data"
        facts["guard"] = report

    return {
        "filters": {
            "block": block,
            "size_marla": size_marla,
            "corner": corner,
            "sun_facing": sun_facing,
            "ndc_open": ndc_open,
        },
        "facts": facts,
    }
