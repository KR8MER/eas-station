# Alpha Sign Communications Protocol — Reference & Conformance Audit

**Implementation:** `scripts/led_sign_controller.py`
(`LEDSignController = Alpha9120CController`, line 2439)
**Authoritative source:** *Alpha® Sign Communications Protocol*, document
**9708‑8061F** (March 10, 2006) — in this repo at `bugs/M-Protocol.pdf`.
**Target hardware:** Alpha 9120C, **Alpha 2.0 protocol generation ("version 2")**.

> Page numbers below refer to the printed page of the manual. Line numbers
> refer to `scripts/led_sign_controller.py`.

Status legend: ✅ conformant · ⚠️ partial / misleading · ❌ non‑conformant
(wire bug) · ⬜ not implemented.

> **Remediation status (June 2026):** the P0–P2 issues called out below have
> been fixed in `scripts/led_sign_controller.py` and are covered by
> `tests/test_alpha_mprotocol.py` (checksum verified against the p.60
> `AAHELLO → 01FB` example). The ❌/⚠️ entries below are retained as the
> historical audit and to document *why* each change was made; the "what it
> used to do" descriptions refer to the pre‑fix code.

---

## 1. Transmission packet structure

The protocol's *Standard packet* (a.k.a. "1‑byte"/"^A" format, p.9) has two
relevant variations — **without** a checksum and **with** a checksum:

```
without checksum:  <NUL×5> <SOH> <TT> <AAAA> <STX> <cmd><data> <EOT>
with    checksum:  <NUL×5> <SOH> <TT> <AAAA> <STX> <cmd><data> <ETX> <CK CK CK CK> <EOT>
```

* `<NUL×5>` — five 0x00 wake‑up bytes for autobauding (p.9). ✅ implemented (`WAKEUP`, line 304).
* `<SOH>` 0x01, `<STX>` 0x02, `<ETX>` 0x03, `<EOT>` 0x04. ✅
* `TT` — Type Code (1 char; `Z` = all sign types). ✅ (`type_code`, default `Z`).
* `AAAA` — two‑char sign address (`00` = broadcast). ✅ (`sign_id`).
* **Sending `<ETX>` commits the frame to checksum mode** — *"If an `<ETX>`
  character is transmitted before the `<EOT>`, the sign will expect a
  Checksum"* (p.11). Our builder **always** appends `<ETX>` + checksum
  (`_build_frame_from_payload`, line 962), so the checksum **must** be correct.

### 1.1 Checksum — ❌ NON‑CONFORMANT (critical)

> **Manual (p.11, Table 7):** *"Four ASCII digits that represent a **16‑bit
> hexadecimal summation** of all transmitted data from the previous `<STX>`
> through the previous `<ETX>` inclusive. The most significant digit is first."*

Worked example (p.60): `…<STX>"AAHELLO"<ETX>"01FB"<EOT>`
`sum(0x02,'A','A','H','E','L','L','O',0x03) = 0x01FB` → **`"01FB"`** (STX *and*
ETX included; 4 hex digits).

**Our implementation** (`_calculate_checksum`, line 954) computes an **XOR** and
returns **2** hex digits, over `payload + ETX` (STX excluded):

```python
checksum = 0
for byte in payload:        # XOR, not summation
    checksum ^= byte
return f"{checksum:02X}"     # 2 digits, should be 4
```

Wrong on three counts: **XOR vs SUM**, **2 vs 4 digits**, **STX excluded**.
Because we transmit `<ETX>`, the sign expects a valid checksum and, per the
manual, *"when a sign receives an invalid Checksum, the associated data will
not be processed."* → **every checksummed frame is rejected.**

**Fix:** sum bytes from `<STX>` through `<ETX>` inclusive, 16‑bit, 4 hex digits:

```python
def _calculate_checksum(self, data: bytes) -> str:
    return f"{sum(data) & 0xFFFF:04X}"
# include STX in the summed range when building the frame
```

(Alternative: omit `<ETX>`+checksum entirely and use the no‑checksum Standard
packet. Adding the *correct* checksum is preferred for error detection.)

---

## 2. Command codes (byte after `<STX>`)

| Code | Meaning | Implemented |
|---|---|---|
| `A` 0x41 | Write TEXT file | ✅ `_build_message` (817) |
| `B` 0x42 | Read TEXT file | ✅ `read_text_file` (2213) |
| `E` 0x45 | Write SPECIAL FUNCTION | ✅ (see §4) |
| `F` 0x46 | Read SPECIAL FUNCTION | ✅ `read_*` (1751‑1896) |
| `G` 0x47 | Write STRING file | ⬜ |
| `H` 0x48 | Read STRING file | ⬜ |
| `I` 0x49 | Write SMALL DOTS PICTURE | ⚠️ `send_dots_graphic` (2296) — see §5 |
| `J` 0x4A | Read SMALL DOTS PICTURE | ⬜ |
| `K`/`L` | Write/Read RGB DOTS PICTURE | ⬜ |
| `M`/`N` | Write/Read LARGE DOTS PICTURE | ⬜ |
| `O` | Write ALPHAVISION | ⬜ |
| `T` 0x54 | Set Timeout Message | ⬜ |

---

## 3. TEXT‑file inline control codes (within Write TEXT `A`)

### 3.1 Colour — ✅ `0x1C` + code (manual p.81)

`Color` enum (line 122) matches exactly: `1`Red `2`Green `3`Amber `4`DimRed
`5`DimGreen `6`Brown `7`Orange `8`Yellow `9`Rainbow1 `A`Rainbow2 `B`ColorMix
`C`Autocolor. RGB `0x1C`+`Z`+`RRGGBB` is **Alpha 3.0 only** (we emit it via
`COLOR_CMD+'Z'+rgb`; harmless on 2.0 if unused). ✅

### 3.2 Font / character set — ⚠️ codes valid, names misleading

`0x1A` + selector (p.81). The selector **bytes** we send (`1`–`9`,`:`) are
valid, but the `Font` enum **names** (line 138) misrepresent them, e.g.
`FONT_15x7='6'` actually selects *Ten‑high standard*, `FONT_32x16=':'` selects
*Seven‑shadow‑fancy*. Wire‑safe, but the names should be corrected to the
manual's font list to avoid operator confusion.

### 3.3 Display mode — ✅ `<ESC>` + position + mode (p.88)

`DisplayMode` enum (line 152) uses `a`–`v` (0x61‑0x76) and the `n`+digit
"special/string" modes (0x6E + 0x30…), which match the manual. ✅
*(Display‑position byte mapping `0x20–0x27` (`LINE_POSITION_MAP`, 291) should be
spot‑checked against the sign's row semantics, but is not a framing error.)*

### 3.4 Speed — ❌ NON‑CONFORMANT

> **Manual (p.36/81):** speed is a **single** control byte:
> `0x15`=Speed 1 (slow) … `0x19`=Speed 5 (fast); `0x09`=No‑hold.

**Our code** emits `SPEED_CMD (0x15)` **+** an ASCII digit (`'1'`–`'5'`)
(`_build_message`, line 917; `SPEED_CMD`, 361; `Speed` enum, 197). The sign
therefore reads `0x15` (always **Speed 1**) followed by a **literal digit
character that prints on the sign**.

**Fix:** emit one byte `0x14 + N` (Speed N), no trailing digit. e.g. Speed 3 →
`0x17`.

### 3.5 Character attributes / "special functions" — ❌ NON‑CONFORMANT

The manual defines these as distinct codes (p.80‑81):

| Attribute | Manual code |
|---|---|
| Wide characters off / on | `0x11` / `0x12` (single byte) |
| Double‑height off / on | `0x05` + `'0'`/`'1'` |
| True descenders off / on | `0x06` + `'0'`/`'1'` |
| **Character flash off / on** | `0x07` + `'0'`/`'1'` |
| Char spacing: proportional / fixed | `0x1E` + `'0'` / `'1'` |
| Wide/double/fancy set | `0x1D` + type + `'0'`/`'1'` |

**Our `SpecialFunction` enum (line 206) routes *everything* through
`SPECIAL_CMD = 0x1E`** (line 362, used at 921‑923) with digits `0`–`7`:

| Our enum | We emit | Actually means on the wire |
|---|---|---|
| `WIDE_CHAR_ON='0'` | `0x1E 0x30` | char spacing → proportional |
| `WIDE_CHAR_OFF='1'` | `0x1E 0x31` | char spacing → fixed |
| `TRUE_DESC_ON='2'` | `0x1E 0x32` | invalid arg for 0x1E |
| `CHAR_FLASH_ON='4'` | `0x1E 0x34` | invalid arg for 0x1E |
| `FIXED_WIDTH='6'` | `0x1E 0x36` | invalid arg for 0x1E |

→ Wide/descender/flash/fixed‑width all do the wrong thing. **Notably,
`send_flashing_message()` and `emergency_override()` rely on `CHAR_FLASH_ON`,
so emergency‑alert flashing does not work.**

**Fix:** map each attribute to its real code (flash → `0x07`+`'1'`, wide →
`0x12`, descenders → `0x06`+`'1'`, fixed/proportional → `0x1E`+`'1'`/`'0'`).

### 3.6 Call Time / Call Date — ⚠️ partial

* Call **Time** = `0x13` (`TIME_CMD`, line 363). ✅ code correct.
* Call **Date** = `0x0B` + format digit `'0'`–`'9'` (p.80). ⬜ **not implemented**
  — `send_time_display()` emits a literal `{TIME}` string and a pre‑formatted
  date string instead of the live `0x13`/`0x0B` fields.

---

## 4. Write SPECIAL FUNCTION (`E` / 0x45) — Table 15 (manual p.21‑26)

Verified label → behaviour, with our implementation status:

| Label | Hex | Function | Status / notes |
|---|---|---|---|
| `␠` | **0x20** | Set Time of Day — 4 digits `HhMm` (24h) | ❌ `set_time_and_date` (1925) sends `"HH:MM:SS\rMM/DD/YY"` — wrong format; date is a *separate* command |
| `!` | **0x21** | Speaker — `"00"`=enable `"FF"`=disable | ❌ `set_speaker` (2136) uses code **0x23** and data `'E'`/`'D'` |
| `$` | **0x24** | Clear Memory (`E$`) / Set Memory Config (`FTPSIZEQQQQ`×N) | ⬜ not implemented as such — **but `set_brightness` emits `E$` (see below)** |
| `&` | **0x26** | Set Day of Week — `'1'`Sun…`'7'`Sat | ❌ `set_day_of_week` (1980) uses code **0x22** and data `'0'`–`'6'` |
| `'` | **0x27** | Set Time Format — `'S'`=am/pm, `'M'`=24h | ⚠️ code ✅ but `set_time_format` (2027) is **inverted** (sends `'S'` for 24h) |
| `(` | **0x28** | Generate Speaker Tone — `A`/`B`/`0`/`1`/`2`+`FFDR` | ⚠️ `beep()` (2179) uses BEL in a text file instead |
| `)` | **0x29** | Set Run Time Table — `FQQQQ` | ⬜ |
| `+` | 0x2B | Display Text at XY (ALPHAVISION) | ⬜ |
| `,` | **0x2C** | **Soft Reset** (no data; non‑destructive) | ⬜ |
| `.` | **0x2E** | Set Run Sequence — `KPF` | ❌ `set_run_mode` (2066) misuses this code as an auto/manual toggle (no such command exists) |
| `/` | **0x2F** | Set Dimming Register — `WWww` (**Solar signs only**) | ⬜ (see brightness) |
| `2` | **0x32** | Set Run Day Table — `FSs` | ⬜ |
| `5` | **0x35** | Set Counter | ⬜ |
| `7` | **0x37** | **Set Serial Address** — 2 hex chars | ⬜ |
| `8` | **0x38** | Set LARGE DOTS PICTURE Memory Config | ⬜ |
| `;` | **0x3B** | Set Date — `mmddyy` | ⬜ (date is currently baked into a text string) |
| `@` | **0x40** | Set Dimming Control Register (Alpha 2.0/3.0, AlphaEclipse) | ⬜ |

### 4.1 `set_brightness` — ❌ DANGEROUS

`set_brightness` (line 1486) builds `payload = f"E${level:X}"`. But **`E$` is
*Clear Memory / Set Memory Configuration*** (0x24), **not** brightness. So every
brightness call pokes the memory‑configuration command with malformed data.
The real brightness control is **Set Dimming Register `E/` (0x2F)** with
`WWww` (`WW`=light threshold, `ww`=`00`=100% … `04`=44%), and it is **only
effective on Solar signs**; AlphaEclipse signs use `E@` (0x40). A plain 9120C
may have **no** M‑Protocol brightness control. **Fix:** stop emitting `E$`;
emit `E/ WWww` per spec (and document the sign‑type limitation).

### 4.2 Existing `WriteSpecialExtCommand` enum (line 239) vs manual

| Enum member | Enum value | Manual code | Verdict |
|---|---|---|---|
| `SET_TIME_DATE` | 0x20 | 0x20 (time only) | ⚠️ code ok, data/format wrong |
| `SET_DAY_OF_WEEK` | 0x22 | **0x26** | ❌ wrong |
| `SET_SPEAKER` | 0x23 | **0x21** | ❌ wrong |
| `SET_TIME_FORMAT` | 0x27 | 0x27 | ✅ code (logic inverted) |
| `SET_RUN_MODE` | 0x2E | 0x2E = Set Run **Sequence** | ❌ misused |
| `SET_BRIGHTNESS` | 0x30 | dimming = **0x2F** | ❌ wrong (and method ignores the enum, uses `E$`) |

---

## 5. SMALL DOTS PICTURE (`I` / 0x49) — ⚠️ unverified format

`send_dots_graphic` (line 2296) builds `I<label><colour><WWWW><HH><hex rows…>`
using ASCII hex‑pair row encoding. The manual's SMALL/LARGE DOTS picture
formats and the **memory‑allocation prerequisite** (a DOTS file must be
allocated via Set Memory Configuration `E$`/`E8` first) differ from this
encoding. Treat as **unverified** until bench‑tested; likely needs the
dimensions/dot‑data format and a preceding memory‑config write.

---

## 6. Not implemented (vs full protocol)

* **STRING files** (`G`/`H`) + **Call String** `0x10` — the standard way to
  live‑update a field without rewriting the layout (and without the display
  blanking). p.37.
* **Counters** (`E5`) and counter field insertion.
* **Call Date** `0x0B` inline field.
* **Large / RGB DOTS** picture files (`K`–`N`) and DOTS read‑back (`J`).
* **Set Memory Configuration write** (`E$ FTPSIZEQQQQ`) — required before using
  non‑default file labels, STRING files, or DOTS files.
* **Scheduling:** Set Run Time Table (`E)`), Run Day Table (`E2`), Run
  Sequence (`E.`).
* **Housekeeping:** Soft Reset (`E,`), Set Serial Address (`E7`),
  Set Date (`E;`), Set Timeout Message (`T`).

---

## 7. Remediation status

| # | Item | Status |
|---|---|---|
| P0 | **Checksum** → 16‑bit SUM over STX→ETX inclusive, 4 hex digits (`_calculate_checksum`) | ✅ done (test: `AAHELLO → 01FB`) |
| P0 | **`set_brightness`** no longer emits `E$` (Clear Memory); now `E/` `WWww` | ✅ done |
| P1 | **Speed** → single byte `0x15`–`0x19` | ✅ done |
| P1 | **Character attributes** → flash `0x07`+`'1'`, wide `0x11/0x12`, descenders `0x06`+`'1'`, spacing `0x1E`+`'0'/'1'` (fixes alert flashing) | ✅ done |
| P1 | **Day of Week** → `E&` data `'1'`–`'7'` | ✅ done |
| P1 | **Speaker** → `E!` data `'00'`/`'FF'` | ✅ done |
| P1 | **Time format** inversion fixed (`'M'`=24h, `'S'`=am/pm) | ✅ done |
| P1 | **Time/date** split into Set Time of Day `E␠`(`HhMm`) + Set Date `E;`(`mmddyy`) | ✅ done |
| P1 | **`set_run_mode`** no longer emits a malformed `0x2E` frame (now a logged no‑op) | ✅ done |
| P2 | **Soft Reset** `E,` | ✅ done |
| P2 | **Set Serial Address** `E7` (2 hex) | ✅ done |
| P2 | **Set Memory Configuration** `E$ FTPSIZEQQQQ` + guarded **Clear Memory** | ✅ done |
| P2 | **Run Time Table** `E)` / **Run Day Table** `E2` | ✅ done |
| P3 | Font enum names; STRING files + Call String; Call Date `0x0B`; counters; large/RGB dots | ⬜ deferred |

Implemented in `scripts/led_sign_controller.py`; verified by
`tests/test_alpha_mprotocol.py`.

> **Hardware note:** the brightness/dimming register (`E/`) is, per the
> manual, only effective on Solar signs; a standard 9120C may ignore it.
> The SMALL DOTS picture format (§5) remains **unverified** against the spec
> and should be bench‑tested before relying on it.

---

*Sources: Alpha® Sign Communications Protocol 9708‑8061F (March 10, 2006),
pp. 9‑11, 18‑26, 36, 50‑60, 80‑89, 117‑118 — `bugs/M-Protocol.pdf`.*
