"""
Incremental Encoder Driver for RP2040
======================================
Hardware:
  Encoder A  → GP6
  Encoder B  → GP4
  Encoder SW → GP22 (push button, active LOW with PULL_UP)

Decoding:
  Uses both edges of A and B (quadrature decoding) for 4x resolution.
  IRQ on both A and B, both edges.

  Quadrature state table:
    Previous | Current | Direction
    AB       | AB      |
    00       | 01      | +1 (CW)
    01       | 11      | +1
    11       | 10      | +1
    10       | 00      | +1
    00       | 10      | -1 (CCW)
    10       | 11      | -1
    11       | 01      | -1
    01       | 00      | -1
    same/invalid → 0 (noise/bounce)

API:
  enc = Encoder()
  enc.value          # current position (int, can be negative)
  enc.reset()        # set position to 0
  enc.delta()        # return change since last delta() call, reset delta
  enc.pressed        # True if button currently pressed
  enc.was_pressed()  # True if button was pressed since last call (clears flag)
  enc.set_range(min, max, wrap=False)  # clamp or wrap position
"""

import machine
import utime
from micropython import const

ENC_A  = const(6)
ENC_B  = const(4)
ENC_SW = const(22)

# Quadrature decode table: index = (prev_ab << 2) | curr_ab
# +1 = CW, -1 = CCW, 0 = invalid/no move
_QEM = [
    0, +1, -1,  0,
   -1,  0,  0, +1,
   +1,  0,  0, -1,
    0, -1, +1,  0,
]

class Encoder:
    def __init__(self,
                 pin_a=ENC_A,
                 pin_b=ENC_B,
                 pin_sw=ENC_SW,
                 min_val=None,
                 max_val=None,
                 wrap=False):

        # Swap A/B to correct rotation direction
        self._pin_a = machine.Pin(pin_b, machine.Pin.IN, machine.Pin.PULL_UP)
        self._pin_b = machine.Pin(pin_a, machine.Pin.IN, machine.Pin.PULL_UP)
        self._pin_sw = machine.Pin(pin_sw, machine.Pin.IN, machine.Pin.PULL_UP)

        self._value      = 0
        self._delta      = 0
        self._raw_steps  = 0    # accumulates raw quadrature steps
        self._prev_ab    = (self._pin_a.value() << 1) | self._pin_b.value()

        self._min  = min_val
        self._max  = max_val
        self._wrap = wrap

        self._btn_pressed   = False   # latched flag for was_pressed()
        self._btn_last      = self._pin_sw.value()

        # IRQ on both edges of A and B
        self._pin_a.irq(
            trigger = machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
            handler = self._enc_irq,
            hard    = True,
        )
        self._pin_b.irq(
            trigger = machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
            handler = self._enc_irq,
            hard    = True,
        )
        # Button IRQ — falling edge = press
        self._pin_sw.irq(
            trigger = machine.Pin.IRQ_FALLING,
            handler = self._sw_irq,
            hard    = True,
        )

    def _enc_irq(self, pin):
        curr_ab = (self._pin_a.value() << 1) | self._pin_b.value()
        idx     = (self._prev_ab << 2) | curr_ab
        step    = _QEM[idx]
        if step:
            self._raw_steps += step
            # 4 raw steps = 1 mechanical detent
            if abs(self._raw_steps) >= 4:
                detent = self._raw_steps // 4
                self._raw_steps = self._raw_steps % 4
                new_val = self._value + detent
                # Apply clamp / wrap
                if self._min is not None and self._max is not None:
                    if self._wrap:
                        span = self._max - self._min + 1
                        new_val = self._min + (new_val - self._min) % span
                    else:
                        new_val = max(self._min, min(self._max, new_val))
                self._value  = new_val
                self._delta += detent
        self._prev_ab = curr_ab

    def _sw_irq(self, pin):
        self._btn_pressed = True

    # --- Public API ---

    @property
    def value(self):
        """Current encoder position."""
        return self._value

    @value.setter
    def value(self, v):
        self._value = v
        self._delta = 0

    def reset(self):
        """Reset position to 0."""
        self._value = 0
        self._delta = 0

    def delta(self):
        """Return accumulated change since last call, then reset to 0."""
        d = self._delta
        self._delta = 0
        return d

    @property
    def pressed(self):
        """True if button is currently held down."""
        return self._pin_sw.value() == 0

    def was_pressed(self):
        """True if button was pressed since last call. Clears the flag."""
        if self._btn_pressed:
            self._btn_pressed = False
            return True
        return False

    def set_range(self, min_val, max_val, wrap=False):
        """Clamp or wrap encoder value to [min_val, max_val]."""
        self._min  = min_val
        self._max  = max_val
        self._wrap = wrap
        # Clamp current value into range
        if wrap:
            span = max_val - min_val + 1
            self._value = min_val + (self._value - min_val) % span
        else:
            self._value = max(min_val, min(max_val, self._value))

    def deinit(self):
        self._pin_a.irq(handler=None)
        self._pin_b.irq(handler=None)
        self._pin_sw.irq(handler=None)


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Encoder test — GP6=A, GP4=B, GP22=SW")
    print("Turn encoder and press button. Ctrl-C to stop.\n")

    enc = Encoder()
    last_val = enc.value

    try:
        while True:
            v = enc.value
            if v != last_val:
                d = enc.delta()
                print(f"  position={v:4d}  delta={d:+d}")
                last_val = v

            if enc.was_pressed():
                print(f"  BUTTON PRESSED  (position={enc.value})")
                enc.reset()
                last_val = 0
                print(f"  position reset to 0")

            utime.sleep_ms(10)

    except KeyboardInterrupt:
        enc.deinit()
        print("\nStopped.")