#!/bin/bash
# Verify the entrypoint script inside the running container

echo "==================================="
echo "CHECKING DOCKER IMAGE ENTRYPOINT"
echo "==================================="

# Get the entrypoint from a running container
echo ""
echo "1. Checking docker-entrypoint.sh in the noaa-poller container:"
docker exec eas-station-noaa-poller-1 cat /usr/local/bin/docker-entrypoint.sh | grep -A 2 "HAS_CONFIG"

echo ""
echo "2. Checking if debug line exists in the container:"
docker exec eas-station-noaa-poller-1 grep "🔍 DEBUG" /usr/local/bin/docker-entrypoint.sh && echo "✅ Debug line FOUND" || echo "❌ Debug line NOT FOUND - image wasn't rebuilt!"

echo ""
echo "3. Checking image build info:"
docker inspect eas-station:latest | grep -A 5 "Created"

echo ""
echo "==================================="
