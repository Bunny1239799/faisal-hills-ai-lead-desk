from app.market_adapter import get_verified_market_facts


def test_market_adapter_returns_deterministic_facts():
    result = get_verified_market_facts(
        block="C",
        size_marla=7,
    )

    assert "facts" in result
    facts = result["facts"]

    assert facts["facts_source"] == "FaisalHills verified partial master"
    assert facts["facts_type"] == "dealer asking-price observations"
    assert isinstance(facts["matched_plots"], int)
    assert isinstance(facts["observation_count"], int)
    assert facts["sender_count_available"] is False


def test_market_adapter_never_claims_sender_count():
    result = get_verified_market_facts(block="C")

    assert result["facts"]["sender_count_available"] is False


def test_market_adapter_handles_no_data():
    result = get_verified_market_facts(
        block="Z",
        size_marla=999,
    )

    facts = result["facts"]

    assert facts["matched_plots"] == 0
    assert facts["trust_status"] == "insufficient_data"
    assert facts["answerable_for_demo"] is False
    assert facts["human_action"] == "confirm_with_team"
    assert facts["reply_mode"] == "insufficient_data"
