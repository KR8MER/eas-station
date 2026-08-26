# Serial-to-Ethernet Adapter Configuration Guide

Complete setup instructions for connecting RS232/RS485 devices (LED signs, VFD displays) to EAS Station™ via network adapters.

---

## Table of Contents

1. [Waveshare RS232/485 TO WIFI POE ETH (B)](#waveshare-rs232485-to-wifi-poe-eth-b)
2. [USR-TCP232-410S Serial Server](#usr-tcp232-410s-serial-server)
3. [Moxa NPort 5110 Serial Server](#moxa-nport-5110-serial-server)
4. [Perle IOLAN SDS Serial Server](#perle-iolan-sds-serial-server)
5. [Generic Serial-to-Ethernet Adapters](#generic-serial-to-ethernet-adapters)
6. [EAS Station™ Configuration](#eas-stationtm-configuration_4)
7. [Troubleshooting](#troubleshooting)

---

## Waveshare RS232/485 TO WIFI POE ETH (B)

### Recommended for: Alpha LED signs, Noritake VFD displays

### Initial Setup

**1. Connect to Waveshare Web Interface**

Default access:
- IP Address: `192.168.1.200` (factory default)
- URL: `http://192.168.1.200`
- Username: `admin`
- Password: `admin`

**2. Set Static IP Address**

Navigate to: **Network Settings**

```
IP Address: 192.168.8.122  (or your preferred IP)
Subnet Mask: 255.255.255.0
Gateway: 192.168.8.1  (your network gateway)
DNS Server: 8.8.8.8  (or your DNS server)
DHCP: Disable  (use static IP)
```

**Save and Reboot** the adapter.

### Serial Port Configuration

#### For Alpha LED Sign (Premier/BetaBrite)

Navigate to: **Wifi-Uart Setting**

**Uart Setting:**
```
Baudrate: 9600
Data Bits: 8
Parity: None
Stop: 1
Flow Control: None
Baudrate adaptive (RFC2117): Enable
```

**UART AutoFrame Setting:**
```
UART AutoFrame: Enable
AutoFrame Time: 500 ms  (adjust 100-10000ms)
AutoFrame Length: 512 bytes  (adjust 16-4096 bytes)
```

**Registered Package Setting:**
```
Registered Package Type: off
Upload Manner: off
```

**Custom heartbeat packet settings:**
```
Custom Heartbeat: off
```

**Socket Distribution settings:**
```
Socket Distribution: on
```

**Modbus Polling settings:**
```
Modbus Polling: off
```

**Httpdclient Mode settings:**
```
Httpdclient Mode: long
```

**485 Switch Settings:**
```
485 selector switch: off  (use for RS232)
```

**Network A Setting (Primary Port):**
```
Mode: Server
Protocol: TCP
Port: 10001
Server Address: (leave blank - not used in Server mode)
MAX TCP Num. (1~24): 1  (only need one connection)
TCP Time out (MAX 600 s): 0  (no timeout)
TCP connection password authentication: Disable
```

**Socket B Setting (Optional Second Port):**
```
Open the SocketB function: off  (or on if using two devices)
Protocol: TCP
Port: 18899
Server Address: (leave blank)
TCPB Time out: 0
```

#### For Noritake VFD Display

Same settings as Alpha LED, except:

**Uart Setting:**
```
Baudrate: 38400  (common for VFD, check your model)
Data Bits: 8
Parity: None
Stop: 1
```

All other settings remain the same.

### Wiring Connections

**RS232 Wiring (3-wire):**
```
Waveshare → Device
TX       → RX
RX       → TX
GND      → GND
```

**RS485 Wiring (2-wire):**
```
Waveshare → Device
485-A    → A (or +)
485-B    → B (or -)
```

### Power Options

1. **PoE (Power over Ethernet)**: IEEE 802.3af compatible
2. **DC Power**: 5V DC via barrel jack (included adapter)

### EAS Station™ Configuration

```bash
# For Alpha LED Sign
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001

# For VFD Display
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

## USR-TCP232-410S Serial Server

### Recommended for: High-reliability applications, industrial environments

### Initial Setup

**1. Connect to USR Web Interface**

Default access:
- IP Address: `192.168.0.7` (factory default)
- URL: `http://192.168.0.7`
- Username: `admin`
- Password: `admin`

**2. Network Configuration**

Navigate to: **Network Settings → Basic Settings**

```
Work Mode: TCP Server
IP Type: Static IP
IP Address: 192.168.8.122
Subnet Mask: 255.255.255.0
Gateway: 192.168.8.1
```

### Serial Port Configuration

Navigate to: **Serial Port Settings**

#### For Alpha LED Sign

```
Baud Rate: 9600
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

#### For VFD Display

```
Baud Rate: 38400
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

### TCP/IP Configuration

Navigate to: **TCP/IP Settings**

```
Local Port: 10001
Work Mode: TCP Server
Max Connections: 1
Inactivity Time: 0 (disable timeout)
```

### Advanced Settings

Navigate to: **Advanced Settings**

```
Buffered Serial Data Length: 512 bytes
Buffered Serial Data Timeout: 100 ms
Serial Packet Length: 1024 bytes
Enable RFC2217: Yes (optional, for compatibility)
```

### EAS Station™ Configuration

```bash
# For Alpha LED Sign
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001

# For VFD Display
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

## Moxa NPort 5110 Serial Server

### Recommended for: Enterprise deployments, mission-critical systems

### Initial Setup

**1. Find the Device**

Use Moxa's DeviceInstaller tool (Windows) or:
```bash
# Linux - scan your network
nmap -p 4800 192.168.1.0/24
```

Default IP: `192.168.127.254`

**2. Access Web Interface**

- URL: `http://192.168.127.254`
- Username: `admin`
- Password: `moxa`

### Network Configuration

Navigate to: **Basic Settings → Network**

```
IP Configuration: Static
IP Address: 192.168.8.122
Subnet Mask: 255.255.255.0
Gateway: 192.168.8.1
```

### Operating Mode

Navigate to: **Operating Settings → Operating Mode**

Select: **TCP Server Mode**

```
TCP Port: 10001
Inactivity Time: 0 (never disconnect)
Max Connection: 1
Ignore Jammed IP: No
Allow Driver Control: No
```

### Serial Settings

Navigate to: **Operating Settings → Port 1**

#### For Alpha LED Sign

```
Baud Rate: 9600
Parity: None
Data Bits: 8
Stop Bits: 1
Flow Control: None
FIFO: Enabled
```

#### For VFD Display

```
Baud Rate: 38400
Parity: None
Data Bits: 8
Stop Bits: 1
Flow Control: None
FIFO: Enabled
```

### Data Packing

Navigate to: **Operating Settings → Data Packing**

```
Delimiter 1: 0D (CR)
Delimiter 2: 0A (LF)
Delimiter Process: Do Nothing
Force Transmit: 100 ms
```

### EAS Station™ Configuration

```bash
# For Alpha LED Sign
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001

# For VFD Display
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

## Perle IOLAN SDS Serial Server

### Recommended for: Secure environments, multiple serial ports

### Initial Setup

**1. Access Web Interface**

Default IP: `192.168.1.100`
- URL: `http://192.168.1.100`
- Username: `root`
- Password: `dbps` (or `password`)

**2. Network Configuration**

Navigate to: **System → IP Configuration**

```
IPv4 Address: 192.168.8.122
Subnet Mask: 255.255.255.0
Default Gateway: 192.168.8.1
DNS Server: 8.8.8.8
```

### Serial Port Configuration

Navigate to: **Serial Ports → Port 1 → Settings**

#### For Alpha LED Sign

```
Baud Rate: 9600
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

#### For VFD Display

```
Baud Rate: 38400
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

### TCP Configuration

Navigate to: **Serial Ports → Port 1 → TCP Sockets**

```
Mode: TCP Server
Listen Port: 10001
Protocol: Raw TCP
Connection Timeout: 0 (never)
Max Connections: 1
```

### Data Handling

Navigate to: **Serial Ports → Port 1 → Advanced**

```
Input Buffer: 4096 bytes
Output Buffer: 4096 bytes
Tx Delay: 0 ms
Rx Delay: 100 ms
```

### EAS Station™ Configuration

```bash
# For Alpha LED Sign
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001

# For VFD Display
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

## Generic Serial-to-Ethernet Adapters

### Common Settings for Most Adapters

If your adapter isn't listed above, use these general guidelines:

### Network Settings

```
Mode: TCP Server (not Client)
Protocol: TCP (not UDP or Telnet)
IP Address: 192.168.8.122 (static, not DHCP)
Port: 10001 (or your preference)
Max Connections: 1
Timeout: 0 or disabled
```

### Serial Settings - Alpha LED Sign

```
Baud Rate: 9600
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

### Serial Settings - VFD Display

```
Baud Rate: 38400 (or 9600, 19200 - check your model)
Data Bits: 8
Parity: None
Stop Bits: 1
Flow Control: None
```

### Data Handling

```
Buffering: 512-1024 bytes
Timeout: 100-500 ms
RFC2217: Enable (if available)
Telnet: Disable
```

---

## EAS Station™ Configuration

### For LED Signs (Alpha, BetaBrite, etc.)

**Via Web UI:**
1. Settings → Environment Variables → LED Display
2. LED Sign IP Address: `192.168.8.122`
3. LED Sign Port: `10001`
4. Save and Restart Hardware Service

**Via .env file:**
```bash
LED_SIGN_ENABLED=true
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001
LED_DEFAULT_TEXT=PUTNAM COUNTY,EMERGENCY MGMT,NO ALERTS,SYSTEM READY
```

### For VFD Displays (Noritake, etc.)

**Via Web UI:**
1. Settings → Environment Variables → VFD Display
2. Connection: `socket://192.168.8.122:10001`
3. Baud Rate: `38400`
4. Save and Restart Hardware Service

**Via .env file:**
```bash
VFD_DISPLAY_ENABLED=true
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

## Testing Your Configuration

### Test 1: Network Connectivity

```bash
# Ping the adapter
ping -c 3 192.168.8.122

# Expected: Reply from 192.168.8.122
```

### Test 2: TCP Port Access

```bash
# Check if port is open
nc -z -v 192.168.8.122 10001

# Expected: Connection to 192.168.8.122 10001 port [tcp/*] succeeded!
```

### Test 3: Send Test Data

```bash
# Send test string
echo "TEST" | nc 192.168.8.122 10001

# For Alpha LED (with M-Protocol header):
echo -ne '\x00\x00\x00\x00\x00\x01\x5A\x30\x30TEST\x04' | nc 192.168.8.122 10001
```

### Test 4: PuTTY Test (Windows/Linux)

**Configuration:**
```
Connection Type: Raw
Host Name: 192.168.8.122
Port: 10001
```

**Test:**
1. Click "Open"
2. Type characters
3. They should be sent to the serial device
4. LED sign should display text (if properly formatted)

### Test 5: EAS Station™ Logs

```bash
# Check hardware service logs
sudo journalctl -u eas-station-hardware.target -n 50

# Look for:
# ✅ "Connected to Alpha LED sign at 192.168.8.122:10001"
# ✅ "Connected to Noritake VFD on socket://192.168.8.122:10001"
```

---

## Troubleshooting

### Connection Refused

**Symptom:** "Connection refused" or "Connection failed"

**Check:**
1. Adapter IP address: `ping 192.168.8.122`
2. Port number: Should be 10001
3. Mode: Must be "TCP Server" not "Client"
4. Firewall: Check adapter and network firewall
5. Max connections: Should be at least 1

### Connection Times Out

**Symptom:** Connection attempts hang, no response

**Check:**
1. Network routing: Can you ping the adapter?
2. Port blocking: Firewall blocking port 10001?
3. Adapter mode: Verify TCP Server mode
4. Adapter reboot: Power cycle the adapter

### Data Corruption / Garbage

**Symptom:** Wrong characters, scrambled output

**Check:**
1. Baud rate mismatch: Adapter vs. device
2. Wiring: TX/RX might be swapped
3. Data format: 8N1 (8 data, no parity, 1 stop)
4. Flow control: Should be disabled/none
5. Grounding: Ensure GND is connected

### Device Not Responding

**Symptom:** Connection succeeds but device doesn't respond

**Check:**
1. Serial wiring: TX → RX, RX → TX (crossed)
2. Device power: Is device powered on?
3. Device settings: Check device baud rate
4. Protocol: Verify correct protocol (M-Protocol for Alpha)
5. Buffer settings: Increase timeout/buffer size

### Multiple Connections Error

**Symptom:** "Max connections reached"

**Check:**
1. Max connections: Set to 1 for single client
2. Stale connections: Reboot adapter to clear
3. Connection timeout: Enable timeout to auto-clear
4. Exclusive mode: Some adapters have an exclusive lock

---

## Comparison Table

| Adapter | Typical Price | Best For | Difficulty | PoE | Multiple Ports |
|---------|--------------|----------|------------|-----|----------------|
| **Waveshare RS232/485 WiFi** | $50-70 | Budget, WiFi | Easy | Yes | 2 (A & B) |
| **USR-TCP232-410S** | $40-60 | Reliability | Easy | No | 4 |
| **Moxa NPort 5110** | $150-200 | Enterprise | Medium | No | 1 |
| **Perle IOLAN SDS** | $200-300 | Secure/Multi | Medium | Optional | 1-16 |

---

## Quick Reference Card

### Waveshare Settings Summary

```
Network:
  IP: 192.168.8.122
  Port: 10001
  Mode: Server

Serial:
  Baud: 9600 (LED) or 38400 (VFD)
  Data: 8
  Parity: None
  Stop: 1
  Flow: None

Advanced:
  AutoFrame: Enable
  AutoFrame Time: 500ms
  AutoFrame Length: 512 bytes
  TCP Max: 1
  Timeout: 0
```

### EAS Station™ Settings Summary

```bash
# LED Sign
LED_SIGN_IP=192.168.8.122
LED_SIGN_PORT=10001

# VFD Display
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

---

**Need Help?**
- Check adapter documentation for your specific model
- Test with PuTTY first to isolate EAS Station™ from adapter issues
- Verify serial wiring with a multimeter
- GitHub Issues: https://github.com/KR8MER/eas-station/issues
