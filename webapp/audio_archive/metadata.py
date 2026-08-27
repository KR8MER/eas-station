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

"""
ICY stream-metadata helpers for the Audio Archives page.

Two jobs:

* Classify junk rows in ``StreamMetadataLog`` — some stations put a raw
  base64-encoded ad URL where the song title belongs.
* Resolve an ad/stream URL to something playable, following VAST XML one hop
  -- the actual resolver lives in ``app_core.audio.vast_resolve`` now, since
  the ICY metadata ingest path (no Flask involved) needs it too; this module
  just re-exports it for the existing "resolve and play" API route.
"""

import re
from typing import Optional

from app_core.audio.vast_resolve import resolve_stream_url

_BASE64_BLOB_RE = re.compile(r'^[A-Za-z0-9+/=]{20,}$')


def is_base64_blob(text: Optional[str]) -> bool:
    """Return True if *text* looks like a raw base64-encoded blob (junk metadata)."""
    if not text:
        return False
    stripped = text.strip()
    return bool(stripped and not re.search(r'\s', stripped) and _BASE64_BLOB_RE.match(stripped))


def is_junk_metadata(
    title: Optional[str],
    display: Optional[str],
    raw: Optional[str],
    stream_url: Optional[str] = None,
) -> bool:
    """Return True if this metadata row contains only junk (no useful display text).

    Junk means the title/display value is a raw base64-encoded URL blob — not a
    real song title, artist, or station ID.  Commercials, promos, and station
    IDs are NOT considered junk and are left alone.  Entries carrying a resolved
    ``stream_url`` (e.g. a VAST ad tag) are kept so the user can try playback.
    """
    if stream_url and stream_url.startswith(("http://", "https://")):
        return False
    if is_base64_blob(title):
        return True
    if not (title or "").strip() and is_base64_blob(display):
        return True
    if not (title or "").strip() and not (display or "").strip() and is_base64_blob(raw):
        return True
    return False


__all__ = ["is_base64_blob", "is_junk_metadata", "resolve_stream_url"]
