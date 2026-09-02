"""Raise the minimum admin password length to the FCC 47 CFR 11.35(d) floor.

FCC 26-38 (PS Docket Nos. 25-224, 22-329), released 2026-06-29, added 47 CFR
11.35(d)(1)(i): a "strong password" for EAS equipment must have a minimum of
15 characters. This application's configurable password policy previously
defaulted to 8, and the setup wizard / new-admin-user forms enforced 12 and 8
respectively -- all below the new regulatory floor (fixed in application
code alongside this migration; see
docs/compliance/FCC_26-38_EAS_CYBERSECURITY.md).

This migration only raises the *stored* ApplicationSettings.password_min_length
for existing installations whose row predates this change and is still below
15 -- it does not touch already-set passwords, which remain valid until
changed.

Revision ID: 20260902_fcc_pw_length_floor
Revises: 20260902_encrypt_stored_secrets
Create Date: 2026-09-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260902_fcc_pw_length_floor"
down_revision = "20260902_encrypt_stored_secrets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    if "application_settings" not in inspector.get_table_names():
        return
    conn.execute(
        sa.text(
            "UPDATE application_settings "
            "SET password_min_length = 15 "
            "WHERE password_min_length IS NULL OR password_min_length < 15"
        )
    )


def downgrade() -> None:
    # Intentionally a no-op: there is no recorded prior value to restore to,
    # and reverting a security floor on downgrade would be surprising.
    pass
