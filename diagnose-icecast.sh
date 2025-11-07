#!/bin/bash
# Icecast Port 8001 Diagnostic Script

echo "=== Icecast Diagnostic Script ==="
echo ""

echo "1. Checking if Icecast container is running..."
docker ps | grep icecast || echo "   ❌ Icecast container NOT running!"
echo ""

echo "2. Checking if port 8001 is listening..."
netstat -tlnp 2>/dev/null | grep 8001 || ss -tlnp 2>/dev/null | grep 8001 || echo "   ❌ Port 8001 NOT listening!"
echo ""

echo "3. Testing local connection to Icecast..."
timeout 5 curl -I http://localhost:8001 2>&1 || echo "   ❌ Cannot connect locally!"
echo ""

echo "4. Checking Docker port mapping..."
docker port eas-icecast 2>/dev/null || echo "   ❌ Container not found or no port mappings!"
echo ""

echo "5. Checking iptables firewall rules..."
if command -v iptables >/dev/null 2>&1; then
    sudo iptables -L -n | grep -E "(8001|ACCEPT|DROP)" || echo "   No specific rules for 8001"
else
    echo "   ⚠️  iptables not available"
fi
echo ""

echo "6. Checking UFW firewall status..."
if command -v ufw >/dev/null 2>&1; then
    sudo ufw status | grep 8001 || echo "   Port 8001 not in UFW rules"
else
    echo "   ⚠️  UFW not installed"
fi
echo ""

echo "7. Checking firewalld (if installed)..."
if command -v firewall-cmd >/dev/null 2>&1; then
    sudo firewall-cmd --list-ports | grep 8001 || echo "   Port 8001 not in firewalld"
else
    echo "   ⚠️  firewalld not installed"
fi
echo ""

echo "8. Checking recent Icecast logs..."
docker logs --tail 20 eas-icecast 2>&1 || echo "   ❌ Cannot read Icecast logs!"
echo ""

echo "=== Diagnostic Complete ==="
echo ""
echo "Next steps:"
echo "  • If container NOT running: Check 'docker-compose logs icecast'"
echo "  • If port NOT listening: Icecast may have crashed or failed to start"
echo "  • If local connection fails: Icecast configuration issue"
echo "  • If all above work: Firewall blocking external connections"
echo ""
echo "To open port 8001 in UFW firewall:"
echo "  sudo ufw allow 8001/tcp"
echo "  sudo ufw reload"
echo ""
echo "To open port 8001 in firewalld:"
echo "  sudo firewall-cmd --permanent --add-port=8001/tcp"
echo "  sudo firewall-cmd --reload"
