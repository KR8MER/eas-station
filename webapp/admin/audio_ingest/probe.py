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

"""Probing a remote stream URL before a source is created."""

import logging
import requests
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)


def _describe_stream_status(status_code: int, reason: str = '') -> Tuple[bool, str]:
    """Translate an HTTP status code from a stream probe into a user message.

    Returns (ok, message) where ok is True only for 2xx responses. Auth-required
    streams (401/403) get an explicit, actionable message so the UI can explain
    *why* the stream cannot be added instead of surfacing a generic error.
    """
    reason = (reason or '').strip()
    if 200 <= status_code < 300:
        return True, f"Stream reachable (HTTP {status_code})."
    if status_code == 401:
        return False, (
            "401 Unauthorized — this stream requires authentication credentials "
            "and cannot be used as a source."
        )
    if status_code == 403:
        return False, (
            "403 Forbidden — this stream requires authentication or is access "
            "restricted (token, referrer, or geo/IP lock) and cannot be used as "
            "a source."
        )
    if status_code == 404:
        return False, "404 Not Found — the stream URL does not exist. Double-check the address."
    if status_code == 429:
        return False, "429 Too Many Requests — the stream server is rate-limiting. Try again later."
    suffix = f" {reason}" if reason else ""
    if 400 <= status_code < 500:
        return False, f"{status_code}{suffix} — the stream server rejected the request."
    if 500 <= status_code < 600:
        return False, f"{status_code}{suffix} — the stream server is experiencing errors. Try again later."
    return False, f"Unexpected response (HTTP {status_code}{suffix})."


def _probe_stream_url(url: str, username: str = '', password: str = '',
                      auth_header: str = '') -> Dict[str, Any]:
    """Make a lightweight connection to a stream URL to verify it is usable.

    Resolves M3U/M3U8 playlists to their first entry, then issues a streaming GET
    (without downloading the body) using the same headers the FFmpeg-based source
    sends, so authentication-gated streams report the real HTTP status (e.g. 403).
    Optional Basic-auth credentials or a raw Authorization value let protected
    streams be validated with their configured authentication.

    Returns a dict: {ok, status, message, resolved_url, content_type}.
    """
    import base64
    from urllib.parse import urljoin, urlparse

    url = (url or '').strip()
    if not url:
        return {'ok': False, 'status': None, 'message': 'Stream URL is required.',
                'resolved_url': None, 'content_type': None}

    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https'):
        return {'ok': False, 'status': None,
                'message': f"Unsupported URL scheme '{parsed.scheme or '(none)'}'. Use http or https.",
                'resolved_url': None, 'content_type': None}
    if not parsed.netloc:
        return {'ok': False, 'status': None, 'message': 'Invalid stream URL: missing hostname.',
                'resolved_url': None, 'content_type': None}

    headers = {'User-Agent': 'EAS-Station/2.0', 'Icy-MetaData': '1'}
    auth_header = (auth_header or '').strip()
    if auth_header:
        if ':' in auth_header and not auth_header.lower().startswith(('bearer ', 'basic ')):
            name, _, value = auth_header.partition(':')
            headers[name.strip()] = value.strip()
        else:
            headers['Authorization'] = auth_header
    elif username or password:
        token = base64.b64encode(f"{username}:{password}".encode('utf-8')).decode('ascii')
        headers['Authorization'] = f"Basic {token}"
    # Disable proxies so we connect directly to external streams (matches the source adapter).
    proxies = {'http': None, 'https': None}
    resolved_url = url

    try:
        # Resolve playlists to a concrete stream entry before probing.
        lower_path = parsed.path.lower()
        if lower_path.endswith('.m3u') or lower_path.endswith('.m3u8'):
            playlist = requests.get(url, timeout=8, headers=headers, proxies=proxies)
            if not playlist.ok:
                ok, message = _describe_stream_status(playlist.status_code, playlist.reason)
                return {'ok': ok, 'status': playlist.status_code,
                        'message': f"Playlist could not be read — {message}",
                        'resolved_url': url, 'content_type': None}
            resolved_url = None
            for line in playlist.text.splitlines():
                entry = line.strip()
                if not entry or entry.startswith('#'):
                    continue
                candidate = urljoin(url, entry)
                cparsed = urlparse(candidate)
                if cparsed.scheme in ('http', 'https') and cparsed.netloc:
                    resolved_url = candidate
                    break
            if not resolved_url:
                return {'ok': False, 'status': None,
                        'message': 'Playlist did not contain a playable stream URL.',
                        'resolved_url': url, 'content_type': None}

        with requests.get(resolved_url, timeout=8, headers=headers, proxies=proxies,
                          stream=True) as response:
            ok, message = _describe_stream_status(response.status_code, response.reason)
            content_type = response.headers.get('Content-Type')
            return {'ok': ok, 'status': response.status_code, 'message': message,
                    'resolved_url': resolved_url, 'content_type': content_type}
    except requests.exceptions.Timeout:
        return {'ok': False, 'status': None,
                'message': 'Connection timed out — the stream server did not respond within 8 seconds.',
                'resolved_url': resolved_url, 'content_type': None}
    except requests.exceptions.SSLError as exc:
        return {'ok': False, 'status': None,
                'message': f'TLS/SSL error connecting to the stream: {exc}',
                'resolved_url': resolved_url, 'content_type': None}
    except requests.exceptions.ConnectionError:
        return {'ok': False, 'status': None,
                'message': 'Connection failed — host unreachable or refused the connection.',
                'resolved_url': resolved_url, 'content_type': None}
    except requests.exceptions.RequestException as exc:
        return {'ok': False, 'status': None,
                'message': f'Could not connect to the stream: {exc}',
                'resolved_url': resolved_url, 'content_type': None}
