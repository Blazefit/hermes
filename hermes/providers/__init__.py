"""Hermes email and AI provider factories."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hermes.config import HermesConfig
    from hermes.providers.base import AIProvider, EmailProvider


def get_email_provider(config: "HermesConfig") -> "EmailProvider":
    """Instantiate the email provider specified in config.

    Args:
        config: HermesConfig instance.

    Returns:
        An EmailProvider implementation (currently MatonProvider).

    Raises:
        ValueError: If the provider name is not recognised.
    """
    name = config.email_provider_name.lower()
    if name == "maton":
        from hermes.providers.maton import MatonProvider

        return MatonProvider(config)
    raise ValueError(f"Unknown email provider: {name!r}")


def get_ai_provider(config: "HermesConfig", role: str = "generation") -> "AIProvider":
    """Instantiate the AI provider for a given role.

    Args:
        config: HermesConfig instance.
        role: ``"generation"`` for draft writing or ``"classifier"`` for
            classification / extraction (cheaper model).

    Returns:
        An AIProvider implementation.

    Raises:
        ValueError: If the provider name is not recognised.
    """
    ai = config.ai_config
    if role == "classifier":
        provider_name = ai.get("classifier_model", "anthropic")
    else:
        provider_name = ai.get("primary_model", "anthropic")

    provider_name = provider_name.lower()

    if provider_name == "anthropic":
        from hermes.providers.anthropic_ai import AnthropicProvider

        return AnthropicProvider(config, role=role)
    elif provider_name == "minimax":
        from hermes.providers.minimax_ai import MiniMaxProvider

        return MiniMaxProvider(config, role=role)
    elif provider_name == "openai":
        from hermes.providers.openai_ai import OpenAIProvider

        return OpenAIProvider(config, role=role)
    raise ValueError(f"Unknown AI provider: {provider_name!r}")
