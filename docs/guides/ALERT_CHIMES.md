# Alert Chimes (Pre / Post-Broadcast Sounds)

EAS Station can prepend or append a short attention sound to **every** outgoing
SAME broadcast — auto-forwarded CAP/IPAWS alerts, OTA relays from upstream
EAS sources, and operator-authored manual broadcasts. The chime plays:

- **Pre-alert chime:** before the very first SAME header burst.
- **Post-alert chime:** after the final EOM (End-of-Message) burst.

Chimes are purely cosmetic — they are **not** part of the SAME / FSK signaling
and decoders such as ENDECs and SAME-aware receivers will simply treat them as
ambient audio. They are useful for station fingerprinting, paging-style call
selection, and operator/listener attention before the official tones begin.

> **Important:** chimes are inserted at the broadcast boundaries. They never
> replace, mask, or modify the SAME headers, attention tone, narration, or EOM.

---

## Where to Configure

The chime settings live in the **Admin → EAS Broadcast Settings → Alert
Chimes** card. Settings persist in the `eas_settings` table.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| Pre-Alert Chime | dropdown | `none` | Profile played before the SAME header. |
| Pre-Alert Chime Duration | seconds (0.1–10.0) | `2.0` | Total length of the pre-alert chime. Ignored for DTMF. |
| Post-Alert Chime | dropdown | `none` | Profile played after the EOM. |
| Post-Alert Chime Duration | seconds (0.1–10.0) | `2.0` | Total length of the post-alert chime. Ignored for DTMF. |
| QC-II Tone A Frequency | Hz (50–4000) | `1000.0` | First tone for QC-II profile. |
| QC-II Tone B Frequency | Hz (50–4000) | `1500.0` | Second tone for QC-II profile. |
| DTMF Sequence | string (0–32 chars) | `""` | Digits dialed for DTMF profile. |

The pre-alert and post-alert profiles are configured independently, so you can
e.g. play a single `bell` before each broadcast and leave the post-alert
position disabled.

---

## Available Chime Profiles

### `none`
No chime is generated. This is the default for both positions.

### `bell`
A single 880 Hz sine tone with an exponential amplitude decay (≈ 5 % of peak
amplitude after 2 s). Sounds like a struck bell or chime. Duration controlled
by the chime-duration field.

### `beep`
A sustained 1000 Hz sine tone for the full configured duration. Useful as a
simple "stand by" attention beep.

### `three_tone`
Three ascending sine tones (440 Hz, 880 Hz, 1320 Hz), each occupying roughly
one third of the duration. Reminiscent of pager / paging-system call tones.

### `qc2` — Motorola Quick Call II
Two-tone paging used by fire, EMS, and dispatch radio systems.

* Tone A plays for **25 %** of the duration (≈ 1 s for a 4 s chime).
* Tone B plays for **75 %** of the duration (≈ 3 s for a 4 s chime).
* The 25 / 75 split mirrors the QC-II standard 1 s / 3 s ratio.
* Set Tone A and Tone B frequencies to the values published by the receiving
  agency / department (typical range 288–3000 Hz).

### `dtmf` — Dual-Tone Multi-Frequency
Plays each character of the configured **DTMF Sequence** as its standard
ITU-T Q.23 / Q.24 tone pair (low-group + high-group sine sum).

* Allowed characters: `0–9`, `A–D`, `*`, `#`. Lower-case is accepted and
  upper-cased. Any other characters are stripped on save.
* Maximum length: 32 valid digits (extra digits are dropped).
* Timing is fixed at **100 ms tone / 50 ms gap** per digit (the chime-duration
  field is **ignored** for DTMF). Total length therefore depends only on the
  number of digits.
* The two tones are summed and the combined waveform is scaled to half
  amplitude so the peak signal level matches single-tone profiles.

---

## Ordering Inside the Composite Broadcast

```
[ pre-alert chime ]   ← system-level chime, configured in EAS settings
   0.5 s silence
[ SAME header burst ] × 3
   ...                ← attention tone (1050 Hz), narration, end-of-message
[ EOM burst ] × 3
   0.5 s silence
[ post-alert chime ]  ← system-level chime, configured in EAS settings
```

For manual broadcasts the existing per-broadcast **pre-alert audio** /
**post-alert audio** uploads continue to bracket the **narration** segment
(between the attention tone and the EOM). The system-level chimes always sit
**outside** the SAME signalling, so the two features are complementary:

```
[ pre-alert CHIME ]
[ SAME header ]
[ attention tone ]
[ pre-alert AUDIO upload ]    ← per-broadcast, optional
[ TTS narration ]
[ post-alert AUDIO upload ]   ← per-broadcast, optional
[ EOM ]
[ post-alert CHIME ]
```

---

## Programmatic / Environment Overrides

For headless deployments, the following environment variables override the
database values when set:

| Variable | Equivalent setting |
|----------|--------------------|
| `EAS_PRE_ALERT_CHIME` | Pre-Alert Chime profile |
| `EAS_POST_ALERT_CHIME` | Post-Alert Chime profile |
| `EAS_PRE_ALERT_CHIME_DURATION` | Pre-Alert Chime Duration (seconds) |
| `EAS_POST_ALERT_CHIME_DURATION` | Post-Alert Chime Duration (seconds) |
| `EAS_QC2_TONE_A_FREQ` | QC-II Tone A Frequency (Hz) |
| `EAS_QC2_TONE_B_FREQ` | QC-II Tone B Frequency (Hz) |
| `EAS_DTMF_SEQUENCE` | DTMF Sequence |

Internally the chime is rendered by `app_utils.eas._generate_chime()`; profiles
are listed in `app_utils.eas.ALERT_CHIME_PROFILES`. Adding new profiles is a
matter of extending that helper and the validation set in
`webapp/admin/maintenance.py`.

---

## REST API

The chime settings are exposed via the standard EAS settings endpoint:

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
  "dtmf_sequence": "*911#"
}
```

Server-side validation:

* `*_chime` must be one of `none`, `bell`, `beep`, `three_tone`, `qc2`, `dtmf`
  (case-insensitive). Unknown values are silently rejected.
* `*_chime_duration` must be a number in `[0.1, 10.0]`.
* `qc2_tone_*_freq` must be a number in `[50.0, 4000.0]` Hz.
* `dtmf_sequence` is filtered to `0-9 A-D * #` and truncated to 32 characters.

---

## Database Schema

Schema additions are applied by Alembic migration
`20260501_add_alert_chime_to_eas_settings`:

| Column | Type | Default |
|--------|------|---------|
| `pre_alert_chime` | `VARCHAR(16) NOT NULL` | `'none'` |
| `post_alert_chime` | `VARCHAR(16) NOT NULL` | `'none'` |
| `pre_alert_chime_duration` | `DOUBLE PRECISION NOT NULL` | `2.0` |
| `post_alert_chime_duration` | `DOUBLE PRECISION NOT NULL` | `2.0` |
| `qc2_tone_a_freq` | `DOUBLE PRECISION NOT NULL` | `1000.0` |
| `qc2_tone_b_freq` | `DOUBLE PRECISION NOT NULL` | `1500.0` |
| `dtmf_sequence` | `VARCHAR(32) NOT NULL` | `''` |

The migration uses `ADD COLUMN IF NOT EXISTS` and the application also
self-heals these columns on first read via `_PENDING_MIGRATIONS` in
`webapp/admin/maintenance.py`, so existing deployments will not require
a manual schema fix-up.
