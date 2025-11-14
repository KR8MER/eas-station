# SDR Waterfall Display Troubleshooting Guide

## Issue
Receiver shows as "locked" but no waterfall/spectrum display appears on `/settings/radio` or `/audio-monitor`.

## Quick Start: Use the Web Diagnostics Tool

**The easiest way to diagnose SDR issues is through the web interface:**

1. Navigate to **Broadcast → SDR Diagnostics** in the main menu
2. Or go directly to: `http://your-server:5000/settings/radio/diagnostics`
3. The diagnostics page will show you:
   - Overall system health status
   - Number of configured vs. loaded receivers
   - Real-time sample buffer status
   - Detailed error messages
   - Built-in troubleshooting tips

**If the diagnostics page shows "RadioManager not initialized", you need to restart the web application (see below).**

## Root Cause (FIXED)
The RadioManager was not being initialized in the web application, so even though receivers were configured in the database, they weren't accessible to the web UI endpoints.

## Solution

### 1. **RESTART THE WEB APPLICATION** (Required)
The fixes have been committed, but you need to restart the web app for them to take effect:

```bash
# If running via docker-compose
docker-compose restart webapp

# If running directly
# Stop the current process (Ctrl+C) and restart:
python app.py
# or
flask run

# If using gunicorn/uwsgi
sudo systemctl restart eas-station  # or whatever your service is called
```

### 2. Run the Diagnostic Script
After restarting, run this to verify everything is working:

```bash
cd /path/to/eas-station
python3 scripts/diagnostics/check_sdr_status.py
```

Expected output when working:
```
✓ Status: Audio pipeline appears healthy
→ Receivers are locked and should be producing data
→ Check /settings/radio for waterfall display
```

### 3. Check the Web UI

After restart, go to: `http://your-server:5000/settings/radio`

You should see:
- A table of configured receivers
- A "Waveform Monitor" section with waterfall displays
- Auto-refresh checkbox (should be checked by default)
- Real-time scrolling waterfall spectrogram for each enabled receiver

### 4. Verify in Browser Console

Open browser Developer Tools (F12) and check the Console tab for:

**Good signs:**
- No errors related to `/api/radio/spectrum/`
- Network requests to `/api/radio/spectrum/{id}` returning 200 OK

**Bad signs (and what they mean):**
- `404 Receiver not running` → RadioManager not initialized (restart needed)
- `503 No samples available` → Receiver starting up or not locked
- `503 Spectrum feature requires NumPy` → NumPy not installed
- JavaScript errors → Frontend issue

## What the Fixes Do

### Fix 1: RadioManager Initialization (`app.py`)
Added `_initialize_radio_receivers()` function that:
- Loads all enabled receivers from database
- Configures RadioManager with those receivers
- Starts receivers that have `auto_start=True`
- Called automatically during app startup

### Fix 2: Sample Buffer Race Condition (`app_core/radio/drivers.py`)
- Sample buffer now initialized BEFORE capture thread starts
- Eliminates race condition where API requests arrived before buffer was ready
- Ensures `get_samples()` always returns data when receiver is running

### Fix 3: Better Error Logging (`webapp/routes_settings_radio.py`)
- Detailed logging when receiver instance not found
- Shows available receivers for debugging
- Provides helpful hints in error responses

## Troubleshooting Steps

### Problem: "No receivers configured in database"
**Solution:** Add a receiver at `/settings/radio`:
1. Click "Add Receiver" button
2. Fill in receiver details (driver, frequency, etc.)
3. Enable "Auto-start" checkbox
4. Save
5. Restart web application

### Problem: "RadioManager has no loaded receivers"
**Solution:** Restart the web application (see step 1 above)

### Problem: "Receiver running but not locked to signal"
**Check:**
- Antenna is connected properly
- Frequency is correct for your location
- SDR device is working (check `dmesg` output)
- Try manual frequency adjustment

### Problem: "No samples available"
**Possible causes:**
1. Receiver just started (wait 2-3 seconds)
2. Sample buffer not initialized (race condition - should be fixed now)
3. SDR device disconnected
4. Driver issue

**Solution:** Check receiver status in the diagnostic script

### Problem: Waterfall shows but no data/all black
**Possible causes:**
1. Signal too weak (nothing to display)
2. Frequency not tuned correctly
3. Antenna issue

**Solution:**
- Check signal strength in receiver status
- Verify frequency is correct
- Try a known-good frequency (e.g., FM radio station)

## API Endpoints for Manual Testing

Test the spectrum endpoint directly:

```bash
# Replace {receiver_id} with your receiver's ID (usually 1)
curl http://localhost:5000/api/radio/spectrum/1
```

Expected response:
```json
{
  "receiver_id": 1,
  "identifier": "rtlsdr0",
  "display_name": "RTL-SDR FM Receiver",
  "sample_rate": 2400000,
  "center_frequency": 97900000,
  "freq_min": 96700000,
  "freq_max": 99100000,
  "fft_size": 2048,
  "spectrum": [0.0, 0.05, 0.12, ...],  // Array of 2048 values
  "timestamp": 1699564821.234
}
```

## Frontend Debugging

If the waterfall still doesn't appear after restart:

1. **Open Browser DevTools** (F12)

2. **Check Console tab** for errors

3. **Check Network tab:**
   - Filter for `/spectrum/`
   - Should see requests every 200ms
   - Check response status (should be 200)
   - Click on request to see response data

4. **Check Elements tab:**
   - Look for `<canvas id="waveform-{receiver_id}">`
   - Canvas should be visible with reasonable dimensions
   - Check if canvas context is being created

5. **Common JavaScript issues:**
   ```javascript
   // In browser console, check:
   console.log(window.receivers);  // Should show array of receivers
   console.log(document.getElementById('waveformAutoRefresh').checked);  // Should be true
   ```

## Docker-Specific Notes

If running in Docker:

1. **Check container logs:**
   ```bash
   docker-compose logs -f webapp
   ```
   Look for:
   ```
   Configured X radio receiver(s) from database
   Started X radio receiver(s) with auto_start enabled
   ```

2. **Restart container:**
   ```bash
   docker-compose restart webapp
   ```

3. **Check if SDR device is passed through:**
   ```bash
   docker-compose exec webapp ls -la /dev/bus/usb/*/*
   ```

## Still Not Working?

If the waterfall still doesn't appear after following all steps:

1. Run the diagnostic script and save output:
   ```bash
   python3 scripts/diagnostics/check_sdr_status.py > sdr_diagnostic.txt
   ```

2. Check application logs for errors during startup

3. Verify the receiver is actually in the database:
   ```bash
   # Connect to your PostgreSQL database
   psql -U postgres -d your_database
   SELECT id, identifier, display_name, enabled, auto_start FROM radio_receivers;
   ```

4. Check browser console for JavaScript errors

5. Provide diagnostic output and logs for further troubleshooting

## Success Indicators

When everything is working correctly:

✓ Diagnostic script shows "Audio pipeline appears healthy"
✓ `/settings/radio` displays colorful scrolling waterfall
✓ Waterfall updates smoothly every 200ms
✓ Receiver status shows "Locked: Yes"
✓ Signal strength meter shows activity
✓ No errors in browser console
✓ Network tab shows successful `/api/radio/spectrum/` requests

## Technical Details

**Waterfall Display:**
- Updates every 200ms (5 Hz refresh rate)
- Shows 100 rows of history (20 seconds)
- Color mapping: Blue (weak) → Cyan → Green → Yellow → Red (strong)
- FFT size: 2048 bins
- Display shows frequency spectrum over time

**Audio Pipeline Flow:**
```
SDR Device → SoapySDR → RadioManager → Sample Buffer →
FFT Processing → Spectrum Data → JSON API →
Frontend JavaScript → Canvas Rendering → Waterfall Display
```

Each step must work for the waterfall to appear.
