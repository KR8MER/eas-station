#!/usr/bin/env python3
"""
Database migration utility for NOAA Alerts System
Safely applies schema changes to the database
"""

import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()


def get_database_url():
    """Build database URL from environment variables"""
    url = os.getenv('DATABASE_URL')
    if url:
        return url

    user = os.getenv('POSTGRES_USER', 'postgres')
    password = os.getenv('POSTGRES_PASSWORD', '')
    host = os.getenv('POSTGRES_HOST', 'postgres')
    port = os.getenv('POSTGRES_PORT', '5432')
    database = os.getenv('POSTGRES_DB', user)

    if password:
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{database}"
    return f"postgresql+psycopg2://{user}@{host}:{port}/{database}"


def run_migration(engine, migration_file):
    """Run a single SQL migration file"""
    print(f"\n{'=' * 60}")
    print(f"Running migration: {migration_file.name}")
    print(f"{'=' * 60}")

    with open(migration_file, 'r') as f:
        sql = f.read()

    with engine.begin() as conn:
        # Execute the migration
        result = conn.execute(text(sql))

        # Get any messages from PostgreSQL NOTICE/RAISE
        if result.returns_rows:
            for row in result:
                print(row)

    print(f"✓ Migration completed: {migration_file.name}")


def main():
    """Run all pending migrations"""
    print("NOAA Alerts System - Database Migration Utility")
    print("=" * 60)

    # Get database connection
    database_url = get_database_url()
    print(f"Database: {database_url.split('@')[1] if '@' in database_url else database_url}")

    try:
        engine = create_engine(database_url, pool_pre_ping=True)

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"Connected to: {version.split(',')[0]}")

        # Find all migration files
        migrations_dir = Path(__file__).parent
        migration_files = sorted(migrations_dir.glob('*.sql'))

        if not migration_files:
            print("\nNo migration files found.")
            return

        print(f"\nFound {len(migration_files)} migration file(s):")
        for mf in migration_files:
            print(f"  - {mf.name}")

        # Run each migration
        for migration_file in migration_files:
            run_migration(engine, migration_file)

        print(f"\n{'=' * 60}")
        print("✓ All migrations completed successfully!")
        print(f"{'=' * 60}\n")

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
