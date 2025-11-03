# DASDEC3 Capability Gap Analysis

This document translates the **Digital Alert Systems DASDEC3 Version 5.1 Software User's Guide (R1.0, 31 May 2023)** into a concrete checklist for EAS Station. It highlights which flagship DASDEC3 capabilities already exist in the open-source stack, which are partially supported, and which remain gaps on the roadmap.

> 📎 Keep a local copy of the vendor manual at `docs/Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf` (not tracked in git) for offline review. Page citations below refer to that PDF.

## Executive Summary

- **Commodity Hardware Advantage:** Where a DASDEC3 bundle starts around **$5,000 USD** (single station) and climbs past **$7,000 USD** with multi-station and redundancy options, the documented Raspberry Pi 5 reference build (Pi 5, relays, balanced audio HAT, dual SDRs, NVMe, UPS) remains **under $600 USD** while delivering equivalent automation.
- **Software Parity:** Alert ingestion, SAME generation, GPIO control, LED signage, and SDR verification are already at parity or ahead because EAS Station can iterate rapidly in software. Remaining work clusters around redundant audio paths, multi-station clustering, and formal FCC test suites.
- **Roadmap Alignment:** Each gap below maps to the canonical [`docs/roadmap/master_todo.md`](master_todo.md) items. Use this file as the bridge between vendor-grade checklists and open-source milestones.

### Primary Reference Documents

1. **Digital Alert Systems DASDEC3 Version 5.1 Software User’s Guide (R1.0, 31 May 2023)** → `docs/Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf`
2. **DASDEC-G3 Release 5.1 Quick Start Guide** → `docs/QSG_DASDEC-G3_R5.1.docx`
3. **Grob Systems Adjunct Specification (ADJ06182024A)** → `docs/D,GrobSystems,ADJ06182024A.pdf`

These documents define the control surface, wiring expectations, and capability groupings used throughout this comparison. When editing this file, verify page and section references against the manuals so the roadmap reflects the vendor’s terminology.

## Capability Matrix

| DASDEC3 Capability (Manual Section) | DASDEC3 Reference | EAS Station Status | Notes & Follow-Up |
| --- | --- | --- | --- |
| Multi-source CAP aggregation & filtering | §3.1, §3.3 | ✅ Implemented | NOAA + IPAWS pollers with dedupe in `app_core/alerts.py` cover the same feature set. |
| On-box audio mixer and relay control | §4.2, §6.1 | ✅ Implemented | GPIO relay automation and WAV rendering mirror DASDEC "Program/Input" routing. |
| Triple-tier user roles & audit logs | §2.5 | ⚠️ In Progress | Basic authentication exists; need per-role permissions + tamper-evident logs (`master_todo.md` → Governance). |
| Dual redundant audio paths | §4.3 | ❌ Not Yet | Documented in roadmap (Hardware Reliability). Requires Pi HAT failover or network AoIP. |
| Station clustering & auto-failover | §8.4 | ❌ Not Yet | Planned high-availability swarm; tracked under Resilient Operations. |
| FCC Part 11 self-tests | §9.2 | ⚠️ In Progress | Manual RWT/RMT workflows exist; automated scheduling & logging still pending. |
| Multi-lingual text-to-speech | §5.5 | ⚠️ In Progress | Polly/CereVoice adapters drafted; needs UI toggles and caching policy. |
| GPIO configurable silence sensor | §6.3 | ❌ Not Yet | Requires ALSA/VU integration and relay mapping. |
| Secure remote management (HTTPS/VPN) | §10.1 | ⚠️ In Progress | Reverse proxy hardening documented, but TLS automation and VPN recipes must be finalized. |
| Integrated graphics/keyer output | §7.4 | ✅ Implemented | LED sign controller & HDMI dashboard parallel DASDEC keyer workflows. |
| Compliance export packages | §9.6 | ⚠️ In Progress | CSV exports exist; PDF bundle + signature workflow remain. |

## Roadmap Actions

1. **Redundant Audio Paths**  
   Implement dual audio interface support with priority failover, mirroring DASDEC3 "Audio 1/Audio 2" switching (Manual §4.3). Requires ALSA multi-device graph and health monitoring hooks in `app_core/system_health.py`.
2. **Role-Based Access Control (RBAC)**  
   Expand the Flask auth blueprint to support Administrator / Operator / Viewer roles with differential UI access (Manual §2.5). Integrate with the audit log backlog item for tamper evidence.
3. **Scheduled FCC Tests**  
   Build cron-backed tasks (Celery or APScheduler) to auto-generate RWT/RMT activations with compliance logging (Manual §9.2). Link outputs to verification dashboard for pass/fail attestation.
4. **Silence Sensor Integration**  
   Introduce ALSA level monitoring to trigger GPIO alerts on loss-of-audio (Manual §6.3). This pairs with the watchdog automation roadmap entry.
5. **Transport Security Playbook**  
   Publish a hardened deployment guide for TLS termination, VPN overlays, and optional MFA (Manual §10.1). Convert the checklist into an Ansible or Docker Compose profile for reproducibility.

## Cost Breakdown (2025 USD)

| Component | Qty | Unit Cost | Extended |
| --- | --- | --- | --- |
| Raspberry Pi 5 (8 GB) | 1 | $120 | $120 |
| NVMe SSD (512 GB) + PCIe carrier | 1 | $80 | $80 |
| Balanced audio HAT (HifiBerry DAC+ ADC Pro or equivalent) | 1 | $110 | $110 |
| 8-channel GPIO relay HAT | 1 | $45 | $45 |
| Dual RTL-SDR (Blog V4 or Airspy Mini + spare) | 2 | $60 | $120 |
| Active cooling case + UPS HAT | 1 | $70 | $70 |
| Shielded cabling & accessories | - | $40 | $40 |
| **Total** |  |  | **$585** |

A comparable DASDEC3 bundle with redundant audio, DASDEC-G3 software license, and multi-station option typically exceeds **$5,000 USD**, making the Raspberry Pi approach a savings of **$4,400+** per installation.

## Historical Context

- **2012–2015:** Early Raspberry Pi builds (Model B/B+) proved CAP-to-SAME encoding could run on ARM. Limitations included USB bandwidth and RAM caps.
- **2016–2020:** Pi 3 and Pi 4 generations introduced gigabit networking and quad-core CPUs, enabling simultaneous polling, rendering, and SDR capture.
- **2023:** Pi 5's PCIe and LPDDR4X upgrades gave EAS Station the runway to match DASDEC3 concurrency without a rack chassis.
- **2024+:** Software refinements—GPIO orchestration, LED signage, SDR verification—close the loop, with remaining gaps centered on redundancy and certification.

## Manual Synchronization Checklist

Before updating this gap analysis:

- Review section headings and feature descriptions in the vendor PDFs/DOCX listed above so terminology mirrors the DASDEC3 documentation.
- Confirm any hardware guidance remains achievable with the Raspberry Pi reference build documented in [`README.md`](../../README.md).
- Cross-check roadmap tickets in [`master_todo.md`](master_todo.md) and [`eas_todo.md`](eas_todo.md) so new features are traced to manual capabilities.
- Update `/about` and `/help` templates if new operator guidance or warnings are introduced here.

Maintain this comparison as roadmap items ship so the documentation accurately reflects parity with DASDEC3 offerings.
