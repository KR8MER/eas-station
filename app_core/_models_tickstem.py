"""Tickstem uptime-monitor integration configuration."""

from __future__ import annotations

from ._models_base import datetime, db, utc_now
from .crypto import EncryptedString


class TickstemSettings(db.Model):
    """Credentials and state for a Tickstem uptime monitor of this box.

    Distinct from HeartbeatSettings: heartbeat is this box pinging *out* on
    a schedule (works with any healthchecks.io-style receiver, no API key).
    This is Tickstem polling *in* against a public URL (usually /health),
    managed here through Tickstem's own bearer-token Monitors API so the
    monitor can be created/paused/resumed without leaving this admin UI.

    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tickstem_settings"

    id = db.Column(db.Integer, primary_key=True)

    api_key = db.Column(EncryptedString, nullable=True)
    # Tickstem account API key (from app.tickstem.dev -> API Keys). Sent as
    # "Authorization: Bearer <api_key>" on every Monitors API call. Only
    # used server-side -- never exposed to the browser beyond the masked
    # password-type form field.

    monitor_id = db.Column(db.String(100), nullable=True)
    # Tickstem-assigned monitor ID once created. None means no monitor
    # exists yet on Tickstem's side.

    monitor_name = db.Column(db.String(200), nullable=False, default='')
    monitor_url = db.Column(db.String(500), nullable=False, default='')
    # Must be a publicly reachable https URL -- Tickstem polls it from the
    # outside, so this can't default to localhost/an internal hostname.

    interval_secs = db.Column(db.Integer, nullable=False, default=60)
    timeout_secs = db.Column(db.Integer, nullable=False, default=10)

    monitor_status = db.Column(db.String(20), nullable=True)
    # Cached copy of Tickstem's last-known status ("active"/"failing"/
    # "paused") -- Tickstem's API has no GET-single-monitor endpoint, so
    # this is refreshed opportunistically from create/pause/resume
    # responses rather than polled independently.

    last_synced_at = db.Column(db.DateTime, nullable=True)
    last_sync_error = db.Column(db.Text, nullable=True)

    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "has_api_key": bool(self.api_key),
            "monitor_id": self.monitor_id,
            "monitor_name": self.monitor_name,
            "monitor_url": self.monitor_url,
            "interval_secs": self.interval_secs,
            "timeout_secs": self.timeout_secs,
            "monitor_status": self.monitor_status,
            "last_synced_at": self.last_synced_at.isoformat() if self.last_synced_at else None,
            "last_sync_error": self.last_sync_error,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
