#!/bin/bash
set -e

echo "================================================================================"
echo "EAS Station - Fix Audio Squeal Issue"
echo "================================================================================"
echo ""
echo "sample rate mismatches after container separation."
echo ""
echo "The issue affects BOTH SDR and HTTP streams (like iHeart):"
echo "  - SDR: IQ sample rates set to audio rates (~44kHz) instead of ~2.4MHz"
echo "  - HTTP: Audio sample rates set to 16kHz instead of native rate (44.1/48kHz)"
echo ""
echo "This script will:"
echo "  1. Diagnose current configurations for ALL stream types"
echo "  2. Fix IQ sample rates for SDR receivers"
echo "  3. Fix audio sample rates for HTTP/iHeart streams"
echo "  4. Restart the audio service to apply changes"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Running diagnostic..."
echo "--------------------------------------------------------------------------------"

# Run diagnostic first to show what's wrong
docker-compose exec -T alerts-db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-alerts}" < diagnose_all_streams.sql

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Failed to run diagnostic"
    echo "   Check that the database container is running: docker-compose ps alerts-db"
    exit 1
fi

echo ""
read -p "Apply fixes based on diagnostic? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted before applying fixes."
    exit 1
fi

echo ""
echo "Step 2: Applying comprehensive database fixes..."
echo "--------------------------------------------------------------------------------"

# Run the comprehensive SQL fix for ALL stream types
docker-compose exec -T alerts-db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-alerts}" < fix_all_stream_sample_rates.sql

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Failed to apply database fixes"
    echo "   Check the error messages above for details"
    exit 1
fi

echo ""
echo "✅ Database fixes applied successfully!"
echo ""
echo "Step 3: Restarting audio service..."
echo "--------------------------------------------------------------------------------"

# Restart the audio service to pick up the configuration changes
docker-compose restart sdr-service

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Failed to restart audio service"
    echo "   You may need to restart it manually: docker-compose restart sdr-service"
    exit 1
fi

echo ""
echo "✅ Audio service restarted successfully!"
echo ""
echo "================================================================================"
echo "Fix Complete!"
echo "================================================================================"
echo ""
echo "The audio squeal should now be fixed. Please check your Icecast streams at:"
echo "  http://localhost:8001/"
echo ""
echo "If the squeal persists, please check the logs:"
echo "  docker-compose logs -f sdr-service"
echo ""
echo "================================================================================"
