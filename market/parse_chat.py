import re
from dataclasses import dataclass
from typing import List, Optional
from market.anonymize import Anonymizer


@dataclass
class ChatMessage:
    raw_timestamp: str
    sender: str
    text: str
    is_system_message: bool = False


# Format A: Android/Standard messages with sender: "12/04/2026, 14:23 - Sender: message"
PATTERN_FORMAT_A = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|AM|PM))?)\s*-\s*([^:]+):\s*(.*)$"
)

# Format A System: Android system notifications without sender/colon: "12/04/2026, 14:23 - Notice text"
PATTERN_FORMAT_A_SYSTEM = re.compile(
    r"^(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|AM|PM))?)\s*-\s*(.*)$"
)

# Format B: iOS Bracketed messages with sender: "[12/04/2026, 14:23:45] Sender: message"
PATTERN_FORMAT_B = re.compile(
    r"^\[(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|AM|PM))?)\]\s*([^:]+):\s*(.*)$"
)

# Format B System: iOS Bracketed system notices without sender/colon: "[12/04/2026, 14:23:45] Notice text"
PATTERN_FORMAT_B_SYSTEM = re.compile(
    r"^\[(\d{1,2}/\d{1,2}/\d{2,4},\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*(?:am|pm|AM|PM))?)\]\s*(.*)$"
)

# System notification patterns
SYSTEM_NOTICES = [
    "messages and calls are end-to-end encrypted",
    "peghaam aur calls end-to-end encrypted",
    "added",
    "left",
    "changed the group description",
    "created group",
    "security code changed",
]


def _is_system_notice(sender: str, text: str) -> bool:
    content = f"{sender} {text}".lower()
    return any(notice in content for notice in SYSTEM_NOTICES)


def parse_whatsapp_chat(
    chat_text: str,
    anonymize: bool = True,
    anonymizer: Optional[Anonymizer] = None,
) -> List[ChatMessage]:
    """
    Parses WhatsApp exported chat text in both standard Android and iOS export formats.
    Supports multiline text messages and redacts PII/phone numbers.
    """
    if anonymizer is None and anonymize:
        anonymizer = Anonymizer()

    messages: List[ChatMessage] = []
    lines = chat_text.splitlines()

    current_msg: Optional[ChatMessage] = None

    for raw_line in lines:
        line = raw_line.strip("\u200e\u202a\u202c\ufeff")  # Strip WhatsApp bidirectional Unicode marks
        if not line.strip():
            continue

        match_a = PATTERN_FORMAT_A.match(line)
        match_b = PATTERN_FORMAT_B.match(line)

        if match_a or match_b:
            match = match_a or match_b
            if current_msg is not None:
                messages.append(current_msg)

            timestamp_str = match.group(1).strip()
            sender_str = match.group(2).strip()
            body_str = match.group(3).strip()

            is_sys = _is_system_notice(sender_str, body_str)

            if anonymize and anonymizer is not None:
                if not is_sys:
                    final_sender = anonymizer.pseudonymize_sender(sender_str)
                else:
                    final_sender = "System"
                final_text = anonymizer.scrub_text(body_str)
            else:
                final_sender = sender_str
                final_text = body_str

            current_msg = ChatMessage(
                raw_timestamp=timestamp_str,
                sender=final_sender,
                text=final_text,
                is_system_message=is_sys,
            )
        else:
            # Check if this line is a system notice without sender
            match_sys_a = PATTERN_FORMAT_A_SYSTEM.match(line)
            match_sys_b = PATTERN_FORMAT_B_SYSTEM.match(line)
            match_sys = match_sys_a or match_sys_b

            if match_sys and _is_system_notice("", match_sys.group(2)):
                if current_msg is not None:
                    messages.append(current_msg)

                timestamp_str = match_sys.group(1).strip()
                body_str = match_sys.group(2).strip()
                final_text = anonymizer.scrub_text(body_str) if (anonymize and anonymizer) else body_str

                current_msg = ChatMessage(
                    raw_timestamp=timestamp_str,
                    sender="System",
                    text=final_text,
                    is_system_message=True,
                )
            elif current_msg is not None:
                # Continuation of multiline message
                continuation_text = anonymizer.scrub_text(line) if (anonymize and anonymizer) else line
                current_msg.text += "\n" + continuation_text

    if current_msg is not None:
        messages.append(current_msg)

    return messages
