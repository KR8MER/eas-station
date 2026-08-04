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
Multi-Factor Authentication (MFA) implementation using TOTP.

Provides:
- TOTP secret generation and verification
- QR code generation for authenticator apps
- Backup code management
- MFA enrollment and validation
"""

import hmac
import secrets
import hashlib
import json
import time
from typing import List, Optional, Tuple
from datetime import datetime, timedelta, timezone
from io import BytesIO

try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False

from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app

from app_core.extensions import db
from app_utils import utc_now

#: Length of one TOTP time step, in seconds (RFC 6238 default, and what every
#: authenticator app uses).
TOTP_INTERVAL_SECONDS = 30

#: How many time steps either side of "now" are accepted, to tolerate clock
#: skew between the server and the authenticator app.  ``1`` means the previous,
#: current, and next codes are all accepted — a 90-second acceptance span.
TOTP_VALID_WINDOW = 1


class MFAManager:
    """Manager for MFA operations."""

    @staticmethod
    def generate_secret() -> str:
        """
        Generate a new TOTP secret key.

        Returns:
            Base32-encoded secret string
        """
        if not TOTP_AVAILABLE:
            raise ImportError("pyotp is required for MFA functionality")
        return pyotp.random_base32()

    @staticmethod
    def generate_backup_codes(count: int = 10) -> List[str]:
        """
        Generate backup codes for account recovery.

        Args:
            count: Number of backup codes to generate

        Returns:
            List of backup code strings
        """
        codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric codes
            code = secrets.token_hex(4).upper()
            codes.append(code)
        return codes

    @staticmethod
    def hash_backup_codes(codes: List[str]) -> str:
        """
        Hash backup codes for secure storage.

        Args:
            codes: List of plaintext backup codes

        Returns:
            JSON string of hashed codes
        """
        hashed = [generate_password_hash(code) for code in codes]
        return json.dumps(hashed)

    @staticmethod
    def verify_backup_code(code: str, hashed_codes_json: str) -> Tuple[bool, Optional[str]]:
        """
        Verify a backup code and remove it if valid.

        Args:
            code: Plaintext backup code to verify
            hashed_codes_json: JSON string of hashed codes

        Returns:
            Tuple of (is_valid, updated_hashed_codes_json)
        """
        try:
            hashed_codes = json.loads(hashed_codes_json)
        except (json.JSONDecodeError, TypeError):
            return False, None

        for i, hashed_code in enumerate(hashed_codes):
            if check_password_hash(hashed_code, code):
                # Remove used code
                hashed_codes.pop(i)
                return True, json.dumps(hashed_codes)

        return False, None

    @staticmethod
    def generate_provisioning_uri(secret: str, username: str, issuer: str = "EAS Station") -> str:
        """
        Generate TOTP provisioning URI for QR code.

        Args:
            secret: TOTP secret key
            username: User's username
            issuer: Application name

        Returns:
            Provisioning URI string
        """
        if not TOTP_AVAILABLE:
            raise ImportError("pyotp is required for MFA functionality")

        totp = pyotp.TOTP(secret)
        return totp.provisioning_uri(name=username, issuer_name=issuer)

    @staticmethod
    def generate_qr_code(provisioning_uri: str) -> bytes:
        """
        Generate QR code image from provisioning URI.

        Args:
            provisioning_uri: TOTP provisioning URI

        Returns:
            PNG image bytes
        """
        if not TOTP_AVAILABLE:
            raise ImportError("qrcode is required for MFA functionality")

        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(provisioning_uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format='PNG')
        return buffer.getvalue()

    @staticmethod
    def verify_totp(secret: str, code: str, window: int = TOTP_VALID_WINDOW) -> bool:
        """
        Verify a TOTP code.

        Args:
            secret: TOTP secret key
            code: User-provided 6-digit code
            window: Number of time windows to check (for clock skew)

        Returns:
            True if code is valid, False otherwise
        """
        return MFAManager.verify_totp_with_counter(secret, code, window)[0]

    @staticmethod
    def verify_totp_with_counter(
        secret: str, code: str, window: int = TOTP_VALID_WINDOW
    ) -> Tuple[bool, Optional[int]]:
        """
        Verify a TOTP code and report *which* time step it belongs to.

        ``pyotp.TOTP.verify()`` only answers "is this code currently valid?",
        which is not enough to tell a replay of an already-used code from a
        genuinely new code generated one time step later.  Both look identical
        to a wall-clock "was the last successful login recent?" check, so such a
        check locks legitimate users out for a minute and a half after every
        login.  Returning the matched time-step counter lets the caller reject
        only true replays.

        Args:
            secret: TOTP secret key
            code: User-provided 6-digit code
            window: Number of time steps to check either side of now (clock skew)

        Returns:
            Tuple of ``(is_valid, counter)``.  ``counter`` is the RFC 6238 time
            step the code was generated for, or ``None`` when the code is
            invalid.  Counters increase monotonically with time, so a code is a
            replay exactly when its counter is not greater than the last one
            this user consumed.
        """
        if not TOTP_AVAILABLE:
            raise ImportError("pyotp is required for MFA functionality")

        # Authenticator apps display codes in groups ("123 456"); operators
        # paste them that way, and a stray space must not fail an otherwise
        # correct code.
        submitted = ''.join((code or '').split())
        if not submitted or not secret:
            return False, None

        totp = pyotp.TOTP(secret)
        interval = int(getattr(totp, 'interval', TOTP_INTERVAL_SECONDS) or TOTP_INTERVAL_SECONDS)
        now_ts = int(time.time())
        current_counter = now_ts // interval

        for offset in range(-abs(window), abs(window) + 1):
            try:
                candidate = totp.at(now_ts, offset)
            except Exception:  # pragma: no cover - pyotp input guard
                continue
            # Constant-time compare so a wrong code leaks no timing signal.
            if hmac.compare_digest(str(candidate), submitted):
                return True, current_counter + offset

        return False, None

    @staticmethod
    def get_current_totp(secret: str) -> str:
        """
        Get current TOTP code (for testing/debugging only).

        Args:
            secret: TOTP secret key

        Returns:
            Current 6-digit TOTP code
        """
        if not TOTP_AVAILABLE:
            raise ImportError("pyotp is required for MFA functionality")

        totp = pyotp.TOTP(secret)
        return totp.now()


# Convenience functions
def generate_totp_secret() -> str:
    """Generate a new TOTP secret."""
    return MFAManager.generate_secret()


def verify_totp_code(secret: str, code: str) -> bool:
    """Verify a TOTP code."""
    return MFAManager.verify_totp(secret, code)


def verify_totp_code_with_counter(secret: str, code: str) -> Tuple[bool, Optional[int]]:
    """Verify a TOTP code and return the time step it was generated for."""
    return MFAManager.verify_totp_with_counter(secret, code)


def _consumed_totp_counter(user) -> Optional[int]:
    """Return the last TOTP time step this user has already spent, if any.

    Prefers the exact counter recorded by :func:`verify_user_mfa`.  Rows written
    before that column existed only carry ``mfa_last_totp_at`` (the wall-clock
    time of the last successful verification), so derive the counter from it —
    that still blocks a replay inside the same time step while letting the next
    code through immediately.

    Deriving from the timestamp is one step coarser than the recorded counter:
    a code accepted from the *next* step (the +1 clock-skew slot) lands in a
    later bucket than the login that spent it, so on such a row that one code
    could be replayed until the step rolls over.  The window is at most 30
    seconds and closes permanently at the next successful verification, which
    writes the exact counter.
    """
    counter = getattr(user, 'mfa_last_totp_counter', None)
    if counter is not None:
        try:
            return int(counter)
        except (TypeError, ValueError):
            return None

    last_at = getattr(user, 'mfa_last_totp_at', None)
    if not last_at:
        return None
    try:
        if last_at.tzinfo is None:
            last_at = last_at.replace(tzinfo=timezone.utc)
        return int(last_at.timestamp()) // TOTP_INTERVAL_SECONDS
    except (AttributeError, TypeError, ValueError, OSError):
        return None


def _record_spent_totp(user, counter: Optional[int]) -> None:
    """Persist the time step a successful verification just consumed.

    Falls back to writing only ``mfa_last_totp_at`` when the counter column is
    not present in the database.  ``update.sh`` runs ``alembic upgrade head``
    before restarting services, but the documented bare ``git pull`` + restart
    flow does not — and without this fallback that combination would make every
    MFA login fail on the commit rather than merely lose counter precision.
    Replay protection still holds in that state via the timestamp-derived
    counter in :func:`_consumed_totp_counter`.
    """
    now = utc_now()
    user.mfa_last_totp_at = now
    user.mfa_last_totp_counter = counter
    try:
        db.session.commit()
        return
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(
            "Could not record TOTP counter for user %s (%s); "
            "run 'alembic upgrade head' to add admin_users.mfa_last_totp_counter",
            getattr(user, 'username', '?'),
            exc,
        )

    # Second attempt without the new column so the login still completes.
    try:
        user.mfa_last_totp_at = now
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        current_app.logger.error(
            "Could not record TOTP usage for user %s: %s",
            getattr(user, 'username', '?'),
            exc,
        )


def enroll_user_mfa(user, verify_code: str) -> Tuple[bool, Optional[List[str]]]:
    """
    Enroll a user in MFA after verification.

    Args:
        user: AdminUser instance
        verify_code: Initial TOTP code to verify setup

    Returns:
        Tuple of (success, backup_codes)
    """
    if not hasattr(user, 'mfa_secret') or not user.mfa_secret:
        current_app.logger.error("User has no MFA secret to enroll")
        return False, None

    # Verify the code
    is_valid, counter = verify_totp_code_with_counter(user.mfa_secret, verify_code)
    if not is_valid:
        current_app.logger.warning(f"MFA enrollment failed for user {user.username}: invalid code")
        return False, None

    # Generate backup codes
    backup_codes = MFAManager.generate_backup_codes()
    user.mfa_backup_codes_hash = MFAManager.hash_backup_codes(backup_codes)
    user.mfa_enabled = True
    now = utc_now()
    user.mfa_enrolled_at = now
    # Spend the enrollment code so it can't be replayed at the login screen,
    # while the *next* code the app shows still works right away.
    user.mfa_last_totp_at = now
    user.mfa_last_totp_counter = counter

    db.session.commit()
    current_app.logger.info(f"MFA enrolled for user {user.username}")

    return True, backup_codes


def disable_user_mfa(user):
    """
    Disable MFA for a user.

    Args:
        user: AdminUser instance
    """
    user.mfa_enabled = False
    user.mfa_secret = None
    user.mfa_backup_codes_hash = None
    user.mfa_enrolled_at = None
    user.mfa_last_totp_at = None
    user.mfa_last_totp_counter = None

    db.session.commit()
    current_app.logger.info(f"MFA disabled for user {user.username}")


def verify_user_mfa(user, code: str) -> bool:
    """
    Verify MFA code for a user (TOTP or backup code).

    Args:
        user: AdminUser instance
        code: TOTP code or backup code

    Returns:
        True if valid, False otherwise
    """
    if not user.mfa_enabled or not user.mfa_secret:
        return False

    # Try TOTP first
    is_valid, counter = verify_totp_code_with_counter(user.mfa_secret, code)
    if is_valid:
        # Reject replays only.  Each TOTP code belongs to exactly one 30-second
        # time step, and counters increase with time, so "already spent" means
        # "counter <= the last one we accepted".  Comparing wall-clock elapsed
        # time instead (the previous implementation blocked every code for 90 s
        # after a successful login) rejected perfectly good *new* codes and
        # forced operators to sit through several code rotations before they
        # could log in again.
        last_counter = _consumed_totp_counter(user)
        if last_counter is not None and counter is not None and counter <= last_counter:
            current_app.logger.warning(
                f"TOTP code reuse attempt for user {user.username} "
                f"(time step {counter} was already used)"
            )
            return False

        # Valid, previously unused code - spend this time step.
        _record_spent_totp(user, counter)
        return True

    # Try backup code
    if user.mfa_backup_codes_hash:
        is_valid, updated_codes = MFAManager.verify_backup_code(code, user.mfa_backup_codes_hash)
        if is_valid:
            user.mfa_backup_codes_hash = updated_codes
            db.session.commit()
            current_app.logger.info(f"Backup code used for user {user.username}")
            return True

    return False


class MFASession:
    """Helper to manage MFA partial authentication in session."""

    SESSION_KEY = 'mfa_pending_user_id'
    SESSION_TIMEOUT_KEY = 'mfa_pending_timeout'
    TIMEOUT_MINUTES = 5

    @classmethod
    def set_pending(cls, session_obj, user_id: int):
        """Mark user as pending MFA verification in session."""
        session_obj[cls.SESSION_KEY] = user_id
        timeout = datetime.utcnow() + timedelta(minutes=cls.TIMEOUT_MINUTES)
        session_obj[cls.SESSION_TIMEOUT_KEY] = timeout.isoformat()

    @classmethod
    def get_pending(cls, session_obj) -> Optional[int]:
        """Get pending MFA user ID if not timed out."""
        user_id = session_obj.get(cls.SESSION_KEY)
        timeout_str = session_obj.get(cls.SESSION_TIMEOUT_KEY)

        if not user_id or not timeout_str:
            return None

        try:
            timeout = datetime.fromisoformat(timeout_str)
            if datetime.utcnow() > timeout:
                cls.clear_pending(session_obj)
                return None
        except ValueError:
            cls.clear_pending(session_obj)
            return None

        return user_id

    @classmethod
    def clear_pending(cls, session_obj):
        """Clear pending MFA state from session."""
        session_obj.pop(cls.SESSION_KEY, None)
        session_obj.pop(cls.SESSION_TIMEOUT_KEY, None)

    @classmethod
    def complete(cls, session_obj, user_id: int):
        """Complete MFA verification and establish full session."""
        cls.clear_pending(session_obj)
        session_obj['user_id'] = user_id
        session_obj.permanent = True
