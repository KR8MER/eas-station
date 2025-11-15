#!/bin/bash
# EAS Station Startup Script for Raspberry Pi with GPIO/OLED Support
# This script ensures GPIO devices are accessible to the Docker container

set -e

echo "=== EAS Station - Raspberry Pi GPIO/OLED Startup ==="
echo ""

# Check if running on Raspberry Pi
if [ ! -f /proc/device-tree/model ]; then
    echo "WARNING: Not detected as Raspberry Pi hardware"
    echo "GPIO functionality may not work correctly"
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo "Detected: $(cat /proc/device-tree/model)"
fi

echo ""

# Check for GPIO device files
echo "Checking GPIO device access..."
GPIO_DEVICES_FOUND=0

if [ -e /dev/gpiomem ]; then
    echo "  ✓ /dev/gpiomem found"
    ls -l /dev/gpiomem
    GPIO_DEVICES_FOUND=1
else
    echo "  ✗ /dev/gpiomem NOT FOUND"
fi

if [ -e /dev/gpiochip0 ]; then
    echo "  ✓ /dev/gpiochip0 found"
    ls -l /dev/gpiochip0
    GPIO_DEVICES_FOUND=1
else
    echo "  ✗ /dev/gpiochip0 NOT FOUND (required for Pi 5)"
fi

if [ $GPIO_DEVICES_FOUND -eq 0 ]; then
    echo ""
    echo "ERROR: No GPIO devices found!"
    echo "Your system may not have GPIO support enabled."
    echo ""
    echo "For Raspberry Pi, ensure gpio is enabled in /boot/config.txt"
    exit 1
fi

echo ""

# Check for .env file
if [ ! -f .env ]; then
    echo "WARNING: .env file not found"
    echo "Using .env.example as template..."
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "Created .env from .env.example - please edit with your settings"
    fi
fi

# Check OLED_ENABLED in .env
if grep -q "^OLED_ENABLED=true" .env 2>/dev/null; then
    echo "✓ OLED is enabled in .env"
else
    echo "⚠ OLED_ENABLED not set to true in .env"
    echo "  The OLED will not activate until you enable it."
    echo ""
    read -p "Enable OLED now? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        # Add or update OLED_ENABLED
        if grep -q "^OLED_ENABLED=" .env; then
            sed -i 's/^OLED_ENABLED=.*/OLED_ENABLED=true/' .env
        elif grep -q "^#.*OLED_ENABLED=" .env; then
            sed -i 's/^#.*OLED_ENABLED=.*/OLED_ENABLED=true/' .env
        else
            echo "OLED_ENABLED=true" >> .env
        fi

        # Ensure other OLED settings exist
        grep -q "^OLED_I2C_BUS=" .env || echo "OLED_I2C_BUS=1" >> .env
        grep -q "^OLED_I2C_ADDRESS=" .env || echo "OLED_I2C_ADDRESS=0x3C" >> .env
        grep -q "^OLED_WIDTH=" .env || echo "OLED_WIDTH=128" >> .env
        grep -q "^OLED_HEIGHT=" .env || echo "OLED_HEIGHT=64" >> .env
        grep -q "^OLED_ROTATE=" .env || echo "OLED_ROTATE=0" >> .env
        grep -q "^OLED_DEFAULT_INVERT=" .env || echo "OLED_DEFAULT_INVERT=false" >> .env

        echo "✓ OLED enabled in .env"
    fi
fi

echo ""

# Ensure GPIO devices have proper permissions
if [ -e /dev/gpiomem ]; then
    GPIOMEM_PERMS=$(stat -c "%a" /dev/gpiomem)
    if [ "$GPIOMEM_PERMS" != "666" ]; then
        echo "Fixing /dev/gpiomem permissions for Docker access..."
        sudo chmod 666 /dev/gpiomem 2>/dev/null || echo "  Warning: Could not change permissions (may need sudo)"
    fi
fi

echo "Syncing .env to persistent Docker volume..."

# Ensure volume exists by starting it briefly if needed
if ! docker volume inspect eas-station_app-config &>/dev/null; then
    echo "Creating app-config volume..."
    docker volume create eas-station_app-config
fi

# Copy local .env to persistent volume
# This preserves settings across git pulls and redeployments
docker run --rm \
  -v eas-station_app-config:/app-config \
  -v "$(pwd)/.env:/host-env:ro" \
  alpine sh -c "cp /host-env /app-config/.env && chmod 644 /app-config/.env" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "✓ Configuration synced to persistent volume"
else
    echo "⚠ Warning: Could not sync .env to volume (continuing anyway)"
fi

echo ""
echo "Starting EAS Station with Raspberry Pi GPIO support..."
echo "Using: docker compose -f docker-compose.yml -f docker-compose.pi.yml"
echo ""

# Stop any existing containers
docker compose down 2>/dev/null || true

# Start with Pi override to enable GPIO
exec docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
