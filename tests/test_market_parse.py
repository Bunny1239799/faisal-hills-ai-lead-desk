import pytest
from market.anonymize import Anonymizer, scrub_pii
from market.parse_chat import parse_whatsapp_chat


FABRICATED_WHATSAPP_ANDROID_CHAT = """10/04/2026, 10:15 am - Messages and calls are end-to-end encrypted. No one outside of this chat, not even WhatsApp, can read or listen to them.
10/04/2026, 10:16 am - +92 300 1234567: Salam, Faisal Hills Block A mein 5 marla ka rate kya chal raha hai?
10/04/2026, 10:17 am - Estate Agent Ali: Wa Alaikum Assalam brother. Block A 5 marla around 45 to 48 Lacs demand hai.
Contact me on 0321-9876543 or email ali.demo@example.com for site visit.
10/04/2026, 10:18 am - +92 300 1234567: Theek hai, mera budget 42 tak hai.
Kya koi corner plot available hai?
Please confirm details.
10/04/2026, 10:19 am - +92 333 5556677: Check my CNIC 37405-1234567-1 record please.
"""

FABRICATED_WHATSAPP_IOS_CHAT = """[10/04/2026, 14:30:15] Messages and calls are end-to-end encrypted.
[10/04/2026, 14:31:00] Usman FH Dealer: Faisal Hills Executive Block 10 marla direct owner available.
Price 85 Lac final.
Contact 03005551234 for token.
[10/04/2026, 14:32:45] +92 345 0001122: Plot number kya hai?
Kindly share map location.
"""


def test_scrub_pii_removes_phone_email_cnic():
    sample = "Call me at +92 300 1234567 or 0321-9876543, email test.demo@domain.pk, CNIC: 37405-1234567-1."
    clean = scrub_pii(sample)

    assert "+92 300 1234567" not in clean
    assert "0321-9876543" not in clean
    assert "test.demo@domain.pk" not in clean
    assert "37405-1234567-1" not in clean
    assert "[PHONE_REDACTED]" in clean
    assert "[EMAIL_REDACTED]" in clean
    assert "[CNIC_REDACTED]" in clean


def test_parse_whatsapp_android_format():
    messages = parse_whatsapp_chat(FABRICATED_WHATSAPP_ANDROID_CHAT, anonymize=True)

    assert len(messages) >= 4

    # System message check
    assert messages[0].is_system_message is True

    # Check sender phone number is pseudonymized
    for msg in messages:
        assert "+92 300 1234567" not in msg.sender
        assert "+92 333 5556677" not in msg.sender
        assert "+92 300 1234567" not in msg.text
        assert "0321-9876543" not in msg.text
        assert "ali.demo@example.com" not in msg.text
        assert "37405-1234567-1" not in msg.text

    # Check multiline parsing
    # The message with "Theek hai, mera budget 42 tak hai." has multiline continuation
    multiline_msgs = [m for m in messages if "Kya koi corner plot available hai?" in m.text]
    assert len(multiline_msgs) == 1
    assert "Theek hai, mera budget 42 tak hai.\nKya koi corner plot available hai?\nPlease confirm details." in multiline_msgs[0].text


def test_parse_whatsapp_ios_format():
    messages = parse_whatsapp_chat(FABRICATED_WHATSAPP_IOS_CHAT, anonymize=True)

    assert len(messages) == 3

    # Check phone number scrubbing in sender and text body
    for msg in messages:
        assert "+92 345 0001122" not in msg.sender
        assert "03005551234" not in msg.text

    dealer_msg = [m for m in messages if "Executive Block 10 marla" in m.text][0]
    assert "Agent_" in dealer_msg.sender
    assert "[PHONE_REDACTED] for token." in dealer_msg.text


def test_sender_pseudonym_consistency():
    anon = Anonymizer()
    p1 = anon.pseudonymize_sender("+923001234567")
    p2 = anon.pseudonymize_sender("+923001234567")
    p3 = anon.pseudonymize_sender("+923009999999")

    assert p1 == p2
    assert p1 != p3
