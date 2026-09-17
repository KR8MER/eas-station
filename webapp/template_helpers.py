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

Repository: https://github.com/KR8MER/eas-station
"""

from __future__ import annotations

"""Template filter and global registrations for the Flask app."""

from flask import Flask
from markupsafe import Markup, escape

from app_utils import (
    format_local,
    format_local_date,
    format_local_datetime,
    format_local_time,
    get_location_timezone_name,
    is_alert_expired,
    local_now,
    to_location_time,
    utc_now,
)


def register(app: Flask) -> None:
    """Attach the project's shared Jinja filters and globals to *app*."""

    app.add_template_filter(_nl2br_filter, name="nl2br")
    app.add_template_filter(_cap_paragraphs_filter, name="cap_paragraphs")
    # `localtime` is the filter templates should reach for when rendering a stored
    # timestamp. Calling `.strftime()` directly on a column renders raw UTC, which
    # reads as hours-off against the operator's wall clock.
    app.add_template_filter(format_local, name="localtime")
    app.add_template_filter(to_location_time, name="to_local")
    app.add_template_filter(format_local_datetime, name="format_local_datetime")
    app.add_template_filter(format_local_date, name="format_local_date")
    app.add_template_filter(format_local_time, name="format_local_time")
    app.add_template_filter(is_alert_expired, name="is_expired")

    app.add_template_global(utc_now, name="current_time")
    app.add_template_global(local_now, name="local_current_time")
    # Exposed so client-side clocks can render in the station's configured zone
    # instead of the browser's. base.html stamps it onto <body data-timezone>,
    # which static/js/core/utils.js reads.
    app.add_template_global(get_location_timezone_name, name="station_timezone")
    app.add_template_global(min, name="min")
    app.add_template_global(max, name="max")


def _nl2br_filter(text: str | None) -> Markup:
    """Escape *text*, then convert newlines to ``<br>``, as a single Markup.

    Templates must not spell this out inline as
    ``{{ text | e | replace('\\n', '<br>') | safe }}``: once ``| e`` has
    produced a ``Markup`` instance, Jinja's ``|replace`` filter routes to
    ``Markup.replace()``, which HTML-escapes its *own* replacement
    argument too (the safety invariant that makes ``Markup`` safe to pass
    around elsewhere) -- so the ``<br>`` this is meant to insert comes out
    as the literal, visible text ``&lt;br&gt;`` instead of a real tag. See
    ``_cap_paragraphs_filter`` below for the same bug with a longer
    replacement chain, and ``docs/reference/CHANGELOG.md``'s entry for
    the alert-detail page rendering raw ``<p>``/``<br>`` tags as text.
    Escaping and substituting on a plain ``str`` first, then wrapping the
    finished HTML in ``Markup`` exactly once at the end, avoids it.
    """
    if not text:
        return Markup("")
    return Markup(str(escape(text)).replace("\n", "<br>\n"))


def _cap_paragraphs_filter(text: str | None) -> Markup:
    """Escape *text*, then turn its plain-text paragraph/bullet breaks
    into safe HTML, as a single Markup.

    For externally-ingested CAP alert description/instruction text,
    which is plain text with ``\\n\\n`` paragraph breaks (not HTML) --
    see ``_nl2br_filter``'s docstring for why this must build the whole
    result as one plain-``str`` replacement chain and wrap it in
    ``Markup`` only at the very end, rather than as chained template
    filters.
    """
    if not text:
        return Markup("")
    result = str(escape(text))
    result = result.replace("\n\n", '</p><p class="mt-2 mb-0">')
    result = result.replace("\n- ", "<br>- ")
    result = result.replace("\n", " ")
    return Markup(result)


__all__ = ["register"]
