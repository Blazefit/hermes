"""Hermes Email CLI.

Commands:
    setup       — Interactive setup wizard
    cycle       — Run one email processing cycle
    status      — Show system status and draft counts
    train       — Pull historical emails and build voice samples
    drafts      — List pending drafts
    migrate     — Show migration instructions
    seed        — Seed database from hermes.yaml
    install-skill — Install the Claude Code skill
"""

import json
import logging
import sys

import click

from hermes import __version__


def _load_config():
    """Lazy-load config to avoid import errors before setup."""
    from hermes.config import HermesConfig
    return HermesConfig()


@click.group()
@click.version_option(__version__, prog_name="hermes")
def main():
    """Hermes Email — AI-powered email automation pipeline."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------

@main.command()
def setup():
    """Run the interactive setup wizard."""
    from hermes.wizard.setup import run_setup_wizard
    run_setup_wizard()


# ---------------------------------------------------------------------------
# cycle
# ---------------------------------------------------------------------------

@main.command()
@click.option("--dry-run", is_flag=True, help="Fetch and classify only — no generation or sending.")
def cycle(dry_run):
    """Run one email processing cycle."""
    config = _load_config()

    if dry_run:
        click.echo("Dry run mode: fetch + classify only")
        from hermes.providers import get_email_provider, get_ai_provider
        from hermes.pipeline.fetch import fetch_new_emails
        from hermes.pipeline.classify import classify_email

        email_provider = get_email_provider(config)
        cls_provider = get_ai_provider(config, role="classifier")

        emails = fetch_new_emails(config, email_provider)
        click.echo(f"Fetched {len(emails)} new emails")

        for email in emails[:config.max_emails_per_cycle]:
            result = classify_email(
                email.get("subject", ""),
                email.get("body", ""),
                config, cls_provider,
            )
            click.echo(
                f"  [{result['category']}] "
                f"confidence={result['confidence']:.2f} "
                f"method={result['method']} "
                f"subject={email.get('subject', '')[:60]}"
            )
        return

    from hermes.pipeline.cycle import run_cycle

    result = run_cycle(config)
    click.echo(json.dumps(result, indent=2, default=str))

    if result.get("status") == "error":
        sys.exit(1)


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

@main.command()
@click.option("--hours", default=24, help="Look back N hours for stats.")
def status(hours):
    """Show system status and draft counts."""
    config = _load_config()
    sb = config.get_supabase()

    click.echo(f"Hermes Email v{__version__}")
    click.echo(f"Business: {config.business_name}")
    click.echo(f"Accounts: {[a.get('address') for a in config.email_accounts]}")
    click.echo(f"Categories: {sorted(config.category_names)}")
    click.echo()

    try:
        stats = sb.rpc("hermes_cycle_stats", {"hours_back": hours}).execute()
        if stats.data:
            row = stats.data[0] if isinstance(stats.data, list) else stats.data
            click.echo(f"Draft stats (last {hours}h):")
            click.echo(f"  Total:          {row.get('total_drafts', 0)}")
            click.echo(f"  Pending review: {row.get('pending_review', 0)}")
            click.echo(f"  Auto-sent:      {row.get('auto_sent', 0)}")
            click.echo(f"  Manually sent:  {row.get('manually_sent', 0)}")
            click.echo(f"  Flagged:        {row.get('flagged', 0)}")
            click.echo(f"  Stale:          {row.get('stale', 0)}")
    except Exception as exc:
        click.echo(f"Could not fetch stats: {exc}")

    try:
        cfg_resp = (
            sb.table("hermes_config")
            .select("category, auto_send_enabled, last_processed_at")
            .execute()
        )
        if cfg_resp.data:
            click.echo()
            click.echo("Category config:")
            for row in cfg_resp.data:
                auto = "ON" if row.get("auto_send_enabled") else "off"
                last = row.get("last_processed_at", "never")
                click.echo(
                    f"  {row['category']:20s}  auto_send={auto:3s}  last_run={last}"
                )
    except Exception as exc:
        click.echo(f"Could not fetch config: {exc}")


# ---------------------------------------------------------------------------
# train
# ---------------------------------------------------------------------------

@main.command()
@click.option("--days", default=90, help="Days back to search for training data.")
def train(days):
    """Pull historical sent emails and build voice samples."""
    config = _load_config()
    from hermes.providers import get_email_provider

    email_provider = get_email_provider(config)
    sb = config.get_supabase()

    click.echo(f"Training pipeline (last {days} days)...")

    for category, cat_cfg in config.categories.items():
        patterns = cat_cfg.get("patterns", [])
        if not patterns:
            continue

        pattern_terms = " OR ".join(
            p.replace("\\s+", " ").replace("\\s", " ").replace("\\b", "")
            for p in patterns[:5]
        )
        query = f"subject:({pattern_terms}) in:sent newer_than:{days}d"

        click.echo(f"  Searching {category}...")
        samples = []
        for acct in config.email_accounts:
            address = acct.get("address", "")
            try:
                messages = email_provider.fetch_messages(
                    address, max_results=50, query=query
                )
                for msg in messages:
                    body = (msg.get("body") or "").strip()
                    if 50 <= len(body) <= 3000:
                        samples.append(body)
            except Exception as exc:
                click.echo(f"    Warning: {address}: {exc}")

        kept = samples[:10]
        click.echo(f"    Found {len(samples)} samples, keeping {len(kept)}")

        if kept:
            try:
                sb.table("hermes_templates").update(
                    {"voice_samples": kept}
                ).eq("category", category).execute()
            except Exception as exc:
                click.echo(f"    Error saving: {exc}")

    from datetime import datetime, timezone

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        sb.table("hermes_config").update(
            {"last_trained_at": now_iso}
        ).neq("id", "").execute()
    except Exception:
        pass

    click.echo("Training complete.")


# ---------------------------------------------------------------------------
# drafts
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--status-filter", "status_filter", default="pending_review",
    help="Filter by status (pending_review, sent, auto_sent, stale, all).",
)
@click.option("--limit", default=20, help="Max drafts to show.")
def drafts(status_filter, limit):
    """List drafts from the database."""
    config = _load_config()
    sb = config.get_supabase()

    query = (
        sb.table("hermes_drafts")
        .select(
            "id, sender_email, sender_name, subject, category, status, "
            "classification_confidence, created_at"
        )
        .order("created_at", desc=True)
        .limit(limit)
    )

    if status_filter != "all":
        query = query.eq("status", status_filter)

    resp = query.execute()
    rows = resp.data or []

    if not rows:
        click.echo(f"No drafts found (status={status_filter})")
        return

    click.echo(f"Drafts ({status_filter}, showing {len(rows)}):\n")
    for row in rows:
        conf = row.get("classification_confidence") or 0.0
        name_or_email = (row.get("sender_name") or row.get("sender_email", ""))[:25]
        subj = (row.get("subject") or "")[:40]
        click.echo(
            f"  [{row['status']:15s}] {row['category']:15s} "
            f"conf={conf:.2f}  {name_or_email:25s}  {subj}"
        )
        click.echo(f"    id={row['id']}  created={row.get('created_at', '')}")


# ---------------------------------------------------------------------------
# migrate
# ---------------------------------------------------------------------------

@main.command()
def migrate():
    """Show database migration instructions."""
    click.echo("Hermes Database Migrations")
    click.echo("=" * 40)
    click.echo()
    click.echo("Run these SQL files in order against your Supabase database:")
    click.echo()
    click.echo("  1. supabase/migrations/001_hermes_tables.sql")
    click.echo("  2. supabase/migrations/002_hermes_rls.sql")
    click.echo("  3. supabase/migrations/003_hermes_functions.sql")
    click.echo("  4. supabase/migrations/004_hermes_blacklist.sql")
    click.echo()
    click.echo("After migrations, run: hermes seed")


# ---------------------------------------------------------------------------
# seed
# ---------------------------------------------------------------------------

@main.command()
def seed():
    """Seed the database from hermes.yaml."""
    config = _load_config()

    # Import from the supabase/seed.py module
    import importlib.util
    from pathlib import Path

    seed_path = config.project_root / "supabase" / "seed.py"
    if not seed_path.exists():
        click.echo(f"Seed script not found: {seed_path}")
        sys.exit(1)

    spec = importlib.util.spec_from_file_location("seed_module", seed_path)
    seed_mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed_mod)

    click.echo(f"Seeding database for {config.business_name}...")
    counts = seed_mod.seed_config(config)
    click.echo(f"  Config rows:   {counts['upserted_config']}")
    click.echo(f"  Template rows: {counts['upserted_templates']}")
    click.echo("Done.")


# ---------------------------------------------------------------------------
# install-skill
# ---------------------------------------------------------------------------

@main.command("install-skill")
@click.option("--target", default=None, help="Target directory for skill files.")
def install_skill(target):
    """Install the Hermes Claude Code skill."""
    import shutil
    from pathlib import Path

    if target:
        target_dir = Path(target)
    else:
        target_dir = Path.home() / ".claude" / "skills" / "hermes"

    target_dir.mkdir(parents=True, exist_ok=True)

    skill_src = Path(__file__).parent.parent / "skill"
    if not skill_src.exists():
        click.echo(f"Skill source directory not found: {skill_src}")
        sys.exit(1)

    for src_file in skill_src.iterdir():
        if src_file.is_file():
            dest = target_dir / src_file.name
            shutil.copy2(src_file, dest)
            click.echo(f"  Copied {src_file.name} -> {dest}")

    click.echo(f"\nSkill installed to {target_dir}")


if __name__ == "__main__":
    main()
