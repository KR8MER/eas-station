# HTTPS Setup Guide

This guide explains how to configure HTTPS for EAS Station™ using nginx and Let's Encrypt.

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Configuration Options](#configuration-options)
- [Troubleshooting](#troubleshooting)
- [Advanced Topics](#advanced-topics)

---

## Overview

EAS Station™ includes built-in HTTPS support using:

- **nginx** - Reverse proxy server that handles SSL/TLS termination
- **Let's Encrypt** - Free, automated SSL certificate authority
- **certbot** - Automated certificate management and renewal

### What This Provides

✅ **Automatic HTTPS** - Certificates are automatically obtained and renewed
✅ **Secure by Default** - Modern TLS configuration (TLS 1.2+, strong ciphers)
✅ **HTTP → HTTPS Redirect** - All HTTP traffic is automatically redirected to HTTPS
✅ **Self-Signed Fallback** - Generates self-signed certificates for development/testing
✅ **Zero Configuration** - Works out of the box for localhost testing

---

## Architecture

```
Internet (HTTPS) → nginx (ports 80/443) → Flask App (internal port 5000)
                    ↑
                    Let's Encrypt certificates
                    (auto-renewed by certbot)
```

**How it works:**

1. nginx listens on ports 80 (HTTP) and 443 (HTTPS)
2. Port 80 serves Let's Encrypt ACME challenges and redirects to HTTPS
3. Port 443 terminates SSL and proxies requests to Flask on internal port 5000
4. certbot runs every 12 hours to check and renew certificates (90-day validity)
5. Flask application only needs to handle HTTP internally

---

## Prerequisites

### For Production Deployment (Let's Encrypt):

- ✅ **Domain name** - You must own a domain (e.g., `eas.example.com`)
- ✅ **DNS configured** - Domain must point to your server's public IP address
- ✅ **Port 80 accessible** - Must be reachable from the internet for ACME validation
- ✅ **Port 443 accessible** - For HTTPS traffic
- ✅ **Valid email** - For Let's Encrypt certificate expiration notifications

### For Development/Testing:

- ⚠️ Will use self-signed certificates (browser warnings expected)

---

## Quick Start

### Option 1: Local Testing (Self-Signed Certificate)

**No configuration needed!** The installer configures nginx with a self-signed certificate by default:

```bash
sudo bash install.sh
```

Access your application at:
- **https://localhost** (⚠️ browser will show security warning - this is expected)
- HTTP traffic automatically redirects to HTTPS

**Browser Security Warning:**
- Click "Advanced" → "Proceed to localhost (unsafe)"
- This is safe for local testing
- Self-signed certificates are not trusted by browsers

### Option 2: Production Deployment (Let's Encrypt)

**Before deploying**, configure your environment variables:

#### Step 1: Configure Environment Variables

Edit `/opt/eas-station/.env`:

```bash
# Your domain name (REQUIRED)
DOMAIN_NAME=eas.example.com

# Email for certificate notifications (REQUIRED)
SSL_EMAIL=admin@example.com

# Use production Let's Encrypt server
CERTBOT_STAGING=0
```

#### Step 2: Verify DNS

Ensure your domain points to your server:

```bash
# Check DNS resolution
nslookup eas.example.com

# Should return your server's public IP
```

#### Step 3: Request the Certificate

Use the web UI at **Settings → SSL Certificates** (`/admin/certbot`), or run certbot directly:

```bash
sudo certbot --nginx -d eas.example.com --email admin@example.com --agree-tos
```

#### Step 4: Verify Certificate

Check the logs:

```bash
sudo tail -n 50 /var/log/letsencrypt/letsencrypt.log
sudo journalctl -u nginx --since "10 minutes ago"
```

Look for:
```
Successfully obtained SSL certificate
```

Access your application:
- **https://eas.example.com** (✅ secure, no warnings)
- HTTP automatically redirects to HTTPS

---

## Configuration Options

### Environment Variables

| Variable | Description | Default | Required |
| --- | --- | --- | --- |
| `DOMAIN_NAME` | Domain name for SSL certificate | `localhost` | Yes (for production) |
| `SSL_EMAIL` | Email for Let's Encrypt notifications | `admin@example.com` | Yes (for production) |
| `CERTBOT_STAGING` | Use Let's Encrypt staging server | `0` | No |

### Let's Encrypt Staging Mode

**When to use staging mode:**

```bash
CERTBOT_STAGING=1
```

✅ **Use staging when:**
- Testing certificate configuration
- Developing SSL features
- Avoiding production rate limits (50 certificates/week per domain)

⚠️ **Staging certificates:**
- Not trusted by browsers
- Show security warnings
- Good for testing automation

❌ **Don't use staging for:**
- Production deployments
- Public-facing sites

### Rate Limits

Let's Encrypt production limits:
- 50 certificates per registered domain per week
- 5 failed validation attempts per hour

**Best practices:**
1. Test with `CERTBOT_STAGING=1` first
2. Switch to production only when configuration is confirmed working
3. Don't delete and recreate certificates unnecessarily

---

## Web UI Certificate Management

**NEW in v2.35.0:** Full SSL certificate management through the web interface - no CLI required!

### Accessing the Certificate Manager

1. Log in to EAS Station™ web interface
2. Navigate to **Settings → SSL Certificates** (or visit `/admin/certbot`)
3. Configure your domain and email in the **Configuration** tab

### Obtaining a Certificate via Web UI

**Step 1: Configure Settings**
- Enable Certbot
- Enter your domain name (e.g., `eas.example.com`)
- Enter your email address
- Choose Production or Staging mode
- Save settings

**Step 2: Test Domain**
- Click **Test Domain** to verify DNS and port 80 accessibility
- Ensure both tests pass before obtaining a certificate

**Step 3: Obtain Certificate**
- Click **Obtain Certificate Now**
- Choose acquisition method:
  - **Standalone** (Recommended): Temporarily stops nginx, obtains cert, restarts nginx
  - **Nginx Plugin**: No downtime, uses nginx plugin
  - **Webroot**: Uses existing web server
- Click **Obtain Certificate** and wait for completion
- Real-time output shows certbot progress

**Step 4: Verify**
- Click **Check Certificate Status** to view certificate details
- Your site should now be accessible via HTTPS

### Managing Certificate Renewal via Web UI

**Check Renewal Status:**
- Click **Manage Certificate Renewal**
- Click **Check Auto-Renewal Status**
- View systemd timer status and next run time

**Manual Renewal:**
- Click **Manage Certificate Renewal**
- Choose renewal type:
  - **Dry Run**: Test renewal without making changes (safe)
  - **Normal Renewal**: Only renew if certificate is expiring soon
  - **Force Renewal**: Force renewal immediately (use with caution)
- Click **Execute Renewal**
- View real-time certbot output

**Enable/Disable Auto-Renewal:**
- Check auto-renewal status
- Click **Enable Auto-Renewal** or **Disable Auto-Renewal**
- Auto-renewal uses systemd timer (certbot.timer)

### Benefits of Web UI Management

✅ **No CLI Access Required** - Everything through the web interface
✅ **Real-Time Feedback** - See certbot output as it runs
✅ **Error Handling** - Clear error messages with actionable guidance
✅ **One-Click Operations** - Obtain, renew, enable auto-renewal with clicks
✅ **Safe Testing** - Dry run option prevents accidental changes
✅ **Status Monitoring** - Check certificate validity, auto-renewal timer status

---

## Troubleshooting

### Problem: Certificate Not Obtained

**Symptom:** Self-signed certificate generated instead of Let's Encrypt

**Check these:**

1. **DNS Resolution**
   ```bash
   nslookup $DOMAIN_NAME
   ```
   Should return your server's IP

2. **Port 80 Accessibility**
   ```bash
   curl http://$DOMAIN_NAME/.well-known/acme-challenge/test
   ```
   Should connect (404 is OK, connection timeout is bad)

3. **Firewall Rules**
   ```bash
   # Check if port 80 is listening
   sudo ss -tlnp | grep ':80'

   # Test from external host
   curl -I http://your-ip-address
   ```

4. **Check Logs**
   ```bash
   sudo tail -n 100 /var/log/letsencrypt/letsencrypt.log
   sudo journalctl -u nginx -n 100
   ```

**Common causes:**
- Domain not pointing to server
- Firewall blocking port 80
- Another service using port 80
- Domain validation timeout

### Problem: Browser Shows "Not Secure"

**Possible causes:**

1. **Self-signed certificate** (expected for localhost)
   - Solution: Use a real domain name with Let's Encrypt

2. **Certificate not installed yet**
   - Solution: Wait for initialization to complete

3. **Mixed content** (HTTPS page loading HTTP resources)
   - Check browser console for errors
   - Solution: Ensure all resources use HTTPS or relative URLs

### Problem: Certificate Renewal Failed

**Check:**

**Common causes:**
- Port 80 blocked
- Domain DNS changed
- Disk full (can't write renewed certificate)

**Manual renewal test:**

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Force renewal
sudo certbot renew --force-renewal
```

### Problem: Port 80 Already in Use

**Symptom:**
```
Error: port 80 is already allocated
```

**Find what's using the port:**

```bash
sudo lsof -i :80
# or
sudo netstat -tlnp | grep :80
```

**Solutions:**

1. **Stop conflicting service:**
   ```bash
   sudo systemctl stop apache2  # or nginx, etc.
   sudo systemctl disable apache2
   ```

2. **Use different port mapping:**
   ```yaml
   ports:
     - "0.0.0.0:8080:80"  # Use port 8080 for IPv4 clients
     - "[::]:8080:80"     # Use port 8080 for IPv6 clients
     - "0.0.0.0:8443:443" # Use port 8443 for IPv4 clients
     - "[::]:8443:443"    # Use port 8443 for IPv6 clients
   ```

   ⚠️ **Note:** Let's Encrypt requires port 80 for validation

---

## Advanced Topics

### Custom nginx Configuration

The nginx configuration for bare-metal deployments is located at `/etc/nginx/sites-available/eas-station` (symlinked from `config/nginx-eas-station.conf`). To customize:

1. Edit the configuration file:
   ```bash
   sudo nano /etc/nginx/sites-available/eas-station
   ```
2. Test and reload nginx:
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

**Common customizations:**

#### Increase Upload Size Limit

```nginx
# In /etc/nginx/sites-available/eas-station server block
client_max_body_size 500M;  # Default is 100M
```

#### Add Custom Headers

```nginx
# In /etc/nginx/sites-available/eas-station server block
add_header X-Custom-Header "value" always;
```

#### Adjust Rate Limiting

Rate limiting zones are defined in the main nginx configuration at `/etc/nginx/nginx.conf` within the http block. To adjust:

```bash
sudo nano /etc/nginx/nginx.conf
```

Find and modify:
```nginx
# Inside the http block
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;  # More permissive
```

Then reload nginx:
```bash
sudo systemctl reload nginx
```

### Multiple Domains

To serve multiple domains:

1. **Edit the nginx configuration**:
   ```bash
   sudo nano /etc/nginx/sites-available/eas-station
   ```
   
   Update the server_name directive:
   ```nginx
   server {
       listen 443 ssl http2;
       server_name eas1.example.com eas2.example.com;
       # ... rest of config
   }
   ```

2. **Obtain certificates for all domains**:
   ```bash
   sudo certbot --nginx -d eas1.example.com -d eas2.example.com
   ```

### Using Existing Certificates

If you already have SSL certificates:

1. **Copy your certificates to the system directory:**
   ```bash
   sudo mkdir -p /etc/letsencrypt/live/yourdomain.com
   sudo cp fullchain.pem /etc/letsencrypt/live/yourdomain.com/
   sudo cp privkey.pem /etc/letsencrypt/live/yourdomain.com/
   sudo cp chain.pem /etc/letsencrypt/live/yourdomain.com/
   sudo chmod 600 /etc/letsencrypt/live/yourdomain.com/*.pem
   ```

2. **Update nginx configuration** to point to your certificates:
   ```bash
   sudo nano /etc/nginx/sites-available/eas-station
   ```
   
   Ensure the SSL certificate paths are correct:
   ```nginx
   ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
   ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
   ```

3. **Reload nginx:**
   ```bash
   sudo systemctl reload nginx
   ```

### Monitoring Certificate Expiration

Check certificate expiration:

```bash
# View certificate details
sudo openssl x509 -in /etc/letsencrypt/live/eas.example.com/cert.pem -noout -dates

# Output shows:
# notBefore=...
# notAfter=...
```

**Automatic renewal:**
- certbot checks every 12 hours
- Renews certificates 30 days before expiration
- No manual intervention required

### HTTPS-Only Mode

To completely disable HTTP (port 80):

1. **Edit the nginx configuration:**
   ```bash
   sudo nano /etc/nginx/sites-available/eas-station
   ```
   
2. **Comment out or remove the HTTP server block** (the one listening on port 80)

3. **Reload nginx:**
   ```bash
   sudo nginx -t && sudo systemctl reload nginx
   ```

⚠️ **Warning:** This breaks Let's Encrypt ACME challenges. Only use if you have other certificate management or already have valid certificates.

### SSL/TLS Configuration

Current configuration:
- **Protocols:** TLS 1.2, TLS 1.3
- **Ciphers:** Mozilla Intermediate compatibility
- **HSTS:** Enabled (63072000 seconds = 2 years)
- **OCSP Stapling:** Enabled

To modify, edit `/etc/nginx/sites-available/eas-station`:

```nginx
ssl_protocols TLSv1.3;  # TLS 1.3 only (more restrictive)
ssl_ciphers 'HIGH:!aNULL:!MD5';  # Different cipher suite
```

After changes, test and reload:
```bash
sudo nginx -t && sudo systemctl reload nginx
```

**Test your configuration:**
- https://www.ssllabs.com/ssltest/
- https://observatory.mozilla.org/

---

## Security Best Practices

1. **Always use production certificates** for public deployments
2. **Keep certbot updated** - Done automatically with `certbot/certbot:latest`
3. **Monitor expiration** - certbot sends emails 30/14/7 days before expiration
4. **Protect private keys** - Never commit certificate files to git
5. **Use strong ciphers** - Default configuration uses Mozilla Intermediate
6. **Enable HSTS** - Already enabled in default config

---

## Related Documentation

- [SSL Web UI Guide](SSL_WEB_UI_GUIDE.md) - Managing certificates from the admin UI
- [Firewall Requirements](../troubleshooting/FIREWALL_REQUIREMENTS.md) - Required network ports
- [Security Guide](../security/SECURITY.md) - General security guidelines

---

## Support

**Certificate not working?**
1. Check troubleshooting section above
2. Review nginx and certbot logs
3. Verify DNS and firewall configuration

**Need help?**
- Review this documentation
- Check project issues: https://github.com/KR8MER/eas-station/issues

---

**Last Updated:** 2026-05-28
**Author:** KR8MER Amateur Radio Emergency Communications
