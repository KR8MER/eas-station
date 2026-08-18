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

from __future__ import annotations

"""The "Run Full Diagnostics" checklist -- shared by the CLI script
(``scripts/diagnostics/check_sdr_status.py``) and the web route
(``/api/radio/diagnostics/run-check`` in ``webapp/radio_settings/routes_diagnostics_status.py``)
so the two surfaces can never drift.

``check_sdr_status.py`` predates the "separated architecture" move (SDR
receivers run in the standalone ``eas-station-sdr.service`` process, not
in-process with the webapp) and still reads a local, almost-always-empty
``get_radio_manager()``. Its device/receiver checks were effectively dead
for anyone running the current architecture -- the real signal for "is the
SDR pipeline actually working" is the Redis state the SDR service publishes
(``sdr:heartbeat``, ``sdr:metrics``, ``sdr:ring_buffer:<id>``,
``eas:spectrum:<id>``), which is what this module actually checks.

Each check returns a dict: ``{id, label, status, message}`` where
``status`` is one of ``pass`` / ``warn`` / ``fail`` / ``info``. The web
route renders these directly as a checklist; the CLI script prints them
with a matching symbol.
"""

import json
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

STATUS_PASS = "pass"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_INFO = "info"

# Heartbeat freshness threshold. sdr_hardware_service.py publishes
# "sdr:heartbeat" with a 10 s Redis TTL (see publish_sdr_metrics()); a key
# that still exists but is older than this is a sign the publisher loop is
# stalled, not just between beats.
HEARTBEAT_STALE_AFTER_S = 15.0

# Spectrum cache TTL is 5 s server-side (sdr_hardware_service.py); treat
# anything above that as stale rather than merely "a bit old".
SPECTRUM_STALE_AFTER_S = 6.0


def _check(check_id: str, label: str, status: str, message: str) -> Dict[str, str]:
    return {"id": check_id, "label": label, "status": status, "message": message}


def _get_json(redis_client, key: str) -> Optional[Any]:
    if not redis_client:
        return None
    try:
        raw = redis_client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception:
        return None


def run_sdr_diagnostics_checks(
    receivers: Sequence[Any],
    redis_client,
) -> List[Dict[str, str]]:
    """Run every check and return them in a fixed, stable order.

    ``receivers`` is a sequence of ``RadioReceiver`` rows (or any object
    exposing ``.identifier``, ``.display_name``, ``.enabled``,
    ``.frequency_hz``, ``.sample_rate``) -- the caller queries the
    database so this module has no direct model/DB dependency, matching
    the rest of ``app_core/radio``'s pure-library style.
    """
    checks: List[Dict[str, str]] = []
    now = time.time()

    # 1. Database: at least one receiver configured.
    if not receivers:
        checks.append(_check(
            "db_receivers", "Database receivers", STATUS_FAIL,
            "No receivers configured. Add one at Settings -> Radio.",
        ))
        # Nothing else to check without a receiver to check it against.
        return checks

    enabled = [r for r in receivers if getattr(r, "enabled", False)]
    checks.append(_check(
        "db_receivers", "Database receivers", STATUS_PASS,
        f"{len(receivers)} configured, {len(enabled)} enabled.",
    ))

    # 2. Config sanity per enabled receiver.
    bad_config = []
    for r in enabled:
        freq = getattr(r, "frequency_hz", None)
        rate = getattr(r, "sample_rate", None)
        if not freq or freq <= 0 or not rate or rate <= 0:
            bad_config.append(getattr(r, "display_name", None) or getattr(r, "identifier", "?"))
    if bad_config:
        checks.append(_check(
            "config_sanity", "Receiver configuration", STATUS_FAIL,
            f"Invalid frequency/sample rate on: {', '.join(bad_config)}.",
        ))
    else:
        checks.append(_check(
            "config_sanity", "Receiver configuration", STATUS_PASS,
            "All enabled receivers have a valid frequency and sample rate.",
        ))

    # 3. SDR service heartbeat freshness.
    heartbeat = _get_json(redis_client, "sdr:heartbeat")
    if heartbeat is None:
        checks.append(_check(
            "sdr_heartbeat", "SDR service heartbeat", STATUS_FAIL,
            "No heartbeat in Redis -- eas-station-sdr.service is not running or Redis is unreachable.",
        ))
    else:
        age = now - float(heartbeat.get("timestamp", 0) or 0)
        if age <= HEARTBEAT_STALE_AFTER_S:
            checks.append(_check(
                "sdr_heartbeat", "SDR service heartbeat", STATUS_PASS,
                f"Last beat {age:.1f}s ago, {heartbeat.get('receiver_count', 0)} receiver(s) loaded.",
            ))
        else:
            checks.append(_check(
                "sdr_heartbeat", "SDR service heartbeat", STATUS_WARN,
                f"Last beat {age:.1f}s ago (stale) -- the SDR service publisher thread may be stuck.",
            ))

    if not enabled:
        checks.append(_check(
            "receiver_health", "Receiver health", STATUS_INFO,
            "No receivers are enabled, so there is nothing to check further.",
        ))
        return checks

    # 4. Per-receiver running / locked / samples flowing, from sdr:metrics
    #    (same source /api/radio/diagnostics/status reads).
    metrics = _get_json(redis_client, "sdr:metrics") or {}
    metrics_receivers: Mapping[str, Any] = metrics.get("receivers", {}) if isinstance(metrics, dict) else {}

    not_reporting = []
    not_running = []
    not_locked = []
    no_samples = []
    running_identifiers = []
    for r in enabled:
        identifier = getattr(r, "identifier", None)
        name = getattr(r, "display_name", None) or identifier
        data = metrics_receivers.get(identifier) if identifier else None
        if not data:
            not_reporting.append(name)
            continue
        if not data.get("running"):
            not_running.append(name)
            continue
        running_identifiers.append(identifier)
        if not data.get("locked"):
            not_locked.append(name)
        if not data.get("samples_available"):
            no_samples.append(name)

    if not_reporting:
        checks.append(_check(
            "receiver_reporting", "Receivers reporting to Redis", STATUS_WARN,
            f"No metrics from: {', '.join(not_reporting)} (SDR service may not have started them yet).",
        ))
    else:
        checks.append(_check(
            "receiver_reporting", "Receivers reporting to Redis", STATUS_PASS,
            "Every enabled receiver has current metrics.",
        ))

    if not_running:
        checks.append(_check(
            "receiver_running", "Receivers running", STATUS_WARN,
            f"Not running: {', '.join(not_running)}.",
        ))
    elif running_identifiers:
        checks.append(_check(
            "receiver_running", "Receivers running", STATUS_PASS,
            f"All {len(running_identifiers)} reporting receiver(s) are running.",
        ))

    if not_locked:
        checks.append(_check(
            "receiver_locked", "Receivers locked to signal", STATUS_WARN,
            f"Not locked: {', '.join(not_locked)} -- check antenna and frequency.",
        ))
    elif running_identifiers:
        checks.append(_check(
            "receiver_locked", "Receivers locked to signal", STATUS_PASS,
            "All running receivers are locked.",
        ))

    if no_samples:
        checks.append(_check(
            "receiver_samples", "Sample data flowing", STATUS_WARN,
            f"No sample data from: {', '.join(no_samples)}.",
        ))
    elif running_identifiers:
        checks.append(_check(
            "receiver_samples", "Sample data flowing", STATUS_PASS,
            "All running receivers are producing sample data.",
        ))

    # 5. Ring buffer health -- overflow/underflow counts, per running
    #    receiver. Not surfaced as a pass/fail check anywhere else in the
    #    UI (the ring buffer stats hash is only ever rendered as raw
    #    numbers, never evaluated).
    drops_by_receiver = []
    for identifier in running_identifiers:
        try:
            raw = redis_client.hgetall(f"sdr:ring_buffer:{identifier}") if redis_client else None
        except Exception:
            raw = None
        if not raw:
            continue
        try:
            overflow = int(raw.get("overflow_count", 0) or 0)
            underflow = int(raw.get("underflow_count", 0) or 0)
        except (TypeError, ValueError):
            continue
        if overflow > 0 or underflow > 0:
            drops_by_receiver.append(f"{identifier} (overflow={overflow}, underflow={underflow})")
    if running_identifiers:
        if drops_by_receiver:
            checks.append(_check(
                "ring_buffer_health", "Ring buffer overflow/underflow", STATUS_WARN,
                f"Drops recorded: {', '.join(drops_by_receiver)}. Consider a lower sample rate "
                "or check USB bandwidth.",
            ))
        else:
            checks.append(_check(
                "ring_buffer_health", "Ring buffer overflow/underflow", STATUS_PASS,
                "No overflow/underflow recorded on any running receiver.",
            ))

    # 6. Spectrum cache freshness -- confirms the fast Redis-cached path
    #    behind the waterfall/spectrum-scope views (RedisChannels.SPECTRUM_PREFIX)
    #    is actually being populated, not just falling through to the slow
    #    command-queue path.
    stale_spectrum = []
    missing_spectrum = []
    for identifier in running_identifiers:
        payload = _get_json(redis_client, f"eas:spectrum:{identifier}")
        if payload is None:
            missing_spectrum.append(identifier)
            continue
        ts = payload.get("timestamp")
        if not isinstance(ts, (int, float)) or (now - ts) > SPECTRUM_STALE_AFTER_S:
            stale_spectrum.append(identifier)
    if running_identifiers:
        if missing_spectrum:
            checks.append(_check(
                "spectrum_cache", "Spectrum cache (waterfall/scope feed)", STATUS_WARN,
                f"No cached spectrum for: {', '.join(missing_spectrum)} -- "
                "waterfall/scope will fall back to the slow command-queue path.",
            ))
        elif stale_spectrum:
            checks.append(_check(
                "spectrum_cache", "Spectrum cache (waterfall/scope feed)", STATUS_WARN,
                f"Stale cached spectrum for: {', '.join(stale_spectrum)}.",
            ))
        else:
            checks.append(_check(
                "spectrum_cache", "Spectrum cache (waterfall/scope feed)", STATUS_PASS,
                "Fresh spectrum data cached for every running receiver.",
            ))

    return checks


def overall_status(checks: Sequence[Mapping[str, str]]) -> str:
    """Roll a list of checks up to one summary status."""
    statuses = {c["status"] for c in checks}
    if STATUS_FAIL in statuses:
        return STATUS_FAIL
    if STATUS_WARN in statuses:
        return STATUS_WARN
    if STATUS_PASS in statuses:
        return STATUS_PASS
    return STATUS_INFO
