"""Fetch emails from configured accounts with deduplication.

Generic N-account fetcher using the configured email provider.
Supports forwarded email detection and cross-account dedup.
"""

import re
import logging
from typing import Dict, List, Optional, Set

from hermes.config import HermesConfig
from hermes.providers.base import EmailProvider

logger = logging.getLogger(__name__)

# Regex to detect forwarded subjects
_FWD_RE = re.compile(r"^(?:fwd?|fw)\s*:\s*", re.IGNORECASE)

# Regex to extract a bare email address from "Name <email>"
_EMAIL_RE = re.compile(r"<([^>]+)>")

# System/noreply addresses to skip when extracting original sender
_SYSTEM_EMAIL_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in [
        r"noreply@", r"no-reply@", r"donotreply@",
        r"notifications@", r"mailer-daemon@", r"postmaster@",
        r"@wodifymail\.com$",
    ]
]


def _is_system_email(email: str) -> bool:
    """Check if an email address is a system/noreply address."""
    return any(p.search(email) for p in _SYSTEM_EMAIL_PATTERNS)


# ---------------------------------------------------------------------------
# Core fetch
# ---------------------------------------------------------------------------


def fetch_new_emails(
    config: HermesConfig,
    email_provider: EmailProvider,
) -> List[Dict]:
    """Fetch new emails from all configured accounts with cross-account dedup.

    The canonical account (first account with ``canonical: true``) is fetched
    first and its messages form the dedup baseline.  Secondary accounts are
    then fetched and any messages whose dedup key matches a canonical message
    are dropped.

    Args:
        config: HermesConfig instance.
        email_provider: An EmailProvider implementation.

    Returns:
        Deduplicated list of parsed email dicts, each annotated with an
        ``account`` key.
    """
    sb = config.get_supabase()
    accounts = config.email_accounts
    canonical = config.canonical_account

    all_messages: List[Dict] = []
    canonical_keys: Set[str] = set()

    # Fetch canonical account first
    if canonical:
        already = _get_already_processed_ids(sb, canonical)
        raw = email_provider.fetch_messages(
            canonical, max_results=config.max_emails_per_cycle
        )
        new = [m for m in raw if m["id"] not in already]
        canonical_keys = {_dedup_key(m) for m in new}
        all_messages.extend(new)
        logger.info(
            "Account %s: %d fetched, %d new",
            canonical, len(raw), len(new),
        )

    # Fetch remaining accounts with dedup against canonical
    for acct in accounts:
        address = acct.get("address", "")
        if address == canonical:
            continue
        already = _get_already_processed_ids(sb, address)
        raw = email_provider.fetch_messages(
            address, max_results=config.max_emails_per_cycle
        )
        new = [m for m in raw if m["id"] not in already]
        for msg in new:
            key = _dedup_key(msg)
            if key in canonical_keys:
                logger.debug(
                    "Dropping %s duplicate of canonical email (key=%s, id=%s)",
                    address, key, msg["id"],
                )
            else:
                all_messages.append(msg)

        logger.info(
            "Account %s: %d fetched, %d new (after dedup)",
            address, len(raw), len(new),
        )

    return all_messages


# ---------------------------------------------------------------------------
# Already-processed IDs
# ---------------------------------------------------------------------------


def _get_already_processed_ids(sb, account: str) -> Set[str]:
    """Query hermes_drafts for gmail_message_ids already processed for account."""
    response = (
        sb.table("hermes_drafts")
        .select("gmail_message_id")
        .eq("gmail_account", account)
        .execute()
    )
    rows = response.data or []
    return {row["gmail_message_id"] for row in rows if row.get("gmail_message_id")}


# ---------------------------------------------------------------------------
# Dedup key
# ---------------------------------------------------------------------------


def _dedup_key(msg: Dict) -> str:
    """Build a dedup key from the original sender and normalised subject.

    Strips forward prefixes so ``info@`` originals and ``owner@`` forwards
    resolve to the same key.
    """
    subject = msg.get("subject", "")
    from_header = msg.get("from_email", "")
    body = msg.get("body", "")

    normalised_subject = _FWD_RE.sub("", subject).strip().lower()
    original_sender = extract_original_sender(from_header, body)

    return f"{original_sender}|{normalised_subject}"


# ---------------------------------------------------------------------------
# Forwarded email helpers (exported for use by cycle.py)
# ---------------------------------------------------------------------------


def extract_original_sender(from_header: str, body: str, forwarding_accounts: Optional[Set] = None) -> str:
    """Return the best-guess original sender email address.

    For forwarded messages the body is searched for the actual originator.
    Skips system/noreply addresses and uses multiple extraction patterns:
    1. Wodify/booking: "Contact Info" + "mailto:email"
    2. Form submissions: "Email: x@y.com"
    3. Gmail forwarded "From:" header (skip noreply)
    4. Any non-system email in body

    Args:
        from_header: Raw From: header value.
        body: Email body text.
        forwarding_accounts: Optional set of known forwarding addresses to skip.

    Returns:
        Lowercase email address of the original sender.
    """
    skip_emails = forwarding_accounts or set()

    # Pattern 1: Wodify/booking — "Contact Info" + mailto:
    mailto_match = re.search(r"mailto:([^\s\n\r<>\"]+@[^\s\n\r<>\"]+)", body, re.IGNORECASE)
    if mailto_match:
        email = mailto_match.group(1).strip().lower()
        if not _is_system_email(email) and email not in skip_emails:
            return email

    # Pattern 2: Form fields — "Email: x@y.com"
    email_field = re.search(
        r"(?:Email|E-mail|email address)\s*[:=]\s*([^\s<>,]+@[^\s<>,]+)", body, re.IGNORECASE
    )
    if email_field:
        email = email_field.group(1).strip().lower()
        if not _is_system_email(email) and email not in skip_emails:
            return email

    # Pattern 3: Forwarded "From:" header — skip system addresses
    fwd_from_match = re.search(
        r"(?:^|\n)[ \t]*From\s*:\s*(.+)", body, re.IGNORECASE
    )
    if fwd_from_match:
        candidate = fwd_from_match.group(1).strip()
        email_match = _EMAIL_RE.search(candidate)
        if email_match:
            email = email_match.group(1).lower()
            if not _is_system_email(email) and email not in skip_emails:
                return email
        elif "@" in candidate:
            email = candidate.split()[0].lower()
            if not _is_system_email(email) and email not in skip_emails:
                return email

    # Pattern 4: Any non-system email in body
    body_emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w{2,}", body)
    for email in body_emails:
        email = email.lower()
        if not _is_system_email(email) and email not in skip_emails:
            return email

    # Fall back to the From: header
    email_match = _EMAIL_RE.search(from_header)
    if email_match:
        return email_match.group(1).lower()

    return from_header.lower()


def extract_sender_name(from_header: str) -> str:
    """Parse the display name from a ``Name <email>`` header value.

    Falls back to the email username prefix if no display name is present.
    """
    if not from_header:
        return ""

    angle_match = re.match(r"^(.+?)\s*<[^>]+>$", from_header.strip())
    if angle_match:
        name = angle_match.group(1).strip().strip('"').strip("'")
        if name:
            return name

    if "@" in from_header:
        local_part = from_header.split("@")[0].strip().lstrip("<").strip()
        return local_part

    return from_header.strip()


def extract_original_sender_name(body: str) -> str:
    """Extract the original sender's display name from a forwarded email body.

    Checks multiple patterns:
    1. Wodify: "Contact Info" followed by name
    2. "Name reserved a ... session" pattern
    3. Form fields: "Name: ..."
    4. Gmail forwarded "From: Name <email>" header (skip noreply)
    """
    # Pattern 1: Wodify — "Contact Info" + name on next line
    contact_match = re.search(
        r"Contact\s*Info\s*[\n\r]*([A-Z][a-z]+ [A-Z][a-z]+[^\n\r]*)", body
    )
    if contact_match:
        name = contact_match.group(1).strip()
        if name and "@" not in name:
            return name

    # Pattern 2: "Name reserved a ... session"
    reserved_match = re.search(r"([A-Z][a-z]+ [A-Z][a-z]+)\s+reserved", body)
    if reserved_match:
        return reserved_match.group(1).strip()

    # Pattern 3: Form field "Name: ..."
    name_field = re.search(
        r"(?:Name|Full Name|First Name)\s*[:=]\s*([^\n\r]+)", body, re.IGNORECASE
    )
    if name_field:
        name = name_field.group(1).strip()
        if name and "@" not in name:
            return name

    # Pattern 4: Gmail forwarded "From:" header — skip noreply
    fwd_from_match = re.search(
        r"(?:^|\n)[ \t]*From\s*:\s*(.+)", body, re.IGNORECASE
    )
    if fwd_from_match:
        candidate = fwd_from_match.group(1).strip()
        angle_match = re.match(r"^(.+?)\s*<([^>]+)>$", candidate)
        if angle_match:
            email = angle_match.group(2).strip()
            if not _is_system_email(email):
                name = angle_match.group(1).strip().strip('"').strip("'")
                if name:
                    return name
        if "@" not in candidate:
            return candidate

    return ""


def is_forwarded(subject: str) -> bool:
    """Check if a subject line indicates a forwarded email."""
    return bool(_FWD_RE.match(subject))


def strip_forward_prefix(subject: str) -> str:
    """Remove Fwd:/FW: prefix from a subject line."""
    return _FWD_RE.sub("", subject).strip()
