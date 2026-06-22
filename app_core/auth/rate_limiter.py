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
Rate limiting for authentication to prevent brute force attacks.

Provides in-memory tracking of failed login attempts per IP address
with automatic cleanup of old entries.
"""

from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
import threading


class LoginRateLimiter:
    """Rate limiter for login attempts to prevent brute force attacks."""

    # Configuration
    MAX_ATTEMPTS = 5  # Maximum failed attempts before lockout
    LOCKOUT_DURATION = timedelta(minutes=15)  # How long to lock out after max attempts
    ATTEMPT_WINDOW = timedelta(minutes=5)  # Time window to count attempts
    CLEANUP_INTERVAL = 300  # Cleanup every 5 minutes (in seconds)
    MAX_TRACKED_IPS = 10000  # Maximum IPs to track to prevent memory exhaustion
    UNKNOWN_IP_PLACEHOLDER = "unknown"  # Placeholder for missing IP addresses

    def __init__(self):
        """Initialize the rate limiter with thread-safe storage."""
        self._attempts: Dict[str, List[datetime]] = defaultdict(list)
        self._lockouts: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._cleanup_timer: Optional[threading.Timer] = None
        self._running = False

    def _normalize_ip(self, ip_address: str) -> str:
        """Normalize IP address, using placeholder for missing/invalid IPs.

        This ensures rate limiting still applies even when IP cannot be determined,
        preventing bypass attacks through proxy misconfiguration.
        """
        if not ip_address or not ip_address.strip():
            return self.UNKNOWN_IP_PLACEHOLDER
        return ip_address.strip()

    def record_failed_attempt(self, ip_address: str) -> None:
        """
        Record a failed login attempt for an IP address.

        Args:
            ip_address: The IP address making the attempt
        """
        ip_address = self._normalize_ip(ip_address)
        
        with self._lock:
            now = datetime.utcnow()

            # Memory bounds protection: if we're tracking too many IPs,
            # clean up aggressively before adding more
            if len(self._attempts) >= self.MAX_TRACKED_IPS:
                self._cleanup_oldest_entries_unlocked(now)

            # Add this attempt
            self._attempts[ip_address].append(now)

            # Clean up old attempts outside the window
            cutoff = now - self.ATTEMPT_WINDOW
            self._attempts[ip_address] = [
                attempt for attempt in self._attempts[ip_address]
                if attempt > cutoff
            ]

            # If max attempts reached, lock out
            if len(self._attempts[ip_address]) >= self.MAX_ATTEMPTS:
                self._lockouts[ip_address] = now
    
    def is_locked_out(self, ip_address: str) -> Tuple[bool, int]:
        """
        Check if an IP address is currently locked out.

        Args:
            ip_address: The IP address to check

        Returns:
            Tuple of (is_locked_out, seconds_remaining)
        """
        ip_address = self._normalize_ip(ip_address)

        with self._lock:
            now = datetime.utcnow()
            
            # Check if there's an active lockout
            if ip_address in self._lockouts:
                lockout_time = self._lockouts[ip_address]
                lockout_end = lockout_time + self.LOCKOUT_DURATION
                
                if now < lockout_end:
                    seconds_remaining = int((lockout_end - now).total_seconds())
                    return True, seconds_remaining
                else:
                    # Lockout expired, clean up
                    del self._lockouts[ip_address]
                    if ip_address in self._attempts:
                        self._attempts[ip_address] = []
            
            return False, 0
    
    def clear_attempts(self, ip_address: str) -> None:
        """
        Clear failed attempts for an IP address (call on successful login).

        Args:
            ip_address: The IP address to clear
        """
        ip_address = self._normalize_ip(ip_address)

        with self._lock:
            if ip_address in self._attempts:
                self._attempts[ip_address] = []
            if ip_address in self._lockouts:
                del self._lockouts[ip_address]

    def get_remaining_attempts(self, ip_address: str) -> int:
        """
        Get the number of remaining attempts before lockout.

        Args:
            ip_address: The IP address to check

        Returns:
            Number of remaining attempts
        """
        ip_address = self._normalize_ip(ip_address)

        with self._lock:
            now = datetime.utcnow()
            cutoff = now - self.ATTEMPT_WINDOW

            # Count recent attempts
            if ip_address in self._attempts:
                recent_attempts = [
                    attempt for attempt in self._attempts[ip_address]
                    if attempt > cutoff
                ]
                return max(0, self.MAX_ATTEMPTS - len(recent_attempts))

            return self.MAX_ATTEMPTS

    def get_attempts_in_window(self, ip_address: str, window: timedelta) -> int:
        """
        Get the number of attempts in a specific time window.

        Args:
            ip_address: The IP address to check
            window: Time window to count attempts in

        Returns:
            Number of attempts in the time window
        """
        ip_address = self._normalize_ip(ip_address)

        with self._lock:
            now = datetime.utcnow()
            cutoff = now - window

            # Count recent attempts
            if ip_address in self._attempts:
                recent_attempts = [
                    attempt for attempt in self._attempts[ip_address]
                    if attempt > cutoff
                ]
                return len(recent_attempts)

            return 0

    def _cleanup_oldest_entries_unlocked(self, now: datetime) -> None:
        """Clean up oldest entries when memory bounds are reached.

        This method must be called while holding self._lock.
        It aggressively removes the oldest half of tracked IPs to prevent
        memory exhaustion during distributed brute-force attacks.
        """
        # First, do a normal cleanup of expired entries
        cutoff = now - self.ATTEMPT_WINDOW

        # Remove expired lockouts
        expired_lockouts = [
            ip for ip, lockout_time in self._lockouts.items()
            if now > lockout_time + self.LOCKOUT_DURATION
        ]
        for ip in expired_lockouts:
            del self._lockouts[ip]
            if ip in self._attempts:
                del self._attempts[ip]

        # Remove entries with no recent attempts
        for ip in list(self._attempts.keys()):
            self._attempts[ip] = [
                attempt for attempt in self._attempts[ip]
                if attempt > cutoff
            ]
            if not self._attempts[ip]:
                del self._attempts[ip]

        # If still over limit, remove oldest half by most recent attempt time
        if len(self._attempts) >= self.MAX_TRACKED_IPS:
            # Sort IPs by most recent attempt (oldest first)
            ips_by_recency = sorted(
                self._attempts.keys(),
                key=lambda ip: max(self._attempts[ip]) if self._attempts[ip] else now
            )
            # Remove oldest half
            to_remove = ips_by_recency[:len(ips_by_recency) // 2]
            for ip in to_remove:
                del self._attempts[ip]
                self._lockouts.pop(ip, None)

    def cleanup_old_entries(self) -> None:
        """
        Clean up expired lockouts and old attempts.

        This method is called automatically by the background cleanup task.
        """
        with self._lock:
            now = datetime.utcnow()

            # Clean up expired lockouts
            expired_lockouts = [
                ip for ip, lockout_time in self._lockouts.items()
                if now > lockout_time + self.LOCKOUT_DURATION
            ]
            for ip in expired_lockouts:
                del self._lockouts[ip]
                if ip in self._attempts:
                    self._attempts[ip] = []

            # Clean up old attempts
            cutoff = now - self.ATTEMPT_WINDOW
            for ip in list(self._attempts.keys()):
                self._attempts[ip] = [
                    attempt for attempt in self._attempts[ip]
                    if attempt > cutoff
                ]
                # Remove empty entries
                if not self._attempts[ip]:
                    del self._attempts[ip]

        # Reschedule cleanup if still running
        if self._running:
            self._schedule_cleanup()

    def _schedule_cleanup(self) -> None:
        """Schedule the next cleanup task."""
        self._cleanup_timer = threading.Timer(
            self.CLEANUP_INTERVAL,
            self.cleanup_old_entries
        )
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def start_cleanup_task(self) -> None:
        """
        Start the automatic cleanup background task.

        This should be called once when the application starts.
        """
        if not self._running:
            self._running = True
            self._schedule_cleanup()

    def stop_cleanup_task(self) -> None:
        """
        Stop the automatic cleanup background task.

        This should be called when the application shuts down.
        """
        self._running = False
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None


# Global rate limiter instance
_rate_limiter = LoginRateLimiter()
_cleanup_started = False
_cleanup_lock = threading.Lock()


def get_rate_limiter() -> LoginRateLimiter:
    """
    Get the global rate limiter instance.

    Automatically starts the cleanup task on first access.
    """
    global _cleanup_started

    # Start cleanup task on first access (thread-safe)
    if not _cleanup_started:
        with _cleanup_lock:
            if not _cleanup_started:
                _rate_limiter.start_cleanup_task()
                _cleanup_started = True

    return _rate_limiter
