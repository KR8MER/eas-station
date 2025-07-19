#!/bin/bash
# Fix systemd service path for CAP Poller

echo "🔍 Locating cap_poller.py file..."

# Find the actual location of cap_poller.py
CAP_POLLER_PATH=""

# Check common locations
POSSIBLE_PATHS=(
    "/home/pi/noaa_alerts_system/poller/cap_poller.py"
    "/home/pi/noaa_alerts_system/cap_poller.py"
    "/noaa_alerts_system/poller/cap_poller.py"
    "/noaa_alerts_system/cap_poller.py"
)

for path in "${POSSIBLE_PATHS[@]}"; do
    if [[ -f "$path" ]]; then
        CAP_POLLER_PATH="$path"
        echo "✅ Found cap_poller.py at: $path"
        break
    fi
done

# If not found in common locations, search for it
if [[ -z "$CAP_POLLER_PATH" ]]; then
    echo "🔍 Searching for cap_poller.py..."
    CAP_POLLER_PATH=$(find /home/pi -name "cap_poller.py" 2>/dev/null | head -1)
    
    if [[ -n "$CAP_POLLER_PATH" ]]; then
        echo "✅ Found cap_poller.py at: $CAP_POLLER_PATH"
    else
        echo "❌ cap_poller.py not found!"
        echo "📋 Please ensure the file exists and try again."
        exit 1
    fi
fi

# Get the directory containing cap_poller.py
WORKING_DIR=$(dirname "$(dirname "$CAP_POLLER_PATH")")
echo "📁 Working directory: $WORKING_DIR"

# Stop the service
echo "⏹️  Stopping cap-poller service..."
sudo systemctl stop cap-poller

# Create updated systemd service file
echo "📝 Creating updated systemd service file..."

sudo tee /etc/systemd/system/cap-poller.service > /dev/null << EOF
[Unit]
Description=NOAA CAP Alert Poller for OHZ016
After=network.target postgresql.service
Requires=postgresql.service
StartLimitInterval=0

[Service]
Type=simple
User=pi
Group=pi
WorkingDirectory=$WORKING_DIR
Environment=PYTHONPATH=$WORKING_DIR
ExecStart=/usr/bin/python3 $CAP_POLLER_PATH --continuous --interval 300 --log-level INFO
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
ReadWritePaths=$WORKING_DIR/logs
ReadWritePaths=/var/log
ReadWritePaths=/tmp

[Install]
WantedBy=multi-user.target
EOF

# Create logs directory if it doesn't exist
sudo mkdir -p "$WORKING_DIR/logs"
sudo chown pi:pi "$WORKING_DIR/logs"

# Reload systemd
echo "🔄 Reloading systemd..."
sudo systemctl daemon-reload

echo "✅ Service updated successfully!"
echo ""
echo "📋 Updated Configuration:"
echo "  File Path:    $CAP_POLLER_PATH"
echo "  Working Dir:  $WORKING_DIR"
echo "  Log Dir:      $WORKING_DIR/logs"
echo ""
echo "🚀 To start the service:"
echo "  sudo systemctl start cap-poller"
echo ""
echo "📊 To monitor:"
echo "  sudo systemctl status cap-poller"
echo "  sudo journalctl -u cap-poller -f"
EOF
