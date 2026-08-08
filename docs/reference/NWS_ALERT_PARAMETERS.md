# NWS Alert Parameters Reference

This document covers two NWS-specific CAP parameters that EAS Station™ parses
and displays on the Alert Detail page: **VTEC** and **eventMotionDescription**.

Both arrive in a CAP alert's `properties.parameters` object (keyed `VTEC` and
`eventMotionDescription`) and are decoded in
`webapp/admin/api/display_data.py` → `_extract_alert_display_data()`.

---

## VTEC — Valid Time Event Code

**Official reference:** NWS Directive 10-1703, ver 9 (March 2025)
https://www.weather.gov/media/vtec/VTEC_explanation_ver9.pdf

VTEC is a structured machine-readable string that NWS appends to every
watch/warning/advisory product. It provides a canonical, unambiguous identifier
for the event that survives text reformatting and allows downstream systems
(like EAS Station™) to link successive updates (issuance → extension →
expiration) to the same event via the Event Tracking Number.

Two types exist:

| Type | Purpose |
|------|---------|
| **P-VTEC** (Primary) | All weather phenomena — the one EAS Station™ parses |
| **H-VTEC** (Hydrologic) | Flood-specific addendum; adds crest time, severity, and cause |

### P-VTEC String Format

```
/k.aaa.cccc.pp.s.####.yymmddThhnnZ-yymmddThhnnZ/
```

| Placeholder | Field |
|-------------|-------|
| `k` | Product class (1 letter) |
| `aaa` | Action (3 letters) |
| `cccc` | Issuing office (4-letter WFO ID) |
| `pp` | Phenomenon (2 letters) |
| `s` | Significance |
| `####` | Event Tracking Number (ETN) |
| `yymmddThhnnZ` (first) | Begin time |
| `yymmddThhnnZ` (second) | End time |

**Real example:** `/O.EXP.KIWX.SV.W.0056.000000T0000Z-260327T0030Z/`

Decoded:

| Field | Raw | Meaning |
|-------|-----|---------|
| Product class | `O` | Operational (live, not test) |
| Action | `EXP` | Expired |
| Office | `KIWX` | NWS Northern Indiana (Fort Wayne) |
| Phenomenon | `SV` | Severe Thunderstorm |
| Significance | `W` | Warning |
| ETN | `0056` | Event #56 for this season/office |
| Begin | `000000T0000Z` | Ongoing at issuance (all-zeros convention) |
| End | `260327T0030Z` | 2026-03-27 00:30 UTC |

---

### Field Reference

#### k — Product Class

| Code | Meaning |
|------|---------|
| `O` | Operational — a real, live product |
| `T` | Test — do not broadcast |
| `E` | Experimental |
| `X` | Experimental VTEC in an operational product |

#### aaa — Action

| Code | Meaning | Notes |
|------|---------|-------|
| `NEW` | New event | First issuance |
| `CON` | Continuing | No change from previous update |
| `EXT` | Extended in time | End time pushed later |
| `EXA` | Extended in area | Additional counties/zones added |
| `EXB` | Extended in area and time | Both |
| `UPG` | Upgraded | e.g. Watch upgraded to Warning |
| `CAN` | Cancelled | Event ended early |
| `EXP` | Expired | Event reached its scheduled end time |
| `COR` | Correction | Fixes an error in a previous product |
| `ROU` | Routine | Scheduled statement (e.g. river forecast) |

#### cccc — Office ID

The four-letter WFO (Weather Forecast Office) identifier, e.g.:

| Code | Office |
|------|--------|
| `KIWX` | NWS Northern Indiana (Fort Wayne, IN) |
| `KCLE` | NWS Cleveland, OH |
| `KIND` | NWS Indianapolis, IN |
| `KIPX` | NWS Wilmington, OH |

A full list is at https://www.weather.gov/srh/nwsoffices

#### pp — Phenomenon

Current codes from NWS Directive 10-1703 ver 9 (March 2025):

| Code | Phenomenon | Code | Phenomenon |
|------|-----------|------|-----------|
| `AF` | Ashfall | `MA` | Marine |
| `AS` | Air Stagnation | `MF` | Marine Dense Fog |
| `BH` | Beach Hazard | `MH` | Marine Ashfall |
| `BW` | Brisk Wind | `MS` | Marine Dense Smoke |
| `BZ` | Blizzard | `RB` | Small Craft for Rough Bar |
| `CF` | Coastal Flood | `RP` | Rip Current Risk |
| `CW` | Cold Weather | `SC` | Small Craft |
| `DF` | Debris Flow | `SE` | Hazardous Seas |
| `DS` | Dust Storm | `SI` | Small Craft for Winds |
| `DU` | Blowing Dust | `SM` | Dense Smoke |
| `EC` | Extreme Cold | `SQ` | Snow Squall |
| `EW` | Extreme Wind | `SR` | Storm |
| `FA` | Flood (areal) | `SS` | Storm Surge |
| `FF` | Flash Flood | `SU` | High Surf |
| `FG` | Dense Fog | `SV` | Severe Thunderstorm |
| `FL` | Flood (forecast point) | `SW` | Small Craft for Hazardous Seas |
| `FR` | Frost | `TO` | Tornado |
| `FW` | Fire Weather | `TR` | Tropical Storm |
| `FZ` | Freeze | `TS` | Tsunami |
| `GL` | Gale | `TY` | Typhoon |
| `HF` | Hurricane Force Wind | `UP` | Freezing Spray ¹ |
| `HT` | Heat | `WI` | Wind |
| `HU` | Hurricane | `WS` | Winter Storm |
| `HW` | High Wind | `WW` | Winter Weather |
| `HY` | Hydrologic | `XH` | Extreme Heat |
| `IS` | Ice Storm | `ZF` | Freezing Fog |
| `LE` | Lake-Effect Snow | `ZR` | Freezing Rain |
| `LO` | Low Water | | |
| `LS` | Lakeshore Flood | | |
| `LW` | Lake Wind | | |

¹ `UP` = "Heavy Freezing Spray" when significance is W or A; plain
"Freezing Spray" otherwise.

**Legacy codes** (removed from the current directive but retained in EAS
Station's lookup so archived alerts decode correctly):

| Code | Former Meaning | Superseded by |
|------|---------------|---------------|
| `BS` | Blowing Snow | — |
| `EH` | Excessive Heat | `XH` |
| `HI` | Inland Hurricane Wind | — |
| `HS` | Heavy Snow | — |
| `HZ` | Hard Freeze | — |
| `IP` | Sleet | — |
| `LB` | Lake-Effect Snow and Blowing Snow | — |
| `SN` | Snow | — |
| `TI` | Inland Tropical Storm Wind | — |
| `WC` | Wind Chill | — |

#### s — Significance

| Code | Meaning | Urgency level |
|------|---------|---------------|
| `W` | Warning | Highest — imminent threat |
| `A` | Watch | Conditions favorable for threat |
| `Y` | Advisory | Less serious; nuisance level |
| `S` | Statement | Informational update |
| `F` | Forecast | Scheduled forecast product |
| `O` | Outlook | Long-range / probabilistic |
| `N` | Synopsis | Area weather synopsis |

#### #### — Event Tracking Number (ETN)

A four-digit number that uniquely identifies a single event within a given
calendar year for a given office and phenomenon/significance pair. All VTEC
strings for the same event (NEW → CON → EXT → EXP) share the same ETN, making
it possible to reconstruct the full history of an event from the alert archive.

ETNs reset to 0001 on 1 January each year.

#### Time Format — `yymmddThhnnZ`

| Segment | Meaning | Example |
|---------|---------|---------|
| `yy` | 2-digit year | `26` → 2026 |
| `mm` | Month | `03` → March |
| `dd` | Day | `27` |
| `T` | Fixed separator | |
| `hh` | Hour (UTC, 00–23) | `00` |
| `nn` | Minute (00–59) | `30` |
| `Z` | UTC indicator | |

**All-zeros convention:** `000000T0000Z` means the event was already in
progress when the product was issued (common on CON, EXT, and EXP actions).
EAS Station™ displays this as "Ongoing at issuance" rather than a timestamp.

---

### H-VTEC (Hydrologic VTEC)

H-VTEC is a second VTEC string that accompanies P-VTEC on flood products. It
adds river-gauge-specific information.

```
/nwsli.s.ic.yymmddThhnnZ.yymmddThhnnZ.yymmddThhnnZ.fr/
```

| Placeholder | Field |
|-------------|-------|
| `nwsli` | NWS location identifier (river gauge) |
| `s` | Flood severity |
| `ic` | Immediate cause |
| `yymmddThhnnZ` (first) | Flood begin |
| `yymmddThhnnZ` (second) | Flood crest |
| `yymmddThhnnZ` (third) | Flood end |
| `fr` | Flood record status |

EAS Station™ does not currently parse H-VTEC strings (they only appear on river
flood products and are not used for EAS broadcast decisions), but they may be
visible in the raw VTEC parameter for Flash Flood and Flood Warnings.

---

## eventMotionDescription — Storm Motion

**Source:** NWS CAP/GeoJSON parameter, populated for severe convective products
(Severe Thunderstorm Warning, Tornado Warning, Tornado Emergency).

### Format

Parts are separated by `...`:

```
<ISO-timestamp>...storm...<direction>DEG...<speed>KT...<lat1>,<lon1> <lat2>,<lon2>...
```

**Real example:**
```
2026-03-27T00:21:00-00:00...storm...304DEG...31KT...40.56,-84.49 40.65,-84.15 40.75,-83.7
```

| Segment | Parsed value | Meaning |
|---------|-------------|---------|
| `2026-03-27T00:21:00-00:00` | timestamp | Observation time (ISO 8601) |
| `storm` | phenomenon type | Type of feature being tracked |
| `304DEG` | 304° | Direction the storm is **moving toward** (not from) |
| `31KT` | 31 knots → 35.7 mph | Storm speed |
| `40.56,-84.49 40.65,-84.15 40.75,-83.7` | track points | Past positions, oldest first |

> **Direction convention:** Like a compass bearing, 0° = north, 90° = east,
> 180° = south, 270° = west. 304° = WNW. This is the direction the storm is
> *moving toward*, not the direction it came from.

### Compass Conversion

EAS Station™ converts degrees to a 16-point compass label using:

```python
dirs = ['N','NNE','NE','ENE','E','ESE','SE','SSE',
        'S','SSW','SW','WSW','W','WNW','NW','NNW']
idx  = int((degrees + 11.25) / 22.5) % 16
```

| Degrees | Label | Degrees | Label |
|---------|-------|---------|-------|
| 0 / 360 | N | 180 | S |
| 22.5 | NNE | 202.5 | SSW |
| 45 | NE | 225 | SW |
| 67.5 | ENE | 247.5 | WSW |
| 90 | E | 270 | W |
| 112.5 | ESE | 292.5 | WNW |
| 135 | SE | 315 | NW |
| 157.5 | SSE | 337.5 | NNW |

### Map Visualization

EAS Station™ plots the track data on the Alert Coverage Map as:

- **Solid dashed orange polyline** — observed track (past positions)
- **Orange circle markers** — each track point; the most recent is larger
- **Faint dotted extension** — projected path ~30 minutes ahead, computed from
  the last known position using the reported speed and direction
- **Hollow circle** — projected position marker

The 30-minute projection uses great-circle dead reckoning:

```
dist_km   = speed_kt × 0.5 hr × 1.852 km/kt
Δlat      = (dist_km / 111.32) × cos(direction_rad)
Δlon      = (dist_km / (111.32 × cos(lat_rad))) × sin(direction_rad)
```

This is an approximation adequate for the short distances involved (~30–50 km).

---

## Code Locations

| Component | File | Function / Symbol |
|-----------|------|-------------------|
| VTEC parser | `app_utils/vtec.py` | `parse_vtec_display()` |
| VTEC action lookup | `app_utils/vtec.py` | `VTEC_ACTIONS` |
| VTEC phenomenon lookup | `app_utils/vtec.py` | `VTEC_PHENOMENA` |
| VTEC significance lookup | `app_utils/vtec.py` | `VTEC_SIGNIFICANCE` |
| VTEC program lookup | `app_utils/vtec.py` | `VTEC_PROGRAMS` |
| Storm motion parser | `webapp/admin/api/motion.py` | `_parse_event_motion()` |
| Caller (both) | `webapp/admin/api/display_data.py` | `_extract_alert_display_data()` |
| Template — VTEC display | `templates/alert_detail.html` | `{% if ipaws_data.vtec_parsed %}` block |
| Template — storm motion display | `templates/alert_detail.html` | `{% if ipaws_data.storm_motion %}` block |
| Map track rendering | `templates/alert_detail.html` | `addStormTrackToMap()` |
| Data injection to JS | `templates/alert_detail.html` | `alertData.stormMotion` |
