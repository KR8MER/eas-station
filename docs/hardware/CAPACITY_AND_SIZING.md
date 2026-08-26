# Capacity and Sizing

`HARDWARE_QUICKSTART.md`'s Requirements section covers *peripheral*
compatibility (GPIO/I2C/network devices). This page covers the separate
question: **how much CPU, RAM, and thermal headroom does a given
configuration actually need**, so an install doesn't discover it's
undersized only after a broadcast is already stuttering.

There's no synthetic benchmark here — the numbers below are a real,
labeled snapshot from a production reference deployment, taken while
investigating a load-average concern raised during EAS Station v3
hardening (2026-08-26). Use it to gauge where your own configuration
sits, not as a pass/fail spec.

## Reference deployment snapshot

| | |
|---|---|
| Board | Raspberry Pi 5 Model B (16 GB) |
| Storage | NVMe SSD |
| OS load | `2.3 / 3.0 / 3.5` (1/5/15 min, on 4 cores) |
| Memory | 15 GiB total, ~10 GiB used, 5.3 GiB "available", 1.2 GiB swap in use |
| CPU temp | 47°C (Pi 5 throttles around 80-85°C — plenty of headroom) |
| Disk | 1.8 TB volume, 63 GB used (4%) |

Running configuration at that snapshot:

- All 12 `eas-station-*.target` services (web, poller, sdr, demod, audio,
  gpio, gps, network, zigbee, displays, hwsetup, endec-feeds)
- **1 active SDR receiver** (RTL-SDR, WFM+stereo+RBDS demodulation via
  `eas-station-demod.service` — see
  [SDR Service Architecture](../architecture/SDR_SERVICE_ARCHITECTURE.md))
- **2 internet-stream EAS monitor sources** (plain Icecast/HTTP relays,
  no demodulation — just SAME decoding)
- 3 outbound Icecast re-streams (one per source above)
- The full web UI, alert poller, and audit/analytics stack under normal
  (non-alert) load

That load average — roughly 60-90% of the box's 4 cores, sustained — is
**expected for this configuration, not a fault**: FM demodulation
(stereo pilot + RBDS, several FFT convolutions per audio chunk) is
genuinely CPU-heavy, and it's one of several always-on subsystems sharing
the machine. It's also why demodulation was split into its own process
(`eas-station-demod.service`) rather than run inline — see the
[Icecast starvation investigation](../reference/CHANGELOG.md) in the
2.193.x changelog entries for the profiling that motivated that.

Swap use (1.2 GiB) on a 16 GiB board looks alarming but wasn't: 5.3 GiB
was still reported "available," meaning it's cold pages from
long-running processes the kernel chose to page out, not active memory
pressure. Watch `swapin`/`swapout` rate (`vmstat 1`), not the raw swap
total, to tell the difference on your own install.

## Sizing guidance by configuration

| Configuration | Minimum board | Notes |
|---|---|---|
| Web UI + poller only, no SDR/hardware | Pi 3B+ / Pi 4 (2 GB) | Lightest supported configuration. No demodulation running at all. |
| + 1 SDR receiver (WFM/stereo/RBDS) | Pi 4 (4 GB) | `eas-station-demod.service` is the CPU cost center here; give it a dedicated core's worth of headroom. |
| + 1-2 internet-stream EAS monitors | Pi 4 (4 GB) | Cheap: no demodulation, just SAME decoding on an already-decoded stream (see the confirmed-benign `broadcast_adapter.py` "Underrun" note if you see this warning). |
| Full reference config (1 SDR + 2-3 stream monitors + all hardware subsystems) | **Pi 5 (8 GB)** recommended, 16 GB gives headroom | This page's reference snapshot. Pi 4 will run this but with less margin under bursty load (alert processing, TTS generation, PDF/report exports). |
| 2+ SDR receivers | Pi 5 (8 GB+) | Each additional WFM/stereo/RBDS receiver adds roughly one reference-snapshot's worth of demod CPU. Not yet load-tested on this project past 1 concurrent receiver — see the multi-receiver `services/demod` testing note in the roadmap. |

**Storage**: budget for Audio Archive retention, not just the OS image.
The reference deployment's `AudioArchiver` writes complete per-source MP3
files roughly every 10 minutes per monitored source; multiply your
retention window × source count × ~9 MB/10 min to estimate.

**Thermal**: a heatsink/fan case is recommended for any configuration
running SDR demodulation continuously (not just during alerts) — passive
Pi cases are more likely to thermal-throttle under the sustained load
in the table above than under bursty web-only traffic.

## What isn't covered yet

- Load testing with more than one concurrently-demodulating SDR receiver
  (tracked as a pre-v3 follow-up).
- IPAWS/NOAA polling burst behavior during a widescale simultaneous
  activation (multiple counties/states alerting at once).
- ARM boards other than Raspberry Pi (untested; the GPIO/I2C stack
  assumes Broadcom SoC pin numbering).
