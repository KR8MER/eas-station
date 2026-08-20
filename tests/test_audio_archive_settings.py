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

"""Audio archiving settings must survive upgrades.

Archiving settings live in ``AudioSourceConfigDB.config_params["archive"]``.
The same JSON column also holds receiver-derived keys that two sync routines
rebuild from scratch on every service start — i.e. after every upgrade.  Both
routines used to assign a fresh dict, deleting the ``archive`` block along with
it, so archiving silently reverted to off with default retention on each
restart.  These tests pin the merge behaviour that fixes it.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.audio.source_config import (
    MANAGED_CONFIG_KEYS,
    merge_managed_config_params,
)
from webapp.audio_archive.config import (
    DEFAULT_ARCHIVE_CONFIG,
    normalize_archive_config,
)


# ---------------------------------------------------------------------------
# merge_managed_config_params
# ---------------------------------------------------------------------------

def test_merge_preserves_user_owned_archive_block():
    """The whole point: a receiver sync must not delete archiving settings."""
    stored = {
        "sample_rate": 32000,
        "channels": 1,
        "managed_by": "radio",
        "archive": {"enabled": True, "retention_days": 30, "format": "mp3"},
    }
    managed = {"sample_rate": 48000, "channels": 2, "managed_by": "radio"}

    merged = merge_managed_config_params(stored, managed)

    assert merged["archive"] == {"enabled": True, "retention_days": 30, "format": "mp3"}
    assert merged["sample_rate"] == 48000
    assert merged["channels"] == 2


def test_merge_replaces_every_managed_key():
    """Receiver-derived values are authoritative — the sync always wins."""
    stored = {key: "stale" for key in MANAGED_CONFIG_KEYS}
    managed = {key: "fresh" for key in MANAGED_CONFIG_KEYS}

    merged = merge_managed_config_params(stored, managed)

    assert all(merged[key] == "fresh" for key in MANAGED_CONFIG_KEYS)


def test_merge_drops_managed_keys_absent_from_a_fresh_sync():
    """A managed key the sync no longer emits must not linger forever."""
    stored = {"buffer_size": 8192, "archive": {"enabled": True}}

    merged = merge_managed_config_params(stored, {"sample_rate": 44100})

    assert "buffer_size" not in merged
    assert merged["archive"] == {"enabled": True}


def test_merge_handles_missing_existing_config():
    assert merge_managed_config_params(None, {"sample_rate": 44100}) == {"sample_rate": 44100}


def test_merge_does_not_mutate_its_inputs():
    stored = {"sample_rate": 32000, "archive": {"enabled": True}}
    managed = {"sample_rate": 48000}

    merge_managed_config_params(stored, managed)

    assert stored == {"sample_rate": 32000, "archive": {"enabled": True}}
    assert managed == {"sample_rate": 48000}


def test_archive_is_not_a_managed_key():
    """A guard against someone 'tidying' archive into the managed set."""
    assert "archive" not in MANAGED_CONFIG_KEYS


# ---------------------------------------------------------------------------
# normalize_archive_config
# ---------------------------------------------------------------------------

def test_normalize_fills_in_every_default():
    assert normalize_archive_config(None) == DEFAULT_ARCHIVE_CONFIG


def test_normalize_coerces_strings_from_form_style_payloads():
    cfg = normalize_archive_config({
        "enabled": "true",
        "retention_days": "14",
        "max_disk_bytes": "1073741824",
        "bitrate": "192",
        "silence_threshold": "0.005",
        "format": "MP3",
    })

    assert cfg["enabled"] is True
    assert cfg["retention_days"] == 14
    assert cfg["max_disk_bytes"] == 1073741824
    assert cfg["bitrate"] == 192
    assert cfg["silence_threshold"] == pytest.approx(0.005)
    assert cfg["format"] == "mp3"


def test_normalize_clamps_out_of_range_values():
    cfg = normalize_archive_config({
        "segment_duration_seconds": 10 ** 9,
        "retention_days": -5,
        "bitrate": 9999,
        "silence_threshold": 42.0,
    })

    assert cfg["segment_duration_seconds"] == 86400
    assert cfg["retention_days"] == 0
    assert cfg["bitrate"] == 320
    assert cfg["silence_threshold"] == 1.0


def test_normalize_falls_back_on_garbage_rather_than_raising():
    """The runtime reads these back with int()/float() at service start; a
    single unparseable stored value would stop archiving from coming up."""
    cfg = normalize_archive_config({
        "retention_days": "not-a-number",
        "format": "flac",
        "output_dir": "   ",
    })

    assert cfg["retention_days"] == DEFAULT_ARCHIVE_CONFIG["retention_days"]
    assert cfg["format"] == "wav"
    assert cfg["output_dir"] == "archives"


def test_normalize_drops_unknown_keys():
    assert "injected" not in normalize_archive_config({"injected": "value"})


def test_normalize_applies_base_before_raw():
    """A partial save keeps the previously stored values for untouched keys."""
    base = {"enabled": True, "retention_days": 30, "format": "mp3", "bitrate": 256}

    cfg = normalize_archive_config({"retention_days": 60}, base=base)

    assert cfg["retention_days"] == 60
    assert cfg["enabled"] is True
    assert cfg["format"] == "mp3"
    assert cfg["bitrate"] == 256
