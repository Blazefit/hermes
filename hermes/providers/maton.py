"""Maton gateway email provider.

Implements EmailProvider using the Maton.ai gateway to interact with
Gmail accounts.  Maton proxies the Gmail REST API and requires a
connection ID per Gmail account.

API docs: https://docs.maton.ai
"""

import base64
import logging
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import requests

from hermes.config import HermesConfig
from hermes.providers.base import EmailProvider

logger = logging.getLogger(__name__)

MATON_GATEWAY_URL = "https://gateway.maton.ai"
GMAIL_MESSAGES_PATH = "/google-mail/gmail/v1/users/me/messages"
GMAIL_SEND_PATH = "/google-mail/gmail/v1/users/me/messages/send"


class MatonProvider(EmailProvider):
    """Email provider using the Maton.ai Gmail gateway.

    Requires:
        - MATON_API_KEY in environment
        - connection_id per account in hermes.yaml
    """

    def __init__(self, config: HermesConfig):
        self._config = config
        self._api_key = config.maton_api_key
        self._connections = config.account_connection_map
        if not self._api_key:
            logger.warning("MATON_API_KEY not set — Maton provider will fail on API calls")

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _headers(self, connection_id: Optional[str] = None) -> Dict[str, str]:
        """Build HTTP headers for Maton API calls."""
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if connection_id:
            headers["Maton-Connection"] = connection_id
        return headers

    def _get_connection_id(self, account: str) -> str:
        """Resolve connection ID for an account, raising if not found."""
        conn_id = self._connections.get(account)
        if not conn_id:
            raise ValueError(f"No Maton connection ID configured for account: {account}")
        return conn_id

    # ------------------------------------------------------------------
    # Fetch messages
    # ------------------------------------------------------------------

    def fetch_messages(
        self,
        account: str,
        max_results: int = 20,
        query: str = "in:inbox is:unread",
    ) -> List[Dict[str, Any]]:
        """Fetch Gmail messages via the Maton gateway.

        Two-step process:
        1. List message IDs matching the query.
        2. Fetch full message detail for each ID.
        """
        connection_id = self._get_connection_id(account)
        headers = self._headers(connection_id)
        messages_url = f"{MATON_GATEWAY_URL}{GMAIL_MESSAGES_PATH}"

        # Step 1 — list message IDs
        list_params = {"maxResults": max_results, "q": query}
        resp = requests.get(messages_url, headers=headers, params=list_params, timeout=30)
        resp.raise_for_status()
        list_data = resp.json()

        message_stubs = list_data.get("messages", [])
        if not message_stubs:
            return []

        # Step 2 — fetch full detail for each message
        messages: List[Dict[str, Any]] = []
        for stub in message_stubs[:max_results]:
            msg_id = stub.get("id")
            if not msg_id:
                continue
            detail_url = f"{messages_url}/{msg_id}"
            detail_resp = requests.get(
                detail_url,
                headers=headers,
                params={"format": "full"},
                timeout=30,
            )
            if detail_resp.status_code != 200:
                logger.warning(
                    "Failed to fetch message %s for %s: HTTP %s",
                    msg_id, account, detail_resp.status_code,
                )
                continue
            raw_msg = detail_resp.json()
            parsed = self._parse_message(raw_msg)
            parsed["account"] = account
            messages.append(parsed)

        return messages

    # ------------------------------------------------------------------
    # Send message
    # ------------------------------------------------------------------

    def send_message(
        self,
        from_account: str,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email via the Maton Gmail send endpoint.

        Builds an RFC 2822 MIME message and base64url-encodes it for the
        Gmail API.  Sets In-Reply-To and References headers when replying
        to keep proper threading.
        """
        connection_id = self._get_connection_id(from_account)

        # Build MIME message
        mime_msg = MIMEText(body, "plain", "utf-8")
        mime_msg["To"] = to
        mime_msg["Subject"] = subject

        if in_reply_to:
            ref_id = in_reply_to if in_reply_to.startswith("<") else f"<{in_reply_to}>"
            mime_msg["In-Reply-To"] = ref_id
            mime_msg["References"] = ref_id

        # base64url-encode the raw message
        raw_bytes = mime_msg.as_bytes()
        raw_b64 = base64.urlsafe_b64encode(raw_bytes).decode("ascii")

        payload: Dict[str, Any] = {"raw": raw_b64}
        if thread_id:
            payload["threadId"] = thread_id

        url = f"{MATON_GATEWAY_URL}{GMAIL_SEND_PATH}"
        headers = self._headers(connection_id)

        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_message(msg: Dict) -> Dict[str, Any]:
        """Extract structured fields from a raw Gmail API message object."""
        headers_list = msg.get("payload", {}).get("headers", [])
        headers_map = {
            h["name"].lower(): h["value"]
            for h in headers_list
            if "name" in h and "value" in h
        }

        body = MatonProvider._extract_body(msg.get("payload", {}))

        return {
            "id": msg.get("id", ""),
            "thread_id": msg.get("threadId", ""),
            "subject": headers_map.get("subject", ""),
            "from_email": headers_map.get("from", ""),
            "to": headers_map.get("to", ""),
            "date": headers_map.get("date", ""),
            "snippet": msg.get("snippet", ""),
            "body": body,
        }

    @staticmethod
    def _extract_body(payload: Dict) -> str:
        """Recursively extract plain-text body from a Gmail payload.

        Handles simple and arbitrarily nested multipart payloads.
        """
        mime_type: str = payload.get("mimeType", "")

        if not mime_type.startswith("multipart/"):
            if mime_type == "text/plain":
                data = payload.get("body", {}).get("data", "")
                if data:
                    try:
                        return base64.urlsafe_b64decode(data + "==").decode(
                            "utf-8", errors="replace"
                        )
                    except Exception:
                        return ""
            return ""

        parts = payload.get("parts", [])
        plain_text = ""
        for part in parts:
            result = MatonProvider._extract_body(part)
            if result:
                if part.get("mimeType", "") == "text/plain":
                    return result
                if not plain_text:
                    plain_text = result

        return plain_text
