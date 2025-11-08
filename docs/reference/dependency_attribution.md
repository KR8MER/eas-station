# Open-Source Dependency Attribution

The EAS Station application is built entirely on open-source libraries. The table below lists each Python dependency, its primary maintainers, licensing, and how the project uses it.

| Library & Version | Upstream Project / Maintainers | License | Purpose in EAS Station |
| --- | --- | --- | --- |
| Alembic 1.14.0 | Mike Bayer & SQLAlchemy community | MIT | Schema migration engine to version-control the database layout. |
| certifi 2025.10.5 | Kenneth Reitz & Mozilla maintainers | MPL-2.0 | Provides the curated bundle of Certificate Authority roots that secure outbound HTTPS requests. |
| charset-normalizer 3.4.4 | Ahmed TAHRI CHERIF & contributors | MIT | Detects and normalises text encodings when decoding HTTP payloads. |
| click 8.2.1 | Armin Ronacher & Pallets team | BSD-3-Clause | Powers the project’s command-line interfaces and Flask’s CLI integration. |
| Flask 3.0.3 | Pallets Projects (founded by Armin Ronacher) | BSD-3-Clause | Core web framework powering the operator UI and REST API. |
| Flask-SQLAlchemy 3.1.1 | Pallets Projects | BSD-3-Clause | Integrates SQLAlchemy ORM with Flask’s application context and configuration system. |
| GeoAlchemy2 0.15.2 | GeoAlchemy maintainers (Olivier Verdier & contributors) | MIT | Adds spatial column types and functions so PostGIS geometries can be queried through SQLAlchemy. |
| greenlet 3.2.4 | Armin Ronacher & contributors | MIT | Implements lightweight coroutines used internally by SQLAlchemy for async-aware database engines. |
| gunicorn 23.0.0 | Benoît Chesneau & Gunicorn maintainers | MIT | Production WSGI server that hosts the Flask application. |
| idna 3.11 | Kim Davies & contributors | BSD-3-Clause | Implements Internationalized Domain Name handling for outbound HTTP requests. |
| itsdangerous 2.2.0 | Pallets Projects | BSD-3-Clause | Provides signed token helpers that secure session data and password reset links. |
| Jinja2 3.1.6 | Pallets Projects | BSD-3-Clause | Template engine that renders the operator web interface. |
| Mako 1.3.10 | Mike Bayer & contributors | MIT | Renders dynamic content for Alembic migration scripts. |
| MarkupSafe 3.0.3 | Armin Ronacher & contributors | BSD-3-Clause | Escapes HTML content inside templates to prevent injection vulnerabilities. |
| numpy 2.2.1 | NumPy developers | BSD-3-Clause | Provides efficient vectorised math used by SciPy audio resampling routines and SoapySDR sample processing. |
| packaging 25.0 | PyPA (Python Packaging Authority) | Apache-2.0 OR BSD-2-Clause | Parses and normalises version specifiers for setup checks and dependency guards. |
| Pillow 10.4.0 | Pillow team (Alex Clark & contributors) | HPND | Image processing library used to render graphics for the Noritake VFD display. |
| psycopg2-binary 2.9.10 | Psycopg Project (Federico Di Gregorio, Daniele Varrazzo, et al.) | LGPL-3.0 with linking exception | PostgreSQL client driver connecting the application to PostGIS. |
| psutil 6.1.1 | Giampaolo Rodolà & contributors | BSD-3-Clause | Collects CPU, memory, disk, and network metrics for the system health dashboard. |
| pydub 0.25.1 | James Robert (jiaaro) & contributors | MIT | Audio segment manipulation and decoding library supporting MP3, AAC, and OGG streams from HTTP and Icecast sources. Requires ffmpeg system package. |
| pyotp 2.9.0 | PyOTP contributors | MIT | Implements TOTP (Time-based One-Time Password) generation and verification for multi-factor authentication. |
| pyserial 3.5 | Chris Liechti & contributors | BSD-3-Clause | Serial port communication library used to control the Noritake GU140x32F-7000B VFD display. |
| pyttsx3 2.90 | `nateshmbhat` (Natesh M Bhat) & contributors | BSD-3-Clause | Offline text-to-speech engine used for narrated alert audio when the voice provider is enabled. |
| python-dotenv 1.0.1 | Saurabh Kumar & python-dotenv contributors | BSD-3-Clause | Loads configuration values from the `.env` file during startup and CLI utilities. |
| PyYAML 6.0.2 | Ingy döt Net, Kirill Simonov & contributors | MIT | YAML parser and emitter used for Docker Compose validation scripts. |
| pytz 2024.2 | Stuart Bishop | MIT | Provides the IANA time zone database for accurate scheduling and timestamps. |
| qrcode 8.0 | Lincoln Loop & contributors | BSD | QR code generation library used for multi-factor authentication enrollment. |
| requests 2.32.3 | Kenneth Reitz & Requests contributors | Apache-2.0 | Fetches CAP feeds, remote APIs, and supporting metadata over HTTP(S). |
| SciPy 1.14.1 | SciPy community | BSD-3-Clause | Supplies signal-processing helpers for audio resampling when ffmpeg is unavailable. |
| SQLAlchemy 2.0.44 | SQLAlchemy authors (led by Mike Bayer) | MIT | Object-relational mapper used for database models, queries, and migrations. |
| typing-extensions 4.15.0 | Python Software Foundation | PSF-2.0 | Backports modern typing features used throughout the codebase. |
| urllib3 2.5.0 | urllib3 maintainers (Seth Michael Larson & contributors) | MIT | Low-level HTTP client powering requests’ connection pooling and TLS handling. |
| Werkzeug 3.0.6 | Pallets Projects | BSD-3-Clause | Supplies the WSGI utilities and request/response handling used by Flask. |

## Optional Providers

The following packages are commented in `requirements.txt` and only required when their corresponding features are enabled.

| Library & Version | Upstream Project / Maintainers | License | Optional Purpose |
| --- | --- | --- | --- |
| json5 0.9.14 | JSON5 community | MIT | Allows parsing of JSON5 configuration files when environments require them. |
| python-dateutil 2.8.2 | Dateutil maintainers (led by Gustavo Niemeyer) | BSD-3-Clause | Enhances datetime parsing in integrations that require ISO8601 variations. |
| azure-cognitiveservices-speech 1.38.0 | Microsoft Azure Cognitive Services team | MIT | Cloud-based speech synthesis provider for narrated alerts. |
| flask-debugtoolbar 0.13.1 | Flask DebugToolbar maintainers | BSD-3-Clause | Development-only debugging overlay. |
| RPi.GPIO 0.7.1+ | Ben Croston & contributors | MIT | Raspberry Pi GPIO control for relay boards (Raspberry Pi hardware only). |

## System Package Dependencies

The following system packages are installed via the Dockerfile and are required for core functionality. These are not Python packages and must be installed using the system package manager (apt).

| Package | Purpose | License | Required For |
| --- | --- | --- | --- |
| **ffmpeg** | Audio codec library with libavcodec and libavformat support | LGPL-2.1+ or GPL-2+ | **CRITICAL** - Required by pydub for MP3/AAC/OGG stream decoding |
| **python3-soapysdr** | SoapySDR Python bindings for Software Defined Radio | Boost Software License 1.0 | **CRITICAL** - Required for SDR receiver support |
| **icecast2** | Streaming media server for audio broadcasting | GPL-2.0 | Audio streaming output (optional but recommended) |
| **libpq-dev** | PostgreSQL client library development headers | PostgreSQL License | Required for building psycopg2 from source |
| **libusb-1.0-0** / **libusb-1.0-0-dev** | USB device access library | LGPL-2.1+ | Required for USB SDR hardware (RTL-SDR, Airspy) |
| **espeak** / **libespeak-ng1** | Text-to-speech synthesis engine | GPL-3.0 | Required by pyttsx3 for offline voice generation |
| **ca-certificates** | Common CA certificates for SSL/TLS | MPL-2.0 & GPL-2.0+ | HTTPS connections and certificate validation |
| **build-essential** | C/C++ compiler toolchain (gcc, g++, make) | GPL-3.0 | Building native Python extensions |
| **soapysdr-tools** | Command-line utilities for SDR testing | Boost Software License 1.0 | SDR diagnostics and device enumeration |
| **soapysdr-module-rtlsdr** | RTL-SDR hardware driver for SoapySDR | MIT | RTL-SDR USB dongle support (conditional install) |
| **soapysdr-module-airspy** | Airspy hardware driver for SoapySDR | MIT | Airspy SDR hardware support (conditional install) |

### Icecast Streaming Server Dependencies

The following system packages are used in the optional Icecast2 streaming container (see `Dockerfile.icecast`):

| Package | Purpose | License |
| --- | --- | --- |
| **icecast2** | Streaming media server | GPL-2.0 |
| **gosu** | Lightweight sudo alternative for Docker privilege dropping | GPL-3.0 |
| **wget** / **curl** | HTTP client utilities for healthchecks and downloads | GPL-3.0 / MIT |
| **perl** | Scripting language for entrypoint script processing | Artistic-2.0 / GPL-1.0+ |

## Documentation Build Dependencies

The following Python packages are used to build the documentation website locally (see `requirements-docs.txt`). They are not required for running the application.

| Library & Version | Upstream Project / Maintainers | License | Purpose |
| --- | --- | --- | --- |
| mkdocs ≥1.5.3 | MkDocs maintainers | BSD-2-Clause | Static site generator for project documentation |
| mkdocs-material ≥9.5.3 | Martin Donath & contributors | MIT | Material Design theme for MkDocs documentation |
| mkdocs-minify-plugin ≥0.8.0 | Brian R. Jackson & contributors | MIT | HTML, CSS, and JavaScript minification for documentation |
| pymdown-extensions ≥10.7 | Isaac Muse & contributors | MIT | Markdown extensions adding syntax highlighting and advanced formatting |

---

All dependencies are sourced from public repositories published under OSI-approved licenses. Ensure that attribution for BSD and MIT packages accompanies any redistribution of EAS Station binaries or container images.
