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

"""Checking and starting nginx around a certificate operation.

The webroot and standalone plugins both need to know whether nginx is holding
port 80 before certbot runs.
"""

import subprocess

from .log import logger


def _ensure_nginx_running():
    """Ensure nginx is running, attempt to start it if not.
    
    This is a safety function called in exception handlers to ensure
    nginx is not left in a stopped state after certificate operations.
    
    Returns:
        bool: True if nginx is running or successfully started, False otherwise
    """
    try:
        # Check if nginx is already running
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'nginx'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.stdout.strip() == 'active':
            return True
        
        # Try to start nginx
        logger.warning("Nginx not running, attempting to start...")
        start_result = subprocess.run(
            ['sudo', 'systemctl', 'start', 'nginx'],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if start_result.returncode == 0:
            logger.info("Successfully started nginx")
            return True
        else:
            logger.error(f"Failed to start nginx: {start_result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Timeout while checking/starting nginx")
        return False
    except Exception as e:
        logger.error(f"Error ensuring nginx is running: {e}")
        return False

def _check_nginx_status():
    """Check if nginx is currently running.
    
    Returns:
        bool: True if nginx is active, False otherwise
    """
    try:
        result = subprocess.run(
            ['sudo', 'systemctl', 'is-active', 'nginx'],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.stdout.strip() == 'active'
    except Exception as e:
        logger.warning(f"Could not check nginx status: {e}")
        return False
