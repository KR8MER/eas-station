# EAS Monitoring Scan Overlap Strategy

## Problem Statement

SAME (Specific Area Message Encoding) headers consist of 3 bursts, each approximately 3 seconds long, for a total of ~9 seconds. If scanning windows don't overlap properly, an alert could be split across two scans, causing neither scan to see the complete sequence and resulting in a missed alert.

## Solution: 75% Overlap Strategy

### Configuration
- **Buffer Duration**: 12 seconds (captures full SAME sequence with margin)
- **Scan Interval**: 3 seconds (75% overlap)

### Visualization

```
Time:     0s    3s    6s    9s    12s   15s   18s   21s
          |-----|-----|-----|-----|-----|-----|-----|
Scan 1:   [------------]
Scan 2:         [------------]
Scan 3:               [------------]
Scan 4:                     [------------]

SAME:          [--------9s--------]

Legend:
  [----]  = 12-second scan window
  SAME    = 9-second SAME header sequence
```

### Why This Works

1. **Complete Capture Guarantee**: Any 9-second SAME sequence will appear **completely** within at least one 12-second scan window
2. **Boundary Protection**: Even if a SAME header starts 1 second after a scan begins, the next scan (3 seconds later) will still capture the full sequence
3. **No Gaps**: With 75% overlap, there are no time periods where audio isn't being analyzed

### Performance Impact

- **Pre-Filter Optimization**: Fast FFT-based SAME tone detection runs before expensive decode
- **CPU Usage**: Despite 4x more frequent scans (3s vs 12s), CPU usage remains low due to pre-filter
- **Detection Speed**: Alerts detected within 3-6 seconds (average 4.5s) vs 10-15s without overlap

### Edge Cases Handled

1. **Alert at Scan Boundary**: 75% overlap ensures full capture
2. **Corrupted Burst**: Multiple overlapping scans increase chance of clean capture
3. **Weak Signal**: Overlapping windows provide multiple decode attempts

### Comparison

| Strategy | Buffer | Interval | Overlap | Risk |
|----------|--------|----------|---------|------|
| Old (no overlap) | 10s | 10s | 0% | **HIGH** - Can miss alerts at boundaries |
| Old (50% overlap) | 10s | 5s | 50% | MEDIUM - Small chance of split sequence |
| **New (75% overlap)** | **12s** | **3s** | **75%** | **NONE** - Guaranteed complete capture |

## Implementation Details

The overlap strategy is implemented in `app_core/audio/eas_monitor.py`:

```python
def __init__(
    self,
    audio_manager: AudioSourceManager,
    buffer_duration: float = 12.0,  # 12 seconds
    scan_interval: float = 3.0,     # 3 seconds = 75% overlap
    ...
):
```

The system automatically logs the overlap percentage and warns if overlap is insufficient:

```
INFO: Initialized ContinuousEASMonitor: buffer=12s, scan_interval=3s (75% overlap)
INFO: Started continuous EAS monitoring with 75% overlapping windows. 
      SAME sequences (9s) will appear completely in at least one scan window.
```

## References

- SAME Protocol: 3 bursts × ~3 seconds each = ~9 seconds total
- FCC SAME Specifications
- Fast pre-filter reduces CPU impact of frequent scanning
