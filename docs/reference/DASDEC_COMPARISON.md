# EAS Station vs. DASDEC-III — Feature Comparison

This document provides an honest, engineering-level comparison between **EAS Station** and the
**Digital Alert Systems DASDEC-III**, the most widely-deployed commercial EAS encoder/decoder
in the United States broadcast market.

> **Important:** EAS Station is experimental and not yet FCC-certified for production emergency
> alerting. This comparison is provided for evaluation and development planning purposes only.

---

## Overview

| Attribute | EAS Station | DASDEC-III |
|-----------|------------|------------|
| Form factor | Software (Raspberry Pi / x86 server) | 1RU rack appliance |
| OS | Debian Linux 13 (Trixie) | Embedded Linux |
| FCC certification | Pending | Yes (Part 11) |
| License | AGPL-3.0 / Commercial | Proprietary |
| Price | Open-source (hardware cost only) | ~$3,000–$5,000 USD |
| Source available | Yes | No |
| Self-hosted | Yes | Yes (appliance) |
| Remote management | Web UI + Tailscale VPN | Web UI + optional VPN |

---

## Alert Ingestion

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| NOAA Weather Radio CAP feed | ✅ | ✅ |
| IPAWS OPEN CAP feed | ✅ | ✅ |
| Custom CAP feed sources | ✅ Multiple | ✅ |
| SDR-based OTA EAS monitoring | ✅ RTL-SDR, Airspy | ✅ Dedicated tuner |
| Analog audio input capture | ⏳ Planned | ✅ |
| FM broadcast source monitoring | ✅ | ✅ |
| Multi-source simultaneous monitoring | ✅ | ✅ |
| Duplicate alert suppression | ✅ | ✅ |

---

## SAME Encoding & Broadcast

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| FCC §11.31 SAME encoding | ✅ Three-burst | ✅ |
| Attention tone (853/960 Hz) | ✅ 1–25 s configurable | ✅ |
| End-of-message burst (NNNN) | ✅ | ✅ |
| TTS voice narration | ✅ Azure OpenAI/Cognitive, pyttsx3 | ✅ Built-in TTS |
| Manual alert creation | ✅ Web-based builder | ✅ |
| Required Weekly Test (RWT) | ✅ Automated scheduler | ✅ |
| Required Monthly Test (RMT) | ✅ | ✅ |
| Authorized area/event filtering | ✅ FIPS + event code lists | ✅ |

---

## Hardware I/O

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| Dry-contact GPIO relays | ✅ Raspberry Pi GPIO | ✅ Dedicated relay board |
| RS-232 automation port | ⏳ Planned | ✅ |
| Balanced audio I/O | ⏳ HAT planned | ✅ |
| LED sign control (Alpha Protocol) | ✅ M-Protocol serial | ❌ Not standard |
| VFD display control | ✅ Multiple protocols | ❌ Not standard |
| OLED status display | ✅ | ❌ |
| Front-panel LCD | ❌ | ✅ |
| Physical alert acknowledge button | ❌ | ✅ |

---

## Geographic Intelligence

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| PostGIS spatial filtering | ✅ County/polygon | ❌ FIPS-code only |
| Coverage percentage calculation | ✅ | ❌ |
| NWS weather zone boundaries | ✅ Built-in catalog | ✅ |
| US county boundaries (TIGER) | ✅ Built-in | ✅ |
| Custom polygon alert areas | ✅ | ❌ |
| Interactive alert map | ✅ Leaflet/web | ❌ |

---

## Security & Access Control

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| Web-based management console | ✅ Flask/Bootstrap | ✅ |
| HTTPS (Let's Encrypt) | ✅ Automated | ✅ Self-signed / manual |
| Multi-factor authentication (TOTP) | ✅ | ❌ |
| Role-based access control | ✅ Per-resource | ✅ User roles |
| Session management | ✅ Token + concurrency limits | ✅ |
| Audit logging | ✅ All admin actions | Limited |
| Malicious login detection | ✅ | ❌ |
| Tailscale zero-trust VPN | ✅ | ❌ |

---

## Compliance & Reporting

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| Alert delivery reports | ✅ Per-alert status | ✅ |
| Required Weekly Test logging | ✅ | ✅ |
| FCC compliance dashboard | ✅ §11.61 pass/fail | Limited |
| Alert export (JSON / CAP / CSV / PDF) | ✅ | ✅ (limited formats) |
| Long-term analytics dashboard | ✅ Highcharts | ❌ |
| 90-day configurable log retention | ✅ | Fixed |
| SNMP v2c health notifications | ✅ | ✅ |
| Email health notifications | ✅ | ✅ |

---

## Operations & Maintenance

| Feature | EAS Station | DASDEC-III |
|---------|------------|------------|
| Automated update mechanism | ✅ `update.sh` | ✅ Firmware updates |
| Backup and restore | ✅ Web UI + CLI | ✅ Config export |
| Database migration management | ✅ Alembic auto-apply | N/A |
| Remote diagnostics | ✅ Web + Tailscale | ✅ Web + optional VPN |
| System health dashboard | ✅ | Limited |
| Container deployment (Docker) | ✅ | ❌ |
| Source code availability | ✅ GitHub | ❌ |

---

## Key Differentiators

### EAS Station Advantages
- **Open source** — full source code available for audit, customisation, and contribution
- **Geographic intelligence** — PostGIS spatial engine provides area-aware filtering far beyond FIPS-code matching
- **Modern security** — TOTP MFA, RBAC, Tailscale VPN, audit logging exceed DASDEC-III's access controls
- **Extensible display outputs** — LED signs and VFD displays not available on commercial appliances
- **Advanced analytics** — Highcharts dashboards, trend analysis, exportable compliance evidence
- **Commodity hardware** — Raspberry Pi 5 at a fraction of commercial appliance cost
- **Container-ready** — Docker image for reproducible multi-architecture deployments

### DASDEC-III Advantages
- **FCC-certified** — legally approved for production emergency alerting (Part 11)
- **Physical I/O** — front-panel LCD, relay board, balanced audio, RS-232 standard equipment
- **Turnkey appliance** — no OS or software maintenance required
- **Proven reliability** — years of production deployments at broadcast facilities
- **Vendor support** — commercial support contract available

---

## Summary Assessment

EAS Station has achieved feature parity with the DASDEC-III across the software and intelligence
layers — alert ingestion, SAME encoding, geographic filtering, compliance reporting, and security
controls all meet or exceed commercial equivalents. The remaining gaps are physical hardware I/O
(balanced audio, RS-232) and FCC Part 11 certification, which require purpose-built HAT hardware
and a formal certification filing respectively.

See the [Feature Roadmap](../roadmap/dasdec3-feature-roadmap.md) for planned completion timelines
on all nine requirement areas.

---

*Last updated: 2026-03-20 | Version: 2.66.0*
