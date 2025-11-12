# HTTPS Setup Guide

This guide explains how to configure HTTPS for EAS Station using nginx and Let's Encrypt.

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

EAS Station includes built-in HTTPS support using:

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

- ✅ Just Docker and Docker Compose
- ⚠️ Will use self-signed certificates (browser warnings expected)

---

## Quick Start

### Option 1: Local Testing (Self-Signed Certificate)

**No configuration needed!** Just deploy:

```bash
# Using main docker-compose.yml
docker compose up -d

# Or using embedded database
docker compose -f docker-compose.embedded-db.yml up -d
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

Edit `stack.env` or `.env`:

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

#### Step 3: Deploy

```bash
docker compose up -d
```

#### Step 4: Verify Certificate

Check the logs:

```bash
docker compose logs nginx
docker compose logs certbot
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
   docker compose ps

   # Test from external host
   curl -I http://your-ip-address
   ```

4. **Check Logs**
   ```bash
   docker compose logs nginx
   docker compose logs certbot
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
   - Check: `docker compose logs nginx`
   - Solution: Wait for initialization to complete

3. **Mixed content** (HTTPS page loading HTTP resources)
   - Check browser console for errors
   - Solution: Ensure all resources use HTTPS or relative URLs

### Problem: Certificate Renewal Failed

**Check:**

```bash
docker compose logs certbot
```

**Common causes:**
- Port 80 blocked
- Domain DNS changed
- Disk full (can't write renewed certificate)

**Manual renewal test:**

```bash
# Test renewal (dry run)
docker compose exec certbot certbot renew --dry-run

# Force renewal
docker compose exec certbot certbot renew --force-renewal
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
   Edit `docker-compose.yml`:
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

The default nginx configuration is in `nginx.conf`. To customize:

1. Edit `nginx.conf`
2. Rebuild and restart:
   ```bash
   docker compose restart nginx
   ```

**Common customizations:**

#### Increase Upload Size Limit

```nginx
# In nginx.conf server block
client_max_body_size 500M;  # Default is 100M
```

#### Add Custom Headers

```nginx
# In nginx.conf server block
add_header X-Custom-Header "value" always;
```

#### Adjust Rate Limiting

```nginx
# At top of nginx.conf
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/s;  # More permissive
```

### Multiple Domains

To serve multiple domains:

1. **Edit nginx.conf**:
   ```nginx
   server {
       listen 443 ssl http2;
       server_name eas1.example.com eas2.example.com;
       # ... rest of config
   }
   ```

2. **Obtain certificates for all domains**:
   ```bash
   DOMAIN_NAME="eas1.example.com eas2.example.com" docker compose up -d
   ```

### Using Existing Certificates

If you already have SSL certificates:

1. **Create certificate directories:**
   ```bash
   mkdir -p certs/live/yourdomain.com
   ```

2. **Copy your certificates:**
   ```bash
   cp fullchain.pem certs/live/yourdomain.com/
   cp privkey.pem certs/live/yourdomain.com/
   cp chain.pem certs/live/yourdomain.com/
   ```

3. **Mount certificates in docker-compose.yml:**
   ```yaml
   volumes:
     - ./certs:/etc/letsencrypt:ro
   ```

### Monitoring Certificate Expiration

Check certificate expiration:

```bash
# View certificate details
docker compose exec nginx openssl s_client -connect localhost:443 -servername $DOMAIN_NAME < /dev/null 2>/dev/null | openssl x509 -noout -dates

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

1. **Edit nginx.conf** - Remove HTTP server block
2. **Edit docker-compose.yml**:
   ```yaml
   nginx:
     ports:
       - "443:443"  # Remove port 80 mapping
   ```

⚠️ **Warning:** This breaks Let's Encrypt ACME challenges. Only use if you have other certificate management.

### SSL/TLS Configuration

Current configuration:
- **Protocols:** TLS 1.2, TLS 1.3
- **Ciphers:** Mozilla Intermediate compatibility
- **HSTS:** Enabled (63072000 seconds = 2 years)
- **OCSP Stapling:** Enabled

To modify, edit `nginx.conf`:

```nginx
ssl_protocols TLSv1.3;  # TLS 1.3 only (more restrictive)
ssl_ciphers 'HIGH:!aNULL:!MD5';  # Different cipher suite
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
7. **Regular updates** - Update Docker images monthly

---

## Related Documentation

- [SYSTEM_DEPENDENCIES.md](../reference/SYSTEM_DEPENDENCIES.md) - Infrastructure components
- [dependency_attribution.md](../reference/dependency_attribution.md) - nginx and certbot attribution
- [PORTAINER_DEPLOYMENT.md](./PORTAINER_DEPLOYMENT.md) - Deployment via Portainer
- [SECURITY.md](../SECURITY.md) - General security guidelines

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

**Last Updated:** 2025-11-09
**Author:** KR8MER Amateur Radio Emergency Communications
