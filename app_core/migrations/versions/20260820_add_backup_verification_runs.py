"""Add backup_verification_runs table for scheduled restore verification.

Revision ID: 20260820_add_backup_verification_runs
Revises: 20260820_add_heartbeat_settings
Create Date: 2026-08-20
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260820_add_backup_verification_runs"
down_revision = "20260820_add_heartbeat_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "backup_verification_runs" not in inspector.get_table_names():
        op.create_table(
            "backup_verification_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("backup_label", sa.String(255), nullable=False),
            sa.Column("passed", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("details", JSONB(), nullable=False, server_default="[]"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("triggered_by", sa.String(32), nullable=False, server_default="scheduled"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_backup_verification_runs_started_at",
            "backup_verification_runs",
            ["started_at"],
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "backup_verification_runs" in inspector.get_table_names():
        op.drop_index("ix_backup_verification_runs_started_at", table_name="backup_verification_runs")
        op.drop_table("backup_verification_runs")
