# NVMe and SSD SMART Monitoring Setup

The EAS Station™ health monitoring page displays S.M.A.R.T. data from your NVMe and SATA drives, including temperature, power-on hours, media errors, and health status.

## Requirements

1. **smartmontools** package installed:
   ```bash
   # Debian/Ubuntu
   sudo apt install smartmontools

   # RHEL/CentOS
   sudo yum install smartmontools
   ```

2. **sudo access** for the web application user

## Sudo Configuration

The web application needs permission to run `smartctl` as root to access raw device data.

### Option 1: Sudoers file (Recommended)

Create `/etc/sudoers.d/eas-station-smartctl`:

```bash
# Allow EAS Station™ web app to run smartctl without password
# Replace 'www-data' with your web app user (could be 'eas-station', 'nginx', etc.)
www-data ALL=(ALL) NOPASSWD: /usr/sbin/smartctl

# If running as a specific user:
# eas-station ALL=(ALL) NOPASSWD: /usr/sbin/smartctl
```

Set correct permissions:
```bash
sudo chmod 0440 /etc/sudoers.d/eas-station-smartctl
sudo visudo -c  # Verify syntax
```

### Option 2: Add user to disk group (Less secure)

```bash
# Add web app user to disk group
sudo usermod -a -G disk www-data

# Restart web service
sudo systemctl restart eas-station
```

**Warning:** This gives the user access to raw disk devices, which is a security risk.

## Verification

1. **Test smartctl access** as the web app user:
   ```bash
   # Switch to web app user
   sudo -u www-data smartctl --scan

   # Test NVMe access
   sudo -u www-data sudo -n smartctl -a /dev/nvme0
   ```

2. **Check health page:**
   - Visit `/system_health` or `/health`
   - Look for "Storage" section with SMART data
   - Should show temperature, power-on hours, etc.

3. **Check logs** for permission errors:
   ```bash
   # Application logs
   journalctl -u eas-station -f | grep -i smart

   # Look for errors like:
   # "smartctl permission denied for /dev/nvme0"
   # "Permission denied (may require root/sudo privileges)"
   ```

## What SMART Data is Displayed

For **NVMe drives**:
- Temperature (automatically converted from Kelvin to Celsius)
- Power-on hours
- Power cycle count
- Media errors and critical warnings
- Data units read/written
- Percentage used
- Available spare capacity
- Overall health status

For **SATA SSDs/HDDs**:
- Temperature
- Power-on hours
- Reallocated sector count
- Pending sectors
- Overall health status

## Troubleshooting

### No SMART data appears

1. **Check if smartctl is installed:**
   ```bash
   which smartctl
   smartctl --version
   ```

2. **Check if devices are detected:**
   ```bash
   sudo smartctl --scan
   lsblk -o NAME,TYPE,TRAN,MODEL
   ```

3. **Test manual access:**
   ```bash
   sudo smartctl -a /dev/nvme0  # For NVMe
   sudo smartctl -a /dev/sda    # For SATA
   ```

4. **Check web app user:**
   ```bash
   # Find which user runs the web app
   ps aux | grep eas-station

   # Test sudo access for that user
   sudo -u <username> sudo -n smartctl --scan
   ```

### "Permission denied" errors

- Verify sudoers configuration (Option 1 above)
- Check sudoers file syntax: `sudo visudo -c`
- Ensure correct username in sudoers file
- Restart web service after sudoers changes

### "smartctl not found" errors

- Install smartmontools package
- Check PATH includes `/usr/sbin`: `echo $PATH`
- Verify location: `which smartctl` (usually `/usr/sbin/smartctl`)

## Security Notes

- **Sudoers approach** (Option 1) is more secure - limits access to only `smartctl` command
- **disk group** approach (Option 2) gives broader access to all block devices
- The health monitoring code runs `sudo -n` which fails if password is required
- No passwords are ever stored or prompted

## NVMe-Specific Features

The code automatically:
- Detects NVMe devices by name (`nvme*`) and transport type
- Uses `-d nvme` flag for NVMe devices
- Skips `-n standby` flag (NVMe doesn't support standby mode)
- Converts temperature from Kelvin to Celsius (NVMe reports in Kelvin)
- Parses NVMe-specific metrics (spare capacity, data units, etc.)

## Files

- SMART collection code: `app_utils/system/smart.py:_collect_smart_health()`
- smartctl output parsing: `app_utils/system/smart_fields.py`
- NVMe detection: `app_utils/system/disks.py:_detect_device_type()`
- Health page route: `webapp/public/pages.py:/system_health`
- Health template: `webapp/templates/system_health.html`
