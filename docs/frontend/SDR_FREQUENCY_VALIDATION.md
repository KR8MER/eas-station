# SDR Frequency and Hardware Validation

## Overview

The EAS Station™ SDR configuration UI provides comprehensive frequency and hardware validation to ensure correct receiver configuration.

## Frequency Input - Already in MHz!

### How It Works

The frontend **already accepts frequency in MHz**, not Hz. Users enter frequencies like:
- NOAA: `162.550` MHz
- FM: `97.9` MHz
- AM: `800` kHz (displayed as `0.800` MHz)

The system automatically converts these to Hz internally before saving to the database.

### Implementation Details

**Frontend Fields:**
- `receiverFrequencyInput` - Visible input field accepting MHz (e.g., "162.550")
- `receiverFrequency` - Hidden field storing Hz value for backend (e.g., 162550000)

**Validation Flow:**
1. User enters frequency in MHz in `receiverFrequencyInput`
2. JavaScript validates via `/api/radio/validate-frequency` endpoint
3. Backend validates against service type constraints:
   - **NOAA**: Must be one of 7 valid frequencies (162.400-162.550 MHz)
   - **FM**: Must be 88.1-108.0 MHz with odd tenths (.1, .3, .5, .7, .9)
   - **AM**: Must be 530-1700 kHz with 10 kHz spacing
4. If valid, hidden field is populated with Hz value
5. UI shows success/error message with formatted frequency

**Code Location:**
- Template: `templates/settings/radio.html` (lines 1762-1802)
- Validation API: `webapp/routes_settings_radio.py` 
- Service config: `app_core/radio/service_config.py`

## Hardware-Specific Validation

### Sample Rate Validation by Hardware

The system automatically validates sample rates based on SDR hardware capabilities.

#### Airspy R2 Constraints

Airspy R2 **ONLY** supports these exact sample rates:
- 2.5 MHz (2,500,000 Hz)
- 10 MHz (10,000,000 Hz)

The UI enforces this by:
1. Detecting Airspy driver selection
2. Fetching hardware capabilities from `/api/radio/capabilities/{driver}`
3. Populating sample rate dropdown with ONLY valid rates (2.5 MHz and 10 MHz)
4. Showing error if invalid rate is selected

**Frontend Implementation** (`templates/settings/radio.html` lines 1645-1703):
```javascript
if (isAirspy) {
    defaultRates = [2500000, 10000000];  // Only 2.5 and 10 MHz
} else {
    defaultRates = [250000, 1024000, 1920000, 2048000, 2400000, 2560000];
}
```

**Backend Validation** (`webapp/routes_settings_radio.py` lines 282-300):
```python
# Validate sample rate compatibility with driver
is_valid, error_msg = validate_sample_rate_for_driver(
    data["driver"], sample_rate, device_args
)
if not is_valid:
    return None, error_msg
```

**Hardware Validation Function** (`app_core/radio/discovery.py:329`):
```python
def validate_sample_rate_for_driver(
    driver: str, 
    sample_rate: int, 
    device_args: Optional[Dict[str, str]] = None
) -> tuple[bool, Optional[str]]:
    """
    Validate sample rate against hardware capabilities.
    Queries actual hardware if available, falls back to known constraints.
    """
```

#### RTL-SDR

RTL-SDR supports a wider range of sample rates:
- 250 kHz - 3.2 MHz typically
- Common rates: 250 kHz, 1.024 MHz, 2.048 MHz, 2.4 MHz, 2.56 MHz

### Validation Layers

The system has **three layers** of validation:

1. **Frontend UI Constraints**
   - Dropdown shows only valid sample rates for selected hardware
   - Real-time frequency validation as user types
   - Visual feedback (green checkmark for valid, red X for invalid)

2. **Frontend API Validation**
   - `/api/radio/validate-frequency` - Validates frequency against service type
   - `/api/radio/capabilities/{driver}` - Gets hardware-specific constraints
   - `/api/radio/service-config/{service_type}` - Gets service defaults

3. **Backend Database Validation**
   - `_parse_receiver_payload()` validates all parameters before save
   - `validate_sample_rate_for_driver()` checks hardware compatibility
   - Database constraints prevent invalid data

## Service Type Configuration

The system automatically configures receivers based on service type:

### NOAA Weather Radio
- **Modulation**: NFM (Narrowband FM)
- **Bandwidth**: 25 kHz
- **Stereo**: Disabled (mono only)
- **De-emphasis**: 75 μs (North America)
- **RBDS**: Disabled
- **Squelch**: Enabled with carrier alarm

### FM Broadcast
- **Modulation**: WFM (Wideband FM)
- **Bandwidth**: 200 kHz
- **Stereo**: Enabled
- **De-emphasis**: 75 μs (North America)
- **RBDS**: Enabled (Program Service, Radio Text)
- **Squelch**: Enabled, no alarm

### AM Broadcast
- **Modulation**: AM
- **Bandwidth**: 10 kHz
- **Stereo**: Disabled (mono only)
- **De-emphasis**: Disabled (AM doesn't use it)
- **RBDS**: Disabled
- **Squelch**: Enabled with carrier alarm

## Validation Error Messages

### Frequency Errors

**NOAA**:
```
Invalid NOAA frequency. Valid frequencies: 162.400, 162.425, 162.450, 
162.475, 162.500, 162.525, 162.550 MHz
```

**FM**:
```
FM frequencies must end in .1, .3, .5, .7, or .9 (e.g., 97.9)
```

```
FM frequency must be between 88.1 and 108.0 MHz
```

**AM**:
```
AM frequency must be between 530 and 1700 kHz with 10 kHz spacing
```

### Sample Rate Errors

**Airspy**:
```
Airspy R2 only supports 2.5 MHz and 10 MHz sample rates. 
Configured rate 2.4 MHz is invalid.
```

**Generic**:
```
Sample rate 5000000 Hz not supported by this hardware. 
Valid rates: [list of supported rates]
```

## User Experience Flow

### Adding a Receiver

1. **Select SDR Device**
   - System detects hardware and driver
   - Fetches hardware capabilities

2. **Choose Service Type**
   - NOAA / FM / AM button group
   - System loads service-specific defaults

3. **Enter Frequency**
   - User types in MHz (e.g., "162.550")
   - Real-time validation shows green checkmark or red error
   - Help text shows valid range for service type

4. **Select Sample Rate**
   - Dropdown shows ONLY valid rates for this hardware
   - Recommended rate is marked with ⭐
   - Help text explains hardware constraints

5. **Configure Advanced Options**
   - Gain, modulation, squelch, etc.
   - Defaults populated based on service type
   - Hardware constraints enforced

6. **Save**
   - Backend validates all parameters
   - Returns specific error if validation fails
   - Success: Receiver added to fleet

## API Endpoints

### `/api/radio/validate-frequency` (POST)
Validates frequency against service type constraints.

**Request**:
```json
{
  "service_type": "NOAA",
  "frequency": "162.550"
}
```

**Response (valid)**:
```json
{
  "valid": true,
  "frequency_hz": 162550000,
  "frequency_display": "162.550 MHz (NOAA WX7)"
}
```

**Response (invalid)**:
```json
{
  "valid": false,
  "error": "Invalid NOAA frequency. Valid frequencies: ..."
}
```

### `/api/radio/capabilities/{driver}` (GET)
Gets hardware-specific capabilities (sample rates, gain range, etc.).

**Response**:
```json
{
  "driver": "airspy",
  "sample_rates": [2500000, 10000000],
  "gains": {
    "LNA": {"min": 0, "max": 15, "step": 1},
    "MIX": {"min": 0, "max": 15, "step": 1},
    "VGA": {"min": 0, "max": 15, "step": 1}
  },
  "frequency_range": {"min": 24000000, "max": 1800000000}
}
```

### `/api/radio/service-config/{service_type}` (GET)
Gets service-specific configuration defaults.

**Response**:
```json
{
  "modulation_type": "NFM",
  "audio_output": true,
  "stereo_enabled": false,
  "deemphasis_us": 75.0,
  "enable_rbds": false,
  "bandwidth": 25000,
  "frequency_placeholder": "e.g., 162.550 for WX7",
  "frequency_help": "Enter NOAA Weather Radio frequency in MHz"
}
```

## Testing Validation

### Test Valid Configurations

**NOAA Weather Radio (RTL-SDR)**:
```
Service Type: NOAA
Frequency: 162.550 MHz
Sample Rate: 2.4 MHz
Driver: rtlsdr
Expected: ✅ Valid
```

**FM Broadcast (Airspy)**:
```
Service Type: FM
Frequency: 97.9 MHz
Sample Rate: 2.5 MHz
Driver: airspy
Expected: ✅ Valid
```

### Test Invalid Configurations

**Airspy with invalid sample rate**:
```
Service Type: NOAA
Frequency: 162.550 MHz
Sample Rate: 2.4 MHz  ❌ Invalid for Airspy!
Driver: airspy
Expected: ❌ Error - "Airspy only supports 2.5 or 10 MHz"
```

**Invalid NOAA frequency**:
```
Service Type: NOAA
Frequency: 162.600 MHz  ❌ Not a valid NOAA frequency!
Expected: ❌ Error - "Invalid NOAA frequency. Valid: 162.400-162.550"
```

**Invalid FM frequency**:
```
Service Type: FM
Frequency: 97.8 MHz  ❌ Must be odd tenth!
Expected: ❌ Error - "FM frequencies must end in .1, .3, .5, .7, or .9"
```

## Summary

✅ **Frequency input is already in MHz** - No changes needed  
✅ **Hardware validation is already implemented** - Airspy constraints enforced  
✅ **Service type validation is working** - NOAA/FM/AM frequency ranges checked  
✅ **Three-layer validation** - Frontend UI + API + Backend database  
✅ **Clear error messages** - Users know exactly what's wrong  
✅ **Real-time feedback** - Validation as you type  

The system is **fully functional** for frequency and hardware validation. No code changes are required.
