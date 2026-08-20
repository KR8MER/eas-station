from __future__ import annotations

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

"""
Audio source ``config_params`` ownership rules.

``AudioSourceConfigDB.config_params`` is a single JSON blob that two very
different writers share:

* **Auto-synced keys** — derived from the ``radio_receivers`` row every time a
  receiver is saved and, more importantly, on every service start
  (``eas_monitoring_service.sync_audio_sources_from_receivers`` and
  ``webapp.admin.audio_ingest.ensure_sdr_audio_monitor_source``).
* **User-owned keys** — written only from the web UI and never derivable from a
  receiver.  ``archive`` (the Audio Archives retention/format settings) is the
  first of these.

Both sync paths used to build a fresh dict and assign it wholesale, so every
service restart — i.e. every upgrade — silently deleted the ``archive`` block
and archiving reverted to "off" with default retention.  ``merge_managed_config_params``
is the fix: it replaces the keys the sync owns and leaves everything else alone.
"""

from typing import Any, Dict, Mapping, Optional

# Keys that the radio→audio sync derives from the RadioReceiver row.  These are
# authoritative: whatever the sync computes replaces what is in the database,
# and any of these keys missing from a fresh sync is dropped.
#
# Anything NOT listed here belongs to some other writer (currently the Audio
# Archives page) and must survive a sync untouched.  When you add a key to
# either sync function, add it here too, or the sync will treat it as
# user-owned and stop updating it.
MANAGED_CONFIG_KEYS: frozenset[str] = frozenset({
    "sample_rate",
    "channels",
    "buffer_size",
    "silence_threshold_db",
    "silence_duration_seconds",
    "device_params",
    "managed_by",
})


def merge_managed_config_params(
    existing: Optional[Mapping[str, Any]],
    managed: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return *managed* applied over *existing*, preserving user-owned keys.

    Keys in :data:`MANAGED_CONFIG_KEYS` come from *managed* only — stale ones
    left over from an older sync are dropped.  Every other key in *existing*
    (notably ``archive``) is carried through unchanged.

    Args:
        existing: The ``config_params`` currently stored on the DB row, or None.
        managed:  The freshly derived receiver-managed parameters.

    Returns:
        dict: A new dict safe to assign to ``AudioSourceConfigDB.config_params``.

    Example:
        >>> stored = {"sample_rate": 32000, "archive": {"enabled": True}}
        >>> merge_managed_config_params(stored, {"sample_rate": 48000})
        {'archive': {'enabled': True}, 'sample_rate': 48000}
    """
    merged: Dict[str, Any] = {
        key: value
        for key, value in (existing or {}).items()
        if key not in MANAGED_CONFIG_KEYS
    }
    merged.update(managed)
    return merged


__all__ = ["MANAGED_CONFIG_KEYS", "merge_managed_config_params"]
