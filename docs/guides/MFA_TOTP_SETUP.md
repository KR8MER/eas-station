# Multi-Factor Authentication (TOTP) Setup

EAS Station™ supports time-based one-time password (TOTP) multi-factor authentication for all admin accounts. Once enabled, users must enter a six-digit code from an authenticator app in addition to their password at every login.

---

## Prerequisites

- An authenticator app installed on your phone:
  - **Google Authenticator** (iOS / Android)
  - **Aegis Authenticator** (Android, open source)
  - **Raivo OTP** (iOS, open source)
  - **Microsoft Authenticator** (iOS / Android)
  - **Authy** (iOS / Android / desktop)

- Your account must be active with a valid password.

---

## Enabling MFA on Your Account

1. Log in to the EAS Station™ web interface.
2. Navigate to **Account → Security Settings** (top-right user menu).
3. Click **Enable Two-Factor Authentication**.
4. A QR code is displayed. Open your authenticator app and scan it.
   - If you cannot scan the QR code, tap **Enter code manually** in your app and type the key shown on screen.
5. Once the app shows a six-digit code, enter it in the **Verification Code** field and click **Verify & Enable**.
6. EAS Station™ verifies the code. If valid, MFA is activated immediately.
7. **Save your backup codes.** A set of 10 single-use recovery codes is displayed. Store these in a safe place — they are the only way to recover access if you lose your authenticator device.

---

## Logging In with MFA Enabled

1. Enter your username and password as normal.
2. After a successful password check, you are redirected to the MFA verification page.
3. Open your authenticator app and enter the current six-digit code.
4. The MFA verification window is **5 minutes**. If it expires, return to the login page and start again.
5. TOTP codes are valid for a **90-second window** (±1 time step) to accommodate minor clock drift. Each code can only be used once.

---

## Using a Backup Code

If you lose access to your authenticator app, enter a backup code in the MFA verification field instead of a TOTP code.

- Backup codes are 8-character alphanumeric strings (e.g., `A3F7D2B1`).
- Each backup code is single-use and is invalidated after successful entry.
- You started with 10 backup codes. Once all are used, you cannot log in without a working authenticator.

---

## Disabling MFA

1. Log in (using both password and TOTP code).
2. Navigate to **Account → Security Settings**.
3. Click **Disable Two-Factor Authentication**.
4. Confirm when prompted.
5. MFA is immediately disabled. Your TOTP secret and backup codes are deleted.

An administrator can also disable MFA for another user via **Admin → User Management → Edit User → Disable MFA**.

---

## Administrator: Enabling MFA for Other Users

1. Go to **Admin → User Management**.
2. Click **Edit** next to the target account.
3. Enable the **Require MFA** toggle if you want to force MFA at next login.
4. The user completes enrollment on their next login session.

---

## Clock Synchronization

TOTP codes are time-sensitive. If your EAS Station™ server clock drifts, codes may be rejected.

Verify NTP is working:

```bash
timedatectl status
```

Expected output includes `System clock synchronized: yes`. If not, enable NTP:

```bash
sudo timedatectl set-ntp true
sudo systemctl restart systemd-timesyncd
```

The system accepts codes from ±1 time step (90 seconds total window) to handle minor clock skew.

---

## Troubleshooting

### Code rejected immediately after scanning QR

- Confirm your phone's time is synchronized (Settings → Date & Time → Automatic).
- Verify you scanned the correct QR code — each enrollment generates a new secret.
- Wait for the current 30-second window to expire and try with the next code.

### Autofilling the code from a password manager

The verification field is marked `autocomplete="one-time-code"`, so iOS/macOS
Passwords, 1Password, Bitwarden and Chrome will offer the stored code above the
keyboard and the form submits itself once the code lands — no typing.

For that to work your password manager needs the TOTP secret, which it cannot
learn from the login page. Add it once, during (or after) enrolment:

1. Start MFA enrolment. Under the QR code, copy the **setup key** shown next to
   *"Or manually enter this secret key"*.
2. Open the saved EAS Station entry in your password manager and paste the key
   into its one-time-code / verification-code field (in iOS Passwords: **Edit →
   Set Up Verification Code → Enter Setup Key**).
3. Finish enrolment using the code your password manager now generates.

If the entry has no verification-code field, the manager has no code to offer
and the field will simply behave as a normal text input.

### "Code already used" error

EAS Station™ refuses to accept the **same** code twice — each 30-second code may
be spent on exactly one successful sign-in. Wait for your authenticator to show
the next code and enter that one; it is accepted immediately, with no cooldown
between logins.

> **Fixed in 2.126.2:** earlier releases rejected *every* code for 90 seconds
> after a successful sign-in, not just reused ones, so a second login meant
> sitting through several code rotations. If you are on an older build and see
> "Invalid verification code" for correct, freshly rotated codes, upgrade.

### Locked out (lost authenticator + backup codes)

If you have lost both your authenticator device and all backup codes, a system administrator must reset MFA via the database:

```bash
# Connect to the PostgreSQL database
psql -U eas_station -d eas_station

-- Find the user
SELECT id, username, mfa_enabled FROM admin_users;

-- Disable MFA for the affected user
UPDATE admin_users SET mfa_enabled = false, mfa_secret = null, mfa_backup_codes_hash = null WHERE username = 'affected_user';
```

Then restart the web service:

```bash
sudo systemctl restart eas-station-web
```

The user can now log in with password only and re-enroll MFA.

### MFA verification page times out

The MFA challenge session expires after 5 minutes. Return to `/login` and authenticate again from the beginning.

---

## Security Notes

- TOTP secrets are stored in the database; ensure the database is protected with a strong password and access controls.
- Backup codes are stored as bcrypt hashes — even with database access, plaintext codes cannot be recovered.
- Audit log entries are created for all MFA events: enrollment, successful verification, failed attempts, and backup code usage.
- Review MFA-related audit events at **Admin → Audit Logs**.
