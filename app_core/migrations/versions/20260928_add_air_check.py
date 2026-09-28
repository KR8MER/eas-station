"""Add SDR receiver roles and off-air self-monitoring (air-check) tables.

Adds ``radio_receivers.role`` ('monitor' | 'air_check') and the
``air_check_records`` / ``air_check_settings`` tables that back the
Air-Check page: every on-air activation is matched against what an
air-check receiver tuned to the station's own transmitter decodes back.

Revision ID: 20260928_add_air_check
Revises: 20260919_add_led_world_clock_screen
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260928_add_air_check"
down_revision = "20260919_add_led_world_clock_screen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "radio_receivers" in tables:
        existing_cols = {col["name"] for col in inspector.get_columns("radio_receivers")}
        if "role" not in existing_cols:
            op.add_column(
                "radio_receivers",
                sa.Column(
                    "role",
                    sa.String(16),
                    nullable=False,
                    server_default="monitor",
                ),
            )

    if "air_check_records" not in tables:
        op.create_table(
            "air_check_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("origin_type", sa.String(16), nullable=True),
            sa.Column("origin_id", sa.Integer(), nullable=True),
            sa.Column("alert_identifier", sa.String(255), nullable=True),
            sa.Column("expected_header", sa.String(255), nullable=True),
            sa.Column("event_code", sa.String(8), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("received_header", sa.String(255), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("receiver_source", sa.String(100), nullable=True),
            sa.Column("receiver_identifier", sa.String(64), nullable=True),
            sa.Column("decode_confidence", sa.Float(), nullable=True),
            sa.Column("mismatch_fields", sa.JSON(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_by", sa.String(100), nullable=True),
        )
        op.create_index("ix_air_check_records_sent_at", "air_check_records", ["sent_at"])
        op.create_index("ix_air_check_records_deadline_at", "air_check_records", ["deadline_at"])
        op.create_index("ix_air_check_records_status", "air_check_records", ["status"])

    if "air_check_settings" not in tables:
        op.create_table(
            "air_check_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("grace_seconds", sa.Integer(), nullable=False, server_default="60"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    tables = inspector.get_table_names()

    if "air_check_settings" in tables:
        op.drop_table("air_check_settings")
    if "air_check_records" in tables:
        op.drop_table("air_check_records")
    if "radio_receivers" in tables:
        existing_cols = {col["name"] for col in inspector.get_columns("radio_receivers")}
        if "role" in existing_cols:
            op.drop_column("radio_receivers", "role")
