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

"""Tests confirming the two alert-dedup windows in
app_core.audio.auto_forward.is_duplicate_broadcast() are actually driven
by their parameters (and therefore by EASSettings.cross_source_dedup_
minutes / header_key_dedup_minutes via load_eas_config()), not just the
CROSS_SOURCE_DEDUP_WINDOW_MINUTES / HEADER_KEY_DEDUP_WINDOW_MINUTES
module constants -- those constants are now fallback defaults only.

Both windows were previously hardcoded (15 min / 1440 min); the 1440
figure is directly user-visible in forwarding_reason text an operator
reads on the Received Audio Alerts page.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app_core.audio.auto_forward import (
    CROSS_SOURCE_DEDUP_WINDOW_MINUTES,
    HEADER_KEY_DEDUP_WINDOW_MINUTES,
    is_duplicate_broadcast,
)

pytestmark = pytest.mark.unit


def _capture_cutoff(db_session_mock):
    """Read back the datetime bound into the EASMessage.created_at >= cutoff
    filter expression the function built and passed to .filter()."""
    call_args = db_session_mock.query.return_value.filter.call_args
    assert call_args is not None, "db_session.query(...).filter(...) was never called"
    binary_expr = call_args.args[0]
    return binary_expr.right.value


def _empty_session():
    """A db_session whose query chains always return an empty result set,
    so is_duplicate_broadcast() falls through to False after recording
    the cutoff it used -- no real EASMessage/ManualEASActivation rows
    needed."""
    session = MagicMock()
    session.query.return_value.filter.return_value.all.return_value = []
    return session


def test_default_window_minutes_matches_module_constant():
    """Sanity check: the function's own default parameter still equals
    the fallback constant (i.e. behaviour is unchanged when a caller
    doesn't pass window_minutes explicitly)."""
    session = _empty_session()
    before = datetime.now(timezone.utc)

    is_duplicate_broadcast("SVR", ["039063"], session)

    cutoff = _capture_cutoff(session)
    delta_minutes = (before - cutoff).total_seconds() / 60.0
    assert abs(delta_minutes - CROSS_SOURCE_DEDUP_WINDOW_MINUTES) < 1.0


def test_custom_cross_source_window_changes_cutoff():
    """A caller passing a different window_minutes (e.g. from a
    configured EASSettings.cross_source_dedup_minutes) must change the
    actual cutoff used for the FIPS-set-match path."""
    session = _empty_session()
    before = datetime.now(timezone.utc)

    is_duplicate_broadcast("SVR", ["039063"], session, window_minutes=45)

    cutoff = _capture_cutoff(session)
    delta_minutes = (before - cutoff).total_seconds() / 60.0
    assert abs(delta_minutes - 45) < 1.0


def test_custom_header_window_changes_cutoff_when_header_present():
    """When a usable SAME header is supplied, the cutoff comes from
    header_window_minutes, not window_minutes -- confirms
    EASSettings.header_key_dedup_minutes (not cross_source_dedup_minutes)
    governs the header-key match path."""
    session = _empty_session()
    before = datetime.now(timezone.utc)

    raw_header = "ZCZC-WXR-SVR-039063+0030-1231200-KRAH/NWS-"
    is_duplicate_broadcast(
        "SVR", ["039063"], session,
        window_minutes=15,
        raw_same_header=raw_header,
        header_window_minutes=720,
    )

    cutoff = _capture_cutoff(session)
    delta_minutes = (before - cutoff).total_seconds() / 60.0
    assert abs(delta_minutes - 720) < 1.0


def test_default_header_window_matches_module_constant():
    session = _empty_session()
    before = datetime.now(timezone.utc)

    raw_header = "ZCZC-WXR-SVR-039063+0030-1231200-KRAH/NWS-"
    is_duplicate_broadcast("SVR", ["039063"], session, raw_same_header=raw_header)

    cutoff = _capture_cutoff(session)
    delta_minutes = (before - cutoff).total_seconds() / 60.0
    assert abs(delta_minutes - HEADER_KEY_DEDUP_WINDOW_MINUTES) < 1.0
