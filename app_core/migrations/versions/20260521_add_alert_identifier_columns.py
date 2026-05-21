"""Add alert_identifier correlation-ID columns to log-shaped tables

Revision ID: 20260521_add_alert_identifier_columns
Revises: 20260521_add_rwt_skip_until
Create Date: 2026-05-21

Adds a nullable, indexed ``alert_identifier`` column to three log-shaped
tables so rows written during an alert's lifecycle can be traced back to
the originating CAP identifier (or OTA-derived correlation ID).  A
SQLAlchemy ``before_insert`` listener in ``app_core.logging_context``
populates the column from the ContextVar set by ``bind_alert`` /
``push_alert`` whenever a write happens inside an alert scope.

Affected tables:

* ``system_log``        — general application logs (44+ write sites)
* ``audio_alerts``      — audio subsystem warnings/errors
* ``eas_messages``      — generated EAS broadcasts

``gpio_activation_logs`` already carries a similarly-shaped ``alert_id``
column (added with the table) and is not touched by this migration; the
auto-populate listener is wired to that field separately.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260521_add_alert_identifier_columns"
down_revision = "20260521_add_rwt_skip_until"
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


def _index_exists(table_name: str, index_name: str) -> bool:
    conn = op.get_bind()
    inspector = inspect(conn)
    try:
        idx_names = {i["name"] for i in inspector.get_indexes(table_name)}
    except Exception:
        return False
    return index_name in idx_names


_TARGETS = (
    ("system_log", "ix_system_log_alert_identifier"),
    ("audio_alerts", "ix_audio_alerts_alert_identifier"),
    ("eas_messages", "ix_eas_messages_alert_identifier"),
)


def upgrade():
    for table, index_name in _TARGETS:
        if not _column_exists(table, "alert_identifier"):
            op.add_column(
                table,
                sa.Column("alert_identifier", sa.String(length=255), nullable=True),
            )
        if not _index_exists(table, index_name):
            op.create_index(index_name, table, ["alert_identifier"])


def downgrade():
    for table, index_name in _TARGETS:
        if _index_exists(table, index_name):
            op.drop_index(index_name, table_name=table)
        if _column_exists(table, "alert_identifier"):
            op.drop_column(table, "alert_identifier")
