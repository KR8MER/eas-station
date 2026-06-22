#!/usr/bin/env python3
"""
Generate complete SQL schema from an actual PostgreSQL database.
This script creates a schema.sql file by using pg_dump from a freshly initialized database.
"""

import subprocess
import sys
import os
import tempfile
import time

def main():
    """Generate schema SQL from a temporary database."""
    
    print("=" * 70)
    print("EAS Station Schema Generator")
    print("=" * 70)
    print()
    
    # Check if PostgreSQL is available
    try:
        subprocess.run(['which', 'psql'], check=True, capture_output=True)
        subprocess.run(['which', 'pg_dump'], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        print("ERROR: PostgreSQL tools (psql, pg_dump) are not installed.")
        print("This script requires PostgreSQL to be installed.")
        sys.exit(1)
    
    # Generate a unique temporary database name
    temp_db = f"eas_schema_temp_{os.getpid()}"
    
    print(f"✓ Using temporary database: {temp_db}")
    print()
    
    try:
        # Create temporary database
        print("Step 1: Creating temporary database...")
        subprocess.run(
            ['sudo', '-u', 'postgres', 'psql', '-c', f'CREATE DATABASE {temp_db};'],
            check=True,
            capture_output=True
        )
        print("✓ Temporary database created")
        print()
        
        # Enable PostGIS extensions
        print("Step 2: Enabling PostGIS extensions...")
        subprocess.run(
            ['sudo', '-u', 'postgres', 'psql', '-d', temp_db, '-c', 'CREATE EXTENSION IF NOT EXISTS postgis;'],
            check=True,
            capture_output=True
        )
        subprocess.run(
            ['sudo', '-u', 'postgres', 'psql', '-d', temp_db, '-c', 'CREATE EXTENSION IF NOT EXISTS postgis_topology;'],
            check=True,
            capture_output=True
        )
        print("✓ PostGIS extensions enabled")
        print()
        
        # Initialize schema using db.create_all()
        print("Step 3: Initializing schema from SQLAlchemy models...")
        
        # Validate database name (only alphanumeric and underscores)
        import re
        if not re.match(r'^[a-z0-9_]+$', temp_db):
            print("ERROR: Invalid database name")
            sys.exit(1)
        
        # Set environment variables for the temporary database
        env = os.environ.copy()
        env['POSTGRES_DB'] = temp_db
        env['POSTGRES_HOST'] = 'localhost'
        env['POSTGRES_PORT'] = '5432'
        env['POSTGRES_USER'] = 'postgres'
        env['POSTGRES_PASSWORD'] = ''
        env['FLASK_ENV'] = 'production'
        env['FLASK_DEBUG'] = 'false'
        env['SECRET_KEY'] = 'temp_key_for_schema_generation'
        
        # Run the schema initialization
        init_script = """
import sys
import os
sys.path.insert(0, os.path.abspath('.'))
os.environ['POSTGRES_DB'] = '{db}'
os.environ['POSTGRES_HOST'] = 'localhost'
os.environ['POSTGRES_USER'] = 'postgres'
os.environ['POSTGRES_PASSWORD'] = ''
os.environ['SECRET_KEY'] = 'temp_key'
os.environ['FLASK_ENV'] = 'production'

from app import app, db
with app.app_context():
    db.create_all()
    print('Schema initialized')
""".format(db=temp_db)  # Database name already validated above
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(init_script)
            init_script_path = f.name
        
        try:
            # Use sys.executable to ensure we use the same Python interpreter
            python_executable = sys.executable or 'python3'
            result = subprocess.run(
                [python_executable, init_script_path],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                env=env,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                print("ERROR: Failed to initialize schema")
                print("STDOUT:", result.stdout)
                print("STDERR:", result.stderr)
                sys.exit(1)
        finally:
            os.unlink(init_script_path)
        
        print("✓ Schema initialized from models")
        print()
        
        # Dump schema to SQL file
        print("Step 4: Dumping schema to SQL...")
        output_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
        
        with open(output_path, 'w') as f:
            # Write header
            f.write("-- EAS Station Database Schema\n")
            f.write("-- Auto-generated from SQLAlchemy models using pg_dump\n")
            f.write("-- Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)\n")
            f.write("--\n")
            f.write("-- This schema file is used for fresh installations.\n")
            f.write("-- For existing database upgrades, use Alembic migrations.\n")
            f.write("--\n")
            f.write("-- Usage:\n")
            f.write("--   psql -U eas_station -d alerts < schema.sql\n")
            f.write("--\n\n")
            
            # Dump schema (structure only, no data)
            result = subprocess.run(
                ['sudo', '-u', 'postgres', 'pg_dump', '-d', temp_db, '--schema-only', '--no-owner', '--no-privileges'],
                capture_output=True,
                text=True,
                check=True
            )
            f.write(result.stdout)
            
            # Add default data inserts
            f.write("\n\n-- Insert default roles\n")
            f.write("INSERT INTO roles (name, description) VALUES\n")
            f.write("    ('admin', 'Full system access with all permissions'),\n")
            f.write("    ('operator', 'Day-to-day operations and monitoring'),\n")
            f.write("    ('viewer', 'Read-only access to view alerts and status')\n")
            f.write("ON CONFLICT (name) DO NOTHING;\n\n")
            
            f.write("-- Insert default permissions\n")
            f.write("INSERT INTO permissions (name, description, category) VALUES\n")
            f.write("    ('view_alerts', 'View alert information', 'alerts'),\n")
            f.write("    ('manage_alerts', 'Create and manage alerts', 'alerts'),\n")
            f.write("    ('view_settings', 'View system settings', 'settings'),\n")
            f.write("    ('manage_settings', 'Modify system settings', 'settings'),\n")
            f.write("    ('view_hardware', 'View hardware status', 'hardware'),\n")
            f.write("    ('manage_hardware', 'Configure hardware devices', 'hardware'),\n")
            f.write("    ('view_users', 'View user accounts', 'admin'),\n")
            f.write("    ('manage_users', 'Create and manage user accounts', 'admin'),\n")
            f.write("    ('view_logs', 'View system logs', 'system'),\n")
            f.write("    ('manage_system', 'Full system administration', 'system')\n")
            f.write("ON CONFLICT (name) DO NOTHING;\n\n")
            
            f.write("-- Schema generation complete\n")
        
        print(f"✓ Schema dumped to: {output_path}")
        
        # Get file size
        file_size = os.path.getsize(output_path)
        print(f"✓ Schema file size: {file_size:,} bytes")
        print()
        
    finally:
        # Clean up temporary database
        print("Step 5: Cleaning up...")
        subprocess.run(
            ['sudo', '-u', 'postgres', 'psql', '-c', f'DROP DATABASE IF EXISTS {temp_db};'],
            capture_output=True
        )
        print("✓ Temporary database removed")
        print()
    
    print("=" * 70)
    print("✓ Schema generation complete!")
    print("=" * 70)

if __name__ == '__main__':
    main()
