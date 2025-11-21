#!/bin/bash
# IPv6 Diagnostics Script for easstation.com
# Run this on your Vultr server to diagnose IPv6 connectivity

echo "=========================================="
echo "EAS Station IPv6 Diagnostics"
echo "=========================================="
echo ""

echo "1. IPv6 System Status"
echo "----------------------------------------"
echo "IPv6 enabled? (should be 0):"
sysctl net.ipv6.conf.all.disable_ipv6
echo ""

echo "2. IPv6 Addresses on Network Interfaces"
echo "----------------------------------------"
ip -6 addr show
echo ""

echo "3. IPv6 Routes"
echo "----------------------------------------"
ip -6 route show
echo ""

echo "4. Check for 2001:19f0:5c00:2aeb:5400:5ff:febe:5432"
echo "----------------------------------------"
if ip -6 addr show | grep -q "2001:19f0:5c00:2aeb:5400:5ff:febe:5432"; then
    echo "✓ IPv6 address is assigned to an interface"
    ip -6 addr show | grep "2001:19f0:5c00:2aeb:5400:5ff:febe:5432" -A 1 -B 1
else
    echo "✗ IPv6 address NOT found on any interface!"
    echo "This is why external connections fail."
fi
echo ""

echo "5. Docker IPv6 Configuration"
echo "----------------------------------------"
echo "Docker daemon config:"
if [ -f /etc/docker/daemon.json ]; then
    cat /etc/docker/daemon.json
else
    echo "✗ /etc/docker/daemon.json does NOT exist"
fi
echo ""

echo "6. Docker Networks with IPv6"
echo "----------------------------------------"
docker network ls
echo ""
docker network inspect bridge | grep -i ipv6 || echo "Default bridge: IPv6 NOT enabled"
echo ""

echo "7. Test IPv6 Connectivity from Server"
echo "----------------------------------------"
echo "Ping Google DNS over IPv6:"
ping6 -c 2 2001:4860:4860::8888 2>&1 || echo "✗ Cannot ping IPv6 addresses"
echo ""

echo "8. Firewall Status (UFW)"
echo "----------------------------------------"
if command -v ufw >/dev/null 2>&1; then
    sudo ufw status verbose | grep -E "(80|443|Status)"
else
    echo "UFW not installed"
fi
echo ""

echo "9. ip6tables Rules"
echo "----------------------------------------"
echo "INPUT chain (port 443):"
sudo ip6tables -L INPUT -n -v | grep -E "(Chain|443|policy)" || echo "No rules found"
echo ""

echo "10. Listening Ports (IPv6)"
echo "----------------------------------------"
echo "Services listening on IPv6 ports 80 and 443:"
sudo netstat -tlnp 2>/dev/null | grep -E ":::(80|443)" || ss -tlnp 2>/dev/null | grep -E ":::(80|443)" || echo "No listeners found"
echo ""

echo "=========================================="
echo "Diagnostics Complete"
echo "=========================================="
echo ""
echo "What to look for:"
echo "  ✓ IPv6 address 2001:19f0:5c00:2aeb:5400:5ff:febe:5432 assigned"
echo "  ✓ Can ping IPv6 addresses"
echo "  ✓ Firewall allows ports 80 and 443"
echo "  ✓ Something listening on :::80 and :::443"
echo ""
echo "If any checks fail, see docs/troubleshooting/FIX_IPV6_CONNECTIVITY.md"
