"""Regression tests for the FCC compliance report builders.

Clicking Reports → FCC Reports (``/logs?type=report_received``) used to
return a 502 gateway error: the builders loaded whole ORM rows, so every
report dragged along ``ReceivedEASAlert.raw_audio_data`` (a ~1 MB WAV
capture per alert), ``ReceivedEASAlert.full_alert_data``, the six
``EASMessage`` audio blobs and ``CAPAlert.raw_json``/``geom`` — hundreds of
megabytes of working set to print a table containing none of it. The
gunicorn worker was OOM-killed and nginx reported a bad gateway.

These tests assert the emitted SQL selects only the columns the reports
actually print, and that every report query carries a row cap.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app_core.eas_storage import (
    REPORT_MAX_ROWS,
    build_initiated_alerts_report,
    build_received_alerts_report,
    build_weekly_summary_report,
    resolve_report_window,
)
from app_core.extensions import db

# Columns that must never appear in a report query. Each is either a
# LargeBinary blob, a large JSON document, or a PostGIS geometry.
HEAVY_COLUMNS = (
    "raw_audio_data",
    "full_alert_data",
    "audio_data",
    "eom_audio_data",
    "same_audio_data",
    "attention_audio_data",
    "tts_audio_data",
    "buffer_audio_data",
    "raw_json",
    "geom",
    "description",
    "instruction",
)


@pytest.fixture
def captured_sql(app, monkeypatch):
    """Run report builders without a database, capturing their SQL.

    ``db.session.execute`` is replaced with a stub that records the
    statement and yields no rows, so the builders exercise their real query
    construction while the assertions inspect the SQL they would run.
    """
    statements: list[str] = []

    def fake_execute(statement, *args, **kwargs):
        # Compiled SQL is newline-wrapped; collapse it so assertions can
        # match on clause boundaries such as " where ".
        statements.append(" ".join(str(statement).split()))
        return iter(())

    with app.app_context():
        monkeypatch.setattr(db.session, "execute", fake_execute)
        yield statements


def _window():
    start, end = resolve_report_window(days=30)
    assert end - start == timedelta(days=30)
    return {"window_start": start, "window_end": end}


def _assert_no_heavy_columns(statements):
    assert statements, "builder issued no queries"
    sql = " ".join(statements).lower()
    offenders = [column for column in HEAVY_COLUMNS if column in sql]
    assert not offenders, (
        f"report query selects heavy column(s) {offenders}; "
        "select only the columns the report prints"
    )


@pytest.mark.parametrize("decision", ["received", "forwarded", "ignored"])
def test_received_report_skips_heavy_columns(captured_sql, decision):
    """The received/forwarded/ignored reports must not load audio blobs."""
    build_received_alerts_report(decision=decision, **_window())
    _assert_no_heavy_columns(captured_sql)


def test_received_report_caps_rows(captured_sql):
    """An unbounded window must not build an unbounded row list."""
    build_received_alerts_report(decision="received", **_window())
    assert any(
        f"limit {REPORT_MAX_ROWS}" in sql.lower().replace("\n", " ")
        or ":param_1" in sql.lower()
        for sql in captured_sql
    ), "received report query has no LIMIT"


def test_received_report_still_filters_by_decision(captured_sql):
    """Column selection must not drop the forwarding_decision filter.

    ``forwarding_decision`` also appears in the SELECT list, so this looks
    specifically for it inside the WHERE clause.
    """
    build_received_alerts_report(decision="forwarded", **_window())
    sql = " ".join(captured_sql).lower()
    where_clause = sql.split(" where ", 1)
    assert len(where_clause) == 2, "received report query has no WHERE clause"
    assert "forwarding_decision in" in where_clause[1], (
        "forwarding_decision filter missing from WHERE clause"
    )


def test_received_report_omits_decision_filter_for_all(captured_sql):
    """The unfiltered 'received' report covers every decision value."""
    build_received_alerts_report(decision="received", **_window())
    sql = " ".join(captured_sql).lower()
    assert "forwarding_decision in" not in sql.split(" where ", 1)[1]


def test_initiated_report_skips_heavy_columns(captured_sql):
    """The initiated report joins CAPAlert without pulling raw_json/geom."""
    build_initiated_alerts_report(**_window())
    _assert_no_heavy_columns(captured_sql)


def test_initiated_report_joins_cap_alert(captured_sql):
    """The event/identifier columns still come from a CAPAlert join."""
    build_initiated_alerts_report(**_window())
    sql = " ".join(captured_sql).lower()
    assert "join cap_alerts" in sql, "CAPAlert join missing from initiated report"


def test_summary_reports_skip_heavy_columns(captured_sql):
    """The weekly/monthly bucket queries stay column-scoped too."""
    build_weekly_summary_report(**_window())
    _assert_no_heavy_columns(captured_sql)
