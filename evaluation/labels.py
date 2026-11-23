"""Evaluation label schemas, constants, and allowed enum sets for datasets."""

from typing import Set

LEAD_TYPES: Set[str] = {
    "buyer",
    "investor",
    "renter",
    "broker",
    "existing_customer",
    "other",
}

INTENTS: Set[str] = {
    "price_inquiry",
    "availability",
    "payment_plan",
    "location",
    "site_visit",
    "legal_approval",
    "discount",
    "booking",
    "returns",
    "complaint",
    "smalltalk",
    "other",
    "prompt_injection",
}

FACTS_NEEDED_VALUES: Set[str] = {
    "pricing",
    "inventory",
    "payment_plans",
    "blocks",
    "legal_facts",
    "society_master",
    "faqs",
    "none",
}

EXPECTED_ACTIONS: Set[str] = {
    "answer_with_facts",
    "ask_clarifying",
    "escalate_human",
    "refuse",
    "smalltalk",
}

LANGUAGES: Set[str] = {
    "en",
    "ur",
    "roman_ur",
    "mixed",
}

RISK_TAGS_VALUES: Set[str] = {
    "negation",
    "short",
    "typo",
    "mixed_intent",
    "injection",
    "legal",
    "discount",
    "abusive",
    "ambiguous",
    "long",
}

REQUIRED_FIELDS: Set[str] = {
    "id",
    "message",
    "language",
    "lead_type",
    "high_intent",
    "needs_human",
    "intent",
    "facts_needed",
    "expected_action",
    "risk_tags",
    "source",
}
