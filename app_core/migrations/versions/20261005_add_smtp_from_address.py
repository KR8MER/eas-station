"""Add notification_settings.smtp_from_address.

A From address for outgoing mail, separate from the SMTP login. Relays such
as SMTP2GO reject mail whose From address is not a verified sender, and their
SMTP usernames are often not email addresses. Blank keeps the old behaviour
(From = SMTP username).

Revision ID: 20261005_add_smtp_from_address
Revises: 20260928_add_air_check
Create Date: 2026-10-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261005_add_smtp_from_address"
down_revision = "20260928_add_air_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_bind())
    if "notification_settings" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("notification_settings")}
    if "smtp_from_address" not in columns:
        op.add_column(
            "notification_settings",
            sa.Column("smtp_from_address", sa.String(255), nullable=False, server_default=""),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    inspector = inspect(op.get_bind())
    if "notification_settings" not in inspector.get_table_names():
        return
    columns = {col["name"] for col in inspector.get_columns("notification_settings")}
    if "smtp_from_address" in columns:
        op.drop_column("notification_settings", "smtp_from_address")
