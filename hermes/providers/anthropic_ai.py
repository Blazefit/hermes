"""Anthropic AI provider for Hermes.

Wraps the official anthropic SDK for classification, extraction,
and draft generation.
"""

import logging
from typing import Optional

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    """AI provider using the Anthropic Messages API via the official SDK."""

    def __init__(self, config: HermesConfig, role: str = "generation"):
        """Initialize the Anthropic provider.

        Args:
            config: HermesConfig instance.
            role: ``"generation"`` or ``"classifier"`` — determines which
                model and default parameters are used.
        """
        self._config = config
        self._role = role

        ai_cfg = config.ai_config.get("anthropic", {})
        if role == "classifier":
            self._model = ai_cfg.get("classifier_model", "claude-haiku-4-5-20251001")
            self._default_max_tokens = ai_cfg.get("max_tokens_classification", 256)
            self._default_temperature = ai_cfg.get("temperature_classification", 0.1)
        else:
            self._model = ai_cfg.get("generation_model", "claude-sonnet-4-6")
            self._default_max_tokens = ai_cfg.get("max_tokens_generation", 1000)
            self._default_temperature = ai_cfg.get("temperature_generation", 0.7)

        self._api_key = config.anthropic_api_key
        if not self._api_key:
            logger.warning("ANTHROPIC_API_KEY not set — Anthropic provider will fail")

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 0,
        temperature: float = -1.0,
    ) -> str:
        """Generate a completion using the Anthropic Messages API.

        Args:
            prompt: User message content.
            system: Optional system prompt.
            max_tokens: Override max tokens (0 = use role default).
            temperature: Override temperature (negative = use role default).

        Returns:
            Generated text.

        Raises:
            anthropic.APIError: On API errors.
        """
        import anthropic

        client = anthropic.Anthropic(api_key=self._api_key)

        effective_max_tokens = max_tokens if max_tokens > 0 else self._default_max_tokens
        effective_temp = temperature if temperature >= 0 else self._default_temperature

        kwargs = {
            "model": self._model,
            "max_tokens": effective_max_tokens,
            "temperature": effective_temp,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        response = client.messages.create(**kwargs)
        return response.content[0].text
