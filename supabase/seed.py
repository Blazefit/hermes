"""Hermes database seeder.

Reads hermes.yaml, inserts hermes_config rows for each category,
and loads template anchor text from templates/{slug}.md into hermes_templates.
"""

from __future__ import annotations

import sys
from pathlib import Path


def seed(config_path: str = "hermes.yaml") -> None:
    """Seed the Hermes database from hermes.yaml and template files.

    Args:
        config_path: Path to hermes.yaml config file.
    """
    from hermes.config import HermesConfig

    cfg = HermesConfig(config_path=config_path)

    if not cfg.supabase_url or not cfg.supabase_service_key:
        print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        sys.exit(1)

    sb = cfg.get_supabase()
    tpl_dir = cfg.templates_dir

    print(f"Seeding Hermes database from: {config_path}")
    print(f"Supabase URL: {cfg.supabase_url}")
    print(f"Categories: {list(cfg.categories.keys())}")
    print(f"Templates dir: {tpl_dir}")
    print()

    # -----------------------------------------------------------------------
    # Seed hermes_config -- one row per category
    # -----------------------------------------------------------------------
    config_count = 0
    for slug, cat in cfg.categories.items():
        row = {
            "category": slug,
            "auto_send_enabled": cat.get("auto_send", False),
            "auto_send_locked": cat.get("auto_send_locked", False),
            "min_confidence_for_auto": cat.get("min_confidence", 0.9),
            "reply_from_account": cfg.reply_from_account,
        }
        try:
            sb.table("hermes_config").upsert(
                row, on_conflict="category"
            ).execute()
            config_count += 1
            auto_label = "auto-send ON" if cat.get("auto_send") else "manual"
            locked_label = " (LOCKED)" if cat.get("auto_send_locked") else ""
            print(f"  [config] {slug}: {auto_label}{locked_label}")
        except Exception as exc:
            print(f"  [config] ERROR inserting {slug}: {exc}")

    print(f"\nInserted/updated {config_count} hermes_config rows.")

    # -----------------------------------------------------------------------
    # Seed hermes_templates -- one row per category with anchor text from .md
    # -----------------------------------------------------------------------
    template_count = 0
    for slug in cfg.categories:
        template_file = tpl_dir / f"{slug}.md"
        if not template_file.exists():
            print(f"  [template] SKIP {slug} -- no file at {template_file}")
            continue

        anchor_text = template_file.read_text(encoding="utf-8").strip()
        if not anchor_text:
            print(f"  [template] SKIP {slug} -- empty template file")
            continue

        row = {
            "category": slug,
            "anchor_text": anchor_text,
        }
        try:
            sb.table("hermes_templates").upsert(
                row, on_conflict="category"
            ).execute()
            template_count += 1
            print(
                f"  [template] {slug}: "
                f"{len(anchor_text)} chars from {template_file.name}"
            )
        except Exception as exc:
            print(f"  [template] ERROR inserting {slug}: {exc}")

    print(f"\nInserted/updated {template_count} hermes_templates rows.")
    print("\nSeed complete.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "hermes.yaml"
    seed(path)
