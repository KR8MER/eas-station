#!/bin/bash
# ONE-COMMAND FIX for database authentication issues
# Run this to fix everything automatically

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║  EAS Station Database Authentication Fix - AUTO MODE          ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run with sudo"
    echo "   Run: sudo /opt/eas-station/scripts/database/fix_database_user.sh"
    exit 1
fi

# Run the fix script
echo "▶ Running database user fix..."
/opt/eas-station/scripts/database/fix_database_user.sh

echo ""
echo "▶ Reloading systemd configuration..."
systemctl daemon-reload

echo ""
echo "▶ Restarting all EAS Station services..."
systemctl restart eas-station.target

echo ""
echo "▶ Waiting for services to start..."
sleep 5

echo ""
echo "▶ Checking service status..."
echo ""

SERVICES=("eas-station-web" "eas-station-poller" "eas-station-audio")
ALL_RUNNING=true

for service in "${SERVICES[@]}"; do
    if systemctl is-active --quiet "$service.service" 2>/dev/null; then
        echo "  ✅ $service.service is running"
    else
        echo "  ❌ $service.service is NOT running"
        ALL_RUNNING=false
    fi
done

echo ""

if [ "$ALL_RUNNING" = true ]; then
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  ✅ SUCCESS! All services are running                         ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Check logs to verify no more authentication errors:"
    echo "  sudo journalctl -u eas-station-poller.service -n 20"
else
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║  ⚠️  Some services failed to start                            ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
    echo "Check logs for errors:"
    echo "  sudo journalctl -u eas-station.target -n 50"
fi
