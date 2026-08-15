#!/bin/bash
# EAS Station - Emergency Alert System
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
#
# This file is part of EAS Station.
#
# EAS Station is dual-licensed software:
# - GNU Affero General Public License v3 (AGPL-3.0) for open-source use
# - Commercial License for proprietary use
#
# You should have received a copy of both licenses with this software.
# For more information, see LICENSE and LICENSE-COMMERCIAL files.
#
# IMPORTANT: This software cannot be rebranded or have attribution removed.
# See NOTICE file for complete terms.
#
# Repository: https://github.com/KR8MER/eas-station

#
# SDR Diagnostic Information Collection Script - Bare Metal Edition
#
# This script collects comprehensive diagnostic information about SDR hardware,
# software configuration, and system status for troubleshooting bare-metal deployments.
#
# Usage:
#   bash scripts/collect_sdr_diagnostics.sh
#   bash scripts/collect_sdr_diagnostics.sh /path/to/output.txt
#

set -e

# Installation directory
INSTALL_DIR="/opt/eas-station"
VENV_DIR="${INSTALL_DIR}/venv"

# Determine output file
if [ -n "$1" ]; then
  OUTPUT_FILE="$1"
else
  OUTPUT_FILE="sdr_diagnostics_$(date +%Y%m%d_%H%M%S).txt"
fi

echo "============================================"
echo "EAS Station SDR Diagnostics Collection"
echo "Bare Metal Deployment Edition"
echo "============================================"
echo ""
echo "Collecting diagnostic information..."
echo "Output will be saved to: $OUTPUT_FILE"
echo ""

# Helper function to run command and capture output
run_command() {
  local title="$1"
  shift
  echo "▶ $title"
  "$@" 2>&1 || echo "  ⚠ Command failed or not available"
}

# Main diagnostic collection
{
  echo "============================================"
  echo "EAS Station SDR Diagnostics Report"
  echo "Bare Metal Deployment"
  echo "Generated: $(date)"
  echo "============================================"
  echo ""
  
  echo "### SYSTEM INFORMATION ###"
  echo ""
  run_command "Hostname" hostname
  echo ""
  run_command "Operating System" uname -a
  echo ""
  run_command "OS Release Info" cat /etc/os-release
  echo ""
  run_command "Systemd Version" systemctl --version | head -1
  echo ""
  
  echo ""
  echo "### USB HARDWARE DETECTION ###"
  echo ""
  run_command "All USB Devices" lsusb
  echo ""
  run_command "SDR-Related USB Devices" lsusb | grep -E "RTL|Airspy|Realtek" || echo "  No SDR devices found via lsusb"
  echo ""
  run_command "USB Device Details" lsusb -v 2>/dev/null | grep -A 20 -E "RTL|Airspy" || echo "  No detailed USB info available"
  echo ""
  
  echo ""
  echo "### SOAPYSDR DEVICE DETECTION ###"
  echo ""
  if [ -f "$VENV_DIR/bin/python" ]; then
    run_command "SoapySDR Device Enumeration (venv)" "$VENV_DIR/bin/python" -c "import SoapySDR; devs = SoapySDR.Device.enumerate(); print('\\n'.join([str(d) for d in devs]) if devs else 'No devices found')"
    echo ""
  fi
  
  run_command "SoapySDR Util - Find Devices" SoapySDRUtil --find
  echo ""
  run_command "SoapySDR Util - Device Info" SoapySDRUtil --info || echo "  No devices to show info for"
  echo ""
  
  echo ""
  echo "### SYSTEMD SERVICE STATUS ###"
  echo ""
  run_command "EAS Station Target Status" systemctl status eas-station.target --no-pager
  echo ""
  run_command "Web Service Status" systemctl status eas-station-web.service --no-pager
  echo ""
  run_command "Poller Service Status" systemctl status eas-station-poller.service --no-pager
  echo ""
  run_command "SDR Hardware Service Status" systemctl status eas-station-sdr.service --no-pager
  echo ""
  run_command "Audio Service Status" systemctl status eas-station-audio.service --no-pager
  echo ""
  
  echo ""
  echo "### SERVICE LOGS (last 50 lines each) ###"
  echo ""
  echo "--- Web Service ---"
  run_command "Web Service Logs" journalctl -u eas-station-web.service -n 50 --no-pager
  echo ""
  
  echo "--- SDR Hardware Service ---"
  run_command "SDR Hardware Service Logs" journalctl -u eas-station-sdr.service -n 50 --no-pager
  echo ""
  
  echo "--- Audio Service ---"
  run_command "Audio Service Logs" journalctl -u eas-station-audio.service -n 50 --no-pager
  echo ""
  
  echo "--- Poller Service (SDR-related) ---"
  run_command "Poller SDR Logs" journalctl -u eas-station-poller.service -n 100 --no-pager | grep -i "sdr\|radio\|receiver" || echo "  No SDR-related logs in poller service"
  echo ""
  
  echo ""
  echo "### DATABASE CONFIGURATION ###"
  echo ""
  echo "--- Radio Receivers ---"
  if [ -f "$VENV_DIR/bin/python" ]; then
    run_command "Radio Receivers Table" sudo -u eas-station "$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from app import app, db
from app_core.models import RadioReceiver
with app.app_context():
    receivers = RadioReceiver.query.all()
    if receivers:
        print('ID | Identifier | Name | Driver | Frequency (MHz) | Sample Rate | Gain | Enabled | Auto-Start')
        print('-' * 100)
        for r in receivers:
            freq_mhz = round(r.frequency_hz / 1000000, 3) if r.frequency_hz else 0
            print(f'{r.id} | {r.identifier} | {r.display_name} | {r.driver} | {freq_mhz} | {r.sample_rate} | {r.gain} | {r.enabled} | {r.auto_start}')
    else:
        print('No radio receivers configured')
" || echo "  Cannot query radio receivers"
  else
    run_command "Radio Receivers Table (psql)" sudo -u postgres psql -d alerts -c "
      SELECT 
        id,
        identifier,
        display_name,
        driver,
        frequency_hz,
        ROUND(frequency_hz::numeric / 1000000, 3) AS frequency_mhz,
        sample_rate,
        gain,
        modulation_type,
        audio_output,
        enabled,
        auto_start
      FROM radio_receivers
      ORDER BY id;
    " || echo "  Cannot connect to database"
  fi
  echo ""
  
  echo "--- Audio Source Configs ---"
  if [ -f "$VENV_DIR/bin/python" ]; then
    run_command "Audio Source Configs" sudo -u eas-station "$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from app import app, db
from app_core.models import AudioSourceConfig
with app.app_context():
    configs = AudioSourceConfig.query.all()
    if configs:
        print('ID | Name | Type | Enabled | Auto-Start')
        print('-' * 80)
        for c in configs:
            print(f'{c.id} | {c.name} | {c.source_type} | {c.enabled} | {c.auto_start}')
    else:
        print('No audio source configs')
" || echo "  Cannot query audio source configs"
  fi
  echo ""
  
  echo ""
  echo "### REDIS STATUS ###"
  echo ""
  run_command "Redis Server Status" systemctl status redis-server.service --no-pager || systemctl status redis.service --no-pager
  echo ""
  run_command "Redis Ping" redis-cli ping
  echo ""
  run_command "Redis Info" redis-cli info server
  echo ""
  run_command "Redis Pub/Sub Channels" redis-cli pubsub channels 'sdr:*'
  echo ""
  run_command "Redis SDR Metrics" redis-cli get sdr:metrics
  echo ""
  run_command "Redis Keys (SDR-related)" redis-cli keys 'sdr:*' || echo "  No SDR keys in Redis"
  echo ""
  
  echo ""
  echo "### SDR DIAGNOSTICS SCRIPT ###"
  echo ""
  if [ -f "$INSTALL_DIR/scripts/sdr_diagnostics.py" ]; then
    run_command "Python SDR Diagnostics" sudo -u eas-station "$VENV_DIR/bin/python" "$INSTALL_DIR/scripts/sdr_diagnostics.py"
  else
    echo "  SDR diagnostics script not found"
  fi
  echo ""
  
  echo ""
  echo "### NETWORK CONNECTIVITY ###"
  echo ""
  run_command "Network Interfaces" ip addr show
  echo ""
  run_command "DNS Resolution" nslookup google.com || ping -c 1 8.8.8.8
  echo ""
  run_command "Localhost Web Service" curl -I http://localhost:5000 2>&1 | head -10 || echo "  Web service not responding on localhost:5000"
  echo ""
  
  echo ""
  echo "### ENVIRONMENT VARIABLES (sanitized) ###"
  echo ""
  echo "Note: Passwords and secrets are redacted"
  echo ""
  if [ -f "$INSTALL_DIR/.env" ]; then
    run_command "EAS Station Config" cat "$INSTALL_DIR/.env" | grep -E "SDR|RADIO|AUDIO|REDIS" | sed 's/PASSWORD=.*/PASSWORD=***REDACTED***/' | sed 's/SECRET=.*/SECRET=***REDACTED***/' | sort || echo "  No SDR/Radio/Audio vars in .env"
  else
    echo "  .env file not found at $INSTALL_DIR/.env"
  fi
  echo ""
  
  echo ""
  echo "### DISK SPACE ###"
  echo ""
  run_command "Disk Usage" df -h
  echo ""
  run_command "Installation Directory Size" du -sh "$INSTALL_DIR" 2>/dev/null || echo "  Cannot check install dir size"
  echo ""
  
  echo ""
  echo "### SYSTEM RESOURCE CHECK ###"
  echo ""
  run_command "Memory Usage" free -h
  echo ""
  run_command "CPU Info" cat /proc/cpuinfo | grep -E "model name|processor|cpu MHz" | head -20
  echo ""
  run_command "Load Average" uptime
  echo ""
  run_command "Top Processes (CPU)" ps aux --sort=-%cpu | head -15
  echo ""
  
  echo ""
  echo "### USB DEVICE MESSAGES (Recent) ###"
  echo ""
  run_command "USB Kernel Messages" dmesg | grep -i usb | tail -50
  echo ""
  run_command "USB Device Permissions" ls -la /dev/bus/usb/*/* 2>/dev/null | grep -E "0bda|1d50" || echo "  No RTL-SDR or Airspy USB devices found in /dev"
  echo ""
  
  echo ""
  echo "### UDEV RULES ###"
  echo ""
  run_command "EAS Station SDR udev Rules" cat /etc/udev/rules.d/99-eas-station-sdr.rules 2>/dev/null || echo "  No EAS Station udev rules found"
  echo ""
  
  echo ""
  echo "============================================"
  echo "DIAGNOSTIC SUMMARY"
  echo "============================================"
  echo ""
  
  # Generate summary
  echo "Quick Status:"
  echo ""
  
  # Check if services are running
  if systemctl is-active --quiet eas-station.target; then
    echo "✓ EAS Station services are running"
  else
    echo "✗ EAS Station services are not fully running"
  fi
  
  # Check if SDR devices detected
  if lsusb | grep -qE "RTL|Airspy|Realtek"; then
    echo "✓ SDR hardware detected via USB"
  else
    echo "✗ No SDR hardware detected via USB"
  fi
  
  # Check if SoapySDR can see devices
  if SoapySDRUtil --find 2>/dev/null | grep -q "driver"; then
    echo "✓ SoapySDR can enumerate devices"
  else
    echo "✗ SoapySDR cannot find devices"
  fi
  
  # Check if Redis is running
  if systemctl is-active --quiet redis-server.service || systemctl is-active --quiet redis.service; then
    echo "✓ Redis server is running"
  else
    echo "✗ Redis server is not running"
  fi
  
  # Check database has receivers configured
  if [ -f "$VENV_DIR/bin/python" ]; then
    RECEIVER_COUNT=$(sudo -u eas-station "$VENV_DIR/bin/python" -c "
import sys
sys.path.insert(0, '$INSTALL_DIR')
from app import app, db
from app_core.models import RadioReceiver
with app.app_context():
    print(RadioReceiver.query.count())
" 2>/dev/null || echo "0")
    
    if [ "$RECEIVER_COUNT" -gt 0 ]; then
      echo "✓ Radio receivers configured in database ($RECEIVER_COUNT found)"
    else
      echo "⚠ No radio receivers configured in database"
    fi
  fi
  
  echo ""
  echo "============================================"
  echo "End of Diagnostic Report"
  echo "============================================"
  echo ""
  echo "Report saved to: $OUTPUT_FILE"
  echo ""
  echo "If you need help interpreting these results:"
  echo "- Share this file with support or the community"
  echo "- Check documentation: /opt/eas-station/docs/"
  echo "- View logs: journalctl -u eas-station.target -f"
  echo ""
  
} > "$OUTPUT_FILE" 2>&1

echo "✓ Diagnostic collection complete!"
echo "Report saved to: $OUTPUT_FILE"
echo ""
echo "You can view the report with:"
echo "  cat $OUTPUT_FILE"
echo "  less $OUTPUT_FILE"
echo ""
