"""Add MDC1200 target unit ID column to eas_settings.

Adds the ``mdc1200_target_unit_id`` column used by the double-packet
MDC1200 ops (Call Alert / Selective Call) to address a specific
receiving subscriber.  When NULL or 0 the encoder falls back to a
single-packet frame.

  - mdc1200_target_unit_id  INTEGER NULL

Revision ID: 20260505_add_mdc1200_target_unit_id_to_eas_settings
Revises: 20260506_split_location_settings
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_add_mdc1200_target_unit_id_to_eas_settings"
down_revision = "20260506_split_location_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS mdc1200_target_unit_id INTEGER"
    )


def downgrade() -> None:
    op.drop_column("eas_settings", "mdc1200_target_unit_id")
