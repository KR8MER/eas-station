# SMS Messaging Policy

**Last updated:** September 14, 2026

This policy applies to the SMS notification feature of EAS Station™. It describes how
text messages are sent, who receives them, and how recipients can opt out.

---

## Program Description

**Who sends the messages.** Messages are sent by **EAS Station, LLC** (d/b/a EAS Station™), a
private technology company that builds Emergency Alert System (EAS) monitoring and decoding
software. EAS Station, LLC is *not* a government agency, first-responder organization, or
public-safety answering point, and does not represent itself as one.

**Who receives them.** People who entered their own mobile number on the public sign-up form at
`/sms-opt-in` and then confirmed a one-time code texted to that number.

**Why they receive them.** They asked to be notified when the EAS Station™ instance they signed
up with decodes and logs an EAS alert for the area it monitors. Each message carries the event
code, headline, affected area identifiers, and a timestamp.

Messages are sent via **Twilio** using a toll-free or long-code phone number provisioned by the
system operator.

### A2P 10DLC use case

This program registers under a **Standard** A2P 10DLC use case. It does **not** claim the carrier
*Emergency* special use case, which is reserved for qualifying first responders and public
emergency-response organizations registering on their own behalf — a private company providing
emergency-related technology does not qualify, even when its messages concern emergencies.

"Emergency" here describes the *subject matter* of the alerts the software decodes, not the
sender's status. Messages are informational notifications to consumers who subscribed to them;
they are not official government warnings and are not a substitute for NWS, IPAWS, or local
authority warnings. See
[A2P 10DLC Registration](../compliance/A2P_10DLC_REGISTRATION.md) for the campaign
submission packet.

---

## Opt-In Mechanism

EAS Station™ supports two ways a phone number is added to the recipient list:

**1. Self-serve double opt-in (recommended).** A public page at
`/sms-opt-in` lets a person enter their own phone number, review the
consent language below, and confirm by entering a one-time code texted to
that number. Only once the code is confirmed is the number added to the
live recipient list. Every attempt — the exact consent text shown, the
submitter's IP address, and the confirmation timestamp — is permanently
recorded and visible to the administrator under **Settings → SMS
Notifications → Consent Records**. This is the flow a carrier or Twilio
compliance reviewer can be pointed at directly.

Separately from consent, every SMS this system actually sends — alert
broadcasts, verification codes, and test messages — is logged under
**Settings → SMS Notifications → SMS Message Log**, searchable by recipient
phone number.

> Consent checkbox text shown on `/sms-opt-in`:
> *"I agree to receive SMS emergency alerts from this EAS Station. Message
> frequency varies. Message and data rates may apply. Reply STOP to opt out
> at any time, HELP for help. See the Terms of Use and Privacy Policy."*

**2. Administrator-added (not a registrable opt-in path).** The system
administrator may still add recipient phone numbers directly in the admin
panel under **Settings → SMS Notifications → SMS Recipients**, for situations
where the recipient cannot use the self-serve page themselves. In that
case:

- Only individuals who have provided **explicit prior written consent** may be added.
  **Verbal consent is not sufficient.**
- Adding a number constitutes the operator's attestation that the individual has
  consented to receive EAS alert SMS messages from this system, and that the operator can
  produce that written consent on request.
- Consent must be obtained and documented **before** any messages are sent.
- **Never submit this path as a campaign Call to Action.** A carrier reviewer can only verify
  consent they can reach on the open web; describing the CTA as "users will be asked verbally"
  is a documented rejection cause (Twilio errors 30909 / 30917). Submit the `/sms-opt-in` URL
  from method 1 instead.
- The EAS Station, LLC messaging program does not use this path at all — its recipient list is
  populated exclusively through the self-serve flow above.

---

## Message Content

Messages contain emergency alert information in the following format:

```
EAS ALERT: [Event Code]
[Alert Headline]
Areas: [Location Codes]
[Timestamp]
- EAS Station
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
- Not accessible by the EAS Station™ project maintainers (for deployments they do not operate).

> **No mobile information will be sold or shared with third parties or affiliates for marketing
> or promotional purposes. Text-messaging originator opt-in data and consent will not be shared
> with any third parties.**

Delivery through Twilio is the sole exception; Twilio acts only as a service provider processing
the number to deliver the requested messages. To have a number and its consent record removed,
reply `STOP` or email **support@easstation.com**.

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
| SMS opt-in flow guide | [guides/SMS_OPT_IN.md](../guides/SMS_OPT_IN.md) |
| Terms of Use | [policies/TERMS_OF_USE.md](TERMS_OF_USE.md) |
| Privacy Policy | [policies/PRIVACY_POLICY.md](PRIVACY_POLICY.md) |
| Live SMS policy page (web UI) | `/sms-compliance` on your EAS Station™ instance |
| Public opt-in page (web UI) | `/sms-opt-in` on your EAS Station™ instance |
