#!/bin/bash
# Quick fix for database authentication issues
# Reloads systemd configuration and restarts all EAS Station services

set -e

# Color output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_info() {
    echo -e "${BLUE}ℹ️  ${NC}$1"
}

echo_success() {
    echo -e "${GREEN}✓  ${NC}$1"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  ${NC}$1"
}

echo ""
echo "═══════════════════════════════════════════"
echo " EAS Station Service Restart"
echo "═══════════════════════════════════════════"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_warning "This script should be run with sudo for full functionality"
    echo_info "Attempting to use sudo for privileged commands..."
    SUDO="sudo"
else
    SUDO=""
fi

# Step 1: Reload systemd daemon to pick up service file changes
echo_info "Reloading systemd daemon configuration..."
$SUDO systemctl daemon-reload
echo_success "Systemd daemon reloaded"
echo ""

# Step 2: Stop all services
echo_info "Stopping all EAS Station services..."
$SUDO systemctl stop eas-station.target 2>/dev/null || echo_warning "Target not found or already stopped"
echo_success "Services stopped"
echo ""

# Step 3: Verify .env file exists
echo_info "Checking configuration..."
if [ -f "/opt/eas-station/.env" ]; then
    if grep -q "^DATABASE_URL=" "/opt/eas-station/.env"; then
        echo_success "DATABASE_URL found in .env file"
    else
        echo_warning "DATABASE_URL not found in .env file - services may fail to start"
    fi
else
    echo_warning ".env file not found at /opt/eas-station/.env - services will fail"
fi
echo ""

# Step 4: Start all services
echo_info "Starting all EAS Station services..."
$SUDO systemctl start eas-station.target
echo_success "Services started"
echo ""

# Step 5: Wait a moment for services to initialize
echo_info "Waiting for services to initialize..."
sleep 3
echo ""

# Step 6: Check service status
echo_info "Checking service status..."
echo ""

SERVICES=(
    "eas-station-web"
    "eas-station-poller"
    "eas-station-audio"
)

ALL_RUNNING=true
for service in "${SERVICES[@]}"; do
    if $SUDO systemctl is-active --quiet "$service.service" 2>/dev/null; then
        echo_success "$service.service is running"
    else
        echo_warning "$service.service is NOT running"
        ALL_RUNNING=false
    fi
done

echo ""

if [ "$ALL_RUNNING" = true ]; then
    echo_success "All critical services are running!"
else
    echo_warning "Some services failed to start. Check logs with:"
    echo "  sudo journalctl -u eas-station.target -n 50 --no-pager"
fi

echo ""

# Step 7: Check for database authentication errors
echo_info "Checking for database authentication errors..."
if $SUDO journalctl -u eas-station.target --since "1 minute ago" 2>/dev/null | grep -q "password authentication failed"; then
    echo_warning "Database authentication errors detected in logs"
    echo ""
    echo "  This may indicate an incorrect database user exists."
    echo "  Run the database fix script:"
    echo "    sudo /opt/eas-station/scripts/database/fix_database_user.sh"
    echo ""
else
    echo_success "No database authentication errors detected"
fi

echo ""
echo_info "Next steps:"
echo "  • View logs: sudo journalctl -u eas-station.target -f"
echo "  • Check status: sudo systemctl status eas-station.target"
echo "  • Web interface: http://$(hostname -I | awk '{print $1}'):5000"
echo ""
