"""Add storage_zone_codes column to location_settings for selective alert storage.

Revision ID: 20251121_add_storage_zone_codes_to_location_settings
Revises: 20251121_polish_network_screens
Create Date: 2025-11-21
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20251121_add_storage_zone_codes_to_location_settings"
down_revision = "20251121_polish_network_screens"
branch_labels = None
depends_on = None


LOCATION_SETTINGS_TABLE = "location_settings"
STORAGE_ZONE_CODES_COLUMN = "storage_zone_codes"
DEFAULT_STORAGE_ZONE_CODES = ["OHZ003", "OHC137"]  # Default to Putnam County zones


def upgrade() -> None:
    """Add the storage_zone_codes column to location_settings if it is missing.

    This column allows distinguishing between:
    - zone_codes: All zones to monitor for EAS broadcasting (local + adjoining counties)
    - storage_zone_codes: Only local county zones for database storage and boundary calculations

    This prevents storing and processing geographic boundaries for adjoining counties
    while still allowing EAS broadcasts for broader coverage areas.
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if LOCATION_SETTINGS_TABLE not in inspector.get_table_names():
        # Table has not been created yet; nothing to do.
        return

    columns = {column["name"] for column in inspector.get_columns(LOCATION_SETTINGS_TABLE)}

    if STORAGE_ZONE_CODES_COLUMN not in columns:
        op.add_column(
            LOCATION_SETTINGS_TABLE,
            sa.Column(
                STORAGE_ZONE_CODES_COLUMN,
                JSONB,
                nullable=False,
                server_default=sa.text(f"'{sa.dialects.postgresql.array(DEFAULT_STORAGE_ZONE_CODES)}'::jsonb"),
            ),
        )

        # For existing installations, populate storage_zone_codes with current zone_codes as default
        # This maintains backwards compatibility - existing setups will store all monitored zones
        bind.execute(
            sa.text(
                f"UPDATE {LOCATION_SETTINGS_TABLE} "
                f"SET {STORAGE_ZONE_CODES_COLUMN} = COALESCE(zone_codes, :default_codes) "
                f"WHERE {STORAGE_ZONE_CODES_COLUMN} IS NULL"
            ),
            {"default_codes": DEFAULT_STORAGE_ZONE_CODES},
        )


def downgrade() -> None:
    """Drop the storage_zone_codes column from location_settings if it exists."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if LOCATION_SETTINGS_TABLE not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(LOCATION_SETTINGS_TABLE)}

    if STORAGE_ZONE_CODES_COLUMN in columns:
        op.drop_column(LOCATION_SETTINGS_TABLE, STORAGE_ZONE_CODES_COLUMN)
