"""Add skip_until and last_heartbeat_at columns to rwt_schedule_config

Revision ID: 20260521_add_rwt_skip_until
Revises: 20260515_add_chain_columns_to_audit_logs
Create Date: 2026-05-21

Adds two columns to the RWT scheduler config table:

* ``skip_until`` (DATE): when set, the scheduler will not fire on any
  configured day whose local date is on or before this date.  Operators
  set this from the RWT Schedule page to suppress automatic RWT
  broadcasts for one or more upcoming scheduled days (e.g. holiday,
  planned manual test).

* ``last_heartbeat_at`` (TIMESTAMPTZ): updated once per scheduler check
  (~ every minute) so the web UI can show "scheduler alive" indication
  independently of whether the scheduler has had any reason to fire.
  Persisted in the DB rather than kept in-process so it is visible
  across all Gunicorn workers.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260521_add_rwt_skip_until"
down_revision = "20260515_add_chain_columns_to_audit_logs"
branch_labels = None
depends_on = None


def _column_exists(table_name: str, column_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        cols = {c["name"] for c in inspector.get_columns(table_name)}
    except Exception:
        return False
    return column_name in cols


def upgrade():
    if not _column_exists("rwt_schedule_config", "skip_until"):
        op.add_column(
            "rwt_schedule_config",
            sa.Column("skip_until", sa.Date(), nullable=True),
        )
    if not _column_exists("rwt_schedule_config", "last_heartbeat_at"):
        op.add_column(
            "rwt_schedule_config",
            sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade():
    if _column_exists("rwt_schedule_config", "last_heartbeat_at"):
        op.drop_column("rwt_schedule_config", "last_heartbeat_at")
    if _column_exists("rwt_schedule_config", "skip_until"):
        op.drop_column("rwt_schedule_config", "skip_until")
