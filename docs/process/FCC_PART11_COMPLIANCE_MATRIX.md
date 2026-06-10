# FCC 47 CFR Part 11 — Compliance Traceability Matrix

This document maps each substantive FCC Part 11 requirement that bears on EAS
encoder/decoder certification to the subsystem(s) in this repository that
implement it, with an honest status and the outstanding gaps. It is a
**rule-by-rule traceability matrix**, complementary to the engineering-oriented
[Certification-Grade Reliability and Audit Plan](certification_reliability_plan.md).

> ⚠️ **Status disclaimer.** EAS Station™ is experimental and **not FCC-certified.**
> Under the current Part 2 / Part 11 regime, equipment authorization assumes a
> dedicated, certified appliance; there is no established path to certify EAS
> functions running as software on commodity hardware. The path that would make
> certification attainable is the rulemaking in **PS Docket No. 25-224**
> (*Modernization of the Nation's Alerting Systems*, NPRM adopted Aug 7, 2025),
> in which this project has [filed comments](https://www.fcc.gov/ecfs/search/search-filings/filing/1060881335987).
> As of this writing no final software-defined-EAS rules have been adopted. This
> matrix tracks technical readiness so the project is positioned if/when they are.

Status legend: ✅ Implemented · 🔶 Partial / needs verification · ⏳ Planned · 🚫 Out of scope until rules change

---

## Subpart B — Equipment Requirements

### § 11.31 — EAS Protocol (SAME)
**Requires:** SAME header structure `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-`;
AFSK modulation with mark = 2083⅓ Hz, space = 1562.5 Hz at 520.83 baud (520 5/6),
LSB-first 7-bit ASCII + null bit framing; preamble of sixteen 0xAB bytes;
two-tone Attention Signal of 853 Hz + 960 Hz; End-of-Message `NNNN` triple burst.

| Element | Implementation | Status |
|---|---|---|
| Header ASCII format & framing | `app_utils/eas_fsk.py::build_same_header`, `encode_same_bits` | ✅ |
| AFSK mark/space/baud constants | `app_utils/eas_fsk.py` (`SAME_MARK_FREQ`=2083⅓, `SAME_SPACE_FREQ`=1562.5, `SAME_BAUD`=3125/6) | ✅ |
| Preamble (16× 0xAB) | `app_utils/eas_fsk.py::encode_same_preamble` | ✅ |
| Attention Signal 853+960 Hz | `app_utils/eas.py` (`_tone_freqs = (853.0, 960.0)`) | ✅ |
| EOM `NNNN` triple burst | `app_utils/eas.py`, `app_utils/endec_feeds.py` (§11.31(c)) | ✅ |
| Decode / off-air parity | `app_utils/eas_decode.py`, `app_utils/eas_demod.py` | ✅ |

**Gaps:** Validate exact inter-burst spacing and timing tolerances against a
calibrated reference as part of the cert test harness (tracked in the reliability plan).

### § 11.32 — EAS Encoder requirements
**Requires:** capability to generate the SAME codes, Attention Signal (8–25 s), and
EOM; programmability of originator/event/location codes and timing.

| Element | Implementation | Status |
|---|---|---|
| Code/attention/EOM generation | `app_utils/eas.py`, `app_utils/eas_fsk.py` | ✅ |
| Event/originator code registry | `app_utils/event_codes.py` | ✅ |
| Location (FIPS) handling, ≤31 per header | `app_utils/fips_codes.py`, header builder | 🔶 verify 31-code cap enforcement |
| Attention Signal duration 8–25 s | `app_utils/eas.py` (default 8 s, configurable) | 🔶 confirm upper bound clamped to 25 s |

**Gaps:** Confirm the encoder rejects/clamps configurations outside the §11.32 /
§11.31 bounds (location-code count, attention-tone duration ceiling).

### § 11.33 — EAS Decoder requirements
**Requires:** monitor **at least two** EAS sources; decode and validate SAME headers
(valid only when two of three header bursts match); store/retain messages in
non-volatile memory; provide display and logging; reject duplicate/expired messages.

| Element | Implementation | Status |
|---|---|---|
| ≥2 monitoring sources (LP1/LP2) | `app_core/audio/eas_monitor_v3.py`, `app_core/audio/source_manager.py` | ✅ |
| 2-of-3 burst validation | `app_utils/eas_decode.py` (2-of-3 majority voting) | ✅ |
| Message storage / retention | `app_core/eas_storage.py`, `app_core/_models_alerts.py` | 🔶 confirm "non-volatile" durability semantics |
| Display & logging | `webapp/routes/eas_compliance.py`, audit ledger | ✅ |
| Duplicate / expiry suppression | `app_core/audio/auto_forward.py`, ingestion dedup | 🔶 verify against §11.33 retention rules |

**Gaps:** Document the non-volatile retention guarantee explicitly; confirm
duplicate and time-window handling matches the decoder rule (not just CAP dedup).

### § 11.34 — Acceptability of the equipment (certification)
**Requires:** certification under **Part 2, Subpart J**; compliance with Part 11
**and Part 15** (digital-device emissions); combined encoder/decoder units allowed
if every spec is met; manufacturer must ship install/operate/program instructions
**plus the full State/county ANSI (FIPS) list**; post-grant software changes governed
as permissive changes.

| Element | Implementation | Status |
|---|---|---|
| Part 2 Subpart J grant | — (external lab + grant) | 🚫 blocked by rules / NPRM |
| Part 15 emissions test | — (physical Pi + HAT + SDR) | ⏳ lab test required |
| Combined unit architecture | whole platform | ✅ (design) |
| Shipped operator manual | `docs/guides/HELP.md` (needs packaging) | 🔶 produce as shipped artifact |
| Shipped ANSI/county list | `app_utils/fips_codes.py` (needs packaging) | 🔶 produce as shipped artifact |
| Software integrity / locked update path | signed audit ledger only | ⏳ signed firmware + verified boot/update needed |

**Gaps (high priority):**
1. The Subpart J path itself is unavailable for software-on-commodity-hardware
   until PS Docket 25-224 produces rules — primary external blocker.
2. **Software integrity** is the crux of any software-EAS regime: add
   signed/verified software images and a secured update path that demonstrably
   prevents silent modification of EAS-critical code.
3. Package §11.34(d) deliverables (manual + ANSI/FIPS tables) as shipped artifacts.

### § 11.35 — Equipment operational readiness
**Requires:** equipment must detect and **log its own defects/failures**; maintain
operational logs; provide for repair/replacement within prescribed windows.

| Element | Implementation | Status |
|---|---|---|
| Self-monitoring / health | `app_core/audio/source_manager.py` health gating, SDR SNR gates | ✅ |
| Tamper-evident operational log | `app_core/auth/audit.py` (Ed25519 + hash chain) | ✅ |
| Defect logging & alarms | Prometheus/Grafana plan | 🔶 map alarms explicitly to §11.35 |

**Gaps:** Map each failure mode (timing drift, source loss, decode failure) to a
logged §11.35 readiness event.

---

## Subpart C/D — Operations

### § 11.45 — Prohibition of false/unauthorized transmissions
**Requires:** no transmission of EAS codes or the Attention Signal except in an
actual emergency, authorized test, or PSA meeting the narrow exception.

| Element | Implementation | Status |
|---|---|---|
| Lab-only operating posture, guardrails | `docs/policies/TERMS_OF_USE.md`, README disclaimers | ✅ |
| Real-semantics-only enforcement | `docs/reference/ABOUT.md` §"Real operational semantics" | ✅ |

### § 11.51 / § 11.52 — Transmission & Monitoring requirements
**Requires:** participants transmit required EAS data; monitor two assigned sources
per the State EAS Plan.

| Element | Implementation | Status |
|---|---|---|
| Two-source monitoring | `app_core/audio/eas_monitor_v3.py` (LP1/LP2) | ✅ |
| State plan source assignment | `docs/reference/OHIO_EAS_DOCUMENTATION.md` | 🔶 wire plan data into config |

### § 11.56 — Obligation to process CAP-formatted messages
**Requires:** process CAP per the **ECIG Recommendations for a CAP EAS
Implementation Guide, Version 1.0** (adopted by reference).

| Element | Implementation | Status |
|---|---|---|
| CAP ingestion (IPAWS/NWS) | `app_core/audio/auto_forward.py`, ingestion stack | ✅ |
| ECIG v1.0 mapping (must-carry, msgType, audio priority, `***` markers, default ORG) | `docs/ECIG-CAP-to-EAS_Implementation_Guide-V1-0.md`, `tests/test_ecig_compliance.py` | ✅ |

---

## Subpart E — Tests

### § 11.61 — Tests of EAS procedures (RWT / RMT)
**Requires:** originate/relay Required Weekly Tests (RWT) and Required Monthly Tests
(RMT) per schedule; RWT carries SAME header + EOM only.

| Element | Implementation | Status |
|---|---|---|
| RWT scheduling (header + EOM only) | `app_core/rwt_scheduler.py` (cites §11.61(a)(1)(ii)) | ✅ |
| RMT handling | `app_core/rwt_scheduler.py`, analytics | ✅ |
| Test logging / reporting | `webapp/routes/eas_compliance.py` | ✅ |

---

## Summary of open items for a certification track

1. **External / regulatory (blocking):** Final rules in PS Docket 25-224 enabling
   software-defined EAS certification. Continue ECFS engagement.
2. **Software integrity:** Signed/verified software images and a secured update path
   (the core technical concern of any software-EAS regime).
3. **Part 15 emissions:** Accredited-lab measurement of the physical device.
4. **§ 11.34(d) shipped artifacts:** Operator manual + bundled State/county ANSI/FIPS list.
5. **§ 11.32/11.33 edge enforcement:** Location-code cap (≤31), attention-tone ceiling
   (≤25 s), non-volatile retention guarantee, decoder duplicate/expiry handling.
6. **§ 11.35 mapping:** Bind self-test/health alarms to logged readiness events.
