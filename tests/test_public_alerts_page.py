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

"""Characterization tests for the /alerts browse surface and its PDF export.

Written *before* the 385-line ``alerts()`` handler and the ~175-line
``alerts_export_pdf()`` were decomposed into ``webapp/public/alerts_page/``.

Unlike /logs (a dispatch) and /stats (an accumulation), this one is a
**pipeline**: parse request args → load filter options → build a query → apply
sorting → paginate (with a hand-rolled fallback) → enrich with audio. So what
these tests pin is the behaviour of each stage as observed at the boundary —
the kwargs handed to the template, and the arguments handed to the PDF
generator.

The sharp edges covered here:

* **Input clamping.** ``page``, ``per_page``, ``sort`` and ``direction`` are all
  attacker-controlled and are each clamped or allow-listed.
* **The VTEC override.** Browsing a VTEC event chain forces expired *and*
  superseded alerts back into view, otherwise the chain would have holes.
* **The pagination fallback.** When ``paginate()`` raises, a hand-rolled
  ``MockPagination`` takes over, and the template calls ``iter_pages()`` on it.
* **The two query builders differ.** The PDF export applies a strict subset of
  the page's filters — no VTEC, no date range, no superseded handling. That is
  pinned as current behaviour, not endorsed.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

_DB_URL = os.environ.get("DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not _DB_URL.startswith(("postgresql", "postgres://")),
    reason="needs a PostgreSQL DATABASE_URL (CAPAlert uses a PostGIS geometry column)",
)

from app_core.extensions import db  # noqa: E402
from app_core.models import CAPAlert, EASMessage, ManualEASActivation  # noqa: E402

BASE = datetime(2026, 8, 7, 12, 0, 0, tzinfo=timezone.utc)

# Alerts are hidden once they expire, so the default row needs an expiry the
# real clock will not overtake — otherwise every filtering test silently
# degrades into "the page shows nothing".
FAR_FUTURE = datetime(2099, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def app():
    from app import app as flask_app

    flask_app.config["TESTING"] = True
    return flask_app


def _wipe():
    for model in (EASMessage, ManualEASActivation, CAPAlert):
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
def render_alerts(app, monkeypatch):
    """GET /alerts with the given query string; return the template kwargs.

    ``render_template`` is replaced on the module that calls it, and the view
    is invoked directly so the app's global login redirect stays out of the way.
    """
    import webapp.public.alerts as alerts_module

    def _run(query_string=""):
        captured = {}

        def _fake_render(template_name, **kwargs):
            captured["template"] = template_name
            captured["data"] = kwargs
            return "RENDERED"

        monkeypatch.setattr(alerts_module, "render_template", _fake_render)

        path = "/alerts" + (f"?{query_string}" if query_string else "")
        with app.test_request_context(path):
            result = app.view_functions["alerts"]()

        assert result == "RENDERED", f"view did not render: {str(result)[:200]}"
        assert captured["template"] == "alerts.html"
        return captured["data"]

    return _run


@pytest.fixture
def export_pdf(app, monkeypatch):
    """GET /alerts/export.pdf; return the kwargs handed to the PDF generator."""
    import webapp.public.alerts as alerts_module

    def _run(query_string=""):
        captured = {}

        def _fake_generate(**kwargs):
            captured.update(kwargs)
            return b"%PDF-1.4 fake"

        monkeypatch.setattr(alerts_module, "generate_pdf_document", _fake_generate)

        path = "/alerts/export.pdf" + (f"?{query_string}" if query_string else "")
        with app.test_request_context(path):
            response = app.view_functions["alerts_export_pdf"]()

        assert getattr(response, "mimetype", None) == "application/pdf", (
            f"export did not return a PDF: {str(response)[:200]}"
        )
        captured["_headers"] = dict(response.headers)
        return captured

    return _run


def _alert(n, **kw):
    row = CAPAlert(**{
        "identifier": f"CAP-{n}",
        "sent": BASE - timedelta(minutes=n),
        "expires": FAR_FUTURE,
        "status": "Actual",
        "message_type": "Alert",
        "scope": "Public",
        "event": "Tornado Warning",
        "severity": "Severe",
        "source": "NOAA",
        "headline": f"Headline {n}",
        "description": f"Description {n}",
        "area_desc": f"Area {n}",
        **kw,
    })
    db.session.add(row)
    db.session.commit()
    return row


def _identifiers(data):
    return [a.identifier for a in data["alerts"]]


# ---------------------------------------------------------------------------
# Request-parameter clamping and validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query_string,expected_per_page",
    [
        ("", 25),            # default
        ("per_page=50", 50),
        ("per_page=1", 10),   # clamped up to the floor
        ("per_page=5000", 100),  # clamped down to the ceiling
        ("per_page=notanumber", 25),  # type=int coercion failure -> default
    ],
)
def test_per_page_is_clamped(ctx, render_alerts, query_string, expected_per_page):
    data = render_alerts(query_string)
    assert data["current_filters"]["per_page"] == expected_per_page
    assert data["pagination"].per_page == expected_per_page


@pytest.mark.parametrize(
    "query_string,expected_page",
    [("", 1), ("page=3", 3), ("page=0", 1), ("page=-7", 1)],
)
def test_page_is_floored_at_one(ctx, render_alerts, query_string, expected_page):
    data = render_alerts(query_string)
    assert data["pagination"].page == expected_page


@pytest.mark.parametrize(
    "query_string,expected_sort,expected_direction",
    [
        ("", "sent", "desc"),
        ("sort=severity&direction=asc", "severity", "asc"),
        ("sort=SEVERITY&direction=ASC", "severity", "asc"),   # case-folded
        ("sort=drop_table&direction=asc", "sent", "asc"),      # not allow-listed
        ("sort=event&direction=sideways", "event", "desc"),    # bad direction
    ],
)
def test_sort_is_allowlisted(ctx, render_alerts, query_string, expected_sort,
                             expected_direction):
    data = render_alerts(query_string)
    assert data["current_filters"]["sort"] == expected_sort
    assert data["current_filters"]["direction"] == expected_direction


def test_sorting_actually_orders_the_rows(ctx, render_alerts):
    _alert(1, event="Alpha")
    _alert(2, event="Zulu")

    assert _identifiers(render_alerts("sort=event&direction=asc")) == ["CAP-1", "CAP-2"]
    assert _identifiers(render_alerts("sort=event&direction=desc")) == ["CAP-2", "CAP-1"]


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def test_search_spans_headline_description_event_and_area(ctx, render_alerts):
    _alert(1, headline="tornado approaching", description="d", event="E1", area_desc="a")
    _alert(2, headline="h", description="tornado debris", event="E2", area_desc="a")
    _alert(3, headline="h", description="d", event="Tornado Warning", area_desc="a")
    _alert(4, headline="h", description="d", event="E4", area_desc="Tornado County")
    _alert(5, headline="h", description="d", event="E5", area_desc="a")

    found = set(_identifiers(render_alerts("search=tornado")))
    assert found == {"CAP-1", "CAP-2", "CAP-3", "CAP-4"}


@pytest.mark.parametrize(
    "query_string,expected",
    [
        ("status=Test", {"CAP-2"}),
        ("severity=Minor", {"CAP-2"}),
        ("event=Flood Watch", {"CAP-2"}),
        ("source=IPAWS", {"CAP-2"}),
    ],
)
def test_exact_match_filters(ctx, render_alerts, query_string, expected):
    _alert(1)
    _alert(2, status="Test", severity="Minor", event="Flood Watch", source="IPAWS")

    assert set(_identifiers(render_alerts(query_string))) == expected


def test_empty_filter_values_mean_no_filter(ctx, render_alerts):
    _alert(1)
    _alert(2, status="Test")
    assert len(_identifiers(render_alerts("status=&severity=&event="))) == 2


def test_date_range_filters(ctx, render_alerts):
    _alert(1, sent=datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc))
    _alert(2, sent=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc))
    _alert(3, sent=datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc))

    assert set(_identifiers(render_alerts("date_from=2026-08-05"))) == {"CAP-2", "CAP-3"}
    # date_to is inclusive of the whole day (the filter adds one day and uses <).
    assert set(_identifiers(render_alerts("date_to=2026-08-05"))) == {"CAP-1", "CAP-2"}
    assert set(_identifiers(render_alerts("date_from=2026-08-05&date_to=2026-08-05"))) == {"CAP-2"}


def test_an_unparseable_date_is_dropped_and_cleared(ctx, render_alerts):
    """A bad date must not filter anything out, and must not echo back."""
    _alert(1)
    data = render_alerts("date_from=not-a-date&date_to=13/45/2026")
    assert len(data["alerts"]) == 1
    assert data["current_filters"]["date_from"] == ""
    assert data["current_filters"]["date_to"] == ""


@pytest.mark.parametrize("raw", ["true", "1", "t", "yes", "on", "TRUE", "Yes"])
def test_show_expired_accepts_many_truthy_spellings(ctx, render_alerts, raw):
    _alert(1, expires=BASE - timedelta(days=400), status="Actual")
    assert len(render_alerts(f"show_expired={raw}")["alerts"]) == 1


@pytest.mark.parametrize("raw", ["", "false", "0", "no", "off", "maybe"])
def test_expired_alerts_are_hidden_by_default(ctx, render_alerts, raw):
    _alert(1, expires=BASE - timedelta(days=400), status="Actual")
    _alert(2, expires=None, status="Actual")   # no expiry always shows
    assert _identifiers(render_alerts(f"show_expired={raw}")) == ["CAP-2"]


def test_status_expired_is_hidden_even_with_a_future_expiry(ctx, render_alerts):
    from app_utils import utc_now

    _alert(1, status="Expired", expires=utc_now() + timedelta(days=1))
    _alert(2, status="Actual", expires=utc_now() + timedelta(days=1))
    assert _identifiers(render_alerts()) == ["CAP-2"]


def test_superseded_alerts_are_hidden_by_default(ctx, render_alerts):
    from app_utils import utc_now

    newer = _alert(1, expires=utc_now() + timedelta(days=1))
    _alert(2, expires=utc_now() + timedelta(days=1), superseded_by_id=newer.id)

    assert _identifiers(render_alerts()) == ["CAP-1"]
    assert set(_identifiers(render_alerts("show_superseded=true"))) == {"CAP-1", "CAP-2"}


# ---------------------------------------------------------------------------
# VTEC event chains
# ---------------------------------------------------------------------------

def test_vtec_filters_narrow_to_one_event_chain(ctx, render_alerts):
    from app_utils import utc_now

    _alert(1, expires=utc_now() + timedelta(days=1),
           vtec_office="KIWX", vtec_etn=17, vtec_year=2026)
    _alert(2, expires=utc_now() + timedelta(days=1),
           vtec_office="KCLE", vtec_etn=17, vtec_year=2026)

    assert _identifiers(render_alerts("vtec_office=KIWX")) == ["CAP-1"]
    assert set(_identifiers(render_alerts("vtec_etn=17"))) == {"CAP-1", "CAP-2"}
    assert set(_identifiers(render_alerts("vtec_year=2026"))) == {"CAP-1", "CAP-2"}


def test_a_vtec_chain_shows_expired_and_superseded_members(ctx, render_alerts):
    """Otherwise the chain would render with holes in it."""
    from app_utils import utc_now

    live = _alert(1, expires=utc_now() + timedelta(days=1),
                  vtec_office="KIWX", vtec_etn=17, vtec_year=2026)
    _alert(2, status="Expired", expires=BASE - timedelta(days=400),
           vtec_office="KIWX", vtec_etn=17, vtec_year=2026)
    _alert(3, expires=utc_now() + timedelta(days=1), superseded_by_id=live.id,
           vtec_office="KIWX", vtec_etn=17, vtec_year=2026)

    data = render_alerts("vtec_office=KIWX")
    assert set(_identifiers(data)) == {"CAP-1", "CAP-2", "CAP-3"}
    assert data["vtec_filter_active"] is True


def test_vtec_filter_active_is_false_without_vtec_args(ctx, render_alerts):
    assert render_alerts()["vtec_filter_active"] is False


@pytest.mark.parametrize("query_string", ["vtec_etn=abc", "vtec_year=nineteen"])
def test_a_non_numeric_vtec_filter_is_ignored_but_still_activates_the_chain(
    ctx, render_alerts, query_string
):
    """The int() cast fails and the filter is skipped — but the flag is already
    set from the raw string, so expired/superseded stay visible."""
    _alert(1, expires=BASE - timedelta(days=400), status="Actual")

    data = render_alerts(query_string)
    assert data["vtec_filter_active"] is True
    assert len(data["alerts"]) == 1


# ---------------------------------------------------------------------------
# Filter options, counts and the echoed filter state
# ---------------------------------------------------------------------------

def test_filter_options_and_counts(ctx, render_alerts):
    from app_utils import utc_now

    _alert(1, status="Actual", severity="Severe", event="Tornado Warning", source="NOAA",
           expires=utc_now() + timedelta(days=1))
    _alert(2, status="Test", severity="Minor", event="Flood Watch", source="IPAWS",
           expires=utc_now() - timedelta(days=1))
    newer = _alert(3, expires=utc_now() + timedelta(days=1))
    _alert(4, expires=utc_now() + timedelta(days=1), superseded_by_id=newer.id)

    data = render_alerts()
    assert data["statuses"] == ["Actual", "Test"]
    assert data["severities"] == ["Minor", "Severe"]
    assert data["events"] == ["Flood Watch", "Tornado Warning"]
    assert data["sources"] == ["IPAWS", "NOAA"]
    assert data["total_alerts"] == 4
    assert data["active_alerts"] == 2   # CAP-2 is expired, CAP-4 superseded
    # "Expired" is the complement of "active", so a superseded alert with a
    # future expiry counts here too — it is not simply an expires < now test.
    assert data["expired_alerts"] == 2
    assert data["superseded_count"] == 1


def test_filter_options_survive_a_database_failure(ctx, render_alerts, monkeypatch):
    """The page must still render, with empty options and zeroed counts."""
    import webapp.public.alerts as alerts_module

    calls = {"n": 0}
    real_query = db.session.query

    def _boom(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("options query failed")

    # Only the filter-option lookups go through db.session.query in this
    # handler; the alert listing itself uses CAPAlert.query.
    monkeypatch.setattr(db.session, "query", _boom)
    try:
        data = render_alerts()
    finally:
        monkeypatch.setattr(db.session, "query", real_query)

    assert calls["n"] > 0
    assert data["statuses"] == []
    assert data["severities"] == []
    assert data["events"] == []
    assert data["sources"] == []
    assert data["total_alerts"] == 0
    assert data["active_alerts"] == 0
    assert data["expired_alerts"] == 0
    assert data["superseded_count"] == 0
    assert alerts_module is not None


def test_current_filters_echoes_every_input(ctx, render_alerts):
    data = render_alerts(
        "search=tor&status=Actual&severity=Severe&event=Tornado+Warning"
        "&source=NOAA&per_page=50&show_expired=true&show_superseded=true"
        "&date_from=2026-08-01&date_to=2026-08-09"
        "&vtec_office=KIWX&vtec_etn=17&vtec_year=2026"
        "&sort=severity&direction=asc"
    )
    assert data["current_filters"] == {
        "search": "tor",
        "status": "Actual",
        "severity": "Severe",
        "event": "Tornado Warning",
        "source": "NOAA",
        "per_page": 50,
        "show_expired": True,
        "show_superseded": True,
        "date_from": "2026-08-01",
        "date_to": "2026-08-09",
        "vtec_office": "KIWX",
        "vtec_etn": "17",
        "vtec_year": "2026",
        "sort": "severity",
        "direction": "asc",
    }


def test_whitespace_is_stripped_from_text_filters(ctx, render_alerts):
    data = render_alerts("search=%20%20tornado%20%20&status=%20Actual%20")
    assert data["current_filters"]["search"] == "tornado"
    assert data["current_filters"]["status"] == "Actual"


# ---------------------------------------------------------------------------
# Pagination, including the hand-rolled fallback
# ---------------------------------------------------------------------------

def test_pagination_splits_pages(ctx, render_alerts):
    for i in range(1, 6):
        _alert(i)

    first = render_alerts("per_page=10&page=1")
    assert len(first["alerts"]) == 5
    assert first["pagination"].total == 5
    assert first["pagination"].pages == 1
    assert first["pagination"].has_next is False


@pytest.fixture
def broken_paginate(monkeypatch):
    """Make ``Query.paginate`` raise, forcing the hand-rolled fallback."""
    from app_core.models import CAPAlert as _CAPAlert

    query_cls = type(_CAPAlert.query)
    assert hasattr(query_cls, "paginate"), "expected a paginate() to break"

    def _boom(self, *args, **kwargs):
        raise RuntimeError("paginate exploded")

    monkeypatch.setattr(query_cls, "paginate", _boom)


def test_fallback_pagination_still_floors_the_page_at_one(ctx, render_alerts, broken_paginate):
    """flask-sqlalchemy normalises page<1 itself, so the handler's own
    ``max(1, page)`` is only observable once the fallback takes over — where the
    value is used raw to compute the offset."""
    for i in range(1, 4):
        _alert(i)

    data = render_alerts("page=0")
    assert data["pagination"].page == 1
    assert data["pagination"].has_prev is False
    assert len(data["alerts"]) == 3


def test_pagination_falls_back_when_paginate_raises(ctx, render_alerts, broken_paginate):
    for i in range(1, 8):
        _alert(i)

    data = render_alerts("per_page=10&page=1")
    pagination = data["pagination"]

    assert len(data["alerts"]) == 7
    assert pagination.total == 7
    assert pagination.page == 1
    assert pagination.per_page == 10
    assert pagination.pages == 1
    assert pagination.has_prev is False
    assert pagination.has_next is False
    assert pagination.prev_num is None
    assert pagination.next_num is None


def test_fallback_pagination_computes_page_links(ctx, render_alerts, broken_paginate):
    # per_page has a floor of 10, so 25 rows across 10 per page gives 3 pages.
    for i in range(1, 26):
        _alert(i)

    data = render_alerts("per_page=10&page=2")
    pagination = data["pagination"]

    assert pagination.pages == 3          # ceil(25 / 10)
    assert pagination.page == 2
    assert pagination.has_prev is True
    assert pagination.has_next is True
    assert pagination.prev_num == 1
    assert pagination.next_num == 3
    assert len(data["alerts"]) == 10
    # The template calls iter_pages(); it must yield real page numbers.
    assert list(pagination.iter_pages()) == [1, 2, 3]


def test_fallback_pagination_offsets_correctly(ctx, render_alerts, broken_paginate):
    for i in range(1, 26):
        _alert(i)

    page1 = _identifiers(render_alerts("per_page=10&page=1"))
    page3 = _identifiers(render_alerts("per_page=10&page=3"))
    assert len(page1) == 10
    assert len(page3) == 5            # the remainder
    assert not set(page1) & set(page3)


def test_fallback_pagination_elides_long_page_runs(ctx, render_alerts, broken_paginate):
    """iter_pages inserts None as the '...' marker on long runs.

    Driven directly rather than by seeding thousands of rows: the elision only
    shows up past ~10 pages, and per_page cannot go below 10, so reaching it
    through the database would need 100+ alerts per assertion.
    """
    _alert(1)
    pagination = render_alerts()["pagination"]
    pagination.pages = 60
    pagination.page = 30

    pages = list(pagination.iter_pages())
    assert pages[:2] == [1, 2]                       # left edge
    assert pages[-2:] == [59, 60]                    # right edge
    assert None in pages                             # the ellipsis marker
    assert [28, 29, 30, 31, 32] == [p for p in pages if p and 27 < p < 33]
    # Far-away pages are elided rather than listed.
    assert 45 not in pages


def test_a_total_pagination_failure_yields_an_empty_page(
    ctx, render_alerts, broken_paginate, monkeypatch
):
    """Both the paginate call and the offset/limit fallback failing is survivable."""
    from app_core.models import CAPAlert as _CAPAlert

    _alert(1)
    query_cls = type(_CAPAlert.query)

    def _boom(self, *args, **kwargs):
        raise RuntimeError("count exploded")

    monkeypatch.setattr(query_cls, "count", _boom)

    data = render_alerts()
    assert data["alerts"] == []
    assert data["pagination"].total == 0
    assert data["pagination"].pages == 0


# ---------------------------------------------------------------------------
# Enrichment: audio map and manual activations
# ---------------------------------------------------------------------------

def test_audio_map_links_eas_messages_to_their_alert(ctx, render_alerts):
    a = _alert(1)
    _alert(2)
    m1 = EASMessage(cap_alert_id=a.id, created_at=BASE, same_header="ZCZC",
                    audio_filename="a.wav", text_filename="a.txt",
                    text_payload="body")
    m2 = EASMessage(cap_alert_id=a.id, created_at=BASE - timedelta(minutes=1),
                    same_header="ZCZC", audio_filename="b.wav",
                    text_filename="b.txt", text_payload=None)
    db.session.add_all([m1, m2])
    db.session.commit()

    audio_map = render_alerts()["audio_map"]
    assert set(audio_map) == {a.id}
    entries = audio_map[a.id]
    assert len(entries) == 2
    # A message with a text_payload links to the rendered summary; one without
    # falls back to its static text file.
    with_payload = next(e for e in entries if e["id"] == m1.id)
    without = next(e for e in entries if e["id"] == m2.id)
    # Both branches yield a URL, so the shapes must be told apart explicitly:
    # a stored text_payload is rendered by a route, everything else is served
    # as a static file. Compared by shape rather than url_for(), which needs a
    # request context this assertion no longer has.
    assert "/static/" not in with_payload["text_url"]
    assert str(m1.id) in with_payload["text_url"]
    assert "/static/" in without["text_url"]
    # Static URLs carry a ?v=<version> cache-buster, so match the path part.
    assert without["text_url"].split("?")[0].endswith("b.txt")
    assert all(e["audio_url"] for e in entries)
    assert all(e["detail_url"] for e in entries)


def test_audio_map_is_empty_without_messages(ctx, render_alerts):
    _alert(1)
    assert render_alerts()["audio_map"] == {}


def test_manual_messages_are_the_ten_newest(ctx, render_alerts):
    for i in range(12):
        db.session.add(ManualEASActivation(
            identifier=f"MA-{i}", event_code="RWT", event_name="Test",
            status="TEST", message_type="Alert", same_header="ZCZC",
            tone_profile="attention", storage_path="/srv/a",
            created_at=BASE - timedelta(minutes=i),
        ))
    db.session.commit()

    manual = render_alerts()["manual_messages"]
    assert len(manual) == 10
    assert [m.identifier for m in manual] == [f"MA-{i}" for i in range(10)]


# ---------------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------------

def test_pdf_export_headers_and_title(ctx, export_pdf):
    _alert(1)
    captured = export_pdf()

    assert captured["title"] == "Alerts Export"
    assert "EAS Station" in captured["footer_text"]
    disposition = captured["_headers"]["Content-Disposition"]
    assert disposition.startswith("inline; filename=alerts_export_")
    assert disposition.endswith(".pdf")


def test_pdf_export_renders_each_alert_as_a_block(ctx, export_pdf):
    _alert(1, headline="Big storm", area_desc="Allen County",
           description="Take shelter now")
    captured = export_pdf()

    section = captured["sections"][0]
    assert section["heading"] == "Alerts Export (1 alerts)"
    content = section["content"]
    assert "Event: Tornado Warning" in content
    assert "Severity: Severe" in content
    assert "Status: Actual" in content
    assert "Source: NOAA" in content
    assert "Headline: Big storm" in content
    assert "Area: Allen County" in content
    assert "Description: Take shelter now" in content
    assert content[-1] == ""       # blank separator after each block


def test_pdf_export_omits_absent_optional_fields(ctx, export_pdf):
    _alert(1, headline=None, area_desc=None, description=None)
    content = export_pdf()["sections"][0]["content"]

    assert not any(line.startswith("Headline:") for line in content)
    assert not any(line.startswith("Area:") for line in content)
    assert not any(line.startswith("Description:") for line in content)


def test_pdf_export_truncates_long_descriptions(ctx, export_pdf):
    _alert(1, description="x" * 900)
    content = export_pdf()["sections"][0]["content"]

    desc_line = next(line for line in content if line.startswith("Description:"))
    assert desc_line.endswith("...")
    assert len(desc_line) == len("Description: ") + 500 + 3


def test_pdf_export_keeps_a_description_at_the_boundary_intact(ctx, export_pdf):
    _alert(1, description="y" * 500)
    content = export_pdf()["sections"][0]["content"]

    desc_line = next(line for line in content if line.startswith("Description:"))
    assert not desc_line.endswith("...")


def test_pdf_export_labels_missing_expiry(ctx, export_pdf):
    _alert(1, expires=None)
    content = export_pdf()["sections"][0]["content"]
    assert "Expires: No expiration" in content


def test_pdf_export_reports_no_alerts_found(ctx, export_pdf):
    section = export_pdf()["sections"][0]
    assert section["heading"] == "Alerts Export (0 alerts)"
    assert section["content"] == ["No alerts found"]


@pytest.mark.parametrize(
    "query_string,expected_subtitle",
    [
        ("show_expired=true", "All alerts"),
        ("", "Active alerts only"),
        ("search=tor&show_expired=true", "Search: tor"),
        ("status=Actual&severity=Severe&show_expired=true",
         "Status: Actual | Severity: Severe"),
        ("event=Tornado+Warning&source=NOAA&show_expired=true",
         "Event: Tornado Warning | Source: NOAA"),
        ("search=tor", "Search: tor | Active alerts only"),
    ],
)
def test_pdf_export_subtitle_summarises_the_filters(
    ctx, export_pdf, query_string, expected_subtitle
):
    assert export_pdf(query_string)["subtitle"] == expected_subtitle


def test_pdf_export_applies_the_same_basic_filters_as_the_page(ctx, export_pdf):
    _alert(1, event="Tornado Warning")
    _alert(2, event="Flood Watch")

    content = export_pdf("event=Flood+Watch")["sections"][0]["content"]
    assert "Event: Flood Watch" in content
    assert "Event: Tornado Warning" not in content


def test_pdf_export_hides_expired_alerts_by_default(ctx, export_pdf):
    from app_utils import utc_now

    _alert(1, expires=utc_now() + timedelta(days=1))
    _alert(2, expires=utc_now() - timedelta(days=1), event="Flood Watch")

    assert export_pdf()["sections"][0]["heading"] == "Alerts Export (1 alerts)"
    assert export_pdf("show_expired=true")["sections"][0]["heading"] == "Alerts Export (2 alerts)"


def test_pdf_export_ignores_filters_the_page_supports(ctx, export_pdf):
    """Pinned as current behaviour, not endorsed.

    The export's query builder is a strict subset of the page's: it has no
    VTEC, date-range or superseded handling, so passing those narrows the page
    but not the PDF. Worth knowing before anyone assumes the two agree.
    """
    from app_utils import utc_now

    newer = _alert(1, expires=utc_now() + timedelta(days=1),
                   sent=datetime(2026, 8, 1, tzinfo=timezone.utc))
    _alert(2, expires=utc_now() + timedelta(days=1), superseded_by_id=newer.id,
           sent=datetime(2026, 8, 9, tzinfo=timezone.utc))

    # Superseded rows are excluded from the page but included in the PDF.
    assert export_pdf()["sections"][0]["heading"] == "Alerts Export (2 alerts)"
    # A date range the page would honour has no effect here.
    assert export_pdf("date_from=2026-08-09")["sections"][0]["heading"] == "Alerts Export (2 alerts)"
    # Likewise a VTEC office that matches nothing.
    assert export_pdf("vtec_office=KIWX")["sections"][0]["heading"] == "Alerts Export (2 alerts)"
