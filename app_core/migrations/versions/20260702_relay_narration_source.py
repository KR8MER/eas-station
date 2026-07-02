"""Add relay_narration_source to eas_settings.

Controls which narration audio is used when relaying an off-air (OTA) EAS
alert: the captured off-air recording, locally synthesised TTS, or automatic
selection based on gate-chop degradation detection.

Revision ID: 20260702_relay_narration_source
Revises: 20260618_ip_filter_source
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260702_relay_narration_source"
down_revision = "20260618_ip_filter_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "eas_settings" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("eas_settings")}
    if "relay_narration_source" not in existing_cols:
        op.add_column(
            "eas_settings",
            sa.Column(
                "relay_narration_source",
                sa.String(16),
                nullable=False,
                server_default="auto",
            ),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "eas_settings" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("eas_settings")}
    if "relay_narration_source" in existing_cols:
        op.drop_column("eas_settings", "relay_narration_source")
