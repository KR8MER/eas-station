# Audio/SDR Configuration Fix Tool

EAS Station™ includes a built-in diagnostic page that detects and repairs the most common sample-rate misconfiguration in SDR setups: an **audio** sample rate accidentally stored where an **IQ** (RF) sample rate belongs, or vice versa. The page lives at `/admin/audio-sdr-fix` (it is not linked from the navigation menus — enter the URL directly while logged in).

---

## When to Use It

Use this tool when you see any of these symptoms after configuring receivers or audio sources:

| Symptom | Likely Cause |
|---------|-------------|
| MP3 streams never appear as Icecast mount points | Audio source sample rate far too low |
| Waterfall display shows the wrong frequency scale (kHz instead of MHz) | Receiver IQ rate set to an audio-rate value |
| High-pitched squeal or tone on SDR audio | Sample-rate mismatch between IQ capture and audio output |

The shared root cause is a sample rate of the wrong magnitude — e.g. `48000` (an audio rate) stored as a receiver's IQ rate, which should be in the millions of Hz.

---

## What the Diagnosis Checks

Clicking **Run Diagnosis** calls `GET /api/admin/audio-sdr-fix/diagnose`, which scans only **enabled** receivers and audio sources:

| Check | Flagged when | Recommended value |
|-------|-------------|-------------------|
| SDR receiver IQ sample rate | Below 100,000 Hz | 2,500,000 Hz (2.5 MHz) for Airspy drivers; 2,400,000 Hz (2.4 MHz) for RTL-SDR and others |
| HTTP stream audio source sample rate | Below 32,000 Hz | 48,000 Hz |
| SDR audio source output sample rate | Below 20,000 Hz | 48,000 Hz |

The results panel shows a summary (receiver count, audio source count, issues, warnings) and a per-item card for every configuration, including frequency, modulation, and current rates, with each problem marked in red alongside its recommended replacement.

> Airspy R2 hardware only supports 2.5 MHz and 10 MHz IQ rates, which is why the tool picks 2.5 MHz when the receiver driver contains "airspy".

---

## Applying Fixes

If issues were found, the **Step 2: Apply Fixes** panel lists exactly what will change. Clicking **Apply Fixes** calls `POST /api/admin/audio-sdr-fix/apply` with `{"auto_fix": true}` and performs these database updates in one transaction:

1. **Receivers** — every enabled receiver with an IQ rate below 100 kHz is set to 2.5 MHz (Airspy) or 2.4 MHz (other drivers).
2. **HTTP stream sources** — every enabled `stream` source with an audio rate below 32 kHz is set to 48 kHz.
3. **SDR audio sources** — every enabled `sdr` source with an audio output rate below 20 kHz is set to 48 kHz.

The response lists each change with old and new values, and the page automatically re-runs the diagnosis so you can confirm everything now reads OK.

> **Note:** Apply Fixes updates *all* matching configurations at once — there is no per-item selection. Review the fix list before confirming. The changes only touch sample-rate fields; frequencies, gains, and other settings are untouched.

---

## Restarting the SDR Service

The new sample rates are stored in the database but the running SDR service keeps using its old values until restarted. The tool's **Step 3** panel shows the command — the `POST /api/admin/audio-sdr-fix/restart-service` endpoint does **not** restart anything itself; it only returns the command for you to run on the host:

```bash
sudo systemctl restart eas-station-sdr.service
```

After the restart, verify:

- Icecast mount points are listed (default `http://<host>:8001/`)
- The waterfall display (`/admin/radio`) shows the correct MHz frequency scale
- Streams play clear audio with no squeal

---

## Routes Reference

| Method | Route | Purpose |
|--------|-------|---------|
| `GET` | `/admin/audio-sdr-fix` | Diagnostic page (HTML) |
| `GET` | `/api/admin/audio-sdr-fix/diagnose` | Scan enabled receivers/sources, return issues as JSON |
| `POST` | `/api/admin/audio-sdr-fix/apply` | Apply the fixes described above (`{"auto_fix": true}`) |
| `POST` | `/api/admin/audio-sdr-fix/restart-service` | Returns the manual `systemctl` restart command (does not restart) |

All routes require a logged-in session (the application's deny-by-default guard); the POST endpoints additionally require the standard CSRF header when called outside the page.

---

## If Problems Persist

- Work through the [SDR Master Troubleshooting Guide](SDR_MASTER_TROUBLESHOOTING_GUIDE.md) for hardware detection, driver, and gain issues — this tool only corrects sample rates.
- Check the SDR service logs: `journalctl -u eas-station-sdr.service -n 100`.
- Verify Icecast itself is healthy via `/api/health/icecast` (see [Health Monitoring Endpoints](../guides/HEALTH_MONITORING.md)).
