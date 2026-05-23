# SMS Messaging Policy

**Last updated:** March 12, 2026

This policy applies to the SMS notification feature of EAS Station™. It describes how
text messages are sent, who receives them, and how recipients can opt out.

---

## Program Description

EAS Station™ is a self-hosted Emergency Alert System (EAS) research and monitoring
platform. When SMS notifications are enabled by the system administrator, EAS Station™
sends text message alerts to pre-configured recipients whenever an EAS alert is received
and broadcast by the system.

Messages are sent via **Twilio** using a toll-free or long-code phone number provisioned
by the system operator. This is **not** a public subscription service — recipients are
added exclusively by the system administrator.

---

## Opt-In Mechanism

Because EAS Station™ is self-hosted software operated by a system administrator (not a
public-facing service), opt-in is managed at the operator level:

- The system administrator adds recipient phone numbers in the EAS Station™ admin panel
  under **Settings → Notifications → SMS Recipients**.
- Only individuals who have provided **explicit prior written consent** may be added.
- Adding a number constitutes the operator's attestation that the individual has
  consented to receive EAS alert SMS messages from this system.
- Consent must be obtained and documented **before** any messages are sent.

---

## Message Content

Messages contain emergency alert information in the following format:

```
EAS ALERT: [Event Code]
[Alert Headline]
Areas: [Location Codes]
[Timestamp]
- EAS Station™
Reply STOP to stop msgs
```

The opt-out reminder (`Reply STOP to stop msgs`) is appended to every message as required
by CTIA messaging guidelines enforced by Twilio. Messages target under 160 characters for
single-segment delivery where possible.

---

## Message Frequency

Message frequency depends entirely on EAS alert volume from the National Weather Service
and other authorized government agencies.

**Message frequency varies. During active weather or emergency events, multiple messages
may be sent within a short period. During quiet periods, no messages may be sent.**

---

## Message & Data Rates

**Message and data rates may apply.** Standard SMS and data rates charged by the
recipient's mobile carrier may apply. EAS Station™ and its operators do not charge any
fee for SMS notifications.

---

## How to Opt Out

Reply **STOP** to any message to stop receiving SMS from this system. You will receive
a one-time confirmation and will receive no further messages from this number.

You may also contact the system operator directly and request removal of your number
from the admin panel.

| Keyword | Effect |
|---|---|
| `STOP` | Unsubscribe from all messages |
| `STOP ALL` | Unsubscribe and block all future messages |
| `CANCEL` | Unsubscribe from all messages |
| `END` | Unsubscribe from all messages |
| `QUIT` | Unsubscribe from all messages |
| `UNSUBSCRIBE` | Unsubscribe from all messages |
| `HELP` | Receive help information |

---

## Help

Reply **HELP** to any message for assistance. You may also contact the system operator
through the contact information they have provided.

---

## Supported Carriers

SMS delivery is compatible with all major US wireless carriers including AT&T, T-Mobile,
Verizon Wireless, US Cellular, Boost Mobile, Cricket Wireless, and other regional and
national carriers.

!!! note
    Carriers are not liable for delayed or undelivered messages.

---

## Privacy

Phone numbers added to the EAS Station™ SMS recipient list are:

- Stored in the local EAS Station™ database on the **operator's** infrastructure.
- Transmitted to **Twilio, Inc.** solely for the purpose of delivering SMS messages.
- Not accessible by the EAS Station™ project maintainers.

See the [Privacy Policy](PRIVACY_POLICY.md) for complete data handling details.
Twilio's privacy policy is at [twilio.com/en-us/legal/privacy](https://www.twilio.com/en-us/legal/privacy).

---

## Operator Compliance Obligations

System operators who enable SMS notifications are responsible for:

- [ ] Obtaining and documenting explicit prior written consent from every recipient.
- [ ] Disclosing message frequency and "message and data rates may apply" before consent.
- [ ] Honoring opt-out (STOP) requests promptly and removing numbers from the admin panel.
- [ ] Complying with the Telephone Consumer Protection Act (TCPA) and CTIA guidelines.
- [ ] Using SMS only for EAS emergency alert notifications — not marketing or other purposes.
- [ ] Submitting toll-free numbers for Twilio verification before production use.

See [Twilio Toll-Free Verification](../guides/notifications.md#toll-free-number-verification)
for the verification process.

---

## Related Pages

| Resource | Location |
|---|---|
| Notifications setup guide | [guides/notifications.md](../guides/notifications.md) |
| Terms of Use | [policies/TERMS_OF_USE.md](TERMS_OF_USE.md) |
| Privacy Policy | [policies/PRIVACY_POLICY.md](PRIVACY_POLICY.md) |
| Live SMS policy page (web UI) | `/sms-compliance` on your EAS Station™ instance |
