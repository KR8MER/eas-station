# VTEC Event Linking

EAS Station™ uses the VTEC **Event Tracking Number (ETN)** to link every update
to a weather event into a single lifecycle chain.  This document explains the
data model, the ingest flow, and how the alert detail page surfaces related
updates.

For the VTEC string format itself (field definitions, action codes, phenomena
codes, etc.) see [`NWS_ALERT_PARAMETERS.md`](NWS_ALERT_PARAMETERS.md).

---

## Why VTEC-Based Linking?

NWS issues multiple CAP alerts for the same physical event:

```
NEW  → (event starts)
CON  → (hourly reissues confirming the event is ongoing)
EXT  → (valid time extended)
CAN  → (event cancelled early)
EXP  → (event expires at the originally-stated time)
```

Without VTEC, each alert looks like an independent record.  With VTEC,
every update shares an identical **event key**:

| Field             | Example  | Notes                             |
|-------------------|----------|-----------------------------------|
| `vtec_office`     | `KIWX`   | 4-letter NWS office ID            |
| `vtec_phenomenon` | `SV`     | 2-letter phenomenon code          |
| `vtec_significance` | `W`    | 1-letter significance (W/A/Y/…)   |
| `vtec_etn`        | `56`     | Event Tracking Number (1–9999)    |
| `vtec_year`       | `2026`   | Derived from end-time in VTEC string |

All five fields together form the stable key for one NWS event.

---

## Data Flow

### 1. Ingest (cap_poller.py)

```mermaid
flowchart TD
    A[NWS CAP feed polled] --> B[_insert_new_alert\nor _update_existing_alert]
    B --> C{VTEC string\nin raw_json?}
    C -- Yes --> D[extract_vtec_identity\napp_utils/vtec.py]
    D --> E[Set vtec_office\nvtec_phenomenon\nvtec_significance\nvtec_etn\nvtec_year\nvtec_action\non CAPAlert]
    E --> F[db.commit]
    C -- No --> F
```

`extract_vtec_identity()` reads the first P-VTEC string from
`raw_json.properties.parameters.VTEC[]` and returns a dict of the six
columns, or `None` if VTEC is absent or unparseable.

### 2. Database Schema

```mermaid
erDiagram
    CAPAlert {
        int id PK
        string identifier
        string vtec_office
        string vtec_phenomenon
        string vtec_significance
        int vtec_etn
        int vtec_year
        string vtec_action
    }
```

A composite index `ix_cap_alerts_vtec_event_key` covers all five key fields
for O(log n) lookups.  Individual indexes on each column support filtering
by single dimension (e.g. all alerts from `KIWX`).

Migration: `app_core/migrations/versions/20260327_add_vtec_columns_to_cap_alerts.py`

### 3. Alert Detail Page (webapp/admin/api/routes_alert_detail.py)

When a user opens an alert detail page the route queries for siblings:

```mermaid
flowchart LR
    A[User opens\nalert_detail] --> B{alert has\nvtec_office, etn, year?}
    B -- Yes --> C[CAPAlert.query\nWHERE vtec_office = X\nAND vtec_phenomenon = X\nAND vtec_significance = X\nAND vtec_etn = X\nAND vtec_year = X\nAND id != this_alert\nORDER BY sent ASC]
    C --> D[related_alerts list]
    B -- No --> E[related_alerts = empty list]
    D --> F[render_template\nalert_detail.html]
    E --> F
```

The resulting `related_alerts` list is rendered as a vertical timeline on
the detail page.

---

## Broadcast Deduplication

VTEC action codes gate automatic rebroadcast in `app_core/audio/auto_forward.py`:

```mermaid
flowchart TD
    A[auto_forward_cap_alert called] --> B{VTEC action\npresent?}
    B -- No --> G[15-min FIPS\ndedup window]
    B -- Yes --> C{action\nin SKIP_ACTIONS?}
    C -- CON / ROU --> D[Skip rebroadcast\n'continuing/routine update']
    C -- No --> E{action in\nTERMINAL_ACTIONS?}
    E -- CAN / EXP --> F[Skip rebroadcast\n'event termination']
    E -- No --> H{action == UPG?}
    H -- Yes --> I[Force rebroadcast\nbypass dedup window]
    H -- No --> G
    G --> J{duplicate\nfound?}
    J -- Yes --> K[Skip rebroadcast]
    J -- No --> L[Broadcast]
    I --> L
```

| Action set constant        | Actions      | Broadcast decision                      |
|----------------------------|--------------|-----------------------------------------|
| `VTEC_SKIP_ACTIONS`        | CON, ROU     | Suppress — already on air               |
| `VTEC_TERMINAL_ACTIONS`    | CAN, EXP     | Suppress — event is over                |
| `VTEC_BROADCAST_ACTIONS`   | NEW, EXT, EXA, EXB, UPG, COR | Eligible for broadcast |
| UPG (special case)         | UPG          | Force — bypass the 15-min FIPS window   |

All three sets are defined in `app_utils/vtec.py` and imported from there by
both `cap_poller.py` and `auto_forward.py`, keeping the logic in one place.

---

## Code Location Summary

| Responsibility                    | File                                                      |
|-----------------------------------|-----------------------------------------------------------|
| VTEC string parsing & code tables | `app_utils/vtec.py`                                       |
| VTEC columns on CAPAlert model    | `app_core/models.py`                                      |
| Alembic migration                 | `app_core/migrations/versions/20260327_add_vtec_columns_to_cap_alerts.py` |
| Ingest: extract & persist VTEC    | `poller/cap_poller.py` → `_insert_new_alert`, `_update_existing_alert` |
| Broadcast dedup gating            | `app_core/audio/auto_forward.py` → `auto_forward_cap_alert` |
| Related alerts query              | `webapp/admin/api/routes_alert_detail.py` → `alert_detail` |
| Event chain timeline (UI)         | `templates/alert_detail.html` (VTEC Event Chain block)    |

---

## Full Lifecycle Example

```mermaid
sequenceDiagram
    participant NWS
    participant Poller as cap_poller.py
    participant DB as CAPAlert table
    participant UI as Alert Detail page
    participant Audio as auto_forward.py

    NWS->>Poller: NEW SV.W #56 (KIWX)
    Poller->>DB: INSERT id=100, vtec_action=NEW, vtec_etn=56, vtec_year=2026
    Poller->>Audio: auto_forward_cap_alert(alert=100)
    Note over Audio: vtec_action=NEW → eligible\nFIPS dedup check passes\n→ BROADCAST

    NWS->>Poller: CON SV.W #56 (KIWX)
    Poller->>DB: INSERT id=101, vtec_action=CON, vtec_etn=56, vtec_year=2026
    Poller->>Audio: auto_forward_cap_alert(alert=101)
    Note over Audio: vtec_action=CON → SKIP\n(already on air)

    NWS->>Poller: EXT SV.W #56 (KIWX)
    Poller->>DB: INSERT id=102, vtec_action=EXT, vtec_etn=56, vtec_year=2026
    Poller->>Audio: auto_forward_cap_alert(alert=102)
    Note over Audio: vtec_action=EXT → eligible\nFIPS dedup passes → BROADCAST

    NWS->>Poller: EXP SV.W #56 (KIWX)
    Poller->>DB: INSERT id=103, vtec_action=EXP, vtec_etn=56, vtec_year=2026
    Poller->>Audio: auto_forward_cap_alert(alert=103)
    Note over Audio: vtec_action=EXP → SKIP\n(event ended)

    UI->>DB: SELECT WHERE vtec_etn=56 AND vtec_year=2026 AND office=KIWX…
    DB-->>UI: [id=100 NEW, id=101 CON, id=102 EXT, id=103 EXP]
    Note over UI: Timeline rendered on alert detail page
```
