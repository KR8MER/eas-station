# Hardware SAME Decoder Evaluation for EAS Station

**Created:** 2025-11-20
**Status:** Research & Planning
**Goal:** Replace software SDR decoding with dedicated hardware SAME decoder

## Executive Summary

You want **hardware-based EAS/SAME decoding** instead of software-defined radio (SDR) processing. This document evaluates off-the-shelf and custom options for integrating a dedicated hardware SAME decoder with your EAS Station.

### Current Architecture (Software-Based)

```
NOAA Weather Radio (162.4-162.55 MHz)
    ↓
RTL-SDR or Airspy (USB dongle)
    ↓
Software Demodulation (multimon-ng, DSP)
    ↓
EAS Station Python Processing
    ↓
Alert Database & Actions
```

**Problems:**
- CPU-intensive DSP processing
- Requires SDR hardware and drivers
- Software decoder complexity
- Potential false positives/negatives

### Target Architecture (Hardware-Based)

```
NOAA Weather Radio (162.4-162.55 MHz)
    ↓
Hardware SAME Decoder (Si4707 or commercial)
    ↓
I2C/Serial/GPIO Interface
    ↓
EAS Station Python Processing
    ↓
Alert Database & Actions
```

**Benefits:**
- ✅ Offload SAME decoding to dedicated hardware
- ✅ Reduced CPU usage
- ✅ More reliable (hardware FSK demodulator)
- ✅ Lower latency
- ✅ Simpler software integration

---

## Hardware Options Available

### Option 1: Silicon Labs Si4707 Chip ❌ (DISCONTINUED - Not Viable)

**What It Was:**
- Single-chip weather band receiver + SAME decoder
- Integrated FSK demodulator (520.83 baud)
- Built-in 1050Hz attention tone detector
- Digital I2C/SPI interface

**Current Status: DISCONTINUED**

The Si4707 was the **only integrated chip** with weather band receiver + hardware SAME decoder. Silicon Labs sold this division to Skyworks, and Skyworks has since **discontinued the entire Si4707 product line**.

**Availability:**
- DigiKey: ❌ Discontinued / Out of Stock
- Mouser: ❌ Discontinued / Out of Stock
- All breakout boards: ❌ Discontinued
- No replacement chip exists

**Why This Matters:**
- Si4707 was **unique** - no other chip has integrated SAME decoding
- Cannot design custom PCB (no chips available)
- Must use alternative approaches

**Value:** ❌ **Not Available** - Dead end, no longer a viable option

---

### Option 2: Commercial Weather Radio + Audio Output ⭐⭐⭐ (Pragmatic)

**Concept:** Use consumer weather radio with headphone jack as receiver

**Architecture:**
```
Consumer Weather Radio (Midland WR400, etc.)
    ↓
3.5mm headphone jack (audio output)
    ↓
USB Audio Interface or Pi audio input
    ↓
External FSK Demodulator Hardware (XR-2211, etc.)
    ↓
GPIO to Raspberry Pi
```

**Recommended Weather Radios:**

| Radio | SAME Capable | Audio Out | Price | Notes |
|-------|--------------|-----------|-------|-------|
| **Midland WR400** | ✅ Yes | ✅ Headphone | $60-80 | Popular, reliable |
| **Midland WR120** | ✅ Yes | ✅ Headphone | $30-40 | Budget option |
| **Sangean CL-100** | ✅ Yes | ✅ Headphone | $70-90 | Excellent reception |
| **Eton FRX5** | ✅ Yes | ✅ Headphone | $80-100 | Hand-crank backup |

**External FSK Demodulator Options:**

**Option 2A: XR-2211 Dual Tone Decoder**
- **Chip:** Exar XR-2211 FSK demodulator/tone decoder
- **Function:** Decodes 1562.5Hz/2083.3Hz FSK to digital levels
- **Output:** Logic levels to GPIO (mark/space)
- **Cost:** $3-5 per chip + supporting components
- **Complexity:** Moderate (analog design)

**Circuit:**
```
Audio In (3.5mm) → XR-2211 → GPIO Pin (mark/space bits)
                     ↓
                  Python software parses SAME protocol
```

**Option 2B: Software FSK Decode (defeats purpose, but simpler)**
- Audio from radio → USB audio interface → Python FSK decoder
- Still software-based, but uses dedicated radio receiver

**Value:** ⭐⭐⭐ **Good** - Pragmatic, uses off-the-shelf radio

**Pros:**
- ✅ Weather radio readily available ($30-100)
- ✅ Proven receiver performance
- ✅ Easy to replace if fails
- ✅ Can test immediately with existing software

**Cons:**
- ⚠️ Still requires FSK demodulation (hardware or software)
- ⚠️ External box (not integrated)
- ⚠️ Less elegant than Si4707 solution

---

### Option 3: Commercial EAS Equipment ⭐ (Overkill & Expensive)

**Products:**
- **DASDEC-III** (Digital Alert Systems) - $3,000-$7,000
- **Sage Digital ENDEC** - $3,000-$5,000
- **Monroe EAS Encoder/Decoder** - $2,000-$4,000
- **TFT EAS Systems** - $2,500-$6,000

**What They Offer:**
- FCC-certified EAS encoder/decoder
- Multiple input sources (EAS, CAP, weather radio)
- RS-232 serial output (decoded messages)
- Network API (some models)
- GPIO outputs for relay control
- Integrated audio routing

**Integration:**
```
Commercial EAS Box (DASDEC, etc.)
    ↓
RS-232 Serial or Ethernet API
    ↓
EAS Station (read decoded alerts)
    ↓
Custom actions (Zigbee, Hailo, etc.)
```

**Example: DASDEC-III Integration**
- Ethernet API provides decoded CAP XML
- EAS Station polls DASDEC API
- When alert received, trigger Zigbee sirens, Hailo verification, etc.
- Essentially use DASDEC as "hardware alert receiver"

**Lab Validation Workflow (DASDEC-III)**
- **Purpose:** Use a certified decoder as an oracle when qualifying the Raspberry Pi stack for FCC Part 11 submission.
- **Setup:**
  - Feed identical RF and IP inputs into both the DASDEC-III and the Pi reference build (dual SDRs + audio HAT).
  - Connect the DASDEC-III Ethernet API (or RS-232) to a capture host that archives CAP XML and syslog events.
- **Procedure:**
  - Trigger live or replayed alerts (NOAA/SAME generator) and record: Pi playout audio, DASDEC-III CAP XML, GPIO/relay activations, and timestamps.
  - Compare DASDEC-III CAP payloads and relay timing against EAS Station ingest/relay logs; investigate any header, FSK timing, or audio discrepancies.
  - Repeat under stress (multiple overlapping alerts, degraded RF) to document stability deltas.
- **Outcome:** Creates auditable evidence that the open-source stack matches a certified commercial decoder, reducing risk before scheduling a lab certification cycle.

**Value:** ⭐ **Poor** - Extremely expensive for hobbyist/amateur use

**Pros:**
- ✅ FCC-certified (if that matters for your deployment)
- ✅ Professional-grade hardware
- ✅ Comprehensive logging and compliance features
- ✅ Vendor support

**Cons:**
- ❌ **Very expensive** ($2,000-$7,000+)
- ❌ Overkill for most deployments
- ❌ Annual support/licensing fees
- ❌ Designed for broadcast stations, not DIY projects

**When to Consider:**
- Commercial broadcast station
- Budget allows $5,000+
- FCC certification required
- Liability concerns require certified equipment

---

## Custom Si4707 HAT Design (Recommended Path)

Since Si4707 modules are discontinued but chip is available, **design a custom Raspberry Pi HAT**.

### Design Specifications

**Form Factor:** Raspberry Pi HAT (65mm × 56mm)

**Key Features:**
- Si4707 weather band receiver + SAME decoder
- I2C interface to Raspberry Pi GPIO
- SMA antenna connector
- 3.5mm audio jack (for monitoring/recording)
- GPIO interrupt output (alert detection)
- LED indicators (power, signal, alert)
- EEPROM for HAT identification

**Schematic Overview:**

```
Raspberry Pi 40-pin GPIO Header
    ↑ (I2C, Power, Interrupt)
    |
[Si4707 IC]
    |
    ├─→ SMA Antenna Connector
    ├─→ 3.5mm Audio Jack (AFE)
    ├─→ LED Indicators
    └─→ Crystal Oscillator (32.768 kHz)
```

**Major Components:**
1. **Si4707-B20-GM** - Main IC ($4-6)
2. **32.768 kHz Crystal** - Reference clock ($1)
3. **50Ω SMA Connector** - Antenna ($2)
4. **Audio Codec** - For 3.5mm jack ($3-5)
5. **Level Shifters** - I2C voltage translation if needed ($1)
6. **Passives** - Resistors, capacitors, inductors ($5-10)
7. **PCB** - 4-layer recommended ($50-100 for 5 boards)

**Total BOM Cost:** ~$20-30 per board (in quantities of 5-10)

### Development Roadmap

**Phase 1: Schematic Design (1-2 weeks)**
- [ ] Study Si4707 datasheet and reference design
- [ ] Design power supply (3.3V LDO)
- [ ] Design antenna matching network
- [ ] I2C interface to Raspberry Pi
- [ ] Audio output circuit
- [ ] LED indicators and user interface

**Phase 2: PCB Layout (1-2 weeks)**
- [ ] Create PCB layout (4-layer)
- [ ] Careful RF layout (antenna traces, ground planes)
- [ ] I2C routing to Pi header
- [ ] Generate Gerber files

**Phase 3: Fabrication (2-3 weeks)**
- [ ] Order PCBs (JLCPCB, OSH Park, or PCBWay)
- [ ] Order components (DigiKey, Mouser)
- [ ] PCB assembly (hand assembly or PCBA service)

**Phase 4: Firmware Development (2-3 weeks)**
- [ ] Python library for Si4707 I2C control
- [ ] Tune to weather channel
- [ ] Read SAME messages from chip
- [ ] Parse and format for EAS Station
- [ ] Test with real weather alerts

**Phase 5: Integration with EAS Station (1-2 weeks)**
- [ ] Replace SDR polling with Si4707 polling
- [ ] Update alert processing pipeline
- [ ] Testing and validation
- [ ] Documentation

**Total Timeline:** 8-12 weeks from start to production

**Total Cost:**
- Initial prototype: $200-400 (PCBs + components + shipping)
- Small production run (10 boards): $300-600
- Per-unit cost at scale: $20-30

---

## Alternative: FPGA-Based SAME Decoder (Advanced)

**Concept:** Implement SAME FSK decoder in FPGA hardware

**Hardware:**
- FPGA development board (Lattice iCE40, Xilinx Artix, etc.)
- ADC for audio input
- GPIO interface to Raspberry Pi

**Advantages:**
- ✅ Fully customizable
- ✅ Can add advanced features (multi-channel, error correction)
- ✅ Learning opportunity

**Disadvantages:**
- ❌ Requires FPGA expertise (Verilog/VHDL)
- ❌ More expensive development boards ($50-200)
- ❌ Longer development time (3-6 months)
- ❌ Still need external receiver for RF

**Recommendation:** ❌ **Not recommended** - Too complex for marginal benefit

---

## Comparison Matrix

| Option | Cost | Complexity | Availability | Performance | Value |
|--------|------|-----------|--------------|-------------|-------|
| **Si4707 Module (if available)** | $40-60 | Low | ❌ None | Excellent | N/A |
| **Custom Si4707 HAT** | $200-400 initial | High | ✅ DIY | Excellent | ⭐⭐⭐⭐⭐ |
| **Weather Radio + XR-2211** | $50-120 | Medium | ✅ Easy | Good | ⭐⭐⭐⭐ |
| **Weather Radio + Software** | $30-100 | Low | ✅ Easy | Good | ⭐⭐⭐ |
| **Commercial EAS (DASDEC)** | $3,000-$7,000 | Low | ✅ Vendor | Excellent | ⭐ |
| **FPGA Custom Design** | $200-500 | Very High | ✅ DIY | Excellent | ⭐⭐ |

---

## Recommended Implementation Path

### **UPDATED: Si4707 is NLA - Weather Radio is Only Viable Option**

Since the Si4707 chip is discontinued with no replacement, **commercial weather radio + audio interface** is the only practical hardware solution.

### Immediate Term (This Week): Weather Radio + Audio ⭐⭐⭐⭐ RECOMMENDED

**Hardware:**
1. Purchase Midland WR400 weather radio ($60-80) - **Amazon has it**
2. 3.5mm aux cable ($5)
3. USB audio interface ($20-50) OR use Pi audio input

**Software:**
1. Connect radio audio output to Pi
2. Use existing software FSK decoder initially
3. Test and validate with real alerts

**Time:** 1-2 days to set up and test
**Cost:** $85-135
**Benefit:** Immediate hardware receiver, proven approach

---

### Medium Term (Optional): Hardware FSK Decoder

**If you want to offload FSK decoding from software:**

Build XR-2211 FSK demodulator circuit:
- Takes audio from weather radio
- Outputs digital levels (mark/space) to GPIO
- Python reads GPIO bits and parses SAME protocol

**Cost:** $10-20 (XR-2211 chip + passive components)
**Complexity:** Moderate (analog circuit design)
**Benefit:** Offloads FSK demodulation to hardware

---

### Long Term: No Integrated Solution Available

**Reality Check:**
- ❌ Si4707 chip discontinued (was the only integrated solution)
- ❌ No replacement chip exists
- ❌ Custom PCB not viable without chips
- ✅ Weather radio + audio is the practical long-term solution

**Alternatives:**
1. Continue with weather radio + audio (works well)
2. Upgrade to commercial EAS equipment ($3,000-$7,000)
3. Hope for new integrated chip (unlikely - small market)

---

## Software Integration

### Current Software Architecture

From your EAS Station codebase:

```python
# poller/cap_poller.py - Current SDR-based approach
def monitor_weather_radio_sdr():
    """Monitor weather radio using RTL-SDR."""
    # Start rtl_fm or similar
    # Pipe audio to multimon-ng
    # Parse SAME output
    # Process alerts
```

### Hardware Si4707 Integration

**New Module:** `app_core/hardware/si4707.py`

```python
"""Si4707 hardware SAME decoder interface."""

import smbus2
import time
from dataclasses import dataclass
from typing import Optional

# I2C address for Si4707
SI4707_I2C_ADDR = 0x11

@dataclass
class SAMEMessage:
    """Parsed SAME message from Si4707."""
    originator: str  # WXR, CIV, EAS, etc.
    event_code: str  # TOR, SVR, FFW, etc.
    location_codes: list[str]  # FIPS codes
    valid_time: str  # TTTT (valid time period)
    issue_time: str  # JJJHHMM (Julian date + time)
    sender_callsign: str  # CCCCCCCC (8 char)
    raw_message: str  # Full ZCZC string

class Si4707Decoder:
    """Hardware SAME decoder using Silicon Labs Si4707."""

    def __init__(self, i2c_bus=1, i2c_addr=SI4707_I2C_ADDR):
        """Initialize Si4707 over I2C.

        Args:
            i2c_bus: I2C bus number (1 for Pi)
            i2c_addr: I2C device address
        """
        self.bus = smbus2.SMBus(i2c_bus)
        self.addr = i2c_addr
        self._initialize_chip()

    def _initialize_chip(self):
        """Power up and configure Si4707."""
        # Power up command
        self.bus.write_i2c_block_data(
            self.addr, 0x01, [0x00, 0xB5]
        )
        time.sleep(0.5)  # Wait for power-up

        # Set WB frequency (162.550 MHz - WX7)
        freq = 16255  # 162.55 MHz in 10kHz units
        self.bus.write_i2c_block_data(
            self.addr, 0x50, [
                0x00,  # Reserved
                (freq >> 8) & 0xFF,  # Freq high
                freq & 0xFF,  # Freq low
                0x00,  # Reserved
            ]
        )

        # Enable SAME interrupt
        self.bus.write_i2c_block_data(
            self.addr, 0x55, [0x00, 0x01]  # SAME interrupt enable
        )

    def poll_for_alert(self) -> Optional[SAMEMessage]:
        """Check if SAME alert is available.

        Returns:
            SAMEMessage if alert received, None otherwise
        """
        # Read SAME status register
        status = self.bus.read_i2c_block_data(self.addr, 0x54, 4)

        same_status = status[1]
        if same_status & 0x01:  # SAME message available
            # Read SAME message from buffer
            raw_data = self.bus.read_i2c_block_data(
                self.addr, 0x56, 256
            )

            # Parse SAME message
            raw_message = bytes(raw_data).decode('ascii', errors='ignore')
            return self._parse_same_message(raw_message)

        return None

    def _parse_same_message(self, raw: str) -> SAMEMessage:
        """Parse SAME message string.

        Format: ZCZC-ORG-EEE-PSSCCC+TTTT-JJJHHMM-CCCCCCCC-

        Args:
            raw: Raw SAME message string

        Returns:
            Parsed SAMEMessage object
        """
        # Example: ZCZC-WXR-TOR-039173+0045-0121415-WTIR/NWS-
        parts = raw.strip().split('-')

        return SAMEMessage(
            originator=parts[1] if len(parts) > 1 else "",
            event_code=parts[2] if len(parts) > 2 else "",
            location_codes=parts[3].split('+')[0].split('-') if len(parts) > 3 else [],
            valid_time=parts[3].split('+')[1] if '+' in parts[3] else "",
            issue_time=parts[4] if len(parts) > 4 else "",
            sender_callsign=parts[5] if len(parts) > 5 else "",
            raw_message=raw,
        )

    def get_signal_quality(self) -> dict:
        """Get receiver signal quality metrics.

        Returns:
            dict with RSSI and SNR
        """
        # Read RSQ (Received Signal Quality) status
        rsq = self.bus.read_i2c_block_data(self.addr, 0x23, 8)

        return {
            "rssi": rsq[4] - 128,  # dBµV
            "snr": rsq[5],  # dB
            "freq_offset": (rsq[7] << 8) | rsq[6],  # kHz offset
        }


# Integration with EAS Station alert poller
def hardware_same_poller():
    """Main polling loop for hardware Si4707 decoder."""
    decoder = Si4707Decoder()

    while True:
        # Check for alerts
        message = decoder.poll_for_alert()

        if message:
            logger.info(
                "HARDWARE SAME ALERT: %s %s for %s",
                message.event_code,
                message.originator,
                message.location_codes,
            )

            # Process alert through existing EAS Station pipeline
            process_same_alert(message)

        # Check signal quality periodically
        signal = decoder.get_signal_quality()
        if signal["rssi"] < -100:
            logger.warning("Weak signal: RSSI %d dBµV", signal["rssi"])

        time.sleep(1)  # Poll every second
```

**Integration Point:** Replace SDR monitoring with Si4707 polling in `poller/cap_poller.py`

---

## Decision Matrix

### Choose Custom Si4707 HAT if:
- ✅ You want the most elegant hardware solution
- ✅ Someone can design PCB (or budget to hire designer)
- ✅ Budget allows $200-400 for prototype
- ✅ Timeline allows 8-12 weeks
- ✅ You enjoy hardware projects

### Choose Weather Radio + Audio if:
- ✅ You want something working immediately
- ✅ Budget is limited ($50-120)
- ✅ Don't want to design custom hardware
- ✅ Acceptable to have external weather radio

### Stick with Current SDR if:
- ✅ Current solution works well enough
- ✅ Don't want hardware project complexity
- ✅ Budget better spent on Zigbee/Cellular/Hailo
- ✅ Software flexibility more important than hardware

---

## My Recommendation

**Phase 1 (Immediate):** Buy Midland WR400 weather radio → audio output → validate
**Phase 2 (3-6 months):** Design custom Si4707 HAT for clean integration
**Phase 3 (1+ year):** Small production run, open-source design

**Reasoning:**
1. Weather radio gives immediate hardware decoding
2. Validates approach and integration
3. Si4707 HAT provides elegant long-term solution
4. Open-source benefits entire community

**Would you like me to:**
1. Create detailed Si4707 HAT schematic design?
2. Write complete integration code for weather radio?
3. Research additional hardware options?

---

**Document Status:** Research Complete - Ready for Decision
**Last Updated:** 2025-11-20
**Maintainer:** Claude (AI Assistant)
