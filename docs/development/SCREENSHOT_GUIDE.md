# Screenshot Guide for EAS-Station Documentation

This guide outlines which screenshots are needed to replace placeholders in the documentation.

## Required Screenshots

### 1. Dashboard / Home Page
**File**: `docs/screenshots/dashboard.png`
- **URL**: `http://localhost:5000/`
- **Content**: Main dashboard showing:
  - Active alerts count
  - Recent alert cards (if any)
  - Map with coverage area
  - System status indicators
- **Dimensions**: 1920x1080 recommended
- **Notes**: Capture with at least one active alert if possible

### 2. Alerts Page
**File**: `docs/screenshots/alerts.png`
- **URL**: `http://localhost:5000/alerts`
- **Content**: Alerts list view showing:
  - Filter options
  - Alert table with multiple entries
  - Severity indicators
  - Date/time stamps
- **Dimensions**: 1920x1080 recommended

### 3. SDR/Radio Settings Page
**File**: `docs/screenshots/radio-settings.png`
- **URL**: `http://localhost:5000/settings/radio`
- **Content**: Radio receiver configuration showing:
  - Configured SDR receivers
  - Receiver status (locked/unlocked)
  - Discovery and diagnostics buttons
  - Waveform monitor (if active)
- **Dimensions**: 1920x1080 recommended
- **Notes**: Show at least one configured receiver

### 4. Radio Receiver Modal
**File**: `docs/screenshots/receiver-add.png`
- **URL**: Click "Add Receiver" on radio settings page
- **Content**: Receiver configuration modal showing:
  - Form fields (Name, Identifier, Driver, Frequency, etc.)
  - Source type dropdown (SDR vs Stream)
  - Help text
- **Dimensions**: Focus on modal, crop as needed

### 5. Device Discovery Results
**File**: `docs/screenshots/device-discovery.png`
- **URL**: Click "Discover Devices" on radio settings page
- **Content**: Discovery modal showing:
  - List of discovered SDR devices
  - Device details (driver, serial, manufacturer)
  - "Add This Device" buttons
- **Dimensions**: Focus on modal
- **Notes**: Requires actual SDR hardware connected

### 6. Waveform Monitor
**File**: `docs/screenshots/waveform-monitor.png`
- **URL**: `http://localhost:5000/settings/radio` (scroll to bottom)
- **Content**: Waveform visualization showing:
  - Live audio waveforms for receivers
  - Sample rate and sample count
  - Green waveform on dark background with grid
- **Dimensions**: Focus on waveform section
- **Notes**: Requires active receivers

### 7. Admin/Settings Page
**File**: `docs/screenshots/admin-settings.png`
- **URL**: `http://localhost:5000/admin`
- **Content**: Admin panel showing:
  - Location settings
  - LED sign configuration
  - EAS broadcast settings
  - Database management options
- **Dimensions**: 1920x1080 recommended
- **Notes**: Capture in collapsed view showing all sections

### 8. Map View
**File**: `docs/screenshots/map-view.png`
- **URL**: Dashboard or alerts page
- **Content**: Interactive map showing:
  - Coverage area polygon
  - Alert markers (if any)
  - Map controls
- **Dimensions**: 1200x800 recommended
- **Notes**: Zoom to show county coverage area

### 9. Alert Detail Modal
**File**: `docs/screenshots/alert-detail.png`
- **URL**: Click on any alert card or row
- **Content**: Alert detail modal showing:
  - Full alert text
  - Affected areas
  - Effective/expires times
  - Severity and urgency
  - Action buttons
- **Dimensions**: Focus on modal

### 10. Audio Sources Page
**File**: `docs/screenshots/audio-sources.png`
- **URL**: `http://localhost:5000/audio`
- **Content**: Audio source management showing:
  - Configured audio sources (SDR, ALSA, Stream, etc.)
  - Source status and metrics
  - Add source button
- **Dimensions**: 1920x1080 recommended

### 11. M3U Stream Configuration
**File**: `docs/screenshots/stream-config.png`
- **URL**: Radio settings → Add Receiver → Source Type: Stream
- **Content**: Stream configuration modal showing:
  - Stream URL field
  - Format selection
  - M3U playlist example
- **Dimensions**: Focus on modal

### 12. Diagnostics Results
**File**: `docs/screenshots/diagnostics.png`
- **URL**: Click "Run Diagnostics" on radio settings page
- **Content**: Diagnostics modal showing:
  - SoapySDR installation status
  - NumPy status
  - Available drivers
  - Connected devices count
  - System ready indicator
- **Dimensions**: Focus on modal

## Screenshot Guidelines

### Technical Requirements
- **Format**: PNG (preferred) or JPG
- **Resolution**: At least 1920x1080 for full-page screenshots
- **Color Depth**: 24-bit RGB
- **Browser**: Chrome or Firefox (latest version)
- **Zoom Level**: 100% (no browser zoom)

### Style Guidelines
- **Clean Data**: Use realistic but clean test data
  - Example station IDs: "EASNODES", "WXR-TEST"
  - Example alerts: Real NOAA weather alerts (not sensitive info)
- **Consistent Theme**: Use default EAS-Station theme (dark/light as designed)
- **No Personal Info**: Don't include real API keys, passwords, or personal data
- **Professional**: No browser extensions, bookmarks, or taskbars visible

### Taking Screenshots

#### On macOS:
```bash
# Full screen
Cmd + Shift + 3

# Selected area
Cmd + Shift + 4

# Specific window
Cmd + Shift + 4, then press Space, click window
```

#### On Windows:
```bash
# Use Snipping Tool or:
Win + Shift + S  # Screen snip

# Or use PowerShell:
# Full screen to clipboard
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait("{PRTSC}")
```

#### On Linux:
```bash
# Full screen
gnome-screenshot

# Selected area
gnome-screenshot -a

# Or use scrot:
scrot -s screenshot.png
```

### After Capturing

1. **Crop/Resize**: Remove unnecessary chrome, focus on content
2. **Optimize**: Use `optipng` or similar to reduce file size
   ```bash
   optipng -o7 screenshot.png
   ```
3. **Name**: Use descriptive names matching this guide
4. **Place**: Put in `docs/screenshots/` directory
5. **Update Docs**: Replace placeholders with actual image references

## Placeholder Locations

Search for these patterns in documentation to find placeholders:

```bash
grep -r "placeholder" docs/
grep -r "TODO.*screenshot" docs/
grep -r "![.*](.*\.png)" docs/
```

## Example Markdown Image Syntax

```markdown
![Dashboard Screenshot](screenshots/dashboard.png)

<!-- With caption -->
![Dashboard showing active alerts](screenshots/dashboard.png)
*Figure 1: Main dashboard with two active weather alerts*

<!-- With link -->
[![Dashboard](screenshots/dashboard.png)](screenshots/dashboard.png)
```

## Automation (Optional)

For automated screenshot generation using Playwright or Puppeteer:

```javascript
// Example using Playwright
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.setViewportSize({ width: 1920, height: 1080 });

  await page.goto('http://localhost:5000');
  await page.screenshot({ path: 'docs/screenshots/dashboard.png' });

  await browser.close();
})();
```

## Need Help?

If you can't capture certain screenshots (e.g., lacking hardware for SDR screenshots):
1. Open an issue requesting community screenshots
2. Use mockup/demo data to simulate the view
3. Add a note in the PR that screenshots are pending

## Review Checklist

Before submitting screenshots:
- [ ] All images are properly named
- [ ] No personal or sensitive information visible
- [ ] Images are optimized (< 500KB each)
- [ ] Aspect ratio and resolution are consistent
- [ ] Documentation markdown references are updated
- [ ] Images render correctly in GitHub markdown preview
