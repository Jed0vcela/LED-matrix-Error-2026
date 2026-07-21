"""
Fast ADC sampler – GP28
========================
Collects N samples as fast as possible (or at fixed interval),
then prints them all to terminal after capture is complete.

Sampling is done in a tight loop with pre-allocated buffer —
no allocation, no print, no interrupts during capture.
"""

import machine
import utime
import array

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
NUM_SAMPLES  = 1000
INTERVAL_US  = 1000    # microseconds between samples (1000 = 1ms)
                       # set to 0 for maximum possible sample rate (~500kHz)

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
_adc = machine.ADC(machine.Pin(28))

# Pre-allocate buffers — no heap allocation during sampling
_samples    = array.array('H', [0] * NUM_SAMPLES)   # uint16, raw ADC values
_timestamps = array.array('I', [0] * NUM_SAMPLES)   # uint32, µs timestamps

# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------
def capture(num=NUM_SAMPLES, interval_us=INTERVAL_US):
    """
    Capture `num` ADC samples into pre-allocated buffer.
    Returns actual number of samples taken.
    Blocks for num * interval_us microseconds.
    """
    adc      = _adc
    samples  = _samples
    times    = _timestamps
    n        = min(num, NUM_SAMPLES)
    read     = adc.read_u16
    ticks_us = utime.ticks_us

    if interval_us > 0:
        # Fixed interval sampling
        t_next = ticks_us()
        for i in range(n):
            # Busy-wait until next sample time
            while utime.ticks_diff(ticks_us(), t_next) < 0:
                pass
            times[i]   = ticks_us()
            samples[i] = read()
            t_next = utime.ticks_add(t_next, interval_us)
    else:
        # Maximum rate — just hammer the ADC
        for i in range(n):
            times[i]   = ticks_us()
            samples[i] = read()

    return n

# ---------------------------------------------------------------------------
# Print
# ---------------------------------------------------------------------------
def print_samples(n=NUM_SAMPLES, show_time=True, show_voltage=False):
    """Print captured samples to terminal."""
    print(f"# samples={n}  interval_us={INTERVAL_US}")
    if show_time and show_voltage:
        print("# index, time_us, raw, voltage")
    elif show_time:
        print("# index, time_us, raw")
    else:
        print("# index, raw")

    t0 = _timestamps[0]
    for i in range(n):
        t  = utime.ticks_diff(_timestamps[i], t0)
        raw = _samples[i]
        if show_time and show_voltage:
            v = raw * 3.3 / 65535
            print(f"{i},{t},{raw},{v:.4f}")
        elif show_time:
            print(f"{i},{t},{raw}")
        else:
            print(f"{i},{raw}")

def print_stats(n=NUM_SAMPLES):
    """Print min/max/avg of captured samples."""
    mn = _samples[0]
    mx = _samples[0]
    s  = 0
    for i in range(n):
        v = _samples[i]
        if v < mn: mn = v
        if v > mx: mx = v
        s += v
    avg = s // n
    t_total = utime.ticks_diff(_timestamps[n-1], _timestamps[0])
    actual_rate = (n - 1) * 1_000_000 // t_total if t_total > 0 else 0
    print(f"# min={mn}  max={mx}  avg={avg}  range={mx-mn}")
    print(f"# total_time={t_total}µs  actual_rate={actual_rate}Hz")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"Capturing {NUM_SAMPLES} samples at {INTERVAL_US}µs interval...")
    n = capture()
    print(f"Done. Printing...")
    print_stats(n)
    print_samples(n, show_time=True, show_voltage=False)
    print("# END")
