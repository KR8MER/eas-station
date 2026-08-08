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

"""Detecting and clearing Let's Encrypt *staging* certificates.

A staging certificate is not trusted by browsers. Certbot will not replace one
with a production certificate for the same domain unless the old lineage is
removed first, so obtaining and renewing both have to check for it.
"""

import subprocess
from typing import Any, Dict

from .log import logger
from .paths import CERTBOT_CONFIG_DIR, CERTBOT_LOGS_DIR, CERTBOT_WORK_DIR


def _is_existing_cert_staging(domain: str) -> bool:
    """Check if an existing certificate for the domain is from the staging server.

    Checks both the renewal config (for acme-staging server URL) and the cert
    issuer (for STAGING / Fake LE indicators).

    Args:
        domain: Domain name to check

    Returns:
        True if a staging certificate exists for this domain
    """
    # Check renewal config files for staging ACME server URL
    renewal_dir = CERTBOT_CONFIG_DIR / 'renewal'
    if renewal_dir.exists():
        for conf_file in renewal_dir.iterdir():
            if not conf_file.name.endswith('.conf'):
                continue
            # Match domain.conf or domain-0001.conf
            base = conf_file.stem
            if base != domain and not (base.startswith(f"{domain}-") and base[len(domain)+1:].isdigit()):
                continue
            try:
                content = conf_file.read_text()
                if 'acme-staging' in content:
                    return True
            except Exception:
                continue

    # Check certificate issuer as a fallback
    live_dir = CERTBOT_CONFIG_DIR / 'live'
    if live_dir.exists():
        for entry in live_dir.iterdir():
            if not entry.is_dir() or entry.name == 'README':
                continue
            if entry.name != domain and not (entry.name.startswith(f"{domain}-") and entry.name[len(domain)+1:].isdigit()):
                continue
            cert_path = entry / 'fullchain.pem'
            if cert_path.exists():
                try:
                    result = subprocess.run(
                        ['openssl', 'x509', '-in', str(cert_path), '-noout', '-issuer'],
                        capture_output=True, text=True, timeout=5
                    )
                    if result.returncode == 0:
                        issuer = result.stdout
                        if '(STAGING)' in issuer or 'Fake LE' in issuer or 'Fake Let\'s Encrypt' in issuer:
                            return True
                except Exception:
                    continue

    return False

def _delete_staging_certs(domain: str) -> Dict[str, Any]:
    """Delete all staging certificates for a domain so a production cert can be obtained.

    Uses 'certbot delete' for each matching cert name, which cleanly removes
    the certificate, renewal config, and associated files.

    Args:
        domain: Domain name whose staging certs should be deleted

    Returns:
        Dict with 'success', 'deleted' (list of deleted cert names), and optionally 'error'
    """
    deleted = []
    errors = []

    # Find all cert names that match this domain
    renewal_dir = CERTBOT_CONFIG_DIR / 'renewal'
    if not renewal_dir.exists():
        return {"success": True, "deleted": []}

    cert_names = []
    for conf_file in renewal_dir.iterdir():
        if not conf_file.name.endswith('.conf'):
            continue
        base = conf_file.stem
        if base == domain or (base.startswith(f"{domain}-") and base[len(domain)+1:].isdigit()):
            # Only delete if it's actually a staging cert
            try:
                content = conf_file.read_text()
                if 'acme-staging' in content:
                    cert_names.append(base)
            except Exception:
                continue

    for cert_name in cert_names:
        try:
            result = subprocess.run(
                [
                    'sudo', 'certbot', 'delete',
                    '--cert-name', cert_name,
                    '--non-interactive',
                    '--config-dir', str(CERTBOT_CONFIG_DIR),
                    '--work-dir', str(CERTBOT_WORK_DIR),
                    '--logs-dir', str(CERTBOT_LOGS_DIR),
                ],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                deleted.append(cert_name)
                logger.info(f"Deleted staging certificate: {cert_name}")
            else:
                errors.append(f"{cert_name}: {result.stderr.strip()}")
                logger.error(f"Failed to delete staging cert {cert_name}: {result.stderr}")
        except Exception as e:
            errors.append(f"{cert_name}: {str(e)}")

    return {
        "success": len(errors) == 0,
        "deleted": deleted,
        "error": "; ".join(errors) if errors else None,
    }
