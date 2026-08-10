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

"""Turning a certbot exit into something an operator can act on."""

from .paths import CERTBOT_BASE_DIR


# Removed _ensure_nginx_log_permissions() function (removed in this version)
# The nginx plugin has fundamental permission issues that cannot be reliably solved
# by changing file permissions. The nginx plugin runs 'nginx -t' which may execute
# in a different security context (AppArmor, SELinux, etc.) that prevents write access
# to /var/log/nginx/error.log even with permissive file permissions.
# Use standalone or webroot modes instead.

def _explain_certbot_failure(stderr: str, stdout: str) -> str:
    """Return a human-readable hint prepended to certbot stderr when we
    recognize the failure mode, so the UI surfaces a remediation step
    instead of an opaque traceback.
    """
    blob = f"{stderr}\n{stdout}"
    raw = (stderr or stdout or "").strip()
    if "Operation not permitted" in blob and "/archive/" in blob and ".pem" in blob:
        return (
            "Certbot failed while chowning a new key file under the certbot "
            "archive directory. This usually means existing files there are "
            "owned by the eas-station user (left over from an older install) "
            "and the kernel/AppArmor is denying root the chown to that group. "
            "Re-run `update.sh` (or `sudo chown -R root:root "
            f"{CERTBOT_BASE_DIR}`) and try again.\n\nOriginal error:\n{raw}"
        )
    return raw
