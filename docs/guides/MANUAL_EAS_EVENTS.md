# Manual EAS Events and Broadcast Builder

EAS Station supports manually-authored EAS broadcasts for drills, required weekly tests (RWT), and locally-generated emergency messages. The primary interface is the **Broadcast Builder**, accessible from the top navigation bar.

> **Important:** EAS Station is experimental software and is not FCC-certified equipment. Manual broadcasts must only be performed in controlled, isolated testing environments. Do not connect the output to licensed broadcast transmitters without proper FCC authorization.

---

## Broadcast Builder (Web Interface)

The Broadcast Builder walks you through constructing a complete EAS SAME header interactively in the browser.

### Opening the Broadcast Builder

Click **Broadcast Builder** in the top navigation bar (requires login). The builder is available at `/broadcast-builder`.

---

### Step 1: Select Originator Code

Choose the FCC Part 11 originator code that applies to your message:

| Code | Originator | Description |
|------|-----------|-------------|
| `EAS` | Emergency Alert System | Relay of another EAS station's message |
| `CIV` | Civil authorities | Local emergency management or government |
| `WXR` | National Weather Service | Weather-related alerts from NWS |
| `PEP` | Primary Entry Point | Presidential-level national alerts |

For drills and test purposes, use `EAS` or `CIV`.

---

### Step 2: Select Event Code

The event selector is filtered to the 47 CFR §11.31(d–e) authorized event codes. Common codes:

| Code | Event |
|------|-------|
| `RWT` | Required Weekly Test |
| `RMT` | Required Monthly Test |
| `EAN` | Emergency Action Notification |
| `TOR` | Tornado Warning |
| `SVR` | Severe Thunderstorm Warning |
| `FFW` | Flash Flood Warning |
| `TOE` | 911 Outage Emergency |
| `CAE` | Child Abduction Emergency |

For routine drills, use `RWT` (Required Weekly Test) or `DMO` (Practice/Demo).

---

### Step 3: Add Locations (PSSCCC)

Each EAS broadcast must specify which FIPS/SAME geographic codes it covers (up to 31 codes per message, per FCC rules).

**Adding locations using the picker:**

1. Select the **State** from the dropdown.
2. Select the **County/Parish** from the list.
3. Optionally select a **FEMA subdivision** if the alert covers only part of a county. The portion digit is set automatically.
4. Click **Add Location**.

Repeat for each covered area. The running list and SAME code preview update live.

**Entering codes manually:**

Paste a comma-separated list of 6-digit SAME codes directly into the manual entry field. Useful for bulk entry when covering many counties.

**Quick-fill from configured counties:**

Click **Load My Counties** to pre-populate the location list with the FIPS codes configured in **Admin → Location Settings**.

---

### Step 4: Set Valid Duration

Enter how long the alert is valid. The SAME `+TTTT` field represents duration in HH:MM format.

- Minimum: 0015 (15 minutes)
- Maximum: 9930 (99 hours, 30 minutes)

For RWT, the typical duration is 60 minutes (0100).

---

### Step 5: Review the SAME Header Preview

The live preview assembles and displays the complete SAME header string:

```
ZCZC-WXR-TOR-039137+0130-0511445-KHIO/NWS-
```

Each field is labeled:
- `ZCZC` — preamble
- `WXR` — originator
- `TOR` — event code
- `039137` — FIPS/SAME code(s)
- `+0130` — duration (1 hour 30 minutes)
- `0511445` — Julian day and UTC time of issuance
- `KHIO/NWS` — your callsign and originator name

Verify all fields before proceeding.

---

### Step 6: Quick Weekly Test Preset

Click **Quick Weekly Test** to pre-load your configured counties, set the event to `RWT`, and populate a standard test script. The preset:

- Omits the attention signal per FCC guidance for RWT
- Pre-fills a standard RWT announcement script
- Sets a 60-minute duration

You can re-enable the dual-tone or 1050 Hz alert tone if your facility requires it.

---

### Step 7: Configure Audio Components

Toggle which audio components to include in the broadcast:

| Component | Description |
|-----------|-------------|
| SAME header bursts | Three repetitions of the FSK-encoded header (required) |
| Attention tone | 8-second dual-tone (853 Hz + 960 Hz) or 1050 Hz NWR alert |
| Voice message | TTS-synthesized or custom audio narration |
| EOM (End of Message) | Three-burst `NNNN` end marker (required) |

All components have configurable 1-second guard intervals between sections.

> **Tip:** EAS Station can also play a configurable **pre-alert** and/or
> **post-alert chime** outside the SAME signalling — useful for station
> fingerprinting, paging-style call selection (QC-II), or DTMF unit IDs.
> See the [Alert Chimes guide](ALERT_CHIMES.md) for details.

---

### Step 8: Enter the Voice Message Text

If **Voice message** is enabled, type the announcement text in the message field. The text-to-speech engine (pyttsx3 or Azure) will synthesize it to audio.

Example RWT script:
```
This is a test of the Emergency Alert System. This is only a test.
The Emergency Alert System is operated by [YOUR STATION] in cooperation with
federal, state, and local authorities. No action is required.
This concludes this test of the Emergency Alert System.
```

---

### Step 9: Confirm and Execute

1. Click **Preview Broadcast** to review the complete audio package plan.
2. Click **Execute Broadcast** to confirm and start the broadcast.
3. EAS Station generates the WAV audio package and triggers the output:
   - GPIO relay activates the transmitter
   - Audio is routed to the configured output device and Icecast stream
   - The message is logged to the EAS message history

---

## Command-Line: manual_eas_event.py

For scripted or automated manual broadcasts, use the command-line tool:

```bash
python scripts/manual_eas_event.py --help
```

**Basic example — Required Weekly Test:**

```bash
python scripts/manual_eas_event.py \
  --originator EAS \
  --event RWT \
  --fips 039137,039057 \
  --duration 0100 \
  --callsign "WXYZ/EAS" \
  --message "This is a test of the Emergency Alert System. This is only a test."
```

**Options:**

| Flag | Description |
|------|-------------|
| `--originator` | EAS originator code (EAS, CIV, WXR, PEP) |
| `--event` | EAS event code (TOR, RWT, SVR, etc.) |
| `--fips` | Comma-separated SAME/FIPS codes |
| `--duration` | Duration in HHMM format (e.g., 0100 = 1 hour) |
| `--callsign` | Station callsign in LLLLLLLL format |
| `--message` | Voice message text (TTS) |
| `--no-attention` | Skip the attention tone |
| `--no-voice` | Skip the voice message |
| `--dry-run` | Build the audio package without broadcasting |

---

## Alert Self-Test (RWT Capture Replay)

For testing the EAS monitoring pipeline without transmitting, use the built-in self-test with bundled sample captures:

```bash
python scripts/run_alert_self_test.py
```

This replays a pre-recorded RWT SAME header through the audio processing pipeline, triggering the full decode and logging workflow without activating the GPIO relay or transmitter.

Via the web interface: **Admin → Operations → Run Self-Test**.

---

## Message Archival

Every executed broadcast (manual or automatic) is stored in the **EAS Messages** table and accessible from:

- **Admin → EAS Messages** — list all broadcasts with timestamps and header details
- **Alert Verification** (`/admin/alert-verification`) — upload captured audio for SAME decode and comparison

Audio files are stored in the media directory (`EAS_AUDIO_DIR`) and linked to the message record.

---

## Troubleshooting

### Broadcast Builder produces no audio

- Confirm TTS is configured (**Admin → Settings → TTS**) and enabled. Use the **"Test TTS"** button on that page to verify synthesis is working.
- For Azure TTS, verify the endpoint URL and API key are correctly entered in **Admin → Settings → TTS**.

### GPIO relay does not activate

- Verify GPIO is enabled in **Admin → Hardware Settings**.
- Check the transmit relay pin matches your physical wiring.
- Inspect hardware service logs: `journalctl -u eas-station-hardware -f`

### SAME header preview shows wrong time

- EAS Station uses UTC for the `JJJHHMM` field. Verify the server clock is correct: `timedatectl status`.

### Broadcast appears in logs but not on air

- Confirm the audio output device is correct in **Admin → Audio Settings**.
- Test with `aplay -D <device> /path/to/test.wav` to verify the output route.
