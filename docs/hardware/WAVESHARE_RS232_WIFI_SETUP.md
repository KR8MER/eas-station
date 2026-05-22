# Waveshare RS232/485 to WiFi POE ETH Adapter Setup Guide

This guide explains how to configure the **Waveshare RS232/485 TO WIFI POE ETH (B)** adapter to work with EAS Station for network-based serial communication with VFD displays and other serial devices.

## Overview

The Waveshare adapter allows you to connect serial devices (like VFD displays, LED signs) over your network instead of requiring direct USB/serial port connections. This provides several benefits:

- **Remote device placement** - Serial device can be anywhere on the network
- **No USB cables required** - Use existing Ethernet infrastructure
- **PoE support** - Single cable for both data and power
- **Multiple connections** - Two independent serial ports (Socket A and B)

## Hardware Setup

### 1. Physical Connections

1. **Power**: Connect PoE Ethernet cable or use the included power adapter
2. **Serial Device**: Connect your VFD display to the RS232 terminal block:
   - TX → RX on VFD
   - RX → TX on VFD  
   - GND → GND on VFD

### 2. Network Configuration

Access the Waveshare web interface to configure the adapter:

1. **Initial Access**: 
   - Default IP: Usually `192.168.1.200` (check documentation)
   - Connect via web browser: `http://192.168.1.200`
   - Default credentials: `admin` / `admin`

2. **Set Static IP** (Recommended):
   - Navigate to Network Settings
   - Set static IP address: `192.168.8.122` (or your preference)
   - Set subnet mask: `255.255.255.0`
   - Set gateway: Your network gateway
   - **Save and reboot adapter**

### 3. Serial Port Configuration

Configure the UART settings to match your VFD display:

**Uart Setting:**
- Baudrate: `9600` (for Waveshare), but VFD typically uses `38400`
- Data Bits: `8`
- Parity: `None`
- Stop: `1`
- Baudrate adaptive: `Enable` (RFC2117)

**UART AutoFrame Setting:**
- UART AutoFrame: `Enable`
- AutoFrame Time: `500` ms
- AutoFrame Length: `512` bytes

**Network A Setting** (Primary serial port):
- Mode: `Server`
- Protocol: `TCP`
- Port: `10001` (default, you can change this)
- Server Address: `10.10.100.100` (not used in Server mode)
- MAX TCP Num: `24`
- TCP Time out: `0` (no timeout)
- TCP connection password: `Disable`

**Socket B Setting** (Optional second port):
- Open the SocketB function: `on`
- Protocol: `TCP`
- Port: `18899`

**Other Settings:**
- Registered Package Type: `off`
- Custom Heartbeat: `off`
- Socket Distribution: `on`
- Modbus Polling: `off`
- Httpdclient Mode: `long`
- 485 selector switch: `off`

## EAS Station Configuration

### Method 1: Web Interface (Recommended)

1. Navigate to **Settings → Environment Variables**
2. Scroll to **VFD Display** section
3. Set **Connection** field to: `socket://192.168.8.122:10001`
4. Set **Baud Rate** to: `38400` (your VFD's actual baud rate)
5. Click **Save Changes**
6. Click **Restart Services** → Select **Hardware Service**
7. Monitor the Hardware Service logs to verify connection

### Method 2: Environment File

Edit `/opt/eas-station/.env` (or your `.env` file):

```bash
# VFD Display Configuration - Network via Waveshare
VFD_PORT=socket://192.168.8.122:10001
VFD_BAUDRATE=38400
```

Then restart the hardware service:
```bash
sudo systemctl restart eas-station-hardware.target
```

## Testing the Connection

### Test 1: Using PuTTY (Windows/Linux)

1. **Install PuTTY**:
   - Windows: Download from https://www.putty.org/
   - Linux: `sudo apt-get install putty`

2. **Configure PuTTY**:
   - Connection type: `Raw` (not SSH or Telnet)
   - Host Name: `192.168.8.122`
   - Port: `10001`
   - Click **Open**

3. **Test Communication**:
   - Type characters in PuTTY window
   - You should see them appear on the VFD display (if configured for text mode)
   - If using the GU-7000 protocol, you'll need to send specific command sequences

### Test 2: Using netcat/nc (Linux)

```bash
# Connect to the adapter
nc 192.168.8.122 10001

# Send test text (for text-mode VFDs)
echo "Hello World" | nc 192.168.8.122 10001

# Test connection is open
timeout 5 nc -z -v 192.168.8.122 10001
```

### Test 3: Using Python

```python
import socket

# Connect to Waveshare adapter
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.connect(('192.168.8.122', 10001))

# Send test data
sock.send(b'Test message\r\n')

# Receive response (if any)
response = sock.recv(1024)
print(f"Response: {response}")

sock.close()
```

## Troubleshooting

### Connection Refused

**Symptom**: Cannot connect to `192.168.8.122:10001`

**Solutions**:
1. Verify adapter IP address with `ping 192.168.8.122`
2. Check firewall settings on adapter web interface
3. Ensure Mode is set to `Server` (not Client)
4. Verify port number is `10001`
5. Check adapter is powered on and linked (LED indicators)

### VFD Shows Garbage Characters

**Symptom**: Display shows random characters or corrupted output

**Solutions**:
1. **Baud rate mismatch**: 
   - Waveshare adapter: Usually 9600
   - VFD device: Check your model (typically 38400)
   - Set `VFD_BAUDRATE` in EAS Station to match VFD device
2. **Check wiring**: TX/RX might be swapped
3. **Verify data format**: 8N1 (8 data bits, No parity, 1 stop bit)

### No Data on VFD

**Symptom**: VFD is blank, no output

**Solutions**:
1. Check VFD power supply
2. Verify TX/RX wiring connections
3. Test with PuTTY first to isolate EAS Station vs. adapter issues
4. Check Hardware Service logs: `sudo journalctl -u eas-station-hardware.target -f`
5. Verify VFD brightness settings (might be set too dim)

### EAS Station Can't Connect

**Symptom**: EAS Station logs show "Failed to connect to VFD on socket://..."

**Solutions**:
1. Check network connectivity: `ping 192.168.8.122`
2. Verify port is open: `nc -z -v 192.168.8.122 10001`
3. Check firewall on EAS Station host
4. Restart hardware service: Via web UI or `sudo systemctl restart eas-station-hardware.target`
5. Verify `VFD_PORT` format: Must start with `socket://`

### Multiple Connection Attempts

**Symptom**: Waveshare shows multiple connections from EAS Station

**Solutions**:
1. Set **MAX TCP Num** to `1` if you only need one connection
2. Check for duplicate service instances
3. Verify **TCP Time out** setting (0 = no timeout)

## Advanced Configuration

### Using Socket B (Second Port)

The Waveshare adapter supports two independent serial ports. To use the second port:

1. Enable Socket B in adapter settings (port 18899)
2. In EAS Station, configure second device:
   ```bash
   LED_PORT=socket://192.168.8.122:18899
   ```

### Password Protection

To enable TCP connection password:

1. In Waveshare web interface, set **TCP connection password authentication**: `Enable`
2. Enter password
3. **Note**: pyserial doesn't support authentication directly - you'll need to modify the connection code

### SSL/TLS Encryption

The basic Waveshare adapter doesn't support SSL/TLS. For encrypted connections:

1. Use a reverse proxy (nginx, stunnel)
2. Configure tunnel from adapter to proxy
3. Point EAS Station to encrypted endpoint

## Reference Information

### Waveshare Specifications

- **Model**: RS232/485 TO WIFI POE ETH (B)
- **Voltage**: PoE (802.3af) or 5V DC
- **Serial Ports**: 2 independent ports (Socket A & B)
- **Protocols**: TCP Server, TCP Client, UDP
- **Baud Rates**: 1200 - 230400 bps
- **Documentation**: https://www.waveshare.com/wiki/RS232/485_TO_WIFI_POE_ETH_(B)

### EAS Station Serial Support

- **Direct Serial**: `/dev/ttyUSB0`, `/dev/ttyACM0`, etc.
- **Network Serial**: `socket://HOST:PORT`
- **RFC2217**: `rfc2217://HOST:PORT` (telnet-based serial)

### Supported Devices

This configuration works with:
- ✅ VFD displays (Noritake GU140x32F-7000B)
- ✅ LED signs (BetaBrite, Alpha, etc.)
- ✅ Serial relays and controllers
- ✅ Any RS232/RS485 device

## Related Documentation

- [VFD Display Setup](VFD_SETUP.md)
- [Hardware Integration Guide](../guides/HARDWARE_INTEGRATION.md)
- [Environment Variables Reference](../reference/ENVIRONMENT_VARIABLES.md)
- [Troubleshooting Guide](../troubleshooting/HARDWARE_TROUBLESHOOTING.md)

---

**Need Help?**
- Check logs: **Logs → Hardware Service**
- Ask in GitHub Discussions: https://github.com/KR8MER/eas-station/discussions
- Report issues: https://github.com/KR8MER/eas-station/issues
