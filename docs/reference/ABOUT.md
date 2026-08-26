# ℹ️ About EAS Station™

EAS Station™ is a complete Emergency Alert System platform that automates the ingestion, encoding, broadcast, and verification of Common Alerting Protocol (CAP) alerts. Built by amateur radio operators supporting Putnam County, Ohio, it combines NOAA and IPAWS feed aggregation, FCC-compliant SAME encoding, PostGIS spatial intelligence, SDR verification, and LED signage integration into a unified operations hub.

The long-term vision is to deliver a software-driven, off-the-shelf drop-in replacement for commercial encoder/decoder appliances. Every subsystem is being designed so commodity compute, SDR front-ends, and readily available interfaces can fulfill the same mission as the traditional rack units.

EAS Station™'s reference build centers on a Raspberry Pi 5 (4 GB RAM baseline, 8 GB recommended when narration and SDR verification share the host) with HATs that expose dry-contact GPIO relays, RS-232 automation ports, and balanced audio interfaces. HDMI confidence monitoring and paired SDR receivers complete the package, proving that inexpensive, fan-less hardware can shoulder the same responsibilities as the utilitarian “black boxes” sold today.

A **GPS/RTC HAT** (Uputronics u-blox MAX-M8Q multi-GNSS or Adafruit Ultimate GPS) brings hardware Pulse-Per-Second to the kernel, letting `chrony` discipline the host as a **true stratum 1 NTP server** with sub-microsecond accuracy and a battery-backed RTC for cold-boot continuity. Every alert timestamp, audit log entry, and SAME `JJJHHMM` field is locked to the satellites with no upstream internet time required.

Raspberry Pi 4 systems remain compatible for labs but no longer represent the documented baseline. Deployments are validated on Debian 13 (Trixie) 64-bit builds. The remaining gap is disciplined software integration, a predictable setup experience, long-haul reliability, and the evidence required to pursue FCC certification.

### Python Release Strategy

- **Supported versions:** Python 3.11 is the minimum supported runtime; 3.12 and 3.13 are recommended and validated. Debian 13 (Trixie) ships Python 3.13, which the installer detects and supports out of the box.
- **SoapySDR compatibility:** The installer links the distribution's pre-compiled SoapySDR bindings (`python3-soapysdr`) into the application virtual environment, so SDR support tracks the OS Python version without from-source builds that would exhaust Raspberry Pi 5 hosts.
- **Mitigation:** The system is updated regularly with CPython patch releases, and pinned dependencies are updated alongside security advisories to ensure CVE fixes without destabilizing the hardware-specific build pipeline or SDR functionality.

## Safety Notice
- **Development status:** The project remains experimental and has only been cross-checked against community tools like [multimon-ng](https://github.com/EliasOenal/multimon-ng) for decoding parity. All other implementations, workflows, and documentation are original and subject to change.
- **Certification pending:** The team is actively building toward hardware parity, but the software is not yet an approved replacement for commercial Emergency Alert System encoders or other FCC-authorized equipment.
- **Regulatory path now opening:** FCC rules have historically assumed that EAS encoding and decoding live in dedicated, proprietary hardware. In PS Docket No. 25-224 (*Modernization of the Nation's Alerting Systems*), the Commission has proposed to permit EAS functionality to be implemented in software rather than in dedicated appliances. EAS Station™ has filed formal comments supporting that proposal ([read the filing on the FCC ECFS](https://www.fcc.gov/ecfs/search/search-filings/filing/1060881335987)). If the Commission adopts software-defined rules, a realistic regulatory path to certification opens up for projects like this one. This filing is a **first step**, not a guarantee of approval — until any such rules take effect, EAS Station™ continues to operate as experimental and uncertified.
- **Lab use only (for now):** Operate EAS Station™ strictly in test environments and never rely on it for live public warning, life safety, or mission-critical decisions until the roadmap is complete and certification paths are pursued.
- **Review legal docs:** Before inviting collaborators or storing data, read the repository [Terms of Use](../policies/TERMS_OF_USE.md) and [Privacy Policy](../policies/PRIVACY_POLICY.md).
- **Real operational semantics only — not for entertainment or media production:** EAS Station™ is built to emulate the *actual* operational behavior of certified EAS encoder/decoder equipment so that researchers, broadcasters, and Part 97 amateur radio operators can study, decode, and exercise the real protocol. It is **not** a creative or content-production toolkit. Do **not** author fictional, fabricated, satirical, or "what-if" EAS workflows (invented event codes, mock CAP feeds presented as real, joke RWT/RMT cycles, imagined alert scenarios) with this software, and do **not** use any of its generated audio, headers, captures, or screenshots in films, TV, trailers, advertising, podcasts, streaming programming, video games, livestream stunts, prank or "creepypasta" content, ARGs, haunted-attraction sound design, or any other entertainment or media production. Labeling content as fiction does **not** cure the violation — 47 C.F.R. § 11.45 prohibits EAS code/Attention Signal broadcast outside actual emergencies and authorized tests regardless of intent (see the *Olympus Has Fallen* trailer case in [Terms of Use § 4b](../policies/TERMS_OF_USE.md)).

## Mission and Scope
- **Primary Goal:** Provide emergency communications teams with automated CAP-to-EAS workflow, from alert ingestion through broadcast verification, with complete compliance documentation.
- **Drop-In Replacement Roadmap:** Targeting parity with commercial encoders across baseband capture, deterministic playout, hardware control, security, resilience, turnkey deployment, compliance analytics, unified documentation, and certification readiness — so the platform can mirror commercial decoder capabilities on commodity hardware.
- **Deployment Model:** Bare-metal systemd architecture for Raspberry Pi or x86 Linux nodes, with a PostgreSQL/PostGIS database service that may be local or external.
- **Operational Focus:** Multi-source alert aggregation, automatic SAME broadcast generation, SDR-based verification, spatial boundary awareness, and audit trail management.

## Current Development Status
See the [Changelog](CHANGELOG.md) for detailed progress and recent releases, including completed features like audio ingest, security controls, and analytics.

## Core Services

![Diagram showing the ingestion and control services flowing into the processing core, which then feeds verification and output capabilities.](../assets/diagrams/core-services-overview.svg)

## Software Stack
The application combines open-source tooling and optional cloud integrations. Versions below match the pinned dependencies in `requirements.txt` unless noted otherwise.

### Application Framework
- Python 3.13 runtime (compatible with current Debian/Raspberry Pi OS SoapySDR bindings)
- Flask 3.1.2 web framework
- Werkzeug 3.1.4 WSGI utilities
- Flask-SQLAlchemy 3.1.1 ORM integration
- SQLAlchemy 2.0.45 ORM core
- Gunicorn production WSGI server

### Data and Spatial Layer
- PostgreSQL 17 with the PostGIS extension (external service)
- GeoAlchemy2 0.18.1 for spatial ORM bindings
- psycopg2-binary 2.9.11 PostgreSQL driver

### System and Utilities
- requests 2.32.5 for CAP feed retrieval and IPAWS integration
- pytz 2025.2 timezone utilities
- psutil 7.1.3 system health and receiver monitoring
- python-dotenv 1.2.1 configuration loading
- cryptography — Ed25519 signing and SHA-256 hashing backing the tamper-evident `audit_logs` chain (see `app_core/auth/audit.py::AuditLogger.verify_chain`)

### Front-End Tooling
- Bootstrap 5 UI framework
- Font Awesome iconography
- Highcharts visualization library

### Optional Integrations
- Azure Cognitive Services Speech SDK 1.38.0 (optional AI narration)
- Systemd for service orchestration and management

## Data Sources & Attribution

EAS Station™ relies on publicly available geographic data to enable spatial filtering, boundary-aware alert processing, and location-based targeting.

### Geographic Data Providers

- **Putnam County GIS Office** - County and municipal boundary shapefiles, reference geographic data
  - Greg Luersman, GIS Coordinator
  - https://www.putnamcountygis.com/Downloads.html
  - Licensed under Public Domain / Open Data terms

- **Allen County GIS Office** - County and municipal boundary shapefiles, reference geographic data
  - Alexis Foundas, GIS Coordinator
  - Licensed under Public Domain / Open Data terms

- **U.S. Census Bureau** - FIPS county codes and TIGER/Line state/county boundaries
  - Public Domain federal data

- **NOAA National Weather Service** - Weather forecast zone boundaries and definitions
  - Public Domain federal data

For complete attribution details, see the `## 📚 Attributions & Open-Source Credits` section of the repository [`README.md`](https://github.com/KR8MER/eas-station/blob/main/README.md).

## Governance and Support
- **Issue Tracking:** Use GitHub issues for bug reports and feature requests.
- **Documentation Updates:** User-facing changes must update the README, HELP, and CHANGELOG entries.
- **Environment Variables:** Any new variables must be mirrored in `.env.example` per contributor guidelines.
- **Release Accounting:** Each deployment must surface the repository `VERSION` manifest in the UI, log its commit hash, and append the relevant entry to [`CHANGELOG.md`](CHANGELOG.md) so the operational history is auditable.
- **Automation Guardrails:** The repository `VERSION` file, shared version resolver, and release metadata test will fail builds when the reported version and changelog drift—keep them aligned before requesting review.
- **Upgrade & Backup Tooling:** Use `python tools/create_backup.py` for pre-flight snapshots and `python tools/inplace_upgrade.py` to roll forward without wiping containers or volumes. The Admin console exposes one-click buttons for both tasks under System Operations, calling the same helpers and recording their status for operators.

## Maintainer Profile
Timothy Kramer (KR8MER) serves as the project's maintainer. Licensed as an amateur radio operator since 2004 and upgraded to General Class in 2025, Kramer brings 17 years of public-safety service as a deputy sheriff and deep familiarity with Motorola mission-critical communications. He now works as a full-time electrical panel electrician while supporting Skywarn operations and a laboratory of professional-grade radios, SDR capture nodes, digital paging systems, and networking equipment. EAS Station reflects his goal of pairing disciplined engineering practices with experimental emergency communications research.

### Contact

- **Email:** [Timothy.Kramer@easstation.com](mailto:Timothy.Kramer@easstation.com)
- **Phone:** (419) 890-1890
- **GitHub:** [github.com/KR8MER/eas-station](https://github.com/KR8MER/eas-station) (issues and discussions)
- **Commercial licensing / legal notices:** [sales@easstation.com](mailto:sales@easstation.com)

For setup instructions, operational tips, and troubleshooting guidance, refer to the dedicated [HELP documentation](../guides/HELP.md).
