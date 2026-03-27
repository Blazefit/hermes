"""Generate Linux crontab entries for Hermes scheduling."""

import os
import shutil


def generate_crontab_entry(
    command: str = "cycle",
    interval_minutes: int = 10,
    config_path: str = None,
    working_dir: str = None,
    log_dir: str = None,
) -> str:
    """Generate a crontab entry for a Hermes command.

    Args:
        command: CLI command to run (cycle, train).
        interval_minutes: Minutes between runs (for cycle). Ignored for train.
        config_path: Path to hermes.yaml.
        working_dir: Working directory.
        log_dir: Directory for log files.

    Returns:
        Crontab entry string.
    """
    working_dir = working_dir or os.getcwd()
    config_path = config_path or os.path.join(working_dir, "hermes.yaml")
    log_dir = log_dir or os.path.join(working_dir, "logs")
    hermes_path = shutil.which("hermes") or "hermes"

    cmd = f"cd {working_dir} && {hermes_path} --config {config_path} {command}"

    if command == "train":
        # Monthly on the 1st at 3am
        return f"0 3 1 * * {cmd} >> {log_dir}/train.log 2>&1"
    else:
        return f"*/{interval_minutes} * * * * {cmd} >> {log_dir}/{command}.log 2>&1"


def print_crontab_instructions(
    interval_minutes: int = 10,
    config_path: str = None,
    working_dir: str = None,
) -> str:
    """Return instructions for installing crontab entries."""
    cycle_entry = generate_crontab_entry("cycle", interval_minutes, config_path, working_dir)
    train_entry = generate_crontab_entry("train", config_path=config_path, working_dir=working_dir)

    return f"""Add these lines to your crontab (run: crontab -e):

# Hermes Email - process cycle every {interval_minutes} minutes
{cycle_entry}

# Hermes Email - train voice samples monthly
{train_entry}
"""
