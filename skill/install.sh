#!/usr/bin/env bash
# Hermes Email System -- installer
# Installs the hermes-email package and runs the setup wizard.

set -euo pipefail

echo "=============================="
echo "  Hermes Email -- Installer"
echo "=============================="
echo ""

# Check Python version
if ! command -v python3 &>/dev/null; then
    echo "ERROR: Python 3 is required but not found."
    echo "Install Python 3.10+ and try again."
    exit 1
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Python: $PYTHON_VERSION"

# Install the package
echo ""
echo "Installing hermes-email..."
pip install --upgrade hermes-email 2>/dev/null || pip3 install --upgrade hermes-email

# Run setup wizard
echo ""
echo "Running setup wizard..."
hermes setup

# Install the Claude Code skill
echo ""
echo "Installing Claude Code skill..."
hermes install-skill

echo ""
echo "=============================="
echo "  Installation complete!"
echo "=============================="
echo ""
echo "Next steps:"
echo "  1. Review hermes.yaml and templates/"
echo "  2. Run: hermes migrate"
echo "  3. Run: hermes seed"
echo "  4. Test: hermes cycle"
