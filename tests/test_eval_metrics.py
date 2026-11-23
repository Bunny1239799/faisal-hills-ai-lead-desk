import pytest
from evaluation.run_eval import (
    compute_binary_metrics,
    compute_multiclass_metrics,
    evaluate_method,
    format_markdown_report,
)
from evaluation.baselines.rules import classify_rules


def test_compute_binary_metrics_perfect():
    actuals = [True, True, False, False]
    preds = [True, True, False, False]
    metrics = compute_binary_metrics(actuals, preds)

    assert metrics["accuracy"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["f1"] == 1.0
    assert metrics["tp"] == 2
    assert metrics["tn"] == 2
    assert metrics["fp"] == 0
    assert metrics["fn"] == 0


def test_compute_binary_metrics_edge_cases():
    actuals = [True, True, False, False]
    preds = [False, False, False, False]
    metrics = compute_binary_metrics(actuals, preds)

    assert metrics["accuracy"] == 0.5
    assert metrics["recall"] == 0.0
    assert metrics["precision"] == 0.0
    assert metrics["fn"] == 2


def test_compute_multiclass_metrics():
    classes = ["buyer", "investor", "renter", "other"]
    actuals = ["buyer", "buyer", "investor", "other"]
    preds = ["buyer", "investor", "investor", "other"]

    accuracy, matrix = compute_multiclass_metrics(actuals, preds, classes)
    assert accuracy == 0.75
    assert matrix["buyer"]["buyer"] == 1
    assert matrix["buyer"]["investor"] == 1
    assert matrix["investor"]["investor"] == 1
    assert matrix["other"]["other"] == 1


def test_rules_baseline_english():
    # Legal NOC inquiry -> needs_human: True
    res_legal = classify_rules("Is Faisal Hills approved by RDA? Please show NOC legal proof.")
    assert res_legal["needs_human"] is True
    assert res_legal["lead_type"] == "buyer"

    # Direct booking -> high_intent: True, needs_human: True
    res_booking = classify_rules("I want to book plot #45 in Block A right now, token ready.")
    assert res_booking["high_intent"] is True
    assert res_booking["needs_human"] is True

    # Discount ask -> needs_human: True
    res_discount = classify_rules("Can I get a 5 lakh discount on cash payment?")
    assert res_discount["needs_human"] is True

    # Complaint -> lead_type: existing_customer, needs_human: True
    res_complaint = classify_rules("You people are fraud, my possession is delayed!")
    assert res_complaint["lead_type"] == "existing_customer"
    assert res_complaint["needs_human"] is True

    # Broker -> lead_type: broker, needs_human: True
    res_broker = classify_rules("I am a real estate dealer, what commission split do you offer?")
    assert res_broker["lead_type"] == "broker"
    assert res_broker["needs_human"] is True

    # Smalltalk -> lead_type: other, high_intent: False, needs_human: False
    res_smalltalk = classify_rules("Hello, good morning!")
    assert res_smalltalk["lead_type"] == "other"
    assert res_smalltalk["high_intent"] is False
    assert res_smalltalk["needs_human"] is False


def test_rules_baseline_urdu_script():
    # Legal NOC
    res_legal = classify_rules("کیا سوسائٹی کے پاس قانونی آر ڈی اے منظوری اور این او سی موجود ہے؟")
    assert res_legal["needs_human"] is True

    # Booking
    res_booking = classify_rules("میں ابھی 5 مرلہ پلاٹ بک کروانا چاہتا ہوں، ٹوکن دینا ہے۔")
    assert res_booking["high_intent"] is True
    assert res_booking["needs_human"] is True

    # Smalltalk
    res_smalltalk = classify_rules("السلام علیکم، خیریت سے ہیں؟")
    assert res_smalltalk["lead_type"] == "other"
    assert res_smalltalk["high_intent"] is False
    assert res_smalltalk["needs_human"] is False


def test_rules_baseline_roman_urdu():
    # Legal NOC
    res_legal = classify_rules("Faisal Hills ki RDA NOC approved hai ya disputed legal matter hai?")
    assert res_legal["needs_human"] is True

    # Discount
    res_discount = classify_rules("5 marla Block A mein rate thora kam ho sakta hai, koi discount milega?")
    assert res_discount["needs_human"] is True

    # Returns
    res_returns = classify_rules("Faisal Hills mein invest karne pe 2 saal baad kitna guaranteed profit milega?")
    assert res_returns["lead_type"] == "investor"
    assert res_returns["needs_human"] is True

    # Site visit high intent
    res_visit = classify_rules("Kal subah site visit karni hai Executive block 10 marla dekhne k liye.")
    assert res_visit["high_intent"] is True


def test_evaluate_method_and_report_generation():
    records = [
        {
            "id": "t1",
            "message": "Faisal Hills NOC legal status?",
            "language": "en",
            "lead_type": "buyer",
            "high_intent": False,
            "needs_human": True,
        },
        {
            "id": "t2",
            "message": "Price of 5 marla?",
            "language": "en",
            "lead_type": "buyer",
            "high_intent": False,
            "needs_human": False,
        },
    ]
    predictions = [
        {
            "id": "t1",
            "lead_type": "buyer",
            "high_intent": False,
            "needs_human": True,
        },
        {
            "id": "t2",
            "lead_type": "buyer",
            "high_intent": False,
            "needs_human": False,
        },
    ]

    eval_result = evaluate_method("rules", records, predictions)
    assert eval_result["lead_type"]["accuracy"] == 1.0
    assert eval_result["needs_human"]["recall"] == 1.0

    report = format_markdown_report({"rules": eval_result}, len(records))
    assert "# Model & Baseline Evaluation Report" in report
    assert "Best `lead_type` Classifier" in report
