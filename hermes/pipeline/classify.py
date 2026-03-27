"""Email classifier for Hermes.

Classifies emails into user-defined categories using regex rules first,
then falls back to AI classification via the configured provider.
Categories and patterns are loaded from hermes.yaml.
"""

import json
import re
import logging
from typing import Dict, Optional, Set

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)


def classify_email(
    subject: str,
    body: str,
    config: HermesConfig,
    ai_provider: Optional[AIProvider] = None,
) -> Dict:
    """Classify an email into a category.

    Tries rule-based matching first, then AI fallback.

    Args:
        subject: Email subject line.
        body: Plain-text email body.
        config: HermesConfig with category definitions.
        ai_provider: Optional AI provider for fallback classification.

    Returns:
        Dict with keys:
            category (str): Category name or "uncategorized".
            confidence (float): 0.0-1.0.
            method (str): "rules" or "ai".
    """
    result = _classify_rules(subject, body, config)
    if result is not None:
        return result

    if ai_provider:
        return _classify_ai(subject, body, config, ai_provider)

    return {"category": "uncategorized", "confidence": 0.0, "method": "rules"}


# ---------------------------------------------------------------------------
# Rule-based classification
# ---------------------------------------------------------------------------


def _classify_rules(subject: str, body: str, config: HermesConfig) -> Optional[Dict]:
    """Regex pattern matching against subject + first 200 chars of body.

    Scores by pattern match count; boosts confidence for subject-line matches.
    Returns None if best score is below the confidence threshold.
    """
    patterns = config.category_patterns
    threshold = config.classification_confidence_threshold
    body_snippet = body[:200]
    scores: Dict[str, float] = {}

    for category, cat_patterns in patterns.items():
        if not cat_patterns:
            continue
        score = 0.0
        for pattern in cat_patterns:
            if re.search(pattern, subject, re.IGNORECASE):
                score += 2.0
            elif re.search(pattern, body_snippet, re.IGNORECASE):
                score += 1.0
        scores[category] = score

    if not scores:
        return None

    best_category = max(scores, key=lambda c: scores[c])
    best_score = scores[best_category]

    if best_score == 0:
        return None

    cat_patterns = patterns.get(best_category, [])
    max_possible = len(cat_patterns) * 2.0 if cat_patterns else 1.0
    confidence = min(best_score / max_possible, 1.0)

    # Boost: a single subject-line match (score >= 2.0) gets at least 0.85
    if best_score >= 2.0:
        confidence = max(confidence, 0.85)

    if confidence < threshold:
        return None

    return {
        "category": best_category,
        "confidence": round(confidence, 4),
        "method": "rules",
    }


# ---------------------------------------------------------------------------
# AI classification
# ---------------------------------------------------------------------------


def _classify_ai(
    subject: str,
    body: str,
    config: HermesConfig,
    ai_provider: AIProvider,
) -> Dict:
    """AI fallback classification using the configured provider."""
    category_names = config.category_names - {"uncategorized"}
    categories_list = ", ".join(sorted(category_names))
    body_snippet = body[:500]

    prompt = (
        f"Classify the following email into exactly one category.\n"
        f"Categories: {categories_list}, uncategorized\n\n"
        f"Subject: {subject}\n"
        f"Body (first 500 chars): {body_snippet}\n\n"
        f"Respond with valid JSON only, no extra text. Format:\n"
        f'{{"category": "<category>", "confidence": <0.0-1.0>}}'
    )

    try:
        response_text = ai_provider.complete(prompt, max_tokens=256, temperature=0.1)
        result = _parse_classification_response(response_text, config.category_names)
        if result:
            result["method"] = "ai"
            return result
    except Exception as exc:
        logger.warning("AI classification failed: %s", exc)

    return {"category": "uncategorized", "confidence": 0.0, "method": "ai"}


def _parse_classification_response(
    text: str,
    valid_categories: Set[str],
) -> Optional[Dict]:
    """Parse JSON from AI response and validate the category."""
    match = re.search(r"\{[^{}]+\}", text, re.DOTALL)
    if not match:
        logger.warning("No JSON object found in AI response: %r", text[:200])
        return None

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse AI JSON response: %s", exc)
        return None

    category = data.get("category", "").strip().lower()
    if category not in valid_categories:
        logger.warning(
            "AI returned unknown category %r, defaulting to uncategorized", category
        )
        category = "uncategorized"

    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))
    return {"category": category, "confidence": round(confidence, 4)}
