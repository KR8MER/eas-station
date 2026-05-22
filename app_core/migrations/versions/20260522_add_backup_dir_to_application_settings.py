"""Add backup_dir column to application_settings.

Revision ID: 20260522_add_backup_dir_to_application_settings
Revises: 20260521_add_alert_identifier_columns
Create Date: 2026-05-22

Replaces the ``BACKUP_DIR`` environment variable with a database-backed
setting on the ``application_settings`` row.  The backup routes,
scheduler, and admin maintenance one-click backup all read this value at
runtime so operators can change the destination from the admin UI
without touching ``.env``.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260522_add_backup_dir_to_application_settings"
down_revision = "20260521_add_alert_identifier_columns"
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
    if not _column_exists("application_settings", "backup_dir"):
        # ``server_default`` is left in place (matching the existing
        # log_level/log_file/upload_folder columns) so existing rows are
        # backfilled in the same statement and future INSERTs that omit the
        # column still work.  The model's Python-side default mirrors it.
        op.add_column(
            "application_settings",
            sa.Column(
                "backup_dir",
                sa.String(length=255),
                nullable=False,
                server_default="/var/backups/eas-station",
            ),
        )


def downgrade():
    if _column_exists("application_settings", "backup_dir"):
        op.drop_column("application_settings", "backup_dir")
