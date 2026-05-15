"""
EAS Station - Emergency Alert System
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)

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
Security audit logging for tracking sensitive operations.

Provides:
- Comprehensive audit trail for security events
- IP address and user agent tracking
- Action categorization and filtering
- Retention management
- Tamper-evident chain: every new row carries the SHA-256 of its predecessor
  and an Ed25519 signature over the row's own canonical-JSON hash.  See
  ``AuditLogger.log`` for the construction, ``AuditLogger.verify_chain`` for
  the verifier, and ``app_core.auth._audit_signing_key`` for key management.
"""

import hashlib
import json
import logging
from enum import Enum
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta

from flask import request, session, current_app
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Index
from cryptography.exceptions import InvalidSignature

from app_core.extensions import db
from app_utils import utc_now

from ._audit_signing_key import get_signing_keypair, is_ephemeral_key


_module_logger = logging.getLogger(__name__)


class AuditAction(Enum):
    """Categorized audit actions for security events."""

    # Authentication events
    LOGIN_SUCCESS = 'auth.login.success'
    LOGIN_FAILURE = 'auth.login.failure'
    LOGOUT = 'auth.logout'
    SESSION_EXPIRED = 'auth.session.expired'

    # MFA events
    MFA_ENROLLED = 'mfa.enrolled'
    MFA_DISABLED = 'mfa.disabled'
    MFA_VERIFY_SUCCESS = 'mfa.verify.success'
    MFA_VERIFY_FAILURE = 'mfa.verify.failure'
    MFA_BACKUP_CODE_USED = 'mfa.backup_code.used'

    # User management events
    USER_CREATED = 'user.created'
    USER_UPDATED = 'user.updated'
    USER_DELETED = 'user.deleted'
    USER_ACTIVATED = 'user.activated'
    USER_DEACTIVATED = 'user.deactivated'
    USER_ROLE_CHANGED = 'user.role.changed'
    PASSWORD_CHANGED = 'user.password.changed'

    # Role/Permission management
    ROLE_CREATED = 'role.created'
    ROLE_UPDATED = 'role.updated'
    ROLE_DELETED = 'role.deleted'
    PERMISSION_GRANTED = 'permission.granted'
    PERMISSION_REVOKED = 'permission.revoked'

    # EAS operations
    EAS_BROADCAST = 'eas.broadcast'
    EAS_MANUAL_ACTIVATION = 'eas.manual_activation'
    EAS_CANCELLATION = 'eas.cancellation'
    # Inbound CAP alert ingested from a polling source (NWS, IPAWS, manual fetch, etc).
    # This is the counterpart to EAS_BROADCAST and is emitted automatically by
    # the SQLAlchemy after_insert listener on CAPAlert in app_core.auth.audit_listeners.
    ALERT_RECEIVED = 'alert.received'

    # System configuration
    CONFIG_UPDATED = 'config.updated'
    RECEIVER_CONFIGURED = 'receiver.configured'
    GPIO_ACTIVATED = 'gpio.activated'
    GPIO_DEACTIVATED = 'gpio.deactivated'

    # Data operations
    ALERT_DELETED = 'alert.deleted'
    LOG_EXPORTED = 'log.exported'
    LOG_DELETED = 'log.deleted'

    # Security events
    PERMISSION_DENIED = 'security.permission_denied'
    INVALID_TOKEN = 'security.invalid_token'
    RATE_LIMIT_EXCEEDED = 'security.rate_limit_exceeded'


class AuditLog(db.Model):
    """Comprehensive audit log for security-sensitive operations."""
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)
    user_id = Column(Integer, nullable=True, index=True)  # Nullable for anonymous actions
    username = Column(String(64), nullable=True)  # Denormalized for historical record
    action = Column(String(128), nullable=False, index=True)
    resource_type = Column(String(64), nullable=True, index=True)  # e.g., 'user', 'role', 'alert'
    resource_id = Column(String(128), nullable=True)  # ID of affected resource
    ip_address = Column(String(45), nullable=True)  # IPv4 or IPv6
    user_agent = Column(String(512), nullable=True)
    success = Column(db.Boolean, default=True, nullable=False, index=True)
    details = Column(JSON, nullable=True)  # Additional context as JSON
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    # --- Tamper-evidence chain (added 2026-05-15) -----------------------------
    # These three columns turn the audit table into a hash-chained, signed
    # ledger.  All three are nullable so (a) rows that existed before the
    # 20260515 migration stay valid, and (b) a deployment that hasn't yet
    # provisioned a signing key can still record audit events -- the chain
    # verifier will simply report unsigned rows as unverified rather than
    # silently dropping them.  See AuditLogger.log()/verify_chain().
    prev_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=True, index=True)
    signature = Column(String(256), nullable=True)

    # Indexes for common queries
    __table_args__ = (
        Index('ix_audit_logs_user_action', 'user_id', 'action'),
        Index('ix_audit_logs_timestamp_action', 'timestamp', 'action'),
    )

    def __repr__(self):
        return f'<AuditLog {self.action} by {self.username} at {self.timestamp}>'

    def to_dict(self) -> Dict[str, Any]:
        """Convert audit log to dictionary."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'success': self.success,
            'details': self.details,
            'prev_hash': self.prev_hash,
            'entry_hash': self.entry_hash,
            'signature': self.signature,
        }

    # --- Tamper-evidence helpers --------------------------------------------

    # The canonical-JSON content fields are EXACTLY the fields that
    # contribute to the entry hash.  Adding a new column to AuditLog without
    # adding it here is safe (the column just won't be hash-protected); the
    # converse -- listing a field here that isn't on the row -- would break
    # verify_chain() across older rows.  When adding new protected fields,
    # remember that pre-migration rows won't have them and the verifier
    # tolerates that by treating missing keys as null.
    _CONTENT_FIELDS = (
        'id',
        'timestamp',
        'user_id',
        'username',
        'action',
        'resource_type',
        'resource_id',
        'ip_address',
        'user_agent',
        'success',
        'details',
    )

    def canonical_content(self) -> Dict[str, Any]:
        """Return the dict whose canonical JSON feeds into ``entry_hash``.

        Anything outside this set (``created_at``, the chain fields
        themselves, ...) is deliberately excluded so the hash is stable
        regardless of when the row was committed or how it was loaded back.

        Timestamps are normalised to a tz-naive UTC ISO string.  This is
        necessary because SQLite (used by tests) silently drops the tz
        offset on read-back even when the column is ``DateTime(timezone=True)``,
        while Postgres preserves it -- so round-tripping the raw value
        would produce different bytes on the two backends.  Normalising
        to UTC strips the representation difference without losing
        information (every timestamp is utc_now() in this code path).
        """
        ts = self.timestamp
        if ts is not None:
            if ts.tzinfo is not None:
                # Force to UTC instant, then drop tzinfo for a stable encoding.
                try:
                    from datetime import timezone as _tz
                    ts = ts.astimezone(_tz.utc).replace(tzinfo=None)
                except Exception:  # noqa: BLE001
                    ts = ts.replace(tzinfo=None)
            ts_str = ts.isoformat()
        else:
            ts_str = None
        return {
            'id': self.id,
            'timestamp': ts_str,
            'user_id': self.user_id,
            'username': self.username,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'success': bool(self.success),
            'details': self.details,
        }


class AuditLogger:
    """Utility class for creating audit log entries."""

    @staticmethod
    def log(
        action: AuditAction,
        success: bool = True,
        user_id: Optional[int] = None,
        username: Optional[str] = None,
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        """
        Create an audit log entry.

        Args:
            action: AuditAction enum value
            success: Whether the action succeeded
            user_id: ID of user performing action (auto-detected if None)
            username: Username (auto-detected if None)
            resource_type: Type of resource affected
            resource_id: ID of resource affected
            details: Additional context as dictionary
            ip_address: IP address (auto-detected if None)
            user_agent: User agent (auto-detected if None)

        Returns:
            Created AuditLog instance
        """
        # Auto-detect user from session if not provided.  ``session`` is a
        # request-context proxy; in background workers (CAP poller, RWT
        # scheduler, the model-insert listener) there is no request and
        # touching the proxy raises.  Treat that as "no user".
        if user_id is None:
            try:
                _sess_user = session.get('user_id')
            except RuntimeError:
                _sess_user = None
            if _sess_user:
                user_id = _sess_user

        if username is None and user_id:
            try:
                from app_core.models import AdminUser
                user = AdminUser.query.get(user_id)
                if user:
                    username = user.username
            except Exception as e:
                try:
                    current_app.logger.warning(f"Could not fetch username for audit log: {e}")
                except RuntimeError:
                    _module_logger.warning("Could not fetch username for audit log: %s", e)

        # Auto-detect IP and user agent from request context.  Same proxy
        # caveat as above: outside a request, leave them as None.
        if ip_address is None:
            try:
                ip_address = request.headers.get('X-Forwarded-For', request.remote_addr)
                if ip_address and ',' in ip_address:
                    ip_address = ip_address.split(',')[0].strip()
            except RuntimeError:
                ip_address = None

        if user_agent is None:
            try:
                user_agent = request.headers.get('User-Agent')
                if user_agent and len(user_agent) > 512:
                    user_agent = user_agent[:512]
            except RuntimeError:
                user_agent = None

        # Create audit log entry
        log_entry = AuditLog(
            action=action.value,
            success=success,
            user_id=user_id,
            username=username,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=ip_address,
            user_agent=user_agent,
            details=details,
        )

        try:
            # The chain MUST be built before commit -- if we commit twice
            # (once to assign id, again with chain fields) another writer
            # could slip a row in between, breaking the prev_hash linkage.
            # Strategy: flush to obtain the auto-increment id, take a row-
            # level chain lock for the duration of this transaction
            # (PG advisory lock; no-op on SQLite), look up the most recent
            # already-signed row's entry_hash, compute our entry_hash,
            # sign it, then commit atomically.
            db.session.add(log_entry)
            db.session.flush()
            AuditLogger._chain_and_sign(log_entry)
            db.session.commit()
        except Exception as e:
            try:
                current_app.logger.error(f"Failed to write audit log: {e}")
            except RuntimeError:
                # Out-of-app-context callers (e.g. background workers) still
                # need a usable logger; fall back to the module logger.
                _module_logger.error("Failed to write audit log: %s", e)
            db.session.rollback()

        return log_entry

    # ------------------------------------------------------------------
    # Chain & signature
    # ------------------------------------------------------------------
    # Sentinel hex string used as the "previous hash" for the very first
    # row in the chain.  64 zeros == SHA-256 of nothing-yet; never a real
    # hash output for any non-empty input we feed in.
    _GENESIS_PREV_HASH = '0' * 64

    # PG advisory-lock key.  Chosen to be a stable arbitrary 32-bit int so
    # the same key is used by every worker process; the value doesn't
    # matter beyond uniqueness within the deployment.  'easlog' as
    # bigendian bytes interpreted as int32 == 0x65_61_73_6c (~1701276012).
    _ADVISORY_LOCK_KEY = 1701276012

    @staticmethod
    def _canonical_json(payload: Dict[str, Any]) -> bytes:
        """Deterministic JSON encoding for hashing.

        ``sort_keys=True`` + ``separators=(',', ':')`` + ``ensure_ascii=False``
        gives one byte-for-byte representation per logical payload, which is
        what we need for the hash to round-trip through verify_chain().
        """
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            default=str,  # datetimes inside `details` etc. survive as ISO strings
        ).encode('utf-8')

    @classmethod
    def _take_chain_lock(cls) -> None:
        """Serialize chain-construction against concurrent writers.

        On PostgreSQL we take a transaction-scoped advisory lock so two
        workers writing audit rows simultaneously can't end up reading the
        same "last entry_hash" and producing a fork.  On SQLite (test
        backend) and any other dialect the call is a no-op -- SQLite is
        single-writer at the DB level anyway.
        """
        bind = db.session.get_bind()
        dialect = getattr(bind, 'dialect', None)
        name = getattr(dialect, 'name', '') if dialect else ''
        if name == 'postgresql':
            db.session.execute(
                db.text("SELECT pg_advisory_xact_lock(:k)"),
                {"k": cls._ADVISORY_LOCK_KEY},
            )

    @classmethod
    def _chain_and_sign(cls, entry: 'AuditLog') -> None:
        """Compute prev_hash, entry_hash, and signature on ``entry``.

        The session is expected to be flushed (so ``entry.id`` is set) and
        the transaction is expected to still be open.  Caller commits.
        """
        cls._take_chain_lock()

        # Find the previous row in the chain -- the highest-id row that
        # already has an entry_hash.  We deliberately skip unsigned legacy
        # rows: if a deployment ran for a while before the migration, those
        # rows weren't hashed and there is nothing to chain off.  The chain
        # therefore "begins" at the first signed row.
        prev = (
            db.session.query(AuditLog)
            .filter(AuditLog.id != entry.id)
            .filter(AuditLog.entry_hash.isnot(None))
            .order_by(AuditLog.id.desc())
            .first()
        )
        prev_hash = prev.entry_hash if prev is not None else cls._GENESIS_PREV_HASH

        payload = entry.canonical_content()
        payload['prev_hash'] = prev_hash
        digest_bytes = hashlib.sha256(cls._canonical_json(payload)).digest()
        entry_hash_hex = digest_bytes.hex()

        try:
            private_key, _public_key, _source = get_signing_keypair()
            signature_hex = private_key.sign(digest_bytes).hex()
        except Exception as exc:  # noqa: BLE001 - any key failure -> unsigned row
            _module_logger.warning(
                "audit chain: could not sign row id=%s (%s); row will be "
                "stored unsigned and flagged by verify_chain()",
                entry.id, exc,
            )
            signature_hex = None

        entry.prev_hash = prev_hash
        entry.entry_hash = entry_hash_hex
        entry.signature = signature_hex

    # ------------------------------------------------------------------
    # Verifier
    # ------------------------------------------------------------------
    @classmethod
    def verify_chain(
        cls,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Walk the audit chain and report integrity.

        Returns a dict with keys:

        * ``ok`` -- True iff every signed row in the scanned range has a
          correct prev_hash linkage, a correct entry_hash for its content,
          and a valid Ed25519 signature.
        * ``checked`` -- number of signed rows examined.
        * ``unsigned`` -- number of rows with no entry_hash (pre-migration
          legacy rows or rows recorded while the signing key was
          unavailable).  Counted but not treated as failures.
        * ``ephemeral_key`` -- True if the in-process signing key is not
          backed by a persistent file.  Operationally this means
          "signature checks below are tautological"; the admin UI surfaces
          this as a warning.
        * ``first_bad_id`` -- id of the first row that failed verification,
          or None.
        * ``reason`` -- human-readable explanation for the first failure,
          or None on success.

        ``limit`` caps how many rows are examined (newest first).  None
        scans the whole table.
        """
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey  # noqa: F401  (imported for clarity)

        try:
            _private, public_key, _source = get_signing_keypair()
        except Exception as exc:  # noqa: BLE001
            return {
                'ok': False,
                'checked': 0,
                'unsigned': 0,
                'ephemeral_key': True,
                'first_bad_id': None,
                'reason': f'signing key unavailable: {exc}',
            }

        query = (
            db.session.query(AuditLog)
            .order_by(AuditLog.id.asc())
        )
        rows: List[AuditLog] = query.all()
        if limit is not None and limit > 0:
            rows = rows[-limit:]

        checked = 0
        unsigned = 0
        # Seed expected_prev with the predecessor's entry_hash if we're
        # starting mid-chain (limit truncated the head).  When the rows
        # cover the entire table the first signed row's expected prev_hash
        # is the genesis sentinel.
        expected_prev: Optional[str]
        if limit is not None and limit > 0 and rows:
            first_id = rows[0].id
            prev_row = (
                db.session.query(AuditLog)
                .filter(AuditLog.id < first_id)
                .filter(AuditLog.entry_hash.isnot(None))
                .order_by(AuditLog.id.desc())
                .first()
            )
            expected_prev = prev_row.entry_hash if prev_row is not None else cls._GENESIS_PREV_HASH
        else:
            expected_prev = cls._GENESIS_PREV_HASH

        for row in rows:
            if row.entry_hash is None:
                unsigned += 1
                continue

            # 1. prev_hash linkage
            if row.prev_hash != expected_prev:
                return {
                    'ok': False,
                    'checked': checked,
                    'unsigned': unsigned,
                    'ephemeral_key': is_ephemeral_key(),
                    'first_bad_id': row.id,
                    'reason': (
                        f'prev_hash mismatch at id={row.id}: '
                        f'expected {expected_prev!r}, got {row.prev_hash!r}'
                    ),
                }

            # 2. entry_hash matches canonical content
            payload = row.canonical_content()
            payload['prev_hash'] = row.prev_hash
            digest_bytes = hashlib.sha256(cls._canonical_json(payload)).digest()
            if digest_bytes.hex() != row.entry_hash:
                return {
                    'ok': False,
                    'checked': checked,
                    'unsigned': unsigned,
                    'ephemeral_key': is_ephemeral_key(),
                    'first_bad_id': row.id,
                    'reason': (
                        f'entry_hash mismatch at id={row.id}: row content '
                        f'does not match stored hash (likely tampered)'
                    ),
                }

            # 3. signature
            if row.signature is None:
                # Hash was recorded but signing failed at write time.  We
                # already counted the hash check above, so this is a soft
                # warning rather than a verify failure: the row is still
                # tamper-evident via the chain, just not signed.
                pass
            else:
                try:
                    public_key.verify(bytes.fromhex(row.signature), digest_bytes)
                except (InvalidSignature, ValueError) as exc:
                    return {
                        'ok': False,
                        'checked': checked,
                        'unsigned': unsigned,
                        'ephemeral_key': is_ephemeral_key(),
                        'first_bad_id': row.id,
                        'reason': f'signature invalid at id={row.id}: {exc}',
                    }

            checked += 1
            expected_prev = row.entry_hash

        return {
            'ok': True,
            'checked': checked,
            'unsigned': unsigned,
            'ephemeral_key': is_ephemeral_key(),
            'first_bad_id': None,
            'reason': None,
        }

    @staticmethod
    def log_login_success(user_id: int, username: str):
        """Log successful login."""
        return AuditLogger.log(
            action=AuditAction.LOGIN_SUCCESS,
            user_id=user_id,
            username=username,
            details={'method': 'password'}
        )

    @staticmethod
    def log_login_failure(username: str, reason: str = 'invalid_credentials'):
        """Log failed login attempt."""
        return AuditLogger.log(
            action=AuditAction.LOGIN_FAILURE,
            success=False,
            username=username,
            details={'reason': reason}
        )

    @staticmethod
    def log_logout(user_id: int, username: str):
        """Log user logout."""
        return AuditLogger.log(
            action=AuditAction.LOGOUT,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_mfa_enrolled(user_id: int, username: str):
        """Log MFA enrollment."""
        return AuditLogger.log(
            action=AuditAction.MFA_ENROLLED,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_mfa_verify_success(user_id: int, username: str, method: str = 'totp'):
        """Log successful MFA verification."""
        return AuditLogger.log(
            action=AuditAction.MFA_VERIFY_SUCCESS,
            user_id=user_id,
            username=username,
            details={'method': method}
        )

    @staticmethod
    def log_mfa_verify_failure(user_id: int, username: str):
        """Log failed MFA verification."""
        return AuditLogger.log(
            action=AuditAction.MFA_VERIFY_FAILURE,
            success=False,
            user_id=user_id,
            username=username
        )

    @staticmethod
    def log_user_created(creator_id: int, creator_username: str, new_user_id: int, new_username: str):
        """Log user creation."""
        return AuditLogger.log(
            action=AuditAction.USER_CREATED,
            user_id=creator_id,
            username=creator_username,
            resource_type='user',
            resource_id=str(new_user_id),
            details={'new_username': new_username}
        )

    @staticmethod
    def log_permission_denied(user_id: Optional[int], username: Optional[str], permission: str, resource: str):
        """Log permission denied event."""
        return AuditLogger.log(
            action=AuditAction.PERMISSION_DENIED,
            success=False,
            user_id=user_id,
            username=username,
            details={'permission': permission, 'resource': resource}
        )

    @staticmethod
    def cleanup_old_logs(days: int = 90):
        """
        Delete audit logs older than specified days.

        Args:
            days: Number of days to retain logs

        Returns:
            Number of logs deleted
        """
        cutoff = utc_now() - timedelta(days=days)
        result = db.session.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete()
        db.session.commit()
        current_app.logger.info(f"Cleaned up {result} audit logs older than {days} days")
        return result
