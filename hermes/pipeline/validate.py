"""Draft validator for Hermes.

Post-generation quality checks on email drafts.  All verified facts,
banned words, and phone patterns come from hermes.yaml — nothing is
hardcoded to a specific business.
"""

import re
import logging
from typing import Dict, List

from hermes.config import HermesConfig

logger = logging.getLogger(__name__)


def validate_draft(
    draft_text: str,
    category: str,
    extracted_details: Dict,
    config: HermesConfig,
) -> Dict:
    """Run all quality checks on a draft email.

    Args:
        draft_text: The full text of the generated draft.
        category: Classified email category.
        extracted_details: Dict from extract_details().
        config: HermesConfig with validation rules.

    Returns:
        Dict with keys:
            passed (bool): False if any flag has severity "block".
            flags (list[dict]): Each flag has type, message, severity.
    """
    flags: List[Dict[str, str]] = []

    flags.extend(_check_detail_coverage(draft_text, extracted_details))
    flags.extend(_check_hallucinations(draft_text, category, config))
    flags.extend(_check_tone(draft_text, config))
    flags.extend(_check_length(draft_text))
    flags.extend(_check_contact_info(draft_text, config))

    # Category-specific guardrails
    cat_cfg = config.category_config(category)
    if cat_cfg.get("auto_send_locked", False):
        flags.extend(_check_locked_category_guardrails(draft_text, category, config))

    passed = not any(f["severity"] == "block" for f in flags)
    return {"passed": passed, "flags": flags}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------


def _check_detail_coverage(draft: str, details: Dict) -> List[Dict[str, str]]:
    """Warn if names, dates, or questions from extracted_details are missing."""
    flags: List[Dict[str, str]] = []
    draft_lower = draft.lower()

    for name in details.get("names", []):
        if name and name.lower() not in draft_lower:
            flags.append({
                "type": "missing_name",
                "message": f"Extracted name not found in draft: {name!r}",
                "severity": "warning",
            })

    for date in details.get("dates", []):
        if date and date.lower() not in draft_lower:
            flags.append({
                "type": "missing_date",
                "message": f"Extracted date not found in draft: {date!r}",
                "severity": "warning",
            })

    for question in details.get("questions", []):
        if question:
            snippet = question.lower()[:20].strip()
            if snippet and snippet not in draft_lower:
                flags.append({
                    "type": "missing_question",
                    "message": f"Question may not be addressed: {question!r}",
                    "severity": "warning",
                })

    return flags


def _check_hallucinations(
    draft: str, category: str, config: HermesConfig
) -> List[Dict[str, str]]:
    """Flag financial patterns; block if found outside locked categories."""
    flags: List[Dict[str, str]] = []
    cat_cfg = config.category_config(category)
    is_locked = cat_cfg.get("auto_send_locked", False)

    for pattern in config.financial_patterns:
        match = re.search(pattern, draft, re.IGNORECASE)
        if match:
            severity = "warning" if is_locked else "block"
            flags.append({
                "type": "financial_pattern",
                "message": (
                    f"Financial language detected ({match.group()!r}). "
                    + (
                        "Requires review."
                        if is_locked
                        else "Financial commitments not allowed outside locked categories."
                    )
                ),
                "severity": severity,
            })

    return flags


def _check_tone(draft: str, config: HermesConfig) -> List[Dict[str, str]]:
    """Block any draft containing banned brand-voice words."""
    flags: List[Dict[str, str]] = []
    draft_lower = draft.lower()

    for word in config.banned_words:
        if word.lower() in draft_lower:
            flags.append({
                "type": "banned_word",
                "message": f"Banned word/phrase detected: {word!r}",
                "severity": "block",
            })

    return flags


def _check_length(draft: str) -> List[Dict[str, str]]:
    """Warn if sentence count is unusually low or high."""
    flags: List[Dict[str, str]] = []

    sentences = [
        s.strip()
        for s in re.split(r"(?<=[.!?])\s+", draft.strip())
        if s.strip()
    ]
    count = len(sentences)

    if count < 3:
        flags.append({
            "type": "too_short",
            "message": f"Draft is very short ({count} sentence(s)); may lack substance.",
            "severity": "warning",
        })
    elif count > 15:
        flags.append({
            "type": "too_long",
            "message": f"Draft is very long ({count} sentences); consider trimming.",
            "severity": "warning",
        })

    return flags


def _check_contact_info(draft: str, config: HermesConfig) -> List[Dict[str, str]]:
    """Block drafts with unrecognised phone numbers."""
    flags: List[Dict[str, str]] = []
    valid_patterns = config.valid_phone_patterns

    if not valid_patterns:
        return flags

    phone_candidates = re.findall(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}", draft)

    for candidate in phone_candidates:
        is_valid = any(
            re.search(p, candidate, re.IGNORECASE) for p in valid_patterns
        )
        if not is_valid:
            flags.append({
                "type": "wrong_phone",
                "message": f"Unrecognised phone number {candidate!r} in draft.",
                "severity": "block",
            })

    return flags


def _check_locked_category_guardrails(
    draft: str, category: str, config: HermesConfig
) -> List[Dict[str, str]]:
    """Guardrails for auto_send_locked categories (e.g. billing).

    Always blocks auto-send and checks for unauthorized commitments.
    """
    flags: List[Dict[str, str]] = [
        {
            "type": "locked_review_required",
            "message": (
                f"All {category!r} emails require human review before sending."
            ),
            "severity": "block",
        }
    ]

    for pattern in config.unauthorized_commitments:
        match = re.search(pattern, draft, re.IGNORECASE)
        if match:
            flags.append({
                "type": "unauthorized_commitment",
                "message": (
                    f"Unauthorized commitment detected: {match.group()!r}. "
                    "Do not promise refunds, credits, waivers, or adjustments."
                ),
                "severity": "block",
            })

    return flags
