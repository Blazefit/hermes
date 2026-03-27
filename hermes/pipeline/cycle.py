"""Process cycle orchestrator for Hermes.

Runs one full email processing cycle:
  1. Acquire advisory lock
  2. Fetch new emails from all accounts
  3. Filter blacklisted senders
  4. Enforce cross-account safety cap
  5. Process each email through the full pipeline
  6. Mark stale drafts
  7. Update last_processed_at
  8. Release lock
"""

import json
import logging
import os
import re
import urllib.request
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

from hermes.config import HermesConfig
from hermes.providers import get_ai_provider, get_email_provider
from hermes.providers.base import AIProvider, EmailProvider
from hermes.pipeline.fetch import (
    fetch_new_emails,
    extract_original_sender,
    extract_sender_name,
    extract_original_sender_name,
    is_forwarded,
    strip_forward_prefix,
)
from hermes.pipeline.classify import classify_email
from hermes.pipeline.extract import extract_details
from hermes.pipeline.generate import generate_draft
from hermes.pipeline.validate import validate_draft
from hermes.pipeline.send import auto_send_draft

logger = logging.getLogger(__name__)


def run_cycle(config: HermesConfig) -> Dict:
    """Run one full email processing cycle.

    Args:
        config: HermesConfig instance.

    Returns:
        Dict with: status, fetched, classified, drafts_generated,
        auto_sent, flagged, errors.
    """
    summary: Dict = {
        "status": "ok",
        "fetched": 0,
        "classified": 0,
        "drafts_generated": 0,
        "auto_sent": 0,
        "flagged": 0,
        "errors": [],
    }

    sb = config.get_supabase()

    # Step 1 — Acquire advisory lock
    try:
        lock_resp = sb.rpc("hermes_try_lock").execute()
        acquired = bool(lock_resp.data)
    except Exception as exc:
        logger.error("Failed to acquire advisory lock: %s", exc)
        summary["status"] = "error"
        summary["errors"].append(f"lock_acquire_error: {exc}")
        return summary

    if not acquired:
        logger.info("Advisory lock held — skipping cycle")
        _log_audit(sb, None, "cycle_skipped", {"reason": "lock_held"})
        summary["status"] = "skipped"
        return summary

    # Instantiate providers
    email_provider = get_email_provider(config)
    gen_provider = get_ai_provider(config, role="generation")
    cls_provider = get_ai_provider(config, role="classifier")

    try:
        # Step 2 — Fetch new emails
        try:
            emails = fetch_new_emails(config, email_provider)
        except Exception as exc:
            logger.error("fetch_new_emails failed: %s", exc)
            summary["status"] = "error"
            summary["errors"].append(f"fetch_error: {exc}")
            return summary

        # Step 2.5 — Filter blacklisted senders
        emails = _filter_blacklisted(sb, emails)

        total_fetched = len(emails)
        summary["fetched"] = total_fetched
        logger.info("Fetched %d new emails (after blacklist filter)", total_fetched)

        # Step 3 — Safety cap
        if total_fetched > config.max_emails_per_cycle:
            logger.warning(
                "Fetched %d exceeds max %d; truncating",
                total_fetched, config.max_emails_per_cycle,
            )
            emails = emails[: config.max_emails_per_cycle]

        # Step 4 — Process each email
        for email in emails:
            account = email.get("account", "")
            try:
                _process_single_email(
                    sb, account, email, summary, config,
                    email_provider, gen_provider, cls_provider,
                )
            except Exception as exc:
                logger.exception(
                    "Unhandled error processing email id=%s: %s",
                    email.get("id", "?"), exc,
                )
                summary["errors"].append(
                    f"process_error id={email.get('id', '?')}: {exc}"
                )

        # Step 5 — Mark stale drafts
        try:
            _mark_stale_drafts(sb, config.stale_draft_hours)
        except Exception as exc:
            logger.error("_mark_stale_drafts failed: %s", exc)
            summary["errors"].append(f"stale_mark_error: {exc}")

        # Step 6 — Update last_processed_at
        try:
            sb.table("hermes_config").update(
                {"last_processed_at": datetime.now(timezone.utc).isoformat()}
            ).neq("id", "00000000-0000-0000-0000-000000000000").execute()
        except Exception as exc:
            logger.error("Failed to update last_processed_at: %s", exc)

    finally:
        # Step 7 — Release lock
        try:
            sb.rpc("hermes_unlock").execute()
        except Exception as exc:
            logger.error("Failed to release advisory lock: %s", exc)
            summary["errors"].append(f"lock_release_error: {exc}")

    if summary["errors"]:
        summary["status"] = "error"

    return summary


# ---------------------------------------------------------------------------
# Blacklist filter
# ---------------------------------------------------------------------------


def _filter_blacklisted(sb, emails: List[Dict]) -> List[Dict]:
    """Remove emails from blacklisted senders/domains."""
    blacklisted_emails = set()
    blacklisted_domains = set()

    try:
        bl_result = sb.table("hermes_sender_blacklist").select("email, domain").execute()
        if bl_result.data:
            for row in bl_result.data:
                if row.get("email"):
                    blacklisted_emails.add(row["email"].lower())
                if row.get("domain"):
                    blacklisted_domains.add(row["domain"].lower())
    except Exception as exc:
        logger.warning("Failed to load blacklist: %s", exc)
        return emails

    if not blacklisted_emails and not blacklisted_domains:
        return emails

    filtered = []
    for email_msg in emails:
        sender = (email_msg.get("from_email") or "").lower()
        sender_domain = sender.split("@")[1] if "@" in sender else ""
        if sender in blacklisted_emails or sender_domain in blacklisted_domains:
            logger.debug("Skipping blacklisted sender: %s", sender)
        else:
            filtered.append(email_msg)

    skipped = len(emails) - len(filtered)
    if skipped:
        logger.info("Skipped %d blacklisted emails", skipped)

    return filtered


# ---------------------------------------------------------------------------
# Single-email pipeline
# ---------------------------------------------------------------------------


def _process_single_email(
    sb,
    account: str,
    email: Dict,
    summary: Dict,
    config: HermesConfig,
    email_provider: EmailProvider,
    gen_provider: AIProvider,
    cls_provider: AIProvider,
) -> None:
    """Run the full pipeline for one email."""
    _email_re = re.compile(r"<([^>]+)>")

    gmail_message_id = email.get("id", "")
    gmail_thread_id = email.get("thread_id", "")
    subject = email.get("subject", "")
    body = email.get("body", "")
    from_header = email.get("from_email", "")

    # Handle forwarded emails
    if is_forwarded(subject):
        subject = strip_forward_prefix(subject)
        sender_email = extract_original_sender(from_header, body)
        original_name = extract_original_sender_name(body)
        sender_name = original_name or extract_sender_name(from_header)
        logger.info(
            "Forwarded email (id=%s): resolved sender=%s <%s>",
            gmail_message_id, sender_name, sender_email,
        )
    else:
        email_match = _email_re.search(from_header)
        sender_email = (
            email_match.group(1).lower() if email_match else from_header.lower().strip()
        )
        sender_name = extract_sender_name(from_header)

    # Check for existing thread (follow-up detection)
    is_followup = False
    if gmail_thread_id:
        try:
            thread_check = (
                sb.table("hermes_drafts")
                .select("id")
                .eq("gmail_thread_id", gmail_thread_id)
                .eq("gmail_account", account)
                .limit(1)
                .execute()
            )
            is_followup = bool(thread_check.data)
        except Exception as exc:
            logger.warning("Thread lookup failed: %s", exc)

    # Classify
    try:
        classification = classify_email(subject, body, config, cls_provider)
    except Exception as exc:
        logger.error("classify_email failed for %s: %s", gmail_message_id, exc)
        summary["errors"].append(f"classify_error id={gmail_message_id}: {exc}")
        return

    category = classification.get("category", "uncategorized")
    confidence = classification.get("confidence", 0.0)
    summary["classified"] += 1
    logger.info(
        "Classified %s as %s (confidence=%.2f, method=%s)",
        gmail_message_id, category, confidence, classification.get("method", "?"),
    )

    # Extract details
    try:
        details = extract_details(subject, body, sender_name, config, cls_provider)
    except Exception as exc:
        logger.error("extract_details failed for %s: %s", gmail_message_id, exc)
        details = {}
        summary["errors"].append(f"extract_error id={gmail_message_id}: {exc}")

    # Generate draft
    original_email_for_gen = {
        "subject": subject,
        "body": body,
        "sender_email": sender_email,
        "sender_name": sender_name,
    }
    try:
        gen_result = generate_draft(
            original_email_for_gen, category, details, config, gen_provider
        )
    except Exception as exc:
        logger.error("generate_draft failed for %s: %s", gmail_message_id, exc)
        gen_result = {"draft_text": None, "model_used": None, "generation_context": {}}
        summary["errors"].append(f"generate_error id={gmail_message_id}: {exc}")

    draft_text: Optional[str] = gen_result.get("draft_text")
    model_used: Optional[str] = gen_result.get("model_used")
    generation_context: Dict = gen_result.get("generation_context") or {}

    if draft_text:
        summary["drafts_generated"] += 1

    # Validate draft
    validation: Dict = {"passed": False, "flags": []}
    if draft_text:
        try:
            validation = validate_draft(draft_text, category, details, config)
        except Exception as exc:
            logger.error("validate_draft failed for %s: %s", gmail_message_id, exc)
            validation = {
                "passed": False,
                "flags": [
                    {"type": "validation_error", "message": str(exc), "severity": "block"}
                ],
            }

    flags = validation.get("flags", [])
    has_blocking = any(f.get("severity") == "block" for f in flags)
    if has_blocking:
        summary["flagged"] += 1

    # Follow-up blocking flag
    if is_followup:
        flags = list(flags)
        flags.append({
            "type": "followup_thread",
            "message": "Follow-up in existing thread",
            "severity": "block",
        })
        has_blocking = True
        summary["flagged"] += 1

    draft_status = "pending_review"

    # Save to hermes_drafts
    upsert_row = {
        "gmail_account": account,
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": gmail_thread_id or None,
        "sender_email": sender_email,
        "sender_name": sender_name or None,
        "subject": subject or None,
        "original_body": body,
        "category": category,
        "classification_confidence": confidence,
        "extracted_details": details,
        "draft_text": draft_text,
        "generation_context": generation_context if generation_context else None,
        "flags": flags,
        "status": draft_status,
        "model_used": model_used,
    }

    draft_id: Optional[str] = None
    try:
        upsert_resp = (
            sb.table("hermes_drafts")
            .upsert(upsert_row, on_conflict="gmail_message_id,gmail_account")
            .execute()
        )
        rows = upsert_resp.data or []
        if rows:
            draft_id = rows[0].get("id")
    except Exception as exc:
        logger.error("Failed to upsert draft for %s: %s", gmail_message_id, exc)
        summary["errors"].append(f"upsert_error id={gmail_message_id}: {exc}")
        return

    # Notification for high-priority categories
    notify_categories = [
        name for name, cfg in config.categories.items()
        if not cfg.get("auto_send_locked", False) and name != "uncategorized"
    ]
    if category in notify_categories and draft_id:
        _send_notification(
            config,
            f"New {category.replace('_', ' ')} email from "
            f"{sender_name or sender_email}: {subject}",
        )

    # Audit log
    _log_audit(
        sb, draft_id, "generated",
        {
            "category": category, "confidence": confidence,
            "method": classification.get("method", "?"),
            "model_used": model_used, "is_followup": is_followup,
            "flag_count": len(flags), "draft_generated": bool(draft_text),
        },
    )

    # Auto-send if validation passed
    if validation.get("passed") and draft_text and not has_blocking:
        try:
            send_result = auto_send_draft(draft_id, config, email_provider)
            if send_result.get("success"):
                summary["auto_sent"] += 1
        except Exception as exc:
            logger.error("auto_send_draft failed for %s: %s", draft_id, exc)
            summary["errors"].append(f"auto_send_error draft_id={draft_id}: {exc}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mark_stale_drafts(sb, stale_hours: int) -> int:
    """Mark pending_review drafts older than stale_hours as stale."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    cutoff_iso = cutoff.isoformat()

    resp = (
        sb.table("hermes_drafts")
        .update({"status": "stale"})
        .eq("status", "pending_review")
        .lt("created_at", cutoff_iso)
        .execute()
    )
    updated = len(resp.data) if resp.data else 0
    if updated:
        logger.info("Marked %d draft(s) as stale (older than %dh)", updated, stale_hours)
    return updated


def _log_audit(sb, draft_id, action, details=None):
    """Insert audit log row. Swallows errors."""
    row = {"action": action, "actor": "system", "details": details or {}}
    if draft_id:
        row["draft_id"] = draft_id
    try:
        sb.table("hermes_audit_log").insert(row).execute()
    except Exception as exc:
        logger.warning("audit log insert failed (action=%s): %s", action, exc)


def _send_notification(config: HermesConfig, message: str) -> None:
    """Send a push notification via webhook if configured."""
    webhook_url = config.notification_webhook_url
    if not webhook_url:
        return
    try:
        data = json.dumps({"text": message}).encode("utf-8")
        req = urllib.request.Request(
            webhook_url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
        logger.info("Notification sent: %s", message[:80])
    except Exception as exc:
        logger.warning("Notification failed: %s", exc)
