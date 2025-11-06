#!/bin/bash
# Quick diagnostic script for EAS Station Portainer deployment

echo "=========================================="
echo "EAS Station Portainer Diagnostics"
echo "=========================================="
echo ""

echo "1. Container Status:"
echo "-------------------"
docker ps --filter "name=eas-station" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

echo "2. Detailed Port Mapping:"
echo "------------------------"
docker port eas-station-app-1 2>/dev/null || docker port eas-station_app_1 2>/dev/null || echo "Container not found. Check container name."
echo ""

echo "3. Network Information:"
echo "----------------------"
docker inspect eas-station-app-1 2>/dev/null | grep -A 10 "Networks" || \
docker inspect eas-station_app_1 2>/dev/null | grep -A 10 "Networks" || \
echo "Container not found."
echo ""

echo "4. What's Listening on Port 80:"
echo "-------------------------------"
sudo netstat -tlnp | grep :80 || echo "Nothing listening on port 80"
echo ""

echo "5. What's Listening on Port 5000:"
echo "---------------------------------"
sudo netstat -tlnp | grep :5000 || echo "Nothing listening on port 5000"
echo ""

echo "6. Test Local Access:"
echo "--------------------"
echo "Testing http://localhost:80 ..."
curl -I http://localhost:80 2>&1 | head -5
echo ""
echo "Testing http://localhost:5000 ..."
curl -I http://localhost:5000 2>&1 | head -5
echo ""

echo "=========================================="
echo "Expected Port Mapping: 0.0.0.0:80->5000/tcp"
echo "If you see 0.0.0.0:5000->5000/tcp or just"
echo "0.0.0.0->5000/tcp, Portainer has old config"
echo "=========================================="
