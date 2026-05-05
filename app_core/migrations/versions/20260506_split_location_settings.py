"""Split location_settings into three tables: location, alert filtering, and hardware.

This migration reorganizes the location_settings table to separate concerns:
- location_settings: Keeps geographic identity (county, state, timezone, map coords)
- alert_filter_settings: New table for alert filtering (fips_codes, zone_codes, storage_zone_codes, area_terms)
- hardware_settings: Moves led_default_lines to existing hardware table

Revision ID: 20260506_split_location_settings
Revises: 20260505_add_mdc1200_to_eas_settings
Create Date: 2026-05-06
"""

from __future__ import annotations

import json
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260506_split_location_settings"
down_revision = "20260505_add_mdc1200_to_eas_settings"
branch_labels = None
depends_on = None


LOCATION_SETTINGS_TABLE = "location_settings"
ALERT_FILTER_SETTINGS_TABLE = "alert_filter_settings"
HARDWARE_SETTINGS_TABLE = "hardware_settings"

DEFAULT_FIPS_CODES = ["039137"]  # Putnam County, OH
DEFAULT_ZONE_CODES = []
DEFAULT_STORAGE_ZONE_CODES = []
DEFAULT_AREA_TERMS = []
DEFAULT_LED_DEFAULT_LINES = []


def upgrade() -> None:
    """Split location_settings table into specialized tables."""
    bind = op.get_bind()
    inspector = inspect(bind)
    
    table_names = inspector.get_table_names()
    
    # ========================================================================
    # Step 1: Create alert_filter_settings table
    # ========================================================================
    if ALERT_FILTER_SETTINGS_TABLE not in table_names:
        op.create_table(
            ALERT_FILTER_SETTINGS_TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column(
                'fips_codes',
                JSONB,
                nullable=False,
                server_default=sa.text(f"'{json.dumps(DEFAULT_FIPS_CODES)}'::jsonb"),
            ),
            sa.Column(
                'zone_codes',
                JSONB,
                nullable=False,
                server_default=sa.text(f"'{json.dumps(DEFAULT_ZONE_CODES)}'::jsonb"),
            ),
            sa.Column(
                'storage_zone_codes',
                JSONB,
                nullable=False,
                server_default=sa.text(f"'{json.dumps(DEFAULT_STORAGE_ZONE_CODES)}'::jsonb"),
            ),
            sa.Column(
                'area_terms',
                JSONB,
                nullable=False,
                server_default=sa.text(f"'{json.dumps(DEFAULT_AREA_TERMS)}'::jsonb"),
            ),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint('id')
        )
    
    # ========================================================================
    # Step 2: Add led_default_lines to hardware_settings
    # ========================================================================
    if HARDWARE_SETTINGS_TABLE in table_names:
        columns = {col["name"] for col in inspector.get_columns(HARDWARE_SETTINGS_TABLE)}
        if "led_default_lines" not in columns:
            op.add_column(
                HARDWARE_SETTINGS_TABLE,
                sa.Column(
                    'led_default_lines',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_LED_DEFAULT_LINES)}'::jsonb"),
                ),
            )
    
    # ========================================================================
    # Step 3: Data migration - copy from location_settings to new tables
    # ========================================================================
    if LOCATION_SETTINGS_TABLE in table_names:
        location_columns = {col["name"] for col in inspector.get_columns(LOCATION_SETTINGS_TABLE)}
        
        # Copy alert filtering data to alert_filter_settings
        # Only do this if alert_filter_settings is empty
        result = bind.execute(sa.text(f"SELECT COUNT(*) FROM {ALERT_FILTER_SETTINGS_TABLE}"))
        count = result.scalar()
        if count == 0:
            # Get data from first location_settings row
            result = bind.execute(sa.text(f"SELECT * FROM {LOCATION_SETTINGS_TABLE} LIMIT 1"))
            location_row = result.fetchone()
            
            if location_row:
                # Build column mapping (handle both dict-like and tuple-like result)
                if hasattr(location_row, '_mapping'):
                    row_dict = dict(location_row._mapping)
                else:
                    # Fallback for older SQLAlchemy versions
                    row_dict = dict(location_row)
                
                fips = row_dict.get('fips_codes', DEFAULT_FIPS_CODES)
                zones = row_dict.get('zone_codes', DEFAULT_ZONE_CODES)
                storage_zones = row_dict.get('storage_zone_codes', DEFAULT_STORAGE_ZONE_CODES)
                area = row_dict.get('area_terms', DEFAULT_AREA_TERMS)
                
                # Ensure values are JSON strings for insertion
                fips_json = json.dumps(fips) if not isinstance(fips, str) else fips
                zones_json = json.dumps(zones) if not isinstance(zones, str) else zones
                storage_zones_json = json.dumps(storage_zones) if not isinstance(storage_zones, str) else storage_zones
                area_json = json.dumps(area) if not isinstance(area, str) else area
                
                bind.execute(
                    sa.text(
                        f"INSERT INTO {ALERT_FILTER_SETTINGS_TABLE} "
                        f"(id, fips_codes, zone_codes, storage_zone_codes, area_terms) "
                        f"VALUES (1, :fips\\:\\:jsonb, :zones\\:\\:jsonb, :storage\\:\\:jsonb, :area\\:\\:jsonb)"
                    ),
                    {
                        "fips": fips_json,
                        "zones": zones_json,
                        "storage": storage_zones_json,
                        "area": area_json,
                    }
                )
        
        # Copy led_default_lines to hardware_settings
        if HARDWARE_SETTINGS_TABLE in table_names and "led_default_lines" in location_columns:
            result = bind.execute(sa.text(f"SELECT * FROM {LOCATION_SETTINGS_TABLE} LIMIT 1"))
            location_row = result.fetchone()
            
            if location_row:
                if hasattr(location_row, '_mapping'):
                    row_dict = dict(location_row._mapping)
                else:
                    row_dict = dict(location_row)
                
                led_lines = row_dict.get('led_default_lines', DEFAULT_LED_DEFAULT_LINES)
                led_json = json.dumps(led_lines) if not isinstance(led_lines, str) else led_lines
                
                # Check if hardware_settings row exists
                result = bind.execute(sa.text(f"SELECT id FROM {HARDWARE_SETTINGS_TABLE} LIMIT 1"))
                hw_row = result.fetchone()
                
                if hw_row:
                    # Update existing row
                    bind.execute(
                        sa.text(
                            f"UPDATE {HARDWARE_SETTINGS_TABLE} "
                            f"SET led_default_lines = :led\\:\\:jsonb "
                            f"WHERE id = 1"
                        ),
                        {"led": led_json}
                    )
                else:
                    # Insert new row with just id and led_default_lines
                    bind.execute(
                        sa.text(
                            f"INSERT INTO {HARDWARE_SETTINGS_TABLE} (id, led_default_lines) "
                            f"VALUES (1, :led\\:\\:jsonb)"
                        ),
                        {"led": led_json}
                    )
    
    # ========================================================================
    # Step 4: Drop moved columns from location_settings
    # ========================================================================
    if LOCATION_SETTINGS_TABLE in table_names:
        location_columns = {col["name"] for col in inspector.get_columns(LOCATION_SETTINGS_TABLE)}
        
        for column in ["fips_codes", "zone_codes", "storage_zone_codes", "area_terms", "led_default_lines"]:
            if column in location_columns:
                op.drop_column(LOCATION_SETTINGS_TABLE, column)


def downgrade() -> None:
    """Restore location_settings to original structure."""
    bind = op.get_bind()
    inspector = inspect(bind)
    
    table_names = inspector.get_table_names()
    
    # ========================================================================
    # Step 1: Re-add columns to location_settings
    # ========================================================================
    if LOCATION_SETTINGS_TABLE in table_names:
        location_columns = {col["name"] for col in inspector.get_columns(LOCATION_SETTINGS_TABLE)}
        
        if "fips_codes" not in location_columns:
            op.add_column(
                LOCATION_SETTINGS_TABLE,
                sa.Column(
                    'fips_codes',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_FIPS_CODES)}'::jsonb"),
                ),
            )
        
        if "zone_codes" not in location_columns:
            op.add_column(
                LOCATION_SETTINGS_TABLE,
                sa.Column(
                    'zone_codes',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_ZONE_CODES)}'::jsonb"),
                ),
            )
        
        if "storage_zone_codes" not in location_columns:
            op.add_column(
                LOCATION_SETTINGS_TABLE,
                sa.Column(
                    'storage_zone_codes',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_STORAGE_ZONE_CODES)}'::jsonb"),
                ),
            )
        
        if "area_terms" not in location_columns:
            op.add_column(
                LOCATION_SETTINGS_TABLE,
                sa.Column(
                    'area_terms',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_AREA_TERMS)}'::jsonb"),
                ),
            )
        
        if "led_default_lines" not in location_columns:
            op.add_column(
                LOCATION_SETTINGS_TABLE,
                sa.Column(
                    'led_default_lines',
                    JSONB,
                    nullable=False,
                    server_default=sa.text(f"'{json.dumps(DEFAULT_LED_DEFAULT_LINES)}'::jsonb"),
                ),
            )
        
        # Copy data back from alert_filter_settings
        if ALERT_FILTER_SETTINGS_TABLE in table_names:
            result = bind.execute(sa.text(f"SELECT * FROM {ALERT_FILTER_SETTINGS_TABLE} LIMIT 1"))
            filter_row = result.fetchone()
            
            if filter_row:
                if hasattr(filter_row, '_mapping'):
                    row_dict = dict(filter_row._mapping)
                else:
                    row_dict = dict(filter_row)
                
                fips = row_dict.get('fips_codes', DEFAULT_FIPS_CODES)
                zones = row_dict.get('zone_codes', DEFAULT_ZONE_CODES)
                storage_zones = row_dict.get('storage_zone_codes', DEFAULT_STORAGE_ZONE_CODES)
                area = row_dict.get('area_terms', DEFAULT_AREA_TERMS)
                
                fips_json = json.dumps(fips) if not isinstance(fips, str) else fips
                zones_json = json.dumps(zones) if not isinstance(zones, str) else zones
                storage_zones_json = json.dumps(storage_zones) if not isinstance(storage_zones, str) else storage_zones
                area_json = json.dumps(area) if not isinstance(area, str) else area
                
                bind.execute(
                    sa.text(
                        f"UPDATE {LOCATION_SETTINGS_TABLE} "
                        f"SET fips_codes = :fips\\:\\:jsonb, "
                        f"zone_codes = :zones\\:\\:jsonb, "
                        f"storage_zone_codes = :storage\\:\\:jsonb, "
                        f"area_terms = :area\\:\\:jsonb"
                    ),
                    {
                        "fips": fips_json,
                        "zones": zones_json,
                        "storage": storage_zones_json,
                        "area": area_json,
                    }
                )
        
        # Copy led_default_lines back from hardware_settings
        if HARDWARE_SETTINGS_TABLE in table_names:
            hw_columns = {col["name"] for col in inspector.get_columns(HARDWARE_SETTINGS_TABLE)}
            if "led_default_lines" in hw_columns:
                result = bind.execute(sa.text(f"SELECT led_default_lines FROM {HARDWARE_SETTINGS_TABLE} LIMIT 1"))
                hw_row = result.fetchone()
                
                if hw_row:
                    if hasattr(hw_row, '_mapping'):
                        led = dict(hw_row._mapping).get('led_default_lines', DEFAULT_LED_DEFAULT_LINES)
                    else:
                        led = hw_row[0] if hw_row[0] is not None else DEFAULT_LED_DEFAULT_LINES
                    
                    led_json = json.dumps(led) if not isinstance(led, str) else led
                    
                    bind.execute(
                        sa.text(
                            f"UPDATE {LOCATION_SETTINGS_TABLE} "
                            f"SET led_default_lines = :led\\:\\:jsonb"
                        ),
                        {"led": led_json}
                    )
    
    # ========================================================================
    # Step 2: Drop alert_filter_settings table
    # ========================================================================
    if ALERT_FILTER_SETTINGS_TABLE in table_names:
        op.drop_table(ALERT_FILTER_SETTINGS_TABLE)
    
    # ========================================================================
    # Step 3: Drop led_default_lines from hardware_settings
    # ========================================================================
    if HARDWARE_SETTINGS_TABLE in table_names:
        hw_columns = {col["name"] for col in inspector.get_columns(HARDWARE_SETTINGS_TABLE)}
        if "led_default_lines" in hw_columns:
            op.drop_column(HARDWARE_SETTINGS_TABLE, "led_default_lines")
