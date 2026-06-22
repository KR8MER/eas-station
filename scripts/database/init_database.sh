#!/bin/bash
# Initialize EAS Station database schema
# Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)
# Licensed under AGPL v3 or Commercial License
#
# This script:
# 1. Ensures database permissions are correct
# 2. Runs Alembic migrations to create all tables
# 3. Verifies database connectivity

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

# Configuration
INSTALL_DIR="${INSTALL_DIR:-/opt/eas-station}"
SERVICE_USER="${SERVICE_USER:-eas-station}"
VENV_DIR="${VENV_DIR:-$INSTALL_DIR/venv}"
DB_NAME="${POSTGRES_DB:-alerts}"
DB_USER="${POSTGRES_USER:-eas-station}"

# Check if running as root or service user
if [ "$EUID" -eq 0 ]; then
    IS_ROOT=true
    echo_info "Running as root"
else
    IS_ROOT=false
    if [ "$USER" != "$SERVICE_USER" ]; then
        echo_warning "Not running as root or $SERVICE_USER user. Some operations may fail."
    fi
fi

echo_info "Initializing EAS Station database..."
echo_info "Database: $DB_NAME"
echo_info "User: $DB_USER"
echo_info "Install directory: $INSTALL_DIR"

# Check if PostgreSQL is accessible
if ! command -v psql &> /dev/null; then
    echo_error "psql command not found. Is PostgreSQL installed?"
    exit 1
fi

# Step 1: Fix permissions (only if running as root)
if [ "$IS_ROOT" = true ]; then
    echo_info "Step 1: Fixing database permissions..."
    
    # Check if database exists
    if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
        echo_info "Granting schema privileges..."
        sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL ON SCHEMA public TO $DB_USER;" 2>/dev/null || echo_warning "Could not grant ALL on schema"
        sudo -u postgres psql -d "$DB_NAME" -c "GRANT CREATE ON SCHEMA public TO $DB_USER;" 2>/dev/null || echo_warning "Could not grant CREATE"
        sudo -u postgres psql -d "$DB_NAME" -c "ALTER SCHEMA public OWNER TO $DB_USER;" 2>/dev/null || echo_warning "Could not alter schema owner"
        
        echo_info "Granting privileges on existing objects..."
        sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO $DB_USER;" 2>/dev/null || true
        sudo -u postgres psql -d "$DB_NAME" -c "GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO $DB_USER;" 2>/dev/null || true
        
        echo_info "Setting default privileges..."
        sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $DB_USER;" 2>/dev/null || true
        sudo -u postgres psql -d "$DB_NAME" -c "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $DB_USER;" 2>/dev/null || true
        
        echo_success "Permissions updated"
    else
        echo_error "Database '$DB_NAME' does not exist!"
        echo_info "Please run the full install.sh script first."
        exit 1
    fi
else
    echo_warning "Step 1: Skipping permission fix (not running as root)"
fi

# Step 2: Run Alembic migrations
echo_info "Step 2: Running database migrations..."

if [ ! -d "$INSTALL_DIR" ]; then
    echo_error "Installation directory not found: $INSTALL_DIR"
    exit 1
fi

if [ ! -f "$VENV_DIR/bin/alembic" ]; then
    echo_error "Alembic not found in virtual environment: $VENV_DIR/bin/alembic"
    exit 1
fi

cd "$INSTALL_DIR"

# Run as service user if we're root, otherwise run as current user
if [ "$IS_ROOT" = true ]; then
    echo_info "Running migrations as $SERVICE_USER..."
    sudo -u "$SERVICE_USER" "$VENV_DIR/bin/alembic" upgrade head
else
    echo_info "Running migrations as current user..."
    "$VENV_DIR/bin/alembic" upgrade head
fi

echo_success "Migrations completed"

# Step 3: Verify database tables
echo_info "Step 3: Verifying database tables..."

EXPECTED_TABLES=(
    "rwt_schedule_config"
    "screen_rotations"
    "display_screens"
    "roles"
    "users"
    "alert_sources"
)

MISSING_TABLES=()

for table in "${EXPECTED_TABLES[@]}"; do
    if [ "$IS_ROOT" = true ]; then
        EXISTS=$(sudo -u postgres psql -d "$DB_NAME" -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '$table');")
    else
        # Try to check without sudo
        EXISTS=$(psql -d "$DB_NAME" -tAc "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_schema = 'public' AND table_name = '$table');" 2>/dev/null || echo "f")
    fi
    
    if [ "$EXISTS" = "t" ]; then
        echo_success "✓ Table '$table' exists"
    else
        echo_warning "✗ Table '$table' is missing"
        MISSING_TABLES+=("$table")
    fi
done

if [ ${#MISSING_TABLES[@]} -gt 0 ]; then
    echo_warning ""
    echo_warning "Some tables are missing. This may be expected if migrations haven't fully completed."
    echo_warning "Missing tables: ${MISSING_TABLES[*]}"
    echo_info ""
    echo_info "If you continue to have issues, try:"
    echo_info "1. Check the migration logs above for errors"
    echo_info "2. Verify your database connection settings in .env"
    echo_info "3. Run: alembic current - to see current migration version"
    echo_info "4. Run: alembic history - to see all available migrations"
else
    echo_success ""
    echo_success "All critical tables verified!"
fi

echo_info ""
echo_info "Database initialization complete!"
echo_info ""
echo_info "You can now start the EAS Station services:"
if [ "$IS_ROOT" = true ]; then
    echo_info "  systemctl restart eas-station.target"
else
    echo_info "  sudo systemctl restart eas-station.target"
fi
