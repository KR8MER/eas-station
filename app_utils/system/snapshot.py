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

"""The composed system health snapshot."""

import platform
import time
from datetime import datetime
from typing import Any, Dict

import psutil

from ..formatting import format_uptime
from ..time import UTC_TZ, local_now, utc_now
from .badges import get_distro_logo_url, get_shields_io_badges
from .common import SystemHealth
from .cpu import _collect_cpu_info
from .db_health import _collect_database_health
from .dependencies import _collect_dependency_versions
from .disk_usage import _collect_disk_info
from .hardware import _collect_hardware_inventory
from .loadavg import _collect_load_averages
from .memory import _collect_memory_info
from .network import _collect_network_info
from .osinfo import _collect_operating_system_details
from .processes import _collect_process_info
from .raspberry_pi import collect_raspberry_pi_health
from .clocksync import _collect_clock_sync
from .rtc import _collect_rtc_status
from .services import _collect_systemd_services
from .smart import _collect_smart_health
from .status import _compute_overall_status
from .subsystems import _collect_gps_status, _collect_hardware_subsystems
from .temperature import _collect_temperature_readings


def build_system_health_snapshot(db, logger) -> SystemHealth:
    """Collect detailed system health metrics.

    Performance: this function runs on the single WebSocket-push thread and
    used to block for ~1.3 s every minute (psutil.cpu_percent(interval=1) +
    time.sleep(0.3) for per-process CPU sampling), stalling the 4 Hz VU-meter
    push.  Both blocking calls have been removed.  CPU samples are now taken
    with ``interval=None`` (non-blocking, reporting the delta since the last
    call); because callers cache the snapshot for ~30 s, the resulting numbers
    are meaningful 30-second averages without ever blocking the loop.
    """

    try:
        uname = platform.uname()
        boot_time = psutil.boot_time()

        os_details = _collect_operating_system_details()
        cpu_info = _collect_cpu_info()
        memory_info = _collect_memory_info()
        disk_info = _collect_disk_info()
        network_info = _collect_network_info()
        process_info = _collect_process_info()
        load_averages = _collect_load_averages()
        database_health = _collect_database_health(db, logger)

        systemd_services = _collect_systemd_services(logger)
        services_status: Dict[str, Any] = {
            service.get("display_name")
            or service.get("name")
            or f"service-{index}": service.get("status")
            for index, service in enumerate(systemd_services.get("services", []), start=1)
        }

        hardware_subsystems = _collect_hardware_subsystems(logger)
        hardware_info = _collect_hardware_inventory(logger)
        smart_info = _collect_smart_health(
            logger, hardware_info.get("block_devices", {}).get("devices") or []
        )
        temperature_info = _collect_temperature_readings(logger, smart_info)

        # Build the health data structure
        health_data = {
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
            "system": {
                "hostname": uname.node,
                "system": uname.system,
                "release": uname.release,
                "version": uname.version,
                "machine": uname.machine,
                "processor": uname.processor,
                "boot_time": datetime.fromtimestamp(boot_time, UTC_TZ).isoformat(),
                "uptime_seconds": time.time() - boot_time,
                **os_details,
            },
            "cpu": cpu_info,
            "memory": memory_info,
            "disk": disk_info,
            "network": network_info,
            "processes": process_info,
            "load_averages": load_averages,
            "database": database_health,
            "services": services_status,
            "systemd": systemd_services,
            "temperature": temperature_info,
            "hardware": hardware_info,
            "hardware_subsystems": hardware_subsystems,
            "smart": smart_info,
            "dependencies": _collect_dependency_versions(logger),
            "gps": _collect_gps_status(logger),
            "rtc": _collect_rtc_status(logger),
            "clock_sync": _collect_clock_sync(logger),
            "raspberry_pi": collect_raspberry_pi_health(
                logger, hardware_info.get("platform")
            ),
        }

        # Add shields.io badges and distro logo
        health_data["shields_badges"] = get_shields_io_badges(health_data)
        health_data["distro_logo_url"] = get_distro_logo_url(os_details.get("distribution_id"))

        uptime_seconds = health_data["system"].get("uptime_seconds")
        if isinstance(uptime_seconds, (int, float)):
            health_data["system"]["uptime_human"] = format_uptime(uptime_seconds)

        # Compute overall status and summary for the header indicator
        status, status_summary, status_reasons = _compute_overall_status(
            cpu_info["cpu_usage_percent"],
            memory_info["percentage"],
            database_health["status"],
            systemd_services,
        )

        health_data["status"] = status
        health_data["status_summary"] = status_summary
        health_data["status_reasons"] = status_reasons

        return health_data

    except Exception as exc:  # pragma: no cover - defensive logging only
        logger.error("Error getting system health: %s", exc)
        return {
            "error": str(exc),
            "timestamp": utc_now().isoformat(),
            "local_timestamp": local_now().isoformat(),
        }
