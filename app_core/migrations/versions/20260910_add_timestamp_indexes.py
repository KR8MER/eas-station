"""Add missing indexes on system_log.timestamp and poll_history.timestamp.

Revision ID: 20260910_add_timestamp_indexes
Revises: 20260904_add_security_perimeter_events
Create Date: 2026-09-10

A DB audit found both tables' most common query shape --
``ORDER BY timestamp DESC LIMIT N`` -- had no index to use, forcing a
parallel sequential scan + sort on every call. system_log is hit this way
every 10 seconds forever by websocket_push.py's slow push loop
(_emit_logs_update) plus the /logs page: EXPLAIN ANALYZE on the live table
(440k rows / 810MB) measured 500-650ms per execution. poll_history has the
same gap, hit by _emit_ipaws_status_update and the /logs aggregate view
(27-36ms on 42k rows).
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260910_add_timestamp_indexes"
down_revision = "20260904_add_security_perimeter_events"
branch_labels = None
depends_on = None


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    return any(ix["name"] == index_name for ix in inspector.get_indexes(table_name))


def upgrade() -> None:
    if not _index_exists("system_log", "ix_system_log_timestamp"):
        op.create_index(
            "ix_system_log_timestamp", "system_log", ["timestamp"]
        )
    if not _index_exists("poll_history", "ix_poll_history_timestamp"):
        op.create_index(
            "ix_poll_history_timestamp", "poll_history", ["timestamp"]
        )


def downgrade() -> None:
    if _index_exists("poll_history", "ix_poll_history_timestamp"):
        op.drop_index("ix_poll_history_timestamp", table_name="poll_history")
    if _index_exists("system_log", "ix_system_log_timestamp"):
        op.drop_index("ix_system_log_timestamp", table_name="system_log")
