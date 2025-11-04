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
| numpy 1.26.4 | NumPy developers | BSD-3-Clause | Provides efficient vectorised math used by SciPy audio resampling routines. |
| packaging 25.0 | PyPA (Python Packaging Authority) | Apache-2.0 OR BSD-2-Clause | Parses and normalises version specifiers for setup checks and dependency guards. |
| psycopg2-binary 2.9.10 | Psycopg Project (Federico Di Gregorio, Daniele Varrazzo, et al.) | LGPL-3.0 with linking exception | PostgreSQL client driver connecting the application to PostGIS. |
| psutil 6.1.1 | Giampaolo Rodolà & contributors | BSD-3-Clause | Collects CPU, memory, disk, and network metrics for the system health dashboard. |
| pyttsx3 2.90 | `nateshmbhat` (Natesh M Bhat) & contributors | BSD-3-Clause | Offline text-to-speech engine used for narrated alert audio when the voice provider is enabled. |
| python-dotenv 1.0.1 | Saurabh Kumar & python-dotenv contributors | BSD-3-Clause | Loads configuration values from the `.env` file during startup and CLI utilities. |
| pytz 2024.2 | Stuart Bishop | MIT | Provides the IANA time zone database for accurate scheduling and timestamps. |
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

All dependencies are sourced from public repositories published under OSI-approved licenses. Ensure that attribution for BSD and MIT packages accompanies any redistribution of EAS Station binaries or container images.
