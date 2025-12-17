# SSL Certificate Management - Web UI Guide

## Overview

As of version 2.35.0, EAS Station provides complete SSL certificate management through the web interface. No CLI access required!

## Accessing the SSL Certificate Manager

1. Log in to your EAS Station web interface
2. Navigate to **Settings → SSL Certificates** in the top navigation menu
3. Or directly visit: `https://your-domain.com/admin/certbot`

## Features

### ✅ Configuration Tab

**Purpose:** Configure your SSL certificate settings before obtaining a certificate.

**Fields:**
- **Certbot Enabled**: Enable/disable automatic SSL certificate management
- **Domain Name**: Your fully qualified domain name (e.g., `eas.example.com`)
- **Email Address**: Email for certificate expiration notifications
- **Use Staging Server**: Toggle between production and staging (for testing)
- **Auto-Renewal Enabled**: Enable automatic certificate renewal
- **Renew Days Before Expiry**: How many days before expiration to renew (default: 30)

**Actions:**
- **Save Settings**: Apply configuration changes
- **Reset**: Reload current settings

---

### ✅ Certificate Status Tab

This tab provides four main sections:

#### 1. Certificate Status

**Purpose:** View current SSL certificate information

**Features:**
- Certificate type (Let's Encrypt, Self-Signed, or None)
- Domain name
- Issuer
- Valid until date
- Days remaining
- Status badge (Valid, Expiring Soon, or Expired)

**Actions:**
- **Check Certificate Status**: Refresh certificate information
- **Download Certificate**: Download the certificate file

#### 2. Obtain SSL Certificate

**Purpose:** Get a new SSL certificate from Let's Encrypt - **directly through the web interface**

**How it works:**
1. Click **Obtain Certificate Now**
2. Choose acquisition method:
   - **Standalone** (Recommended): Temporarily stops nginx, obtains cert, restarts nginx
   - **Nginx Plugin**: No downtime, uses nginx plugin
   - **Webroot**: Uses existing web server
3. Click **Obtain Certificate**
4. Watch real-time certbot output
5. Certificate is automatically installed

**Real-time feedback:**
- Progress indicator during execution
- Live certbot output in scrollable window
- Success/error messages with actionable guidance
- Post-installation instructions

**No CLI required!** Everything happens through the web UI.

#### 3. Domain Validation

**Purpose:** Test if your domain is properly configured for Let's Encrypt

**Tests:**
- DNS Resolution: Verifies domain resolves to correct IP
- HTTP Accessibility: Checks if port 80 is accessible (required for ACME challenge)

**Action:**
- **Test Domain**: Run both tests and see results

#### 4. Certificate Renewal

**Purpose:** Manage certificate renewal - **directly through the web interface**

**Options:**
1. **Dry Run** (Safe - No Changes)
   - Tests renewal process without making changes
   - Safe to run anytime
   - Good for testing before actual renewal

2. **Normal Renewal**
   - Renews certificates that are within 30 days of expiration
   - Skips certificates not due for renewal

3. **Force Renewal**
   - Forces immediate renewal regardless of expiration
   - Use with caution due to rate limits

**Auto-Renewal Management:**
- **Check Auto-Renewal Status**: View systemd timer status and next run time
- **Enable Auto-Renewal**: Start the certbot.timer for automatic renewal
- **Disable Auto-Renewal**: Stop automatic renewal

**Real-time feedback:**
- Progress indicator during execution
- Live certbot output
- Timer status (enabled/disabled, active/stopped, next run time)
- Success/error messages

**No CLI required!** All renewal operations through the web UI.

---

## Typical Workflows

### First-Time Certificate Setup

1. **Navigate** to Settings → SSL Certificates
2. **Configure** (Configuration tab):
   - Enable Certbot
   - Enter domain name
   - Enter email address
   - Leave staging disabled for production
   - Save settings
3. **Test** (Certificate Status tab):
   - Click "Test Domain"
   - Verify both DNS and HTTP tests pass
4. **Obtain** (Certificate Status tab):
   - Click "Obtain Certificate Now"
   - Choose "Standalone" method
   - Click "Obtain Certificate"
   - Wait for completion (~1-2 minutes)
5. **Verify** (Certificate Status tab):
   - Click "Check Certificate Status"
   - Confirm valid certificate is shown
6. **Enable Auto-Renewal** (Certificate Status tab):
   - Click "Manage Certificate Renewal"
   - Click "Check Auto-Renewal Status"
   - Click "Enable Auto-Renewal" if not already enabled

### Testing Renewal

1. **Navigate** to Settings → SSL Certificates → Certificate Status tab
2. Click **Manage Certificate Renewal**
3. Select **Dry Run (Test Only - No Changes)** from the dropdown
4. Click **Execute Renewal**
5. Watch the output - should show "dry run: renewing cert"
6. Verify success message

### Forcing Certificate Renewal

1. **Navigate** to Settings → SSL Certificates → Certificate Status tab
2. Click **Manage Certificate Renewal**
3. Select **Force Renewal (Renew Now)** from the dropdown
4. Click **Execute Renewal**
5. Watch the certbot output
6. Verify success and check certificate status

### Checking Auto-Renewal Status

1. **Navigate** to Settings → SSL Certificates → Certificate Status tab
2. Click **Manage Certificate Renewal**
3. Click **Check Auto-Renewal Status**
4. View:
   - Timer Enabled: Yes/No
   - Timer Active: Running/Stopped
   - Next Run: Date and time
5. Enable or disable as needed

---

## Security Notes

### Permissions Required

- SSL certificate operations require `system.configure` permission
- Only users with this permission can access the SSL Certificates page
- All operations are logged for audit purposes
- **System Requirements**: Certbot operations require proper sudo configuration

#### Sudo Configuration

The application requires sudo permissions for certbot operations. These are configured in `/etc/sudoers.d/eas-station`:

```bash
# Install sudoers configuration (done automatically during installation)
sudo cp config/sudoers-eas-station /etc/sudoers.d/eas-station
sudo chmod 440 /etc/sudoers.d/eas-station
```

**Required permissions include:**
- Running certbot commands (requires root for port 80 binding and system file modifications)
- Managing nginx service (start, stop, restart, reload)
- Creating and managing certbot data directories
- Creating and managing nginx log directories (required for nginx plugin)
- Managing certbot.timer systemd service

#### Certbot Service Configuration

The certbot systemd service (`/etc/systemd/system/certbot.service`) must run as root because:
1. Certbot needs to bind to port 80 (privileged port, requires root or CAP_NET_BIND_SERVICE)
2. Certbot needs to write to system directories like `/etc/letsencrypt`
3. Certbot needs to reload nginx after certificate renewal

The service is configured with:
- `User=root` - Required for privileged operations
- Custom directories in `/opt/eas-station/certbot_data/` for config, work, and logs
- `PrivateTmp=yes` - Isolates /tmp from other processes for security

#### Nginx Log Directory Permissions

The nginx plugin requires nginx to run configuration tests, which involves writing to log files. The application automatically:
1. Creates `/var/log/nginx` directory if it doesn't exist
2. Sets permissions to 755 (readable by all, writable by owner)
3. Sets ownership to `www-data:www-data` (nginx user)
4. Creates necessary log files with proper permissions

If you encounter "Permission denied" errors related to nginx logs, the system will attempt to fix these automatically. If issues persist, manually verify:
```bash
sudo mkdir -p /var/log/nginx
sudo chmod 755 /var/log/nginx
sudo chown www-data:www-data /var/log/nginx
sudo touch /var/log/nginx/error.log /var/log/nginx/access.log
sudo chown www-data:www-data /var/log/nginx/*.log
```

### Safe Operations

The following operations are **safe** to run anytime:
- Check Certificate Status
- Test Domain
- Download Certificate
- Dry Run renewal test

### Operations to Use Carefully

The following operations should be used with care:
- **Obtain Certificate**: Only obtain when you need a new certificate
- **Force Renewal**: Subject to Let's Encrypt rate limits (5 per week)

### Rate Limits

Let's Encrypt has production rate limits:
- **50 certificates per registered domain per week**
- **5 failed validation attempts per account per hour**

Best practices:
1. Test with staging mode first
2. Use dry run before force renewal
3. Don't repeatedly obtain certificates unnecessarily

---

## Troubleshooting

### "Domain name is not configured"

**Solution:** Go to Configuration tab and enter your domain name, then save settings.

### "Certbot is not installed on this system"

**Solution:** Install certbot on your server:
```bash
sudo apt-get update
sudo apt-get install certbot python3-certbot-nginx
```

### "Permission denied" errors

**Symptom:** Errors like:
- `PermissionError: [Errno 13] Permission denied` when binding to port 80
- `open() "/var/log/nginx/error.log" failed (13: Permission denied)`
- `Could not bind TCP port 80 because you don't have the appropriate permissions`

**Possible causes:**
1. Sudoers configuration not properly installed
2. Nginx log directory doesn't exist or has wrong permissions
3. Certbot service not configured to run as root

**Solutions:**

1. **Check and reinstall sudoers configuration:**
   ```bash
   sudo cp config/sudoers-eas-station /etc/sudoers.d/eas-station
   sudo chmod 440 /etc/sudoers.d/eas-station
   sudo visudo -c  # Verify syntax
   ```

2. **Fix nginx log directory permissions:**
   ```bash
   sudo mkdir -p /var/log/nginx
   sudo chmod 755 /var/log/nginx
   sudo chown www-data:www-data /var/log/nginx
   sudo touch /var/log/nginx/error.log /var/log/nginx/access.log
   sudo chown www-data:www-data /var/log/nginx/*.log
   ```

3. **Verify certbot service configuration:**
   ```bash
   sudo systemctl cat certbot.service | grep User
   # Should show: User=root
   
   # If not, reinstall the service file:
   sudo cp systemd/certbot.service /etc/systemd/system/
   sudo systemctl daemon-reload
   ```

4. **Use nginx plugin instead of standalone:**
   - The nginx plugin doesn't require stopping nginx or binding to port 80
   - It requires nginx to be running and properly configured
   - Select "Nginx Plugin (Recommended - No Downtime)" in the web UI

5. **Verify certbot data directory permissions:**
   ```bash
   sudo mkdir -p /opt/eas-station/certbot_data/{config,work,logs}
   sudo chmod -R 777 /opt/eas-station/certbot_data
   ```

**Prevention:** The application automatically attempts to fix these permissions when you obtain or renew certificates. If issues persist after trying these solutions, check system logs:
```bash
sudo journalctl -u certbot.service -n 50
sudo journalctl -u nginx -n 50
```

### "Failed to stop nginx"

**Possible causes:**
- nginx is not installed
- Insufficient permissions

**Solution:** Ensure nginx is installed and the web app has sudo privileges for systemctl commands.

### "Port 80 is not accessible"

**Possible causes:**
- Firewall blocking port 80
- Domain not pointing to your server
- Another service using port 80

**Solutions:**
1. Check firewall: `sudo ufw allow 80`
2. Verify DNS: `nslookup your-domain.com`
3. Check port usage: `sudo lsof -i :80`

### "Certbot failed" with rate limit error

**Cause:** Hit Let's Encrypt rate limits

**Solutions:**
1. Wait for rate limit reset (usually 1 hour or 1 week)
2. Use staging mode for testing
3. Avoid repeatedly requesting certificates

---

## Benefits Over CLI

### ✅ User-Friendly
- No need to SSH into server
- No need to remember commands
- Visual feedback and progress indicators

### ✅ Safe
- Clear descriptions of what each operation does
- Dry run testing before making changes
- Automatic error handling and recovery

### ✅ Convenient
- One-click operations
- Real-time output
- Status monitoring

### ✅ Accessible
- Works from any device with a web browser
- No terminal access required
- Role-based permissions

---

## Technical Details

### How It Works

When you click "Obtain Certificate" or "Execute Renewal":

1. Web UI sends POST request to backend
2. Backend validates your settings
3. Backend constructs appropriate certbot command
4. Command is executed with `subprocess` module
5. Real-time output is captured and returned
6. Results are displayed in the UI

### Commands Used

The web UI executes these certbot commands (examples):

**Obtain Certificate (Standalone):**
```bash
sudo systemctl stop nginx
sudo certbot certonly --standalone --non-interactive --agree-tos --email you@example.com -d eas.example.com
sudo systemctl start nginx
```

**Renew (Dry Run):**
```bash
sudo certbot renew --dry-run
```

**Renew (Force):**
```bash
sudo certbot renew --force-renewal
```

**Enable Auto-Renewal:**
```bash
sudo systemctl enable --now certbot.timer
```

---

## Version History

- **v2.35.0**: Added full web UI execution for all certbot operations
- **v2.33.1**: Initial web UI for viewing certificate status (commands only)
- **Earlier**: CLI-only certificate management

---

## See Also

- [HTTPS Setup Guide](HTTPS_SETUP.md) - Comprehensive HTTPS setup documentation
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) - How SSL fits into the system
- [Security Documentation](../security/SECURITY.md) - Security best practices
