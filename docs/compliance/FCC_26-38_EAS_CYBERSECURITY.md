# FCC 26-38 EAS Cybersecurity Requirements — Compliance Reference

## The rule

**FCC 26-38** — *Report and Order in PS Docket Nos. 25-224 and 22-329, and Further
Notice of Proposed Rulemaking in PS Docket Nos. 25-224, 15-94, and 15-91*
("*Modernization of the Nation's Alerting Systems*" / "*Protecting the Nation's
Communications Systems from Cybersecurity Threats*"). Adopted June 25, 2026,
released June 29, 2026. Full text:
<https://docs.fcc.gov/public/attachments/FCC-26-38A1.pdf>.

Appendix A of the order amends **47 CFR § 11.35** by adding paragraph (d),
**"Equipment operational readiness"** (final rule text, quoted directly from
the order):

> (d) EAS Participants shall employ the following security controls with
> respect to EAS equipment, studio transmitter link equipment, and any
> remotely managed equipment that routes, processes, or inserts content into
> the transmission of the EAS Participant's programming:
>
> (1) Prior to any use to broadcast to the public, EAS Participants shall
> change any default password, use strong passwords, and change any password
> if the EAS Participant has reason to believe that the password has been
> compromised.
>
> (i) A strong password is any password that has a minimum of 15 characters
> and does not use dictionary words. Instead of using a strong password, EAS
> Participants may use alternative authentication measures, such as look-up
> secrets, out-of-band devices, single- or multi-factor one-time password
> devices, or single- or multi-factor cryptographic authentication, that are
> reasonably sufficient to mitigate the risk of unauthorized access.
>
> (ii) Passwords employed to comply with this requirement shall not be
> reused for the EAS Participant's other accounts, equipment, applications,
> or services.
>
> (2) Install security patches and security-related software and firmware
> updates issued by equipment manufacturers promptly after those patches or
> upgrades become available. Security patches and security-related software
> and firmware updates issued by equipment manufacturers may be tested
> before they are installed, provided that the testing begins promptly and
> is completed in a timeframe that is consistent with industry best
> practices; and
>
> (3) Use a network firewall or comparable network segmentation practice
> that limits remote management access to authorized devices and authorized
> users.

**Compliance deadline**: 60 days after the rule's publication in the
*Federal Register* (Report and Order ¶ 28). The order itself does not fix
that publication date — check the *Federal Register* for PS Docket Nos.
25-224 / 22-329 to compute the actual deadline. **WEA is explicitly excluded**
from these requirements (¶ 27); only EAS is covered.

**Who's regulated**: "EAS Participants" (47 CFR § 11.2(b)) — the station/
system operator, not the equipment vendor. EAS Station™ is EAS Software
running on an EAS Participant's own hardware; this document describes what
the platform does to make § 11.35(d) compliance achievable, and what remains
the operator's responsibility regardless of software.

## Requirement-by-requirement: what this platform does

### (1) Password requirements

| Sub-requirement | Status | Where |
|---|---|---|
| No default password before use | ✅ Enforced | The setup wizard (`/setup`) requires creating a real admin account before the system is usable — there is no factory-default admin credential to change. |
| 15-character minimum | ✅ Enforced (as of 2.214.0) | `webapp/routes_setup.py` (first-run admin creation), `webapp/admin/dashboard.py` / `ApplicationSettings.password_min_length` (account creation and resets, admin-configurable but defaults to 15, cannot be set below the rule's floor without an operator explicitly weakening it). |
| Not a dictionary word | ⚠️ Not implemented | No wordlist/dictionary check exists. `ApplicationSettings` supports requiring upper/lower/digit/special-character classes as a partial mitigation, but that is not equivalent to a dictionary check. Treat this as an operator responsibility (pick a genuinely random 15+ character password or passphrase) until a dictionary check is built. |
| Alternative authentication (MFA, etc.) | ✅ Available | TOTP-based MFA (`app_core/auth/mfa.py`) satisfies the rule's "alternative authentication measures ... reasonably sufficient to mitigate the risk of unauthorized access" language as a substitute for the strong-password requirement. |
| Change password if compromise suspected | ⚠️ Operator action | The UI supports resetting any account's password at any time (Admin → User Accounts); there is no automated compromise-detection trigger. |
| Not reused across other accounts/services | ⚠️ Operator action | Not something software can verify — the application has no visibility into an operator's other accounts. |

Password storage itself goes beyond what the rule requires: hashes are
salted (scrypt, via werkzeug) *and* peppered (a second, database-independent
secret — see `docs/security/SECURITY.md § 7`), so a stolen database dump
alone isn't enough to recover a password even before considering its length.

**Existing installs**: raising the enforced minimum to 15 does not
retroactively invalidate or expire any current password (a password hash
can't be measured for length). A passive, dismissible reminder banner
(`templates/base.html`, wired in `webapp/admin/auth.py`) nudges any account
whose password was last changed before 2026-09-02 — i.e. before this floor
existed — to rotate it. Nothing is blocked or forced.

### (2) Prompt patching

✅ **In-app, one-click**: Admin → Data & Storage → Admin Operations
(`/admin/operations`) has a working "Check for Updates" / "Run Update"
flow (`webapp/admin/maintenance/routes_operations.py`) that checks the
configured branch/tag against upstream, then launches `update.sh` under its
own systemd unit and streams live progress back to the browser —
`pip install --upgrade -r requirements.txt` and `alembic upgrade head`, the
same two steps verified end-to-end against a real Postgres database while
implementing this document's companion change (see the 2.214.0 CHANGELOG
entry). No SSH/CLI access is required. "Promptly after patches become
available" is still an operational commitment — the mechanism doesn't
auto-trigger itself on a schedule — but there is no software barrier to
acting on it the moment a release lands.

### (3) Firewall / network segmentation

✅ **In-app, one place**: `install.sh` configures UFW with a default-deny-incoming
policy and the station's fixed baseline (22, 80, 443) during initial setup.
Every port beyond that baseline — the LAN NTP server (UDP/123) and Icecast
streaming (TCP, configured port) — is opened, scoped to specific subnets, and
closed again entirely from **Settings → Firewall** (`webapp/admin/firewall.py`,
`/admin/firewall`), with no SSH access required. This is the platform's direct
implementation of "a network firewall ... that limits remote management access
to authorized devices and authorized users": every rule an operator adds is
CIDR-scoped (never a bare "open to the world" toggle short of the operator
explicitly typing `0.0.0.0/0`), tagged so the UI can only ever modify rules it
created itself, and requires the `system.configure` permission to change.

That page also re-checks the UFW baseline itself and offers a one-click fix
(`Apply Baseline Fix`) for a host that has drifted from install.sh's
provisioning — e.g. a deployment provisioned before UFW auto-configuration
existed, or one where the firewall was later disabled. `docs/security/SECURITY.md`'s
fail2ban integration adds host-firewall enforcement of the ban list on top of
this. Tailscale integration (`webapp/admin/tailscale.py`,
`templates/admin/tailscale.html`) offers a further option: administer the
station over a private mesh network instead of exposing admin ports to the
public Internet at all.

Postgres (5432) and Redis (6379) are never exposed through this page or
`install.sh` — there is no rule type for them, by design.

## Operator checklist

Software support doesn't complete compliance by itself. To actually meet
§ 11.35(d):

- [ ] Confirm UFW (or an equivalent firewall) is active and default-deny —
      check **Settings → Firewall** in the web UI (or `sudo ufw status verbose`
      directly), and click "Apply Baseline Fix" there if it reports drift.
- [ ] Review every rule listed on **Settings → Firewall** (LAN NTP, Icecast)
      and confirm each is scoped to a real subnet you control, never
      `0.0.0.0/0`, unless you specifically intend that stream to be public.
- [ ] If any admin port is intentionally exposed to the public Internet,
      consider migrating remote management to Tailscale instead.
- [ ] Rotate any admin password last set before 2026-09-02 to a genuinely
      random 15+ character value (the in-app banner will flag affected
      accounts) — a random passphrase from a password manager, not a
      pattern-based one, since there's no automated dictionary-word check.
- [ ] Do not reuse this station's admin password anywhere else.
- [ ] Run the update from Admin → Admin Operations promptly whenever a
      security-relevant release lands — watch `docs/reference/CHANGELOG.md`,
      or use "Check for Updates" on that page.
- [ ] After upgrading to 2.214.0 or later, confirm existing stored
      credentials were actually re-encrypted (defense-in-depth, not itself
      an § 11.35(d) requirement, but directly relevant to the same threat
      model): `sudo -u postgres psql -d alerts -c "SELECT azure_openai_key FROM tts_settings;"`
      should show a `enc:v1:...` value, not plaintext.
