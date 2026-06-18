"""Add fail2ban_settings table for UI-managed firewall enforcement.

Stores whether app-level bans (ip_filters) are mirrored to the host firewall
via a fail2ban actuator jail, plus the optional sshd-jail tuning. Rendered to
/etc/fail2ban/jail.local and applied from the Security Center UI.

Revision ID: 20260618_fail2ban_settings
Revises: 20260616_traffic_privacy_anomaly
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260618_fail2ban_settings"
down_revision = "20260616_traffic_privacy_anomaly"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "fail2ban_settings" not in inspector.get_table_names():
        op.create_table(
            "fail2ban_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("protect_ssh", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("ssh_maxretry", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("ssh_bantime", sa.Integer(), nullable=False, server_default="3600"),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "fail2ban_settings" in inspector.get_table_names():
        op.drop_table("fail2ban_settings")
