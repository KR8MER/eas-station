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

"""Renewing an existing certificate: the dry run and the real run."""

import subprocess

from flask import jsonify, request

from app_core.auth.roles import require_permission
from app_core.certbot_settings import get_certbot_settings

from .blueprint import DOMAIN_PATTERN, certbot_bp
from .failures import _explain_certbot_failure
from .log import logger
from .paths import CERTBOT_CONFIG_DIR, CERTBOT_LOGS_DIR, CERTBOT_WORK_DIR, clear_stale_locks
from .staging import _is_existing_cert_staging


@certbot_bp.route('/api/certbot/renew-certificate', methods=['POST'])
@require_permission('system.configure')
def renew_certificate():
    """Check renewal timer status and provide renewal instructions.
    
    Certificate renewal is handled automatically by systemd timer (certbot.timer).
    This endpoint provides status and manual renewal instructions.
    """
    try:
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        if not settings.domain_name:
            return jsonify({
                "success": False,
                "error": "Domain name is not configured"
            }), 400

        # SECURITY: Validate domain name (defense in depth)
        domain = settings.domain_name.strip()
        if not DOMAIN_PATTERN.match(domain):
            logger.error(f"Invalid domain name in database: {domain}")
            return jsonify({
                "success": False,
                "error": "Invalid domain name in configuration"
            }), 500

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Check certbot.timer status
        timer_info = {
            'enabled': False,
            'active': False,
            'next_run': 'Unknown'
        }
        
        try:
            # Check if timer is enabled
            enabled_result = subprocess.run(
                ['sudo', 'systemctl', 'is-enabled', 'certbot.timer'],
                capture_output=True,
                text=True,
                timeout=5
            )
            timer_info['enabled'] = (enabled_result.returncode == 0)
            
            # Check if timer is active
            active_result = subprocess.run(
                ['sudo', 'systemctl', 'is-active', 'certbot.timer'],
                capture_output=True,
                text=True,
                timeout=5
            )
            timer_info['active'] = (active_result.stdout.strip() == 'active')
            
            # Get next run time
            if timer_info['active']:
                status_result = subprocess.run(
                    ['sudo', 'systemctl', 'status', 'certbot.timer'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                for line in status_result.stdout.split('\n'):
                    if 'Trigger:' in line:
                        timer_info['next_run'] = line.split('Trigger:')[1].strip()
                        break
        except Exception as e:
            logger.warning(f"Could not check certbot.timer status: {e}")

        # Build response with instructions
        # Note: --staging is only shown for the obtain command (where it
        # actually selects the ACME server).  For 'certbot renew', the server
        # is read from the stored renewal config, so the flag is meaningless.
        staging_flag = ' --staging' if settings.staging else ''
        dir_flags = (
            f" --config-dir {CERTBOT_CONFIG_DIR} "
            f"--work-dir {CERTBOT_WORK_DIR} "
            f"--logs-dir {CERTBOT_LOGS_DIR}"
        )
        instructions = {
            'timer_status': timer_info,
            'manual_commands': {
                'dry_run_test': f'certbot renew --dry-run{dir_flags}',
                'force_renew': f'certbot renew --force-renewal{dir_flags}',
                'obtain_new': f'certbot certonly --standalone -d {domain} --email {settings.email}{staging_flag}{dir_flags}'
            },
            'note': 'Certificate operations are executed from within the application container.'
        }

        if timer_info['active']:
            message = f"Certbot automatic renewal is active. Next run: {timer_info['next_run']}"
        elif timer_info['enabled']:
            message = "Certbot timer is enabled but not currently active. Start it with: systemctl start certbot.timer"
        else:
            message = "Certbot timer is not enabled. Enable it with: systemctl enable --now certbot.timer"

        return jsonify({
            "success": True,
            "message": message,
            "instructions": instructions
        })

    except Exception as exc:
        logger.error(f"Failed to check renewal status: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500

@certbot_bp.route('/api/certbot/renew-certificate-execute', methods=['POST'])
@require_permission('system.configure')
def renew_certificate_execute():
    """Execute certbot renewal operation.
    
    This endpoint actually runs certbot renew with the configured settings.
    """
    try:
        data = request.get_json() if request.is_json else {}
        dry_run = data.get('dry_run', False)
        force = data.get('force', False)
        
        settings = get_certbot_settings()

        if not settings.enabled:
            return jsonify({
                "success": False,
                "error": "Certbot is not enabled in settings"
            }), 400

        # Check if certbot is installed
        try:
            result = subprocess.run(
                ['which', 'certbot'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return jsonify({
                    "success": False,
                    "error": "Certbot is not installed on this system"
                }), 500
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"Failed to check certbot installation: {str(e)}"
            }), 500

        # Detect staging-to-production mismatch.
        # 'certbot renew' reads the ACME server URL from the stored renewal
        # config, so passing or omitting --staging has no effect — it will
        # always renew from whichever server was used during the original
        # 'certbot certonly'.  If the current cert is staging but the user
        # wants production, they must re-obtain, not renew.
        domain = settings.domain_name.strip()
        if not settings.staging and domain and _is_existing_cert_staging(domain):
            return jsonify({
                "success": False,
                "error": (
                    "Cannot renew: the current certificate was issued by the Let's Encrypt "
                    "staging server, but your settings are now set to production. "
                    "Renewal would only produce another staging certificate. "
                    "Please use 'Obtain Certificate' to get a new production certificate — "
                    "the staging certificate will be cleaned up automatically."
                ),
            }), 400

        # Clear any lock left by a previous run that was killed or crashed
        # before it could clean up after itself (see clear_stale_locks()).
        clear_stale_locks()

        # Build certbot renew command
        # Note: --staging is intentionally NOT appended here.  certbot renew
        # uses the ACME server stored in each renewal config file, so the flag
        # is meaningless and could be misleading in logs.
        certbot_cmd = [
            'sudo', 'certbot', 'renew',
            '--config-dir', str(CERTBOT_CONFIG_DIR),
            '--work-dir', str(CERTBOT_WORK_DIR),
            '--logs-dir', str(CERTBOT_LOGS_DIR),
            # certbot renew applies a random.uniform(1, 480)s sleep before
            # renewing whenever stdin isn't a tty (see certbot's renewal.py),
            # to spread load across Let's Encrypt when many hosts share a
            # cron schedule. Irrelevant for a single admin clicking a button
            # here, and a draw over our 120s subprocess timeout below is what
            # was surfacing as spurious "renewal operation timed out" errors.
            '--no-random-sleep-on-renew',
        ]

        if dry_run:
            certbot_cmd.append('--dry-run')

        if force:
            certbot_cmd.append('--force-renewal')
        
        try:
            logger.info(f"Running certbot renewal (dry_run={dry_run}, force={force})")
            logger.info(f"Certbot renewal command: {' '.join(certbot_cmd)}")
            result = subprocess.run(
                certbot_cmd,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode != 0:
                logger.error(f"Certbot renewal failed: {result.stderr}")
                logger.error(f"Certbot stdout: {result.stdout}")
                explained = _explain_certbot_failure(result.stderr, result.stdout)
                return jsonify({
                    "success": False,
                    "error": f"Certbot renew failed: {explained}",
                    "output": result.stdout
                }), 500
            
            action = "tested (dry run)" if dry_run else ("force renewed" if force else "renewed")
            logger.info(f"Successfully {action} certificate")
            
            return jsonify({
                "success": True,
                "message": f"Certificate successfully {action}",
                "output": result.stdout,
                "note": "Certificate renewal completed. Nginx will automatically use the new certificate on next reload." if not dry_run else "Dry run completed successfully. No changes were made."
            })
            
        except subprocess.TimeoutExpired:
            return jsonify({
                "success": False,
                "error": "Certbot renewal operation timed out"
            }), 500
        except Exception as e:
            logger.error(f"Certbot renewal failed: {e}")
            return jsonify({
                "success": False,
                "error": f"Failed to execute certbot renewal: {str(e)}"
            }), 500

    except Exception as exc:
        logger.error(f"Failed to renew certificate: {exc}")
        return jsonify({"success": False, "error": str(exc)}), 500
