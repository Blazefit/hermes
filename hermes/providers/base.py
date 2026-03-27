"""Abstract base classes for Hermes providers."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class EmailProvider(ABC):
    """Abstract interface for fetching and sending emails."""

    @abstractmethod
    def fetch_messages(
        self,
        account: str,
        max_results: int = 20,
        query: str = "in:inbox is:unread",
    ) -> List[Dict[str, Any]]:
        """Fetch email messages for an account.

        Args:
            account: Email address to fetch messages for.
            max_results: Maximum number of messages to return.
            query: Provider-specific search query.

        Returns:
            List of parsed message dicts with at minimum:
                id, thread_id, subject, from_email, to, date, snippet, body, account
        """

    @abstractmethod
    def send_message(
        self,
        from_account: str,
        to: str,
        subject: str,
        body: str,
        thread_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send an email message.

        Args:
            from_account: Sending account email address.
            to: Recipient email address.
            subject: Email subject line.
            body: Plain text email body.
            thread_id: Thread ID for threading replies.
            in_reply_to: Message ID to set In-Reply-To header.

        Returns:
            Dict with at minimum: id (provider message ID).
        """


class AIProvider(ABC):
    """Abstract interface for AI text generation."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 1000,
        temperature: float = 0.7,
    ) -> str:
        """Generate a text completion.

        Args:
            prompt: The user/input prompt text.
            system: Optional system prompt.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature.

        Returns:
            Generated text string.

        Raises:
            Exception: On API errors.
        """
