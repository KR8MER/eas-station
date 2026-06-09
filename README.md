# <img src="static/img/eas-system-wordmark.svg" alt="EAS Station™" width="192" height="48" style="vertical-align: middle;"> EAS Station™

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL%20v3-blue?style=flat-square&logo=gnu&logoColor=white)](https://www.gnu.org/licenses/agpl-3.0)
[![Commercial License](https://img.shields.io/badge/License-Commercial-green?style=flat-square)](LICENSE-COMMERCIAL)
[![Version](https://img.shields.io/badge/Version-2.81.1-blueviolet?style=flat-square)](docs/reference/CHANGELOG.md)
[![Raspberry Pi](https://img.shields.io/badge/Raspberry%20Pi-Compatible-C51A4A?style=flat-square&logo=raspberrypi&logoColor=white)](https://www.raspberrypi.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.1.2-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![Werkzeug](https://img.shields.io/badge/Werkzeug-3.1.4-000000?style=flat-square)](https://werkzeug.palletsprojects.com/)
[![Jinja2](https://img.shields.io/badge/Jinja2-3.1.6-B41717?style=flat-square&logo=jinja&logoColor=white)](https://jinja.palletsprojects.com/)
[![Socket.IO](https://img.shields.io/badge/Socket.IO-5.15.0-010101?style=flat-square&logo=socketdotio&logoColor=white)](https://socket.io/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-2.0.45-CA2C39?style=flat-square&logo=sqlalchemy&logoColor=white)](https://www.sqlalchemy.org/)
[![Alembic](https://img.shields.io/badge/Alembic-1.17.2-6BA3BE?style=flat-square&logo=sqlalchemy&logoColor=white)](https://alembic.sqlalchemy.org/)
[![PostgreSQL + PostGIS](https://img.shields.io/badge/PostgreSQL-17%20%2B%20PostGIS-0093D0?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7.1-DC382D?style=flat-square&logo=redis&logoColor=white)](https://redis.io/)
[![Gunicorn](https://img.shields.io/badge/Gunicorn-23.0.0-499848?style=flat-square&logo=gunicorn&logoColor=white)](https://gunicorn.org/)
[![gevent](https://img.shields.io/badge/gevent-25.9.1-1F8B4C?style=flat-square)](https://www.gevent.org/)
[![Nginx](https://img.shields.io/badge/Nginx-Alpine-009639?style=flat-square&logo=nginx&logoColor=white)](https://nginx.org/)
[![Let's Encrypt](https://img.shields.io/badge/Let's%20Encrypt-Certbot-003A70?style=flat-square&logo=letsencrypt&logoColor=white)](https://letsencrypt.org/)
[![Systemd](https://img.shields.io/badge/Systemd-Services-33A9DC?style=flat-square&logo=systemd&logoColor=white)](https://systemd.io/)
[![Icecast](https://img.shields.io/badge/Icecast-2.4.4-1F3B73?style=flat-square)](https://icecast.org/)
[![SoapySDR](https://img.shields.io/badge/SoapySDR-enabled-FF6600?style=flat-square)](https://github.com/pothosware/SoapySDR)
[![FFmpeg](https://img.shields.io/badge/FFmpeg-system-007808?style=flat-square&logo=ffmpeg&logoColor=white)](https://ffmpeg.org/)
[![pydub](https://img.shields.io/badge/pydub-0.25.1-FF8A65?style=flat-square)](https://github.com/jiaaro/pydub)
[![eSpeak NG](https://img.shields.io/badge/eSpeak%20NG-TTS-5C2D91?style=flat-square)](https://github.com/espeak-ng/espeak-ng)
[![NumPy](https://img.shields.io/badge/NumPy-2.3.5-013243?style=flat-square&logo=numpy&logoColor=white)](https://numpy.org/)
[![SciPy](https://img.shields.io/badge/SciPy-1.16.3-8CAAE6?style=flat-square&logo=scipy&logoColor=white)](https://scipy.org/)
[![Numba](https://img.shields.io/badge/Numba-0.61%2B-00A3E0?style=flat-square&logo=numba&logoColor=white)](https://numba.pydata.org/)
[![lxml](https://img.shields.io/badge/lxml-6.0.2-4A7EBB?style=flat-square)](https://lxml.de/)
[![Pillow](https://img.shields.io/badge/Pillow-12.0.0-3776AB?style=flat-square)](https://python-pillow.org/)
[![Bootstrap](https://img.shields.io/badge/Bootstrap-5.3.0-7952B3?style=flat-square&logo=bootstrap&logoColor=white)](https://getbootstrap.com/)
[![Font Awesome](https://img.shields.io/badge/Font%20Awesome-6.4.0-528DD7?style=flat-square&logo=fontawesome&logoColor=white)](https://fontawesome.com/)
[![Leaflet](https://img.shields.io/badge/Leaflet-1.9.4-199900?style=flat-square&logo=leaflet&logoColor=white)](https://leafletjs.com/)
[![Chart.js](https://img.shields.io/badge/Chart.js-3.9.1-FF6384?style=flat-square&logo=chartdotjs&logoColor=white)](https://www.chartjs.org/)
[![PyOTP](https://img.shields.io/badge/PyOTP-2.9.0-2E7D32?style=flat-square)](https://pyauth.github.io/pyotp/)
[![cryptography](https://img.shields.io/badge/cryptography-46.0.5-2c5282?style=flat-square)](https://cryptography.io/)
[![Twilio](https://img.shields.io/badge/Twilio-SMS-F22F46?style=flat-square&logo=twilio&logoColor=white)](https://www.twilio.com/)
[![chrony](https://img.shields.io/badge/chrony-NTP-1F4E79?style=flat-square)](https://chrony-project.org/)
[![gpsd](https://img.shields.io/badge/gpsd-3.x-2E86AB?style=flat-square)](https://gpsd.gitlab.io/gpsd/)
[![GPS Stratum 1](https://img.shields.io/badge/Stratum%201-GPS%2FPPS-0F766E?style=flat-square)](#a-broadcast-grade-time-source-built-in)

> **An open, software-defined Emergency Alert System platform — the kind of infrastructure that used to cost $5,000–$7,000 per appliance, now running on a $80 Raspberry Pi at roughly 12 watts.**

EAS Station™ is a complete CAP-to-broadcast research and training platform: it pulls Common Alerting Protocol feeds from NOAA/NWS and FEMA IPAWS, encodes FCC-Part-11-compliant SAME audio, verifies the result on the air with a software-defined radio, geofences every message against PostGIS-backed boundary data, disciplines its own clock from GPS satellites to **stratum 1**, and records every operator action into a cryptographically tamper-evident audit ledger. It does all of this from a single Raspberry Pi 5 — or any Linux server — wired together from boring, battle-tested open-source components instead of a proprietary appliance.

The project's long-term goal is to be a credible, auditable, drop-in alternative to commercial encoder/decoder hardware for laboratories, training programs, and broadcasters who want to understand and own the stack instead of leasing a black box.

---

> ⚠️ **Laboratory / Research Use Only** — EAS Station™ generates valid SAME headers and attention tones that will trigger downstream EAS equipment. It is **not FCC-certified** and must only be operated in controlled test environments. Never connect it to on-air RF, an STL path, or a public streaming chain without explicit authorization. See [Legal & Compliance](#-legal--compliance).

---

## 🎯 Who This Is For, and What It's For

EAS Station™ was built because the existing EAS appliance market is closed, expensive, and impossible to audit. The platform reframes the same workflows as transparent, inspectable, programmable infrastructure — useful across several distinct audiences:

### Public-Safety Agencies & Emergency Management Offices
**Use it to:** stand up a non-production training rig that mirrors the agency's real CAP/IPAWS workflow, validate FIPS-code and NWS-zone coverage before an exercise, run tabletop drills with realistic alert ingestion and replay, and prototype custom alert distribution (LED signage in EOCs, GPIO triggers to siren controllers, SMS/email/SNMP notifications to on-call staff) without touching the production warning system.

### Broadcasters & Engineering Departments
**Use it to:** experiment with CAP-to-SAME workflows in a bench environment that costs less than a single appliance service contract, evaluate SDR-based off-air verification against an existing encoder, document Required Weekly Test (RWT) and Required Monthly Test (RMT) compliance for audit purposes, and pilot ideas — multi-receiver coordination, alert geofencing, audit-trail integrity — that an operations team can later take to vendors as a requirement spec.

### Amateur Radio: ARES, RACES, SKYWARN, Public-Service Nets
**Use it to:** run realistic CAP-to-EAS training exercises during nets, integrate EAS audio with two-way LMR systems via MDC1200 selective calling (PTT-ID, Emergency, Voice Selective Call), build SKYWARN spotter feedback loops with PostGIS-targeted alert subscription, and operate a stratum-1 GPS-disciplined NTP server for the rest of the club's lab — all on the same Pi.

### Universities, Research Labs & Standards Work
**Use it to:** teach FCC Part 11 / NRSC-4-B SAME modulation hands-on, study CAP 1.2 schema parsing and IPAWS authentication, instrument an end-to-end alert pipeline for software-engineering coursework, or use the running system as the test article in research on alert latency, integrity, geographic targeting accuracy, or social-science studies of alert effectiveness.

### Telecom / Utility / Critical Infrastructure Operators
**Use it to:** subscribe to weather and infrastructure alerts for an operations center, drive site-local signage and PA chains via the GPIO/serial display layer, integrate compliance-health monitoring into existing NMS via SNMP traps, and treat alert ingestion as auditable infrastructure rather than a manual-watch role.

### Software Engineers & Open-Source Contributors
**Use it as:** a non-trivial, full-stack reference application — Flask + SQLAlchemy + PostGIS + Redis + Socket.IO + SoapySDR + systemd — with real DSP, real spatial queries, real hardware I/O, real cryptographic audit chaining, and a meaningful test suite. Build CAP integrations against the REST API, or contribute upstream.

---

## 🧭 What the Platform Actually Does

Rather than a feature checklist, here is the platform organized around the real operational responsibilities it takes off the operator's plate.

### Alert Ingestion — A Reliable Front Door for CAP

The poller subsystem maintains continuous, deduplicated subscriptions to **NOAA/NWS** and **FEMA IPAWS** CAP feeds, plus any number of additional CAP 1.2 endpoints an organization wants to add (state warning points, municipal feeds, internal test sources). Alerts are parsed with `lxml` (5–10× faster than the stdlib parser), normalized, deduplicated, and committed to PostgreSQL/PostGIS with full geographic context. A stalled feed is detected and auto-resumed rather than silently dropping events. For agencies validating their footprint, a built-in **setup wizard** walks operators through finding their FIPS county codes and NWS forecast zones.

**Why it matters institutionally:** The most common operational failure in alert systems is silent feed loss. The poller is built to make that visible — on the dashboard, in the logs, in the audit trail — instead of hiding it.

### SAME Encoding & On-Air Broadcast Workflow

The encoder generates bit-perfect Specific Area Message Encoding headers per **FCC Part 11** and **NRSC-4-B**, complete with the 853/960 Hz two-tone attention sequence, optional eSpeak NG (or Azure Cognitive Services) text-to-speech voice-over with operator-tunable phonetic normalization for road numbers and abbreviations, and an EOM bookend. A **manual EAS workflow** lets training staff print custom drill messages, an **RWT/RMT scheduler** automates the FCC-required weekly and monthly tests, and the **EAS Compliance dashboard** surfaces the cadence so gaps are caught before an audit.

**Beyond the broadcast chain**, the encoder also supports a family of **pre/post-alert signaling profiles** designed for forwarding EAS audio over a Motorola-style two-way LMR network: **MDC1200** (PTT-ID Pre/Post, Emergency, Request-to-Talk, Remote Monitor, Call Alert, Voice Selective Call), **Quick-Call II**, and **DTMF**. This makes the platform usable as a CAP-to-LMR bridge for public-safety voice systems that already exist on a county or campus.

### SDR Verification — Closing the Loop Off-Air

A separate `eas-station-sdr` service uses **RTL-SDR, Airspy, or SDRplay** receivers (via the SoapySDR abstraction) to demodulate the actual RF, decode received SAME headers in real time, and prove that what went out of the transmitter is what the encoder commanded. Verification cross-checks have been validated against `multimon-ng` for decoding parity. A **live, continuously-updating waterfall** on the Radio Receiver Diagnostics page lets an engineer watch a frequency the way they would on a benchtop spectrum analyzer; a one-click **"Capture IQ" button** records a one-second complex64 `.npy` recording per receiver and streams it to the browser via a single-use download URL — feed it straight into `scripts/rbds_diagnose.py`, `inspectrum`, or GNU Radio for offline forensic work without SSH-ing into the host. The same SDR pipeline also carries a full **RBDS / RDS decoder** (PTYN, AF method-B, Linkage Actuator, Slow Labelling, Open Data Applications, Fast Switching) and an **Icecast streaming layer** so any number of remote listeners can monitor demodulated audio over HTTP.

**Why it matters institutionally:** Most encoder vendors do not publish how they verify their own output, and there's no second pair of ears in the rack. This subsystem makes off-air verification a property of the platform, not the operator's headphones.

### Geographic Intelligence — Alerts Matched to a Real Footprint

PostGIS is treated as a first-class component, not an optional add-on. County and NWS zone boundaries are loaded from authoritative sources (U.S. Census **TIGER/Line**, NOAA/NWS, and contributed local GIS offices), and every incoming alert is matched against the station's coverage polygon with real spatial queries. Custom **shapefile import** lets organizations add their own service-area definitions (utility territories, school district boundaries, campus polygons), and the **interactive Leaflet maps** in the dashboard let operators see the alert area and the station footprint together at a glance.

### Timekeeping — A Broadcast-Grade Time Source Built In

Every EAS event is timestamped, geofenced, and audited — and a station that drifts seconds against NIST is a station whose RWT logs and CAP `sent`/`effective`/`expires` math eventually cease to match the real world. The reference build pairs a **u-blox MAX-M8Q multi-GNSS GPS HAT** (or Adafruit MTK3339 as a drop-in alternative) with hardware **Pulse-Per-Second** and a battery-backed RTC. `chrony` consumes the NMEA fix and the PPS edge as a kernel refclock, so the station serves NTP at **true stratum 1** with no upstream internet time required and survives complete network isolation. A dedicated **GPS & Time Dashboard** at `/admin/gps-dashboard` presents a polar sky plot coloured by constellation, full `chronyc tracking` parsing, per-PRN signal-level bars, parsed `chronyc sources`, and a logarithmic sync-health meter — modelled visually on W0CHP's chrogps-dash. A one-click checklist under Admin → Hardware probes every prerequisite (RTC overlay, PPS device, package state, `/boot/firmware/config.txt`) and offers a single **Run** button per remediation step, so the system can be brought up by an operator who has never edited `chrony.conf` by hand.

**Beyond compliance, this is a useful capability in its own right** — the platform serves NTP to the rest of a lab, EOC, or campus rack as a side effect of being a correctly-clocked EAS encoder.

### Tamper-Evident Audit Ledger — Integrity You Can Prove

Every alert insert, encoder action, and operator change is recorded into the existing `audit_logs` table — but with a tamper-evidence layer that was added in v2.75. Each row carries the SHA-256 of its predecessor's `entry_hash`, an SHA-256 over its own canonical-JSON content (including the prev-link), and an **Ed25519 signature** over that hash. The signing key is loaded from a configured path in production, with documented fallbacks. Verification is exposed via `AuditLogger.verify_chain()`, which walks the table, checks every signed row's prev-link, recomputes its content hash, and verifies the signature — returning a structured result that includes the index of the first bad row if integrity has been broken.

**Why it matters institutionally:** This is the difference between "we logged it" and "we can prove the log hasn't been edited." For incident reviews, regulator interaction, training-program documentation, or research integrity, that distinction is the whole point.

### Hardware Integration — The Things the System Actually Has to Drive

The platform was designed under the assumption that an EAS station is not a pure software product — it has to flip relays and drive signs. The hardware service exposes:
- **GPIO relay control** for transmitter PTT lines and external equipment
- **OLED status panels** (Argon, generic SSD1306/SH1106) for at-a-glance current-alert state
- **VFD displays** with a custom screen editor and bitmap support
- **Scrolling LED signage** over RS-232 (and RS-232-over-Ethernet) for EOC and lobby installations
- **NeoPixel / WS2812B** addressable strips for status walls
- **Zigbee** (via Argon40 ZNP) for optional wireless sensor and device control
- **GPIO pin map** in the web UI so what's wired and what's firing is never a mystery

### Security, Notifications & Operations

The web tier is built for organizations that have to share operator credentials safely: **role-based access control** (admin / operator / viewer), **TOTP multi-factor authentication** with QR-code enrollment, **scoped API keys** for automation, **Redis-backed rate limiting** on login and webhook endpoints, **CSRF protection** on every state-changing endpoint, and **nginx HTTPS** with optional automatic Let's Encrypt provisioning. **Tailscale integration** offers a one-tab path to private-network access for distributed teams.

Outbound notifications cover **email** (SMTP, with an optional bundled local Postfix relay), **SMS** (Twilio), and **SNMP v2c traps** for integration with existing NMS platforms.

Day-to-day operations are made survivable by a **whiptail TUI configurator** (`sudo eas-config`), automatic **Alembic migrations** with a recovery script for half-applied schema changes, **pre-flight backup tooling** (`tools/create_backup.py`), **one-button in-place upgrades** (`tools/inplace_upgrade.py`), a comprehensive **web diagnostics page** plus CLI scripts, and an in-browser **journalctl log viewer** and **documentation reader** that renders the full 90+ document library.

### Web Dashboard & REST API

The UI is a **responsive Bootstrap 5** application with **11 built-in themes** (every page including the Changelog viewer driven by theme CSS custom properties), **live Socket.IO push** for alert / radio / GPS updates, a full alert timeline with search and filter, an **Analytics dashboard** with Chart.js visualizations and one-click client-side PDF export of the full statistics report, an **audio monitoring** view with playback and live receive history, **operator-selectable display units** (coordinate format, altitude, speed, distance) saved per browser, and a **System Health** panel surfacing CPU/memory/disk/temperature.

Everything in the UI is reachable from a **REST API** namespaced under `/api/`, with `X-API-Key` header authentication and a vendored JavaScript client for browser-side integrations.

---

## 🏗️ Architecture

The platform is intentionally split into focused systemd services so a web crash never affects audio, and a hardware fault never brings down the dashboard.

```mermaid
graph TB
    subgraph External["External Sources"]
        SRC[Alert Sources<br/>NOAA · IPAWS · CAP]
        RF[RF Signals<br/>162 MHz · SDR]
        GPS_IN[GPS Satellites<br/>NMEA + PPS]
    end

    subgraph Services["Systemd Services"]
        POLL[eas-station-poller<br/>CAP Feed Polling]
        WEB[eas-station-web<br/>Flask · Gunicorn]
        SDR_SVC[eas-station-sdr<br/>SDR Hardware]
        AUDIO_SVC[eas-station-audio<br/>EAS Monitoring]
        HW_SVC[eas-station-hardware<br/>GPIO · Displays]
        CHRONY[chrony + gpsd<br/>Stratum 1 NTP]
    end

    subgraph Infrastructure["Infrastructure"]
        DB[(PostgreSQL 17<br/>+ PostGIS 3.4)]
        REDIS[(Redis 7<br/>Cache · Pub/Sub)]
        NGINX[nginx<br/>HTTPS · Proxy]
        AUDIT[(Tamper-Evident<br/>Audit Ledger<br/>Ed25519)]
    end

    subgraph Output["Outputs"]
        TX[FM Transmitter<br/>GPIO Relay]
        UI[Web Browser<br/>HTTPS]
        LED[LED · OLED · VFD<br/>Displays]
        STREAM[Icecast<br/>Audio Stream]
        NTP[NTP Stratum 1<br/>LAN Time Serving]
    end

    SRC -->|CAP XML| POLL
    RF --> SDR_SVC
    GPS_IN --> CHRONY

    POLL -->|Store Alerts| DB
    WEB -->|Query Data| DB
    WEB -->|Commands| REDIS
    SDR_SVC -->|IQ + Spectrum| REDIS
    AUDIO_SVC -->|Decode| REDIS
    DB -->|Hash-chain insert| AUDIT

    NGINX -->|Reverse Proxy| WEB
    WEB --> UI
    HW_SVC -->|Relay Control| TX
    HW_SVC -->|Messages| LED
    SDR_SVC -->|Demod Audio| STREAM
    CHRONY --> NTP

    style External fill:#3b82f6,color:#fff
    style DB fill:#8b5cf6,color:#fff
    style AUDIT fill:#dc2626,color:#fff
    style WEB fill:#10b981,color:#fff
    style AUDIO_SVC fill:#f59e0b,color:#000
    style UI fill:#6366f1,color:#fff
    style CHRONY fill:#0f766e,color:#fff
```

| Service | Responsibility |
|---------|---------------|
| **eas-station-web** | Flask UI, REST API, dashboards — no direct hardware access |
| **eas-station-poller** | CAP feed polling, XML parsing, deduplication, database writes |
| **eas-station-sdr** | SDR capture, FM demodulation, SAME decoding, RBDS, Icecast streaming, IQ capture |
| **eas-station-hardware** | GPIO relays, OLED/VFD/LED displays, NeoPixel, Zigbee |
| **eas-station-audio** | Audio processing, EAS monitoring, Redis pub/sub |
| **chrony + gpsd** | GPS-disciplined kernel refclock; stratum-1 NTP serving |

**Infrastructure:** PostgreSQL 17 + PostGIS 3.4 for persistent storage · Redis 7 for real-time metrics and inter-service messaging · nginx for HTTPS termination · chrony + gpsd for stratum-1 time.

**Frontend libraries (all vendored locally under `static/vendor/`):** Bootstrap 5, jQuery, Font Awesome, Leaflet (maps), Mermaid (diagrams), Chart.js 3 with the datalabels, matrix and date-fns adapter plugins (dashboards), and jsPDF + html2canvas (client-side PDF report export).

---

## 🚀 Quick Start

### One-Command Install

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
sudo bash install.sh
```

The interactive **whiptail TUI installer** is built for the case where the person installing the station is not the person who wrote the software. It guides operators through every option and handles the rest automatically:

| What you configure | What the installer does for you |
|---|---|
| Admin account (user / pass / email) | Installs PostgreSQL, Redis, Python, nginx |
| Hostname, domain, callsign, EAS originator | Generates a secure 64-char `SECRET_KEY` |
| State, county, FIPS / NWS zone codes | Runs Alembic database migrations |
| Alert sources (NOAA, IPAWS) | Creates your administrator account |
| Icecast streaming passwords | Generates the Ed25519 audit-log signing key |
| Hardware (GPIO, LED, VFD, Zigbee, GPS HAT) | Starts all systemd services |
| Tailscale / SSL preferences | Configures nginx with SSL (Let's Encrypt optional) |

Then open **https://your-server-ip** and log in — the station is live.

> 💡 **Debian 13 (Trixie) and Python 3.13 are fully supported.** The installer auto-detects the host OS and selects the right packages.

### Update an Existing Installation

```bash
cd /opt/eas-station
sudo bash update.sh
```

Optional backup → stop services → pull latest code → preserve `.env` → run Alembic migrations (and refuse to fall back to `db.create_all()` if a migration fails, so a clean error is never traded for a half-migrated database) → restart everything.

### Reconfigure After Install

```bash
sudo eas-config        # interactive whiptail TUI for any .env setting
```

Or visit `/settings` in the web UI for hardware, Icecast, notifications, TTS, FIPS codes, broadcast settings, and more. Anything that was historically an `.env` variable but is now a runtime concern (poller cadence, broadcast settings, notifications, application logging) lives in dedicated DB tables — `.env` is reserved for boot-time infrastructure only.

### Uninstall

```bash
sudo bash uninstall.sh   # stops services, removes files, optionally removes PostgreSQL/Redis/nginx
```

---

## ⚙️ System Requirements

| Category | Minimum | Recommended |
|----------|---------|-------------|
| **Compute** | 2-core CPU, 2 GB RAM | Raspberry Pi 5 (8 GB) or x86 server |
| **Storage** | 20 GB | 50 GB+ SSD (alerts database grows over time) |
| **OS** | Debian 12 / Ubuntu 22.04 | Debian 13 (Trixie) · Raspberry Pi OS |
| **Python** | 3.11 | 3.12 or 3.13 |
| **SDR** | *(optional)* RTL-SDR v3 | Airspy R2/Mini · SDRplay |
| **GPS** | *(optional)* any NMEA UART | Uputronics MAX-M8Q HAT + PPS |
| **GPIO** | *(optional)* any relay HAT | Multi-relay HAT + USB sound card |

Typical power draw at the reference Pi 5 build with SDR + GPS HAT: **~12 W**. See [requirements.txt](requirements.txt) for the full Python dependency list.

---

## 📈 Where the Project Is Today

| Status | Capability |
|--------|------------|
| ✅ Done | Multi-source CAP ingestion (NOAA, IPAWS, custom) with PostGIS targeting |
| ✅ Done | FCC Part 11 / NRSC-4-B SAME encoding with manual workflow and TTS narration |
| ✅ Done | SDR off-air verification with live waterfall and one-click IQ capture |
| ✅ Done | RBDS / RDS decoder with full Group 1A / 7A / 13A / 15B parsing |
| ✅ Done | MDC1200 / Quick-Call II / DTMF pre/post-alert signaling for LMR forwarding |
| ✅ Done | Stratum 1 GPS-disciplined time source + dedicated GPS & Time Dashboard |
| ✅ Done | Tamper-evident Ed25519-signed audit ledger with chain verification |
| ✅ Done | RBAC, TOTP MFA, scoped API keys, rate limiting, CSRF, HTTPS |
| ✅ Done | Automated RWT/RMT scheduling and EAS Compliance dashboard |
| ✅ Done | LED / OLED / VFD / NeoPixel / GPIO / Zigbee hardware integration |
| ✅ Done | Settings Hub, web diagnostics, one-button upgrade, journalctl viewer |
| 🔄 In Progress | Advanced relay control, multi-receiver coordination |
| 🔄 In Progress | FCC rulemaking engagement — [comments filed](https://www.fcc.gov/ecfs/filing/status/detail/confirmation/202606082733827779) in PS Docket No. 25-224 supporting software-defined EAS (a first step toward a possible certification path) |
| ⏳ Planned | FCC Part 11 certification documentation track |
| ⏳ Planned | Time-series performance graphs on the GPS & Time dashboard |
| ⏳ Planned | Cloud sync, mobile app, multi-site coordination |

See the [Changelog](docs/reference/CHANGELOG.md) and the feature roadmap in `docs/roadmap/` for details.

---

## 📚 Documentation

| Topic | Link |
|-------|------|
| **Setup & Installation** | [docs/guides/SETUP_INSTRUCTIONS](docs/guides/SETUP_INSTRUCTIONS.md) |
| **Quickstart** | [docs/installation/QUICKSTART](docs/installation/QUICKSTART.md) |
| **SDR Configuration** | [docs/hardware/SDR_SETUP](docs/hardware/SDR_SETUP.md) |
| **GPS HAT / Stratum 1** | [docs/hardware/GPS_HAT_SETUP](docs/hardware/GPS_HAT_SETUP.md) |
| **Hardware Quickstart** | [docs/guides/HARDWARE_QUICKSTART](docs/guides/HARDWARE_QUICKSTART.md) |
| **Alert Signals (MDC1200 / QC-II / DTMF)** | [docs/guides/ALERT_SIGNALS](docs/guides/ALERT_SIGNALS.md) |
| **Audit Log Review** | [docs/guides/AUDIT_LOG_REVIEW](docs/guides/AUDIT_LOG_REVIEW.md) |
| **MFA / TOTP Setup** | [docs/guides/MFA_TOTP_SETUP](docs/guides/MFA_TOTP_SETUP.md) |
| **Icecast Streaming** | [docs/guides/ICECAST_STREAMING_SETUP](docs/guides/ICECAST_STREAMING_SETUP.md) |
| **Tailscale Setup** | [docs/guides/TAILSCALE_SETUP](docs/guides/TAILSCALE_SETUP.md) |
| **Daily Operations** | [docs/guides/HELP](docs/guides/HELP.md) |
| **REST / JS API Reference** | [docs/frontend/JAVASCRIPT_API](docs/frontend/JAVASCRIPT_API.md) |
| **System Architecture** | [docs/architecture/SYSTEM_ARCHITECTURE](docs/architecture/SYSTEM_ARCHITECTURE.md) |
| **Theory of Operation** | [docs/architecture/THEORY_OF_OPERATION](docs/architecture/THEORY_OF_OPERATION.md) |
| **SAME Protocol Reference** | [docs/reference/protocols/SAME](docs/reference/protocols/SAME.md) |
| **MDC1200 Protocol Reference** | [docs/reference/protocols/MDC1200](docs/reference/protocols/MDC1200.md) |
| **Developer Guide** | [docs/development/AGENTS](docs/development/AGENTS.md) |
| **Changelog** | [docs/reference/CHANGELOG](docs/reference/CHANGELOG.md) |

---

## 🤝 Contributing

```bash
git clone https://github.com/KR8MER/eas-station.git
cd eas-station
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # edit with local DB settings
python app.py
```

See the [Contributing Guide](docs/process/CONTRIBUTING.md) and the [Code Standards](docs/development/AGENTS.md). When bumping any dependency in `requirements.txt`, also update the matching badge above and the live footer partial at `templates/partials/tech_stack_badges.html` — the drift guard `tests/test_tech_stack_badges.py` will fail CI otherwise.

---

## ⚖️ Legal & Compliance

> 🚨 **EAS Station™ generates valid SAME headers and attention tones.** These signals will trigger downstream EAS equipment if coupled to any RF, STL, or streaming chain.
>
> - **Not FCC-certified** — for laboratory, research, and training use only.
> - **Never connect to on-air infrastructure** without explicit authorization.
> - **Real operational semantics only — no fictional or entertainment use.** EAS Station™ is built to emulate the *actual* behavior of certified EAS encoder/decoder equipment for research, training, and Part 97 amateur-radio experimentation. It is **not** a content-creation toolkit. Do **not** use it to author fictional or fabricated EAS workflows (invented event codes, mock CAP feeds presented as real, joke RWT/RMT cycles, "what-if" alert scenarios) and do **not** use its output in films, TV, trailers, advertising, podcasts, streaming, video games, livestream stunts, prank/creepypasta content, ARGs, or any other entertainment or media production. Labeling content as fiction does **not** cure the violation — 47 C.F.R. § 11.45 applies regardless of intent (see the *Olympus Has Fallen* trailer case below).
> - Unauthorized broadcast has real consequences: iHeartMedia paid a [$1M settlement](https://docs.fcc.gov/public/attachments/DA-15-199A1.pdf) (2015); the *Olympus Has Fallen* trailer misuse cost [$1.9M](https://docs.fcc.gov/public/attachments/DA-14-1097A1.pdf).
> - The maintainer will cooperate fully with authorities against any misuse.

See [Terms of Use](docs/policies/TERMS_OF_USE.md), [Privacy Policy](docs/policies/PRIVACY_POLICY.md), [FCC Compliance / About](docs/reference/ABOUT.md), and the [Trademark Policy](docs/policies/TRADEMARK_POLICY.md).

---

## 📜 License

EAS Station™ is **dual-licensed**:

### Open Source — AGPL v3
Free to use, modify, and distribute under the [GNU Affero General Public License v3](LICENSE). Modifications to network-deployed versions must be made available as source.

### Commercial License
For proprietary or closed-source use without AGPL obligations — no source disclosure required, priority support, custom development assistance. See [LICENSE-COMMERCIAL](LICENSE-COMMERCIAL).

```
Copyright (c) 2025-2026 Timothy Kramer (KR8MER)
EAS Station™ — https://github.com/KR8MER/eas-station
```

Branding governed by the [Trademark Policy](docs/policies/TRADEMARK_POLICY.md). See [NOTICE](NOTICE) for required attribution details.

---

## 📚 Attributions & Open‑Source Credits

EAS Station™ stands on the shoulders of an enormous open‑source ecosystem. The badges at the top of this README are a curated highlight; this section is the exhaustive list of every third‑party library, system package, and CDN asset the project relies on. Each entry explains what role that library plays inside EAS Station™, not just what the upstream project is. Versions track [`requirements.txt`](requirements.txt) and the system‑package install scripts in [`scripts/`](scripts/).

> The drift guard `tests/test_tech_stack_badges.py` and the workflow `.github/workflows/release-metadata.yml` enforce that the curated badge subset in this README, in `templates/partials/tech_stack_badges.html` (the live page footer), and in `requirements.txt` stay aligned. Bumping a dependency means updating all three.

### Python runtime, framework & extensions

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| Flask | 3.1.2 | BSD‑3‑Clause | The web framework. Every dashboard, admin page, and JSON endpoint is a Flask route. | https://flask.palletsprojects.com/ |
| Werkzeug | 3.1.4 | BSD‑3‑Clause | WSGI request/response plumbing under Flask — URL routing, cookies, exceptions, request parsing. | https://werkzeug.palletsprojects.com/ |
| Jinja2 | 3.1.6 | BSD‑3‑Clause | Server‑side HTML templates (`templates/*.html`), including the footer badge partial. | https://jinja.palletsprojects.com/ |
| itsdangerous | 2.2.0 | BSD‑3‑Clause | Cryptographic signing for session cookies, CSRF tokens, and one‑use download URLs. | https://itsdangerous.palletsprojects.com/ |
| Flask‑SQLAlchemy | 3.1.1 | BSD‑3‑Clause | Thin Flask integration over SQLAlchemy — wires the engine to the app and request scope. | https://flask-sqlalchemy.palletsprojects.com/ |
| Flask‑SocketIO | 5.5.1 | MIT | Server side of the WebSocket layer that pushes live alert / radio / GPS updates to the dashboard. | https://flask-socketio.readthedocs.io/ |
| Flask‑WTF | 1.2.2 | BSD‑3‑Clause | CSRF protection on every POST form and JSON endpoint. | https://flask-wtf.readthedocs.io/ |
| Flask‑Limiter | 4.1.1 | MIT | Rate limiting on login, API key, and webhook endpoints (Redis or in‑memory backend). | https://flask-limiter.readthedocs.io/ |
| Flask‑Caching | 2.3.1 | BSD‑3‑Clause | Response and view caching for expensive admin pages and read‑heavy JSON endpoints. | https://flask-caching.readthedocs.io/ |
| python‑socketio | 5.15.0 | MIT | Core Socket.IO protocol implementation that Flask‑SocketIO builds on. | https://python-socketio.readthedocs.io/ |

### Database & ORM

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| SQLAlchemy | 2.0.45 | MIT | ORM for every persisted entity — alerts, settings, audit logs, RBAC, GPS samples. | https://www.sqlalchemy.org/ |
| Alembic | 1.17.2 | MIT | Schema migrations (`app_core/migrations/versions/*`); `alembic upgrade head` runs on install/update. | https://alembic.sqlalchemy.org/ |
| psycopg2‑binary | 2.9.11 | LGPL‑3.0 | Sync PostgreSQL driver SQLAlchemy talks to. | https://www.psycopg.org/ |
| GeoAlchemy2 | 0.18.1 | MIT | SQLAlchemy types and ST_* function bindings for PostGIS geometry/geography columns. | https://geoalchemy-2.readthedocs.io/ |
| PostgreSQL | 17 | PostgreSQL | Primary database (alerts, users, audit, configuration). | https://www.postgresql.org/ |
| PostGIS | 3.4 | GPL‑2.0+ | Spatial extension — county/zone boundary matching, polygon containment, alert geo‑filtering. | https://postgis.net/ |
| greenlet | 3.3.0 | MIT / PSF | Required for SQLAlchemy 2.0 sync I/O when running under the gevent worker. | https://greenlet.readthedocs.io/ |

### Caching, queueing & runtime servers

| Component | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| Redis (server) | 7.1 | RSAL/SSPL/AGPL (per upstream) | Pub/sub bus between the web app and the SDR / hardware services; cache; rate‑limit store; capture registry; live spectrum + waterfall feed. | https://redis.io/ |
| redis (Python) | 7.1.0 | MIT | Python client for the Redis server. | https://github.com/redis/redis-py |
| hiredis | 3.3.0 | BSD‑3‑Clause | C parser accelerator for `redis‑py` (faster pub/sub fan‑out). | https://github.com/redis/hiredis-py |
| Gunicorn | 23.0.0 | MIT | Production WSGI server fronting the Flask app. | https://gunicorn.org/ |
| gevent | 25.9.1+ | MIT | Async worker class for Gunicorn so Flask‑SocketIO can hold thousands of concurrent WebSocket connections. | https://www.gevent.org/ |
| Nginx | Alpine | BSD‑2‑Clause | Reverse proxy / TLS terminator / static file server in front of Gunicorn and Icecast. | https://nginx.org/ |
| systemd | system | LGPL‑2.1+ | Process supervisor for `eas-station`, `sdr_hardware_service`, `hardware_service`, `gps_manager`, Icecast, Redis. | https://systemd.io/ |
| Let's Encrypt / Certbot | — | Apache‑2.0 / ISRG | Automated TLS certificate issuance and renewal for the public HTTPS endpoint. | https://letsencrypt.org/ |

### HTTP, serialization & utilities

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| requests | 2.32.5 | Apache‑2.0 | Sync HTTP client used by the CAP/IPAWS pollers and most outbound integrations. | https://requests.readthedocs.io/ |
| httpx | 0.28.1 | BSD‑3‑Clause | Modern async HTTP client with connection pooling for high‑throughput CAP fetches. | https://www.python-httpx.org/ |
| certifi | 2025.11.12 | MPL‑2.0 | Up‑to‑date CA bundle for SSL verification (mandatory for IPAWS over TLS). | https://github.com/certifi/python-certifi |
| feedparser | 6.0.11 | BSD‑2‑Clause | Parses RSS/Atom feeds used by the LED‑sign news ticker. | https://github.com/kurtmckee/feedparser |
| orjson | 3.11.5 | Apache‑2.0 / MIT | Fast C‑backed JSON encoder/decoder for the live data feeds and Redis payloads. | https://github.com/ijl/orjson |
| ujson | 5.11.0 | BSD‑3‑Clause | Fallback fast JSON parser when `orjson` is unavailable. | https://github.com/ultrajson/ultrajson |
| PyYAML | 6.0.3 | MIT | Reads screen editor definitions and config templates. | https://pyyaml.org/ |
| lxml | 6.0.2 | BSD‑3‑Clause | High‑performance XML parser for CAP alert ingestion (5–10× faster than stdlib). | https://lxml.de/ |
| mistune | 3.1.4 | BSD‑3‑Clause | Renders the in‑app documentation viewer (`/docs/*`) from project markdown. | https://mistune.lepture.com/ |
| python‑dateutil | 2.9.0.post0 | Apache‑2.0 / BSD‑3 | Robust parsing of CAP timestamp fields with mixed offsets and tz abbreviations. | https://dateutil.readthedocs.io/ |
| pytz | 2025.2 | MIT | Time‑zone database for local display of alert effective/expire times and audit logs. | https://pythonhosted.org/pytz/ |
| python‑dotenv | 1.2.1 | BSD‑3‑Clause | Loads `.env` configuration at startup. | https://github.com/theskumar/python-dotenv |
| psutil | 7.1.3 | BSD‑3‑Clause | System‑health snapshot: CPU/mem/disk/load/temperature shields and the System Health dashboard. | https://github.com/giampaolo/psutil |
| openpyxl | 3.1.5 | MIT | XLSX export of alert history and audit reports. | https://openpyxl.readthedocs.io/ |

### Audio, SDR & signal processing

| Component | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| NumPy | 2.3.5 | BSD‑3‑Clause | Foundation for every IQ buffer, FM demod, FFT, and SAME bit slicer. Also drives the one‑click IQ capture (`numpy.save` to `.npy`). | https://numpy.org/ |
| SciPy | 1.16.3 | BSD‑3‑Clause | DSP filter design (`signal.lfilter`, FIR/IIR design) for the interference notch, deemphasis, and channel filters. | https://scipy.org/ |
| Numba | ≥ 0.61.0, < 0.64 | BSD‑2‑Clause | JIT‑compiles the inner SAME DLL and RBDS workers; ~6× faster real‑time demod on a Pi. | https://numba.pydata.org/ |
| pydub | 0.25.1 | MIT | Decodes MP3/AAC/OGG Icecast streams for the EAS audio monitor. | https://github.com/jiaaro/pydub |
| pyttsx3 | 2.99 | MPL‑2.0 | Offline TTS engine option for voice‑over narration of alert text. | https://github.com/nateshmbhat/pyttsx3 |
| audioop‑lts | 0.2.2 | Python‑2.0 | Drop‑in replacement for `audioop`, removed from the Python 3.13 stdlib but still needed by `pydub`. | https://github.com/AbstractUmbra/audioop |
| SoapySDR | system | BSL‑1.0 | Vendor‑agnostic SDR abstraction layer driving RTL‑SDR, Airspy, and SDRplay receivers. | https://github.com/pothosware/SoapySDR |
| Icecast | 2.4.4 | GPL‑2.0 | Streams the demodulated FM/AM audio over HTTP for remote monitoring and stream‑profile mounts. | https://icecast.org/ |
| FFmpeg | system | LGPL‑2.1+ / GPL‑2+ | Underlying codec backend that `pydub` shells out to for MP3/AAC decode/encode. | https://ffmpeg.org/ |
| eSpeak NG | system | GPL‑3.0 | System TTS used to narrate CAP alert summaries into the SAME envelope. | https://github.com/espeak-ng/espeak-ng |

### Hardware / I/O

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| pyserial | 3.5 | BSD‑3‑Clause | Serial transport for the VFD display, RS‑232 LED signs, and UART NMEA GPS. | https://github.com/pyserial/pyserial |
| gpiozero | 2.0.1 | BSD‑3‑Clause | High‑level GPIO control for relay HATs, PTT lines, and transmitter keying. | https://gpiozero.readthedocs.io/ |
| rpi‑ws281x | ≥ 0.0.5 | MIT | WS2812B / NeoPixel addressable LED strip driver (DMA‑backed on the Pi). | https://github.com/rpi-ws281x/rpi-ws281x-python |
| luma.oled | 3.14.0 | MIT | I2C SSD1306/SH1106 driver for the Argon OLED status panel. | https://github.com/rm-hull/luma.oled |
| Pillow | 12.0.0 | MIT‑CMU | Rasterizes glyphs and bitmaps for the VFD screen editor and OLED frames. | https://python-pillow.org/ |
| zigpy | ≥ 0.60 | GPL‑3.0 | Core Zigbee protocol stack for optional wireless sensor / device control. | https://github.com/zigpy/zigpy |
| zigpy‑znp | ≥ 0.11 | GPL‑3.0 | TI Z‑Stack (CC2652P / CC1352P) radio driver under `zigpy`. | https://github.com/zigpy/zigpy-znp |
| pynmea2 | 1.19.0 | MIT | Parses NMEA‑0183 sentences (GGA, GSA, GSV, RMC) from the GPS HAT. | https://github.com/Knio/pynmea2 |

### Timekeeping (stratum 1)

| Component | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| chrony | system | GPL‑2.0 | NTP daemon that consumes the GPS NMEA + PPS edge as a kernel refclock; serves stratum 1 NTP. | https://chrony-project.org/ |
| gpsd | system | BSD‑2‑Clause | Multiplexes the GPS UART so chrony, the dashboard, and the GPS dashboard can all read the fix simultaneously. | https://gpsd.gitlab.io/gpsd/ |

### Security / auth / notifications

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| PyOTP | 2.9.0 | MIT | TOTP generation and verification for the MFA login flow. | https://pyauth.github.io/pyotp/ |
| cryptography | ≥ 46.0.5 | Apache‑2.0 / BSD‑3‑Clause | Ed25519 signing and SHA‑256 hashing for the tamper‑evident `audit_logs` chain — every audit row is hash‑chained to its predecessor and signed so post‑hoc DB edits are detectable via `AuditLogger.verify_chain()`. | https://cryptography.io/ |
| qrcode | 8.2 | BSD‑3‑Clause | Renders the QR code shown during MFA enrollment. | https://github.com/lincolnloop/python-qrcode |
| Twilio | ≥ 9.0 | MIT | SMS delivery for alert‑forwarding and compliance‑health notifications. | https://www.twilio.com/ |
| pysnmp | ≥ 6.2 | BSD‑2‑Clause | Sends SNMP v2c traps when compliance health degrades (optional; gracefully absent). | https://pysnmp.readthedocs.io/ |

### Geospatial

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| pyshp | 3.0.3 | MIT | Reads ESRI shapefiles when importing custom county/zone boundaries into PostGIS. | https://github.com/GeospatialPython/pyshp |
| pyproj | 3.7.1 | MIT | Reprojects shapefile CRSes to WGS84 during boundary import. | https://pyproj4.github.io/pyproj/ |

### Testing & QA

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| pytest | 9.0.2 | MIT | Test runner for the whole suite (`tests/`). | https://pytest.org/ |
| pytest‑asyncio | 1.3.0 | Apache‑2.0 | Lets async coroutines run as `pytest` test functions. | https://pytest-asyncio.readthedocs.io/ |

### Front‑end vendored / CDN assets

| Library | Version | License | Purpose in EAS Station™ | Project |
|---|---|---|---|---|
| Bootstrap | 5.3.0 | MIT | CSS grid + component library underlying every dashboard layout. | https://getbootstrap.com/ |
| Font Awesome (Free) | 6.4.0 | CC BY 4.0 / SIL OFL / MIT | Icon set used throughout navigation, status pills, and badges. | https://fontawesome.com/ |
| Leaflet | 1.9.4 | BSD‑2‑Clause | Interactive maps for alert polygons, coverage zones, and county boundaries. | https://leafletjs.com/ |
| Chart.js | 3.9.1 | MIT | Time‑series charts on the Analytics, System Health, and GPS dashboards. | https://www.chartjs.org/ |
| Socket.IO client | 4.5.4 | MIT | Browser WebSocket client that receives the live alert / radio / GPS push updates. | https://socket.io/ |
| jsPDF + html2canvas | latest | MIT | Client‑side PDF export of the full Statistics dashboard. | https://github.com/parallax/jsPDF |
| Mermaid | latest | MIT | In‑browser rendering of architecture and data‑flow diagrams in the docs viewer. | https://mermaid.js.org/ |

### Data sources & boundary data

NOAA/NWS CAP API · FEMA IPAWS · U.S. Census Bureau (TIGER/Line) · PostGIS Team · Putnam County GIS · Allen County GIS

License identifiers above are best‑effort summaries — always consult the upstream project's own licensing files for the canonical terms. If you spot a discrepancy or a missing attribution, please open an issue.

---

## 🙏 Acknowledgments

NOAA/NWS · FEMA/IPAWS · PostGIS Team · U.S. Census Bureau (TIGER/Line) · Putnam County GIS Office · Allen County GIS Office · Flask Community · RTL-SDR Project · W0CHP (chrogps-dash visual reference) · Amateur Radio Community

| Resource | Link |
|----------|------|
| NOAA CAP API | https://www.weather.gov/documentation/services-web-api |
| FEMA IPAWS | https://www.fema.gov/emergency-managers/practitioners/integrated-public-alert-warning-system |
| FCC Part 11 | https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-11 |
| PostGIS Docs | https://postgis.net/documentation/ |

---

<div align="center">
  <strong>Made with ☕ and 📻 for Amateur Radio Emergency Communications</strong><br>
  <strong>73 de KR8MER</strong> 📡
</div>
