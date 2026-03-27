"""Hermes interactive setup wizard.

Walks the user through configuring Hermes from scratch:
  1. Business identity
  2. Email accounts
  3. Email provider (Maton / OAuth)
  4. Categories
  5. AI provider
  6. Supabase credentials
  7. Brand voice (optional)
  8. Write config files
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
import yaml


# ---------------------------------------------------------------------------
# Default categories
# ---------------------------------------------------------------------------

DEFAULT_CATEGORIES: Dict[str, Dict[str, Any]] = {
    "inquiry": {
        "display_name": "General Inquiry",
        "patterns": ["question", "info", "information", "interested", "learn more"],
        "auto_send": False,
        "auto_send_locked": False,
        "min_confidence": 0.9,
    },
    "booking": {
        "display_name": "Booking / Appointment",
        "patterns": ["book", "schedule", "appointment", "reserve", "sign up"],
        "auto_send": False,
        "auto_send_locked": False,
        "min_confidence": 0.9,
    },
    "billing": {
        "display_name": "Billing & Payments",
        "patterns": ["bill", "charge", "payment", "invoice", "refund", "receipt"],
        "auto_send": False,
        "auto_send_locked": True,
        "min_confidence": 0.9,
    },
    "support": {
        "display_name": "Support / Help",
        "patterns": ["help", "issue", "problem", "broken", "not working", "support"],
        "auto_send": False,
        "auto_send_locked": False,
        "min_confidence": 0.9,
    },
    "uncategorized": {
        "display_name": "Uncategorized",
        "patterns": [],
        "auto_send": False,
        "auto_send_locked": True,
        "min_confidence": 0.9,
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _prompt(label: str, default: str = "", required: bool = False) -> str:
    """Prompt user for input with optional default."""
    suffix = f" [{default}]" if default else ""
    while True:
        value = click.prompt(f"  {label}{suffix}", default=default, show_default=False)
        value = value.strip()
        if value or not required:
            return value
        click.echo("    This field is required.")


def _prompt_choice(label: str, choices: List[str]) -> str:
    """Show numbered choices and return selection."""
    for i, c in enumerate(choices, 1):
        click.echo(f"    [{i}] {c}")
    while True:
        raw = click.prompt(f"  {label}", type=str)
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(choices):
                return choices[idx]
        except ValueError:
            pass
        click.echo(f"    Please enter a number 1-{len(choices)}")


def _prompt_yes_no(label: str, default: bool = False) -> bool:
    """Ask a yes/no question."""
    suffix = " [Y/n]" if default else " [y/N]"
    raw = click.prompt(
        f"  {label}{suffix}", default="y" if default else "n", show_default=False
    )
    return raw.strip().lower() in ("y", "yes", "true", "1")


def _slugify(text: str) -> str:
    """Convert a string to a URL/config-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


# ---------------------------------------------------------------------------
# Wizard steps
# ---------------------------------------------------------------------------

def _step_business() -> Dict[str, Any]:
    """Step 1: Business Identity."""
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 1: Business Identity")
    click.echo("=" * 60)

    name = _prompt("Business name", required=True)
    owner = _prompt("Owner / operator name", required=True)
    location = _prompt("Location (city, state)")
    website = _prompt("Website URL")
    tagline = _prompt("Tagline / motto (optional)")
    timezone = _prompt("Timezone", default="America/New_York")
    phones_raw = _prompt("Phone number(s) (comma-separated)")
    phones = [p.strip() for p in phones_raw.split(",") if p.strip()] if phones_raw else []

    return {
        "name": name,
        "owner_name": owner,
        "location": location,
        "website": website,
        "tagline": tagline,
        "timezone": timezone,
        "phone_numbers": phones,
    }


def _step_accounts() -> Tuple[List[Dict], str]:
    """Step 2: Email Accounts."""
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 2: Email Accounts")
    click.echo("=" * 60)

    count_raw = _prompt("How many email accounts? (1-5)", default="1")
    try:
        count = max(1, min(5, int(count_raw)))
    except ValueError:
        count = 1

    accounts: List[Dict] = []
    for i in range(count):
        click.echo(f"\n  Account {i + 1}:")
        address = _prompt("Email address", required=True)
        role = "primary" if i == 0 else "secondary"
        if count > 1:
            role = _prompt("Role (primary/secondary)", default=role)
        canonical = i == 0
        accounts.append({
            "address": address,
            "role": role,
            "canonical": canonical,
        })

    # Default reply-from
    addresses = [a["address"] for a in accounts]
    if len(addresses) == 1:
        default_reply = addresses[0]
        click.echo(f"\n  Default reply-from: {default_reply}")
    else:
        click.echo("\n  Which account should replies be sent from?")
        default_reply = _prompt_choice("Select", addresses)

    return accounts, default_reply


def _step_email_provider(accounts: List[Dict]) -> Tuple[Dict, Dict[str, str]]:
    """Step 3: Email Provider configuration.

    Returns:
        (provider_name str wrapped in dict, env_vars dict)
    """
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 3: Email Provider")
    click.echo("=" * 60)

    choice = _prompt_choice("How do you connect to Gmail?", [
        "Gmail via Maton (recommended)",
        "Gmail via OAuth (direct)",
    ])

    env_vars: Dict[str, str] = {}
    provider_name = "maton"

    if "Maton" in choice:
        provider_name = "maton"
        api_key = _prompt("Maton API key", required=True)
        env_vars["MATON_API_KEY"] = api_key

        click.echo("\n  For each account, enter the Maton connection ID.")
        click.echo("  (Find this at https://ctrl.maton.ai/connections)")
        for acct in accounts:
            conn_id = _prompt(f"Connection ID for {acct['address']}")
            acct["connection_id"] = conn_id
    else:
        provider_name = "oauth"
        click.echo("\n  OAuth requires client credentials from Google Cloud Console.")
        client_id = _prompt("Google Client ID")
        client_secret = _prompt("Google Client Secret")
        if client_id:
            env_vars["GOOGLE_CLIENT_ID"] = client_id
        if client_secret:
            env_vars["GOOGLE_CLIENT_SECRET"] = client_secret
        click.echo("\n  After setup, run 'hermes oauth <account>' for each account.")

    return {"provider": provider_name}, env_vars


def _step_categories() -> Dict[str, Dict[str, Any]]:
    """Step 4: Categories."""
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 4: Email Categories")
    click.echo("=" * 60)

    click.echo("\n  Default categories:")
    for slug, cat in DEFAULT_CATEGORIES.items():
        click.echo(f"    - {slug}: {cat['display_name']}")

    customize = _prompt_yes_no("Customize categories?", default=False)

    if not customize:
        return dict(DEFAULT_CATEGORIES)

    categories = dict(DEFAULT_CATEGORIES)

    while True:
        click.echo("\n  Current categories:")
        slugs = list(categories.keys())
        for i, slug in enumerate(slugs, 1):
            cat = categories[slug]
            click.echo(f"    [{i}] {slug}: {cat.get('display_name', slug)}")

        action = _prompt_choice(
            "Action", ["Add category", "Remove category", "Edit category", "Done"]
        )

        if action == "Done":
            break

        elif action == "Add category":
            name = _prompt("Category display name", required=True)
            slug = _slugify(name)
            patterns_raw = _prompt("Keywords/patterns (comma-separated)")
            patterns = (
                [p.strip() for p in patterns_raw.split(",") if p.strip()]
                if patterns_raw else []
            )
            auto_send = _prompt_yes_no("Enable auto-send?", default=False)
            categories[slug] = {
                "display_name": name,
                "patterns": patterns,
                "auto_send": auto_send,
                "auto_send_locked": False,
                "min_confidence": 0.9,
            }
            click.echo(f"    Added: {slug}")

        elif action == "Remove category":
            removable = [s for s in slugs if s != "uncategorized"]
            if not removable:
                click.echo("    No categories to remove.")
                continue
            slug = _prompt_choice("Remove which?", removable)
            del categories[slug]
            click.echo(f"    Removed: {slug}")

        elif action == "Edit category":
            slug = _prompt_choice("Edit which?", slugs)
            cat = categories[slug]
            click.echo(f"    Editing: {slug} ({cat.get('display_name', slug)})")
            new_name = _prompt("Display name", default=cat.get("display_name", slug))
            patterns_str = ", ".join(cat.get("patterns", []))
            new_patterns_raw = _prompt("Keywords/patterns", default=patterns_str)
            new_patterns = [
                p.strip() for p in new_patterns_raw.split(",") if p.strip()
            ]
            new_auto = _prompt_yes_no(
                "Enable auto-send?", default=cat.get("auto_send", False)
            )
            categories[slug] = {
                "display_name": new_name,
                "patterns": new_patterns,
                "auto_send": new_auto,
                "auto_send_locked": cat.get("auto_send_locked", False),
                "min_confidence": cat.get("min_confidence", 0.9),
            }

    # Ensure uncategorized always exists
    if "uncategorized" not in categories:
        categories["uncategorized"] = DEFAULT_CATEGORIES["uncategorized"]

    return categories


def _step_ai_provider() -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Step 5: AI Provider.

    Returns:
        (ai_config dict, env_vars dict)
    """
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 5: AI Provider")
    click.echo("=" * 60)

    choice = _prompt_choice("Primary AI provider", [
        "Anthropic (Claude)",
        "OpenAI (GPT)",
        "MiniMax",
    ])

    provider_map = {
        "Anthropic (Claude)": ("anthropic", "ANTHROPIC_API_KEY"),
        "OpenAI (GPT)": ("openai", "OPENAI_API_KEY"),
        "MiniMax": ("minimax", "MINIMAX_API_KEY"),
    }
    provider_name, env_key = provider_map[choice]

    api_key = _prompt(f"{choice} API key", required=True)
    env_vars = {env_key: api_key}
    ai_config: Dict[str, Any] = {"primary_model": provider_name}

    # Optional fallback
    if _prompt_yes_no("Add a fallback AI provider?", default=False):
        remaining = [k for k in provider_map if k != choice]
        fb_choice = _prompt_choice("Fallback provider", remaining)
        fb_name, fb_key = provider_map[fb_choice]
        fb_api_key = _prompt(f"{fb_choice} API key")
        if fb_api_key:
            env_vars[fb_key] = fb_api_key
        ai_config["classifier_model"] = fb_name

    return ai_config, env_vars


def _step_supabase() -> Tuple[str, str]:
    """Step 6: Supabase credentials."""
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 6: Supabase")
    click.echo("=" * 60)

    click.echo("  Find these in your Supabase project Settings > API.")
    url = _prompt("Supabase URL", required=True)
    key = _prompt("Supabase service role key", required=True)
    return url, key


def _step_brand_voice(business: Dict) -> Optional[str]:
    """Step 7: Brand Voice (optional).

    Returns:
        Brand voice markdown string, or None if skipped.
    """
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 7: Brand Voice (optional)")
    click.echo("=" * 60)

    if not _prompt_yes_no("Generate a starter brand voice document?", default=True):
        return None

    tone = _prompt_choice("Communication tone", [
        "Formal & professional",
        "Casual & friendly",
        "Warm & personal",
    ])
    industry = _prompt("Industry / business type", default="")
    always_raw = _prompt("Things to always mention (comma-separated)")
    always = (
        [a.strip() for a in always_raw.split(",") if a.strip()] if always_raw else []
    )
    never_raw = _prompt("Things to never say (comma-separated)")
    never = (
        [n.strip() for n in never_raw.split(",") if n.strip()] if never_raw else []
    )

    from hermes.wizard.brand_voice import generate_brand_voice

    tone_keyword = {
        "Formal & professional": "formal",
        "Casual & friendly": "casual",
        "Warm & personal": "friendly",
    }.get(tone, "friendly")

    return generate_brand_voice(
        business_name=business.get("name", ""),
        owner_name=business.get("owner_name", ""),
        location=business.get("location", ""),
        website=business.get("website", ""),
        phone=", ".join(business.get("phone_numbers", [])),
        tone=tone_keyword,
        industry=industry,
        always_mention=always,
        never_say=never,
    )


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_hermes_yaml(
    output_dir: Path,
    business: Dict,
    accounts: List[Dict],
    default_reply: str,
    email_provider: Dict,
    categories: Dict,
    ai_config: Dict,
    supabase_url: str,
) -> Path:
    """Write hermes.yaml in the canonical config format."""
    config: Dict[str, Any] = {
        "business": {
            "name": business.get("name", ""),
            "owner_name": business.get("owner_name", ""),
            "tagline": business.get("tagline", ""),
            "timezone": business.get("timezone", "UTC"),
        },
        "email": {
            "provider": email_provider.get("provider", "maton"),
            "accounts": accounts,
            "reply_from": default_reply,
        },
        "categories": categories,
        "ai": ai_config,
        "supabase": {"url": supabase_url},
        "brand_voice_file": "brand-voice.md",
        "templates_dir": "templates",
        "processing": {
            "max_emails_per_cycle": 20,
            "stale_draft_hours": 48,
            "classification_confidence_threshold": 0.8,
            "auto_send_confidence_threshold": 0.9,
        },
        "validation": {
            "verified_facts": {},
            "banned_words": [],
        },
    }

    # Add optional business fields
    if business.get("location"):
        config["business"]["location"] = business["location"]
    if business.get("website"):
        config["business"]["website"] = business["website"]
    if business.get("phone_numbers"):
        config["business"]["phone_numbers"] = business["phone_numbers"]

    path = output_dir / "hermes.yaml"
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            config, f, default_flow_style=False, sort_keys=False, allow_unicode=True
        )
    return path


def _write_dotenv(output_dir: Path, env_vars: Dict[str, str]) -> Path:
    """Write .env file with API keys."""
    path = output_dir / ".env"
    lines = []
    for key, value in env_vars.items():
        # Escape any single quotes in values
        escaped = value.replace("'", "'\\''")
        lines.append(f"{key}='{escaped}'")

    with open(path, "w", encoding="utf-8") as f:
        f.write("# Hermes Email System -- environment variables\n")
        f.write("# Generated by hermes setup\n\n")
        f.write("\n".join(lines))
        f.write("\n")

    return path


def _write_templates(
    output_dir: Path, business: Dict, categories: Dict
) -> List[Path]:
    """Generate template .md files for each category."""
    from hermes.wizard.templates import generate_category_template

    templates_dir = output_dir / "templates"
    templates_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for slug, cat in categories.items():
        content = generate_category_template(
            business_name=business.get("name", ""),
            owner_name=business.get("owner_name", ""),
            category_slug=slug,
            category_display=cat.get("display_name", slug),
        )
        path = templates_dir / f"{slug}.md"
        path.write_text(content, encoding="utf-8")
        written.append(path)

    return written


# ---------------------------------------------------------------------------
# Main wizard
# ---------------------------------------------------------------------------

def run_setup_wizard(config_path: str = "hermes.yaml") -> None:
    """Run the full interactive setup wizard.

    Args:
        config_path: Where to write hermes.yaml (also determines the
                     output directory for .env, templates, etc.).
    """
    click.echo("\n" + "#" * 60)
    click.echo("  HERMES EMAIL SETUP WIZARD")
    click.echo("#" * 60)
    click.echo("\n  This wizard will walk you through setting up Hermes.")
    click.echo("  Press Ctrl+C at any time to abort.\n")

    output_dir = Path(config_path).resolve().parent

    # Step 1: Business
    business = _step_business()

    # Step 2: Email accounts
    accounts, default_reply = _step_accounts()

    # Step 3: Email provider
    email_provider, provider_env = _step_email_provider(accounts)

    # Step 4: Categories
    categories = _step_categories()

    # Step 5: AI provider
    ai_config, ai_env = _step_ai_provider()

    # Step 6: Supabase
    supabase_url, supabase_key = _step_supabase()

    # Step 7: Brand voice
    brand_voice = _step_brand_voice(business)

    # Merge env vars
    env_vars: Dict[str, str] = {}
    env_vars.update(provider_env)
    env_vars.update(ai_env)
    env_vars["SUPABASE_URL"] = supabase_url
    env_vars["SUPABASE_SERVICE_ROLE_KEY"] = supabase_key

    # Step 8: Confirm and write
    click.echo("\n" + "=" * 60)
    click.echo("  STEP 8: Confirm & Write")
    click.echo("=" * 60)

    click.echo(f"\n  Business:     {business['name']}")
    click.echo(f"  Owner:        {business['owner_name']}")
    click.echo(
        f"  Accounts:     {', '.join(a['address'] for a in accounts)}"
    )
    click.echo(f"  Reply-from:   {default_reply}")
    click.echo(f"  Provider:     {email_provider.get('provider', '?')}")
    click.echo(f"  AI:           {ai_config.get('primary_model', '?')}")
    click.echo(f"  Categories:   {', '.join(categories.keys())}")
    click.echo(f"  Supabase:     {supabase_url}")
    click.echo(f"  Brand voice:  {'yes' if brand_voice else 'no'}")
    click.echo(f"\n  Output dir:   {output_dir}")

    if not _prompt_yes_no("\nProceed?", default=True):
        click.echo("Aborted.")
        return

    # Write files
    output_dir.mkdir(parents=True, exist_ok=True)

    yaml_path = _write_hermes_yaml(
        output_dir, business, accounts, default_reply,
        email_provider, categories, ai_config, supabase_url,
    )
    click.echo(f"\n  Wrote: {yaml_path}")

    env_path = _write_dotenv(output_dir, env_vars)
    click.echo(f"  Wrote: {env_path}")

    template_paths = _write_templates(output_dir, business, categories)
    for tp in template_paths:
        click.echo(f"  Wrote: {tp}")

    if brand_voice:
        bv_path = output_dir / "brand-voice.md"
        bv_path.write_text(brand_voice, encoding="utf-8")
        click.echo(f"  Wrote: {bv_path}")

    # Next steps
    click.echo("\n" + "=" * 60)
    click.echo("  SETUP COMPLETE")
    click.echo("=" * 60)
    click.echo(f"""
  Next steps:

  1. Review and customize your template files in templates/
  2. Edit brand-voice.md to refine your communication style
  3. Run migrations:     hermes migrate
  4. Seed the database:  hermes seed
  5. Test a cycle:       hermes cycle
  6. Install the skill:  hermes install-skill

  Configuration: {yaml_path}
  Environment:   {env_path}
""")
