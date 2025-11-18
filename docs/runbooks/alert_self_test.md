# Alert Pipeline Self-Test

Validate the SAME decoding and FIPS filtering chain without waiting for a live
broadcast. The `scripts/run_alert_self_test.py` helper replays curated RWT audio
captures through the same logic that production alerts use so operators can
prove the system still activates for the programmed counties.

## When to Run

- After changing receiver wiring, decoder parameters, or FIPS configuration
- Before compliance audits that require proof of alert readiness
- During lab demonstrations for customers that need to see a deterministic test
- Any time an operator suspects alerts are being ignored or suppressed

## Web UI Quick Start

1. Sign in and open **Tools → Alert Verification**.
2. Scroll to the **Alert Self-Test** panel and verify the configured FIPS list matches your coverage area.
3. Keep the bundled samples selected (or paste custom audio paths) and click **Run Self-Test**.
4. Review the summary card—"Forwarded" entries prove the monitoring chain would fire.

Results are logged with timestamps, duplicate counts, and per-file explanations so you can take a screenshot for auditors.

## CLI Quick Start

```bash
python scripts/run_alert_self_test.py
```

Running the script without arguments automatically replays the bundled RWT
captures located in `samples/`. Output resembles:

```
EAS Alert Self-Test
========================================================================
Configured FIPS: 039137
Audio samples: 2
Duplicate cooldown: 30.0s

Result   Event    Origin  Matched FIPS       File
------------------------------------------------------------------------
✅ forwarded          RWT     WXR     039137            ZCZC-EAS-RWT-039137+0015-3042020-KR8MER.wav (Matched configured FIPS: 039137)
⚪️ filtered           RWT     WXR     —                 ZCZC-EAS-RWT-042001-042071-042133+0300-3040858-WJONTV.wav (No configured FIPS overlap)
------------------------------------------------------------------------
Forwarded alerts: 1
See docs/runbooks/alert_self_test.md for interpretation guidance.
```

## Command Options

| Flag | Description |
| --- | --- |
| `audio ...` | Optional list of WAV/MP3 files to replay. If omitted the bundled samples are used. |
| `--fips 039137 039069` | Override the county codes pulled from Location Settings. |
| `--require-match` | Exit with status code `3` if none of the samples would have activated. Useful for CI smoke tests. |
| `--cooldown 0` | Adjust the duplicate suppression window (seconds) to test back-to-back activations. |
| `--source-name NOAA-radio` | Customize the source label recorded in the report. |
| `--no-default-samples` | Require explicit file paths instead of replaying the built-in captures. |

## Result Codes

| Icon | Status | Meaning |
| --- | --- | --- |
| ✅ | `forwarded` | The alert matched at least one configured FIPS code and would have activated. |
| ⚪️ | `filtered` | The alert decoded successfully but none of its FIPS codes overlap the configured list. |
| 🟡 | `duplicate_suppressed` | The alert was identical to one seen within the cooldown window and would be ignored. |
| ❌ | `decode_error` | The audio file could not be decoded (missing SAME header or unsupported format). |

The script exits with:

- `0` when every file decoded and (optionally) at least one match occurred
- `2` if any file failed to decode
- `3` when `--require-match` is set and no alert was forwarded

## Tips for Reliable Demonstrations

- Use a copy of the customer’s receiver recording if possible so they hear a
  familiar audio capture.
- Pair `--cooldown 0` with two copies of the same file to prove duplicate
  suppression is working.
- Override FIPS codes with `--fips` when demonstrating outside of the customer’s
  home market so the bundled captures still activate.
- Pipe the script output into a logbook for audit artifacts:
  `python scripts/run_alert_self_test.py --require-match | tee self-test.log`

## Troubleshooting

| Symptom | Action |
| --- | --- |
| `decode_error` for every file | Ensure `ffmpeg` is installed and the audio files are accessible. |
| `filtered` when it should match | Confirm Location Settings contains the expected county codes or use `--fips` to override. |
| `duplicate_suppressed` unexpectedly | Increase `--cooldown` or diversify the test files so each alert has unique SAME headers. |

Document the results in customer-facing reports to prove the monitoring chain is
ready before relying on live broadcasts.
