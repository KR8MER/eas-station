# EAS Station — DASDEC-III Feature Roadmap

This document tracks progress toward feature parity with commercial EAS encoder/decoder appliances
such as the Digital Alert Systems DASDEC-III. Progress is organized around nine requirement areas
that together define a production-ready, FCC-certifiable Emergency Alert System platform.

> **Status:** Experimental / Lab Use Only — not yet approved for production emergency alerting.

---

## Requirement Area 1 — Baseband Audio Capture

Capture and decode SAME-encoded EAS audio from broadcast sources using software-defined radio or
analog audio inputs.

| Feature | Status | Notes |
|---------|--------|-------|
| RTL-SDR receiver integration | ✅ Complete | Via SoapySDR |
| Airspy receiver support | ✅ Complete | Via SoapySDR |
| FM broadcast demodulation | ✅ Complete | WBFM → baseband audio |
| SAME header FSK demodulation | ✅ Complete | Goertzel-based, vectorised |
| 16 kHz resampling pipeline | ✅ Complete | `ResamplingBroadcastAdapter` |
| Multi-receiver simultaneous monitoring | ✅ Complete | Per-receiver worker threads |
| EAS decoder audio monitor tap | ✅ Complete | Configurable Icecast stream |
| Analog line-in capture | ⏳ Planned | ALSA source adapter |

---

## Requirement Area 2 — Deterministic Alert Playout

Generate and play FCC-compliant SAME-encoded audio alerts with attention tone and end-of-message
bursts at deterministic timing.

| Feature | Status | Notes |
|---------|--------|-------|
| SAME header encoding (FSK) | ✅ Complete | Three-burst per FCC §11.31 |
| 853/960 Hz attention tone | ✅ Complete | Configurable duration 1–25 s |
| Voice narration via TTS | ✅ Complete | Azure OpenAI, Azure Cognitive, pyttsx3 |
| End-of-message burst | ✅ Complete | NNNN marker |
| Audio file output to disk | ✅ Complete | WAV/PCM format |
| `aplay` / `paplay` playback | ✅ Complete | Configurable audio player |
| EAS broadcast enable/disable switch | ✅ Complete | Database setting |
| Originator and station-ID configuration | ✅ Complete | Database setting |
| Manual EAS activation workflow | ✅ Complete | Web-based broadcast builder |
| Required Weekly Test scheduler | ✅ Complete | Automated RWT generation |

---

## Requirement Area 3 — Hardware Control

Interface with physical relay, display, and indicator hardware common to broadcast-facility EAS
installations.

| Feature | Status | Notes |
|---------|--------|-------|
| GPIO relay activation | ✅ Complete | Raspberry Pi GPIO via RPi.GPIO |
| GPIO pin mapping UI | ✅ Complete | Configurable output assignments |
| GPIO audit log | ✅ Complete | Every activation recorded |
| Alpha Protocol LED sign control | ✅ Complete | Serial M-Protocol + WYSIWYG preview |
| VFD (vacuum fluorescent) display | ✅ Complete | Multiple protocols |
| OLED display support | ✅ Complete | Via HardwareSettings |
| Zigbee device integration | ✅ Complete | Coordinator management via web UI |
| RS-232 automation port | ⏳ Planned | Direct UART signalling |
| Balanced audio I/O HAT | ⏳ Planned | WM8731/PCM3060 HAT support |

---

## Requirement Area 4 — Security and Access Control

Protect the operations console from unauthorised access and provide a complete audit trail for FCC
compliance documentation.

| Feature | Status | Notes |
|---------|--------|-------|
| Local user authentication | ✅ Complete | Username + password |
| TOTP multi-factor authentication | ✅ Complete | RFC 6238 TOTP |
| Role-based access control (RBAC) | ✅ Complete | Per-resource permission model |
| Session management | ✅ Complete | Token rotation, concurrent-session limits |
| Malicious login detection | ✅ Complete | Brute-force blocking |
| Audit logging | ✅ Complete | All administrative actions |
| HTTPS / Let's Encrypt | ✅ Complete | Automated Certbot renewal |
| Tailscale mesh VPN | ✅ Complete | Zero-config remote access |
| Email DKIM signing | ⏳ Planned | opendkim integration |

---

## Requirement Area 5 — Resilience and Reliability

Ensure continuous, unattended operation during network outages, power transitions, and upstream
feed failures.

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-source CAP feed polling | ✅ Complete | NOAA + IPAWS + custom feeds |
| Poll failure detection and logging | ✅ Complete | PollHistory records |
| Separated service architecture | ✅ Complete | Independent systemd units |
| Redis metrics caching | ✅ Complete | Decouples UI from live data |
| PostgreSQL persistence | ✅ Complete | All alerts, settings, logs in DB |
| Database migration management | ✅ Complete | Alembic with auto-apply on startup |
| Backup and restore tooling | ✅ Complete | One-click web UI |
| Duplicate alert suppression | ✅ Complete | Content-hash deduplication |
| Local GPS time source | ⏳ Planned | `gpsd` integration for stratum-1 timing |

---

## Requirement Area 6 — Turnkey Deployment

Allow a non-developer operator to install, configure, and operate the system from the web interface
with minimal command-line interaction.

| Feature | Status | Notes |
|---------|--------|-------|
| Automated install script | ✅ Complete | `install.sh` |
| Automated update script | ✅ Complete | `update.sh` |
| Database-backed configuration | ✅ Complete | All settings stored in PostgreSQL |
| Settings Hub web UI | ✅ Complete | Single-page access to all settings |
| WiFi configuration via web | ✅ Complete | NetworkManager integration |
| Icecast streaming setup via web | ✅ Complete | Stream profiles and server config |
| Certbot SSL via web | ✅ Complete | One-click certificate request/renew |
| Container image (Docker) | ✅ Complete | `Dockerfile` provided |
| ARM64 / Raspberry Pi 5 support | ✅ Complete | Native Debian 13 + Docker |
| Out-of-box sensible defaults | ✅ Complete | Pre-seeded database settings |

---

## Requirement Area 7 — Compliance Analytics

Provide operators with the evidence required to demonstrate FCC EAS compliance, including Required
Weekly Test records, alert delivery reports, and long-term trend data.

| Feature | Status | Notes |
|---------|--------|-------|
| Required Weekly Test scheduler | ✅ Complete | Automated RWT with configurable window |
| Alert delivery reports | ✅ Complete | Per-alert status records |
| Compliance dashboard | ✅ Complete | FCC §11.61 pass/fail indicators |
| Alert export (JSON / CAP / CSV) | ✅ Complete | Downloadable records |
| PDF export for audit trail | ✅ Complete | Alert and log PDF downloads |
| Analytics dashboard | ✅ Complete | Trends, event-type breakdown |
| PostGIS coverage calculation | ✅ Complete | Geographic coverage per alert |
| 90-day log retention (configurable) | ✅ Complete | Application Settings control |
| SNMP health notifications | ✅ Complete | v2c traps to NMS targets |
| Email health notifications | ✅ Complete | SMTP alerts for system issues |

---

## Requirement Area 8 — Unified Documentation

Provide operators, developers, and evaluators with clear, accurate documentation covering
installation, operation, hardware, security, and compliance.

| Feature | Status | Notes |
|---------|--------|-------|
| Installation quick-start guide | ✅ Complete | `docs/installation/` |
| User help documentation | ✅ Complete | `docs/guides/HELP.md` + `/help` page |
| Hardware setup guides | ✅ Complete | SDR, GPIO, LED, VFD, GPS, Zigbee |
| Troubleshooting guides | ✅ Complete | Per-subsystem articles |
| Security documentation | ✅ Complete | `docs/security/SECURITY.md` |
| Architecture documentation | ✅ Complete | System architecture + theory of operation |
| API/JavaScript reference | ✅ Complete | `docs/frontend/` |
| CHANGELOG | ✅ Complete | `docs/reference/CHANGELOG.md` |
| Dependency attribution | ✅ Complete | `docs/reference/dependency_attribution.md` |
| Developer agent guidelines | ✅ Complete | `docs/development/AGENTS.md` |
| In-app documentation viewer | ✅ Complete | `/docs/` route serves markdown files |
| DASDEC-III feature comparison | ✅ Complete | `docs/reference/DASDEC_COMPARISON.md` |

---

## Requirement Area 9 — Certification Readiness

Prepare the evidence package and procedural documentation required to pursue FCC Part 11 equipment
authorisation for a software-defined EAS encoder/decoder.

| Feature | Status | Notes |
|---------|--------|-------|
| FCC §11.31 SAME encoding verified | ✅ Complete | Tested against multimon-ng |
| Three-burst SAME header | ✅ Complete | FCC §11.31(c) |
| Attention tone duration range | ✅ Complete | 8–25 s per §11.31(d) |
| EOM burst present | ✅ Complete | FCC §11.31(e) |
| Required Weekly Test automation | ✅ Complete | FCC §11.61(a)(1) |
| Required Monthly Test support | ✅ Complete | FCC §11.61(a)(3) |
| Compliance dashboard evidence view | ✅ Complete | Exportable for FCC audit |
| FCC Part 11 certification filing | ⏳ Planned | Requires completed evidence package |
| Third-party interoperability testing | ⏳ Planned | Cross-test with DASDEC, SAGE, TFT |
| EAS Participants handbook alignment | ⏳ Planned | Full §11.55 workflow verification |

---

## Summary

| Requirement Area | Complete | Planned |
|-----------------|----------|---------|
| 1 — Baseband Capture | 7 | 1 |
| 2 — Deterministic Playout | 10 | 0 |
| 3 — Hardware Control | 7 | 2 |
| 4 — Security | 8 | 1 |
| 5 — Resilience | 8 | 1 |
| 6 — Turnkey Deployment | 10 | 0 |
| 7 — Compliance Analytics | 10 | 0 |
| 8 — Unified Documentation | 12 | 0 |
| 9 — Certification Readiness | 7 | 3 |
| **Total** | **79** | **8** |

---

*Last updated: 2026-03-20 | Version: 2.66.0*
