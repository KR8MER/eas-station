# 📜 Attribution & Open-Source Credits

EAS Station™ stands on a deep stack of open-source software, public data feeds,
and community standards. This page is the **canonical, exhaustive** record of
everything the platform depends on and how it is licensed. A friendlier,
branded summary is available in the running application at **`/attribution`**
(Help → Attribution & Credits).

> **Keep this in sync.** When you add or bump a dependency you must update
> `requirements.txt` (or the apt package list), the footer badge strip
> (`templates/partials/tech_stack_badges.html`), the README badge block, and
> this file. The drift guard `tests/test_tech_stack_badges.py` enforces the
> badge ↔ requirements relationship.

---

## EAS Station™ Itself

| Item | Detail |
| --- | --- |
| **Copyright** | © 2025–2026 EAS Station, LLC (KR8MER) |
| **License** | Dual-licensed: **AGPL-3.0** (`LICENSE`) **or** Commercial (`LICENSE-COMMERCIAL`) |
| **Required attribution** | `"Powered by EAS Station - Copyright (c) 2025-2026 EAS Station, LLC (KR8MER)"` (see `NOTICE`) |
| **Trademarks & branding** | "EAS Station", logos, and wordmarks are **not** covered by the software licenses — see `docs/policies/TRADEMARK_POLICY.md` |
| **Repository** | <https://github.com/KR8MER/eas-station> |

When deploying under the AGPL you **must preserve** the copyright and license
notices and may not rebrand the software or strip attribution. See `NOTICE` for
the complete terms.

---

## Python Dependencies

All versions track `requirements.txt`. Licenses are the upstream project
licenses at the time of writing; consult each project for authoritative terms.

### Application Framework

| Package | Purpose | License |
| --- | --- | --- |
| **Flask** | Web framework powering every route & API | BSD-3-Clause |
| **Werkzeug** | WSGI plumbing under Flask (routing, requests) | BSD-3-Clause |
| **Jinja2** | Server-side HTML template engine | BSD-3-Clause |
| **itsdangerous** | Secure session cookies & CSRF tokens | BSD-3-Clause |
| **Flask-SQLAlchemy** | Flask ORM integration | BSD-3-Clause |
| **Flask-Caching** | Response & metric caching | BSD-3-Clause |
| **Flask-SocketIO** / **python-socketio** | WebSocket channel for live updates | MIT |
| **Flask-WTF** | CSRF protection & form validation | BSD-3-Clause |
| **Flask-Limiter** | Rate limiting (Redis/memory backend) | MIT |
| **Flask-Compress** / **Brotli** | gzip/Brotli response compression | MIT |
| **gunicorn** | Production WSGI server | MIT |
| **gevent** / **greenlet** | Async workers for Socket.IO under Gunicorn | MIT |

### Data & Spatial Layer

| Package | Purpose | License |
| --- | --- | --- |
| **SQLAlchemy** | ORM behind every persisted entity | MIT |
| **psycopg2-binary** | PostgreSQL driver | LGPL-3.0 (with exception) |
| **GeoAlchemy2** | PostGIS spatial extensions for SQLAlchemy | MIT |
| **Alembic** | Schema migrations (runs on every install/update) | MIT |
| **pyshp** | ESRI Shapefile reader for boundary conversion | MIT |
| **pyproj** | CRS reprojection from shapefile `.prj` to WGS84 | MIT |
| **geoip2** / **maxminddb** | Country-level visitor geolocation (Traffic Analytics) | Apache-2.0 / MIT |

### Networking, Parsing & I/O

| Package | Purpose | License |
| --- | --- | --- |
| **requests** | HTTP client for CAP feed polling | Apache-2.0 |
| **httpx** | Modern async HTTP client with pooling | BSD-3-Clause |
| **certifi** | CA bundle for SSL verification (required for IPAWS) | MPL-2.0 |
| **feedparser** | RSS/Atom parsing for the LED sign ticker | BSD-2-Clause |
| **lxml** | Fast C-based XML parser for CAP processing | BSD-3-Clause |
| **BeautifulSoup4** | XML/HTML parsing for CAP messages | MIT |
| **orjson** / **ujson** | Fast JSON parsers | Apache-2.0 / MIT / BSD |
| **PyYAML** | YAML parsing | MIT |
| **python-dateutil** / **pytz** | Datetime parsing & timezones | Apache-2.0 / MIT |
| **python-dotenv** | `.env` configuration loading | BSD-3-Clause |
| **mistune** | Markdown rendering for the docs viewer | BSD-3-Clause |
| **openpyxl** | Spreadsheet exports | MIT |

### Audio, SDR & Signal Processing

| Package | Purpose | License |
| --- | --- | --- |
| **numpy** | Sample processing for SoapySDR & EAS resampling | BSD-3-Clause |
| **scipy** | Advanced signal processing (optional) | BSD-3-Clause |
| **numba** | JIT compilation for real-time FM/RBDS demodulation | BSD-2-Clause |
| **pydub** | Audio stream decoding (MP3/AAC/OGG) | MIT |
| **audioop-lts** | `audioop` replacement for Python 3.13+ | Python-2.0 |
| **pyttsx3** | Offline text-to-speech engine | Mozilla/BSD |
| **SoapySDR** (system binding) | SDR receiver abstraction | Boost-1.0 |
| **pyalsaaudio** (optional) | ALSA capture bindings for the ALSA audio source adapter | PSF-2.0 |
| **PyAudio** (optional) | PortAudio capture bindings for the PulseAudio source adapter | MIT |

### Hardware Integration

| Package | Purpose | License |
| --- | --- | --- |
| **pyserial** | Serial comms for VFD display and GPS HAT | BSD-3-Clause |
| **pynmea2** | NMEA-0183 GPS sentence parsing | MIT |
| **Pillow** | Image rendering for VFD/OLED graphics | MIT-CMU (HPND) |
| **luma.oled** | I²C SSD1306/SH1106 OLED driver | MIT |
| **gpiozero** | Raspberry Pi GPIO control | BSD-3-Clause |
| **rpi-ws281x** | WS2812B/NeoPixel addressable LED control | BSD-2-Clause |
| **zigpy** / **zigpy-znp** | Zigbee protocol stack & Z-Stack radio driver | GPL-3.0 / GPL-3.0 |

### Security, Notifications & Ops

| Package | Purpose | License |
| --- | --- | --- |
| **cryptography** | Ed25519 signatures for the tamper-evident audit chain | Apache-2.0 / BSD-3-Clause |
| **pyotp** | TOTP generation/verification for MFA | MIT |
| **qrcode** | QR code generation for MFA enrollment | BSD-3-Clause |
| **twilio** | SMS alert delivery | MIT |
| **pysnmp** | SNMP v2c trap notifications | BSD-2-Clause |
| **psutil** | System resource monitoring | BSD-3-Clause |
| **redis** / **hiredis** | State management & inter-service pub/sub | MIT / BSD-3-Clause |
| **pytest** / **pytest-asyncio** | Test framework (web UI test runner) | MIT |

---

## Infrastructure & System Packages

| Component | Purpose | License |
| --- | --- | --- |
| **PostgreSQL + PostGIS** | Spatial database; geographic alert filtering | PostgreSQL License / GPL-2.0 |
| **Redis** | Metrics cache & inter-service messaging | BSD-3-Clause / RSALv2/SSPL (newer) |
| **nginx** | Reverse proxy / TLS termination | BSD-2-Clause |
| **certbot** | Automated Let's Encrypt certificate management | Apache-2.0 |
| **Icecast** | Audio streaming server | GPL-2.0 |
| **ffmpeg** (libav*) | Audio transcoding for stream decoding | LGPL-2.1 / GPL-2.0 |
| **systemd** | Native service orchestration | LGPL-2.1 |
| **chrony** | NTP discipline / stratum-1 timekeeping | GPL-2.0 |
| **gpsd** | GPS daemon for the GPS/RTC HAT | BSD-3-Clause |
| **espeak-ng** | Offline speech backend for pyttsx3 | GPL-3.0 |
| **Postfix** | Optional local mail server | IPL-1.0 / EPL-2.0 |
| **fail2ban** | Host-level intrusion banning (Security Center → fail2ban) | GPL-2.0+ |
| **ALSA** (libasound2-dev, alsa-utils) | Sound-card capture layer for the ALSA source adapter | LGPL-2.1 |
| **PortAudio** (portaudio19-dev) | Cross-platform audio I/O backing PyAudio | MIT |

---

## Frontend Assets

| Asset | Purpose | License |
| --- | --- | --- |
| **Bootstrap 5** | Mobile-first responsive UI framework | MIT |
| **Font Awesome (Free)** | UI iconography | CC BY 4.0 / SIL OFL 1.1 / MIT |
| **Socket.IO client** | Browser WebSocket client | MIT |
| **Chart.js** | Analytics charts & sparklines | MIT |
| **simple-icons** | Brand marks for tech-stack badges | CC0-1.0 |
| **Flag assets** | Country flags for Traffic Analytics | Public domain / CC0 |

---

## Data Sources & Standards

| Source | Use | Terms |
| --- | --- | --- |
| **NOAA / National Weather Service CAP feeds** | Primary alert ingestion | U.S. Government public data |
| **FEMA IPAWS / IPAWS-OPEN** | Authenticated alert aggregation | U.S. Government public data |
| **U.S. Census Bureau TIGER/Line** | County/zone boundary geometry | U.S. Government public domain |
| **FIPS / SAME location codes** | Geographic targeting (see `FIPS_DATA_SOURCES.md`) | U.S. Government public domain |
| **Iowa Environmental Mesonet** ([mesonet.agron.iastate.edu](https://mesonet.agron.iastate.edu/ogc/)) | NEXRAD Level III base reflectivity (WMS-T mosaic) for the weather-alert radar overlay | Public data, Iowa State University |
| **MaxMind GeoLite2** (operator-supplied) | Visitor geolocation in Traffic Analytics | CC BY-SA 4.0 (operator obtains DB) |
| **NRSC-4-B / SAME, NWS VTEC, RBDS standards** | Protocol implementation references | Published industry standards |
| **multimon-ng** | Decoding-parity cross-check (not bundled) | GPL-2.0 |

GeoLite2 data is **not** distributed with EAS Station — operators supply their
own MaxMind database. See `app_core/analytics/geo.py`.

---

## Acknowledgments

- **The Pallets Projects** (Flask, Jinja2, Werkzeug, itsdangerous, Click)
- **The PostGIS & PostgreSQL teams** for spatial database technology
- **The RTL-SDR / SoapySDR project** for accessible software-defined radio
- **The amateur radio community** for testing, feedback, and field validation
- Every upstream maintainer whose work is listed above

---

*Something missing or mis-licensed? Open an issue at
<https://github.com/KR8MER/eas-station/issues> so we can correct the record.*
