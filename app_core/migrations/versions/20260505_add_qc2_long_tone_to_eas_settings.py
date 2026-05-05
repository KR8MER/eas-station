"""Add QC-II long-tone columns to eas_settings.

Adds two columns that support the optional sustained tone appended after the
standard QC-II two-tone sequence:

  - qc2_long_tone_enabled   BOOLEAN NOT NULL DEFAULT FALSE
  - qc2_long_tone_seconds   DOUBLE PRECISION NOT NULL DEFAULT 10.0

Revision ID: 20260505_add_qc2_long_tone_to_eas_settings
Revises: 20260501_add_alert_chime_to_eas_settings
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_add_qc2_long_tone_to_eas_settings"
down_revision = "20260501_add_alert_chime_to_eas_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS qc2_long_tone_enabled BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS qc2_long_tone_seconds DOUBLE PRECISION NOT NULL DEFAULT 10.0"
    )


def downgrade() -> None:
    op.drop_column("eas_settings", "qc2_long_tone_seconds")
    op.drop_column("eas_settings", "qc2_long_tone_enabled")
