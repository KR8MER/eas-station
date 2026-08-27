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

"""Resolve an ad/stream URL (following VAST XML one hop) to playable audio.

Lives in app_core (not webapp/audio_archive, where this used to live)
because it needs to run from two places: the Audio Archives page's manual
"resolve and play" button (webapp), AND the ICY metadata ingest path
(app_core.audio.sources, no Flask involved) -- see the module docstring on
why ingest-time resolution matters.

Why resolve at ingest time at all, when the manual button already exists:
iHeartRadio's ad server (Triton) discards a VAST cache entry within minutes
of serving it -- observed in production: every entry checked more than ~20
minutes after being logged already 404s. An operator browsing Song History
later and clicking "resolve" is almost always too late; the link is
already gone. Resolving immediately, while the ad is still playing, and
storing the underlying creative's CDN URL instead of the ephemeral VAST
wrapper fixes that: the CDN file is a stable, reused asset (not a
per-impression token) and stays valid far longer.
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

_AUDIO_MIMES = {
    "audio/mpeg", "audio/mp3", "audio/mp4", "audio/aac",
    "audio/ogg", "audio/wav", "audio/x-wav", "audio/webm",
}

# Cap on the response we will read while resolving an ad tag.
_MAX_RESOLVE_BYTES = 2 * 1024 * 1024
_DEFAULT_TIMEOUT_SECONDS = 8.0


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
    bare ``root.iter("MediaFile")`` silently matches nothing.
    """
    return (el for el in root.iter() if _local_tag(el.tag) == name)


def _first_text_local(root: ET.Element, name: str) -> Optional[str]:
    for el in _iter_local(root, name):
        text = (el.text or "").strip()
        if text:
            return text
    return None


def resolve_stream_url(url: str, *, timeout: float = _DEFAULT_TIMEOUT_SECONDS) -> Dict[str, Any]:
    """Resolve an ad/stream URL to a directly playable audio URL.

    Handles three cases:

    1. Direct audio (``audio/*`` content type) — the URL is returned as-is.
    2. VAST XML — the first audio ``MediaFile`` URL is returned, along with
       ``ad_title``/``ad_system``/``duration`` when the ad server provides them.
    3. Anything else — an ``error`` explaining why it could not be resolved.

    Args:
        url: The candidate URL (e.g. from a ``StreamMetadataLog`` row, or a
            just-parsed ICY StreamTitle attribute).
        timeout: Socket timeout in seconds. Callers on a real-time thread
            (ICY metadata ingest) should pass something shorter than the
            web UI's on-demand default.

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
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            data = resp.read(_MAX_RESOLVE_BYTES)
    except Exception as exc:
        logger.warning("resolve_stream_url failed for %s: %s", url, exc)
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


__all__ = ["resolve_stream_url"]
