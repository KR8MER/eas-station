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

"""Regression test: ZigpyController must call the pysnmp-era-equivalent
correct zigpy application method for permit-join under zigpy 2.x.

zigpy's ControllerApplication renamed permit_joining(duration) to
permit(time_s=60, node=None) somewhere between the 0.60.0 floor this
project used to pin and 2.1.0 (verified directly against an installed
zigpy==2.1.0 + zigpy-znp==1.1.0 -- inspect.signature(ControllerApplication)
has no `permit_joining` attribute at all on that version). Every call to
the old name is wrapped in a broad `except Exception` in this file (or, for
permit_join() itself, not wrapped at all -- it would raise straight through
to the caller), so this class of break is easy to ship unnoticed: hardware
tests are deselected in CI, and there was no unit coverage for this class
before this file.

This test doesn't exercise real Zigbee hardware (no serial coordinator is
available in CI) -- it stubs `_app` with a fake object exposing an async
`permit()` and asserts ZigpyController.permit_join()/close_join() call it
(and never call a `permit_joining` that shouldn't exist on the real object).
"""

import asyncio
import threading

from services.zigbee.controller import ZigpyController


class _FakeApp:
    """Stands in for zigpy_znp's ControllerApplication -- only implements
    what ZigpyController actually calls, so a signature mismatch there
    would fail loudly (unlike calling a *nonexistent* attribute, which is
    exactly the bug this test guards against)."""

    def __init__(self):
        self.permit_calls = []

    async def permit(self, duration):
        self.permit_calls.append(duration)


def _make_controller_with_loop():
    controller = ZigpyController(
        port="/dev/ttyUSB0", baudrate=115200, channel=15,
        pan_id="0x1A62", redis_client=None, db_path=":memory:",
    )

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    controller._loop = loop
    controller._running = True
    controller._app = _FakeApp()
    return controller, loop, thread


def _teardown_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=5)
    loop.close()


class TestPermitJoinUsesCurrentZigpyApi:
    def test_permit_join_calls_permit_not_permit_joining(self):
        controller, loop, thread = _make_controller_with_loop()
        try:
            controller.permit_join(duration=45)
            assert controller._app.permit_calls == [45]
            assert not hasattr(controller._app, "permit_joining")
        finally:
            if controller._permit_join_timer:
                controller._permit_join_timer.cancel()
            _teardown_loop(loop, thread)

    def test_close_join_calls_permit_with_zero(self):
        controller, loop, thread = _make_controller_with_loop()
        try:
            controller.close_join()
            assert controller._app.permit_calls == [0]
        finally:
            _teardown_loop(loop, thread)
