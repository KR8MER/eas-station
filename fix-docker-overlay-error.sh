#!/bin/bash
# Fix Docker overlay2 corruption issue on Raspberry Pi
# This script performs a complete Docker cleanup and rebuild

set -e

echo "=================================================="
echo "Docker Overlay2 Corruption Fix"
echo "=================================================="
echo ""
echo "⚠️  WARNING: This will remove ALL Docker containers and images!"
echo "⚠️  You will need to rebuild everything (takes 10-15 min on Pi 5)"
echo ""
read -p "Continue? (yes/NO): " -r
if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Step 1: Stopping all Docker containers..."
sudo docker compose -f docker-compose.yml -f docker-compose.pi.yml down -v 2>/dev/null || true
sudo docker stop $(sudo docker ps -aq) 2>/dev/null || true
sudo docker rm -f $(sudo docker ps -aq) 2>/dev/null || true
echo "✓ Containers stopped"

echo ""
echo "Step 2: Stopping Docker daemon..."
sudo systemctl stop docker
sudo systemctl stop docker.socket
echo "✓ Docker daemon stopped"

echo ""
echo "Step 3: Removing corrupted overlay2 layers..."
# Remove the specific corrupted directory
if [ -d "/var/lib/docker/overlay2/bf1c5625b2a72d33a909c0f4f661ad4ad179c2867b2d31e6618ece99f880e13e" ]; then
    sudo rm -rf /var/lib/docker/overlay2/bf1c5625b2a72d33a909c0f4f661ad4ad179c2867b2d31e6618ece99f880e13e
    echo "✓ Removed specific corrupted layer"
fi

# Remove all overlay2 to be safe
echo "Removing all overlay2 layers..."
sudo rm -rf /var/lib/docker/overlay2/*
sudo rm -rf /var/lib/docker/image/*
sudo rm -rf /var/lib/docker/buildkit/*
echo "✓ Overlay2 cleared"

echo ""
echo "Step 4: Restarting Docker daemon..."
sudo systemctl start docker
sleep 5

# Wait for Docker to be ready
echo "Waiting for Docker to be ready..."
for i in {1..30}; do
    if sudo docker info &>/dev/null; then
        echo "✓ Docker is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        echo "✗ Docker failed to start properly"
        echo "Check logs: sudo journalctl -u docker -n 50"
        exit 1
    fi
    sleep 1
done

echo ""
echo "Step 5: Verifying Docker status..."
sudo docker info | grep -E "Operating System|Architecture|Storage Driver"
echo ""

echo "Step 6: Building images for ARM64..."
echo "This will take 10-15 minutes. Please be patient..."
cd /home/user/eas-station

if sudo docker compose -f docker-compose.yml -f docker-compose.pi.yml build --no-cache --pull; then
    echo "✓ Build complete!"
else
    echo "✗ Build failed"
    exit 1
fi

echo ""
echo "Step 7: Starting containers..."
if sudo docker compose -f docker-compose.yml -f docker-compose.pi.yml up -d; then
    echo "✓ Containers started!"
else
    echo "✗ Failed to start containers"
    sudo docker compose logs --tail=50
    exit 1
fi

echo ""
echo "=================================================="
echo "✅ Docker fix complete!"
echo "=================================================="
echo ""
echo "Check status with:"
echo "  sudo docker compose ps"
echo "  sudo docker compose logs -f"
echo ""
