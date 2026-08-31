"""Add system_log retention + lower the audio_metrics retention default.

system_log had no retention policy at all -- unbounded growth, 1M+ rows /
850+ MB in one real deployment with nothing ever pruning it. Adds
system_log_max_age_days (default 90, matching the existing operational-log
precedent of audio_alert_max_age_days) and wires SystemLog into
RetentionScheduler's sweep (app_core/retention.py).

Also lowers audio_metrics_max_age_days from 30 to 3 on the already-persisted
settings row -- the column's Python-level default change alone only affects
*new* rows, never the existing single settings row (id=1), so the live value
needs an explicit UPDATE. See the column's docstring in
app_core/_models_settings.py for why 30 days of raw per-sample audio metrics
was pure bloat nothing reads.

Revision ID: 20260831_system_log_retention
Revises: 20260831_audio_metrics_idx
Create Date: 2026-08-31
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260831_system_log_retention"
down_revision = "20260831_audio_metrics_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {c["name"] for c in inspector.get_columns("retention_settings")}
    if "system_log_max_age_days" not in existing_cols:
        op.add_column(
            "retention_settings",
            sa.Column(
                "system_log_max_age_days",
                sa.Integer(),
                nullable=False,
                server_default="90",
            ),
        )

    # Bring the already-persisted row's audio_metrics_max_age_days down to
    # the new default. Only touch it if it's still at the old default (30)
    # -- an admin who deliberately changed it to something else already
    # made their own choice, this migration shouldn't override that.
    op.execute(
        "UPDATE retention_settings SET audio_metrics_max_age_days = 3 "
        "WHERE audio_metrics_max_age_days = 30"
    )


def downgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    existing_cols = {c["name"] for c in inspector.get_columns("retention_settings")}
    if "system_log_max_age_days" in existing_cols:
        op.drop_column("retention_settings", "system_log_max_age_days")

    op.execute(
        "UPDATE retention_settings SET audio_metrics_max_age_days = 30 "
        "WHERE audio_metrics_max_age_days = 3"
    )
