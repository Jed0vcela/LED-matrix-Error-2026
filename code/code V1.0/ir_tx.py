"""
NEC IR vysílač – nosná 38 kHz (nastavitelné)
==============================================
Hardware:
  IR-TX -> GP5 (přes tranzistor/driver a IR LED - viz HW.md)

Nosnou vlnu 38 kHz generuje přímo hardwarové PWM (GP5), software jen
zapíná/vypíná její výstup (duty 50 % / 0 %) podle časování NEC protokolu
(mark/space) - carrier samotný tedy běží přesně na frekvenci PWM, ne
odhadem přes smyčku.

Standardní NEC časování (v mikrosekundách):
  header mark    9000
  header space   4500
  bit mark        560   (společný pro bit 0 i 1)
  "0" space       560
  "1" space      1680
  stop mark       560

Jeden celý rámec (adresa + negace adresy + příkaz + negace příkazu,
32 bitů) trvá vždy stejně dlouho bez ohledu na to, jaký konkrétní kód se
posílá - bajt a jeho bitová negace totiž dají dohromady vždy přesně
8 jedniček (kdykoliv je bit v bajtu 1, je na stejné pozici v negaci 0, a
naopak). Napříč (adresa, ~adresa, příkaz, ~příkaz) tak vždy vyjde přesně
16 jedničkových a 16 nulových bitů -> rámec s časy výše trvá vždy
~67,8 ms.

Spuštění samostatně: pořád dokola vysílá testovací kód ADDR/CMD níže,
s 500ms pauzou mezi jednotlivými rámci. Ctrl-C pro zastavení.
"""

import machine
import utime

IR_TX_PIN  = 5
CARRIER_HZ = 38000   # případně 37900 - obě hodnoty běžné IR přijímače zvládnou

# Testovací kód, který se posílá při samostatném spuštění souboru
ADDR = 0x00
CMD  = 0x0B

# NEC časování (mikrosekundy)
HEADER_MARK  = 9000
HEADER_SPACE = 4500
BIT_MARK     = 560
ZERO_SPACE   = 560
ONE_SPACE    = 1680
STOP_MARK    = 560

FRAME_PAUSE_MS = 500   # pauza mezi jednotlivými rámci při smyčce

# ---------------------------------------------------------------------------
# PWM nosná - vytvoří se jednou, dál se jen zapíná/vypíná (duty 50 %/0 %)
# ---------------------------------------------------------------------------
_pwm = machine.PWM(machine.Pin(IR_TX_PIN))
_pwm.freq(CARRIER_HZ)
_pwm.duty_u16(0)   # zpočátku vypnuto (žádná nosná)


def _mark(us):
    """Nosná zapnutá (50 % střída) po dobu `us` mikrosekund."""
    _pwm.duty_u16(32768)
    utime.sleep_us(us)


def _space(us):
    """Nosná vypnutá po dobu `us` mikrosekund."""
    _pwm.duty_u16(0)
    if us:
        utime.sleep_us(us)


def send_nec(addr, cmd):
    """
    Vyšle jeden kompletní NEC rámec (adresa + ~adresa + příkaz + ~příkaz).
    Na dobu vysílání (cca 68 ms) se schválně vypnou přerušení, ať
    časování mark/space nic nerozhodí - tenhle soubor běží samostatně,
    takže to nikde jinde nevadí.
    """
    naddr = (~addr) & 0xFF
    ncmd  = (~cmd) & 0xFF
    data = addr | (naddr << 8) | (cmd << 16) | (ncmd << 24)

    state = machine.disable_irq()
    try:
        _mark(HEADER_MARK)
        _space(HEADER_SPACE)
        for i in range(32):
            bit = (data >> i) & 1
            _mark(BIT_MARK)
            _space(ONE_SPACE if bit else ZERO_SPACE)
        _mark(STOP_MARK)
        _pwm.duty_u16(0)
    finally:
        machine.enable_irq(state)


def send_repeat():
    """NEC 'repeat' rámec (posílá se při podrženém tlačítku na
    originálním ovladači) - jen header a stop bit, bez datových bitů."""
    state = machine.disable_irq()
    try:
        _mark(HEADER_MARK)
        _space(HEADER_SPACE // 2)   # repeat má poloviční space (~2250 µs)
        _mark(STOP_MARK)
        _pwm.duty_u16(0)
    finally:
        machine.enable_irq(state)


# ---------------------------------------------------------------------------
# Samostatné spuštění - vysílá pořád dokola
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("NEC vysílač na GP{} - nosná {} Hz".format(IR_TX_PIN, CARRIER_HZ))
    print("Vysílám addr=0x{:02X} cmd=0x{:02X} (~68 ms rámec + {} ms pauza)"
          .format(ADDR, CMD, FRAME_PAUSE_MS))
    print("Ctrl-C pro zastavení.\n")

    try:
        while True:
            send_nec(ADDR, CMD)
            utime.sleep_ms(FRAME_PAUSE_MS)
    except KeyboardInterrupt:
        _pwm.duty_u16(0)
        _pwm.deinit()
        print("\nZastaveno.")
