#!/bin/bash
# Pull configuration from Docker persistent volume to local .env
# Use this to edit settings that are stored in the volume

set -e

echo "=== Pull Configuration from Docker Volume ==="
echo ""

# Check if volume exists
if ! docker volume inspect eas-station_app-config &>/dev/null; then
    echo "ERROR: Docker volume 'eas-station_app-config' not found"
    echo "The volume is created when you first start the containers."
    echo ""
    echo "Run: ./start-pi.sh"
    exit 1
fi

# Backup existing .env if it exists
if [ -f .env ]; then
    BACKUP_FILE=".env.backup.$(date +%Y%m%d-%H%M%S)"
    cp .env "$BACKUP_FILE"
    echo "✓ Backed up existing .env to $BACKUP_FILE"
fi

# Pull from volume
echo "Pulling configuration from persistent volume..."
docker run --rm \
  -v eas-station_app-config:/app-config \
  -v "$(pwd):/host" \
  alpine sh -c "cp /app-config/.env /host/.env && chmod 644 /host/.env"

if [ $? -eq 0 ]; then
    echo "✓ Configuration pulled from volume to .env"
    echo ""
    echo "You can now edit .env with your changes."
    echo "After editing, run: ./start-pi.sh"
    echo "(start-pi.sh will sync your changes back to the volume)"
else
    echo "✗ Failed to pull configuration"
    exit 1
fi

echo ""
echo "Current OLED settings:"
grep "^OLED_" .env 2>/dev/null || echo "  (no OLED settings found)"
