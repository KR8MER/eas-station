"""Add dashboard_headline and dashboard_subtitle columns to application_settings.

Revision ID: 20260524_add_dashboard_branding_to_application_settings
Revises: 20260522_add_system_metric_samples
Create Date: 2026-05-24

Introduces a user-configurable dashboard header. ``dashboard_headline`` is
displayed above the default "Emergency Alert Dashboard" title (typically
call letters or an agency name); ``dashboard_subtitle`` overrides the
county/state subtitle when set. Both default to an empty string so
existing deployments keep their current behaviour until an admin fills
the fields in via the Application Settings page.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260524_add_dashboard_branding_to_application_settings"
down_revision = "20260522_add_system_metric_samples"
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
    if not _column_exists("application_settings", "dashboard_headline"):
        op.add_column(
            "application_settings",
            sa.Column(
                "dashboard_headline",
                sa.String(length=120),
                nullable=False,
                server_default="",
            ),
        )
    if not _column_exists("application_settings", "dashboard_subtitle"):
        op.add_column(
            "application_settings",
            sa.Column(
                "dashboard_subtitle",
                sa.String(length=160),
                nullable=False,
                server_default="",
            ),
        )


def downgrade():
    if _column_exists("application_settings", "dashboard_subtitle"):
        op.drop_column("application_settings", "dashboard_subtitle")
    if _column_exists("application_settings", "dashboard_headline"):
        op.drop_column("application_settings", "dashboard_headline")
