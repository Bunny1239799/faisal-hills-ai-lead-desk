"""EB-01 — build the genuine dealer-question replay dataset (v1).

EB-01 (the M12.4 blocker) asked for a curated file of REAL dealer
questions. The founder's task directive ("complete the EB-01
replay-data gate") is the authorized controlled derivation from the
extracted WhatsApp messages, taken from the REGISTERED source: the 14
organized group exports whose `GROUP_SOURCE_INDEX.csv` rows all carry
`authorized_for_extraction=YES`.

Selection — a message is a genuine dealer QUESTION when:
  * it carries a property or price signal, AND
  * it carries inquiry intent (a question mark, or buyer-intent words
    need/want/required/chahiye/looking..., or price-inquiry words
    kitna/kitne/how much/price/rate/qeemat), AND
  * it is NOT an inventory listing (the same extraction the candidate
    builder uses must produce no observation for it), AND
  * it survives contact redaction with text left.

Privacy — the MINIMUM necessary information for replay (exactly what
the master file's preferred solution asks for):
  * id, question text (contact-redacted), source group id, source
    message id, source message date
  * NO sender name, NO sender hash, NO phone, NO email, NO link, NO
    @mention, NO raw chat beyond the question itself
  * near-identical messages are deduplicated; the set is capped

Outputs:
  * evaluation/datasets/production/real_dealer_questions_v1.jsonl
  * evaluation/datasets/production/real_dealer_questions_v1.manifest.json
    (version, provenance, rules, counts, sha256 of the dataset)
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(r"D:\AI-Projects\laya-gateway")
CAND = Path(r"D:\FaisalHills_Master_Data\10_INVENTORY_CANDIDATE_2026_10_24")
sys.path.insert(0, str(CAND))
sys.path.insert(0, str(ROOT))

import extract_inventory as ex  # noqa: E402  (the candidate's own parser)

OUT_JSONL = ROOT / "evaluation" / "datasets" / "production" / \
    "real_dealer_questions_v1.jsonl"
OUT_MANIFEST = ROOT / "evaluation" / "datasets" / "production" / \
    "real_dealer_questions_v1.manifest.json"
INDEX_CSV = Path(r"D:\FaisalHills_Master_Data\WHATSAPP EXPORTS INVENTORY"
                 r"\GROUP_SOURCE_INDEX.csv")
SCRATCH = Path(r"D:\FaisalHillsAILeadDesk\test-artifacts\whatsapp_inv_20261024"
               r"\extracted")

CAP = 150

QUESTION_INTENT_RE = re.compile(
    r"\?|\b(?:need|needs|want|wanted|looking|required|require|searching|"
    r"seeking|interested|chahiye|chahye|chah raha|kitna|kitne|kitni|"
    r"how much|kya rate|kya price|price\??|rate\??|availab)\b",
    re.IGNORECASE)

# societies other than Faisal Hills: a Faisal Hills Lead Desk replays
# Faisal Hills questions (out-of-scope escalation is validated by the
# golden set, not by this dataset)
OTHER_SOCIETY_RE = re.compile(
    r"\bb[\s-]?17\b|\bmpchs\b|\bbahria\b|\bdha\b|\bfaisal\s*town\b|"
    r"\bft\s*[0-9a-z]\b|\bft[a-z0-9]\b|\bfmc\b|\bmargalla\b|"
    r"\bmulti\s*garden|\bgulberg\b|\bawt\b|\bg-?1[0-4]\b|\bpwd\b|"
    r"\bsoan\b|\bqurtaba\b|\bbani\s*gala|\bemporium\b|\bskyarc\b|"
    r"\bchanar\b|\bdeal\s*with\s*atif\b",
    re.IGNORECASE)

# phone shapes the shared redactor's fixed-width tails can miss
_PHONE_EXTRA_RE = re.compile(r"\b(?:\+92|0)?\s?3\d{2}[-\s]?\d{7,9}\b")

# dotted FH spellings ("F.H.B 35x70") that are listings in disguise
_DOTTED_FH_RE = re.compile(r"\bF\s*\.\s*H\s*\.?\s*[-–]?\s*([A-E])\b",
                           re.IGNORECASE)


def clean_question(body: str) -> str:
    """Redact contact patterns and trim the question to its core."""
    text = ex.redact(body)
    text = _PHONE_EXTRA_RE.sub("[CONTACT-REDACTED]", text)
    text = re.sub(r"\s*[\U0001F000-\U0001FAFF\u2600-\u27BF]+\s*", " ", text)
    text = ex.normalize_ws(text)
    return text[:300].rstrip()


def is_listing(body: str) -> bool:
    """The same acceptance the candidate builder uses: any segment that
    parses into a real inventory observation makes this a LISTING."""
    listings = ex.split_listings(body)
    for seg, frag in listings:
        seg_other = bool(ex.OTHER_SOCIETY_RE.search(seg))
        seg_fh = bool(ex.FH_TOKEN_RE.search(seg)) or bool(
            ex.FH_PLOT_RE.search(seg)) or bool(_DOTTED_FH_RE.search(seg))
        if seg_other and not seg_fh:
            continue
        if not seg_fh and not (ex.LISTING_SIGNAL_RE.search(seg)):
            continue
        flags = []
        obs = ex.extract_from_segment(seg, flags)
        if obs is None:
            continue
        anchors = ((1 if obs["block"] else 0)
                   + (1 if obs["size_marla"] != "" else 0)
                   + (1 if obs["price_median_pkr"] != "" else 0)
                   + (1 if obs["plot_number"] else 0))
        if anchors >= 2:
            return True
    return False


def main():
    registry = []
    with open(INDEX_CSV, "r", encoding="utf-8-sig", newline="") as fh:
        registry = [r for r in csv.DictReader(fh)
                    if r.get("authorized_for_extraction", "").strip().upper()
                    == "YES"]

    questions = []
    stats = {
        "groups": 0,
        "messages_read": 0,
        "noise_skipped": 0,
        "other_society_skipped": 0,
        "listings_skipped": 0,
        "no_question_intent": 0,
        "empty_after_redaction": 0,
        "duplicates_dropped": 0,
        "selected": 0,
        "capped": 0,
    }
    seen_norms = set()

    for reg in registry:
        group_id = reg["group_id"].strip()
        folder = SCRATCH / group_id
        txts = list(folder.glob("*.txt"))
        if not txts:
            continue
        stats["groups"] += 1
        messages = ex.parse_export(txts[0])
        seq = 0
        for msg in messages:
            low = msg["body"].strip().lower()
            if (low == "" or low in ex.SKIP_BODY_EXACT
                    or any(low.startswith(p) and len(low) < 160
                           for p in ex.SYSTEM_PATTERNS)):
                stats["noise_skipped"] += 1
                continue
            stats["messages_read"] += 1
            seq += 1
            message_id = "%s-%05d" % (group_id, seq)
            body = ex.clean_body(msg["body"])
            if not ex.PROPERTY_SIGNAL_RE.search(body):
                continue
            if is_listing(body):
                stats["listings_skipped"] += 1
                continue
            if OTHER_SOCIETY_RE.search(body):
                stats["other_society_skipped"] += 1
                continue
            if not QUESTION_INTENT_RE.search(body):
                stats["no_question_intent"] += 1
                continue
            text = clean_question(body)
            if len(text) < 8 or "[CONTACT-REDACTED]" == text:
                stats["empty_after_redaction"] += 1
                continue
            norm = re.sub(r"[^a-z0-9]+", " ", text.lower())[:80].strip()
            if norm in seen_norms:
                stats["duplicates_dropped"] += 1
                continue
            seen_norms.add(norm)
            questions.append({
                "id": "EB01-%s-%05d" % (group_id, seq),
                "question": text,
                "source_group_id": group_id,
                "source_message_id": message_id,
                "source_message_date": msg["date"],
            })

    # deterministic order, then the minimum-necessary cap
    questions.sort(key=lambda q: (q["source_message_date"], q["id"]))
    if len(questions) > CAP:
        stats["capped"] = len(questions) - CAP
        questions = questions[:CAP]
    for i, q in enumerate(questions, start=1):
        q["id"] = "EB01-Q%04d" % i
    stats["selected"] = len(questions)

    OUT_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_JSONL, "w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q, ensure_ascii=False) + "\n")

    digest = hashlib.sha256(OUT_JSONL.read_bytes()).hexdigest()
    registry_sha = hashlib.sha256(INDEX_CSV.read_bytes()).hexdigest()
    manifest = {
        "dataset": "real_dealer_questions_v1",
        "version": "v1",
        "created": "2026-10-25",
        "purpose": (
            "EB-01 genuine dealer-question replay data - the minimum "
            "necessary information to replay real dealer questions "
            "through the real validation flow"),
        "authorized_source": (
            "14 organized WhatsApp group exports, all "
            "authorized_for_extraction=YES in GROUP_SOURCE_INDEX.csv "
            "(sha256 %s)" % registry_sha[:16]),
        "derivation_authorization": (
            "founder task directive 2026-10-25: complete the EB-01 "
            "replay-data gate (controlled derivation from the extracted "
            "WhatsApp messages - the master file's authorized "
            "alternative)"),
        "selection_rules": [
            "property or price signal present",
            "inquiry intent present (question mark, buyer-intent or "
            "price-inquiry words, Roman Urdu included)",
            "NOT an inventory listing (the candidate extraction must "
            "produce no observation)",
            "contact-redacted (phone/email/link/@mention patterns)",
            "near-identical texts deduplicated",
            "capped at %d questions, oldest first" % CAP,
        ],
        "privacy": [
            "no sender names, no sender hashes, no phone numbers, no "
            "emails, no links, no @mentions",
            "no raw chat beyond the question text itself",
            "contact_index_private.csv never opened",
        ],
        "counts": stats,
        "dataset_sha256": digest,
        "never_served_by_operator_desk": True,
        "read_only": True,
    }
    with open(OUT_MANIFEST, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, ensure_ascii=False)

    print(json.dumps(stats, indent=1))
    print("dataset:", OUT_JSONL)
    print("sha256:", digest[:16])


if __name__ == "__main__":
    main()
