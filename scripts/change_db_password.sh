#!/bin/bash
# Script to change PostgreSQL database password
# Copyright (c) 2025 Timothy Kramer (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
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

echo_header() {
    echo ""
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  $1${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════${NC}"
    echo ""
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    echo ""
    echo -e "${YELLOW}Please run:${NC} ${BOLD}sudo $0${NC}"
    echo ""
    exit 1
fi

echo_header "PostgreSQL Password Change Script"

# Default values
DB_USER="eas-station"
DB_NAME="alerts"
INSTALL_DIR="/opt/eas-station"
ENV_FILE="$INSTALL_DIR/.env"

# Get parameters
if [ $# -eq 2 ]; then
    DB_USER="$1"
    NEW_PASSWORD="$2"
elif [ $# -eq 1 ]; then
    NEW_PASSWORD="$1"
else
    echo_error "Usage: sudo $0 [username] <new_password>"
    echo ""
    echo "Examples:"
    echo "  sudo $0 'myNewPassword123'"
    echo "  sudo $0 eas-station 'myNewPassword123'"
    echo ""
    exit 1
fi

echo_info "Database user: ${BOLD}$DB_USER${NC}"
echo_info "Database name: ${BOLD}$DB_NAME${NC}"
echo ""

# Verify PostgreSQL is installed
if ! command -v psql &> /dev/null; then
    echo_error "PostgreSQL (psql) is not installed or not in PATH"
    exit 1
fi

# Change the PostgreSQL password
echo_info "Changing PostgreSQL password for user '$DB_USER'..."

if sudo -u postgres psql -c "ALTER USER \"$DB_USER\" WITH PASSWORD '$NEW_PASSWORD';" 2>&1; then
    echo_success "PostgreSQL password changed successfully"
else
    echo_error "Failed to change PostgreSQL password"
    echo_info "Make sure PostgreSQL is running: sudo systemctl status postgresql"
    exit 1
fi

# Update .env file if it exists
if [ -f "$ENV_FILE" ]; then
    echo_info "Updating DATABASE_URL in $ENV_FILE..."
    
    # Backup .env file
    cp "$ENV_FILE" "$ENV_FILE.backup.$(date +%Y%m%d-%H%M%S)"
    echo_success "Backed up .env file"
    
    # URL-encode the password for DATABASE_URL
    # Use Python for proper URL encoding
    ENCODED_PASSWORD=$(python3 -c "from urllib.parse import quote; print(quote('$NEW_PASSWORD', safe=''))")
    
    # Construct new DATABASE_URL
    NEW_DATABASE_URL="postgresql+psycopg2://$DB_USER:$ENCODED_PASSWORD@localhost:5432/$DB_NAME"
    
    # Update or add DATABASE_URL in .env file
    if grep -q "^DATABASE_URL=" "$ENV_FILE"; then
        # Update existing DATABASE_URL
        sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$NEW_DATABASE_URL|" "$ENV_FILE"
        echo_success "Updated DATABASE_URL in .env file"
    else
        # Add DATABASE_URL if it doesn't exist
        echo "DATABASE_URL=$NEW_DATABASE_URL" >> "$ENV_FILE"
        echo_success "Added DATABASE_URL to .env file"
    fi
    
    # Set proper ownership
    chown eas-station:eas-station "$ENV_FILE"
    
    echo_info "New DATABASE_URL (password masked):"
    echo "  postgresql+psycopg2://$DB_USER:***@localhost:5432/$DB_NAME"
else
    echo_warning ".env file not found at $ENV_FILE"
    echo_info "You'll need to manually update DATABASE_URL in your .env file:"
    ENCODED_PASSWORD=$(python3 -c "from urllib.parse import quote; print(quote('$NEW_PASSWORD', safe=''))")
    echo ""
    echo "  DATABASE_URL=postgresql+psycopg2://$DB_USER:$ENCODED_PASSWORD@localhost:5432/$DB_NAME"
    echo ""
fi

# Test the connection
echo ""
echo_info "Testing database connection..."
if PGPASSWORD="$NEW_PASSWORD" psql -U "$DB_USER" -h localhost -d "$DB_NAME" -c "SELECT 1;" &> /dev/null; then
    echo_success "Database connection test successful!"
else
    echo_error "Database connection test failed"
    echo_info "Check PostgreSQL logs: sudo journalctl -u postgresql -n 50"
    exit 1
fi

# Restart EAS Station services if systemd target exists
if systemctl list-unit-files | grep -q "eas-station.target"; then
    echo ""
    echo_info "Restarting EAS Station services to apply new password..."
    systemctl restart eas-station.target
    sleep 3
    
    if systemctl is-active --quiet eas-station.target; then
        echo_success "EAS Station services restarted successfully"
    else
        echo_warning "Some services may have failed to start"
        echo_info "Check status: sudo systemctl status eas-station.target"
    fi
fi

echo ""
echo_header "Password Change Complete"
echo_success "PostgreSQL password for user '$DB_USER' has been changed"
echo_success "DATABASE_URL has been updated in .env file"
echo ""
echo_info "Next steps:"
echo "  1. Check service status: ${BOLD}sudo systemctl status eas-station.target${NC}"
echo "  2. View logs: ${BOLD}sudo journalctl -u eas-station-poller.service -f${NC}"
echo ""
