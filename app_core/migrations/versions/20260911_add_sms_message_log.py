"""Add sms_message_log table: one row per outbound SMS send attempt
(alert broadcast, opt-in verification code, or admin test message),
searchable by recipient phone number.

Revision ID: 20260911_add_sms_message_log
Revises: 20260911_add_sms_opt_in_requests
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260911_add_sms_message_log"
down_revision = "20260911_add_sms_opt_in_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "sms_message_log" not in inspector.get_table_names():
        op.create_table(
            "sms_message_log",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("phone_number", sa.String(length=20), nullable=False),
            sa.Column("message_type", sa.String(length=20), nullable=False),
            sa.Column("event_code", sa.String(length=16), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("twilio_sid", sa.String(length=64), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_sms_message_log_phone_number", "sms_message_log", ["phone_number"]
        )
        op.create_index(
            "ix_sms_message_log_message_type", "sms_message_log", ["message_type"]
        )
        op.create_index(
            "ix_sms_message_log_created_at", "sms_message_log", ["created_at"]
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "sms_message_log" in inspector.get_table_names():
        op.drop_table("sms_message_log")
