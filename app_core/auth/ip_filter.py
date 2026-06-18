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
IP filtering system for allowlist/blocklist management.

Provides:
- IP address and CIDR range matching
- Allowlist (whitelist) and blocklist (blacklist) management
- Automatic blocking based on failed attempts
- Flood protection
"""

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple
from enum import Enum

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text
from app_core.extensions import db
from app_utils import utc_now


class IPFilterType(Enum):
    """Type of IP filter."""
    ALLOWLIST = 'allowlist'
    BLOCKLIST = 'blocklist'


class IPFilterReason(Enum):
    """Reason for IP filter."""
    MANUAL = 'manual'
    AUTO_MALICIOUS = 'auto_malicious'
    AUTO_BRUTE_FORCE = 'auto_brute_force'
    AUTO_FLOOD = 'auto_flood'


class IPFilter(db.Model):
    """IP address filter (allowlist or blocklist)."""
    __tablename__ = 'ip_filters'
    
    id = Column(Integer, primary_key=True)
    ip_address = Column(String(45), nullable=False, index=True)  # IP or CIDR range
    filter_type = Column(String(20), nullable=False, index=True)  # allowlist or blocklist
    reason = Column(String(50), nullable=False)  # Why was this added
    description = Column(Text, nullable=True)  # User-provided description
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_by = Column(Integer, nullable=True)  # User ID who created it
    expires_at = Column(DateTime(timezone=True), nullable=True)  # Optional expiration
    is_active = Column(Boolean, default=True, nullable=False)
    
    def __repr__(self):
        return f'<IPFilter {self.ip_address} ({self.filter_type})>'
    
    def to_dict(self):
        """Convert to dictionary."""
        return {
            'id': self.id,
            'ip_address': self.ip_address,
            'filter_type': self.filter_type,
            'reason': self.reason,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'is_active': self.is_active,
        }
    
    @staticmethod
    def is_ip_allowed(ip_address: str) -> Tuple[bool, Optional[str]]:
        """
        Check if an IP address is allowed to access the system.
        
        Returns:
            Tuple of (is_allowed, reason_if_blocked)
        """
        if not ip_address:
            return True, None
        
        try:
            ip_obj = ipaddress.ip_address(ip_address)
        except ValueError:
            return True, None  # Invalid IP, let other systems handle it
        
        # Check blocklist first
        blocked_filters = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True
        ).all()
        
        for filter_entry in blocked_filters:
            # Check if expired
            if filter_entry.expires_at and utc_now() > filter_entry.expires_at:
                filter_entry.is_active = False
                db.session.add(filter_entry)
                db.session.commit()
                continue
            
            # Check if IP matches
            if IPFilter._ip_matches(ip_address, filter_entry.ip_address):
                return False, filter_entry.reason
        
        # Check if allowlist exists
        allowlist_filters = IPFilter.query.filter_by(
            filter_type=IPFilterType.ALLOWLIST.value,
            is_active=True
        ).all()
        
        if allowlist_filters:
            # Allowlist exists, so check if IP is in it
            for filter_entry in allowlist_filters:
                if IPFilter._ip_matches(ip_address, filter_entry.ip_address):
                    return True, None
            
            # Not in allowlist
            return False, 'not_in_allowlist'
        
        # No allowlist, not blocked
        return True, None
    
    @staticmethod
    def is_ip_blocked(ip_address: str) -> Tuple[bool, Optional[str]]:
        """
        Check whether an IP address is on the active blocklist.

        Unlike :meth:`is_ip_allowed`, this checks ONLY the blocklist and never
        applies allowlist-exclusivity ("deny everything not explicitly
        allowed"). It is intended for the global per-request ban gate, where
        accidentally enabling allowlist-only mode for every visitor would lock
        the entire site out. Expired blocklist entries are deactivated as a
        side effect, mirroring :meth:`is_ip_allowed`.

        Returns:
            Tuple of (is_blocked, reason_if_blocked)
        """
        if not ip_address:
            return False, None

        try:
            ipaddress.ip_address(ip_address)
        except ValueError:
            return False, None  # Invalid IP, let other systems handle it

        blocked_filters = IPFilter.query.filter_by(
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True
        ).all()

        for filter_entry in blocked_filters:
            # Deactivate expired bans so they stop matching. Coerce naive
            # timestamps (e.g. from SQLite, which drops tzinfo) to UTC so the
            # comparison can never raise inside the per-request ban gate.
            expires_at = filter_entry.expires_at
            if expires_at is not None:
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
                if utc_now() > expires_at:
                    filter_entry.is_active = False
                    db.session.add(filter_entry)
                    db.session.commit()
                    # Lift the matching host-firewall ban for the expired entry.
                    try:
                        from app_core.auth.firewall import firewall_unban
                        firewall_unban(filter_entry.ip_address)
                    except Exception:
                        pass
                    continue

            if IPFilter._ip_matches(ip_address, filter_entry.ip_address):
                return True, filter_entry.reason

        return False, None

    @staticmethod
    def _ip_matches(ip_address: str, filter_pattern: str) -> bool:
        """
        Check if an IP address matches a filter pattern.
        
        Supports:
        - Exact IP: 192.168.1.1
        - CIDR range: 192.168.1.0/24
        """
        try:
            ip_obj = ipaddress.ip_address(ip_address)
            
            # Check if pattern is CIDR
            if '/' in filter_pattern:
                network = ipaddress.ip_network(filter_pattern, strict=False)
                return ip_obj in network
            else:
                # Exact match
                filter_ip = ipaddress.ip_address(filter_pattern)
                return ip_obj == filter_ip
        except ValueError:
            return False
    
    @staticmethod
    def add_to_blocklist(
        ip_address: str,
        reason: str,
        description: Optional[str] = None,
        created_by: Optional[int] = None,
        expires_in_hours: Optional[int] = None
    ) -> 'IPFilter':
        """
        Add an IP to the blocklist.
        
        Args:
            ip_address: IP address or CIDR range
            reason: Reason for blocking
            description: User-provided description
            created_by: User ID who created it
            expires_in_hours: Optional expiration time in hours
            
        Returns:
            Created IPFilter instance
        """
        expires_at = None
        if expires_in_hours:
            expires_at = utc_now() + timedelta(hours=expires_in_hours)
        
        filter_entry = IPFilter(
            ip_address=ip_address,
            filter_type=IPFilterType.BLOCKLIST.value,
            reason=reason,
            description=description,
            created_by=created_by,
            expires_at=expires_at,
            is_active=True
        )
        
        db.session.add(filter_entry)
        db.session.commit()

        # Mirror to the host firewall (no-op unless fail2ban enforcement is on).
        try:
            from app_core.auth.firewall import firewall_ban
            firewall_ban(ip_address)
        except Exception:
            pass

        return filter_entry

    @staticmethod
    def add_to_allowlist(
        ip_address: str,
        description: Optional[str] = None,
        created_by: Optional[int] = None
    ) -> 'IPFilter':
        """
        Add an IP to the allowlist.
        
        Args:
            ip_address: IP address or CIDR range
            description: User-provided description
            created_by: User ID who created it
            
        Returns:
            Created IPFilter instance
        """
        filter_entry = IPFilter(
            ip_address=ip_address,
            filter_type=IPFilterType.ALLOWLIST.value,
            reason=IPFilterReason.MANUAL.value,
            description=description,
            created_by=created_by,
            is_active=True
        )
        
        db.session.add(filter_entry)
        db.session.commit()
        
        return filter_entry
    
    @staticmethod
    def remove_filter(filter_id: int) -> bool:
        """
        Remove an IP filter.
        
        Args:
            filter_id: ID of the filter to remove
            
        Returns:
            True if removed, False if not found
        """
        filter_entry = IPFilter.query.get(filter_id)
        if filter_entry:
            ip_address = filter_entry.ip_address
            was_blocklist = filter_entry.filter_type == IPFilterType.BLOCKLIST.value
            db.session.delete(filter_entry)
            db.session.commit()

            # Lift the matching host-firewall ban, if any.
            if was_blocklist:
                try:
                    from app_core.auth.firewall import firewall_unban
                    firewall_unban(ip_address)
                except Exception:
                    pass
            return True
        return False
    
    @staticmethod
    def cleanup_expired() -> int:
        """
        Clean up expired filters.
        
        Returns:
            Number of filters cleaned up
        """
        now = utc_now()
        expired = IPFilter.query.filter(
            IPFilter.expires_at.isnot(None),
            IPFilter.expires_at < now,
            IPFilter.is_active == True
        ).all()
        
        count = 0
        unban_ips = []
        for filter_entry in expired:
            filter_entry.is_active = False
            db.session.add(filter_entry)
            if filter_entry.filter_type == IPFilterType.BLOCKLIST.value:
                unban_ips.append(filter_entry.ip_address)
            count += 1

        db.session.commit()

        # Lift the matching host-firewall bans for the now-expired entries.
        if unban_ips:
            try:
                from app_core.auth.firewall import firewall_unban
                for ip in unban_ips:
                    firewall_unban(ip)
            except Exception:
                pass
        return count


class FloodProtection:
    """Flood protection to detect rapid-fire login attempts."""
    
    # Configuration
    MAX_ATTEMPTS_PER_MINUTE = 10
    FLOOD_BAN_HOURS = 1
    
    @staticmethod
    def check_flood(ip_address: str, rate_limiter) -> Tuple[bool, int]:
        """
        Check if an IP is flooding login attempts.

        Args:
            ip_address: IP address to check
            rate_limiter: LoginRateLimiter instance

        Returns:
            Tuple of (is_flooding, attempts_in_last_minute)
        """
        if not ip_address or not rate_limiter:
            return False, 0

        # Check attempts in last minute using public method
        attempts_count = rate_limiter.get_attempts_in_window(
            ip_address,
            timedelta(minutes=1)
        )

        is_flooding = attempts_count >= FloodProtection.MAX_ATTEMPTS_PER_MINUTE

        return is_flooding, attempts_count
    
    @staticmethod
    def auto_ban_flooder(ip_address: str) -> IPFilter:
        """
        Automatically ban an IP for flooding.
        
        Args:
            ip_address: IP address to ban
            
        Returns:
            Created IPFilter instance
        """
        return IPFilter.add_to_blocklist(
            ip_address=ip_address,
            reason=IPFilterReason.AUTO_FLOOD.value,
            description=f'Automatically banned for flooding (>{FloodProtection.MAX_ATTEMPTS_PER_MINUTE} attempts/min)',
            expires_in_hours=FloodProtection.FLOOD_BAN_HOURS
        )


class AutoBanManager:
    """Manage automatic banning based on failed attempts."""
    
    # Configuration
    FAILED_ATTEMPTS_THRESHOLD = 5
    BAN_DURATION_HOURS = 24
    
    @staticmethod
    def check_and_ban(ip_address: str, rate_limiter) -> Optional[IPFilter]:
        """
        Check if an IP should be auto-banned and ban it if needed.
        
        Args:
            ip_address: IP address to check
            rate_limiter: LoginRateLimiter instance
            
        Returns:
            IPFilter instance if banned, None otherwise
        """
        if not ip_address or not rate_limiter:
            return None
        
        # Check if already in permanent blocklist
        existing = IPFilter.query.filter_by(
            ip_address=ip_address,
            filter_type=IPFilterType.BLOCKLIST.value,
            is_active=True
        ).filter(
            (IPFilter.expires_at.is_(None)) | (IPFilter.expires_at > utc_now())
        ).first()
        
        if existing:
            return None  # Already banned
        
        # Check failed attempts
        remaining = rate_limiter.get_remaining_attempts(ip_address)
        
        if remaining <= 0:
            # Auto-ban
            return IPFilter.add_to_blocklist(
                ip_address=ip_address,
                reason=IPFilterReason.AUTO_BRUTE_FORCE.value,
                description=f'Automatically banned after {AutoBanManager.FAILED_ATTEMPTS_THRESHOLD} failed login attempts',
                expires_in_hours=AutoBanManager.BAN_DURATION_HOURS
            )
        
        return None
