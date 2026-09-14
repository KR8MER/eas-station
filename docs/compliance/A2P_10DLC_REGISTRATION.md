# A2P 10DLC Campaign Registration

**Last updated:** September 14, 2026

This is the submission packet for registering the EAS Station™ SMS alert program as a US A2P
10DLC campaign, written after a campaign rejection on 2026-09-11 (errors 30886, 30907, 30909).
Every field below is meant to be copied verbatim into the Twilio Console.

Operators of their own EAS Station™ deployments should use this as a template, substituting
their own registered brand name and their own instance's public URLs.

---

## 1. Why the previous submission was rejected

| Error | Reviewer finding | What changed |
| --- | --- | --- |
| *(use case)* | The brand is a private technology company providing emergency-alert software. Private companies do not qualify for the **Emergency** special use case even when their messages concern emergencies — the registrant itself must be a first responder or public emergency-response organization. | The program no longer claims the Emergency special use case. It registers under a **Standard** use case, and `/sms-compliance` now says so explicitly, including that EAS Station, LLC is not a public-safety agency. |
| **30886** | Campaign description too vague — does not say who the sender is, who the recipients are, or why they get messages. | §3 below is a concrete, copy-paste description naming the registered brand, the recipients, and the purpose. The same three facts now open `/sms-compliance` §1. |
| **30907** | Website URL does not match the brand, campaign purpose, consent flow, or sample messages. | The Privacy Policy no longer reads as testing-only guidance that contradicts a live messaging program; it now has a Mobile Information section (§7) naming the program. `/sms-compliance` and `docs/policies/SMS_MESSAGING.md` were reconciled — the latter previously said recipients are "added exclusively by the system administrator", contradicting the public sign-up form. |
| **30909** | Call to Action could not be verified. The submission said *"Users will be verbally asked to consent."* | Verbal consent is not a verifiable CTA and must never be submitted. The real, public, unauthenticated web form is the CTA — see §4. It is now linked in the site footer on every page and from a button at the top of `/sms-compliance`. |

> **Do not resubmit the Emergency use case, and never describe the CTA as verbal.** Those two
> choices caused this rejection. If a genuine first-responder agency wants this messaging, that
> agency must register as the Brand itself.

---

## 2. Recommended use case

Register under a **Standard** use case. Twilio makes the final call, but in order of fit:

1. **Public Service Announcement** — *recommended.* Informational messages raising awareness of
   important issues. Closest match to weather/hazard alert notifications sent to subscribers who
   asked for them.
2. **Account Notification** — a reasonable alternative framing: notifications tied to the
   subscription the recipient created on the website.
3. **Low Volume Mixed** — acceptable fallback if message volume is low and the reviewer pushes
   back on both of the above.

Do **not** select Marketing (no promotional content is sent) or Emergency (the brand does not
qualify).

---

## 3. Campaign description (copy verbatim)

> EAS Station, LLC is a private software company that builds Emergency Alert System (EAS)
> monitoring and decoding software, and operates its own monitoring station at easstation.com.
> This campaign sends SMS alert notifications from EAS Station, LLC to individual consumers who
> personally signed up for them on our website at https://easstation.com/sms-opt-in and confirmed
> a one-time code texted to their own phone. Recipients are members of the public who asked to be
> notified by text whenever our monitoring station decodes an EAS alert for the area it monitors.
> Each message contains the EAS event code, the alert headline, the affected area identifiers, and
> a timestamp, so a subscriber learns of an alert without watching our dashboard. EAS Station, LLC
> is a private technology company, not a government agency or first-responder organization, and
> these messages are informational notifications to our own subscribers rather than official
> government warnings. No marketing, promotional, or third-party content is sent on this campaign,
> and no phone number is ever purchased, rented, or imported from any outside list. EAS Station,
> LLC is the direct offering party for this campaign; it is not messaging on behalf of any client.

Notes on why this satisfies 30886: it names the registered brand, states the sender is a private
company (matching the brand record), identifies the recipients and how they got on the list,
states the purpose, states the direct-offering (ISV) position, and matches both the sample
messages in §5 and the website copy at `/sms-compliance`.

---

## 4. Call to Action / message flow (copy verbatim)

Submit this URL as the opt-in URL:

```
https://easstation.com/sms-opt-in
```

It is publicly reachable with no login, no paywall, and no account. A reviewer can complete the
entire flow themselves. Description to submit:

> Consumers opt in themselves on a public web form at https://easstation.com/sms-opt-in, linked
> in the footer of every page on easstation.com and from a button at the top of
> https://easstation.com/sms-compliance. No login or account is required to reach it. The form
> asks for a mobile number in international format and an optional name. Directly beneath the
> number field is a consent checkbox that is UNCHECKED BY DEFAULT and must be actively checked
> before the form can be submitted; consent is not bundled with any other action and is never
> pre-selected. The checkbox label reads verbatim: "I agree to receive SMS emergency alerts from
> this EAS Station. Message frequency varies. Message and data rates may apply. Reply STOP to opt
> out at any time, HELP for help. See the Terms of Use and Privacy Policy." Links to the Terms of
> Use, Privacy Policy, and full SMS Messaging Policy appear immediately below the form. On submit,
> a 6-digit one-time code is texted to the number; the number is NOT added to the recipient list
> at this point. The visitor enters that code back into the form, and only once it is confirmed is
> the number added. Each confirmed sign-up is permanently recorded with the exact consent text
> displayed, the submitter's IP address, and the submission and confirmation timestamps. This web
> form is the only opt-in path for this campaign. There is no keyword, short-code, paper,
> point-of-sale, voice, or verbal opt-in, and no numbers are imported from purchased, rented,
> partner, or affiliate lists.

If a reviewer asks for a screenshot instead of a URL, capture the sign-up form showing the
unchecked consent checkbox and its full label text, and host it somewhere publicly reachable.
The form is not behind a login, so a plain URL should be sufficient.

---

## 5. Sample messages

Submit all three. They are reproduced byte-for-byte from the message bodies built in
`app_core/notifications/sms.py` — if that code changes, update these.

**Sample 1 — alert notification**

```
EAS ALERT: TOR
Tornado Warning for Hardin County
Areas: 039065
2026-09-14T14:02:00
- EAS Station
Reply STOP to stop msgs
```

**Sample 2 — opt-in verification code**

```
EAS Station verification code: 481920
Enter this on the page where you requested it to confirm you want to receive emergency alert texts. Expires in 10 minutes. Reply STOP to opt out, HELP for help.
```

**Sample 3 — required alert / weekly test**

```
EAS ALERT: RWT
Required Weekly Test
Areas: 039065
2026-09-14T11:00:00
- EAS Station
Reply STOP to stop msgs
```

---

## 6. Opt-out and help

These are configured in the Twilio Messaging Service's **Advanced Opt-Out** settings, not in this
codebase — set them there before resubmitting so the reviewer's own `STOP`/`HELP` test matches
what was registered.

- **Opt-out keywords:** `STOP`, `STOP ALL`, `CANCEL`, `END`, `QUIT`, `UNSUBSCRIBE` — handled
  automatically by Twilio at the carrier level.
- **Opt-out message:** "You have been unsubscribed from EAS Station alerts. No further messages
  will be sent. Reply HELP for help."
- **Help keyword:** `HELP`
- **Help message:** "EAS Station alert notifications. Msg&data rates may apply. Msg frequency
  varies. Email support@easstation.com. Reply STOP to unsubscribe."

---

## 7. Required URLs

| Field | URL |
| --- | --- |
| Website / brand URL | `https://easstation.com` |
| Opt-in / CTA URL | `https://easstation.com/sms-opt-in` |
| Privacy Policy | `https://easstation.com/privacy` |
| Terms of Use | `https://easstation.com/terms` |
| SMS Messaging Policy | `https://easstation.com/sms-compliance` |

All five must be live and publicly reachable before resubmitting. The Privacy Policy must carry
the mobile-data statement in its §7 — carriers reject campaigns whose privacy policy does not say
that mobile opt-in data is not sold or shared with third parties for marketing (errors 30908 /
30933).

---

## 8. Pre-submission checklist

- [ ] Brand record names **EAS Station, LLC** and matches the company details on easstation.com.
- [ ] Use case is a **Standard** one from §2 — **not** Emergency.
- [ ] Campaign description is the §3 text, naming sender, recipients, and purpose.
- [ ] Opt-in URL is `https://easstation.com/sms-opt-in` and loads with no login.
- [ ] Consent checkbox on that page is unchecked by default and blocks submit until checked.
- [ ] Message flow description is the §4 text, with no mention of verbal consent.
- [ ] All three sample messages from §5 are entered and match live output.
- [ ] Opt-out and help keywords and responses from §6 are configured.
- [ ] All five URLs in §7 resolve publicly.
- [ ] Privacy Policy §7 carries the no-sale / no-sharing statement.
- [ ] No number on the campaign's recipient list arrived by administrator entry — see
      [SMS Messaging Policy](../policies/SMS_MESSAGING.md).

---

## Related

| Document | Path |
| --- | --- |
| SMS Messaging Policy | [policies/SMS_MESSAGING.md](../policies/SMS_MESSAGING.md) |
| Privacy Policy | [policies/PRIVACY_POLICY.md](../policies/PRIVACY_POLICY.md) |
| Terms of Use | [policies/TERMS_OF_USE.md](../policies/TERMS_OF_USE.md) |
| Double opt-in implementation | [guides/SMS_OPT_IN.md](../guides/SMS_OPT_IN.md) |
