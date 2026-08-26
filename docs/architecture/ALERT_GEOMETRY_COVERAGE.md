# Alert Geometry and Coverage Calculation

This document explains how EAS Station™ resolves spatial geometry for incoming CAP
alerts and calculates coverage percentages against configured emergency-service
boundaries.

## Document Overview

**Purpose:** Describe the geometry resolution priority chain, per-type routing
rules, poll-cycle preservation, and the "Calculate Coverage" UI flow

**Audience:** Developers, system operators, and contributors working on spatial
alert processing

**Key files:**
- `webapp/admin/coverage.py` — `try_build_geometry_from_same_codes()`
- `poller/cap_poller.py` — `_update_existing_alert()`, `_set_alert_geometry()`
- `webapp/admin/intersections.py` — `/admin/calculate_single_alert/<id>` route
- `templates/alert_detail.html` — `triggerIntersectionFix()` JS function

---

## Table of Contents

1. [Geometry Resolution Priority Chain](#1-geometry-resolution-priority-chain)
2. [Alert Type Routing](#2-alert-type-routing)
3. [Poll-Cycle Geometry Preservation](#3-poll-cycle-geometry-preservation)
4. [Calculate Coverage Button Flow](#4-calculate-coverage-button-flow)
5. [End-to-End Coverage Calculation Sequence](#5-end-to-end-coverage-calculation-sequence)

---

## 1. Geometry Resolution Priority Chain

When an alert is ingested or when the admin triggers a coverage calculation,
the system resolves geometry through a strict three-level priority chain.
Polygon geometry is always preferred because it represents the real, precise
affected area.  SAME/FIPS codes are a fallback that produces a coarse
full-county union and is appropriate only for county-wide alerts that carry
no polygon.

```mermaid
flowchart TD
    START([Alert needs geometry]) --> P1

    P1{"`**Priority 1**
    Does raw_json.geometry
    have coordinates?`"}

    P1 -- Yes --> P1_PARSE[Parse with PostGIS
    ST_GeomFromGeoJSON]
    P1_PARSE --> P1_OK{Parse succeeded?}
    P1_OK -- Yes --> STORE_P1[("Store alert.geom
    from polygon")]
    STORE_P1 --> DONE_P1([✅ Geometry ready
    precise polygon area])

    P1_OK -- No --> P1_FAIL["Log debug: parse failed
    (e.g. >10 000 vertices,
    bad topology)"]
    P1_FAIL --> BLOCK_FIPS["⛔ Skip SAME codes —
    alert IS polygon-based,
    FIPS union would inflate
    coverage"]
    BLOCK_FIPS --> FAIL([❌ No geometry
    UI shows error])

    P1 -- No --> P2

    P2{"`**Priority 2**
    Is alert.geom already
    stored in DB?`"}
    P2 -- Yes --> DONE_P2([✅ Geometry ready
    previously stored])
    P2 -- No --> P3

    P3{"`**Priority 3**
    SAME / FIPS codes
    Is us_county_boundaries
    table populated?`"}
    P3 -- No --> FAIL2([❌ No geometry
    county data not loaded])
    P3 -- Yes --> P3_CODES{SAME codes
    present in
    raw_json?}
    P3_CODES -- No --> FAIL3([❌ No geometry
    no SAME codes found])
    P3_CODES -- Yes --> BUILD["ST_Union of matching
    county boundary geometries
    (county FIPS + statewide codes)"]
    BUILD --> STORE_P3[("Store alert.geom
    from county union")]
    STORE_P3 --> DONE_P3([✅ Geometry ready
    county-union area])
```

> **Why Priority 1 failures block Priority 3:**
> If `raw_json['geometry']` has coordinates, the NWS issued a specific polygon
> for the event (e.g. a thunderstorm warning covering part of one county).
> Falling back to the full-county union from FIPS codes would report near-100%
> county coverage for an alert that only clips one corner.  The correct behaviour
> is to surface the parse failure so an operator can investigate.

---

## 2. Alert Type Routing

Different NWS product types reliably contain (or lack) polygon geometry.
The table below shows which priority path is normally taken.

| Alert type | Geometry in feed? | Priority taken | Notes |
|---|---|---|---|
| Tornado Warning | ✅ Polygon | **1** | Precise warned area polygon |
| Severe Thunderstorm Warning | ✅ Polygon | **1** | Storm-cell tracking polygon |
| Flash Flood Warning | ✅ Polygon | **1** | Basin/watershed polygon |
| Tornado Watch | ❌ SAME codes only | **3** | Box covers multiple counties |
| Severe Thunderstorm Watch | ❌ SAME codes only | **3** | Box covers multiple counties |
| High Wind Warning | ❌ SAME codes only | **3** | County-wide, no polygon |
| Winter Storm Warning | ❌ SAME codes only | **3** | County-wide, no polygon |
| Blizzard Warning | ❌ SAME codes only | **3** | County-wide, no polygon |
| Flood Watch | ❌ SAME codes only | **3** | County-wide or multi-county |
| Winter Weather Advisory | ❌ SAME codes only | **3** | County-wide, no polygon |
| Special Weather Statement | Sometimes | **1** or **3** | Depends on NWS office |
| Air Quality Alert | ❌ SAME codes only | **3** | County-wide |
| Extreme Heat Warning | ❌ SAME codes only | **3** | County-wide |

The flowchart below summarises the decision the system makes at ingest time:

```mermaid
flowchart LR
    FEED([CAP alert
    arrives]) --> HAS_GEOM{Polygon in
    raw_json?}

    HAS_GEOM -- Yes --> WARN_TYPE{Event type}
    WARN_TYPE -- "Warning / Statement
    with narrow polygon" --> P1_PATH["Priority 1
    Precise polygon area"]
    WARN_TYPE -- "Watch / Advisory
    with polygon" --> P1_PATH

    HAS_GEOM -- No --> FIPS_TYPE{Event type}
    FIPS_TYPE -- "County-wide Warning
    (High Wind, Winter Storm…)" --> P3_PATH["Priority 3
    SAME codes → county union"]
    FIPS_TYPE -- "Watch / Advisory" --> P3_PATH
    FIPS_TYPE -- "Statement (no codes)" --> FAIL_PATH["No geometry
    Manual review"]

    P1_PATH --> INTERSECT[Calculate boundary
    intersections]
    P3_PATH --> INTERSECT
    FAIL_PATH --> SKIP([Coverage pending])
    INTERSECT --> COVERAGE[Display coverage %
    on alert detail page]
```

---

## 3. Poll-Cycle Geometry Preservation

The CAP poller fetches fresh alert data every few minutes.  For alerts that
carry no polygon (watches, advisories, county-wide warnings), every update
returns `geometry_data = None`.  Before the fix this wiped any SAME-derived
geometry on each poll, causing the admin dashboard to show "Coverage Pending"
again seconds after a successful calculation.

The fix: `_update_existing_alert` only calls `_set_alert_geometry` when the
feed provides actual polygon data.  When `geometry_data is None`, existing
geometry — whether polygon-derived or SAME-derived — is left untouched.

```mermaid
flowchart TD
    POLL([Poller: update received
    for existing alert]) --> HAS_NEW{"`geometry_data
    is not None?`"}

    HAS_NEW -- Yes --> REPLACE["_set_alert_geometry()
    Validate + store new polygon
    May replace stale SAME-derived
    geometry with accurate polygon"]

    HAS_NEW -- No --> PRESERVE["Leave alert.geom unchanged
    Preserves SAME-derived geom
    through polygon-less updates"]

    REPLACE --> COMPARE{ST_Equals
    old ≠ new?}
    PRESERVE --> NEED_CALC{Intersections
    already exist?}

    COMPARE -- Changed --> RECALC[Re-run boundary
    intersections]
    COMPARE -- Unchanged --> NEED_CALC

    NEED_CALC -- None --> RECALC
    NEED_CALC -- Exist --> SKIP([Skip — coverage
    already current])

    RECALC --> COMMIT([Commit intersections
    Coverage display updated])
```

---

## 4. Calculate Coverage Button Flow

The **Calculate Coverage** / **Calculate Affected Boundaries** button on the
Alert Detail page calls `POST /admin/calculate_single_alert/<id>`.  It uses
the same three-priority geometry chain, then runs boundary intersection
calculations and reloads the page when done.

```mermaid
flowchart TD
    BTN([User clicks
    Calculate Coverage button]) --> DISABLE["Disable all
    .coverage-calc-btn elements
    Show spinners"]
    DISABLE --> TOAST1["🟦 Info toast:
    'Calculating coverage
    boundaries, please wait…'"]
    TOAST1 --> FETCH["POST /admin/calculate_single_alert/<id>"]

    FETCH --> GEOM_BUILD["try_build_geometry_from_same_codes()
    Priority 1 → 2 → 3"]

    GEOM_BUILD --> HAS_GEOM{alert.geom
    set?}

    HAS_GEOM -- No --> ERR400["HTTP 400
    JSON error message"]
    ERR400 --> TOAST_ERR["🔴 Error toast:
    'Alert has no geometry data…'"]
    TOAST_ERR --> REENABLE["Re-enable buttons
    User can retry"]

    HAS_GEOM -- Yes --> DEL["Delete existing
    Intersection records"]
    DEL --> ITER["For each Boundary in DB:
    ST_Intersects + ST_Area"]
    ITER --> SAVE["Insert new
    Intersection rows"]
    SAVE --> RESP200["HTTP 200
    intersections_created,
    boundaries_tested,
    errors[]"]

    RESP200 --> COUNT{intersections
    created > 0?}
    COUNT -- Yes --> TOAST_OK["🟢 Success toast:
    'Found N intersections
    (tested M). Refreshing…'"]
    COUNT -- No --> TOAST_WARN["🟡 Warning toast:
    'No intersections found
    (tested M). Refreshing…'"]

    TOAST_OK --> RELOAD["window.location.reload()
    after 2.5 s"]
    TOAST_WARN --> RELOAD
    RELOAD --> DONE([Page reloaded
    Coverage data displayed])

    ITER --> ERR_BOUND["boundary_error?
    Append to errors[]"]
    ERR_BOUND --> ITER
```

---

## 5. End-to-End Coverage Calculation Sequence

This sequence diagram shows all participants from the browser through the
Flask app, PostGIS, and back, for the common case of a county-wide alert
(e.g. High Wind Warning) with no polygon geometry.

```mermaid
sequenceDiagram
    participant Browser as Browser<br>Alert Detail Page
    participant Flask as Flask<br>intersections.py
    participant Coverage as coverage.py<br>try_build_geometry_from_same_codes()
    participant DB as PostgreSQL<br>+ PostGIS
    participant Boundaries as Boundary table<br>(configured service areas)

    Note over Browser: User clicks "Calculate Affected Boundaries"

    Browser->>Browser: Disable buttons, show spinners
    Browser->>Browser: Show info toast

    Browser->>Flask: POST /admin/calculate_single_alert/<id>

    Flask->>Coverage: try_build_geometry_from_same_codes(alert_id)

    Coverage->>DB: SELECT raw_json FROM cap_alerts WHERE id=?
    DB-->>Coverage: alert record (raw_json has no geometry)

    Note over Coverage: Priority 1 — no polygon in raw_json, skip

    Note over Coverage: Priority 2 — alert.geom is None, skip

    Note over Coverage: Priority 3 — use SAME/FIPS codes

    Coverage->>DB: SELECT COUNT(*) FROM us_county_boundaries
    DB-->>Coverage: N rows (table ready)

    Coverage->>DB: SELECT ST_Union(geom) FROM us_county_boundaries<br>WHERE geoid = ANY(['39137', '39125', …])
    DB-->>Coverage: MultiPolygon geometry

    Coverage->>DB: UPDATE cap_alerts SET geom = ? WHERE id = ?
    DB-->>Coverage: OK

    Coverage-->>Flask: True (geometry stored)

    Flask->>DB: DELETE FROM intersections WHERE cap_alert_id = ?
    DB-->>Flask: N rows deleted

    Flask->>Boundaries: SELECT * FROM boundaries

    loop For each configured boundary
        Flask->>DB: ST_Intersects(alert.geom, boundary.geom)
        DB-->>Flask: true / false

        alt Intersects
            Flask->>DB: ST_Area(ST_Intersection(alert.geom, boundary.geom))
            DB-->>Flask: area_sqm
            Flask->>DB: INSERT INTO intersections
        end
    end

    Flask->>DB: COMMIT
    Flask-->>Browser: 200 {"intersections_created": N, "boundaries_tested": M}

    Browser->>Browser: Show success toast with counts
    Browser->>Browser: Reload page after 2.5 s

    Note over Browser: Coverage percentages now displayed
```

---

## Related Documentation

- **[Data Flow Sequences](DATA_FLOW_SEQUENCES.md)** — Complete CAP alert ingest pipeline
- **[System Architecture](SYSTEM_ARCHITECTURE.md)** — High-level component overview
- **[`webapp/admin/coverage.py`](https://github.com/KR8MER/eas-station/blob/main/webapp/admin/coverage.py)** — Geometry resolution implementation
- **[`poller/cap_poller.py`](https://github.com/KR8MER/eas-station/blob/main/poller/cap_poller.py)** — Poll-cycle geometry preservation

---

**Last Updated:** 2026-03-27
