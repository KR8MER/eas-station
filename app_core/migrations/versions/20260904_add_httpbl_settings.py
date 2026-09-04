"""Add httpbl_enabled and httpbl_api_key columns to application_settings.

Revision ID: 20260904_add_httpbl_settings
Revises: 20260904_web_request_log_endpoint
Create Date: 2026-09-04

Adds an admin-UI toggle for Project Honeypot http:BL reputation checks
(see app_core/auth/httpbl.py) plus the account's http:BL access key,
stored in the database so it can be set from Application Settings rather
than requiring shell access to edit .env -- the same pattern already used
for Icecast credentials configured via the admin UI. Both default to
"off"/empty so existing deployments are unaffected until an admin opts in.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260904_add_httpbl_settings"
down_revision = "20260904_web_request_log_endpoint"
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
    if not _column_exists("application_settings", "httpbl_enabled"):
        op.add_column(
            "application_settings",
            sa.Column(
                "httpbl_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if not _column_exists("application_settings", "httpbl_api_key"):
        op.add_column(
            "application_settings",
            sa.Column(
                "httpbl_api_key",
                sa.String(length=64),
                nullable=True,
            ),
        )


def downgrade():
    if _column_exists("application_settings", "httpbl_api_key"):
        op.drop_column("application_settings", "httpbl_api_key")
    if _column_exists("application_settings", "httpbl_enabled"):
        op.drop_column("application_settings", "httpbl_enabled")
