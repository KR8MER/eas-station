"""Regression test for the Alert Verification page's delivery-record query.

``collect_alert_delivery_records`` loaded whole ``EASMessage`` ORM rows for
every message in the display window, which drags along all six audio
``LargeBinary`` columns even though only metadata (``same_header``,
``created_at``, ``metadata_payload``) is ever read. On a production
instance with 235 messages averaging ~6.4 MB of audio each, the default
30-day window pulled roughly 180 MB from Postgres on every page load.

This test asserts the emitted SQL for the ``eas_messages`` query never
selects an audio blob column.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Query

from app_core.eas_storage import collect_alert_delivery_records

# Every LargeBinary column on EASMessage; none may appear in the SELECT list.
AUDIO_BLOB_COLUMNS = (
    "audio_data",
    "eom_audio_data",
    "same_audio_data",
    "attention_audio_data",
    "tts_audio_data",
    "buffer_audio_data",
)


@pytest.fixture
def captured_sql(app, monkeypatch):
    """Run collect_alert_delivery_records without a database, capturing SQL.

    ``collect_alert_delivery_records`` uses the legacy ``Model.query`` API
    (``CAPAlert.query``, ``EASMessage.without_audio()``). Patching
    ``Query.all()`` at the class level -- rather than ``Session.execute``
    -- sidesteps needing a real ``Result`` object: ``str(self)`` compiles
    the same SQL the real call would have run, and returning ``[]`` lets
    ``collect_alert_delivery_records`` proceed exactly as it would for an
    empty window.
    """
    statements: list[str] = []

    def fake_all(self):
        statements.append(" ".join(str(self).split()))
        return []

    with app.app_context():
        monkeypatch.setattr(Query, "all", fake_all)
        yield statements


def test_delivery_records_query_skips_audio_blobs(captured_sql):
    collect_alert_delivery_records(window_days=30)
    sql = " ".join(captured_sql).lower()
    offenders = [
        column
        for column in AUDIO_BLOB_COLUMNS
        if f"eas_messages.{column}" in sql
    ]
    assert not offenders, (
        f"collect_alert_delivery_records selects audio blob column(s) {offenders}; "
        "use EASMessage.without_audio() instead of EASMessage.query"
    )


def test_delivery_records_query_still_filters_by_window(captured_sql):
    collect_alert_delivery_records(window_days=30)
    sql = " ".join(captured_sql).lower()
    assert "eas_messages.created_at >=" in sql or ":created_at_1" in sql, (
        "window filter missing from eas_messages query"
    )
