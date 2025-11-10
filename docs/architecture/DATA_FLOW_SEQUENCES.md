# EAS Station Data Flow Sequence Diagrams

This document provides detailed sequence diagrams showing how data flows through the EAS Station system, from initial ingestion through processing to final output. These diagrams focus on the actual data paths and transformations as data moves through components like SDR receivers, audio streams, CAP pollers, and broadcast systems.

## Document Overview

**Purpose:** Visualize complete data processing paths through the system
**Audience:** Developers, system architects, and operators understanding data flows
**Related:** [System Architecture](SYSTEM_ARCHITECTURE.md), [Theory of Operation](THEORY_OF_OPERATION.md)

---

## Table of Contents

1. [Alert Processing Data Flow](#alert-processing-data-flow)
2. [SDR Continuous Monitoring Data Flow](#sdr-continuous-monitoring-data-flow)
3. [Multi-Source Audio Ingest Data Flow](#multi-source-audio-ingest-data-flow)
4. [Radio Capture Coordination Data Flow](#radio-capture-coordination-data-flow)
5. [EAS Message Generation Data Flow](#eas-message-generation-data-flow)
6. [Complete Alert-to-Broadcast Pipeline](#complete-alert-to-broadcast-pipeline)

---

## Alert Processing Data Flow

This sequence shows the complete path of a CAP alert from external sources through validation, storage, spatial processing, and availability to operators.

**Key Components:**
- `poller/cap_poller.py` - Fetches and orchestrates alert processing
- `app_core/alerts.py` - Alert management and deduplication
- `app_core/boundaries.py` - Spatial geometry processing
- PostgreSQL + PostGIS - Data persistence and spatial queries

```mermaid
sequenceDiagram
    participant NOAA as NOAA/IPAWS<br>CAP Feed
    participant Poller as CAP Poller<br>cap_poller.py
    participant Parser as XML Parser<br>parse_cap_xml()
    participant AlertMgr as Alert Manager<br>alerts.py
    participant DB as PostgreSQL<br>+ PostGIS
    participant Spatial as Spatial Engine<br>boundaries.py
    participant WebUI as Web UI<br>Dashboard

    Note over Poller: Polling interval triggered

    Poller->>NOAA: HTTP GET CAP feed
    NOAA-->>Poller: CAP XML document

    Poller->>Parser: Parse CAP XML
    Parser->>Parser: Validate schema
    Parser->>Parser: Extract alert data
    Parser->>Parser: Parse geometry (polygon/circle/SAME)

    alt Invalid XML or Schema
        Parser-->>Poller: Validation error
        Poller->>Poller: Log error, skip alert
    else Valid CAP
        Parser-->>Poller: Parsed alert data

        Poller->>AlertMgr: save_cap_alert(alert_data)
        AlertMgr->>AlertMgr: Check duplicate by identifier

        alt Duplicate found
            AlertMgr->>AlertMgr: Compare msgType priority
            Note right of AlertMgr: CANCEL > UPDATE > ALERT

            alt Lower priority
                AlertMgr-->>Poller: Skip (duplicate)
            else Higher priority
                AlertMgr->>DB: UPDATE cap_alerts SET...
                DB-->>AlertMgr: Updated
            end
        else New alert
            AlertMgr->>DB: INSERT INTO cap_alerts
            DB-->>AlertMgr: alert_id

            alt Has geometry
                AlertMgr->>Spatial: process_geometry(alert_id, geom)
                Spatial->>Spatial: ST_SetSRID(geom, 4326)
                Spatial->>Spatial: ST_IsValid(geom)

                alt Invalid geometry
                    Spatial->>Spatial: ST_MakeValid(geom)
                end

                Spatial->>DB: ST_Intersects query
                Note right of Spatial: Find intersecting boundaries
                DB-->>Spatial: Intersection results

                loop For each intersection
                    Spatial->>Spatial: Calculate intersection area
                    Spatial->>DB: INSERT INTO intersections
                end

                Spatial-->>AlertMgr: Spatial processing complete
            end

            AlertMgr->>DB: UPDATE alert status = 'processed'
            AlertMgr-->>Poller: Alert saved successfully
        end
    end

    Poller->>DB: INSERT INTO poll_history
    Note right of Poller: Log poll stats

    DB->>WebUI: Notify new alert available
    WebUI->>WebUI: Refresh dashboard

    Note over Poller,WebUI: Alert now available for broadcast
```

**Data Transformations:**
1. **CAP XML → Parsed dictionary** (XML parsing)
2. **Geometry string → PostGIS geometry** (ST_SetSRID, validation)
3. **Geometry → Intersection records** (ST_Intersects, area calculation)
4. **Alert data → Database record** (CAPAlert model)

**Files:** `poller/cap_poller.py:2166`, `app_core/alerts.py`, `app_core/boundaries.py`

---

## SDR Continuous Monitoring Data Flow

This sequence shows how SDR receivers continuously capture RF signals, convert them to audio samples, and monitor signal quality.

**Key Components:**
- `app_core/radio/manager.py` - Radio coordinator
- `app_core/radio/drivers.py` - SoapySDR device wrappers
- SoapySDR library - Hardware abstraction layer

```mermaid
sequenceDiagram
    participant RF as RF Signal<br>(162.400 MHz)
    participant Device as SDR Device<br>(RTL-SDR/Airspy)
    participant Driver as SoapySDR Driver<br>drivers.py
    participant Manager as Radio Manager<br>manager.py
    participant DB as Database<br>receiver_status
    participant WebUI as Web UI<br>Monitoring

    Note over Manager: System startup

    Manager->>Manager: configure_receivers()
    Manager->>Driver: RTLSDRReceiver.create()
    Driver->>Device: SoapySDR.Device(driver='rtlsdr')
    Device-->>Driver: Device handle

    Driver->>Driver: Setup stream params
    Note right of Driver: Format: CF32 (complex float32)<br>Sample rate: 228 kHz

    Driver->>Device: setupStream(SOAPY_SDR_RX, SOAPY_SDR_CF32)
    Device-->>Driver: Stream handle

    Manager->>Driver: start()
    Driver->>Device: activateStream()
    Device-->>Driver: Stream active

    Driver->>Driver: Start _capture_loop() thread

    loop Continuous monitoring
        RF->>Device: RF energy
        Device->>Device: ADC sampling
        Device->>Device: Digital downconversion
        Device->>Device: I/Q demodulation

        Driver->>Device: readStream(buffer, timeout)
        Device-->>Driver: IQ samples (complex float32[])

        Driver->>Driver: Calculate signal power
        Note right of Driver: power = np.mean(np.abs(samples)**2)

        Driver->>Driver: Calculate SNR
        Note right of Driver: SNR = 10 * log10(signal/noise)

        Driver->>Driver: Update lock status
        Note right of Driver: locked = power > threshold

        alt Capture requested
            Manager->>Driver: capture_to_file(duration, format)
            Driver->>Driver: Create _CaptureTicket

            loop Until duration met
                Driver->>Driver: Feed samples to ticket

                alt Format: IQ
                    Driver->>Driver: Write complex64 samples
                else Format: PCM
                    Driver->>Driver: Demodulate to audio
                    Driver->>Driver: Write float32 PCM
                end
            end

            Driver->>Driver: Close file, finalize
            Driver-->>Manager: Capture file path
        end

        Driver->>Manager: Update status metrics
        Manager->>Manager: _update_status()
        Manager->>DB: UPDATE radio_receiver_status
        Note right of Manager: Signal strength, lock, errors

        DB->>WebUI: Status change notification
        WebUI->>WebUI: Update receiver indicators
    end

    Note over Driver,Manager: Runs continuously until stop()
```

**Data Transformations:**
1. **RF energy → ADC samples** (Hardware ADC)
2. **ADC samples → I/Q samples** (Digital downconversion)
3. **I/Q samples → Complex float32** (SoapySDR format conversion)
4. **I/Q samples → Audio PCM** (FM demodulation for PCM format)
5. **Samples → Power/SNR metrics** (Statistical calculations)

**Files:** `app_core/radio/manager.py:233`, `app_core/radio/drivers.py:408`

---

## Multi-Source Audio Ingest Data Flow

This sequence shows how audio data from multiple sources (SDR, ALSA, PulseAudio, streams) flows through adapters into a unified audio controller.

**Key Components:**
- `app_core/audio/sources.py` - Source adapter implementations
- `app_core/audio/ingest.py` - AudioIngestController
- `app_core/audio/metering.py` - Audio level monitoring

```mermaid
sequenceDiagram
    participant Sources as Audio Sources<br>(SDR/ALSA/Stream/File)
    participant Adapters as Source Adapters<br>sources.py
    participant Controller as Audio Controller<br>ingest.py
    participant Meter as Audio Meter<br>metering.py
    participant Buffer as Audio Buffer<br>Queue
    participant Consumer as Audio Consumer<br>(Broadcast/Monitor)
    participant DB as Database<br>Metrics

    Note over Controller: System startup

    Controller->>Controller: start_all()

    par Start all sources
        Controller->>Adapters: SDRSourceAdapter.start()
        Controller->>Adapters: ALSASourceAdapter.start()
        Controller->>Adapters: StreamSourceAdapter.start()
        Controller->>Adapters: FileSourceAdapter.start()
    end

    loop Each adapter capture loop
        Adapters->>Adapters: Start _capture_loop() thread
    end

    loop Continuous audio ingestion
        par SDR Source
            Sources->>Adapters: SDR: PCM audio from RadioManager
            Adapters->>Adapters: Validate format (float32, 24kHz)
        and ALSA Source
            Sources->>Adapters: ALSA: Read from hw:X,Y device
            Adapters->>Adapters: Convert to PCM float32
        and Stream Source
            Sources->>Adapters: HTTP Stream: Read chunks
            Adapters->>Adapters: Decode (MP3/AAC → PCM)
            Adapters->>Adapters: Resample to 24kHz
        and File Source
            Sources->>Adapters: File: Read WAV/MP3
            Adapters->>Adapters: Decode and convert
        end

        Adapters->>Adapters: _read_audio_chunk()
        Note right of Adapters: Standardize to PCM float32

        Adapters->>Controller: Audio chunk ready
        Controller->>Controller: Priority selection
        Note right of Controller: Priority order:<br>1. SDR (highest)<br>2. ALSA<br>3. PulseAudio<br>4. Stream<br>5. File (lowest)

        Controller->>Controller: Select highest priority active source
        Controller->>Meter: process_chunk(audio_data)

        Meter->>Meter: Calculate peak level
        Note right of Meter: peak_db = 20*log10(max(abs(samples)))

        Meter->>Meter: Calculate RMS level
        Note right of Meter: rms_db = 20*log10(sqrt(mean(samples²)))

        Meter->>Meter: Detect silence
        Note right of Meter: silence = rms_db < threshold

        alt Silence detected
            Meter->>DB: INSERT INTO audio_alerts
            Note right of Meter: Log silence event
        end

        Meter->>Meter: Calculate health score
        Note right of Meter: Score based on:<br>- Signal level<br>- Stability<br>- Error rate

        Meter->>Controller: Metrics (peak, rms, health)
        Controller->>DB: INSERT INTO audio_source_metrics

        Controller->>Buffer: enqueue(audio_chunk)
        Buffer->>Consumer: dequeue()

        Consumer->>Consumer: Process audio
        Note right of Consumer: Broadcast, monitor,<br>or analysis
    end

    Note over Sources,DB: Continuous flow until stop()
```

**Data Transformations:**
1. **Raw audio → PCM float32** (Format conversion)
2. **Variable sample rate → 24 kHz** (Resampling)
3. **PCM samples → dB levels** (Peak/RMS calculation)
4. **Levels → Health score** (Health algorithm)
5. **Audio chunks → Buffer queue** (Priority selection)

**Files:** `app_core/audio/ingest.py:356`, `app_core/audio/sources.py:~500`, `app_core/audio/metering.py`

---

## Radio Capture Coordination Data Flow

This sequence shows how EAS broadcasts trigger coordinated radio captures across all receivers for verification.

**Key Components:**
- `app_utils/eas.py` - EASBroadcaster
- `app_core/radio/manager.py` - Radio capture coordinator
- `app_core/radio/drivers.py` - Individual receiver drivers

```mermaid
sequenceDiagram
    participant Broadcast as EAS Broadcast<br>eas.py
    participant Manager as Radio Manager<br>manager.py
    participant Receiver1 as Receiver 1<br>(162.400 MHz)
    participant Receiver2 as Receiver 2<br>(162.550 MHz)
    participant Device1 as SDR Device 1
    participant Device2 as SDR Device 2
    participant Storage as File Storage<br>captures/
    participant DB as Database<br>receiver_status

    Note over Broadcast: EAS message ready to transmit

    Broadcast->>Broadcast: Build audio file
    Broadcast->>Manager: request_captures(duration=60s)

    Manager->>Manager: Get all enabled receivers

    par Coordinate captures
        Manager->>Receiver1: capture_to_file(60s, 'pcm')
        Receiver1->>Receiver1: Create _CaptureTicket
        Note right of Receiver1: Target samples = 60s * 24000 Hz

        Receiver1->>Receiver1: Set ticket in _capture_ticket

        and

        Manager->>Receiver2: capture_to_file(60s, 'pcm')
        Receiver2->>Receiver2: Create _CaptureTicket
        Receiver2->>Receiver2: Set ticket in _capture_ticket
    end

    Note over Broadcast: Start transmission
    Broadcast->>Broadcast: Key transmitter (GPIO)
    Broadcast->>Broadcast: Play audio file

    loop Capture loop for Receiver 1
        Device1->>Receiver1: IQ samples from readStream()
        Receiver1->>Receiver1: Check if _capture_ticket exists

        alt Ticket active
            Receiver1->>Receiver1: Demodulate IQ → PCM audio
            Receiver1->>Receiver1: Feed samples to ticket
            Receiver1->>Receiver1: Check sample count

            alt Target samples reached
                Receiver1->>Receiver1: Finalize capture
                Receiver1->>Storage: Write WAV file
                Note right of Receiver1: captures/rx1_20250105_143022.wav
                Storage-->>Receiver1: File path
                Receiver1->>Receiver1: Clear _capture_ticket
            end
        end
    end

    loop Capture loop for Receiver 2
        Device2->>Receiver2: IQ samples from readStream()
        Receiver2->>Receiver2: Check if _capture_ticket exists

        alt Ticket active
            Receiver2->>Receiver2: Demodulate IQ → PCM audio
            Receiver2->>Receiver2: Feed samples to ticket
            Receiver2->>Receiver2: Check sample count

            alt Target samples reached
                Receiver2->>Receiver2: Finalize capture
                Receiver2->>Storage: Write WAV file
                Note right of Receiver2: captures/rx2_20250105_143022.wav
                Storage-->>Receiver2: File path
                Receiver2->>Receiver2: Clear _capture_ticket
            end
        end
    end

    par Wait for completions
        Receiver1-->>Manager: Capture 1 complete, file path
        and
        Receiver2-->>Manager: Capture 2 complete, file path
    end

    Manager->>Manager: _record_receiver_statuses()

    loop For each receiver
        Manager->>DB: INSERT INTO radio_receiver_status
        Note right of Manager: Capture metadata:<br>- File path<br>- Signal strength<br>- Lock status<br>- Duration
    end

    Manager-->>Broadcast: All captures complete

    Broadcast->>Broadcast: Unkey transmitter
    Broadcast->>DB: UPDATE eas_messages SET verified=true

    Note over Broadcast,DB: Captures ready for verification
```

**Data Transformations:**
1. **Capture request → _CaptureTicket** (Ticket creation)
2. **IQ samples → PCM audio** (FM demodulation)
3. **PCM samples → WAV file** (File writing)
4. **Capture metadata → Database record** (Status recording)

**Files:** `app_utils/eas.py:1076`, `app_core/radio/manager.py:233`, `app_core/radio/drivers.py:408`

---

## EAS Message Generation Data Flow

This sequence shows the complete data flow for generating an EAS message from alert selection through SAME encoding to final audio file.

**Key Components:**
- `app_utils/eas.py` - EASBroadcaster and SAME generation
- `app_utils/eas_fsk.py` - FSK encoding
- `app_utils/eas_tts.py` - Text-to-speech providers

```mermaid
sequenceDiagram
    participant Operator as Operator<br>Web UI
    participant Workflow as EAS Workflow<br>eas.py
    participant SAME as SAME Generator<br>build_same_header()
    participant FSK as FSK Encoder<br>eas_fsk.py
    participant TTS as TTS Provider<br>eas_tts.py
    participant Audio as Audio Builder<br>build_files()
    participant Storage as File Storage<br>static/audio/
    participant DB as Database<br>eas_messages

    Operator->>Workflow: Submit EAS form
    Note right of Operator: Event: TOR<br>Areas: SAME codes<br>Duration: 30 min

    Workflow->>Workflow: Validate input
    Workflow->>SAME: build_same_header(event, areas, duration)

    SAME->>SAME: Build components
    Note right of SAME: ORG-EEE-PSSCCC+TTTT-JJJHHMM-LLLLLLLL

    SAME->>SAME: Format ORG (originator)
    Note right of SAME: 'EAS' for EAS Participant

    SAME->>SAME: Format EEE (event code)
    Note right of SAME: 'TOR' → Tornado Warning

    SAME->>SAME: Format PSSCCC (location codes)
    Note right of SAME: Multiple SAME codes:<br>055079+055081+055083

    SAME->>SAME: Format TTTT (duration)
    Note right of SAME: 30 min → '0030'

    SAME->>SAME: Format JJJHHMM (timestamp)
    Note right of SAME: Julian day + time

    SAME->>SAME: Format LLLLLLLL (station ID)
    Note right of SAME: From configuration

    SAME->>SAME: Assemble complete header
    Note right of SAME: "ZCZC-EAS-TOR-055079+0030-0051430-KEAX/NWS"

    SAME-->>Workflow: SAME header string

    Workflow->>FSK: encode_same_fsk(header)

    FSK->>FSK: Generate preamble
    Note right of FSK: 16 bytes of 0xAB<br>(alternating 1010 1011)

    FSK->>FSK: Encode ASCII to FSK
    Note right of FSK: MARK: 2083 Hz (binary 1)<br>SPACE: 1563 Hz (binary 0)<br>Baud: 520.83 Hz

    loop For each character
        FSK->>FSK: Get ASCII byte
        FSK->>FSK: Convert to 8 bits

        loop For each bit
            alt Bit = 1
                FSK->>FSK: Generate MARK tone (2083 Hz)
            else Bit = 0
                FSK->>FSK: Generate SPACE tone (1563 Hz)
            end
        end
    end

    FSK-->>Workflow: FSK audio buffer (header)

    Workflow->>Workflow: Generate attention tone
    Note right of Workflow: 853 Hz + 960 Hz<br>Duration: 8 seconds

    alt Narration enabled
        Workflow->>TTS: generate_speech(message_text)
        TTS->>TTS: Call TTS provider API
        Note right of TTS: Azure/OpenAI/pyttsx3
        TTS->>TTS: Receive audio stream
        TTS->>TTS: Convert to PCM float32
        TTS-->>Workflow: TTS audio buffer
    end

    Workflow->>FSK: encode_eom()
    Note right of FSK: "NNNN" × 3
    FSK-->>Workflow: EOM audio buffer

    Workflow->>Audio: build_files(components)

    Audio->>Audio: Concatenate segments
    Note right of Audio: Order:<br>1. SAME header × 3<br>2. Attention tone<br>3. TTS narration (optional)<br>4. EOM × 3<br>5. 1s silence

    Audio->>Audio: Normalize audio levels
    Audio->>Audio: Apply fade in/out
    Audio->>Storage: Write WAV file
    Note right of Storage: eas_20250105_143022.wav

    Storage-->>Audio: File path
    Audio-->>Workflow: Complete audio file path

    Workflow->>DB: INSERT INTO eas_messages
    Note right of Workflow: Store:<br>- SAME header<br>- Audio path<br>- CAP alert ID<br>- Timestamp

    DB-->>Workflow: message_id

    Workflow-->>Operator: Success + audio player
```

**Data Transformations:**
1. **Form input → SAME header string** (String formatting)
2. **SAME header → ASCII bytes** (Text encoding)
3. **ASCII bytes → FSK audio** (Frequency-shift keying)
4. **Text message → TTS audio** (Text-to-speech synthesis)
5. **Audio segments → Complete WAV file** (Audio concatenation)
6. **WAV file → Database record** (Metadata persistence)

**Files:** `app_utils/eas.py:1076`, `app_utils/eas_fsk.py`, `app_utils/eas_tts.py`

---

## Complete Alert-to-Broadcast Pipeline

This sequence shows the end-to-end data flow from CAP alert fetch to broadcast transmission and verification.

**Key Components:** All major system components involved in complete pipeline

```mermaid
sequenceDiagram
    participant NOAA as NOAA<br>CAP Feed
    participant Poller as CAP Poller<br>cap_poller.py
    participant DB as Database<br>PostgreSQL
    participant WebUI as Web UI<br>Dashboard
    participant Operator as Operator
    participant EAS as EAS Broadcaster<br>eas.py
    participant GPIO as GPIO Controller
    participant TX as Transmitter
    participant Radio as Radio Manager
    participant SDR as SDR Receivers
    participant Verify as Verification<br>System

    Note over NOAA,Poller: 1. Alert Ingestion Phase

    Poller->>NOAA: Poll for CAP alerts
    NOAA-->>Poller: CAP XML feed
    Poller->>Poller: Parse and validate
    Poller->>Poller: Check relevance (UGC codes)
    Poller->>DB: Store CAPAlert
    Poller->>DB: Calculate spatial intersections
    DB-->>Poller: Alert saved

    Note over DB,WebUI: 2. Alert Presentation Phase

    DB->>WebUI: New alert notification
    WebUI->>WebUI: Refresh alerts dashboard
    WebUI-->>Operator: Display new alert

    Operator->>Operator: Review alert details
    Operator->>Operator: Decide to broadcast

    Note over Operator,EAS: 3. EAS Generation Phase

    Operator->>WebUI: Click "Broadcast EAS"
    WebUI->>EAS: handle_alert(cap_alert_id)

    EAS->>DB: SELECT * FROM cap_alerts WHERE id=?
    DB-->>EAS: Alert data

    EAS->>EAS: build_same_header()
    EAS->>EAS: Generate FSK encoding
    EAS->>EAS: Generate attention tone

    alt Narration enabled
        EAS->>EAS: Generate TTS narration
    end

    EAS->>EAS: Generate EOM
    EAS->>EAS: Concatenate audio
    EAS->>EAS: Save WAV file

    EAS->>DB: INSERT INTO eas_messages
    DB-->>EAS: message_id

    Note over EAS,Radio: 4. Capture Coordination Phase

    EAS->>Radio: request_captures(duration=60s)

    par Start all captures
        Radio->>SDR: Receiver 1: capture_to_file()
        Radio->>SDR: Receiver 2: capture_to_file()
        Radio->>SDR: Receiver N: capture_to_file()
    end

    SDR->>SDR: Start recording to buffers

    Note over EAS,TX: 5. Broadcast Phase

    EAS->>GPIO: Key transmitter (relay on)
    GPIO->>TX: PTT active
    TX->>TX: Carrier on

    EAS->>EAS: Play audio file
    EAS->>EAS: Stream audio to output

    Note over TX,SDR: 6. Reception Phase

    TX->>SDR: RF transmission (162.4 MHz)

    par All receivers capturing
        SDR->>SDR: Receiver 1: Record samples
        SDR->>SDR: Receiver 2: Record samples
        SDR->>SDR: Receiver N: Record samples
    end

    EAS->>EAS: Audio playback complete
    EAS->>GPIO: Unkey transmitter (relay off)
    GPIO->>TX: PTT inactive
    TX->>TX: Carrier off

    par Finalize captures
        SDR->>SDR: Receiver 1: Save WAV file
        SDR->>SDR: Receiver 2: Save WAV file
        SDR->>SDR: Receiver N: Save WAV file
    end

    SDR-->>Radio: All capture files ready

    Radio->>DB: INSERT INTO radio_receiver_status
    Note right of Radio: Record capture metadata

    Radio-->>EAS: Captures complete

    Note over Radio,Verify: 7. Verification Phase

    Radio->>Verify: Submit capture files
    Verify->>Verify: Decode SAME headers
    Verify->>Verify: Compare with transmitted

    alt Headers match
        Verify->>DB: UPDATE eas_messages SET verified=true
        Verify->>DB: INSERT INTO verifications (success)
    else Headers mismatch
        Verify->>DB: INSERT INTO verifications (failure)
        Verify->>WebUI: Alert operator of mismatch
    end

    Note over WebUI,Operator: 8. Reporting Phase

    WebUI->>DB: Query verification results
    DB-->>WebUI: Verification records
    WebUI-->>Operator: Display verification report

    Note over NOAA,Operator: Complete pipeline: ~60-120 seconds
```

**Complete Data Path:**
1. **CAP XML** (NOAA) → **CAPAlert record** (Database)
2. **CAPAlert** → **SAME header string** (EAS Generator)
3. **SAME header** → **FSK audio** (FSK Encoder)
4. **FSK + TTS + Tones** → **Complete WAV file** (Audio Builder)
5. **WAV file** → **RF signal** (Transmitter)
6. **RF signal** → **IQ samples** (SDR Receivers)
7. **IQ samples** → **Demodulated audio** (FM Demodulator)
8. **Demodulated audio** → **Decoded SAME header** (Verification)
9. **Decoded vs. Original** → **Verification record** (Database)

**Timeline:** Complete flow typically takes 60-120 seconds from alert fetch to verified broadcast.

**Files:** Multiple components across entire codebase

---

## Summary

These sequence diagrams illustrate the major data processing paths through the EAS Station system:

1. **Alert Processing** - CAP alerts flow from external sources through validation and spatial processing to storage
2. **SDR Monitoring** - RF signals are continuously converted to digital samples and monitored for quality
3. **Audio Ingest** - Multiple audio sources flow through adapters into a unified controller with priority selection
4. **Radio Capture** - Broadcast triggers coordinated capture across all receivers for verification
5. **EAS Generation** - Alert data transforms through SAME encoding, FSK modulation, and audio assembly
6. **Complete Pipeline** - End-to-end flow from CAP fetch to verified broadcast

Each diagram shows:
- **Components involved** with file references
- **Data transformations** at each step
- **Decision points** and error handling
- **Timing and synchronization** between components

**Key Insights:**
- Data flows through well-defined layers with clear transformations
- Spatial processing (PostGIS) is critical for alert relevance
- Radio captures are coordinated but operate independently
- Verification closes the loop by comparing transmitted vs. received data
- The system maintains comprehensive audit trails at each stage

**Related Documentation:**
- [System Architecture](SYSTEM_ARCHITECTURE.md) - Component diagrams and relationships
- [Theory of Operation](THEORY_OF_OPERATION.md) - Conceptual overview
- [DIAGRAMS Index](../DIAGRAMS.md) - All available diagrams

---

**Last Updated:** 2025-11-05
**Diagram Count:** 6 comprehensive sequence diagrams
**Coverage:** Complete data processing paths from input to output
