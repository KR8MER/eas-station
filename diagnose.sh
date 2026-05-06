#!/bin/bash
# EAS Station diagnostic script for database and service issues

echo "=========================================="
echo "EAS Station Installation Diagnostics"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "ERROR: This script must be run as root"
    echo "Usage: sudo bash diagnose.sh"
    exit 1
fi

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "1. Checking services status..."
echo "-------------------------------"
systemctl status eas-station-web.service --no-pager -l | head -20
echo ""

echo "2. Checking nginx status..."
echo "-------------------------------"
systemctl status nginx --no-pager -l | head -10
echo ""

echo "3. Checking database connection..."
echo "-------------------------------"
if sudo -u postgres psql -d alerts -c "SELECT version();" 2>/dev/null | grep PostgreSQL; then
    echo -e "${GREEN}✓ Database connection OK${NC}"
else
    echo -e "${RED}✗ Database connection FAILED${NC}"
fi
echo ""

echo "4. Database schema health check..."
echo "-------------------------------"
if [ -f /opt/eas-station/venv/bin/python3 ] && [ -f /opt/eas-station/scripts/database/check_schema.py ]; then
    cd /opt/eas-station
    sudo -u eas-station /opt/eas-station/venv/bin/python3 \
        scripts/database/check_schema.py 2>&1
else
    echo -e "${YELLOW}⚠ check_schema.py not found; falling back to basic table check${NC}"
    TABLES=$(sudo -u postgres psql -d alerts -tAc "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('hardware_settings', 'icecast_settings', 'alert_filter_settings', 'poll_history');" 2>/dev/null)
    for t in hardware_settings icecast_settings alert_filter_settings poll_history; do
        if echo "$TABLES" | grep -q "$t"; then
            echo -e "${GREEN}✓ $t exists${NC}"
        else
            echo -e "${RED}✗ $t MISSING${NC}"
        fi
    done
fi
echo ""

echo "5. Checking recent web service logs..."
echo "-------------------------------"
journalctl -u eas-station-web.service -n 50 --no-pager
echo ""

echo "6. Checking .env file..."
echo "-------------------------------"
if [ -f /opt/eas-station/.env ]; then
    echo -e "${GREEN}✓ .env file exists${NC}"
    echo "Database URL: $(grep DATABASE_URL /opt/eas-station/.env | sed 's/:[^:]*@/:***@/')"
else
    echo -e "${RED}✗ .env file MISSING${NC}"
fi
echo ""

echo "7. Testing app import..."
echo "-------------------------------"
cd /opt/eas-station
sudo -u eas-station /opt/eas-station/venv/bin/python3 -c "
try:
    from app import app
    print('${GREEN}✓ App imports successfully${NC}')
except Exception as e:
    print('${RED}✗ App import failed: ' + str(e) + '${NC}')
    import traceback
    traceback.print_exc()
" 2>&1 | head -30
echo ""

echo "=========================================="
echo "Diagnostic complete"
echo "=========================================="
