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

"""Unified Settings hub page - a single page listing all settings sections.

The card list comes from the `settings` section of the navigation registry
(``webapp/navigation/registry.py``), injected into every template as
``nav_section_map`` and already filtered to the current user's permissions.
This route therefore has nothing to compute — adding a settings page means
editing the registry, not this file or the template.
"""

from flask import Flask, render_template


def register(app: Flask, logger) -> None:
    """Register the unified settings hub route."""

    @app.route("/settings")
    def settings_hub():
        """Render the unified settings hub page."""
        return render_template("settings_hub.html")
