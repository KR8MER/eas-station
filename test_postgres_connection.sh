#!/bin/bash
# Quick PostgreSQL connection test for EAS Station

echo "Testing PostgreSQL connection..."
echo ""

# Try common connection methods
echo "Attempt 1: localhost"
if psql -h localhost -p 5432 -U casaos -d casaos -c "SELECT version();" 2>/dev/null; then
    echo "✅ SUCCESS: Use -h localhost"
    exit 0
fi

echo "Attempt 2: 127.0.0.1"
if psql -h 127.0.0.1 -p 5432 -U casaos -d casaos -c "SELECT version();" 2>/dev/null; then
    echo "✅ SUCCESS: Use -h 127.0.0.1"
    exit 0
fi

echo "Attempt 3: Unix socket (no -h)"
if psql -U casaos -d casaos -c "SELECT version();" 2>/dev/null; then
    echo "✅ SUCCESS: Use Unix socket (omit -h parameter)"
    exit 0
fi

echo ""
echo "❌ All connection attempts failed"
echo ""
echo "Troubleshooting steps:"
echo ""
echo "1. Check if PostgreSQL is running:"
echo "   sudo systemctl status postgresql"
echo ""
echo "2. Check PostgreSQL is listening:"
echo "   sudo netstat -tlnp | grep 5432"
echo "   or: sudo ss -tlnp | grep 5432"
echo ""
echo "3. Try connecting as postgres user:"
echo "   sudo -u postgres psql -l"
echo ""
echo "4. Check if database exists:"
echo "   sudo -u postgres psql -c '\l' | grep casaos"
echo ""
echo "5. Check if user exists:"
echo "   sudo -u postgres psql -c '\du' | grep casaos"
echo ""
