#!/bin/bash
# Diagnostic script to identify why cap_poller is using constant 50% CPU

echo "=== CAP Poller CPU Diagnostic ==="
echo ""

# Check if pollers are running
echo "1. Checking running poller containers..."
docker ps --filter "name=poller" --format "table {{.Names}}\t{{.Status}}\t{{.Command}}"
echo ""

# Check poller logs for sleep messages
echo "2. Checking if pollers are actually sleeping..."
echo "   Looking for 'Waiting X seconds' messages in last 50 lines..."
docker logs noaa-poller 2>&1 | tail -50 | grep -i "waiting\|sleep" || echo "   ⚠️  NO SLEEP MESSAGES FOUND"
echo ""

# Check for rate limiting and API issues
echo "3. Checking for API rate limiting and errors..."
echo "   HTTP 429 (Rate Limited) errors:"
docker logs noaa-poller 2>&1 | tail -200 | grep -c "429\|Rate limited" | xargs -I {} echo "      Count: {}"
echo "   Timeout errors:"
docker logs noaa-poller 2>&1 | tail -200 | grep -c "Timeout" | xargs -I {} echo "      Count: {}"
echo "   If counts are high, increase --interval or reduce zone codes"
echo ""

# Check for continuous error loops
echo "4. Checking for error loops..."
docker logs noaa-poller 2>&1 | tail -100 | grep -c "Error in continuous polling" | xargs -I {} echo "   Error count in last 100 lines: {}"
echo ""

# Check restart count
echo "5. Checking Docker restart count..."
docker inspect noaa-poller --format='{{.RestartCount}}' | xargs -I {} echo "   Restart count: {}"
echo ""

# Check if --continuous flag is present
echo "6. Checking command line arguments..."
docker inspect noaa-poller --format='{{.Config.Cmd}}' | grep -o "continuous" && echo "   ✓ --continuous flag present" || echo "   ⚠️  --continuous flag MISSING"
echo ""

# Check recent log entries
echo "7. Last 10 log entries from noaa-poller:"
docker logs noaa-poller 2>&1 | tail -10
echo ""

# Check CPU usage
echo "8. Current CPU usage:"
docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}" | grep -E "CONTAINER|poller"
echo ""

echo "=== Analysis ==="
echo "If you see:"
echo "  - No 'Waiting X seconds' messages → Poller is NOT sleeping (tight loop)"
echo "  - HTTP 429 or 'Rate limited' messages → API is rate limiting requests ⚠️ COMMON CAUSE"
echo "  - Timeout errors → API is slow or blocking, increase interval"
echo "  - High restart count → Docker is restarting container repeatedly"
echo "  - Many 'Database not ready' messages → Database connection failure"
echo "  - Many 'Error in continuous polling' messages → Exception in poll loop"
echo "  - Missing --continuous flag → Running in single-shot mode with Docker restart"
echo ""
echo "⚠️  HIGH RESTART COUNT = DATABASE CONNECTION ISSUE"
echo "If RestartCount is high (>10), the poller is likely:"
echo "  1. Failing to connect to database"
echo "  2. Crashing after 60 seconds of retries"
echo "  3. Docker immediately restarting it"
echo "  4. Repeat = constant CPU usage!"
echo ""
echo "Fix: Check database connection (POSTGRES_HOST, password, network)"
echo ""
echo "To enable debug records (if needed for troubleshooting):"
echo "  docker exec noaa-poller sh -c 'export CAP_POLLER_DEBUG_RECORDS=1'"
echo ""
