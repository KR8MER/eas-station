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

"""systemd unit status collection."""

import subprocess
from typing import Any, Dict


def _collect_orphaned_failed_services(logger, service_prefix: str, known_service_names: set) -> list:
    """Any {service_prefix}-* unit systemd currently has in a failed state,
    whether or not it's still one of the names EAS_SERVICES/POLLER_SERVICES
    knows about.

    Services get retired or renamed as the codebase evolves (e.g.
    eas-station-eas.service, folded into -audio/-demod during the hardware
    subsystem split) -- but update.sh never disables/removes the old unit on
    a box that's been running since before the change, so systemd is left
    holding a stale failed record for a unit whose definition no longer
    exists anywhere in the current codebase. The fixed-allowlist loop below
    only ever checks names it already knows about, so that stale record was
    completely invisible to this dashboard -- confirmed on a real deployment
    where `systemctl --failed` showed exactly this (a `not-found` unit,
    killed by a stop timeout two weeks earlier) with nothing here reflecting
    it at all.
    """
    try:
        result = subprocess.run(
            [
                "systemctl", "list-units", "--all", "--plain", "--no-legend",
                "--state=failed", f"{service_prefix}-*",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        if logger:
            logger.debug("Could not list failed %s-* units: %s", service_prefix, exc)
        return []

    orphans = []
    for line in (result.stdout or "").splitlines():
        parts = line.split(None, 4)
        if not parts:
            continue
        unit_name = parts[0]
        if unit_name in known_service_names:
            continue  # already reported by the per-name loop above
        if "@" in unit_name:
            # A template-instantiated unit (e.g.
            # eas-station-failure-recovery@eas-station-audio.service) is
            # expected to exist under a name the static allowlist above
            # can't enumerate ahead of time -- it's legitimate, currently-
            # relevant infrastructure, not a leftover from a retired
            # service, so it must not get the "no longer part of this
            # install" message. A real failure here is still worth
            # surfacing, just not through this orphan-specific path.
            continue
        description = parts[4] if len(parts) > 4 else unit_name
        orphans.append({"name": unit_name, "description": description})
    return orphans


def _collect_systemd_services(logger) -> Dict[str, Any]:
    """Collect status information for EAS Station systemd services."""

    # Import here to avoid circular dependency (app_core imports app_utils)
    from app_core.config import SERVICE_PREFIX, get_eas_services, INFRASTRUCTURE_SERVICES

    result: Dict[str, Any] = {
        "available": False,
        "status": "unavailable",
        "services": [],
        "summary": {"total": 0, "active": 0, "inactive": 0, "failed": 0},
        "issues": [],
        "error": None,
    }
    
    # List of EAS Station services to monitor (from centralized config)
    eas_services = get_eas_services()

    # Additional system services that EAS Station depends on
    dependency_services = INFRASTRUCTURE_SERVICES + ["icecast2.service"]
    
    try:
        all_services = eas_services + dependency_services
        services_data = []
        
        for service_name in all_services:
            try:
                # Check if service exists first
                check_cmd = ["systemctl", "list-unit-files", service_name]
                check_result = subprocess.run(
                    check_cmd,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if service_name not in check_result.stdout:
                    # Service doesn't exist, skip it
                    continue
                
                # Get service status
                status_cmd = ["systemctl", "show", service_name, 
                             "--property=ActiveState,SubState,LoadState,UnitFileState,Description"]
                status_result = subprocess.run(
                    status_cmd,
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                
                if status_result.returncode == 0:
                    # Parse systemctl output
                    props = {}
                    for line in status_result.stdout.strip().split('\n'):
                        if '=' in line:
                            key, value = line.split('=', 1)
                            props[key] = value
                    
                    active_state = props.get('ActiveState', 'unknown')
                    sub_state = props.get('SubState', 'unknown')
                    description = props.get('Description', service_name)
                    
                    # Determine if this is an EAS service or dependency
                    is_eas_service = service_name in eas_services
                    
                    service_info = {
                        "name": service_name,
                        "display_name": description,
                        "active_state": active_state,
                        "sub_state": sub_state,
                        "status": active_state,
                        "is_running": active_state == "active",
                        "is_eas_service": is_eas_service,
                        "category": "EAS Station" if is_eas_service else "Dependencies"
                    }
                    
                    services_data.append(service_info)
                    
                    # Track issues
                    if active_state == "failed":
                        result["issues"].append({
                            "service": service_name,
                            "issue": f"{description} has failed",
                            "severity": "error"
                        })
                    elif active_state != "active" and is_eas_service:
                        result["issues"].append({
                            "service": service_name,
                            "issue": f"{description} is not running",
                            "severity": "warning"
                        })
                        
            except subprocess.TimeoutExpired:
                if logger:
                    logger.debug(f"Timeout checking service {service_name}")
            except Exception as exc:
                if logger:
                    logger.debug(f"Error checking service {service_name}: {exc}")

        # Catch failed units that aren't (or are no longer) in the allowlist
        # above -- see _collect_orphaned_failed_services for why this exists.
        for orphan in _collect_orphaned_failed_services(logger, SERVICE_PREFIX, set(all_services)):
            services_data.append({
                "name": orphan["name"],
                "display_name": orphan["description"],
                "active_state": "failed",
                "sub_state": "failed",
                "status": "failed",
                "is_running": False,
                "is_eas_service": True,
                "category": "EAS Station",
                "orphaned": True,
            })
            result["issues"].append({
                "service": orphan["name"],
                "issue": (
                    f"{orphan['name']} is a failed systemd unit no longer part of this "
                    "install (likely left over from a retired/renamed service) -- "
                    f"run: sudo systemctl reset-failed {orphan['name']}"
                ),
                "severity": "error",
            })

        if services_data:
            result["available"] = True
            result["status"] = "available"
            result["services"] = services_data
            
            # Calculate summary
            result["summary"]["total"] = len(services_data)
            result["summary"]["active"] = len([s for s in services_data if s["active_state"] == "active"])
            result["summary"]["inactive"] = len([s for s in services_data if s["active_state"] == "inactive"])
            result["summary"]["failed"] = len([s for s in services_data if s["active_state"] == "failed"])
        else:
            result["error"] = "No systemd services found"
            
    except FileNotFoundError:
        result["error"] = "systemctl command not found - systemd not available"
    except Exception as exc:
        if logger:
            logger.error(f"Error collecting systemd service status: {exc}")
        result["error"] = str(exc)
    
    return result
