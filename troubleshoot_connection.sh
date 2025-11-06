#!/bin/bash
# Comprehensive EAS Station Connection Troubleshooting

echo "======================================================"
echo "EAS Station Connection Troubleshooting"
echo "======================================================"
echo ""

echo "1. Container Status:"
echo "-------------------"
docker ps -a --filter "name=eas-station" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
echo ""

echo "2. Detailed Port Mapping:"
echo "------------------------"
CONTAINER=$(docker ps --filter "name=eas-station-app" --format "{{.Names}}" | head -1)
if [ -n "$CONTAINER" ]; then
    docker port $CONTAINER
else
    echo "App container not found!"
fi
echo ""

echo "3. Check if App is Running Inside Container:"
echo "--------------------------------------------"
if [ -n "$CONTAINER" ]; then
    echo "Checking processes inside container..."
    docker exec $CONTAINER ps aux | grep -E "python|gunicorn|flask" || echo "No Python/Flask processes found!"
else
    echo "Cannot check - container not running"
fi
echo ""

echo "4. Container Logs (last 30 lines):"
echo "----------------------------------"
if [ -n "$CONTAINER" ]; then
    docker logs --tail 30 $CONTAINER
else
    echo "Cannot get logs - container not running"
fi
echo ""

echo "5. Network Connectivity - Port 80:"
echo "----------------------------------"
echo "Local test (from server):"
curl -v http://localhost:80 2>&1 | head -20
echo ""

echo "6. What's Listening on Port 80:"
echo "-------------------------------"
sudo netstat -tlnp | grep :80 || sudo ss -tlnp | grep :80 || echo "Nothing listening on port 80"
echo ""

echo "7. Firewall Status:"
echo "------------------"
echo "UFW Status:"
sudo ufw status 2>/dev/null || echo "UFW not installed/active"
echo ""
echo "Firewalld Status:"
sudo firewall-cmd --list-all 2>/dev/null || echo "Firewalld not installed/active"
echo ""

echo "8. Docker Network Info:"
echo "----------------------"
if [ -n "$CONTAINER" ]; then
    docker inspect $CONTAINER --format='{{range .NetworkSettings.Networks}}Network: {{.NetworkID}} IP: {{.IPAddress}}{{end}}'
else
    echo "Container not running"
fi
echo ""

echo "======================================================"
echo "INSTRUCTIONS:"
echo "======================================================"
echo "Run this script and share the output:"
echo "  sudo bash troubleshoot_connection.sh > output.txt 2>&1"
echo ""
echo "Or copy-paste the entire output to share"
echo "======================================================"
