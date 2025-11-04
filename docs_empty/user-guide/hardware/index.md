# Hardware Setup

Hardware integration guide for SDR receivers, GPIO relays, and LED signs.

## Overview

EAS Station supports various hardware peripherals:

- **SDR Receivers** - RTL-SDR, Airspy for alert verification
- **GPIO Relays** - Raspberry Pi GPIO for transmitter keying
- **LED Signs** - Alpha Protocol displays for visual alerts
- **Audio Interfaces** - USB sound cards, Pi HATs

## Hardware Guides

- [SDR Receivers](sdr.md) - Software-defined radio setup
- [GPIO Relays](gpio.md) - Relay control and transmitter keying
- [LED Signs](led.md) - LED display integration

## Recommended Hardware

### Raspberry Pi Setup

**Compute:**
- Raspberry Pi 5 (8GB recommended)
- Official power supply
- Active cooling case

**Storage:**
- External SSD (USB 3.0)
- 64GB minimum, 256GB recommended

**Networking:**
- Ethernet (recommended)
- WiFi acceptable for testing

### SDR Receivers

**Recommended:**
- RTL-SDR Blog V3 ($35)
- Airspy Mini ($99)
- HackRF One ($299)

### GPIO Control

**Relay Boards:**
- Waveshare RPi Relay Board
- Seeed Studio Relay HAT
- Generic 5V relay modules

### LED Signs

**Compatible:**
- BetaBrite LED signs
- Alpha Protocol displays
- American Time & Signal

## Safety Considerations

!!! warning "Electrical Safety"
    - Use isolated relays for transmitter keying
    - Never work on live circuits
    - Proper grounding essential
    - Fuse all power connections

!!! danger "RF Safety"
    - Keep transmitters off during setup
    - Use dummy loads for testing
    - Follow FCC power limits
    - Proper antenna installation

## Next Steps

Choose your hardware integration:

- [Set up SDR Receiver](sdr.md)
- [Configure GPIO Relays](gpio.md)
- [Connect LED Sign](led.md)
