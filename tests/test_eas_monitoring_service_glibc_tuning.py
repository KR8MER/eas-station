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

"""Guard the glibc malloc-arena fix on eas_monitoring_service.py / its unit.

eas_monitoring_service.py (eas-station-audio.service) is the most heavily
threaded eas-station process -- websocket push fast+slow loops, gated-alert
scheduler, per-source audio pipelines, ffmpeg feeder threads -- but never
had services.common.bootstrap.init_runtime() applied, the fix that cut a
different service's RSS from 9.68 GB to 320 MB (see
systemd/eas-station-displays.service and app_utils/glibc_tuning.py). A
week of system_metric_samples showed this service's RSS climbing from
~400 MB to ~3.4 GB over ~2.8 days between restarts -- the classic
one-malloc-arena-per-thread signature.

These are source-text checks, not an integration test that actually runs
main() (which needs Redis/DB/audio hardware) -- same style as
tests/test_systemd_memory_limits.py and tests/test_systemd_units_phase4.py.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PY = REPO_ROOT / "eas_monitoring_service.py"
UNIT_FILE = REPO_ROOT / "systemd" / "eas-station-audio.service"


def test_service_imports_and_calls_init_runtime():
    text = SERVICE_PY.read_text(encoding="utf-8")
    assert "from services.common.bootstrap import init_runtime" in text, (
        "eas_monitoring_service.py must import init_runtime from "
        "services.common.bootstrap"
    )
    assert re.search(r'init_runtime\(\s*["\']audio["\']\s*\)', text), (
        'eas_monitoring_service.py must call init_runtime("audio") in main()'
    )


def test_init_runtime_call_precedes_thread_spawns():
    """init_runtime() only constrains malloc arenas for threads created
    after it runs -- calling it after threads already exist silently no-ops
    the fix for that service."""
    text = SERVICE_PY.read_text(encoding="utf-8")
    main_start = text.index("def main():")
    init_runtime_pos = text.index('init_runtime("audio")', main_start)
    first_thread_spawn_pos = text.index("threading.Thread(", main_start)
    assert init_runtime_pos < first_thread_spawn_pos, (
        "init_runtime(\"audio\") must run before the first threading.Thread(...) "
        "in main() -- arena caps only bind threads created afterward"
    )


def test_unit_pins_glibc_malloc_tuning_and_memdiag_dump_dir():
    text = UNIT_FILE.read_text(encoding="utf-8")
    assert re.search(r'^Environment="MALLOC_ARENA_MAX=2"\s*$', text, re.MULTILINE), (
        "eas-station-audio.service must pin MALLOC_ARENA_MAX=2"
    )
    assert re.search(
        r'^Environment="MALLOC_TRIM_THRESHOLD_=131072"\s*$', text, re.MULTILINE
    ), "eas-station-audio.service must pin MALLOC_TRIM_THRESHOLD_=131072"
    assert re.search(r'^Environment="MEMDIAG_DUMP_DIR=', text, re.MULTILINE), (
        "eas-station-audio.service must set MEMDIAG_DUMP_DIR so SIGUSR1/SIGUSR2 "
        "dumps land somewhere reachable outside PrivateTmp"
    )
