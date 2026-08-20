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

"""Outbound dead-man's-switch heartbeat configuration."""

from ._models_base import datetime, db, utc_now


class HeartbeatSettings(db.Model):
    """Outbound "I'm alive" ping configuration, stored in the database.

    Every other health check in this application is inward-facing (it
    reports status on a page someone has to look at). This one is the
    opposite: it periodically pings an external monitoring service
    (e.g. a healthchecks.io-style check) so that *silence itself* --
    total loss of power, network, or a wedged OS -- is what raises the
    alarm, on a channel outside this box.

    All settings are stored in a single row (id=1).
    """
    __tablename__ = "heartbeat_settings"

    id = db.Column(db.Integer, primary_key=True)

    enabled = db.Column(db.Boolean, nullable=False, default=False)
    # Master switch. Deliberately defaults to off -- an unconfigured
    # ping_url would otherwise fail silently on every cycle.

    ping_url = db.Column(db.String(500), nullable=False, default='')
    # External heartbeat endpoint (e.g. https://hc-ping.com/<uuid>). Pinged
    # unconditionally on every cycle -- this is NOT gated on internal
    # system health, since its entire purpose is to prove the box itself
    # is alive and networked, independent of what it thinks of its own
    # health.

    interval_seconds = db.Column(db.Integer, nullable=False, default=300)
    # Seconds between pings (minimum enforced in the worker: 60).

    last_ping_at = db.Column(db.DateTime, nullable=True)
    # UTC timestamp of the most recent ping attempt (success or failure).

    last_ping_success = db.Column(db.Boolean, nullable=True)
    # Outcome of the most recent ping attempt.

    last_ping_error = db.Column(db.Text, nullable=True)
    # Exception text from the most recent failed ping, if any.

    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "enabled": self.enabled,
            "ping_url": self.ping_url,
            "interval_seconds": self.interval_seconds,
            "last_ping_at": self.last_ping_at.isoformat() if self.last_ping_at else None,
            "last_ping_success": self.last_ping_success,
            "last_ping_error": self.last_ping_error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
