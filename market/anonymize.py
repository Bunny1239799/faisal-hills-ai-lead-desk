import re
from typing import Dict, Optional


PHONE_REGEX = re.compile(
    r"(?:\+?92[-\s]?)?(?:0?3\d{2}[-\s]?\d{7}|\b0?3\d{2}[-\s]?\d{3}[-\s]?\d{4}\b|\b\d{10,13}\b)"
)
CNIC_REGEX = re.compile(r"\b\d{5}[-\s]?\d{7}[-\s]?\d\b")
EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class Anonymizer:
    """
    Anonymizes sensitive customer PII including phone numbers, emails,
    CNIC numbers, and consistent pseudonyms for senders.
    """

    def __init__(self, salt: str = "faisal-hills-desk"):
        self.salt = salt
        self._sender_map: Dict[str, str] = {}
        self._sender_counter: int = 1

    def pseudonymize_sender(self, sender_raw: str) -> str:
        """
        Maps a sender name or raw phone number to a consistent pseudonym like 'Agent_1' or 'Customer_2'.
        """
        sender_clean = sender_raw.strip()
        if not sender_clean:
            return "Participant_Unknown"

        if sender_clean in self._sender_map:
            return self._sender_map[sender_clean]

        lower_s = sender_clean.lower()
        if "agent" in lower_s or "dealer" in lower_s or "admin" in lower_s or "office" in lower_s:
            prefix = "Agent"
        else:
            prefix = "Customer"

        anon_name = f"{prefix}_{self._sender_counter}"
        self._sender_counter += 1
        self._sender_map[sender_clean] = anon_name
        return anon_name

    def scrub_text(self, text: str) -> str:
        """
        Scrubs phone numbers, CNIC, and emails from text.
        """
        if not text:
            return ""

        scrubbed = CNIC_REGEX.sub("[CNIC_REDACTED]", text)
        scrubbed = EMAIL_REGEX.sub("[EMAIL_REDACTED]", scrubbed)
        scrubbed = PHONE_REGEX.sub("[PHONE_REDACTED]", scrubbed)
        return scrubbed


def scrub_pii(text: str) -> str:
    """
    Standalone helper to redact phone numbers, CNIC, and emails from text.
    """
    anon = Anonymizer()
    return anon.scrub_text(text)
