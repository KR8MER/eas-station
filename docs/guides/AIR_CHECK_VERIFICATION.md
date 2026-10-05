# Air-Check Verification (Off-Air Self-Monitoring)

An **air-check** confirms that an alert this station sent was actually heard
back off the air. It closes the loop between "the encoder generated a valid
SAME header" and "that header left the transmitter intact".

**UI:** Diagnostics → **Air-Check** (`/air-check`)

## How it works

1. **Every SDR receiver has a role** (Monitor → Receivers → edit → **Role**):
   - **Monitor** (default): listens to an upstream source (NWR, LP-1, a state
     relay). Its decodes are FIPS-filtered and may be relayed.
   - **Air-check**: tuned to **this station's own transmitter**. Its decodes are
     compared with what the station sent and are **never relayed**, so
     monitoring your own output cannot loop it back onto the air.
2. **Every transmission opens an air-check.** Automatic CAP broadcasts, relayed
   off-air alerts, manual Broadcast Builder sends, Required Weekly Tests and
   resends all record the exact SAME header as it starts playing. The record's
   deadline is the playout length plus relay lead-in/lead-out plus the
   **grace period** (default 60 s, adjustable on the Air-Check page).
3. **The air-check receiver's decode is compared field by field**: originator,
   event code, location codes (in any order), purge time, issue time and
   station ID.

| Status | Meaning | What happens |
| --- | --- | --- |
| **Verified** | Heard back with every field matching | INFO entry in the system log |
| **Mismatch** | Heard back, but at least one field differs (the page lists which) | ERROR logged; included in health alerts |
| **Missed** | Not heard by the deadline | ERROR logged; included in the compliance health-alert email / SNMP trap |
| **Unexpected** | A header heard on your transmitter that this station did not send | WARNING logged; included in health alerts |
| **Pending** | Sent, waiting for the decode | Swept to *missed* every 30 s once past its deadline |

A decode must agree with a sent header on at least three of the six fields to
count as the same transmission. Anything less is recorded as *unexpected*.

When no receiver has the **Air-check** role, nothing is recorded and no
errors are raised. The feature is inert until you assign that role.

## Setting it up

1. Put an SDR on an antenna that hears your own transmitter (a separate
   receiver, not the one monitoring your upstream source).
2. **Monitor → Receivers** → add or edit that receiver, tune it to your
   frequency, enable **Audio Output**, and set **Role** to *Air-check*.
3. Send a test (Diagnostics → Weekly Test Schedule → *Send Test RWT Now*).
4. Open **Diagnostics → Air-Check**. The RWT should show as *verified* within
   seconds of its EOM.

If a known-good transmission shows as *missed* but later flips to *verified*
with the note "heard after the deadline", your air chain has more delay than the
grace period allows. Raise the grace period on the Air-Check page.

## Acknowledging problems

*Missed*, *mismatch* and *unexpected* rows count as open problems in the
24-hour summary and in the health-alert emails until someone clicks
**Acknowledge**. Acknowledged rows stay in the history.

## Notes and limits

- Air-checks run in the audio service (`eas-station-audio`). If that service
  is down, nothing is decoded and every transmission will be reported *missed*.
  That is intended, because the station cannot confirm what it put on the air.
- The decoder reports a header when it hears the EOM (end of message). If
  the EOM is never heard (a transmission cut off mid-message), the decoder
  gives up waiting after 5 minutes. By then the air-check has usually been
  marked *missed*. It then changes to *verified* (or *mismatch*) with a
  "heard after the deadline" note, so a missed check that later resolves
  this way points at a lost EOM.
- Receiver role changes take effect in the audio service within about
  30 seconds.
- Code: `app_core/air_check/` (matching, lifecycle, reporting),
  `webapp/admin/air_check.py` (page and API). Design notes:
  [Theory of Operation → Verification & Compliance](../architecture/THEORY_OF_OPERATION.md#6-verification-compliance).
