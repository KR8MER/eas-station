# EAS Station™ Theory of Operation

The EAS Station™ platform orchestrates NOAA and IPAWS Common Alerting Protocol (CAP) messages from ingestion to FCC-compliant broadcast and verification. This document explains the end-to-end data flow, highlights the subsystems that participate in each phase, and provides historical context for the Specific Area Message Encoding (SAME) protocol that anchors the audio workflow.

---

## System Architecture Overview

EAS Station™ uses a **separated service architecture** with complete hardware isolation for reliability and fault tolerance:

```mermaid
graph TB
    subgraph External["External Sources"]
        NOAA[NOAA Weather Service<br/>CAP XML Feeds]
        IPAWS[FEMA IPAWS<br/>CAP XML Feeds]
        RF[RF Signals<br/>162 MHz NOAA WX]
    end

    subgraph EASServices["EAS Station™ Services"]
        subgraph AppLayer["Application Layer"]
            APP[app<br/>Flask Web UI<br/>Port 5000]
            NOAA_POLL[noaa-poller<br/>CAP Polling]
            IPAWS_POLL[ipaws-poller<br/>CAP Polling]
        end

        subgraph HardwareLayer["Hardware Services"]
            SDR[sdr-service<br/>SDR + Audio<br/>USB Access]
            HW[hardware.target<br/>5 subsystems<br/>Ports 5101–5105]
        end

        subgraph Infrastructure["Infrastructure"]
            REDIS[(Redis<br/>Cache + IPC)]
            DB[(PostgreSQL<br/>+ PostGIS)]
            ICECAST[Icecast<br/>Audio Streaming]
            NGINX[nginx<br/>Reverse Proxy<br/>HTTPS]
        end
    end

    subgraph Hardware["Physical Hardware"]
        SDR_DEV[SDR Receivers<br/>RTL-SDR/Airspy]
        GPIO[GPIO Pins<br/>Relay Control]
        OLED[OLED Display<br/>SSD1306]
        LED[LED Signs<br/>Alpha Protocol]
        VFD_DEV[VFD Display<br/>Noritake]
    end

    subgraph Output["Outputs"]
        TX[FM Transmitter]
        BROWSER[Web Browser]
        STREAM[Audio Streams]
    end

    %% Data flows
    NOAA --> NOAA_POLL
    IPAWS --> IPAWS_POLL
    NOAA_POLL --> DB
    IPAWS_POLL --> DB
    RF --> SDR_DEV --> SDR
    
    APP --> DB
    APP --> REDIS
    SDR --> REDIS
    SDR --> ICECAST
    HW --> REDIS
    
    SDR --> SDR_DEV
    HW --> GPIO --> TX
    HW --> OLED
    HW --> LED
    HW --> VFD_DEV
    
    NGINX --> APP
    BROWSER --> NGINX
    ICECAST --> STREAM

    style APP fill:#d4edda
    style SDR fill:#e1f5ff
    style HW fill:#fff3e0
    style DB fill:#fff3cd
    style REDIS fill:#f8d7da
```

### Service Responsibilities

| Service | Hardware Access | Purpose |
|---------|----------------|---------|
| **app** | None (read-only /dev for SMART) | Web UI, API, configuration |
| **noaa-poller** | None | NOAA CAP XML feed polling |
| **ipaws-poller** | None | FEMA IPAWS feed polling |
| **sdr-service** | USB (`/dev/bus/usb`) | SDR capture, audio processing, SAME decoding |
| **hardware-service** | GPIO, I2C (`/dev/gpiomem`, `/dev/i2c-1`) | Relay control, displays (OLED/VFD/LED) |

---

## High-Level Data Flow

```mermaid
flowchart TD
    A[CAP Sources<br/>NOAA + IPAWS] -->|HTTP Polling<br/>noaa-poller<br/>ipaws-poller| B[Ingestion Pipeline]
    B -->|app_core/alerts.py| C[Persistence Layer]
    C -->|PostgreSQL 17<br/>+ PostGIS 3.4| D[(Database<br/>alerts, boundaries<br/>receivers, configs)]
    C -->|app_core/location.py<br/>app_core/boundaries.py| E[Spatial Intelligence]
    D -->|Flask webapp<br/>REST APIs| F[Operator Experience]
    B -->|auto_forward.py<br/>Automatic forwarding| G
    F -->|Manual activation<br/>Scheduled RWT| G[EAS Workflow]
    G -->|app_utils/eas.py<br/>app_utils/eas_fsk.py| H[SAME Generator]
    H -->|hardware-service<br/>GPIO Control| I[Broadcast Output]
    
    subgraph Verification["Verification Loop"]
        J[sdr-service<br/>RF Capture]
        K[streaming_same_decoder.py<br/>Real-time Decode]
        L[Compliance Dashboard]
    end
    
    I -->|RF Signal| J
    J --> K
    K --> D
    D --> L
    L --> F

    style A fill:#3b82f6,color:#fff
    style D fill:#8b5cf6,color:#fff
    style F fill:#10b981,color:#fff
    style I fill:#f59e0b,color:#000
```

Each node references an actual module, package, or service in the repository so operators and developers can trace the implementation.

## Pipeline Stages

### 1. Ingestion & Validation

The CAP polling system runs as two separate systemd services for fault isolation:

```mermaid
sequenceDiagram
    participant NOAA as NOAA Weather API
    participant NP as noaa-poller
    participant IPAWS as FEMA IPAWS
    participant IP as ipaws-poller
    participant DB as PostgreSQL + PostGIS
    participant REDIS as Redis

    loop Every poll interval (default 120s)
        NP->>NOAA: GET /alerts (CAP XML)
        NOAA-->>NP: CAP 1.2 Feed
        NP->>NP: Parse & Validate XML
        NP->>NP: Extract geometry (polygon/circle/SAME)
        NP->>DB: Check duplicate (CAP identifier)
        alt New Alert
            NP->>DB: INSERT cap_alerts
            NP->>DB: Calculate spatial intersections
            NP->>REDIS: Publish alert notification
        end
    end

    loop Every poll interval (default 120s)
        IP->>IPAWS: GET /recent/{timestamp}
        IPAWS-->>IP: CAP 1.2 Feed
        IP->>IP: Parse & Validate XML
        IP->>DB: Store alerts + intersections
    end
```

- **Pollers (`poller/cap_poller.py`)** fetch CAP 1.2 feeds from NOAA Weather Service and FEMA IPAWS on configurable intervals (default 120 seconds, configured at Settings → Poller and persisted in `poller_settings.poll_interval_sec`)
- **Schema Enforcement** validates XML against CAP schema and normalises polygons, circles, and SAME location codes
- **Deduplication (`app_core/alerts.py`)** compares CAP identifiers, message types, and sent timestamps
- **Configuration** for runtime settings (polling, EAS broadcast, notifications, application logging) lives in dedicated database tables editable from the admin UI; only boot-time infrastructure (`SECRET_KEY`, `DATABASE_URL`, hostnames, paths) is read from the persistent `/app-config/.env` file

### 2. Persistence & Spatial Context

```mermaid
erDiagram
    CAPAlert ||--o{ AlertIntersection : has
    Boundary ||--o{ AlertIntersection : intersects
    CAPAlert ||--o{ EASMessage : generates
    RadioReceiver ||--o{ RadioReceiverStatus : reports
    AudioSource ||--o{ AudioSourceMetrics : captures
    DisplayScreen ||--o{ ScreenRotation : rotates
    AdminUser ||--o{ AuditLog : creates

    CAPAlert {
        int id PK
        string cap_identifier UK
        string event_code
        string severity
        timestamp sent
        timestamp expires
        geometry polygon
        string same_codes
    }

    Boundary {
        int id PK
        string name
        string fips_code
        string type
        geometry geom
    }
```

- **Database** runs PostgreSQL 17 with PostGIS 3.4 extension
- **ORM Models (`app_core/models.py`)** describe alerts, boundaries, receivers, audio sources, displays
- **Spatial Processing** uses PostGIS `ST_Intersects` for geographic matching

### 3. Operator Experience

- **Flask Web Application (`webapp/`)** provides Bootstrap 5 responsive interface
- **Setup Wizard (`/setup`)** manages ALL configuration—no hardcoded environment variables
- **Settings Pages** (`/settings/*`) expose:
  - Environment variables (`/settings/environment`)
  - Location settings, Audio/SDR configuration
  - Hardware (GPIO, OLED, VFD, LED signs)
  - IPAWS/NOAA feed configuration
- **System Health (`app_core/system_health.py`)** monitors CPU, memory, SDR state, audio pipeline

### 4. Broadcast Orchestration

Broadcast can be triggered **automatically** (zero intervention) or **manually** by an operator:

```mermaid
flowchart TD
    subgraph AutoPath["Automatic Path (v2.52.0+)"]
        CAP_IN[New CAP Alert<br/>IPAWS / NOAA] --> DEDUP{Cross-Source<br/>Duplicate?}
        OTA_IN[OTA Alert Received<br/>FIPS Match] --> DEDUP
        DEDUP -->|No| AUTO_FWD[auto_forward.py<br/>EASBroadcaster.handle_alert]
        DEDUP -->|Yes| SKIP[Skip<br/>Already broadcast]
    end

    subgraph ManualPath["Manual Path"]
        START([Operator Initiates<br/>EAS Broadcast]) --> SELECT{Alert Source}
        SELECT -->|Manual| MANUAL[Select Event Code<br/>Enter Details]
        SELECT -->|From CAP| CAP[Select Active Alert]
        MANUAL --> CONFIG
        CAP --> CONFIG[Configure SAME Header]
    end

    AUTO_FWD --> SAME
    CONFIG --> SAME[Generate SAME Header<br/>app_utils/eas.py]

    SAME --> ORIGINATOR[Substitute Station Originator<br/>replaces source originator]
    ORIGINATOR --> FSK[FSK Encode @ 520.83 baud<br/>app_utils/eas_fsk.py]
    FSK --> TONE[Generate Attention Tone<br/>853 Hz + 960 Hz]

    TONE --> TTS{TTS Enabled?}
    TTS -->|Yes| NARRATE[Generate TTS Audio<br/>Azure/pyttsx3]
    TTS -->|No| EOM
    NARRATE --> EOM[Generate EOM x3<br/>NNNN]

    EOM --> AUDIO[Build Complete Audio<br/>Header x3 + Tone + Voice + EOM x3]
    AUDIO --> STORE[(Store WAV File)]

    STORE --> GPIO{GPIO Configured?}
    GPIO -->|Yes| KEY[hardware-service<br/>Key Transmitter]
    GPIO -->|No| PLAY
    KEY --> PLAY[Play Audio]
    PLAY --> UNKEY[Unkey Transmitter]
    UNKEY --> LOG[Log to Database<br/>eas_forwarded = true]

    style CAP_IN fill:#3b82f6,color:#fff
    style OTA_IN fill:#3b82f6,color:#fff
    style START fill:#10b981,color:#fff
    style ORIGINATOR fill:#8b5cf6,color:#fff
    style STORE fill:#10b981,color:#fff
    style KEY fill:#f59e0b,color:#000
    style SKIP fill:#ef4444,color:#fff
```

**Automatic Forwarding (v2.52.0+):**
- **CAP alerts** (`poller/cap_poller.py`) — after saving a new alert, calls `auto_forward_cap_alert()` which triggers `EASBroadcaster.handle_alert()` for full SAME + audio + GPIO broadcast
- **OTA alerts** (`app_core/audio/alert_forwarding.py`) — when a FIPS-matched OTA alert is received, calls `auto_forward_ota_alert()` through the same broadcast pipeline
- **Cross-source deduplication** (`app_core/audio/auto_forward.py`) — checks `eas_messages` and `manual_eas_activations` tables within a 15-minute window for same event code + overlapping FIPS codes to prevent duplicate broadcasts when the same alert arrives via IPAWS + NOAA + OTA
- **Originator substitution** — the original alert's originator is replaced with the station's configured originator in `build_same_header()` (`app_utils/eas.py:647`)

**Manual Path:**
- **Workflow UI (`webapp/eas/`)** guides operators through alert selection and SAME header preview
- **SAME Generator (`app_utils/eas.py`, `app_utils/eas_fsk.py`)** creates FCC-compliant 520⅔ baud FSK audio
- **Hardware Integration** via isolated `hardware-service` systemd service for GPIO relay control

### 5. Audio Processing & SDR Monitoring

The `sdr-service` systemd service handles all SDR hardware and audio processing:

```mermaid
flowchart LR
    subgraph sdr-service["sdr-service (systemd)"]
        SDR[SoapySDR<br/>Drivers]
        DEMOD[FM Demodulator<br/>demodulation.py]
        DECODE[Streaming SAME<br/>Decoder]
        ICEOUT[Icecast Output<br/>Streaming]
    end
    
    subgraph Hardware["USB Hardware"]
        RTL[RTL-SDR]
        AIR[Airspy]
    end
    
    RTL --> SDR
    AIR --> SDR
    SDR -->|IQ Samples| DEMOD
    DEMOD -->|PCM Audio| DECODE
    DEMOD -->|PCM Audio| ICEOUT
    DECODE -->|Alerts| REDIS[(Redis)]
    ICEOUT --> ICECAST[Icecast Server]
    
    style sdr-service fill:#e1f5ff
```

- **Real-Time Streaming Decoder (`app_core/audio/streaming_same_decoder.py`)** — <200ms latency, <5% CPU
- **Audio Source Manager (`app_core/audio/source_manager.py`)** — multi-source with automatic failover
- **Icecast Integration** streams demodulated audio for remote monitoring

### 6. Verification & Compliance

```mermaid
sequenceDiagram
    participant TX as Transmitter
    participant SDR as sdr-service
    participant DECODE as Streaming Decoder
    participant DB as Database
    participant UI as Compliance Dashboard

    TX->>TX: Broadcast EAS
    TX-->>SDR: RF Signal (162.x MHz)
    SDR->>SDR: Capture IQ samples
    SDR->>SDR: FM Demodulate
    SDR->>DECODE: PCM audio stream
    
    DECODE->>DECODE: Detect SAME preamble
    DECODE->>DECODE: FSK decode header
    DECODE->>DECODE: Validate checksum
    
    alt Valid SAME Header
        DECODE->>DB: Store verification record
        DECODE->>DB: Match with transmitted
        DB->>UI: Verification status
    end
    
    UI->>DB: Query verification history
    DB-->>UI: Compliance report data
```

- **SDR Capture** via SoapySDR drivers (`app_core/radio/drivers.py`)
- **Alert Verification** supports WAV/MP3 uploads and automated SDR captures
- **Compliance Dashboard** reconciles alerts for FCC reporting
## SAME Protocol Deep Dive

The Specific Area Message Encoding protocol is the broadcast payload EAS Station™ produces for on-air activation. Key characteristics:

- **Encoding Format** – ASCII characters transmitted with 520⅔ baud frequency-shift keying (FSK) using mark and space tones at 2083.3 Hz and 1562.5 Hz. The generator in `app_utils/eas.py` honours this cadence and injects the mandated three-header burst sequence (Preamble, ZCZC, message body, End of Message).
- **Message Structure** – SAME headers follow `ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL-`. EAS Station™ assembles each component from CAP payloads: ORG from `senderName`, EEE from the CAP event code, PSSCCC from matched FIPS/SAME codes, TTTT for duration, and `LLLLLLLL` for the station identifier configured in the admin UI.
- **Attention Signal** – After the third header, the attention signal is generated using simultaneous 853 Hz and 960 Hz sine waves for a configurable duration (defaults defined in `app_utils/eas.py`).
- **End of Message** – The `NNNN` EOM triplet terminates the activation. The workflow enforces the three-EOM rule and logs playout with timestamps in `app_core/eas_storage.py`.

> 📑 **Cross-Reference:** Sections 4.1–4.3 of the DASDEC3 *Version 5.1 Software User’s Guide* describe identical header, audio, and relay sequencing. Keep `docs/resources/vendor/Version 5.1 Software_Users Guide_R1.0 5-31-23.pdf` open when editing this document so the nomenclature stays aligned.

### Historical Background

- **1994 Rollout** – The FCC adopted SAME to replace the two-tone Attention Signal, enabling geographically targeted alerts and automated receiver activation.
- **2002 IPAWS Integration** – FEMA’s Integrated Public Alert and Warning System standardised CAP 1.2 feeds, which EAS Station™ ingests via dedicated pollers.
- **Ongoing Enforcement** – FCC Enforcement Bureau cases such as the 2015 iHeartMedia consent decree (The Bobby Bones Show) and the 2014 Olympus Has Fallen trailer settlement demonstrate the penalties for misuse. The `/about` page links to the official notices to reinforce best practices.

### Raspberry Pi Platform Evolution

EAS Station™’s quest to deliver a software-first encoder/decoder is tightly coupled with the Raspberry Pi roadmap:

- **Model B (2012):** Early tests proved a $35 board could poll CAP feeds and render SAME tones with USB DACs, albeit with limited concurrency.
- **Pi 3 (2016):** Integrated Wi-Fi and quad-core CPUs enabled simultaneous NOAA/IPAWS polling and text-to-speech without overruns.
- **Pi 4 (2020):** Gigabit Ethernet and USB 3.0 stabilised dual-SDR capture alongside GPIO relay control, unlocking continuous lab deployments.
- **Pi 5 (2023):** PCIe 2.0 storage, LPDDR4X memory, and the BCM2712 SoC provided the horsepower for SDR verification, compliance analytics, and narration on a single board—the reference build documented in [`README.md`](https://github.com/KR8MER/eas-station/blob/main/README.md).
- **Pi 5 Production Runs (2024+):** Hardened kits with UPS-backed power, relay breakouts, and CM4-based carrier boards were documented alongside vendor references (`docs/resources/vendor/QSG_DASDEC-G3_R5.1.docx`, `docs/resources/vendor/D,GrobSystems,ADJ06182024A.pdf`) to mirror field requirements captured in the DASDEC3 manual.

The reference stack—Pi 5 (8 GB), balanced audio HAT, dual SDR receivers, NVMe storage, GPIO relay bank, and UPS-backed power—totals **~$585 USD** in 2025. Equivalent DASDEC3 racks list for **$5,000–$7,000 USD**, illustrating the leverage gained by investing in software quality rather than proprietary hardware.


## Operational Checklist

When deploying or evaluating the system:

2. **Verify CAP Connectivity** – Confirm polling logs in `logs/` show successful fetches and schema validation.
3. **Map Boundaries** – Populate counties and polygons through the admin interface (`/settings/geo`) or import via the CLI tools in `tools/`.
4. **Configure Broadcast Outputs** – Set the station identifier, text-to-speech provider, GPIO pinout, and LED sign parameters in `/settings`.
5. **Exercise the Workflow** – Use `/eas/workflow` to run a Required Weekly Test (RWT) and inspect stored WAV files under `static/audio/`.
6. **Validate Verification Loop** – Upload the generated WAV to the decoder lab to confirm headers decode as issued.

Refer back to this document whenever you need a grounded explanation of what happens between CAP ingestion and verified broadcast.

---

**Last Updated:** 2025-12-16
**Related Documents:** [System Architecture](SYSTEM_ARCHITECTURE), [Data Flow Sequences](DATA_FLOW_SEQUENCES), [Diagrams Index](../reference/DIAGRAMS)
