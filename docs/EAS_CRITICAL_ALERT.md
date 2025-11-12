# ⚠️ CRITICAL EAS EVENT CODES MISSING FROM OHIO PLAN

**ALERT DATE:** 2025-01-12
**PRIORITY:** IMMEDIATE ACTION REQUIRED
**AFFECTED:** All Ohio EAS Participants

---

## Executive Summary

The Ohio EAS Plan (December 2018) is **missing 27+ event codes** currently approved by the FCC. **Six of these codes are CRITICAL for Ohio operations**, including the recently identified **Snow Squall Warning (SQW)**.

---

## CRITICAL Missing Codes (Immediate Action Required)

### 1. SQW - Snow Squall Warning ❌ **HIGHEST PRIORITY**

**Why Critical:** Snow squalls cause sudden whiteout conditions leading to multi-vehicle pileups on Ohio highways.

**Definition:** Sudden, brief, intense snowfall with gusty winds causing visibility near zero and flash freeze conditions.

**Ohio Impact:** I-71, I-75, I-77, I-80/90 corridors experience deadly pile-ups during snow squalls.

**Action:** Add to all encoders/decoders IMMEDIATELY

```
Event Code: SQW
Event Name: Snow Squall Warning
Category: Warning
Relay: REQUIRED
Duration: Typically 30-60 minutes
Coverage: County-specific
```

---

### 2. ISW - Ice Storm Warning ❌ **CRITICAL**

**Why Critical:** Ice storms cause widespread power outages, tree damage, and hazardous travel across Ohio.

**Definition:** Significant ice accumulation (≥ 0.25 inches) expected to cause dangerous conditions.

**Ohio Impact:** Statewide - Major events occur every winter season.

**Action:** Add to all encoders/decoders IMMEDIATELY

```
Event Code: ISW
Event Name: Ice Storm Warning
Category: Warning
Relay: REQUIRED
Duration: 12-48 hours typical
Coverage: Multi-county
```

---

### 3. WCW - Wind Chill Warning ❌ **CRITICAL**

**Why Critical:** Dangerous wind chills cause frostbite and hypothermia, especially in northern Ohio.

**Definition:** Wind chills ≤ -25°F expected for 3+ hours.

**Ohio Impact:** Northern counties, especially near Lake Erie, experience life-threatening wind chills annually.

**Action:** Add to all encoders/decoders IMMEDIATELY

```
Event Code: WCW
Event Name: Wind Chill Warning
Category: Warning
Relay: REQUIRED
Duration: Several hours to days
Coverage: Regional
```

---

### 4. LSW - Lake Effect Snow Warning ❌ **CRITICAL**

**Why Critical:** Lake effect snow causes sudden heavy snowfall in lakeshore counties.

**Definition:** Heavy lake effect snow (≥ 6 inches in 12 hours or ≥ 8 inches in 24 hours).

**Ohio Impact:** Critical for Ashtabula, Lake, Cuyahoga, Erie, Lucas, Ottawa counties.

**Action:** Add to all encoders/decoders - PRIORITY for lakeshore stations

```
Event Code: LSW
Event Name: Lake Effect Snow Warning
Category: Warning
Relay: REQUIRED for lakeshore areas
Duration: Hours to days
Coverage: Lake Erie shoreline counties
```

---

### 5. LFW - Lakeshore Flood Warning ❌ **CRITICAL**

**Why Critical:** Lake Erie flooding threatens waterfront communities and infrastructure.

**Definition:** Lakeshore flooding causing significant impact expected.

**Ohio Impact:** Affects all Lake Erie shoreline communities, marinas, beaches.

**Action:** Add to all encoders/decoders - PRIORITY for lakeshore stations

```
Event Code: LFW
Event Name: Lakeshore Flood Warning
Category: Warning
Relay: REQUIRED for lakeshore areas
Duration: Hours to days
Coverage: Lake Erie shoreline
```

---

### 6. EQE - Earthquake Early Warning ❌ **NATIONAL PRIORITY**

**Why Critical:** ShakeAlert system provides seconds of warning before earthquake shaking arrives.

**Definition:** Earthquake Early Warning from USGS ShakeAlert system.

**Ohio Impact:** Although less frequent, Ohio experiences earthquakes (e.g., 2011 magnitude 5.8 Virginia quake felt statewide).

**Action:** Add to all encoders/decoders - NATIONAL REQUIREMENT

```
Event Code: EQE
Event Name: Earthquake Early Warning
Category: Warning
Relay: REQUIRED
Duration: Seconds to minutes
Coverage: Varies
```

---

## Additional Missing High-Priority Codes

### Severe Weather
- **DSW** - Dust Storm Warning
- **SSW** - Storm Surge Warning
- **TSW** - Tsunami Warning
- **HUW** - Hurricane Warning
- **TRW** - Tropical Storm Warning

### Winter Weather
- **ECW** - Extreme Cold Warning
- **FZW** - Freeze Warning
- **HFW** - Hard Freeze Warning

### Summer Weather
- **EHW** - Extreme Heat Warning
- **FWW** - Fire Weather Warning

### Watches (All Missing)
- Multiple watch codes for above warnings

---

## Historical Context: Why SQW Was Added

**January 2018:** FCC approved Snow Squall Warning (SQW) event code.

**Reason:** Multiple deadly multi-vehicle pile-ups across snow belt states due to sudden snow squalls.

**Ohio Incidents:**
- I-71 Madison County (2012): 50+ vehicle pile-up
- I-77 Stark County (2015): 25+ vehicle pile-up
- I-70 multiple locations: Annual occurrences

**NWS Implementation:** National Weather Service began issuing SQW in January 2018.

**Ohio Plan:** Published December 2018 but **SQW not included**.

---

## Implementation Instructions

### For Station Engineers

**Step 1: Check Your Equipment**
```bash
# Verify current event codes in encoder
# Check manufacturer documentation for firmware version
# Confirm if new codes available
```

**Step 2: Contact Equipment Manufacturer**
- Request firmware update with all current FCC event codes
- Specifically request: SQW, ISW, WCW, LSW, LFW, EQE
- Schedule update during maintenance window

**Step 3: Program New Codes**

**For Warnings (Transmit Automatically):**
- SQW - Snow Squall Warning
- ISW - Ice Storm Warning
- WCW - Wind Chill Warning
- LSW - Lake Effect Snow Warning (lakeshore stations)
- LFW - Lakeshore Flood Warning (lakeshore stations)
- EQE - Earthquake Early Warning

**For Watches (Optional but Recommended):**
- WCA - Wind Chill Watch
- All other watch codes

**Step 4: Configure Location Codes**
- Ensure all affected county FIPS codes programmed
- Lakeshore stations: Priority on Lake Erie counties

**Step 5: Test**
```
☐ Encoder generates new codes correctly
☐ Decoder recognizes new codes
☐ Audio path functions
☐ Automatic relay triggers
☐ Proper EOM reset
```

---

### For Broadcasters/Operators

**Immediate Actions:**

1. ✅ **Notify Engineering Department** of missing codes
2. ✅ **Contact Equipment Manufacturer** for firmware update
3. ✅ **Schedule Equipment Update** during next maintenance
4. ✅ **Test New Codes** thoroughly before winter season
5. ✅ **Document Changes** in station logs
6. ✅ **Train Staff** on new event codes

**Timeline:**
- **Immediate:** Order equipment updates
- **Within 30 days:** Install and test
- **Before winter:** Complete implementation of winter codes

---

### For SECC/LECC Chairs

**Plan Update Actions:**

1. ✅ **Draft Updated Ohio EAS Plan** with all current codes
2. ✅ **Circulate for Committee Review**
3. ✅ **Submit to FCC** for approval
4. ✅ **Distribute Updated Plan** to all participants
5. ✅ **Verify Station Compliance**

---

## Snow Squall Warning Details

### What Stations Need to Know

**Issuance:**
- National Weather Service issues SQW
- Duration: Typically 30-60 minutes
- Coverage: Usually single county or portion of county
- Timing: Minutes of warning before arrival

**Characteristics:**
- Sudden onset
- Visibility drops to near zero in seconds
- Brief but intense snowfall
- Gusty winds
- Flash freeze of roads
- Rapidly accumulating snow

**Message Format:**
```
"THE NATIONAL WEATHER SERVICE HAS ISSUED A SNOW SQUALL WARNING
FOR [COUNTY] UNTIL [TIME]. A DANGEROUS SNOW SQUALL IS APPROACHING
[LOCATION]. TRAVEL IS HIGHLY DISCOURAGED. IF YOU MUST TRAVEL, USE
EXTREME CAUTION. SUDDEN WHITE OUT CONDITIONS AND ICY ROADS ARE
IMMINENT."
```

**Station Response:**
1. Alert triggers automatically from NWS
2. Interrupt programming immediately
3. Air full warning message
4. Continue monitoring until warning expires
5. Air cancellation when issued

---

## Verification Checklist

### Equipment Verification

```
☐ Equipment manufacturer contacted
☐ Firmware version confirmed
☐ Update availability confirmed
☐ Update ordered/scheduled
☐ Installation planned
☐ Testing procedures prepared
☐ Staff training scheduled
```

### Code Implementation

```
☐ SQW - Snow Squall Warning
☐ ISW - Ice Storm Warning
☐ WCW - Wind Chill Warning
☐ LSW - Lake Effect Snow Warning
☐ LFW - Lakeshore Flood Warning
☐ EQE - Earthquake Early Warning
☐ All other missing warning codes
☐ Watch codes (recommended)
☐ Statement codes (recommended)
```

### Testing

```
☐ Test message generation (all new codes)
☐ Test message reception (from LP stations)
☐ Test automatic relay function
☐ Test audio paths
☐ Test EOM reset
☐ Document test results
☐ File test reports with FCC (as required)
```

---

## Resources & Contacts

### Ohio SECC Chair
**Greg Savoldi**
Radio Station WNCI
Phone: 614-487-2485
Mobile: 614-496-2121
Email: gregsavoldi@iheartmedia.com

### Ohio EMA (24/7)
**Emergency Management Agency**
Phone: 614-889-7150
Website: https://ema.ohio.gov

### National Weather Service
**Wilmington, OH Office** (Serving most of Ohio)
Phone: 937-383-0428
Email: brandon.peloquin@noaa.gov (Warning Coordination Meteorologist)

### FCC Public Safety Bureau
Website: https://www.fcc.gov/public-safety-and-homeland-security

---

## Frequently Asked Questions

**Q: Do I have to wait for the Ohio Plan update to add these codes?**
A: No. These are FCC-approved national event codes. You can and should implement them now. The Ohio Plan update will formalize their use.

**Q: Will my old equipment support new codes?**
A: Most equipment manufactured after 2017 can support new codes with firmware updates. Contact your manufacturer.

**Q: What if I can't update before winter?**
A: At minimum, add SQW, ISW, and WCW before winter season. Plan for full update by spring 2025.

**Q: Are these codes mandatory?**
A: Warning codes should be configured for automatic relay. Watch codes are optional but strongly recommended.

**Q: How do I get firmware updates?**
A: Contact your EAS equipment manufacturer directly. Most provide updates at no charge.

**Q: What about testing?**
A: Test all new codes thoroughly. Coordinate with your LECC chair for any area-wide testing.

---

## Important Notes

⚠️ **DO NOT** relay DMO (Practice/Demo Warning) codes
⚠️ **DO** configure for automatic relay of warning codes
⚠️ **DO** train all staff on new event codes
⚠️ **DO** test before winter season
⚠️ **DO** document all changes

---

**This is not a test. This is an action alert.**

**Equipment updates required before winter 2025-2026 season.**

---

*Document prepared January 12, 2025*
*Based on Ohio EAS Plan December 2018 and current FCC event code list*
*For questions, contact your operational area LECC chair or Ohio SECC chair*
