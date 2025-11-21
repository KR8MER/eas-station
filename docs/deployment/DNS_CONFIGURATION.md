# DNS Configuration Quick Reference

**For:** Domain you already own
**Purpose:** Point to Squarespace and Vultr

---

## Configuration Overview

You'll need to configure DNS records at your domain registrar to point to:
1. **Squarespace** - For your commercial website (easstation.com)
2. **Vultr** - For EAS Station instances (instances.easstation.com, demo.easstation.com, etc.)

---

## Option 1: Use Squarespace Nameservers (Recommended)

**Pros:** Simplified management, automatic SSL, integrated with Squarespace
**Cons:** Need to manage Vultr A records in Squarespace

### Step 1: At Your Domain Registrar

Change nameservers to Squarespace:
```
ns1.squarespace.com
ns2.squarespace.com
ns3.squarespace.com
ns4.squarespace.com
```

### Step 2: In Squarespace

1. Go to **Settings → Domains → Use a Domain I Own**
2. Enter your domain: `easstation.com`
3. Squarespace will verify nameservers (takes 24-48 hours)

### Step 3: Add Vultr Subdomains in Squarespace

Once domain is connected:
1. Go to **Settings → Domains → easstation.com → DNS Settings**
2. Click **"Add Record"**

**For production EAS instances:**
```
Type: A
Host: demo
Value: YOUR_VULTR_SERVER_IP
TTL: 3600
```

**For managed hosting (multiple customers):**
```
Type: A
Host: customer1
Value: VULTR_IP_1
TTL: 3600

Type: A
Host: customer2
Value: VULTR_IP_2
TTL: 3600
```

**For wildcard (all subdomains to one server):**
```
Type: A
Host: *
Value: YOUR_VULTR_SERVER_IP
TTL: 3600
```

---

## Option 2: Use Vultr DNS (Alternative)

**Pros:** Keep everything in one place if heavily using Vultr
**Cons:** Need to configure Squarespace with A records

### Step 1: Enable Vultr DNS

1. Log in to [Vultr](https://my.vultr.com)
2. Go to **DNS**
3. Click **"Add Domain"**
4. Enter: `easstation.com`

### Step 2: At Your Domain Registrar

Change nameservers to Vultr:
```
ns1.vultr.com
ns2.vultr.com
```

###Step 3: In Vultr DNS Manager

**For Squarespace (main website):**
```
Type: A
Name: @
Data: 198.185.159.144
TTL: 3600

Type: A
Name: @
Data: 198.185.159.145
TTL: 3600

Type: CNAME
Name: www
Data: ext-cust.squarespace.com
TTL: 3600
```

**For Vultr EAS instances:**
```
Type: A
Name: demo
Data: YOUR_VULTR_SERVER_IP
TTL: 3600

Type: A
Name: prod
Data: YOUR_PRODUCTION_IP
TTL: 3600
```

---

## Option 3: Keep Current Registrar DNS

**Pros:** No changes to nameservers
**Cons:** Manage DNS in two places

### At Your Current Registrar DNS Panel

**For Squarespace (root domain):**
```
Type: A
Host: @
Value: 198.185.159.144
TTL: 3600

Type: A
Host: @
Value: 198.185.159.145
TTL: 3600

Type: CNAME
Host: www
Value: ext-cust.squarespace.com
TTL: 3600
```

**For Vultr subdomains:**
```
Type: A
Host: demo
Value: YOUR_VULTR_IP
TTL: 3600

Type: A
Host: app
Value: YOUR_VULTR_IP
TTL: 3600
```

---

## Recommended Structure

```
easstation.com                  → Squarespace website (marketing)
www.easstation.com              → Squarespace website
demo.easstation.com             → Vultr (public demo instance)
docs.easstation.com             → GitHub Pages or Squarespace
app.easstation.com              → Vultr (main production instance)
customer1.easstation.com        → Vultr (managed hosting customer 1)
customer2.easstation.com        → Vultr (managed hosting customer 2)
*.instances.easstation.com      → Vultr (wildcard for auto-provisioning)
```

---

## Verification

### Check DNS Propagation

**Online tools:**
- [whatsmydns.net](https://www.whatsmydns.net)
- [dnschecker.org](https://dnschecker.org)

**Command line:**
```bash
# Check A record
dig easstation.com

# Check subdomain
dig demo.easstation.com

# Check from specific DNS server
dig @8.8.8.8 easstation.com
```

**Expected output:**
```
;; ANSWER SECTION:
easstation.com.   3600   IN   A   198.185.159.144
easstation.com.   3600   IN   A   198.185.159.145
```

### Check SSL

Once DNS is propagated:
```bash
curl -I https://easstation.com
curl -I https://demo.easstation.com
```

Should see:
```
HTTP/2 200
server: nginx
```

---

## Common DNS Records Reference

| Type | Purpose | Example |
|------|---------|---------|
| **A** | Point domain to IPv4 | `easstation.com → 198.185.159.144` |
| **AAAA** | Point domain to IPv6 | `easstation.com → 2001:db8::1` |
| **CNAME** | Alias to another domain | `www → easstation.com` |
| **MX** | Email routing | `@ → mail.easstation.com` |
| **TXT** | Verification, SPF, DKIM | `v=spf1 include:_spf.google.com` |

---

## Email Configuration (Google Workspace)

If using Google Workspace for `sales@easstation.com`:

**MX Records:**
```
Priority: 1
Host: @
Value: ASPMX.L.GOOGLE.COM

Priority: 5
Host: @
Value: ALT1.ASPMX.L.GOOGLE.COM

Priority: 5
Host: @
Value: ALT2.ASPMX.L.GOOGLE.COM
```

**SPF Record (TXT):**
```
Type: TXT
Host: @
Value: v=spf1 include:_spf.google.com ~all
```

**DKIM Record (provided by Google):**
```
Type: TXT
Host: google._domainkey
Value: (Google will provide this)
```

---

## Troubleshooting

### DNS Not Propagating

**Wait time:** 1-48 hours (usually 1-4 hours)

**Clear local DNS cache:**
```bash
# macOS
sudo dscacheutil -flushcache

# Windows
ipconfig /flushdns

# Linux
sudo systemd-resolve --flush-caches
```

### SSL Certificate Issues

**Let's Encrypt rate limits:**
- 50 certificates per domain per week
- 5 duplicate certificates per week

**Fix:** Wait 7 days or use different subdomains

### Squarespace "Domain Not Connected"

1. Verify nameservers at registrar
2. Wait 24-48 hours
3. Contact Squarespace support with domain registrar info

---

## Quick Start (Recommended for You)

**Since you already own the domain:**

1. **Change nameservers to Squarespace** (at your registrar)
   ```
   ns1.squarespace.com
   ns2.squarespace.com
   ns3.squarespace.com
   ns4.squarespace.com
   ```

2. **Wait 24 hours** for propagation

3. **In Squarespace:**
   - Connect your domain
   - Add A records for Vultr subdomains

4. **Deploy Vultr server** and note IP address

5. **Add A record in Squarespace:**
   - Host: `demo`
   - Value: `YOUR_VULTR_IP`

6. **Test:**
   - `https://easstation.com` → Squarespace website
   - `https://demo.easstation.com` → EAS Station on Vultr

---

## Support

**Squarespace DNS Help:** [support.squarespace.com/hc/en-us/articles/205812378](https://support.squarespace.com/hc/en-us/articles/205812378)
**Vultr DNS Docs:** [vultr.com/docs/introduction-to-vultr-dns](https://www.vultr.com/docs/introduction-to-vultr-dns/)

---

**Last Updated:** November 21, 2025
