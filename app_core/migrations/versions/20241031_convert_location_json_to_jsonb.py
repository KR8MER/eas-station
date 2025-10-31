"""Convert location_settings JSON columns to JSONB for better performance."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects.postgresql import JSONB


revision = "20241031_convert_location_json_to_jsonb"
down_revision = "20241205_add_location_fips_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Convert JSON columns to JSONB for better PostgreSQL performance and function support."""
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check if table exists
    if 'location_settings' not in inspector.get_table_names():
        return

    existing_columns = {col['name']: col for col in inspector.get_columns('location_settings')}

    # Convert zone_codes from JSON to JSONB if it exists
    if 'zone_codes' in existing_columns:
        with op.batch_alter_table("location_settings", schema=None) as batch:
            batch.alter_column(
                'zone_codes',
                type_=JSONB,
                existing_type=sa.JSON(),
                postgresql_using='zone_codes::jsonb'
            )

    # Convert area_terms from JSON to JSONB if it exists
    if 'area_terms' in existing_columns:
        with op.batch_alter_table("location_settings", schema=None) as batch:
            batch.alter_column(
                'area_terms',
                type_=JSONB,
                existing_type=sa.JSON(),
                postgresql_using='area_terms::jsonb'
            )

    # Convert led_default_lines from JSON to JSONB if it exists
    if 'led_default_lines' in existing_columns:
        with op.batch_alter_table("location_settings", schema=None) as batch:
            batch.alter_column(
                'led_default_lines',
                type_=JSONB,
                existing_type=sa.JSON(),
                postgresql_using='led_default_lines::jsonb'
            )

    # Convert fips_codes from JSON to JSONB if it exists and is JSON type
    if 'fips_codes' in existing_columns:
        with op.batch_alter_table("location_settings", schema=None) as batch:
            batch.alter_column(
                'fips_codes',
                type_=JSONB,
                existing_type=sa.JSON(),
                postgresql_using='fips_codes::jsonb'
            )


def downgrade() -> None:
    """Convert JSONB columns back to JSON."""
    with op.batch_alter_table("location_settings", schema=None) as batch:
        batch.alter_column(
            'fips_codes',
            type_=sa.JSON(),
            existing_type=JSONB,
            postgresql_using='fips_codes::json'
        )
        batch.alter_column(
            'zone_codes',
            type_=sa.JSON(),
            existing_type=JSONB,
            postgresql_using='zone_codes::json'
        )
        batch.alter_column(
            'area_terms',
            type_=sa.JSON(),
            existing_type=JSONB,
            postgresql_using='area_terms::json'
        )
        batch.alter_column(
            'led_default_lines',
            type_=sa.JSON(),
            existing_type=JSONB,
            postgresql_using='led_default_lines::json'
        )
