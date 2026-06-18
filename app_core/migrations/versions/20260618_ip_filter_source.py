"""Add source column to ip_filters for the unified Global Ban List.

Records which security system added each ban (manual, login brute force, SSH
brute force, malicious request, flood, API/stream abuse) so the Security Center
can badge entries. Backfills existing rows from their reason/description.

Revision ID: 20260618_ip_filter_source
Revises: 20260618_fail2ban_settings
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260618_ip_filter_source"
down_revision = "20260618_fail2ban_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "ip_filters" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("ip_filters")}
    if "source" not in existing_cols:
        op.add_column("ip_filters", sa.Column("source", sa.String(length=40), nullable=True))
        op.create_index("ix_ip_filters_source", "ip_filters", ["source"])

    # Backfill source from the legacy reason (+ description for SSH vs login).
    # auto_malicious -> malicious_request; auto_flood -> flood;
    # auto_brute_force + "ssh" in description -> ssh_brute_force, else login_brute_force;
    # everything else (manual / unknown) -> manual.
    op.execute(
        """
        UPDATE ip_filters SET source = 'malicious_request'
        WHERE source IS NULL AND reason = 'auto_malicious'
        """
    )
    op.execute(
        """
        UPDATE ip_filters SET source = 'flood'
        WHERE source IS NULL AND reason = 'auto_flood'
        """
    )
    op.execute(
        """
        UPDATE ip_filters SET source = 'ssh_brute_force'
        WHERE source IS NULL AND reason = 'auto_brute_force'
          AND LOWER(COALESCE(description, '')) LIKE '%ssh%'
        """
    )
    op.execute(
        """
        UPDATE ip_filters SET source = 'login_brute_force'
        WHERE source IS NULL AND reason = 'auto_brute_force'
        """
    )
    op.execute(
        """
        UPDATE ip_filters SET source = 'manual'
        WHERE source IS NULL
        """
    )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    if "ip_filters" not in inspector.get_table_names():
        return

    existing_cols = {c["name"] for c in inspector.get_columns("ip_filters")}
    if "source" in existing_cols:
        try:
            op.drop_index("ix_ip_filters_source", table_name="ip_filters")
        except Exception:
            pass
        op.drop_column("ip_filters", "source")
