# EAS Station System Architecture

## Document Overview

This document provides comprehensive architectural diagrams and flowcharts for the entire EAS Station system, covering all major components, data flows, and operational workflows. It serves as a visual reference for understanding how the system operates from end to end.

**Related Documents:**
- [Data Flow Sequences](DATA_FLOW_SEQUENCES) - Detailed sequence diagrams showing data processing paths ⭐ NEW
- [Theory of Operation](THEORY_OF_OPERATION) - Conceptual overview and protocol details
- [Audio Ingest Documentation](../audio) - Audio ingest system specifics
- [Help Guide](../guides/HELP) - Operational procedures

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Core Components](#core-components)
3. [Alert Processing Pipeline](#alert-processing-pipeline)
4. [Audio Ingest System](#audio-ingest-system)
5. [Broadcast Workflow](#broadcast-workflow)
6. [Verification System](#verification-system)
7. [Data Flow Diagrams](#data-flow-diagrams)
8. [Component Interactions](#component-interactions)
9. [Deployment Architecture](#deployment-architecture)
10. [Professional Diagrams](#professional-diagrams)

---

## System Overview

### High-Level Architecture

EAS Station uses a **separated service architecture** where hardware access is isolated into dedicated containers for reliability and security:

```mermaid
graph TB
    subgraph "External Sources"
        NOAA[NOAA Weather Service<br>CAP Feeds]
        IPAWS[FEMA IPAWS<br>CAP Feeds]
        RF[RF Signals<br>162 MHz NOAA WX]
    end

    subgraph "EAS Station Services"
        subgraph "Application Layer"
            APP[app<br>Flask Web UI<br>Port 5000]
            NOAA_POLL[noaa-poller<br>CAP Polling]
            IPAWS_POLL[ipaws-poller<br>CAP Polling]
        end

        subgraph "Hardware Services"
            SDR_SVC[sdr-service<br>SDR + Audio<br>USB Access]
            HW_SVC[hardware-service<br>GPIO/OLED/VFD<br>Port 5001]
        end

        subgraph "Infrastructure"
            REDIS[(Redis<br>Cache + IPC)]
            DB[(PostgreSQL 17<br>+ PostGIS 3.4)]
            ICECAST[Icecast<br>Audio Streaming]
            NGINX[nginx<br>Reverse Proxy<br>HTTPS]
        end
    end

    subgraph "Physical Hardware"
        SDR_DEV[SDR Receivers<br>RTL-SDR/Airspy]
        GPIO[GPIO Pins<br>Relay Control]
        OLED[OLED Display<br>SSD1306]
        LED[LED Signs<br>Alpha Protocol]
        VFD[VFD Display<br>Noritake]
    end

    subgraph "Outputs"
        TX[FM Transmitter]
        BROWSER[Web Browser]
        STREAM[Audio Streams]
    end

    %% Data flows
    NOAA --> NOAA_POLL
    IPAWS --> IPAWS_POLL
    NOAA_POLL --> DB
    IPAWS_POLL --> DB
    RF --> SDR_DEV --> SDR_SVC
    
    APP --> DB
    APP --> REDIS
    SDR_SVC --> REDIS
    SDR_SVC --> ICECAST
    HW_SVC --> REDIS
    
    SDR_SVC --> SDR_DEV
    HW_SVC --> GPIO --> TX
    HW_SVC --> OLED
    HW_SVC --> LED
    HW_SVC --> VFD
    
    NGINX --> APP
    BROWSER --> NGINX
    ICECAST --> STREAM

    style APP fill:#d4edda
    style SDR_SVC fill:#e1f5ff
    style HW_SVC fill:#fff3e0
    style DB fill:#fff3cd
    style REDIS fill:#f8d7da
```

### Service Responsibilities

| Service | Hardware Access | Purpose | Config Source |
|---------|----------------|---------|---------------|
| **app** | None | Web UI, API, configuration | `/app-config/.env` |
| **noaa-poller** | None | NOAA CAP XML polling | `/app-config/.env` |
| **ipaws-poller** | None | FEMA IPAWS polling | `/app-config/.env` |
| **sdr-service** | USB (`/dev/bus/usb`) | SDR capture, audio processing, SAME decoding | `/app-config/.env` |
| **hardware-service** | GPIO, I2C | Relay control, displays (OLED/VFD/LED) | `/app-config/.env` |
| **nginx** | None | HTTPS termination, reverse proxy | Environment vars |
| **redis** | None | Cache, inter-service communication | Volume-based |
| **icecast** | None | Audio streaming | `/app-config/.env` |

### System Layers

| Layer | Purpose | Key Components |
|-------|---------|----------------|
| **External Sources** | Alert origins and RF monitoring | NOAA, IPAWS, SDR receivers |
| **Ingestion** | Fetch and validate CAP alerts | Pollers, validators |
| **Data** | Persistent storage and spatial processing | PostgreSQL, PostGIS |
| **Processing** | Business logic and orchestration | Alert manager, audio/radio controllers |
| **Application** | User interface and APIs | Flask web app, REST endpoints |
| **Output** | Broadcast generation | SAME encoder, TTS, GPIO, LED |
| **Verification** | Capture and validate broadcasts | SDR capture, SAME decoder |

---

## Core Components

### Component Dependency Map

```mermaid
graph LR
    subgraph "Core Modules"
        MODELS[app_core/models.py<br>Database Models]
        EXT[app_core/extensions.py<br>Flask Extensions]
        ALERTS[app_core/alerts.py<br>Alert Management]
        BOUNDARIES[app_core/boundaries.py<br>Spatial Processing]
        LOCATION[app_core/location.py<br>Location Services]
    end

    subgraph "Audio System"
        AUDIO_INGEST[app_core/audio/ingest.py<br>Audio Controller]
        AUDIO_SOURCES[app_core/audio/sources.py<br>Source Adapters]
        AUDIO_METER[app_core/audio/metering.py<br>Monitoring]
    end

    subgraph "Radio System"
        RADIO_MGR[app_core/radio/manager.py<br>Radio Manager]
        RADIO_DRV[app_core/radio/drivers.py<br>SoapySDR Drivers]
    end

    subgraph "Utilities"
        EAS_UTIL[app_utils/eas.py<br>SAME Generator]
        UTILS[app_utils/__init__.py<br>Common Utilities]
    end

    subgraph "Web Application"
        WEBAPP[webapp/__init__.py<br>Flask App Factory]
        ROUTES[webapp/admin/<br>Route Handlers]
        TEMPLATES[templates/<br>Jinja2 Views]
    end

    subgraph "Background Services"
        CAP_POLL[poller/cap_poller.py<br>NOAA Poller]
        IPAWS_POLL[poller/ipaws_poller.py<br>IPAWS Poller]
    end

    %% Dependencies
    EXT --> MODELS
    ALERTS --> MODELS
    BOUNDARIES --> MODELS
    LOCATION --> MODELS
    AUDIO_INGEST --> MODELS
    RADIO_MGR --> MODELS
    WEBAPP --> EXT
    WEBAPP --> ROUTES
    ROUTES --> TEMPLATES
    ROUTES --> ALERTS
    ROUTES --> AUDIO_INGEST
    ROUTES --> RADIO_MGR
    ROUTES --> EAS_UTIL
    CAP_POLL --> ALERTS
    IPAWS_POLL --> ALERTS
    AUDIO_SOURCES --> AUDIO_INGEST
    AUDIO_METER --> AUDIO_INGEST
    RADIO_DRV --> RADIO_MGR
```

---

## Alert Processing Pipeline

### End-to-End Alert Flow

```mermaid
sequenceDiagram
    participant NOAA as NOAA/IPAWS
    participant Poller as CAP Poller
    participant Validator as Validator
    participant AlertMgr as Alert Manager
    participant DB as Database
    participant Spatial as Spatial Engine
    participant Web as Web UI
    participant Operator as Operator

    NOAA->>Poller: CAP XML Feed
    Poller->>Poller: Fetch on Schedule
    Poller->>Validator: Parse CAP XML
    Validator->>Validator: Schema Validation
    Validator->>Validator: Normalize Geometry

    alt Valid CAP
        Validator->>AlertMgr: Validated Alert
        AlertMgr->>AlertMgr: Check Duplicates

        alt New Alert
            AlertMgr->>DB: Store CAPAlert
            AlertMgr->>Spatial: Process Geometry
            Spatial->>Spatial: Calculate Intersections
            Spatial->>DB: Store Intersections
            DB->>Web: Alert Available
            Web->>Operator: Dashboard Update
            Operator->>Operator: Review Alert
        else Duplicate
            AlertMgr->>AlertMgr: Log & Skip
        end
    else Invalid CAP
        Validator->>Poller: Reject
        Poller->>Poller: Log Error
    end
```

### Alert Ingestion Flowchart

```mermaid
flowchart TD
    START([Polling Interval<br>Triggered]) --> FETCH[Fetch CAP Feed]
    FETCH --> PARSE{Parse XML<br>Successful?}

    PARSE -->|No| LOG_ERR[Log Parse Error]
    LOG_ERR --> END([End])

    PARSE -->|Yes| VALIDATE{Schema<br>Valid?}
    VALIDATE -->|No| LOG_SCHEMA[Log Schema Error]
    LOG_SCHEMA --> END

    VALIDATE -->|Yes| EXTRACT[Extract Alert Data]
    EXTRACT --> GEOM{Has<br>Geometry?}

    GEOM -->|No| USE_SAME[Use SAME Codes]
    GEOM -->|Yes| NORM_GEOM[Normalize Geometry]

    USE_SAME --> DUP_CHECK
    NORM_GEOM --> DUP_CHECK{Duplicate<br>Check}

    DUP_CHECK -->|Duplicate| LOG_DUP[Log Duplicate]
    LOG_DUP --> END

    DUP_CHECK -->|New| STORE[Store to Database]
    STORE --> SPATIAL[Calculate Intersections]
    SPATIAL --> UPDATE_UI[Update Web UI]
    UPDATE_UI --> NOTIFY[Notify Operators]
    NOTIFY --> END

    style START fill:#e1f5ff
    style END fill:#e1f5ff
    style STORE fill:#d4edda
    style LOG_ERR fill:#f8d7da
    style LOG_SCHEMA fill:#f8d7da
    style LOG_DUP fill:#fff3cd
```

### Spatial Processing Detail

```mermaid
flowchart TD
    START([Alert with Geometry]) --> TYPE{Geometry<br>Type?}

    TYPE -->|Polygon| POLY[Parse Polygon Coords]
    TYPE -->|Circle| CIRCLE[Parse Center + Radius]
    TYPE -->|SAME Codes| SAME[Lookup FIPS Codes]

    POLY --> VALID_POLY{Valid<br>Polygon?}
    VALID_POLY -->|No| ERROR[Log Geometry Error]
    VALID_POLY -->|Yes| CREATE_GEOM[Create PostGIS Geometry]

    CIRCLE --> BUFFER[Create Buffer Geometry]
    BUFFER --> CREATE_GEOM

    SAME --> LOOKUP[Query Boundary Table]
    LOOKUP --> CREATE_GEOM

    CREATE_GEOM --> INTERSECT[ST_Intersects Query]
    INTERSECT --> BOUNDARIES[(Boundary Table)]
    BOUNDARIES --> RESULTS[Intersection Results]
    RESULTS --> CALCULATE[Calculate Areas]
    CALCULATE --> STORE[(Store Intersections)]
    STORE --> DONE([Complete])

    ERROR --> DONE

    style START fill:#e1f5ff
    style DONE fill:#e1f5ff
    style STORE fill:#d4edda
    style ERROR fill:#f8d7da
```

---

## Audio Ingest System

### Audio Ingest Architecture

```mermaid
graph TB
    subgraph "Audio Sources"
        SDR_SRC[SDR Receiver<br>RadioManager]
        ALSA_SRC[ALSA Device<br>hw:X,Y]
        PULSE_SRC[PulseAudio<br>Device Index]
        FILE_SRC[Audio File<br>WAV/MP3]
    end

    subgraph "Source Adapters"
        SDR_ADAPT[SDRSourceAdapter]
        ALSA_ADAPT[ALSASourceAdapter]
        PULSE_ADAPT[PulseSourceAdapter]
        FILE_ADAPT[FileSourceAdapter]
    end

    subgraph "Audio Controller"
        CONTROLLER[AudioIngestController]
        PRIORITY[Priority Selection]
        BUFFER[Audio Buffer Queue]
    end

    subgraph "Monitoring"
        METER[AudioMeter<br>Peak/RMS Levels]
        SILENCE[SilenceDetector<br>Threshold Detection]
        HEALTH[HealthMonitor<br>Health Score 0-100]
    end

    subgraph "Database"
        METRICS[(AudioSourceMetrics)]
        HEALTH_DB[(AudioHealthStatus)]
        ALERTS_DB[(AudioAlert)]
    end

    subgraph "Web UI"
        UI[Audio Sources Page<br>/audio/sources]
        API[REST API<br>/api/audio/*]
        JS[JavaScript Monitor<br>Real-time Updates]
    end

    %% Connections
    SDR_SRC --> SDR_ADAPT
    ALSA_SRC --> ALSA_ADAPT
    PULSE_SRC --> PULSE_ADAPT
    FILE_SRC --> FILE_ADAPT

    SDR_ADAPT --> CONTROLLER
    ALSA_ADAPT --> CONTROLLER
    PULSE_ADAPT --> CONTROLLER
    FILE_ADAPT --> CONTROLLER

    CONTROLLER --> PRIORITY
    PRIORITY --> BUFFER
    BUFFER --> METER
    BUFFER --> SILENCE
    METER --> HEALTH
    SILENCE --> HEALTH

    HEALTH --> METRICS
    HEALTH --> HEALTH_DB
    SILENCE --> ALERTS_DB

    METRICS --> API
    HEALTH_DB --> API
    ALERTS_DB --> API
    API --> UI
    UI --> JS
    JS --> API

    style SDR_SRC fill:#e1f5ff
    style CONTROLLER fill:#fff3cd
    style UI fill:#d4edda
```

### Audio Source Lifecycle

```mermaid
stateDiagram-v2
    [*] --> CONFIGURED: Create Source
    CONFIGURED --> STARTING: start()
    STARTING --> RUNNING: Capture Thread Started
    STARTING --> ERROR: Start Failed
    RUNNING --> STOPPING: stop()
    RUNNING --> ERROR: Capture Error
    RUNNING --> DISCONNECTED: Connection Lost
    STOPPING --> STOPPED: Clean Shutdown
    ERROR --> STOPPED: Manual Reset
    DISCONNECTED --> STARTING: Reconnect Attempt
    STOPPED --> STARTING: Restart
    STOPPED --> [*]: Delete Source

    note right of RUNNING
        - Reading audio chunks
        - Updating metrics
        - Detecting silence
        - Calculating health
    end note

    note right of ERROR
        - Log error details
        - Alert operators
        - Attempt recovery
    end note
```

### Audio Metrics Flow

```mermaid
sequenceDiagram
    participant Source as Audio Source
    participant Adapter as Source Adapter
    participant Controller as Controller
    participant Meter as Audio Meter
    participant Silence as Silence Detector
    participant Health as Health Monitor
    participant DB as Database
    participant UI as Web UI

    loop Every Audio Chunk
        Source->>Adapter: Audio Data
        Adapter->>Adapter: Convert to PCM
        Adapter->>Controller: Audio Chunk
        Controller->>Meter: Process Chunk
        Meter->>Meter: Calculate Peak/RMS
        Meter->>Health: Level Data
        Controller->>Silence: Check Audio
        Silence->>Silence: Check Threshold

        alt Silence Detected
            Silence->>Health: Silence Event
            Silence->>DB: Store Alert
        end

        Health->>Health: Update Health Score
        Health->>DB: Store Metrics
        DB->>UI: New Data Available
        UI->>UI: Update Display
    end
```

---

## Broadcast Workflow

### EAS Workflow Process

```mermaid
flowchart TD
    START([Operator Initiates<br>EAS Workflow]) --> SELECT_TYPE{Alert Type}

    SELECT_TYPE -->|Manual| MANUAL[Select Event Code]
    SELECT_TYPE -->|From CAP| CAP_SELECT[Select CAP Alert]

    MANUAL --> CONFIG[Configure Message]
    CAP_SELECT --> EXTRACT[Extract CAP Data]
    EXTRACT --> CONFIG

    CONFIG --> SAME_GEN[Generate SAME Header]
    SAME_GEN --> VALIDATE{SAME Header<br>Valid?}

    VALIDATE -->|No| ERROR[Show Error]
    ERROR --> CONFIG

    VALIDATE -->|Yes| NARR{Include<br>Narration?}

    NARR -->|No| BUILD_AUDIO
    NARR -->|Yes| TTS[Generate TTS Audio]
    TTS --> TTS_OK{TTS<br>Success?}
    TTS_OK -->|No| TTS_ERROR[TTS Error]
    TTS_ERROR --> NARR
    TTS_OK -->|Yes| BUILD_AUDIO

    BUILD_AUDIO[Build Complete Audio]
    BUILD_AUDIO --> PREVIEW[Show Preview Player]
    PREVIEW --> APPROVE{Operator<br>Approves?}

    APPROVE -->|No| CONFIG
    APPROVE -->|Yes| STORE_FILE[Store Audio File]

    STORE_FILE --> GPIO_CHECK{GPIO<br>Configured?}

    GPIO_CHECK -->|Yes| TRANSMIT[Key Transmitter]
    GPIO_CHECK -->|No| SKIP_TX[Skip Transmission]

    TRANSMIT --> TX_WAIT[Transmit Audio]
    TX_WAIT --> UNKEY[Unkey Transmitter]
    UNKEY --> LED_CHECK
    SKIP_TX --> LED_CHECK

    LED_CHECK{LED Sign<br>Configured?}

    LED_CHECK -->|Yes| LED_SEND[Send LED Message]
    LED_CHECK -->|No| SKIP_LED[Skip LED]

    LED_SEND --> LOG
    SKIP_LED --> LOG

    LOG[Log EAS Message]
    LOG --> DB_STORE[Store to Database]
    DB_STORE --> COMPLETE([Workflow Complete])

    style START fill:#e1f5ff
    style COMPLETE fill:#d4edda
    style ERROR fill:#f8d7da
    style TTS_ERROR fill:#f8d7da
```

### SAME Generation Detail

```mermaid
flowchart LR
    START([SAME Generator]) --> PREAMBLE[Generate Preamble<br>16 bytes 0xAB]
    PREAMBLE --> HEADER[Build SAME Header<br>ZCZC-ORG-EEE-...]
    HEADER --> ENCODE[FSK Encode<br>520.83 baud]
    ENCODE --> TRIPLET{Generate<br>3x Headers}

    TRIPLET --> ATT_SIGNAL[Generate Attention<br>853Hz + 960Hz]
    ATT_SIGNAL --> NARRATION{Has<br>Narration?}

    NARRATION -->|Yes| TTS_AUDIO[Append TTS Audio]
    NARRATION -->|No| EOM

    TTS_AUDIO --> EOM[Generate EOM<br>NNNN x3]
    EOM --> SILENCE[Add 1s Silence]
    SILENCE --> OUTPUT[(Audio WAV File)]

    style START fill:#e1f5ff
    style OUTPUT fill:#d4edda
```

### Audio Generation Pipeline

```mermaid
sequenceDiagram
    participant Operator
    participant Workflow as EAS Workflow
    participant SAME as SAME Generator
    participant TTS as TTS Service
    participant Audio as Audio Builder
    participant GPIO as GPIO Controller
    participant Storage as File Storage
    participant DB as Database

    Operator->>Workflow: Submit EAS Form
    Workflow->>Workflow: Validate Input
    Workflow->>SAME: Generate SAME Header
    SAME->>SAME: Build Header String
    SAME->>SAME: FSK Encode
    SAME->>SAME: Triplet Headers
    SAME->>SAME: Attention Signal
    SAME-->>Workflow: SAME Audio Buffer

    alt Narration Enabled
        Workflow->>TTS: Request Narration
        TTS->>TTS: Generate Speech
        TTS-->>Workflow: TTS Audio Buffer
    end

    SAME->>SAME: Generate EOM
    Workflow->>Audio: Combine Audio Segments
    Audio->>Audio: Normalize Levels
    Audio->>Storage: Save WAV File
    Storage-->>Workflow: File Path

    Workflow->>DB: Store EASMessage

    alt GPIO Configured
        Workflow->>GPIO: Key Transmitter
        GPIO->>GPIO: Wait for Audio
        GPIO->>GPIO: Unkey Transmitter
    end

    Workflow-->>Operator: Success + Audio Player
```

---

## Verification System

### SDR Capture & Verification Flow

```mermaid
flowchart TD
    START([SDR Monitoring Active]) --> SCAN[Scan Frequencies]
    SCAN --> DETECT{Energy<br>Detected?}

    DETECT -->|No| WAIT[Wait]
    WAIT --> SCAN

    DETECT -->|Yes| RECORD[Start Recording]
    RECORD --> SQUELCH{Squelch<br>Open?}

    SQUELCH -->|No| STOP_REC[Stop Recording]
    STOP_REC --> SCAN

    SQUELCH -->|Yes| CONTINUE[Continue Recording]
    CONTINUE --> TIMEOUT{Max Duration<br>Reached?}

    TIMEOUT -->|Yes| FINALIZE
    TIMEOUT -->|No| SQUELCH

    FINALIZE[Finalize Recording]
    FINALIZE --> SAVE[Save Audio File]
    SAVE --> DECODE[Attempt SAME Decode]
    DECODE --> VALID{Valid SAME<br>Header?}

    VALID -->|No| LOG_FAIL[Log Decode Failure]
    LOG_FAIL --> SCAN

    VALID -->|Yes| EXTRACT[Extract SAME Data]
    EXTRACT --> MATCH{Matches<br>Transmitted?}

    MATCH -->|Yes| VERIFY_OK[Mark as Verified]
    MATCH -->|No| MISMATCH[Log Mismatch]

    VERIFY_OK --> STORE[Store Verification]
    MISMATCH --> STORE
    STORE --> DB[(Database)]
    DB --> SCAN

    style START fill:#e1f5ff
    style VERIFY_OK fill:#d4edda
    style LOG_FAIL fill:#f8d7da
    style MISMATCH fill:#fff3cd
```

### Verification Workflow

```mermaid
sequenceDiagram
    participant TX as Transmitter
    participant SDR as SDR Receiver
    participant Radio as Radio Manager
    participant Decoder as SAME Decoder
    participant DB as Database
    participant UI as Web UI

    TX->>TX: Transmit EAS
    TX->>SDR: RF Signal
    SDR->>Radio: Audio Stream
    Radio->>Radio: Start Recording
    Radio->>Radio: Detect SAME Tones

    alt SAME Detected
        Radio->>Decoder: Audio File
        Decoder->>Decoder: Decode SAME Header

        alt Valid Header
            Decoder->>Decoder: Extract Data
            Decoder->>DB: Store Verification
            DB->>DB: Match with Transmitted

            alt Match Found
                DB->>UI: Verification Success
            else No Match
                DB->>UI: Orphan Reception
            end
        else Invalid Header
            Decoder->>DB: Store Failed Decode
            DB->>UI: Decode Failure
        end
    else No SAME Detected
        Radio->>DB: No Activity
    end
```

---

## Data Flow Diagrams

### Database Entity Relationships

```mermaid
erDiagram
    CAPAlert ||--o{ Intersection : "intersects"
    CAPAlert ||--o{ EASMessage : "generates"
    Boundary ||--o{ Intersection : "affected_by"
    RadioReceiver ||--o{ RadioReceiverStatus : "has"
    AudioSourceMetrics ||--|| AudioHealthStatus : "health_of"
    AudioAlert }o--|| AudioSourceMetrics : "triggered_by"
    LEDMessage }o--|| CAPAlert : "displays"

    CAPAlert {
        int id PK
        string identifier UK
        string event
        string severity
        string urgency
        timestamp sent
        timestamp expires
        geometry geom
        string area_desc
    }

    Boundary {
        int id PK
        string name
        string type
        geometry geom
        string description
    }

    Intersection {
        int id PK
        int cap_alert_id FK
        int boundary_id FK
        float intersection_area
        float coverage_percentage
    }

    EASMessage {
        int id PK
        int cap_alert_id FK
        string same_header
        bytea audio_data
        timestamp created_at
    }

    RadioReceiver {
        int id PK
        string name
        string device_type
        string serial
        int frequency
        bool enabled
    }

    AudioSourceMetrics {
        int id PK
        string source_name
        string source_type
        float peak_level_db
        float rms_level_db
        bool silence_detected
        timestamp timestamp
    }
```

### Data Flow: CAP to Broadcast

```mermaid
graph LR
    subgraph "External"
        CAP[CAP XML]
    end

    subgraph "Ingestion"
        PARSE[XML Parser]
        VALID[Validator]
    end

    subgraph "Storage"
        ALERT[(CAPAlert)]
        BOUND[(Boundary)]
        INTER[(Intersection)]
    end

    subgraph "Processing"
        SPATIAL[Spatial Engine]
        FILTER[Alert Filter]
    end

    subgraph "Presentation"
        WEB[Web Dashboard]
        API[REST API]
    end

    subgraph "Broadcast"
        WORKFLOW[EAS Workflow]
        SAME[SAME Generator]
        TTS[TTS Engine]
        AUDIO[Audio Builder]
    end

    subgraph "Output"
        WAV[WAV File]
        TX[Transmitter]
        LED[LED Sign]
    end

    CAP --> PARSE
    PARSE --> VALID
    VALID --> ALERT
    ALERT --> SPATIAL
    BOUND --> SPATIAL
    SPATIAL --> INTER
    INTER --> FILTER
    FILTER --> WEB
    FILTER --> API
    WEB --> WORKFLOW
    WORKFLOW --> SAME
    WORKFLOW --> TTS
    SAME --> AUDIO
    TTS --> AUDIO
    AUDIO --> WAV
    WAV --> TX
    WORKFLOW --> LED

    style CAP fill:#e1f5ff
    style ALERT fill:#fff3cd
    style BOUND fill:#fff3cd
    style INTER fill:#fff3cd
    style WAV fill:#d4edda
```

---

## Component Interactions

### Web Request Flow

```mermaid
sequenceDiagram
    participant Browser
    participant Flask as Flask App
    participant Auth as Auth Layer
    participant Routes as Route Handler
    participant Core as Core Module
    participant DB as Database
    participant Template as Jinja2 Template

    Browser->>Flask: HTTP Request
    Flask->>Flask: CSRF Validation
    Flask->>Auth: Check Authentication

    alt Authenticated Route
        Auth->>Auth: Verify Session
        alt Valid Session
            Auth->>Routes: Allow Access
        else Invalid
            Auth-->>Browser: Redirect to Login
        end
    else Public Route
        Flask->>Routes: Route Request
    end

    Routes->>Core: Call Business Logic
    Core->>DB: Query Data
    DB-->>Core: Result Set
    Core-->>Routes: Processed Data
    Routes->>Template: Render Template
    Template-->>Routes: HTML
    Routes-->>Flask: HTTP Response
    Flask-->>Browser: Send Response
```

### System Health Monitoring

```mermaid
flowchart TD
    START([Health Check Triggered]) --> CPU[Check CPU Usage]
    CPU --> MEMORY[Check Memory Usage]
    MEMORY --> DISK[Check Disk Usage]
    DISK --> DB_CONN[Check DB Connection]
    DB_CONN --> POLLER[Check Poller Status]
    POLLER --> SDR[Check SDR Status]
    SDR --> AUDIO[Check Audio System]

    AUDIO --> AGGREGATE[Aggregate Health Data]
    AGGREGATE --> SCORE{Calculate<br>Health Score}

    SCORE -->|< 50| CRITICAL[Status: Critical]
    SCORE -->|50-79| WARNING[Status: Warning]
    SCORE -->|>= 80| HEALTHY[Status: Healthy]

    CRITICAL --> LOG
    WARNING --> LOG
    HEALTHY --> LOG

    LOG[Log Health Status]
    LOG --> STORE[Store to Database]
    STORE --> UPDATE[Update UI]
    UPDATE --> END([Complete])

    style START fill:#e1f5ff
    style CRITICAL fill:#f8d7da
    style WARNING fill:#fff3cd
    style HEALTHY fill:#d4edda
    style END fill:#e1f5ff
```

### Multi-Service Coordination

```mermaid
graph TB
    subgraph "Docker Compose Services"
        APP[app<br>Flask Web + API]
        NOAA_POLL[noaa-poller<br>CAP Polling]
        IPAWS_POLL[ipaws-poller<br>FEMA Polling]
        SDR_SVC[sdr-service<br>SDR + Audio]
        HW_SVC[hardware-service<br>GPIO/Displays]
        DB[PostgreSQL<br>+ PostGIS]
        REDIS[Redis<br>Cache + IPC]
        ICECAST[Icecast<br>Audio Streaming]
        NGINX[nginx<br>HTTPS Proxy]
    end

    subgraph "Shared Volumes"
        VOL_CONFIG[app-config<br>/app-config/.env]
        VOL_DATA[alerts-db-data]
        VOL_REDIS[redis-data]
        VOL_CERTS[certbot-conf]
    end

    subgraph "Docker Network"
        NET[eas-network<br>Bridge + IPv6]
    end

    subgraph "External"
        OPERATOR[Browser<br>HTTPS :443]
        NOAA_API[NOAA API]
        IPAWS_API[IPAWS API]
        USB[USB Devices]
        I2C[I2C/GPIO]
    end

    %% Network connections
    APP --> NET
    NOAA_POLL --> NET
    IPAWS_POLL --> NET
    SDR_SVC --> NET
    HW_SVC --> NET
    DB --> NET
    REDIS --> NET
    ICECAST --> NET
    NGINX --> NET

    %% Volume mounts
    APP --> VOL_CONFIG
    NOAA_POLL --> VOL_CONFIG
    IPAWS_POLL --> VOL_CONFIG
    SDR_SVC --> VOL_CONFIG
    HW_SVC --> VOL_CONFIG
    DB --> VOL_DATA
    REDIS --> VOL_REDIS
    NGINX --> VOL_CERTS

    %% External connections
    NGINX --> OPERATOR
    NOAA_POLL --> NOAA_API
    IPAWS_POLL --> IPAWS_API
    SDR_SVC --> USB
    HW_SVC --> I2C

    %% Internal dependencies
    APP --> REDIS
    APP --> DB
    SDR_SVC --> REDIS
    SDR_SVC --> ICECAST
    HW_SVC --> REDIS

    style APP fill:#d4edda
    style SDR_SVC fill:#e1f5ff
    style HW_SVC fill:#fff3e0
    style DB fill:#fff3cd
    style REDIS fill:#f8d7da
```

### Service Communication Patterns

```mermaid
sequenceDiagram
    participant Browser
    participant nginx
    participant app
    participant Redis
    participant sdr-service
    participant hardware-service
    participant DB

    Browser->>nginx: HTTPS Request
    nginx->>app: HTTP Proxy
    app->>DB: Query alerts
    DB-->>app: Alert data
    
    app->>Redis: Publish command
    Redis-->>sdr-service: Subscribe notification
    sdr-service->>sdr-service: Process SDR audio
    sdr-service->>Redis: Audio metrics
    
    app->>Redis: GPIO command
    Redis-->>hardware-service: GPIO trigger
    hardware-service->>hardware-service: Activate relay
    hardware-service->>Redis: Status update
    
    app-->>nginx: Response
    nginx-->>Browser: HTTPS Response
```

---

## Deployment Architecture

### Single-Host Deployment (Raspberry Pi 5)

```mermaid
graph TB
    subgraph "Raspberry Pi 5 Hardware"
        subgraph "Software Stack"
            HOST[Docker Engine 24+]
            subgraph "Containers"
                APP_C[Web Application<br>Python 3.12 + Flask]
                POLL_C[CAP Poller<br>Background Service]
                IPAWS_C[IPAWS Poller<br>Background Service]
                DB_C[PostgreSQL 17<br>PostGIS 3.4]
            end
        end

        subgraph "Peripherals"
            SDR1[RTL-SDR<br>USB 3.0]
            SDR2[Airspy<br>USB 3.0]
            GPIO_HAT[GPIO Relay HAT<br>Transmitter Control]
            AUDIO_HAT[Audio DAC HAT<br>Balanced Output]
            ETH[Gigabit Ethernet]
        end

        subgraph "Storage"
            NVME[NVMe SSD<br>PCIe Gen 2]
        end
    end

    subgraph "External Connections"
        INTERNET[Internet<br>CAP Feeds]
        TX_EXT[FM Transmitter]
        LED_EXT[LED Sign<br>RS-232]
        MONITOR[HDMI Monitor]
    end

    APP_C --> DB_C
    POLL_C --> DB_C
    IPAWS_C --> DB_C

    HOST --> APP_C
    HOST --> POLL_C
    HOST --> IPAWS_C
    HOST --> DB_C

    DB_C --> NVME
    APP_C --> NVME

    SDR1 --> APP_C
    SDR2 --> APP_C
    GPIO_HAT --> APP_C
    AUDIO_HAT --> APP_C
    ETH --> INTERNET
    GPIO_HAT --> TX_EXT
    APP_C --> LED_EXT
    APP_C --> MONITOR

    style HOST fill:#e1f5ff
    style APP_C fill:#d4edda
    style DB_C fill:#fff3cd
    style NVME fill:#f8d7da
```

### External Database Deployment

```mermaid
graph TB
    subgraph "Application Server"
        APP[EAS Station Application<br>Docker Compose]
        POLL[CAP Pollers<br>Docker Containers]
    end

    subgraph "Database Server"
        PG[PostgreSQL 17<br>Dedicated Server]
        PGIS[PostGIS 3.4<br>Extension]
        BACKUP[Automated Backups<br>pg_dump]
    end

    subgraph "Network"
        FW[Firewall<br>Port 5432]
        VPN[VPN Tunnel<br>Optional]
    end

    subgraph "Monitoring"
        PROM[Prometheus<br>Metrics]
        GRAF[Grafana<br>Dashboards]
    end

    APP --> FW
    POLL --> FW
    FW --> PG
    PG --> PGIS
    PG --> BACKUP

    VPN --> FW

    APP --> PROM
    PG --> PROM
    PROM --> GRAF

    style APP fill:#d4edda
    style PG fill:#fff3cd
    style FW fill:#f8d7da
```

---

## Summary

This architecture document provides visual representations of:

1. **System Overview** - High-level component layout and data flows
2. **Core Components** - Module dependencies and relationships
3. **Alert Processing** - End-to-end CAP ingestion and validation
4. **Audio Ingest** - Real-time audio monitoring architecture
5. **Broadcast Workflow** - EAS message generation and transmission
6. **Verification System** - SDR capture and SAME decoding
7. **Data Flows** - Database entities and information routing
8. **Component Interactions** - Service coordination and communication
9. **Deployment** - Physical and logical deployment architectures

These diagrams serve as living documentation that should be updated as the system evolves.

**Related Resources:**
- [Data Flow Sequences](DATA_FLOW_SEQUENCES) - Detailed data processing paths ⭐ NEW
- [Theory of Operation](THEORY_OF_OPERATION) - Detailed operational concepts
- [Developer Guide](../development/AGENTS) - Code standards and practices
- [Help Guide](../guides/HELP) - Operational procedures

---

## Professional Diagrams

For enhanced clarity and presentation, the following professional SVG diagrams are available:

### Alert Processing Pipeline

Detailed flowchart showing the complete CAP alert ingestion workflow from external sources through validation, parsing, spatial processing, and database storage.

![Alert Processing Pipeline](../assets/diagrams/alert-processing-pipeline.svg)

**File:** [../assets/diagrams/alert-processing-pipeline.svg](../assets/diagrams/alert-processing-pipeline.svg)

---

### EAS Broadcast Workflow

Step-by-step workflow diagram illustrating the complete EAS message generation and transmission process, from alert selection through SAME encoding to broadcast completion.

![EAS Broadcast Workflow](../assets/diagrams/broadcast-workflow.svg)

**File:** [../assets/diagrams/broadcast-workflow.svg](../assets/diagrams/broadcast-workflow.svg)

---

### Audio Source Routing Architecture

Block diagram showing multi-source audio ingestion architecture with adapters, priority selection, monitoring systems, and database integration.

![Audio Source Routing](../assets/diagrams/audio-source-routing.svg)

**File:** [../assets/diagrams/audio-source-routing.svg](../assets/diagrams/audio-source-routing.svg)

---

### Hardware Deployment Architecture

Physical deployment diagram showing Raspberry Pi 5 hardware configuration with all peripherals, storage, and external connections.

![Hardware Deployment](../assets/diagrams/system-deployment-hardware.svg)

**File:** [../assets/diagrams/system-deployment-hardware.svg](../assets/diagrams/system-deployment-hardware.svg)

---

**Last Updated:** 2025-11-05
**Diagram Format:** Mermaid.js (Markdown) and SVG (Professional graphics)
