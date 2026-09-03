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

"""The EAS Station™ navigation tree — single source of truth.

Everything that renders navigation reads this module:

    * ``templates/components/navbar.html``  — the top navbar
    * ``templates/settings_hub.html``       — the ``/settings`` hub cards
    * ``templates/site_navigation.html``    — the ``/navigation`` site map

Adding a page means adding one :class:`NavItem` here. Do not hand-write links
into those templates — they will drift, which is exactly what this registry
replaced.

Information architecture
------------------------

    Dashboard    the landing page
    Monitor      what is coming IN   (alerts received, audio, station hardware)
    Broadcast    what is going OUT   (message builder, history, displays)
    Diagnostics  is it working?      (all tests + all diagnostics, one place)
    Reports      what happened       (logs, analytics, security, exports)
    Settings     configuration       (direct link to the /settings hub)
    Help         documentation

Permission tuples are *any-of*. Names must exist in
``app_core.auth.roles.PermissionDefinition``.
"""

import os

from .permissions import (
    ALERTS_EXPORT,
    ALERTS_VIEW,
    EAS_VIEW,
    LOGS_VIEW,
    RECEIVERS_VIEW,
    SYSTEM_CONFIGURE,
)
from .registry_settings import SETTINGS_SECTION
from .types import (
    NAVBAR_LINK,
    NavGroup,
    NavItem,
    NavSection,
)

# Anyone who monitors the station's radio/audio chain.
_RADIO_WATCHERS = (ALERTS_VIEW, RECEIVERS_VIEW, LOGS_VIEW)

# /debug/ipaws only has anything to show when the poller was started with
# CAP_POLLER_DEBUG_RECORDS=1 (see poller/cap_poller.py) -- it's an opt-in,
# CPU/DB-intensive troubleshooting mode, off by default. Mirror that same
# flag here so the nav entry doesn't lead people to a page that's
# permanently empty for this station.
_IPAWS_POLLER_DEBUG_ENABLED = os.environ.get(
    "CAP_POLLER_DEBUG_RECORDS", ""
).strip().lower() in {"1", "true", "yes", "on", "t", "y"}


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

_DASHBOARD = NavSection(
    key="dashboard",
    label="Dashboard",
    icon="fas fa-gauge-high",
    navbar=NAVBAR_LINK,
    href="/",
    description="Live station overview.",
    requires_auth=False,
    accent="primary",
)


_MONITOR = NavSection(
    key="monitor",
    label="Monitor",
    icon="fas fa-satellite-dish",
    description="Alerts and audio arriving at the station.",
    accent="info",
    requires_auth=False,
    groups=(
        NavGroup(
            label="Alerts",
            icon="fas fa-bell",
            requires_auth=False,
            items=(
                NavItem(
                    label="Active Alerts",
                    icon="fas fa-bell",
                    href="/alerts",
                    description="Current CAP alerts with map coverage and details.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Statistics",
                    icon="fas fa-chart-bar",
                    href="/stats",
                    description="Alert counts, event types and trends over time.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Received Alerts",
                    icon="fas fa-radio",
                    href="/audio/received",
                    description="Alerts decoded off-air from monitored stations.",
                    permissions=_RADIO_WATCHERS,
                ),
            ),
        ),
        NavGroup(
            label="Audio & Radio",
            icon="fas fa-headphones",
            items=(
                NavItem(
                    label="Live Audio",
                    icon="fas fa-headphones",
                    href="/audio-monitor",
                    description="Listen to the live decoder feed in the browser.",
                    permissions=_RADIO_WATCHERS,
                ),
                NavItem(
                    label="Audio Health",
                    icon="fas fa-wave-square",
                    href="/audio/health/dashboard",
                    description="Signal level, silence detection and stream uptime.",
                    permissions=_RADIO_WATCHERS,
                ),
                NavItem(
                    label="EAS Decoder Monitor",
                    icon="fas fa-satellite-dish",
                    href="/admin/eas_decoder_monitor",
                    description="Live SAME/FSK decoder state for each receiver.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="ENDEC Device Feeds",
                    icon="fas fa-plug",
                    href="/admin/endec_feeds",
                    description="Serial and network feeds from external ENDEC units.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
        NavGroup(
            label="Station Hardware",
            icon="fas fa-microchip",
            items=(
                # Hardware Settings and Zigbee used to also be listed here,
                # duplicating Settings -> Hardware's entries for the exact
                # same pages under different labels/icons. GPS & Time is a
                # live-status dashboard (fix quality, sky plot) so it stays
                # here in Monitor; the other two are configuration screens,
                # so Settings is their one home now.
                NavItem(
                    label="GPS & Time",
                    icon="fas fa-satellite",
                    endpoint="hardware.gps_dashboard_page",
                    description="GNSS fix quality, satellites and time discipline.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
    ),
)


_BROADCAST = NavSection(
    key="broadcast",
    label="Broadcast",
    icon="fas fa-tower-broadcast",
    description="Compose, send and display outgoing EAS messages.",
    accent="success",
    groups=(
        NavGroup(
            label="Create & Send",
            icon="fas fa-tower-broadcast",
            items=(
                NavItem(
                    label="Broadcast Builder",
                    icon="fas fa-broadcast-tower",
                    endpoint="eas.workflow_home",
                    description="Build, preview and transmit a SAME/EAS message.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="Broadcast History",
                    icon="fas fa-history",
                    endpoint="audio_history",
                    description="Every message this station has transmitted.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="Pending Alerts",
                    icon="fas fa-hourglass-half",
                    endpoint="pending_alerts.pending_alerts_list",
                    description="Alerts held during the gating window, awaiting broadcast or cancellation.",
                    permissions=(EAS_VIEW,),
                ),
            ),
        ),
        NavGroup(
            label="Display Outputs",
            icon="fas fa-tv",
            items=(
                NavItem(
                    label="Display Controls",
                    icon="fas fa-tv",
                    endpoint="displays_control",
                    description="Drive the connected LED, VFD and OLED displays.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="Display Preview",
                    icon="fas fa-eye",
                    endpoint="displays_preview_page",
                    description="See what each display is showing right now.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="LED Sign",
                    icon="fas fa-sign-hanging",
                    endpoint="led_control",
                    description="Message, brightness and scroll speed for the LED sign.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="VFD Display",
                    icon="fas fa-desktop",
                    endpoint="vfd_control",
                    description="Text and backlight control for the VFD panel.",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="OLED Screens",
                    icon="fas fa-display",
                    endpoint="screens_page",
                    description="Design and assign the small OLED status screens.",
                    permissions=(EAS_VIEW,),
                ),
            ),
        ),
    ),
)


# Every test and every diagnostic in the product lives here. They used to be
# spread across three different dropdowns (Broadcast, Tools, Monitor), which
# made "is the station healthy?" a scavenger hunt.
_DIAGNOSTICS = NavSection(
    key="diagnostics",
    label="Diagnostics",
    icon="fas fa-stethoscope",
    description="Every test and health check, in one place.",
    accent="warning",
    groups=(
        NavGroup(
            label="Tests & Verification",
            icon="fas fa-flask",
            items=(
                NavItem(
                    label="Weekly Test Schedule",
                    icon="fas fa-calendar-check",
                    endpoint="rwt_schedule_page",
                    description="Schedule and review the Required Weekly Test (RWT).",
                    permissions=(EAS_VIEW,),
                ),
                NavItem(
                    label="Audio Tests",
                    icon="fas fa-flask",
                    endpoint="audio_tests_dashboard",
                    description="End-to-end audio pipeline test suite and results.",
                    permissions=(RECEIVERS_VIEW,),
                ),
                NavItem(
                    label="Alert Verification",
                    icon="fas fa-shield-halved",
                    endpoint="alert_verification",
                    description="Verify decoded alerts against the originating CAP feed.",
                    permissions=(ALERTS_VIEW,),
                ),
            ),
        ),
        NavGroup(
            label="System Health",
            icon="fas fa-heartbeat",
            items=(
                NavItem(
                    label="System Diagnostics",
                    icon="fas fa-stethoscope",
                    href="/diagnostics",
                    description="Service, database and dependency checks.",
                ),
                NavItem(
                    label="Health Dashboard",
                    icon="fas fa-heartbeat",
                    href="/system_health",
                    description="Live CPU, memory, disk and service health tiles.",
                ),
                NavItem(
                    label="SDR Diagnostics",
                    icon="fas fa-signal",
                    href="/admin/radio/diagnostics",
                    description="Live waterfall, spectrum scope, historical trend charts and a full pipeline health checklist per receiver.",
                    permissions=(RECEIVERS_VIEW,),
                ),
            ) + (
                (
                    NavItem(
                        label="IPAWS Poller Debug",
                        icon="fas fa-bug",
                        href="/debug/ipaws",
                        description="Raw IPAWS poll requests, responses and timings.",
                    ),
                )
                if _IPAWS_POLLER_DEBUG_ENABLED
                else ()
            ),
        ),
    ),
)


_REPORTS = NavSection(
    key="reports",
    label="Reports",
    icon="fas fa-file-lines",
    description="Logs, analytics, security review and data exports.",
    accent="secondary",
    groups=(
        NavGroup(
            label="Logs",
            icon="fas fa-file-alt",
            permissions=(LOGS_VIEW,),
            items=(
                NavItem(
                    label="All Logs",
                    icon="fas fa-file-alt",
                    href="/logs",
                    query="?type=all",
                    description="Unified log hub across every service and category.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="Audit Log",
                    icon="fas fa-clipboard-list",
                    href="/logs",
                    query="?type=audit",
                    description="Who did what, and when.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="Configuration Changes",
                    icon="fas fa-sliders",
                    href="/logs",
                    query="?type=audit&action=config.updated",
                    description="Audit trail filtered to configuration edits.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="Compliance Log",
                    icon="fas fa-clipboard-check",
                    href="/logs",
                    query="?type=compliance",
                    description="FCC compliance events for the station record.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="FCC Reports",
                    icon="fas fa-file-contract",
                    href="/logs",
                    query="?type=report_received",
                    description="Received-alert reports in FCC filing format.",
                    permissions=(LOGS_VIEW,),
                ),
            ),
        ),
        NavGroup(
            label="Analytics",
            icon="fas fa-chart-line",
            items=(
                NavItem(
                    label="Analytics Dashboard",
                    icon="fas fa-chart-line",
                    href="/analytics",
                    description="Alert volume, coverage and response-time analysis.",
                ),
                NavItem(
                    label="Repository Statistics",
                    icon="fas fa-code-branch",
                    href="/repo-stats",
                    description="Live code, route and component metrics for this build.",
                ),
                NavItem(
                    label="API Reference",
                    icon="fas fa-plug",
                    href="/api-reference",
                    description="Live reference of every /api/* route, generated from this build.",
                ),
            ),
        ),
        NavGroup(
            label="Security",
            icon="fas fa-shield-halved",
            permissions=(LOGS_VIEW,),
            items=(
                NavItem(
                    label="Security Center",
                    icon="fas fa-shield-halved",
                    href="/security/center",
                    description="Traffic, failed logins, IP bans and fail2ban state.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="Active Sessions",
                    icon="fas fa-user-clock",
                    href="/admin/sessions",
                    description="Signed-in users and their live sessions.",
                    permissions=(LOGS_VIEW,),
                ),
                NavItem(
                    label="Firewall",
                    icon="fas fa-shield-halved",
                    endpoint="firewall.firewall_page",
                    description="Host firewall baseline, LAN NTP and Icecast port rules, in one place.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
        NavGroup(
            label="Data Export",
            icon="fas fa-file-export",
            permissions=(ALERTS_EXPORT,),
            items=(
                NavItem(
                    label="JSON Feed",
                    icon="fas fa-code",
                    href="/export/alerts",
                    description="Machine-readable JSON feed of current alerts.",
                    permissions=(ALERTS_EXPORT,),
                ),
                NavItem(
                    label="CAP 1.2 XML",
                    icon="fas fa-file-code",
                    href="/export/alerts/cap.xml",
                    description="Standards-compliant CAP 1.2 XML export.",
                    permissions=(ALERTS_EXPORT,),
                ),
                NavItem(
                    label="CSV Download",
                    icon="fas fa-file-csv",
                    href="/export/alerts/csv",
                    description="Spreadsheet-ready CSV of alert records.",
                    permissions=(ALERTS_EXPORT,),
                ),
            ),
        ),
    ),
)


_HELP = NavSection(
    key="help",
    label="Help",
    icon="fas fa-circle-question",
    description="Documentation, project information and support.",
    accent="secondary",
    requires_auth=False,
    groups=(
        NavGroup(
            label="Getting Around",
            icon="fas fa-sitemap",
            requires_auth=False,
            items=(
                NavItem(
                    label="Site Navigation",
                    icon="fas fa-sitemap",
                    endpoint="site_navigation",
                    description="Every page in the system, grouped by category.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Documentation",
                    icon="fas fa-book",
                    endpoint="docs_index",
                    description="Full operator and developer documentation.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Help & Support",
                    icon="fas fa-life-ring",
                    endpoint="help_page",
                    description="How-to guides and troubleshooting.",
                    requires_auth=False,
                ),
            ),
        ),
        NavGroup(
            label="About This System",
            icon="fas fa-circle-info",
            requires_auth=False,
            items=(
                NavItem(
                    label="About",
                    icon="fas fa-circle-info",
                    endpoint="about_page",
                    description="What EAS Station™ is and how it works.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Attribution & Credits",
                    icon="fas fa-certificate",
                    endpoint="attribution_page",
                    description="Open-source dependencies and their licences.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Support the Project",
                    icon="fas fa-heart",
                    endpoint="support_page",
                    description="Help fund continued development.",
                    requires_auth=False,
                ),
                NavItem(
                    label="Version Info",
                    icon="fas fa-code-branch",
                    href="/help/version",
                    description="Running version, build commit and changelog.",
                    requires_auth=False,
                ),
                NavItem(
                    label="UI Style Guide",
                    icon="fas fa-palette",
                    endpoint="style_guide_page",
                    description="Shared components, themes and design patterns.",
                ),
            ),
        ),
    ),
)


#: The complete navigation tree, in navbar order.
NAVIGATION = (
    _DASHBOARD,
    _MONITOR,
    _BROADCAST,
    _DIAGNOSTICS,
    _REPORTS,
    SETTINGS_SECTION,
    _HELP,
)


#: The signed-in user's own menu (right-hand side of the navbar).
#:
#: Display Units lives here rather than in a two-item Settings dropdown: it is
#: per-browser personalization, not station configuration.
USER_MENU = NavGroup(
    label="Account",
    icon="fas fa-user-circle",
    items=(
        NavItem(
            label="Security Settings",
            icon="fas fa-shield-halved",
            href="/security/settings",
            description="Your password, MFA and active sessions.",
        ),
        NavItem(
            label="Display Units",
            icon="fas fa-ruler",
            modal_target="globalUnitsModal",
            description="Choose units for lat/lon, altitude, speed and distance.",
        ),
    ),
)


__all__ = ["NAVIGATION", "USER_MENU"]
