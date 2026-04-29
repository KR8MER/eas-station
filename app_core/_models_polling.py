"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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

"""CAP poller history, debug record, and configuration models."""

from ._models_base import JSONB, datetime, db, utc_now


class PollHistory(db.Model):
    __tablename__ = "poll_history"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime(timezone=True), default=utc_now)
    status = db.Column(db.String(20), nullable=False)
    alerts_fetched = db.Column(db.Integer, default=0)
    alerts_new = db.Column(db.Integer, default=0)
    alerts_updated = db.Column(db.Integer, default=0)
    execution_time_ms = db.Column(db.Integer)
    error_message = db.Column(db.Text)
    data_source = db.Column(db.String(64))
    # JSON field for additional details (endpoints polled, zone config, etc.)
    details = db.Column(db.JSON)


class PollDebugRecord(db.Model):
    __tablename__ = "poll_debug_records"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, nullable=False)
    poll_run_id = db.Column(db.String(64), nullable=False, index=True)
    poll_started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    poll_status = db.Column(db.String(20), nullable=False, default="UNKNOWN")
    data_source = db.Column(db.String(64))
    alert_identifier = db.Column(db.String(255))
    alert_event = db.Column(db.String(255))
    alert_sent = db.Column(db.DateTime(timezone=True))
    source = db.Column(db.String(64))
    is_relevant = db.Column(db.Boolean, default=False, nullable=False)
    relevance_reason = db.Column(db.String(255))
    relevance_matches = db.Column(db.JSON, default=list)
    ugc_codes = db.Column(db.JSON, default=list)
    area_desc = db.Column(db.Text)
    was_saved = db.Column(db.Boolean, default=False, nullable=False)
    was_new = db.Column(db.Boolean, default=False, nullable=False)
    alert_db_id = db.Column(db.Integer)
    parse_success = db.Column(db.Boolean, default=False, nullable=False)
    parse_error = db.Column(db.Text)
    polygon_count = db.Column(db.Integer)
    geometry_type = db.Column(db.String(64))
    geometry_geojson = db.Column(db.JSON)
    geometry_preview = db.Column(db.JSON)
    raw_properties = db.Column(db.JSON)
    raw_xml_present = db.Column(db.Boolean, default=False, nullable=False)
    notes = db.Column(db.Text)


class PollerSettings(db.Model):
    """Alert poller configuration stored in database.

    Replaces environment variables for poller configuration.
    All settings are stored in a single row (id=1).
    """
    __tablename__ = "poller_settings"

    id = db.Column(db.Integer, primary_key=True)

    # Poller Configuration
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    # When enabled, the poller service will fetch alerts from CAP feeds

    poll_interval_sec = db.Column(db.Integer, nullable=False, default=120)
    # Seconds between polls (minimum: 30, recommended: 120 for IPAWS, 300 for NOAA)

    cap_timeout = db.Column(db.Integer, nullable=False, default=30)
    # HTTP request timeout in seconds for CAP feed requests

    noaa_user_agent = db.Column(
        db.String(500),
        nullable=False,
        default='EAS Station (+https://github.com/KR8MER/eas-station; support@easstation.com)',
    )
    # User-Agent header sent to NOAA API (required for compliance)

    cap_endpoints = db.Column(JSONB, nullable=False, default=list)
    # List of custom CAP feed URLs to poll (in addition to built-in NOAA feeds)

    ipaws_feed_urls = db.Column(JSONB, nullable=False, default=list)
    # List of IPAWS CAP feed URLs to poll

    ipaws_default_lookback_hours = db.Column(db.Integer, nullable=False, default=12)
    # Hours to look back when constructing IPAWS feed URLs with {timestamp} placeholder

    # Logging Settings
    log_fetched_alerts = db.Column(db.Boolean, nullable=False, default=False)
    # When enabled, poller logs detailed information about each alert fetched
    # including full ID, event type, sent/effective/expires times, urgency/severity/certainty,
    # area description, and headline. Useful for debugging missing alerts.

    # Metadata
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "poll_interval_sec": self.poll_interval_sec,
            "cap_timeout": self.cap_timeout,
            "noaa_user_agent": self.noaa_user_agent,
            "cap_endpoints": self.cap_endpoints or [],
            "ipaws_feed_urls": self.ipaws_feed_urls or [],
            "ipaws_default_lookback_hours": self.ipaws_default_lookback_hours,
            "log_fetched_alerts": self.log_fetched_alerts,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


