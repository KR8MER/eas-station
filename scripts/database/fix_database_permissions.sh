#!/bin/bash
# Fix PostgreSQL database permissions for EAS Station
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Licensed under AGPL v3 or Commercial License

set -e  # Exit on error

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

echo_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

echo_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo_error "This script must be run as root (use sudo)"
    exit 1
fi

echo_info "Fixing PostgreSQL database permissions for EAS Station..."

# Configuration
DB_NAME="${POSTGRES_DB:-alerts}"
DB_USER="${POSTGRES_USER:-eas-station}"

echo_info "Database: $DB_NAME"
echo_info "User: $DB_USER"

# Check if PostgreSQL is running
if ! systemctl is-active --quiet postgresql; then
    echo_info "Starting PostgreSQL service..."
    systemctl start postgresql
fi

# Check if database exists
if ! sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
    echo_error "Database '$DB_NAME' does not exist!"
    echo_info "Please run the full install.sh script first."
    exit 1
fi

# Check if user exists
if ! sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename = '$DB_USER'" | grep -q 1; then
    echo_error "Database user '$DB_USER' does not exist!"
    echo_info "Please run the full install.sh script first."
    exit 1
fi

# Configure PostgreSQL authentication (pg_hba.conf) if needed
echo_info "Checking PostgreSQL authentication configuration..."

# Detect PostgreSQL version to find the correct pg_hba.conf location
PG_VERSION=$(sudo -u postgres psql -tAc "SELECT version();" | grep -oP 'PostgreSQL \K[0-9]+' | head -1)
if [ -z "$PG_VERSION" ]; then
    # Fallback: try common versions
    for v in 17 16 15 14 13; do
        if [ -d "/etc/postgresql/$v" ]; then
            PG_VERSION=$v
            break
        fi
    done
fi

if [ -n "$PG_VERSION" ]; then
    PG_HBA_CONF="/etc/postgresql/$PG_VERSION/main/pg_hba.conf"
    
    if [ -f "$PG_HBA_CONF" ]; then
        # Backup the original pg_hba.conf
        if [ ! -f "${PG_HBA_CONF}.backup" ]; then
            cp "$PG_HBA_CONF" "${PG_HBA_CONF}.backup"
            echo_info "Backed up pg_hba.conf to ${PG_HBA_CONF}.backup"
        fi
        
        # Check if eas-station authentication rule already exists
        if ! grep -q "^host.*alerts.*\"eas-station\".*md5" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*\"eas-station\".*scram-sha-256" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*eas_station.*md5" "$PG_HBA_CONF" && \
           ! grep -q "^host.*alerts.*eas_station.*scram-sha-256" "$PG_HBA_CONF"; then
            
            echo_info "Adding authentication rules for eas-station user..."
            # Insert before the first "local all" line to ensure it takes precedence
            sed -i '/^# TYPE.*DATABASE.*USER.*ADDRESS.*METHOD/a\
# EAS Station authentication (added by fix_database_permissions.sh)\
host    alerts          "eas-station"   127.0.0.1/32            scram-sha-256\
host    alerts          "eas-station"   ::1/128                 scram-sha-256' "$PG_HBA_CONF"
            
            # Reload PostgreSQL to apply changes
            systemctl reload postgresql
            echo_success "PostgreSQL authentication configured and reloaded"
        else
            echo_info "Authentication rule for eas-station already exists"
        fi
    else
        echo_warning "pg_hba.conf not found at expected location: $PG_HBA_CONF"
    fi
else
    echo_warning "Could not detect PostgreSQL version"
fi

echo_info "Granting schema privileges (required for PostgreSQL 15+)..."
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;" || echo_warning "Failed to grant schema privileges"
sudo -u postgres psql -d "$DB_NAME" -c "GRANT CREATE ON SCHEMA public TO $DB_USER;" || echo_warning "Failed to grant CREATE privilege"
sudo -u postgres psql -d "$DB_NAME" -c "ALTER SCHEMA public OWNER TO $DB_USER;" || echo_warning "Failed to set schema owner"

echo_info "Granting privileges on existing tables and sequences..."
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;" || echo_warning "No tables to grant privileges on"
sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;" || echo_warning "No sequences to grant privileges on"

echo_info "Setting default privileges for future objects..."
sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;" || echo_warning "Failed to set default table privileges"
sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;" || echo_warning "Failed to set default sequence privileges"

echo_info "Ensuring PostGIS extensions are installed..."
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS postgis;" || echo_warning "PostGIS extension already exists or failed to create"
sudo -u postgres psql -d "$DB_NAME" -c "CREATE EXTENSION IF NOT EXISTS postgis_topology;" || echo_warning "PostGIS topology extension already exists or failed to create"

echo_success "Database permissions fixed!"
echo_info ""
echo_info "Next steps:"
echo_info "1. Run database migrations: cd /opt/eas-station && sudo -u eas-station /opt/eas-station/venv/bin/alembic upgrade head"
echo_info "2. Restart the EAS Station services: systemctl restart eas-station.target"
echo_info ""
echo_info "If tables are still missing, you may need to run the migrations manually."
