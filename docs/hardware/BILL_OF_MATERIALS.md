# EAS Station - Bill of Materials (BOM)

**Version:** 1.0
**Last Updated:** November 21, 2025
**Target Platform:** Raspberry Pi 5 with Argon ONE V5 Case

---

## Overview

This BOM provides a complete parts list for building a professional EAS Station deployment. All components are readily available from major electronics distributors.

**Total Cost:** ~$450 - $650 (depending on configuration)

---

## Core Components

### 1. Compute Platform

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **Raspberry Pi 5 (8GB)** | RPI5-8GB | 1 | $80 | $80 | [Adafruit](https://www.adafruit.com/product/5813), [CanaKit](https://www.canakit.com/raspberry-pi-5-8gb.html) | Recommended for production use |
| **Raspberry Pi 5 (4GB)** | RPI5-4GB | 1 | $60 | $60 | [Adafruit](https://www.adafruit.com/product/5812) | Budget option, works fine |
| **Argon ONE V5 Case** | ARG-ONE-V5 | 1 | $50-60 | $55 | [Argon40](https://argon40.com/products/argon-one-v5-case-for-raspberry-pi-5) | Includes NVMe slot, OLED, active cooling |
| **NVMe M.2 SSD (500GB)** | Various | 1 | $35-50 | $40 | Amazon, Newegg | Crucial P3, Samsung 980, WD Blue recommended |
| **Official Pi 5 Power Supply (27W USB-C)** | SC1112 | 1 | $12 | $12 | [Adafruit](https://www.adafruit.com/product/5782), [CanaKit](https://www.canakit.com/raspberry-pi-5-power-supply-27w-usb-c.html) | Required for stable operation |

**Core Subtotal:** $187 - $247 (depending on Pi model and SSD choice)

---

## Audio & Broadcast Components

### 2. Audio Output (Choose One)

**Option A: USB Audio Interface (Recommended for Broadcast)**

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **Behringer U-Phoria UMC22** | UMC22 | 1 | $59 | $59 | Amazon, Sweetwater | Budget USB audio interface, XLR/TRS outputs |
| **Focusrite Scarlett Solo (3rd Gen)** | SCARLETT-SOLO-3G | 1 | $119 | $119 | Amazon, Sweetwater | Professional USB audio, better quality |

**Option B: Raspberry Pi HAT Audio**

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **HiFiBerry DAC+ Pro** | HIFIBERRY-DACPRO | 1 | $45 | $45 | [HiFiBerry](https://www.hifiberry.com/shop/boards/hifiberry-dac-pro/), Adafruit | High-quality audio output HAT |
| **IQaudIO DAC Pro** | IQAUDIO-DACPRO | 1 | $40 | $40 | [IQaudIO](https://www.iqaudio.com/) | Alternative audio HAT |

**Audio Subtotal:** $40 - $119

---

## SDR Receiver (Optional but Recommended)

### 3. Software-Defined Radio for Broadcast Verification

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **RTL-SDR Blog V3** | RTL-SDR-V3 | 1 | $35 | $35 | [RTL-SDR.com](https://www.rtl-sdr.com/buy-rtl-sdr-dvb-t-dongles/), Amazon | Good for VHF/UHF monitoring |
| **Airspy Mini** | AIRSPY-MINI | 1 | $99 | $99 | [Airspy](https://airspy.com/airspy-mini/), Amazon | Better sensitivity, recommended for production |
| **Magnetic Mount VHF/UHF Antenna** | Various | 1 | $15-25 | $20 | Amazon | For receiving broadcast signals |
| **SMA Male to F Female Adapter** | SMA-F-ADAPTER | 1 | $5 | $5 | Amazon | If needed for antenna connection |

**SDR Subtotal:** $40 - $124 (RTL-SDR setup = $40, Airspy setup = $124)

---

## GPIO Control & Relay HATs

### 4. Relay Control (Optional - For Transmitter/Equipment Control)

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **Sequent Microsystems 8-Relay HAT** | SM-8RELAY | 1 | $45 | $45 | [Sequent Microsystems](https://sequentmicrosystems.com/products/8-relays-stackable-card-for-raspberry-pi), Amazon | Stackable, 8 SPDT relays |
| **Waveshare RPi Relay Board** | WS-RELAY-HAT | 1 | $15 | $15 | [Waveshare](https://www.waveshare.com/rpi-relay-board.htm), Amazon | Budget option, 4 relays |
| **Pi-Supply IoT Relay HAT** | PS-IOT-RELAY | 1 | $25 | $25 | [Pi-Supply](https://uk.pi-supply.com/products/iot-relay-hat-for-raspberry-pi), Amazon | Single high-power relay |

**Relay Subtotal:** $15 - $45 (if needed)

---

## Networking & Connectivity

### 5. Network and Cables

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **Cat6 Ethernet Cable (6 ft)** | Various | 1 | $5 | $5 | Amazon, Monoprice | For wired network connection |
| **USB-A to USB-C Cable (for peripherals)** | Various | 2 | $5 | $10 | Amazon, Monoprice | For SDR, audio interface |
| **Micro HDMI to HDMI Cable** | Various | 1 | $8 | $8 | Amazon, CanaKit | For initial setup/monitoring |

**Networking Subtotal:** $23

---

## Storage & Peripherals

### 6. MicroSD Card (Backup/Recovery)

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **SanDisk Ultra 32GB microSD** | SDSQUAR-032G | 1 | $7 | $7 | Amazon, Best Buy | For emergency boot/recovery |

---

## Audio Cables & Adapters

### 7. Audio Connectivity

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **3.5mm TRS to Dual 1/4" TS Cable** | HOSA-CMP159 | 1 | $10 | $10 | Amazon, Sweetwater | For connecting to broadcast equipment |
| **XLR Male to XLR Female Cable (6 ft)** | Various | 2 | $12 | $24 | Amazon, Sweetwater | Balanced audio to transmitter |
| **3.5mm TRS Male to Male Cable** | Various | 1 | $5 | $5 | Amazon, Monoprice | For audio monitoring |

**Audio Cables Subtotal:** $39 (typical broadcast setup)

---

## Complete Configuration Options

### Configuration 1: Minimal EAS Station (Development/Testing)
**Total: ~$247**

- Raspberry Pi 5 (4GB): $60
- Argon ONE V5 Case: $55
- NVMe SSD (500GB): $40
- Pi 5 Power Supply: $12
- HiFiBerry DAC+ Pro: $45
- Cat6 Cable: $5
- HDMI Cable: $8
- microSD Card: $7
- Basic audio cables: $15

**Use Case:** Lab testing, development, non-critical deployments

---

### Configuration 2: Standard Broadcast Station (Recommended)
**Total: ~$450**

- Raspberry Pi 5 (8GB): $80
- Argon ONE V5 Case: $55
- NVMe SSD (500GB): $40
- Pi 5 Power Supply: $12
- Behringer UMC22 USB Audio: $59
- RTL-SDR Blog V3: $35
- VHF/UHF Antenna: $20
- SMA Adapter: $5
- Sequent 8-Relay HAT: $45
- Cat6 Cable: $5
- HDMI Cable: $8
- microSD Card: $7
- Audio cables (XLR, TRS): $39
- USB cables: $10
- **Spare cables/adapters:** $30

**Use Case:** Production radio/TV station, emergency management, amateur radio club

---

### Configuration 3: Professional/Multi-Site (High-End)
**Total: ~$650**

- Raspberry Pi 5 (8GB): $80
- Argon ONE V5 Case: $55
- NVMe SSD (1TB): $70
- Pi 5 Power Supply: $12
- Focusrite Scarlett Solo: $119
- Airspy Mini: $99
- VHF/UHF Antenna: $20
- SMA Adapter: $5
- Sequent 8-Relay HAT: $45
- Cat6 Cable: $5
- HDMI Cable: $8
- microSD Card: $7
- Professional audio cables: $50
- USB cables: $10
- **UPS battery backup:** $65

**Use Case:** 24/7 mission-critical deployment, commercial broadcast, multi-station coordination

---

## Optional Accessories

### Display & Monitoring

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **7" HDMI Touchscreen** | Various | 1 | $50-80 | $65 | Amazon, Adafruit | For local monitoring |
| **Official Pi 7" Touchscreen** | RPI-DISPLAY | 1 | $70 | $70 | Adafruit, CanaKit | Native DSI connection |

### Backup Power

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **APC Back-UPS 425VA** | BE425M | 1 | $50 | $50 | Amazon, Best Buy | 40 minutes runtime at 50W load |
| **CyberPower 600VA UPS** | CP685AVR | 1 | $65 | $65 | Amazon, Best Buy | 60 minutes runtime, AVR |

### LED Signage Integration

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **Adafruit RGB LED Matrix (64x32)** | ADA-2278 | 1 | $40 | $40 | Adafruit | For alert display |
| **Adafruit RGB Matrix HAT** | ADA-2345 | 1 | $15 | $15 | Adafruit | To drive LED matrix |

### Enclosure & Mounting

| Component | Part Number | Qty | Unit Price | Total | Supplier | Notes |
|-----------|-------------|-----|------------|-------|----------|-------|
| **19" Rack Shelf** | Various | 1 | $20-40 | $30 | Amazon, Monoprice | For rack mounting |
| **DIN Rail Mount for Pi** | Various | 1 | $15 | $15 | Amazon | For industrial installations |

---

## Assembly Notes

### Argon ONE V5 Case Assembly

1. **Install NVMe SSD first** (before Pi installation)
2. Install Raspberry Pi 5 into case
3. Connect OLED display cable to GPIO pins (per Argon40 instructions)
4. Secure with provided screws
5. Install magnetic base plate

**Important:** The Argon ONE V5 has an active cooling system with programmable fan control. EAS Station can control the fan speed via I2C.

### HAT Stacking Order (if using multiple HATs)

**Recommended order (bottom to top):**
1. Raspberry Pi 5
2. Audio HAT (HiFiBerry/IQaudIO)
3. Relay HAT (with stacking headers)
4. GPIO breakout (if needed)

**Note:** The Argon ONE V5 case provides GPIO access via a top panel. You'll need to use ribbon cables or GPIO extenders to access HATs inside the case.

---

## Power Budget Analysis

| Component | Typical Power | Max Power | Notes |
|-----------|---------------|-----------|-------|
| Raspberry Pi 5 (8GB) | 8W | 12W | Under heavy load |
| NVMe SSD | 3W | 5W | During writes |
| USB Audio Interface | 2W | 2.5W | USB-powered |
| RTL-SDR | 0.5W | 1W | USB-powered |
| Relay HAT | 0.5W | 2W | When relays active |
| Argon ONE Fan | 0.5W | 1W | At full speed |
| **Total** | **14.5W** | **23.5W** | Within 27W supply limit |

**Recommendation:** Official 27W Pi 5 power supply provides adequate headroom. For configurations with multiple USB devices, consider a powered USB hub.

---

## Purchasing Recommendations

### Trusted Suppliers (US)

**Electronics:**
- [Adafruit](https://www.adafruit.com) - Raspberry Pi, HATs, accessories
- [CanaKit](https://www.canakit.com) - Raspberry Pi kits
- [SparkFun](https://www.sparkfun.com) - Sensors, breakouts
- [Pimoroni](https://shop.pimoroni.com) - Pi accessories (UK-based)

**Audio Equipment:**
- [Sweetwater](https://www.sweetwater.com) - Professional audio interfaces
- [B&H Photo](https://www.bhphotovideo.com) - Audio/video equipment

**General Components:**
- [Amazon](https://www.amazon.com) - General availability
- [Mouser](https://www.mouser.com) - Electronic components
- [Digi-Key](https://www.digikey.com) - Electronic components
- [Monoprice](https://www.monoprice.com) - Cables, accessories

**SDR Equipment:**
- [RTL-SDR.com](https://www.rtl-sdr.com) - RTL-SDR receivers
- [Airspy](https://airspy.com) - Airspy receivers

### International Suppliers

**UK/Europe:**
- [The Pi Hut](https://thepihut.com) - Raspberry Pi and accessories
- [Pimoroni](https://shop.pimoroni.com) - Pi HATs and accessories
- [RS Components](https://www.rs-online.com) - Industrial electronics

**Canada:**
- [BuyaPi.ca](https://www.buyapi.ca) - Raspberry Pi products
- [Canada Computers](https://www.canadacomputers.com) - General electronics

**Australia:**
- [Core Electronics](https://core-electronics.com.au) - Raspberry Pi and makers
- [Little Bird Electronics](https://littlebird.com.au) - Arduino, Pi, HATs

---

## Volume Discounts

For **10+ station deployments**, contact suppliers for bulk pricing:

- **Raspberry Pi Foundation:** Educational/commercial bulk orders
- **Argon40:** Direct bulk orders may be available
- **Audio Manufacturers:** Dealer pricing for 10+ units

**Expected savings:** 10-20% on orders of 10+ complete systems

---

## Spare Parts Recommendations

For critical deployments, maintain spares:

| Component | Qty | Priority | Cost |
|-----------|-----|----------|------|
| Raspberry Pi 5 (8GB) | 1 | High | $80 |
| NVMe SSD (500GB) | 1 | High | $40 |
| USB Audio Interface | 1 | Medium | $59 |
| RTL-SDR | 1 | Low | $35 |
| Power Supply | 1 | High | $12 |
| microSD Card | 2 | High | $14 |
| Ethernet Cable | 2 | Medium | $10 |
| **Spare Kit Total** | - | - | **$250** |

---

## Compatibility Notes

### Argon ONE V5 Specific Considerations

**Pros:**
- ✅ Excellent cooling (passive + active fan)
- ✅ Built-in NVMe support (no USB adapter needed)
- ✅ OLED display for status information
- ✅ Clean, professional appearance
- ✅ GPIO breakout on top panel
- ✅ Magnetic mounting

**Cons:**
- ⚠️ HATs must be installed externally via GPIO ribbon cable
- ⚠️ Slightly more expensive than basic cases
- ⚠️ OLED requires I2C software setup

**Alternative Cases if HAT Access Needed:**
- **Geekworm X1001** - Open-air case with HAT stacking support
- **Pimoroni NVMe Base** - Exposes GPIO for direct HAT mounting
- **DIN Rail Mount Case** - Industrial installations

---

## Software Configuration for Hardware

### Argon ONE V5 OLED Display

EAS Station can display real-time status on the OLED:
- Current alert status
- System uptime
- CPU/memory usage
- Network status
- Active relays

**Setup:** I2C must be enabled in `/boot/config.txt`:
```bash
dtparam=i2c_arm=on
```

### HiFiBerry DAC Configuration

**Add to `/boot/config.txt`:**
```bash
dtoverlay=hifiberry-dacplus
```

**Disable onboard audio:**
```bash
dtparam=audio=off
```

### RTL-SDR Permissions

**Add udev rule** (`/etc/udev/rules.d/20-rtlsdr.rules`):
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0bda", ATTRS{idProduct}=="2838", MODE="0666"
```

EAS Station Docker container already includes these configurations.

---

## Warranty & Support

| Component | Warranty | Support |
|-----------|----------|---------|
| Raspberry Pi | 1 year | Community + Foundation |
| Argon ONE V5 | 1 year | Argon40 direct |
| NVMe SSD | 3-5 years | Manufacturer |
| USB Audio | 1-3 years | Manufacturer |
| RTL-SDR/Airspy | 1 year | Manufacturer |

**Extended warranty:** Consider purchasing from suppliers offering extended warranty options for critical deployments.

---

## Cost Summary by Configuration

| Configuration | Core | Audio | SDR | Relay | Cables | Spare | **Total** |
|--------------|------|-------|-----|-------|--------|-------|----------|
| **Minimal** | $247 | $0 | $0 | $0 | $0 | $0 | **$247** |
| **Standard** | $247 | $59 | $60 | $45 | $39 | $0 | **$450** |
| **Professional** | $247 | $119 | $124 | $45 | $50 | $65 | **$650** |
| **+ Spare Kit** | - | - | - | - | - | $250 | **+$250** |

---

## Next Steps

1. **Order components** based on your configuration choice
2. **Download EAS Station** from [GitHub](https://github.com/KR8MER/eas-station)
3. **Follow setup guide** in [docs/guides/SETUP_INSTRUCTIONS.md](../guides/SETUP_INSTRUCTIONS.md)
4. **Configure hardware** per software documentation
5. **Test with self-test alerts** before production deployment

---

## Questions?

For hardware-specific questions:
- **General EAS Station:** [GitHub Issues](https://github.com/KR8MER/eas-station/issues)
- **Argon ONE V5:** [Argon40 Support](https://argon40.com/pages/contact-us)
- **HiFiBerry:** [HiFiBerry Forums](https://support.hifiberry.com/)
- **RTL-SDR:** [RTL-SDR Reddit](https://www.reddit.com/r/RTLSDR/)

---

**Document Version:** 1.0
**Last Updated:** November 21, 2025
**Maintainer:** Timothy Kramer (KR8MER)

*Hardware specifications subject to change. Prices approximate as of November 2025.*
