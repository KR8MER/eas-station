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


"""The Settings section of the navigation tree.

Split out of ``registry.py`` because this subtree is a distinct concern: it is
the content of the ``/settings`` hub page, laid out as cards, rather than a
navbar dropdown. In the navbar Settings renders as a single link (its
``navbar`` mode is ``NAVBAR_LINK``); the groups below are what the hub shows.
"""

from .permissions import (
    GPIO_VIEW,
    LOGS_VIEW,
    RECEIVERS_VIEW,
    SYSTEM_CONFIGURE,
    SYSTEM_MANAGE_USERS,
    SYSTEM_VIEW_CONFIG,
    SYSTEM_VIEW_USERS,
)
from .types import NAVBAR_LINK, NavGroup, NavItem, NavSection

# Anyone who can see the user directory.
_USER_READERS = (SYSTEM_VIEW_USERS, SYSTEM_MANAGE_USERS)


SETTINGS_SECTION = NavSection(
    key="settings",
    label="Settings",
    icon="fas fa-cog",
    navbar=NAVBAR_LINK,
    href="/settings",
    description="Configure every part of the station.",
    accent="dark",
    permissions=(
        SYSTEM_VIEW_CONFIG,
        SYSTEM_CONFIGURE,
        GPIO_VIEW,
        RECEIVERS_VIEW,
        SYSTEM_VIEW_USERS,
        SYSTEM_MANAGE_USERS,
        LOGS_VIEW,
    ),
    groups=(
        NavGroup(
            label="Configuration",
            icon="fas fa-sliders",
            items=(
                NavItem(
                    label="Admin Dashboard",
                    icon="fas fa-sliders",
                    href="/admin",
                    description="Core system configuration and admin overview.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
                NavItem(
                    label="Environment Variables",
                    icon="fas fa-code",
                    href="/admin/environment",
                    description="Runtime environment and application variables.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
                NavItem(
                    label="Application Settings",
                    icon="fas fa-sliders-h",
                    href="/admin/application/",
                    description="Log levels, file storage and retention policy.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Alert Sources",
                    icon="fas fa-rss",
                    href="/admin/alert-feeds",
                    description="Manage NOAA CAP and IPAWS alert feed sources.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
                NavItem(
                    label="Alert Poller",
                    icon="fas fa-satellite-dish",
                    href="/admin/poller/",
                    description="Polling interval and feed fetch behaviour.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Uptime Heartbeat",
                    icon="fas fa-heart-pulse",
                    href="/admin/heartbeat/",
                    description="Outbound dead-man's-switch ping to an external monitor.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Tickstem Uptime Monitor",
                    icon="fas fa-satellite-dish",
                    href="/admin/tickstem/",
                    description="Inbound uptime checks against this box's /health endpoint, managed via Tickstem's Monitors API.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Alert Gating",
                    icon="fas fa-hourglass-half",
                    href="/admin/alert-gating/",
                    description="Hold-off timer and manual-override settings for gated alerts.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Notifications",
                    icon="fas fa-bell",
                    href="/admin/notifications/",
                    description="Email, SMS and SNMP trap notification settings.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
                NavItem(
                    label="Mail Server",
                    icon="fas fa-envelope-open-text",
                    href="/admin/mail-server/",
                    description="SMTP / outgoing email server configuration.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
            ),
        ),
        NavGroup(
            label="Audio & Speech",
            icon="fas fa-volume-up",
            items=(
                NavItem(
                    label="Icecast Streaming",
                    icon="fas fa-podcast",
                    href="/admin/icecast",
                    description="Live audio stream server configuration.",
                    permissions=(SYSTEM_VIEW_CONFIG,),
                ),
                NavItem(
                    label="Audio Profiles",
                    icon="fas fa-stream",
                    href="/settings/stream-profiles",
                    description="Audio encoding and stream profile presets.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Text-to-Speech",
                    icon="fas fa-volume-up",
                    href="/admin/tts",
                    description="TTS provider and voice settings for alert audio.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Pronunciation Dictionary",
                    icon="fas fa-spell-check",
                    href="/admin/tts/pronunciation",
                    description="Fix place names TTS mispronounces (Lima, Cairo…).",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
        NavGroup(
            label="Network",
            icon="fas fa-wifi",
            items=(
                NavItem(
                    label="WiFi & Network",
                    icon="fas fa-wifi",
                    href="/admin/network",
                    description="Network interface and connectivity settings.",
                    permissions=(GPIO_VIEW, SYSTEM_CONFIGURE),
                ),
                NavItem(
                    label="Tailscale VPN",
                    icon="fas fa-shield-alt",
                    href="/admin/tailscale",
                    description="Secure mesh VPN network configuration.",
                    permissions=(GPIO_VIEW, SYSTEM_CONFIGURE),
                ),
                NavItem(
                    label="SSL Certificates",
                    icon="fas fa-certificate",
                    href="/admin/certbot",
                    description="Let's Encrypt / Certbot HTTPS certificate management.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
        NavGroup(
            label="Hardware",
            icon="fas fa-microchip",
            items=(
                NavItem(
                    label="SDR Receivers",
                    icon="fas fa-signal",
                    href="/admin/radio",
                    description="Software-defined radio receiver configuration.",
                    permissions=(RECEIVERS_VIEW,),
                ),
                NavItem(
                    label="Audio Streams",
                    icon="fas fa-stream",
                    href="/admin/audio-sources",
                    description="Audio input source and stream configuration.",
                    permissions=(RECEIVERS_VIEW,),
                ),
                NavItem(
                    label="Audio Archives",
                    icon="fas fa-archive",
                    href="/admin/audio/archives",
                    description="Archived audio recording storage settings.",
                    permissions=(RECEIVERS_VIEW,),
                ),
                NavItem(
                    label="Audio/SDR Fix",
                    icon="fas fa-wrench",
                    href="/admin/audio-sdr-fix",
                    description="Diagnose and correct IQ/audio sample-rate mismatches.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Hardware Settings",
                    icon="fas fa-microchip",
                    endpoint="hardware.hardware_settings_page",
                    description="GPIO, OLED, LED display and VFD configuration.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="GPIO & Relays",
                    icon="fas fa-plug",
                    href="/admin/gpio",
                    description="General-purpose I/O pin and relay management.",
                    permissions=(GPIO_VIEW,),
                ),
                NavItem(
                    label="Zigbee",
                    icon="fas fa-home",
                    href="/admin/zigbee",
                    description="Zigbee device and coordinator settings.",
                    permissions=(GPIO_VIEW, SYSTEM_CONFIGURE),
                ),
            ),
        ),
        NavGroup(
            label="Data & Storage",
            icon="fas fa-database",
            items=(
                NavItem(
                    label="Backups",
                    icon="fas fa-database",
                    href="/admin/backups",
                    description="Create, restore and manage configuration backups.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Alert Purge",
                    icon="fas fa-broom",
                    href="/admin/alert-purge/",
                    description="Remove received alerts and reclaim captured audio storage, manually or on a schedule.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Alert Management",
                    icon="fas fa-exclamation-triangle",
                    href="/admin/alert-management",
                    description="Edit or remove stored alerts; mark or delete expired alerts.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="County Boundaries",
                    icon="fas fa-map",
                    href="/admin/county_boundaries",
                    description="Import and manage county/zone boundary geometry.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
                NavItem(
                    label="Data Management",
                    icon="fas fa-database",
                    href="/admin/data-management",
                    description="Upload and manage general boundary polygons (electric, fire, school, custom, ...) and the NOAA zone catalog.",
                    permissions=(SYSTEM_CONFIGURE,),
                ),
            ),
        ),
        NavGroup(
            label="Security & Access",
            icon="fas fa-shield-halved",
            items=(
                NavItem(
                    label="Roles & Permissions",
                    icon="fas fa-user-shield",
                    href="/admin/rbac",
                    description="Define roles and the permissions attached to them.",
                    permissions=_USER_READERS,
                ),
                NavItem(
                    label="User Accounts",
                    icon="fas fa-users",
                    href="/admin/user-accounts",
                    description="Create, edit and deactivate user accounts.",
                    permissions=(SYSTEM_MANAGE_USERS,),
                ),
                NavItem(
                    label="Local Authorities",
                    icon="fas fa-building-shield",
                    href="/admin/local-authorities",
                    description="Configure trusted local authority originators.",
                    permissions=(SYSTEM_MANAGE_USERS,),
                ),
                NavItem(
                    label="Security Policies",
                    icon="fas fa-shield-halved",
                    href="/security/settings",
                    description="Password policy, session limits and MFA settings.",
                    permissions=(SYSTEM_MANAGE_USERS,),
                ),
                # Also listed under Diagnostics -> Security with the same
                # LOGS_VIEW gate -- normally a duplicate worth pruning, but
                # it's the *only* Settings-hub item visible to a LOGS_VIEW-
                # only viewer (test_settings_link_never_leads_to_an_empty_hub
                # catches this); removing it here leaves that viewer with a
                # Settings link that opens to nothing. Kept intentionally.
                NavItem(
                    label="Security Center",
                    icon="fas fa-tower-observation",
                    href="/security/center",
                    description="Traffic, malicious logins, IP bans and fail2ban.",
                    permissions=(LOGS_VIEW,),
                ),
            ),
        ),
    ),
)


__all__ = ["SETTINGS_SECTION"]
