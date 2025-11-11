# Systemd Timer Setup for EAS Station Backups

This directory contains systemd unit files for automated EAS Station backups.

## Files

- `eas-backup.service` - Service unit that runs the backup
- `eas-backup.timer` - Timer unit that schedules the backup (daily at 2 AM)

## Installation

1. **Edit the service file** to match your installation:
   ```bash
   sudo nano examples/systemd/eas-backup.service
   ```

   Update these paths:
   - `WorkingDirectory=/opt/eas-station` (your EAS Station installation path)
   - `ExecStart=/opt/eas-station/tools/backup_scheduler.py` (path to script)
   - `--output-dir /var/backups/eas-station` (backup destination)
   - `--notify admin@example.com` (your email address)

2. **Copy the unit files** to systemd directory:
   ```bash
   sudo cp examples/systemd/eas-backup.service /etc/systemd/system/
   sudo cp examples/systemd/eas-backup.timer /etc/systemd/system/
   ```

3. **Reload systemd** to recognize the new units:
   ```bash
   sudo systemctl daemon-reload
   ```

4. **Enable and start the timer**:
   ```bash
   sudo systemctl enable eas-backup.timer
   sudo systemctl start eas-backup.timer
   ```

## Verification

Check timer status:
```bash
sudo systemctl status eas-backup.timer
```

List all timers:
```bash
sudo systemctl list-timers
```

View logs:
```bash
# Recent backup logs
sudo journalctl -u eas-backup.service -n 50

# Follow live logs
sudo journalctl -u eas-backup.service -f

# View log file
sudo tail -f /var/log/eas-backup.log
```

## Testing

Run backup manually (without waiting for timer):
```bash
sudo systemctl start eas-backup.service
```

Check the result:
```bash
sudo systemctl status eas-backup.service
ls -lh /var/backups/eas-station/
```

## Customization

### Change Schedule

Edit the timer file to change when backups run:
```bash
sudo nano /etc/systemd/system/eas-backup.timer
```

Examples:
```ini
# Every 6 hours
OnCalendar=*-*-* 00,06,12,18:00:00

# Twice daily (2 AM and 2 PM)
OnCalendar=*-*-* 02,14:00:00

# Weekly on Sunday at 3 AM
OnCalendar=Sun *-*-* 03:00:00

# First day of month at 4 AM
OnCalendar=*-*-01 04:00:00
```

After editing, reload and restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart eas-backup.timer
```

### Change Retention Policy

Edit the service file to adjust how many backups to keep:
```bash
sudo nano /etc/systemd/system/eas-backup.service
```

Add retention options to ExecStart:
```
ExecStart=/usr/bin/python3 /opt/eas-station/tools/backup_scheduler.py \
    --output-dir /var/backups/eas-station \
    --label scheduled \
    --keep-daily 14 \
    --keep-weekly 8 \
    --keep-monthly 12 \
    --log-file /var/log/eas-backup.log \
    --notify admin@example.com
```

## Troubleshooting

### Timer not running

Check if timer is enabled:
```bash
sudo systemctl is-enabled eas-backup.timer
```

If disabled, enable it:
```bash
sudo systemctl enable eas-backup.timer
```

### Permission issues

Ensure backup directory exists and is writable:
```bash
sudo mkdir -p /var/backups/eas-station
sudo chown root:root /var/backups/eas-station
sudo chmod 755 /var/backups/eas-station
```

### Email notifications not working

Install mail utilities:
```bash
# Debian/Ubuntu
sudo apt-get install mailutils

# RHEL/CentOS
sudo yum install mailx
```

Configure mail server in `/etc/postfix/main.cf` or use external SMTP.

## Uninstallation

Stop and disable the timer:
```bash
sudo systemctl stop eas-backup.timer
sudo systemctl disable eas-backup.timer
```

Remove unit files:
```bash
sudo rm /etc/systemd/system/eas-backup.service
sudo rm /etc/systemd/system/eas-backup.timer
sudo systemctl daemon-reload
```
