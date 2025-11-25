# Complete EAS Event Code Reference

**Purpose:** Master reference for encoding/decoding all EAS event codes
**Last Updated:** 2025-01-12
**Status:** Updated to include all current FCC event codes

---

## Critical Information

### Ohio Plan Status
- ✅ **Current Ohio Plan:** December 2018
- ❌ **Missing Codes:** 27+ event codes not in current plan
- ⚠️ **Action Required:** Update encoders/decoders with complete list

### Priority Codes for Ohio

**CRITICAL for Ohio Operations:**
1. **SQW** - Snow Squall Warning (NOT IN CURRENT PLAN)
2. **ISW** - Ice Storm Warning (NOT IN CURRENT PLAN)
3. **WCW** - Wind Chill Warning (NOT IN CURRENT PLAN)
4. **LSW** - Lake Effect Snow Warning (NOT IN CURRENT PLAN)
5. **LFW** - Lakeshore Flood Warning (NOT IN CURRENT PLAN)
6. **EQE** - Earthquake Early Warning (NOT IN CURRENT PLAN)

---

## Event Code Categories

### Administrative & Test Codes
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **ADR** | Administrative Message | ✅ YES | Optional | Administrative notifications |
| **DMO** | Practice/Demo Warning | ✅ YES | Optional | Practice activations (DO NOT RELAY) |
| **EAT** | Emergency Action Termination | ✅ YES | **REQUIRED** | Terminates EAN |
| **NIC** | National Information Center | ✅ YES | **REQUIRED** | Emergency information available |
| **NMN** | Network Message Notification | ✅ YES | Optional | Network operations |
| **NPT** | National Periodic Test | ✅ YES | **REQUIRED** | National EAS test |
| **RMT** | Required Monthly Test | ✅ YES | **REQUIRED** | Monthly system test |
| **RWT** | Required Weekly Test | ✅ YES | **REQUIRED** | Weekly system test |

---

### National Emergency Codes
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **EAN** | Emergency Action Notification | ✅ YES | **REQUIRED** | Presidential alert - national emergency |
| **EAT** | Emergency Action Termination | ✅ YES | **REQUIRED** | Ends national emergency |

---

### Public Safety Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **BLU** | Blue Alert | ✅ YES | Optional | Suspect who killed/seriously injured law enforcement |
| **CAE** | Child Abduction Emergency | ✅ YES | **REQUIRED** | AMBER Alert - child abduction |
| **CDW** | Civil Danger Warning | ✅ YES | **REQUIRED** | Curfew, air attacks, explosions, other civil dangers |
| **CEM** | Civil Emergency Message | ✅ YES | **REQUIRED** | Emergency instructions to public |
| **FRW** | Fire Warning | ✅ YES | **REQUIRED** | Uncontrolled fire threatening populated areas |
| **HMW** | Hazardous Materials Warning | ✅ YES | **REQUIRED** | Chemical spill, toxic gas release |
| **LEW** | Law Enforcement Warning | ✅ YES | **REQUIRED** | Prison break, police emergency |
| **NUW** | Nuclear Power Plant Warning | ✅ YES | **REQUIRED** | Nuclear facility incident |
| **RHW** | Radiological Hazard Warning | ✅ YES | **REQUIRED** | Radioactive material release |
| **SPW** | Shelter In Place Warning | ✅ YES | **REQUIRED** | Take shelter indoors immediately |
| **TOE** | 9-1-1 Telephone Outage Emergency | ✅ YES | **REQUIRED** | 9-1-1 system failure |

---

### Severe Weather - Immediate Danger
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **BZW** | Blizzard Warning | ✅ YES | Optional | Severe winter storm with sustained winds ≥35 mph |
| **DSW** | Dust Storm Warning | ❌ **MISSING** | **ADD** | Visibility near zero due to dust |
| **EWW** | Extreme Wind Warning | ✅ YES | Optional | Sustained winds ≥115 mph from severe thunderstorms |
| **FFW** | Flash Flood Warning | ✅ YES | Optional | Flash flooding occurring or imminent |
| **HUW** | Hurricane Warning | ❌ **MISSING** | **ADD** | Hurricane conditions expected within 36 hours |
| **HWW** | High Wind Warning | ✅ YES | Optional | Sustained winds 40+ mph or gusts 58+ mph |
| **ISW** | Ice Storm Warning | ❌ **MISSING** | **ADD** | ⚠️ **CRITICAL FOR OHIO** - Significant ice accumulation |
| **LSW** | Lake Effect Snow Warning | ❌ **MISSING** | **ADD** | ⚠️ **CRITICAL FOR OHIO** - Heavy lake effect snow |
| **FLW** | Flood Warning | ✅ YES | Optional | River/stream flooding |
| **SQW** | Snow Squall Warning | ❌ **MISSING** | **ADD** | ⚠️ **CRITICAL FOR OHIO** - Sudden heavy snow, zero visibility |
| **SSW** | Storm Surge Warning | ❌ **MISSING** | **ADD** | Life-threatening storm surge |
| **SVR** | Severe Thunderstorm Warning | ✅ YES | Optional | Severe thunderstorm with wind ≥58 mph or hail ≥1" |
| **TOR** | Tornado Warning | ✅ YES | **RECOMMENDED** | Tornado sighted or indicated on radar |
| **TRW** | Tropical Storm Warning | ❌ **MISSING** | **ADD** | Tropical storm conditions expected within 36 hours |
| **TSW** | Tsunami Warning | ❌ **MISSING** | **ADD** | Tsunami occurring or imminent |

---

### Severe Weather - Watch/Advisory
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **AVA** | Avalanche Watch | ❌ **MISSING** | **ADD** | Conditions favorable for avalanches |
| **FFA** | Flash Flood Watch | ✅ YES | Optional | Flash flooding possible |
| **FLA** | Flood Watch | ✅ YES | Optional | Flooding possible |
| **HUA** | Hurricane Watch | ❌ **MISSING** | **ADD** | Hurricane conditions possible within 48 hours |
| **HWA** | High Wind Watch | ✅ YES | Optional | High winds possible |
| **SVA** | Severe Thunderstorm Watch | ✅ YES | Optional | Conditions favorable for severe thunderstorms |
| **SSA** | Storm Surge Watch | ❌ **MISSING** | **ADD** | Storm surge possible |
| **TOA** | Tornado Watch | ✅ YES | Optional | Conditions favorable for tornadoes |
| **TRA** | Tropical Storm Watch | ❌ **MISSING** | **ADD** | Tropical storm conditions possible within 48 hours |
| **TSA** | Tsunami Watch | ❌ **MISSING** | **ADD** | Tsunami possible |
| **WCA** | Wind Chill Watch | ❌ **MISSING** | **ADD** | Dangerous wind chills possible |
| **WSA** | Winter Storm Watch | ✅ YES | Optional | Significant winter storm possible |

---

### Immediate Action Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **AVW** | Avalanche Warning | ❌ **MISSING** | **ADD** | Avalanche occurring or imminent |
| **EQW** | Earthquake Warning | ✅ YES | **REQUIRED** | Earthquake occurring or imminent |
| **EQE** | Earthquake Early Warning | ❌ **MISSING** | **ADD** | ⚠️ **CRITICAL** - ShakeAlert system warning |
| **EVI** | Evacuation Immediate | ✅ YES | **REQUIRED** | Leave area immediately |
| **VOW** | Volcano Warning | ❌ **MISSING** | **ADD** | Volcanic eruption imminent or occurring |
| **WCW** | Wind Chill Warning | ❌ **MISSING** | **ADD** | ⚠️ **CRITICAL FOR OHIO** - Dangerous wind chills |
| **WSW** | Winter Storm Warning | ✅ YES | Optional | Major winter storm occurring or imminent |

---

### Cold Weather Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **BZW** | Blizzard Warning | ✅ YES | Optional | Severe winter storm |
| **ECA** | Extreme Cold Watch | ❌ **MISSING** | **ADD** | Extreme cold possible |
| **ECW** | Extreme Cold Warning | ❌ **MISSING** | **ADD** | Extreme cold occurring |
| **FZA** | Freeze Watch | ❌ **MISSING** | **ADD** | Freezing temperatures possible |
| **FZW** | Freeze Warning | ❌ **MISSING** | **ADD** | Freezing temperatures occurring |
| **HFA** | Hard Freeze Watch | ❌ **MISSING** | **ADD** | Hard freeze possible |
| **HFW** | Hard Freeze Warning | ❌ **MISSING** | **ADD** | Hard freeze occurring |
| **ISW** | Ice Storm Warning | ❌ **MISSING** | **ADD** | Significant ice accumulation |
| **LSW** | Lake Effect Snow Warning | ❌ **MISSING** | **ADD** | ⚠️ Heavy lake effect snow |
| **SQW** | Snow Squall Warning | ❌ **MISSING** | **ADD** | ⚠️ Sudden heavy snow squall |
| **WCA** | Wind Chill Watch | ❌ **MISSING** | **ADD** | Dangerous wind chills possible |
| **WCW** | Wind Chill Warning | ❌ **MISSING** | **ADD** | ⚠️ Dangerous wind chills occurring |
| **WSA** | Winter Storm Watch | ✅ YES | Optional | Winter storm possible |
| **WSW** | Winter Storm Warning | ✅ YES | Optional | Winter storm occurring |

---

### Heat Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **EHA** | Extreme Heat Watch | ❌ **MISSING** | **ADD** | Extreme heat possible |
| **EHW** | Extreme Heat Warning | ❌ **MISSING** | **ADD** | Extreme heat occurring |
| **HTA** | Heat Advisory | ❌ **MISSING** | **ADD** | Hot temperatures with humidity |

---

### Fire Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **EFD** | Extreme Fire Danger | ❌ **MISSING** | **ADD** | Critical fire weather conditions |
| **FRW** | Fire Warning | ✅ YES | **REQUIRED** | Uncontrolled fire threatening areas |
| **FWW** | Fire Weather Warning | ❌ **MISSING** | **ADD** | Critical fire weather conditions |

---

### Coastal/Marine Warnings
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **CFA** | Coastal Flood Watch | ❌ **MISSING** | **ADD** | Coastal flooding possible |
| **CFS** | Coastal Flood Statement | ❌ **MISSING** | **ADD** | Coastal flood information |
| **CFW** | Coastal Flood Warning | ❌ **MISSING** | **ADD** | Coastal flooding occurring |
| **HLS** | Hurricane Statement | ❌ **MISSING** | **ADD** | Hurricane information update |
| **HUA** | Hurricane Watch | ❌ **MISSING** | **ADD** | Hurricane possible |
| **HUW** | Hurricane Warning | ❌ **MISSING** | **ADD** | Hurricane imminent |
| **LFA** | Lakeshore Flood Watch | ❌ **MISSING** | **ADD** | Lakeshore flooding possible |
| **LFS** | Lakeshore Flood Statement | ❌ **MISSING** | **ADD** | Lakeshore flood information |
| **LFW** | Lakeshore Flood Warning | ❌ **MISSING** | **ADD** | ⚠️ **OHIO LAKE ERIE** - Lakeshore flooding |
| **SNW** | Special Marine Warning | ✅ YES | Optional | Waterspout or severe storm over water |
| **SSA** | Storm Surge Watch | ❌ **MISSING** | **ADD** | Storm surge possible |
| **SSW** | Storm Surge Warning | ❌ **MISSING** | **ADD** | Storm surge occurring |
| **TRA** | Tropical Storm Watch | ❌ **MISSING** | **ADD** | Tropical storm possible |
| **TRW** | Tropical Storm Warning | ❌ **MISSING** | **ADD** | Tropical storm imminent |
| **TSA** | Tsunami Watch | ❌ **MISSING** | **ADD** | Tsunami possible |
| **TSW** | Tsunami Warning | ❌ **MISSING** | **ADD** | Tsunami occurring |

---

### Weather Statements
| Code | Event Name | In Ohio Plan | Transmit | Description |
|------|------------|--------------|----------|-------------|
| **CFS** | Coastal Flood Statement | ❌ **MISSING** | **ADD** | Coastal flood follow-up |
| **FFS** | Flash Flood Statement | ✅ YES | Optional | Flash flood follow-up |
| **FLS** | Flood Statement | ✅ YES | Optional | Flood follow-up |
| **HLS** | Hurricane Statement | ❌ **MISSING** | **ADD** | Hurricane follow-up |
| **LFS** | Lakeshore Flood Statement | ❌ **MISSING** | **ADD** | Lakeshore flood follow-up |
| **SPS** | Special Weather Statement | ✅ YES | Optional | Significant weather information |
| **SVS** | Severe Weather Statement | ✅ YES | Optional | Severe weather follow-up |

---

## Implementation Guide

### Phase 1: Critical Updates (IMMEDIATE)

**Add these codes to all encoders/decoders NOW:**

```
Priority 1 - Weather Safety (Ohio-Critical):
SQW - Snow Squall Warning
ISW - Ice Storm Warning
WCW - Wind Chill Warning
LSW - Lake Effect Snow Warning
LFW - Lakeshore Flood Warning

Priority 1 - National Critical:
EQE - Earthquake Early Warning

Priority 2 - Severe Weather:
DSW - Dust Storm Warning
SSW - Storm Surge Warning
TSW - Tsunami Warning
HUW - Hurricane Warning
TRW - Tropical Storm Warning
```

### Phase 2: Complete Weather Coverage

**Add all weather watches and warnings:**

```
Cold Weather Complete:
ECA, ECW - Extreme Cold Watch/Warning
FZA, FZW - Freeze Watch/Warning
HFA, HFW - Hard Freeze Watch/Warning
WCA - Wind Chill Watch

Hot Weather Complete:
EHA, EHW - Extreme Heat Watch/Warning
HTA - Heat Advisory

Tropical Complete:
HUA, HLS - Hurricane Watch/Statement
TRA - Tropical Storm Watch
SSA - Storm Surge Watch
TSA - Tsunami Watch

Winter Complete:
AVA, AVW - Avalanche Watch/Warning
```

### Phase 3: Complete Coverage

**Add remaining codes:**

```
Coastal/Marine:
CFA, CFS, CFW - Coastal Flood Watch/Statement/Warning
LFA, LFS - Lakeshore Flood Watch/Statement

Fire:
EFD - Extreme Fire Danger
FWW - Fire Weather Warning

Other:
VOW - Volcano Warning
```

---

## Encoder/Decoder Configuration

### Required Settings

**All Ohio Stations Must Configure:**

1. **Warning Codes** (Required transmission)
   - All codes marked **REQUIRED** in tables above
   - Minimum: EAN, EAT, CAE, CDW, CEM, EQW, EVI, FRW, FFW, HMW, LEW, NIC, NPT, TOE, NUW, RHW, SPW, TOR, RMT, RWT

2. **Location Codes** (FIPS codes)
   - All Ohio county codes within coverage area
   - Adjacent state counties if coverage extends

3. **Monitoring Sources**
   - LP-1 station for operational area
   - LP-2 station for operational area
   - NOAA Weather Radio (recommended)
   - LP-3 if signal reception requires

4. **Message Duration**
   - Maximum 2 minutes for complete message
   - Includes opening, body, and closing

5. **Automatic Relay**
   - Enabled if station unattended
   - Within 15 minutes of valid alert receipt

### Ohio-Specific Message Format

**Opening:**
```
"WE INTERRUPT THIS PROGRAM TO ACTIVATE THE EMERGENCY ALERT SYSTEM"
```

**Closing:**
```
"THIS CONCLUDES THIS EMERGENCY ALERT SYSTEM MESSAGE"
```

---

## Testing Requirements

### Equipment Testing

**After adding new codes, test:**

1. ✅ Encoder can generate all new event codes
2. ✅ Decoder recognizes all new event codes
3. ✅ Audio paths function for all codes
4. ✅ Automatic relay works for required codes
5. ✅ Message formatting correct
6. ✅ End-of-message properly resets system

### Code Verification Checklist

```
☐ SQW - Snow Squall Warning (CRITICAL)
☐ ISW - Ice Storm Warning (CRITICAL)
☐ WCW - Wind Chill Warning (CRITICAL)
☐ LSW - Lake Effect Snow Warning (CRITICAL)
☐ LFW - Lakeshore Flood Warning (CRITICAL)
☐ EQE - Earthquake Early Warning (CRITICAL)
☐ DSW - Dust Storm Warning
☐ SSW - Storm Surge Warning
☐ TSW - Tsunami Warning
☐ HUW - Hurricane Warning
☐ TRW - Tropical Storm Warning
☐ AVW - Avalanche Warning
☐ CFW - Coastal Flood Warning
☐ ECW - Extreme Cold Warning
☐ EHW - Extreme Heat Warning
☐ FWW - Fire Weather Warning
☐ FZW - Freeze Warning
☐ HFW - Hard Freeze Warning
☐ HTA - Heat Advisory
☐ HLS - Hurricane Statement
☐ VOW - Volcano Warning
☐ All watch codes (see tables above)
☐ All statement codes (see tables above)
```

---

## Quick Reference Summary

### Total Event Codes

- **FCC Approved:** 78+ event codes
- **Ohio Plan (2018):** 51 event codes
- **Missing from Ohio Plan:** 27+ codes
- **Critical Missing:** 6 codes (SQW, ISW, WCW, LSW, LFW, EQE)

### Transmission Requirements

- **Must Transmit:** 19 warning codes
- **Should Transmit:** Weather codes relevant to Ohio
- **Optional:** Administrative and informational codes
- **Never Relay:** DMO (Practice/Demo Warning)

### Ohio Priority Event Codes

**Top 10 for Ohio Operations:**
1. TOR - Tornado Warning
2. SQW - Snow Squall Warning ⚠️ ADD
3. FFW - Flash Flood Warning
4. SVR - Severe Thunderstorm Warning
5. ISW - Ice Storm Warning ⚠️ ADD
6. WCW - Wind Chill Warning ⚠️ ADD
7. EVI - Evacuation Immediate
8. SPW - Shelter In Place
9. HMW - Hazardous Materials Warning
10. LSW - Lake Effect Snow Warning ⚠️ ADD

---

## Resources

### FCC References
- **47 CFR § 11.31** - Event codes
- **FCC EAS Operating Handbook** - Complete event code list
- **FCC Public Notices** - Event code updates

### Ohio Resources
- **Ohio EMA:** 614-889-7150 (24/7)
- **SECC Chair:** Greg Savoldi - gregsavoldi@iheartmedia.com
- **State EAS Plan:** December 2018 (requires update)

### Equipment Manufacturers
Contact your EAS equipment manufacturer for:
- Firmware updates with new event codes
- Configuration assistance
- Testing procedures

---

## Document Information

**Created:** 2025-01-12
**Purpose:** Complete event code reference for encoder/decoder programming
**Status:** ⚠️ Includes codes NOT in current Ohio Plan
**Action Required:** Update all equipment with missing codes

**Important:** This document includes event codes not yet approved in the Ohio State EAS Plan. Coordinate with SECC before implementing non-approved codes for official use.

---

*For equipment programming, testing, or questions about event code implementation, contact your operational area LECC chair or the Ohio SECC.*
