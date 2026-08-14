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

"""Tests for the min_log_confidence_percent gate in
app_core.audio.eas_monitor._store_received_alert().

Reviewing the Received Audio Alerts page turned up a real pattern: a
configured audio source is a nationwide EAS relay network, so it
legitimately decodes real SAME headers for alerts all over the country
that are correctly filtered as "no FIPS match" -- those are true decodes,
not noise, and must always be stored regardless of confidence. The gate
only targets the smaller, genuinely noise-shaped bucket: detections with
NO decoded event code at all, below a configurable confidence floor.
"""

from unittest.mock import MagicMock, patch

import pytest

from app_core.audio.eas_monitor import _store_received_alert

pytestmark = pytest.mark.unit


def _mock_settings(min_log_confidence_percent):
    settings = MagicMock()
    settings.min_log_confidence_percent = min_log_confidence_percent
    return settings


def _run_store(alert, min_log_confidence_percent=0.0):
    """Invoke _store_received_alert() with app-context, EASSettings, and
    DB writes mocked out, returning whether a record was actually added.

    ReceivedEASAlert.received_at >= cutoff (and friends) are built as real
    SQLAlchemy filter *expressions* even on a mocked model class -- a bare
    MagicMock's ordering dunders (__ge__ etc.) raise TypeError rather than
    returning a comparable object, so they're wired to return a sentinel
    "filter expression" here instead of the real thing.
    """
    mock_db = MagicMock()
    mock_db.session.query.return_value.filter.return_value.first.return_value = None

    mock_received_alert_cls = MagicMock()
    mock_received_alert_cls.received_at.__ge__ = MagicMock(return_value="filter_expr")
    mock_received_alert_cls.raw_same_header.__eq__ = MagicMock(return_value="filter_expr")
    mock_received_alert_cls.event_code.__eq__ = MagicMock(return_value="filter_expr")
    mock_received_alert_cls.originator_code.__eq__ = MagicMock(return_value="filter_expr")
    mock_received_alert_cls.callsign.__eq__ = MagicMock(return_value="filter_expr")

    mock_eas_settings_cls = MagicMock()
    mock_eas_settings_cls.query.get.return_value = _mock_settings(min_log_confidence_percent)

    with patch("flask.has_app_context", return_value=True), \
         patch("app_core.models.ReceivedEASAlert", mock_received_alert_cls), \
         patch("app_core.models.EASSettings", mock_eas_settings_cls), \
         patch("app_core.extensions.db", mock_db):
        _store_received_alert(
            alert=alert,
            forwarding_decision="ignored",
            forwarding_reason="No FIPS codes in alert",
            matched_fips=[],
        )

    return mock_db.session.add.called


def test_no_header_low_confidence_suppressed_when_threshold_set():
    alert = {"event_code": "", "confidence": 0.55, "source_name": "sdr-wbks"}
    added = _run_store(alert, min_log_confidence_percent=70.0)
    assert added is False


def test_no_header_high_confidence_not_suppressed():
    """Confidence above the threshold still gets logged even with no
    decoded event code -- the gate only trims the low end."""
    alert = {"event_code": "", "confidence": 0.85, "source_name": "sdr-wbks"}
    added = _run_store(alert, min_log_confidence_percent=70.0)
    assert added is True


def test_no_header_low_confidence_kept_by_default():
    """Default 0 (disabled) preserves prior behaviour: log everything."""
    alert = {"event_code": "", "confidence": 0.55, "source_name": "sdr-wbks"}
    added = _run_store(alert, min_log_confidence_percent=0.0)
    assert added is True


def test_decoded_event_code_never_suppressed_regardless_of_confidence():
    """A real decoded alert (e.g. from a nationwide relay network, out of
    this station's FIPS coverage) is a true decode, not noise -- always
    stored no matter how the confidence floor is configured."""
    alert = {
        "event_code": "CEM", "originator": "CIV", "confidence": 0.40,
        "location_codes": ["041029"], "source_name": "ERN-LUC",
    }
    added = _run_store(alert, min_log_confidence_percent=99.0)
    assert added is True


def test_unknown_event_code_treated_as_no_header():
    """event_code defaulting to the literal 'UNKNOWN' sentinel (missing
    key) is the same "no header" case as an empty string."""
    alert = {"confidence": 0.10, "source_name": "sdr-wbks"}
    added = _run_store(alert, min_log_confidence_percent=50.0)
    assert added is False
