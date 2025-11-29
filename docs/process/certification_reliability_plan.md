# Certification-Grade Reliability and Audit Plan

This playbook summarizes the timing, redundancy, verification, and compliance controls required to operate the station at certification-level reliability.

## Timing and Signal Fidelity
- **Deterministic timing:** Lock system clocks with chrony disciplined by GPS PPS; alert when drift exceeds tolerance for SAME frame spacing or attention tone cadence.
- **Test harness:** Measure SAME header spacing, 1600/800 Hz AFSK at 520.83 bps, attention tone duration/levels, and EOM handling through both loopback and over-the-air captures.
- **SAME alignment:** Validate header start offsets, inter-frame spacing, and bit timing against tolerances before releases.
- **Attention tone checks:** Verify tone length, level matching, and stereo balance on each build.
- **EOM handling:** Confirm three clean EOM bursts terminate playback and clear encoder/decoder states.

## Redundancy and Failover
- **Active/standby nodes:** Run dual nodes with keepalived/VRRP for floating IP failover; alert on role flips and gratuitous ARP anomalies.
- **State durability:** Use Postgres streaming replication with synchronous commit for alert state tables; keep Redis behind Sentinel with AOF persistence for transient queues.
- **Operational drills:** Maintain a manual takeover playbook (power, network, services, DNS/IP steps) and rehearse regularly to validate staff readiness.

## SDR Verification and RF Hygiene
- **Calibration:** Measure and record PPM per SDR stick; refuse service when calibration or SNR gates fail.
- **Quality gating:** Require minimum SNR and clean constellation before decoding; log rejects with timestamps and stick serials.
- **Audit artifacts:** Archive short IQ snippets immediately before and after alerts for later dispute resolution.

## Hardware Controls
- **Stable device naming:** Enforce udev rules for persistent names and per-device serial whitelists to prevent accidental role swaps.
- **Portable GPIO:** Use libgpiod for all GPIO access to remain portable across kernels and boards.

## Ingestion Hygiene
- **Deduplication:** De-duplicate CAP messages by identifier and sent time; prefer IPAWS primary feeds over mirrors.
- **Storm protection:** Rate-limit ingestion bursts to prevent replay amplification or malformed floods.

## Backups and Compliance
- **Tamper resistance:** Store logs in WORM-style targets with signed hash chains for audit trails.
- **Access security:** Require client mTLS for IPAWS COG access and track certificate expiration with proactive alarms.
- **Backups:** Schedule periodic backups for databases and config, including replication metadata and udev/GPIO rules.

## Monitoring and Observability
- **Metrics and dashboards:** Export metrics to Prometheus and visualize in Grafana; alert on timing drift, VRRP state changes, replication lag, Sentinel failover, SNR gating, and IQ archival failures.
- **Auth and API exposure:** Use Keycloak for SSO and DreamFactory for read-only REST over Postgres where external dashboards need limited access.

## Simulation and Operator Readiness
- **Scenario simulator:** Provide a simulator to run RWT, RMT, and EAN preemption scenarios, capturing operator acknowledgements and timing deltas.
- **Playback review:** Record simulated audio/IQ alongside logs to confirm end-to-end timing and UI prompts.

## Acceptance Checklist
- Timing harness validates SAME headers, AFSK bit rates, attention tone duration/level, and EOM clearing in loopback and OTA paths.
- Chrony+GPS PPS health alarms trigger on drift beyond tolerance; VRRP, replication, and Sentinel failovers alert immediately.
- SDRs calibrated per-stick with enforced SNR gates and archived IQ slices before/after alerts.
- Udev persistent names, serial whitelists, and libgpiod-based GPIO confirmed on both nodes.
- CAP ingestion de-duplication, IPAWS preference, and rate-limiting verified under load tests.
- WORM log storage with signed hash chains and mTLS-enforced IPAWS connectivity in place; certificate expiry monitoring active.
- Simulator exercises RWT/RMT/EAN preemption workflows and logs operator acknowledgements for drills.
