#!/bin/bash

echo "=================================="
echo "NOAA Alerts API Debug Script"
echo "=================================="

# Test if APIs are working
echo "Testing API endpoints..."

# Test system status API
echo "1. Testing /api/system_status"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost/api/system_status

# Test alerts API
echo "2. Testing /api/alerts"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost/api/alerts

# Test boundaries API
echo "3. Testing /api/boundaries"
curl -s -o /dev/null -w "HTTP Status: %{http_code}\n" http://localhost/api/boundaries

echo ""
echo "Detailed API responses:"
echo "=================================="

# Get actual responses
echo "System Status Response:"
curl -s http://localhost/api/system_status | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"

echo ""
echo "Alerts Response:"
curl -s http://localhost/api/alerts | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"

echo ""
echo "Boundaries Response:"  
curl -s http://localhost/api/boundaries | python3 -m json.tool 2>/dev/null || echo "Not valid JSON or error"

echo ""
echo "=================================="
echo "Apache Error Log (last 20 lines):"
sudo tail -20 /var/log/apache2/error.log

echo ""
echo "=================================="
echo "Application Log (if exists):"
if [ -f "/home/pi/noaa_alerts_system/logs/noaa_alerts.log" ]; then
    tail -20 /home/pi/noaa_alerts_system/logs/noaa_alerts.log
elif [ -f "/tmp/noaa_alerts.log" ]; then
    tail -20 /tmp/noaa_alerts.log
else
    echo "No application log found"
fi

echo ""
echo "=================================="
echo "Database Connection Test:"
cd /home/pi/noaa_alerts_system
python3 -c "
import os
os.chdir('/home/pi/noaa_alerts_system')
try:
    from app import app, db
    with app.app_context():
        from sqlalchemy import text
        result = db.session.execute(text('SELECT 1'))
        print('? Database connection successful')
except Exception as e:
    print(f'? Database connection failed: {e}')
"

echo ""
echo "=================================="
echo "Flask App Import Test:"
python3 -c "
import os
os.chdir('/home/pi/noaa_alerts_system')
try:
    from app import app
    print('? Flask app import successful')
    print(f'?? Template folder: {app.template_folder}')
    print(f'?? Working directory: {os.getcwd()}')
except Exception as e:
    print(f'? Flask app import failed: {e}')
"