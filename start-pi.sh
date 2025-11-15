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
    echo "  To enable OLED: Add 'OLED_ENABLED=true' to your .env file"
fi

echo ""
echo "Starting EAS Station with Raspberry Pi GPIO support..."
echo "Using: docker compose -f docker-compose.yml -f docker-compose.pi.yml"
echo ""

# Stop any existing containers
docker compose down 2>/dev/null || true

# Start with Pi override to enable GPIO
exec docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d
