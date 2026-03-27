"""MiniMax AI provider for Hermes.

Calls the MiniMax chat completions API directly via requests.
Strips ``<think>...</think>`` tags from MiniMax-M2.7 responses.
"""

import json
import re
import logging
from typing import Optional

import requests

from hermes.config import HermesConfig
from hermes.providers.base import AIProvider

logger = logging.getLogger(__name__)

MINIMAX_API_URL = "https://api.minimax.io/v1/chat/completions"


class MiniMaxProvider(AIProvider):
    """AI provider using the MiniMax chat completions API."""

    def __init__(self, config: HermesConfig, role: str = "generation"):
        self._config = config
        self._role = role

        ai_cfg = config.ai_config.get("minimax", {})
        self._model = ai_cfg.get("model", "MiniMax-M2.7")

        if role == "classifier":
            self._default_temperature = ai_cfg.get("temperature_classification", 0.1)
        else:
            self._default_temperature = ai_cfg.get("temperature_generation", 0.7)

        self._api_key = config.minimax_api_key
        if not self._api_key:
            logger.warning("MINIMAX_API_KEY not set — MiniMax provider will fail")

    def complete(
        self,
        prompt: str,
        system: Optional[str] = None,
        max_tokens: int = 0,
        temperature: float = -1.0,
    ) -> str:
        """Generate a completion using the MiniMax chat API.

        Args:
            prompt: User message content.
            system: Optional system prompt (sent as a system message).
            max_tokens: Not directly used by MiniMax — included for interface compat.
            temperature: Override temperature (negative = use role default).

        Returns:
            Generated text with <think> tags stripped.

        Raises:
            RuntimeError: On MiniMax API errors.
            requests.HTTPError: On HTTP failures.
        """
        effective_temp = temperature if temperature >= 0 else self._default_temperature

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "temperature": effective_temp,
            "messages": messages,
        }

        resp = requests.post(
            MINIMAX_API_URL, headers=headers, json=payload, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()

        # Check for API-level errors
        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            raise RuntimeError(f"MiniMax API error: {base_resp}")

        content = data["choices"][0]["message"]["content"]

        # Strip <think>...</think> reasoning tags from M2.7 responses
        content = re.sub(r"<think>.*?</think>\s*", "", content, flags=re.DOTALL)

        return content
