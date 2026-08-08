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

"""Compatibility shim for the radio settings routes.

The implementation lives in ``webapp/radio_settings/``. This module keeps
``from webapp.routes_settings_radio import register`` resolving, which is what
the route registry in ``webapp/__init__.py`` uses.

Deliberately **not** re-exported: the names a test injects fakes for
(``get_redis_client``, ``_log_radio_event``, ``RADIO_CAPTURE_DIR`` and friends).
Re-exporting them would make ``monkeypatch.setattr`` here succeed while
patching a name nothing reads — a silent no-op. Leaving them out turns that
into an immediate AttributeError that points at the real target,
``webapp.radio_settings.deps``.
"""

from webapp.radio_settings import (
    _parse_receiver_payload,
    _receiver_to_dict,
    _send_sdr_command,
    _sync_audio_monitors,
    _sync_radio_manager_state,
    register,
)

__all__ = [
    "_parse_receiver_payload",
    "_receiver_to_dict",
    "_send_sdr_command",
    "_sync_audio_monitors",
    "_sync_radio_manager_state",
    "register",
]
