# Audio Hardware Setup and Configuration

## Overview

This guide covers the setup, configuration, and troubleshooting of audio hardware for EAS Station deployments. Proper audio configuration is critical for reliable alert detection and playout.

## Table of Contents

- [Hardware Selection](#hardware-selection)
- [USB Audio Interface Setup](#usb-audio-interface-setup)
- [ALSA Configuration](#alsa-configuration)
- [Device Permissions](#device-permissions)
- [Audio Routing](#audio-routing)
- [Testing and Calibration](#testing-and-calibration)
- [Performance Tuning](#performance-tuning)
- [Troubleshooting](#troubleshooting)

## Hardware Selection

### USB Audio Interface Requirements

**Minimum Specifications:**
- USB 2.0 or higher (USB 3.0 recommended)
- Sample Rate: 44.1kHz or 48kHz
- Bit Depth: 16-bit minimum, 24-bit preferred
- Linux ALSA class-compliant (no proprietary drivers)
- Balanced inputs (XLR or TRS) for professional audio

**Recommended Interfaces:**

| Model | Inputs | Outputs | Sample Rate | Price Range | Notes |
|-------|--------|---------|-------------|-------------|-------|
| Behringer U-Phoria UMC202HD | 2 | 2 | 48kHz/24-bit | $60-80 | Budget-friendly, reliable |
| Focusrite Scarlett 2i2 (3rd Gen) | 2 | 2 | 192kHz/24-bit | $180-200 | Professional quality |
| Behringer UMC404HD | 4 | 4 | 96kHz/24-bit | $100-120 | Multi-input for multiple sources |
| Behringer UMC1820 | 8 | 8 | 96kHz/24-bit | $250-300 | Rack-mount, expandable |
| M-Audio M-Track Duo | 2 | 2 | 48kHz/24-bit | $90-110 | Compact, bus-powered |

### Avoid These Interfaces

- **Cheap USB sound cards** (poor audio quality, driver issues)
- **Non-class-compliant devices** (require Windows/Mac drivers)
- **USB 1.1 devices** (insufficient bandwidth)
- **Built-in Raspberry Pi audio** (poor quality, no line input)

## USB Audio Interface Setup

### Physical Connection

1. **Connect to USB 3.0 port** (blue port on Raspberry Pi 4/5)
   - Provides better power and bandwidth
   - Reduces audio dropouts

2. **Use quality USB cables**
   - Ferrite chokes on both ends (reduces RF interference)
   - Maximum length: 6 feet (2 meters)
   - Avoid USB hubs if possible

3. **Ground all equipment properly**
   - Connect audio sources and interface to same ground reference
   - Use balanced audio cables to minimize ground loops
   - Consider ground loop isolators for noisy environments

### Verify Detection

After connecting the USB audio interface:

```bash
# List USB devices
lsusb

# Expected output (example for Behringer UMC202HD):
# Bus 002 Device 003: ID 1397:0507 BEHRINGER International GmbH

# List ALSA playback devices
aplay -l

# Expected output:
# card 1: U192k [UMC202HD 192k], device 0: USB Audio [USB Audio]
#   Subdevices: 1/1
#   Subdevice #0: subdevice #0

# List ALSA capture devices
arecord -l

# Expected output:
# card 1: U192k [UMC202HD 192k], device 0: USB Audio [USB Audio]
#   Subdevices: 1/1
#   Subdevice #0: subdevice #0
```

### Identify Device Names

ALSA devices can be referenced by:
- **Card number**: `hw:1,0` (card 1, device 0)
- **Card name**: `hw:U192k` (using card name)
- **Logical name**: `default` (system default)
- **PCM name**: `plughw:1,0` (with format conversion)

## ALSA Configuration

### System-Wide Configuration

Create or edit `/etc/asound.conf`:

```bash
sudo nano /etc/asound.conf
```

**Basic Configuration (Single USB Interface):**

```
# Make USB audio interface the default
defaults.pcm.card 1
defaults.ctl.card 1

# Define USB audio interface PCM device
pcm.usb_audio {
    type hw
    card 1
    device 0
}

# Capture device with automatic format conversion
pcm.usb_capture {
    type plug
    slave {
        pcm "hw:1,0"
        format S24_3LE
        rate 48000
        channels 2
    }
}

# Playback device with automatic format conversion
pcm.usb_playback {
    type plug
    slave {
        pcm "hw:1,0"
        format S24_3LE
        rate 48000
        channels 2
    }
}
```

**Multi-Source Configuration (Multiple USB Interfaces):**

```
# Primary receiver on card 1
pcm.receiver_primary {
    type plug
    slave {
        pcm "hw:1,0"
        rate 48000
    }
}

# Secondary receiver on card 2
pcm.receiver_secondary {
    type plug
    slave {
        pcm "hw:2,0"
        rate 48000
    }
}

# Multi-device capture (aggregate inputs)
pcm.multi_capture {
    type multi
    slaves {
        a { pcm "hw:1,0" channels 2 }
        b { pcm "hw:2,0" channels 2 }
    }
    bindings {
        0 { slave a channel 0 }
        1 { slave a channel 1 }
        2 { slave b channel 0 }
        3 { slave b channel 1 }
    }
}
```

### User Configuration

For per-user ALSA config, create `~/.asoundrc`:

```bash
nano ~/.asoundrc
```

Same syntax as `/etc/asound.conf`, but applies only to current user.

### Test ALSA Configuration

```bash
# Test playback with speaker-test
speaker-test -c 2 -t wav -D usb_playback

# Record 10 seconds of audio and play it back
arecord -D usb_capture -f cd -d 10 test.wav
aplay test.wav

# Monitor live input
arecord -D usb_capture -f cd | aplay -
```

## Device Permissions

### Add User to audio Group

```bash
# Add current user to audio group
sudo usermod -aG audio $USER

# Verify membership
groups $USER

# Log out and back in for changes to take effect
```

### udev Rules for USB Audio

Create `/etc/udev/rules.d/85-usb-audio.rules`:

```bash
sudo nano /etc/udev/rules.d/85-usb-audio.rules
```

**Generic USB Audio Rule:**

```
# Allow audio group access to all USB audio devices
SUBSYSTEM=="sound", GROUP="audio", MODE="0660"
KERNEL=="pcmC[0-9]D[0-9][cp]", GROUP="audio", MODE="0660"
KERNEL=="controlC[0-9]", GROUP="audio", MODE="0660"
```

**Device-Specific Rules:**

```
# Behringer UMC202HD (Vendor ID: 1397, Product ID: 0507)
SUBSYSTEM=="usb", ATTR{idVendor}=="1397", ATTR{idProduct}=="0507", GROUP="audio", MODE="0660", TAG+="uaccess"

# Focusrite Scarlett 2i2 3rd Gen (Vendor ID: 1235, Product ID: 8210)
SUBSYSTEM=="usb", ATTR{idVendor}=="1235", ATTR{idProduct}=="8210", GROUP="audio", MODE="0660", TAG+="uaccess"
```

**Reload udev rules:**

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger
```

## Audio Routing

### Input Routing (Monitoring Sources)

**Single Receiver:**
```
[Weather Radio] ---> [Audio Out] ---> [USB Interface Input 1] ---> [EAS Station Capture]
```

**Multiple Receivers (Mixer):**
```
[Weather Radio 1] ---> [Mixer Channel 1]
[Weather Radio 2] ---> [Mixer Channel 2]    ---> [Mixer Main Out] ---> [USB Interface] ---> [EAS Station]
[EAS Encoder]     ---> [Mixer Channel 3]
```

**Multiple USB Interfaces:**
```
[Weather Radio 1] ---> [USB Interface 1 Input 1] ---> [EAS Station Source 1]
[Weather Radio 2] ---> [USB Interface 2 Input 1] ---> [EAS Station Source 2]
```

### Output Routing (Alert Playout)

**Direct to Transmitter:**
```
[EAS Station Playout] ---> [USB Interface Output] ---> [Transmitter Audio Input]
```

**Through Mixer/Console:**
```
[EAS Station Playout] ---> [USB Interface Output] ---> [Mixer EAS Channel] ---> [Program Bus] ---> [Transmitter]
```

**Monitor and Program Buses:**
```
[EAS Station Playout] ---> [USB Interface Output 1] ---> [Studio Monitors]
                      ---> [USB Interface Output 2] ---> [Transmitter Input]
```

### Loopback for Testing

Create ALSA loopback device for testing without hardware:

```bash
# Load loopback kernel module
sudo modprobe snd-aloop

# Make permanent (add to /etc/modules)
echo "snd-aloop" | sudo tee -a /etc/modules

# Loopback appears as two devices:
# - hw:Loopback,0,0 - playback to device 0, appears on capture 0
# - hw:Loopback,0,1 - playback to device 1, appears on capture 1
```

## Testing and Calibration

### Input Level Calibration

1. **Generate test tone from source:**
   - Use 1kHz sine wave at reference level (-20dBFS or 0VU)
   - Most broadcast equipment outputs 0VU = +4dBu

2. **Measure input level in EAS Station:**
   - Navigate to `/settings/audio-sources`
   - Enable metering for input source
   - Observe peak and RMS meters

3. **Adjust input gain:**
   - Target: Peak levels at -6dBFS to -3dBFS
   - RMS levels at -18dBFS to -12dBFS
   - No clipping (red indicators)

4. **Adjust on audio interface:**
   - Use physical gain knob or switch
   - Pad switch for hot signals (+4dBu)
   - Avoid digital gain in software (adds noise)

### Output Level Calibration

1. **Generate test tone in EAS Station:**
   - Use audio playout test function
   - 1kHz sine wave at -20dBFS

2. **Measure at transmitter input:**
   - Should read 0VU or +4dBu
   - Check with oscilloscope or multimeter

3. **Adjust output level:**
   - Use USB interface output level control
   - Or adjust transmitter input sensitivity
   - Avoid overdriving transmitter (distortion, splatter)

### Frequency Response Test

```bash
# Generate frequency sweep (requires sox)
sox -n sweep.wav synth 10 sine 20-20000

# Play sweep and monitor
aplay -D usb_playback sweep.wav

# Record sweep for analysis
arecord -D usb_capture -f cd -d 10 recorded_sweep.wav
```

Analyze recorded sweep with:
- Audacity (free, cross-platform)
- SoX spectrum analysis
- REW (Room EQ Wizard)

Target: Flat response ±3dB from 300Hz to 3kHz (voice range)

### Latency Testing

```bash
# Measure round-trip latency
# Play tone and measure delay between output and input

# Install jack-delay (requires JACK audio)
sudo apt install jack-delay

# Or use simple arecord/aplay loopback:
arecord -D usb_capture -f cd | aplay -D usb_playback
```

Acceptable latency:
- **Monitoring only**: <50ms
- **Playout with timing requirements**: <20ms
- **Real-time encoding**: <10ms

## Performance Tuning

### Disable PulseAudio

For real-time audio, disable PulseAudio and use ALSA directly:

```bash
# Stop PulseAudio
systemctl --user stop pulseaudio.socket
systemctl --user stop pulseaudio.service

# Disable PulseAudio from starting
systemctl --user disable pulseaudio.socket
systemctl --user disable pulseaudio.service

# Mask PulseAudio (prevent any activation)
systemctl --user mask pulseaudio.socket
systemctl --user mask pulseaudio.service

# Reboot to ensure clean state
sudo reboot
```

**To re-enable PulseAudio later:**
```bash
systemctl --user unmask pulseaudio.socket
systemctl --user enable pulseaudio.socket
systemctl --user start pulseaudio.socket
```

### USB Audio Buffer Tuning

Adjust ALSA buffer sizes for lower latency:

```bash
# Edit /etc/modprobe.d/alsa-base.conf
sudo nano /etc/modprobe.d/alsa-base.conf

# Add USB audio tuning:
options snd-usb-audio nrpacks=1
options snd-usb-audio async_unlink=0
```

**Warning:** Smaller buffers reduce latency but increase CPU usage and risk audio dropouts.

### Real-Time Priority

Grant real-time scheduling priority:

```bash
# Edit /etc/security/limits.conf
sudo nano /etc/security/limits.conf

# Add:
@audio   -  rtprio     95
@audio   -  memlock    unlimited
```

Reboot for changes to take effect.

### CPU Frequency Scaling

Disable CPU frequency scaling for consistent performance:

```bash
# Install cpufrequtils
sudo apt install cpufrequtils

# Set governor to performance
sudo cpufreq-set -g performance

# Make permanent (edit /etc/default/cpufrequtils):
echo 'GOVERNOR="performance"' | sudo tee /etc/default/cpufrequtils

# Restart service
sudo systemctl restart cpufrequtils
```

## Troubleshooting

### No Audio Devices Detected

**Symptoms:**
- `arecord -l` shows no devices
- USB audio interface not listed

**Solutions:**

```bash
# 1. Check USB connection
lsusb

# 2. Check kernel messages
dmesg | grep -i audio
dmesg | grep -i usb

# 3. Reload USB audio driver
sudo modprobe -r snd_usb_audio
sudo modprobe snd_usb_audio

# 4. Check for power issues
vcgencmd get_throttled
# If output is not "throttled=0x0", undervoltage or thermal throttling occurred

# 5. Test with different USB port
# Try other USB 3.0 ports

# 6. Check device permissions
ls -l /dev/snd/
```

### Audio Dropouts or Crackling

**Symptoms:**
- Intermittent audio glitches
- Pops and clicks during recording
- Buffer underrun messages in logs

**Solutions:**

```bash
# 1. Increase USB audio buffer size
# Edit /etc/modprobe.d/alsa-base.conf
options snd-usb-audio nrpacks=4

# 2. Disable USB power management
# Edit /etc/default/grub (for x86) or /boot/cmdline.txt (for Pi)
# Add: usbcore.autosuspend=-1

# 3. Check CPU load
top
# If audio processes are consuming >80% CPU, upgrade hardware

# 4. Check for USB bandwidth conflicts
# Remove other USB devices (cameras, storage) and test

# 5. Update firmware (Raspberry Pi)
sudo rpi-update

# 6. Check logs for errors
journalctl -u docker-eas-station -f
```

### Sample Rate Mismatch

**Symptoms:**
- Playback too fast or too slow
- "sample rate mismatch" errors

**Solutions:**

```bash
# 1. Check supported sample rates
cat /proc/asound/card1/stream0

# 2. Force sample rate in ALSA config
# Edit /etc/asound.conf or ~/.asoundrc
pcm.usb_audio {
    type plug
    slave {
        pcm "hw:1,0"
        rate 48000  # Force 48kHz
    }
}

# 3. Set EAS Station to match interface rate
# Edit .env file
AUDIO_INGEST_SAMPLE_RATE=48000

# 4. Restart services
docker-compose restart
```

### Ground Loops and Hum

**Symptoms:**
- 60Hz or 50Hz hum in audio
- Buzz or hum that varies with other equipment

**Solutions:**

1. **Check grounding:**
   - Connect all audio equipment to same electrical outlet
   - Use same ground reference

2. **Use balanced connections:**
   - Replace unbalanced (TS) cables with balanced (TRS or XLR)

3. **Ground loop isolator:**
   - Install between audio source and USB interface
   - Examples: Behringer HD400, ART DTI, Ebtech Hum X

4. **Ferrite chokes:**
   - Add to audio cables near source and interface
   - Reduces RF interference

5. **Power conditioning:**
   - Use isolated power supply for audio equipment
   - Add line filters

### USB Device Resets

**Symptoms:**
- USB audio device disconnects and reconnects
- "device not responding" errors in dmesg

**Solutions:**

```bash
# 1. Check power supply
# Ensure using official Raspberry Pi power supply (5V 3A minimum)

# 2. Use powered USB hub
# Add external USB 3.0 hub with power adapter

# 3. Disable USB autosuspend
echo -1 | sudo tee /sys/module/usbcore/parameters/autosuspend

# Make permanent (add to /etc/rc.local before exit 0):
echo -1 > /sys/module/usbcore/parameters/autosuspend

# 4. Check for electromagnetic interference
# Move Pi and USB devices away from transmitters and RF equipment

# 5. Replace USB cable
# Use shielded USB cable with ferrite chokes
```

### ALSA Configuration Not Applied

**Symptoms:**
- Changes to /etc/asound.conf not taking effect
- Wrong audio device still in use

**Solutions:**

```bash
# 1. Restart ALSA
sudo /etc/init.d/alsa-utils restart

# 2. Reload ALSA configuration
sudo alsactl restore

# 3. Restart application
docker-compose restart

# 4. Check for syntax errors
# Test ALSA config
aplay -L
arecord -L

# 5. Verify file permissions
ls -l /etc/asound.conf
# Should be readable by all users
```

## Docker Audio Integration

### Expose Audio Devices to Docker

**In `docker-compose.yml`:**

```yaml
services:
  app:
    devices:
      - /dev/snd:/dev/snd  # Expose all ALSA devices
    group_add:
      - audio  # Add container to audio group
    environment:
      - PULSE_SERVER=unix:/run/user/1000/pulse/native  # If using PulseAudio
    volumes:
      - /run/user/1000/pulse:/run/user/1000/pulse  # PulseAudio socket
      - ~/.config/pulse:/home/appuser/.config/pulse  # PulseAudio config
```

### Privileged Mode (Not Recommended for Production)

```yaml
services:
  app:
    privileged: true  # Grants all device access
```

Use `privileged: true` only for development/testing. Production deployments should use specific device mappings.

## Audio Monitoring Tools

### Command-Line Tools

```bash
# Install audio tools
sudo apt install alsa-utils sox pulseaudio-utils

# Real-time level meter (requires sox)
rec -t alsa hw:1,0 -n stats

# ALSA mixer (adjust levels)
alsamixer

# View detailed device info
cat /proc/asound/cards
cat /proc/asound/card1/stream0

# Monitor audio activity
alsaplayer test.wav
```

### Graphical Tools

```bash
# Install Audacity for waveform analysis
sudo apt install audacity

# Or use QjackCtl for JACK routing (advanced)
sudo apt install qjackctl
```

## Best Practices

1. **Use balanced audio connections** whenever possible (XLR or TRS)
2. **Keep audio cables short** (<6 feet/2 meters preferred)
3. **Route audio cables away from power cables** (avoid 50/60Hz hum)
4. **Label all cables** (use label maker or tape)
5. **Document your configuration** (create wiring diagram)
6. **Test regularly** (daily audio level checks, weekly frequency sweeps)
7. **Keep spare equipment** (backup USB interface, cables)
8. **Monitor for errors** (check logs daily for audio warnings)
9. **Update firmware** (USB interface, Raspberry Pi bootloader)
10. **Ground everything properly** (prevents hum and RFI)

## Additional Resources

- [ALSA Project Documentation](https://www.alsa-project.org/wiki/Main_Page)
- [Raspberry Pi Audio Guide](https://www.raspberrypi.com/documentation/computers/configuration.html#audio-configuration)
- [USB Audio Class Specification](https://www.usb.org/document-library/audio-devices-rev-30-and-adopters-agreement)
- [Reference Pi Build Guide](../hardware/reference_pi_build.md)
- [System Health Monitoring](post_install.md#system-health-monitoring)

---

**Document Version:** 1.0
**Last Updated:** 2025-11-05
**Maintainer:** EAS Station Development Team
