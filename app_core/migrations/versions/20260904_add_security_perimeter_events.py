"""Add security_perimeter_events and security_perimeter_ingest_state tables.

Revision ID: 20260904_add_security_perimeter_events
Revises: 20260904_add_httpbl_settings
Create Date: 2026-09-04

Backs the Security Center "Edge Defense" tab (app_core/analytics/
security_blocks.py): requests nginx rejected before they ever reached the
app (scanner-bait paths, the Spamhaus/local bad-actor blocklist, and rate
limiting), fed by scripts/ingest_security_perimeter_log.py tailing the
nginx access log. security_perimeter_ingest_state is a single-row (id=1)
checkpoint of how far into that log the ingester has read.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260904_add_security_perimeter_events"
down_revision = "20260904_add_httpbl_settings"
branch_labels = None
depends_on = None


def _table_exists(table_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    return table_name in inspector.get_table_names()


def upgrade():
    if not _table_exists("security_perimeter_events"):
        op.create_table(
            "security_perimeter_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ip_address", sa.String(length=64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("block_reason", sa.String(length=32), nullable=False),
            sa.Column("method", sa.String(length=8), nullable=True),
            sa.Column("path", sa.String(length=512), nullable=True),
            sa.Column("user_agent", sa.String(length=512), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_security_perimeter_events_occurred_at",
            "security_perimeter_events", ["occurred_at"],
        )
        op.create_index(
            "ix_security_perimeter_events_ip_address",
            "security_perimeter_events", ["ip_address"],
        )
        op.create_index(
            "ix_security_perimeter_events_status_code",
            "security_perimeter_events", ["status_code"],
        )
        op.create_index(
            "ix_security_perimeter_events_block_reason",
            "security_perimeter_events", ["block_reason"],
        )
        op.create_index(
            "ix_security_perimeter_events_path",
            "security_perimeter_events", ["path"],
        )

    if not _table_exists("security_perimeter_ingest_state"):
        op.create_table(
            "security_perimeter_ingest_state",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("log_inode", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("log_offset", sa.BigInteger(), nullable=False, server_default="0"),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )


def downgrade():
    if _table_exists("security_perimeter_ingest_state"):
        op.drop_table("security_perimeter_ingest_state")
    if _table_exists("security_perimeter_events"):
        op.drop_table("security_perimeter_events")
