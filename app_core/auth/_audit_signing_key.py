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

"""Ed25519 signing-key loader for the tamper-evident audit-log chain.

This helper is intentionally tiny.  The :mod:`app_core.auth.audit` module owns
the chain-construction logic; this module just answers "what is the
Ed25519 private key we should sign new audit rows with, and what is its
corresponding public key for verification?".

Key-resolution order:

1. ``AUDIT_SIGNING_KEY_PATH`` environment variable -- absolute or relative
   path to a PEM-encoded Ed25519 private key (the standard production
   deployment puts this at ``${INSTALL_DIR}/secrets/audit_signing.key`` with
   ``0600`` permissions, installed by ``install.sh``).
2. ``${REPO_ROOT}/secrets/audit_signing.key`` -- convenience fallback for
   local development; not used in production.
3. **Ephemeral key** -- generated in-process on first use and held for the
   lifetime of the process.  A warning is emitted via ``logging`` so this
   never silently slips into production.  Restarting the process will rotate
   the in-memory key and break the verifiability of rows signed by the old
   one, which is the correct behaviour: an ephemeral key is by definition not
   a tamper-evidence guarantee, and the resulting "signature mismatch" on
   verify_chain() is exactly the signal that production needs a real key.
"""

import logging
import os
import threading
from pathlib import Path
from typing import Optional, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)


logger = logging.getLogger(__name__)


_KEY_CACHE: Optional[Tuple[Ed25519PrivateKey, Ed25519PublicKey, str]] = None
_KEY_LOCK = threading.Lock()
_KEY_SOURCE_EPHEMERAL = "ephemeral"
_KEY_SOURCE_ENV = "env"
_KEY_SOURCE_REPO = "repo-secrets"


def _project_root() -> Path:
    # This file lives at app_core/auth/_audit_signing_key.py; project root is
    # two levels up (app_core/.. == repo root).  We don't import the
    # versioning module here because that pulls in Flask -- this helper must
    # stay importable from a bare-Alembic context for offline schema work.
    return Path(__file__).resolve().parents[2]


def _load_from_path(path: Path) -> Optional[Ed25519PrivateKey]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        logger.warning("audit signing key path %s is unreadable: %s", path, exc)
        return None
    try:
        key = serialization.load_pem_private_key(data, password=None)
    except Exception as exc:  # noqa: BLE001 - any crypto failure means "no key"
        logger.warning("audit signing key at %s could not be parsed: %s", path, exc)
        return None
    if not isinstance(key, Ed25519PrivateKey):
        logger.warning(
            "audit signing key at %s is not Ed25519 (got %s); ignoring",
            path,
            type(key).__name__,
        )
        return None
    return key


def _resolve_key() -> Tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Return ``(private, public, source)``.

    ``source`` is one of ``"env"``, ``"repo-secrets"``, ``"ephemeral"`` and is
    surfaced to the verifier so the admin UI can flag deployments that are
    still running on an ephemeral key.
    """
    env_path = os.environ.get("AUDIT_SIGNING_KEY_PATH", "").strip()
    if env_path:
        key = _load_from_path(Path(env_path).expanduser())
        if key is not None:
            return key, key.public_key(), _KEY_SOURCE_ENV
        # Explicit env path that fails to load is a configuration error, not
        # a silent fallback.  Fall through to repo-relative; if that also
        # fails we log loudly via the ephemeral branch.

    repo_path = _project_root() / "secrets" / "audit_signing.key"
    if repo_path.exists():
        key = _load_from_path(repo_path)
        if key is not None:
            return key, key.public_key(), _KEY_SOURCE_REPO

    # Last resort: ephemeral key.  Warn so this never gets shipped silently.
    logger.warning(
        "audit-log signing key not found (checked AUDIT_SIGNING_KEY_PATH=%r "
        "and %s); generating an EPHEMERAL key for this process. Audit chain "
        "signatures will not survive a restart -- provision a persistent "
        "key for production deployments.",
        env_path or "(unset)",
        repo_path,
    )
    private = Ed25519PrivateKey.generate()
    return private, private.public_key(), _KEY_SOURCE_EPHEMERAL


def get_signing_keypair() -> Tuple[Ed25519PrivateKey, Ed25519PublicKey, str]:
    """Return a cached ``(private, public, source)`` triple.

    The cache is process-wide; tests that need a fresh key should call
    :func:`reset_signing_key_cache_for_tests` between cases.
    """
    global _KEY_CACHE
    if _KEY_CACHE is not None:
        return _KEY_CACHE
    with _KEY_LOCK:
        if _KEY_CACHE is None:
            _KEY_CACHE = _resolve_key()
    return _KEY_CACHE


def is_ephemeral_key() -> bool:
    """Return True if the currently-cached signing key was generated in-process."""
    return get_signing_keypair()[2] == _KEY_SOURCE_EPHEMERAL


def reset_signing_key_cache_for_tests() -> None:
    """Drop the cached keypair so the next call re-resolves from env/disk.

    Test-only helper.  Production code must never call this -- rotating the
    signing key mid-process would break the chain.
    """
    global _KEY_CACHE
    with _KEY_LOCK:
        _KEY_CACHE = None


__all__ = [
    "get_signing_keypair",
    "is_ephemeral_key",
    "reset_signing_key_cache_for_tests",
]
