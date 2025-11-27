"""Add EAS forwarding tracking columns to cap_alerts table.

Revision ID: 20251127_add_eas_forwarding_tracking
Revises: 20251123_enable_audio_source_autostart
Create Date: 2025-11-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20251127_add_eas_forwarding_tracking"
down_revision = "20251123_enable_audio_source_autostart"
branch_labels = None
depends_on = None


CAP_ALERTS_TABLE = "cap_alerts"


def upgrade() -> None:
    """Add EAS forwarding tracking columns to cap_alerts table.

    These columns track:
    - eas_forwarded: Whether the alert triggered an EAS broadcast
    - eas_forwarding_reason: Why it was or wasn't forwarded (e.g., BLOCKCHANNEL)
    - eas_audio_url: URL/path to generated EAS audio file if broadcast
    """
    bind = op.get_bind()
    inspector = inspect(bind)

    if CAP_ALERTS_TABLE not in inspector.get_table_names():
        # Table has not been created yet; nothing to do.
        return

    columns = {column["name"] for column in inspector.get_columns(CAP_ALERTS_TABLE)}

    if "eas_forwarded" not in columns:
        op.add_column(
            CAP_ALERTS_TABLE,
            sa.Column(
                "eas_forwarded",
                sa.Boolean,
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if "eas_forwarding_reason" not in columns:
        op.add_column(
            CAP_ALERTS_TABLE,
            sa.Column(
                "eas_forwarding_reason",
                sa.String(255),
                nullable=True,
            ),
        )

    if "eas_audio_url" not in columns:
        op.add_column(
            CAP_ALERTS_TABLE,
            sa.Column(
                "eas_audio_url",
                sa.String(512),
                nullable=True,
            ),
        )


def downgrade() -> None:
    """Drop EAS forwarding tracking columns from cap_alerts table."""
    bind = op.get_bind()
    inspector = inspect(bind)

    if CAP_ALERTS_TABLE not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns(CAP_ALERTS_TABLE)}

    if "eas_audio_url" in columns:
        op.drop_column(CAP_ALERTS_TABLE, "eas_audio_url")

    if "eas_forwarding_reason" in columns:
        op.drop_column(CAP_ALERTS_TABLE, "eas_forwarding_reason")

    if "eas_forwarded" in columns:
        op.drop_column(CAP_ALERTS_TABLE, "eas_forwarded")
