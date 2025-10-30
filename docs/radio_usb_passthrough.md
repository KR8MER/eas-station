# USB Passthrough for SDR Receivers

Multi-SDR deployments need direct access to the host USB bus so the SoapySDR
drivers can open RTL2832U and Airspy dongles. Rather than running the
application container with `--privileged`, map the USB device hierarchy into
the service and keep the security profile tight.

## Docker Compose snippet

```yaml
services:
  app:
    image: ghcr.io/kr8mer/noaa-alerts:latest
    devices:
      - /dev/bus/usb:/dev/bus/usb
    environment:
      - RADIO_CAPTURE_DIR=/var/lib/noaa/radio
      - RADIO_CAPTURE_DURATION=30
      - RADIO_CAPTURE_MODE=iq
```

### Checklist

1. Attach the SDR hardware and confirm it appears in `lsusb` on the host.
2. Start the stack with the device mapping above.
3. Verify the container can see the bus:

   ```bash
   docker compose exec app ls /dev/bus/usb
   ```

4. Install the host-side SoapySDR plugins (`soapysdr-module-rtlsdr` or
   `soapysdr-module-airspy`).

### Troubleshooting

- **Permission denied** – make sure the Docker user is a member of the group
  that owns `/dev/bus/usb` (often `plugdev`).
- **Missing driver** – the `driver` field in the radio settings UI should match
  the Soapy module (e.g. `rtlsdr`, `rtl2832u`, or `airspy`).
- **Multiple dongles** – give each receiver a unique identifier so capture
  results are tracked correctly.

Once the mapping is in place the radio settings page can start the receivers
and coordinate IQ captures for SAME bursts.
