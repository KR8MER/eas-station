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

"""LED-sign and VFD signage models."""

from ._models_base import db, utc_now


class LEDMessage(db.Model):
    __tablename__ = "led_messages"

    id = db.Column(db.Integer, primary_key=True)
    message_type = db.Column(db.String(50), nullable=False)
    content = db.Column(db.Text, nullable=False)
    priority = db.Column(db.Integer, default=2)
    color = db.Column(db.String(20))
    font_size = db.Column(db.String(20))
    effect = db.Column(db.String(20))
    speed = db.Column(db.String(20))
    display_time = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime(timezone=True))
    sent_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, default=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"))
    repeat_interval = db.Column(db.Integer)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class LEDSignStatus(db.Model):
    __tablename__ = "led_sign_status"

    id = db.Column(db.Integer, primary_key=True)
    sign_ip = db.Column(db.String(15), nullable=False)
    brightness_level = db.Column(db.Integer, default=10)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)
    is_connected = db.Column(db.Boolean, default=False)
    serial_mode = db.Column(db.String(10), default="RS232")  # RS232 or RS485
    baud_rate = db.Column(db.Integer, default=9600)  # Serial baud rate


class LEDRSSFeed(db.Model):
    """RSS feed source for LED sign ticker display."""
    __tablename__ = "led_rss_feeds"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
    interval_minutes = db.Column(db.Integer, default=15)
    color = db.Column(db.String(20), default="AMBER")
    effect = db.Column(db.String(20), default="ROLL_LEFT")
    speed = db.Column(db.String(20), default="SPEED_3")
    max_items = db.Column(db.Integer, default=5)
    last_fetched = db.Column(db.DateTime(timezone=True), nullable=True)
    auto_send = db.Column(db.Boolean, default=False)
    priority = db.Column(db.Integer, default=3)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    items = db.relationship(
        "LEDRSSItem",
        backref="feed",
        lazy=True,
        cascade="all, delete-orphan",
    )


class LEDRSSItem(db.Model):
    """Cached item from an RSS feed ready for LED display."""
    __tablename__ = "led_rss_items"

    id = db.Column(db.Integer, primary_key=True)
    feed_id = db.Column(
        db.Integer,
        db.ForeignKey("led_rss_feeds.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = db.Column(db.String(200), nullable=False)
    summary = db.Column(db.Text)
    link = db.Column(db.String(500))
    published = db.Column(db.DateTime(timezone=True))
    last_shown = db.Column(db.DateTime(timezone=True))
    show_count = db.Column(db.Integer, default=0)
    guid = db.Column(db.String(500))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class VFDDisplay(db.Model):
    """VFD display content and state tracking."""
    __tablename__ = "vfd_displays"

    id = db.Column(db.Integer, primary_key=True)
    content_type = db.Column(db.String(50), nullable=False)  # text, image, alert, status
    content_data = db.Column(db.Text)  # Text content or image path
    binary_data = db.Column(db.LargeBinary)  # Image binary data
    priority = db.Column(db.Integer, default=2)  # 0=emergency, 1=alert, 2=normal, 3=low
    x_position = db.Column(db.Integer, default=0)
    y_position = db.Column(db.Integer, default=0)
    duration_seconds = db.Column(db.Integer)
    scheduled_time = db.Column(db.DateTime(timezone=True))
    displayed_at = db.Column(db.DateTime(timezone=True))
    is_active = db.Column(db.Boolean, default=True)
    alert_id = db.Column(db.Integer, db.ForeignKey("cap_alerts.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)


class VFDStatus(db.Model):
    """VFD display hardware status tracking."""
    __tablename__ = "vfd_status"

    id = db.Column(db.Integer, primary_key=True)
    port = db.Column(db.String(50), nullable=False)
    baudrate = db.Column(db.Integer, default=38400)
    brightness_level = db.Column(db.Integer, default=7)
    is_connected = db.Column(db.Boolean, default=False)
    error_count = db.Column(db.Integer, default=0)
    last_error = db.Column(db.Text)
    last_update = db.Column(db.DateTime(timezone=True), default=utc_now)
    current_content_type = db.Column(db.String(50))  # What's currently displayed


