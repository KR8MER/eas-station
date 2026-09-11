"""Add sms_opt_in_requests table for the public double opt-in SMS flow.

Revision ID: 20260911_add_sms_opt_in_requests
Revises: 20260910_add_timestamp_indexes
Create Date: 2026-09-11

Replaces the old design where an administrator added a phone number to
NotificationSettings.sms_recipients directly and merely attested that
consent was obtained out-of-band -- a carrier/Twilio A2P 10DLC campaign
reviewer has nothing verifiable to point at in that flow. This table backs
a public self-serve opt-in page (web form + SMS code confirmation): each
row is one opt-in attempt, with a verbatim snapshot of the consent text
shown at submission time and a nullable verified_at that is the actual
source of truth for "did this number confirm."
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260911_add_sms_opt_in_requests"
down_revision = "20260910_add_timestamp_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "sms_opt_in_requests" not in inspector.get_table_names():
        op.create_table(
            "sms_opt_in_requests",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("phone_number", sa.String(length=20), nullable=False),
            sa.Column("name", sa.String(length=255), nullable=True),
            sa.Column("consent_text", sa.Text(), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("code_hash", sa.String(length=255), nullable=False),
            sa.Column("code_expires_at", sa.DateTime(), nullable=False),
            sa.Column("code_attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_sms_opt_in_requests_phone_number",
            "sms_opt_in_requests",
            ["phone_number"],
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "sms_opt_in_requests" in inspector.get_table_names():
        op.drop_table("sms_opt_in_requests")
