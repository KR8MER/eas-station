"""Add pre/post-alert chime settings to eas_settings.

Adds seven columns controlling system-level alert chimes that play before the
SAME header (pre-alert) and after the EOM (post-alert):

  - pre_alert_chime           VARCHAR(16) NOT NULL DEFAULT 'none'
  - post_alert_chime          VARCHAR(16) NOT NULL DEFAULT 'none'
  - pre_alert_chime_duration  DOUBLE PRECISION NOT NULL DEFAULT 2.0
  - post_alert_chime_duration DOUBLE PRECISION NOT NULL DEFAULT 2.0
  - qc2_tone_a_freq           DOUBLE PRECISION NOT NULL DEFAULT 1000.0
  - qc2_tone_b_freq           DOUBLE PRECISION NOT NULL DEFAULT 1500.0
  - dtmf_sequence             VARCHAR(32) NOT NULL DEFAULT ''

Allowed chime values: 'none', 'bell', 'beep', 'three_tone', 'qc2', 'dtmf'.

Revision ID: 20260501_add_alert_chime_to_eas_settings
Revises: 20260501_fix_display_screens
Create Date: 2026-05-01
"""

from __future__ import annotations

from alembic import op


revision = "20260501_add_alert_chime_to_eas_settings"
down_revision = "20260501_fix_display_screens"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS pre_alert_chime VARCHAR(16) NOT NULL DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS post_alert_chime VARCHAR(16) NOT NULL DEFAULT 'none'"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS pre_alert_chime_duration DOUBLE PRECISION NOT NULL DEFAULT 2.0"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS post_alert_chime_duration DOUBLE PRECISION NOT NULL DEFAULT 2.0"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS qc2_tone_a_freq DOUBLE PRECISION NOT NULL DEFAULT 1000.0"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS qc2_tone_b_freq DOUBLE PRECISION NOT NULL DEFAULT 1500.0"
    )
    op.execute(
        "ALTER TABLE eas_settings"
        " ADD COLUMN IF NOT EXISTS dtmf_sequence VARCHAR(32) NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.drop_column("eas_settings", "dtmf_sequence")
    op.drop_column("eas_settings", "qc2_tone_b_freq")
    op.drop_column("eas_settings", "qc2_tone_a_freq")
    op.drop_column("eas_settings", "post_alert_chime_duration")
    op.drop_column("eas_settings", "pre_alert_chime_duration")
    op.drop_column("eas_settings", "post_alert_chime")
    op.drop_column("eas_settings", "pre_alert_chime")
