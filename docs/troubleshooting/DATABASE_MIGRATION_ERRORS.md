# Database Migration Errors - Troubleshooting Guide

**Last Updated:** November 21, 2025

---

## Error: "column location_settings.storage_zone_codes does not exist"

### Symptoms

Application fails to start with error:
```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn)
column location_settings.storage_zone_codes does not exist
```

### Cause

This occurs when the database schema is out of sync with the application code. The SQLAlchemy model expects a column that doesn't exist in the database table.

### Solution

#### Option 1: Run Database Migrations (Recommended)

```bash
# Stop the application
docker compose down

# Run database migrations
docker compose run --rm eas-app flask db upgrade

# Restart the application
docker compose up -d
```

#### Option 2: Apply SQL Fix Manually

If migrations don't work, you can manually fix the database:

```bash
# Connect to the database
docker compose exec alerts-db psql -U easstation easalerts

# Then run:
```

```sql
-- Check if column exists
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'location_settings';

-- If storage_zone_codes exists, drop it
ALTER TABLE location_settings DROP COLUMN IF EXISTS storage_zone_codes;

-- Verify it's gone
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'location_settings'
ORDER BY ordinal_position;
```

Exit psql with `\q`, then restart:

```bash
docker compose restart eas-app
```

#### Option 3: Use the Fix Script

```bash
# From the eas-station directory
docker compose exec -T alerts-db psql -U easstation -d easalerts < scripts/fix_storage_zone_codes.sql

# Restart
docker compose restart eas-app
```

### Verification

Check that the application starts successfully:

```bash
docker compose logs -f eas-app
```

You should see:
```
[INFO] Booting worker with pid: XXX
[INFO] Application startup complete
```

Visit https://localhost in your browser to confirm the web interface loads.

---

## Other Common Migration Errors

### Error: "relation does not exist"

**Cause:** Missing table in database

**Fix:**
```bash
docker compose run --rm eas-app flask db upgrade
```

### Error: "column already exists"

**Cause:** Migration trying to add a column that already exists

**Fix:**
```bash
# Mark migration as complete without running it
docker compose run --rm eas-app flask db stamp head
```

### Error: "multiple heads detected"

**Cause:** Database migration history is branched

**Fix:**
```bash
# Merge migration heads
docker compose run --rm eas-app flask db merge heads

# Then upgrade
docker compose run --rm eas-app flask db upgrade
```

### Error: "Can't locate revision identified by"

**Cause:** Missing migration file or corrupted migration history

**Fix:**
```bash
# Reset to a known good state (CAUTION: this may lose data)
docker compose exec alerts-db psql -U easstation -d easalerts -c "DELETE FROM alembic_version;"

# Re-run all migrations
docker compose run --rm eas-app flask db upgrade
```

---

## Database Backup Before Migrations

**Always backup before running migrations:**

```bash
# Backup database
docker compose exec alerts-db pg_dump -U easstation easalerts | gzip > backup_$(date +%Y%m%d_%H%M%S).sql.gz

# Restore if needed
gunzip -c backup_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T alerts-db psql -U easstation easalerts
```

---

## Reset Database (Nuclear Option)

**WARNING:** This destroys all data. Only use for development/testing.

```bash
# Stop everything
docker compose down

# Remove database volume
docker volume rm eas-station_postgres-data

# Restart (will create fresh database)
docker compose up -d

# Run migrations
docker compose run --rm eas-app flask db upgrade
```

---

## Migration Best Practices

### Creating New Migrations

```bash
# After modifying models.py
docker compose run --rm eas-app flask db migrate -m "describe your change"

# Review the generated migration file
# Edit if needed: app_core/migrations/versions/YYYYMMDD_*.py

# Apply migration
docker compose run --rm eas-app flask db upgrade
```

### Testing Migrations

```bash
# Upgrade
docker compose run --rm eas-app flask db upgrade

# Downgrade (test rollback)
docker compose run --rm eas-app flask db downgrade -1

# Upgrade again
docker compose run --rm eas-app flask db upgrade
```

---

## Getting Help

If you're still stuck:

1. **Check logs:** `docker compose logs -f eas-app`
2. **Check database:** `docker compose exec alerts-db psql -U easstation easalerts`
3. **GitHub Issues:** [Report the issue](https://github.com/KR8MER/eas-station/issues)
4. **Include:**
   - Full error message
   - Output of `docker compose logs eas-app | tail -50`
   - Output of `docker compose exec alerts-db psql -U easstation -d easalerts -c "\d location_settings"`

---

**Last Updated:** November 21, 2025
