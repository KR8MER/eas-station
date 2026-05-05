"""Add MDC1200 selective-calling columns to eas_settings.

Adds four columns supporting the new ``mdc1200`` pre/post-alert chime
profile (Motorola MDC1200 1200-baud FFSK selective calling):

  - mdc1200_unit_id      INTEGER NOT NULL DEFAULT 1
  - mdc1200_op_code      VARCHAR(32) NOT NULL DEFAULT 'ptt_id_pre'
  - mdc1200_op_code_raw  SMALLINT NULL
  - mdc1200_arg_raw      SMALLINT NULL

Revision ID: 20260505_add_mdc1200_to_eas_settings
Revises: 20260505_add_qc2_long_tone_to_eas_settings
Create Date: 2026-05-05
"""

from __future__ import annotations

from alembic import op


revision = "20260505_add_mdc1200_to_eas_settings"
down_revision = "20260505_add_qc2_long_tone_to_eas_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS mdc1200_unit_id INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS mdc1200_op_code VARCHAR(32) NOT NULL DEFAULT 'ptt_id_pre'"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS mdc1200_op_code_raw SMALLINT"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS mdc1200_arg_raw SMALLINT"
    )


def downgrade() -> None:
    op.drop_column("eas_settings", "mdc1200_arg_raw")
    op.drop_column("eas_settings", "mdc1200_op_code_raw")
    op.drop_column("eas_settings", "mdc1200_op_code")
    op.drop_column("eas_settings", "mdc1200_unit_id")
