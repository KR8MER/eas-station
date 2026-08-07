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

"""Shields.io badge and distro logo URLs for the health page."""

from typing import Any, Dict, Optional


def get_distro_logo_url(distro_id: Optional[str]) -> Optional[str]:
    """Return logo URL for common Linux distributions."""
    
    # Map distribution IDs to their logo URLs
    distro_logos = {
        "ubuntu": "https://assets.ubuntu.com/v1/29985a98-ubuntu-logo32.png",
        "debian": "https://www.debian.org/logos/openlogo-nd-50.png",
        "fedora": "https://fedoraproject.org/assets/images/fedora-coreos-logo.png",
        "centos": "https://www.centos.org/assets/img/logo-centos-white.png",
        "rhel": "https://www.redhat.com/cms/managed-files/Logo-Red_Hat-A-Reverse-RGB.png",
        "arch": "https://archlinux.org/static/logos/archlinux-logo-dark-90dpi.ebdee92a15b3.png",
        "alpine": "https://alpinelinux.org/alpinelinux-logo.svg",
        "opensuse": "https://en.opensuse.org/images/c/cd/Button-filled-colour.png",
        "raspbian": "https://www.raspberrypi.com/app/uploads/2022/02/COLOUR-Raspberry-Pi-Symbol-Registered.png",
    }
    
    if not distro_id:
        return None
        
    distro_id_lower = distro_id.lower()
    
    # Check for exact match first
    if distro_id_lower in distro_logos:
        return distro_logos[distro_id_lower]
    
    # Check for partial matches
    for key, url in distro_logos.items():
        if key in distro_id_lower or distro_id_lower in key:
            return url
    
    return None


def _escape_shields_io_text(text: str) -> str:
    """Escape text for use in shields.io badge URLs.
    
    Shields.io uses specific escape sequences:
    - Dashes (-) must be doubled (--) as they're used as separators
    - Underscores (_) must be doubled (__) as they're used for spaces
    - Spaces can remain as-is or be replaced with underscores
    
    Args:
        text: The text to escape for shields.io
        
    Returns:
        Escaped text safe for use in shields.io badge URLs
    """
    # Replace underscores first (before dashes) to avoid double-escaping
    escaped = text.replace('_', '__')
    # Replace dashes with double dashes (shields.io separator escape)
    escaped = escaped.replace('-', '--')
    # Spaces are fine in shields.io, but we can optionally replace with underscores
    # For now, keep spaces as they're more readable
    return escaped


def get_shields_io_badges(health_data: Dict[str, Any]) -> Dict[str, str]:
    """Generate shields.io badge URLs for system metrics."""
    
    badges = {}
    system = health_data.get("system", {})
    cpu = health_data.get("cpu", {})
    memory = health_data.get("memory", {})
    
    # OS Badge
    os_name = system.get("distribution") or system.get("system") or "Unknown"
    os_version = system.get("distribution_version") or system.get("release") or ""
    if os_version:
        os_label = f"{os_name} {os_version}"
    else:
        os_label = os_name
    badges["os"] = f"https://img.shields.io/badge/OS-{_escape_shields_io_text(os_label)}-blue?style=flat-square&logo=linux"
    
    # Kernel Badge
    kernel = system.get("kernel_release") or system.get("release") or "Unknown"
    badges["kernel"] = f"https://img.shields.io/badge/Kernel-{_escape_shields_io_text(kernel)}-lightgrey?style=flat-square"
    
    # Architecture Badge
    arch = system.get("machine") or "Unknown"
    badges["architecture"] = f"https://img.shields.io/badge/Arch-{_escape_shields_io_text(arch)}-informational?style=flat-square"
    
    # Uptime Badge (format for badge)
    uptime_seconds = system.get("uptime_seconds", 0)
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    if days > 0:
        uptime_label = f"{days}d {hours}h"
    else:
        uptime_label = f"{hours}h"
    badges["uptime"] = f"https://img.shields.io/badge/Uptime-{_escape_shields_io_text(uptime_label)}-success?style=flat-square"
    
    # CPU Usage Badge
    cpu_usage = cpu.get("cpu_usage_percent", 0)
    cpu_color = "critical" if cpu_usage > 80 else "yellow" if cpu_usage > 50 else "success"
    badges["cpu"] = f"https://img.shields.io/badge/CPU-{cpu_usage:.0f}%25-{cpu_color}?style=flat-square&logo=intel"
    
    # Memory Usage Badge
    mem_usage = memory.get("percentage", 0)
    mem_color = "critical" if mem_usage > 90 else "yellow" if mem_usage > 75 else "success"
    badges["memory"] = f"https://img.shields.io/badge/Memory-{mem_usage:.0f}%25-{mem_color}?style=flat-square&logo=memory"
    
    # CPU Cores Badge
    physical_cores = cpu.get("physical_cores", 0)
    total_cores = cpu.get("total_cores", 0)
    badges["cores"] = f"https://img.shields.io/badge/Cores-{physical_cores}p/{total_cores}t-informational?style=flat-square"

    # Disk Usage Badge (root partition)
    disk_list = health_data.get("disk") or []
    root_disk = next(
        (d for d in disk_list if isinstance(d, dict) and d.get("mountpoint") == "/"),
        disk_list[0] if disk_list else None,
    )
    if root_disk and isinstance(root_disk, dict):
        disk_pct = root_disk.get("percentage", 0) or 0
        disk_color = "critical" if disk_pct > 90 else "yellow" if disk_pct > 75 else "success"
        badges["disk"] = (
            f"https://img.shields.io/badge/Disk-{disk_pct:.0f}%25-{disk_color}?style=flat-square&logo=databricks&logoColor=white"
        )

    # Load Average Badge (1-minute load)
    load_avgs = health_data.get("load_averages") or {}
    load_1m = load_avgs.get("1m") if isinstance(load_avgs, dict) else None
    if load_1m is not None:
        load_label = f"{load_1m:.2f}"
        core_count = total_cores or 4
        load_color = "critical" if load_1m > core_count else "yellow" if load_1m > core_count * 0.7 else "success"
        badges["load"] = (
            f"https://img.shields.io/badge/Load%20Avg-{_escape_shields_io_text(load_label)}-{load_color}?style=flat-square"
        )

    # Temperature Badge (highest sensor reading)
    temp_data = health_data.get("temperature") or {}
    sensors = temp_data.get("sensors") if isinstance(temp_data, dict) else None
    highest_temp: Optional[float] = None
    if isinstance(sensors, dict):
        for sensor_entries in sensors.values():
            if not isinstance(sensor_entries, list):
                continue
            for entry in sensor_entries:
                current = entry.get("current") if isinstance(entry, dict) else None
                if isinstance(current, (int, float)) and (highest_temp is None or current > highest_temp):
                    highest_temp = current
    if highest_temp is not None:
        temp_color = "critical" if highest_temp > 80 else "yellow" if highest_temp > 65 else "success"
        badges["temperature"] = (
            f"https://img.shields.io/badge/Temp-{highest_temp:.0f}%C2%B0C-{temp_color}?style=flat-square&logo=thermal&logoColor=white"
        )

    # Database Status Badge
    db_info = health_data.get("database") or {}
    db_status = db_info.get("status", "unknown") if isinstance(db_info, dict) else "unknown"
    if db_status == "connected":
        db_color = "success"
        db_label = "connected"
    elif db_status and db_status != "unknown":
        db_color = "critical"
        db_label = "error"
    else:
        db_color = "lightgrey"
        db_label = "unknown"
    badges["database"] = (
        f"https://img.shields.io/badge/Database-{db_label}-{db_color}?style=flat-square&logo=postgresql&logoColor=white"
    )

    return badges
