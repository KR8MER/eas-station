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

"""Unified Settings hub page - a single page listing all settings sections."""

from flask import Flask, render_template

from app_core.auth.roles import has_permission


def register(app: Flask, logger) -> None:
    """Register the unified settings hub route."""

    @app.route("/settings")
    def settings_hub():
        """Render the unified settings hub page."""

        can_view_system_config = has_permission("system.view_config")
        can_manage_config = has_permission("system.configure")
        can_view_gpio = has_permission("gpio.view")
        can_manage_users = has_permission("system.manage_users")
        can_view_users = has_permission("system.view_users") or can_manage_users
        can_manage_receivers = has_permission("receivers.view")
        can_view_logs = has_permission("logs.view")

        return render_template(
            "settings_hub.html",
            can_view_system_config=can_view_system_config,
            can_manage_config=can_manage_config,
            can_view_gpio=can_view_gpio,
            can_manage_users=can_manage_users,
            can_view_users=can_view_users,
            can_manage_receivers=can_manage_receivers,
            can_view_logs=can_view_logs,
        )
