"""Draft generator for Hermes.

Assembles full context (brand voice, template anchor, voice samples,
sender history, thread history) and generates a reply draft via AI.
All business-specific content comes from hermes.yaml and local files.
"""

import json
import logging
import os
from typing import Dict, List, Optional

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)


def generate_draft(
    original_email: Dict,
    category: str,
    extracted_details: Dict,
    config: HermesConfig,
    ai_provider: AIProvider,
    thread_history: Optional[List[Dict]] = None,
) -> Dict:
    """Generate a reply draft for an email.

    Args:
        original_email: Dict with keys: subject, body, sender_email, sender_name.
        category: Classified email category.
        extracted_details: Structured details from extract_details().
        config: HermesConfig instance.
        ai_provider: AI provider for generation.
        thread_history: Optional list of prior messages in the thread.

    Returns:
        Dict with keys:
            draft_text (Optional[str]): Generated reply or None on failure.
            model_used (Optional[str]): Model identifier.
            generation_context (Dict): Context metadata.
    """
    brand_voice = _load_brand_voice(config)
    template_anchor = _load_template(config, category)
    voice_samples = _load_voice_samples(config, category)
    sender_history = _get_sender_history(
        config, original_email.get("sender_email", "")
    )

    generation_context: Dict = {
        "category": category,
        "brand_voice_loaded": bool(brand_voice),
        "template_anchor_loaded": bool(template_anchor),
        "voice_samples_count": len(voice_samples),
        "sender_history_found": sender_history is not None,
        "thread_messages": len(thread_history) if thread_history else 0,
    }

    system_prompt = _build_system_prompt(config, brand_voice, template_anchor, voice_samples)
    user_prompt = _build_user_prompt(
        original_email, extracted_details, sender_history, thread_history, config
    )

    draft_text: Optional[str] = None
    model_used: Optional[str] = None

    try:
        draft_text = ai_provider.complete(
            user_prompt, system=system_prompt, temperature=0.7
        )
        model_used = getattr(ai_provider, "_model", "unknown")
    except Exception as exc:
        logger.error("Draft generation failed: %s", exc)

    generation_context["model_used"] = model_used

    return {
        "draft_text": draft_text,
        "model_used": model_used,
        "generation_context": generation_context,
    }


# ---------------------------------------------------------------------------
# Context loaders
# ---------------------------------------------------------------------------


def _load_brand_voice(config: HermesConfig) -> str:
    """Read the brand voice file."""
    path = config.brand_voice_file
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        logger.warning("Brand voice file not found: %s", path)
        return ""
    except OSError as exc:
        logger.warning("Failed to read brand voice: %s", exc)
        return ""


def _load_template(config: HermesConfig, category: str) -> str:
    """Load template anchor text for a category.

    Tries Supabase first, falls back to file in templates_dir.
    """
    try:
        sb = config.get_supabase()
        result = (
            sb.table("hermes_templates")
            .select("anchor_text")
            .eq("category", category)
            .maybe_single()
            .execute()
        )
        if result.data and result.data.get("anchor_text"):
            return result.data["anchor_text"]
    except Exception as exc:
        logger.warning("Supabase template fetch failed for %s: %s", category, exc)

    template_path = config.templates_dir / f"{category}.md"
    try:
        with open(template_path, "r", encoding="utf-8") as fh:
            return fh.read()
    except FileNotFoundError:
        logger.warning("Template file not found: %s", template_path)
        return ""
    except OSError as exc:
        logger.warning("Failed to read template %s: %s", template_path, exc)
        return ""


def _load_voice_samples(config: HermesConfig, category: str, limit: int = 5) -> List[str]:
    """Load voice samples from Supabase hermes_templates table."""
    try:
        sb = config.get_supabase()
        result = (
            sb.table("hermes_templates")
            .select("voice_samples")
            .eq("category", category)
            .maybe_single()
            .execute()
        )
        if result.data and result.data.get("voice_samples"):
            raw = result.data["voice_samples"]
            if isinstance(raw, list):
                samples = raw
            elif isinstance(raw, str):
                try:
                    samples = json.loads(raw)
                except json.JSONDecodeError:
                    samples = [raw]
            else:
                samples = []
            return [str(s) for s in samples[:limit]]
    except Exception as exc:
        logger.warning("Failed to load voice samples for %s: %s", category, exc)
    return []


def _get_sender_history(config: HermesConfig, email: str) -> Optional[Dict]:
    """Look up a sender in hermes_sender_history."""
    if not email:
        return None
    try:
        sb = config.get_supabase()
        result = (
            sb.table("hermes_sender_history")
            .select("*")
            .eq("email", email.lower().strip())
            .maybe_single()
            .execute()
        )
        return result.data if result.data else None
    except Exception as exc:
        logger.warning("Failed to fetch sender history for %s: %s", email, exc)
        return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_system_prompt(
    config: HermesConfig,
    brand_voice: str,
    template_anchor: str,
    voice_samples: List[str],
) -> str:
    """Build the system prompt from config identity and loaded context."""
    parts = [
        f"You are {config.owner_name}, owner of {config.business_name}.",
        "You write warm, direct, conversational email replies.",
        "",
    ]

    if config.tagline:
        parts.insert(1, config.tagline)
        parts.insert(2, "")

    if brand_voice:
        parts += ["## Brand Voice", brand_voice.strip(), ""]

    if template_anchor:
        parts += ["## Reply Template & Guidelines", template_anchor.strip(), ""]

    if voice_samples:
        parts += ["## Example Replies (Your Voice)"]
        for i, sample in enumerate(voice_samples, start=1):
            parts += [f"### Example {i}", sample.strip(), ""]

    return "\n".join(parts)


def _build_user_prompt(
    email: Dict,
    details: Dict,
    sender_history: Optional[Dict],
    thread_history: Optional[List[Dict]],
    config: HermesConfig,
) -> str:
    """Build the user prompt with email context and instructions."""
    sender_name = email.get("sender_name", "").strip()
    sender_email = email.get("sender_email", "").strip()
    subject = email.get("subject", "").strip()
    body = email.get("body", "").strip()

    first_name = sender_name.split()[0] if sender_name else ""

    parts = [
        "Write a reply to the email below. Follow these instructions exactly:",
        "",
        "INSTRUCTIONS:",
        "- Address every specific question or detail the sender raised",
        "- Write conversationally — warm and human, not formal or corporate",
        "- Keep replies concise and direct — aim for 4-6 sentences by default",
        "- Never pad replies with filler. Say what needs to be said and stop.",
        f"- Use their first name ({first_name!r}) naturally if available",
        f"- Sign the reply as {config.owner_name.split()[0]} (first name only)",
        "- Never fabricate information (rates, dates, policies) you are not certain of",
        "- Do not include a subject line — reply body only",
        "",
    ]

    if thread_history:
        parts += ["## Thread History (most recent last)"]
        for msg in thread_history:
            role = msg.get("role", "unknown").upper()
            msg_body = msg.get("body", "").strip()
            parts += [f"[{role}]", msg_body, ""]

    if sender_history:
        parts += ["## Sender Context"]
        if sender_history.get("is_member"):
            parts.append(f"- This person is a current {config.business_name} member.")
        interactions = sender_history.get("total_interactions", 0)
        if interactions > 1:
            parts.append(
                f"- You have exchanged {interactions} messages with them before."
            )
        if sender_history.get("notes"):
            parts.append(f"- Notes: {sender_history['notes']}")
        parts.append("")

    parts += [
        "## Email to Reply To",
        f"From: {sender_name} <{sender_email}>",
        f"Subject: {subject}",
        "",
        body,
        "",
    ]

    parts += ["## Extracted Details Checklist (ensure each is addressed)"]
    has_details = False

    if details.get("questions"):
        for q in details["questions"]:
            parts.append(f"- Question: {q}")
        has_details = True

    if details.get("dates"):
        for d in details["dates"]:
            parts.append(f"- Date/timing mentioned: {d}")
        has_details = True

    if details.get("experience_level") and details["experience_level"] != "unknown":
        parts.append(f"- Experience level: {details['experience_level']}")
        has_details = True

    if details.get("party_size"):
        parts.append(f"- Party size: {details['party_size']}")
        has_details = True

    if details.get("class_time_preference"):
        parts.append(f"- Time preference: {details['class_time_preference']}")
        has_details = True

    if details.get("goals_concerns"):
        for item in details["goals_concerns"]:
            parts.append(f"- Goal/concern: {item}")
        has_details = True

    if details.get("details"):
        for item in details["details"]:
            parts.append(f"- Other detail: {item}")
        has_details = True

    if not has_details:
        parts.append(
            "(No structured details extracted — use context from the email body.)"
        )

    parts.append("")
    parts.append("Write the reply now:")

    return "\n".join(parts)
