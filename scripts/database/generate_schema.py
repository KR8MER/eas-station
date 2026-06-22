#!/usr/bin/env python3
"""
Generate complete SQL schema from SQLAlchemy models.
This script creates a schema.sql file that can be used for fresh installations.
"""

import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from io import StringIO
from sqlalchemy import create_engine
from sqlalchemy.schema import CreateTable, CreateIndex, CreateSequence
from app import app, db

# Import all models to ensure they're registered with SQLAlchemy
from app_core.models import (
    NWSZone, Boundary, CAPAlert, SystemLog, AdminUser, EASMessage,
    EASDecodedAudio, ReceivedEASAlert, ManualEASActivation, AlertDeliveryReport,
    Intersection, PollHistory, PollDebugRecord, LocationSettings, RadioReceiver,
    RadioReceiverStatus, LEDMessage, LEDSignStatus, VFDDisplay, VFDStatus,
    AudioSourceMetrics, AudioHealthStatus, AudioAlert
)
from app_core.auth.roles import Role, Permission
from app_core.auth.audit import AuditLog
from app_core.auth.ip_filter import IPFilter
from app_core.analytics.models import MetricSnapshot, TrendRecord, AnomalyRecord


def generate_schema_sql():
    """Generate SQL schema from SQLAlchemy models."""
    
    with app.app_context():
        # Create a mock PostgreSQL engine for SQL generation
        # We use postgresql dialect to generate proper PostgreSQL DDL
        engine = create_engine('postgresql://user:pass@localhost/db', strategy='mock', executor=lambda sql, *_: None)
        
        output = StringIO()
        
        # Header
        output.write("-- EAS Station Database Schema\n")
        output.write("-- Auto-generated from SQLAlchemy models\n")
        output.write("-- Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)\n")
        output.write("--\n")
        output.write("-- This schema file is used for fresh installations.\n")
        output.write("-- For existing database upgrades, use Alembic migrations.\n")
        output.write("--\n\n")
        
        # Enable PostGIS extensions
        output.write("-- Enable PostGIS extensions\n")
        output.write("CREATE EXTENSION IF NOT EXISTS postgis;\n")
        output.write("CREATE EXTENSION IF NOT EXISTS postgis_topology;\n\n")
        
        # Generate CREATE TABLE statements for all models
        output.write("-- Create all tables\n")
        output.write("-- Tables are created in dependency order to satisfy foreign key constraints\n\n")
        
        # Get all tables in metadata
        metadata = db.metadata
        
        # Create tables in order of dependencies
        for table in metadata.sorted_tables:
            output.write(f"-- Table: {table.name}\n")
            create_table_ddl = str(CreateTable(table).compile(engine))
            output.write(create_table_ddl)
            output.write(";\n\n")
            
            # Create indexes
            for index in table.indexes:
                try:
                    create_index_ddl = str(CreateIndex(index).compile(engine))
                    output.write(create_index_ddl)
                    output.write(";\n")
                except Exception as e:
                    output.write(f"-- Warning: Could not generate index {index.name}: {e}\n")
            
            output.write("\n")
        
        # Add default roles
        output.write("-- Insert default roles\n")
        output.write("INSERT INTO roles (name, description) VALUES\n")
        output.write("    ('admin', 'Full system access with all permissions'),\n")
        output.write("    ('operator', 'Day-to-day operations and monitoring'),\n")
        output.write("    ('viewer', 'Read-only access to view alerts and status')\n")
        output.write("ON CONFLICT (name) DO NOTHING;\n\n")
        
        # Add default permissions
        output.write("-- Insert default permissions\n")
        output.write("INSERT INTO permissions (name, description, category) VALUES\n")
        output.write("    ('view_alerts', 'View alert information', 'alerts'),\n")
        output.write("    ('manage_alerts', 'Create and manage alerts', 'alerts'),\n")
        output.write("    ('view_settings', 'View system settings', 'settings'),\n")
        output.write("    ('manage_settings', 'Modify system settings', 'settings'),\n")
        output.write("    ('view_hardware', 'View hardware status', 'hardware'),\n")
        output.write("    ('manage_hardware', 'Configure hardware devices', 'hardware'),\n")
        output.write("    ('view_users', 'View user accounts', 'admin'),\n")
        output.write("    ('manage_users', 'Create and manage user accounts', 'admin'),\n")
        output.write("    ('view_logs', 'View system logs', 'system'),\n")
        output.write("    ('manage_system', 'Full system administration', 'system')\n")
        output.write("ON CONFLICT (name) DO NOTHING;\n\n")
        
        # Footer
        output.write("-- Schema generation complete\n")
        output.write("-- Next steps:\n")
        output.write("-- 1. Grant privileges to the application user\n")
        output.write("-- 2. Create initial admin user via application\n")
        
        return output.getvalue()


if __name__ == '__main__':
    schema_sql = generate_schema_sql()
    
    # Write to file
    output_path = os.path.join(os.path.dirname(__file__), 'schema.sql')
    with open(output_path, 'w') as f:
        f.write(schema_sql)
    
    print(f"✓ Schema generated successfully: {output_path}")
    print(f"✓ Total size: {len(schema_sql)} bytes")
