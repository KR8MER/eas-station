# 🛡️ Privacy Policy

_Last updated: September 14, 2026_

EAS Station™ is software published by EAS Station, LLC (KR8MER). This policy covers two
distinct situations, and which one applies to you determines which sections below are relevant:

1. **Your own deployment.** You download and self-host EAS Station™ on infrastructure you
   control. The maintainers receive no data from it at all. Sections 1–6 apply.
2. **The EAS Station, LLC deployment at [easstation.com](https://easstation.com).** EAS Station, LLC
   operates its own instance of this software, including an opt-in SMS alert notification program
   for subscribers who sign up at [easstation.com/sms-opt-in](https://easstation.com/sms-opt-in).
   Section 7 governs the data that program collects, and EAS Station, LLC is the data controller
   for it.

## 1. Project Scope
- For deployments you host yourself, the maintainers do not collect or process any information from your installations, receive telemetry, or run analytics against them.
- All data stored by such an application resides within the infrastructure you provision (databases, volumes, backups).
- Section 7 is the exception: it describes data collected directly by EAS Station, LLC from subscribers to its own SMS program, not from your deployment.

## 2. Local Data Storage
- The system may store configuration details, receiver metadata, CAP alert content, generated audio, and system logs.
- In a development or evaluation deployment these records exist to support testing workflows only. Remove sample data before reusing hardware or sharing backups.
- Treat any stored alert content as non-authoritative until validated on certified FCC equipment.

## 3. Optional Integrations
- If you enable third-party services (e.g., Azure Speech, SMTP relays, mapping APIs) their respective privacy policies apply.
- Configure credentials via environment variables and avoid transmitting sensitive or personally identifiable information through optional integrations.

## 4. Development & Testing Data
This section is guidance for deployments you are standing up, evaluating, or developing against.
It does not describe the production EAS Station, LLC deployment covered by Section 7.

- While your deployment remains in development, populate EAS Station™ exclusively with non-production or simulated data.
- Do not ingest live IPAWS traffic, dispatch records, or emergency response telemetry into a deployment that has not been provisioned and secured for production use.
- The maintainers are not responsible for safeguarding any datasets you choose to import.

## 5. Security Practices
- Restrict access to the application behind VPNs or private networks.
- Rotate credentials regularly and store secrets outside of source control.
- Apply dependency and OS security updates before inviting additional testers.
- Disconnect experimental builds from broadcast chains, transmitter controls, or other life-safety infrastructure.

## 6. No Data Warranty
- The maintainers disclaim all responsibility for data loss, corruption, disclosure, or regulatory issues arising from use of the software.
- You are solely responsible for implementing appropriate backups and safeguards.

## 7. Mobile Information & SMS Messaging Data

This section applies to the opt-in SMS alert program operated by EAS Station, LLC at
[easstation.com](https://easstation.com), and to any deployment of this software where the
operator has enabled SMS notifications. It is written to satisfy CTIA messaging guidelines and
U.S. wireless carrier requirements for A2P 10DLC messaging campaigns.

### 7.1 What is collected when you opt in
When you sign up at [easstation.com/sms-opt-in](https://easstation.com/sms-opt-in), the
following is recorded and retained as the evidence of your consent:

- The **mobile phone number** you submit, in E.164 format.
- An optional **name**, only if you choose to provide one.
- The **IP address** the sign-up was submitted from.
- The **exact consent language** displayed to you at the moment you checked the consent box, stored verbatim as a snapshot.
- **Timestamps** for the sign-up attempt and for the confirmation of the one-time code texted to your number.

### 7.2 How it is used
Your mobile number is used for one purpose only: to deliver the emergency alert notifications
you signed up to receive, along with the one-time verification code that confirms your sign-up
and any `HELP` or `STOP` confirmation replies. It is not used for marketing or promotional
messaging of any kind.

### 7.3 Sharing — no sale, no marketing disclosure

> **No mobile information will be sold or shared with third parties or affiliates for marketing or
> promotional purposes. Text-messaging originator opt-in data and consent will not be shared with
> any third parties.**

The single exception is delivery: your number is transmitted to **Twilio, Inc.**, which acts as a
service provider processing it solely to deliver the messages you requested. Twilio is
contractually restricted to that purpose and may not use the number for its own marketing.
Twilio's own [privacy policy](https://www.twilio.com/en-us/legal/privacy) governs its processing.
No other third party receives subscriber phone numbers, and no subscriber data is ever sold,
rented, or licensed to anyone.

### 7.4 Opting out and deletion
Reply **STOP** to any message to be removed from the recipient list immediately; carriers and
Twilio process this automatically and you will receive a single confirmation. You may also
request removal and deletion of your consent record by contacting the operator through the
channels in Section 8. Consent records are retained while your number remains subscribed, and
for a limited period afterward only as proof that consent was validly obtained and honored.

### 7.5 Self-hosted deployments
If an operator other than EAS Station, LLC has enabled SMS notifications on their own deployment,
that operator — not EAS Station, LLC — is the data controller for the phone numbers they collect.
The maintainers have no access to them. Operators are bound by the SMS terms in the
[Terms of Use](TERMS_OF_USE.md) and must meet the same standard described in this section.

## 8. Contact
- This policy is provided by EAS Station, LLC (KR8MER).
- **SMS subscribers** — for help with the SMS alert program, to request removal, or to ask what data is held about your number, email **support@easstation.com**. You may also reply `HELP` to any message you have received.
- General privacy questions about the software may be submitted through the GitHub issue tracker.
- Do **not** send sensitive personal data, emergency requests, or proprietary information through the public issue tracker; use the email address above instead.
