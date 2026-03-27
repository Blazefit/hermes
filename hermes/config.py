"""Hermes configuration loader.

Reads hermes.yaml + .env to build a validated HermesConfig object
that every other module uses for business identity, categories,
email accounts, AI settings, and validation rules.
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULTS: Dict[str, Any] = {
    "business": {
        "name": "My Business",
        "owner_name": "Owner",
        "tagline": "",
        "timezone": "UTC",
    },
    "email": {
        "provider": "maton",
        "accounts": [],
        "reply_from": "",
    },
    "ai": {
        "primary_model": "anthropic",
        "classifier_model": "anthropic",
        "anthropic": {
            "generation_model": "claude-sonnet-4-6",
            "classifier_model": "claude-haiku-4-5-20251001",
            "max_tokens_generation": 1000,
            "max_tokens_classification": 256,
            "temperature_generation": 0.7,
            "temperature_classification": 0.1,
        },
        "minimax": {
            "model": "MiniMax-M2.7",
            "temperature_generation": 0.7,
            "temperature_classification": 0.1,
        },
        "openai": {
            "generation_model": "gpt-4o",
            "classifier_model": "gpt-4o-mini",
            "max_tokens_generation": 1000,
            "max_tokens_classification": 256,
            "temperature_generation": 0.7,
            "temperature_classification": 0.1,
        },
    },
    "processing": {
        "max_emails_per_cycle": 20,
        "classification_confidence_threshold": 0.8,
        "auto_send_confidence_threshold": 0.9,
        "stale_draft_hours": 48,
    },
    "validation": {
        "verified_facts": {},
        "banned_words": [],
        "financial_patterns": [
            r"\$\d+(?:\.\d{1,2})?",
            r"\b\d+\s*dollars?\b",
            r"\brefund\b",
            r"\bcredit\b",
            r"\bwaive\b",
            r"\bcomplimentary\b",
            r"\bfree\s+month\b",
            r"\bdiscount\s+\d+\s*%",
        ],
        "unauthorized_commitments": [
            r"\bI'?ll\s+refund\b",
            r"\bI'?ll\s+credit\b",
            r"\bI'?ll\s+waive\b",
            r"\bI'?ll\s+adjust\b",
        ],
        "valid_phone_patterns": [],
    },
    "scheduler": {
        "type": "launchd",
        "interval_minutes": 15,
        "label": "com.hermes.email-cycle",
    },
}


class HermesConfig:
    """Central configuration object for the Hermes pipeline.

    Loads hermes.yaml from the project root (or a custom path) and merges
    with environment variables from .env.  Provides typed properties for
    every config section plus a ``get_supabase()`` helper.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        project_root: Optional[str] = None,
    ):
        load_dotenv()

        if config_path:
            self._config_path = Path(config_path).resolve()
        else:
            self._config_path = self._find_config()

        if project_root:
            self._project_root = Path(project_root).resolve()
        elif self._config_path:
            self._project_root = self._config_path.parent
        else:
            self._project_root = Path.cwd()

        self._raw: Dict[str, Any] = {}
        if self._config_path and self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as fh:
                self._raw = yaml.safe_load(fh) or {}
            logger.info("Loaded config from %s", self._config_path)
        else:
            logger.warning("No hermes.yaml found. Using defaults.")

        self._validate()

    # ------------------------------------------------------------------
    # Config file discovery
    # ------------------------------------------------------------------

    @staticmethod
    def _find_config() -> Optional[Path]:
        """Walk up from cwd looking for hermes.yaml."""
        current = Path.cwd()
        for _ in range(10):
            candidate = current / "hermes.yaml"
            if candidate.exists():
                return candidate
            parent = current.parent
            if parent == current:
                break
            current = parent
        return None

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self) -> None:
        errors: List[str] = []

        biz = self._raw.get("business", {})
        if not biz.get("name"):
            logger.warning("business.name not set — using default")

        email_cfg = self._raw.get("email", {})
        accounts = email_cfg.get("accounts", [])
        if not accounts:
            logger.warning("No email accounts configured in hermes.yaml")

        reply_from = email_cfg.get("reply_from", "")
        account_addresses = {a.get("address", "") for a in accounts}
        if reply_from and reply_from not in account_addresses:
            errors.append(
                f"email.reply_from ({reply_from!r}) is not in the configured accounts"
            )

        if not os.environ.get("SUPABASE_URL"):
            logger.warning("SUPABASE_URL not set in environment")
        if not os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
            logger.warning("SUPABASE_SERVICE_ROLE_KEY not set in environment")

        if errors:
            for err in errors:
                logger.error("Config error: %s", err)
            raise ValueError(f"Configuration errors: {'; '.join(errors)}")

    # ------------------------------------------------------------------
    # Properties: business
    # ------------------------------------------------------------------

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def business_name(self) -> str:
        return self._raw.get("business", {}).get("name", _DEFAULTS["business"]["name"])

    @property
    def owner_name(self) -> str:
        return self._raw.get("business", {}).get(
            "owner_name", _DEFAULTS["business"]["owner_name"]
        )

    @property
    def tagline(self) -> str:
        return self._raw.get("business", {}).get("tagline", "")

    @property
    def timezone(self) -> str:
        return self._raw.get("business", {}).get(
            "timezone", _DEFAULTS["business"]["timezone"]
        )

    # ------------------------------------------------------------------
    # Properties: email
    # ------------------------------------------------------------------

    @property
    def email_provider_name(self) -> str:
        return self._raw.get("email", {}).get("provider", "maton")

    @property
    def email_accounts(self) -> List[Dict[str, Any]]:
        return self._raw.get("email", {}).get("accounts", [])

    @property
    def canonical_account(self) -> Optional[str]:
        for acct in self.email_accounts:
            if acct.get("canonical", False):
                return acct.get("address")
        if self.email_accounts:
            return self.email_accounts[0].get("address")
        return None

    @property
    def reply_from_account(self) -> str:
        return (
            self._raw.get("email", {}).get("reply_from", "")
            or self.canonical_account
            or ""
        )

    @property
    def account_connection_map(self) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for acct in self.email_accounts:
            addr = acct.get("address", "")
            conn_id = acct.get("connection_id", "")
            if addr and conn_id:
                result[addr] = conn_id
        return result

    # ------------------------------------------------------------------
    # Properties: categories
    # ------------------------------------------------------------------

    @property
    def categories(self) -> Dict[str, Dict[str, Any]]:
        cats = dict(self._raw.get("categories", {}))
        if "uncategorized" not in cats:
            cats["uncategorized"] = {
                "patterns": [],
                "auto_send": False,
                "auto_send_locked": True,
                "min_confidence": 0.9,
            }
        return cats

    @property
    def category_names(self) -> Set[str]:
        return set(self.categories.keys())

    @property
    def category_patterns(self) -> Dict[str, List[str]]:
        return {
            name: cfg.get("patterns", []) for name, cfg in self.categories.items()
        }

    def category_config(self, category: str) -> Dict[str, Any]:
        cats = self.categories
        cfg = cats.get(category, cats.get("uncategorized", {}))
        return {
            "auto_send": cfg.get("auto_send", False),
            "auto_send_locked": cfg.get("auto_send_locked", True),
            "min_confidence": cfg.get("min_confidence", 0.9),
        }

    # ------------------------------------------------------------------
    # Properties: AI
    # ------------------------------------------------------------------

    @property
    def ai_config(self) -> Dict[str, Any]:
        defaults = _DEFAULTS["ai"]
        raw = self._raw.get("ai", {})
        merged = {**defaults}
        for key in ("primary_model", "classifier_model"):
            if key in raw:
                merged[key] = raw[key]
        for provider in ("anthropic", "minimax", "openai"):
            if provider in raw:
                merged[provider] = {**defaults.get(provider, {}), **raw[provider]}
        return merged

    @property
    def primary_model(self) -> str:
        return self.ai_config.get("primary_model", "anthropic")

    @property
    def classifier_model(self) -> str:
        return self.ai_config.get("classifier_model", "anthropic")

    # ------------------------------------------------------------------
    # Properties: validation
    # ------------------------------------------------------------------

    @property
    def verified_facts(self) -> Dict[str, str]:
        return self._raw.get("validation", {}).get("verified_facts", {})

    @property
    def banned_words(self) -> List[str]:
        return self._raw.get("validation", {}).get(
            "banned_words", _DEFAULTS["validation"]["banned_words"]
        )

    @property
    def financial_patterns(self) -> List[str]:
        return self._raw.get("validation", {}).get(
            "financial_patterns", _DEFAULTS["validation"]["financial_patterns"]
        )

    @property
    def unauthorized_commitments(self) -> List[str]:
        return self._raw.get("validation", {}).get(
            "unauthorized_commitments",
            _DEFAULTS["validation"]["unauthorized_commitments"],
        )

    @property
    def valid_phone_patterns(self) -> List[str]:
        return self._raw.get("validation", {}).get("valid_phone_patterns", [])

    # ------------------------------------------------------------------
    # Properties: processing
    # ------------------------------------------------------------------

    @property
    def max_emails_per_cycle(self) -> int:
        return self._raw.get("processing", {}).get(
            "max_emails_per_cycle",
            _DEFAULTS["processing"]["max_emails_per_cycle"],
        )

    @property
    def classification_confidence_threshold(self) -> float:
        return self._raw.get("processing", {}).get(
            "classification_confidence_threshold",
            _DEFAULTS["processing"]["classification_confidence_threshold"],
        )

    @property
    def auto_send_confidence_threshold(self) -> float:
        return self._raw.get("processing", {}).get(
            "auto_send_confidence_threshold",
            _DEFAULTS["processing"]["auto_send_confidence_threshold"],
        )

    @property
    def stale_draft_hours(self) -> int:
        return self._raw.get("processing", {}).get(
            "stale_draft_hours",
            _DEFAULTS["processing"]["stale_draft_hours"],
        )

    # ------------------------------------------------------------------
    # Properties: brand voice & templates
    # ------------------------------------------------------------------

    @property
    def brand_voice_file(self) -> Path:
        relative = self._raw.get("brand_voice_file", "brand-voice.md")
        return self._project_root / relative

    @property
    def templates_dir(self) -> Path:
        relative = self._raw.get("templates_dir", "templates")
        return self._project_root / relative

    # ------------------------------------------------------------------
    # Properties: scheduler
    # ------------------------------------------------------------------

    @property
    def scheduler_config(self) -> Dict[str, Any]:
        return {**_DEFAULTS["scheduler"], **self._raw.get("scheduler", {})}

    # ------------------------------------------------------------------
    # Environment helpers
    # ------------------------------------------------------------------

    @property
    def maton_api_key(self) -> str:
        return os.environ.get("MATON_API_KEY", "")

    @property
    def anthropic_api_key(self) -> str:
        return os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def minimax_api_key(self) -> str:
        return os.environ.get("MINIMAX_API_KEY", "")

    @property
    def openai_api_key(self) -> str:
        return os.environ.get("OPENAI_API_KEY", "")

    @property
    def supabase_url(self) -> str:
        return os.environ.get("SUPABASE_URL", "")

    @property
    def supabase_service_key(self) -> str:
        return os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

    @property
    def notification_webhook_url(self) -> str:
        return os.environ.get("NOTIFICATION_WEBHOOK_URL", "")

    # ------------------------------------------------------------------
    # Supabase client
    # ------------------------------------------------------------------

    def get_supabase(self):
        """Create and return a Supabase client with service role credentials."""
        if not self.supabase_url or not self.supabase_service_key:
            raise ValueError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in environment"
            )
        from supabase import create_client

        return create_client(self.supabase_url, self.supabase_service_key)

    def __repr__(self) -> str:
        return (
            f"HermesConfig(business={self.business_name!r}, "
            f"accounts={len(self.email_accounts)}, "
            f"categories={list(self.category_names)})"
        )
