#!/bin/bash
#
# Emergency Fix Script for Website 504 Errors
# This script fixes the --system-site-packages issue on a deployed system
#
# Run this script on the deployed server:
#   TMPFILE=$(mktemp /tmp/eas-fix-website.XXXXXX)
#   curl -fsSL -o "$TMPFILE" https://raw.githubusercontent.com/KR8MER/eas-station/copilot/fix-broken-logs/scripts/fix_website_504.sh
#   sudo bash "$TMPFILE"
#
# Use mktemp, not a fixed /tmp/fix_website.sh path: a predictable filename
# in a world-writable directory lets a local user pre-plant that exact
# path (before this script is ever downloaded) with content of their own
# choosing, which `sudo bash` then executes as root. mktemp's unpredictable
# suffix plus /tmp's sticky bit (which blocks a non-owner from deleting or
# replacing a file they don't own, even with write access to the directory)
# closes that off.
#

set -e  # Exit on error

echo "=========================================="
echo "EAS Station Website 504 Fix"
echo "=========================================="
echo ""
echo "This script fixes the --system-site-packages issue that"
echo "causes 504 Gateway Timeout errors."
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root or with sudo"
    echo "Usage: sudo bash fix_website_504.sh"
    exit 1
fi

# Configuration
INSTALL_DIR="/opt/eas-station"
SERVICE_USER="eas-station"
VENV_DIR="${INSTALL_DIR}/venv"

echo "Step 1: Verifying installation directory..."
if [ ! -d "$INSTALL_DIR" ]; then
    echo "ERROR: Installation directory not found: $INSTALL_DIR"
    echo "Is EAS Station installed?"
    exit 1
fi
echo "✓ Installation directory exists: $INSTALL_DIR"
echo ""

echo "Step 2: Checking current venv configuration..."
if [ -f "${VENV_DIR}/pyvenv.cfg" ]; then
    if grep -q "include-system-site-packages = true" "${VENV_DIR}/pyvenv.cfg"; then
        echo "⚠ DETECTED: Virtual environment has system-site-packages enabled"
        echo "  This is the root cause of the 504 errors"
        NEEDS_FIX=true
    else
        echo "✓ Virtual environment already configured correctly"
        NEEDS_FIX=false
    fi
else
    echo "⚠ Virtual environment configuration file not found"
    NEEDS_FIX=true
fi
echo ""

if [ "$NEEDS_FIX" = false ]; then
    echo "=========================================="
    echo "No fix needed - venv is already correct"
    echo "=========================================="
    echo ""
    echo "If you're still experiencing 504 errors, check:"
    echo "  1. Gunicorn logs: sudo journalctl -u eas-station-web.service -n 100"
    echo "  2. Nginx logs: sudo journalctl -u nginx -n 100"
    echo "  3. Port conflicts: sudo netstat -tlnp | grep :5000"
    exit 0
fi

echo "Step 3: Stopping EAS Station services..."
systemctl stop eas-station.target 2>/dev/null || systemctl stop eas-station-web.service
echo "✓ Services stopped"
echo ""

echo "Step 4: Backing up current virtual environment..."
BACKUP_DIR="${INSTALL_DIR}/venv_backup_$(date +%Y%m%d_%H%M%S)"
if [ -d "$VENV_DIR" ]; then
    cp -r "$VENV_DIR" "$BACKUP_DIR"
    echo "✓ Backup created: $BACKUP_DIR"
else
    echo "⚠ No existing venv to backup"
fi
echo ""

echo "Step 5: Removing old virtual environment..."
rm -rf "$VENV_DIR"
echo "✓ Old venv removed"
echo ""

echo "Step 6: Creating new virtual environment (WITHOUT system-site-packages)..."
if ! sudo -u "$SERVICE_USER" python3 -m venv "$VENV_DIR"; then
    echo "ERROR: Failed to create virtual environment"
    echo "Attempting to restore backup..."
    if [ -d "$BACKUP_DIR" ]; then
        mv "$BACKUP_DIR" "$VENV_DIR"
        echo "Backup restored. Please investigate the error manually."
    fi
    exit 1
fi
echo "✓ New venv created"
echo ""

echo "Step 7: Verifying venv configuration..."
if grep -q "include-system-site-packages = false" "${VENV_DIR}/pyvenv.cfg"; then
    echo "✓ Venv correctly configured WITHOUT system-site-packages"
else
    echo "ERROR: Venv configuration is incorrect"
    cat "${VENV_DIR}/pyvenv.cfg"
    exit 1
fi
echo ""

echo "Step 8: Upgrading pip..."
sudo -u "$SERVICE_USER" "${VENV_DIR}/bin/pip" install --upgrade pip --quiet
echo "✓ Pip upgraded"
echo ""

echo "Step 9: Installing Python dependencies..."
cd "$INSTALL_DIR"
if [ ! -f "requirements.txt" ]; then
    echo "ERROR: requirements.txt not found in $INSTALL_DIR"
    exit 1
fi

echo "  This may take several minutes..."
PIP_INSTALL_LOG=$(mktemp /tmp/eas-pip-install.XXXXXX)
if ! sudo -u "$SERVICE_USER" "${VENV_DIR}/bin/pip" install -r requirements.txt 2>&1 | tee "$PIP_INSTALL_LOG" | grep -E "Successfully|ERROR"; then
    echo "⚠ Some packages may have failed to install"
    echo "  Check $PIP_INSTALL_LOG for details"
fi
echo "✓ Dependencies installed"
echo ""

echo "Step 10: Testing application import..."
if sudo -u "$SERVICE_USER" timeout 30 "${VENV_DIR}/bin/python3" -c "import sys; sys.path.insert(0, '$INSTALL_DIR'); from app import app; print('✓ Import successful')" 2>&1 | grep -q "Import successful"; then
    echo "✓ Application imports successfully"
else
    echo "⚠ WARNING: Application import test failed"
    echo "  This may indicate other issues beyond the venv fix"
    echo "  Continuing anyway - check logs after restart"
fi
echo ""

echo "Step 11: Reloading systemd configuration..."
systemctl daemon-reload
echo "✓ Systemd reloaded"
echo ""

echo "Step 12: Starting web service..."
systemctl start eas-station-web.service
echo "✓ Web service started"
echo ""

echo "Step 13: Waiting for service to initialize (30 seconds)..."
sleep 30
echo "✓ Initialization period complete"
echo ""

echo "Step 14: Checking service status..."
if systemctl is-active --quiet eas-station-web.service; then
    echo "✓ Web service is ACTIVE"
else
    echo "✗ ERROR: Web service is NOT active"
    echo ""
    echo "Recent logs:"
    journalctl -u eas-station-web.service -n 30 --no-pager
    echo ""
    echo "Full logs: sudo journalctl -u eas-station-web.service -n 200 --no-pager"
    exit 1
fi
echo ""

echo "Step 15: Testing web service response..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5000/api/health 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "✓ Web service is responding (HTTP 200)"
else
    echo "⚠ WARNING: Web service returned HTTP $HTTP_CODE"
    echo "  Expected: 200"
    echo "  This may indicate the service is still starting up"
    echo "  Wait 1-2 minutes and test manually:"
    echo "    curl http://localhost:5000/api/health"
fi
echo ""

echo "Step 16: Starting remaining EAS Station services..."
systemctl start eas-station.target 2>/dev/null || true
echo "✓ All services started"
echo ""

echo "=========================================="
echo "Fix Complete!"
echo "=========================================="
echo ""
echo "Verification:"
echo "  ✓ Virtual environment recreated WITHOUT --system-site-packages"
echo "  ✓ Dependencies reinstalled"
echo "  ✓ Services restarted"
echo ""
echo "Next steps:"
echo "  1. Test website: http://$(hostname -I | awk '{print $1}')"
echo "  2. Monitor logs: sudo journalctl -u eas-station-web.service -f"
echo "  3. Check all services: sudo systemctl status eas-station.target"
echo ""
echo "If still experiencing issues:"
echo "  1. Check for port conflicts: sudo netstat -tlnp | grep :5000"
echo "  2. Review full logs: sudo journalctl -u eas-station-web.service -n 200"
echo "  3. Check nginx config: sudo nginx -t"
echo ""
echo "Backup location (if you need to rollback):"
echo "  $BACKUP_DIR"
echo ""
