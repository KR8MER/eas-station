# Performance Optimization Guide

**EAS Station - Quick Reference for Performance Analysis**

## Current Performance Status ✅

**System performs EXCELLENTLY on Raspberry Pi 3B+:**
- EAS Decoder: <5% CPU
- Total System: <15% CPU
- Latency: <200ms end-to-end
- Status: Production-ready with significant headroom

## Should I Convert Python to C?

**❌ NO** - See detailed analysis in [PYTHON_TO_C_ANALYSIS.md](./PYTHON_TO_C_ANALYSIS.md)

**Reasons:**
1. NumPy already uses C/BLAS for computational hotspots
2. Current performance exceeds all targets
3. High maintenance cost for minimal gain (0.5-1% CPU improvement)
4. Better alternatives available (Cython, Numba, profiling)

## Performance Optimization Checklist

### Before You Optimize

- [ ] **Profile first** - Use py-spy or cProfile to find actual bottlenecks
- [ ] **Measure current performance** - Establish baseline metrics
- [ ] **Identify target** - Define specific performance goal
- [ ] **Consider alternatives** - Can better libraries solve the problem?

### Optimization Strategies (In Order)

#### 1. Use Optimized Libraries (Easiest) ⭐

```python
# Already done in EAS Station:
from app_utils.optimized_parsing import json_loads, json_dumps  # Uses orjson
import numpy as np  # Uses optimized BLAS

# Consider:
import scipy.signal  # For advanced DSP
import numba  # For JIT compilation
```

#### 2. Profile and Find Hotspots

```bash
# Install profiling tools
pip install py-spy memray

# Profile CPU usage
py-spy record -o profile.svg --pid <PID>

# Profile memory
memray run --live python eas_service.py

# Analyze results
py-spy top --pid <PID>
```

#### 3. Vectorize with NumPy

```python
# Bad: Python loops
result = []
for i in range(len(data)):
    result.append(data[i] * coefficient)

# Good: NumPy vectorization
result = data * coefficient  # 10-100x faster
```

#### 4. Use Numba JIT Compilation

```python
from numba import jit

@jit(nopython=True)
def fast_function(x, y):
    result = 0.0
    for i in range(len(x)):
        result += x[i] * y[i]
    return result
```

**Benefits**: 10-100x speedup, no code changes, automatic optimization

#### 5. Selective Cython Optimization

```python
# For specific hotspots after profiling
# streaming_same_decoder.pyx
cimport numpy as cnp

cpdef double correlation(cnp.ndarray[cnp.float32_t] window, 
                        cnp.ndarray[cnp.float32_t] coeffs):
    cdef int i
    cdef double result = 0.0
    for i in range(window.shape[0]):
        result += window[i] * coeffs[i]
    return result
```

**Benefits**: 2-10x speedup, keep Python interface, gradual migration

#### 6. Hardware Acceleration (Last Resort)

```python
# Ensure NumPy uses OpenBLAS/MKL
import numpy as np
np.show_config()  # Check BLAS configuration

# For Raspberry Pi: ARM NEON automatically used by NumPy
# No code changes needed if NumPy built correctly
```

## Module-Specific Optimization Notes

### StreamingSAMEDecoder

**Current**: <5% CPU (excellent)  
**Hotspot**: Line 244-251 (4 dot products)  
**Already Optimal**: NumPy dot() uses C/BLAS  
**If Needed**: Consider Numba JIT or Cython

### AudioRingBuffer

**Current**: <1% CPU (excellent)  
**Architecture**: Lock-free, atomic operations  
**Already Optimal**: Near-perfect design  
**No Action**: Don't touch what works

### Tone Detection

**Current**: <2% CPU (excellent)  
**Algorithm**: Goertzel (optimal for single-frequency)  
**Infrequent**: Only during alert windows  
**No Action**: Not worth optimizing

### CAP Poller

**Current**: <1% CPU (excellent)  
**I/O Bound**: Network and database dominant  
**Already Optimal**: Uses orjson/lxml  
**No Action**: I/O can't be optimized with C

## Performance Monitoring

### Key Metrics to Track

```python
# CPU Usage
import psutil
cpu_percent = psutil.cpu_percent(interval=1)

# Memory Usage
memory_info = psutil.virtual_memory()

# Real-time Latency
import time
start = time.perf_counter()
# ... operation ...
latency = time.perf_counter() - start
```

### Alerting Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| EAS Decoder CPU | >10% | >20% |
| Total System CPU | >50% | >80% |
| Latency | >500ms | >1000ms |
| Memory | >80% | >90% |

## Common Performance Anti-Patterns

### ❌ Don't Do This

```python
# Anti-pattern 1: Python loops on NumPy arrays
for i in range(len(array)):
    array[i] = array[i] * 2

# Anti-pattern 2: Repeated small operations
for sample in audio_stream:
    process_single_sample(sample)  # Python function call overhead

# Anti-pattern 3: String concatenation in loops
result = ""
for item in items:
    result += str(item)  # O(n²) complexity

# Anti-pattern 4: Premature optimization
# Optimizing code that runs once per hour
```

### ✅ Do This Instead

```python
# Good 1: Vectorized operations
array *= 2

# Good 2: Batch processing
process_batch(audio_stream)

# Good 3: Use join
result = "".join(str(item) for item in items)

# Good 4: Profile first
# Optimize code that runs 1000s of times per second
```

## Hardware Considerations

### Raspberry Pi Performance Tiers

| Model | CPU | Performance | Recommendation |
|-------|-----|-------------|----------------|
| Pi 3B+ | 4-core 1.4GHz | Good (current baseline) | ✅ Supported |
| Pi 4 | 4-core 1.5-1.8GHz | Better | ✅ Recommended |
| Pi 5 | 4-core 2.4GHz | Best | ✅ Future-proof |

### When to Upgrade Hardware

- Current CPU usage >80% sustained
- Latency >1000ms regularly
- Unable to add new features due to CPU constraints
- Cheaper than development time to optimize

## Quick Decision Tree

```
Need better performance?
│
├─ Is current performance <80% of target?
│  └─ NO → Don't optimize (you're fine!)
│  
├─ YES → Profile with py-spy
│  │
│  ├─ Hotspot in library code (NumPy, etc)?
│  │  └─ Check if better library exists
│  │
│  ├─ Hotspot in your code?
│  │  ├─ Can vectorize with NumPy? → Do it
│  │  ├─ Pure numerical code? → Try Numba
│  │  └─ Complex algorithm? → Consider Cython
│  │
│  └─ I/O bound?
│     └─ Can't optimize with code changes
│        Consider caching, async I/O, or better hardware
```

## Resources

### Documentation
- [Python to C Analysis](./PYTHON_TO_C_ANALYSIS.md) - Full analysis
- [EAS Decoding Summary](../architecture/EAS_DECODING_SUMMARY.md) - Architecture details
- [System Architecture](../architecture/SYSTEM_ARCHITECTURE.md) - Overall design

### External Resources
- [NumPy Performance](https://numpy.org/doc/stable/user/c-info.html)
- [Numba Documentation](https://numba.pydata.org/)
- [Cython Tutorial](https://cython.readthedocs.io/)
- [py-spy Profiler](https://github.com/benfred/py-spy)

## Summary

**Default Answer to "Should I Optimize?"**

**NO** - Current performance is excellent. Only optimize if:
1. Profiling shows actual bottleneck
2. Performance target not met
3. User-visible impact (latency, dropped audio)
4. Better library/algorithm not available

**Remember**: Premature optimization is the root of all evil. Profile first, optimize only what matters.

---

*Last Updated: December 20, 2025 - Version 2.43.0*
