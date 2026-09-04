"""Column-level secret encryption and password peppering shared across the app.

Every stored credential this module touches -- third-party API keys, SMTP/
streaming passwords, Tailscale auth keys, TOTP secrets -- was previously
written to the database in plaintext. `EncryptedString` closes that: it's a
drop-in SQLAlchemy column type that encrypts on write and decrypts on read,
so a model column just declares `db.Column(EncryptedString(...))` and every
existing read/write call site keeps working unchanged.

Key material: both the encryption key and the password pepper are derived
from the Flask app's SECRET_KEY via HKDF-SHA256, using a distinct "info"
label per purpose. This gives each purpose a cryptographically independent
subkey without requiring a second secret to deploy and protect -- SECRET_KEY
is already required, already validated for length at setup, and already the
one thing every deployment must already keep safe and stable.

⚠️ Rotating SECRET_KEY invalidates every value encrypted with
EncryptedString (every stored API key/password/token) and the peppered-
password baseline for every login, since both derive from it. Back up
secrets before rotating, or expect to re-enter them and have password hashes
silently upgrade on next successful login (see app_core/_models_admin.py).
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from flask import current_app, has_app_context
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

logger = logging.getLogger(__name__)

_ENCRYPTION_INFO = b"eas-station-column-encryption-v1"
_PEPPER_INFO = b"eas-station-password-pepper-v1"
_ENC_PREFIX = "enc:v1:"

# Cache key is either the id() of the current Flask app instance, or this
# sentinel when there is none -- see _fernet()/_root_secret().
_NO_APP_CONTEXT = object()

_fernet_cache: tuple | None = None  # (cache_key, Fernet) -- see _fernet()


def _root_secret() -> bytes:
    # Every process that touches an EncryptedString column isn't a Flask
    # request handler -- the standalone CAP poller, the heartbeat worker,
    # and other background services read these columns via a raw
    # sessionmaker() session with no app context pushed at all. Flask
    # itself only ever gets SECRET_KEY from the environment in this app's
    # setup, so falling back to the same environment variable outside a
    # request/app context derives the identical key those processes would
    # get if they *did* have a Flask app pushed -- not a weaker fallback.
    if has_app_context():
        key = current_app.secret_key
    else:
        key = os.environ.get('SECRET_KEY')
    if not key:
        raise RuntimeError(
            "SECRET_KEY is not configured; cannot derive encryption/pepper keys."
        )
    return key.encode("utf-8") if isinstance(key, str) else key


def _derive_key(info: bytes, length: int = 32) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=info)
    return hkdf.derive(_root_secret())


def _fernet() -> Fernet:
    global _fernet_cache
    # Cache per Flask app instance so tests spinning up multiple apps with
    # different SECRET_KEYs in the same process don't share a stale key.
    # Outside an app context (see _root_secret()) there's no app instance
    # to key the cache on, so a single shared entry is used instead --
    # correct as long as SECRET_KEY doesn't change mid-process, which it
    # never does for a long-running service reading its own environment.
    cache_key = id(current_app._get_current_object()) if has_app_context() else _NO_APP_CONTEXT
    if _fernet_cache is None or _fernet_cache[0] != cache_key:
        derived = _derive_key(_ENCRYPTION_INFO)
        _fernet_cache = (cache_key, Fernet(base64.urlsafe_b64encode(derived)))
    return _fernet_cache[1]


def encrypt_secret(plaintext: str | None) -> str | None:
    """Encrypt a value for storage. None/empty pass through unchanged."""
    if not plaintext:
        return plaintext
    token = _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_secret(value: str | None) -> str | None:
    """Decrypt a stored value. Tolerates legacy plaintext rows written
    before this feature existed -- anything without the version prefix is
    returned as-is rather than treated as an error, and gets encrypted
    automatically the next time it's saved.
    """
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        return value
    token = value[len(_ENC_PREFIX):]
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "Failed to decrypt a stored secret (SECRET_KEY may have changed "
            "since it was saved). Re-enter this value."
        )
        return ""


class EncryptedString(TypeDecorator):
    """Text column that's transparently encrypted at rest.

    Backed by Text (not a fixed-length String) because Fernet ciphertext
    plus the version prefix runs noticeably longer than the plaintext it
    replaces -- a fixed VARCHAR sized for the old plaintext would truncate.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        return decrypt_secret(value)


_PEPPER_ITERATIONS = 100_000


def pepper_password(password: str) -> str:
    """Mix a password with the server-side pepper before hashing/checking it.

    The pepper is a secret independent of anything stored in the database
    (unlike the per-hash salt scrypt already applies), so a stolen database
    dump alone -- without SECRET_KEY -- isn't enough to brute-force offline.

    PBKDF2-HMAC-SHA256 rather than a plain HMAC round: this is only an
    *intermediate* value (the real, final password hash is
    werkzeug_generate_password_hash()'s scrypt, applied to this value's
    output in AdminUser.set_password()), so a single HMAC round would
    already be cryptographically sound here -- but real iterations make
    this step itself computationally expensive too, which is strictly more
    hardening for negligible cost at login-time scale, and keeps this
    function in the same "deliberately slow" category as the hash it feeds.
    """
    key = _derive_key(_PEPPER_INFO)
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), key, _PEPPER_ITERATIONS).hex()


# Every (table, column) EncryptedString applies to. Kept as a single list so
# the backfill below and its test coverage can't silently drift from the
# actual set of encrypted columns.
ENCRYPTED_COLUMNS = [
    ("icecast_settings", "source_password"),
    ("icecast_settings", "admin_password"),
    ("tts_settings", "azure_openai_key"),
    ("notification_settings", "smtp_password"),
    ("notification_settings", "sms_auth_token"),
    ("notification_settings", "snmp_community"),
    ("tailscale_settings", "auth_key"),
    ("tickstem_settings", "api_key"),
    ("admin_users", "mfa_secret"),
    ("map_tile_settings", "carto_api_key"),
]


def backfill_legacy_plaintext_secrets(db_session) -> int:
    """Encrypt any row still holding a pre-EncryptedString plaintext value.

    EncryptedString only encrypts on *write* -- a value written before this
    column type existed sits in the database as plaintext until something
    saves that row again. This makes that happen once, at startup, for every
    row still in that state, by reading the column with a raw SQL SELECT
    (bypassing the ORM's automatic decryption, so a plaintext value doesn't
    look identical to an already-decrypted one) and writing back through
    encrypt_secret() wherever the stored value isn't already ciphertext.

    Idempotent and cheap to call on every startup: rows already encrypted
    (the common case after the first run) are skipped via the "enc:v1:"
    prefix check, at the cost of one SELECT per column.

    Returns the number of rows encrypted.
    """
    from sqlalchemy import text
    from sqlalchemy import inspect as sa_inspect

    encrypted_count = 0
    inspector = sa_inspect(db_session.get_bind())
    existing_tables = set(inspector.get_table_names())

    for table, column in ENCRYPTED_COLUMNS:
        if table not in existing_tables:
            continue
        rows = db_session.execute(
            text(f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL AND {column} != ''")
        ).fetchall()
        for row_id, raw_value in rows:
            if raw_value.startswith(_ENC_PREFIX):
                continue
            db_session.execute(
                text(f"UPDATE {table} SET {column} = :new_value WHERE id = :row_id"),
                {"new_value": encrypt_secret(raw_value), "row_id": row_id},
            )
            encrypted_count += 1

    if encrypted_count:
        db_session.commit()
        logger.info(
            "Encrypted %d previously-plaintext secret column value(s) at rest.",
            encrypted_count,
        )
    return encrypted_count
