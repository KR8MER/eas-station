# Pre/Post-Alert Signaling

EAS Station™ can prepend or append a short attention signal to **every** outgoing
SAME broadcast — auto-forwarded CAP/IPAWS alerts, OTA relays from upstream
EAS sources, and operator-authored manual broadcasts. The signal plays:

- **Pre-alert signal:** before the very first SAME header burst.
- **Post-alert signal:** after the final EOM (End-of-Message) burst.

Signals are purely cosmetic — they are **not** part of the SAME / FSK signaling
and decoders such as ENDECs and SAME-aware receivers will simply treat them as
ambient audio. They are useful for station fingerprinting, paging-style call
selection, and operator/listener attention before the official tones begin.

> **Important:** signals are inserted at the broadcast boundaries. They never
> replace, mask, or modify the SAME headers, attention tone, narration, or EOM.

---

## Where to Configure

The signal settings live in the **Admin → Broadcast → EAS Encoder Settings →
Pre/Post-Alert Signaling** card. Settings persist in the `eas_settings` table.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| Pre-Alert Signal | dropdown | `none` | Profile played before the SAME header. |
| Pre-Alert Signal Duration | seconds (0.1–10.0) | `2.0` | Total length of the pre-alert signal. Ignored for DTMF, QC-II, and MDC1200. |
| Post-Alert Signal | dropdown | `none` | Profile played after the EOM. |
| Post-Alert Signal Duration | seconds (0.1–10.0) | `2.0` | Total length of the post-alert signal. Ignored for DTMF, QC-II, and MDC1200. |
| QC-II Tone A Frequency | Hz (50–4000) | `1000.0` | First tone for QC-II profile. |
| QC-II Tone B Frequency | Hz (50–4000) | `1500.0` | Second tone for QC-II profile. |
| QC-II Enable Long Tone | boolean | `false` | Append a sustained tone after the A+B sequence. |
| QC-II Long Tone Duration | seconds (1–120) | `10.0` | Duration of the appended long tone. |
| DTMF Sequence | string (0–32 chars) | `""` | Digits dialed for DTMF profile. |
| MDC1200 Unit ID | integer (1–65535, decimal **or** `0x0001`–`0xFFFF` hex) | `1` | Source subscriber unit ID for the MDC1200 profile (the transmitting station's ID — what receiving radios display as the caller). |
| MDC1200 Op-Code | dropdown | `ptt_id_pre` | Symbolic preset (or `custom` for raw bytes). |
| MDC1200 Raw Op-Code | byte (0x00–0xFF, optional) | *(unset)* | Used only when preset = `custom`. |
| MDC1200 Raw Argument | byte (0x00–0xFF, optional) | *(unset)* | Used only when preset = `custom`. |
| MDC1200 Target Unit ID | integer (1–65535, decimal **or** `0x0001`–`0xFFFF` hex, optional) | *(unset)* | Destination subscriber ID for double-packet ops (`call_alert`, `selective_call`). When set the encoder appends a second 14-byte info block carrying this ID — frame becomes ~267 ms instead of ~173 ms. Leave blank to fall back to a single-packet frame. |

The pre-alert and post-alert profiles are configured independently, so you can
e.g. play a single `bell` before each broadcast and leave the post-alert
position disabled.

---

## Available Signal Profiles

### `none`
No signal is generated. This is the default for both positions.

### `bell`
A single 880 Hz sine tone with an exponential amplitude decay (≈ 5 % of peak
amplitude after 2 s). Sounds like a struck bell or chime. Duration controlled
by the signal-duration field.

### `beep`
A sustained 1000 Hz sine tone for the full configured duration. Useful as a
simple "stand by" attention beep.

### `three_tone`
Three ascending sine tones (440 Hz, 880 Hz, 1320 Hz), each occupying roughly
one third of the duration. Reminiscent of pager / paging-system call tones.

### `qc2` — Motorola Quick Call II
Two-tone paging used by fire, EMS, and dispatch radio systems.

* Tone A plays for **1 s**.
* Tone B plays for **4 s**.
* Total duration is **5 s** (duration field is ignored).
* Set Tone A and Tone B frequencies to the values published by the receiving
  agency / department (typical range 288–3000 Hz).
* Optionally enable the **Long Tone** to append a sustained tone at Tone B
  frequency after the A+B sequence. Configure its duration (1–120 s) with
  the **Long Tone Duration** field.

> **Note for existing deployments:** Prior to this change, Tone B was 3 s
> (4 s total). Existing QC-II configurations will automatically use the new
> 4 s Tone B (5 s total) without any settings change.

### `dtmf` — Dual-Tone Multi-Frequency
Plays each character of the configured **DTMF Sequence** as its standard
ITU-T Q.23 / Q.24 tone pair (low-group + high-group sine sum).

* Allowed characters: `0–9`, `A–D`, `*`, `#`. Lower-case is accepted and
  upper-cased. Any other characters are stripped on save.
* Maximum length: 32 valid digits (extra digits are dropped).
* Timing is fixed at **100 ms tone / 50 ms gap** per digit (the signal-duration
  field is **ignored** for DTMF). Total length therefore depends only on the
  number of digits.
* The two tones are summed and the combined waveform is scaled to half
  amplitude so the peak signal level matches single-tone profiles.

### `mdc1200` — Motorola Selective Calling

A 1200-baud FFSK packet (mark = 1200 Hz, space = 1800 Hz) carrying this
station's *Unit ID* and an op-code that tells receiving Motorola subscribers
what kind of call this is (PTT-ID, Emergency, Request to Talk, Call
Alert, Selective Call, etc.).

* Packet duration is fixed by the protocol — the signal-duration field is
  **ignored**:
  * **Single-packet ops** (PTT-ID, Emergency, Request to Talk, Remote
    Monitor, Custom): 26 bytes / 208 bits → **~173 ms**.
  * **Double-packet ops** (Call Alert, Selective Call): 40 bytes /
    320 bits → **~267 ms**. A second 14-byte info block carrying the
    target subscriber's ID is appended after a 4-byte inter-packet
    re-sync preamble.
* **Unit ID** is the 16-bit *source* identifier — the EAS station's own
  ID that receiving radios display as the caller (1–65535). Accepts both
  decimal (`1234`) and hex (`0x04D2`) input — Motorola CPS commonly
  displays unit IDs as 4-digit hex.
* **Target Unit ID** is the 16-bit *destination* ID for double-packet
  ops. When `call_alert` or `selective_call` is selected and a target
  ID is configured, the encoder produces the canonical 40-byte double
  frame; receiving radios programmed with that ID alert (Call Alert →
  beep + display) or unmute their speaker (Selective Call → audio
  path opens). Leaving the field blank falls back to a single-packet
  frame whose source ID also acts as the target — some receivers
  tolerate this shortcut, but real Motorola CPS-programmed
  subscribers usually expect the double form.
* **Op-Code preset** chooses what packet to emit:

  | Preset | `op` | `arg` | Frame | Meaning |
  |---|---|---|---|---|
  | `ptt_id_pre` | `0x01` | `0x80` | single | PTT-ID at the start of a transmission (default) |
  | `ptt_id_post` | `0x00` | `0x80` | single | PTT-ID at the end of a transmission |
  | `emergency` | `0x40` | `0x80` | single | Emergency alarm |
  | `request_to_talk` | `0x35` | `0x89` | single | Request-to-talk paging |
  | `remote_monitor` | `0x11` | `0x80` | single | Remote-monitor command |
  | `call_alert` | `0x63` | `0x85` | double | Page a target subscriber (target ID required for canonical form) |
  | `selective_call` | `0x35` | `0x80` | double | Voice Selective Call — unmute target subscriber |
  | `custom` | any | any | single | Operator-supplied raw op/arg bytes (decimal or `0x..` hex) |

* **Smart pre/post pairing.** When *both* the pre and post signals are set
  to `mdc1200` and the op-code preset is `ptt_id_pre` (the default), EAS
  Station automatically substitutes `ptt_id_post` on the post-alert
  position so receiving Motorola radios see a complete bookend pair and
  close the call cleanly. All other presets — including `call_alert`
  and `selective_call` — pass through unchanged on both sides.

> **Verifying generated packets.** Render any test alert and decode the
> generated WAV with [multimon-ng](https://github.com/EliasOenal/multimon-ng):
> `multimon-ng -a MDC -t wav <file>.wav` will print one line per packet,
> e.g. `MDC: 0180 1234 PTT ID PRE`. Use this on the bench before going on
> the air with a real fleet.

#### Two-way LMR forwarding (the canonical use case)

The driving design goal of MDC1200 support is **forwarding EAS audio over
an existing Motorola-style two-way radio system**. With MDC1200 signals
enabled and the audio output wired into a base-station radio's auxiliary
input (PTT keying handled by an external GPIO / VOX / COR loop), each
broadcast goes on-air as:

```
[radio PTT keys up by GPIO/VOX]
  Pre  MDC1200 PTT-ID-Pre   ← "from unit 1234"
  1 s silence
  SAME header burst × 3     ← decoded by ENDECs and SAME-aware radios
  Attention tone (8 s)
  Voice narration
  SAME EOM × 3
  1 s silence
  Post MDC1200 PTT-ID-Post  ← "1234 clear"
[PTT releases]
```

Receiving subscribers display the calling unit ID, optionally selectively
unmute for that ID, log the call in their dispatch console, trigger any
configured alarms, and cleanly close the call on the post-ID. Common
fleets where this fits naturally: county EM dispatch repeaters,
volunteer fire / EMS / Skywarn / RACES nets, school and utility radio
systems, industrial site-wide LMR. The full technical reference,
including frame format, FEC, and op-code table, lives in
[`docs/reference/protocols/MDC1200.md`](../reference/protocols/MDC1200.md).

> **PTT keying is not part of this feature.** EAS Station™ produces audio.
> Putting the radio into transmit is the responsibility of the radio
> interface (GPIO output, COR loop, VOX, VOIP gateway, …) and must be
> configured separately, keyed off the same trigger that starts EAS
> Station audio playback.

---

## Ordering Inside the Composite Broadcast

```
[ pre-alert signal ]   ← system-level signal, configured in EAS settings
   1 s silence
[ SAME header burst ] × 3
   ...                ← attention tone (1050 Hz), narration, end-of-message
[ EOM burst ] × 3
   1 s silence
[ post-alert signal ]  ← system-level signal, configured in EAS settings
```

For manual broadcasts the existing per-broadcast **pre-alert audio** /
**post-alert audio** uploads continue to bracket the **narration** segment
(between the attention tone and the EOM). The system-level signals always sit
**outside** the SAME signalling, so the two features are complementary:

```
[ pre-alert SIGNAL ]
[ SAME header ]
[ attention tone ]
[ pre-alert AUDIO upload ]    ← per-broadcast, optional
[ TTS narration ]
[ post-alert AUDIO upload ]   ← per-broadcast, optional
[ EOM ]
[ post-alert SIGNAL ]
```

---

## Programmatic / Environment Overrides

For headless deployments, the following environment variables override the
database values when set:

| Variable | Equivalent setting |
|----------|--------------------|
| `EAS_PRE_ALERT_CHIME` | Pre-Alert Signal profile |
| `EAS_POST_ALERT_CHIME` | Post-Alert Signal profile |
| `EAS_PRE_ALERT_CHIME_DURATION` | Pre-Alert Signal Duration (seconds) |
| `EAS_POST_ALERT_CHIME_DURATION` | Post-Alert Signal Duration (seconds) |
| `EAS_QC2_TONE_A_FREQ` | QC-II Tone A Frequency (Hz) |
| `EAS_QC2_TONE_B_FREQ` | QC-II Tone B Frequency (Hz) |
| `EAS_QC2_LONG_TONE_ENABLED` | QC-II Long Tone enabled (`1`, `true`, or `yes`) |
| `EAS_QC2_LONG_TONE_SECONDS` | QC-II Long Tone Duration (seconds) |
| `EAS_DTMF_SEQUENCE` | DTMF Sequence |
| `EAS_MDC1200_UNIT_ID` | MDC1200 source Unit ID (decimal or `0x..` hex) |
| `EAS_MDC1200_OP_CODE` | MDC1200 Op-Code preset name |
| `EAS_MDC1200_OP_CODE_RAW` | MDC1200 Raw Op-Code byte (decimal or `0x..` hex) |
| `EAS_MDC1200_ARG_RAW` | MDC1200 Raw Argument byte (decimal or `0x..` hex) |
| `EAS_MDC1200_TARGET_UNIT_ID` | MDC1200 Target Unit ID for Call Alert / Selective Call double-packet ops (decimal or `0x..` hex; empty/0 → single packet) |

Internally the signal is rendered by `app_utils.eas._generate_chime()`; profiles
are listed in `app_utils.eas.ALERT_CHIME_PROFILES`. Adding new profiles is a
matter of extending that helper and the validation set in
`webapp/admin/maintenance.py`.

---

## REST API

The signal settings are exposed via the standard EAS settings endpoint:

```http
GET /admin/eas_settings
PUT /admin/eas_settings    Content-Type: application/json
```

`PUT` payload fields (all optional):

```json
{
  "pre_alert_chime": "bell",
  "post_alert_chime": "none",
  "pre_alert_chime_duration": 1.5,
  "post_alert_chime_duration": 2.0,
  "qc2_tone_a_freq": 1387.5,
  "qc2_tone_b_freq": 1530.0,
  "qc2_long_tone_enabled": true,
  "qc2_long_tone_seconds": 10.0,
  "dtmf_sequence": "*911#",
  "mdc1200_unit_id": "0x04D2",
  "mdc1200_op_code": "ptt_id_pre",
  "mdc1200_op_code_raw": null,
  "mdc1200_arg_raw": null,
  "mdc1200_target_unit_id": null
}
```

Server-side validation:

* `*_chime` must be one of `none`, `bell`, `beep`, `three_tone`, `qc2`, `dtmf`, `mdc1200`
  (case-insensitive). Unknown values are silently rejected.
* `*_chime_duration` must be a number in `[0.1, 10.0]`.
* `qc2_tone_*_freq` must be a number in `[50.0, 4000.0]` Hz.
* `qc2_long_tone_enabled` must be a boolean.
* `qc2_long_tone_seconds` must be a number in `[1.0, 120.0]`.
* `dtmf_sequence` is filtered to `0-9 A-D * #` and truncated to 32 characters.
* `mdc1200_unit_id` must be an integer in `[1, 65535]`. Strings are parsed
  with `int(value, 0)`, so `"1234"` and `"0x04D2"` are both accepted.
* `mdc1200_op_code` must be one of `ptt_id_pre`, `ptt_id_post`, `emergency`,
  `request_to_talk`, `remote_monitor`, `call_alert`, `selective_call`,
  `custom` (case-insensitive).
* `mdc1200_op_code_raw` and `mdc1200_arg_raw` must each be an integer in
  `[0, 255]` (or `null`/`""` to clear). Strings are parsed with
  `int(value, 0)`, so both decimal and `0x..` hex are accepted.
* `mdc1200_target_unit_id` must be an integer in `[1, 65535]`, or
  `null`/`""`/`0` to clear (which forces single-packet emission).
  Strings are parsed with `int(value, 0)`, so both decimal and `0x..`
  hex are accepted. Used only when `mdc1200_op_code` is `call_alert` or
  `selective_call`; ignored for other presets.

---

## Database Schema

Schema additions are applied by Alembic migrations
`20260501_add_alert_chime_to_eas_settings`,
`20260505_add_qc2_long_tone_to_eas_settings`,
`20260505_add_mdc1200_to_eas_settings`, and
`20260505_add_mdc1200_target_unit_id_to_eas_settings`:

| Column | Type | Default |
|--------|------|---------|
| `pre_alert_chime` | `VARCHAR(16) NOT NULL` | `'none'` |
| `post_alert_chime` | `VARCHAR(16) NOT NULL` | `'none'` |
| `pre_alert_chime_duration` | `DOUBLE PRECISION NOT NULL` | `2.0` |
| `post_alert_chime_duration` | `DOUBLE PRECISION NOT NULL` | `2.0` |
| `qc2_tone_a_freq` | `DOUBLE PRECISION NOT NULL` | `1000.0` |
| `qc2_tone_b_freq` | `DOUBLE PRECISION NOT NULL` | `1500.0` |
| `qc2_long_tone_enabled` | `BOOLEAN NOT NULL` | `FALSE` |
| `qc2_long_tone_seconds` | `DOUBLE PRECISION NOT NULL` | `10.0` |
| `dtmf_sequence` | `VARCHAR(32) NOT NULL` | `''` |
| `mdc1200_unit_id` | `INTEGER NOT NULL` | `1` |
| `mdc1200_op_code` | `VARCHAR(32) NOT NULL` | `'ptt_id_pre'` |
| `mdc1200_op_code_raw` | `SMALLINT NULL` | `NULL` |
| `mdc1200_arg_raw` | `SMALLINT NULL` | `NULL` |
| `mdc1200_target_unit_id` | `INTEGER NULL` | `NULL` |

The migration uses `ADD COLUMN IF NOT EXISTS` and the application also
self-heals these columns on first read via `_PENDING_MIGRATIONS` in
`webapp/admin/maintenance.py`, so existing deployments will not require
a manual schema fix-up.
