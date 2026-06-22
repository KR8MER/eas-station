#!/bin/bash
# EAS Station Uninstallation Script
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}ℹ️  [INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}✓  [SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}⚠️  [WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}✗  [ERROR]${NC} $1"
}

echo_prompt() {
    echo -e "${CYAN}❯${NC} $1"
}

# Display uninstallation banner
clear
echo -e "${BOLD}${RED}"
cat << "EOF"
╔═══════════════════════════════════════════════════════════════════════╗
║                                                                       ║
║              📡  EAS STATION UNINSTALLATION  📡                       ║
║                                                                       ║
║           Emergency Alert System - Complete Removal                  ║
║                                                                       ║
╚═══════════════════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    echo ""
    echo -e "${YELLOW}Please run:${NC} ${BOLD}sudo ./uninstall.sh${NC}"
    echo ""
    exit 1
fi

# Configuration variables (match install.sh)
INSTALL_DIR="/opt/eas-station"
SERVICE_USER="eas-station"
SERVICE_GROUP="eas-station"
LOG_DIR="/var/log/eas-station"
SYSTEMD_DIR="/etc/systemd/system"

# Warning and confirmation
echo -e "${RED}${BOLD}⚠️  WARNING: THIS WILL COMPLETELY REMOVE EAS STATION ⚠️${NC}"
echo ""
echo -e "${WHITE}This will remove:${NC}"
echo -e "  • All EAS Station services and systemd units"
echo -e "  • Application files in ${INSTALL_DIR}"
echo -e "  • Log files in ${LOG_DIR}"
echo -e "  • Nginx configuration"
echo -e "  • User account: ${SERVICE_USER}"
echo ""
echo -e "${YELLOW}This will ${BOLD}NOT${NC}${YELLOW} remove:${NC}"
echo -e "  • PostgreSQL database (${BOLD}alerts${NC} database)"
echo -e "  • PostgreSQL server"
echo -e "  • Redis server"
echo -e "  • Python packages"
echo -e "  • Nginx server (only EAS Station config removed)"
echo ""
echo -e "${CYAN}You can optionally remove these at the end.${NC}"
echo ""

read -p "$(echo -e ${RED}${BOLD}Are you sure you want to uninstall EAS Station? [y/N]:${NC} )" -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo_info "Uninstallation cancelled"
    exit 0
fi

echo ""
echo -e "${BOLD}${CYAN}Starting uninstallation...${NC}"
echo ""

# Stop all EAS Station services
echo_info "Stopping EAS Station services..."
systemctl stop eas-station.target 2>/dev/null || true
systemctl stop eas-station-web.service 2>/dev/null || true
systemctl stop eas-station-eas.service 2>/dev/null || true
systemctl stop eas-station-audio.service 2>/dev/null || true
systemctl stop eas-station-sdr.service 2>/dev/null || true
# Phase 4 replaced eas-station-hardware.service with five per-subsystem
# units bundled under eas-station-hardware.target; stop both the legacy
# unit (in case of an older install) and the new ones via the target.
systemctl stop eas-station-hardware.service 2>/dev/null || true
systemctl stop eas-station-hardware.target 2>/dev/null || true
systemctl stop eas-station-network.service 2>/dev/null || true
systemctl stop eas-station-zigbee.service 2>/dev/null || true
systemctl stop eas-station-gps.service 2>/dev/null || true
systemctl stop eas-station-displays.service 2>/dev/null || true
systemctl stop eas-station-gpio.service 2>/dev/null || true
systemctl stop eas-station-ipaws-poller.service 2>/dev/null || true
systemctl stop eas-station-noaa-poller.service 2>/dev/null || true
echo_success "Services stopped"

# Disable all EAS Station services
echo_info "Disabling EAS Station services..."
systemctl disable eas-station.target 2>/dev/null || true
systemctl disable eas-station-web.service 2>/dev/null || true
systemctl disable eas-station-eas.service 2>/dev/null || true
systemctl disable eas-station-audio.service 2>/dev/null || true
systemctl disable eas-station-sdr.service 2>/dev/null || true
systemctl disable eas-station-hardware.service 2>/dev/null || true
systemctl disable eas-station-hardware.target 2>/dev/null || true
systemctl disable eas-station-network.service 2>/dev/null || true
systemctl disable eas-station-zigbee.service 2>/dev/null || true
systemctl disable eas-station-gps.service 2>/dev/null || true
systemctl disable eas-station-displays.service 2>/dev/null || true
systemctl disable eas-station-gpio.service 2>/dev/null || true
systemctl disable eas-station-ipaws-poller.service 2>/dev/null || true
systemctl disable eas-station-noaa-poller.service 2>/dev/null || true
echo_success "Services disabled"

# Remove systemd service files
echo_info "Removing systemd service files..."
rm -f ${SYSTEMD_DIR}/eas-station.target
rm -f ${SYSTEMD_DIR}/eas-station-hardware.target
rm -f ${SYSTEMD_DIR}/eas-station-*.service
systemctl daemon-reload
echo_success "Systemd files removed"

# Remove Nginx configuration
echo_info "Removing Nginx configuration..."
if [ -f /etc/nginx/sites-enabled/eas-station ]; then
    rm -f /etc/nginx/sites-enabled/eas-station
    echo_success "Removed Nginx sites-enabled symlink"
fi
if [ -f /etc/nginx/sites-available/eas-station ]; then
    rm -f /etc/nginx/sites-available/eas-station
    echo_success "Removed Nginx sites-available config"
fi
# Test and reload Nginx if it's running
if systemctl is-active --quiet nginx; then
    nginx -t && systemctl reload nginx 2>/dev/null || echo_warning "Nginx reload failed (may need manual intervention)"
    echo_success "Nginx configuration reloaded"
fi

# Remove application directory
echo_info "Removing application directory..."
if [ -d "$INSTALL_DIR" ]; then
    rm -rf "$INSTALL_DIR"
    echo_success "Removed ${INSTALL_DIR}"
else
    echo_warning "Directory ${INSTALL_DIR} not found"
fi

# Remove log directory
echo_info "Removing log directory..."
if [ -d "$LOG_DIR" ]; then
    rm -rf "$LOG_DIR"
    echo_success "Removed ${LOG_DIR}"
else
    echo_warning "Directory ${LOG_DIR} not found"
fi

# Remove service user
echo_info "Removing service user..."
if id "$SERVICE_USER" &>/dev/null; then
    userdel "$SERVICE_USER" 2>/dev/null || true
    echo_success "Removed user: ${SERVICE_USER}"
else
    echo_warning "User ${SERVICE_USER} not found"
fi

# Remove service group (if empty)
if getent group "$SERVICE_GROUP" &>/dev/null; then
    groupdel "$SERVICE_GROUP" 2>/dev/null || echo_warning "Group ${SERVICE_GROUP} may have other members (not removed)"
fi

echo ""
echo -e "${GREEN}${BOLD}✓ EAS Station has been uninstalled${NC}"
echo ""

# Optional cleanup prompts
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${WHITE}  Optional: Remove Dependencies${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""

# PostgreSQL database removal
echo_prompt "Do you want to remove the PostgreSQL database (${BOLD}alerts${NC})? [y/N]:"
read -n 1 -r REMOVE_DB
echo
if [[ $REMOVE_DB =~ ^[Yy]$ ]]; then
    echo_info "Removing PostgreSQL database..."
    sudo -u postgres psql -c "DROP DATABASE IF EXISTS alerts;" 2>/dev/null || echo_warning "Database removal failed"
    sudo -u postgres psql -c "DROP USER IF EXISTS \"eas-station\";" 2>/dev/null || echo_warning "Database user removal failed"
    echo_success "Database removed"
fi
echo ""

# PostgreSQL server removal
echo_prompt "Do you want to remove PostgreSQL server entirely? [y/N]:"
read -n 1 -r REMOVE_PG
echo
if [[ $REMOVE_PG =~ ^[Yy]$ ]]; then
    echo_info "Removing PostgreSQL..."
    systemctl stop postgresql 2>/dev/null || true
    apt-get remove --purge -y postgresql postgresql-* 2>/dev/null || echo_warning "PostgreSQL removal failed"
    rm -rf /etc/postgresql 2>/dev/null || true
    rm -rf /var/lib/postgresql 2>/dev/null || true
    echo_success "PostgreSQL removed"
fi
echo ""

# Redis removal
echo_prompt "Do you want to remove Redis server? [y/N]:"
read -n 1 -r REMOVE_REDIS
echo
if [[ $REMOVE_REDIS =~ ^[Yy]$ ]]; then
    echo_info "Removing Redis..."
    systemctl stop redis-server 2>/dev/null || true
    apt-get remove --purge -y redis-server redis-tools 2>/dev/null || echo_warning "Redis removal failed"
    rm -rf /etc/redis 2>/dev/null || true
    rm -rf /var/lib/redis 2>/dev/null || true
    echo_success "Redis removed"
fi
echo ""

# Nginx removal
echo_prompt "Do you want to remove Nginx web server? [y/N]:"
read -n 1 -r REMOVE_NGINX
echo
if [[ $REMOVE_NGINX =~ ^[Yy]$ ]]; then
    echo_info "Removing Nginx..."
    systemctl stop nginx 2>/dev/null || true
    apt-get remove --purge -y nginx nginx-common 2>/dev/null || echo_warning "Nginx removal failed"
    rm -rf /etc/nginx 2>/dev/null || true
    echo_success "Nginx removed"
fi
echo ""

# Python packages removal
echo_prompt "Do you want to remove Python packages installed by EAS Station? [y/N]:"
read -n 1 -r REMOVE_PYTHON
echo
if [[ $REMOVE_PYTHON =~ ^[Yy]$ ]]; then
    echo_info "Removing Python packages..."
    if [ -f "$INSTALL_DIR/requirements.txt" ]; then
        pip3 uninstall -y -r "$INSTALL_DIR/requirements.txt" 2>/dev/null || echo_warning "Some packages may not have been removed"
        echo_success "Python packages removed (system packages were left intact)"
    else
        echo_warning "Requirements file not found - skipping Python package removal"
        echo_info "You can manually remove packages with: pip3 list | grep -E '(flask|sqlalchemy|redis|psutil)' | awk '{print \$1}' | xargs pip3 uninstall -y"
    fi
fi
echo ""

# Cleanup
echo_info "Running cleanup..."
apt-get autoremove -y 2>/dev/null || true
apt-get autoclean -y 2>/dev/null || true
echo_success "Cleanup complete"

echo ""
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  ✓ Uninstallation Complete${NC}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "${WHITE}EAS Station has been completely removed from your system.${NC}"
echo ""
echo -e "${DIM}If you reinstall later, you may want to keep the PostgreSQL database${NC}"
echo -e "${DIM}for historical alert data.${NC}"
echo ""
