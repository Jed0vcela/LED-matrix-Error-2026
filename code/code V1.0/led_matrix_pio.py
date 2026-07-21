"""
16x32 LED Matrix Driver for RP2040 – PIO, 3-level grayscale
=============================================================
Pin assignments:
  Row: row_mosi=GP3  row_clk=GP2  row_latch=GP1
  Col: col_mosi=GP15 col_clk=GP14 col_latch=GP12 col_OE=GP13 (active LOW)

Grayscale model
---------------
3 brightness levels per pixel:
  0 = off
  1 = 50% brightness  (on in every other frame)
  2 = 100% brightness (on in every frame)

Implementation:
  Two framebuffers maintained internally:
    _full   — bitmask of ALL lit pixels (level 1 + level 2)
    _bright — bitmask of FULL brightness pixels (level 2 only)

  fill_fifo() alternates which buffer it sends each call:
    even calls → send _full   (level 1 + level 2 both on)
    odd calls  → send _bright (only level 2 on)

  Result:
    level 2 pixel: on in both frames → 100% duty cycle
    level 1 pixel: on in even frames only → 50% duty cycle
    level 0 pixel: off in both frames → 0%

  Frame rate is high enough (~330Hz) that 50% flicker is invisible.

PIO programs are identical to the proven working version.
SM0: col shift + col_latch + OE (set pins GP12, GP13)
SM1: row shift + row_latch      (set pin  GP1)

Ghosting prevention: SM1 called twice per row —
  first with all-1s (deselect all rows), then with real row selector.

Usage:
  from led_matrix_pio import *
  start()
  set_pixel(0, 0, 2)   # full brightness
  set_pixel(0, 1, 1)   # half brightness
  set_pixel(0, 2, 0)   # off
  show()
  while True:
      fill_fifo()
"""

import machine
import utime
import rp2
import array
from micropython import const

# ---------------------------------------------------------------------------
# Pins
# ---------------------------------------------------------------------------
ROW_MOSI  = const(3)
ROW_CLK   = const(2)
ROW_LATCH = const(1)
COL_MOSI  = const(15)
COL_CLK   = const(14)
COL_LATCH = const(12)
COL_OE    = const(13)
ROWS      = const(16)
COLS      = const(32)

_ROW_BLANK = const(0xFFFF0000)   # all rows deselected

# ---------------------------------------------------------------------------
# Back buffer — _back[row][col] = 0, 1, or 2
# ---------------------------------------------------------------------------
_back = [[0] * COLS for _ in range(ROWS)]

# Internal front buffers — rebuilt by show()
# _full[row]   = bitmask of pixels with level >= 1 (shown every frame)
# _bright[row] = bitmask of pixels with level == 2 (shown every other frame)
_full   = array.array('I', [0] * ROWS)
_bright = array.array('I', [0] * ROWS)

# Row selector words
_row_sel = array.array('I', [
    ((0xFFFF ^ (0x8000 >> i)) & 0xFFFF) << 16
    for i in range(ROWS)
])

# Which frame are we on — alternates each fill_fifo() call
_frame_toggle = 0

# ---------------------------------------------------------------------------
# Public pixel API
# ---------------------------------------------------------------------------
def set_pixel(row, col, level=2):
    """Set pixel brightness: 0=off, 1=half, 2=full."""
    if 0 <= row < ROWS and 0 <= col < COLS:
        _back[ROWS - 1 - row][col] = max(0, min(2, int(level)))

def get_pixel(row, col):
    if 0 <= row < ROWS and 0 <= col < COLS:
        return _back[ROWS - 1 - row][col]
    return 0

def clear():
    for r in range(ROWS):
        for c in range(COLS): _back[r][c] = 0

def fill(level=2):
    for r in range(ROWS):
        for c in range(COLS): _back[r][c] = level

def show():
    """
    Recompute _full and _bright from back buffer.
    Call after drawing, before fill_fifo().
    """
    for r in range(ROWS):
        row  = _back[r]
        full = 0
        brt  = 0
        for c in range(COLS):
            bit = 1 << c
            v   = row[c]
            if v >= 1: full |= bit
            if v >= 2: brt  |= bit
        _full[r]   = full
        _bright[r] = brt

# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------
def draw_hline(row, col, w, level=2):
    for c in range(col, min(col + w, COLS)):
        set_pixel(row, c, level)

def draw_vline(col, row, h, level=2):
    for r in range(row, min(row + h, ROWS)):
        set_pixel(r, col, level)

def draw_rect(row, col, h, w, level=2):
    draw_hline(row,         col, w, level)
    draw_hline(row + h - 1, col, w, level)
    draw_vline(col,         row, h, level)
    draw_vline(col + w - 1, row, h, level)

def fill_rect(row, col, h, w, level=2):
    for r in range(row, min(row + h, ROWS)):
        for c in range(col, min(col + w, COLS)):
            set_pixel(r, c, level)

def scroll_left(n=1):
    for r in range(ROWS):
        row = _back[r]
        _back[r] = row[n:] + row[:n]

def scroll_right(n=1):
    for r in range(ROWS):
        row = _back[r]
        _back[r] = row[-n:] + row[:-n]

# ---------------------------------------------------------------------------
# PIO SM0 – col shift + col_latch + OE
# set_base = GP12: bit0=col_latch, bit1=OE
#
# set(pins, 0b10) → OE=1 (blank),   col_latch=0
# set(pins, 0b11) → OE=1 (blank),   col_latch=1  (latch pulse)
# set(pins, 0b00) → OE=0 (enabled), col_latch=0
# ---------------------------------------------------------------------------
@rp2.asm_pio(
    out_init     = (rp2.PIO.OUT_LOW,),
    sideset_init = (rp2.PIO.OUT_LOW,),
    set_init     = (rp2.PIO.OUT_LOW, rp2.PIO.OUT_HIGH),  # OE starts HIGH (disabled)
    out_shiftdir = rp2.PIO.SHIFT_LEFT,
    autopull     = False,
)
def col_program():
    wrap_target()

    # Blank
    set(pins, 0b10)                         # OE=1, col_latch=0

    # Blank row: tell SM1 to shift all-1s then latch
    irq(noblock, 4)
    wait(1, irq, 5)

    # Shift 32 col bits
    pull(block)                             # stall here if FIFO empty (OE already off)
    set(x, 31)
    label("col_loop")
    out(pins, 1)            .side(0)
    jmp(x_dec, "col_loop")  .side(1)
    nop()                   .side(0)

    # Latch col
    set(pins, 0b11)                         # col_latch=1, OE=1
    set(pins, 0b10)                         # col_latch=0, OE=1

    # Real row: tell SM1 to shift row selector then latch
    irq(noblock, 4)
    wait(1, irq, 5)

    # Enable display
    set(pins, 0b00)                         # OE=0 (enabled)

    # Hold delay ~256µs: 4× faster frame rate for flicker-free grayscale
    # 8MHz clock, inner loop: jmp[7] = 8 cycles = 1µs × 32 iters = 32µs
    # outer loop: 8 × 32µs = ~256µs → frame=4ms → grayscale flip=122Hz
    set(y, 7)
    label("delay_outer")
    set(x, 31)
    label("delay_inner")
    jmp(x_dec, "delay_inner") [7]
    jmp(y_dec, "delay_outer")

    wrap()


# ---------------------------------------------------------------------------
# PIO SM1 – row shift + row_latch
# set_base = GP1 (row_latch)
# Called twice per row: once with blank word, once with real row word.
# ---------------------------------------------------------------------------
@rp2.asm_pio(
    out_init     = (rp2.PIO.OUT_LOW,),
    sideset_init = (rp2.PIO.OUT_LOW,),
    set_init     = (rp2.PIO.OUT_LOW,),
    out_shiftdir = rp2.PIO.SHIFT_LEFT,
    autopull     = False,
)
def row_program():
    wrap_target()

    wait(1, irq, 4)                         # wait for SM0, clears IRQ4

    pull(block)
    set(x, 15)
    label("row_loop")
    out(pins, 1)            .side(0)
    jmp(x_dec, "row_loop")  .side(1)
    nop()                   .side(0)

    set(pins, 1)                            # row_latch high
    set(pins, 0)                            # row_latch low

    irq(noblock, 5)                         # signal SM0: done

    wrap()


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------
_sm_col = rp2.StateMachine(
    0, col_program,
    freq         = 8_000_000,
    out_base     = machine.Pin(COL_MOSI),
    sideset_base = machine.Pin(COL_CLK),
    set_base     = machine.Pin(COL_LATCH),
)

_sm_row = rp2.StateMachine(
    1, row_program,
    freq         = 2_000_000,
    out_base     = machine.Pin(ROW_MOSI),
    sideset_base = machine.Pin(ROW_CLK),
    set_base     = machine.Pin(ROW_LATCH),
)

# ---------------------------------------------------------------------------
# Start / stop
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Core 1 display loop
# Core 1 runs _core1_loop() continuously, feeding PIO as fast as needed.
# Core 0 just calls show() when it has a new frame ready.
# ---------------------------------------------------------------------------
import _thread

_core1_running  = False
_core1_lock     = _thread.allocate_lock()
_core1_callback = None   # called between every frame, set by token ring etc.

def register_callback(fn):
    """Register a function to be called between display frames on Core 1."""
    global _core1_callback
    _core1_callback = fn

def _core1_loop():
    while _core1_running:
        fill_fifo()
        if _core1_callback:
            _core1_callback()

def start():
    global _core1_running
    _sm_col.restart()
    _sm_row.restart()
    _sm_col.active(1)
    _sm_row.active(1)
    _core1_running = True
    _thread.start_new_thread(_core1_loop, ())

def stop():
    global _core1_running
    _core1_running = False
    utime.sleep_ms(20)   # let core1 finish current fill_fifo()
    machine.Pin(COL_OE, machine.Pin.OUT, value=1)
    _sm_col.active(0)
    _sm_row.active(0)

# ---------------------------------------------------------------------------
# fill_fifo() — push one frame, alternating between _full and _bright
#
# Even call → send _full   (all pixels level>=1 lit)
# Odd call  → send _bright (only level==2 lit)
#
# SM1 is called twice per row so needs 2 words per row:
#   _ROW_BLANK  (for blank-row phase)
#   row_sel[i]  (for real-row phase)
# ---------------------------------------------------------------------------
# Grayscale cycle: 4 frames per period
#   frame 0 → _full   (level-1 + level-2 on) → level-1 gets 1/4 = 25%
#   frame 1 → _bright (level-2 only)
#   frame 2 → _bright
#   frame 3 → _bright
# Level-2 pixels: on 4/4 = 100%
# Level-1 pixels: on 1/4 = 25%
_GS_CYCLE = (_full, _bright, _bright, _bright)

def fill_fifo():
    """
    Send one complete frame from the grayscale cycle.
    4-frame cycle: _full once then _bright three times.
    Level-1 pixels = 25% duty cycle, level-2 = 100%.

    Waits for SM0 FIFO to drain before toggling to prevent
    rows from different buffers mixing in the same visual frame.
    """
    global _frame_toggle
    buf = _GS_CYCLE[_frame_toggle]
    for i in range(ROWS):
        _sm_row.put(_ROW_BLANK)
        _sm_col.put(buf[i])
        _sm_row.put(_row_sel[i])
    # Drain FIFO before advancing cycle — prevents frame mixing
    while _sm_col.tx_fifo() > 0:
        pass
    _frame_toggle = (_frame_toggle + 1) % 4

def run_frames(ms):
    """Keep display fed for ms milliseconds."""
    end = utime.ticks_add(utime.ticks_ms(), ms)
    while utime.ticks_diff(end, utime.ticks_ms()) > 0:
        fill_fifo()
    # Drain after loop so caller can safely call show() without
    # show() racing with PIO consuming old buffer data
    while _sm_col.tx_fifo() > 0:
        pass

# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    start()
    show()   # init with empty buffer

    print("3-level grayscale demo")

    # Three vertical bands: off / half / full
    print("Bands: off | half | full")
    clear()
    for r in range(ROWS):
        for c in range(COLS):
            if   c < 10:  set_pixel(r, c, 0)   # off
            elif c < 21:  set_pixel(r, c, 1)   # half
            else:         set_pixel(r, c, 2)   # full
    show()
    run_frames(4000)

    # Gradient: cols map to level 0, 1, 2, 1, 0, ...
    print("Alternating bands")
    clear()
    for r in range(ROWS):
        for c in range(COLS):
            set_pixel(r, c, [0, 1, 2][(c // 5) % 3])
    show()
    run_frames(4000)

    # Checkerboard: alternate half and full
    print("Checkerboard half/full")
    clear()
    for r in range(ROWS):
        for c in range(COLS):
            set_pixel(r, c, 1 + (r + c) % 2)   # alternates 1 and 2
    show()
    run_frames(4000)

    # Sine wave: bright peak, half brightness shoulders
    import math
    print("Sine wave with glow")
    offset = 0
    for _ in range(400):
        clear()
        for c in range(COLS):
            peak = 7.5 + 7 * math.sin((c + offset) * 0.4)
            for r in range(ROWS):
                dist = abs(r - peak)
                if   dist < 0.7: set_pixel(r, c, 2)   # bright core
                elif dist < 2.0: set_pixel(r, c, 1)   # dim halo
        show()
        offset += 1
        run_frames(20)

    stop()
    print("Done.")