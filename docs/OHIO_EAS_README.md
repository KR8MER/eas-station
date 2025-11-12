# Ohio Emergency Alert System (EAS) Documentation

**Welcome to the Ohio EAS Documentation Repository**

This documentation provides comprehensive information about Ohio's Emergency Alert System, including the official state plan, complete event codes, and critical updates.

---

## 🚨 CRITICAL ALERTS

### ⚠️ Missing Event Codes Identified
**27+ FCC-approved event codes are NOT in the current Ohio EAS Plan**

**6 CRITICAL codes missing, including:**
- **SQW** - Snow Squall Warning (causes deadly highway pile-ups)
- **ISW** - Ice Storm Warning
- **WCW** - Wind Chill Warning
- **LSW** - Lake Effect Snow Warning
- **LFW** - Lakeshore Flood Warning
- **EQE** - Earthquake Early Warning

➡️ **[Read Critical Alert](./EAS_CRITICAL_ALERT.md)** ⚠️

---

## 📚 Documentation Index

### Official Plans & Documentation

| Document | Description | Status |
|----------|-------------|--------|
| **[Ohio EAS Plan PDF](./Ohio-EAS-Plan-approved-by-FCC-03-18-19.pdf)** | Official State Plan (December 2018) | ✅ Current (needs update) |
| **[Ohio EAS Documentation](./OHIO_EAS_DOCUMENTATION.md)** | Comprehensive markdown documentation | ✅ Complete |
| **[Complete Event Code Reference](./EAS_EVENT_CODES_COMPLETE.md)** | All FCC event codes with Ohio status | ✅ Complete |
| **[Critical Missing Codes Alert](./EAS_CRITICAL_ALERT.md)** | Action required notice | ⚠️ URGENT |

---

## 🎯 Quick Links

### For Broadcasters & Cable Operators

- **[Station Requirements](#station-requirements)**
- **[Event Code Quick Reference](#event-codes)**
- **[Test Schedules](#testing)**
- **[Contact Information](#contacts)**
- **[Equipment Setup Guide](#equipment)**

### For Emergency Management

- **[Notification Procedures](#notification)**
- **[Authorized Notifiers](#notifiers)**
- **[Operational Areas](#areas)**
- **[SECC Information](#secc)**

### For Engineers

- **[Equipment Configuration](#equipment)**
- **[Missing Code Implementation](#missing-codes)**
- **[Testing Procedures](#testing)**
- **[Technical Specifications](#technical)**

---

## 📖 System Overview

### What is the Ohio EAS?

The Ohio Emergency Alert System provides procedures for federal, state, and local government officials to issue emergency information and warnings to the public through broadcast and cable media.

**Coverage:** All 88 Ohio counties
**Operational Areas:** 12 regional areas
**Participants:** 400+ radio/TV stations and cable systems

### Key Facts

- **State Primary:** WNCI 97.9 FM (Columbus)
- **Alternate State Primary:** WBNS-FM 97.1 FM (Columbus)
- **National Primary Stations:** WTAM 1100 AM (Cleveland), WLW 700 AM (Cincinnati)
- **Authority:** 47 CFR Part 11 (FCC Rules)
- **Current Plan:** December 2018 (FCC approved March 18, 2019)

---

## <a name="event-codes"></a>📋 Event Codes

### Code Categories

| Category | Required Codes | Optional Codes | Missing Codes |
|----------|----------------|----------------|---------------|
| **Administrative** | 5 | 3 | 0 |
| **National Emergency** | 2 | 0 | 0 |
| **Public Safety** | 11 | 0 | 0 |
| **Severe Weather** | 3 | 15 | **14** ⚠️ |
| **Winter Weather** | 0 | 2 | **8** ⚠️ |
| **Other Weather** | 0 | 0 | **5** ⚠️ |

**Total:** 51 codes in plan, **27+ codes missing**

### Most Critical Missing Codes

1. **SQW** - Snow Squall Warning ⚠️ **IMMEDIATE NEED**
2. **ISW** - Ice Storm Warning ⚠️
3. **WCW** - Wind Chill Warning ⚠️
4. **LSW** - Lake Effect Snow Warning ⚠️
5. **LFW** - Lakeshore Flood Warning ⚠️
6. **EQE** - Earthquake Early Warning ⚠️

➡️ **[Complete Event Code List](./EAS_EVENT_CODES_COMPLETE.md)**

---

## <a name="station-requirements"></a>🎛️ Station Requirements

### Equipment

**All Stations Must Have:**
- FCC-certified EAS encoder/decoder
- Audio inputs from LP-1 and LP-2 stations
- NOAA Weather Radio input (strongly recommended)

**Local Primary (LP) Stations Also Need:**
- Telephone coupler for Notifier access
- 24-hour operation capability
- Additional monitoring for cross-area relay

### Programming Requirements

**Decoders Must Be Programmed For:**
- All required warning event codes
- County location codes within coverage area
- LP-1 and LP-2 station monitoring
- Automatic relay (if unattended)

➡️ **[Equipment Configuration Guide](./EAS_EVENT_CODES_COMPLETE.md#encoder-decoder-configuration)**

---

## <a name="testing"></a>🧪 Testing Schedule

### Required Monthly Tests (RMT)

**Conducted by Ohio EOC - 2nd Wednesday of Each Month**
(March on 1st Wednesday during Severe Weather Awareness Week)

| Month | Time | Relay Via |
|-------|------|-----------|
| January | 9:50 AM | SP/LP-1 |
| February | 3:50 AM | SP/LP-2 |
| **March*** | **9:50 AM** | **SP/LP-1** |
| April | 3:50 AM | SP/LP-1 |
| May | 9:50 AM | SP/LP-2 |
| June | 3:50 AM | SP/LP-2 |
| July | 9:50 AM | SP/LP-1 |
| August | 3:50 AM | SP/LP-1 |
| September | 9:50 AM | SP/LP-2 |
| October | 3:50 AM | SP/LP-1 |
| November | 9:50 AM | SP/LP-1 |
| December | 3:50 AM | SP/LP-2 |

*1st Wednesday during Severe Weather Awareness Week

**Test Requirements:**
- Must retransmit within 60 minutes of receipt
- Alternates between daytime/nighttime
- Tests both LP-1 and LP-2 paths
- Minimum 4 tests annually via IPAWS
- Minimum 4 tests annually via OEAS CAP network

### Required Weekly Tests (RWT)
- Conducted weekly by all stations
- Tests EAS header and EOM codes
- Per FCC requirements

---

## <a name="areas"></a>🗺️ Operational Areas

### 12 Ohio EAS Operational Areas

1. **Central** - Columbus region (Franklin & surrounding counties)
2. **Central & East Lakeshore** - Cleveland/Lake Erie
3. **East Central** - Canton/Akron region
4. **Lima** - Northwest interior
5. **North Central** - Mansfield/Marion
6. **Northwest** - Toledo region
7. **South Central** - Portsmouth/Chillicothe
8. **Southeast** - Athens/Marietta
9. **Southwest** - Cincinnati region
10. **Upper Ohio Valley** - Steubenville/Wheeling border
11. **West Central** - Dayton region
12. **Youngstown** - Northeast region

➡️ **[Operational Area Maps & Station Lists](./OHIO_EAS_DOCUMENTATION.md#operational-areas)**

---

## <a name="notification"></a>📢 Notification Procedures

### Authorized Notifiers

**Statewide Alerts:**
1. Governor of Ohio
2. Ohio Emergency Management Agency
3. Ohio State Highway Patrol
4. National Weather Service (weather only)

**Local Alerts:**
5. County EMA Directors (local area only)
6. County Sheriffs (local area only)

### Activation Process

**State Level:**
- Ohio Emergency Operations Center/Joint Dispatch Facility
- Connected to State Primary via private radio link
- Distribution via IPAWS and OEAS networks

**Local Level:**
- Contact Local Primary stations (LP-1 or LP-2)
- Direct encoder connection or IPAWS
- Coordinate multi-county through Ohio EMA

➡️ **[Complete Notification Procedures](./OHIO_EAS_DOCUMENTATION.md#notification-procedures)**

---

## <a name="contacts"></a>📞 Key Contacts

### State Emergency Communications Committee (SECC)

**Chair:**
Greg Savoldi - WNCI Columbus
Phone: 614-487-2485 | Mobile: 614-496-2121
Email: gregsavoldi@iheartmedia.com

**Vice-Chair:**
Dave Ford - Ohio Emergency Management Agency
Phone: 614-889-7154 | 24/7: 614-889-7150
Email: rdford@dps.state.oh.us

**Cable Co-Chair:**
Jonathon McGee - Ohio Cable Telecommunications Association
Phone: 614-461-4014
Email: jmcgee@octa.org

### Emergency Contacts

**Ohio EMA (24/7):** 614-889-7150
**National Weather Service (Wilmington):** 937-383-0428

➡️ **[All LECC Chairs & Vice-Chairs](./OHIO_EAS_DOCUMENTATION.md#committee-contacts)**

---

## <a name="equipment"></a>⚙️ Equipment & Technical

### Encoder/Decoder Configuration

**Critical Settings:**
- Warning codes (all required codes programmed)
- Location codes (all counties in coverage area)
- Monitoring assignments (LP-1, LP-2, NOAA)
- Automatic relay (enabled if unattended)

### Message Format

**Ohio Standard Opening:**
```
"WE INTERRUPT THIS PROGRAM TO ACTIVATE THE EMERGENCY ALERT SYSTEM"
```

**Ohio Standard Closing:**
```
"THIS CONCLUDES THIS EMERGENCY ALERT SYSTEM MESSAGE"
```

**Maximum Message Duration:** 2 minutes (including open, body, close)

➡️ **[Complete Technical Specifications](./OHIO_EAS_DOCUMENTATION.md#eas-message-format)**

---

## <a name="missing-codes"></a>⚠️ Missing Code Implementation

### Action Required

**All Ohio EAS participants must:**

1. ✅ Review equipment firmware version
2. ✅ Contact manufacturer for updates
3. ✅ Add missing warning codes (priority: SQW, ISW, WCW, LSW, LFW, EQE)
4. ✅ Test new code functionality
5. ✅ Train staff on new codes
6. ✅ Document updates

**Timeline:**
- **Immediate:** Order equipment updates
- **30 Days:** Install and test
- **Before Winter 2025:** Complete winter code implementation

➡️ **[Implementation Instructions](./EAS_CRITICAL_ALERT.md#implementation-instructions)**

---

## 📊 Statistics

### Ohio EAS by the Numbers

- **88** counties covered
- **12** operational areas
- **26** Local Primary stations
- **2** State Primary stations
- **2** National Primary stations
- **400+** participating stations and systems
- **51** event codes in current plan
- **27+** event codes missing (needs update)

---

## 🔗 External Resources

### Federal Resources
- [FCC EAS Rules (47 CFR Part 11)](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-A/part-11)
- [FCC EAS Operating Handbook](https://www.fcc.gov/public-safety-and-homeland-security/policy-and-licensing-division/alerting/eas)
- [FEMA IPAWS](https://www.fema.gov/emergency-managers/practitioners/integrated-public-alert-warning-system)

### State Resources
- [Ohio Emergency Management Agency](https://ema.ohio.gov)
- [Ohio Association of Broadcasters](https://www.oab.org)
- [Ohio Cable Telecommunications Association](https://www.octa.org)

### Weather Resources
- [National Weather Service - Wilmington OH](https://www.weather.gov/iln)
- [National Weather Service - Cleveland OH](https://www.weather.gov/cle)
- [NOAA Weather Radio Information](https://www.weather.gov/nwr)

---

## 📝 Document Status

| Document | Version | Last Updated | Status |
|----------|---------|--------------|--------|
| Official Ohio EAS Plan | Dec 2018 | Dec 2018 | ⚠️ Needs update |
| Ohio EAS Documentation | 1.0 | Jan 2025 | ✅ Current |
| Complete Event Codes | 1.0 | Jan 2025 | ✅ Current |
| Critical Alert | 1.0 | Jan 2025 | ⚠️ Action required |

---

## 🔄 Recent Updates

**January 12, 2025:**
- Complete documentation created from official PDF
- Missing event codes identified and documented
- Critical alert issued for missing codes
- Implementation guidance prepared

**December 2018:**
- Ohio EAS Plan published
- FCC submission completed

**March 18, 2019:**
- Ohio EAS Plan approved by FCC

---

## ❓ Frequently Asked Questions

**Q: Where do I find my station's monitoring assignments?**
A: Check your operational area section in the [full documentation](./OHIO_EAS_DOCUMENTATION.md) or Attachment III of the official plan.

**Q: How do I add missing event codes?**
A: Follow the [implementation instructions](./EAS_CRITICAL_ALERT.md#implementation-instructions) and contact your equipment manufacturer.

**Q: Who do I contact with questions?**
A: Contact your [operational area LECC chair](./OHIO_EAS_DOCUMENTATION.md#committee-contacts) or the state SECC chair.

**Q: When is the next RMT test?**
A: Second Wednesday of each month (see [test schedule](#testing)) - check calendar for specific dates.

**Q: Do I need FCC permission to add missing codes?**
A: No. These are FCC-approved national codes. You should implement them now. The Ohio Plan update will formalize their use.

---

## 📧 Feedback & Updates

**Report Issues:**
- Documentation errors or omissions
- Missing information
- Technical questions

**Contact:**
Ohio SECC Chair - Greg Savoldi
Email: gregsavoldi@iheartmedia.com
Phone: 614-487-2485

---

## ⚖️ Legal Notice

This documentation is derived from the official State of Ohio Emergency Alert System (EAS) Plan approved by the FCC on March 18, 2019. For official regulatory purposes, refer to the [original PDF document](./Ohio-EAS-Plan-approved-by-FCC-03-18-19.pdf).

**Authority:** 47 CFR Part 11 - Federal Communications Commission

**Disclaimer:** While every effort has been made to ensure accuracy, this documentation is provided for informational purposes. Always verify critical information with official sources.

---

**Document Repository:** `/home/user/eas-station/docs/`
**Last Updated:** January 12, 2025
**Maintained By:** EAS Station Documentation Project

---

*For the safety of Ohio residents, please ensure your EAS equipment is up-to-date and properly configured.*
