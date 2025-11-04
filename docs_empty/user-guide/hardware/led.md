# LED Sign Integration

Connect Alpha Protocol LED displays for visual emergency alerts.

## Compatible Hardware

- BetaBrite LED signs
- American Time & Signal displays
- Alpha Protocol compatible displays
- TCP/IP enabled signs

## Network Setup

### Find LED Sign IP

Most LED signs use DHCP. Check your router's DHCP leases or use:

```bash
nmap -p 10001 192.168.1.0/24
```

### Configure Static IP (Recommended)

Set static IP on LED sign or reserve DHCP lease.

## Configuration

In `.env`:

```bash
LED_SIGN_IP=192.168.1.100
LED_SIGN_PORT=10001
DEFAULT_LED_LINES=LINE 1,LINE 2,LINE 3,LINE 4
```

## Testing Connection

```bash
telnet $LED_SIGN_IP $LED_SIGN_PORT
```

Should connect successfully.

## Alpha Protocol

EAS Station uses Alpha Protocol to control signs:

- Text display
- Colors (if supported)
- Special effects
- Multiple pages

## Message Templates

Configure default messages:

1. Navigate to **Admin → LED Settings**
2. Set default messages
3. Configure alert templates
4. Test display

## Troubleshooting

**Sign not responding:**

1. Verify network connectivity:
   ```bash
   ping $LED_SIGN_IP
   ```

2. Check port open:
   ```bash
   telnet $LED_SIGN_IP $LED_SIGN_PORT
   ```

3. Verify protocol compatibility
4. Check sign is in remote mode

See [Troubleshooting Guide](../troubleshooting.md).
