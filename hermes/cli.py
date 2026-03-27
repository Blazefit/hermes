"""Hermes CLI -- command-line interface for the Hermes email system.

Usage:
    hermes setup          Interactive setup wizard
    hermes cycle          Run one email processing cycle
    hermes status         Show inbox counts per account
    hermes train          Run voice sample training
    hermes drafts         List pending drafts
    hermes migrate        Run SQL migrations against Supabase
    hermes seed           Seed database from config + templates
    hermes install-skill  Install the Claude Code skill file
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import click
from dotenv import load_dotenv


def _load_config(config_path: str):
    """Load HermesConfig, handling missing file gracefully."""
    from hermes.config import HermesConfig

    try:
        return HermesConfig(config_path=config_path)
    except FileNotFoundError:
        click.echo(f"Config file not found: {config_path}")
        click.echo("Run 'hermes setup' to create one.")
        sys.exit(1)
    except ValueError as exc:
        click.echo(f"Config error: {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.option(
    "--config", "-c",
    default="hermes.yaml",
    envvar="HERMES_CONFIG",
    help="Path to hermes.yaml (default: ./hermes.yaml)",
)
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """Hermes -- AI-powered email processing system."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


# ---------------------------------------------------------------------------
# hermes setup
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def setup(ctx: click.Context) -> None:
    """Run the interactive setup wizard."""
    from hermes.wizard.setup import run_setup_wizard

    run_setup_wizard(ctx.obj["config_path"])


# ---------------------------------------------------------------------------
# hermes cycle
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def cycle(ctx: click.Context) -> None:
    """Run one email processing cycle (fetch + classify + draft)."""
    config_path = ctx.obj["config_path"]

    try:
        from hermes.pipeline.cycle import run_cycle
    except ImportError:
        click.echo("ERROR: hermes.pipeline.cycle not yet implemented.")
        click.echo("The processing pipeline module is required for this command.")
        sys.exit(1)

    click.echo("Starting processing cycle...")
    result = run_cycle(config_path=config_path)
    click.echo(json.dumps(result, indent=2, default=str))
    if result.get("status") == "error":
        sys.exit(1)


# ---------------------------------------------------------------------------
# hermes status
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show inbox status -- draft counts by status and category."""
    config_path = ctx.obj["config_path"]
    cfg = _load_config(config_path)
    sb = cfg.get_supabase()

    click.echo("Hermes Status")
    click.echo("=" * 50)

    # Draft counts by status
    click.echo("\nDrafts by status:")
    for status_val in [
        "pending_review", "approved", "sent", "auto_sent", "discarded", "stale"
    ]:
        try:
            resp = (
                sb.table("hermes_drafts")
                .select("id", count="exact")
                .eq("status", status_val)
                .execute()
            )
            count = resp.count if resp.count is not None else len(resp.data or [])
            if count > 0:
                click.echo(f"  {status_val:20s}  {count}")
        except Exception as exc:
            click.echo(f"  {status_val:20s}  ERROR: {exc}")

    # Draft counts by category
    click.echo("\nDrafts by category (pending_review):")
    for slug in cfg.categories:
        try:
            resp = (
                sb.table("hermes_drafts")
                .select("id", count="exact")
                .eq("status", "pending_review")
                .eq("category", slug)
                .execute()
            )
            count = resp.count if resp.count is not None else len(resp.data or [])
            if count > 0:
                click.echo(f"  {slug:20s}  {count}")
        except Exception as exc:
            click.echo(f"  {slug:20s}  ERROR: {exc}")

    # Config last processed
    click.echo("\nLast processed:")
    try:
        resp = (
            sb.table("hermes_config")
            .select("category, last_processed_at, auto_send_enabled")
            .execute()
        )
        for row in resp.data or []:
            cat = row.get("category", "?")
            lp = row.get("last_processed_at", "never")
            auto = "auto" if row.get("auto_send_enabled") else "manual"
            click.echo(f"  {cat:20s}  {lp or 'never':30s}  [{auto}]")
    except Exception as exc:
        click.echo(f"  ERROR: {exc}")

    # Email accounts
    click.echo(f"\nAccounts: {len(cfg.email_accounts)}")
    for acct in cfg.email_accounts:
        addr = acct.get("address", "?")
        role = acct.get("role", "?")
        click.echo(f"  {addr} ({role})")

    click.echo(f"\nReply-from: {cfg.reply_from_account}")


# ---------------------------------------------------------------------------
# hermes train
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def train(ctx: click.Context) -> None:
    """Run voice sample training from sent email history."""
    config_path = ctx.obj["config_path"]

    try:
        from hermes.pipeline.train import run_training
    except ImportError:
        click.echo("ERROR: hermes.pipeline.train not yet implemented.")
        sys.exit(1)

    click.echo("Starting voice training...")
    result = run_training(config_path=config_path)
    click.echo(json.dumps(result, indent=2, default=str))


# ---------------------------------------------------------------------------
# hermes drafts
# ---------------------------------------------------------------------------

@cli.command()
@click.option(
    "--status", "-s",
    "draft_status",
    default="pending_review",
    help="Filter by draft status (default: pending_review)",
)
@click.option("--limit", "-n", default=20, help="Max drafts to show (default: 20)")
@click.pass_context
def drafts(ctx: click.Context, draft_status: str, limit: int) -> None:
    """List drafts from Supabase, filtered by status."""
    config_path = ctx.obj["config_path"]
    cfg = _load_config(config_path)
    sb = cfg.get_supabase()

    try:
        query = (
            sb.table("hermes_drafts")
            .select(
                "id, sender_email, sender_name, subject, category, "
                "classification_confidence, status, created_at"
            )
            .eq("status", draft_status)
            .order("created_at", desc=True)
            .limit(limit)
        )
        resp = query.execute()
    except Exception as exc:
        click.echo(f"ERROR querying drafts: {exc}")
        sys.exit(1)

    rows = resp.data or []
    if not rows:
        click.echo(f"No drafts with status '{draft_status}'.")
        return

    click.echo(f"Drafts ({draft_status}) -- {len(rows)} found:")
    click.echo("-" * 80)
    for row in rows:
        sender = row.get("sender_name") or row.get("sender_email", "?")
        subj = (row.get("subject") or "(no subject)")[:50]
        cat = row.get("category", "?")
        conf = row.get("classification_confidence", 0) or 0
        created = (row.get("created_at") or "")[:19]
        draft_id = (row.get("id") or "")[:8]
        click.echo(
            f"  [{draft_id}] {sender:25s}  {cat:15s}  "
            f"{conf:.0%}  {created}  {subj}"
        )


# ---------------------------------------------------------------------------
# hermes migrate
# ---------------------------------------------------------------------------

@cli.command()
@click.option("--dry-run", is_flag=True, help="Print SQL without executing")
@click.pass_context
def migrate(ctx: click.Context, dry_run: bool) -> None:
    """Run SQL migrations from supabase/migrations/ against the database."""
    config_path = ctx.obj["config_path"]
    cfg = _load_config(config_path)

    # Find migration files: look relative to the package, then relative to config
    migrations_dir = Path(__file__).resolve().parent.parent / "supabase" / "migrations"
    if not migrations_dir.exists():
        migrations_dir = cfg.project_root / "supabase" / "migrations"
    if not migrations_dir.exists():
        click.echo(f"No migrations directory found at {migrations_dir}")
        sys.exit(1)

    sql_files = sorted(migrations_dir.glob("*.sql"))
    if not sql_files:
        click.echo("No .sql files found in migrations directory.")
        return

    click.echo(f"Found {len(sql_files)} migration(s) in {migrations_dir}:")
    for f in sql_files:
        click.echo(f"  {f.name}")

    if dry_run:
        click.echo("\n--dry-run: printing SQL without executing.\n")
        for f in sql_files:
            click.echo(f"-- === {f.name} ===")
            click.echo(f.read_text(encoding="utf-8"))
            click.echo()
        return

    # Execute via psycopg2 if DATABASE_URL is set, otherwise via Supabase REST RPC
    database_url = os.environ.get("DATABASE_URL", "")

    if database_url:
        _migrate_psycopg2(database_url, sql_files)
    else:
        _migrate_supabase_rest(cfg, sql_files)


def _migrate_psycopg2(database_url: str, sql_files: list) -> None:
    """Execute migrations via direct PostgreSQL connection."""
    try:
        import psycopg2
    except ImportError:
        click.echo("ERROR: psycopg2 not installed. Run: pip install psycopg2-binary")
        click.echo("Or set DATABASE_URL to use direct connection.")
        sys.exit(1)

    click.echo("\nConnecting via DATABASE_URL...")
    conn = psycopg2.connect(database_url)
    conn.autocommit = True

    for f in sql_files:
        sql = f.read_text(encoding="utf-8")
        click.echo(f"\nRunning {f.name}...")
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            click.echo(f"  OK")
        except Exception as exc:
            click.echo(f"  ERROR: {exc}")

    conn.close()
    click.echo("\nMigrations complete.")


def _migrate_supabase_rest(cfg, sql_files: list) -> None:
    """Execute migrations via Supabase SQL RPC.

    Requires a custom 'hermes_exec_sql' function in the database.
    Falls back to suggesting psycopg2 if unavailable.
    """
    sb = cfg.get_supabase()

    click.echo("\nRunning migrations via Supabase RPC...")
    click.echo(
        "NOTE: Requires a 'hermes_exec_sql' RPC function or "
        "DATABASE_URL for direct DB access."
    )

    for f in sql_files:
        sql = f.read_text(encoding="utf-8")
        click.echo(f"\nRunning {f.name}...")
        try:
            sb.rpc("hermes_exec_sql", {"sql_text": sql}).execute()
            click.echo(f"  OK")
        except Exception as exc:
            error_msg = str(exc)
            if "hermes_exec_sql" in error_msg or "function" in error_msg.lower():
                click.echo(
                    f"  SKIP: RPC function not available. "
                    f"Set DATABASE_URL in .env and re-run."
                )
                return
            click.echo(f"  ERROR: {exc}")

    click.echo("\nMigrations complete.")


# ---------------------------------------------------------------------------
# hermes seed
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def seed(ctx: click.Context) -> None:
    """Seed the database from hermes.yaml and template files."""
    config_path = ctx.obj["config_path"]
    cfg = _load_config(config_path)
    sb = cfg.get_supabase()
    tpl_dir = cfg.templates_dir

    click.echo(f"Seeding from: {config_path}")

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
            sb.table("hermes_config").upsert(row, on_conflict="category").execute()
            config_count += 1
            click.echo(f"  [config] {slug}")
        except Exception as exc:
            click.echo(f"  [config] ERROR {slug}: {exc}")

    click.echo(f"  {config_count} config rows upserted.")

    template_count = 0
    for slug in cfg.categories:
        tpl_file = tpl_dir / f"{slug}.md"
        if not tpl_file.exists():
            click.echo(f"  [template] SKIP {slug}")
            continue
        anchor = tpl_file.read_text(encoding="utf-8").strip()
        if not anchor:
            continue
        row = {"category": slug, "anchor_text": anchor}
        try:
            sb.table("hermes_templates").upsert(
                row, on_conflict="category"
            ).execute()
            template_count += 1
            click.echo(f"  [template] {slug} ({len(anchor)} chars)")
        except Exception as exc:
            click.echo(f"  [template] ERROR {slug}: {exc}")

    click.echo(f"  {template_count} template rows upserted.")
    click.echo("Seed complete.")


# ---------------------------------------------------------------------------
# hermes install-skill
# ---------------------------------------------------------------------------

@cli.command("install-skill")
@click.pass_context
def install_skill(ctx: click.Context) -> None:
    """Install the Hermes skill file to ~/.claude/skills/hermes/."""
    skill_src = Path(__file__).resolve().parent.parent / "skill" / "skill.md"
    if not skill_src.exists():
        click.echo(f"Skill file not found: {skill_src}")
        sys.exit(1)

    dest_dir = Path.home() / ".claude" / "skills" / "hermes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / "skill.md"

    shutil.copy2(skill_src, dest_file)
    click.echo(f"Installed skill to: {dest_file}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Entry point for the hermes CLI."""
    cli()


if __name__ == "__main__":
    main()
