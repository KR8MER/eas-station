# Local Mail Server (Postfix)

EAS Station™ can install and manage a **Postfix** mail transfer agent directly on the host
server. Once running, it acts as a local send-only SMTP relay — no external email
provider is required.

!!! tip "Easiest path for most users"
    If you just want reliable outbound email and don't want to manage a full mail server,
    use a [free authenticated relay](notifications.md#free-authenticated-relays-no-port-25-required)
    instead. Brevo, SendGrid, and Resend all have free tiers that work on Vultr without
    any support tickets.

---

## Overview

| | Details |
|---|---|
| **Software** | Postfix (standard Linux MTA) |
| **Install method** | `apt-get` — handled automatically by the GUI |
| **SMTP port** | 25 (loopback only — not exposed externally) |
| **Mail URL** | `smtp://localhost:25` |
| **Auth required** | No (loopback trust) |
| **Inbound mail** | Disabled — send-only configuration |

---

## Setup via the Admin UI

No terminal access required. All steps are performed in the browser.

### 1. Open Mail Server Settings

Go to **Settings → Mail Server** in the EAS Station™ navigation bar.

### 2. Install Postfix

If Postfix is not yet installed, the page shows an **Install Postfix** button. Click it.
EAS Station™ runs `apt-get install postfix` in the background. Installation takes about
30–60 seconds depending on connection speed. The page reloads automatically when done.

### 3. Configure

Two fields are required:

**Mail Hostname (FQDN)**
:   The fully-qualified domain name this server will use when introducing itself to
    remote mail servers. Example: `mail.yourdomain.com`.

    This **must match** your server's PTR (reverse-DNS) record for reliable delivery.
    EAS Station™ auto-detects the current system hostname as a starting point.

**Sender Address**
:   The `From:` address on all outbound alert emails. Example: `alerts@yourdomain.com`.

    The domain should have an SPF record that includes your server's IP.

Click **Apply Configuration & Restart**. EAS Station™ writes `/etc/postfix/main.cf` and
restarts the Postfix service.

### 4. Connect to EAS Station™ Notifications

Once Postfix is running (green **Port 25 Open** badge), click:

**Use Postfix for Alert Emails**

This sets the notification mail URL to `smtp://localhost:25` directly in the database.
You can also click **Open Notification Settings** to review the full email configuration.

### 5. Send a Test Email

Enter a recipient address and click **Send Test**. Check your spam folder if the
message doesn't arrive within a few minutes.

---

## Vultr-Specific Setup

### Unblock Port 25

Vultr blocks outbound port 25 by default on all new instances. You must request
it to be unblocked before Postfix can deliver mail directly.

1. Log into [my.vultr.com](https://my.vultr.com/).
2. Open a **Support ticket** with subject: *"Request to unblock SMTP port 25"*.
3. Include your instance IP and a brief description of the use case
   (e.g., "Self-hosted emergency alert notification system").
4. Vultr typically responds within a few hours for accounts in good standing.

!!! note
    If you don't want to wait or deal with this, use a
    [free relay service](notifications.md#free-authenticated-relays-no-port-25-required)
    instead — they operate on port 587 and work immediately.

### DNS Records

For mail to reach recipients without being flagged as spam, configure the following
DNS records for your sending domain:

#### PTR (Reverse DNS)

Set in the Vultr control panel:

1. Go to **Products → Instances** → your instance.
2. Click **Settings → IPv4**.
3. Set the **Reverse DNS** field to match the hostname you configured in EAS Station™
   (e.g., `mail.yourdomain.com`).

#### SPF (Sender Policy Framework)

Add a TXT record to your domain's DNS:

```
v=spf1 ip4:YOUR_SERVER_IP ~all
```

Replace `YOUR_SERVER_IP` with your Vultr instance's public IPv4 address.

#### MX Record (Optional)

Not required for a send-only server, but some spam filters check for a valid MX record:

```
mail.yourdomain.com  MX  10  mail.yourdomain.com
```

---

## Postfix Configuration Details

EAS Station™ writes the following `main.cf` to `/etc/postfix/main.cf`:

```ini
# Postfix main.cf — managed by EAS Station™
myhostname = mail.yourdomain.com    # ← your configured hostname
myorigin   = $myhostname

# Only accept local delivery
mydestination = $myhostname, localhost.$mydomain, localhost

# Direct internet delivery — no relay
relayhost =

# Loopback trust only
mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128

# Bind to loopback only — not exposed externally
inet_interfaces = loopback-only
inet_protocols  = all

# Opportunistic TLS on outbound connections
smtp_tls_security_level = may
smtp_tls_loglevel       = 1

# Enforce sender address
sender_canonical_maps = static:alerts@yourdomain.com  # ← your From address
```

---

## Authenticated Smart Relay (Optional)

If you prefer Postfix to relay through a third-party SMTP service rather than delivering
directly (e.g., because port 25 is blocked or you want better deliverability), you can
configure a smart relay. This is **not currently available via the GUI** — it requires
editing `/etc/postfix/main.cf` directly.

Add these lines after applying the base configuration:

```ini
# Smart relay via Brevo (example — substitute any provider)
relayhost = [smtp-relay.brevo.com]:587
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
smtp_tls_security_level = encrypt
```

Create `/etc/postfix/sasl_passwd`:
```
[smtp-relay.brevo.com]:587  your@email.com:YOUR_SMTP_KEY
```

Then run:
```bash
sudo postmap /etc/postfix/sasl_passwd
sudo systemctl restart postfix
```

---

## Useful Commands

View the mail queue:
```bash
mailq
```

Flush the queue (retry all deferred messages):
```bash
postqueue -f
```

View live Postfix logs:
```bash
journalctl -u postfix -f
```

Check Postfix configuration:
```bash
postfix check
```

---

## Troubleshooting

### "Port 25 Closed" after Apply

- Postfix may still be starting up — click **Refresh** after 10–15 seconds.
- Check logs: `journalctl -u postfix -e`
- Verify `inet_interfaces = loopback-only` is set (only listens on 127.0.0.1, but
  the port should still be reachable from EAS Station™).

### Mail is being deferred / rejected

- Confirm Vultr has unblocked port 25 on your account.
- Verify your PTR record matches `myhostname` exactly.
- Check the mail log: `journalctl -u postfix -f`

### Mail going to spam

- Add the SPF TXT record for your domain.
- Ensure the PTR record is set correctly in Vultr.
- For better deliverability, consider adding DKIM signing via `opendkim`
  (advanced — not currently managed by EAS Station™).
