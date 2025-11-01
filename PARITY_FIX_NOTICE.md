# SAME Parity Bit Fix - October 31, 2025

## Issue Description

A critical bug was discovered and fixed in the SAME audio encoder on **October 31, 2025**. The bug caused incorrect parity bits to be encoded in SAME headers, resulting in audio files that cannot be decoded correctly.

### Technical Details

**The Bug:**
- The SAME specification (47 CFR §11.31) requires **even parity** for each character
- Each character is transmitted as: `[start bit (0)][7 data bits][parity bit][stop bit (1)]`
- Before Oct 31, the encoder incorrectly used a **hardcoded parity bit of 0**
- This only works correctly for characters with an even number of 1-bits

**Example:**
- Space character (' ') = ASCII 32 = `0100000` (binary) - has 1 one-bit (odd)
- Correct encoding: `0 0100000 1 1` (parity=1 makes total even)
- Buggy encoding:  `0 0100000 0 1` (parity=0 makes total odd) ❌

**The Fix:**
```python
# Before (incorrect):
char_bits.append(0)

# After (correct):
parity_bit = ones_count & 1
char_bits.append(parity_bit)
```

### Impact

Audio files generated **before October 31, 2025** have:
- ✗ Incorrect parity bits
- ✗ Cannot be decoded correctly by the fixed decoder
- ✗ Show malformed SAME headers with garbled characters
- ✗ Missing or corrupted location codes, timestamps, station IDs

**Example of malformed output:**
```
ZCZC-EAS-RWT-03913715-3051127-KR8MER@ -
```

Instead of properly formatted:
```
ZCZC-EAS-RWT-039137-150000+0030-3051127-KR8MER  -
```

### Resolution

1. **Delete old audio files** generated before Oct 31, 2025
2. **Regenerate EAS messages** using the web interface
3. **Verify** that new audio files decode correctly

### Cleanup Script

Run the provided cleanup script to remove old audio files:

```bash
python3 cleanup_old_audio.py
```

The script will:
- Remove database records created before Oct 31, 2025
- Delete audio files from disk created before Oct 31, 2025
- Preserve all files created after the fix

### Verification

After regeneration, test that audio files decode correctly:

```bash
python3 -c "
from app_utils.eas_decode import decode_same_audio

result = decode_same_audio('path/to/your/file.wav')
print('Decoded headers:')
for header in result.headers:
    print(f'  {header.header}')
    print(f'  Confidence: {header.confidence:.2%}')
"
```

A properly encoded and decoded header should show:
- Clear, well-formed SAME header structure
- High confidence score (>80%)
- Correct location codes separated by dashes
- Proper '+' before duration code
- 8-character station ID

### Related Commits

- `8fba7cf` - Restore dynamic SAME parity bit (Oct 31, 2025)
- `ac7f050` - Revert "Fix SAME parity bits in SAME encoder" (Oct 31, 2025)
- `1a0a36e` - Fix SAME parity bits (Oct 31, 2025)
- `217853d` - Fix SAME audio decode regression (Oct 31, 2025)

### Prevention

The fix has been validated with:
- Unit tests in `tests/test_eas_fsk.py`
- Integration tests in `tests/test_eas_decode.py`
- Parity validation in the decoder prevents future encoding bugs

All audio generated after October 31, 2025 12:00 UTC is correct and does not need regeneration.
