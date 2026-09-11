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

"""Where certbot is allowed to write, and making sure it exists.

`/etc/letsencrypt`, `/var/lib/letsencrypt` and `/var/log/letsencrypt` are
read-only in containerised and sandboxed deployments, so this project points
certbot at a writable `certbot_data/` tree beside the repository instead.

``_ensure_certbot_directories()`` runs at import time, as it did in the
single-file module — importing this module is what creates the tree.
"""

import subprocess
from pathlib import Path

from .log import logger


# Certbot writable directories configuration
# In containerized/sandboxed environments, /var/log/letsencrypt, /etc/letsencrypt,
# and /var/lib/letsencrypt may be read-only. Use writable directories instead.
# Four levels up is the repository root:
#   paths.py -> certbot/ -> admin/ -> webapp/ -> <repo root>
# The single-file module needed three. Dropping one here would silently
# point the whole certbot tree at webapp/certbot_data — pinned by
# tests/test_certbot_package.py.
CERTBOT_BASE_DIR = Path(__file__).parent.parent.parent.parent / 'certbot_data'
CERTBOT_CONFIG_DIR = CERTBOT_BASE_DIR / 'config'
CERTBOT_WORK_DIR = CERTBOT_BASE_DIR / 'work'
CERTBOT_LOGS_DIR = CERTBOT_BASE_DIR / 'logs'


def _ensure_webroot_directory():
    """Ensure webroot directory exists with proper permissions for certbot.

    The webroot directory must be writable by root (certbot runs as root via sudo)
    and readable by nginx (www-data) to serve the ACME challenge files.
    
    Certbot creates challenge files as root, then nginx serves them to Let's Encrypt.
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        webroot_path = '/var/www/certbot'
        challenge_path = '/var/www/certbot/.well-known/acme-challenge'
        
        # Create directories with sudo (certbot runs as root)
        subprocess.run(
            ['sudo', 'mkdir', '-p', challenge_path],
            capture_output=True,
            timeout=5
        )
        
        # Set ownership to root:root (certbot needs to write as root)
        subprocess.run(
            ['sudo', 'chown', '-R', 'root:root', webroot_path],
            capture_output=True,
            timeout=5
        )
        
        # Set permissions to 755 (owner=rwx, group=rx, other=rx)
        # This allows root to write, and www-data (nginx) to read
        subprocess.run(
            ['sudo', 'chmod', '-R', '755', webroot_path],
            capture_output=True,
            timeout=5
        )
        
        logger.info(f"Webroot directory configured: {webroot_path}")
        return True
        
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while configuring webroot directory")
        return False
    except Exception as e:
        logger.warning(f"Error configuring webroot directory: {e}")
        return False

def _ensure_certbot_directories():
    """Ensure certbot directories exist with proper permissions.

    Creates directories if they don't exist and sets permissions to allow
    both the web app user and root (via sudo) to write to them.
    Also removes stale lock files that can cause permission errors.

    Uses sudo for all operations since certbot runs as root and creates
    root-owned files that the web app user cannot modify.
    """
    # Always use sudo to ensure we can fix root-owned directories/files
    try:
        # Create directories with sudo
        for directory in [CERTBOT_CONFIG_DIR, CERTBOT_WORK_DIR, CERTBOT_LOGS_DIR]:
            subprocess.run(
                ['sudo', 'mkdir', '-p', str(directory)],
                capture_output=True,
                timeout=5
            )

        # Fix permissions on the entire certbot_data directory tree.
        # 755 (not world-WRITABLE) still gives the eas-station user
        # read+traverse access for the .exists()/iterdir() checks and
        # openssl/read_text() calls elsewhere in this package (install.py,
        # staging.py) -- none of which ever read a private key's actual
        # bytes, only its path or (for fullchain.pem, which is public PKI
        # material by design) its content. The privkey*.pem chmod below
        # locks down the one thing in this tree that's actually secret.
        subprocess.run(
            ['sudo', 'chmod', '-R', '755', str(CERTBOT_BASE_DIR)],
            capture_output=True,
            timeout=10
        )

        # Normalize ownership to root:root. Certbot runs as root and calls
        # copy_ownership_and_apply_mode(old_key, new_key, copy_group=True),
        # which translates to os.chown(new_key, -1, old_key_gid). On hosts
        # where that chown returns EPERM (AppArmor profile, user namespaces,
        # certain bind-mounts), the renewal aborts with
        #     PermissionError: [Errno 1] Operation not permitted:
        #     '.../archive/<domain>/privkeyN.pem'
        # Leaving the tree owned by root makes the copy-group step a no-op
        # so the failure cannot recur. Changing this to a non-root group
        # (e.g. eas-station) would reintroduce exactly the failure this
        # comment describes on the next renewal -- do not "fix" this to
        # grant eas-station a group instead of the privkey chmod below.
        subprocess.run(
            ['sudo', 'chown', '-R', 'root:root', str(CERTBOT_BASE_DIR)],
            capture_output=True,
            timeout=10
        )

        # Lock the actual private key material down to root-only. This is
        # the one piece of this tree that's genuinely secret -- fullchain/
        # cert/chain.pem are public PKI material by design, and nothing in
        # this codebase ever reads a privkey.pem's *content* as the
        # eas-station user (only its path, or a stat()/.exists() check,
        # neither of which needs read permission on the file itself -- stat
        # only needs execute/search permission on its parent directories,
        # which the 755 above already grants). nginx's master process reads
        # these directly at config-load/reload time, but it does so as
        # root (before dropping privilege to www-data for its workers), so
        # root-only here doesn't affect it either.
        subprocess.run(
            ['sudo', 'find', str(CERTBOT_BASE_DIR), '-name', 'privkey*.pem',
             '-exec', 'chmod', '600', '{}', '+'],
            capture_output=True,
            timeout=10
        )

        # Remove ALL .certbot.lock files (they're root-owned, need sudo)
        # Use find command which handles the case where files don't exist
        subprocess.run(
            ['sudo', 'find', str(CERTBOT_BASE_DIR), '-name', '.certbot.lock', '-delete'],
            capture_output=True,
            timeout=10
        )

        logger.info(f"Certbot directories configured: {CERTBOT_BASE_DIR}")
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while configuring certbot directories")
    except Exception as e:
        logger.warning(f"Error configuring certbot directories: {e}")

def clear_stale_locks() -> None:
    """Remove .certbot.lock files left by a run that died without cleaning up.

    _ensure_certbot_directories() only runs at import time (Flask app
    startup), so a lock left behind by a killed/crashed/hung certbot
    invocation blocks every later renew/obtain attempt with "Another
    instance of Certbot is already running" until the app process is
    restarted. Call this right before each certbot invocation instead.
    Skips removal if a certbot process is actually alive, so a genuinely
    in-progress run isn't clobbered.
    """
    try:
        pgrep_result = subprocess.run(
            ['pgrep', '-x', 'certbot'],
            capture_output=True,
            timeout=5,
        )
        if pgrep_result.returncode == 0:
            return

        subprocess.run(
            ['sudo', 'find', str(CERTBOT_BASE_DIR), '-name', '.certbot.lock', '-delete'],
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Timeout while clearing stale certbot locks")
    except Exception as e:
        logger.warning(f"Error clearing stale certbot locks: {e}")


# Ensure directories exist at module load time
_ensure_certbot_directories()
