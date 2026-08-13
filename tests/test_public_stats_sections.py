"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)

This file is part of EAS Station.

EAS Station is dual-licensed software:
- GNU Affero General Public License v3 (AGPL-3.0) for open-source use
- Commercial License for proprietary use

You should have received a copy of both licenses with this software.
For more information, see LICENSE and LICENSE-COMMERCIAL files.

IMPORTANT: This software cannot be rebranded or have attribution removed.
See NOTICE file for complete terms.

Repository: https://github.com/KR8MER/eas-station"""

"""Characterization tests for the /stats dashboard's data layer.

Written *before* the 645-line ``stats()`` handler was decomposed into the
``webapp/public/stats_sections/`` package. The handler is one long sequence of
independent ``try/except`` blocks, each contributing a fragment to one
``stats_data`` dict and each declaring its own fallback — so what has to be
pinned is the **contents of that dict**, not the rendered HTML.

The tests reach the dict by replacing ``render_template`` with a capture, which
works identically before and after the split, and by calling the view function
directly so the global login redirect does not get in the way.

Two things this covers that are easy to get wrong in a refactor:

* **Every fallback.** A collector that raises must leave its documented default
  behind, not a missing key — the template indexes these unconditionally.
* **The derived rates.** Forwarding rate, cancellation/update rate, coverage
  overlap and the p95 execution time are all division-by-count expressions with
  a zero guard, and each is asserted with a real numerator and denominator.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import pytest

_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (CAPAlert uses a PostGIS geometry column)",
)

from app_core.extensions import db  # noqa: E402
from app_core.models import (  # noqa: E402
    AlertGatingSettings,
    Boundary,
    CAPAlert,
    EASMessage,
    GatedAlert,
    GPIOActivationLog,
    Intersection,
    ManualEASActivation,
    PollHistory,
    ReceivedEASAlert,
)

# Fixed instants. `sent` values are chosen so the hour/day-of-week/month
# buckets below are unambiguous: 2026-08-07 is a Friday (weekday 4, so the
# handler's ((weekday + 1) % 7) index is 5), hour 14, month 8.
SENT = datetime(2026, 8, 7, 14, 30, 0, tzinfo=timezone.utc)

_MODELS = (
    Intersection, EASMessage, ManualEASActivation, ReceivedEASAlert,
    GPIOActivationLog, PollHistory, CAPAlert, Boundary,
    GatedAlert, AlertGatingSettings,
)


@pytest.fixture(scope="module")
def app():
    """The real application object, bound to the configured PostgreSQL URL."""
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


def _wipe():
    for model in _MODELS:
        db.session.query(model).delete(synchronize_session=False)
    db.session.commit()


@pytest.fixture
def ctx(app):
    with app.app_context():
        _wipe()
        yield
        db.session.rollback()
        _wipe()
        db.session.remove()


@pytest.fixture
def stats_data(app, monkeypatch):
    """Call the /stats view and return the dict it hands the template.

    ``render_template`` is patched on the module that *calls* it. The view is
    invoked directly rather than through the test client so the app's global
    login redirect does not stand in the way of exercising the query layer.
    """
    import webapp.public.stats as stats_module

    def _run():
        captured = {}

        def _fake_render(template_name, **kwargs):
            captured["template"] = template_name
            captured["data"] = kwargs
            return "RENDERED"

        monkeypatch.setattr(stats_module, "render_template", _fake_render)

        with app.test_request_context("/stats"):
            result = app.view_functions["stats"]()

        assert result == "RENDERED", f"view did not render the template: {result!r}"
        assert captured["template"] == "stats.html"
        return captured["data"]

    return _run


def _alert(**kw):
    row = CAPAlert(**{
        "identifier": f"CAP-{kw.pop('n', 0)}",
        "sent": SENT,
        "status": "Actual",
        "message_type": "Alert",
        "scope": "Public",
        "event": "Tornado Warning",
        "severity": "Severe",
        "urgency": "Immediate",
        "certainty": "Observed",
        "source": "NWS",
        "expires": SENT + timedelta(hours=2),
        "eas_forwarded": False,
        **kw,
    })
    db.session.add(row)
    db.session.commit()
    return row


def _poll(**kw):
    row = PollHistory(**{
        "timestamp": SENT,
        "status": "success",
        "alerts_fetched": 3,
        "alerts_new": 1,
        "alerts_updated": 0,
        "execution_time_ms": 100,
        "error_message": None,
        "data_source": "NOAA",
        **kw,
    })
    db.session.add(row)
    db.session.commit()
    return row


# ---------------------------------------------------------------------------
# Basic counts and category breakdowns
# ---------------------------------------------------------------------------

def test_basic_counts(ctx, stats_data):
    from app_utils import utc_now

    db.session.add(Boundary(name="Allen", type="county"))
    db.session.commit()
    # "Active" is evaluated against the real clock, not the fixed SENT used by
    # the bucket tests, so these two need wall-clock-relative expiry.
    now = utc_now()
    _alert(n=1, sent=now - timedelta(minutes=5), expires=now + timedelta(hours=1))
    _alert(n=2, sent=now - timedelta(hours=3), expires=now - timedelta(hours=1))

    data = stats_data()
    assert data["total_boundaries"] == 1
    assert data["total_alerts"] == 2
    assert data["active_alerts"] == 1
    assert data["expired_alerts"] == 1


def test_boundary_stats_group_by_type(ctx, stats_data):
    for name, kind in [("Allen", "county"), ("Putnam", "county"), ("OHZ001", "zone")]:
        db.session.add(Boundary(name=name, type=kind))
    db.session.commit()

    data = stats_data()
    assert sorted(data["boundary_stats"], key=lambda r: r["type"]) == [
        {"type": "county", "count": 2},
        {"type": "zone", "count": 1},
    ]


def test_alert_category_breakdowns(ctx, stats_data):
    _alert(n=1, severity="Severe", event="Tornado Warning")
    _alert(n=2, severity="Severe", event="Tornado Warning")
    _alert(n=3, severity=None, event="Flood Watch")

    data = stats_data()
    assert data["alert_by_status"] == [{"status": "Actual", "count": 3}]
    # NULL severities are filtered out of the severity breakdown.
    assert data["alert_by_severity"] == [{"severity": "Severe", "count": 2}]
    assert data["alert_by_event"] == [
        {"event": "Tornado Warning", "count": 2},
        {"event": "Flood Watch", "count": 1},
    ]


def test_urgency_and_certainty_skip_nulls(ctx, stats_data):
    _alert(n=1, urgency="Immediate", certainty="Observed")
    _alert(n=2, urgency=None, certainty=None)

    data = stats_data()
    assert data["alert_by_urgency"] == [{"urgency": "Immediate", "count": 1}]
    assert data["alert_by_certainty"] == [{"certainty": "Observed", "count": 1}]


# ---------------------------------------------------------------------------
# Time-based buckets
# ---------------------------------------------------------------------------

def test_hour_dow_and_month_buckets(ctx, stats_data):
    _alert(n=1)

    data = stats_data()
    hourly = data["alert_by_hour"]
    assert len(hourly) == 24 and sum(hourly) == 1 and hourly[14] == 1

    dow = data["alert_by_dow"]
    # Postgres `extract(dow)` is 0=Sunday, so a Friday is 5.
    assert len(dow) == 7 and sum(dow) == 1 and dow[5] == 1

    months = data["alert_by_month"]
    # The month list is zero-indexed, so August (8) lands at index 7.
    assert len(months) == 12 and sum(months) == 1 and months[7] == 1


def test_year_bucket_excludes_epoch_corrupted_rows(ctx, stats_data):
    """Years older than five back are dropped to hide 1970 epoch defaults."""
    _alert(n=1)
    _alert(n=2, sent=datetime(1970, 1, 1, tzinfo=timezone.utc))

    data = stats_data()
    years = {row["year"] for row in data["alert_by_year"]}
    assert 1970 not in years
    assert 2026 in years


def test_dow_hour_matrix_and_daily_totals(ctx, stats_data):
    _alert(n=1)
    _alert(n=2)
    _alert(n=3, sent=SENT - timedelta(days=1))

    data = stats_data()
    matrix = data["dow_hour_matrix"]
    assert len(matrix) == 7 and all(len(row) == 24 for row in matrix)
    # Python weekday(): Friday is 4, and the handler maps it with (w + 1) % 7.
    assert matrix[5][14] == 2
    assert matrix[4][14] == 1  # the Thursday row

    assert data["daily_alerts"] == [
        {"date": "2026-08-06", "count": 1},
        {"date": "2026-08-07", "count": 2},
    ]
    assert data["recent_by_day"] == data["daily_alerts"][-30:]


def test_alert_events_and_filter_options(ctx, stats_data):
    _alert(n=1)
    # `event` is NOT NULL and `source` carries a server default of 'UNKNOWN',
    # so the "Unknown" fallbacks are reachable only through empty strings.
    _alert(n=2, severity=None, status="Test", event="", source="")

    data = stats_data()
    assert len(data["alert_events"]) == 2
    row = next(r for r in data["alert_events"] if r["identifier"] == "CAP-1")
    assert row["severity"] == "Severe"
    assert row["sent"] == SENT.isoformat()
    assert row["expires"] == (SENT + timedelta(hours=2)).isoformat()

    blank = next(r for r in data["alert_events"] if r["identifier"] == "CAP-2")
    assert blank["severity"] == "Unknown"
    assert blank["event"] == "Unknown"
    # `source` is normalized to the model's ALERT_SOURCE_UNKNOWN on insert, so
    # it is never blank by the time it reaches here — the collector's
    # `source or "Unknown"` fallback is unreachable in practice. Asserted as it
    # actually behaves rather than as the code reads.
    assert blank["source"] == "UNKNOWN"

    # Filter options collect only the non-empty values.
    assert data["filter_options"]["severities"] == ["Severe"]
    assert sorted(data["filter_options"]["statuses"]) == ["Actual", "Test"]
    assert data["filter_options"]["events"] == ["Tornado Warning"]


# ---------------------------------------------------------------------------
# Durations, coverage and derived rates
# ---------------------------------------------------------------------------

def test_duration_stats_in_hours(ctx, stats_data):
    _alert(n=1, expires=SENT + timedelta(hours=2))
    _alert(n=2, expires=SENT + timedelta(hours=4))
    # A non-positive duration is excluded rather than skewing the average.
    _alert(n=3, expires=SENT - timedelta(hours=1))

    data = stats_data()
    entry = next(r for r in data["duration_stats"] if r["event"] == "Tornado Warning")
    assert entry["count"] == 2
    assert entry["average"] == 3.0
    assert entry["minimum"] == 2.0
    assert entry["maximum"] == 4.0
    # The template reads `avg_durations`, which is an alias for the same list.
    assert data["avg_durations"] == data["duration_stats"]
    assert data["avg_durations"] != []


def test_eas_forwarding_rate(ctx, stats_data):
    _alert(n=1, eas_forwarded=True)
    _alert(n=2, eas_forwarded=False)
    _alert(n=3, eas_forwarded=False)
    _alert(n=4, eas_forwarded=False)

    data = stats_data()
    assert data["eas_forwarding_stats"] == {"forwarded": 1, "total": 4, "rate": 25.0}


def test_eas_forwarding_rate_keeps_one_decimal(ctx, stats_data):
    """1/3 must read 33.3, not 33 — the rate is rounded to one place."""
    _alert(n=1, eas_forwarded=True)
    _alert(n=2, eas_forwarded=False)
    _alert(n=3, eas_forwarded=False)

    assert stats_data()["eas_forwarding_stats"]["rate"] == 33.3


def test_eas_forwarding_rate_guards_zero_total(ctx, stats_data):
    data = stats_data()
    assert data["eas_forwarding_stats"] == {"forwarded": 0, "total": 0, "rate": 0}


def test_message_type_rates(ctx, stats_data):
    _alert(n=1, message_type="Alert")
    _alert(n=2, message_type="Cancel")
    _alert(n=3, message_type="Update")
    _alert(n=4, message_type="AllClear")

    data = stats_data()
    assert sorted(r["message_type"] for r in data["alert_by_message_type"]) == [
        "Alert", "AllClear", "Cancel", "Update",
    ]
    # Cancel and AllClear both count as cancellations; matching is case-folded.
    assert data["cancellation_rate"] == 50.0
    assert data["update_rate"] == 25.0


def test_coverage_overlap_rate_counts_distinct_alerts(ctx, stats_data):
    b = Boundary(name="Allen", type="county")
    db.session.add(b)
    db.session.commit()
    a1 = _alert(n=1)
    _alert(n=2)
    # Two intersections on the same alert must count once.
    db.session.add(Intersection(cap_alert_id=a1.id, boundary_id=b.id))
    db.session.add(Intersection(cap_alert_id=a1.id, boundary_id=b.id))
    db.session.commit()

    data = stats_data()
    assert data["alerts_with_coverage"] == 1
    assert data["coverage_overlap_rate"] == 50.0


def test_most_affected_boundaries(ctx, stats_data):
    b1 = Boundary(name="Allen", type="county")
    b2 = Boundary(name="Putnam", type="county")
    db.session.add_all([b1, b2])
    db.session.commit()
    a = _alert(n=1)
    db.session.add(Intersection(cap_alert_id=a.id, boundary_id=b1.id))
    db.session.add(Intersection(cap_alert_id=a.id, boundary_id=b1.id))
    db.session.add(Intersection(cap_alert_id=a.id, boundary_id=b2.id))
    db.session.commit()

    data = stats_data()
    assert data["most_affected_boundaries"] == [
        {"name": "Allen", "type": "county", "count": 2},
        {"name": "Putnam", "type": "county", "count": 1},
    ]


# ---------------------------------------------------------------------------
# Downstream subsystem stats
# ---------------------------------------------------------------------------

def test_manual_activation_and_received_eas_counts(ctx, stats_data):
    db.session.add(ManualEASActivation(
        identifier="MA-1", event_code="RWT", event_name="Required Weekly Test",
        status="TEST", message_type="Alert", same_header="ZCZC",
        tone_profile="attention", storage_path="/srv/a", created_at=SENT,
    ))
    for i, decision in enumerate(["forwarded", "ignored", "ignored"]):
        db.session.add(ReceivedEASAlert(
            received_at=SENT, source_name="mon", forwarding_decision=decision,
        ))
    db.session.commit()

    data = stats_data()
    assert data["manual_activation_count"] == 1
    assert data["received_eas_stats"] == {"total": 3, "forwarded": 1, "ignored": 2}


def test_relay_stats(ctx, stats_data):
    for success, duration, kind in [(True, 10.0, "alert"), (True, 20.0, "alert"),
                                    (False, 5.0, "test")]:
        db.session.add(GPIOActivationLog(
            activated_at=SENT, pin=17, activation_type=kind,
            duration_seconds=duration, success=success,
        ))
    db.session.commit()

    data = stats_data()
    assert data["relay_stats"]["total"] == 3
    assert data["relay_stats"]["success_rate"] == 66.7
    by_type = {r["type"]: r for r in data["relay_stats"]["by_type"]}
    assert by_type["alert"] == {"type": "alert", "count": 2, "avg_duration": 15.0}
    assert by_type["test"] == {"type": "test", "count": 1, "avg_duration": 5.0}


def test_broadcast_latency(ctx, stats_data):
    a = _alert(n=1)
    db.session.add(EASMessage(
        cap_alert_id=a.id, created_at=SENT + timedelta(seconds=30),
        same_header="ZCZC", audio_filename="a.wav", text_filename="a.txt",
    ))
    db.session.add(EASMessage(
        cap_alert_id=a.id, created_at=SENT + timedelta(seconds=90),
        same_header="ZCZC", audio_filename="b.wav", text_filename="b.txt",
    ))
    db.session.commit()

    data = stats_data()
    assert data["broadcast_latency"] == {
        "avg_seconds": 60.0, "min_seconds": 30.0,
        "max_seconds": 90.0, "total_broadcasts": 2,
    }


def test_broadcast_latency_is_none_without_matching_rows(ctx, stats_data):
    data = stats_data()
    assert data["broadcast_latency"] is None


def test_gated_alert_stats_counts_by_status(ctx, stats_data):
    db.session.add(AlertGatingSettings(id=1, enabled=True, hold_off_seconds=90))
    for status in ["pending", "pending", "released", "approved", "cancelled", "cancelled"]:
        db.session.add(GatedAlert(
            source="cap", status=status, hold_until=SENT + timedelta(minutes=2),
        ))
    db.session.commit()

    data = stats_data()
    assert data["gated_alert_stats"] == {
        "enabled": True, "hold_off_seconds": 90, "total": 6,
        "pending": 2, "released": 1, "approved": 1, "cancelled": 2,
    }


def test_gated_alert_stats_default_without_settings_row(ctx, stats_data):
    data = stats_data()
    assert data["gated_alert_stats"] == {
        "enabled": False, "hold_off_seconds": 0, "total": 0,
        "pending": 0, "released": 0, "approved": 0, "cancelled": 0,
    }


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def test_polling_metrics(ctx, stats_data):
    _poll(status="success", execution_time_ms=100)
    _poll(status="ok", execution_time_ms=200)
    _poll(status="failed", execution_time_ms=300, error_message="boom")

    data = stats_data()
    polling = data["polling"]
    assert polling["total_runs"] == 3
    assert polling["successful_polls"] == 2   # 'success' and 'ok' both count
    assert polling["failed_polls"] == 1
    assert polling["success_rate"] == pytest.approx(2 / 3)
    assert polling["average_execution_ms"] == pytest.approx(200.0)
    assert polling["avg_time_ms"] == polling["average_execution_ms"]
    assert polling["total_polls"] == polling["total_runs"]
    assert polling["last_error"] == "boom"
    assert len(polling["recent_runs"]) == 3


def test_polling_counts_a_success_status_with_an_error_as_failed(ctx, stats_data):
    """An error message outranks a success status in both tallies."""
    _poll(status="success", error_message="partial failure")

    polling = stats_data()["polling"]
    assert polling["successful_polls"] == 0
    assert polling["failed_polls"] == 1


def test_polling_defaults_with_no_history(ctx, stats_data):
    polling = stats_data()["polling"]
    assert polling == {
        "success_rate": 0, "total_runs": 0, "failed_runs": 0, "recent_runs": [],
        "total_polls": 0, "successful_polls": 0, "failed_polls": 0, "avg_time_ms": 0,
    }


def test_polling_recent_runs_capped_at_ten(ctx, stats_data):
    for i in range(15):
        _poll(timestamp=SENT - timedelta(minutes=i))

    assert len(stats_data()["polling"]["recent_runs"]) == 10


def test_polling_trend_windows(ctx, stats_data):
    from app_utils import utc_now

    now = utc_now()
    _poll(timestamp=now - timedelta(days=1), status="success", execution_time_ms=100)
    _poll(timestamp=now - timedelta(days=1), status="failed", execution_time_ms=200)
    _poll(timestamp=now - timedelta(days=20), status="success", execution_time_ms=300)
    _poll(timestamp=now - timedelta(days=90), status="success", execution_time_ms=999)

    # Sits between the two windows: counted by 30d, excluded by 7d. Without it
    # a 7d→14d drift in the cutoff would be invisible.
    _poll(timestamp=now - timedelta(days=10), status="success", execution_time_ms=400)

    trend = stats_data()["polling_trend"]
    assert trend["count_7d"] == 2
    assert trend["count_30d"] == 4
    assert trend["rate_7d"] == 50.0
    assert trend["rate_30d"] == 75.0
    # The 90-day-old run is outside both windows and must not reach the p95.
    assert trend["p95_execution_ms"] == 400


def test_polling_trend_p95_is_a_percentile_not_a_maximum(ctx, stats_data):
    """With enough samples the 95th percentile must sit below the maximum.

    Fewer than ~21 samples makes `int(len * 0.95)` land on the last index, so
    a p95-turned-max regression hides. 25 samples separates them.
    """
    from app_utils import utc_now

    now = utc_now()
    for i in range(25):
        _poll(timestamp=now - timedelta(days=1, minutes=i), execution_time_ms=(i + 1) * 10)

    trend = stats_data()["polling_trend"]
    assert trend["count_30d"] == 25
    # sorted times are 10..250; int(25 * 0.95) == 23 -> the 24th value.
    assert trend["p95_execution_ms"] == 240
    assert trend["p95_execution_ms"] != 250  # i.e. not simply the max


def test_polling_trend_defaults_when_empty(ctx, stats_data):
    assert stats_data()["polling_trend"] == {
        "rate_7d": 0, "rate_30d": 0, "count_7d": 0,
        "count_30d": 0, "p95_execution_ms": 0,
    }


# ---------------------------------------------------------------------------
# Fallbacks — every collector declares one, and the template indexes them all
# ---------------------------------------------------------------------------

EXPECTED_KEYS = {
    "total_boundaries", "total_alerts", "active_alerts", "expired_alerts",
    "boundary_stats", "alert_by_status", "alert_by_severity", "alert_by_event",
    "alert_by_hour", "alert_by_dow", "alert_by_month", "alert_by_year",
    "most_affected_boundaries", "duration_stats", "avg_durations",
    "alert_by_urgency", "alert_by_certainty", "eas_forwarding_stats",
    "manual_activation_count", "received_eas_stats", "alert_events",
    "filter_options", "daily_alerts", "recent_by_day", "dow_hour_matrix",
    "polling", "alert_by_message_type",
    "cancellation_rate", "update_rate", "coverage_overlap_rate",
    "alerts_with_coverage", "broadcast_latency", "relay_stats", "polling_trend",
    "gated_alert_stats",
}


def test_every_expected_key_is_present_on_an_empty_database(ctx, stats_data):
    data = stats_data()
    missing = EXPECTED_KEYS - set(data)
    assert not missing, f"stats.html would KeyError on: {sorted(missing)}"


def test_shape_defaults_on_an_empty_database(ctx, stats_data):
    data = stats_data()
    assert data["alert_by_hour"] == [0] * 24
    assert data["alert_by_dow"] == [0] * 7
    assert data["alert_by_month"] == [0] * 12
    assert data["dow_hour_matrix"] == [[0] * 24 for _ in range(7)]
    assert data["filter_options"] == {"severities": [], "statuses": [], "events": []}
    assert data["avg_durations"] == data["duration_stats"]
    assert data["gated_alert_stats"] == {
        "enabled": False, "hold_off_seconds": 0, "total": 0,
        "pending": 0, "released": 0, "approved": 0, "cancelled": 0,
    }


class _Boom:
    """A stand-in query object that raises however it is used."""

    def __getattr__(self, name):
        def _raise(*args, **kwargs):
            raise RuntimeError("table gone")
        return _raise


@pytest.mark.parametrize(
    "broken_model,affected",
    [
        (GPIOActivationLog, {"relay_stats": {"total": 0, "success_rate": 0, "by_type": []}}),
        (ManualEASActivation, {"manual_activation_count": 0}),
        (ReceivedEASAlert, {"received_eas_stats": {"total": 0, "forwarded": 0, "ignored": 0}}),
        (GatedAlert, {"gated_alert_stats": {
            "enabled": False, "hold_off_seconds": 0, "total": 0,
            "pending": 0, "released": 0, "approved": 0, "cancelled": 0,
        }}),
    ],
)
def test_a_failing_collector_falls_back_without_killing_the_page(
    ctx, stats_data, monkeypatch, broken_model, affected
):
    """One collector raising must not lose the whole dashboard."""
    _alert(n=1)
    monkeypatch.setattr(broken_model, "query", _Boom())

    data = stats_data()
    for key, expected in affected.items():
        assert data[key] == expected
    # The rest of the dashboard still rendered.
    assert data["total_alerts"] == 1
    assert EXPECTED_KEYS - set(data) == set()


def test_the_four_basic_counts_fail_together(ctx, stats_data, monkeypatch):
    """They share one try block, so any one of them failing zeroes all four.

    Pinned deliberately: it is the current behaviour and the split must not
    quietly change it. Giving each count its own fallback would be a
    behavioural improvement, and belongs in its own commit.
    """
    _alert(n=1)
    monkeypatch.setattr(Boundary, "query", _Boom())

    data = stats_data()
    assert data["total_boundaries"] == 0
    assert data["total_alerts"] == 0      # not 1, despite the alert existing
    assert data["active_alerts"] == 0
    assert data["expired_alerts"] == 0
    assert data["boundary_stats"] == []
    # Everything downstream of the shared block still populated.
    assert EXPECTED_KEYS - set(data) == set()
    assert data["alert_by_status"] == [{"status": "Actual", "count": 1}]
