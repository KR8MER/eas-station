#!/bin/bash
# EAS Station Startup Script for Raspberry Pi with GPIO/OLED Support
# This script ensures GPIO devices are accessible to the Docker container

set -e

usage() {
    cat <<EOF
Usage: ./start-pi.sh [options]

Options:
  --force-env-sync   Always copy local .env into the app-config volume (overwrites existing)
  --skip-env-sync    Do not copy local .env into the app-config volume
  -h, --help         Show this message

Without flags the script copies .env into the volume only when it does not
already exist, or when you confirm an overwrite interactively.
EOF
}

FORCE_ENV_SYNC=0
SKIP_ENV_SYNC=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force-env-sync)
            FORCE_ENV_SYNC=1
            ;;
        --skip-env-sync)
            SKIP_ENV_SYNC=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
    shift
done

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
    echo "  ✓ /dev/gpiomem found (Pi 1-4)"
    ls -l /dev/gpiomem
    GPIO_DEVICES_FOUND=1
else
    echo "  ✗ /dev/gpiomem NOT FOUND (normal for Pi 5)"
fi

if [ -e /dev/gpiochip0 ]; then
    echo "  ✓ /dev/gpiochip0 found (Pi 5 lgpio)"
    ls -l /dev/gpiochip0
    GPIO_DEVICES_FOUND=1
else
    echo "  ✗ /dev/gpiochip0 NOT FOUND"
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

# For Pi 5, ensure gpiochip0 is accessible
if [ -e /dev/gpiochip0 ]; then
    GPIOCHIP_GROUP=$(stat -c "%G" /dev/gpiochip0)
    if [ "$GPIOCHIP_GROUP" = "gpio" ]; then
        # Add current user to gpio group if not already a member
        if ! groups | grep -q gpio; then
            echo "Note: Add yourself to gpio group for better permissions:"
            echo "  sudo usermod -a -G gpio $USER"
        fi
    fi
fi

echo "Syncing .env to persistent Docker volume..."

sync_env_to_volume() {
    docker run --rm \
      -v eas-station_app-config:/app-config \
      -v "$(pwd)/.env:/host-env:ro" \
      alpine sh -c "cp /host-env /app-config/.env && chmod 644 /app-config/.env" 2>/dev/null
}

# Ensure volume exists by starting it briefly if needed
if ! docker volume inspect eas-station_app-config &>/dev/null; then
    echo "Creating app-config volume..."
    docker volume create eas-station_app-config
fi

VOLUME_HAS_ENV=0
if docker run --rm -v eas-station_app-config:/app-config alpine sh -c 'test -f /app-config/.env'; then
    VOLUME_HAS_ENV=1
fi

if [ $SKIP_ENV_SYNC -eq 1 ]; then
    echo "Skipping configuration sync (--skip-env-sync specified)"
elif [ $VOLUME_HAS_ENV -eq 1 ] && [ $FORCE_ENV_SYNC -eq 0 ]; then
    echo "Existing configuration detected inside app-config volume."
    read -p "Replace it with the local .env file? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        if sync_env_to_volume; then
            echo "✓ Configuration synced to persistent volume"
        else
            echo "⚠ Warning: Could not sync .env to volume (continuing anyway)"
        fi
    else
        echo "Preserving existing configuration in app-config volume."
    fi
else
    if sync_env_to_volume; then
        echo "✓ Configuration synced to persistent volume"
    else
        echo "⚠ Warning: Could not sync .env to volume (continuing anyway)"
    fi
fi

echo ""
echo "Starting EAS Station with Raspberry Pi GPIO support..."
echo "Using: docker compose -f docker-compose.yml -f docker-compose.pi.yml"
echo ""

# Stop any existing containers
docker compose down 2>/dev/null || true

# Check if we need to rebuild (force rebuild on first run or if images are missing)
NEED_BUILD=0
if ! docker images | grep -q "eas-station.*latest"; then
    echo "Images not found, will build..."
    NEED_BUILD=1
fi

# Check architecture of existing images
if [ $NEED_BUILD -eq 0 ]; then
    IMAGE_ARCH=$(docker image inspect eas-station:latest --format='{{.Architecture}}' 2>/dev/null || echo "unknown")
    HOST_ARCH=$(uname -m)

    if [ "$IMAGE_ARCH" != "arm64" ] && [ "$HOST_ARCH" = "aarch64" ]; then
        echo "⚠️  Architecture mismatch detected!"
        echo "   Image: $IMAGE_ARCH, Host: $HOST_ARCH (ARM64)"
        echo "   Will rebuild images for correct architecture..."
        NEED_BUILD=1
    fi
fi

if [ $NEED_BUILD -eq 1 ]; then
    echo ""
    echo "Building ARM64 images for Raspberry Pi..."
    echo "This may take 10-15 minutes on first run..."
    docker compose -f docker-compose.yml -f docker-compose.pi.yml build --no-cache --pull
    echo "✓ Build complete"
    echo ""
fi

# Start with Pi override to enable GPIO
exec docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
