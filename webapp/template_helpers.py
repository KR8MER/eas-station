"""Template filter and global registrations for the Flask app."""

from __future__ import annotations

from flask import Flask

from app_utils import (
    format_local_date,
    format_local_datetime,
    format_local_time,
    is_alert_expired,
    local_now,
    utc_now,
)


def register(app: Flask) -> None:
    """Attach the project's shared Jinja filters and globals to *app*."""

    app.add_template_filter(_nl2br_filter, name="nl2br")
    app.add_template_filter(format_local_datetime, name="format_local_datetime")
    app.add_template_filter(format_local_date, name="format_local_date")
    app.add_template_filter(format_local_time, name="format_local_time")
    app.add_template_filter(is_alert_expired, name="is_expired")

    app.add_template_global(utc_now, name="current_time")
    app.add_template_global(local_now, name="local_current_time")


def _nl2br_filter(text: str | None) -> str:
    if not text:
        return ""
    return text.replace("\n", "<br>\n")


__all__ = ["register"]
