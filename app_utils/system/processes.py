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

"""Process table snapshot: top CPU/memory consumers and audio decoders."""

from typing import Any, Dict, List, Optional

import psutil

_AUDIO_PROCESS_KEYWORDS = (
    "ffmpeg",
    "sox",
    "gst-launch",
    "gst-launch-1.0",
    "arecord",
    "aplay",
    "liquidsoap",
    "pulseaudio",
    "jackd",
    "audio_service",
    "eas_decode",
    "eas_detection",
)


def _is_audio_processing_process(name: Optional[str], cmdline: Optional[str]) -> bool:
    """Return True when process metadata suggests active audio decoding/encoding."""

    haystack = " ".join(filter(None, [name, cmdline])).lower()
    return any(keyword in haystack for keyword in _AUDIO_PROCESS_KEYWORDS)


def _collect_process_info() -> Dict[str, Any]:
    """Sample the process table for the top CPU/memory consumers and any
    audio encoding/decoding processes.

    Single pass over the process table. This used to iterate
    ``psutil.process_iter()`` three times and sleep 300 ms between samples to
    compute CPU deltas — that stall, run on the shared WebSocket-push thread,
    dropped audio-monitoring ticks every snapshot. We now call
    ``cpu_percent(None)`` once per process, returning the delta since the
    previous call by the *same* psutil bookkeeping (process objects keyed by
    pid). Because callers cache the snapshot for ~30 s, consecutive calls
    produce a meaningful 30-second average without any sleep.
    """

    process_info: Dict[str, Any] = {
        "total_processes": 0,
        "running_processes": 0,
        "top_processes": [],
        "audio_decoding": {
            "cpu_percent_total": 0.0,
            "processes": [],
        },
    }

    try:
        processes: List[Dict[str, Any]] = []
        audio_processes: List[Dict[str, Any]] = []
        audio_cpu_total = 0.0
        total_processes = 0
        running_processes = 0
        running_status = psutil.STATUS_RUNNING

        for proc in psutil.process_iter(["pid", "name", "username", "status"]):
            total_processes += 1
            info = proc.info
            if info.get("status") == running_status:
                running_processes += 1

            try:
                cpu_percent = proc.cpu_percent(None)
                memory_percent = proc.memory_percent()
                name = info.get("name") or proc.name()
                cmdline_list = proc.cmdline()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

            cmdline = " ".join(cmdline_list[:12]) if cmdline_list else None

            if cpu_percent is None:
                cpu_percent = 0.0
            if memory_percent is None:
                memory_percent = 0.0

            process_entry = {
                "pid": info.get("pid", proc.pid),
                "name": name,
                "username": info.get("username"),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
            }

            if cmdline:
                process_entry["command"] = cmdline

            processes.append(process_entry)

            if _is_audio_processing_process(name, cmdline):
                audio_cpu_total += cpu_percent
                audio_processes.append({
                    **process_entry,
                    "command": cmdline or name,
                })

        processes.sort(key=lambda entry: entry.get("cpu_percent", 0) or 0, reverse=True)
        audio_processes.sort(key=lambda entry: entry.get("cpu_percent", 0) or 0, reverse=True)

        process_info["total_processes"] = total_processes
        process_info["running_processes"] = running_processes
        process_info["top_processes"] = processes[:10]
        process_info["audio_decoding"] = {
            "cpu_percent_total": round(audio_cpu_total, 1),
            "processes": audio_processes[:5],
        }
    except Exception:
        pass

    return process_info
