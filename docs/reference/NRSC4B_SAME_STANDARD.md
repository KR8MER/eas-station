# NRSC-4-B SAME Standard Reference

> **Canonical source:** NRSC-4-B *United States RBDS Standard* (2005), Section 4 — Specific Area Message Encoding (SAME). This document summarises the standard for implementers working with the EAS Station™ codebase.

---

## 1. Overview

**SAME (Specific Area Message Encoding)** is the audio-layer protocol used by the US Emergency Alert System (EAS) to convey machine-readable alert headers on broadcast and cable channels. NRSC-4-B (Section 4 / Annex D) formally standardises SAME for FM broadcasters, aligning it with the FCC EAS rules at **47 CFR Part 11**.

Every EAS activation begins with a SAME header, followed by the audio attention signal and voice message, and ends with the End-of-Message (EOM) code. Decoders must detect and validate the header, respect the purge time, and forward the alert downstream.

---

## 2. Physical Layer (§4.3.1)

| Parameter | Value |
|---|---|
| Modulation | Audio-frequency-shift keying (AFSK) |
| Mark frequency | **2083.3 Hz** (binary 1) |
| Space frequency | **1562.5 Hz** (binary 0) |
| Centre frequency | **1822.9 Hz** |
| Symbol (baud) rate | **520.83 baud** (= 25000/48 symbols/second) |
| Bit order | LSB first |
| Preamble | **16 bytes** of `0xAB` (10101011 repeated) |
| Encoding | NRZ (non-return-to-zero) |

The 16-byte preamble provides bit-clock synchronisation. No start or stop bits are used; the bit stream is continuous within each burst.

---

## 3. Transmission Protocol — Triple-Burst (§4.3.2)

NRSC-4-B mandates that every SAME header, including the End-of-Message code, be transmitted **three times** separated by one-second pauses:

```
[Burst 1] — 1 s silence — [Burst 2] — 1 s silence — [Burst 3]
```

Each burst consists of:
1. 16-byte preamble (`0xAB` × 16)
2. The SAME ASCII message string
3. A trailing carriage return (`0x0D`)

**Purpose:** Redundancy allows receivers to reconstruct a correct header even when one burst is partially corrupted by noise. EAS Station™ applies 2-of-3 majority voting across the three bursts (see Section 7).

---

## 4. Header Format (§4.3.3)

A SAME header is a printable-ASCII string with the following dash-delimited structure:

```
ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-
```

### 4.1 Field Definitions

| Field | Width | Description |
|---|---|---|
| `ZCZC` | 4 | Start code — marks the beginning of the header |
| `ORG` | 3 | Originator code |
| `EEE` | 3 | Event code |
| `PSSCCC` | 6 per location | Location code(s), separated by `-`, maximum **31** codes |
| `+TTTT` | 4 | Purge time in HHMM format (e.g. `0100` = 1 hour) |
| `JJJHHMM` | 7 | Issue time: day-of-year (`JJJ`) + UTC hour (`HH`) + minute (`MM`) |
| `LLLLLLLL` | 1–8 | Station identifier (call letters / source ID) |

### 4.2 Start Code

`ZCZC` — ASCII characters `5A 43 5A 43`. Receivers scan the bit stream after the preamble for this four-byte sequence to begin header parsing.

### 4.3 Originator Codes (§4.3.3.2)

| Code | Source |
|---|---|
| `EAS` | EAS Participant (encoder/decoder device) |
| `CIV` | Civil Authorities (e.g. state/local emergency management) |
| `WXR` | National Weather Service |
| `PEP` | Primary Entry Point System (FEMA/IPAWS) |

Only these four codes are valid per NRSC-4-B. Any other value indicates a non-compliant or malformed header.

### 4.4 Event Codes (§4.3.3.3)

Three-letter codes defined by the FCC (47 CFR §11.31(e)). Examples:

| Code | Event |
|---|---|
| `EAN` | Emergency Action Notification (national) |
| `EAT` | Emergency Action Termination |
| `NPT` | National Periodic Test |
| `RWT` | Required Weekly Test |
| `TOR` | Tornado Warning |
| `SVR` | Severe Thunderstorm Warning |
| `FFW` | Flash Flood Warning |
| `TOE` | 911 Telephone Outage Emergency |

EAS Station™ maintains a full registry in `app_utils/eas.py → EVENT_CODE_REGISTRY`.

### 4.5 Location Codes (§4.3.3.3)

Each six-digit FIPS-based code identifies a geographic area:

```
P  SS  CCC
│  │   └─ County FIPS (001–999; 000 = entire state)
│  └───── State FIPS (two digits)
└──────── Subdivision/priority digit
```

**Constraints:**
- Minimum 1, maximum **31** location codes per header.
- Codes are separated by `-`.
- `P=0` = all or most of the county; higher values indicate sub-county areas (not widely used).

### 4.6 Purge Time (§4.3.3.4)

Four-character field `TTTT` in **HHMM format**:

| Code | Duration |
|---|---|
| `0015` | 15 minutes |
| `0030` | 30 minutes |
| `0045` | 45 minutes |
| `0100` | 1 hour |
| `0130` | 1 hour 30 minutes |
| `0200` | 2 hours |
| `0230` | 2 hours 30 minutes |
| `0300` | 3 hours |
| `0330` | 3 hours 30 minutes |
| `0400` | 4 hours |
| `0430` | 4 hours 30 minutes |
| `0500` | 5 hours |
| `0530` | 5 hours 30 minutes |
| `0600` | 6 hours |

Only these fourteen values are valid. EAS Station™ validates the received code against `NRSC4B_VALID_PURGE_TIMES` in `app_utils/eas.py`.

> **Common mistake:** `TTTT` is **not** decimal minutes. `0100` means 1 hour, not 100 minutes.

### 4.7 Issue Time (§4.3.3.5)

Seven-digit UTC field `JJJHHMM`:

| Sub-field | Digits | Range | Meaning |
|---|---|---|---|
| `JJJ` | 3 | 001–366 | Day of year |
| `HH` | 2 | 00–23 | Hour (UTC) |
| `MM` | 2 | 00–59 | Minute (UTC) |

EAS Station™ computes a `datetime` object by anchoring `JJJ` to the current calendar year and adds the UTC hours/minutes.

### 4.8 Station Identifier (§4.3.3.6)

1–8 printable ASCII characters identifying the originating station or device. Typically the FCC call sign of the broadcast station or the identifier of the originating ENDEC. The field is terminated by a trailing `-` before the carriage return.

---

## 5. End-of-Message (EOM) Code (§4.3.4)

```
NNNN
```

Transmitted three times (triple-burst, same one-second gaps as the header) to signal the end of the alert audio. Each EOM burst consists of:
1. 16-byte `0xAB` preamble
2. The four ASCII characters `NNNN`
3. No trailing carriage return (or an optional one — receivers must accept both)

---

## 6. NRSC-4-B Compliance Flags

`describe_same_header()` in `app_utils/eas.py` evaluates and exposes the following per-header compliance flags:

| Field | Meaning |
|---|---|
| `nrsc4b_compliant` | `True` if all five field-level checks pass |
| `nrsc4b_valid_originator` | Originator is one of `EAS/CIV/WXR/PEP` |
| `nrsc4b_valid_event` | Event code is in the registered code table |
| `nrsc4b_valid_purge` | Purge code is one of the 14 defined HHMM values |
| `nrsc4b_valid_issue_time` | Day-of-year 1–366, hour 0–23, minute 0–59 |
| `nrsc4b_valid_location_count` | 1 ≤ location count ≤ 31 |
| `nrsc4b_valid_station_id` | Station identifier is 1–8 printable ASCII chars |

---

## 7. Error Correction — 2-of-3 Majority Voting (§4.5)

Because the header is transmitted three times, receivers can reconstruct a clean header even when individual bursts are corrupted:

```
Burst 1:  ZCZC-WXR-TOR-0...
Burst 2:  ZCZC-WXR-TOR-0...  ← bit error at byte 12
Burst 3:  ZCZC-WXR-TOR-0...
```

**Algorithm** (implemented in `app_utils/eas_decode.py → _vote_on_bytes()`):

1. Align all three bursts byte-for-byte.
2. For each byte position, collect the values from each burst.
3. **If 2 or 3 bursts agree** → use the agreed value.
4. **If all three differ** (no majority) or only 2 bursts were received → use the **most recently received** burst's value (the last burst is preferred, per §4.5 guidance, because later transmissions reflect any in-flight correction by the originating ENDEC).

The decode result exposes:

| Field | Type | Description |
|---|---|---|
| `burst_count` | `int` | Number of bursts detected (0–3) |
| `voting_applied` | `bool` | `True` when ≥ 2 bursts were compared |

A `burst_count` < 3 indicates a degraded or partial transmission; decoders should log a warning but still forward the decoded alert.

---

## 8. Decoded Header Fields

`describe_same_header()` returns a dict with every field parsed from the header. Key fields:

| Key | Type | Description |
|---|---|---|
| `start_code` | `str` | `"ZCZC"` |
| `originator` | `str` | Three-letter originator code |
| `originator_description` | `str` | Human-readable originator name |
| `nrsc4b_valid_originator` | `bool` | Originator is a valid NRSC-4-B code |
| `event_code` | `str` | Three-letter event code |
| `event_name` | `str` | Human-readable event name |
| `nrsc4b_valid_event` | `bool` | Event is registered in the code table |
| `location_count` | `int` | Number of location codes in the header |
| `location_count_valid` | `bool` | 1 ≤ count ≤ 31 |
| `locations` | `list[dict]` | Detailed breakdown of each location code |
| `raw_locations` | `list[str]` | Raw six-digit FIPS strings as received |
| `purge_code` | `str` | Four-character HHMM string |
| `purge_hh` | `int` | Hours component of the purge time |
| `purge_mm` | `int` | Minutes component of the purge time |
| `purge_minutes` | `int` | Total purge duration in minutes |
| `purge_label` | `str` | Human-readable duration (e.g. `"1 hour"`) |
| `nrsc4b_valid_purge` | `bool` | Purge code is one of the 14 defined values |
| `issue_code` | `str` | Seven-character `JJJHHMM` string |
| `issue_day_of_year` | `int` | Day of year (1–366) |
| `issue_hour` | `int` | UTC hour (0–23) |
| `issue_minute` | `int` | UTC minute (0–59) |
| `issue_time_iso` | `str` | ISO-8601 UTC datetime string |
| `issue_time_label` | `str` | Human-readable label (e.g. `"Day 042 at 14:30 UTC"`) |
| `issue_components` | `dict` | `{day_of_year, hour, minute}` |
| `nrsc4b_valid_issue_time` | `bool` | Issue time passes all range checks |
| `station_identifier` | `str` | Station ID (trimmed) |
| `station_identifier_raw` | `str` | Station ID as received (may have trailing dashes) |
| `nrsc4b_valid_station_id` | `bool` | ID is 1–8 chars |
| `header_length` | `int` | Total character length of the raw header string |
| `nrsc4b_compliant` | `bool` | Overall NRSC-4-B compliance |

Each entry in `locations` is a dict with:

| Key | Description |
|---|---|
| `code` | Six-digit string |
| `p_digit` | Subdivision digit (0–9) |
| `p_meaning` | Human-readable meaning of the P digit |
| `state_fips` | Two-digit state FIPS code |
| `state_name` | State name |
| `state_abbr` | State abbreviation |
| `county_fips` | Three-digit county FIPS code |
| `is_statewide` | `True` if `county_fips == "000"` |
| `description` | Human-readable area name (from FIPS lookup) |

---

## 9. Constants (app_utils/eas.py)

| Constant | Value | Description |
|---|---|---|
| `NRSC4B_PREAMBLE_BYTE` | `0xAB` | Preamble byte value |
| `NRSC4B_PREAMBLE_LENGTH` | `16` | Number of preamble bytes per burst |
| `NRSC4B_BURST_COUNT` | `3` | Mandatory number of bursts |
| `NRSC4B_BAUD_RATE_FRAC` | `'25000/48'` | Exact baud rate as fraction (≈ 520.83 baud) |
| `NRSC4B_MARK_FREQ_HZ` | `2083.3` | Mark (1) frequency in Hz |
| `NRSC4B_SPACE_FREQ_HZ` | `1562.5` | Space (0) frequency in Hz |
| `NRSC4B_CENTER_FREQ_HZ` | `1822.9` | Centre frequency in Hz |
| `NRSC4B_MAX_LOCATIONS` | `31` | Maximum number of location codes |
| `NRSC4B_STATION_ID_MAX_LEN` | `8` | Maximum station identifier length |
| `NRSC4B_VALID_PURGE_TIMES` | (14-tuple) | All valid HHMM purge codes |
| `NRSC4B_VALID_ORIGINATORS` | (4-tuple) | `EAS`, `CIV`, `WXR`, `PEP` |

---

## 10. Relationship to Other Standards

| Standard | Relationship |
|---|---|
| **47 CFR Part 11** | FCC EAS rules; NRSC-4-B implements these at the FM broadcast layer |
| **ECIG EAS-ENDEC** | Equipment manufacturer guideline; mostly consistent with NRSC-4-B |
| **CAP / IPAWS** | XML-based national alert aggregation; IPAWS OPEN converts CAP to SAME |
| **NRSC-4-B §3** | RBDS physical layer (57 kHz subcarrier); SAME lives on the audio baseband |
| **EAS Station™ RBDS decoder** | Decodes EWS Group 9A which carries RBDS-layer emergency warning data correlated with SAME |

---

## 11. Implementation Notes

### Where the code lives

| Function / Class | File | Purpose |
|---|---|---|
| `describe_same_header()` | `app_utils/eas.py` | Parse and validate a SAME header string |
| `_vote_on_bytes()` | `app_utils/eas_decode.py` | 2-of-3 majority voting |
| `SAMEAudioDecodeResult` | `app_utils/eas_decode.py` | Decode result with `burst_count` / `voting_applied` |
| `_bits_to_text()` | `app_utils/eas_decode.py` | Convert demodulated bits → header text |
| `EVENT_CODE_REGISTRY` | `app_utils/eas.py` | Complete map of EAS event codes |
| `NRSC4B_VALID_PURGE_TIMES` | `app_utils/eas.py` | The 14 valid purge codes |
| `NRSC4B_VALID_ORIGINATORS` | `app_utils/eas.py` | The 4 valid originator codes |

### Field Descriptions metadata

`SAME_HEADER_FIELD_DESCRIPTIONS` in `app_utils/eas.py` is a list of dicts that describe every SAME header field for UI rendering and API documentation. Each entry has:
- `key` — the field name in the `describe_same_header()` output
- `label` — human-readable label
- `description` — extended description
- `nrsc4b_section` — the NRSC-4-B section that governs this field (where applicable)
- `valid_values` / `max_count` / `max_length` — validation metadata for UI hints
