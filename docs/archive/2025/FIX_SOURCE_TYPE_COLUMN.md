# Fix for Missing source_type Column Error

## Problem

The application is failing with the following error:

```
sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedColumn) column radio_receivers.source_type does not exist
```

This error occurs because the database schema is missing the `source_type` column that was added to the `RadioReceiver` model to support both SDR and streaming radio sources.

## Root Cause

The Alembic migration `20251105_add_stream_support_to_receivers` exists in the codebase but has not been applied to the database. This migration adds:

1. `source_type` column (VARCHAR(16), NOT NULL, default='sdr')
2. `stream_url` column (VARCHAR(512), nullable)
3. Makes `driver`, `frequency_hz`, and `sample_rate` columns nullable (since streaming sources don't need these)

## Solutions

You have three options to fix this issue:

### Option 1: Run Alembic Migration (Recommended)

If you're using Docker Compose, the migrations should run automatically on container startup via the `docker-entrypoint.sh` script.

To manually run migrations:

```bash
# Using Docker Compose
docker-compose exec app python -m alembic upgrade head

# Or restart the containers to trigger automatic migration
docker-compose restart app
```

### Option 2: Use the Standalone Migration Script

A standalone Python script is provided that can apply the migration directly without using Alembic:

```bash
# Make sure you have database credentials set
export POSTGRES_HOST=localhost  # or your database host
export POSTGRES_PASSWORD=your_password

# Run the migration script
python3 scripts/apply_source_type_migration.py
```

The script will:
- Check if the migration has already been applied
- Apply the necessary ALTER TABLE statements
- Update the alembic_version table

### Option 3: Apply SQL Directly

If you prefer to run the SQL manually, connect to your PostgreSQL database and execute:

```sql
-- Add source_type column (defaults to 'sdr' for existing records)
ALTER TABLE radio_receivers
ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'sdr';

-- Add stream_url column (nullable)
ALTER TABLE radio_receivers
ADD COLUMN stream_url VARCHAR(512);

-- Make these columns nullable since streaming sources don't need them
ALTER TABLE radio_receivers ALTER COLUMN driver DROP NOT NULL;
ALTER TABLE radio_receivers ALTER COLUMN frequency_hz DROP NOT NULL;
ALTER TABLE radio_receivers ALTER COLUMN sample_rate DROP NOT NULL;

-- Update alembic version tracking (optional but recommended)
DELETE FROM alembic_version;
INSERT INTO alembic_version (version_num) VALUES ('20251105_add_stream_support_to_receivers');
```

## Verification

After applying the fix, verify it worked:

```bash
# Connect to PostgreSQL
psql -h localhost -U postgres -d alerts

# Check the schema
\d radio_receivers

# You should see source_type and stream_url columns
```

Or restart your application - it should start without the "column does not exist" error.

## Files Involved

- **Model Definition**: `/home/user/eas-station/app_core/models.py:520-591` (RadioReceiver class)
- **Alembic Migration**: `/home/user/eas-station/app_core/migrations/versions/20251105_add_stream_support_to_receivers.py`
- **Standalone Script**: `/home/user/eas-station/apply_source_type_migration.py`
- **Entrypoint**: `/home/user/eas-station/docker-entrypoint.sh` (runs migrations automatically)

## Prevention

To prevent this issue in the future:

1. Always run `alembic upgrade head` after pulling new code with migrations
2. Use the Docker Compose setup which automatically runs migrations on startup
3. Check the logs when containers start to ensure migrations completed successfully

## Support

If you continue to experience issues:

1. Check the application logs for detailed error messages
2. Verify database connectivity with the credentials in your `.env` or `stack.env`
3. Ensure PostgreSQL version is compatible (9.6 or later recommended)
4. Check that PostGIS extension is installed if using spatial features
