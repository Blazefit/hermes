"""Send reply and audit logging for Hermes.

Handles sending email replies via the configured email provider,
preventing duplicate sends, logging audit entries, and updating
sender history.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from hermes.config import HermesConfig
from hermes.providers.base import EmailProvider

logger = logging.getLogger(__name__)

# Draft statuses that indicate the email has already been sent
_SENT_STATUSES = {"sent", "auto_sent"}

# Draft statuses that are terminal
_TERMINAL_STATUSES = {"sent", "auto_sent", "discarded", "stale"}


def send_reply(
    draft_id: str,
    config: HermesConfig,
    email_provider: EmailProvider,
    reply_text: Optional[str] = None,
    from_account: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch a draft from Supabase, send it, and update records.

    Args:
        draft_id: UUID of the hermes_drafts row.
        config: HermesConfig instance.
        email_provider: EmailProvider for sending.
        reply_text: Optional override text. If None, stored draft_text is used.
        from_account: Sending account. Defaults to config.reply_from_account.

    Returns:
        Dict with: success, draft_id, message_id, error.
    """
    sb = config.get_supabase()
    from_account = from_account or config.reply_from_account

    # Fetch draft
    result = (
        sb.table("hermes_drafts")
        .select("*")
        .eq("id", draft_id)
        .maybe_single()
        .execute()
    )
    draft = result.data
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")

    # Duplicate-send guard
    if draft["status"] in _SENT_STATUSES:
        logger.warning(
            "Draft %s already has status %r — skipping send.",
            draft_id, draft["status"],
        )
        return {
            "success": False,
            "draft_id": draft_id,
            "message_id": None,
            "error": f"Draft already sent (status={draft['status']!r})",
        }

    # Resolve reply text
    send_text = reply_text if reply_text is not None else draft.get("draft_text", "")
    if not send_text:
        return {
            "success": False,
            "draft_id": draft_id,
            "message_id": None,
            "error": "No reply text available to send.",
        }

    # Compute edit diff if text was overridden
    edit_diff: Optional[Dict] = None
    stored_text = draft.get("draft_text", "") or ""
    if reply_text is not None and reply_text != stored_text:
        edit_diff = {"original": stored_text, "edited": reply_text}

    # Build email headers
    subject = draft.get("subject") or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    to_address = draft.get("sender_email", "")
    thread_id = draft.get("gmail_thread_id")
    original_message_id = draft.get("gmail_message_id")

    # Send
    try:
        send_result = email_provider.send_message(
            from_account=from_account,
            to=to_address,
            subject=subject,
            body=send_text,
            thread_id=thread_id,
            in_reply_to=original_message_id,
        )
    except Exception as exc:
        logger.error("Failed to send draft %s: %s", draft_id, exc)
        _log_audit(
            sb, draft_id=draft_id, action="fetch_failed",
            actor=from_account, details={"error": str(exc), "stage": "send"},
        )
        return {
            "success": False,
            "draft_id": draft_id,
            "message_id": None,
            "error": str(exc),
        }

    sent_at = datetime.now(timezone.utc).isoformat()
    returned_message_id = send_result.get("id")

    # Update draft record
    update_payload: Dict[str, Any] = {"status": "sent", "sent_at": sent_at}
    if edit_diff is not None:
        update_payload["edit_diff"] = edit_diff
        update_payload["user_edits"] = reply_text

    sb.table("hermes_drafts").update(update_payload).eq("id", draft_id).execute()

    # Audit log
    _log_audit(
        sb, draft_id=draft_id, action="sent", actor=from_account,
        details={
            "to": to_address, "subject": subject,
            "gmail_message_id": returned_message_id,
            "sent_at": sent_at, "was_edited": edit_diff is not None,
        },
    )

    # Update sender history
    sender_email = draft.get("sender_email", "")
    sender_name = draft.get("sender_name", "")
    category = draft.get("category", "uncategorized")
    if sender_email:
        _update_sender_history(sb, sender_email, sender_name, category)

    logger.info(
        "Sent draft %s to %s (message_id=%s)",
        draft_id, to_address, returned_message_id,
    )

    return {
        "success": True,
        "draft_id": draft_id,
        "message_id": returned_message_id,
        "error": None,
    }


def auto_send_draft(
    draft_id: str,
    config: HermesConfig,
    email_provider: EmailProvider,
) -> Dict[str, Any]:
    """Attempt to auto-send a draft if all conditions are met.

    Checks: auto_send_enabled, auto_send_locked, confidence threshold,
    blocking flags, not already sent.
    """
    sb = config.get_supabase()

    # Fetch draft
    result = (
        sb.table("hermes_drafts")
        .select("*")
        .eq("id", draft_id)
        .maybe_single()
        .execute()
    )
    draft = result.data
    if not draft:
        raise ValueError(f"Draft not found: {draft_id}")

    if draft["status"] in _SENT_STATUSES:
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": True, "skip_reason": f"Already sent ({draft['status']!r})",
            "error": None,
        }

    category = draft.get("category", "uncategorized")
    cat_cfg = config.category_config(category)

    # Auto-send enabled check
    if not cat_cfg.get("auto_send", False):
        reason = f"auto_send is disabled for category {category!r}"
        logger.info("Skipping auto-send for draft %s: %s", draft_id, reason)
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": True, "skip_reason": reason, "error": None,
        }

    # Locked check
    if cat_cfg.get("auto_send_locked", False):
        reason = f"auto_send_locked for category {category!r}"
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": True, "skip_reason": reason, "error": None,
        }

    # Confidence threshold
    min_confidence = cat_cfg.get("min_confidence", config.auto_send_confidence_threshold)
    confidence = draft.get("classification_confidence") or 0.0
    if confidence < min_confidence:
        reason = f"Confidence {confidence:.3f} below threshold {min_confidence:.3f}"
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": True, "skip_reason": reason, "error": None,
        }

    # Blocking flags
    flags = draft.get("flags") or []
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except json.JSONDecodeError:
            flags = []
    blocking = [f for f in flags if isinstance(f, dict) and f.get("severity") == "block"]
    if blocking:
        reason = (
            f"Draft has {len(blocking)} blocking flag(s): "
            + ", ".join(f.get("type", "unknown") for f in blocking)
        )
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": True, "skip_reason": reason, "error": None,
        }

    # All checks passed — send
    from_account = config.reply_from_account
    send_text = draft.get("draft_text", "") or ""
    if not send_text:
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": False, "skip_reason": None, "error": "No draft text.",
        }

    subject = draft.get("subject") or ""
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    to_address = draft.get("sender_email", "")
    thread_id = draft.get("gmail_thread_id")
    original_message_id = draft.get("gmail_message_id")

    try:
        send_result = email_provider.send_message(
            from_account=from_account, to=to_address, subject=subject,
            body=send_text, thread_id=thread_id, in_reply_to=original_message_id,
        )
    except Exception as exc:
        logger.error("Auto-send failed for draft %s: %s", draft_id, exc)
        return {
            "success": False, "draft_id": draft_id, "message_id": None,
            "skipped": False, "skip_reason": None, "error": str(exc),
        }

    sent_at = datetime.now(timezone.utc).isoformat()
    returned_message_id = send_result.get("id")

    sb.table("hermes_drafts").update({
        "status": "auto_sent", "sent_at": sent_at,
    }).eq("id", draft_id).execute()

    _log_audit(
        sb, draft_id=draft_id, action="auto_sent", actor="auto_send",
        details={
            "to": to_address, "subject": subject,
            "gmail_message_id": returned_message_id,
            "confidence": confidence, "from_account": from_account,
        },
    )

    sender_email = draft.get("sender_email", "")
    sender_name = draft.get("sender_name", "")
    if sender_email:
        _update_sender_history(sb, sender_email, sender_name, category)

    logger.info("Auto-sent draft %s to %s", draft_id, to_address)

    return {
        "success": True, "draft_id": draft_id,
        "message_id": returned_message_id,
        "skipped": False, "skip_reason": None, "error": None,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _log_audit(
    sb, draft_id: str, action: str, actor: str, details: Dict[str, Any]
) -> None:
    """Insert a row into hermes_audit_log. Swallows errors."""
    try:
        sb.table("hermes_audit_log").insert({
            "draft_id": draft_id,
            "action": action,
            "actor": actor,
            "details": details,
        }).execute()
    except Exception as exc:
        logger.warning("Audit log insert failed for %s: %s", draft_id, exc)


def _update_sender_history(
    sb, email: str, name: Optional[str] = None, category: str = ""
) -> None:
    """Upsert sender history row."""
    email = email.lower().strip()
    if not email:
        return

    try:
        result = (
            sb.table("hermes_sender_history")
            .select("*")
            .eq("email", email)
            .maybe_single()
            .execute()
        )
        existing = result.data
        now_iso = datetime.now(timezone.utc).isoformat()

        if existing:
            new_count = (existing.get("total_interactions") or 1) + 1
            existing_cats = existing.get("categories") or []
            if isinstance(existing_cats, str):
                try:
                    existing_cats = json.loads(existing_cats)
                except json.JSONDecodeError:
                    existing_cats = []
            if category and category not in existing_cats:
                existing_cats = list(existing_cats) + [category]

            sb.table("hermes_sender_history").update({
                "total_interactions": new_count,
                "categories": existing_cats,
                "updated_at": now_iso,
            }).eq("email", email).execute()
        else:
            sb.table("hermes_sender_history").insert({
                "email": email,
                "name": name or None,
                "total_interactions": 1,
                "categories": [category] if category else [],
                "first_contact": now_iso,
                "updated_at": now_iso,
            }).execute()
    except Exception as exc:
        logger.warning("Failed to update sender history for %s: %s", email, exc)
