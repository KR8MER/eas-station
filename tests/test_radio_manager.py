"""
EAS Station - Emergency Alert System
Copyright (c) 2025 Timothy Kramer (KR8MER)

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

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app_core.radio.manager import RadioManager, ReceiverConfig, ReceiverInterface, ReceiverStatus


class _DummyReceiver(ReceiverInterface):
    def __init__(self, config: ReceiverConfig, *, event_logger=None) -> None:
        super().__init__(config, event_logger=event_logger)
        self.started = 0
        self.stopped = 0
        self._running = False
        self._status = ReceiverStatus(identifier=config.identifier, locked=False)

    def start(self) -> None:
        self.started += 1
        self._running = True

    def stop(self) -> None:
        self.stopped += 1
        self._running = False

    def get_status(self) -> ReceiverStatus:
        return self._status

    def is_running(self) -> bool:
        return self._running

    def capture_to_file(self, duration_seconds, output_dir, prefix, *, mode="iq"):
        raise NotImplementedError


def test_start_all_respects_auto_start_flag():
    manager = RadioManager()
    manager.register_driver("dummy", _DummyReceiver)

    configs = [
        ReceiverConfig(
            identifier="auto",
            driver="dummy",
            frequency_hz=162_550_000,
            sample_rate=2_400_000,
            enabled=True,
            auto_start=True,
        ),
        ReceiverConfig(
            identifier="manual",
            driver="dummy",
            frequency_hz=162_550_000,
            sample_rate=2_400_000,
            enabled=True,
            auto_start=False,
        ),
    ]

    manager.configure_receivers(configs)
    manager.start_all()

    auto_receiver = manager.get_receiver("auto")
    manual_receiver = manager.get_receiver("manual")

    assert auto_receiver is not None
    assert manual_receiver is not None
    assert auto_receiver.started == 1
    assert manual_receiver.started == 0


def test_receiver_config_preserves_auto_start_flag():
    from app_core.models import RadioReceiver

    class _Stub:
        identifier = "wx42"
        display_name = "Weather"
        driver = "rtlsdr"
        frequency_hz = 162_550_000
        sample_rate = 2_400_000
        gain = None
        channel = None
        serial = None
        enabled = True
        auto_start = False
        modulation_type = 'IQ'
        audio_output = False
        stereo_enabled = True
        deemphasis_us = 75.0
        enable_rbds = False
        squelch_enabled = False
        squelch_threshold_db = -65.0
        squelch_open_ms = 150
        squelch_close_ms = 750
        squelch_alarm = False

    config = RadioReceiver.to_receiver_config(_Stub())
    assert config.enabled is True
    assert config.auto_start is False
