"""Extract structured details from email bodies for draft generation.

Uses AI to pull names, dates, questions, and other structured info
from incoming emails.  Falls back to basic regex extraction when
AI is unavailable.
"""

import json
import re
import logging
from typing import Dict, List, Optional

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)

# Expected keys with their default values
_DEFAULT_DETAILS: Dict = {
    "names": [],
    "dates": [],
    "experience_level": "",
    "questions": [],
    "goals_concerns": [],
    "party_size": "",
    "class_time_preference": "",
    "details": [],
}

_EXTRACTION_PROMPT_TEMPLATE = """You are an assistant for {business_name}. Extract structured details from the following email.

Email Subject: {subject}
Sender Name: {sender_name}
Email Body:
{body}

Extract the following information and return ONLY valid JSON (no markdown, no extra text):

{{
  "names": ["list of names mentioned — sender and any companions"],
  "dates": ["list of dates or timing mentioned (e.g. 'next Monday', 'March 15')"],
  "experience_level": "beginner/intermediate/advanced/unknown — inferred from context",
  "questions": ["list of specific questions the sender asked"],
  "goals_concerns": ["list of goals or concerns expressed"],
  "party_size": "number of people mentioned (as a string), or empty string if unknown",
  "class_time_preference": "preferred times or schedule preferences, or empty string",
  "details": ["catch-all list of any other relevant details not captured above"]
}}"""


def extract_details(
    subject: str,
    body: str,
    sender_name: str,
    config: HermesConfig,
    ai_provider: Optional[AIProvider] = None,
) -> Dict:
    """Extract structured details from an email.

    Tries AI extraction first, then falls back to basic regex.

    Args:
        subject: Email subject line.
        body: Decoded plain-text email body.
        sender_name: Sender's display name (may be empty).
        config: HermesConfig instance.
        ai_provider: Optional AI provider for extraction.

    Returns:
        Dict with keys: names, dates, experience_level, questions,
        goals_concerns, party_size, class_time_preference, details.
    """
    prompt = _EXTRACTION_PROMPT_TEMPLATE.format(
        business_name=config.business_name,
        subject=subject,
        sender_name=sender_name or "Unknown",
        body=body[:3000],
    )

    if ai_provider:
        try:
            raw = ai_provider.complete(prompt, max_tokens=500, temperature=0.1)
            result = _parse_details(raw)
            logger.debug("extract_details: used AI provider")
            return result
        except Exception as exc:
            logger.warning("AI extraction failed: %s — using basic fallback", exc)

    logger.info("extract_details: using basic regex fallback")
    return _basic_extract(subject, body, sender_name)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_details(text: str) -> Dict:
    """Parse JSON from an AI response and ensure all expected keys exist."""
    # Strip markdown code fences
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if fence_match:
        text = fence_match.group(1)

    obj_match = re.search(r"\{[\s\S]*\}", text)
    if obj_match:
        text = obj_match.group(0)

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse JSON from AI response: {exc}") from exc

    result: Dict = {}
    for key, default in _DEFAULT_DETAILS.items():
        value = parsed.get(key, default)
        if isinstance(default, list) and not isinstance(value, list):
            value = [str(value)] if value else []
        if isinstance(default, str) and not isinstance(value, str):
            value = str(value) if value else ""
        result[key] = value

    return result


# ---------------------------------------------------------------------------
# Basic regex fallback
# ---------------------------------------------------------------------------


def _basic_extract(subject: str, body: str, sender_name: str) -> Dict:
    """Fallback extraction when AI is unavailable.

    Extracts questions (lines ending with '?') and populates the sender name.
    """
    questions: List[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.endswith("?"):
            questions.append(stripped)

    names: List[str] = [sender_name] if sender_name else []

    return {
        "names": names,
        "dates": [],
        "experience_level": "",
        "questions": questions,
        "goals_concerns": [],
        "party_size": "",
        "class_time_preference": "",
        "details": [],
    }
