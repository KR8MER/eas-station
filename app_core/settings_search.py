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

"""Search Settings: an index over settings *field labels and stored values*,
not just page labels.

webapp.navigation already flattens the Settings hub's ~35 pages into
`nav_settings_items` (label/url/group) for the Ctrl+K command palette, but
that only ever matches a page's own label -- it has no idea a given page
holds "Stream Bitrate: 128" or "GPIO Pin 17". This module builds that
finer-grained index: one entry per (settings model, column) pair, each
carrying its humanized field label, current value, and the settings page it
belongs to.

Security: every field is checked against `app_core.crypto`'s encrypted-column
list (belt) and an isinstance check on the column's SQLAlchemy type (suspenders)
before being included -- a value that lives in an `EncryptedString` column
(source/admin passwords, API keys, SMTP/SMS/SNMP credentials, VPN auth keys)
must never appear here, searchable or not. A small manual blocklist catches
the couple of columns that carry a bearer token in a plain URL without using
`EncryptedString` (see `_EXCLUDED_COLUMNS`).

Deliberately NOT a global context processor like `nav_settings_items`: unlike
that free in-memory tuple walk, this does a real `SELECT` per mapped model
(~15), so `build_settings_search_index()` is only ever called from the
`/settings` route itself.
"""

import logging
from typing import Any, Callable, Optional

from sqlalchemy import inspect as sa_inspect

from app_core.crypto import ENCRYPTED_COLUMNS, EncryptedString
from app_core.extensions import db
from app_core.models import (
    AlertFilterSettings,
    AlertGatingSettings,
    ApplicationSettings,
    CertbotSettings,
    EASSettings,
    HardwareSettings,
    HeartbeatSettings,
    IcecastSettings,
    LocationSettings,
    NotificationSettings,
    PollerSettings,
    TailscaleSettings,
    TickstemSettings,
    TTSSettings,
)

logger = logging.getLogger(__name__)

# Every (table, column) an EncryptedString covers, as a set for O(1) lookup.
_ENCRYPTED_COLUMN_SET = set(ENCRYPTED_COLUMNS)

# Columns that carry a bearer token in a plain URL/id rather than an
# EncryptedString column -- the isinstance/table-column checks above can't
# catch these, so they're named explicitly. (Anything on
# TickstemServiceHeartbeat is moot: that model is multi-row, per-service
# state, not a settings page, and isn't in SETTINGS_MODELS_BY_URL below.)
_EXCLUDED_COLUMNS: set[tuple[str, str]] = {
    ("heartbeat_settings", "ping_url"),
}

# One settings page can be backed by more than one model (Location & Alert
# Filtering genuinely covers both LocationSettings and AlertFilterSettings).
# Pages with no simple field/value config -- Backups, RBAC, User Accounts,
# the pgweb link, Alert Sources (a live IPAWS/NOAA status page, not a config
# form) -- are left out entirely; they're action/record pages, not settings
# forms, and don't fit "search the variable and the entered data".
#
# NotificationSettings also backs /admin/mail-server/ (its smtp_* columns),
# but every field's a duplicate of what /admin/notifications/ already shows
# for the same row -- attributing them all to one page avoids two identical,
# redundant hits for the same search.
SETTINGS_MODELS_BY_URL: dict[str, tuple[type, ...]] = {
    "/admin/application/": (ApplicationSettings,),
    "/admin/location-settings": (LocationSettings, AlertFilterSettings),
    "/admin/eas-encoder-settings": (EASSettings,),
    "/admin/poller/": (PollerSettings,),
    "/admin/heartbeat/": (HeartbeatSettings,),
    "/admin/tickstem/": (TickstemSettings,),
    "/admin/alert-gating/": (AlertGatingSettings,),
    "/admin/notifications/": (NotificationSettings,),
    "/admin/icecast": (IcecastSettings,),
    "/admin/tts": (TTSSettings,),
    "/admin/tailscale": (TailscaleSettings,),
    "/admin/certbot": (CertbotSettings,),
}

# HardwareSettings is one ~60-column model shared by three distinct pages
# (Hardware Settings, GPIO & Relays, Zigbee) -- routed by column prefix
# instead of lumping every field under one page, since misattributing e.g. a
# Zigbee coordinator setting to "Hardware Settings" defeats the point of a
# search meant to tell you *which* page to go to.
def _hardware_settings_url(column_name: str) -> str:
    if column_name.startswith("zigbee_"):
        return "/admin/zigbee"
    if column_name.startswith("gpio_") or column_name == "dead_air_buzzer_gpio_pin":
        return "/admin/gpio"
    return "/admin/hardware"


# Small acronym fixups applied after title-casing each underscore-split word
# (e.g. "smtp_host" -> "Smtp Host" -> "SMTP Host").
_ACRONYMS = {
    "smtp", "gpio", "api", "tts", "snmp", "ssl", "gps", "oled", "vfd", "led",
    "ip", "id", "url", "fips", "cap", "ipaws", "eas", "same", "mdc1200", "i2c",
    "sdr", "dns", "vpn", "ntp",
}


def _humanize(column_name: str) -> str:
    words = []
    for word in column_name.split("_"):
        words.append(word.upper() if word.lower() in _ACRONYMS else word.capitalize())
    return " ".join(words)


def _format_value(value: Any) -> tuple[Optional[str], str]:
    """Returns (value_display, value_search); value_display is None to skip
    this field entirely (used for nested dict/JSON blobs that aren't
    meaningfully "entered data").
    """
    if value is None:
        return "(not set)", ""
    if isinstance(value, bool):
        return ("Yes" if value else "No"), ("yes" if value else "no")
    if isinstance(value, dict):
        return None, ""
    if isinstance(value, (list, tuple)):
        if not value:
            return "(none)", ""
        text = ", ".join(str(v) for v in value)
        return text, text.lower()
    text = str(value)
    return text, text.lower()


def _index_model(
    model: type,
    url_for_column: Callable[[str], Optional[str]],
    visible_pages: dict[str, dict],
    results: list[dict[str, str]],
) -> None:
    try:
        row = model.query.first()
    except Exception:
        logger.debug("Settings search: could not query %s", model.__tablename__, exc_info=True)
        return
    if row is None:
        return

    mapper = sa_inspect(model)
    for column in mapper.columns:
        if column.primary_key:
            continue
        if isinstance(column.type, (db.DateTime, db.Date, db.Time)):
            continue
        if (model.__tablename__, column.key) in _ENCRYPTED_COLUMN_SET:
            continue
        if (model.__tablename__, column.key) in _EXCLUDED_COLUMNS:
            continue
        if isinstance(column.type, EncryptedString):
            continue

        page_url = url_for_column(column.key)
        if page_url is None:
            continue
        page = visible_pages.get(page_url)
        if page is None:
            continue  # current viewer can't see this page -- exclude its fields too

        value = getattr(row, column.key, None)
        if isinstance(value, dict):
            continue
        display, search_text = _format_value(value)
        if display is None:
            continue

        results.append({
            "field_label": _humanize(column.key),
            "value_display": display,
            "value_search": search_text,
            "page_label": page["label"],
            "page_url": page_url,
            "group": page["group"],
        })


def build_settings_search_index(nav_settings_items: list[dict]) -> list[dict[str, str]]:
    """Build the flat field/value search index for the current viewer.

    Args:
        nav_settings_items: the already permission-filtered list
            `webapp.navigation._flatten_settings_items()` produces --
            reusing it means this index inherits the exact same
            page-visibility rules as the Settings hub and command palette,
            with no separate permission logic to keep in sync.

    Returns:
        List of {field_label, value_display, value_search, page_label,
        page_url, group} dicts. Never includes an encrypted or
        credential-bearing field, regardless of the query run against it.
    """
    if not nav_settings_items:
        return []

    visible_pages = {item["url"]: item for item in nav_settings_items}
    results: list[dict[str, str]] = []

    for page_url, models in SETTINGS_MODELS_BY_URL.items():
        for model in models:
            _index_model(model, lambda _col, u=page_url: u, visible_pages, results)

    _index_model(HardwareSettings, _hardware_settings_url, visible_pages, results)

    return results
