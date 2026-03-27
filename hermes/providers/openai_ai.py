"""OpenAI AI provider for Hermes.

Wraps the official openai SDK for classification, extraction,
and draft generation.
"""

import logging
from typing import Optional

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)


class OpenAIProvider(AIProvider):
    """AI provider using the OpenAI Chat Completions API via the official SDK."""

    def __init__(self, config: HermesConfig, role: str = "generation"):
        self._config = config
        self._role = role

        ai_cfg = config.ai_config.get("openai", {})
        if role == "classifier":
            self._model = ai_cfg.get("classifier_model", "gpt-4o-mini")
            self._default_max_tokens = ai_cfg.get("max_tokens_classification", 256)
            self._default_temperature = ai_cfg.get("temperature_classification", 0.1)
        else:
            self._model = ai_cfg.get("generation_model", "gpt-4o")
            self._default_max_tokens = ai_cfg.get("max_tokens_generation", 1000)
            self._default_temperature = ai_cfg.get("temperature_generation", 0.7)

        self._api_key = config.openai_api_key
        if not self._api_key:
            logger.warning("OPENAI_API_KEY not set — OpenAI provider will fail")

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 0,
        temperature: float = -1.0,
    ) -> str:
        """Generate a completion using the OpenAI Chat API.

        Args:
            prompt: User message content.
            system: Optional system prompt.
            max_tokens: Override max tokens (0 = use role default).
            temperature: Override temperature (negative = use role default).

        Returns:
            Generated text.

        Raises:
            openai.APIError: On API errors.
        """
        import openai

        client = openai.OpenAI(api_key=self._api_key)

        effective_max_tokens = max_tokens if max_tokens > 0 else self._default_max_tokens
        effective_temp = temperature if temperature >= 0 else self._default_temperature

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=effective_max_tokens,
            temperature=effective_temp,
        )
        return response.choices[0].message.content or ""
