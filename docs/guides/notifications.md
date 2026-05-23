# Notifications — Email & SMS

EAS Station™ can send notifications to operators whenever an EAS alert is received and
broadcast. Two channels are supported: **email** (via SMTP) and **SMS** (via Twilio).

Both are configured in the web UI under **Settings → Notifications**.

## Notification Flow

```mermaid
sequenceDiagram
    participant EAS as EAS Broadcast
    participant DB as Database
    participant NS as Notification Service
    participant SMTP as SMTP Server
    participant Twilio as Twilio API
    participant Op as Operator/Recipient

    EAS->>DB: Store broadcast record
    EAS->>NS: Trigger post-broadcast notification

    NS->>DB: Load notification settings
    DB-->>NS: Email + SMS configuration

    alt Email enabled
        NS->>NS: Build alert summary email
        NS->>SMTP: Connect and authenticate
        SMTP-->>NS: Ready
        NS->>SMTP: Send message to recipients
        SMTP-->>Op: Alert email delivered
    end

    alt SMS enabled
        NS->>NS: Build SMS alert message
        NS->>Twilio: POST /Messages (REST API)
        Twilio-->>NS: Message SID returned
        Twilio->>Op: SMS delivered to E.164 number
    end

    NS->>DB: Log delivery status
```

---

## Email Notifications

### How It Works

After each EAS broadcast, EAS Station™ connects to the configured SMTP server and delivers
an alert summary to every address in the **EAS Alert Recipients** list. A separate list
(**Compliance / Health Alert Recipients**) receives system-health and FCC compliance
notifications.

Optionally, the full composite EAS audio (SAME header + attention tone + voice +
end-of-message) can be attached as a WAV file.

### SMTP URL Format

```
smtp://username:password@host:port?tls=true
```

| Component | Description |
|---|---|
| `username` | SMTP login (some providers use `apikey` literally) |
| `password` | SMTP password or API key |
| `host` | SMTP server hostname |
| `port` | Usually `587` (STARTTLS) or `465` (TLS) |
| `?tls=true` | Append to enable STARTTLS; omit for plain / localhost |

**Localhost Postfix (no auth):**
```
smtp://localhost:25
```

### Choosing an SMTP Provider

#### Free Authenticated Relays (No Port 25 Required)

These work on any host, including Vultr, and do not require port 25 to be unblocked.
All support TLS on port 587.

| Provider | Free Limit | SMTP Host | Username | Notes |
|---|---|---|---|---|
| **Brevo** (Sendinblue) | 300 msg/day | `smtp-relay.brevo.com:587` | Your login email | No credit card required |
| **SendGrid** | 100 msg/day | `smtp.sendgrid.net:587` | `apikey` (literally) | Pass = API key |
| **Mailgun** | 100 msg/day (3 mo) | `smtp.mailgun.org:587` | Mailgun SMTP login | Domain verification required |
| **Resend** | 100 msg/day | `smtp.resend.com:587` | `resend` (literally) | Pass = API key |
| **SMTP2GO** | 1,000 msg/month | `mail.smtp2go.com:587` | SMTP2GO username | Good for low-volume |

For EAS Station™, alert volume is typically very low (alerts are only sent on actual EAS
events), so any free tier will comfortably cover normal operation.

**Example — Brevo:**
```
smtp://your@email.com:YOUR_SMTP_KEY@smtp-relay.brevo.com:587?tls=true
```

**Example — SendGrid:**
```
smtp://apikey:SG.xxxxxxxxxxxx@smtp.sendgrid.net:587?tls=true
```

#### Self-Hosted Postfix

If you prefer to run your own mail server on the same host, see the
[Local Mail Server guide](local_mail_server.md). Once Postfix is running:

```
smtp://localhost:25
```

#### Gmail

!!! warning "App Password Required"
    Google blocks SMTP logins with your regular password. You must create an
    **App Password** under your Google Account → Security → 2-Step Verification →
    App passwords.

```
smtp://your.address@gmail.com:APP_PASSWORD@smtp.gmail.com:587?tls=true
```

#### Microsoft 365 / Outlook

```
smtp://your.address@yourdomain.com:PASSWORD@smtp.office365.com:587?tls=true
```

### Configuration Steps

1. Go to **Settings → Notifications** in the EAS Station™ web UI.
2. Set **Enable Email Notifications** to **Enabled**.
3. Enter your SMTP URL in the **Mail Server URL** field.
4. Add recipient addresses to **EAS Alert Recipients** (one per line).
5. Optionally add addresses to **Compliance / Health Alert Recipients**.
6. Toggle **Attach Composite Audio** if you want WAV files attached to alert emails.
7. Click **Save Settings**.
8. Use the **Send Test Email** button to verify delivery before going live.

---

## SMS Notifications (Twilio)

EAS Station™ sends SMS alerts via **Twilio**. You need a Twilio account and a purchased
phone number (toll-free or long code).

### Prerequisites

- Twilio account at [twilio.com](https://www.twilio.com/)
- A Twilio phone number (toll-free recommended for production — see below)
- Account SID and Auth Token from the Twilio Console

### Configuration Steps

1. Go to **Settings → Notifications**.
2. Set **Enable SMS Notifications** to **Enabled**.
3. Enter your **Account SID** (starts with `AC…`).
4. Enter your **Auth Token**.
5. Enter your **From Number** in E.164 format (e.g. `+18005550100`).
6. Add recipient phone numbers to **SMS Recipients** (one per line, E.164 format).
7. Click **Save Settings**.
8. Use **Send Test SMS** to verify delivery.

### Phone Number Format (E.164)

All numbers must include the country code with a leading `+`:

```
+15555551234   ← US number
+447911123456  ← UK number
```

### Toll-Free Number Verification

If you use a **toll-free number** with Twilio, US carriers require you to submit it for
verification before it can send messages at scale. Unverified toll-free numbers have
very limited throughput and may have messages blocked or filtered.

!!! warning "Verify before going live"
    Submit your toll-free number for verification as soon as you purchase it.
    Unverified numbers are blocked by AT&T, T-Mobile, and Verizon for most traffic.

#### Complete Twilio Verification Form Field Guide

The Twilio toll-free verification form asks for the following information. Use these
exact values for EAS Station™:

**Business / Organization Information**

| Field | What to Enter |
|---|---|
| Business name | Your organization name (e.g. "Putnam County ARES" or personal callsign) |
| Business website | Full URL of your EAS Station™ instance (e.g. `https://eas.example.com`) |
| Business type | Non-profit / Government / Individual (choose what applies) |
| Business industry | Public Safety / Emergency Services |
| Business address | Your physical mailing address |

**Contact Information**

| Field | What to Enter |
|---|---|
| First name | Your first name |
| Last name | Your last name |
| Contact email | Your email address |
| Contact phone | Your phone number |

**Use Case**

| Field | What to Enter |
|---|---|
| Use case category | **Emergency** (select from dropdown) |
| Use case description | `EAS Station™ sends real-time Emergency Alert System (EAS) notifications to a small list of pre-authorized recipients (operators, monitoring personnel). Recipients have provided explicit prior written consent. Messages contain NWS/IPAWS alert event codes, affected area identifiers, and timestamps. Use case: emergency public-safety notification only.` |

**Opt-In Information**

| Field | What to Enter |
|---|---|
| Opt-in type | **Website opt-in** (or **Offline opt-in** if consent is documented offline) |
| Opt-in image / URL | `https://yourserver/sms-compliance` |
| Opt-in description | `Recipients are added exclusively by the system administrator in the EAS Station™ admin panel after obtaining explicit prior written consent from the individual. The consent disclosure shown at the opt-in URL is read to/provided to each recipient before their number is added.` |

**Message Content**

| Field | What to Enter |
|---|---|
| Message sample | See block below |
| Privacy policy URL | `https://yourserver/privacy` |
| Terms of service URL | `https://yourserver/terms` |

**Exact Message Sample** (copy this verbatim into the form):

```
EAS ALERT: TOR
Tornado Warning for Putnam County
Areas: 039137
2026-03-12T14:00:00
- EAS Station™
Reply STOP to stop msgs
```

#### Compliance Pages

EAS Station™ includes three public-facing compliance pages that Twilio reviewers can access
without logging in:

| Page | URL | Purpose |
|---|---|---|
| SMS Messaging Policy | `/sms-compliance` | Opt-in disclosure, keywords, frequency, rates — **required** |
| Privacy Policy | `/privacy` | Data handling, Twilio as sub-processor |
| Terms of Use | `/terms` | Operator consent obligations |

Verify these pages are reachable by opening them in a private browser window before
submitting the Twilio form.

#### Submission Process

1. Log into the [Twilio Console](https://console.twilio.com/).
2. Navigate to **Phone Numbers → Manage → Active Numbers**.
3. Click your toll-free number.
4. Click **Register for A2P** or **Verify for Toll-Free** (exact label varies by Twilio console version).
5. Complete all sections using the tables above.
6. Upload or paste the message sample exactly as shown.
7. Submit — Twilio typically reviews within 3–7 business days.
8. You will receive an email confirmation when verification is approved.

### CTIA Message Content Requirements

EAS Station™ automatically appends **`Reply STOP to stop msgs`** to every outgoing alert
message. This opt-out footer is required by CTIA messaging guidelines and enforced by
Twilio during verification review. Do not remove or alter this text.

Test messages also include `Reply STOP to stop msgs, HELP for help` to demonstrate
compliance to Twilio reviewers.

### Operator Consent Requirements

!!! warning "TCPA Compliance"
    You must obtain **explicit prior written consent** from every recipient before
    adding their number to EAS Station™. This is a legal requirement under the
    Telephone Consumer Protection Act (TCPA) and CTIA guidelines.

    - Document consent before adding any number.
    - Honor `STOP` opt-outs immediately — Twilio processes them automatically at the
      carrier level, but you must also remove the number from the admin panel.
    - Inform recipients: "Message and data rates may apply. Message frequency varies."
    - Use the consent language shown on the `/sms-compliance` page.

See the full [SMS Messaging Policy](../policies/SMS_MESSAGING.md) for consumer-facing
disclosures.

---

## Recipient Management

### Email Recipients

Enter one email address per line. Two separate lists are maintained:

- **EAS Alert Recipients** — receives a notification for every EAS broadcast.
- **Compliance / Health Alert Recipients** — receives system health alerts and
  FCC compliance warnings (separate from EAS broadcast emails).

### SMS Recipients

Enter one E.164 phone number per line. All numbers receive an SMS on every EAS broadcast.

---

## Troubleshooting

### Test email/SMS not arriving

- Check the **Mail Server URL** format — copy it exactly from the examples above.
- For Gmail, verify you are using an **App Password**, not your account password.
- For Brevo/SendGrid, confirm the API key has sending permission.
- Check the EAS Station™ application log for SMTP errors:
  ```
  journalctl -u eas-station-web -f
  ```

### Emails going to spam

- Add an SPF record for your sending domain.
- Use a dedicated sending domain, not a personal Gmail address.
- For local Postfix, set up a proper PTR record — see
  [Local Mail Server](local_mail_server.md#dns-records).

### Twilio SMS not delivering

- Verify your toll-free number is registered/verified in the Twilio Console.
- Check the Twilio Console → Monitor → Logs for delivery errors.
- Confirm `sms_from_number` is in E.164 format including the country code.
- If using a trial Twilio account, you can only send to verified numbers.
