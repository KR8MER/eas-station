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

"""CPU, USB and platform inventory."""

import contextlib
import os
import platform
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from .block_devices import _collect_block_devices
from .common import _safe_read_text
from .device_tree import _collect_device_tree_details


def _collect_hardware_inventory(logger) -> Dict[str, Any]:
    """Gather hardware inventory details for the host."""

    cpu_details = _collect_cpu_details(logger)
    platform_details = _collect_platform_details()
    block_devices = _collect_block_devices(logger)
    usb_devices = _collect_usb_devices(logger)

    return {
        "cpu": cpu_details,
        "platform": platform_details,
        "block_devices": block_devices,
        "usb": usb_devices,
    }


def _collect_usb_devices(logger) -> Dict[str, Any]:
    """Inspect USB devices via sysfs for detailed inventory."""

    result: Dict[str, Any] = {
        "available": False,
        "devices": [],
        "summary": {"devices": 0, "hubs": 0},
        "error": None,
    }

    devices_root = Path("/sys/bus/usb/devices")
    if not devices_root.exists():
        result["error"] = "USB sysfs tree not available"
        return result

    try:
        entries = sorted(devices_root.iterdir(), key=lambda path: path.name)
    except Exception as exc:  # pragma: no cover - depends on host permissions
        result["error"] = str(exc)
        return result

    for entry in entries:
        if not entry.is_dir():
            continue

        id_vendor = _safe_read_text(entry / "idVendor")
        id_product = _safe_read_text(entry / "idProduct")
        if not id_vendor or not id_product:
            continue

        product = _safe_read_text(entry / "product")
        manufacturer = _safe_read_text(entry / "manufacturer")
        serial = _safe_read_text(entry / "serial")
        busnum = _safe_read_text(entry / "busnum")
        devnum = _safe_read_text(entry / "devnum")
        device_class = _safe_read_text(entry / "bDeviceClass")
        device_subclass = _safe_read_text(entry / "bDeviceSubClass")
        device_protocol = _safe_read_text(entry / "bDeviceProtocol")

        speed_value: Optional[float] = None
        speed_raw = _safe_read_text(entry / "speed")
        if speed_raw:
            with contextlib.suppress(ValueError):
                speed_value = float(speed_raw)

        driver = None
        driver_path = entry / "driver"
        if driver_path.exists():
            with contextlib.suppress(OSError):
                target = os.readlink(driver_path)
                driver = os.path.basename(target)

        interface_classes: List[str] = []
        for interface_dir in entry.iterdir():
            if not interface_dir.is_dir():
                continue
            class_value = _safe_read_text(interface_dir / "bInterfaceClass")
            if class_value:
                interface_classes.append(class_value)

        device_entry = {
            "path": entry.name,
            "vendor_id": id_vendor,
            "product_id": id_product,
            "manufacturer": manufacturer,
            "product": product,
            "serial": serial,
            "bus_number": busnum,
            "device_number": devnum,
            "device_class": device_class,
            "device_subclass": device_subclass,
            "device_protocol": device_protocol,
            "speed_mbps": speed_value,
            "driver": driver,
            "interfaces": interface_classes,
            "is_hub": (device_class or "").lower() in {"09", "9"},
        }

        result["devices"].append(device_entry)

    result["summary"]["devices"] = len(result["devices"])
    result["summary"]["hubs"] = sum(1 for device in result["devices"] if device.get("is_hub"))

    if result["devices"]:
        result["available"] = True
    else:
        result["error"] = result.get("error") or "No USB devices detected"

    return result


def _collect_cpu_details(logger) -> Dict[str, Any]:
    """Return static CPU capabilities and metadata."""

    cpu_freq = psutil.cpu_freq()

    details: Dict[str, Any] = {
        "model_name": None,
        "vendor_id": None,
        "architecture": platform.machine() or None,
        "processor": platform.processor() or None,
        "cache_size": None,
        "microcode": None,
        "stepping": None,
        "family": None,
        "model": None,
        "hardware": None,
        "revision": None,
        "serial": None,
        "cpu_implementer": None,
        "cpu_part": None,
        "flags": [],
        "supports_virtualization": None,
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "max_frequency": cpu_freq.max if cpu_freq else None,
        "min_frequency": cpu_freq.min if cpu_freq else None,
    }

    try:
        cpuinfo_path = Path("/proc/cpuinfo")
        if cpuinfo_path.exists():
            content = cpuinfo_path.read_text(encoding="utf-8", errors="ignore")
            sections = [segment for segment in content.split("\n\n") if segment.strip()]
            merged_fields: Dict[str, str] = {}
            features: List[str] = []

            for section in sections:
                for line in section.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    key = key.strip().lower()
                    value = value.strip()
                    if not value:
                        continue

                    merged_fields.setdefault(key, value)

                    if key in {"flags", "features"}:
                        features.extend(flag.strip() for flag in value.split() if flag.strip())

            def _set_from_fields(target: str, *candidates: str) -> None:
                for candidate in candidates:
                    value = merged_fields.get(candidate)
                    if value:
                        details[target] = value
                        return

            _set_from_fields("model_name", "model name", "model")
            _set_from_fields("vendor_id", "vendor_id", "cpu implementer")
            _set_from_fields("microcode", "microcode")
            _set_from_fields("stepping", "stepping", "cpu revision")
            _set_from_fields("family", "cpu family", "cpu architecture")
            _set_from_fields("model", "model")
            _set_from_fields("cache_size", "cache size")
            _set_from_fields("hardware", "hardware")
            _set_from_fields("revision", "revision")
            _set_from_fields("serial", "serial")
            _set_from_fields("cpu_implementer", "cpu implementer")
            _set_from_fields("cpu_part", "cpu part")

            if features:
                details["flags"] = sorted(set(features))

            virtualization_field = merged_fields.get("virtualization")
            if virtualization_field:
                lowered = virtualization_field.strip().lower()
                if lowered in {"vt-x", "svm", "hardware", "full"}:
                    details["supports_virtualization"] = True
                elif lowered in {"none", "n/a", "no"}:
                    details["supports_virtualization"] = False
    except Exception as exc:  # pragma: no cover - depends on host filesystem
        if logger:
            logger.debug("Failed to parse /proc/cpuinfo: %s", exc)

    flags_set = set(details.get("flags") or [])
    if flags_set:
        if details["supports_virtualization"] is None:
            details["supports_virtualization"] = any(flag in {"vmx", "svm"} for flag in flags_set)

    return details


def _collect_platform_details() -> Dict[str, Any]:
    """Return chassis / firmware metadata using DMI and device-tree sources."""

    details: Dict[str, Any] = {}
    has_dmi = False

    base_path = Path("/sys/devices/virtual/dmi/id")
    if base_path.exists():
        fields = {
            "sys_vendor": "sys_vendor",
            "product_name": "product_name",
            "product_version": "product_version",
            "product_serial": "product_serial",
            "board_name": "board_name",
            "board_vendor": "board_vendor",
            "board_version": "board_version",
            "chassis_asset_tag": "chassis_asset_tag",
            "bios_vendor": "bios_vendor",
            "bios_version": "bios_version",
            "bios_date": "bios_date",
        }

        for key, filename in fields.items():
            value = _safe_read_text(base_path / filename)
            if value is not None:
                details[key] = value
                has_dmi = True

    # Augment with device-tree metadata when available (common on ARM boards).
    dt_details = _collect_device_tree_details()
    if dt_details:
        for key, value in dt_details.items():
            details.setdefault(key, value)
        
        # If we have device-tree data but no DMI BIOS info, mark BIOS fields as not applicable
        if dt_details and not has_dmi:
            # Remove any empty/placeholder BIOS fields that might confuse the UI
            for bios_key in ["bios_vendor", "bios_version", "bios_date"]:
                if bios_key in details and not details[bios_key]:
                    del details[bios_key]

    return details
