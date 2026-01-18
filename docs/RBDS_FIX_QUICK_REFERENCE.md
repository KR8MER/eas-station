# RBDS Fix - Quick Reference

## What Was Wrong

**CRITICAL BUG**: Missing register reset after processing RBDS blocks

- **Location**: `app_core/radio/demodulation.py` line 1100
- **Symptom**: 100% CRC failures (RBDS synchronizes but all blocks fail)
- **Cause**: Bits from previous block contaminated next block
- **Type**: Regression (was fixed in v2.44.8, then lost)

## What Was Fixed

Added one line of code:
```python
self._rbds_reg = 0  # Reset register after processing each block
```

## Quick Verification

```bash
# 1. Check the fix is present
grep -n "_rbds_reg = 0" app_core/radio/demodulation.py
# Should show lines 972 and 1100

# 2. Run validation
python3 validate_rbds_system.py

# 3. Run diagnostic
python3 tools/rbds_auto_diagnostic.py
```

## Quick Deployment

```bash
# 1. Pull the fix
git pull

# 2. Restart service
systemctl restart eas-station-audio.service

# 3. Monitor logs
journalctl -u eas-station-audio.service -f | grep -i rbds
```

## Configuration Requirements

### In Admin → Radio Settings:

1. ✅ **Enable RBDS**: Check "Extract RBDS/RDS" checkbox
2. ✅ **Sample Rate**: Set to ≥ 114,000 Hz (recommend 250,000 Hz)
3. ✅ **Modulation**: Set to FM or WFM (NOT NFM)
4. ✅ **Good Signal**: Ensure antenna and tuning are correct

### What to Look for in Logs:

```
✅ "RBDS ENABLED: creating worker thread at 250000 Hz"
✅ "RBDS SYNCHRONIZED at bit 12345"
✅ "RBDS group: PI=0xABCD type=0"
✅ "RBDS decoded: PS='WXYZ-FM' PI=ABCD"
```

### What to Look for in UI:

Navigate to **Audio Monitoring** page:
- "FM Stereo / RBDS Information" section should appear
- Shows: Station Name, PI Code, Radio Text, Program Type

## Files Changed

1. `app_core/radio/demodulation.py` - Added register reset (line 1100)
2. `VERSION` - Updated to 2.46.4
3. `docs/reference/CHANGELOG.md` - Documented fix
4. `RBDS_DIAGNOSTIC_REPORT.md` - Comprehensive diagnostic report (NEW)
5. `validate_rbds_system.py` - Validation script (NEW)

## Complete Documentation

- **Full Report**: `RBDS_DIAGNOSTIC_REPORT.md`
- **Validation**: `validate_rbds_system.py`
- **Diagnostic**: `tools/rbds_auto_diagnostic.py`

## Expected Results

After this fix:
1. RBDS synchronizes ✅
2. Blocks pass CRC checks ✅
3. Groups decode successfully ✅
4. Station names appear ✅
5. PI codes and radio text visible ✅

## If It Still Doesn't Work

Check:
1. Sample rate is ≥ 114 kHz
2. Modulation is FM or WFM (not NFM)
3. RBDS checkbox is enabled
4. Signal strength is good (strong FM signal)
5. Numba is installed: `pip install numba==0.60.0`
6. Logs show "RBDS ENABLED" message
7. Run diagnostic: `python3 tools/rbds_auto_diagnostic.py`

## Support

See detailed diagnostics in:
- `RBDS_DIAGNOSTIC_REPORT.md` - Complete diagnostic analysis
- `docs/archive/rbds-fixes/` - Historical fix documentation
- Automated diagnostic tool: `tools/rbds_auto_diagnostic.py`
