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

"""Timestamps rendered in the UI must be in the station's local timezone.

Every timestamp is persisted in UTC. Templates that called ``.strftime()``
directly on a column rendered that raw UTC value with no conversion and no
timezone label, so the Received Alerts table (and a dozen other pages) read
several hours ahead of the operator's wall clock.
"""

import re
from datetime import datetime
from pathlib import Path

import pytest
import pytz

from app_utils.time import (
    format_local,
    get_location_timezone_name,
    set_location_timezone,
    to_location_time,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# The only template call allowed to reach strftime directly: it formats a value
# that is already local, so there is nothing left to convert.
ALLOWED_STRFTIME_RECEIVERS = {"local_current_time()"}


@pytest.fixture
def eastern_timezone():
    """Pin the location timezone to US Eastern for the duration of a test."""
    original = get_location_timezone_name()
    set_location_timezone("America/New_York")
    yield
    set_location_timezone(original)


def test_aware_utc_is_converted_to_local(eastern_timezone):
    """An aware UTC timestamp renders at the local wall-clock hour."""
    received_at = pytz.UTC.localize(datetime(2026, 8, 11, 10, 6, 43))

    assert format_local(received_at, "%Y-%m-%d %H:%M:%S %Z") == "2026-08-11 06:06:43 EDT"


def test_naive_timestamps_are_treated_as_utc(eastern_timezone):
    """Naive columns (``default=datetime.utcnow``) convert like aware ones."""
    naive = datetime(2026, 8, 11, 10, 6, 43)

    assert format_local(naive, "%Y-%m-%d %H:%M:%S %Z") == "2026-08-11 06:06:43 EDT"


def test_standard_time_uses_the_standard_offset(eastern_timezone):
    """The offset follows DST rather than being hard-coded."""
    winter = pytz.UTC.localize(datetime(2026, 1, 15, 10, 6, 43))

    assert format_local(winter, "%Y-%m-%d %H:%M:%S %Z") == "2026-01-15 05:06:43 EST"


def test_missing_timestamp_returns_the_supplied_default():
    """A null column renders the caller's placeholder, not a traceback."""
    assert format_local(None) == "N/A"
    assert format_local(None, "%Y-%m-%d", "—") == "—"
    assert to_location_time(None) is None


def test_localtime_filter_is_registered():
    """Templates can only use the filter if the app actually registers it."""
    from flask import Flask

    from webapp import template_helpers

    app = Flask(__name__)
    template_helpers.register(app)

    assert "localtime" in app.jinja_env.filters
    assert "to_local" in app.jinja_env.filters


def test_no_template_formats_a_stored_timestamp_as_raw_utc():
    """Guard against ``.strftime()`` creeping back into a template.

    Rendering a stored (UTC) timestamp with ``.strftime()`` skips the timezone
    conversion silently — the page simply shows the wrong hour. Use the
    ``localtime`` filter instead.
    """
    offenders = []

    for template in sorted(TEMPLATES_DIR.rglob("*.html")):
        for line_number, line in enumerate(template.read_text().splitlines(), 1):
            for match in re.finditer(r"([\w.()\[\]]+)\.strftime\(", line):
                if match.group(1) in ALLOWED_STRFTIME_RECEIVERS:
                    continue
                offenders.append(
                    f"{template.relative_to(PROJECT_ROOT)}:{line_number}: "
                    f"{match.group(1)}.strftime(...)"
                )

    assert not offenders, (
        "Templates must render stored timestamps with the `localtime` filter, "
        "e.g. {{ alert.received_at | localtime('%Y-%m-%d %H:%M:%S %Z', 'N/A') }}. "
        "Raw .strftime() displays UTC:\n  " + "\n  ".join(offenders)
    )
