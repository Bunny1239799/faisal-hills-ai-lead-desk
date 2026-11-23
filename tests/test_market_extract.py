import pytest
from market.extract import (
    extract_market_entities,
    extract_size_marla,
    extract_block,
    extract_price_pkr,
    extract_side,
    extract_attributes_and_category,
)


def test_extract_size_marla_english_and_units():
    assert extract_size_marla("Looking for 5 marla in block a") == 5.0
    assert extract_size_marla("10 Marla plot available") == 10.0
    assert extract_size_marla("Need 1 kanal plot urgently") == 20.0
    assert extract_size_marla("Plot size 7.5 marla") == 7.5
    assert extract_size_marla("2 kanals direct deal") == 40.0


def test_extract_size_marla_roman_urdu_and_urdu():
    assert extract_size_marla("Mujhe 5 marlay chahiye") == 5.0
    assert extract_size_marla("Executive block mein das marla ka rate") == 10.0
    assert extract_size_marla("فیصل ہلز بلاک اے میں ۵ مرلہ پلاٹ چاہیے") == 5.0
    assert extract_size_marla("ایک کنال برائے فروخت") == 20.0
    assert extract_size_marla("۱۰ مرلہ کی قیمت بتائیں") == 10.0


def test_extract_block_mapping():
    code, name = extract_block("Looking for Block A 5 marla")
    assert code == "A"
    assert name == "Block A"

    code, name = extract_block("Plot in executive block")
    assert code == "EXEC"
    assert name == "Executive Block"

    code, name = extract_block("فیصل ہلز بلاک بی میں ریٹ کیا ہے؟")
    assert code == "B"
    assert name == "Block B"

    code, name = extract_block("C block commercial rates?")
    assert code == "C"
    assert name == "Block C"

    code, name = extract_block("ایگزیکٹو بلاک 10 مرلہ")
    assert code == "EXEC"
    assert name == "Executive Block"

    # Non-existent or unsupported block
    code, name = extract_block("D block plot rates")
    assert code is None
    assert name is None


def test_extract_price_pkr_normalization():
    # Lac / Lakh
    pkr, raw = extract_price_pkr("Demand is 45 lacs final")
    assert pkr == 4_500_000
    assert "45 lacs" in raw

    pkr, raw = extract_price_pkr("Budget 62.5 lakh tak hai")
    assert pkr == 6_250_000

    # Crore
    pkr, raw = extract_price_pkr("Demand 1.5 crore")
    assert pkr == 15_000_000

    pkr, raw = extract_price_pkr("قیمت 1 کروڑ 20 لاکھ")
    # First captured major unit
    assert pkr == 10_000_000

    # Urdu digits
    pkr, raw = extract_price_pkr("ڈیمانڈ ۵۰ لاکھ")
    assert pkr == 5_000_000

    # Raw digits
    pkr, raw = extract_price_pkr("transfer fee 5500000 pkr")
    assert pkr == 5_500_000


def test_extract_side_buy_vs_sell():
    # Sell side
    assert extract_side("5 marla block A available for sale, demand 48 lac") == "SELL"
    assert extract_side("Direct owner hot deal in executive block") == "SELL"
    assert extract_side("بلاک اے میں ۵ مرلہ برائے فروخت") == "SELL"

    # Buy side
    assert extract_side("Need 10 marla plot in block c under 70 lac") == "BUY"
    assert extract_side("Mujhe block B mein 5 marla lena hai, budget 42 lac") == "BUY"
    assert extract_side("مجھے ایگزیکٹو بلاک میں پلاٹ چاہیے") == "BUY"

    # Neutral inquiry
    assert extract_side("Faisal Hills mein market situation kya hai?") == "INQUIRY"


def test_extract_attributes_and_category():
    cat, corner, blvd, park, attrs = extract_attributes_and_category(
        "Commercial 5 marla main boulevard corner plot"
    )
    assert cat == "commercial"
    assert corner is True
    assert blvd is True
    assert park is False
    assert "corner" in attrs
    assert "boulevard" in attrs
    assert "commercial" in attrs

    cat, corner, blvd, park, attrs = extract_attributes_and_category(
        "رہائشی پلاٹ پارک فیسنگ اور کارنر"
    )
    assert cat == "residential"
    assert corner is True
    assert park is True
    assert blvd is False


def test_end_to_end_market_entity_extraction():
    # Fabricated English line
    line_en = "Selling Block A 5 marla corner residential plot, demand 46 lacs"
    ent_en = extract_market_entities(line_en)
    assert ent_en.size_marla == 5.0
    assert ent_en.block_code == "A"
    assert ent_en.side == "SELL"
    assert ent_en.price_pkr == 4_600_000
    assert ent_en.is_corner is True
    assert ent_en.category == "residential"

    # Fabricated Roman Urdu line
    line_ru = "Mujhe Executive block mein 10 marla plot chahiye, budget 85 lac tak hai"
    ent_ru = extract_market_entities(line_ru)
    assert ent_ru.size_marla == 10.0
    assert ent_ru.block_code == "EXEC"
    assert ent_ru.side == "BUY"
    assert ent_ru.price_pkr == 8_500_000

    # Fabricated Urdu script line
    line_ur = "فیصل ہلز بلاک بی ۱۰ مرلہ کمرشل مین بلیوارڈ برائے فروخت ڈیمانڈ ۱.۲ کروڑ"
    ent_ur = extract_market_entities(line_ur)
    assert ent_ur.size_marla == 10.0
    assert ent_ur.block_code == "B"
    assert ent_ur.side == "SELL"
    assert ent_ur.category == "commercial"
    assert ent_ur.is_boulevard is True
    assert ent_ur.price_pkr == 12_000_000
