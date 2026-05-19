"""GPS HAT diagnostic probes.

Inspects every prerequisite for a working GPS/RTC HAT setup on a
Raspberry Pi running Pi OS — RTC chip vs overlay coherence, PPS device
presence, gpsd / chrony / package state, ``/boot/firmware/config.txt``
overlays, and the well-known failure modes we have seen in the field
(RV-3028 PORF, baud-rate mismatch, ``hwclock`` missing on Bookworm,
serial-port contention between gpsd and the EAS Station hardware
service).

This module is **read-only**. It runs as the unprivileged web service
user and never invokes ``sudo``, ``apt``, or ``systemctl --change``.
Any probe that needs root context (e.g. reading ``/etc/default/gpsd``
which is world-readable, ``lsof`` of ``/dev/serial0`` which is not)
is wrapped in a try/except and degrades to ``unknown`` on permission
errors so the rest of the report still renders.

The single public entry point is ``collect_gps_hat_diagnostics()``,
which returns a JSON-serialisable dict that the admin UI consumes via
``/api/admin/gps-hat/diagnostics`` (added in the API layer).
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Knowledge base — what we expect on a healthy install. Keep flat and
# documented so the UI can render the same constants without re-deriving.
# ---------------------------------------------------------------------------

# Boot config locations Pi OS uses; first existing path wins.
_CONFIG_TXT_CANDIDATES: Tuple[str, ...] = (
    "/boot/firmware/config.txt",  # Pi OS Bookworm and newer
    "/boot/config.txt",           # Pi OS Bullseye and older
)

# Map of RTC kernel-driver names → human label, expected I²C address, and
# the dtoverlay token that the user should have in config.txt.
_RTC_CHIPS: Dict[str, Dict[str, str]] = {
    "ds3231":  {"label": "DS3231",   "addr": "0x68", "overlay": "ds3231"},
    "rv3028":  {"label": "RV-3028",  "addr": "0x52", "overlay": "rv3028"},
    "ds1307":  {"label": "DS1307",   "addr": "0x68", "overlay": "ds1307"},
    "pcf8523": {"label": "PCF8523",  "addr": "0x68", "overlay": "pcf8523"},
    "pcf85063": {"label": "PCF85063", "addr": "0x51", "overlay": "pcf85063"},
}

# Packages we expect for the full GPS/PPS/chrony chain. Annotated so the UI
# can decide which ones are required vs nice-to-have.
_PACKAGES: Tuple[Tuple[str, str, bool], ...] = (
    # (apt name, role, required-for-time-sync)
    ("chrony",            "Time synchronization daemon",          True),
    ("gpsd",              "GPS multiplexer",                      True),
    ("gpsd-clients",      "cgps / gpspipe diagnostic tools",     False),
    ("pps-tools",         "ppstest diagnostic command",          False),
    ("util-linux-extra",  "hwclock command (Bookworm and newer)", True),
    ("i2c-tools",         "i2cdetect for RTC verification",      False),
)


# ---------------------------------------------------------------------------
# Tiny helpers
# ---------------------------------------------------------------------------

def _read(path: Path | str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except Exception:
        return None


def _run(cmd: List[str], timeout: float = 3.0) -> Tuple[int, str, str]:
    """Run a command, capturing stdout/stderr. Never raises."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout or "", result.stderr or ""
    except FileNotFoundError:
        return 127, "", "command not found"
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return -1, "", str(exc)


def _which(cmd: str) -> Optional[str]:
    return shutil.which(cmd)


def _config_txt_path() -> Optional[str]:
    for candidate in _CONFIG_TXT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Subsystem probes — each one returns a dict and never raises.
# ---------------------------------------------------------------------------

def _probe_rtc() -> Dict[str, Any]:
    """Inspect /sys/class/rtc/rtc0 and detect chip + drift / PORF state."""
    out: Dict[str, Any] = {
        "device_present": False,
        "kernel_name": None,
        "detected_chip": None,
        "chip_label": None,
        "expected_addr": None,
        "expected_overlay": None,
        "is_battery_backed": False,
        "porf_set": None,
        "since_epoch": None,
        "drift_seconds": None,
        "drift_status": "unknown",
    }
    rtc_dir = Path("/sys/class/rtc/rtc0")
    if not rtc_dir.exists():
        return out
    out["device_present"] = True

    name = _read(rtc_dir / "name")
    if name:
        out["kernel_name"] = name
        lowered = name.lower()
        for chip_key, info in _RTC_CHIPS.items():
            if chip_key in lowered:
                out["detected_chip"] = chip_key
                out["chip_label"] = info["label"]
                out["expected_addr"] = info["addr"]
                out["expected_overlay"] = f"i2c-rtc,{info['overlay']}"
                out["is_battery_backed"] = True
                break

    # since_epoch is None / 0 / -EINVAL when the rv3028 driver refuses to
    # return time because PORF is set. We treat any of those as "porf_set".
    raw = _read(rtc_dir / "since_epoch")
    try:
        seconds = int(raw) if raw else 0
    except ValueError:
        seconds = 0

    if seconds > 0:
        out["since_epoch"] = seconds
        out["porf_set"] = False
        try:
            drift = float(seconds) - datetime.now(timezone.utc).timestamp()
            out["drift_seconds"] = round(drift, 3)
            ad = abs(drift)
            if ad < 2:
                out["drift_status"] = "in_sync"
            elif ad < 60:
                out["drift_status"] = "minor"
            elif ad < 3600:
                out["drift_status"] = "moderate"
            else:
                out["drift_status"] = "severe"
        except Exception:
            out["drift_status"] = "unknown"
    else:
        # An rv3028 with PORF set has since_epoch of 0 / EINVAL; treat as PORF
        # if we know the chip is one that latches that flag, otherwise just
        # report "unreadable" without making a claim.
        if out["detected_chip"] in ("rv3028", "ds3231"):
            out["porf_set"] = True
            out["drift_status"] = "unreadable"
        else:
            out["drift_status"] = "unreadable"

    return out


def _probe_i2c(expected_addr: Optional[str]) -> Dict[str, Any]:
    """Run i2cdetect (if available) and parse seen addresses on bus 1."""
    out: Dict[str, Any] = {
        "tool_present": _which("i2cdetect") is not None,
        "bus_scanned": False,
        "addresses": [],
        "rtc_address_match": None,
    }
    if not out["tool_present"]:
        return out
    rc, stdout, _ = _run(["i2cdetect", "-y", "1"], timeout=4.0)
    if rc != 0:
        return out
    out["bus_scanned"] = True
    addrs: List[str] = []
    # i2cdetect output: rows like "60: -- -- 62 -- -- 65 -- -- -- -- -- -- -- -- -- --"
    for line in stdout.splitlines():
        m = re.match(r"^([0-9a-f]{2}):\s+(.*)$", line.strip(), re.IGNORECASE)
        if not m:
            continue
        row_base = int(m.group(1), 16)
        for col, cell in enumerate(m.group(2).split()):
            cell = cell.strip()
            if cell and cell.lower() != "--" and cell.lower() != "uu":
                try:
                    addr = int(cell, 16)
                except ValueError:
                    continue
                addrs.append(f"0x{addr:02x}")
        # row_base is just for parser clarity; cell value is the absolute addr
        _ = row_base
    out["addresses"] = sorted(set(addrs))
    if expected_addr:
        out["rtc_address_match"] = expected_addr.lower() in (a.lower() for a in out["addresses"])
    return out


def _probe_pps() -> Dict[str, Any]:
    """Find /sys/class/pps/ppsX devices and classify GPIO vs line-discipline."""
    out: Dict[str, Any] = {
        "devices": [],
        "gpio_device": None,
        "ldisc_devices": [],
        "ppstest_available": _which("ppstest") is not None,
    }
    base = Path("/sys/class/pps")
    if not base.exists():
        return out
    for entry in sorted(base.iterdir()):
        if not entry.name.startswith("pps"):
            continue
        info: Dict[str, Any] = {"name": entry.name, "path": str(entry)}
        # Resolve device link to discriminate gpio vs line-discipline
        try:
            target = os.fspath((entry / "device").resolve())
        except Exception:
            target = ""
        info["device_target"] = target
        # last-known assert sequence (proves pulses are arriving)
        assert_raw = _read(entry / "assert")
        if assert_raw and "#" in assert_raw:
            ts_part, _, seq_part = assert_raw.partition("#")
            try:
                info["assert_sequence"] = int(seq_part)
            except ValueError:
                info["assert_sequence"] = None
            info["assert_raw"] = assert_raw
        else:
            info["assert_sequence"] = None
        if "/tty/" in target or Path(target).name.startswith("tty"):
            info["kind"] = "line_discipline"
            out["ldisc_devices"].append(info)
        else:
            info["kind"] = "gpio"
            if out["gpio_device"] is None:
                out["gpio_device"] = info
        out["devices"].append(info)
    return out


def _probe_serial(expected_baud: int = 9600) -> Dict[str, Any]:
    """Look at /dev/serial0 → resolved tty, and try lsof for current owner."""
    out: Dict[str, Any] = {
        "device": "/dev/serial0",
        "exists": False,
        "resolved": None,
        "owner": "unknown",
        "expected_baud": expected_baud,
    }
    dev = Path("/dev/serial0")
    if dev.exists():
        out["exists"] = True
        try:
            out["resolved"] = os.fspath(dev.resolve())
        except Exception:
            out["resolved"] = None
    # lsof is privileged for /dev/tty* — best-effort; users running this
    # behind a unit with CAP_SYS_PTRACE may see results, otherwise None.
    if _which("lsof"):
        rc, stdout, _ = _run(["lsof", "-Fcp", "/dev/serial0"], timeout=2.0)
        if rc == 0 and stdout.strip():
            owners: List[str] = []
            pid: Optional[str] = None
            for line in stdout.splitlines():
                if line.startswith("p"):
                    pid = line[1:]
                elif line.startswith("c") and pid:
                    owners.append(f"{line[1:]} (pid {pid})")
                    pid = None
            if owners:
                out["owner"] = ", ".join(owners)
            else:
                out["owner"] = "free"
        elif rc == 0:
            out["owner"] = "free"
    return out


def _probe_packages() -> Dict[str, Any]:
    """Use dpkg-query for each well-known package."""
    out: Dict[str, Any] = {"items": [], "missing_required": []}
    have_dpkg = _which("dpkg-query") is not None
    out["dpkg_available"] = have_dpkg
    for name, role, required in _PACKAGES:
        item = {"name": name, "role": role, "required": required, "installed": False, "version": None}
        if have_dpkg:
            rc, stdout, _ = _run(
                ["dpkg-query", "-W", "-f=${Status}|${Version}", name], timeout=2.0
            )
            if rc == 0 and "install ok installed" in stdout:
                item["installed"] = True
                _, _, ver = stdout.partition("|")
                item["version"] = ver.strip() or None
        out["items"].append(item)
        if required and not item["installed"]:
            out["missing_required"].append(name)
    return out


def _probe_services() -> Dict[str, Any]:
    """Query systemctl is-active / is-enabled for the relevant units."""
    out: Dict[str, Any] = {"items": []}
    units = ("chrony.service", "gpsd.service", "gpsd.socket")
    for unit in units:
        active = "unknown"
        enabled = "unknown"
        rc, stdout, _ = _run(["systemctl", "is-active", unit], timeout=2.0)
        if rc in (0, 3):  # 0 active, 3 inactive — both authoritative
            active = stdout.strip() or "unknown"
        rc, stdout, _ = _run(["systemctl", "is-enabled", unit], timeout=2.0)
        if rc in (0, 1):
            enabled = stdout.strip() or "unknown"
        out["items"].append({"unit": unit, "active": active, "enabled": enabled})
    return out


def _probe_gpsd_config() -> Dict[str, Any]:
    """Parse /etc/default/gpsd."""
    out: Dict[str, Any] = {
        "path": "/etc/default/gpsd",
        "exists": False,
        "devices": None,
        "options": None,
        "has_n_flag": False,
        "has_b_flag": False,
        "baud_flag": None,
    }
    text = _read(out["path"])
    if text is None:
        return out
    out["exists"] = True
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.strip().strip('"').strip("'")
        if key.strip() == "DEVICES":
            out["devices"] = val
        elif key.strip() == "GPSD_OPTIONS":
            out["options"] = val
            tokens = val.split()
            out["has_n_flag"] = "-n" in tokens
            out["has_b_flag"] = "-b" in tokens
            for i, tok in enumerate(tokens):
                if tok == "-s" and i + 1 < len(tokens):
                    try:
                        out["baud_flag"] = int(tokens[i + 1])
                    except ValueError:
                        pass
                elif tok.startswith("-s") and len(tok) > 2:
                    try:
                        out["baud_flag"] = int(tok[2:])
                    except ValueError:
                        pass
    return out


def _probe_chrony_config() -> Dict[str, Any]:
    """Parse /etc/chrony/chrony.conf for rtcsync, PPS / SHM refclock, pool."""
    out: Dict[str, Any] = {
        "path": "/etc/chrony/chrony.conf",
        "exists": False,
        "rtcsync_enabled": False,
        "has_pps_refclock": False,
        "has_shm_refclock": False,
        "pool_lines": [],
    }
    text = _read(out["path"])
    if text is None:
        return out
    out["exists"] = True
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line == "rtcsync" or line.startswith("rtcsync "):
            out["rtcsync_enabled"] = True
        elif line.startswith("refclock"):
            tokens = line.split()
            if len(tokens) >= 2:
                if tokens[1].upper() == "PPS":
                    out["has_pps_refclock"] = True
                elif tokens[1].upper() == "SHM":
                    out["has_shm_refclock"] = True
        elif line.startswith("pool ") or line.startswith("server "):
            out["pool_lines"].append(line)
    return out


def _probe_chrony_runtime() -> Dict[str, Any]:
    """Ask chronyc for the currently selected source, if chronyd is up."""
    out: Dict[str, Any] = {
        "tool_present": _which("chronyc") is not None,
        "tracking_ok": False,
        "selected_source": None,
        "stratum": None,
        "leap_status": None,
        "system_time_offset_seconds": None,
        "last_offset_seconds": None,
        "root_dispersion_seconds": None,
        "sources": [],
    }
    if not out["tool_present"]:
        return out
    rc, stdout, _ = _run(["chronyc", "-c", "tracking"], timeout=2.0)
    if rc != 0:
        return out
    out["tracking_ok"] = True
    parts = [p.strip() for p in stdout.strip().split(",")]
    # chronyc -c tracking format (chrony ≥4.x):
    #   0:ref_id_hex 1:ref_id_name 2:stratum 3:ref_time
    #   4:system_time_offset 5:last_offset 6:rms_offset 7:frequency
    #   8:residual_freq 9:skew 10:root_delay 11:root_dispersion
    #   12:update_interval 13:leap_status
    if len(parts) >= 2:
        out["selected_source"] = parts[1] or None
    if len(parts) >= 3:
        try:
            out["stratum"] = int(parts[2])
        except ValueError:
            pass
    if len(parts) >= 5:
        try:
            out["system_time_offset_seconds"] = float(parts[4])
            # Keep last_offset_seconds for backwards compatibility — older
            # callers expected this name. New callers should prefer the
            # named field above.
            out["last_offset_seconds"] = float(parts[4])
        except ValueError:
            pass
    if len(parts) >= 12:
        try:
            out["root_dispersion_seconds"] = float(parts[11])
        except ValueError:
            pass
    if len(parts) >= 14:
        out["leap_status"] = parts[13] or None

    # Source table: useful for surfacing GPS / PPS Reach=0 (the classic
    # port-contention symptom).
    rc2, stdout2, _ = _run(["chronyc", "-c", "sources"], timeout=2.0)
    if rc2 == 0 and stdout2.strip():
        sources: List[Dict[str, Any]] = []
        # CSV format (chrony ≥4.x):
        #   M,S,Name,Stratum,Poll,Reach,LastRx,LastSample,...
        for raw in stdout2.strip().splitlines():
            cols = [c.strip() for c in raw.split(",")]
            if len(cols) < 6:
                continue
            try:
                reach_octal = int(cols[5])
            except ValueError:
                reach_octal = None
            sources.append({
                "mode": cols[0],
                "state": cols[1],
                "name": cols[2],
                "stratum": int(cols[3]) if cols[3].isdigit() else None,
                "reach": reach_octal,
                "last_rx_seconds": int(cols[6]) if len(cols) > 6 and cols[6].lstrip("-").isdigit() else None,
            })
        out["sources"] = sources
        # Convenient flag: any refclock (M="#") that's stuck at reach=0
        # almost always means the source isn't actually getting samples
        # — for this codebase that's the gpsd-can't-read-serial-port
        # symptom, called out in the action recommender below.
        out["refclocks_unreached"] = [
            s["name"] for s in sources
            if s.get("mode") == "#" and s.get("reach") == 0
        ]
    return out


def _probe_config_txt(rtc_overlay: Optional[str], expected_pps_pin: int) -> Dict[str, Any]:
    """Parse the active /boot/firmware/config.txt for the relevant overlay lines."""
    out: Dict[str, Any] = {
        "path": _config_txt_path(),
        "exists": False,
        "i2c_arm_on": False,
        "i2c_rtc_overlay_line": None,
        "i2c_rtc_overlay_match": None,
        "pps_gpio_overlay_line": None,
        "pps_gpio_pin_in_config": None,
        "pps_pin_match": None,
    }
    if not out["path"]:
        return out
    text = _read(out["path"])
    if text is None:
        return out
    out["exists"] = True
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("dtparam=") and "i2c_arm=on" in line:
            out["i2c_arm_on"] = True
        if line.startswith("dtoverlay=i2c-rtc"):
            out["i2c_rtc_overlay_line"] = line
            if rtc_overlay:
                out["i2c_rtc_overlay_match"] = rtc_overlay in line
        if line.startswith("dtoverlay=pps-gpio"):
            out["pps_gpio_overlay_line"] = line
            m = re.search(r"gpiopin=(\d+)", line)
            if m:
                pin = int(m.group(1))
                out["pps_gpio_pin_in_config"] = pin
                out["pps_pin_match"] = pin == expected_pps_pin
    return out


# ---------------------------------------------------------------------------
# Action recommender — turn raw probe data into a checklist with shell
# commands the user can copy-paste.
# ---------------------------------------------------------------------------

def _build_actions(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Translate raw probe data into a checklist of issues. Each entry
    that has a corresponding helper command also gets a ``runner``
    field describing the endpoint and body the UI should POST when
    the operator clicks "Run". Actions without a ``runner`` stay
    copy-paste-only (e.g. PPS pin mismatch with EAS Station settings,
    which is solved by editing the form, not by a privileged action).
    """
    actions: List[Dict[str, Any]] = []
    rtc = report["rtc"]
    pkg = report["packages"]
    gpsd_cfg = report["gpsd_config"]
    chrony_cfg = report["chrony_config"]
    chrony_run = report["chrony_runtime"]
    config_txt = report["config_txt"]
    pps = report["pps"]
    serial = report["serial"]
    expected_baud = serial.get("expected_baud", 9600)
    expected_pps_pin = report.get("expected_pps_pin", 18)

    # 1. Missing packages
    missing = [item for item in pkg["items"] if item["required"] and not item["installed"]]
    if missing:
        names = " ".join(item["name"] for item in missing)
        package_list = [item["name"] for item in missing]
        actions.append({
            "id": "install_packages",
            "severity": "error",
            "label": f"Install missing packages: {names}",
            "reason": "Required packages are not installed; the time-sync chain cannot run without them.",
            "command": f"sudo apt update && sudo apt install -y {names}",
            "runner": {
                "endpoint": "/admin/hardware/gps-hat/apt-install",
                "body": {"packages": package_list, "update_first": True},
                "button_label": "Install",
                "confirm": (
                    "This will run apt update and install: "
                    + ", ".join(package_list)
                    + ". Continue?"
                ),
            },
        })

    # 2. RTC chip vs overlay mismatch
    if rtc["detected_chip"] and rtc["expected_overlay"]:
        actual_line = config_txt.get("i2c_rtc_overlay_line")
        # Helper takes overlay name without the "i2c-rtc," prefix; we already
        # have that as the chip name baked into expected_overlay.
        chip_only = rtc["expected_overlay"].split(",", 1)[1] if "," in rtc["expected_overlay"] else rtc["expected_overlay"]
        if not actual_line:
            actions.append({
                "id": "config_rtc_overlay",
                "severity": "warning",
                "label": f"Add {rtc['expected_overlay']} overlay to {config_txt['path']}",
                "reason": f"Detected {rtc['chip_label']} RTC but no i2c-rtc overlay line is in config.txt.",
                "command": f"echo 'dtoverlay={rtc['expected_overlay']}' | sudo tee -a {config_txt['path']}",
                "requires_reboot": True,
                "runner": {
                    "endpoint": "/admin/hardware/gps-hat/config-txt-overlay",
                    "body": {"overlay": "i2c-rtc", "params": chip_only},
                    "button_label": "Add overlay",
                    "confirm": f"Add 'dtoverlay=i2c-rtc,{chip_only}' to {config_txt['path']}? You'll need to reboot for it to take effect.",
                },
            })
        elif config_txt.get("i2c_rtc_overlay_match") is False:
            actions.append({
                "id": "fix_rtc_overlay",
                "severity": "warning",
                "label": f"Replace RTC overlay with {rtc['expected_overlay']}",
                "reason": f"Overlay in config.txt does not match the {rtc['chip_label']} chip detected on the bus.",
                "command": (
                    f"sudo sed -i 's|^dtoverlay=i2c-rtc.*|dtoverlay={rtc['expected_overlay']}|' "
                    f"{config_txt['path']}"
                ),
                "requires_reboot": True,
                "runner": {
                    "endpoint": "/admin/hardware/gps-hat/config-txt-overlay",
                    "body": {"overlay": "i2c-rtc", "params": chip_only},
                    "button_label": "Replace overlay",
                    "confirm": (
                        f"Replace existing dtoverlay=i2c-rtc line in {config_txt['path']} "
                        f"with 'dtoverlay=i2c-rtc,{chip_only}'? You'll need to reboot."
                    ),
                },
            })

    # 3. RV-3028 / DS3231 PORF — needs hwclock -w after system clock is sane
    if rtc.get("porf_set"):
        actions.append({
            "id": "seed_rtc",
            "severity": "warning",
            "label": "Seed RTC from system clock (clears PORF)",
            "reason": (
                f"{rtc.get('chip_label') or 'RTC'} reports power-on-reset flag set. "
                "After the system clock is synchronized, write it back to the RTC to clear the flag."
            ),
            "command": "timedatectl && sudo hwclock -w && sudo hwclock -r",
            "preconditions": ["System clock must be synchronized (chrony or NTP)."],
            "runner": {
                "endpoint": "/admin/hardware/gps-hat/seed-rtc",
                "body": {},
                "button_label": "Seed RTC",
                "extra_params": [
                    {
                        "name": "force_unsynced",
                        "type": "boolean",
                        "default": False,
                        "label": "Force even if system clock isn't NTP-synchronized (footgun)",
                    },
                ],
            },
        })

    # 4. PPS overlay missing or wrong pin
    if config_txt.get("pps_gpio_overlay_line") is None:
        actions.append({
            "id": "config_pps_overlay",
            "severity": "info",
            "label": f"Add pps-gpio overlay (gpiopin={expected_pps_pin}) to config.txt",
            "reason": "PPS time discipline requires the pps-gpio kernel overlay.",
            "command": f"echo 'dtoverlay=pps-gpio,gpiopin={expected_pps_pin}' | sudo tee -a {config_txt['path']}",
            "requires_reboot": True,
            "runner": {
                "endpoint": "/admin/hardware/gps-hat/config-txt-overlay",
                "body": {"overlay": "pps-gpio", "params": f"gpiopin={expected_pps_pin}"},
                "button_label": "Add PPS overlay",
                "confirm": (
                    f"Add 'dtoverlay=pps-gpio,gpiopin={expected_pps_pin}' to {config_txt['path']}? "
                    "You'll need to reboot for /dev/pps0 to appear."
                ),
            },
        })
    elif config_txt.get("pps_pin_match") is False:
        # No runner: this is a settings/UI mismatch the user should resolve in
        # the GPS receiver form, not by re-flashing the dtoverlay.
        actions.append({
            "id": "fix_pps_pin",
            "severity": "warning",
            "label": "PPS GPIO pin in config.txt does not match EAS Station settings",
            "reason": (
                f"config.txt has gpiopin={config_txt.get('pps_gpio_pin_in_config')}, "
                f"but EAS Station expects {expected_pps_pin}."
            ),
            "command": "Edit the dtoverlay=pps-gpio line in config.txt to match your HAT.",
        })

    # 5. gpsd config — needs DEVICES + -n + correct baud
    gpsd_installed = any(p["name"] == "gpsd" and p["installed"] for p in pkg["items"])
    if gpsd_installed:
        if not gpsd_cfg.get("exists"):
            actions.append({
                "id": "write_gpsd_default",
                "severity": "warning",
                "label": "Write /etc/default/gpsd",
                "reason": "gpsd is installed but /etc/default/gpsd is missing.",
                "command": (
                    "sudo tee /etc/default/gpsd <<'EOF'\n"
                    'DEVICES="/dev/serial0 /dev/pps0"\n'
                    f'GPSD_OPTIONS="-n -b -s {expected_baud}"\n'
                    'START_DAEMON="true"\n'
                    'USBAUTO="false"\n'
                    "EOF"
                ),
                "runner": {
                    "endpoint": "/admin/hardware/gps-hat/gpsd-config",
                    "body": {
                        "devices": ["/dev/serial0", "/dev/pps0"],
                        "options": f"-n -b -s {expected_baud}",
                        "start_daemon": True,
                        "usbauto": False,
                    },
                    "button_label": "Write gpsd config",
                },
            })
        else:
            issues = []
            if not gpsd_cfg.get("has_n_flag"):
                issues.append("missing -n (gpsd will idle until clients connect)")
            if gpsd_cfg.get("baud_flag") and gpsd_cfg["baud_flag"] != expected_baud:
                issues.append(f"baud is {gpsd_cfg['baud_flag']} but the HAT runs at {expected_baud}")
            if not gpsd_cfg.get("baud_flag"):
                issues.append(f"no -s flag (will auto-detect; force -s {expected_baud})")
            if issues:
                # Try to preserve the user's existing DEVICES line if it parses
                # cleanly; otherwise fall back to the standard pair. The helper
                # validates this against its own allowlist either way.
                existing_devs = (gpsd_cfg.get("devices") or "").split()
                preserved_devs = [d for d in existing_devs if d.startswith("/dev/")] \
                                 or ["/dev/serial0", "/dev/pps0"]
                actions.append({
                    "id": "fix_gpsd_options",
                    "severity": "warning",
                    "label": "Fix GPSD_OPTIONS in /etc/default/gpsd",
                    "reason": "; ".join(issues),
                    "command": (
                        f"sudo sed -i 's|^GPSD_OPTIONS=.*|GPSD_OPTIONS=\"-n -b -s {expected_baud}\"|' "
                        "/etc/default/gpsd && sudo systemctl restart gpsd"
                    ),
                    "runner": {
                        "endpoint": "/admin/hardware/gps-hat/gpsd-config",
                        "body": {
                            "devices": preserved_devs,
                            "options": f"-n -b -s {expected_baud}",
                            "start_daemon": True,
                            "usbauto": False,
                        },
                        "button_label": "Fix gpsd config",
                        "post_action": {
                            "endpoint": "/admin/hardware/gps-hat/systemctl",
                            "body": {"unit": "gpsd.service", "verb": "restart"},
                            "label": "restart gpsd",
                        },
                    },
                })

    # 6. chrony refclock + rtcsync
    if chrony_cfg.get("exists"):
        if not chrony_cfg.get("rtcsync_enabled"):
            actions.append({
                "id": "enable_rtcsync",
                "severity": "info",
                "label": "Enable rtcsync in chrony.conf",
                "reason": "Without rtcsync, the kernel will not periodically copy disciplined system time back to the RTC.",
                "command": "echo 'rtcsync' | sudo tee -a /etc/chrony/chrony.conf && sudo systemctl restart chrony",
                "runner": {
                    "endpoint": "/admin/hardware/gps-hat/chrony-config",
                    "body": {
                        "ensure_rtcsync": True,
                        "ensure_pps_refclock": False,
                        "pps_device": "/dev/pps0",
                    },
                    "button_label": "Enable rtcsync",
                    "post_action": {
                        "endpoint": "/admin/hardware/gps-hat/systemctl",
                        "body": {"unit": "chrony.service", "verb": "restart"},
                        "label": "restart chrony",
                    },
                },
            })
        if pps.get("gpio_device") and not chrony_cfg.get("has_pps_refclock"):
            actions.append({
                "id": "add_pps_refclock",
                "severity": "info",
                "label": "Add PPS refclock to chrony.conf",
                "reason": "PPS device is present but chrony is not configured to use it.",
                "command": (
                    "sudo tee -a /etc/chrony/chrony.conf <<'EOF'\n"
                    "refclock SHM 0 refid GPS precision 1e-1 offset 0.0 delay 0.2 noselect\n"
                    "refclock PPS /dev/pps0 lock GPS refid PPS\n"
                    "EOF\n"
                    "sudo systemctl restart chrony"
                ),
                "runner": {
                    "endpoint": "/admin/hardware/gps-hat/chrony-config",
                    "body": {
                        "ensure_rtcsync": True,
                        "ensure_pps_refclock": True,
                        "pps_device": "/dev/pps0",
                    },
                    "button_label": "Configure refclocks",
                    "post_action": {
                        "endpoint": "/admin/hardware/gps-hat/systemctl",
                        "body": {"unit": "chrony.service", "verb": "restart"},
                        "label": "restart chrony",
                    },
                },
            })

    # 7. chrony tracking — call it out if it's not running
    if not chrony_run.get("tracking_ok"):
        actions.append({
            "id": "start_chrony",
            "severity": "warning",
            "label": "Start the chrony service",
            "reason": "chronyc is not responding — system clock is not being disciplined.",
            "command": "sudo systemctl enable --now chrony",
            "runner": {
                "endpoint": "/admin/hardware/gps-hat/systemctl",
                "body": {"unit": "chrony.service", "verb": "enable", "now": True},
                "button_label": "Enable + start",
            },
        })

    # 8. GPS/PPS refclocks configured but never reaching chrony. This is
    #    the port-contention symptom: gpsd is configured for /dev/serial0
    #    (which resolves to /dev/ttyAMAN on Pi 5) but EAS Station's
    #    hardware service has the same port open. gpsd never gets NMEA,
    #    SHM 0 stays empty, the `lock GPS` constraint on PPS never fires,
    #    and chrony falls back to internet NTP at stratum ≥ 2. There is
    #    no one-click fix yet — properly resolving it needs Tier 3
    #    (gpsd-as-NMEA-source mode in gps_manager.py).
    unreached = chrony_run.get("refclocks_unreached") or []
    if unreached and serial.get("exists"):
        # Only surface when chrony itself is otherwise healthy — if chrony
        # isn't tracking yet there are bigger fish to fry.
        if chrony_run.get("tracking_ok"):
            current_stratum = chrony_run.get("stratum")
            stratum_note = (
                f" (currently stratum {current_stratum} via internet NTP)"
                if current_stratum is not None else ""
            )
            actions.append({
                "id": "refclocks_unreached",
                "severity": "info",
                "label": (
                    "GPS / PPS refclocks aren't reaching chrony "
                    + stratum_note
                ),
                "reason": (
                    f"chrony has the {' / '.join(unreached)} refclock(s) configured "
                    "but Reach=0 — no samples have ever arrived. The most common "
                    "cause is gpsd not being able to open the GPS serial port "
                    "because EAS Station's hardware service holds it. Until the "
                    "gpsd-as-NMEA-source feature lands, the workaround is to "
                    "uncheck 'Enable GPS Receiver' under Admin → Hardware "
                    "Settings → GPS, save, and let gpsd own the port. You'll "
                    "lose the live GPS card but gain stratum-1 PPS time."
                ),
                "command": (
                    "# Check who owns the serial port:\n"
                    "sudo lsof /dev/ttyAMA10 /dev/ttyAMA0 /dev/serial0 2>/dev/null"
                ),
            })

    return actions


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def collect_gps_hat_diagnostics(
    expected_pps_pin: int = 18,
    expected_baud: int = 9600,
    logger: Optional[logging.Logger] = None,
) -> Dict[str, Any]:
    """Top-level probe. Returns a JSON-serialisable diagnostic report.

    Args:
        expected_pps_pin: BCM pin EAS Station has configured for PPS
            (passed in by the caller from settings).
        expected_baud: Baud rate EAS Station has configured for the GPS
            serial port (passed in by the caller from settings).
        logger: Optional logger; defaults to module logger.
    """
    log = logger or _logger
    report: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_pps_pin": expected_pps_pin,
        "expected_baud": expected_baud,
    }

    try:
        report["rtc"] = _probe_rtc()
    except Exception as exc:
        log.debug("rtc probe failed: %s", exc)
        report["rtc"] = {"error": str(exc)}

    try:
        report["i2c"] = _probe_i2c(
            (report.get("rtc") or {}).get("expected_addr")
        )
    except Exception as exc:
        log.debug("i2c probe failed: %s", exc)
        report["i2c"] = {"error": str(exc)}

    try:
        report["pps"] = _probe_pps()
    except Exception as exc:
        log.debug("pps probe failed: %s", exc)
        report["pps"] = {"error": str(exc)}

    try:
        report["serial"] = _probe_serial(expected_baud=expected_baud)
    except Exception as exc:
        log.debug("serial probe failed: %s", exc)
        report["serial"] = {"error": str(exc)}

    try:
        report["packages"] = _probe_packages()
    except Exception as exc:
        log.debug("packages probe failed: %s", exc)
        report["packages"] = {"error": str(exc), "items": [], "missing_required": []}

    try:
        report["services"] = _probe_services()
    except Exception as exc:
        log.debug("services probe failed: %s", exc)
        report["services"] = {"error": str(exc), "items": []}

    try:
        report["gpsd_config"] = _probe_gpsd_config()
    except Exception as exc:
        log.debug("gpsd config probe failed: %s", exc)
        report["gpsd_config"] = {"error": str(exc)}

    try:
        report["chrony_config"] = _probe_chrony_config()
    except Exception as exc:
        log.debug("chrony config probe failed: %s", exc)
        report["chrony_config"] = {"error": str(exc)}

    try:
        report["chrony_runtime"] = _probe_chrony_runtime()
    except Exception as exc:
        log.debug("chrony runtime probe failed: %s", exc)
        report["chrony_runtime"] = {"error": str(exc)}

    try:
        report["config_txt"] = _probe_config_txt(
            (report.get("rtc") or {}).get("expected_overlay"),
            expected_pps_pin,
        )
    except Exception as exc:
        log.debug("config.txt probe failed: %s", exc)
        report["config_txt"] = {"error": str(exc)}

    try:
        report["actions"] = _build_actions(report)
    except Exception as exc:
        log.debug("action builder failed: %s", exc)
        report["actions"] = []

    # Top-level summary the UI can render as a status badge.
    actions = report["actions"]
    if any(a["severity"] == "error" for a in actions):
        report["status"] = "error"
    elif any(a["severity"] == "warning" for a in actions):
        report["status"] = "warning"
    elif actions:
        report["status"] = "info"
    else:
        report["status"] = "ok"
    report["action_count"] = len(actions)
    return report
