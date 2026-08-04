"""Track the TOTP time step of the last accepted MFA code.

Replay prevention previously compared elapsed wall-clock time against
``mfa_last_totp_at``, which rejected every code for 90 seconds after a
successful login — including brand-new codes the authenticator had already
rotated to.  Recording the RFC 6238 time step instead lets the login flow
reject only genuine replays.

Revision ID: 20260804_mfa_totp_counter
Revises: 20260702_relay_narration_source
Create Date: 2026-08-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260804_mfa_totp_counter"
down_revision = "20260702_relay_narration_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "admin_users" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("admin_users")}
    if "mfa_last_totp_counter" not in existing_cols:
        op.add_column(
            "admin_users",
            sa.Column("mfa_last_totp_counter", sa.BigInteger(), nullable=True),
        )


def downgrade() -> None:
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)

    if "admin_users" not in inspector.get_table_names():
        return

    existing_cols = {col["name"] for col in inspector.get_columns("admin_users")}
    if "mfa_last_totp_counter" in existing_cols:
        op.drop_column("admin_users", "mfa_last_totp_counter")
