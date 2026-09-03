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

    Also distinct from TickstemServiceHeartbeat (below): that's a *third*
    direction -- per-service outbound heartbeats, gated on each service's
    own health, so a missed ping names the specific subsystem that failed.

    All settings are stored in a single row (id=1).
    """
    __tablename__ = "tickstem_settings"

    id = db.Column(db.Integer, primary_key=True)

    api_key = db.Column(EncryptedString, nullable=True)
    # Tickstem account API key (from app.tickstem.dev -> API Keys). Sent as
    # "Authorization: Bearer <api_key>" on every Monitors/Heartbeats API
    # call this module or TickstemServiceHeartbeat makes. Only used
    # server-side -- never exposed to the browser beyond the masked
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


class TickstemServiceHeartbeat(db.Model):
    """One outbound Tickstem heartbeat per critical EAS Station service.

    Why per-service rather than one aggregate heartbeat: Tickstem's
    heartbeat ping carries no payload -- a missed ping just says "this
    heartbeat didn't check in," nothing about *why*. A single heartbeat
    gated on "is everything healthy" can only ever say "something's wrong"
    in the resulting alert. Naming the specific failed subsystem requires a
    separate heartbeat per service, each with its own name on Tickstem's
    side (e.g. "EAS Station -- poller.service"), so a missed ping's alert
    identifies exactly which one.

    "Critical" here means app_core.config.get_eas_services() -- the 11 EAS
    subsystems plus the poller -- not the generic infrastructure services
    (postgres, nginx, redis, ...) that already have their own standard
    monitoring ecosystems and aren't EAS-specific.

    One row per service_name, keyed by the systemd unit name so it maps
    directly onto get_system_health()'s per-service status.
    """
    __tablename__ = "tickstem_service_heartbeats"

    id = db.Column(db.Integer, primary_key=True)

    service_name = db.Column(db.String(200), nullable=False, unique=True)
    # systemd unit name, e.g. "eas-station-poller.service" -- matches
    # app_core.config.get_eas_services() and the "name" key
    # get_system_health()["systemd"]["services"] entries carry.

    heartbeat_id = db.Column(db.String(100), nullable=False)
    # Tickstem-assigned heartbeat ID, for pause/resume/delete via the
    # account's bearer-token API.

    ping_url = db.Column(db.String(500), nullable=False)
    # Full ping URL (token embedded) returned when the heartbeat was
    # created. No auth needed to ping it -- the token in the URL is the
    # credential -- so this is what the worker POSTs to, not the account
    # API key.

    enabled = db.Column(db.Boolean, nullable=False, default=True)

    interval_secs = db.Column(db.Integer, nullable=False, default=300)

    status = db.Column(db.String(20), nullable=True)
    # Cached copy of Tickstem's last-known heartbeat status, refreshed
    # opportunistically from create/pause/resume responses (Tickstem has
    # no GET-single-heartbeat-by-service endpoint on this side).

    last_ping_at = db.Column(db.DateTime, nullable=True)
    last_ping_success = db.Column(db.Boolean, nullable=True)
    last_ping_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=True, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_name": self.service_name,
            "heartbeat_id": self.heartbeat_id,
            "enabled": self.enabled,
            "interval_secs": self.interval_secs,
            "status": self.status,
            "last_ping_at": self.last_ping_at.isoformat() if self.last_ping_at else None,
            "last_ping_success": self.last_ping_success,
            "last_ping_error": self.last_ping_error,
        }
