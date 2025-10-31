"""Add SAME/FIPS codes to location settings."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect, text

from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS


revision = "20241205_add_location_fips_codes"
down_revision = "20241112_add_eas_message_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Get database connection and inspector
    conn = op.get_bind()
    inspector = inspect(conn)

    # Check existing columns
    existing_columns = {col['name'] for col in inspector.get_columns('location_settings')}

    default_codes = DEFAULT_LOCATION_SETTINGS.get("fips_codes", [])
    default_json = json.dumps(default_codes)

    # Only add the column if it doesn't exist
    if 'fips_codes' not in existing_columns:
        with op.batch_alter_table("location_settings", schema=None) as batch:
            batch.add_column(
                sa.Column(
                    "fips_codes",
                    sa.JSON(),
                    nullable=False,
                    server_default=sa.text("'[]'::jsonb"),
                )
            )

    if default_json:
        op.execute(
            text(
                """
                UPDATE location_settings
                SET fips_codes = :fips_default::jsonb
                WHERE fips_codes IS NULL
                   OR jsonb_array_length(fips_codes) = 0
                """
            ).bindparams(fips_default=default_json)
        )


def downgrade() -> None:
    with op.batch_alter_table("location_settings", schema=None) as batch:
        batch.drop_column("fips_codes")
