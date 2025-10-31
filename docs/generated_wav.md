# Investigating `generated.wav`

The legacy `generated.wav` sample that lives at the repository root was produced
before the SAME encoder appended the parity bit that consumer equipment expects
for each 7-bit ASCII character. Because the parity bit was hard-coded to `0`,
any character whose ASCII representation has an odd number of `1` bits (for
example, `Z` or `C`) would wind up with odd parity once transmitted. SAME
receivers treat that as a framing error, so the decoder in `app_utils/eas_decode`
can only recover garbage control characters when pointed at the legacy file.

```python
from app_utils.eas_decode import decode_same_audio
result = decode_same_audio("generated.wav")
print(result.raw_text)
```

Running the snippet above yields output similar to:

```
ZCZC\x04\x04M-RWT-039137\x000\x00\x005+\x02"\n\x12\x02Bj-I8MER\x00 -\r
```

Those spurious control characters are the direct result of the missing parity
bit. The fix in `app_utils/eas_fsk.encode_same_bits` now computes the even parity
bit for every ASCII character before appending it to the outgoing frame, which
lets downstream decoders reconstruct the intended header (`ZCZC-M-RWT-039137-…`).

To regenerate a clean SAME sample with the corrected framing, you can run:

```python
from app_utils.eas_fsk import (
    SAME_BAUD,
    SAME_MARK_FREQ,
    SAME_SPACE_FREQ,
    encode_same_bits,
    generate_fsk_samples,
)
import wave, struct

header = "ZCZC-EAS-RWT-039137+0030-1231512-KWNP/NWS-"
samples = generate_fsk_samples(
    encode_same_bits(header, include_preamble=True),
    sample_rate=22050,
    bit_rate=float(SAME_BAUD),
    mark_freq=SAME_MARK_FREQ,
    space_freq=SAME_SPACE_FREQ,
    amplitude=20000,
)

with wave.open("regenerated.wav", "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(22050)
    wav.writeframes(b"".join(struct.pack("<h", s) for s in samples))
```

The resulting audio decodes cleanly with `decode_same_audio` and standard SAME
monitors, confirming that the original `generated.wav` was indeed invalid while
the encoder fix resolves the framing issue.
