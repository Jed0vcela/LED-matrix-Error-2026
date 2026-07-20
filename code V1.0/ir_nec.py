"""
NEC IR Receiver + Matrix Current Control
=========================================
Hardware (new HW version):
  IR-RX  → GP0   (active LOW, pulled HIGH by receiver)
  IR-TX  → GP5   (PIO1 SM0, future use)
  Iset1  → GP7   (LOW = lower current, lowest authority)
  Iset2  → GP10  (LOW = lower current, medium authority)
  Iset3  → GP11  (LOW = lower current, highest authority)
  LED    → GP25  (onboard LED, mirrors IR-RX for debug)

Iset authority:
  All three pins combine to set LED current sink level.
  Iset3 has highest authority, Iset1 lowest.
  All HIGH = maximum brightness.
  Levels 0-7 (3-bit, Iset3=MSB, Iset1=LSB):
    0b000 = 0 = minimum current (all LOW)
    0b111 = 7 = maximum current (all HIGH)
"""

import machine
import utime
import _thread
import array
from micropython import const

IR_RX_PIN = const(0)
LED_PIN   = const(25)

_LEADER_LOW_MIN  = const(8000)
_LEADER_LOW_MAX  = const(10500)
_LEADER_HIGH_MIN = const(3000)
_LEADER_HIGH_MAX = const(5500)
_REPEAT_HIGH_MIN = const(1400)
_REPEAT_HIGH_MAX = const(2800)
_BIT_LOW_MIN     = const(200)
_BIT_LOW_MAX     = const(1000)
_BIT_ONE_MIN     = const(1000)
_MAX_EDGES       = const(68)
_FRAME_GAP_US    = const(10000)


class NEC:
    def __init__(self, pin_num=IR_RX_PIN, callback=None, debug=False):
        self._cb    = callback
        self._debug = debug
        self._queue = []

        self._times  = array.array('i', [0] * _MAX_EDGES)
        self._levels = array.array('i', [0] * _MAX_EDGES)
        self._count  = 0
        self._last_edge_us = 0
        self._armed  = True

        self._last_addr = 0
        self._last_cmd  = 0

        self._led = machine.Pin(LED_PIN, machine.Pin.OUT, value=0)
        self._lock = _thread.allocate_lock()

        self._pin = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_UP)
        self._pin.irq(
            trigger = machine.Pin.IRQ_FALLING | machine.Pin.IRQ_RISING,
            handler = self._edge_irq,
            hard    = True,
        )

    def _edge_irq(self, pin):
        now   = utime.ticks_us()
        level = pin.value()
        self._led.value(0 if level else 1)
        if not self._armed:
            return
        if self._count > 0:
            if utime.ticks_diff(now, self._last_edge_us) > _FRAME_GAP_US:
                self._count = 0
        if self._count < _MAX_EDGES:
            self._times[self._count]  = now
            self._levels[self._count] = level
            self._count += 1
        self._last_edge_us = now

    def _decode(self):
        n  = self._count
        t  = self._times
        lv = self._levels
        if n < 4:
            return None

        start = -1
        for i in range(n):
            if lv[i] == 0:
                start = i
                break
        if start < 0 or start + 2 >= n:
            return None

        leader_low  = utime.ticks_diff(t[start + 1], t[start])
        if self._debug: print(f"decode: n={n} leader_low={leader_low}")
        if not (_LEADER_LOW_MIN < leader_low < _LEADER_LOW_MAX):
            return None

        leader_high = utime.ticks_diff(t[start + 2], t[start + 1])
        if self._debug: print(f"  leader_high={leader_high}")

        if _REPEAT_HIGH_MIN < leader_high < _REPEAT_HIGH_MAX:
            return ('repeat',)
        if not (_LEADER_HIGH_MIN < leader_high < _LEADER_HIGH_MAX):
            return None

        bits = 0
        ei   = start + 2
        for i in range(32):
            fe = ei + i * 2
            re = ei + i * 2 + 1
            ne = ei + i * 2 + 2
            if ne >= n:
                return None
            bit_low  = utime.ticks_diff(t[re], t[fe])
            if not (_BIT_LOW_MIN < bit_low < _BIT_LOW_MAX):
                return None
            bit_high = utime.ticks_diff(t[ne], t[re])
            if bit_high >= _BIT_ONE_MIN:
                bits |= (1 << i)

        addr  = (bits >>  0) & 0xFF
        naddr = (bits >>  8) & 0xFF
        cmd   = (bits >> 16) & 0xFF
        ncmd  = (bits >> 24) & 0xFF

        if self._debug:
            print(f"  raw: addr=0x{addr:02X} ~addr=0x{naddr:02X} cmd=0x{cmd:02X} ~cmd=0x{ncmd:02X}")

        if (addr ^ naddr) != 0xFF or (cmd ^ ncmd) != 0xFF:
            return None

        return (addr, cmd, False)

    def update(self):
        if self._count < 4:
            return
        if utime.ticks_diff(utime.ticks_us(), self._last_edge_us) < _FRAME_GAP_US:
            return

        self._armed = False
        result = self._decode()
        self._count = 0
        self._armed = True

        if result is None:
            return

        if result[0] == 'repeat':
            addr, cmd, repeat = self._last_addr, self._last_cmd, True
        else:
            addr, cmd, repeat = result
            self._last_addr = addr
            self._last_cmd  = cmd

        if self._cb:
            self._cb(addr, cmd, repeat)
        else:
            with self._lock:
                if len(self._queue) < 16:
                    self._queue.append((addr, cmd, repeat))

    def poll(self):
        self.update()
        with self._lock:
            return self._queue.pop(0) if self._queue else None

    def set_callback(self, cb):
        self._cb = cb

    def deinit(self):
        self._pin.irq(handler=None)
        self._led.value(0)


# ---------------------------------------------------------------------------
# Matrix current control — 3 Iset pins
# Iset3=MSB, Iset1=LSB → 8 levels (0=min, 7=max)
# ---------------------------------------------------------------------------
class MatrixCurrent:
    """
    Controls LED matrix current via 3 Iset pins.
    Level 0 (0b000) = minimum current (all pins LOW)
    Level 7 (0b111) = maximum current (all pins HIGH)
    Iset3 has highest authority, Iset1 lowest.
    """
    ISET1 = const(7)
    ISET2 = const(10)
    ISET3 = const(11)

    def __init__(self):
        self._pins = [
            machine.Pin(self.ISET1, machine.Pin.OUT, value=1),
            machine.Pin(self.ISET2, machine.Pin.OUT, value=1),
            machine.Pin(self.ISET3, machine.Pin.OUT, value=1),
        ]
        self._level = 7   # start at max

    def set_level(self, level):
        """Set brightness level 0-7. 7=max, 0=min."""
        level = max(0, min(7, int(level)))
        self._level = level
        self._pins[0].value((level >> 0) & 1)   # Iset1 = bit 0
        self._pins[1].value((level >> 1) & 1)   # Iset2 = bit 1
        self._pins[2].value((level >> 2) & 1)   # Iset3 = bit 2

    def get_level(self):
        return self._level

    def step_up(self):
        self.set_level(self._level + 1)
        return self._level

    def step_down(self):
        self.set_level(self._level - 1)
        return self._level

    def toggle(self):
        """Toggle between min and max (for simple 2-state control)."""
        self.set_level(0 if self._level > 0 else 7)
        return self._level


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("NEC IR decoder — GP0, debug mode")
    print("Onboard LED (GP25) mirrors IR receiver.")
    print("Ctrl-C to stop.\n")

    current = MatrixCurrent()

    def on_ir(addr, cmd, repeat):
        if not repeat:
            print(f">>> addr=0x{addr:02X}  cmd=0x{cmd:02X}")
        else:
            print(f">>> REPEAT")

    ir = NEC(pin_num=IR_RX_PIN, callback=on_ir, debug=True)

    try:
        while True:
            ir.update()
            utime.sleep_ms(1)
    except KeyboardInterrupt:
        ir.deinit()
        print("Stopped.")