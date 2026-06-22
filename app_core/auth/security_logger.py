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
Security logging for fail2ban integration.

Provides structured logging of security events in a format that can be
easily parsed by fail2ban or other intrusion detection systems.
"""

import logging
from typing import Optional
from datetime import datetime

# Create a dedicated security logger
security_logger = logging.getLogger('eas_station.security')


class SecurityEvent:
    """Enumeration of security event types."""
    
    MALICIOUS_LOGIN = 'MALICIOUS_LOGIN'
    FAILED_LOGIN = 'FAILED_LOGIN'
    RATE_LIMIT_EXCEEDED = 'RATE_LIMIT_EXCEEDED'
    SQL_INJECTION = 'SQL_INJECTION'
    COMMAND_INJECTION = 'COMMAND_INJECTION'
    SUSPICIOUS_INPUT = 'SUSPICIOUS_INPUT'


def log_security_event(
    event_type: str,
    ip_address: str,
    username: Optional[str] = None,
    details: Optional[str] = None
) -> None:
    """
    Log a security event in a fail2ban-compatible format.
    
    Format: [TIMESTAMP] EVENT_TYPE from IP_ADDRESS username=USERNAME details=DETAILS
    
    This format allows fail2ban to easily parse and take action based on
    patterns like multiple MALICIOUS_LOGIN or FAILED_LOGIN events.
    
    Args:
        event_type: Type of security event (use SecurityEvent constants)
        ip_address: IP address of the source
        username: Username involved (if applicable)
        details: Additional details about the event
    """
    timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    # Build log message
    parts = [
        f"[{timestamp}]",
        f"{event_type}",
        f"from {ip_address}"
    ]
    
    if username:
        parts.append(f"username={username}")
    
    if details:
        parts.append(f"details={details}")
    
    message = " ".join(parts)
    
    # Log at WARNING level for fail2ban to pick up
    security_logger.warning(message)


def log_malicious_login_attempt(ip_address: str, username: str, reason: str) -> None:
    """
    Log a malicious login attempt (SQL injection, command injection, etc.).
    
    Args:
        ip_address: IP address of attacker
        username: Username attempted (sanitized)
        reason: Reason why it was flagged as malicious
    """
    log_security_event(
        SecurityEvent.MALICIOUS_LOGIN,
        ip_address,
        username=username,
        details=reason
    )


def log_failed_login_attempt(ip_address: str, username: str) -> None:
    """
    Log a regular failed login attempt.
    
    Args:
        ip_address: IP address of user
        username: Username attempted (sanitized)
    """
    log_security_event(
        SecurityEvent.FAILED_LOGIN,
        ip_address,
        username=username
    )


def log_rate_limit_exceeded(ip_address: str) -> None:
    """
    Log when an IP exceeds rate limits.
    
    Args:
        ip_address: IP address being rate limited
    """
    log_security_event(
        SecurityEvent.RATE_LIMIT_EXCEEDED,
        ip_address,
        details="Too many failed login attempts"
    )


def get_fail2ban_config() -> str:
    """
    Generate a sample fail2ban configuration for EAS Station.
    
    Returns:
        String containing fail2ban jail configuration
    """
    return """
# /etc/fail2ban/jail.local
# EAS Station security jail configuration

[eas-station-malicious]
enabled = true
port = http,https
filter = eas-station-malicious
logpath = /var/log/eas-station/security.log
maxretry = 1
bantime = 3600
findtime = 600

[eas-station-auth]
enabled = true
port = http,https
filter = eas-station-auth
logpath = /var/log/eas-station/security.log
maxretry = 5
bantime = 1800
findtime = 600

# /etc/fail2ban/filter.d/eas-station-malicious.conf
[Definition]
failregex = ^.*MALICIOUS_LOGIN from <HOST>.*$
ignoreregex =

# /etc/fail2ban/filter.d/eas-station-auth.conf
[Definition]
failregex = ^.*(FAILED_LOGIN|RATE_LIMIT_EXCEEDED) from <HOST>.*$
ignoreregex =
"""


def setup_security_logging(log_file: Optional[str] = None) -> None:
    """
    Setup the security logger with file handler.
    
    Args:
        log_file: Path to security log file. If None, uses default location.
    """
    if log_file is None:
        log_file = '/var/log/eas-station/security.log'
    
    # Create file handler
    try:
        handler = logging.FileHandler(log_file)
        handler.setLevel(logging.WARNING)
        
        # Use simple format for fail2ban parsing
        formatter = logging.Formatter('%(message)s')
        handler.setFormatter(formatter)
        
        security_logger.addHandler(handler)
        security_logger.setLevel(logging.WARNING)
    except (IOError, PermissionError) as e:
        # Fall back to console if can't write to file
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.WARNING)
        formatter = logging.Formatter('%(message)s')
        console_handler.setFormatter(formatter)
        security_logger.addHandler(console_handler)
        security_logger.setLevel(logging.WARNING)
        security_logger.warning(f"Could not setup security log file: {e}")
