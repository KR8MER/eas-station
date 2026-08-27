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
* Resolve an ad/stream URL to something playable, following VAST XML one hop.
"""

import ipaddress
import logging
import re
import socket
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BASE64_BLOB_RE = re.compile(r'^[A-Za-z0-9+/=]{20,}$')

_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac",
    "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm",
}

# Cap on the response we will read while resolving an ad tag.
_MAX_RESOLVE_BYTES = 2 * 1024 * 1024
_RESOLVE_TIMEOUT_SECONDS = 8


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


def _is_public_url(url: str) -> bool:
    """Return True if *url* is http(s) and resolves to a public IP address.

    Blocks SSRF: the URL comes from stream metadata, which is attacker-supplied
    as far as this server is concerned.
    """
    if not url.startswith(("http://", "https://")):
        return False
    try:
        host = urlparse(url).hostname or ""
        if not host:
            return False
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (socket.gaierror, ValueError):
        return False
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _local_tag(tag: str) -> str:
    """Strip a namespace URI from an ElementTree tag.

    e.g. '{http://www.iab.com/VAST}MediaFile' -> 'MediaFile'.
    """
    return tag.rsplit('}', 1)[-1] if '}' in tag else tag


def _iter_local(root: ET.Element, name: str):
    """``root.iter(name)`` that ignores XML namespaces.

    Real-world VAST responses almost universally declare a default
    ``xmlns`` (e.g. ``xmlns="http://www.iab.com/VAST"``, standard since
    VAST 3.0). ElementTree folds that into every descendant's tag --
    ``<MediaFile>`` parses as ``{http://www.iab.com/VAST}MediaFile`` -- so a
    bare ``root.iter("MediaFile")`` silently matches nothing. That was the
    actual reason "resolve ad" always reported "no audio MediaFile found",
    even for VAST payloads that had a perfectly playable audio/mpeg
    MediaFile sitting right there.
    """
    return (el for el in root.iter() if _local_tag(el.tag) == name)


def _first_text_local(root: ET.Element, name: str) -> Optional[str]:
    for el in _iter_local(root, name):
        text = (el.text or "").strip()
        if text:
            return text
    return None


def resolve_stream_url(url: str) -> Dict[str, Any]:
    """Resolve an ad/stream URL to a directly playable audio URL.

    Handles three cases:

    1. Direct audio (``audio/*`` content type) — the URL is returned as-is.
    2. VAST XML — the first audio ``MediaFile`` URL is returned.
    3. Anything else — an ``error`` explaining why it could not be resolved.

    Args:
        url: The candidate URL from a ``StreamMetadataLog`` row.

    Returns:
        dict: ``{"audio_url": ..., "type": ...}`` on success, otherwise
        ``{"error": ..., "type": ...}``.  Never raises for network failures.
    """
    if not _is_public_url(url):
        return {"error": "Invalid or missing URL", "type": "rejected"}

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (EAS-Station)"}
        )
        with urllib.request.urlopen(req, timeout=_RESOLVE_TIMEOUT_SECONDS) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read(_MAX_RESOLVE_BYTES)
    except Exception as exc:
        logger.warning("resolve-stream-url failed for %s: %s", url, exc)
        return {"error": str(exc), "type": "fetch_error", "original_url": url}

    # 1. Already a direct audio stream
    if any(ct in content_type for ct in ("audio/", "video/mp2t", "application/ogg")):
        return {"audio_url": url, "type": "direct"}

    # 2. VAST / XML
    if "xml" in content_type or data.lstrip()[:5] in (b"<?xml", b"<VAST"):
        try:
            root = ET.fromstring(data)
        except ET.ParseError as exc:
            return {"error": f"XML parse error: {exc}", "type": "xml_error", "original_url": url}

        # AdTitle/AdSystem/Duration are informational, not required for
        # playback -- extract best-effort so the UI can show more than just
        # "Ad URL" when the ad server actually provides them.
        ad_title = _first_text_local(root, "AdTitle")
        ad_system = _first_text_local(root, "AdSystem")
        duration = _first_text_local(root, "Duration")

        for media_file in _iter_local(root, "MediaFile"):
            mime = (media_file.get("type") or "").lower().strip()
            audio_url = (media_file.text or "").strip()
            if audio_url.startswith(("http://", "https://")) and (
                mime in _AUDIO_MIMES or mime.startswith("audio/")
            ):
                result: Dict[str, Any] = {
                    "audio_url": audio_url,
                    "type": "vast",
                    "mime": mime,
                    "original_url": url,
                }
                if ad_title:
                    result["ad_title"] = ad_title
                if ad_system:
                    result["ad_system"] = ad_system
                if duration:
                    result["duration"] = duration
                return result
        return {
            "error": "VAST parsed but no audio MediaFile found",
            "type": "vast_no_audio",
            "original_url": url,
        }

    # 3. Unknown format
    return {
        "error": f"Unrecognised content type: {content_type or '(none)'}",
        "type": "unknown",
        "original_url": url,
    }


__all__ = ["is_base64_blob", "is_junk_metadata", "resolve_stream_url"]
