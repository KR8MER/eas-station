#!/bin/bash
# Setup script for CAP Poller systemd service

echo "🚀 Setting up CAP Poller as systemd service..."

# Create the systemd service file
sudo tee /etc/systemd/system/cap-poller.service > /dev/null << 'EOF'
[Unit]
Description=NOAA CAP Alert Poller for OHZ016
After=network.target postgresql.service
Requires=postgresql.service
StartLimitInterval=0

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=/noaa_alerts_system
Environment=PYTHONPATH=/noaa_alerts_system
ExecStart=/usr/bin/python3 /noaa_alerts_system/poller/cap_poller.py --continuous --interval 300 --log-level INFO
Restart=always
RestartSec=60
StandardOutput=journal
StandardError=journal

# Resource limits
MemoryMax=512M
CPUQuota=50%

# Security settings
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/noaa_alerts_system/logs
ReadWritePaths=/var/log
ReadWritePaths=/tmp

[Install]
WantedBy=multi-user.target
EOF

# Create log directory if it doesn't exist
sudo mkdir -p /noaa_alerts_system/logs
sudo chown pi:pi /noaa_alerts_system/logs

# Set permissions
sudo chmod 644 /etc/systemd/system/cap-poller.service

# Reload systemd and enable service
sudo systemctl daemon-reload
sudo systemctl enable cap-poller.service

echo "✅ Systemd service created and enabled"
echo ""
echo "🔧 Service Management Commands:"
echo "  Start:   sudo systemctl start cap-poller"
echo "  Stop:    sudo systemctl stop cap-poller"
echo "  Status:  sudo systemctl status cap-poller"
echo "  Logs:    sudo journalctl -u cap-poller -f"
echo "  Restart: sudo systemctl restart cap-poller"
echo ""
echo "📋 Service will:"
echo "  - Poll OHZ016 every 5 minutes (300 seconds)"
echo "  - Auto-restart if it crashes"
echo "  - Start automatically on boot"
echo "  - Log to systemd journal"
echo ""
echo "🚀 To start now: sudo systemctl start cap-poller"
