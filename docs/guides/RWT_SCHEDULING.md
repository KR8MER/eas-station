# Automatic RWT Scheduling Guide

This guide explains how to configure and use the automatic Required Weekly Test (RWT) scheduling system in EAS Station.

---

## Overview

The automatic RWT scheduler allows you to configure RWT broadcasts to run automatically on specific days of the week within designated time windows. This ensures compliance with FCC requirements for regular system testing while minimizing manual intervention.

### Key Features

- **Automatic Scheduling**: Set it and forget it - RWT broadcasts send automatically
- **Day Selection**: Choose specific days (Monday-Sunday)
- **Time Windows**: Configure start and end times
- **Geographic Targeting**: Specify SAME/FIPS codes for targeted areas
- **Compliance Logging**: All broadcasts logged for FCC compliance tracking
- **Lean Audio**: RWT contains only SAME header and EOM tones (no TTS, no attention tones)

---

## Accessing RWT Schedule Configuration

### Via Navigation Menu
1. Log into EAS Station
2. Click **Broadcast** in the top navigation bar
3. Select **RWT Schedule** from the dropdown menu

### Direct URL
Navigate directly to: `https://your-server/rwt-schedule`

---

## Configuration Options

### 1. Enable/Disable Toggle

Turn automatic RWT broadcasts on or off with a single switch. When disabled, no automatic broadcasts will occur (manual broadcasts can still be triggered).

### 2. Days of Week

Select which days RWT should be sent using checkboxes:
- Monday (0)
- Tuesday (1)
- Wednesday (2)
- Thursday (3)
- Friday (4)
- Saturday (5)
- Sunday (6)

**Example**: Select Sunday and Tuesday for twice-weekly testing.

### 3. Time Window Configuration

Set the hours during which RWT broadcasts can occur:

- **Start Time**: Hour (0-23) and Minute (0-59)
- **End Time**: Hour (0-23) and Minute (0-59)

**Example**: Start 08:00, End 16:00 = RWT can send anytime between 8:00 AM and 4:00 PM

**Note**: Only ONE RWT will be sent per day, even if the time window is multiple hours.

### 4. SAME/FIPS Codes

Configure which geographic areas receive the RWT. Enter FIPS codes separated by commas or newlines.

**Default**: 7 Ohio counties pre-configured:
```
039003  # Allen County, OH
039039  # Defiance County, OH
039063  # Hancock County, OH
039069  # Henry County, OH
039125  # Paulding County, OH
039161  # Van Wert County, OH
039173  # Wood County, OH
```

**To add your own counties**:
1. Find FIPS codes at [NOAA FIPS Codes](https://www.weather.gov/nwr/FIPS)
2. Enter as 6-digit codes (e.g., 039003 for Allen County, OH)
3. Separate multiple codes with commas or newlines

### 5. Originator Code

Select the message originator:
- **WXR** (National Weather Service) - Default
- **EAS** (EAS Participant/Broadcaster)
- **CIV** (Civil Authorities)
- **PEP** (Primary Entry Point)

### 6. Station Identifier

Enter your 8-character station identifier (e.g., `EASNODES`, `WXYZ123`, etc.). This will be automatically padded with spaces if shorter than 8 characters.

---

## How Automatic Scheduling Works

### Scheduling Logic

The system checks every minute whether an RWT should be sent. For a broadcast to occur, ALL of the following must be true:

1. **Schedule Enabled**: The toggle is ON
2. **Configured Day**: Current day matches one of the selected days
3. **Within Time Window**: Current time is between start and end times
4. **Not Already Sent**: RWT has not been sent today

### Broadcast Behavior

When conditions are met, the system automatically:

1. **Generates SAME Header** with configured FIPS codes
2. **Creates Audio Package**:
   - SAME header (3 bursts)
   - End of Message (EOM) tones (3 bursts)
   - **NO** TTS narration
   - **NO** attention tones (853/960 Hz)
3. **Stores in Database** for compliance logging
4. **Logs Event** in system logs

### Once Per Day Guarantee

The scheduler ensures only ONE RWT is sent per configured day. Once sent, no additional RWT will be sent that day, regardless of how many times conditions are met.

---

## Testing Your Configuration

### Send Test RWT Now

Use the **"Send Test RWT Now"** button to immediately trigger a test broadcast:

1. Configure your settings
2. Click **"Send Test RWT Now"**
3. Confirm the broadcast
4. Check **Broadcast Archive** to verify the RWT was sent

This is useful for:
- Verifying SAME codes are correct
- Testing audio output
- Confirming database logging
- Validating before enabling automatic scheduling

---

## Monitoring and Verification

### Last Run Information

The configuration page displays:
- **Last Run Time**: When the last automatic RWT was sent
- **Last Run Status**: Success or failure
- **Last Run Details**: Additional information about the broadcast

### Broadcast Archive

All RWT broadcasts (manual and automatic) are stored in the database:

1. Navigate to **Broadcast → Broadcast Archive**
2. Look for entries with event code "RWT"
3. View details including:
   - Identifier
   - SAME header
   - Timestamp
   - Audio components
   - Download links

### System Logs

Check system logs for scheduler activity:

```bash
docker compose logs -f app | grep "RWT"
```

Look for messages like:
- `RWT scheduler started for automatic weekly tests`
- `Triggering automatic RWT broadcast`
- `RWT broadcast sent successfully`

---

## Example Configurations

### Example 1: Weekly Sunday Morning Test

**Use Case**: Send RWT every Sunday morning

**Configuration**:
- Enable: ON
- Days: Sunday (6)
- Start Time: 08:00
- End Time: 12:00
- SAME Codes: (your counties)
- Originator: WXR
- Station ID: EASNODES

**Result**: One RWT will be sent each Sunday between 8:00 AM and 12:00 PM.

### Example 2: Bi-Weekly Testing

**Use Case**: Send RWT twice per week

**Configuration**:
- Enable: ON
- Days: Tuesday (1), Friday (4)
- Start Time: 14:00
- End Time: 16:00
- SAME Codes: (your counties)
- Originator: EAS
- Station ID: WXYZ1234

**Result**: One RWT on Tuesday and one on Friday, each between 2:00 PM and 4:00 PM.

### Example 3: Daily Testing (Not Recommended)

**Use Case**: Send RWT every day (excessive for FCC requirements)

**Configuration**:
- Enable: ON
- Days: All days (0-6)
- Start Time: 10:00
- End Time: 11:00
- SAME Codes: (your counties)
- Originator: WXR
- Station ID: EASNODES

**Result**: One RWT every day between 10:00 AM and 11:00 AM.

**Note**: FCC requires weekly testing, not daily. This configuration is excessive.

---

## Troubleshooting

### RWT Not Sending Automatically

**Check**:
1. **Schedule Enabled**: Toggle is ON
2. **Days Configured**: At least one day is selected
3. **Time Window**: Current time is within start/end times
4. **Scheduler Running**: Check logs for "RWT scheduler started"
5. **Database Table**: Run migration to create `rwt_schedule_config` table

**Verify**:
```bash
# Check if scheduler is running
docker compose logs -f app | grep "RWT scheduler"

# Should see: "RWT scheduler started for automatic weekly tests"
```

### RWT Sent Multiple Times Per Day

This should not happen due to the once-per-day check. If it does:

1. Check system logs for errors
2. Verify database last_run_at is being updated
3. Report issue to maintainer

### Manual Test Button Not Working

**Check**:
1. Configuration saved
2. Browser console for errors
3. Network connectivity
4. Authentication status (must be logged in)

---

## Advanced Configuration

### Environment Variable Override

You can override default SAME codes using environment variables:

```bash
# In .env file
EAS_MANUAL_FIPS_CODES="039003,039039,039063,039069,039125,039161,039173"
```

This sets the default SAME codes for all manual RWT generation, including the scheduler.

### Custom Scheduler Interval

The scheduler checks every 1 minute by default. This is not configurable through the UI but can be modified in `app_core/rwt_scheduler.py`:

```python
class RWTScheduler:
    def __init__(self, check_interval_minutes: int = 1):  # Change this value
```

---

## FCC Compliance Notes

### Required Weekly Tests

Per FCC Part 11, broadcast stations must conduct:
- **Weekly Tests**: At least once per week
- **Monthly Tests**: Once per calendar month (can be the weekly test)

The RWT scheduler helps maintain compliance by:
- Automating weekly test generation
- Logging all broadcasts for records
- Using proper SAME header format
- Including originator and station ID

### Record Keeping

All RWT broadcasts are stored in the database with:
- Timestamp
- SAME header
- Audio files
- Geographic codes
- Originator information

This provides compliance documentation for FCC inspections.

---

## Security Considerations

### Access Control

RWT schedule configuration requires:
- User authentication
- Proper permissions/roles
- CSRF protection on all API calls

### Audit Trail

All configuration changes are logged:
- Who made the change
- When it was made
- What was changed

Check system logs for audit information.

---

## API Reference

### Get Configuration

```http
GET /api/rwt-schedule/config
```

Returns current RWT schedule configuration.

### Save Configuration

```http
POST /api/rwt-schedule/config
Content-Type: application/json

{
  "enabled": true,
  "days_of_week": [0, 2],
  "start_hour": 8,
  "start_minute": 0,
  "end_hour": 16,
  "end_minute": 0,
  "same_codes": ["039003", "039039"],
  "originator": "WXR",
  "station_id": "EASNODES"
}
```

### Trigger Test RWT

```http
POST /api/rwt-schedule/test
```

Immediately sends a test RWT broadcast.

---

## Related Documentation

- [EAS Broadcast Workflow](HELP.md) - Manual EAS generation
- [SAME Encoding](../architecture/THEORY_OF_OPERATION.md) - Technical details
- [Setup Instructions](SETUP_INSTRUCTIONS.md) - Initial configuration

---

## Support

For issues or questions:

1. Check system logs: `docker compose logs -f app`
2. Review configuration: `/rwt-schedule`
3. Test manually: Use "Send Test RWT Now" button
4. Report issues: https://github.com/KR8MER/eas-station/issues

---

**Last Updated**: 2025-11-18
**Version**: 2.7.2+
