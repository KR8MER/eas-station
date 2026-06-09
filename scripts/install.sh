#!/bin/bash
# EAS Station - DEPRECATED installer shim
#
# This used to be a second, parallel installer. It drifted badly out of sync
# with the project and produced broken half-installs:
#   - it called `manage.py db upgrade`, but there is no manage.py (the real
#     installer uses Alembic directly),
#   - it restarted `eas-monitoring` / `sdr-hardware`, but the shipped units are
#     named `eas-station-*.service`,
#   - it pointed users at http://localhost:5000, but the real install serves the
#     web UI through nginx.
#
# There is exactly one supported installer: ./install.sh in the repository root.
# See docs/installation/QUICKSTART.md and docs/installation/INSTALLATION_DETAILS.md.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo "scripts/install.sh is DEPRECATED"
echo "=========================================="
echo
echo "This script no longer performs an installation. Use the single,"
echo "canonical installer in the repository root instead:"
echo
echo "    sudo bash \"$PROJECT_ROOT/install.sh\""
echo
echo "Docs:"
echo "    docs/installation/QUICKSTART.md"
echo "    docs/installation/INSTALLATION_DETAILS.md"
echo
exit 1
