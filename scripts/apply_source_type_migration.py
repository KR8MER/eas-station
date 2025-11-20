#!/usr/bin/env python3
"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station
"""

"""
Standalone script to apply the source_type column migration to radio_receivers table.
This fixes the error: column radio_receivers.source_type does not exist

Usage:
    python3 apply_source_type_migration.py

Environment variables (reads from stack.env or can be set manually):
    POSTGRES_HOST (default: localhost)
    POSTGRES_PORT (default: 5432)
    POSTGRES_DB (default: alerts)
    POSTGRES_USER (default: postgres)
    POSTGRES_PASSWORD (required)

Or set DATABASE_URL directly:
    DATABASE_URL=postgresql://user:pass@host:port/dbname python3 apply_source_type_migration.py
"""

import os
import sys
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Try to load from stack.env or .env
if os.path.exists('stack.env'):
    load_dotenv('stack.env')
elif os.path.exists('.env'):
    load_dotenv('.env')

def get_db_connection():
    """Get a database connection using environment variables."""

    # Try DATABASE_URL first
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return psycopg2.connect(database_url)

    # Build from individual variables
    host = os.getenv('POSTGRES_HOST', 'localhost')
    port = os.getenv('POSTGRES_PORT', '5432')
    database = os.getenv('POSTGRES_DB', 'alerts')
    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD')

    if not password:
        print("ERROR: POSTGRES_PASSWORD environment variable is required", file=sys.stderr)
        sys.exit(1)

    print(f"Connecting to database: {user}@{host}:{port}/{database}")

    return psycopg2.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password
    )

def check_column_exists(cursor, table_name, column_name):
    """Check if a column exists in a table."""
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.columns
            WHERE table_name = %s
            AND column_name = %s
        )
    """, (table_name, column_name))
    return cursor.fetchone()[0]

def check_migration_applied(cursor):
    """Check if the migration has already been applied."""
    # Check if source_type column exists
    source_type_exists = check_column_exists(cursor, 'radio_receivers', 'source_type')
    stream_url_exists = check_column_exists(cursor, 'radio_receivers', 'stream_url')

    return source_type_exists and stream_url_exists

def apply_migration(cursor):
    """Apply the migration SQL."""

    print("Applying migration: Add source_type and stream_url to radio_receivers...")

    # Add source_type column (defaults to 'sdr' for existing records)
    print("  - Adding source_type column...")
    cursor.execute("""
        ALTER TABLE radio_receivers
        ADD COLUMN source_type VARCHAR(16) NOT NULL DEFAULT 'sdr'
    """)

    # Add stream_url column (nullable)
    print("  - Adding stream_url column...")
    cursor.execute("""
        ALTER TABLE radio_receivers
        ADD COLUMN stream_url VARCHAR(512)
    """)

    # Make driver nullable (since streams don't need it)
    print("  - Making driver column nullable...")
    cursor.execute("""
        ALTER TABLE radio_receivers
        ALTER COLUMN driver DROP NOT NULL
    """)

    # Make frequency_hz nullable
    print("  - Making frequency_hz column nullable...")
    cursor.execute("""
        ALTER TABLE radio_receivers
        ALTER COLUMN frequency_hz DROP NOT NULL
    """)

    # Make sample_rate nullable
    print("  - Making sample_rate column nullable...")
    cursor.execute("""
        ALTER TABLE radio_receivers
        ALTER COLUMN sample_rate DROP NOT NULL
    """)

    print("Migration applied successfully!")

def update_alembic_version(cursor):
    """Update the alembic_version table to mark this migration as applied."""

    migration_id = '20251105_add_stream_support_to_receivers'

    # Check if alembic_version table exists
    cursor.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables
            WHERE table_name = 'alembic_version'
        )
    """)

    if not cursor.fetchone()[0]:
        print("WARNING: alembic_version table does not exist. Migration tracking will not be updated.")
        return

    # Update or insert the version
    print(f"Updating alembic_version to: {migration_id}")
    cursor.execute("DELETE FROM alembic_version")
    cursor.execute("INSERT INTO alembic_version (version_num) VALUES (%s)", (migration_id,))

def main():
    """Main execution function."""

    print("=" * 70)
    print("Radio Receivers Source Type Migration Script")
    print("=" * 70)
    print()

    try:
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()

        # Check if migration is already applied
        if check_migration_applied(cursor):
            print("Migration has already been applied. Nothing to do.")
            cursor.close()
            conn.close()
            return

        # Apply the migration
        apply_migration(cursor)

        # Update alembic version
        update_alembic_version(cursor)

        # Commit changes
        conn.commit()

        print()
        print("=" * 70)
        print("SUCCESS: Migration completed successfully!")
        print("=" * 70)

        cursor.close()
        conn.close()

    except psycopg2.Error as e:
        print()
        print("=" * 70)
        print("ERROR: Database error occurred")
        print("=" * 70)
        print(f"Error: {e}")
        print()
        print("Please check your database connection settings and try again.")
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 70)
        print("ERROR: Unexpected error occurred")
        print("=" * 70)
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()
