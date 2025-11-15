#!/bin/bash
# Verification script for GPIO and OLED functionality
# Run this after starting containers to verify everything is working

set -e

echo "=== EAS Station GPIO/OLED Verification ==="
echo ""

# Function to check container logs for specific patterns
check_logs() {
    local container=$1
    local pattern=$2
    local name=$3

    echo -n "Checking $name... "
    if docker logs "$container" 2>&1 | grep -q "$pattern"; then
        echo "✓ FOUND"
        return 0
    else
        echo "✗ NOT FOUND"
        return 1
    fi
}

# Find the app container
APP_CONTAINER=$(docker compose ps -q app 2>/dev/null | head -1)

if [ -z "$APP_CONTAINER" ]; then
    echo "ERROR: App container not found. Is it running?"
    echo ""
    echo "Start the stack with: ./start-pi.sh"
    exit 1
fi

echo "Found app container: $APP_CONTAINER"
echo ""

# Check for GPIO initialization
echo "=== GPIO Status ==="
if check_logs "$APP_CONTAINER" "GPIO controller initialized" "GPIO initialization"; then
    echo "  GPIO backend is active"

    # Check which backend
    if docker logs "$APP_CONTAINER" 2>&1 | grep -q "using gpiozero OutputDevice"; then
        echo "  Backend: gpiozero (standard)"
    elif docker logs "$APP_CONTAINER" 2>&1 | grep -q "using LGPIO backend"; then
        echo "  Backend: lgpio (Raspberry Pi 5)"
    elif docker logs "$APP_CONTAINER" 2>&1 | grep -q "using sysfs GPIO"; then
        echo "  Backend: sysfs (legacy)"
    fi
else
    echo "  ⚠ GPIO initialization not found in logs"
fi

# Check for MockFactory fallback (BAD)
if check_logs "$APP_CONTAINER" "MockFactory fallback" "MockFactory (should NOT appear)"; then
    echo "  ⚠⚠⚠ ERROR: Using MockFactory - GPIO hardware not accessible!"
    echo ""
    echo "  This means the container cannot access /dev/gpiomem"
    echo "  Solution: Ensure you started with: ./start-pi.sh"
    echo "           OR docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d"
    MOCK_DETECTED=1
else
    echo "  ✓ MockFactory NOT detected (good)"
    MOCK_DETECTED=0
fi

echo ""

# Check for OLED initialization
echo "=== OLED Status ==="
if check_logs "$APP_CONTAINER" "OLED" "OLED mentions"; then

    # Check if OLED is enabled
    if docker logs "$APP_CONTAINER" 2>&1 | grep -q "OLED display disabled"; then
        echo "  ⚠ OLED is disabled in configuration"
        echo "  Solution: Set OLED_ENABLED=true in .env file"
        OLED_DISABLED=1
    elif docker logs "$APP_CONTAINER" 2>&1 | grep -q "OLED.*initialized"; then
        echo "  ✓ OLED display initialized successfully"
        OLED_DISABLED=0
    elif docker logs "$APP_CONTAINER" 2>&1 | grep -q "OLED dependencies unavailable"; then
        echo "  ⚠ OLED libraries (luma.oled) not available"
        echo "  This is unusual - the Docker image should include these"
        OLED_DISABLED=1
    else
        echo "  ? OLED status unclear from logs"
        OLED_DISABLED=1
    fi
else
    echo "  ⚠ No OLED log entries found"
    OLED_DISABLED=1
fi

echo ""

# Check OLED I2C button
echo "=== OLED Button (GPIO 4) ==="
if docker logs "$APP_CONTAINER" 2>&1 | grep -q "OLED.*button"; then
    if docker logs "$APP_CONTAINER" 2>&1 | grep -q "gpiozero pin factory unavailable"; then
        echo "  ⚠ Button initialization failed - no GPIO access"
    else
        echo "  ✓ OLED button initialized (GPIO 4, physical pin 7)"
    fi
else
    echo "  - No button log entries (may be normal if OLED disabled)"
fi

echo ""

# Summary
echo "=== Summary ==="
ISSUES=0

if [ $MOCK_DETECTED -eq 1 ]; then
    echo "❌ GPIO: MockFactory detected - hardware NOT accessible"
    ISSUES=$((ISSUES + 1))
else
    echo "✓ GPIO: Hardware backend active"
fi

if [ $OLED_DISABLED -eq 1 ]; then
    echo "⚠ OLED: Not fully operational"
    ISSUES=$((ISSUES + 1))
else
    echo "✓ OLED: Initialized and operational"
fi

echo ""

if [ $ISSUES -eq 0 ]; then
    echo "🎉 All systems operational!"
    echo ""
    echo "Your OLED should be displaying information."
    echo "GPIO pin 12 is configured for relay control."
    echo ""
    echo "Test the relay with:"
    echo "  - Web UI: http://your-pi-ip/admin/gpio"
    echo "  - API: curl -X POST http://localhost:5000/api/gpio/activate/12 \\"
    echo "         -H 'Content-Type: application/json' \\"
    echo "         -d '{\"reason\": \"Test\", \"activation_type\": \"test\"}'"
else
    echo "⚠ Found $ISSUES issue(s) - see above for details"
    echo ""
    echo "Common fixes:"
    echo "  1. Restart with Pi override: ./start-pi.sh"
    echo "  2. Enable OLED: echo 'OLED_ENABLED=true' >> .env && docker compose restart"
    echo "  3. Check logs: docker logs $APP_CONTAINER | grep -i 'gpio\|oled'"
fi

echo ""
echo "=== Recent Log Entries ==="
echo "Last 30 lines mentioning GPIO or OLED:"
docker logs "$APP_CONTAINER" 2>&1 | grep -i "gpio\|oled" | tail -30

exit $ISSUES
