# Database Utilities

This directory contains database management and troubleshooting scripts for EAS Station™.

## Scripts

### `init_database.sh` - Initialize Database Schema

Comprehensive database initialization script that:
1. Fixes PostgreSQL permissions (PostgreSQL 15+ compatibility)
2. Runs all Alembic migrations to create tables
3. Verifies critical tables exist

**Usage:**
```bash
# Make the script executable
chmod +x scripts/database/init_database.sh

# As root (recommended for first-time setup)
sudo ./scripts/database/init_database.sh

# As eas-station user (if already configured)
./scripts/database/init_database.sh
```

**When to use:**
- During initial installation
- After upgrading PostgreSQL
- When tables are missing or database needs reinitialization
- After database restore

---

### `fix_database_permissions.sh` - Fix PostgreSQL Permissions

Standalone script to fix PostgreSQL permission issues without running migrations.

**Usage:**
```bash
# Make the script executable
chmod +x scripts/database/fix_database_permissions.sh

# Run the script as root
sudo ./scripts/database/fix_database_permissions.sh
```

**When to use:**
- When you see "permission denied for schema public" errors
- After upgrading to PostgreSQL 15+
- When migration or table creation fails with permission errors

**What it fixes:**
- Grants CREATE and ALL privileges on public schema
- Sets schema ownership to eas_station user
- Grants privileges on existing tables and sequences
- Sets default privileges for future objects

---

## Common Issues

### "permission denied for schema public"

**Cause:** PostgreSQL 15+ changed default permissions on the public schema.

**Solution:**
```bash
sudo ./scripts/database/fix_database_permissions.sh
sudo ./scripts/database/init_database.sh
```

### "relation does not exist" errors

**Cause:** Database tables haven't been created by migrations.

**Solution:**
```bash
# Fix permissions first
sudo ./scripts/database/fix_database_permissions.sh

# Then run migrations
cd /opt/eas-station
sudo -u eas-station /opt/eas-station/venv/bin/alembic upgrade head

# Or use the init script
sudo ./scripts/database/init_database.sh
```

### Tables missing after migration

**Debugging steps:**
```bash
# Check current migration version
cd /opt/eas-station
sudo -u eas-station /opt/eas-station/venv/bin/alembic current

# View migration history
sudo -u eas-station /opt/eas-station/venv/bin/alembic history

# Check for failed migrations
sudo -u eas-station /opt/eas-station/venv/bin/alembic upgrade head --verbose

# Verify tables exist
sudo -u postgres psql -d alerts -c "\dt"
```

---

## Manual Database Reset (DESTRUCTIVE)

**⚠️ WARNING: This will DELETE ALL DATA!**

Only use if you need to completely reset the database:

```bash
# Stop services
sudo systemctl stop eas-station.target

# Drop and recreate database
sudo -u postgres psql -c "DROP DATABASE IF EXISTS alerts;"
sudo -u postgres psql -c "CREATE DATABASE alerts;"

# Fix permissions
sudo ./scripts/database/fix_database_permissions.sh

# Initialize schema
sudo ./scripts/database/init_database.sh

# Start services
sudo systemctl start eas-station.target
```

---

## Environment Variables

These scripts respect the following environment variables:

- `INSTALL_DIR` - Installation directory (default: `/opt/eas-station`)
- `SERVICE_USER` - Service user (default: `eas-station`)
- `POSTGRES_DB` - Database name (default: `alerts`)
- `POSTGRES_USER` - Database user (default: `eas_station`)
- `VENV_DIR` - Python virtual environment directory (default: `$INSTALL_DIR/venv`)

**Example:**
```bash
POSTGRES_DB=mydb POSTGRES_USER=myuser sudo ./scripts/database/init_database.sh
```
