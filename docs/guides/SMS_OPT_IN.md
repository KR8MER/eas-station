# SMS Opt-In (Double Opt-In)

`/sms-opt-in` is a public, unauthenticated page where a person can sign themselves up
for SMS emergency alerts, without an administrator having to add their number by hand.

---

## Why this exists

Carriers and Twilio review A2P 10DLC campaigns for exactly one thing above all else:
**can you show a verifiable way the recipient actually agreed to receive texts from
this number?** An administrator manually adding a phone number and attesting that
consent was obtained some other way (verbally, on paper, over email) gives a reviewer
nothing they can click through and confirm themselves.

`/sms-opt-in` fixes that: the person enters their own number, agrees to explicit
consent language, and proves they control that number by entering a one-time code
texted to it — a standard **double opt-in** pattern. Only then is the number added to
the live recipient list. If you're registering (or re-registering) a Twilio campaign,
point the reviewer at this page.

---

## How it works

1. Visitor opens `/sms-opt-in` — no account or login needed.
2. They enter their phone number (international format, e.g. `+15555550100`) and
   optionally a name, and check the required consent checkbox:

   > *"I agree to receive SMS emergency alerts from this EAS Station. Message frequency
   > varies. Message and data rates may apply. Reply STOP to opt out at any time, HELP
   > for help. See the Terms of Use and Privacy Policy."*

3. EAS Station™ texts a 6-digit code to that number via Twilio (valid for 10 minutes).
4. The visitor enters the code on the same page.
5. On a correct code: the number is added to `Settings → Notifications → SMS
   Recipients` automatically, and a permanent record is written — phone number, name,
   the exact consent text shown, the submitter's IP address, and the confirmation
   timestamp.

Administrators can review every confirmed sign-up under **Settings → Notifications →
Consent Records**.

Every SMS this system actually asks Twilio to send — alert broadcasts, opt-in
verification codes, and admin test messages — is separately recorded in
**Settings → Notifications → SMS Message Log**, searchable by recipient phone number.
Consent Records answers "did this number agree to receive alerts and when"; the
Message Log answers "was a text actually sent to this number, and did it succeed."

---

## Abuse protection

- Requests are rate-limited per IP address (five attempts per 15-minute window,
  the same limiter `/login` uses for password attempts).
- A given phone number can't be re-texted more than once a minute, so a bystander who
  doesn't control a number can't be used to spam it with repeated codes.
- A confirmation code allows five wrong guesses before that attempt is invalidated —
  the visitor has to start over, rather than being able to brute-force a 6-digit code.
- Codes are hashed at rest (the same peppered-hash scheme MFA backup codes use) —
  never stored in plaintext once sent.

---

## Prerequisites

SMS notifications must already be configured under **Settings → Notifications → SMS
Notifications** (Twilio Account SID, Auth Token, and From Number) — see
[guides/notifications.md](notifications.md). `/sms-opt-in` returns a clear error if SMS
isn't configured yet rather than silently failing.

---

## Removing a self-serve sign-up

Self-serve sign-ups land in the same `Settings → Notifications → SMS Recipients` list
as administrator-added numbers — remove a number there the same way regardless of how
it was added. The corresponding row in **Consent Records** is kept as a historical
record even after removal (it's evidence of what consent was given and when, not a
live subscription flag).

---

## Related Pages

| Resource | Location |
|---|---|
| SMS messaging policy (opt-in, opt-out, message content) | [policies/SMS_MESSAGING.md](../policies/SMS_MESSAGING.md) |
| Notifications setup guide | [notifications.md](notifications.md) |
| Public opt-in page (web UI) | `/sms-opt-in` on your EAS Station™ instance |
| Consent records (admin, web UI) | `Settings → Notifications → Consent Records` |
