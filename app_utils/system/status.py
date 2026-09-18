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

"""Overall health status derived from the collected snapshot figures."""

from typing import Any, Dict, List, Tuple


def _compute_overall_status(
    cpu_usage_percent: float,
    memory_percent: float,
    db_status: str,
    systemd_services: Dict[str, Any],
) -> Tuple[str, str, List[str]]:
    """Roll CPU, memory, database and systemd figures into one status for
    the header indicator: ``(status, status_summary, status_reasons)``."""

    status = "healthy"
    status_reasons: List[str] = []

    # Check CPU usage
    if cpu_usage_percent >= 90:
        status = "critical"
        status_reasons.append(f"CPU usage is {cpu_usage_percent:.1f}%")
    elif cpu_usage_percent >= 75:
        if status != "critical":
            status = "warning"
        status_reasons.append(f"CPU usage is {cpu_usage_percent:.1f}%")

    # Check memory usage
    if memory_percent >= 92:
        status = "critical"
        status_reasons.append(f"Memory usage is {memory_percent:.1f}%")
    elif memory_percent >= 80:
        if status != "critical":
            status = "warning"
        status_reasons.append(f"Memory usage is {memory_percent:.1f}%")

    # Check database status
    if db_status != "connected":
        status = "critical"
        status_reasons.append(f"Database: {db_status}")

    # Check systemd services
    systemd_status = systemd_services.get("status", "unknown")
    if systemd_status == "degraded":
        if status != "critical":
            status = "warning"
        failed_count = systemd_services.get("summary", {}).get("failed", 0)
        status_reasons.append(f"{failed_count} service(s) failed")
    elif systemd_status == "stopped":
        status = "critical"
        status_reasons.append("All services stopped")

    # Build status summary
    if status == "healthy":
        status_summary = "All systems operational"
    elif status_reasons:
        status_summary = "; ".join(status_reasons[:2])  # Show up to 2 reasons
    else:
        status_summary = "System status unknown"

    return status, status_summary, status_reasons
