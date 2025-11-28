#!/bin/bash
set -e

echo "================================================================================"
echo "EAS Station - Fix Audio Squeal Issue"
echo "================================================================================"
echo ""
echo "This script fixes the high-pitched squeal in Icecast streams caused by"
echo "sample rate mismatches after container separation."
echo ""
echo "The issue: RadioReceiver IQ sample rates were set to audio rates (~44kHz)"
echo "instead of proper SDR IQ rates (~2.4MHz), causing the demodulator to"
echo "interpret IQ data incorrectly."
echo ""
echo "This script will:"
echo "  1. Check current radio receiver configurations"
echo "  2. Fix IQ sample rates < 100kHz to proper SDR rate (2.4MHz)"
echo "  3. Restart the audio service to apply changes"
echo ""
read -p "Continue? (y/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]
then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Applying database fixes..."
echo "--------------------------------------------------------------------------------"

# Run the SQL fix inside the database container
docker-compose exec -T alerts-db psql -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-alerts}" < fix_sample_rates.sql

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ ERROR: Failed to apply database fixes"
    echo "   Check that the database container is running: docker-compose ps alerts-db"
    exit 1
fi

echo ""
echo "✅ Database fixes applied successfully!"
echo ""
echo "Step 2: Restarting audio service..."
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
