"""
Photodiode reader – GP28 (ADC2)
================================
Reads analog value from photodiode every 500ms and prints to terminal.
GP28 = ADC channel 0 on RP2040.

ADC returns 0–65535 (16-bit scaled from 12-bit hardware).
Voltage = raw * 3.3 / 65535

Pull resistor options (comment/uncomment as needed):
  - No pull    : floating input, most sensitive, photodiode sets the voltage
  - Pull-up    : pin biased HIGH, photodiode pulls it down when lit
  - Pull-down  : pin biased LOW, photodiode pushes it up when lit

For a bare photodiode with no external resistor:
  Pull-down is usually best — dark = 0V, light = higher voltage.
  But experiment — depends on your circuit.
"""

import machine
import utime

# ---------------------------------------------------------------------------
# Configuration — change PULL to try different modes
# Options: None, machine.Pin.PULL_UP, machine.Pin.PULL_DOWN
# ---------------------------------------------------------------------------
PULL = None   # start with no pull, photodiode + external resistor assumed

INTERVAL_MS = 500

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
# Configure the pin pull (ADC pin must be set up as Pin first for pull config)
_pin = machine.Pin(28, machine.Pin.IN, PULL)

# Then create ADC on the same pin — this takes over the pin for analog reading
_adc = machine.ADC(machine.Pin(28))

def read_raw():
    """Return raw 16-bit ADC value (0–65535)."""
    return _adc.read_u16()

def read_voltage():
    """Return voltage in volts (0.0–3.3V)."""
    return read_raw() * 3.3 / 65535

def read_percent():
    """Return light level as 0–100%."""
    return read_raw() / 655.35

# ---------------------------------------------------------------------------
# Continuous reader
# ---------------------------------------------------------------------------
def run(interval_ms=INTERVAL_MS, show_voltage=True, show_percent=True):
    """
    Print ADC readings every interval_ms.
    Ctrl-C to stop.
    """
    pull_name = {None: "none", machine.Pin.PULL_UP: "pull-up",
                 machine.Pin.PULL_DOWN: "pull-down"}.get(PULL, "unknown")
    print(f"Photodiode on GP28 | pull={pull_name} | interval={interval_ms}ms")
    print(f"{'raw':>7}  {'voltage':>8}  {'percent':>8}")
    print("-" * 30)

    try:
        while True:
            raw     = read_raw()
            voltage = raw * 3.3 / 65535
            percent = raw / 655.35
            parts   = [f"{raw:>7}"]
            if show_voltage: parts.append(f"  {voltage:>6.4f}V")
            if show_percent: parts.append(f"  {percent:>6.2f}%")
            print("".join(parts))
            utime.sleep_ms(interval_ms)
    except KeyboardInterrupt:
        print("\nStopped.")

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run()
