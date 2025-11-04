# SDR Receiver Setup

Configure software-defined radio receivers for EAS alert verification.

## Supported Hardware

- RTL-SDR (RTL2832U chipset)
- Airspy Mini/R2
- HackRF One
- Other OsmoSDR-compatible devices

## RTL-SDR Setup

### Install Drivers

**On Host System:**
```bash
sudo apt update
sudo apt install rtl-sdr
```

### USB Passthrough (Docker)

Add to `docker-compose.yml`:

```yaml
services:
  eas-station:
    devices:
      - /dev/bus/usb:/dev/bus/usb
    privileged: true  # Or specific capabilities
```

### Test SDR

```bash
rtl_test -t
```

Expected output:
```plaintext
Found 1 device(s):
  0:  Realtek, RTL2838UHIDIR, SN: 00000001
Using device 0: Generic RTL2832U OEM
```

## Configuration

In `.env` or admin panel:

```bash
# SDR receiver settings
SDR_ENABLED=true
SDR_DEVICE_INDEX=0
SDR_FREQUENCY=162550000  # NOAA Weather Radio
SDR_SAMPLE_RATE=2400000
```

## Antenna Setup

For NOAA Weather Radio (162.400-162.550 MHz):

- Use 1/4 wave antenna (~18 inches)
- Vertical polarization
- Clear line of sight preferred
- Indoor antenna acceptable for testing

## Troubleshooting

**Device not found:**
```bash
lsusb | grep -i realtek
# Should show RTL2832U device
```

**Permission denied:**
```bash
sudo usermod -aG plugdev $USER
# Logout and login again
```

See [Troubleshooting Guide](../troubleshooting.md) for more help.
