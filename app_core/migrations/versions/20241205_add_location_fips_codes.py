"""Add SAME/FIPS codes to location settings."""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from app_utils.location_settings import DEFAULT_LOCATION_SETTINGS


revision = "20241205_add_location_fips_codes"
down_revision = "20241112_add_eas_message_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    default_codes = DEFAULT_LOCATION_SETTINGS.get("fips_codes", [])
    default_json = json.dumps(default_codes)

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
                SET fips_codes = :default::jsonb
                WHERE fips_codes IS NULL
                   OR jsonb_array_length(fips_codes) = 0
                """
            ).bindparams(default=default_json)
        )


def downgrade() -> None:
    with op.batch_alter_table("location_settings", schema=None) as batch:
        batch.drop_column("fips_codes")
