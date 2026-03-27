#!/usr/bin/env python3
"""Dynamic seeder for Hermes.

Reads hermes.yaml and inserts config and template rows into Supabase
so the database matches the YAML configuration.

Usage:
    python -m supabase.seed                # from project root
    hermes seed                            # via CLI
"""

import logging
import sys

from hermes.config import HermesConfig

logger = logging.getLogger(__name__)


def seed_config(config: HermesConfig) -> dict:
    """Insert or update hermes_config and hermes_templates rows.

    Args:
        config: Loaded HermesConfig.

    Returns:
        Dict with counts: {upserted_config, upserted_templates}.
    """
    sb = config.get_supabase()
    counts = {"upserted_config": 0, "upserted_templates": 0}

    # Seed hermes_config — one row per category
    for name, cat_cfg in config.categories.items():
        row = {
            "category": name,
            "auto_send_enabled": cat_cfg.get("auto_send", False),
            "auto_send_locked": cat_cfg.get("auto_send_locked", False),
            "min_confidence_for_auto": cat_cfg.get("min_confidence", 0.9),
            "reply_from_account": config.reply_from_account,
        }
        try:
            sb.table("hermes_config").upsert(row, on_conflict="category").execute()
            counts["upserted_config"] += 1
            logger.info("Seeded config for category: %s", name)
        except Exception as exc:
            logger.error("Failed to seed config for %s: %s", name, exc)

    # Seed hermes_templates — one row per category with anchor text from file
    templates_dir = config.templates_dir
    for name in config.categories:
        template_file = templates_dir / f"{name}.md"
        anchor_text = ""
        if template_file.exists():
            try:
                anchor_text = template_file.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("Failed to read template %s: %s", template_file, exc)

        if not anchor_text:
            anchor_text = f"Default template for {name.replace('_', ' ')} emails."

        row = {
            "category": name,
            "anchor_text": anchor_text,
        }
        try:
            sb.table("hermes_templates").upsert(
                row, on_conflict="category"
            ).execute()
            counts["upserted_templates"] += 1
            logger.info("Seeded template for category: %s", name)
        except Exception as exc:
            logger.error("Failed to seed template for %s: %s", name, exc)

    return counts


def main():
    """CLI entry point for seeding."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    try:
        config = HermesConfig()
    except Exception as exc:
        print(f"Error loading config: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"Seeding database for {config.business_name}...")
    print(f"Categories: {sorted(config.category_names)}")

    counts = seed_config(config)

    print(f"\nDone:")
    print(f"  Config rows upserted:   {counts['upserted_config']}")
    print(f"  Template rows upserted: {counts['upserted_templates']}")


if __name__ == "__main__":
    main()
