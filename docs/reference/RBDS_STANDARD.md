# RBDS Standard Reference (NRSC-4-B)

## 1. Overview

**RBDS** (Radio Broadcast Data System) is the North American adaptation of the European **RDS** (Radio Data System, IEC 62106 / EN 50067) standard. The relevant US specification is **NRSC-4-B**, published by the National Radio Systems Committee.

RBDS embeds digital metadata in FM broadcasts using a 57 kHz subcarrier that is phase-locked to the third harmonic of the 19 kHz stereo pilot. The data stream carries the station name, program type, radio text, traffic announcements, clock time, alternative frequencies, and — critically for EAS stations — **Emergency Warning System (EWS)** alerts.

---

## 2. Physical Layer

| Parameter | Value |
|---|---|
| Subcarrier frequency | 57 kHz (3 × 19 kHz pilot) |
| Modulation | BPSK (Binary Phase-Shift Keying) |
| Bit rate | 1187.5 bps (exact: 1187.5 = 57000/48) |
| Symbol encoding | Differential (transitions = 1, no-transition = 0) |
| Error protection | CRC-10 per block + offset word |
| Group framing | 104-bit groups (4 × 26-bit blocks) |

### Error Protection

Each 26-bit block contains:
- 16 bits of data
- 10 bits of CRC (generator polynomial: x¹⁰ + x⁸ + x⁷ + x⁵ + x⁴ + x³ + 1)
- A unique **offset word** (A, B, C, C', D) XORed into the syndrome to identify block position

Correct syndrome values for each block:

| Block | Offset word | Syndrome (hex) |
|---|---|---|
| A | 0x0FC | 0x17F |
| B | 0x198 | 0x0BE |
| C (version A) | 0x168 | 0x12F |
| C' (version B) | 0x350 | 0x217 |
| D | 0x1B4 | 0x0B4 |

---

## 3. Data Model

### PI Code (Program Identification)

The 16-bit PI code uniquely identifies the station. Block A of every group carries the PI code.

| Bits | Meaning |
|---|---|
| 15–12 | Country code / area code |
| 11–0 | Program reference number |

**US call sign decoding (NRSC-4 Annex D):**

- Range `0x1000`–`0x54A7`: K-prefix stations (algorithmic)
- Range `0x54A8`–`0x994F`: W-prefix stations (algorithmic)
- Range `0x9950`–`0x99B9`: Legacy 3-letter calls (lookup table)

The EAS Station function `pi_to_call_sign()` in `app_core/radio/demodulation.py` implements this lookup.

### Group Structure

```
Block A (bits 15-0): PI code
Block B (bits 15-0):
  bits 15-12: Group type (0-15)
  bit  11:    Version (0=A, 1=B)
  bit  10:    TP (Traffic Program)
  bits  9-5:  PTY (Program Type, 0-31)
  bits  4-0:  Group-type-dependent payload
Block C (bits 15-0): Group-type-dependent
Block D (bits 15-0): Group-type-dependent
```

---

## 4. Group Types Table

| Group | Function | Decoded? |
|---|---|---|
| 0A | PS name, TA, MS, DI, AF | ✅ Yes |
| 0B | PS name, TA, MS, DI | ✅ Yes |
| 1A | PIN, ECC, Language, Linkage | ✅ Yes |
| 1B | Language, ECC | ✅ Yes |
| 2A | RadioText (64 chars) | ✅ Yes |
| 2B | RadioText (32 chars) | ✅ Yes |
| 3A | ODA Application ID | ✅ Yes |
| 3B | ODA data | — |
| 4A | Clock Time and Date | ✅ Yes |
| 4B | Reserved | — |
| 5A | Transparent Data Channel (4 bytes) | ✅ Yes |
| 5B | Transparent Data Channel (2 bytes) | ✅ Yes |
| 6A | In-House Applications (5 words) | ✅ Yes |
| 6B | In-House Applications (3 words) | ✅ Yes |
| 7A | Radio Paging | Logged only |
| 7B | Reserved | — |
| 8A | Traffic Message Channel (ALERT-C) | ✅ Presence flagged |
| 8B | Reserved | — |
| 9A | Emergency Warning System (**EWS**) | ✅ Yes |
| 9B | Reserved | — |
| 10A | Program Type Name (PTYN) | ✅ Yes |
| 10B | Program Type Name (PTYN, 2 chars/segment) | ✅ Yes |
| 11A | ODA data | — |
| 12A | ODA data | — |
| 13A | Enhanced Radio Paging | — |
| 14A | Enhanced Other Networks (slow) | ✅ Yes |
| 14B | Enhanced Other Networks (fast) | ✅ Yes |
| 15A | Defined in RDS, not RBDS | — |
| 15B | Fast Switching Information | ✅ Yes |

---

## 5. Decoded Group Details

### Group 0A/0B — Program Service (PS) Name, Flags, Alternative Frequencies

**Block B low bits:**
- Bit 4: TA (Traffic Announcement)
- Bit 3: MS (Music/Speech)
- Bit 2: DI bit (Decoder Identification, address-dependent)
- Bits 1-0: Address (segment 0-3, selects 2 chars of PS and which DI bit)

**Block C (0A only):** Two AF codes (Method A, direct frequency encoding)
- Code 1-204: `87.6 + 0.1 × code` MHz
- Code 224-249: Method A count (next code = first AF, following = list)
- Code 250: Follow-on frequency indicator
- Code 205: Filler / not used

**Block D:** Two PS name characters at position `address × 2` and `address × 2 + 1`

**Decoder Identification (DI) bits by address:**

| Address | DI bit | Meaning |
|---|---|---|
| 3 | d0 | Stereo (1) / Mono (0) |
| 2 | d1 | Artificial head (binaural) |
| 1 | d2 | Compressed audio |
| 0 | d3 | Dynamic PTY |

### Group 1A/1B — Programme Item Number + Slow Labeling Codes

**Block C:** Programme Item Number (PIN)
- Bits 15-11: Day of month (0=no PIN, 1-31)
- Bits 10-6: Hour (0-23)
- Bits 5-0: Minute (0-59)

**Block B bits 4-2:** Variant selector (0-7) for Block D interpretation:

| Variant | Block D meaning |
|---|---|
| 0 | Language code (bits 7-0) |
| 1 | Programme item (spare) |
| 2 | Paging (spare) |
| 3 | Language code (bits 7-0) |
| 4 | Extended Country Code (ECC, bits 7-0) |
| 5 | Linkage information: bit 15=LA, bit 14=SC, bits 11-0=LSN |
| 6 | Broadcaster's use |
| 7 | EWS channel (spare) |

### Group 2A/2B — RadioText

**Block B bits 4-0:**
- Bit 4: A/B flag (toggle clears RT buffer)
- Bits 3-0: Text segment address (0-15)

**2A:** 4 chars per segment (Blocks C and D), max 64 chars  
**2B:** 2 chars per segment (Block D only), max 32 chars

Carriage return (0x0D) terminates the displayed text.

### Group 3A — ODA Application Identification

Registers an Open Data Application (ODA) for a specific group type.

- Block B bits 4-1: ODA group type (0-15)
- Block B bit 0: ODA version (A or B)
- Block C: 16-bit Application ID (AID)
- Block D: Application-specific message

Common AIDs:
- `0x4BD7`: RDS-TMC (Traffic Message Channel)
- `0xCD46`: RT+ (Radio Text Plus, song title/artist tagging)

### Group 4A — Clock Time and Date

- Block B bits 1-0 + Block C bits 15-1: MJD (Modified Julian Day, 17 bits)
- Block C bit 0: Hour MSB
- Block D bits 15-12: Hour LSBs
- Block D bits 11-6: Minute (0-59)
- Block D bit 5: Local offset sign (0=+, 1=-)
- Block D bits 4-0: Local offset in half-hours

MJD to calendar conversion uses the algorithm from EN 50067 Annex G.

### Group 5A/5B — Transparent Data Channel (TDC)

Carries arbitrary byte streams on up to 32 channels.

- Block B bits 4-0: Channel address (0-31)
- **5A:** 4 bytes from Blocks C and D
- **5B:** 2 bytes from Block D only

### Group 6A/6B — In-House Applications

Proprietary data for use by the broadcaster's own equipment.

- Block B bits 4-0: In-house application data (5 bits)
- **6A:** Blocks C and D carry additional 32 bits
- **6B:** Block D carries 16 bits (Block C = PI of other network)

### Group 7A — Radio Paging

Used for alphanumeric paging services. EAS Station logs these groups at DEBUG level but does not decode paging data.

### Group 8A — Traffic Message Channel (TMC / ALERT-C)

ALERT-C encoded traffic messages. EAS Station flags the presence of TMC (`tmc_present=True`) but does not implement full ALERT-C decoding, which requires a location database.

### Group 9A — Emergency Warning System (EWS) ⚠️

**This is the most important group for EAS Station operation.**

EWS is the RBDS mechanism for broadcasting emergency alerts directly in the FM signal, complementing SAME/EAS audio alerts.

- Block B bits 4-0: EWS channel number (0-31)
- Block C: EWS message word 1 (16 bits, broadcaster-defined format)
- Block D: EWS message word 2 (16 bits, broadcaster-defined format)

EWS channel assignments and message formats are defined by the Emergency Alert System coordinator for each country/region. See Section 10 for the relationship to SAME/EAS.

### Group 10A/10B — Program Type Name (PTYN)

Provides an 8-character name further describing the PTY.

**10A:** 4 chars per segment (2 segments: 0 and 1)
- Block B bit 4: A/B flag
- Block B bit 0: Segment (0 or 1)
- Blocks C, D: 4 characters

**10B:** 2 chars per segment
- Block B bit 4: A/B flag
- Block B bit 0: Segment (0 or 1)
- Block D only: 2 characters

### Group 14A/14B — Enhanced Other Networks (EON)

Carries information about other stations in a network for cross-network TA/TP linking.

**14A (slow)** — variant in Block B bits 3-0:

| Variant | Block D content |
|---|---|
| 0-3 | PS name chars (2 per variant) |
| 4 | AF code (bits 15-8) |
| 12 | Linkage information |
| 13 | PTY (bits 15-11), TA (bit 0) |
| 14 | PIN (day/hour/minute) |

Block B bit 4: TP of the other network  
Block C: PI code of the other network

**14B (fast)** — for rapid TA updates:

- Block B bit 4: TP of other network
- Block B bit 3: TA of other network
- Block C: PI code of other network

### Group 15B — Fast Switching Information

Repeats critical flags from Group 0A at higher frequency for fast TA/TP response.

- Block B bit 4: TA
- Block B bit 3: MS
- Block B bit 2: DI bit (same address scheme as Group 0)
- Block B bits 1-0: Address
- Block D: PS name chars (same as Group 0A Block D)
- TP comes from Block B bit 10 (same as all groups)

---

## 6. Programme Type Codes (PTY)

| Code | RBDS Name |
|---|---|
| 0 | None / Not defined |
| 1 | News |
| 2 | Information |
| 3 | Sports |
| 4 | Talk |
| 5 | Rock |
| 6 | Classic Rock |
| 7 | Adult Hits |
| 8 | Soft Rock |
| 9 | Top 40 |
| 10 | Country |
| 11 | Oldies |
| 12 | Soft |
| 13 | Nostalgia |
| 14 | Jazz |
| 15 | Classical |
| 16 | Rhythm and Blues |
| 17 | Soft Rhythm and Blues |
| 18 | Foreign Language |
| 19 | Religious Music |
| 20 | Religious Talk |
| 21 | Personality |
| 22 | Public |
| 23 | College |
| 24 | Spanish Talk |
| 25 | Spanish Music |
| 26 | Hip Hop |
| 27–28 | Unassigned |
| 29 | Weather |
| 30 | Emergency Test |
| 31 | ALERT! (Emergency) |

---

## 7. Language Codes (Annex J)

Language codes are carried in Group 1A/1B, variant 0, Block D bits 7-0.

| Code | Language | Code | Language |
|---|---|---|---|
| 0x01 | Albanian | 0x40 | Background sound |
| 0x02 | Breton | 0x45 | Zulu |
| 0x03 | Catalan | 0x46 | Vietnamese |
| 0x04 | Croatian | 0x47 | Uzbek |
| 0x05 | Welsh | 0x48 | Urdu |
| 0x06 | Czech | 0x49 | Ukrainian |
| 0x07 | Danish | 0x4A | Thai |
| 0x08 | German | 0x4B | Telugu |
| 0x09 | English | 0x56 | Russian |
| 0x0A | Spanish | 0x65 | Korean |
| 0x0F | French | 0x69 | Japanese |
| 0x15 | Italian | 0x6B | Hindi |
| 0x20 | Polish | 0x6C | Hebrew |
| 0x21 | Portuguese | 0x70 | Greek |
| 0x27 | Finnish | 0x75 | Chinese |
| 0x28 | Swedish | 0x7E | Arabic |
| 0x29 | Turkish | 0x7F | Amharic |

See `RBDS_LANGUAGE_CODES` in `app_core/radio/demodulation.py` for the complete table.

---

## 8. PI Code Structure

For US stations the 16-bit PI code encodes the call sign:

- **Algorithmic K stations** (PI `0x1000`–`0x54A7`): `PI - 0x1000` maps to base-26 encoding of letters A-Z for positions 1-3 of the call sign.
- **Algorithmic W stations** (PI `0x54A8`–`0x994F`): `PI - 0x54A8` maps similarly.
- **Legacy 3-letter calls** (PI `0x9950`–`0x99B9`): Direct lookup table per NRSC-4 Annex D.3.

PI codes outside the US ranges (< `0x1000` or `0x9A00`–`0xFFFF`) are European/other-country codes and are displayed as hex without a call sign.

---

## 9. EWS Integration with EAS

Group 9A carries the **Emergency Warning System** data, which is the in-band RBDS complement to EAS/SAME audio alerts.

**Relationship to SAME:**
- SAME (Specific Area Message Encoding) is the audio-layer protocol used by EAS. It consists of a digital header broadcast as AFSK before the alert audio.
- EWS Group 9A carries **the same alert information in the RBDS data stream**, allowing receivers without audio-path monitoring to detect and decode alerts purely from the FM subcarrier.
- The EWS channel number (bits 4-0 of Block B) identifies which of up to 32 alert channels is active.
- Blocks C and D carry two 16-bit words whose format is defined by the alert coordinator (often mirroring key SAME fields like event code and FIPS location).

**EAS Station handling:**
- When Group 9A is received, `ews_channel`, `ews_message_c`, and `ews_message_d` are populated in `RBDSData`.
- The audio monitoring UI displays an **alert-style panel** (red background) when EWS data is present.
- The fields are propagated through `metadata['rbds_ews_channel']` etc. for use by monitoring logic.

---

## 10. Alternative Frequencies (Method A)

When a broadcaster transmits on multiple frequencies (e.g., translators, network affiliates), Group 0A Block C carries alternative frequency codes.

**Method A encoding:**
- Each byte is an AF code.
- Codes 1–204: Direct frequency. `freq_MHz = 87.6 + 0.1 × code`
- Code 224–249: Count byte. Value = number of following AF codes. The next code is the first AF.
- Code 205: Filler (ignore).
- Codes 250–255: Special (follow-on, regional variant, etc.)

EAS Station implements the simple case (direct codes 1-204 only). Count bytes (224-249) and special codes are skipped. The decoded frequencies are available as `rbds_af_list` in the metadata.

---

## 11. How EAS Station Implements This

### Where the code lives

| File | Responsibility |
|---|---|
| `app_core/radio/demodulation.py` | All RBDS decoding: `RBDSDecoder`, `RBDSData`, `RBDS_LANGUAGE_CODES` |
| `app_core/audio/sources.py` | Propagates `RBDSData` fields into the source metadata dict |
| `app_core/audio/redis_sdr_adapter.py` | Propagates `RBDSData` fields into the Redis-backed metrics metadata |
| `templates/audio_monitoring.html` | Renders RBDS fields in the FM source card |

### Decoded fields and metadata keys

| `RBDSData` field | Metadata key | Group source |
|---|---|---|
| `pi_code` | `rbds_pi_code` | All groups (Block A) |
| `call_sign` | `rbds_call_sign` | Derived from PI |
| `ps_name` | `rbds_ps_name` | Group 0A/0B |
| `pty_name` | `rbds_pty_name` | Group 10A/10B |
| `radio_text` | `rbds_radio_text` | Group 2A/2B |
| `pty` | `rbds_pty` | All groups (Block B) |
| `tp` | `rbds_tp` | All groups (Block B) |
| `ta` | `rbds_ta` | Group 0A/0B |
| `ms` | `rbds_ms` | Group 0A/0B |
| `di_stereo` | `rbds_di_stereo` | Group 0 address 3 |
| `clock_time_utc` | `rbds_clock_time_utc` | Group 4A |
| `clock_time_local` | `rbds_clock_time_local` | Group 4A |
| `af_list` | `rbds_af_list` | Group 0A Block C |
| `pin_day/hour/minute` | `rbds_pin_day/hour/minute` | Group 1A/1B Block C |
| `ecc` | `rbds_ecc` | Group 1A variant 4 |
| `language_code` | `rbds_language_code` | Group 1A/1B variant 0 |
| `language_name` | `rbds_language_name` | Derived from language_code |
| `linkage_set_number` | `rbds_linkage_set_number` | Group 1A variant 5 |
| `oda_apps` | `rbds_oda_apps` | Group 3A |
| `tdc_data` | `rbds_tdc_data` | Group 5A/5B channel 0 (hex string) |
| `tmc_present` | `rbds_tmc_present` | Group 8A |
| `ews_channel` | `rbds_ews_channel` | Group 9A |
| `ews_message_c` | `rbds_ews_message_c` | Group 9A Block C |
| `ews_message_d` | `rbds_ews_message_d` | Group 9A Block D |
| `eon_list` | `rbds_eon_list` | Group 14A/14B |
| `fast_tp/ta/ms` | `rbds_fast_ta/ms` | Group 15B |

### Running the tests

```bash
python -m pytest tests/test_rbds_demodulation.py -q
```

All RBDS decoder tests are in `tests/test_rbds_demodulation.py`.
