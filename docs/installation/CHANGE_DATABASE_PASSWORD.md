# How to Change PostgreSQL Database Password

## Quick Method (Recommended)

Use the provided script to change the password automatically:

```bash
sudo /opt/eas-station/scripts/change_db_password.sh 'aU96LvLqQUuvw8Cx3jBQ_u2_Qp-ovXjSP-ZZdaqPrTM'
```

Or specify a different username:

```bash
sudo /opt/eas-station/scripts/change_db_password.sh eas-station 'aU96LvLqQUuvw8Cx3jBQ_u2_Qp-ovXjSP-ZZdaqPrTM'
```

The script will:
1. Change the PostgreSQL password
2. Update the DATABASE_URL in `.env` file
3. Backup the old `.env` file
4. Test the database connection
5. Restart EAS Station services

## Manual Method

If you prefer to change the password manually:

### Step 1: Change PostgreSQL Password

```bash
sudo -u postgres psql -c "ALTER USER \"eas-station\" WITH PASSWORD 'aU96LvLqQUuvw8Cx3jBQ_u2_Qp-ovXjSP-ZZdaqPrTM';"
```

### Step 2: Update .env File

Edit `/opt/eas-station/.env` and update the DATABASE_URL line:

```bash
sudo nano /opt/eas-station/.env
```

Change the DATABASE_URL to:

```
DATABASE_URL=postgresql+psycopg2://eas-station:aU96LvLqQUuvw8Cx3jBQ_u2_Qp-ovXjSP-ZZdaqPrTM@localhost:5432/alerts
```

**Note**: Special characters in passwords are automatically URL-encoded by the script. If doing manually and your password contains special characters like `@`, `#`, `/`, etc., you need to URL-encode them:

```python
# Use Python to URL-encode the password
python3 -c "from urllib.parse import quote; print(quote('your-password', safe=''))"
```

### Step 3: Test Connection

```bash
PGPASSWORD='aU96LvLqQUuvw8Cx3jBQ_u2_Qp-ovXjSP-ZZdaqPrTM' psql -U eas-station -h localhost -d alerts -c "SELECT 1;"
```

### Step 4: Restart Services

```bash
sudo systemctl restart eas-station.target
```

## Verify Everything Works

Check service status:

```bash
sudo systemctl status eas-station.target
```

View poller logs to confirm database connection:

```bash
sudo journalctl -u eas-station-poller.service -f
```

You should see logs like:
```
[CAP_POLLER] DATABASE_URL found in environment: postgresql+psycopg2://eas-station:***@localhost:5432/alerts
INFO:__main__:Connected to database
```

## Troubleshooting

### Password Authentication Failed

If you still see "password authentication failed" errors:

1. **Check PostgreSQL is running:**
   ```bash
   sudo systemctl status postgresql
   ```

2. **Verify user exists:**
   ```bash
   sudo -u postgres psql -c "\du eas-station"
   ```

3. **Check pg_hba.conf authentication method:**
   ```bash
   sudo cat /etc/postgresql/*/main/pg_hba.conf | grep -v "^#"
   ```
   
   Ensure there's a line like:
   ```
   local   all             all                                     md5
   host    all             all             127.0.0.1/32            md5
   host    all             all             ::1/128                 md5
   ```

4. **Reload PostgreSQL if you changed pg_hba.conf:**
   ```bash
   sudo systemctl reload postgresql
   ```

### .env File Not Being Loaded

If the DATABASE_URL from .env isn't being used:

1. **Verify .env file exists and has correct permissions:**
   ```bash
   ls -la /opt/eas-station/.env
   sudo cat /opt/eas-station/.env | grep DATABASE_URL
   ```

2. **Check systemd service loads the .env file:**
   ```bash
   sudo cat /opt/eas-station/systemd/eas-station-poller.service | grep EnvironmentFile
   ```

3. **Reload systemd and restart services:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart eas-station.target
   ```

## Security Notes

- The password contains special characters (`_` and `-`) which are safe in DATABASE_URL
- Never commit `.env` files with passwords to git repositories
- Use strong, randomly generated passwords for production systems
- Backup your `.env` file before making changes (the script does this automatically)

## Additional Resources

- PostgreSQL Password Documentation: https://www.postgresql.org/docs/current/sql-alterrole.html
- URL Encoding: https://www.urlencoder.org/
- EAS Station Documentation: https://github.com/KR8MER/eas-station
