#!/bin/bash
# Diagnostic script for 502/504 errors in eas-station-web service
# This script checks common causes of immediate gunicorn worker failures

set -e

echo "================================================================================"
echo "EAS Station 502/504 Error Diagnostic Script"
echo "================================================================================"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

ERRORS=0
WARNINGS=0

# mktemp, not fixed /tmp/*.txt paths: this script is typically run as root
# (sudo), and a predictable world-writable-directory filename is a classic
# symlink race (CWE-377) -- a local user could pre-plant a symlink there
# and have this script's redirects overwrite an arbitrary file as root.
DEP_CHECK_FILE=$(mktemp /tmp/eas-dep-check.XXXXXX)
GEVENT_CHECK_FILE=$(mktemp /tmp/eas-gevent-check.XXXXXX)
APP_IMPORT_FILE=$(mktemp /tmp/eas-app-import.XXXXXX)
trap 'rm -f "$DEP_CHECK_FILE" "$GEVENT_CHECK_FILE" "$APP_IMPORT_FILE"' EXIT

# Check 1: Service status
echo "[1] Checking service status..."
if systemctl is-active --quiet eas-station-web.service; then
    echo -e "${GREEN}✓${NC} Service is running"
else
    echo -e "${RED}✗${NC} Service is NOT running"
    ERRORS=$((ERRORS + 1))
    echo "  Last 20 log lines:"
    journalctl -u eas-station-web.service -n 20 --no-pager | sed 's/^/    /'
fi
echo ""

# Check 2: Environment file
echo "[2] Checking .env file..."
if [ -f /opt/eas-station/.env ]; then
    echo -e "${GREEN}✓${NC} .env file exists"
    
    # Check for DATABASE_URL
    if grep -q "^DATABASE_URL=" /opt/eas-station/.env; then
        echo -e "${GREEN}✓${NC} DATABASE_URL is set"
    else
        echo -e "${RED}✗${NC} DATABASE_URL is NOT set in .env"
        ERRORS=$((ERRORS + 1))
    fi
    
    # Check for SECRET_KEY
    if grep -q "^SECRET_KEY=" /opt/eas-station/.env; then
        SECRET_VALUE=$(grep "^SECRET_KEY=" /opt/eas-station/.env | cut -d= -f2)
        if [ ${#SECRET_VALUE} -lt 32 ]; then
            echo -e "${YELLOW}⚠${NC} SECRET_KEY is too short (should be 32+ characters)"
            WARNINGS=$((WARNINGS + 1))
        else
            echo -e "${GREEN}✓${NC} SECRET_KEY is set and adequate length"
        fi
    else
        echo -e "${YELLOW}⚠${NC} SECRET_KEY is NOT set (will use temporary key)"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo -e "${RED}✗${NC} .env file does NOT exist"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check 3: Database connectivity
echo "[3] Checking database connectivity..."
if systemctl is-active --quiet postgresql; then
    echo -e "${GREEN}✓${NC} PostgreSQL is running"
    
    # Try to connect as eas-station user
    if sudo -u eas-station psql -d eas_station -c "SELECT 1;" &>/dev/null; then
        echo -e "${GREEN}✓${NC} Database connection works"
    else
        echo -e "${RED}✗${NC} Cannot connect to database as eas-station user"
        ERRORS=$((ERRORS + 1))
        echo "  Check DATABASE_URL in .env and database permissions"
    fi
else
    echo -e "${RED}✗${NC} PostgreSQL is NOT running"
    ERRORS=$((ERRORS + 1))
    echo "  Start with: sudo systemctl start postgresql"
fi
echo ""

# Check 4: Python dependencies
echo "[4] Checking Python dependencies..."
if [ -x /opt/eas-station/venv/bin/python3 ]; then
    echo -e "${GREEN}✓${NC} Virtual environment exists"
    
    # Run dependency check
    if /opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_dependencies.py &>"$DEP_CHECK_FILE"; then
        echo -e "${GREEN}✓${NC} All critical dependencies installed"
    else
        echo -e "${RED}✗${NC} Dependency check failed"
        ERRORS=$((ERRORS + 1))
        echo "  Details:"
        cat "$DEP_CHECK_FILE" | sed 's/^/    /'
    fi
else
    echo -e "${RED}✗${NC} Virtual environment does NOT exist"
    ERRORS=$((ERRORS + 1))
fi
echo ""

# Check 5: Gevent compatibility
echo "[5] Checking gevent compatibility..."
if /opt/eas-station/venv/bin/python3 /opt/eas-station/scripts/check_gevent_compat.py &>"$GEVENT_CHECK_FILE"; then
    echo -e "${GREEN}✓${NC} Gevent compatibility check passed"
else
    echo -e "${RED}✗${NC} Gevent compatibility issues detected"
    ERRORS=$((ERRORS + 1))
    echo "  Details:"
    cat "$GEVENT_CHECK_FILE" | sed 's/^/    /'
fi
echo ""

# Check 6: App import test
echo "[6] Testing app.py import..."
cd /opt/eas-station
export SKIP_DB_INIT=1  # Skip background services during import test
if /opt/eas-station/venv/bin/python3 -c "from app import app; print('Import successful')" 2>"$APP_IMPORT_FILE"; then
    echo -e "${GREEN}✓${NC} app.py imports successfully"
else
    echo -e "${RED}✗${NC} app.py import FAILED - this is likely the cause of 502/504"
    ERRORS=$((ERRORS + 1))
    echo "  Error details:"
    cat "$APP_IMPORT_FILE" | sed 's/^/    /'
fi
unset SKIP_DB_INIT
echo ""

# Check 7: Port availability
echo "[7] Checking port 5000..."
if netstat -tuln | grep -q ":5000 "; then
    echo -e "${GREEN}✓${NC} Port 5000 is in use (service or another process)"
    # Check what's using it
    PORT_USER=$(sudo lsof -i :5000 -t 2>/dev/null | head -1)
    if [ -n "$PORT_USER" ]; then
        PORT_PROC=$(ps -p $PORT_USER -o comm= 2>/dev/null || echo "unknown")
        echo "  Process: $PORT_PROC (PID: $PORT_USER)"
    fi
else
    echo -e "${YELLOW}⚠${NC} Port 5000 is not in use (service may not be listening)"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# Check 8: Nginx configuration (if nginx is installed)
echo "[8] Checking Nginx..."
if command -v nginx &>/dev/null; then
    if systemctl is-active --quiet nginx; then
        echo -e "${GREEN}✓${NC} Nginx is running"
        
        # Check if eas-station config is enabled
        if [ -L /etc/nginx/sites-enabled/eas-station ]; then
            echo -e "${GREEN}✓${NC} eas-station nginx config is enabled"
        else
            echo -e "${YELLOW}⚠${NC} eas-station nginx config NOT enabled"
            WARNINGS=$((WARNINGS + 1))
            echo "  Enable with: sudo ln -s /etc/nginx/sites-available/eas-station /etc/nginx/sites-enabled/"
        fi
        
        # Test nginx config
        if sudo nginx -t &>/dev/null; then
            echo -e "${GREEN}✓${NC} Nginx configuration is valid"
        else
            echo -e "${RED}✗${NC} Nginx configuration has errors"
            ERRORS=$((ERRORS + 1))
            sudo nginx -t 2>&1 | sed 's/^/    /'
        fi
    else
        echo -e "${YELLOW}⚠${NC} Nginx is installed but not running"
        WARNINGS=$((WARNINGS + 1))
    fi
else
    echo "  ℹ Nginx not installed (optional)"
fi
echo ""

# Check 9: File permissions
echo "[9] Checking file permissions..."
if [ -d /opt/eas-station ]; then
    OWNER=$(stat -c '%U' /opt/eas-station)
    if [ "$OWNER" = "eas-station" ]; then
        echo -e "${GREEN}✓${NC} /opt/eas-station owned by eas-station"
    else
        echo -e "${RED}✗${NC} /opt/eas-station owned by $OWNER (should be eas-station)"
        ERRORS=$((ERRORS + 1))
        echo "  Fix with: sudo chown -R eas-station:eas-station /opt/eas-station"
    fi
fi

if [ -d /var/log/eas-station ]; then
    OWNER=$(stat -c '%U' /var/log/eas-station)
    if [ "$OWNER" = "eas-station" ]; then
        echo -e "${GREEN}✓${NC} /var/log/eas-station owned by eas-station"
    else
        echo -e "${RED}✗${NC} /var/log/eas-station owned by $OWNER (should be eas-station)"
        ERRORS=$((ERRORS + 1))
        echo "  Fix with: sudo chown eas-station:eas-station /var/log/eas-station"
    fi
else
    echo -e "${YELLOW}⚠${NC} /var/log/eas-station does not exist (will be created on start)"
    WARNINGS=$((WARNINGS + 1))
fi
echo ""

# Summary
echo "================================================================================"
echo "Summary"
echo "================================================================================"
if [ $ERRORS -eq 0 ]; then
    if [ $WARNINGS -eq 0 ]; then
        echo -e "${GREEN}✓ All checks passed!${NC}"
        echo ""
        echo "If you're still seeing 502/504 errors, check:"
        echo "  1. Recent service logs: journalctl -u eas-station-web.service -n 100"
        echo "  2. Nginx error log: tail -f /var/log/nginx/eas-station-error.log"
        echo "  3. Try manual start: sudo -u eas-station bash -c 'cd /opt/eas-station && source venv/bin/activate && gunicorn app:app'"
    else
        echo -e "${YELLOW}⚠ $WARNINGS warning(s) found${NC}"
        echo "These may not prevent startup but should be addressed."
    fi
else
    echo -e "${RED}✗ $ERRORS error(s) found that will prevent service startup${NC}"
    echo ""
    echo "Fix the errors above and then restart the service:"
    echo "  sudo systemctl restart eas-station-web.service"
fi
echo ""

# Cleanup

exit $ERRORS
