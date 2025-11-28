#!/bin/bash
# Comprehensive fix for all three audio/SDR issues:
# 1. MP3 streams not showing as mount points in Icecast
# 2. Waterfall display looking wrong (wrong frequency scale)
# 3. High-pitched squeal from SDR audio

set -e

echo "================================================================================"
echo "EAS Station - Comprehensive Audio/SDR Fix"
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

# Check if running in Docker
if [ -f /.dockerenv ]; then
    echo "⚠️  Detected running inside Docker container"
    echo "   Please run this script from the HOST machine, not inside a container"
    exit 1
fi

# Check for docker compose
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DOCKER_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    DOCKER_CMD="docker-compose"
else
    echo "❌ Docker Compose not found. Please install Docker Compose."
    exit 1
fi

echo "Step 1: Running diagnostic to identify issues..."
echo "--------------------------------------------------------------------------------"

$DOCKER_CMD exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql

echo ""
echo "================================================================================
echo ""
read -p "Did you see any ❌ markers in the diagnosis? (y/n): " has_issues

if [ "$has_issues" != "y" ] && [ "$has_issues" != "Y" ]; then
    echo ""
    echo "✅ No issues detected! Your configuration looks correct."
    echo ""
    echo "If you're still experiencing problems, check the following:"
    echo "  - Docker logs: $DOCKER_CMD logs -f sdr-service"
    echo "  - Icecast status: http://localhost:8001/"
    echo "  - Web waterfall: http://localhost:5000/settings/radio"
    echo ""
    exit 0
fi

echo ""
echo "Step 2: Applying fixes to sample rate configuration..."
echo "--------------------------------------------------------------------------------"

$DOCKER_CMD exec -T alerts-db psql -U postgres -d alerts < fix_all_stream_sample_rates.sql

echo ""
echo "✅ Database fixes applied"
echo ""

read -p "Would you like to auto-detect HTTP stream sample rates? (recommended, y/n): " auto_detect

if [ "$auto_detect" == "y" ] || [ "$auto_detect" == "Y" ]; then
    echo ""
    echo "Step 3: Auto-detecting HTTP stream sample rates..."
    echo "--------------------------------------------------------------------------------"

    if [ -f "./detect_stream_sample_rates.sh" ]; then
        bash ./detect_stream_sample_rates.sh
    else
        echo "⚠️  detect_stream_sample_rates.sh not found, skipping auto-detection"
    fi
fi

echo ""
echo "Step 4: Restarting services to apply changes..."
echo "--------------------------------------------------------------------------------"

echo "Restarting sdr-service (audio processing)..."
$DOCKER_CMD restart sdr-service

echo "Waiting for service to start..."
sleep 3

echo ""
echo "✅ Services restarted"
echo ""

echo "Step 5: Verifying fixes..."
echo "--------------------------------------------------------------------------------"

$DOCKER_CMD exec -T alerts-db psql -U postgres -d alerts < diagnose_all_streams.sql

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
echo "   → $DOCKER_CMD logs -f sdr-service"
echo ""
echo "If issues persist, check:"
echo "  - SDR device is connected (lsusb)"
echo "  - Antenna is connected properly"
echo "  - Frequency is correct for your location"
echo ""
echo "================================================================================"
