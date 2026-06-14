"""Add auto_purge_settings table for scheduled received-alert purging.

Holds the single-row (id=1) configuration for the automatic purge of
``received_eas_alerts``: enabled flag, age threshold, scope (audio-only vs.
full record), forwarding-decision filter, optional source restriction, and
whether to also delete the generated EAS broadcast message.

Revision ID: 20260614_add_auto_purge_settings
Revises: 20260612_tower_light_states
Create Date: 2026-06-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

revision = "20260614_add_auto_purge_settings"
down_revision = "20260612_tower_light_states"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        return table_name in inspector.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    if _table_exists("auto_purge_settings"):
        return

    op.create_table(
        "auto_purge_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("max_age_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="full"),
        sa.Column(
            "decision_filter",
            sa.String(length=20),
            nullable=False,
            server_default="not_forwarded",
        ),
        sa.Column("source_filter", sa.String(length=100), nullable=True),
        sa.Column(
            "delete_generated_messages",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_summary", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    if not _table_exists("auto_purge_settings"):
        return
    op.drop_table("auto_purge_settings")
