# Reference Raspberry Pi Build Guide

## Overview

This document describes the reference hardware configuration for deploying EAS Station on Raspberry Pi single-board computers. This build is designed to provide a complete, drop-in replacement for commercial EAS encoder/decoder hardware suitable for broadcast station deployments.

## Supported Raspberry Pi Models

### Recommended Models

| Model | CPU | RAM | Status | Notes |
|-------|-----|-----|--------|-------|
| **Raspberry Pi 5 (8GB)** | 2.4GHz Quad-core ARM Cortex-A76 | 8GB | ✅ Recommended | Best performance, PCIe slot for M.2 storage |
| **Raspberry Pi 4 Model B (8GB)** | 1.8GHz Quad-core ARM Cortex-A72 | 8GB | ✅ Recommended | Excellent balance of performance and cost |
| **Raspberry Pi 4 Model B (4GB)** | 1.8GHz Quad-core ARM Cortex-A72 | 4GB | ✅ Supported | Suitable for moderate deployments |

### Minimum Requirements

- **CPU**: Quad-core ARM Cortex-A72 or better
- **RAM**: 4GB minimum, 8GB recommended
- **Storage**: 32GB microSD minimum, SSD strongly recommended
- **USB Ports**: 2× USB 3.0 for SDR and audio hardware
- **Networking**: Gigabit Ethernet (Wi-Fi not recommended for production)

### Not Recommended

- Raspberry Pi 3 and earlier models (insufficient CPU/RAM for real-time audio processing)
- Raspberry Pi Zero models (single-core, limited USB)
- Compute Module without proper carrier board

## Storage Configuration

### MicroSD Card (Basic Deployment)

**Minimum Specifications:**
- Capacity: 32GB minimum, 64GB recommended
- Speed Class: UHS-I U3 (minimum 30MB/s write)
- Application Performance Class: A2 preferred
- Endurance: High-endurance or industrial-grade cards recommended

**Recommended Cards:**
- SanDisk Extreme Pro (A2, 170MB/s read)
- Samsung EVO Plus (U3, 130MB/s read)
- Kingston Canvas React Plus (A1/U3, 100MB/s read)

### SSD Storage (Production Deployment)

**Strongly recommended for 24/7 operation** due to better reliability and performance.

**Connection Methods:**

1. **USB 3.0 SATA Adapter** (Pi 4/5)
   - Use quality USB 3.0 to SATA adapter
   - Connect to USB 3.0 port (blue port)
   - Enable USB boot in bootloader

2. **M.2 NVMe via PCIe** (Pi 5 only)
   - Use official Raspberry Pi M.2 HAT+
   - Supports NVMe SSDs up to Gen 3 speeds
   - Best performance option

**Recommended SSDs:**
- Samsung 870 EVO (SATA)
- Crucial MX500 (SATA)
- Samsung 980 (M.2 NVMe for Pi 5)

**Capacity Guidelines:**
- Minimum: 128GB
- Recommended: 256GB (allows extensive audio archival)
- Large Deployment: 512GB or 1TB

## GPIO and Relay Control

### GPIO Header Pinout (40-pin)

The Raspberry Pi 40-pin GPIO header provides control signals for external equipment.

```
        3.3V  (1) (2)  5V
       GPIO2  (3) (4)  5V
       GPIO3  (5) (6)  GND
       GPIO4  (7) (8)  GPIO14 (UART TX)
         GND  (9) (10) GPIO15 (UART RX)
      GPIO17 (11) (12) GPIO18 (PCM CLK)
      GPIO27 (13) (14) GND
      GPIO22 (15) (16) GPIO23
        3.3V (17) (18) GPIO24
      GPIO10 (19) (20) GND
       GPIO9 (21) (22) GPIO25
      GPIO11 (23) (24) GPIO8
         GND (25) (26) GPIO7
       GPIO0 (27) (28) GPIO1 (I2C)
       GPIO5 (29) (30) GND
       GPIO6 (31) (32) GPIO12
      GPIO13 (33) (34) GND
      GPIO19 (35) (36) GPIO16
      GPIO26 (37) (38) GPIO20
         GND (39) (40) GPIO21
```

### Recommended GPIO Pins for EAS Station

| Function | GPIO | Physical Pin | Notes |
|----------|------|--------------|-------|
| **Primary Relay** | GPIO17 | Pin 11 | Main transmitter control |
| **Secondary Relay** | GPIO27 | Pin 13 | Backup or secondary equipment |
| **Alert Indicator LED** | GPIO22 | Pin 15 | Visual alert status |
| **Emergency Stop** | GPIO23 | Pin 16 | Hardware interrupt for operator override |

**⚠️ Important GPIO Notes:**
- GPIO outputs are **3.3V logic level** (NOT 5V tolerant)
- Maximum current per pin: 16mA
- Total GPIO current budget: 50mA across all pins
- **Always use level shifters and relay modules** - never drive loads directly

### Relay HAT Options

#### Option 1: Waveshare RPi Relay Board (B)

**Specifications:**
- 4× SPDT relays (10A @ 250VAC, 10A @ 30VDC)
- Optical isolation
- Status LEDs
- Standard GPIO control

**Pinout:**
- Relay 1: GPIO26 (Pin 37)
- Relay 2: GPIO20 (Pin 38)
- Relay 3: GPIO21 (Pin 40)
- Relay 4: GPIO19 (Pin 35)

**Purchase:** ~$25-30 USD

#### Option 2: Seeed Studio 4-Channel Relay HAT

**Specifications:**
- 4× SPDT relays (5A @ 250VAC, 5A @ 30VDC)
- Mechanical and solid-state options
- Opto-isolated
- Grove connectors for expansion

**Pinout:**
- Relay 1: GPIO5 (Pin 29)
- Relay 2: GPIO6 (Pin 31)
- Relay 3: GPIO13 (Pin 33)
- Relay 4: GPIO16 (Pin 36)

**Purchase:** ~$20-25 USD

#### Option 3: Custom Relay Board

For custom integrations, use:
- **Relay Module**: Omron G2R-1-E or equivalent
- **Optocoupler**: PC817 for isolation
- **Driver**: ULN2803 Darlington array
- **Diode**: 1N4007 flyback protection

**Reference schematic:** See `docs/hardware/gpio.md` for detailed wiring.

### Relay Wiring Safety

**⚠️ DANGER - HIGH VOLTAGE:**

Relays may switch AC mains voltage and broadcast transmitter RF. Improper wiring can cause:
- Electric shock
- Fire
- Equipment damage
- FCC compliance violations

**Safety Requirements:**
1. All high-voltage wiring must be performed by a licensed electrician or qualified broadcast engineer
2. Use appropriate gauge wire for load current
3. Install circuit breakers and fuses
4. Follow NEC (National Electrical Code) or local electrical codes
5. Ensure proper grounding
6. Use shielded cable for RF environments
7. Label all relay connections clearly
8. Implement emergency stop circuits

## Audio Hardware

### USB Audio Interfaces

#### Recommended Models

**Budget Option: Behringer U-Phoria UMC202HD**
- 2-in/2-out USB audio interface
- 48kHz sample rate
- XLR and 1/4" line inputs
- ALSA class-compliant (no drivers needed)
- Price: ~$60-80 USD

**Broadcast Option: Focusrite Scarlett 2i2 (3rd Gen)**
- 2-in/2-out professional audio interface
- 192kHz/24-bit capability
- Air preamps with pad switches
- Direct monitoring
- ALSA class-compliant
- Price: ~$180-200 USD

**Multi-Channel Option: Behringer U-PHORIA UMC1820**
- 8× XLR inputs with ADAT expansion
- Monitor multiple receivers simultaneously
- Rack-mountable
- Price: ~$250-300 USD

#### Audio Connection Examples

**Monitoring Weather Radio:**
```
[Weather Radio] ---> [Audio Out] ---> [USB Interface Input 1] ---> [Raspberry Pi USB 3.0]
```

**Monitoring and Broadcasting:**
```
[Multiple Sources] ---> [Mixer] ---> [USB Interface Input] ---> [Raspberry Pi]
[Raspberry Pi] ---> [USB Interface Output] ---> [Transmitter Input]
```

### Audio Specifications

**Input Requirements:**
- Level: -10dBV to +4dBu (consumer to professional line level)
- Impedance: 10kΩ or higher (balanced preferred)
- Connector: XLR or 1/4" TRS
- Sample Rate: 44.1kHz or 48kHz
- Bit Depth: 16-bit minimum, 24-bit preferred

**Output Requirements:**
- Level: +4dBu (professional line level) or adjustable
- Impedance: 100Ω balanced output
- Connector: XLR or 1/4" TRS
- Latency: <10ms total system latency

### PulseAudio Configuration

For production use, disable PulseAudio or configure direct ALSA access:

```bash
# Disable PulseAudio (recommended for real-time audio)
systemctl --user stop pulseaudio.socket
systemctl --user stop pulseaudio.service
systemctl --user disable pulseaudio.socket
systemctl --user disable pulseaudio.service
```

See `docs/deployment/audio_hardware.md` for detailed audio configuration.

## SDR Receivers

### Supported SDR Hardware

#### RTL-SDR (Budget Option)

**RTL-SDR Blog V3/V4:**
- Frequency Range: 500kHz - 1.7GHz
- Sample Rate: 2.4 MSPS
- Built-in bias tee for LNA power
- Temperature-controlled oscillator (TCXO)
- Price: ~$35-40 USD
- Driver: `rtl-sdr` via SoapySDR

**Connection:**
```
[VHF Antenna] ---> [RTL-SDR] ---> [Raspberry Pi USB 3.0]
```

**Tuning for NOAA Weather Radio:**
- Frequency: 162.400 - 162.550 MHz (7 channels)
- Bandwidth: 25 kHz FM
- Gain: 30-40 dB typical

#### Airspy Mini/R2 (Performance Option)

**Airspy Mini:**
- Frequency Range: 24 - 1800 MHz
- Sample Rate: 6 MSPS
- Better sensitivity than RTL-SDR
- Price: ~$100 USD

**Airspy R2:**
- Frequency Range: 24 - 1800 MHz
- Sample Rate: 10 MSPS
- Best-in-class sensitivity
- Price: ~$170-200 USD
- Driver: `airspy` via SoapySDR

### Antenna Considerations

**VHF Weather Radio Reception (162 MHz):**
- **Indoor:** Telescopic whip antenna (included with RTL-SDR)
- **Outdoor:** Diamond X-50A dual-band vertical (weather + amateur radio)
- **Attic:** 1/4 wave ground plane (approx. 18 inches)

**Cable:**
- RG-6 or RG-8X coaxial cable
- Use quality connectors (Amphenol, PL-259)
- Minimize cable length (<50 feet ideal)

### USB Power Considerations

SDR devices draw significant current:
- RTL-SDR: ~300mA
- Airspy Mini: ~180mA
- Airspy R2: ~250mA

**Use powered USB 3.0 hub if connecting multiple SDRs** to avoid brownouts.

## Serial/RS-232 Integration

### USB to RS-232 Adapters

For controlling legacy EAS equipment, transmitters, or automation systems:

**Recommended Adapters:**

**FTDI-based (Best Compatibility):**
- StarTech ICUSB232V2 (industrial-grade)
- FTDI US232R-100 (genuine FTDI chipset)
- Price: ~$30-50 USD

**Prolific PL2303-based (Budget):**
- Ensure genuine Prolific chipset (many counterfeits)
- Works with Linux kernel drivers
- Price: ~$10-15 USD

### Serial Pinout (DB-9 Male)

```
Pin 1: DCD (Data Carrier Detect)
Pin 2: RX  (Receive Data)
Pin 3: TX  (Transmit Data)
Pin 4: DTR (Data Terminal Ready)
Pin 5: GND (Signal Ground)
Pin 6: DSR (Data Set Ready)
Pin 7: RTS (Request To Send)
Pin 8: CTS (Clear To Send)
Pin 9: RI  (Ring Indicator)
```

**Common Broadcast Equipment Connections:**
- **DASDEC/EAS Encoder**: 9600 baud, 8N1, hardware flow control
- **Transmitter Remote Control**: 9600 baud, 8N1, no flow control
- **Automation System**: 19200 baud, 8N1, varies by vendor

### Device Permissions

Grant access to serial devices:

```bash
# Add user to dialout group
sudo usermod -aG dialout $USER

# Or create udev rule (create /etc/udev/rules.d/50-serial.rules):
KERNEL=="ttyUSB*", MODE="0666", GROUP="dialout"
KERNEL=="ttyACM*", MODE="0666", GROUP="dialout"
```

## Power Supply

### Requirements

**Raspberry Pi Power:**
- Pi 4: 5V 3A USB-C (15W minimum)
- Pi 5: 5V 5A USB-C (25W recommended)

**Official Raspberry Pi Power Supply strongly recommended** to avoid undervoltage issues.

### Uninterruptible Power Supply (UPS)

For broadcast installations, **UPS is mandatory**:

**Recommended UPS Solutions:**

1. **CyberPower CP1500PFCLCD** (~$200)
   - 1500VA/1000W pure sine wave
   - 10+ outlets
   - Runtime: 2-3 hours for Pi + peripherals
   - USB monitoring support

2. **APC Back-UPS Pro 1500VA** (~$230)
   - 1500VA/900W sine wave
   - USB/network management
   - Replaceable batteries

3. **PiJuice HAT** (Portable option)
   - Attaches to Pi GPIO
   - Rechargeable battery (5000-12000mAh)
   - Runtime: 2-6 hours depending on load
   - Price: ~$60-90

### Power Budget

Calculate total power draw:

```
Raspberry Pi 5:        25W
USB Audio Interface:    5W
RTL-SDR:                2W
Relay HAT:              3W (coils energized)
USB SSD:                5W
-----------------------------------
Total:                 40W

Recommended UPS:      500VA minimum (50W+ capacity)
```

## Network Configuration

### Ethernet (Strongly Recommended)

**Requirements:**
- Gigabit Ethernet (1000Base-T)
- CAT5e or CAT6 cable
- Shielded cable if running near RF equipment
- Static IP address configured on station network

### Network Switch Placement

**Do not connect directly to internet-facing router.** Place behind:
- Firewall with port forwarding rules
- VPN for remote access
- Dedicated management VLAN

### Wi-Fi (Not Recommended for Production)

If wired Ethernet is unavailable:
- Use 5GHz Wi-Fi only (less interference)
- Enterprise-grade access point
- WPA3 security
- Dedicated SSID for station equipment

## Cooling and Thermal Management

### Passive Cooling

**Minimum Requirements:**
- Aluminum heatsink on CPU
- Thermal tape or compound
- Ventilated case

**Recommended Cases:**

1. **Argon ONE V2 Case** (~$25)
   - Aluminum body acts as heatsink
   - GPIO access
   - Power button
   - M.2 SATA expansion slot

2. **Flirc Raspberry Pi Case** (~$20)
   - Entire case is a heatsink
   - Fanless design
   - Excellent cooling

### Active Cooling

For 24/7 operation or warm environments, add:
- 5V PWM-controlled fan (Noctua NF-A4x10 recommended)
- Fan control via GPIO or HAT
- Target CPU temperature: <60°C idle, <70°C load

### Temperature Monitoring

Check CPU temperature:
```bash
vcgencmd measure_temp
```

Configure thermal throttling alerts in EAS Station system health monitoring.

## Rack Mounting

### 19" Rack Solutions

**Option 1: MyElectronicals Raspberry Pi Rack Kit** (~$40)
- Mounts 4× Raspberry Pi units
- 1U rack space
- Includes power distribution

**Option 2: Custom Panel**
- Blank 1U or 2U rack panel
- Mount Pi case with standoffs
- Mount relay modules adjacent
- Label all connections

### Cable Management

- Use Velcro cable ties
- Label all cables with Brother P-Touch or similar
- Document pinouts in station log
- Keep spare cables on-site

## Assembly Checklist

### Initial Setup

- [ ] Flash Raspberry Pi OS to SD card or SSD
- [ ] Connect keyboard, mouse, monitor for initial setup
- [ ] Boot and complete OS setup wizard
- [ ] Configure static IP address
- [ ] Update system: `sudo apt update && sudo apt upgrade`
- [ ] Install Docker and Docker Compose
- [ ] Clone EAS Station repository

### Hardware Installation

- [ ] Install heatsink or mount in cooled case
- [ ] Connect USB audio interface to USB 3.0 port (blue)
- [ ] Connect SDR receiver to USB 3.0 port
- [ ] Connect relay HAT to GPIO header (if used)
- [ ] Connect Ethernet cable
- [ ] Connect USB-C power supply (last step)

### Software Configuration

- [ ] Run setup wizard: `python3 tools/setup_wizard.py`
- [ ] Configure audio sources in web UI: `/settings/audio-sources`
- [ ] Configure SDR receivers in web UI: `/settings/radio`
- [ ] Test GPIO relay control: `/admin/gpio`
- [ ] Verify system health: `/system/health`

### Production Validation

- [ ] Conduct 72-hour burn-in test
- [ ] Monitor CPU temperature under load
- [ ] Verify audio levels with test tone generator
- [ ] Test relay activation and timing
- [ ] Simulate power failure with UPS
- [ ] Document final configuration in station log

## Troubleshooting

### USB Audio Not Detected

```bash
# List USB audio devices
arecord -l
aplay -l

# Check USB device enumeration
lsusb
dmesg | grep -i audio
```

### SDR Not Detected

```bash
# Test RTL-SDR
rtl_test

# List SoapySDR devices
SoapySDRUtil --find

# Check USB permissions
ls -l /dev/bus/usb/*/*
```

### GPIO Relay Not Working

```bash
# Test GPIO manually
echo 17 > /sys/class/gpio/export
echo out > /sys/class/gpio/gpio17/direction
echo 1 > /sys/class/gpio/gpio17/value
echo 0 > /sys/class/gpio/gpio17/value
echo 17 > /sys/class/gpio/unexport
```

### Undervoltage Detected

Yellow lightning bolt icon or throttling logs indicate insufficient power:

1. Replace power supply with official Raspberry Pi PSU
2. Remove USB devices and test
3. Check for damaged USB-C cable
4. Measure voltage at GPIO pins (should be 5.0V ±0.25V)

## Parts List and Cost Estimate

| Component | Model | Est. Cost | Required |
|-----------|-------|-----------|----------|
| **Single-Board Computer** | Raspberry Pi 5 8GB | $80 | ✅ Yes |
| **Storage** | Samsung 870 EVO 256GB SSD | $40 | ✅ Yes |
| **Storage Adapter** | USB 3.0 to SATA adapter | $15 | ✅ Yes |
| **Power Supply** | Official RPi 5 USB-C PSU | $12 | ✅ Yes |
| **Case** | Argon ONE V2 or Flirc | $20 | ✅ Yes |
| **USB Audio Interface** | Behringer UMC202HD | $70 | ✅ Yes |
| **SDR Receiver** | RTL-SDR Blog V4 | $40 | ✅ Yes |
| **Antenna** | Tram 1089 VHF Base | $35 | Recommended |
| **Relay HAT** | Waveshare RPi Relay Board | $25 | Optional |
| **UPS** | CyberPower CP1500PFCLCD | $200 | Recommended |
| **Rack Mount Kit** | MyElectronicals 1U Kit | $40 | Optional |
| **Ethernet Cable** | CAT6 25ft | $10 | ✅ Yes |
| | **Total (Basic):** | **~$347** | |
| | **Total (Full Featured):** | **~$587** | |

## Additional Resources

- [Official Raspberry Pi Documentation](https://www.raspberrypi.com/documentation/)
- [GPIO Pinout Reference](https://pinout.xyz/)
- [RTL-SDR Quick Start](../guides/SDR_QUICKSTART.md)
- [Audio Hardware Setup](../deployment/audio_hardware.md)
- [GPIO Integration Guide](gpio.md)
- [Deployment Checklist](../deployment/post_install.md)

## Support and Community

For hardware-specific questions:
- GitHub Issues: https://github.com/KR8MER/eas-station/issues
- Raspberry Pi Forums: https://forums.raspberrypi.com/
- RTL-SDR Reddit: r/RTLSDR

---

**Document Version:** 1.0
**Last Updated:** 2025-11-05
**Maintainer:** EAS Station Development Team
