"""healthchecks.io per-service heartbeat integration configuration."""

from __future__ import annotations

from ._models_base import datetime, db, utc_now
from .crypto import EncryptedString


class HealthchecksSettings(db.Model):
    """Account API key for healthchecks.io's Management API.

    healthchecks.io has no "poll an external URL" product the way Tickstem's
    Monitors API does -- every check is a dead-man's-switch that this box
    pings *out* to on a schedule (see HealthchecksServiceHeartbeat below),
    the same shape as TickstemServiceHeartbeat. This settings row exists
    only to hold the account API key those per-service checks are managed
    through (from healthchecks.io -> Settings -> API Access).

    All settings are stored in a single row (id=1).
    """
    __tablename__ = "healthchecks_settings"

    id = db.Column(db.Integer, primary_key=True)

    api_key = db.Column(EncryptedString, nullable=True)
    # healthchecks.io account API key. Sent as "X-Api-Key: <api_key>" on
    # every Checks Management API call this module makes. Only used
    # server-side -- never exposed to the browser beyond the masked
    # password-type form field.

    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "has_api_key": bool(self.api_key),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class HealthchecksServiceHeartbeat(db.Model):
    """One outbound healthchecks.io check per critical EAS Station service.

    Mirrors TickstemServiceHeartbeat exactly, one row per systemd unit name
    from app_core.config.get_eas_services(), each pinged by the shared
    heartbeat_worker.HeartbeatWorker loop only while that specific service
    is active. A missed ping then identifies exactly which subsystem
    failed, rather than only "something is wrong" the way one combined
    heartbeat's alert would.
    """
    __tablename__ = "healthchecks_service_heartbeats"

    id = db.Column(db.Integer, primary_key=True)

    service_name = db.Column(db.String(200), nullable=False, unique=True)
    # systemd unit name, e.g. "eas-station-poller.service" -- matches
    # app_core.config.get_eas_services() and the "name" key
    # get_system_health()["systemd"]["services"] entries carry.

    check_uuid = db.Column(db.String(100), nullable=False)
    # healthchecks.io-assigned check UUID, for pause/resume/delete via the
    # account's X-Api-Key-authenticated Management API.

    ping_url = db.Column(db.String(500), nullable=False)
    # Full ping URL returned when the check was created. No auth needed to
    # ping it, so this is what the worker POSTs to, not the account API key.

    enabled = db.Column(db.Boolean, nullable=False, default=True)

    interval_secs = db.Column(db.Integer, nullable=False, default=300)

    status = db.Column(db.String(20), nullable=True)
    # Cached copy of healthchecks.io's last-known status ("new"/"up"/
    # "grace"/"down"/"paused"), refreshed opportunistically from create/
    # pause/resume responses -- polling it independently would need its own
    # GET call per check, for information the worker's own ping outcome
    # already mostly tells us.

    last_ping_at = db.Column(db.DateTime, nullable=True)
    last_ping_success = db.Column(db.Boolean, nullable=True)
    last_ping_error = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, nullable=True, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "service_name": self.service_name,
            "check_uuid": self.check_uuid,
            "enabled": self.enabled,
            "interval_secs": self.interval_secs,
            "status": self.status,
            "last_ping_at": self.last_ping_at.isoformat() if self.last_ping_at else None,
            "last_ping_success": self.last_ping_success,
            "last_ping_error": self.last_ping_error,
        }
