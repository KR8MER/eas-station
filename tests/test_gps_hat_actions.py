from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_gps_hat_module():
    spec = importlib.util.spec_from_file_location(
        "gps_hat_under_test",
        Path(__file__).resolve().parents[1] / "app_utils" / "gps_hat.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_build_actions = _load_gps_hat_module()._build_actions


def _base_report(**overrides):
    report = {
        "rtc": {
            "detected_chip": None,
            "expected_overlay": None,
            "chip_label": None,
            "porf_set": None,
        },
        "pps": {"gpio_device": {"name": "pps0"}},
        "serial": {"exists": True},
        "packages": {"items": [], "missing_required": []},
        "services": {"items": []},
        "gpsd_config": {"exists": True, "has_n_flag": True, "baud_flag": 9600},
        "chrony_config": {
            "exists": True,
            "rtcsync_enabled": True,
            "has_pps_refclock": True,
            "has_shm_refclock": True,
            "pool_lines": [],
        },
        "chrony_runtime": {"tracking_ok": True, "refclocks_unreached": []},
        "config_txt": {
            "path": "/boot/firmware/config.txt",
            "exists": True,
            "pps_gpio_overlay_line": "dtoverlay=pps-gpio,gpiopin=18",
            "pps_pin_match": True,
        },
        "expected_pps_pin": 18,
        "expected_baud": 9600,
        "expected_source": "auto",
    }
    report.update(overrides)
    return report


def test_serial_source_warns_to_switch_to_gpsd_for_chrony_pps():
    actions = _build_actions(_base_report(expected_source="serial"))

    switch_actions = [a for a in actions if a["id"] == "switch_gps_source_to_gpsd"]
    assert len(switch_actions) == 1
    assert "NMEA Source to 'gpsd'" in switch_actions[0]["reason"]
    assert "systemctl restart gpsd chrony eas-station-hardware" in switch_actions[0]["command"]
    assert switch_actions[0]["runner"]["endpoint"] == "/admin/hardware/gps-hat/source-mode"
    assert switch_actions[0]["runner"]["body"] == {"gps_source": "gpsd"}
    assert switch_actions[0]["runner"]["post_action"]["endpoint"] == "/admin/hardware/restart-services"


def test_gpsd_source_does_not_warn_to_switch_to_gpsd():
    actions = _build_actions(_base_report(expected_source="gpsd"))

    assert "switch_gps_source_to_gpsd" not in {a["id"] for a in actions}
