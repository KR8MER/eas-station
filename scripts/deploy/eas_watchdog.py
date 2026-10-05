#!/usr/bin/env python3
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

"""Hourly health watchdog for the EAS Station host.

Run unprivileged by the self-hosted GitHub Actions runner
(.github/workflows/deploy-pi.yml, ``watchdog`` job), which opens or updates
a GitHub issue when this exits non-zero and closes it on recovery. Checks:

* every unit under ``eas-station.target`` is active;
* per-service anonymous memory (cgroup ``memory.stat`` -- page cache is
  excluded) stays under an absolute ceiling and does not climb steadily
  within one service run. The redis-py 8 pub/sub leak (CHANGELOG 3.23.4)
  grew demod ~25 MB/h for 13 days before anyone noticed;
* swap usage stays under half;
* the web health endpoint answers 200;
* every Icecast mount delivers at least ~real time, judged against the
  bitrate in its own MP3 frame headers (CHANGELOG 3.23.5/3.23.8: streams
  silently ran at 50-70% of real time).

Standard library only, so it runs on any Python 3 without the app venv.
"""

import argparse
import json
import socket
import subprocess
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TARGET = "eas-station.target"
HEALTH_URL = "http://localhost:5000/health"
ICECAST = ("127.0.0.1", 8000)

MEMORY_CEILING_BYTES = 1536 * 1024 * 1024    # any one service, unless overridden
# eas-station-web runs several gunicorn workers (~400 MB each), so its
# total is legitimately larger; the leak-trend check still covers it.
MEMORY_CEILING_OVERRIDES = {"eas-station-web.service": 3 * 1024 * 1024 * 1024}
LEAK_MIN_SPAN_S = 6 * 3600                   # trend needs this much history
LEAK_RATE_BYTES_PER_H = 15 * 1024 * 1024     # sustained growth that alarms
LEAK_MIN_GROWTH_BYTES = 150 * 1024 * 1024
HISTORY_S = 48 * 3600
SWAP_MAX_FRACTION = 0.5
STREAM_MIN_RATIO = 0.85
STREAM_SKIP_S = 1.5      # Icecast bursts its buffer to a new listener
STREAM_MEASURE_S = 10.0

_MPEG1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]
_MPEG2_L3 = [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]


# ---------------------------------------------------------------- pure logic

def mp3_bitrate_kbps(data: bytes) -> Optional[int]:
    """Most common Layer III bitrate among frame headers in *data*."""
    seen: Counter = Counter()
    i = 0
    while i < len(data) - 3 and sum(seen.values()) < 50:
        if data[i] == 0xFF and (data[i + 1] & 0xE0) == 0xE0:
            version = (data[i + 1] >> 3) & 0x3
            layer = (data[i + 1] >> 1) & 0x3
            index = data[i + 2] >> 4
            rate_index = (data[i + 2] >> 2) & 0x3
            if layer == 1 and version != 1 and 0 < index < 15 and rate_index != 3:
                table = _MPEG1_L3 if version == 3 else _MPEG2_L3
                seen[table[index]] += 1
                i += 4
                continue
        i += 1
    return seen.most_common(1)[0][0] if seen else None


def stream_ratio(byte_count: int, seconds: float, bitrate_kbps: int) -> float:
    """Delivered audio as a fraction of real time."""
    return (byte_count * 8) / (bitrate_kbps * 1000.0 * seconds)


def leak_verdict(samples: List[Tuple[float, int]]) -> Optional[str]:
    """Return a description if *samples* (time, bytes) show a sustained leak.

    Uses a least-squares slope over one service run, so a single spike or a
    one-off allocation does not alarm; only steady growth does.
    """
    if len(samples) < 4:
        return None
    span = samples[-1][0] - samples[0][0]
    if span < LEAK_MIN_SPAN_S:
        return None
    n = len(samples)
    mean_t = sum(t for t, _ in samples) / n
    mean_m = sum(m for _, m in samples) / n
    var = sum((t - mean_t) ** 2 for t, _ in samples)
    if var == 0:
        return None
    slope = sum((t - mean_t) * (m - mean_m) for t, m in samples) / var   # bytes/s
    per_hour = slope * 3600
    growth = samples[-1][1] - samples[0][1]
    if per_hour >= LEAK_RATE_BYTES_PER_H and growth >= LEAK_MIN_GROWTH_BYTES:
        return (f"growing {per_hour / 2**20:.0f} MB/h over {span / 3600:.1f} h "
                f"(+{growth / 2**20:.0f} MB, now {samples[-1][1] / 2**20:.0f} MB)")
    return None


def update_history(state: Dict, unit: str, invocation: str, now: float,
                   mem: int) -> List[Tuple[float, int]]:
    """Append a sample; history resets when the service restarts."""
    entry = state.get(unit)
    if not entry or entry.get("invocation") != invocation:
        entry = {"invocation": invocation, "samples": []}
    samples = [(t, m) for t, m in entry["samples"] if now - t <= HISTORY_S]
    samples.append((now, mem))
    entry["samples"] = samples
    state[unit] = entry
    return samples


# ------------------------------------------------------------- host probes

def _systemctl(*args: str) -> str:
    return subprocess.run(["systemctl", *args], capture_output=True, text=True,
                          check=False).stdout


def target_units() -> List[str]:
    out = _systemctl("list-dependencies", TARGET, "--plain", "--no-pager")
    units = []
    for line in out.splitlines():
        name = line.strip()
        if name.startswith("eas-station") and name.endswith(".service"):
            units.append(name)
    return sorted(set(units))


def unit_props(unit: str) -> Dict[str, str]:
    out = _systemctl("show", unit, "-p", "ActiveState,SubState,InvocationID,ControlGroup")
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def cgroup_anon_bytes(control_group: str) -> Optional[int]:
    """Anonymous memory of a unit's processes (page cache excluded).

    Prefers the cgroup's ``memory.stat``; Raspberry Pi OS ships with the
    memory controller disabled, so fall back to summing ``RssAnon`` of the
    processes in ``cgroup.procs`` -- the same leak-relevant number.
    """
    base = Path("/sys/fs/cgroup") / control_group.lstrip("/")
    try:
        for line in (base / "memory.stat").read_text().splitlines():
            key, _, value = line.partition(" ")
            if key == "anon":
                return int(value)
    except (OSError, ValueError):
        pass
    try:
        pids = (base / "cgroup.procs").read_text().split()
    except OSError:
        return None
    total = 0
    for pid in pids:
        try:
            for line in Path(f"/proc/{pid}/status").read_text().splitlines():
                if line.startswith("RssAnon:"):
                    total += int(line.split()[1]) * 1024
                    break
        except (OSError, ValueError):
            continue        # process exited between listing and reading
    return total if pids else None


def swap_fraction() -> float:
    info = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0])
    total = info.get("SwapTotal", 0)
    return 0.0 if not total else (total - info.get("SwapFree", 0)) / total


def health_ok() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=10) as resp:
            return resp.status == 200
    except OSError:
        return False


def icecast_mounts() -> List[str]:
    url = f"http://{ICECAST[0]}:{ICECAST[1]}/status-json.xsl"
    with urllib.request.urlopen(url, timeout=10) as resp:
        stats = json.load(resp).get("icestats", {})
    sources = stats.get("source") or []
    if isinstance(sources, dict):
        sources = [sources]
    return sorted(s["listenurl"].rsplit("/", 1)[-1] for s in sources if s.get("listenurl"))


def measure_mount(mount: str) -> Dict:
    sock = socket.create_connection(ICECAST, timeout=5)
    try:
        sock.sendall(f"GET /{mount} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())
        sock.settimeout(1.0)
        start = time.monotonic()
        head = b""
        counted = 0
        while True:
            now = time.monotonic()
            if now - start >= STREAM_SKIP_S + STREAM_MEASURE_S:
                break
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                break
            if len(head) < 64 * 1024:
                head += chunk
            if now - start >= STREAM_SKIP_S:
                counted += len(chunk)
    finally:
        sock.close()
    body = head.split(b"\r\n\r\n", 1)[-1]
    kbps = mp3_bitrate_kbps(body)
    ratio = stream_ratio(counted, STREAM_MEASURE_S, kbps) if kbps else None
    return {"mount": mount, "kbps": kbps, "ratio": ratio}


# ------------------------------------------------------------------- main

def run(state_path: Path) -> Tuple[List[str], List[str]]:
    problems: List[str] = []
    lines: List[str] = []
    try:
        state = json.loads(state_path.read_text())
    except (OSError, ValueError):
        state = {}
    now = time.time()

    for unit in target_units():
        props = unit_props(unit)
        active = props.get("ActiveState") == "active"
        if not active:
            problems.append(f"`{unit}` is {props.get('ActiveState')}/{props.get('SubState')}")
            continue
        mem = cgroup_anon_bytes(props.get("ControlGroup", ""))
        if mem is None:
            continue
        lines.append(f"| `{unit}` | {mem / 2**20:.0f} MB |")
        ceiling = MEMORY_CEILING_OVERRIDES.get(unit, MEMORY_CEILING_BYTES)
        if mem > ceiling:
            problems.append(f"`{unit}` uses {mem / 2**20:.0f} MB (ceiling "
                            f"{ceiling / 2**20:.0f} MB)")
        verdict = leak_verdict(update_history(state, unit, props.get("InvocationID", ""),
                                              now, mem))
        if verdict:
            problems.append(f"`{unit}` looks like a memory leak: {verdict}")

    swap = swap_fraction()
    lines.append(f"| swap used | {swap:.0%} |")
    if swap > SWAP_MAX_FRACTION:
        problems.append(f"swap is {swap:.0%} used")

    if not health_ok():
        problems.append(f"`{HEALTH_URL}` did not return 200")

    try:
        mounts = icecast_mounts()
    except OSError as exc:
        mounts = []
        problems.append(f"Icecast status unavailable: {exc}")
    results: List[Dict] = []
    threads = [threading.Thread(target=lambda m=m: results.append(_safe_measure(m)))
               for m in mounts]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for r in sorted(results, key=lambda r: r["mount"]):
        if r.get("error"):
            problems.append(f"`/{r['mount']}`: {r['error']}")
        elif r["ratio"] is None:
            problems.append(f"`/{r['mount']}` delivered no decodable MP3 audio")
        else:
            lines.append(f"| `/{r['mount']}` | {r['ratio']:.0%} of real time "
                         f"@ {r['kbps']} kbps |")
            if r["ratio"] < STREAM_MIN_RATIO:
                problems.append(f"`/{r['mount']}` delivers {r['ratio']:.0%} of real time "
                                f"(listeners hear dropouts)")

    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
    except OSError as exc:
        # Leak trends need the history, but one unsaved sample must not
        # turn into a false "watchdog failed" alarm.
        lines.append(f"| state file | not saved: {exc} |")
    return problems, lines


def _safe_measure(mount: str) -> Dict:
    try:
        return measure_mount(mount)
    except OSError as exc:
        return {"mount": mount, "error": str(exc), "ratio": None, "kbps": None}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="EAS Station host watchdog")
    parser.add_argument("--state", type=Path,
                        default=Path.home() / ".eas-watchdog" / "state.json")
    parser.add_argument("--report", type=Path, help="write a Markdown report here")
    args = parser.parse_args(argv)

    problems, lines = run(args.state)
    report = ["### Problems" if problems else "### All checks passed", ""]
    report += [f"- {p}" for p in problems] or ["- none"]
    report += ["", "### Readings", "", "| Check | Value |", "|---|---|", *lines]
    text = "\n".join(report) + "\n"
    print(text)
    if args.report:
        args.report.write_text(text)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
