# LED Sign Integration

Connect Alpha Protocol LED displays for visual emergency alerts.

## Compatible Hardware

- BetaBrite LED signs
- American Time & Signal displays
- Alpha Protocol compatible displays
- Any serial LED sign (RS232/RS485) via Lantronix adapter

## Connection Methods

EAS Station connects to LED signs via TCP/IP using a **Lantronix serial-to-Ethernet adapter** (or compatible device). The adapter provides a transparent bridge between:

- **LED Sign:** Serial interface (RS232 or RS485)
- **Network:** Ethernet/TCP connection
- **EAS Station:** TCP/IP client

### How It Works

The Lantronix adapter **emulates a serial port over TCP/IP**:

1. EAS Station sends M-Protocol commands via TCP to the adapter's IP address
2. The adapter converts TCP data to serial data (RS232 or RS485)
3. The LED sign receives standard serial commands
4. Response data flows back through the adapter to EAS Station

This architecture allows:
- Remote LED sign placement anywhere on your network
- No need for USB-to-serial adapters on the server
- Easy scaling to multiple LED signs
- Standard network troubleshooting tools (ping, telnet)

### Serial Mode Selection

Choose the correct serial mode for your LED sign hardware:

**RS232 (Standard Serial)**
- Most common for LED signs
- Point-to-point connection (one sign per adapter)
- Maximum distance: ~50 feet
- DB9 or DB25 connector
- Voltage levels: ±3V to ±15V

**RS485 (Industrial Serial)**
- Long-distance communication (up to 4000 feet)
- Multi-drop capable (multiple signs on one bus)
- Twisted-pair wiring
- Better noise immunity
- Common in industrial/outdoor installations

## Lantronix Adapter Setup

### 1. Configure Lantronix Adapter

Access your Lantronix adapter's web interface or serial console:

**Network Settings:**
- IP Address: Static IP on your network (e.g., `192.168.1.200`)
- Port: `10001` (standard Alpha protocol port)
- Protocol: TCP Server mode

**Serial Port Settings (must match your LED sign):**

For **RS232 LED signs:**
- Baud Rate: 9600 or 19200 (check sign manual)
- Data Bits: 8
- Stop Bits: 1
- Parity: None
- Flow Control: None (or RTS/CTS if required)

For **RS485 LED signs:**
- Baud Rate: 9600 or 19200 (check sign manual)
- Data Bits: 8
- Stop Bits: 1
- Parity: None
- RS485 Mode: 2-wire or 4-wire (depends on sign)
- Termination: Enable if at end of bus

**Connection Mode:**
- Set to "TCP Server" or "Accept connections"
- Port: 10001
- No encryption/authentication needed for local network

### 2. Test Lantronix Connection

Verify the adapter is accessible:

```bash
# Ping the adapter
ping 192.168.1.200

# Test TCP connection
telnet 192.168.1.200 10001
```

If telnet connects successfully, the adapter is ready.

### 3. Physical Wiring

**RS232 Connection:**
- Connect DB9/DB25 serial cable from adapter to LED sign
- Minimum wiring: TX, RX, GND (pins 2, 3, 5 on DB9)
- Use straight-through cable (not null-modem)

**RS485 Connection:**
- Connect A/B twisted pair from adapter to LED sign
- Observe polarity (A to A, B to B)
- Add termination resistor (120Ω) at far end if needed
- Use shielded twisted-pair cable for long runs

## Network Setup

### Find Lantronix Adapter IP

Check your router's DHCP leases or scan for the adapter:

```bash
nmap -p 10001 192.168.1.0/24
```

### Configure Static IP (Recommended)

Set a static IP on the Lantronix adapter or reserve its DHCP lease.

## EAS Station Configuration

In `.env`:

```bash
# Lantronix adapter IP address
LED_SIGN_IP=192.168.1.200

# TCP port (standard Alpha port)
LED_SIGN_PORT=10001

# Serial mode (RS232 or RS485)
LED_SERIAL_MODE=RS232

# Baud rate (must match adapter and sign)
LED_BAUD_RATE=9600

# Default display content
DEFAULT_LED_LINES=PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY
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

1. Verify network connectivity to Lantronix adapter:
   ```bash
   ping $LED_SIGN_IP
   ```

2. Check TCP port is accessible:
   ```bash
   telnet $LED_SIGN_IP $LED_SIGN_PORT
   ```

3. Verify Lantronix adapter settings:
   - Check serial port configuration (baud rate, data bits, parity)
   - Ensure TCP server mode is enabled
   - Verify correct port number (10001)

4. Check physical serial connection:
   - Verify cables are securely connected
   - For RS232: Check TX/RX pins are correct
   - For RS485: Verify A/B polarity and termination

5. LED sign issues:
   - Verify sign is powered on
   - Check sign is in remote/network control mode
   - Verify protocol compatibility (M-Protocol/Alpha)
   - Check sign's serial settings match adapter

**Common Issues:**

**"Connection refused" or timeout:**
- Lantronix adapter may not be configured for TCP server mode
- Firewall blocking port 10001
- Wrong IP address

**Characters garbled or missing:**
- Baud rate mismatch between adapter and sign
- Wrong serial mode (RS232 vs RS485)
- Cable wiring issue

**Intermittent connection:**
- Check network stability
- RS485: Add or check termination resistors
- Cable may be damaged or too long for RS232

**Compatible Lantronix Models:**
- UDS1100 (1-port)
- UDS2100 (2-port)
- xDirect
- XPort series
- Any device supporting "serial-to-TCP" or "raw TCP" mode

See [Troubleshooting Guide](../troubleshooting.md).
