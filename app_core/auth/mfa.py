"""
Multi-Factor Authentication (MFA) implementation using TOTP.

Provides:
- TOTP secret generation and verification
- QR code generation for authenticator apps
- Backup code management
- MFA enrollment and validation
"""

import secrets
import hashlib
import json
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from io import BytesIO

try:
    import pyotp
    import qrcode
    TOTP_AVAILABLE = True
except ImportError:
    TOTP_AVAILABLE = False

from werkzeug.security import generate_password_hash, check_password_hash
from flask import current_app

from app_core.db import db
from app_utils.timestamp import utc_now


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
    def verify_totp(secret: str, code: str, window: int = 1) -> bool:
        """
        Verify a TOTP code.

        Args:
            secret: TOTP secret key
            code: User-provided 6-digit code
            window: Number of time windows to check (for clock skew)

        Returns:
            True if code is valid, False otherwise
        """
        if not TOTP_AVAILABLE:
            raise ImportError("pyotp is required for MFA functionality")

        totp = pyotp.TOTP(secret)
        return totp.verify(code, valid_window=window)

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
    if not verify_totp_code(user.mfa_secret, verify_code):
        current_app.logger.warning(f"MFA enrollment failed for user {user.username}: invalid code")
        return False, None

    # Generate backup codes
    backup_codes = MFAManager.generate_backup_codes()
    user.mfa_backup_codes_hash = MFAManager.hash_backup_codes(backup_codes)
    user.mfa_enabled = True
    user.mfa_enrolled_at = utc_now()

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
    if verify_totp_code(user.mfa_secret, code):
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
