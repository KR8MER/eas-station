#!/bin/bash
# EAS Station Update Script
# This script pulls the latest changes and rebuilds the container

set -e

echo "======================================"
echo "EAS Station Update Script"
echo "======================================"
echo ""

cd /home/user/eas-station

echo "Step 1: Pulling latest changes from Git..."
git fetch origin
git pull origin claude/update-docs-and-todos-011CUqEUamfTp5er4Q41FgTR

echo ""
echo "Step 2: Stopping containers..."
docker compose down || docker-compose down

echo ""
echo "Step 3: Rebuilding with latest code..."
docker compose build --no-cache || docker-compose build --no-cache

echo ""
echo "Step 4: Starting containers..."
docker compose up -d || docker-compose up -d

echo ""
echo "======================================"
echo "Update Complete!"
echo "======================================"
echo ""
echo "The stack.env editor should now work."
echo "Access your EAS Station at: http://omv.local:5000/admin"
echo ""
echo "To view logs, run:"
echo "  docker compose logs -f"
echo ""
