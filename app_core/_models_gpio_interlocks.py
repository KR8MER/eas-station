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

"""Relay interlock (mutual-exclusion) group configuration."""

from ._models_base import db, utc_now


class RelayInterlockGroup(db.Model):
    """A named set of GPIO relay pins that must never all be active at once.

    Motivating case: two PTT (push-to-talk) relay lines wired to separate
    transmitters that must never key simultaneously. Membership lives in
    :class:`RelayInterlockMember`; enforcement happens in
    ``app_utils.gpio.controller.GPIOController.activate()``.
    """
    __tablename__ = "relay_interlock_groups"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, unique=True)
    enabled = db.Column(db.Boolean, nullable=False, default=True)

    # When True, activating a pin in this group force-deactivates any other
    # currently-active member instead of refusing the new activation. Off by
    # default -- surprise-deactivating a different relay as a side effect of
    # an unrelated activation request is not a safe default for a life-safety
    # appliance; refuse-and-log is.
    force_deactivate_conflict = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, nullable=True, default=utc_now)
    updated_at = db.Column(db.DateTime, nullable=True, default=utc_now, onupdate=utc_now)

    members = db.relationship(
        "RelayInterlockMember",
        backref="group",
        cascade="all, delete-orphan",
        order_by="RelayInterlockMember.pin",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "force_deactivate_conflict": self.force_deactivate_conflict,
            "pins": [m.pin for m in self.members],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class RelayInterlockMember(db.Model):
    """One GPIO pin's membership in a :class:`RelayInterlockGroup`."""
    __tablename__ = "relay_interlock_members"

    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(
        db.Integer,
        db.ForeignKey("relay_interlock_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pin = db.Column(db.Integer, nullable=False, index=True)
    created_at = db.Column(db.DateTime, nullable=True, default=utc_now)

    __table_args__ = (
        db.UniqueConstraint("group_id", "pin", name="uq_relay_interlock_member_group_pin"),
    )
