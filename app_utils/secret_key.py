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

"""Shared Flask ``SECRET_KEY`` resolution.

Every process that touches encrypted-at-rest settings (``app_core.crypto``
derives its encryption/pepper keys from ``current_app.secret_key``) must
resolve to the *same* key, or decryption of values written by one process
fails silently in another. ``app.py`` (Gunicorn) and ``eas_monitoring_service.py``
(the standalone audio/EAS process) are separate Flask apps that both need
this, so the resolution logic lives here once instead of being duplicated.
"""

import logging
import os
import secrets

logger = logging.getLogger(__name__)

# Values that mean "no real secret was configured" rather than an actual key.
PLACEHOLDER_SECRETS = {
    '',
    'dev-key-change-in-production',
    'replace-with-a-long-random-string',
}


def load_or_generate_secret_key(key_file: str) -> str:
    """Load the Flask secret key from *key_file*, or generate and persist a new one.

    This ensures every process using this fallback (e.g. Gunicorn workers,
    which import the web app independently without ``--preload``) uses the
    **same** secret key, preventing session cookies -- or values encrypted
    with a key derived from it -- signed by one process from being rejected
    by another.

    The key file is written with mode 0o600 (owner-read only) and is excluded
    from version control via ``.gitignore``.
    """
    try:
        if os.path.isfile(key_file):
            with open(key_file, 'r') as _f:
                _key = _f.read().strip()
            if len(_key) >= 32:
                return _key
    except Exception as _read_err:
        logger.debug("Could not read secret key file %s: %s", key_file, _read_err)

    # Generate a new key and try to persist it atomically.
    _key = secrets.token_hex(32)
    try:
        _tmp = key_file + '.tmp'
        with open(_tmp, 'w') as _f:
            _f.write(_key)
        os.chmod(_tmp, 0o600)
        os.replace(_tmp, key_file)
        logger.info("Persisted runtime secret key to %s", key_file)
    except Exception as _write_err:
        logger.debug("Could not persist secret key to %s: %s", key_file, _write_err)
    return _key


def resolve_secret_key(default_key_file: str) -> tuple[str, bool]:
    """Resolve the Flask secret key from ``SECRET_KEY``, falling back to a shared file.

    Args:
        default_key_file: Path to use for the persisted fallback key when
            ``SECRET_KEY_FILE`` is not set. Callers should pass a path that
            resolves to the same file across every process on the host (e.g.
            derived from the repository root), so a process using the
            fallback still agrees with one that has ``SECRET_KEY`` set.

    Returns:
        ``(secret_key, used_fallback)`` -- ``used_fallback`` is True when
        ``SECRET_KEY`` was missing or a placeholder and the shared key file
        was used instead, so callers can log a warning in their own style.
    """
    secret_key = os.environ.get('SECRET_KEY', '')
    if secret_key in PLACEHOLDER_SECRETS or len(secret_key) < 32:
        secret_key = load_or_generate_secret_key(
            os.environ.get('SECRET_KEY_FILE', default_key_file)
        )
        return secret_key, True
    return secret_key, False
