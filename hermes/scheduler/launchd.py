"""Generate macOS launchd plist files for Hermes scheduling."""

import os
from pathlib import Path


PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_path}</string>
        <string>-m</string>
        <string>hermes.cli</string>
        <string>{command}</string>
        <string>--config</string>
        <string>{config_path}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_dir}</string>
    <key>StartInterval</key>
    <integer>{interval}</integer>
    <key>StandardOutPath</key>
    <string>{log_dir}/{command}.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/{command}.err</string>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>"""


def generate_plist(
    command: str = "cycle",
    interval: int = 600,
    label_prefix: str = "com.hermes-email",
    config_path: str = None,
    working_dir: str = None,
    log_dir: str = None,
) -> str:
    """Generate a launchd plist for a Hermes command.

    Args:
        command: CLI command to run (cycle, train).
        interval: Seconds between runs.
        label_prefix: Bundle ID prefix.
        config_path: Path to hermes.yaml.
        working_dir: Working directory.
        log_dir: Directory for log files.

    Returns:
        Plist XML string.
    """
    import shutil

    working_dir = working_dir or os.getcwd()
    config_path = config_path or os.path.join(working_dir, "hermes.yaml")
    log_dir = log_dir or os.path.join(working_dir, "logs")
    python_path = shutil.which("python3") or shutil.which("python") or "/usr/bin/python3"

    return PLIST_TEMPLATE.format(
        label=f"{label_prefix}.{command}",
        python_path=python_path,
        command=command,
        config_path=config_path,
        working_dir=working_dir,
        interval=interval,
        log_dir=log_dir,
    )


def install_plist(command: str = "cycle", interval: int = 600, **kwargs) -> str:
    """Generate and install a launchd plist.

    Returns the path to the installed plist file.
    """
    plist_content = generate_plist(command=command, interval=interval, **kwargs)
    label = f"{kwargs.get('label_prefix', 'com.hermes-email')}.{command}"
    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"

    os.makedirs(plist_path.parent, exist_ok=True)
    plist_path.write_text(plist_content)

    return str(plist_path)
