"""Add a composite index for "latest metric per source" lookups.

audio_source_metrics is an append-only time-series table (one row per audio
level sample, several per second per source) that had grown to 1.5M+ rows.
The "list audio sources" endpoint (GET /api/audio/sources) needs only the
single most recent row per source, but without an index covering
(source_name, timestamp) together, Postgres had no way to answer that
cheaply -- it had to sequential-scan and sort the *entire* table, which
measured at 21+ seconds and was intermittently hitting the statement
timeout outright. This index, paired with rewriting that query to use
DISTINCT ON instead of "fetch everything, keep the first row seen in
Python", turns it into a fast per-source index lookup.

Revision ID: 20260831_audio_metrics_latest_index
Revises: 20260828_rwt_test_announcements
Create Date: 2026-08-31
"""

from __future__ import annotations

from alembic import op

revision = "20260831_audio_metrics_latest_index"
down_revision = "20260828_rwt_test_announcements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    existing = {ix["name"] for ix in inspector.get_indexes("audio_source_metrics")}
    if "ix_audio_source_metrics_source_name_timestamp" not in existing:
        # CONCURRENTLY: this table is written to continuously by the audio
        # monitoring service (several rows/sec); a plain CREATE INDEX takes
        # an exclusive lock that would stall those inserts for as long as
        # the build takes on 1.5M+ existing rows. CONCURRENTLY can't run
        # inside a transaction, hence autocommit_block().
        with op.get_context().autocommit_block():
            op.execute(
                "CREATE INDEX CONCURRENTLY ix_audio_source_metrics_source_name_timestamp "
                "ON audio_source_metrics (source_name, timestamp DESC)"
            )


def downgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    existing = {ix["name"] for ix in inspector.get_indexes("audio_source_metrics")}
    if "ix_audio_source_metrics_source_name_timestamp" in existing:
        with op.get_context().autocommit_block():
            op.execute("DROP INDEX CONCURRENTLY ix_audio_source_metrics_source_name_timestamp")
