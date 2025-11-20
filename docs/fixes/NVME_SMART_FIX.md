# NVMe SMART Data Display Fix

## Problem
Users with NVMe drives (particularly Samsung SSD 990 PRO and similar models) were seeing "unknown" for all SMART data fields in the System Health Monitor, even though running `smartctl --all /dev/nvme0` directly showed correct SMART information.

## Root Cause
The issue was caused by the `-n standby,now` flag being passed to `smartctl` for all device types. This flag is designed for ATA/SATA drives to skip devices that are in standby/sleep mode, but it's incompatible with NVMe devices:

- **ATA/SATA drives**: Support standby mode and respect the `-n standby,now` flag
- **NVMe drives**: Don't have the same standby mode concept, and this flag could cause smartctl to skip the device or behave unexpectedly

## Solution
Modified the SMART data collection in `app_utils/system.py` to:
1. **Detect NVMe devices** using the existing `_detect_device_type()` function
2. **Skip the `-n standby,now` flag** when querying NVMe devices
3. **Add debug logging** to show the exact smartctl command being executed

### Command Changes

**Before (all devices):**
```bash
smartctl --json=o -H -A -n standby,now -d nvme /dev/nvme0n1
```

**After (NVMe devices):**
```bash
smartctl --json=o -H -A -d nvme /dev/nvme0n1
```

**After (SATA/SCSI devices - unchanged):**
```bash
smartctl --json=o -H -A -n standby,now -d auto /dev/sda
```

## Testing
Added comprehensive test suite for Samsung 990 PRO specifically:
- Tests overall SMART status parsing
- Tests temperature extraction
- Tests power metrics (power-on hours, power cycles)
- Tests media errors and critical warnings
- Tests NVMe-specific statistics
- Tests complete device result as returned by the system

All 33 tests pass successfully.

## What Should Work Now
After this fix, NVMe drives should correctly display:
- ✅ Overall health status (Passed/Failed)
- ✅ Temperature in Celsius
- ✅ Power-on hours
- ✅ Power cycle count
- ✅ Media errors
- ✅ Critical warnings
- ✅ Data units read/written (with byte conversions)
- ✅ Host read/write commands
- ✅ Percentage used (wear leveling)
- ✅ Unsafe shutdowns
- ✅ Controller busy time

## Affected Devices
This fix benefits all NVMe solid-state drives, including but not limited to:
- Samsung 990 PRO / 980 PRO / 970 EVO Plus
- WD Black SN850 / SN770 / SN750
- Crucial P5 Plus / P3
- Kingston KC3000 / KC2500
- Seagate FireCuda 530
- And any other NVMe SSD

## Background: NVMe vs SATA
NVMe (Non-Volatile Memory Express) is a modern protocol designed specifically for SSDs connected via PCIe, while SATA was designed for mechanical hard drives. Key differences affecting SMART monitoring:

1. **Power Management**: NVMe uses different power states (Active, Idle, Standby, Sleep) but manages them differently than SATA
2. **SMART Attributes**: NVMe reports different health metrics optimized for flash memory
3. **Command Set**: NVMe uses a native command set rather than the SCSI/ATA translation layer

## Debugging
If SMART data still shows as "unknown" after this fix, check:

1. **Permissions**: Ensure the application has permission to run `smartctl` (usually requires root/sudo)
   ```bash
   sudo smartctl --all /dev/nvme0n1
   ```

2. **Device Detection**: Check that the device appears in `lsblk` output
   ```bash
   lsblk -o NAME,PATH,TYPE,SIZE,MODEL,SERIAL,TRAN
   ```

3. **Smartctl Version**: Ensure smartctl is installed and up-to-date
   ```bash
   smartctl --version
   ```

4. **Application Logs**: Enable debug logging to see the exact smartctl commands being executed
   - The application now logs: `"Querying SMART data for /dev/nvmeXnY with command: smartctl --json=o -H -A -d nvme /dev/nvmeXnY"`

## Related Files
- `app_utils/system.py`: Main SMART data collection logic
- `tests/test_nvme_samsung_990_pro.py`: Comprehensive NVMe test suite
- `tests/test_system_health_fixes.py`: General SMART data tests

## References
- [smartmontools Documentation](https://www.smartmontools.org/)
- [NVMe Specification](https://nvmexpress.org/specifications/)
- [Samsung 990 PRO Specifications](https://www.samsung.com/semiconductor/minisite/ssd/product/consumer/990pro/)
