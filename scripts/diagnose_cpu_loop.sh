#!/bin/bash
# Diagnostic script to identify what's causing constant CPU usage in cap_poller.py

echo "================================"
echo "CAP Poller CPU Usage Diagnostic"
echo "================================"
echo ""

echo "1. Checking if poller is running..."
docker ps | grep noaa-poller
if [ $? -ne 0 ]; then
    echo "   ERROR: noaa-poller container not running!"
    exit 1
fi
echo "   ✓ Container is running"
echo ""

echo "2. Checking command-line arguments..."
docker inspect noaa-poller | grep -A5 "Cmd" | head -10
echo ""

echo "3. Checking recent logs for 'Waiting' messages (should appear every 180s)..."
echo "   Last 20 lines:"
docker logs noaa-poller --tail 20 | grep -E "Waiting|Starting CAP|Polling cycle complete"
echo ""

echo "4. Counting log lines in last 60 seconds..."
docker logs noaa-poller --since 60s | wc -l
echo "   (Should be ~5-10 lines, not hundreds)"
echo ""

echo "5. Checking for error loops..."
docker logs noaa-poller --tail 100 | grep -c "Error in continuous polling"
echo "   (Should be 0, if > 0 then exception loop)"
echo ""

echo "6. Checking CPU usage RIGHT NOW..."
docker stats --no-stream noaa-poller | tail -1
echo ""

echo "7. Checking if radio capture is enabled..."
docker exec noaa-poller env | grep -E "CAP_POLLER_ENABLE_RADIO|RADIO.*="
if [ $? -ne 0 ]; then
    echo "   ✓ No radio variables set (disabled)"
fi
echo ""

echo "8. Checking thread count..."
docker exec noaa-poller ps aux | grep python
echo ""

echo "9. Live monitoring for 30 seconds..."
echo "   Watch the timestamps - should see 'Waiting' message once every 180s"
echo "   If you see rapid-fire logs, that's the problem!"
echo ""
docker logs noaa-poller --follow --tail 5 &
LOG_PID=$!
sleep 30
kill $LOG_PID 2>/dev/null
echo ""

echo "================================"
echo "Diagnostic Complete"
echo "================================"
echo ""
echo "WHAT TO LOOK FOR:"
echo "- If Step 3 shows NO 'Waiting' messages: Loop is not sleeping!"
echo "- If Step 4 shows 100+ lines: Excessive logging/looping"
echo "- If Step 5 shows >0: Exception loop (check Step 3 logs for error)"
echo "- If Step 6 shows >50% CPU: Confirms high usage"
echo "- If Step 9 shows rapid logs: Not sleeping between iterations"
echo ""
echo "NEXT STEPS:"
echo "- Share the output of this script"
echo "- Check if you see 'Waiting 180 seconds' in the logs"
echo "- If NO waiting messages, the sleep is not happening!"
