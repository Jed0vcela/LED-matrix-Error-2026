"""
Token Ring – UART multiplayer for RP2040
=========================================
Hardware:
  TX -> GP8  (UART1)
  RX -> GP9  (UART1)

Ring wiring:
  Pico1 GP8 -> Pico2 GP9
  Pico2 GP8 -> Pico3 GP9
  PicoN GP8 -> Pico1 GP9
  All GNDs connected.

Packet format (11 bytes):
  [0]    0xAA        sync1
  [1]    0x55        sync2
  [2]    ORIGIN      node id (last byte of unique_id)
  [3]    HOP_COUNT   incremented by each forwarding node
  [4]    SEQ         sequence number
  [5]    FLAGS       reserved
  [6]    BUTTONS     bit0=fire1 bit1=right bit2=left bit3=down bit4=up bit5=fire2
  [7:9]  PAYLOAD     reserved
  [10]   CRC         XOR of bytes [2:10]

Heartbeat:
  Each node sends a plain text line every heartbeat_ms (default 1000ms):
  "HB <id_hex> <uptime_s> mem=<free> ring=<size> lat=<ms> tx=<n> rx=<n> fwd=<n> crc_err=<n>"
  Heartbeat is NOT a ring packet — it is always sent regardless of ring state.
  Received heartbeat lines are printed with "<<< " prefix.

Usage (integrated with display):
  from token_ring import TokenRing
  ring = TokenRing()
  ring.start()              # registers with led_matrix_pio core1 callback
  ring.send_buttons(byte)   # call from main loop
  ring.get_state()          # returns {node_id: buttons_byte}
  ring.get_info()           # returns (ring_size, latency_ms)

Standalone test:
  Run this file directly — steps through UART test, packet test, full loop.
  Set ring.debug = True to see every TX/RX/FWD event.
"""

import machine
import utime
from micropython import const

BAUD_RATE = const(115200)
TX_PIN    = const(8)
RX_PIN    = const(9)
PKT_LEN   = const(11)
SYNC1     = const(0xAA)
SYNC2     = const(0x55)

BTN_FIRE1 = const(1 << 0)
BTN_RIGHT = const(1 << 1)
BTN_LEFT  = const(1 << 2)
BTN_DOWN  = const(1 << 3)
BTN_UP    = const(1 << 4)
BTN_FIRE2 = const(1 << 5)

def _node_id():
    return machine.unique_id()[-1]

def _crc(buf):
    c = 0
    for i in range(2, 10):
        c ^= buf[i]
    return c


class TokenRing:

    def __init__(self):
        self._id   = _node_id()
        self._seq  = 0
        self._uart = machine.UART(
            1,
            baudrate = BAUD_RATE,
            tx       = machine.Pin(TX_PIN),
            rx       = machine.Pin(RX_PIN),
            bits=8, parity=None, stop=1,
            timeout=0,
        )

        # RX state machine
        # states: 0=wait sync1  1=wait sync2  2=data  10=heartbeat line
        self._rx_buf   = bytearray(PKT_LEN)
        self._rx_idx   = 0
        self._rx_state = 0
        self._hb_buf   = bytearray()

        # Shared state
        self._remote_buttons = {}
        self._my_buttons     = 0

        # Ring stats
        self._ring_size   = 0
        self._latency_ms  = 0
        self._sent_time   = {}

        # Packet counters
        self._pkts_sent      = 0
        self._pkts_returned  = 0
        self._pkts_forwarded = 0
        self._pkts_crc_fail  = 0

        # Timing
        self._boot_ms        = utime.ticks_ms()
        self._last_inject    = utime.ticks_ms()
        self._last_heartbeat = utime.ticks_ms()
        self._inject_ms      = 100
        self.heartbeat_ms    = 1000

        self.debug = False

        print("TokenRing id=0x" + "{:02X}".format(self._id)
              + " TX=GP" + str(TX_PIN) + " RX=GP" + str(RX_PIN))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self):
        """Register with led_matrix_pio Core 1 callback."""
        from led_matrix_pio import register_callback
        register_callback(self._tick)
        print("TokenRing: running on Core 1")

    def stop(self):
        from led_matrix_pio import register_callback
        register_callback(None)

    def send_buttons(self, buttons_byte):
        self._my_buttons = buttons_byte & 0xFF

    def get_state(self):
        return dict(self._remote_buttons)

    def get_info(self):
        return (self._ring_size, self._latency_ms)

    def node_id(self):
        return self._id

    @staticmethod
    def buttons_byte(fire1, right, left, down, up, fire2):
        b = 0
        if fire1: b |= BTN_FIRE1
        if right: b |= BTN_RIGHT
        if left:  b |= BTN_LEFT
        if down:  b |= BTN_DOWN
        if up:    b |= BTN_UP
        if fire2: b |= BTN_FIRE2
        return b

    @staticmethod
    def unpack_buttons(byte):
        return {
            'fire1': bool(byte & BTN_FIRE1),
            'right': bool(byte & BTN_RIGHT),
            'left':  bool(byte & BTN_LEFT),
            'down':  bool(byte & BTN_DOWN),
            'up':    bool(byte & BTN_UP),
            'fire2': bool(byte & BTN_FIRE2),
        }

    # ------------------------------------------------------------------
    # Core 1 tick
    # ------------------------------------------------------------------

    def _tick(self):
        now = utime.ticks_ms()

        # Heartbeat — always sent, independent of ring state
        if utime.ticks_diff(now, self._last_heartbeat) >= self.heartbeat_ms:
            self._last_heartbeat = now
            self._send_heartbeat()

        # Ring packet inject
        if utime.ticks_diff(now, self._last_inject) >= self._inject_ms:
            self._last_inject = now
            self._inject()

        # Drain RX
        while self._uart.any():
            b = self._uart.read(1)[0]
            self._rx_byte(b)

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def _send_heartbeat(self):
        try:
            import gc
            free = gc.mem_free()
        except Exception:
            free = 0
        uptime = utime.ticks_diff(utime.ticks_ms(), self._boot_ms) // 1000
        parts = [
            "HB",
            "{:02X}".format(self._id),
            str(uptime) + "s",
            "mem=" + str(free),
            "ring=" + str(self._ring_size),
            "lat=" + str(self._latency_ms) + "ms",
            "tx=" + str(self._pkts_sent),
            "rx=" + str(self._pkts_returned),
            "fwd=" + str(self._pkts_forwarded),
            "crc_err=" + str(self._pkts_crc_fail),
        ]
        line = " ".join(parts)
        self._uart.write(line.encode())
        self._uart.write(bytes([13, 10]))
        if self.debug:
            print("HB>>> " + line)

    # ------------------------------------------------------------------
    # Ring packet inject
    # ------------------------------------------------------------------

    def _inject(self):
        seq = self._seq & 0xFF
        pkt = bytearray(PKT_LEN)
        pkt[0]  = SYNC1
        pkt[1]  = SYNC2
        pkt[2]  = self._id
        pkt[3]  = 0
        pkt[4]  = seq
        pkt[5]  = 0
        pkt[6]  = self._my_buttons
        pkt[7]  = 0
        pkt[8]  = 0
        pkt[9]  = 0
        pkt[10] = _crc(pkt)
        self._uart.write(pkt)
        self._pkts_sent += 1
        self._sent_time[seq] = utime.ticks_ms()
        self._seq = (self._seq + 1) & 0xFF
        if len(self._sent_time) > 16:
            oldest = min(self._sent_time)
            del self._sent_time[oldest]
        if self.debug:
            print("TX seq=" + str(seq)
                  + " origin=0x" + "{:02X}".format(self._id)
                  + " raw=" + str(["{:02x}".format(x) for x in pkt]))

    # ------------------------------------------------------------------
    # RX byte state machine
    # ------------------------------------------------------------------

    def _rx_byte(self, b):
        s = self._rx_state

        # State 10: collecting heartbeat text line
        if s == 10:
            if b == 10:
                # newline = end of line
                try:
                    line = self._hb_buf.decode().strip()
                    if line.startswith("HB "):
                        print("<<< " + line)
                except Exception:
                    pass
                self._hb_buf = bytearray()
                self._rx_state = 0
            elif b == 13:
                pass  # skip CR
            elif len(self._hb_buf) < 120:
                self._hb_buf += bytes([b])
            else:
                self._hb_buf = bytearray()
                self._rx_state = 0
            return

        # State 0: waiting for sync1 or start of HB line
        if s == 0:
            if b == SYNC1:
                self._rx_buf[0] = b
                self._rx_state = 1
            elif b == 0x48:  # 'H' = start of "HB ..." heartbeat line
                self._hb_buf = bytearray([b])
                self._rx_state = 10

        # State 1: waiting for sync2
        elif s == 1:
            if b == SYNC2:
                self._rx_buf[1] = b
                self._rx_idx   = 2
                self._rx_state = 2
            elif b == SYNC1:
                pass  # could still be start of sync
            else:
                self._rx_state = 0

        # State 2: collecting packet data bytes
        elif s == 2:
            self._rx_buf[self._rx_idx] = b
            self._rx_idx += 1
            if self._rx_idx == PKT_LEN:
                self._rx_state = 0
                self._process_packet()

    # ------------------------------------------------------------------
    # Packet processing
    # ------------------------------------------------------------------

    def _process_packet(self):
        buf      = self._rx_buf
        crc_calc = _crc(buf)

        if crc_calc != buf[10]:
            self._pkts_crc_fail += 1
            if self.debug:
                print("RX CRC FAIL got=" + hex(buf[10])
                      + " expected=" + hex(crc_calc)
                      + " raw=" + str(["{:02x}".format(x) for x in buf]))
            return

        origin    = buf[2]
        hop_count = buf[3]
        seq       = buf[4]
        buttons   = buf[6]

        if self.debug:
            tag = "[MINE]" if origin == self._id else "[FWD]"
            print("RX origin=0x" + "{:02X}".format(origin)
                  + " hops=" + str(hop_count)
                  + " seq=" + str(seq)
                  + " btns=" + str(buttons)
                  + " " + tag)

        if origin == self._id:
            # Own packet returned
            if seq in self._sent_time:
                self._latency_ms = utime.ticks_diff(
                    utime.ticks_ms(), self._sent_time[seq])
                del self._sent_time[seq]
            self._ring_size     = hop_count
            self._pkts_returned += 1
        else:
            # Foreign packet — store and forward
            self._remote_buttons[origin] = buttons
            fwd     = bytearray(buf)
            fwd[3]  = (hop_count + 1) & 0xFF
            fwd[10] = _crc(fwd)
            self._uart.write(fwd)
            self._pkts_forwarded += 1
            if self.debug:
                print("FWD origin=0x" + "{:02X}".format(origin)
                      + " hops=" + str(fwd[3]))


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":

    print("=" * 40)
    print("Token Ring Standalone Test")
    print("=" * 40)

    ring = TokenRing()

    # Step 1: raw UART loopback
    print()
    print("Step 1: raw UART loopback (short GP8 to GP9)")
    ring._uart.write(b"HELLO")
    utime.sleep_ms(20)
    n = ring._uart.any()
    print("  sent 5 bytes, received: " + str(n) + " bytes")
    if n > 0:
        print("  data: " + str(ring._uart.read()))
        print("  PASS")
    else:
        print("  FAIL - check GP8/GP9 wiring")
    print()

    # Step 2: single packet loopback
    print("Step 2: single packet inject and receive")
    ring._uart.read()
    ring._inject()
    utime.sleep_ms(20)
    n = ring._uart.any()
    print("  injected 11 bytes, received: " + str(n) + " bytes")
    if n >= 11:
        raw = ring._uart.read(11)
        crc_ok = _crc(raw) == raw[10]
        print("  sync ok: " + str(raw[0] == SYNC1 and raw[1] == SYNC2))
        print("  crc ok:  " + str(crc_ok))
        print("  origin:  0x" + "{:02X}".format(raw[2]))
        print("  hops:    " + str(raw[3]))
        print("  PASS" if crc_ok else "  FAIL")
    else:
        print("  FAIL - not enough bytes returned")
    print()

    # Step 3: heartbeat test
    print("Step 3: heartbeat transmit")
    ring._send_heartbeat()
    utime.sleep_ms(20)
    n = ring._uart.any()
    print("  sent heartbeat, received back: " + str(n) + " bytes")
    if n > 0:
        print("  " + str(ring._uart.read()))
        print("  PASS")
    else:
        print("  FAIL")
    print()

    # Step 3.5: raw byte monitor — see exactly what arrives from other device
    print("Step 3.5: raw monitor - connect other device, watch for 10s")
    print("  Any bytes arriving will be printed as hex")
    ring._uart.read()   # flush
    t = utime.ticks_ms()
    raw_count = 0
    while utime.ticks_diff(utime.ticks_ms(), t) < 10000:
        if ring._uart.any():
            data = ring._uart.read()
            raw_count += len(data)
            print("  RX " + str(len(data)) + " bytes: "
                  + str(["0x{:02x}".format(b) for b in data]))
        utime.sleep_ms(10)
    print("  total received: " + str(raw_count) + " bytes")
    if raw_count == 0:
        print("  NOTHING received - check TX/RX wiring between devices")
        print("  Remember: device A TX(GP8) -> device B RX(GP9) AND")
        print("            device B TX(GP8) -> device A RX(GP9)")
    print()

    # Step 4: full tick loop
    print("Step 4: full tick loop (Ctrl-C to stop)")
    print("  debug=True: every TX/RX/FWD/HB printed")
    print("  <<< lines = heartbeat from other device")
    print()
    ring.debug = True
    ring._uart.read()
    ring._inject_ms  = 2000
    ring.heartbeat_ms = 3000

    last_stats = utime.ticks_ms()
    returned   = 0

    try:
        while True:
            ring._tick()

            if ring._pkts_returned > returned:
                returned = ring._pkts_returned
                print("  own pkt returned: ring_size=" + str(ring._ring_size)
                      + " latency=" + str(ring._latency_ms) + "ms")

            now = utime.ticks_ms()
            if utime.ticks_diff(now, last_stats) >= 5000:
                last_stats = now
                print("--- stats: tx=" + str(ring._pkts_sent)
                      + " rx=" + str(ring._pkts_returned)
                      + " fwd=" + str(ring._pkts_forwarded)
                      + " crc_err=" + str(ring._pkts_crc_fail)
                      + " remote=" + str(list(ring._remote_buttons.keys())))

            utime.sleep_ms(1)

    except KeyboardInterrupt:
        print()
        print("Stopped.")
        print("ring_size=" + str(ring._ring_size)
              + " latency=" + str(ring._latency_ms) + "ms")
        print("tx=" + str(ring._pkts_sent)
              + " rx=" + str(ring._pkts_returned)
              + " fwd=" + str(ring._pkts_forwarded))