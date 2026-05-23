# Database User Fix Script

## Purpose

The `fix_database_user.sh` script resolves database authentication issues caused by incorrectly named PostgreSQL users. During installation or manual setup, users might be created with variations like "eas_station" (underscore) instead of the correct "eas-station" (hyphen), causing authentication failures.

## Symptoms This Fixes

- Error: `password authentication failed for user "eas_station"`
- Migration failures during system updates
- Screen manager database connection errors in poller service
- Services failing to start with database authentication errors

## What It Does

1. **Detects Incorrect Users**: Scans for users like "eas_station", "easstation", "eas-station-old"
2. **Creates Correct User**: Ensures "eas-station" user exists with correct password from `.env`
3. **Migrates Data**: Reassigns all database object ownership from incorrect users to "eas-station"
4. **Cleans Up**: Safely drops incorrect users after migration
5. **Updates Permissions**: Sets proper schema and table permissions for PostgreSQL 15+

## Usage

```bash
sudo /opt/eas-station/scripts/database/fix_database_user.sh
```

**Requirements:**
- Must run as root or with sudo
- `.env` file must exist at `/opt/eas-station/.env` with valid DATABASE_URL
- PostgreSQL service must be running

## Safety Features

- **Non-Destructive**: Reassigns ownership before dropping users (no data loss)
- **Interactive**: Prompts for confirmation before making changes
- **Validation**: Checks for required files and PostgreSQL connection
- **Idempotent**: Safe to run multiple times

## After Running

1. Restart all services:
   ```bash
   sudo systemctl restart eas-station.target
   ```

2. Verify services are running:
   ```bash
   sudo systemctl status eas-station.target
   ```

3. Check for database errors in logs:
   ```bash
   sudo journalctl -u eas-station-web.service -n 50
   sudo journalctl -u eas-station-poller.service -n 50
   ```

## Related Files

- `/opt/eas-station/.env` - Contains DATABASE_URL with correct username and password
- `systemd/eas-station-*.service` - Service files that load environment variables
- `install.sh` - Creates database user during installation

## Technical Details

The script:
- Parses DATABASE_URL from `.env` to extract the password
- Uses PostgreSQL's `REASSIGN OWNED BY` to transfer object ownership
- Applies proper GRANT statements for PostgreSQL 15+ schema security changes
- Handles both pg_hba.conf authentication methods (md5 and scram-sha-256)

## Troubleshooting

**If script fails:**
1. Check PostgreSQL is running: `sudo systemctl status postgresql`
2. Verify `.env` file exists and contains DATABASE_URL
3. Ensure DATABASE_URL format: `postgresql+psycopg2://user:password@host:port/database`
4. Check PostgreSQL logs: `sudo journalctl -u postgresql -n 50`

**If authentication still fails after running:**
1. Verify password in `.env` matches PostgreSQL user password
2. Check pg_hba.conf allows connections from localhost
3. Restart PostgreSQL: `sudo systemctl restart postgresql`
4. Restart EAS Station™ services: `sudo systemctl restart eas-station.target`
