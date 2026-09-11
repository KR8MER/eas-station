#!/bin/bash
# Diagnose SMART monitoring issues

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "EAS Station SMART Monitoring Diagnostics"
echo "=========================================="
echo

# 1. Check user
echo "1. Current user and groups:"
echo "   User: $(whoami)"
echo "   Groups: $(groups)"
echo

# 2. Find service user
echo "2. Service user:"
SERVICE_USER=$(ps aux | grep '[e]as_monitoring_service.py' | awk '{print $1}' | head -1)
if [ -n "$SERVICE_USER" ]; then
    echo -e "   ${GREEN}✓ Found: $SERVICE_USER${NC}"
else
    echo -e "   ${RED}✗ Could not detect service user${NC}"
    SERVICE_USER="eas-station"
fi
echo

# 3. Check smartctl
echo "3. smartctl installation:"
if command -v smartctl &>/dev/null; then
    SMARTCTL_PATH=$(which smartctl)
    echo -e "   ${GREEN}✓ Found: $SMARTCTL_PATH${NC}"
    smartctl --version | head -2 | sed 's/^/   /'
else
    echo -e "   ${RED}✗ smartctl not found${NC}"
    exit 1
fi
echo

# 4. Check devices
echo "4. Available devices:"
DEVICES=$(sudo smartctl --scan 2>&1)
if [ -n "$DEVICES" ]; then
    echo -e "${GREEN}$DEVICES${NC}" | sed 's/^/   /'
else
    echo -e "   ${YELLOW}! No devices found${NC}"
fi
echo

# 5. Check sudoers
echo "5. Sudoers configuration:"
SUDOERS_FILE="/etc/sudoers.d/eas-station-smartctl"
if [ -f "$SUDOERS_FILE" ]; then
    echo -e "   ${GREEN}✓ File exists: $SUDOERS_FILE${NC}"
    echo "   Contents:"
    sudo cat "$SUDOERS_FILE" | sed 's/^/     /'

    # Check if correct user
    if sudo grep -q "^$SERVICE_USER " "$SUDOERS_FILE"; then
        echo -e "   ${GREEN}✓ Configured for correct user: $SERVICE_USER${NC}"
    else
        echo -e "   ${RED}✗ NOT configured for $SERVICE_USER${NC}"
        echo "   Fix with:"
        echo "     sudo tee /etc/sudoers.d/eas-station-smartctl <<EOF"
        echo "     $SERVICE_USER ALL=(ALL) NOPASSWD: /usr/sbin/smartctl"
        echo "     EOF"
        echo "     sudo chmod 0440 /etc/sudoers.d/eas-station-smartctl"
    fi
else
    echo -e "   ${RED}✗ File not found: $SUDOERS_FILE${NC}"
    echo "   Create with:"
    echo "     sudo ./scripts/setup_smart_monitoring.sh $SERVICE_USER"
fi
echo

# 6. Test sudo access
echo "6. Testing sudo access as $SERVICE_USER:"
if sudo -u "$SERVICE_USER" sudo -n smartctl --version &>/dev/null; then
    echo -e "   ${GREEN}✓ Sudo access works${NC}"
else
    echo -e "   ${RED}✗ Sudo access FAILED${NC}"
    echo "   Possible issues:"
    echo "     - Sudoers file has wrong user"
    echo "     - Sudoers file has wrong permissions"
    echo "     - User needs to log out/in for group changes"
fi
echo

# 7. Test device access
echo "7. Testing device access:"
if [ -e /dev/nvme0 ]; then
    echo "   Testing /dev/nvme0..."
    if sudo -u "$SERVICE_USER" sudo -n smartctl -H /dev/nvme0 &>/dev/null; then
        echo -e "   ${GREEN}✓ Can read /dev/nvme0${NC}"
    else
        echo -e "   ${RED}✗ Cannot read /dev/nvme0${NC}"
    fi
elif [ -e /dev/sda ]; then
    echo "   Testing /dev/sda..."
    if sudo -u "$SERVICE_USER" sudo -n smartctl -H /dev/sda &>/dev/null; then
        echo -e "   ${GREEN}✓ Can read /dev/sda${NC}"
    else
        echo -e "   ${RED}✗ Cannot read /dev/sda${NC}"
    fi
else
    echo -e "   ${YELLOW}! No /dev/nvme0 or /dev/sda found${NC}"
fi
echo

# 8. Check Python code
echo "8. Python environment:"
VENV_PATH="/opt/eas-station/venv/bin/python"
if [ -f "$VENV_PATH" ]; then
    echo -e "   ${GREEN}✓ Found venv: $VENV_PATH${NC}"

    # Test if psutil is installed
    if $VENV_PATH -c "import psutil" 2>/dev/null; then
        echo -e "   ${GREEN}✓ psutil installed${NC}"
    else
        echo -e "   ${RED}✗ psutil not installed${NC}"
    fi
else
    echo -e "   ${YELLOW}! venv not at expected location${NC}"
fi
echo

# 9. Test Python SMART code
echo "9. Testing Python SMART collection:"
# mktemp, not a fixed /tmp/test_smart.py path: this script typically runs
# as root, and a predictable filename in a world-writable directory is a
# classic symlink race (CWE-377) -- a local user could pre-plant it
# pointing at an arbitrary file before this line ever runs. chmod 644
# because it's read below by a *different* user (sudo -u "$SERVICE_USER"),
# not secret content, so it needs to stay world-readable like the plain
# `cat >` it replaces would have produced under a typical root umask.
SMART_TEST_SCRIPT=$(mktemp /tmp/eas-test-smart.XXXXXX.py)
chmod 644 "$SMART_TEST_SCRIPT"
cat > "$SMART_TEST_SCRIPT" <<'PYTEST'
import sys
sys.path.insert(0, '/opt/eas-station')

try:
    from app_utils.system import _collect_smart_health

    # Mock logger
    class MockLogger:
        def debug(self, *args, **kwargs): pass
        def info(self, *args, **kwargs): pass
        def warning(self, *args, **kwargs): pass
        def error(self, *args, **kwargs): pass

    # Mock devices
    devices = [
        {'name': 'nvme0', 'path': '/dev/nvme0', 'transport': 'nvme'}
    ]

    result = _collect_smart_health(MockLogger(), devices)

    if result.get('available'):
        print("✓ SMART collection works")
        if result.get('devices'):
            print(f"✓ Found {len(result['devices'])} device(s)")
            for dev in result['devices']:
                if dev.get('error'):
                    print(f"✗ {dev['name']}: {dev['error']}")
                else:
                    print(f"✓ {dev['name']}: {dev.get('overall_status', 'unknown')}")
        else:
            print("! No device data collected")
    else:
        print(f"✗ SMART collection failed: {result.get('error')}")

except Exception as e:
    print(f"✗ Python error: {e}")
    import traceback
    traceback.print_exc()
PYTEST

if [ -f "$VENV_PATH" ]; then
    sudo -u "$SERVICE_USER" $VENV_PATH "$SMART_TEST_SCRIPT" 2>&1 | sed 's/^/   /'
else
    echo "   Skipped (venv not found)"
fi
rm -f "$SMART_TEST_SCRIPT"
echo

# 10. Check logs
echo "10. Recent SMART errors in logs:"
if journalctl -u eas-station.target --since "10 minutes ago" 2>/dev/null | grep -i smart | tail -5; then
    :
else
    echo "    (no recent SMART messages in logs)"
fi
echo

echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Run this script on your server and share the output."
echo "It will show exactly what's failing."
