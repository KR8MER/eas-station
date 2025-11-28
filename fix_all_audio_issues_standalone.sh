#!/bin/bash
# Comprehensive fix for all three audio/SDR issues (Standalone PostgreSQL version)
# 1. MP3 streams not showing as mount points in Icecast
# 2. Waterfall display looking wrong (wrong frequency scale)
# 3. High-pitched squeal from SDR audio

set -e

echo "================================================================================"
echo "EAS Station - Comprehensive Audio/SDR Fix (Standalone PostgreSQL)"
echo "================================================================================"
echo ""
echo "This script fixes THREE related issues:"
echo "  1. MP3 streams not appearing as Icecast mount points"
echo "  2. Waterfall display showing wrong frequency scale"
echo "  3. High-pitched squeal/tone from SDR audio"
echo ""
echo "Root cause: RadioReceiver.sample_rate set to audio rate instead of IQ rate"
echo ""
echo "================================================================================"
echo ""

# PostgreSQL connection parameters
echo "PostgreSQL Connection Setup"
echo "--------------------------------------------------------------------------------"
read -p "PostgreSQL host [localhost]: " PG_HOST
PG_HOST=${PG_HOST:-localhost}

read -p "PostgreSQL port [5432]: " PG_PORT
PG_PORT=${PG_PORT:-5432}

read -p "PostgreSQL database name [alerts]: " PG_DB
PG_DB=${PG_DB:-alerts}

read -p "PostgreSQL username [postgres]: " PG_USER
PG_USER=${PG_USER:-postgres}

read -s -p "PostgreSQL password: " PG_PASSWORD
echo ""
echo ""

# Export for psql
export PGPASSWORD="$PG_PASSWORD"

# Test connection
echo "Testing PostgreSQL connection..."
if ! psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" -c "SELECT 1;" > /dev/null 2>&1; then
    echo "❌ Failed to connect to PostgreSQL"
    echo "   Please check your connection parameters and try again"
    exit 1
fi
echo "✅ Connected to PostgreSQL successfully"
echo ""

echo "Step 1: Running diagnostic to identify issues..."
echo "--------------------------------------------------------------------------------"

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" < diagnose_all_streams.sql

echo ""
echo "================================================================================"
echo ""
read -p "Did you see any ❌ markers in the diagnosis? (y/n): " has_issues

if [ "$has_issues" != "y" ] && [ "$has_issues" != "Y" ]; then
    echo ""
    echo "✅ No issues detected! Your configuration looks correct."
    echo ""
    echo "If you're still experiencing problems, check the following:"
    echo "  - Docker logs: sudo docker compose logs -f sdr-service"
    echo "  - Icecast status: http://localhost:8001/"
    echo "  - Web waterfall: http://localhost:5000/settings/radio"
    echo ""
    exit 0
fi

echo ""
echo "Step 2: Applying fixes to sample rate configuration..."
echo "--------------------------------------------------------------------------------"

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" < fix_all_stream_sample_rates.sql

echo ""
echo "✅ Database fixes applied"
echo ""

read -p "Would you like to auto-detect HTTP stream sample rates? (recommended, y/n): " auto_detect

if [ "$auto_detect" == "y" ] || [ "$auto_detect" == "Y" ]; then
    echo ""
    echo "Step 3: Auto-detecting HTTP stream sample rates..."
    echo "--------------------------------------------------------------------------------"

    # Create a temporary version of detect script with our connection params
    if [ -f "./detect_stream_sample_rates.sh" ]; then
        # Modify the script to use our connection parameters
        sed "s/docker-compose exec -T alerts-db psql -U postgres -d alerts/psql -h $PG_HOST -p $PG_PORT -U $PG_USER -d $PG_DB/g" \
            detect_stream_sample_rates.sh > /tmp/detect_stream_sample_rates_standalone.sh
        chmod +x /tmp/detect_stream_sample_rates_standalone.sh
        bash /tmp/detect_stream_sample_rates_standalone.sh
        rm /tmp/detect_stream_sample_rates_standalone.sh
    else
        echo "⚠️  detect_stream_sample_rates.sh not found, skipping auto-detection"
    fi
fi

echo ""
echo "Step 4: Restarting services to apply changes..."
echo "--------------------------------------------------------------------------------"

# Check for docker compose files
if [ -f "docker-compose.pi.yml" ]; then
    echo "Detected Raspberry Pi setup, using pi-specific compose files..."
    COMPOSE_CMD="sudo docker compose -f docker-compose.yml -f docker-compose.pi.yml"
else
    COMPOSE_CMD="sudo docker compose"
fi

echo "Restarting sdr-service (audio processing)..."
$COMPOSE_CMD restart sdr-service

echo "Waiting for service to start..."
sleep 5

echo ""
echo "✅ Services restarted"
echo ""

echo "Step 5: Verifying fixes..."
echo "--------------------------------------------------------------------------------"

psql -h "$PG_HOST" -p "$PG_PORT" -U "$PG_USER" -d "$PG_DB" < diagnose_all_streams.sql

echo ""
echo "================================================================================"
echo "FIX COMPLETE"
echo "================================================================================"
echo ""
echo "Next steps:"
echo ""
echo "1. Check Icecast mount points:"
echo "   → Open: http://localhost:8001/"
echo "   → You should see /stream-name.mp3 mount points listed"
echo ""
echo "2. Check waterfall display:"
echo "   → Open: http://localhost:5000/settings/radio"
echo "   → Frequency axis should show MHz range (e.g., 96.7 - 99.1 MHz)"
echo "   → Waterfall should show colorful spectrum data"
echo ""
echo "3. Check audio quality:"
echo "   → Listen to Icecast streams"
echo "   → Should sound clear, no high-pitched squeal"
echo ""
echo "4. Monitor logs for errors:"
echo "   → $COMPOSE_CMD logs -f sdr-service"
echo ""
echo "If issues persist, check:"
echo "  - SDR device is connected (lsusb)"
echo "  - Antenna is connected properly"
echo "  - Frequency is correct for your location"
echo ""
echo "================================================================================"

# Clean up password from environment
unset PGPASSWORD
