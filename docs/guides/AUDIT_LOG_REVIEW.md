# Audit Log Review

EAS Station™ maintains two audit trails: a structured **database audit log** that captures user actions and security events, and a **security log file** in fail2ban-compatible format that captures authentication events.

---

## Database Audit Log

The database audit log records:

- Successful and failed login attempts
- MFA enrollment and verification events
- IP filter additions, changes, and deletions
- Permission denial events
- Configuration changes

### Viewing Audit Logs in the Web Interface

1. Navigate to **Admin → Security → Audit Logs**.
2. Use the filter controls to narrow results:
   - **Date range** — filter by start and end date/time
   - **User** — filter by username
   - **Action type** — filter by event category
   - **IP address** — filter by source IP
3. Click any row to expand details.
4. Use **Export CSV** to download the filtered log for archival or analysis.

### Audit Log Event Types

| Event | Trigger |
|-------|---------|
| `LOGIN_SUCCESS` | Successful username/password authentication |
| `LOGIN_FAILURE` | Failed login attempt (wrong password) |
| `LOGIN_MFA_SUCCESS` | Successful TOTP or backup code verification |
| `LOGIN_MFA_FAILURE` | Invalid MFA code entered |
| `LOGIN_MFA_BACKUP` | Backup code used for login |
| `LOGOUT` | User session ended |
| `MFA_ENROLLED` | MFA enabled on an account |
| `MFA_DISABLED` | MFA disabled on an account |
| `IP_FILTER_ADDED` | IP address added to allowlist or blocklist |
| `IP_FILTER_REMOVED` | IP filter deleted |
| `PERMISSION_DENIED` | Access denied due to insufficient role |
| `CONFIG_CHANGED` | Application configuration updated |
| `USER_CREATED` | New admin account created |
| `USER_DELETED` | Admin account deleted |
| `API_KEY_CREATED` | New API key generated |
| `API_KEY_DELETED` | API key removed |

---

## Via the REST API

Retrieve audit log entries programmatically:

```bash
curl -H "X-API-Key: <key>" \
  "https://your-eas-station.example.com/security/audit-logs?days=7"
```

**Query parameters:**

| Parameter | Description | Default |
|-----------|-------------|---------|
| `days` | Lookback window | 7 |
| `user` | Filter by username | All |
| `action` | Filter by event type | All |
| `limit` | Maximum results | 100 |

**Direct database query:**

```bash
psql -U eas_station -d eas_station -c \
  "SELECT timestamp, action, username, ip_address, details
   FROM audit_logs
   WHERE timestamp > NOW() - INTERVAL '24 hours'
   ORDER BY timestamp DESC
   LIMIT 50;"
```

---

## Security Log File

Authentication events are also written to `/var/log/eas-station/security.log` in a format compatible with fail2ban.

### Log Format

```
[YYYY-MM-DD HH:MM:SS UTC] EVENT_TYPE from IP_ADDRESS username=USERNAME details=DETAILS
```

**Example entries:**

```
[2025-02-20 14:32:11 UTC] FAILED_LOGIN from 192.168.1.50 username=admin details=wrong_password
[2025-02-20 14:32:45 UTC] MALICIOUS_LOGIN from 203.0.113.10 username=admin'; DROP TABLE-- details=malicious_input
[2025-02-20 14:33:00 UTC] RATE_LIMIT_EXCEEDED from 203.0.113.10 username=unknown details=too_many_attempts
```

### Event Types in Security Log

| Event Type | Description |
|------------|-------------|
| `FAILED_LOGIN` | Incorrect password |
| `MALICIOUS_LOGIN` | SQL/command injection attempt detected in login fields |
| `RATE_LIMIT_EXCEEDED` | IP locked out after too many failures |

### Tailing the Security Log

```bash
sudo tail -f /var/log/eas-station/security.log
```

### Searching for Specific IPs or Events

```bash
# All events from a specific IP
grep "203.0.113.10" /var/log/eas-station/security.log

# All malicious attempts today
grep "MALICIOUS_LOGIN" /var/log/eas-station/security.log | grep "$(date +%Y-%m-%d)"

# Count failed logins per IP
grep "FAILED_LOGIN" /var/log/eas-station/security.log | \
  awk '{print $5}' | sort | uniq -c | sort -rn | head -20
```

---

## fail2ban Integration

The security log is designed for fail2ban integration to automatically block attacking IPs at the firewall level. See the [Security Guide](../security/SECURITY.md) for fail2ban configuration instructions.

---

## Malicious Login Attempts Dashboard

EAS Station™ tracks injection and brute-force attempts in the **Malicious Logins** page:

1. Navigate to **Admin → Security → Malicious Logins**.
2. The dashboard shows:
   - Total malicious attempts logged
   - Number of unique attacking IPs
   - Attempts in the last 24 hours
   - Top attacking IPs by attempt count
3. Use the **Quick Ban** button next to any IP to immediately add it to the blocklist.

---

## IP Filter Management

View and manage automatically and manually created IP filters:

1. Go to **Admin → Security → IP Filters**.
2. The list shows each filter's IP/CIDR, type (allowlist/blocklist), reason, and expiry.
3. Actions:
   - **Toggle** — activate or deactivate a filter without deleting it
   - **Delete** — permanently remove the filter
   - **Add new** — manually add an IP to the allowlist or blocklist

**Auto-ban triggers and durations:**

| Trigger | Ban Duration |
|---------|-------------|
| SQL/command injection in login | 24 hours |
| 5 consecutive failed logins | 24 hours |
| >10 login attempts per minute (flooding) | 1 hour |

!!! tip "Add your admin IP to the allowlist"
    Before enabling strict rate limiting, add your own IP address to the allowlist to prevent accidental lockout. Go to **Admin → Security → IP Filters → Add → Allowlist**.

---

## Log Rotation

The security log at `/var/log/eas-station/security.log` is automatically rotated by the system's logrotate configuration. Default rotation: daily, keeping 30 days of history, compressed.

Verify logrotate configuration:

```bash
cat /etc/logrotate.d/eas-station
```

To force a rotation manually:

```bash
sudo logrotate --force /etc/logrotate.d/eas-station
```

---

## Regular Review Recommendations

- **Daily**: Glance at the **Malicious Logins** dashboard for new auto-bans.
- **Weekly**: Export the audit log as CSV and archive it. Review any `CONFIG_CHANGED` or `USER_CREATED` events you did not initiate.
- **Monthly**: Purge expired blocklist entries (**Admin → Security → IP Filters → Cleanup**) and review any remaining active blocks.
- **Immediately**: Investigate any `MALICIOUS_LOGIN` events, unusual off-hours logins, or logins from unexpected IP ranges.

---

## Troubleshooting

### Audit log is empty

- The audit log starts populating from the moment of the first login after the `audit_logs` table was created. Run `alembic upgrade head` to ensure the table exists.

### Security log not being written

- Check that `/var/log/eas-station/` exists and is writable by the `eas-station` user:
  ```bash
  sudo mkdir -p /var/log/eas-station
  sudo chown eas-station:eas-station /var/log/eas-station
  sudo systemctl restart eas-station-web
  ```

### fail2ban is not picking up events

- Confirm the `logpath` in your jail configuration points to `/var/log/eas-station/security.log`.
- Test the filter regex:
  ```bash
  sudo fail2ban-regex /var/log/eas-station/security.log /etc/fail2ban/filter.d/eas-station-auth.conf
  ```
