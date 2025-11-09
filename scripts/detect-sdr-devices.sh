#!/bin/bash
#
# SDR Device Detection Script
#
# This script detects connected SDR devices and provides the exact USB device
# paths needed for Docker device passthrough.
#
# Usage:
#   ./scripts/detect-sdr-devices.sh
#
# Output:
#   - Lists all detected SDR devices
#   - Shows USB bus/device paths
#   - Provides docker-compose.yml device configuration snippets
#

set -e

echo "=========================================="
echo "EAS Station - SDR Device Detection"
echo "=========================================="
echo ""

# Check if running as root or with sudo
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Warning: This script should be run with sudo for full USB device access"
    echo "   Usage: sudo ./scripts/detect-sdr-devices.sh"
    echo ""
fi

# Check for required commands
MISSING_COMMANDS=()
for cmd in lsusb find; do
    if ! command -v $cmd &> /dev/null; then
        MISSING_COMMANDS+=($cmd)
    fi
done

if [ ${#MISSING_COMMANDS[@]} -ne 0 ]; then
    echo "❌ Error: Missing required commands: ${MISSING_COMMANDS[*]}"
    echo "   On Debian/Ubuntu: sudo apt-get install usbutils"
    echo "   On RHEL/CentOS: sudo yum install usbutils"
    exit 1
fi

# Known SDR device vendor/product IDs
declare -A SDR_DEVICES=(
    # RTL-SDR devices
    ["0bda:2832"]="RTL-SDR (Generic RTL2832U)"
    ["0bda:2838"]="RTL-SDR (RTL2832U)"

    # Airspy devices
    ["1d50:60a1"]="Airspy HF+"
    ["1d50:60b9"]="Airspy R2"
    ["1d50:60b3"]="Airspy Mini"

    # HackRF devices
    ["1d50:6089"]="HackRF One"

    # NooElec devices
    ["0bda:2838"]="NooElec RTL-SDR"

    # SDRplay devices
    ["1df7:2500"]="SDRplay RSP1"
    ["1df7:3000"]="SDRplay RSP1A"
    ["1df7:3010"]="SDRplay RSP2"
)

echo "🔍 Scanning for SDR devices..."
echo ""

FOUND_DEVICES=()

# Parse lsusb output
while IFS= read -r line; do
    # Extract bus, device, and ID
    if [[ $line =~ Bus\ ([0-9]+)\ Device\ ([0-9]+):\ ID\ ([0-9a-f]+:[0-9a-f]+) ]]; then
        BUS="${BASH_REMATCH[1]}"
        DEV="${BASH_REMATCH[2]}"
        VID_PID="${BASH_REMATCH[3]}"

        # Check if this is a known SDR device
        if [[ -n "${SDR_DEVICES[$VID_PID]}" ]]; then
            DEVICE_NAME="${SDR_DEVICES[$VID_PID]}"
            DEVICE_PATH="/dev/bus/usb/$BUS/$DEV"

            echo "✅ Found: $DEVICE_NAME"
            echo "   Vendor:Product ID: $VID_PID"
            echo "   USB Bus: $BUS, Device: $DEV"
            echo "   Device Path: $DEVICE_PATH"

            # Check if device exists and permissions
            if [ -e "$DEVICE_PATH" ]; then
                PERMS=$(ls -l "$DEVICE_PATH" | awk '{print $1, $3, $4}')
                echo "   Permissions: $PERMS"
            else
                echo "   ⚠️  Warning: Device path does not exist"
            fi

            echo ""

            FOUND_DEVICES+=("$BUS:$DEV:$VID_PID:$DEVICE_NAME:$DEVICE_PATH")
        fi
    fi
done < <(lsusb)

# Check for SDR-related kernel modules
echo "🔍 Checking for SDR kernel modules..."
if lsmod | grep -q rtl2832; then
    echo "   ✅ rtl2832 module loaded"
fi
if lsmod | grep -q dvb_usb_rtl28xxu; then
    echo "   ✅ dvb_usb_rtl28xxu module loaded"
fi
if lsmod | grep -q airspy; then
    echo "   ✅ airspy module loaded"
fi

# Check if any kernel drivers are blocking SDR access
echo ""
echo "🔍 Checking for conflicting drivers..."
BLACKLIST_CHECK=0
for driver in dvb_usb_rtl28xxu rtl2832 rtl2830; do
    if lsmod | grep -q "^$driver"; then
        echo "   ⚠️  Warning: Kernel driver '$driver' may conflict with SoapySDR"
        echo "      Consider blacklisting: echo 'blacklist $driver' | sudo tee /etc/modprobe.d/blacklist-sdr.conf"
        BLACKLIST_CHECK=1
    fi
done

if [ $BLACKLIST_CHECK -eq 0 ]; then
    echo "   ✅ No conflicting drivers detected"
fi

echo ""
echo "=========================================="
echo "Docker Compose Configuration"
echo "=========================================="
echo ""

if [ ${#FOUND_DEVICES[@]} -eq 0 ]; then
    echo "❌ No SDR devices found."
    echo ""
    echo "Troubleshooting:"
    echo "  1. Ensure SDR device is connected"
    echo "  2. Run with sudo: sudo ./scripts/detect-sdr-devices.sh"
    echo "  3. Try: lsusb to see all USB devices"
    echo "  4. Check dmesg for USB connection messages"
    exit 0
fi

echo "Add the following to your docker-compose.yml under 'devices:'"
echo ""
echo "# Option 1: Passthrough all USB devices (simplest, recommended)"
echo "devices:"
echo "  - /dev/bus/usb:/dev/bus/usb  # All USB devices"
echo ""
echo "# Option 2: Passthrough only specific SDR devices (more secure)"
echo "devices:"

for device_info in "${FOUND_DEVICES[@]}"; do
    IFS=':' read -r BUS DEV VID_PID DEVICE_NAME DEVICE_PATH <<< "$device_info"

    # Pad bus and device numbers
    BUS_PAD=$(printf "%03d" $((10#$BUS)))
    DEV_PAD=$(printf "%03d" $((10#$DEV)))

    echo "  # $DEVICE_NAME (VID:PID $VID_PID)"
    echo "  - /dev/bus/usb/$BUS_PAD/$DEV_PAD:/dev/bus/usb/$BUS_PAD/$DEV_PAD"
done

echo ""
echo "⚠️  Note: USB device numbers (DEV) change when unplugged/replugged!"
echo "   For permanent setup, use Option 1 (passthrough all USB)"
echo "   or create udev rules to assign stable device names."
echo ""

# Generate udev rules suggestion
echo "=========================================="
echo "Permanent Device Access (udev rules)"
echo "=========================================="
echo ""
echo "For permanent SDR access without running Docker as root,"
echo "create /etc/udev/rules.d/52-sdr.rules with:"
echo ""

for device_info in "${FOUND_DEVICES[@]}"; do
    IFS=':' read -r BUS DEV VID_PID DEVICE_NAME DEVICE_PATH <<< "$device_info"
    IFS=':' read -r VID PID <<< "$VID_PID"

    echo "# $DEVICE_NAME"
    echo "SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"$VID\", ATTRS{idProduct}==\"$PID\", MODE=\"0666\", GROUP=\"plugdev\""
done

echo ""
echo "Then reload udev rules:"
echo "  sudo udevadm control --reload-rules"
echo "  sudo udevadm trigger"
echo ""
echo "And add your user to the plugdev group:"
echo "  sudo usermod -a -G plugdev \$USER"
echo "  # Log out and back in for group changes to take effect"
echo ""

# Check SoapySDR installation
echo "=========================================="
echo "SoapySDR Installation Check"
echo "=========================================="
echo ""

if command -v SoapySDRUtil &> /dev/null; then
    echo "✅ SoapySDR is installed on host"
    echo ""
    echo "Detected SDR devices via SoapySDR:"
    SoapySDRUtil --find 2>/dev/null || echo "   (No devices detected by SoapySDR)"
else
    echo "⚠️  SoapySDR not installed on host (not required for Docker deployment)"
    echo "   The Docker container includes SoapySDR and drivers"
fi

echo ""
echo "=========================================="
echo "Next Steps"
echo "=========================================="
echo ""
echo "1. Update your docker-compose.yml with the device passthrough above"
echo "2. Restart your containers: docker-compose down && docker-compose up -d"
echo "3. In the EAS Station web UI, go to Settings > Radio"
echo "4. Click 'Discover Devices' to detect your SDR"
echo "5. Click 'Add This Device' to configure it"
echo ""
echo "Done! 🎉"
echo ""
