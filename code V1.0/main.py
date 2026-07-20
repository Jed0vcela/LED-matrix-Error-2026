"""
Systém menu + multiplayer had + malování pro LED matici
========================================================
Importuje moduly led_matrix_pio, encoder, token_ring, ir_nec.
Spouští se jako main.py.

Ovládání menu:
  Otočení enkodéru = posun v položkách
  Stisk enkodéru   = potvrdit výběr
  Fire1 / Fire2    = potvrdit výběr
  Libovolné šipkové tlačítko = posun v položkách

Položky menu:
  SNAKE     - had pro jednoho hráče
  2P SNAKE  - had pro dva hráče přes token ring (propojení dvou zařízení)
  ATTRACT   - klidový/animační režim (šetřič displeje)
  PAINT     - volné malování na matici
  SETTINGS  - jas (enkodér) + info o ringu (propojení)
"""

import machine
import utime
import math

from led_matrix_pio import (
    start, stop,
    set_pixel, clear, fill, show,
    fill_rect, draw_rect,
    ROWS, COLS, _back,
)
from ir_nec import NEC, MatrixCurrent
from encoder import Encoder
from token_ring import TokenRing

# Fotodioda na GP28 - použije se pro automatický jas (SETTINGS: MAN/AUTO).
# Import obalený v try/except, aby hlavní program fungoval i bez ní.
try:
    from photodiode import read_raw as _photo_read_raw
except Exception:
    _photo_read_raw = None

_auto_brightness = False   # přepíná se v SETTINGS (MAN/AUTO)
_show_score_on_quit = True   # přepíná se v SETTINGS (SCORE PŘI KONCI)
_last_auto_check = 0

# ---------------------------------------------------------------------------
# Tlačítka (piny nastavené jako vstup s pull-up, tlačítko stisknuto = 0)
# ---------------------------------------------------------------------------
_BTN_FIRE1 = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)
_BTN_RIGHT = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_UP)
_BTN_LEFT  = machine.Pin(18, machine.Pin.IN, machine.Pin.PULL_UP)
_BTN_DOWN  = machine.Pin(19, machine.Pin.IN, machine.Pin.PULL_UP)
_BTN_UP    = machine.Pin(20, machine.Pin.IN, machine.Pin.PULL_UP)
_BTN_FIRE2 = machine.Pin(21, machine.Pin.IN, machine.Pin.PULL_UP)

# Jednotlivé funkce vrací True, pokud je dané tlačítko právě stisknuté
def btn_left():  return _BTN_LEFT.value()  == 0
def btn_right(): return _BTN_RIGHT.value() == 0
def btn_up():    return _BTN_UP.value()    == 0
def btn_down():  return _BTN_DOWN.value()  == 0
def btn_fire1(): return _BTN_FIRE1.value() == 0
def btn_fire2(): return _BTN_FIRE2.value() == 0
def any_btn():   return (btn_left() or btn_right() or btn_up() or
                         btn_down() or btn_fire1() or btn_fire2())
def all_btn():   return (btn_left() and btn_right() and btn_up() and
                         btn_down() and btn_fire1() and btn_fire2())

def wait_no_buttons(enc=None, timeout_ms=2000):
    """Počká, dokud uživatel nepustí všechna tlačítka (max. timeout_ms),
    aby se jeden stisk neprovedl vícekrát za sebou."""
    t = utime.ticks_ms()
    while any_btn() or (enc and enc.pressed):
        if utime.ticks_diff(utime.ticks_ms(), t) > timeout_ms:
            break
        utime.sleep_ms(1)

class EncoderEdge:
    """
    Obal nad enkodérem, který dělá spolehlivou hranovou detekci stisku
    jeho tlačítka vlastním pollováním (žádné IRQ potřeba) - was_pressed()
    teď vrátí True jen jednou při skutečném stisku (přechod
    nestisknuto->stisknuto), a dokud se tlačítko drží, se znovu
    nespustí, dokud se nepustí a nestiskne znovu.

    Dřív se všude volalo was_pressed() přímo na hardwarové třídě, a
    občas se stalo, že hra hned po spuštění z menu sama skončila -
    stisk enkodéru použitý k potvrzení výběru v menu byl zřejmě ještě
    "aktivní", když hra hned po startu zkontrolovala, jestli se má
    ukončit. Tenhle obal to řeší tak, že hranu počítá sám z nezávisle
    dostupného syrového stavu (.pressed), místo aby se spoléhal na
    interní chování was_pressed() hardwarové třídy.
    """
    def __init__(self, raw_enc):
        self._enc = raw_enc
        self._prev_pressed = False

    def was_pressed(self):
        cur = bool(self._enc.pressed)
        edge = cur and not self._prev_pressed
        self._prev_pressed = cur
        return edge

    @property
    def pressed(self):
        return self._enc.pressed

    def delta(self):
        return self._enc.delta()

    @property
    def value(self):
        return self._enc.value

    @value.setter
    def value(self, v):
        self._enc.value = v

    def set_range(self, lo, hi, wrap=False):
        return self._enc.set_range(lo, hi, wrap=wrap)

class Buttons:
    """
    Přečte všech 6 tlačítek jednou za smyčku a vrátí jak jejich
    aktuální stav (drženo/nedrženo), tak "hranu" (bylo právě
    stisknuto v tomto kroku). Nahrazuje dřívější opakované
    sledování prev/edge stavu, které bylo duplikované v každém
    herním režimu zvlášť.
    """
    __slots__ = ('_prev',)

    def __init__(self):
        self._prev = {'up': False, 'down': False, 'left': False,
                       'right': False, 'fire1': False, 'fire2': False}

    def poll(self):
        """Vrátí dvojici (drženo, právě_stisknuto) pro všechna tlačítka."""
        cur = {
            'up':    btn_up(),    'down':  btn_down(),
            'left':  btn_left(),  'right': btn_right(),
            'fire1': btn_fire1(), 'fire2': btn_fire2(),
        }
        prev = self._prev
        edge = {k: cur[k] and not prev[k] for k in cur}
        self._prev = cur
        return cur, edge

# ---------------------------------------------------------------------------
# Testovací režim displeje
# ---------------------------------------------------------------------------
def run_test_mode():
    """
    Testovací režim displeje. Aktivuje se stiskem VŠECH 6 tlačítek zároveň
    (bez enkodéru) — vhodné pro rychlou kontrolu, že všechny LED a napájení
    fungují. Displej velmi rychle bliká celý naráz (ale ne tak rychle, aby
    to oko nepostřehlo — je to zjevný rychlý blikot/stroboskop).
    Stiskem JAKÉHOKOLIV tlačítka se test ukončí a program pokračuje přesně
    tam, odkud byl test spuštěn (v menu, ve hře, v malování, ...).
    Lze aktivovat kdykoliv, protože kontrola všech 6 tlačítek je zanořená
    do hlavních smyček všech režimů.
    """
    wait_no_buttons()   # nejdřív počkat, až uživatel pustí všech 6 tlačítek
    on = False
    while True:
        on = not on
        if on: fill()
        else:  clear()
        show()
        # čekání rozdělené na kratší kousky, aby reakce na stisk byla okamžitá
        for _ in range(3):
            if any_btn():
                clear(); show()
                wait_no_buttons()
                return
            utime.sleep_ms(10)

_current_ref = None   # nastaví main() - odkaz na MatrixCurrent pro auto jas

def _apply_auto_brightness():
    """
    Přepočítá jas podle fotodiody a rovnou ho nastaví.
    Syrová hodnota 3000 a méně = minimální jas, 7000 a víc = maximální,
    mezi tím lineární interpolace. Nemusí to být přesné, takže se
    počítá přes bitový posun místo skutečného dělení.
    """
    if _photo_read_raw is None or _current_ref is None:
        return
    try:
        raw = _photo_read_raw()
    except Exception:
        return
    if raw <= 3000:
        lvl = 0
    elif raw >= 7000:
        lvl = 7
    else:
        # (7000-3000) rozsah na 8 úrovní - zhruba 500 na úroveň, >>9 (512)
        # je dost blízko a je to jen bitový posun, ne dělení
        lvl = (raw - 3000) >> 9
        if lvl > 7: lvl = 7
        if lvl < 0: lvl = 0
    _current_ref.set_level(lvl)

def check_test_mode():
    """Pomocná funkce: pokud jsou stisklá všechna tlačítka, spustí test
    a vrátí True (volající smyčka pak má hned pokračovat dalším cyklem).
    Mimochodem (jednou za ~300ms) tady také přepočítá automatický jas,
    pokud je zapnutý - toto je jediné místo volané ze všech herních
    smyček, takže auto jas takhle funguje všude, ne jen v SETTINGS."""
    global _last_auto_check
    if _auto_brightness:
        now = utime.ticks_ms()
        if utime.ticks_diff(now, _last_auto_check) >= 300:
            _last_auto_check = now
            _apply_auto_brightness()
    if all_btn():
        run_test_mode()
        return True
    return False

# ---------------------------------------------------------------------------
# Obecný výběr z několika možností (obtížnost, herní režim apod.)
# ---------------------------------------------------------------------------
def _pick_option(enc, title, options, initial=0):
    """
    Obrazovka výběru z několika možností - používají ji všechny
    obrazovky "vyber si obtížnost/režim" před hrou.
      Šipky nahoru/dolů NEBO otočení enkodéru = změna volby
      Fire1/Fire2 nebo stisk enkodéru          = potvrzení
    Vrátí index vybrané možnosti.
    """
    sel = initial % len(options)
    btns = Buttons()
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()
    while True:
        if check_test_mode():
            continue
        cur, edge = btns.poll()
        if edge['up']:   sel = (sel - 1) % len(options)
        if edge['down']: sel = (sel + 1) % len(options)
        if enc:
            d = enc.delta()
            if d:
                sel = (sel + (1 if d > 0 else -1)) % len(options)
        if edge['fire1'] or edge['fire2'] or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            return sel
        clear()
        draw_text(title, col_start=(COLS - text_width(title)) // 2,
                   row_start=0, level=1)
        name = options[sel]
        draw_text(name, col_start=(COLS - text_width(name)) // 2,
                   row_start=8, level=2)
        show()
        utime.sleep_ms(20)

# ---------------------------------------------------------------------------
# Kompletní font (velká písmena + číslice + symboly), každý znak 3×5 bodů
# ---------------------------------------------------------------------------
_FONT = {
    ' ': [0b00000,0b00000,0b00000],
    '!': [0b00000,0b10111,0b00000],
    '-': [0b00100,0b00100,0b00100],
    '.': [0b00000,0b10000,0b00000],
    ':': [0b00000,0b01010,0b00000],
    '0': [0b11111,0b10001,0b11111],
    '1': [0b00000,0b11111,0b00000],
    '2': [0b11101,0b10101,0b10111],
    '3': [0b10101,0b10101,0b11111],
    '4': [0b00111,0b00100,0b11111],
    '5': [0b10111,0b10101,0b11101],
    '6': [0b11111,0b10101,0b11101],
    '7': [0b00001,0b00001,0b11111],
    '8': [0b11111,0b10101,0b11111],
    '9': [0b10111,0b10101,0b11111],
    'A': [0b11111,0b00101,0b11111],
    'B': [0b11111,0b10101,0b01010],
    'C': [0b11111,0b10001,0b10001],
    'D': [0b11111,0b10001,0b01110],
    'E': [0b11111,0b10101,0b10001],
    'F': [0b11111,0b00101,0b00001],
    'G': [0b11111,0b10001,0b11101],
    'H': [0b11111,0b00100,0b11111],
    'I': [0b00000,0b11111,0b00000],
    'J': [0b11000,0b10000,0b11111],
    'K': [0b11111,0b00100,0b11011],
    'L': [0b11111,0b10000,0b10000],
    'M': [0b11111,0b00110,0b11111],
    'N': [0b11111,0b00010,0b11111],
    'O': [0b11111,0b10001,0b11111],
    'P': [0b11111,0b00101,0b00111],
    'Q': [0b01111,0b01001,0b11111],
    'R': [0b11111,0b00101,0b11011],
    'S': [0b10111,0b10101,0b11101],
    'T': [0b00001,0b11111,0b00001],
    'U': [0b11111,0b10000,0b11111],
    'V': [0b01111,0b10000,0b01111],
    'W': [0b11111,0b01000,0b11111],
    'X': [0b11011,0b00100,0b11011],
    'Y': [0b00111,0b11100,0b00111],
    'Z': [0b11001,0b10101,0b10011],
}

def draw_char(ch, col_start, row_start=0, level=2):
    """Vykreslí jeden znak na danou pozici a vrátí sloupec pro další znak."""
    cols = _FONT.get(ch.upper(), _FONT[' '])
    for ci, mask in enumerate(cols):
        for ri in range(5):
            set_pixel(row_start + ri, col_start + ci, level if (mask >> ri) & 1 else 0)
    return col_start + 4   # pozice dalšího znaku (3 body široký + 1 mezera)

def draw_text(text, col_start=0, row_start=0, level=2):
    """Vykreslí celý text znak po znaku od dané pozice."""
    col = col_start
    for ch in text:
        col = draw_char(ch, col, row_start, level)
    return col

def text_width(text):
    """Vrátí šířku textu v bodech (pro vycentrování na displeji)."""
    return len(text) * 4 - 1   # 3 body + 1 mezera na znak, poslední mezera se nepočítá

# ---------------------------------------------------------------------------
# Pomocná funkce pro náhodné číslo (na Pi Pico používá urandom, jinak náhradní generátor)
# ---------------------------------------------------------------------------
try:
    import urandom
    def _randint(a, b): return urandom.randint(a, b)
except ImportError:
    _seed = 12345
    def _randint(a, b):
        global _seed
        _seed = (_seed * 1103515245 + 12345) & 0x7FFFFFFF
        return a + (_seed % (b - a + 1))

# ---------------------------------------------------------------------------
# Zobrazení skóre / blikání celé matice / odpočet před hrou
# ---------------------------------------------------------------------------
def show_score(score, row_start=5):
    """Zobrazí skóre, které 4× blikne (vycentrované na displeji)."""
    for _ in range(4):
        clear()
        draw_text(str(score), col_start=max(0, (COLS - text_width(str(score))) // 2),
                  row_start=row_start)
        show()
        utime.sleep_ms(300)
        clear(); show()
        utime.sleep_ms(150)

def blink_all(times=3, on_ms=120, off_ms=80):
    """Rozbliká celou matici (např. po konci hry)."""
    for _ in range(times):
        fill(); show(); utime.sleep_ms(on_ms)
        clear(); show(); utime.sleep_ms(off_ms)

def _end_game_flash(score, times=3, on_ms=120, off_ms=80):
    """
    Po konci jednohráčské hry - bliknutí celé matice a zobrazení skóre,
    ale jen pokud je to v SETTINGS zapnuté ("SCORE PŘI KONCI"). Když je
    to vypnuté, hra prostě skončí potichu bez blikání a bez ukázání
    skóre.
    """
    if _show_score_on_quit:
        blink_all(times, on_ms, off_ms)
        show_score(score)

def countdown():
    """Odpočet 3, 2, 1 před začátkem hry."""
    for n in (3, 2, 1):
        clear()
        draw_text(str(n), col_start=14, row_start=5, level=2)
        show(); utime.sleep_ms(600)
        clear(); show(); utime.sleep_ms(100)

# ---------------------------------------------------------------------------
# IR dálkové ovládání (kódy tlačítek dálkového ovladače)
# ---------------------------------------------------------------------------
IR_CMD_UP    = 0x0b
IR_CMD_DOWN  = 0x0f
IR_CMD_LEFT  = 0x49
IR_CMD_RIGHT = 0x4a
IR_CMD_OK    = 0x0D
IR_CMD_STAR  = 0x01   # hvězdička = ztlumit
IR_CMD_HASH  = 0x0a   # mřížka    = zesvětlit

def process_ir(ir, current, ir_state):
    """Přečte přijaté IR příkazy a promítne je do jasu / směru pohybu."""
    while True:
        r = ir.poll()
        if r is None:
            break
        addr, cmd, repeat = r
        if repeat:
            continue   # opakovaný kód při podrženém tlačítku ignorujeme
        if cmd == IR_CMD_STAR:
            current.step_down()
        elif cmd == IR_CMD_HASH:
            current.step_up()
        elif cmd == IR_CMD_LEFT:  ir_state['dir'] = -1
        elif cmd == IR_CMD_UP:    ir_state['dir'] = -1
        elif cmd == IR_CMD_RIGHT: ir_state['dir'] =  1
        elif cmd == IR_CMD_DOWN:  ir_state['dir'] =  1
        ir_state['cmd'] = cmd

# ---------------------------------------------------------------------------
# Hlavní menu
# ---------------------------------------------------------------------------
MENU_ITEMS = [
    "SNAKE",
    "2P SNAKE",
    "LIFE",
    "BREAKOUT",
    "2P PONG",
    "FLAPPY",
    "GALAGA",
    "ASTEROID",
    "FROGGER",
    "REACTION",
    "MISSILE",
    "RACER",
    "2P TRON",
    "TREX",
    "ELEVATOR",
    "ELEV2",
    "ATTRACT",
    "PAINT",
    "TIME",
    "STOPWCH",
    "BTN TEST",
    "SETTINGS",
    "INFO",
]

def draw_menu(selected, scroll_offset):
    """
    Vykreslí položky menu na displeji 16×32.
    Naráz jsou vidět 3 položky (řádky 0-4, 6-10, 11-15).
    Vybraná položka svítí na úrovni 2, ostatní na úrovni 1.
    Šipky vpravo ukazují, že lze menu posunout dál nahoru/dolů.
    """
    clear()
    visible = 3
    row_positions = [0, 6, 11]

    for vi in range(visible):
        item_idx = scroll_offset + vi
        if item_idx >= len(MENU_ITEMS):
            break
        label   = MENU_ITEMS[item_idx]
        level   = 2 if item_idx == selected else 1
        row     = row_positions[vi]
        draw_text(label, col_start=1, row_start=row, level=level)

    # Šipka nahoru, pokud lze menu posunout výš
    if scroll_offset > 0:
        set_pixel(0, 30, 2)
        set_pixel(1, 31, 2)
        set_pixel(1, 29, 2)

    # Šipka dolů, pokud lze menu posunout níž
    if scroll_offset + visible < len(MENU_ITEMS):
        set_pixel(15, 30, 2)
        set_pixel(14, 31, 2)
        set_pixel(14, 29, 2)

    # Kurzor výběru: jasná tečka vlevo od vybrané položky
    vi_sel = selected - scroll_offset
    if 0 <= vi_sel < visible:
        set_pixel(row_positions[vi_sel] + 2, 0, 2)

    show()

def run_menu(enc, ir, current, ir_state, initial_selected=0):
    """
    Spustí smyčku menu. Vrátí index vybrané položky.
    Otočení enkodéru posouvá výběr, stisk enkodéru / fire1 / fire2 potvrdí.
    `initial_selected` - položka, na které se má kurzor objevit (aby se po
    návratu ze hry menu neotevíralo vždy znovu od SNAKE, ale tam, kde
    hráč naposledy skončil).
    """
    selected      = max(0, min(initial_selected, len(MENU_ITEMS) - 1))
    visible       = 3
    scroll_offset = 0
    if selected >= visible:
        scroll_offset = min(selected - visible + 1, len(MENU_ITEMS) - visible)
    prev_enc      = enc.value

    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()   # zahodit "zaseknutý" stisk enkodéru, který mohl
                             # zůstat nespotřebovaný z předchozí hry (pokud
                             # hra sama enc.was_pressed() nikdy nečetla,
                             # jinak by tenhle stisk hned "potvrdil" SNAKE)
    enc.set_range(0, len(MENU_ITEMS) - 1, wrap=True)
    enc.value = selected

    draw_menu(selected, scroll_offset)

    while True:
        if check_test_mode():
            continue

        process_ir(ir, current, ir_state)
        ir_state['dir'] = None

        # Otočení enkodéru = posun výběru
        new_val = enc.value
        if new_val != prev_enc:
            selected = new_val
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + visible:
                scroll_offset = selected - visible + 1
            prev_enc = new_val
            draw_menu(selected, scroll_offset)

        # Šipka nahoru/vlevo = předchozí položka
        if btn_up() or btn_left():
            selected = (selected - 1) % len(MENU_ITEMS)
            enc.value = selected
            prev_enc = selected
            if selected < scroll_offset:
                scroll_offset = selected
            draw_menu(selected, scroll_offset)
            wait_no_buttons(enc)

        # Šipka dolů/vpravo = další položka
        elif btn_down() or btn_right():
            selected = (selected + 1) % len(MENU_ITEMS)
            enc.value = selected
            prev_enc = selected
            if selected >= scroll_offset + visible:
                scroll_offset = selected - visible + 1
            draw_menu(selected, scroll_offset)
            wait_no_buttons(enc)

        # Potvrzení výběru
        elif btn_fire1() or btn_fire2() or enc.was_pressed():
            wait_no_buttons(enc)
            return selected

        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Obrazovka nastavení: jas, datum a čas (vše v jedné obrazovce)
# ---------------------------------------------------------------------------
def run_settings(enc, current, ring):
    """
    Nastavení jasu (ruční / auto podle fotodiody), času a toho, jestli
    se po konci hry ukazuje skóre.
      Šipky vlevo/vpravo = výběr položky (režim jasu / jas / hod / min /
                             skóre při konci)
      Enkodér             = změna vybrané položky
                             - u režimu: přepne MANUAL <-> AUTO
                             - u jasu: mění úroveň (funguje jen v režimu
                               MANUAL - v AUTO se jas řídí sám podle
                               fotodiody a pole jen zobrazuje aktuální
                               hodnotu)
                             - u hodin/minut: mění číslici o její řádovou
                               hodnotu, se zabalením v platném rozsahu
                               (čas tedy nikdy nemůže být neplatný)
                             - u "skóre při konci": zapne/vypne, jestli
                               hry po konci bliknou a ukážou skóre,
                               nebo prostě potichu skončí
      Fire1 / Fire2 nebo stisk enkodéru = odchod do menu
    """
    global _auto_brightness, _show_score_on_quit

    y, mo, d, wd, h, mi, s = _rtc_get()
    lvl = current.get_level()
    cursor = 0   # 0=režim jasu, 1=jas, 2=H10, 3=H1, 4=M10, 5=M1, 6=skóre při konci

    btns = Buttons()
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if check_test_mode():
            continue

        cur, edge = btns.poll()

        if edge['left']:
            cursor = (cursor - 1) % 7
        if edge['right']:
            cursor = (cursor + 1) % 7

        if _auto_brightness:
            lvl = current.get_level()   # vždy ukázat živě dopočítanou hodnotu

        if enc:
            dlt = enc.delta()
            if dlt:
                if cursor == 0:
                    _auto_brightness = not _auto_brightness
                elif cursor == 1 and not _auto_brightness:
                    lvl = max(0, min(7, lvl + dlt))
                    current.set_level(lvl)
                elif cursor == 2:  h  = (h + 10 * dlt) % 24
                elif cursor == 3:  h  = (h +  1 * dlt) % 24
                elif cursor == 4:  mi = (mi + 10 * dlt) % 60
                elif cursor == 5:  mi = (mi +  1 * dlt) % 60
                elif cursor == 6:  _show_score_on_quit = not _show_score_on_quit
                if 2 <= cursor <= 5:
                    _rtc_set(y, mo, d, h, mi, s, wd)

        if edge['fire1'] or edge['fire2'] or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            enc.set_range(0, len(MENU_ITEMS) - 1, wrap=True)
            return

        clear()

        mode_txt = "AUTO" if _auto_brightness else "MAN"
        draw_text(mode_txt, col_start=(COLS - text_width(mode_txt)) // 2,
                   row_start=0, level=2 if cursor == 0 else 1)

        # Jas - jen sloupcový ukazatel, žádný textový popisek
        for i in range(8):
            if i < lvl:
                seg_lvl = 2 if (cursor == 1 and not _auto_brightness) else 1
                fill_rect(6, i * 4, 3, 2, seg_lvl)

        # Skóre při konci hry - krátký pruh (na plný text tu není místo):
        # plný pruh = zapnuto, jen krajní body ("prázdný" pruh) = vypnuto
        row_score = 9
        bar_w = 10
        bar_col0 = (COLS - bar_w) // 2
        lvl_score = 2 if cursor == 6 else 1
        if _show_score_on_quit:
            for i in range(bar_w):
                set_pixel(row_score, bar_col0 + i, lvl_score)
        else:
            set_pixel(row_score, bar_col0, lvl_score)
            set_pixel(row_score, bar_col0 + bar_w - 1, lvl_score)

        # Čas (dvojtečka bliká v 1s intervalech, stejně jako na TIME obrazovce)
        colon_on = (utime.ticks_ms() // 1000) % 2 == 0
        time_txt = "{:02d}{}{:02d}".format(h, ':' if colon_on else ' ', mi)
        time_chars = [(time_txt[0], cursor==2), (time_txt[1], cursor==3), (time_txt[2], False),
                      (time_txt[3], cursor==4), (time_txt[4], cursor==5)]
        col = (COLS - text_width(time_txt)) // 2
        for ch, sel in time_chars:
            col = draw_char(ch, col, row_start=11, level=2 if sel else 1)

        show()
        utime.sleep_ms(20)

# ---------------------------------------------------------------------------
# Reálný čas (RTC) - pomocné funkce
# ---------------------------------------------------------------------------
def _rtc_get():
    """
    Vrátí (year, month, day, weekday, hour, minute, second).
    Pokud RTC z nějakého důvodu selže (nepodporováno apod.), vrátí
    rozumnou výchozí hodnotu místo pádu.
    """
    try:
        y, mo, d, wd, h, mi, s, _ss = machine.RTC().datetime()
        return y, mo, d, wd, h, mi, s
    except Exception:
        return 2025, 1, 1, 0, 0, 0, 0

def _rtc_set(y, mo, d, h, mi, s=0, wd=0):
    try:
        machine.RTC().datetime((y, mo, d, wd, h, mi, s, 0))
    except Exception:
        pass

# ---------------------------------------------------------------------------
# TIME — jen zobrazení aktuálního času (nastavení je v SETTINGS)
# ---------------------------------------------------------------------------
def run_show_time(enc):
    """Zobrazí aktuální čas (HH:MM, dvojtečka bliká v 1s intervalech),
    živě aktualizované. Jakékoliv tlačítko nebo stisk enkodéru = zpět
    do menu."""
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if check_test_mode():
            continue

        y, mo, d, wd, h, mi, s = _rtc_get()
        colon_on = (utime.ticks_ms() // 1000) % 2 == 0
        clear()
        txt = "{:02d}{}{:02d}".format(h, ':' if colon_on else ' ', mi)
        draw_text(txt, col_start=(COLS - text_width(txt)) // 2, row_start=6, level=2)
        show()

        if any_btn() or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            return
        utime.sleep_ms(100)

# ---------------------------------------------------------------------------
# Stopky
# ---------------------------------------------------------------------------
def run_stopwatch(enc=None):
    """
    Stopky. Po spuštění čekají, až se stiskne Fire1 - tím se čas
    začne počítat. Dalším stiskem Fire1 se počítání pozastaví, dalším
    znovu obnoví. Fire2 kdykoliv vynuluje čas zpět na 0:00 (a
    zastaví počítání, čeká se znovu na Fire1).
      Fire1 = start / pauza
      Fire2 = reset
      Stisk enkodéru = konec
    """
    running = False
    elapsed_ms = 0
    start_ref = utime.ticks_ms()

    btns = Buttons()
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if check_test_mode():
            continue

        now = utime.ticks_ms()
        cur, edge = btns.poll()

        if edge['fire1']:
            if running:
                elapsed_ms += utime.ticks_diff(now, start_ref)
                running = False
            else:
                start_ref = now
                running = True

        if edge['fire2']:
            running = False
            elapsed_ms = 0

        if enc and enc.was_pressed():
            return

        total_ms = elapsed_ms + (utime.ticks_diff(now, start_ref) if running else 0)
        total_s = total_ms // 1000
        mm = (total_s // 60) % 100
        ss = total_s % 60

        clear()
        txt = "{:02d}:{:02d}".format(mm, ss)
        draw_text(txt, col_start=(COLS - text_width(txt)) // 2, row_start=6,
                   level=2 if running else 1)
        show()
        utime.sleep_ms(30)

# ---------------------------------------------------------------------------
# Info - autor skriptu, autor hardwaru, verze
# ---------------------------------------------------------------------------
_INFO_SCRIPT_AUTHOR = "YOU"    # <-- doplň svoje jméno
_INFO_HW_AUTHOR      = "YOU"    # <-- doplň jméno autora hardwaru
_INFO_VERSION        = "1.0"

def run_info(enc=None):
    """
    Zobrazí verzi skriptu.
      Stisk enkodéru nebo Fire1/Fire2 = konec
    """
    btns = Buttons()
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if check_test_mode():
            continue
        cur, edge = btns.poll()

        if edge['fire1'] or edge['fire2'] or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            return

        clear()
        draw_text("VERSION", col_start=(COLS - text_width("VERSION")) // 2,
                   row_start=2, level=1)
        ver_s = str(_INFO_VERSION)
        draw_text(ver_s, col_start=(COLS - text_width(ver_s)) // 2,
                   row_start=9, level=2)
        show()
        utime.sleep_ms(20)

# ---------------------------------------------------------------------------
# Test tlačítek (zároveň ovladač pro navazující zařízení v řetězci)
# ---------------------------------------------------------------------------
def run_button_test(enc, ring):
    """
    Ukáže, které tlačítko je právě stisknuté - jedna tečka na tlačítko,
    rozmístěné jako šipky (D-pad) + dvě tečky pro Fire1/Fire2.

    Zároveň každý cyklus posílá vlastní stav tlačítek dál přes ring/hop
    řetězec - takže tahle obrazovka může sloužit jako "ovladač" pro hru,
    která běží na navazujícím (upstream) zařízení, aniž by sama musela
    cokoliv počítat nebo zobrazovat ze hry samotné.

    Schválně nevolá check_test_mode(): all-button-press diagnostika by
    tady jen překryla to, co tahle obrazovka sama ukazuje (naráz stisknutá
    všechna tlačítka je tu naprosto validní a chtěný stav k zobrazení).

    Odchod: stiskem enkodéru (Fire1/Fire2 jsou součástí testu, takže je
    nelze použít k odchodu jako jinde v menu).
    """
    btns = Buttons()
    # Souřadnice jednotlivých teček (řádek, sloupec)
    DOTS = {
        'up':    (6, 4),
        'left':  (10, 1),
        'right': (10, 7),
        'down':  (14, 4),
        'fire1': (10, 16),
        'fire2': (10, 22),
    }

    wait_no_buttons(enc)
    while True:
        cur, _ = btns.poll()

        # Vlastní stav se posílá dál stejně jako ve hře - toto zařízení
        # je plnohodnotným článkem řetězce ovladačů.
        if ring:
            ring.send_buttons(TokenRing.buttons_byte(
                cur['fire1'], cur['right'], cur['left'],
                cur['down'], cur['up'], cur['fire2']))

        clear()
        draw_text("BTN", col_start=0, row_start=0, level=1)
        for name, (r, c) in DOTS.items():
            set_pixel(r, c, 2 if cur[name] else 0)
        show()

        if enc.was_pressed():
            wait_no_buttons(enc)
            return

        utime.sleep_ms(15)

# ---------------------------------------------------------------------------
# Malovací režim
# ---------------------------------------------------------------------------
def run_paint(enc=None, current=None, ring=None):
    """
    Volné kreslení na matici - teď i pro dva hráče najednou na jednom
    sdíleném plátně. Na začátku krátce zkontroluje, jestli něco
    přichází přes řetězec - pokud ano, hraje se ve dvou (druhý kurzor
    podle přeposlaných tlačítek), pokud ne, funguje to úplně stejně
    jako dřív pro jednoho.

      Šipky            = pohyb kurzoru (při podržení se pohyb sám opakuje)
      Šipky + Fire1
      podrženo zároveň = kreslí tahem (každé nové políčko se vybarví)
      Fire1            = přepnout bod pod kurzorem (rozsvítit/zhasnout)
      Fire2            = smazat celé plátno
      Enkodér          = jas
      Fire1+Fire2 nebo
      stisk enkodéru   = odchod zpět do menu (jen lokálně)
    """
    remote_id   = _mp_detect_peer(ring)
    multiplayer = remote_id is not None

    # Plátno = jeden byte na každý bod (0 = zhasnuto, 1/2 = úroveň jasu)
    canvas = bytearray(ROWS * COLS)
    r, c = ROWS // 2, COLS // 2   # lokální kurzor začíná uprostřed
    rr_, rc_ = ROWS // 2, (COLS // 2 + 5) % COLS   # vzdálený kurzor, kousek vedle
    btns = Buttons()
    ticks_ms   = utime.ticks_ms
    ticks_diff = utime.ticks_diff

    REPEAT_DELAY = 350   # ms než se podržená šipka začne sama opakovat
    REPEAT_RATE  = 90    # ms mezi jednotlivými opakováními
    held_since  = {'up': 0, 'down': 0, 'left': 0, 'right': 0}
    rheld_since = {'up': 0, 'down': 0, 'left': 0, 'right': 0}
    blink_t = ticks_ms()
    blink_on = True   # pro blikání kurzoru, ať je vždy vidět, i nad nakresleným bodem

    remote_prev = {'up': False, 'down': False, 'left': False,
                   'right': False, 'fire1': False, 'fire2': False}

    def move(dr, dc):
        """Posune lokální kurzor o (dr, dc), ale nedovolí mu opustit displej."""
        nonlocal r, c
        r = max(0, min(ROWS - 1, r + dr))
        c = max(0, min(COLS - 1, c + dc))

    def rmove(dr, dc):
        """Posune vzdálený kurzor o (dr, dc), ale nedovolí mu opustit displej."""
        nonlocal rr_, rc_
        rr_ = max(0, min(ROWS - 1, rr_ + dr))
        rc_ = max(0, min(COLS - 1, rc_ + dc))

    while True:
        # Enkodér mění jas i tady
        if enc and current:
            d = enc.delta()
            if d: current.step_up() if d > 0 else current.step_down()

        cur, edge = btns.poll()
        now = ticks_ms()

        # Test displeje (všech 6 tlačítek naráz) má přednost před ostatními kombinacemi
        if all_btn():
            run_test_mode()
            continue

        # Kombinace Fire1+Fire2 zároveň, nebo stisk enkodéru = konec (jen lokálně)
        if (cur['fire1'] and cur['fire2']) or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            return

        # Pohyb lokálního kurzoru šipkami, s automatickým opakováním při
        # podržení - a pokud se přitom drží i Fire1, každé nové políčko
        # se rovnou vybarví (usnadňuje kreslení tahem)
        for name, dr, dc in (('up', -1, 0), ('down', 1, 0),
                             ('left', 0, -1), ('right', 0, 1)):
            moved = False
            if edge[name]:
                move(dr, dc); held_since[name] = now; moved = True
            elif cur[name] and ticks_diff(now, held_since[name]) >= REPEAT_DELAY:
                move(dr, dc); held_since[name] = now - (REPEAT_DELAY - REPEAT_RATE); moved = True
            elif not cur[name]:
                held_since[name] = 0
            if moved and cur['fire1']:
                canvas[r * COLS + c] = 2

        # Fire1 = přepnout bod pod kurzorem (kreslit / mazat jeden bod)
        if edge['fire1']:
            idx = r * COLS + c
            canvas[idx] = 0 if canvas[idx] else 2

        # Fire2 = smazat celé plátno
        if edge['fire2']:
            for i in range(len(canvas)):
                canvas[i] = 0

        # --- Druhé zařízení (pokud je připojené) ---
        if multiplayer:
            ring.send_buttons(TokenRing.buttons_byte(
                cur['fire1'], cur['right'], cur['left'],
                cur['down'], cur['up'], cur['fire2']))
            remote = ring.get_state().get(remote_id, 0)
            rb = TokenRing.unpack_buttons(remote)
            remote_edge = {k: rb[k] and not remote_prev[k] for k in rb}
            remote_prev = rb

            for name, dr, dc in (('up', -1, 0), ('down', 1, 0),
                                 ('left', 0, -1), ('right', 0, 1)):
                rmoved = False
                if remote_edge[name]:
                    rmove(dr, dc); rheld_since[name] = now; rmoved = True
                elif rb[name] and ticks_diff(now, rheld_since[name]) >= REPEAT_DELAY:
                    rmove(dr, dc); rheld_since[name] = now - (REPEAT_DELAY - REPEAT_RATE); rmoved = True
                elif not rb[name]:
                    rheld_since[name] = 0
                if rmoved and rb['fire1']:
                    canvas[rr_ * COLS + rc_] = 2

            if remote_edge['fire1']:
                idx = rr_ * COLS + rc_
                canvas[idx] = 0 if canvas[idx] else 2
            if remote_edge['fire2']:
                for i in range(len(canvas)):
                    canvas[i] = 0

        # Blikání kurzoru (přepíná se cca každých 300 ms)
        if ticks_diff(now, blink_t) >= 300:
            blink_t = now
            blink_on = not blink_on

        # Vykreslení celého plátna (kreslíme jen rozsvícené body, kvůli rychlosti)
        clear()
        for row in range(ROWS):
            base = row * COLS
            for col in range(COLS):
                v = canvas[base + col]
                if v:
                    set_pixel(row, col, v)

        # Kurzor(y) navrch: blikají, ať jsou vidět i nad nakresleným bodem
        cursor_v = canvas[r * COLS + c]
        if blink_on:
            set_pixel(r, c, 1 if cursor_v else 2)
        else:
            set_pixel(r, c, cursor_v)

        if multiplayer:
            rcursor_v = canvas[rr_ * COLS + rc_]
            if not blink_on:   # obráceně než lokální, ať jde kurzory rozeznat
                set_pixel(rr_, rc_, 1 if rcursor_v else 2)
            else:
                set_pixel(rr_, rc_, rcursor_v)

        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Animace v klidovém/attract režimu (šetřič displeje)
# ---------------------------------------------------------------------------
def attract_sine(enc=None, current=None):
    """Vlnící se sinusovka putující po displeji."""
    import array as _arr
    LUT = COLS
    peaks = _arr.array('H', [0] * (LUT * COLS))
    for off in range(LUT):
        for col in range(COLS):
            p = 7.5 + 7 * math.sin((col + off) * 0.4)
            peaks[off * COLS + col] = int(p * 16)
    offset = 0
    for _ in range(300):
        if check_test_mode(): continue
        if any_btn() or (enc and enc.was_pressed()): return True
        if enc and current:
            d = enc.delta()
            if d: current.step_up() if d > 0 else current.step_down()
        clear()
        base = (offset % LUT) * COLS
        for col in range(COLS):
            pf = peaks[base + col]
            peak = pf >> 4
            frac = pf & 0xF
            if 0 <= peak < ROWS:           set_pixel(peak, col, 2)
            if 0 <= peak - 1 < ROWS:       set_pixel(peak-1, col, 2 if frac < 3 else 1)
            if 0 <= peak + 1 < ROWS:       set_pixel(peak+1, col, 2 if frac > 13 else 1)
        show(); utime.sleep_ms(20); offset += 1
    return False

def attract_bounce(enc=None, current=None):
    """Odrážející se čtvereček po celém displeji."""
    bx, by, dx, dy = 0, 0, 1, 1
    for _ in range(250):
        if check_test_mode(): continue
        if any_btn() or (enc and enc.was_pressed()): return True
        if enc and current:
            d = enc.delta()
            if d: current.step_up() if d > 0 else current.step_down()
        clear()
        fill_rect(by, bx, 3, 5, 2)
        draw_rect(max(0,by-1), max(0,bx-1), 5, 7, 1)
        show()
        bx += dx; by += dy
        if bx <= 0 or bx >= COLS-5: dx = -dx
        if by <= 0 or by >= ROWS-3: dy = -dy
        utime.sleep_ms(28)
    return False

def attract_checker(enc=None, current=None):
    """Blikající šachovnicový vzor."""
    for i in range(12):
        if check_test_mode(): continue
        if any_btn() or (enc and enc.was_pressed()): return True
        if enc and current:
            d = enc.delta()
            if d: current.step_up() if d > 0 else current.step_down()
        clear()
        for r in range(ROWS):
            for c in range(COLS):
                set_pixel(r, c, 2 if (r+c+i)%2==0 else 1)
        show(); utime.sleep_ms(200)
    return False

def attract_rain(enc=None, current=None):
    """Padající kapky deště se stříkanci dopadu."""
    drops = []; splats = []
    for _ in range(300):
        if check_test_mode(): continue
        if any_btn() or (enc and enc.was_pressed()): return True
        if enc and current:
            d = enc.delta()
            if d: current.step_up() if d > 0 else current.step_down()
        if _randint(0,3) == 0:
            drops.append([_randint(0, COLS-1), 0])
        new_drops = []
        for col, row in drops:
            if row+1 >= ROWS: splats.append([col, row, 3])
            else:             new_drops.append([col, row+1])
        drops  = new_drops
        splats = [[c,r,t-1] for c,r,t in splats if t>1]
        clear()
        for col, row in drops:       set_pixel(row, col, 2)
        for col, row, _ in splats:
            set_pixel(row, col, 1)
            if col > 0:        set_pixel(row, col-1, 1)
            if col < COLS-1:   set_pixel(row, col+1, 1)
        show(); utime.sleep_ms(50)
    return False

_ATTRACT = [attract_sine, attract_bounce, attract_checker, attract_rain]

def run_attract(enc=None, current=None):
    """Postupně přehrává jednotlivé animace dokola, dokud se nestiskne tlačítko."""
    i = 0
    while True:
        if _ATTRACT[i % len(_ATTRACT)](enc=enc, current=current):
            return
        i += 1

# ---------------------------------------------------------------------------
# Had pro jednoho hráče
# ---------------------------------------------------------------------------
_DR = [0, 1, 0, -1]   # posun v řádku pro směry: 0=vpravo, 1=dolů, 2=vlevo, 3=nahoru
_DC = [1, 0, -1, 0]   # posun ve sloupci pro tytéž směry

def _place_food(snake_set):
    """Náhodně umístí jídlo na volné políčko (mimo tělo hada)."""
    while True:
        r = _randint(0, ROWS-1); c = _randint(0, COLS-1)
        if (r,c) not in snake_set: return (r,c)

def run_snake(enc=None, ir=None, current=None, ir_state=None, ring=None):
    """Hlavní smyčka hry had pro jednoho hráče. Vrací dosažené skóre."""
    direction = 0
    snake = [(ROWS//2, COLS//4 - i) for i in range(4)]
    snake_set = set(snake)
    food  = _place_food(snake_set)
    score = 0; grow = 0; step_ms = 200   # step_ms = rychlost hada (klesá = zrychluje se)
    btns = Buttons()
    ticks_ms   = utime.ticks_ms
    ticks_diff = utime.ticks_diff
    last_step = ticks_ms()

    while True:
        if check_test_mode():
            continue

        # Ovládání přes IR dálkový ovladač
        if ir and ir_state:
            process_ir(ir, current, ir_state)
            if ir_state['dir']:
                direction = (direction + ir_state['dir']) % 4
                ir_state['dir'] = None

        # Ovládání tlačítky: šipky = absolutní směr, fire1/fire2 = otočení doleva/doprava
        cur, edge = btns.poll()
        if edge['up']    and direction != 1: direction = 3
        if edge['down']  and direction != 3: direction = 1
        if edge['left']  and direction != 0: direction = 2
        if edge['right'] and direction != 2: direction = 0
        if edge['fire1']: direction = (direction-1) % 4
        if edge['fire2']: direction = (direction+1) % 4

        if enc and enc.was_pressed():
            return score

        # Odeslání stavu tlačítek přes token ring (pro případného druhého hráče)
        if ring:
            ring.send_buttons(TokenRing.buttons_byte(
                cur['fire1'], cur['right'], cur['left'],
                cur['down'], cur['up'], cur['fire2']))

        # Krok hry (posun hada) probíhá jen jednou za step_ms, ne každý průchod smyčky
        now = ticks_ms()
        if ticks_diff(now, last_step) >= step_ms:
            last_step = now
            nr = snake[0][0] + _DR[direction]
            nc = snake[0][1] + _DC[direction]
            if nr < 0 or nr >= ROWS or nc < 0 or nc >= COLS: return score   # náraz do zdi
            if (nr,nc) in snake_set: return score   # náraz do vlastního těla
            if (nr,nc) == food:
                score += 1; grow += 3
                food = _place_food(snake_set)
                step_ms = max(80, step_ms-5)   # s každým jídlem trochu rychlejší
            snake.insert(0, (nr,nc)); snake_set.add((nr,nc))
            if grow > 0: grow -= 1
            else:
                tail = snake.pop(); snake_set.discard(tail)

        # Vykreslení: jídlo bliká, hlava svítí víc než tělo
        clear()
        if (ticks_ms() // 125) % 2 == 0:
            set_pixel(food[0], food[1], 2)
        for i,(r,c) in enumerate(snake):
            set_pixel(r, c, 2 if i==0 else 1)
        show()

# ---------------------------------------------------------------------------
# 2-player snake
# ---------------------------------------------------------------------------
def run_2p_snake(enc=None, ir=None, current=None, ir_state=None, ring=None):
    """
    2-player snake. Player 1 = local buttons. Player 2 = remote via token ring.
    Both snakes on same display. Different brightness to distinguish.
    P1 head=level2, body=level1. P2 head=level2 blink, body=level1.
    Game ends when either snake dies. Show who won.
    """
    if ring is None:
        clear()
        draw_text("NO RING", col_start=0, row_start=5, level=2)
        show(); utime.sleep_ms(2000)
        return

    # Zkontrolujeme, jestli je v ringu druhé zařízení (druhý hráč)
    state = ring.get_state()
    if not state:
        clear()
        draw_text("WAIT", col_start=4, row_start=5, level=2)
        show()
        t = utime.ticks_ms()
        # Počkáme až 3 s, jestli se druhé zařízení objeví
        while not ring.get_state() and utime.ticks_diff(utime.ticks_ms(), t) < 3000:
            utime.sleep_ms(100)
        if not ring.get_state():
            clear()
            draw_text("NO P2", col_start=0, row_start=5, level=2)
            show(); utime.sleep_ms(2000)
            return

    # Hadi startují na opačných stranách displeje a míří k sobě
    s1 = [(ROWS//2, 6 - i)      for i in range(4)]   # P1 vlevo, míří doprava
    s2 = [(ROWS//2, COLS-7 + i) for i in range(4)]   # P2 vpravo, míří doleva
    d1 = 0   # doprava
    d2 = 2   # doleva

    food = _place_food(set(s1) | set(s2))
    sc1 = 0; sc2 = 0
    gr1 = 0; gr2 = 0
    step_ms = 250
    btns = Buttons()
    ticks_ms   = utime.ticks_ms
    ticks_diff = utime.ticks_diff

    remote_id = list(ring.get_state().keys())[0]
    remote_prev = {'up': False, 'down': False, 'left': False,
                   'right': False, 'fire1': False, 'fire2': False}
    last_step = ticks_ms()

    while True:
        # --- Lokální ovládání hráče 1 ---
        cur, edge = btns.poll()

        # Test displeje (všech 6 tlačítek naráz) má přednost před vším ostatním
        if cur['up'] and cur['down'] and cur['left'] and cur['right'] and cur['fire1'] and cur['fire2']:
            run_test_mode()
            continue

        if edge['up']    and d1 != 1: d1 = 3
        if edge['down']  and d1 != 3: d1 = 1
        if edge['left']  and d1 != 0: d1 = 2
        if edge['right'] and d1 != 2: d1 = 0
        if edge['fire1']: d1 = (d1-1) % 4
        if edge['fire2']: d1 = (d1+1) % 4

        # Odeslání tlačítek P1 přes ring pro druhé zařízení
        ring.send_buttons(TokenRing.buttons_byte(
            cur['fire1'], cur['right'], cur['left'],
            cur['down'], cur['up'], cur['fire2']))

        if enc and enc.was_pressed():
            return

        # --- Vzdálené ovládání hráče 2, přijaté z ringu ---
        # Hrana (změna vypnuto->zapnuto) se počítá i pro vzdálený stav -
        # bez toho by držení Fire tlačítka na druhém zařízení protočilo
        # směr mnohokrát za jediný lidský stisk (smyčka běží mnohem
        # rychleji než trvá stisk tlačítka), takže zatáčení přes Fire
        # bylo prakticky neovladatelné a had narážel sám do sebe.
        remote = ring.get_state().get(remote_id, 0)
        rb = TokenRing.unpack_buttons(remote)
        remote_edge = {k: rb[k] and not remote_prev[k] for k in rb}
        remote_prev = rb
        # P2 má zrcadlené ovládání (je na druhé straně displeje)
        if rb['up']    and d2 != 1: d2 = 3
        if rb['down']  and d2 != 3: d2 = 1
        if rb['left']  and d2 != 0: d2 = 2
        if rb['right'] and d2 != 2: d2 = 0
        if remote_edge['fire1']: d2 = (d2-1) % 4
        if remote_edge['fire2']: d2 = (d2+1) % 4

        # --- Krok hry (probíhá jen jednou za step_ms) ---
        now = ticks_ms()
        if ticks_diff(now, last_step) >= step_ms:
            last_step = now

            # Posun hada P1 a kontrola nárazu do zdi/vlastního těla/těla P2
            n1r = s1[0][0] + _DR[d1]
            n1c = s1[0][1] + _DC[d1]
            p1_dead = (n1r < 0 or n1r >= ROWS or n1c < 0 or n1c >= COLS
                       or (n1r,n1c) in set(s1) or (n1r,n1c) in set(s2))

            # Posun hada P2 a kontrola nárazu do zdi/vlastního těla/těla P1
            n2r = s2[0][0] + _DR[d2]
            n2c = s2[0][1] + _DC[d2]
            p2_dead = (n2r < 0 or n2r >= ROWS or n2c < 0 or n2c >= COLS
                       or (n2r,n2c) in set(s2) or (n2r,n2c) in set(s1))

            # Čelní srážka obou hlav = prohrávají oba
            if (n1r,n1c) == (n2r,n2c):
                p1_dead = True; p2_dead = True

            if p1_dead or p2_dead:
                blink_all(3, 100, 80)
                clear()
                if p1_dead and p2_dead:
                    draw_text("DRAW", col_start=4, row_start=5, level=2)
                elif p1_dead:
                    draw_text("P2 WIN", col_start=0, row_start=5, level=2)
                else:
                    draw_text("P1 WIN", col_start=0, row_start=5, level=2)
                show(); utime.sleep_ms(3000)
                return

            # Posun P1 vpřed, případné sežrání jídla a růst
            s1.insert(0,(n1r,n1c))
            if (n1r,n1c) == food:
                sc1 += 1; gr1 += 3; food = _place_food(set(s1)|set(s2))
                step_ms = max(100, step_ms-5)
            elif gr1 > 0: gr1 -= 1
            else: s1.pop()

            # Posun P2 vpřed, případné sežrání jídla a růst
            s2.insert(0,(n2r,n2c))
            if (n2r,n2c) == food:
                sc2 += 1; gr2 += 3; food = _place_food(set(s1)|set(s2))
                step_ms = max(100, step_ms-5)
            elif gr2 > 0: gr2 -= 1
            else: s2.pop()

        # --- Vykreslení obou hadů a jídla ---
        clear()
        if (ticks_ms() // 125) % 2 == 0:
            set_pixel(food[0], food[1], 2)
        # Had hráče 1
        for i,(r,c) in enumerate(s1):
            set_pixel(r, c, 2 if i==0 else 1)

        # Had hráče 2 — hlava bliká, aby šlo hady od sebe rozeznat
        s1_set = set(s1)   # spočítáno jen jednou (dřív se počítalo pro každý bod zvlášť = pomalé)
        p2_head_on = (ticks_ms() // 200) % 2 == 0
        for i,(r,c) in enumerate(s2):
            if i == 0:
                if p2_head_on: set_pixel(r, c, 2)
            elif (r,c) not in s1_set:   # tělo P2 kreslíme, jen když se nepřekrývá s P1
                set_pixel(r, c, 1)
        show()

# ---------------------------------------------------------------------------
# Sdílený pomocník pro multiplayer PAINT / LIFE
# ---------------------------------------------------------------------------
def _mp_detect_peer(ring, wait_ms=1500):
    """
    Krátce na začátku zkontroluje, jestli něco přichází přes řetězec.
    Pokud ano, hraje se ve dvou (vrátí ID druhého zařízení); pokud po
    celou dobu nic nepřijde, hra pokračuje přesně jako pro jednoho
    hráče - žádná UART data = žádná změna chování.
    """
    if ring is None:
        return None
    clear()
    draw_text("...", col_start=(COLS - text_width("...")) // 2, row_start=6, level=1)
    show()
    t = utime.ticks_ms()
    while utime.ticks_diff(utime.ticks_ms(), t) < wait_ms:
        if ring.get_state():
            return list(ring.get_state().keys())[0]
        utime.sleep_ms(50)
    return None

# ---------------------------------------------------------------------------
# Game of Life
# ---------------------------------------------------------------------------
def run_life(enc=None, current=None, ring=None):
    """
    Conwayova hra Life. Na začátku krátce zkontroluje, jestli něco
    přichází přes řetězec - pokud ano, hraje se ve dvou (druhý kurzor
    podle přeposlaných tlačítek, stejné sdílené plátno); pokud ne,
    běží to úplně stejně jako pro jednoho hráče.

      Šipky        = pohyb kurzoru (jen když je simulace pozastavená;
                     dá se i podržet, pohyb se sám opakuje)
      Šipky + Fire2
      podrženo zároveň = kreslí tahem (každá nová buňka rovnou ožije)
      Fire2        = přepnout buňku pod kurzorem živá/mrtvá (jen v pauze)
      Fire1        = pauza / běh - VŽDY JEN LOKÁLNĚ: druhé zařízení
                     může svým Fire1 přepínat jen svoje buňky (Fire2),
                     ne pauzu - jinak by si obě zařízení mohla navzájem
                     přebíjet běh/pauzu, protože pauza sama o sobě
                     nejde (a ani nemá smysl) přenášet po síti.
      Enkodér      = rychlost simulace (1-50 generací/s)
      Stisk enkodéru = odchod do menu (jen lokálně)

    Simulace používá řádkové součty (tři sousední sloupce najednou)
    místo počítání 8 sousedů zvlášť pro každou buňku - výrazně méně
    operací (hlavně mnohem míň modulo a voláním funkcí), takže běží
    podstatně rychleji než předchozí "naivní" verze, která si na
    nastavení 40/s reálně vzala spíš 10/s.
    """
    remote_id   = _mp_detect_peer(ring)
    multiplayer = remote_id is not None

    board = bytearray(ROWS * COLS)
    nxt   = bytearray(ROWS * COLS)
    hsum  = bytearray(ROWS * COLS)

    def step():
        # Krok 1: vodorovný součet tří sloupců vedle sebe pro každou
        # buňku (obtáčí se dokola na okrajích řádku).
        for r in range(ROWS):
            off = r * COLS
            hsum[off] = board[off+COLS-1] + board[off] + board[off+1]
            for c in range(1, COLS - 1):
                hsum[off+c] = board[off+c-1] + board[off+c] + board[off+c+1]
            hsum[off+COLS-1] = board[off+COLS-2] + board[off+COLS-1] + board[off]

        # Krok 2: pro každou buňku sečíst řádkové součty řádku nad,
        # vlastního a pod, odečíst sebe sama = počet sousedů.
        for r in range(ROWS):
            off  = r * COLS
            offu = ((r - 1) % ROWS) * COLS
            offd = ((r + 1) % ROWS) * COLS
            for c in range(COLS):
                n = hsum[offu+c] + hsum[off+c] + hsum[offd+c] - board[off+c]
                nxt[off+c] = 1 if (n == 3 or (board[off+c] and n == 2)) else 0

        board[:] = nxt

    def draw(cursor_r, cursor_c, show_cursor, rcursor_r=None, rcursor_c=None, show_rcursor=False):
        clear()
        for r in range(ROWS):
            off = r * COLS
            for c in range(COLS):
                if board[off+c]:
                    set_pixel(r, c, 2)
        if show_cursor:
            set_pixel(cursor_r, cursor_c, 1 if board[cursor_r*COLS+cursor_c] else 2)
        if show_rcursor:
            set_pixel(rcursor_r, rcursor_c, 1 if board[rcursor_r*COLS+rcursor_c] else 2)
        show()

    # Náhodná počáteční deska
    for i in range(ROWS * COLS):
        board[i] = 1 if _randint(0, 2) == 0 else 0

    cursor_r = ROWS // 2
    cursor_c = COLS // 2
    rcursor_r = ROWS // 2
    rcursor_c = COLS // 2 + 4 if multiplayer else COLS // 2
    running  = True   # rovnou po startu běží
    speed    = 10     # generací za sekundu

    btns = Buttons()
    last_step  = utime.ticks_ms()
    last_blink = utime.ticks_ms()
    cursor_vis = True

    REPEAT_DELAY = 350   # ms než se podržená šipka začne sama opakovat
    REPEAT_RATE  = 90    # ms mezi jednotlivými opakováními
    held_since  = {'up': 0, 'down': 0, 'left': 0, 'right': 0}
    rheld_since = {'up': 0, 'down': 0, 'left': 0, 'right': 0}

    remote_prev = {'up': False, 'down': False, 'left': False,
                   'right': False, 'fire1': False, 'fire2': False}

    if enc:
        enc.set_range(1, 50, wrap=False)
        enc.value = speed

    while True:
        if check_test_mode():
            continue

        now = utime.ticks_ms()

        if enc:
            d = enc.delta()
            if d: speed = enc.value

        # Blikání kurzoru (500 ms)
        if utime.ticks_diff(now, last_blink) >= 500:
            last_blink = now
            cursor_vis = not cursor_vis

        cur, edge = btns.poll()
        if not running:
            # Šipky se dají podržet (opakují se samy) - a když se
            # přitom drží i Fire2, každá nová buňka se rovnou oživí
            # (usnadňuje kreslení tahem)
            for name, dr, dc in (('up', -1, 0), ('down', 1, 0),
                                 ('left', 0, -1), ('right', 0, 1)):
                moved = False
                if edge[name]:
                    cursor_r = (cursor_r + dr) % ROWS
                    cursor_c = (cursor_c + dc) % COLS
                    held_since[name] = now; cursor_vis = True; last_blink = now
                    moved = True
                elif cur[name] and utime.ticks_diff(now, held_since[name]) >= REPEAT_DELAY:
                    cursor_r = (cursor_r + dr) % ROWS
                    cursor_c = (cursor_c + dc) % COLS
                    held_since[name] = now - (REPEAT_DELAY - REPEAT_RATE)
                    cursor_vis = True; last_blink = now
                    moved = True
                elif not cur[name]:
                    held_since[name] = 0
                if moved and cur['fire2']:
                    board[cursor_r * COLS + cursor_c] = 1
            if edge['fire2']:
                idx = cursor_r * COLS + cursor_c
                board[idx] = 1 - board[idx]

        # Pauza/běh - VŽDY jen podle lokálního Fire1, nikdy podle
        # přeposlaného stavu druhého zařízení (viz vysvětlení nahoře).
        if edge['fire1']:
            running = not running
            last_step = now

        # --- Druhé zařízení (pokud je připojené) ---
        if multiplayer:
            ring.send_buttons(TokenRing.buttons_byte(
                cur['fire1'], cur['right'], cur['left'],
                cur['down'], cur['up'], cur['fire2']))
            remote = ring.get_state().get(remote_id, 0)
            rb = TokenRing.unpack_buttons(remote)
            remote_edge = {k: rb[k] and not remote_prev[k] for k in rb}
            remote_prev = rb

            if not running:
                for name, dr, dc in (('up', -1, 0), ('down', 1, 0),
                                     ('left', 0, -1), ('right', 0, 1)):
                    rmoved = False
                    if remote_edge[name]:
                        rcursor_r = (rcursor_r + dr) % ROWS
                        rcursor_c = (rcursor_c + dc) % COLS
                        rheld_since[name] = now
                        rmoved = True
                    elif rb[name] and utime.ticks_diff(now, rheld_since[name]) >= REPEAT_DELAY:
                        rcursor_r = (rcursor_r + dr) % ROWS
                        rcursor_c = (rcursor_c + dc) % COLS
                        rheld_since[name] = now - (REPEAT_DELAY - REPEAT_RATE)
                        rmoved = True
                    elif not rb[name]:
                        rheld_since[name] = 0
                    if rmoved and rb['fire2']:
                        board[rcursor_r * COLS + rcursor_c] = 1
                if remote_edge['fire2']:
                    idx = rcursor_r * COLS + rcursor_c
                    board[idx] = 1 - board[idx]

        if enc and enc.was_pressed():
            return

        if running:
            step_ms = 1000 // speed
            if utime.ticks_diff(now, last_step) >= step_ms:
                last_step = now
                step()

        draw(cursor_r, cursor_c, not running and cursor_vis,
             rcursor_r, rcursor_c, multiplayer and not running and cursor_vis)
        utime.sleep_ms(20)

# ---------------------------------------------------------------------------
# Pong — jeden hráč (BREAKOUT — cihličky nahoře, pálka dole)
# ---------------------------------------------------------------------------
def run_pong_1p(enc=None, current=None):
    """
    Jednohráčský breakout/pong.
      Pálka dole, ovládaná šipkami vlevo/vpravo nebo enkodérem.
      Míček se odráží od stěn a pálky, cihličky nahoře mizí při zásahu.
      Fire1/Fire2 = odpálit míček (z pauzy); druhý stisk = konec.
    """
    SLED_W  = 6
    SLED_ROW = ROWS - 1
    BRICK_ROWS = 4
    BRICK_COLS = COLS

    bricks = [[1] * BRICK_COLS for _ in range(BRICK_ROWS)]
    total_bricks = BRICK_ROWS * BRICK_COLS

    sled_col = (COLS - SLED_W) // 2
    ball_r   = SLED_ROW - 1
    ball_c   = sled_col + SLED_W // 2
    # Rychlost míčku (×2 pevná řádová čárka pro plynulejší pohyb)
    bv_r = -2
    bv_c =  2
    ball_fr = ball_r * 2
    ball_fc = ball_c * 2

    score    = 0
    launched = False
    speed_ms = 80

    if enc:
        enc.set_range(0, COLS - SLED_W, wrap=False)
        enc.value = sled_col

    btns = Buttons()
    last_step = utime.ticks_ms()

    while True:
        if check_test_mode():
            continue

        now = utime.ticks_ms()

        if enc:
            d = enc.delta()
            if d: sled_col = enc.value
        if btn_left()  and sled_col > 0:
            sled_col -= 1
            if enc: enc.value = sled_col
        if btn_right() and sled_col < COLS - SLED_W:
            sled_col += 1
            if enc: enc.value = sled_col

        cur, edge = btns.poll()
        if edge['fire1'] or edge['fire2']:
            if not launched:
                launched = True
            else:
                return

        if enc and enc.was_pressed():
            return

        if launched and utime.ticks_diff(now, last_step) >= speed_ms:
            last_step = now

            ball_fr += bv_r
            ball_fc += bv_c
            br = ball_fr // 2
            bc = ball_fc // 2

            if ball_fc < 0:
                ball_fc = 0; bv_c = abs(bv_c)
            elif ball_fc >= COLS * 2:
                ball_fc = (COLS - 1) * 2; bv_c = -abs(bv_c)

            if ball_fr < 0:
                ball_fr = 0; bv_r = abs(bv_r)

            if 0 <= br < BRICK_ROWS and 0 <= bc < BRICK_COLS:
                if bricks[br][bc]:
                    bricks[br][bc] = 0
                    score += 1
                    bv_r = -bv_r
                    speed_ms = max(30, speed_ms - 1)

            if br == SLED_ROW - 1 and sled_col <= bc < sled_col + SLED_W:
                bv_r = -abs(bv_r)
                rel = bc - sled_col - SLED_W // 2
                bv_c = rel if rel != 0 else (1 if bv_c > 0 else -1)
                bv_c = max(-3, min(3, bv_c))
                if bv_c == 0: bv_c = 1

            br = ball_fr // 2
            bc = ball_fc // 2

            if br >= ROWS:   # míček proletěl pálkou = konec
                _end_game_flash(score)
                return

            if score >= total_bricks:   # všechny cihličky zbořeny = výhra
                _end_game_flash(score, 5, 50, 50)
                return

        clear()
        for r in range(BRICK_ROWS):
            for c in range(BRICK_COLS):
                if bricks[r][c]:
                    set_pixel(r, c, 2 if r < 2 else 1)
        for i in range(SLED_W):
            set_pixel(SLED_ROW, sled_col + i, 2)
        br = ball_fr // 2
        bc = ball_fc // 2
        if 0 <= br < ROWS and 0 <= bc < COLS:
            set_pixel(br, bc, 2)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Pong — dva hráči (přes token ring)
# ---------------------------------------------------------------------------
def run_pong_2p(enc=None, current=None, ring=None):
    """
    2hráčský pong pro řetězec dvou zařízení. Tohle (poslední/hrací)
    zařízení vždy ovládá dolní pálku (P1) místními šipkami a horní
    pálku (P2) podle stavu tlačítek, který přes řetězec (FWD/hop)
    posílá první zařízení, běžící v BTN TEST. Míček počítá a zobrazuje
    jen tohle zařízení - druhé jen posílá svůj stav tlačítek dál, samo
    nic nezobrazuje ani nepočítá.

    Žádné ID zařízení se nepoužívá - hru vždy hraje a zobrazuje ten,
    kdo tuhle funkci spustí, druhé zařízení je automaticky P2 podle
    toho, co posílá řetězcem.

      Šipky vlevo/vpravo = pohyb dolní pálky (P1, lokální)
      (druhé zařízení ovládá horní pálku P2 svými vlastními šipkami)
      Stisk enkodéru = konec hry

    Před spuštěním míčku je 3s odpočet, během kterého jsou obě pálky
    už vidět a dají se hýbat.
    """
    if ring is None:
        clear()
        draw_text("NO RING", col_start=0, row_start=5, level=2)
        show(); utime.sleep_ms(2000)
        return

    # Počkáme, jestli se v řetězci objeví druhé (přeposílající) zařízení.
    clear()
    draw_text("WAIT", col_start=4, row_start=5, level=2)
    show()
    t = utime.ticks_ms()
    while not ring.get_state() and utime.ticks_diff(utime.ticks_ms(), t) < 5000:
        utime.sleep_ms(100)
    if not ring.get_state():
        clear()
        draw_text("NO P2", col_start=0, row_start=5, level=2)
        show(); utime.sleep_ms(2000)
        return
    rem_id = list(ring.get_state().keys())[0]

    SLED_W = 6
    s1_col = (COLS - SLED_W) // 2   # dolní pálka P1 - vždy lokální
    s2_col = (COLS - SLED_W) // 2   # horní pálka P2 - podle FWD dat

    def _sync_paddle():
        """P1 se hýbe podle místních šipek, P2 podle toho, co poslední
        zařízení v řetězci přeposlalo jako stav tlačítek prvního
        zařízení (běžícího v BTN TEST)."""
        nonlocal s1_col, s2_col
        if btn_left()  and s1_col > 0:
            s1_col -= 1
        if btn_right() and s1_col < COLS - SLED_W:
            s1_col += 1

        rb = TokenRing.unpack_buttons(ring.get_state().get(rem_id, 0))
        if rb['left']  and s2_col > 0:
            s2_col -= 1
        if rb['right'] and s2_col < COLS - SLED_W:
            s2_col += 1

    def _draw_paddles():
        for i in range(SLED_W):
            set_pixel(ROWS-1, s1_col + i, 2)
            set_pixel(0,      s2_col + i, 2)

    # --- Odpočet - pálky už jsou vidět a dají se hýbat ---
    for n in (3, 2, 1):
        t_n = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), t_n) < 800:
            if check_test_mode():
                continue
            _sync_paddle()
            clear()
            _draw_paddles()
            draw_text(str(n), col_start=(COLS - text_width(str(n))) // 2,
                       row_start=6, level=2)
            show()
            utime.sleep_ms(20)
        clear(); show(); utime.sleep_ms(60)

    ball_fr = (ROWS // 2) * 2
    ball_fc = (COLS // 2) * 2
    bv_r = -2
    bv_c = 2

    sc1 = 0; sc2 = 0
    WIN_SCORE = 5
    speed_ms  = 60
    launched  = True
    serve_at  = None   # čas, kdy se má míček po bodu znovu spustit

    last_step = utime.ticks_ms()

    while True:
        if check_test_mode():
            continue

        now = utime.ticks_ms()

        _sync_paddle()

        if enc and enc.was_pressed():
            return

        # Míček po bodu znovu spustit po krátké pauze
        if not launched and serve_at is not None and utime.ticks_diff(now, serve_at) >= 0:
            launched = True
            serve_at = None

        if launched and utime.ticks_diff(now, last_step) >= speed_ms:
            last_step = now

            ball_fr += bv_r
            ball_fc += bv_c
            br = ball_fr // 2
            bc = ball_fc // 2

            if ball_fc < 0:
                ball_fc = 0; bv_c = abs(bv_c)
            elif ball_fc >= COLS * 2:
                ball_fc = (COLS-1)*2; bv_c = -abs(bv_c)

            # Dolní pálka (P1, řádek ROWS-1)
            if br >= ROWS - 1:
                if s1_col <= bc < s1_col + SLED_W:
                    bv_r = -abs(bv_r)
                    rel  = bc - s1_col - SLED_W//2
                    bv_c = rel if rel != 0 else (1 if bv_c>0 else -1)
                    bv_c = max(-3, min(3, bv_c)) or 1
                elif br >= ROWS:
                    sc2 += 1
                    ball_fr = (ROWS//2)*2; ball_fc = (COLS//2)*2
                    bv_r = 2; launched = False; serve_at = now + 800

            # Horní pálka (P2, řádek 0)
            if br <= 0:
                if s2_col <= bc < s2_col + SLED_W:
                    bv_r = abs(bv_r)
                    rel  = bc - s2_col - SLED_W//2
                    bv_c = rel if rel != 0 else (1 if bv_c>0 else -1)
                    bv_c = max(-3, min(3, bv_c)) or 1
                elif br < 0:
                    sc1 += 1
                    ball_fr = (ROWS//2)*2; ball_fc = (COLS//2)*2
                    bv_r = -2; launched = False; serve_at = now + 800

            if sc1 >= WIN_SCORE or sc2 >= WIN_SCORE:
                blink_all()
                clear()
                if sc1 >= WIN_SCORE:
                    draw_text("P1 WIN", col_start=0, row_start=5, level=2)
                else:
                    draw_text("P2 WIN", col_start=0, row_start=5, level=2)
                show(); utime.sleep_ms(3000)
                return

        clear()
        _draw_paddles()
        br = ball_fr // 2
        bc = ball_fc // 2
        if 0 <= br < ROWS and 0 <= bc < COLS:
            set_pixel(br, bc, 2)
        if sc1 > 0:
            for i in range(min(sc1, 5)):
                set_pixel(ROWS-2, i*2, 1)
        if sc2 > 0:
            for i in range(min(sc2, 5)):
                set_pixel(1, COLS-1-i*2, 1)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Flappy — uhýbací hra
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Flappy — obrazovka nastavení obtížnosti
# ---------------------------------------------------------------------------
_FLAPPY_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
# speed_ms/min_ms = počáteční a nejrychlejší (nejnižší) interval posunu
# barriers        = jestli se v mezerách objevují zničitelné překážky
_FLAPPY_DIFF_PARAMS = [
    {'speed_ms': 110, 'min_ms': 55, 'barriers': False},
    {'speed_ms': 80,  'min_ms': 30, 'barriers': False},
    {'speed_ms': 75,  'min_ms': 28, 'barriers': True},
]

def _flappy_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit a spustit hru."""
    return _pick_option(enc, "FLAPPY", _FLAPPY_DIFF_NAMES, 1)

def _flappy_score_meter(score):
    """
    Vykreslí skóre jako pruh přes celou šířku displeje:
    - nejdřív se řádek zaplňuje bod po bodu na nízký jas,
    - jakmile je celý řádek plný, začne se stejným způsobem
      "přesvítit" na plný jas,
    - jakmile je celý řádek na plný jas, začne se stejně plnit řádek pod ním.
    """
    row_capacity = 2 * COLS   # kolik bodů skóre potřeba na kompletní řádek (obě fáze)
    row = min(score // row_capacity, ROWS - 1)
    rem = score - row * row_capacity

    for r in range(row):
        for c in range(COLS):
            set_pixel(r, c, 2)

    if rem <= COLS:
        for c in range(rem):
            set_pixel(row, c, 1)
    else:
        bright_count = rem - COLS
        for c in range(COLS):
            set_pixel(row, c, 2 if c < bright_count else 1)

# ---------------------------------------------------------------------------
# Flappy — hra
# ---------------------------------------------------------------------------
def run_flappy(enc=None, current=None):
    """
    Hra ve stylu Flappy Bird.
      Šipky nahoru/dolů = přímé ovládání hráče (bez fyziky/gravitace)
      Překážky se sunou zprava doleva, je potřeba trefit mezeru
      Enkodér = rychlost posunu
      Fire1/Fire2 = výstřel (v HARD módu ničí zničitelné překážky)
      Stisk enkodéru = konec

    Na začátku je obrazovka s výběrem obtížnosti a pak 3s odpočet -
    hra se spustí sama, není třeba mačkat fire pro start.
    Skóre nahoře se zobrazuje jako pruh přes celou šířku: nejdřív na
    nízký jas, pak (po zaplnění řádku) přesvícený na plný jas, pak se
    stejně plní další řádek pod ním.
    HARD mód navíc obsahuje v některých mezerách zničitelné (tence
    zobrazené) překážky - je potřeba je včas sestřelit, jinak srážka
    s nimi počítá stejně jako náraz do zdi.
    """
    diff = _flappy_setup(enc)
    P = _FLAPPY_DIFF_PARAMS[diff]

    PLAYER_COL = 4
    GAP_H      = 5
    OBS_W      = 2
    OBS_SPACING = 12
    BULLET_MS  = 25

    player_row = ROWS // 2
    score      = 0
    speed_ms   = P['speed_ms']

    if enc:
        enc.set_range(20, 200, wrap=False)
        enc.value = speed_ms

    def _make_obstacle(col):
        gap_top = _randint(1, ROWS - GAP_H - 1)
        obs = {'col': col, 'gap': gap_top, 'barrier_row': None, 'barrier_alive': False}
        if P['barriers'] and _randint(0, 1) == 0:
            obs['barrier_row']   = _randint(gap_top, gap_top + GAP_H - 1)
            obs['barrier_alive'] = True
        return obs

    obstacles = [_make_obstacle(COLS + i * OBS_SPACING) for i in range(3)]
    bullet = None   # [row, col] nebo None

    btns = Buttons()
    countdown()

    last_step   = utime.ticks_ms()
    last_move   = utime.ticks_ms()
    last_bullet = utime.ticks_ms()
    MOVE_MS     = 80

    while True:
        if check_test_mode():
            continue

        now = utime.ticks_ms()

        if enc:
            d = enc.delta()
            if d: speed_ms = enc.value

        if utime.ticks_diff(now, last_move) >= MOVE_MS:
            if btn_up() and player_row > 0:
                player_row -= 1
                last_move = now
            elif btn_down() and player_row < ROWS - 1:
                player_row += 1
                last_move = now

        cur, edge = btns.poll()
        if (edge['fire1'] or edge['fire2']) and bullet is None:
            bullet = [player_row, PLAYER_COL + 1]

        if enc and enc.was_pressed():
            return

        # --- Pohyb střely (vodorovně doprava, ničí zničitelné překážky) ---
        if bullet is not None and utime.ticks_diff(now, last_bullet) >= BULLET_MS:
            last_bullet = now
            bullet[1] += 1
            if bullet[1] >= COLS:
                bullet = None
            else:
                for obs in obstacles:
                    if (obs['barrier_alive'] and bullet is not None
                            and obs['barrier_row'] == bullet[0]
                            and obs['col'] <= bullet[1] < obs['col'] + OBS_W):
                        obs['barrier_alive'] = False
                        bullet = None
                        break

        if utime.ticks_diff(now, last_step) >= speed_ms:
            last_step = now
            for obs in obstacles:
                obs['col'] -= 1
                if obs['col'] + OBS_W < 0:
                    new = _make_obstacle(COLS)
                    obs['col'] = new['col']; obs['gap'] = new['gap']
                    obs['barrier_row'] = new['barrier_row']
                    obs['barrier_alive'] = new['barrier_alive']
                    score += 1
                    speed_ms = max(P['min_ms'], speed_ms - 1)
                    if enc: enc.value = speed_ms

            for obs in obstacles:
                if obs['col'] <= PLAYER_COL < obs['col'] + OBS_W:
                    hit_wall    = not (obs['gap'] <= player_row < obs['gap'] + GAP_H)
                    hit_barrier = (obs['barrier_alive'] and obs['barrier_row'] == player_row)
                    if hit_wall or hit_barrier:
                        _end_game_flash(score)
                        return

        clear()
        for obs in obstacles:
            for oc in range(OBS_W):
                c2 = obs['col'] + oc
                if 0 <= c2 < COLS:
                    for r in range(ROWS):
                        if not (obs['gap'] <= r < obs['gap'] + GAP_H):
                            set_pixel(r, c2, 2 if oc == 0 else 1)
                    if obs['barrier_alive']:
                        set_pixel(obs['barrier_row'], c2, 1)
        if bullet is not None:
            set_pixel(bullet[0], bullet[1], 2)
        set_pixel(player_row, PLAYER_COL, 2)
        _flappy_score_meter(score)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Galaga — obrazovka nastavení obtížnosti / MLG módu před hrou
# ---------------------------------------------------------------------------
_GALAGA_DIFF_NAMES = ["EASY", "NORMAL", "HARD"]
# bullet_ms      = interval pohybu hráčovy střely (nižší = rychlejší)
# dive_ms        = interval pohybu střemhlavého nepřítele (nižší = rychlejší let)
# sway_ms        = interval komíhání formace (nižší = rychlejší)
# dive_chk_ms    = jak často se zkouší spustit nový střemhlavý útok
# fire_chk_ms    = jak často se zkouší vypálit nepřátelská střela
# fire_chance    = 1 ku N šance při každém pokusu (nižší N = víc střelby)
# efire_ms       = interval pohybu nepřátelské střely
_GALAGA_DIFF_PARAMS = [
    {'bullet_ms': 65, 'dive_ms': 110, 'sway_ms': 400,
     'dive_chk_ms': 1500, 'fire_chk_ms': 2600, 'fire_chance': 5, 'efire_ms': 70},
    {'bullet_ms': 45, 'dive_ms': 70,  'sway_ms': 300,
     'dive_chk_ms': 900,  'fire_chk_ms': 1600, 'fire_chance': 3, 'efire_ms': 55},
    {'bullet_ms': 30, 'dive_ms': 45,  'sway_ms': 220,
     'dive_chk_ms': 600,  'fire_chk_ms': 900,  'fire_chance': 2, 'efire_ms': 35},
]

def _galaga_setup(enc=None):
    """
    Obrazovka před hrou.
      Šipky nahoru/dolů nebo enkodér = obtížnost (EASY / NORMAL / HARD)
      Šipky vlevo/vpravo             = zapnout/vypnout MLG mód
      Fire1/Fire2 nebo stisk enkodéru = potvrdit a spustit hru
    Vrátí (diff_index, mlg_mode).
    """
    diff = 1
    mlg  = False
    btns = Buttons()
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if check_test_mode():
            continue
        cur, edge = btns.poll()

        if edge['up']:   diff = (diff - 1) % 3
        if edge['down']: diff = (diff + 1) % 3
        if edge['left'] or edge['right']:
            mlg = not mlg
        if enc:
            d = enc.delta()
            if d: diff = (diff + (1 if d > 0 else -1)) % 3

        if edge['fire1'] or edge['fire2'] or (enc and enc.was_pressed()):
            wait_no_buttons(enc)
            return diff, mlg

        clear()
        draw_text("GALAGA", col_start=(COLS - text_width("GALAGA")) // 2,
                   row_start=0, level=1)
        dname = _GALAGA_DIFF_NAMES[diff]
        draw_text(dname, col_start=(COLS - text_width(dname)) // 2,
                   row_start=6, level=2)
        mtxt = "MLG " + ("ON" if mlg else "OFF")
        draw_text(mtxt, col_start=(COLS - text_width(mtxt)) // 2,
                   row_start=11, level=2 if mlg else 1)
        show()
        utime.sleep_ms(20)

# ---------------------------------------------------------------------------
# Galaga — zjednodušená verze
# ---------------------------------------------------------------------------
def run_galaga(enc=None, current=None):
    """
    Zjednodušená Galaga. Formace nepřátel nahoře se pomalu komíhá ze
    strany na stranu; občas se jeden nepřítel odpojí a zaútočí přímým
    střemhlavým letem dolů na hráče, a formace také občas střílí dolů.
    Hráč střílí nahoru (jeden aktivní výstřel naráz). Zásah do lodi
    (potápěčem nebo nepřátelskou střelou) = konec hry — skóre je
    celkový počet sestřelených nepřátel (potápěč = 2 body, nepřítel ve
    formaci = 1 bod). Po vyčištění formace se objeví další vlna.

      Šipky vlevo/vpravo nebo enkodér = pohyb lodi
      Fire1 / Fire2                  = střelba
      Podržení Fire 3s               = nabije a vypálí megastřelu (3×3,
                                        výbuch 5×5) - loď se přitom
                                        nemůže hýbat
      Stisk enkodéru                 = konec (vrátí aktuální skóre)

    Na začátku je obrazovka s výběrem obtížnosti (rychlost střel a letu,
    četnost nepřátelské palby) a MLG módu (šířka lodi se náhodně mění
    při každém sestřelu).

    Poznámka: pro jednoduchost útočí vždy jen jeden nepřítel naráz a
    útočí přímo dolů (bez zatáčení do strany).
    """
    diff, mlg = _galaga_setup(enc)
    P = _GALAGA_DIFF_PARAMS[diff]

    PLAYER_ROW = ROWS - 1
    PLAYER_W   = 3
    MLG_MIN_W, MLG_MAX_W = 1, 8

    EN_ROWS = [1, 3, 5]
    EN_COLS = [2, 6, 10, 14, 18, 22, 26, 30]
    EN_MIN, EN_MAX = min(EN_COLS), max(EN_COLS)

    enemies = []
    for r in EN_ROWS:
        for c in EN_COLS:
            enemies.append({'r0': r, 'c0': c, 'alive': True,
                             'diving': False, 'dr': r, 'dc': c})

    player_col = (COLS - PLAYER_W) // 2
    if enc:
        enc.set_range(0, COLS - PLAYER_W, wrap=False)
        enc.value = player_col

    bullet = None        # [row, col] nebo None - normální výstřel
    mega_bullet = None   # [row, col] nebo None - megastřela (3x3)

    fire_press_start   = None
    mega_fired_this_hold = False

    sway_offset = 0
    sway_dir    = 1

    diver = None    # index do `enemies`, nebo None (jen jeden potápěč naráz)
    enemy_bullets = []   # seznam [row, col] - nepřátelské střely padající dolů

    def _kill_enemy(idx, was_diving):
        """Označí nepřítele za mrtvého, připočte skóre a v MLG módu
        náhodně přeškáluje šířku lodi."""
        nonlocal PLAYER_W, player_col, diver, score
        enemies[idx]['alive'] = False
        if was_diving:
            diver = None
        score += 2 if was_diving else 1
        if mlg:
            PLAYER_W = _randint(MLG_MIN_W, MLG_MAX_W)
            player_col = max(0, min(player_col, COLS - PLAYER_W))
            if enc:
                enc.set_range(0, COLS - PLAYER_W, wrap=False)
                enc.value = player_col

    score = 0
    btns  = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    last_bullet    = ticks_ms()
    last_mega      = ticks_ms()
    last_sway      = ticks_ms()
    last_dive_chk  = ticks_ms()
    last_dive_step = ticks_ms()
    last_fire_chk  = ticks_ms()
    last_efire     = ticks_ms()

    while True:
        if check_test_mode():
            continue

        now = ticks_ms()
        cur, edge = btns.poll()
        firing_held = cur['fire1'] or cur['fire2']

        # --- Nabíjení megastřely / uzamčení pohybu při podržení Fire ---
        if firing_held:
            if fire_press_start is None:
                fire_press_start = now
                mega_fired_this_hold = False
            elif (not mega_fired_this_hold and mega_bullet is None and
                  ticks_diff(now, fire_press_start) >= 3000):
                mega_bullet = [PLAYER_ROW - 2,
                                max(1, min(COLS - 2, player_col + PLAYER_W // 2))]
                mega_fired_this_hold = True
        else:
            fire_press_start = None

        # --- Ovládání lodi (uzamčeno, dokud se drží Fire kvůli megastřele) ---
        if not firing_held:
            if enc:
                d = enc.delta()
                if d: player_col = enc.value
            if btn_left()  and player_col > 0:
                player_col -= 1
                if enc: enc.value = player_col
            if btn_right() and player_col < COLS - PLAYER_W:
                player_col += 1
                if enc: enc.value = player_col

        if (edge['fire1'] or edge['fire2']) and bullet is None:
            bullet = [PLAYER_ROW - 1, player_col + PLAYER_W // 2]

        if enc and enc.was_pressed():
            return score

        # --- Komíhání formace ze strany na stranu ---
        if ticks_diff(now, last_sway) >= P['sway_ms']:
            last_sway = now
            new_offset = sway_offset + sway_dir
            if EN_MIN + new_offset < 0 or EN_MAX + new_offset > COLS - 1:
                sway_dir = -sway_dir
                new_offset = sway_offset + sway_dir
            sway_offset = new_offset

        # --- Občas se jeden nepřítel odpojí a zaútočí střemhlav ---
        if diver is None and ticks_diff(now, last_dive_chk) >= P['dive_chk_ms']:
            last_dive_chk = now
            if _randint(0, 2) == 0:   # cca 1 pokus ze 3
                candidates = [i for i, e in enumerate(enemies)
                              if e['alive'] and not e['diving']]
                if candidates:
                    i = candidates[_randint(0, len(candidates) - 1)]
                    e = enemies[i]
                    e['diving'] = True
                    e['dr'] = e['r0']
                    e['dc'] = e['c0'] + sway_offset
                    diver = i

        # --- Pohyb útočícího nepřítele ---
        if diver is not None and ticks_diff(now, last_dive_step) >= P['dive_ms']:
            last_dive_step = now
            e = enemies[diver]
            e['dr'] += 1
            if e['dr'] == PLAYER_ROW and player_col <= e['dc'] < player_col + PLAYER_W:
                return score   # zásah do lodi = konec hry
            if e['dr'] > PLAYER_ROW:
                e['diving'] = False   # unikl dolů - vrátí se zpátky do formace
                diver = None

        # --- Formace občas střílí dolů ---
        if ticks_diff(now, last_fire_chk) >= P['fire_chk_ms']:
            last_fire_chk = now
            if _randint(0, P['fire_chance'] - 1) == 0:
                candidates = [i for i, e in enumerate(enemies)
                              if e['alive'] and not e['diving']]
                if candidates:
                    i = candidates[_randint(0, len(candidates) - 1)]
                    e = enemies[i]
                    enemy_bullets.append([e['r0'] + 1, e['c0'] + sway_offset])

        # --- Pohyb nepřátelských střel ---
        if ticks_diff(now, last_efire) >= P['efire_ms']:
            last_efire = now
            still = []
            for eb in enemy_bullets:
                eb[0] += 1
                if eb[0] == PLAYER_ROW and player_col <= eb[1] < player_col + PLAYER_W:
                    return score   # zásah nepřátelskou střelou = konec hry
                if eb[0] < ROWS:
                    still.append(eb)
            enemy_bullets = still

        # --- Pohyb normální střely ---
        if bullet is not None and ticks_diff(now, last_bullet) >= P['bullet_ms']:
            last_bullet = now
            bullet[0] -= 1
            if bullet[0] < 0:
                bullet = None
            else:
                br, bc = bullet
                hit = None
                for i, e in enumerate(enemies):
                    if not e['alive']:
                        continue
                    er, ec = (e['dr'], e['dc']) if e['diving'] else (e['r0'], e['c0'] + sway_offset)
                    if er == br and ec == bc:
                        hit = i
                        break
                if hit is not None:
                    _kill_enemy(hit, enemies[hit]['diving'])
                    bullet = None

        # --- Pohyb megastřely (3×3, výbuch 5×5) ---
        if mega_bullet is not None and ticks_diff(now, last_mega) >= P['bullet_ms']:
            last_mega = now
            mega_bullet[0] -= 1
            if mega_bullet[0] < 1:
                mega_bullet = None
            else:
                mr, mc = mega_bullet
                hit_r = hit_c = None
                for e in enemies:
                    if not e['alive']:
                        continue
                    er, ec = (e['dr'], e['dc']) if e['diving'] else (e['r0'], e['c0'] + sway_offset)
                    if abs(er - mr) <= 1 and abs(ec - mc) <= 1:
                        hit_r, hit_c = er, ec
                        break
                if hit_r is not None:
                    # Výbuch 5x5 kolem zásahu - zabije všechny nepřátele uvnitř
                    for i, e in enumerate(enemies):
                        if not e['alive']:
                            continue
                        er, ec = (e['dr'], e['dc']) if e['diving'] else (e['r0'], e['c0'] + sway_offset)
                        if abs(er - hit_r) <= 2 and abs(ec - hit_c) <= 2:
                            _kill_enemy(i, e['diving'])
                    # Krátký záblesk výbuchu
                    er0 = max(0, hit_r - 2); ec0 = max(0, hit_c - 2)
                    ew  = min(COLS, hit_c + 3) - ec0
                    eh  = min(ROWS, hit_r + 3) - er0
                    fill_rect(er0, ec0, ew, eh, 2)
                    show(); utime.sleep_ms(150)
                    mega_bullet = None

        # --- Nová vlna, jakmile jsou všichni sestřeleni ---
        if not any(e['alive'] for e in enemies):
            clear()
            draw_text("WAVE", col_start=4, row_start=5, level=2)
            show(); utime.sleep_ms(700)
            for e in enemies:
                e['alive'] = True
                e['diving'] = False
            diver = None
            bullet = None
            mega_bullet = None
            enemy_bullets = []

        # --- Vykreslení ---
        clear()
        for e in enemies:
            if not e['alive']:
                continue
            if e['diving']:
                set_pixel(e['dr'], e['dc'], 2)
            else:
                set_pixel(e['r0'], e['c0'] + sway_offset, 1)
        if bullet is not None:
            set_pixel(bullet[0], bullet[1], 2)
        if mega_bullet is not None:
            fill_rect(mega_bullet[0] - 1, mega_bullet[1] - 1, 3, 3, 2)
        for eb in enemy_bullets:
            set_pixel(eb[0], eb[1], 1)
        for i in range(PLAYER_W):
            set_pixel(PLAYER_ROW, player_col + i, 2)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Asteroids — obrazovka nastavení obtížnosti
# ---------------------------------------------------------------------------
_AST_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
_AST_DIFF_PARAMS = [
    {'count': 3, 'ast_ms': 220},
    {'count': 5, 'ast_ms': 160},
    {'count': 7, 'ast_ms': 110},
]

def _asteroids_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit a spustit hru."""
    return _pick_option(enc, "ASTRO", _AST_DIFF_NAMES, 1)

def _ast_wrap_dist(a, b, size):
    """Vzdálenost dvou bodů na ose, která se obtáčí dokola (kratší ze
    dvou možných cest kolem)."""
    d = abs(a - b)
    return min(d, size - d)

# 8 směrů po 45°: 0=nahoru, jde po směru hodinových ručiček
_AST_DIRS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]

def _ast_ship_cells(row, col, ship_dir):
    """
    Vrátí seznam buněk, které loď blokuje pro srážku (ne jen ty dvě,
    které se skutečně vykreslují). Při diagonálním natočení jsou přední
    a zadní bod jen diagonálně sousední, takže mezi nimi zůstává
    "díra" - asteroid letící rovně (vodorovně/svisle) by tou dírou
    proletěl skrz, aniž by se dotkl kresleného bodu. Proto se u
    diagonálních směrů přidají dvě spojovací buňky, které tu díru
    zacelí (jen pro účely detekce srážky, kreslí se pořád jen dva body).
    """
    dr, dc = _AST_DIRS[ship_dir]
    tail_r = (row - dr) % ROWS
    tail_c = (col - dc) % COLS
    cells = [(row, col), (tail_r, tail_c)]
    if dr != 0 and dc != 0:   # diagonální směr - zacelit mezeru
        cells.append((row, tail_c))
        cells.append((tail_r, col))
    return cells

def _ast_cells(a):
    """Buňky, které asteroid zabírá - jedna pro malý, 2×2 pro velký."""
    if not a['big']:
        return [(a['r'], a['c'])]
    r2 = (a['r'] + 1) % ROWS
    c2 = (a['c'] + 1) % COLS
    return [(a['r'], a['c']), (a['r'], c2), (r2, a['c']), (r2, c2)]

# ---------------------------------------------------------------------------
# Asteroids — hra
# ---------------------------------------------------------------------------
def run_asteroids(enc=None, current=None):
    """
    Zjednodušené Asteroids. Loď jsou dva body - přední (plný jas) určuje
    směr, zadní (tlumený) je vždy za ním. Loď se natáčí po 45° do osmi
    směrů. Svět se dokola obtáčí (co zmizí vpravo, objeví se vlevo,
    stejně nahoře/dole) - to platí pro loď, střely i asteroidy.

      Šipky vlevo/vpravo = otočení lodi o 45° (krátký stisk = jeden
                            krok, podržení = otáčí dál po 200ms)
      Fire1               = tah vpřed ve směru, kam loď právě míří
      Fire2               = výstřel ve směru lodi
      Podržení Fire2 3s   = nabije a vypálí megastřelu (3×3, výbuch
                             5×5) - loď se přitom nemůže hýbat ani
                             otáčet
      Stisk enkodéru      = konec (vrátí aktuální skóre)

    Asteroidy letí náhodným směrem (jeden z osmi) stálou rychlostí
    podle obtížnosti. Od druhé vlny výš jsou některé asteroidy velké
    (2×2 body) a vydrží víc zásahů. Srážka lodi s asteroidem = konec
    hry. Sestřelený malý asteroid = 1 bod (2 megastřelou), velký = 3
    body (4 megastřelou). Po vyčištění vlny přiletí další (skóre jede
    dál, jediný způsob prohry je srážka).

    Detekce srážky lodi s asteroidem počítá i s tím, že při
    diagonálním natočení jsou přední a zadní bod lodi jen diagonálně
    sousední - bez zvláštního ošetření by asteroid letící rovně mohl
    proletět "dírou" mezi nimi, aniž by se jich dotkl.
    """
    diff = _asteroids_setup(enc)
    P = _AST_DIFF_PARAMS[diff]

    ship_row = ROWS // 2
    ship_col = COLS // 2
    ship_dir = 0   # index do _AST_DIRS, 0 = nahoru

    bullets     = []    # seznam dict: r, c, dr, dc, life
    mega_bullet = None  # dict: r, c, dr, dc, nebo None

    fire_press_start      = None
    mega_fired_this_hold  = False
    last_rotate_left      = 0
    last_rotate_right     = 0
    ROTATE_MS = 200

    def _make_asteroid(allow_big):
        while True:
            r = _randint(0, ROWS - 1)
            c = _randint(0, COLS - 1)
            if (_ast_wrap_dist(r, ship_row, ROWS) +
                    _ast_wrap_dist(c, ship_col, COLS) >= 4):
                break
        d = _AST_DIRS[_randint(0, 7)]
        big = allow_big and _randint(0, 2) == 0   # cca 1 ze 3, od 2. vlny
        return {'r': r, 'c': c, 'dr': d[0], 'dc': d[1],
                'big': big, 'hp': 3 if big else 1}

    wave = 1
    asteroids = [_make_asteroid(wave >= 2) for _ in range(P['count'])]

    score = 0
    btns  = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    MOVE_MS   = 90
    BULLET_MS = 40
    last_move   = ticks_ms()
    last_bullet = ticks_ms()
    last_mega   = ticks_ms()
    last_ast    = ticks_ms()

    while True:
        if check_test_mode():
            continue

        now = ticks_ms()
        cur, edge = btns.poll()
        charging_hold = cur['fire2']

        # --- Nabíjení megastřely držením Fire2 ---
        if charging_hold:
            if fire_press_start is None:
                fire_press_start = now
                mega_fired_this_hold = False
            elif (not mega_fired_this_hold and mega_bullet is None and
                  ticks_diff(now, fire_press_start) >= 3000):
                d = _AST_DIRS[ship_dir]
                mega_bullet = {'r': (ship_row + d[0]*2) % ROWS,
                               'c': (ship_col + d[1]*2) % COLS,
                               'dr': d[0], 'dc': d[1]}
                mega_fired_this_hold = True
        else:
            fire_press_start = None

        # --- Otáčení (krátký stisk = krok, podržení = opakuje po 200ms)
        #     a tah (obojí uzamčeno, dokud se nabíjí megastřela) ---
        if not charging_hold:
            if cur['left']:
                if edge['left'] or ticks_diff(now, last_rotate_left) >= ROTATE_MS:
                    ship_dir = (ship_dir - 1) % 8
                    last_rotate_left = now
            else:
                last_rotate_left = 0

            if cur['right']:
                if edge['right'] or ticks_diff(now, last_rotate_right) >= ROTATE_MS:
                    ship_dir = (ship_dir + 1) % 8
                    last_rotate_right = now
            else:
                last_rotate_right = 0

            if cur['fire1'] and ticks_diff(now, last_move) >= MOVE_MS:
                last_move = now
                d = _AST_DIRS[ship_dir]
                ship_row = (ship_row + d[0]) % ROWS
                ship_col = (ship_col + d[1]) % COLS

        # --- Výstřel (hrana Fire2 - i během nabíjení vystřelí okamžitě) ---
        if edge['fire2'] and len(bullets) < 5:
            d = _AST_DIRS[ship_dir]
            bullets.append({'r': (ship_row+d[0]) % ROWS, 'c': (ship_col+d[1]) % COLS,
                             'dr': d[0], 'dc': d[1], 'life': 24})

        if enc and enc.was_pressed():
            return score

        # --- Pohyb střel ---
        if ticks_diff(now, last_bullet) >= BULLET_MS:
            last_bullet = now
            still = []
            for b in bullets:
                b['r'] = (b['r'] + b['dr']) % ROWS
                b['c'] = (b['c'] + b['dc']) % COLS
                b['life'] -= 1
                hit = None
                for i, a in enumerate(asteroids):
                    if (b['r'], b['c']) in _ast_cells(a):
                        hit = i
                        break
                if hit is not None:
                    a = asteroids[hit]
                    a['hp'] -= 1
                    if a['hp'] <= 0:
                        del asteroids[hit]
                        score += 3 if a['big'] else 1
                elif b['life'] > 0:
                    still.append(b)
            bullets = still

        # --- Pohyb megastřely (3×3, výbuch 5×5) ---
        if mega_bullet is not None and ticks_diff(now, last_mega) >= BULLET_MS:
            last_mega = now
            mega_bullet['r'] = (mega_bullet['r'] + mega_bullet['dr']) % ROWS
            mega_bullet['c'] = (mega_bullet['c'] + mega_bullet['dc']) % COLS
            mr, mc = mega_bullet['r'], mega_bullet['c']

            def _cell_in_radius(cell, radius):
                cr, cc = cell
                return (_ast_wrap_dist(cr, mr, ROWS) <= radius and
                        _ast_wrap_dist(cc, mc, COLS) <= radius)

            hit_any = any(any(_cell_in_radius(cell, 1) for cell in _ast_cells(a))
                          for a in asteroids)
            if hit_any:
                survivors = []
                for a in asteroids:
                    if any(_cell_in_radius(cell, 2) for cell in _ast_cells(a)):
                        score += 4 if a['big'] else 2
                    else:
                        survivors.append(a)
                asteroids = survivors
                for dr2 in range(-2, 3):
                    for dc2 in range(-2, 3):
                        set_pixel((mr+dr2) % ROWS, (mc+dc2) % COLS, 2)
                show(); utime.sleep_ms(150)
                mega_bullet = None

        # --- Pohyb asteroidů a kolize s lodí ---
        if ticks_diff(now, last_ast) >= P['ast_ms']:
            last_ast = now
            for a in asteroids:
                a['r'] = (a['r'] + a['dr']) % ROWS
                a['c'] = (a['c'] + a['dc']) % COLS

            ship_cells = _ast_ship_cells(ship_row, ship_col, ship_dir)
            for a in asteroids:
                if any(cell in ship_cells for cell in _ast_cells(a)):
                    return score   # srážka s asteroidem = konec hry

        # --- Nová vlna, jakmile jsou všechny asteroidy zničené ---
        if not asteroids:
            wave += 1
            clear()
            draw_text("WAVE", col_start=4, row_start=5, level=2)
            show(); utime.sleep_ms(700)
            asteroids   = [_make_asteroid(wave >= 2) for _ in range(P['count'])]
            bullets     = []
            mega_bullet = None

        # --- Vykreslení ---
        clear()
        for a in asteroids:
            for cell in _ast_cells(a):
                set_pixel(cell[0], cell[1], 1)
        for b in bullets:
            set_pixel(b['r'], b['c'], 2)
        if mega_bullet is not None:
            mr, mc = mega_bullet['r'], mega_bullet['c']
            for dr2 in (-1, 0, 1):
                for dc2 in (-1, 0, 1):
                    set_pixel((mr+dr2) % ROWS, (mc+dc2) % COLS, 2)
        tail_r = (ship_row - _AST_DIRS[ship_dir][0]) % ROWS
        tail_c = (ship_col - _AST_DIRS[ship_dir][1]) % COLS
        set_pixel(tail_r, tail_c, 1)
        set_pixel(ship_row, ship_col, 2)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# T-Rex — obrazovka nastavení obtížnosti
# ---------------------------------------------------------------------------
_TREX_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
# Rozestupy překážek jsou teď u všech obtížností podobné (jen s trochou
# náhody) - liší se jen rychlost a to, jestli létají ptáci (jen HARD).
_TREX_DIFF_PARAMS = [
    {'speed_ms': 90, 'min_ms': 45, 'spawn_ms': 800, 'birds': False},
    {'speed_ms': 65, 'min_ms': 35, 'spawn_ms': 600, 'birds': False},
    {'speed_ms': 40, 'min_ms': 22, 'spawn_ms': 500, 'birds': True},
]

def _trex_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit."""
    return _pick_option(enc, "TREX", _TREX_DIFF_NAMES, 1)

def run_trex(enc=None, current=None):
    """
    Běžecká hra ve stylu T-Rex. Hráč (jeden bod) běží na pevném místě,
    překážky náhodné výšky přijíždějí zprava doleva.

    Skok má "fyziku": podržení šipky nahoru během letu sníží
    gravitaci (jak při stoupání, tak při pádu), takže skok vyjde výš
    a trvá déle - kratší stisk = nižší/kratší skok. Když se nahoru
    nedrží, pád je navíc trochu rychlejší než stoupání, ať to
    nepůsobí "plovoucím" dojmem. Šipka dolů za letu okamžitě vrátí
    hráče na zem - funguje ale až po krátké ochranné době od odrazu,
    aby náhodný souběh stisků (např. nahoru a dolů skoro zároveň)
    nezpůsobil "okamžitou smrt" hned po výskoku.

    V těžkém režimu navíc létají ptáci ve dvou možných výškách (nízko
    - stačí malý skok, nebo vysoko - blízko stropu skoku, tam se
    vyplatí radši ptáka sestřelit než riskovat skok). Fire1 vystřelí
    projektil, který ptáka zničí.

      Šipka nahoru (podržet = vyšší/delší skok)
      Šipka dolů    = okamžitě zpátky na zem
      Fire1         = výstřel (jen v HARD režimu s ptáky)
      Stisk enkodéru = konec (vrátí skóre)
    """
    diff = _trex_setup(enc)
    P = _TREX_DIFF_PARAMS[diff]

    PLAYER_COL = 4
    GROUND_ROW = ROWS - 1
    SCALE        = 16
    V0           = 24
    GRAVITY      = 4   # normální gravitace (nedrží se nahoru) - skok teď
                        # trvá zhruba poloviční dobu a dosahuje zhruba
                        # poloviční výšky oproti dřívější verzi
    GRAVITY_HELD = 2   # snížená gravitace při podržení nahoru - vyšší/delší skok
    GRAVITY_FALL = 6   # rychlejší pád, když se při klesání nedrží nahoru
    PHYS_MS      = 45
    MIN_JUMP_MS  = 120   # ochranná doba, než šipka dolů může zrušit skok

    # Výška překážek je teď stejná napříč obtížnostmi (liší se jen
    # rychlost/rozestupy a ptáci) - min. 2, ať už nejsou i triviální
    # jednořádkové překážky. Základní (bez podržení) skok dosáhne asi
    # o 2 řádky výš, než je nejvyšší překážka.
    MIN_OBSTACLE_H = 2
    MAX_OBSTACLE_H = 3
    BASE_SPACING_MS = P['spawn_ms']
    SPACING_JITTER_MS = 200   # trocha náhody v rozestupech překážek

    BIRD_ROW_LOW  = GROUND_ROW - 3
    BIRD_ROW_HIGH = GROUND_ROW - 5
    BIRD_SPAWN_MS = P['spawn_ms'] * 2
    BULLET_MS     = 30

    player_pos = 0    # výška nad zemí v pixelových jednotkách (0 = na zemi)
    player_vel = 0
    jumping    = False
    jump_start = 0

    obstacles = []    # dict: col, height
    birds     = []    # dict: col, row
    bullets   = []    # dict: col, row
    score = 0
    speed_ms = P['speed_ms']
    next_spawn_ms = BASE_SPACING_MS
    btns = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    last_phys       = ticks_ms()
    last_scroll     = ticks_ms()
    last_spawn      = ticks_ms()
    last_bird_spawn = ticks_ms()
    last_bullet     = ticks_ms()

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if edge['up'] and not jumping:
            jumping = True
            player_vel = V0
            jump_start = now

        if cur['down'] and jumping and ticks_diff(now, jump_start) >= MIN_JUMP_MS:
            player_pos = 0
            player_vel = 0
            jumping = False

        if P['birds'] and edge['fire1'] and len(bullets) < 4:
            player_row_now = GROUND_ROW - 1 - player_pos // SCALE
            bullets.append({'col': PLAYER_COL + 1, 'row': player_row_now})

        if enc and enc.was_pressed():
            return score

        if jumping and ticks_diff(now, last_phys) >= PHYS_MS:
            last_phys = now
            player_pos += player_vel
            if player_vel > 0:
                g = GRAVITY_HELD if cur['up'] else GRAVITY
            else:
                g = GRAVITY_HELD if cur['up'] else GRAVITY_FALL
            player_vel -= g
            if player_pos <= 0:
                player_pos = 0
                player_vel = 0
                jumping = False

        if ticks_diff(now, last_spawn) >= next_spawn_ms:
            last_spawn = now
            if not any(o['col'] > COLS - 6 for o in obstacles):
                h = _randint(MIN_OBSTACLE_H, MAX_OBSTACLE_H)
                obstacles.append({'col': COLS, 'height': h})
            # trocha náhody v rozestupu do další překážky
            next_spawn_ms = max(150, BASE_SPACING_MS +
                                 _randint(-SPACING_JITTER_MS, SPACING_JITTER_MS))

        if P['birds'] and ticks_diff(now, last_bird_spawn) >= BIRD_SPAWN_MS:
            last_bird_spawn = now
            if not any(b['col'] > COLS - 8 for b in birds):
                row = BIRD_ROW_LOW if _randint(0, 1) == 0 else BIRD_ROW_HIGH
                birds.append({'col': COLS, 'row': row})

        if bullets and ticks_diff(now, last_bullet) >= BULLET_MS:
            last_bullet = now
            still_b = []
            for bl in bullets:
                bl['col'] += 2
                hit = False
                for bd in list(birds):
                    if bd['col'] == bl['col'] and bd['row'] == bl['row']:
                        birds.remove(bd)
                        score += 2
                        hit = True
                        break
                if not hit and bl['col'] < COLS:
                    still_b.append(bl)
            bullets = still_b

        if ticks_diff(now, last_scroll) >= speed_ms:
            last_scroll = now
            player_row_h = player_pos // SCALE
            player_row_now = GROUND_ROW - 1 - player_row_h

            still = []
            for o in obstacles:
                o['col'] -= 1
                if o['col'] == PLAYER_COL and player_row_h < o['height']:
                    return score   # náraz - hráč nebyl dost vysoko
                if o['col'] < -1:
                    score += 1
                    speed_ms = max(P['min_ms'], speed_ms - 1)
                else:
                    still.append(o)
            obstacles = still

            still_birds = []
            for bd in birds:
                bd['col'] -= 1
                if bd['col'] == PLAYER_COL and bd['row'] == player_row_now:
                    return score   # náraz do ptáka
                if bd['col'] >= -1:
                    still_birds.append(bd)
            birds = still_birds

        clear()
        for cc in range(COLS):
            set_pixel(GROUND_ROW, cc, 1)
        for o in obstacles:
            if 0 <= o['col'] < COLS:
                for hh in range(o['height']):
                    set_pixel(GROUND_ROW - hh, o['col'], 2)
        for bd in birds:
            if 0 <= bd['col'] < COLS:
                set_pixel(bd['row'], bd['col'], 2)
        for bl in bullets:
            if 0 <= bl['col'] < COLS:
                set_pixel(bl['row'], bl['col'], 2)
        # Displayed o řádek výš než by čistě odpovídalo srážkové výšce -
        # dá to malou zrakovou "rezervu" a hlavně to vypadá, že dinosaurus
        # stojí NA zemi, ne že s ní splývá.
        player_row = GROUND_ROW - 1 - player_pos // SCALE
        set_pixel(player_row, PLAYER_COL, 2)
        show()
        utime.sleep_ms(10)

_ELEV2_FLOORS   = [1, 3, 5, 7, 9, 11, 13]   # 7 pater, stejné jako u prvního Elevatoru
_ELEV2_BLDG_L   = COLS // 2 - 1             # levá kolejnice
_ELEV2_BLDG_M   = COLS // 2                 # prostřední sloupec - příčky + kabina
_ELEV2_BLDG_R   = COLS // 2 + 1             # pravá kolejnice
_ELEV2_STOP_COL = _ELEV2_BLDG_L - 2         # kam dojdou čekající lidé (1 volný bod od budovy)
_ELEV2_ORIGIN   = len(_ELEV2_FLOORS) - 1    # "první patro" - odkud lidé chodí (dole)
_ELEV2_ROOF     = 0                         # speciální střešní patro (jen v MLG)
_ELEV2_QUEUE_MAX = 6                        # NORMAL: víc než 6 čekajících = prohra
_ELEV2_MLG_CAP   = 10                       # MLG: kapacita výtahu

_ELEV2_MODE_NAMES = ["NORMAL", "MLG"]

# Hřibovitý mrak - 4 fáze růstu, odvozené přímo z ASCII předlohy
# (ořezáno na obsazenou oblast, řádek 0 = úroveň země, záporné = nahoru,
# sloupec 0 = střed dopadu). level 2 = jasné jádro/okraj, 1 = tlumený lem.
_MUSHROOM_F0 = [(-3, -1, 1), (-3, 0, 1), (-3, 1, 1), (-3, 2, 1), (-2, -2, 1),
                (-2, -1, 2), (-2, 0, 2), (-2, 1, 2), (-2, 2, 2), (-2, 3, 1),
                (-1, -3, 1), (-1, -2, 2), (-1, -1, 2), (-1, 0, 2), (-1, 1, 2),
                (-1, 2, 2), (-1, 3, 2), (-1, 4, 1), (0, -4, 1), (0, -3, 1),
                (0, -2, 1), (0, -1, 1), (0, 0, 1), (0, 1, 1), (0, 2, 1),
                (0, 3, 1), (0, 4, 1), (0, 5, 1)]
_MUSHROOM_F1 = [(-6, -1, 2), (-6, 0, 2), (-6, 1, 2), (-6, 2, 2), (-5, -2, 2),
                (-5, -1, 2), (-5, 0, 2), (-5, 1, 2), (-5, 2, 2), (-5, 3, 2),
                (-4, -2, 1), (-4, -1, 2), (-4, 0, 2), (-4, 1, 2), (-4, 2, 2),
                (-4, 3, 1), (-3, -1, 1), (-3, 0, 2), (-3, 1, 2), (-3, 2, 1),
                (-2, -1, 1), (-2, 0, 2), (-2, 1, 2), (-2, 2, 1), (-1, -2, 1),
                (-1, -1, 2), (-1, 0, 2), (-1, 1, 2), (-1, 2, 2), (-1, 3, 1),
                (0, -3, 1), (0, -2, 1), (0, -1, 1), (0, 0, 1), (0, 1, 1),
                (0, 2, 1), (0, 3, 1), (0, 4, 1)]
_MUSHROOM_F2 = [(-7, -2, 2), (-7, -1, 2), (-7, 0, 2), (-7, 1, 2), (-7, 2, 2),
                (-7, 3, 2), (-6, -3, 2), (-6, -2, 2), (-6, -1, 2), (-6, 0, 2),
                (-6, 1, 2), (-6, 2, 2), (-6, 3, 2), (-6, 4, 2), (-5, -3, 1),
                (-5, -2, 2), (-5, -1, 2), (-5, 0, 2), (-5, 1, 2), (-5, 2, 2),
                (-5, 3, 2), (-5, 4, 1), (-4, -2, 1), (-4, -1, 2), (-4, 0, 2),
                (-4, 1, 2), (-4, 2, 2), (-4, 3, 1), (-3, -1, 1), (-3, 0, 2),
                (-3, 1, 2), (-3, 2, 1), (-2, -1, 1), (-2, 0, 2), (-2, 1, 2),
                (-2, 2, 1), (-1, -2, 1), (-1, -1, 2), (-1, 0, 2), (-1, 1, 2),
                (-1, 2, 2), (-1, 3, 1), (0, -3, 1), (0, -2, 1), (0, -1, 1),
                (0, 0, 1), (0, 1, 1), (0, 2, 1), (0, 3, 1), (0, 4, 1)]
_MUSHROOM_F3 = [(-7, -3, 2), (-7, -2, 2), (-7, -1, 2), (-7, 0, 2), (-7, 1, 2),
                (-7, 2, 2), (-7, 3, 2), (-7, 4, 2), (-6, -4, 2), (-6, -3, 2),
                (-6, -2, 2), (-6, -1, 2), (-6, 0, 2), (-6, 1, 2), (-6, 2, 2),
                (-6, 3, 2), (-6, 4, 2), (-6, 5, 2), (-5, -4, 2), (-5, -3, 1),
                (-5, -2, 2), (-5, -1, 2), (-5, 0, 2), (-5, 1, 2), (-5, 2, 2),
                (-5, 3, 2), (-5, 4, 1), (-5, 5, 2), (-4, -3, 1), (-4, -2, 1),
                (-4, -1, 2), (-4, 0, 2), (-4, 1, 2), (-4, 2, 2), (-4, 3, 1),
                (-4, 4, 1), (-3, -1, 1), (-3, 0, 2), (-3, 1, 2), (-3, 2, 1),
                (-2, -1, 1), (-2, 0, 2), (-2, 1, 2), (-2, 2, 1), (-1, -2, 1),
                (-1, -1, 2), (-1, 0, 2), (-1, 1, 2), (-1, 2, 2), (-1, 3, 1),
                (0, -3, 1), (0, -2, 1), (0, -1, 1), (0, 0, 1), (0, 1, 1),
                (0, 2, 1), (0, 3, 1), (0, 4, 1)]
_MUSHROOM_FRAMES = [_MUSHROOM_F0, _MUSHROOM_F1, _MUSHROOM_F2, _MUSHROOM_F3]

def _elev2_setup(enc=None):
    """Obrazovka před hrou - výběr režimu NORMAL / MLG."""
    return _pick_option(enc, "ELEV2", _ELEV2_MODE_NAMES, 0)

def run_elevator2(enc=None, current=None):
    """Výtah 2 - výběr režimu, pak spustí NORMAL nebo MLG variantu."""
    mode = _elev2_setup(enc)
    if mode == 0:
        return _run_elev2_normal(enc, current)
    else:
        return _run_elev2_mlg(enc, current)

def _run_elev2_normal(enc, current):
    """
    NORMAL režim. Lidé chodí jen z prvního (nejnižšího) patra - to je
    "patro 0". Patro 1 znamená, že výtah musí vyjet o 1 patro výš,
    patro 2 o 2 patra výš atd. Přichází pomalu zleva a zastaví se
    kousek od budovy (1 volný bod, ať to nesplývá) na řádku prvního
    patra - když už tam někdo čeká, další se zastaví za ním a stojí
    ve frontě. Cílové patro prvního člověka ve frontě se ukazuje jako
    číslo vpravo dole od budovy; jakmile ho vyzvedneš, číslo se změní
    na pomlčku (někdo je na cestě) - a znovu se ukáže až po vysazení,
    s cílem dalšího čekajícího. Skóre je vlevo nahoře.

    Výtah (jasný blikající bod) pojme jen JEDNOHO člověka najednou.

      Šipky nahoru/dolů = pohyb výtahu o patro (jde i podržet, nemusí
                           se mačkat opakovaně)
      Fire1              = vyzvednout čekajícího (jen na prvním patře,
                            když je výtah prázdný a někdo už čeká
                            těsně u budovy)
      Fire2              = vysadit cestujícího - správné patro +1 bod,
                            špatné patro -1 bod (cestující i tak vystoupí)
      Stisk enkodéru     = konec (vrátí skóre)

    Prohra nastane, pokud se ve frontě nahromadí víc než 6 lidí.
    Lidé zpočátku chodí pomaleji, postupně čím dál rychleji.
    """
    elevator_idx = _ELEV2_ORIGIN
    elevator_row = _ELEV2_FLOORS[elevator_idx]

    queue = []      # fronta na prvním patře: {'col':, 'target': index patra}
    rider = None    # cestující ve výtahu: {'target': index patra} nebo None

    score = 0
    btns  = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    PERSON_MS      = 320
    SPAWN_MS       = 3000   # zpočátku hodně pomalu...
    SPAWN_MIN_MS   = 1200
    SPAWN_DECAY    = 40     # ...postupně rychleji po každém spawnu
    ANIM_MS        = 60
    FLOOR_MOVE_MS  = 250    # max. 4 patra za vteřinu při podržení šipky

    last_person_move = ticks_ms()
    last_spawn       = ticks_ms()
    last_blink       = ticks_ms()
    last_floor_move  = ticks_ms()
    blink_on = True

    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    def _draw():
        clear()
        for rr in range(ROWS):
            set_pixel(rr, _ELEV2_BLDG_L, 1)
            set_pixel(rr, _ELEV2_BLDG_R, 1)
        for fr in _ELEV2_FLOORS:
            set_pixel(fr, _ELEV2_BLDG_M, 1)

        # "Zem" - dva úplně spodní řádky displeje, slabě nasvícené
        for gr in (ROWS - 2, ROWS - 1):
            for cc in range(_ELEV2_STOP_COL + 1):
                set_pixel(gr, cc, 1)

        origin_row = _ELEV2_FLOORS[_ELEV2_ORIGIN]
        for p in queue:
            if 0 <= p['col'] < COLS:
                set_pixel(origin_row, p['col'], 2)   # jasněji než zem

        # Číslo (nebo pomlčka) vpravo dole od budovy - číslo = počet
        # pater od výchozího (0), ne syrový index v poli
        label_row = ROWS - 6
        label_col = COLS - 4
        if rider is not None:
            draw_char('-', label_col, row_start=label_row, level=2)
        elif queue:
            floor_num = _ELEV2_ORIGIN - queue[0]['target']
            draw_char(str(floor_num), label_col, row_start=label_row, level=2)

        # Skóre vlevo nahoře
        draw_text(str(score), col_start=0, row_start=0, level=1)

        if blink_on:
            set_pixel(elevator_row, _ELEV2_BLDG_M, 2)
        show()

    def _animate_elevator(from_idx, to_idx):
        nonlocal elevator_row
        r_from = _ELEV2_FLOORS[from_idx]
        r_to   = _ELEV2_FLOORS[to_idx]
        step = 1 if r_to > r_from else -1
        r = r_from
        while r != r_to:
            r += step
            elevator_row = r
            _draw()
            utime.sleep_ms(ANIM_MS)
        elevator_row = r_to

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if ticks_diff(now, last_blink) >= 250:
            last_blink = now
            blink_on = not blink_on

        # Šipky se dají i podržet (netřeba mačkat opakovaně), ale ne
        # rychleji než 4 patra za vteřinu.
        if cur['up'] and elevator_idx > 0:
            if edge['up'] or ticks_diff(now, last_floor_move) >= FLOOR_MOVE_MS:
                new_idx = elevator_idx - 1
                _animate_elevator(elevator_idx, new_idx)
                elevator_idx = new_idx
                last_floor_move = now
        if cur['down'] and elevator_idx < len(_ELEV2_FLOORS) - 1:
            if edge['down'] or ticks_diff(now, last_floor_move) >= FLOOR_MOVE_MS:
                new_idx = elevator_idx + 1
                _animate_elevator(elevator_idx, new_idx)
                elevator_idx = new_idx
                last_floor_move = now

        if enc and enc.was_pressed():
            return score

        # --- Fire1 = vyzvednout (jen na prvním patře, prázdný výtah,
        #     někdo už čeká těsně u budovy) ---
        if edge['fire1'] and rider is None and elevator_idx == _ELEV2_ORIGIN:
            if queue and queue[0]['col'] == _ELEV2_STOP_COL:
                rider = {'target': queue.pop(0)['target']}

        # --- Fire2 = vysadit - správné patro +1, špatné patro -1 ---
        if edge['fire2'] and rider is not None:
            if rider['target'] == elevator_idx:
                score += 1
            else:
                score -= 1
            rider = None

        # --- Pohyb čekajících lidí (fronta, nesmí se předbíhat) ---
        if ticks_diff(now, last_person_move) >= PERSON_MS:
            last_person_move = now
            for i, p in enumerate(queue):
                max_col = _ELEV2_STOP_COL if i == 0 else queue[i-1]['col'] - 1
                if p['col'] < max_col:
                    p['col'] += 1

        # --- Spawn nových lidí (postupně rychleji) ---
        if ticks_diff(now, last_spawn) >= SPAWN_MS:
            last_spawn = now
            if len(queue) >= _ELEV2_QUEUE_MAX:
                return score   # fronta přetekla = prohra
            # Cílové patro 1..N pater nad výchozím (0) - vzdálenost od
            # výchozího indexu, ne náhodný syrový index.
            floor_num = _randint(1, _ELEV2_ORIGIN)
            tgt = _ELEV2_ORIGIN - floor_num
            queue.append({'col': 0, 'target': tgt})
            SPAWN_MS = max(SPAWN_MIN_MS, SPAWN_MS - SPAWN_DECAY)

        _draw()
        utime.sleep_ms(15)

def _run_elev2_mlg(enc, current):
    """
    MLG režim. Výtah pojme až 10 lidí z prvního patra najednou. Kolik
    jich chce na které patro, ukazují tečky vpravo na řádku daného
    patra. Jakmile odjedeš od prvního patra s někým na palubě, spustí
    se časovač (1 vteřina na cestujícího) zobrazený jako mizející
    sloupec teček v úplně posledním sloupci displeje - vyprší-li dřív,
    než všechny vysadíš, prohráváš (cílem je naplánovat si trasu
    předem). Fronta nemá limit, ale nezobrazuje se víc lidí, než se
    vejde na displej, a chodí rychleji než v normálním režimu.

    Fire2 vysadí VŽDY JEN JEDNOHO cestujícího za stisk - přednostně
    toho, kdo chce zrovna tohle patro (+1 bod); když nikdo nechce,
    vysadí se první ve frontě cestujících a je to bráno jako špatné
    patro (-1 bod).

    Zvláštní cestující "Osama" (bliká ve frontě, nad ním svítí
    vykřičník) smí být ve výtahu jen sám - šance, že se objeví místo
    normálního cestujícího, je 5 % (zhruba 1 z 20). Pokud čeká vepředu
    fronty a zrovna ho nejde vzít (výtah není prázdný), po chvíli se
    - aby fronta nezůstala navždycky zaseknutá - přesune na konec
    fronty a čeká znovu odzadu.

    Jakmile s Osamou odjedeš od prvního patra, má každou vteřinu 20%
    šanci vybouchnout přímo ve výtahu (velká "hřibovitá" exploze, pak
    konec hry). Jediná záchrana: dovézt ho na speciální střešní patro
    (úplně nahoře) a tam stisknout Fire2 - hráč ho shodí ze střechy
    (pád s vodorovnou stálou rychlostí a zrychlující se svislou
    složkou, takže dráha vypadá jako čtvrtkruh) za 20 bodů, čímž
    riziko výbuchu skončí. Když dopadne na zem, vybuchne (hřibovitý
    mrak) přímo ve frontě - zničí všechny čekající a nechá kráter
    (vidět jako mezera v jinak slabě nasvícené "zemi"), který se 5
    vteřin postupně zaceluje zleva doprava (fronta zatím nepřibývá),
    pak vše pokračuje normálně.

    Obyčejné cestující lze taky shodit ze střechy - mají stejnou
    pádovou animaci a po dopadu menší "šplouchnutí", které zničí 2
    nejbližší čekající ve frontě (ale bez kráteru) - počítá se to
    jako špatné patro (-1 bod).

    Skóre je vlevo nahoře.

      Šipky nahoru/dolů = pohyb výtahu o patro (jde i podržet)
      Fire1              = nastoupit dalšího čekajícího (jen na prvním
                            patře), dokud je místo
      Fire2              = vysadit jednoho cestujícího (nebo shodit
                            někoho ze střechy)
      Stisk enkodéru     = konec (vrátí skóre)
    """
    elevator_idx = _ELEV2_ORIGIN
    elevator_row = _ELEV2_FLOORS[elevator_idx]

    queue = []             # {'col':, 'target': idx nebo None, 'is_osama': bool}
    cargo = []              # {'target': idx} - obyčejní cestující na palubě
    carrying_osama = False
    osama_risk_on  = False

    score = 0
    btns  = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    PERSON_MS    = 150
    SPAWN_MS     = 500
    SPAWN_MIN_MS = 150
    SPAWN_DECAY  = 25
    ANIM_MS      = 50
    OSAMA_SPAWN_ODDS = 20    # 5 % - zhruba 1 z 20
    CRATER_MS    = 5000
    FLOOR_MOVE_MS = 250     # max. 4 patra za vteřinu při podržení šipky

    route_timer_end  = None
    crater_until     = 0
    last_osama_check = ticks_ms()

    last_person_move = ticks_ms()
    last_spawn        = ticks_ms()
    last_blink         = ticks_ms()
    last_floor_move    = ticks_ms()
    blink_on = True

    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    def _valid_targets():
        # obyčejní cestující nikdy nechtějí na výchozí ani na střešní patro
        return [i for i in range(len(_ELEV2_FLOORS))
                if i != _ELEV2_ORIGIN and i != _ELEV2_ROOF]

    def _draw(overlay=None):
        clear()
        for rr in range(ROWS):
            set_pixel(rr, _ELEV2_BLDG_L, 1)
            set_pixel(rr, _ELEV2_BLDG_R, 1)
        for fr in _ELEV2_FLOORS:
            set_pixel(fr, _ELEV2_BLDG_M, 1)

        # "Zem" - dva úplně spodní řádky displeje, slabě nasvícené;
        # kráter je vidět jako mezera, co se zleva doprava zaceluje.
        now2 = ticks_ms()
        in_crater_now = ticks_diff(now2, crater_until) < 0
        if in_crater_now:
            crater_start = crater_until - CRATER_MS
            elapsed = ticks_diff(now2, crater_start)
            filled = max(0, int((elapsed / CRATER_MS) * (_ELEV2_STOP_COL + 1)))
        else:
            filled = _ELEV2_STOP_COL + 1
        for gr in (ROWS - 2, ROWS - 1):
            for cc in range(filled):
                if 0 <= cc < COLS:
                    set_pixel(gr, cc, 1)

        origin_row = _ELEV2_FLOORS[_ELEV2_ORIGIN]
        for p in queue:
            if 0 <= p['col'] < COLS:
                if p.get('is_osama'):
                    osama_visible = (ticks_ms() // 200) % 2 == 0
                    if osama_visible:
                        c = p['col']
                        set_pixel(origin_row, c, 2)
                        # vykřičník - svislá čárka, mezera, tečka, pak
                        # 1 volný bod mezery před Osamou samotnou
                        if origin_row - 5 >= 0: set_pixel(origin_row - 5, c, 2)
                        if origin_row - 4 >= 0: set_pixel(origin_row - 4, c, 2)
                        if origin_row - 2 >= 0: set_pixel(origin_row - 2, c, 2)
                else:
                    set_pixel(origin_row, p['col'], 2)   # jasněji než zem

        # Počty cestujících podle cílového patra (tečky vpravo od budovy)
        counts = {}
        for c in cargo:
            counts[c['target']] = counts.get(c['target'], 0) + 1
        for fi, fr in enumerate(_ELEV2_FLOORS):
            n = counts.get(fi, 0)
            for i in range(n):
                cc = _ELEV2_BLDG_R + 1 + i
                if cc < COLS:
                    set_pixel(fr, cc, 1)

        # Ukazatel Osamy na střešním patře, dokud je na palubě
        if carrying_osama:
            roof_row = _ELEV2_FLOORS[_ELEV2_ROOF]
            if (ticks_ms() // 150) % 2 == 0:
                set_pixel(roof_row, _ELEV2_BLDG_R + 1, 2)

        # Časovač trasy - mizející sloupec v úplně posledním sloupci displeje
        if route_timer_end is not None:
            remaining_ms = utime.ticks_diff(route_timer_end, ticks_ms())
            remaining_s = max(0, (remaining_ms + 999) // 1000)
            for i in range(min(remaining_s, ROWS)):
                set_pixel(ROWS - 1 - i, COLS - 1, 2)

        # Skóre vlevo nahoře
        draw_text(str(score), col_start=0, row_start=0, level=1)

        if overlay is not None:
            set_pixel(overlay[0], overlay[1], 2)

        if blink_on:
            set_pixel(elevator_row, _ELEV2_BLDG_M, 2)
        show()

    def _animate_elevator(from_idx, to_idx):
        nonlocal elevator_row
        r_from = _ELEV2_FLOORS[from_idx]
        r_to   = _ELEV2_FLOORS[to_idx]
        step = 1 if r_to > r_from else -1
        r = r_from
        while r != r_to:
            r += step
            elevator_row = r
            _draw()
            utime.sleep_ms(ANIM_MS)
        elevator_row = r_to

    def _fall_animation(start_row, start_col, end_row, end_col, steps=14, step_ms=40):
        """
        Pád ze střechy dolů: vodorovná rychlost je konstantní, svislá
        se zrychluje (jako gravitace) - dráha tak vypadá jako
        čtvrtkruh, i když se nepočítá goniometricky.
        """
        col_speed = (end_col - start_col) / steps
        row_accel = (2.0 * (end_row - start_row)) / (steps * (steps + 1))
        row = float(start_row)
        col = float(start_col)
        row_speed = 0.0
        _draw(overlay=(int(row), int(col)))
        utime.sleep_ms(step_ms)
        for _ in range(steps):
            row_speed += row_accel
            row += row_speed
            col += col_speed
            _draw(overlay=(int(row), int(col)))
            utime.sleep_ms(step_ms)

    def _explosion_animation(center_row, center_col, max_radius=20, step_ms=60):
        """Rozšiřující se prstenec přes displej - použije se pro výbuch
        přímo ve výtahu."""
        for radius in range(0, max_radius, 2):
            clear()
            for rr in range(ROWS):
                for cc2 in range(COLS):
                    d = abs(rr - center_row) + abs(cc2 - center_col)
                    if radius <= d < radius + 2:
                        set_pixel(rr, cc2, 2)
            show()
            utime.sleep_ms(step_ms)
        fill(); show(); utime.sleep_ms(150)
        clear(); show(); utime.sleep_ms(100)

    def _mushroom_cloud(ground_row, center_col):
        """
        Hřibovitý mrak pro dopad Osamy do fronty - 4 fáze růstu podle
        skutečné předlohy (úzký krček, široká zaoblená hlavice nahoře,
        rozšířená patka dole u země).
        """
        for frame in _MUSHROOM_FRAMES:
            clear()
            for dr, dc, lvl in frame:
                rr = ground_row + dr
                cc2 = center_col + dc
                if 0 <= rr < ROWS and 0 <= cc2 < COLS:
                    set_pixel(rr, cc2, lvl)
            show()
            utime.sleep_ms(180)
        utime.sleep_ms(300)
        clear(); show()

    def _splash_animation(center_row, center_col):
        """Menší a rychlejší "šplouchnutí" pro obyčejného cestujícího
        shozeného ze střechy - jen krátký rozšiřující se bod."""
        for radius in range(0, 4):
            clear()
            for rr in range(ROWS):
                for cc2 in range(COLS):
                    if abs(rr - center_row) + abs(cc2 - center_col) <= radius:
                        set_pixel(rr, cc2, 2)
            show()
            utime.sleep_ms(50)
        utime.sleep_ms(60)

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if ticks_diff(now, last_blink) >= 250:
            last_blink = now
            blink_on = not blink_on

        # Šipky se dají i podržet (netřeba mačkat opakovaně), ale ne
        # rychleji než 4 patra za vteřinu.
        prev_idx = elevator_idx
        if cur['up'] and elevator_idx > 0:
            if edge['up'] or ticks_diff(now, last_floor_move) >= FLOOR_MOVE_MS:
                new_idx = elevator_idx - 1
                _animate_elevator(elevator_idx, new_idx)
                elevator_idx = new_idx
                last_floor_move = now
        if cur['down'] and elevator_idx < len(_ELEV2_FLOORS) - 1:
            if edge['down'] or ticks_diff(now, last_floor_move) >= FLOOR_MOVE_MS:
                new_idx = elevator_idx + 1
                _animate_elevator(elevator_idx, new_idx)
                elevator_idx = new_idx
                last_floor_move = now

        # Odjezd od prvního patra spustí buď riziko Osamy, nebo časovač trasy
        if prev_idx == _ELEV2_ORIGIN and elevator_idx != _ELEV2_ORIGIN:
            if carrying_osama:
                osama_risk_on = True
                last_osama_check = now
            elif cargo:
                route_timer_end = now + len(cargo) * 1000

        if enc and enc.was_pressed():
            return score

        # --- Fire1 = nastoupit (jen na prvním patře) ---
        if edge['fire1'] and elevator_idx == _ELEV2_ORIGIN and queue:
            if queue[0]['col'] == _ELEV2_STOP_COL:
                front = queue[0]
                if front.get('is_osama'):
                    if not cargo and not carrying_osama:
                        carrying_osama = True
                        queue.pop(0)
                elif not carrying_osama and len(cargo) < _ELEV2_MLG_CAP:
                    cargo.append({'target': queue.pop(0)['target']})

        # --- Fire2 = vysadit JEDNOHO cestujícího, nebo shodit někoho ze střechy ---
        if edge['fire2']:
            if elevator_idx == _ELEV2_ROOF and carrying_osama:
                carrying_osama = False
                osama_risk_on = False
                route_timer_end = None
                land_col = max(0, _ELEV2_STOP_COL - 2)
                _fall_animation(_ELEV2_FLOORS[_ELEV2_ROOF], _ELEV2_BLDG_M,
                                 _ELEV2_FLOORS[_ELEV2_ORIGIN], land_col)
                score += 20
                _mushroom_cloud(_ELEV2_FLOORS[_ELEV2_ORIGIN], land_col)
                queue = []
                crater_until = utime.ticks_ms() + CRATER_MS
            elif elevator_idx == _ELEV2_ROOF and cargo:
                cargo.pop(0)
                land_col = max(0, _ELEV2_STOP_COL - 2)
                _fall_animation(_ELEV2_FLOORS[_ELEV2_ROOF], _ELEV2_BLDG_M,
                                 _ELEV2_FLOORS[_ELEV2_ORIGIN], land_col)
                score -= 1
                _splash_animation(_ELEV2_FLOORS[_ELEV2_ORIGIN], land_col)
                del queue[0:2]   # "šplouchnutí" zničí 2 nejbližší čekající
                if not cargo:
                    route_timer_end = None
            elif cargo:
                match_idx = None
                for i, c in enumerate(cargo):
                    if c['target'] == elevator_idx:
                        match_idx = i
                        break
                if match_idx is not None:
                    cargo.pop(match_idx)
                    score += 1
                else:
                    cargo.pop(0)
                    score -= 1
                if not cargo:
                    route_timer_end = None

        # --- Riziko výbuchu Osamy (20 % za vteřinu, dokud je na palubě) ---
        if osama_risk_on and carrying_osama:
            if ticks_diff(now, last_osama_check) >= 1000:
                last_osama_check = now
                if _randint(0, 4) == 0:   # 20% šance
                    _explosion_animation(elevator_row, _ELEV2_BLDG_M)
                    return score   # Osama vybouchl - konec hry

        # --- Časovač trasy (jen s obyčejnými cestujícími na palubě) ---
        if route_timer_end is not None and cargo:
            if ticks_diff(now, route_timer_end) >= 0:
                return score   # trasa nestihnuta včas - konec hry

        in_crater = ticks_diff(now, crater_until) < 0

        # --- Pohyb čekajících lidí (jen mimo kráter) ---
        if not in_crater and ticks_diff(now, last_person_move) >= PERSON_MS:
            last_person_move = now
            for i, p in enumerate(queue):
                max_col = _ELEV2_STOP_COL if i == 0 else queue[i-1]['col'] - 1
                if p['col'] < max_col:
                    p['col'] += 1

        # --- Spawn nových lidí (rychleji, bez limitu fronty) ---
        if not in_crater and ticks_diff(now, last_spawn) >= SPAWN_MS:
            last_spawn = now
            # Nový příchozí nikdy nesmí sdílet sloupec s posledním ve
            # frontě (při vysoké rychlosti by se jinak spawn a pohyb
            # mohly "potkat" ve stejném tiku a dva lidé by chvíli
            # stáli na stejném pixelu).
            spawn_col = min(0, queue[-1]['col'] - 1) if queue else 0
            if _randint(0, OSAMA_SPAWN_ODDS - 1) == 0:
                queue.append({'col': spawn_col, 'target': None, 'is_osama': True})
            else:
                targets = _valid_targets()
                tgt = targets[_randint(0, len(targets) - 1)]
                queue.append({'col': spawn_col, 'target': tgt, 'is_osama': False})
            SPAWN_MS = max(SPAWN_MIN_MS, SPAWN_MS - SPAWN_DECAY)

        _draw()
        utime.sleep_ms(15)

# ---------------------------------------------------------------------------
# Frogger
# ---------------------------------------------------------------------------
_FROGGER_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
_FROGGER_DIFF_PARAMS = [
    {'speed_mult': 1.5, 'width': 2},
    {'speed_mult': 1.0, 'width': 2},
    {'speed_mult': 0.7, 'width': 3},
]

def _frogger_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit."""
    return _pick_option(enc, "FROG", _FROGGER_DIFF_NAMES, 1)

def run_frogger(enc=None, current=None):
    """
    Frogger. Žabák (jeden bod) startuje dole a musí se dostat na horní
    okraj přes pruhy s pohybujícími se překážkami - každý čtvrtý pruh
    je bezpečný "medián" bez provozu. Dosažení horního okraje = bod,
    žabák se vrátí dolů a pruhy jedou dál stejným tempem. Náraz do
    překážky = konec hry.
      Šipky = pohyb o jedno políčko
      Stisk enkodéru = konec (vrátí skóre)
    """
    diff = _frogger_setup(enc)
    P = _FROGGER_DIFF_PARAMS[diff]

    lanes = []
    for r in range(1, ROWS - 1):
        if r % 4 == 0:
            lanes.append({'row': r, 'safe': True})
        else:
            direction = 1 if (r % 2 == 0) else -1
            spacing = _randint(4, 7)
            lanes.append({
                'row': r, 'safe': False, 'dir': direction,
                'offset': _randint(0, spacing - 1), 'spacing': spacing,
                'width': P['width'],
                'speed_ms': max(40, int(_randint(70, 150) * P['speed_mult'])),
                'last': 0,
            })

    player_row = ROWS - 1
    player_col = COLS // 2
    score = 0
    btns = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    def _lane_has_obstacle(lane, col):
        return ((col - lane['offset']) % lane['spacing']) < lane['width']

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if edge['up']    and player_row > 0:        player_row -= 1
        elif edge['down']  and player_row < ROWS - 1: player_row += 1
        elif edge['left']  and player_col > 0:        player_col -= 1
        elif edge['right'] and player_col < COLS - 1:  player_col += 1

        if enc and enc.was_pressed():
            return score

        for lane in lanes:
            if lane['safe']:
                continue
            if ticks_diff(now, lane['last']) >= lane['speed_ms']:
                lane['last'] = now
                lane['offset'] = (lane['offset'] + lane['dir']) % lane['spacing']

        for lane in lanes:
            if lane['safe'] or lane['row'] != player_row:
                continue
            if _lane_has_obstacle(lane, player_col):
                return score

        if player_row == 0:
            score += 1
            player_row = ROWS - 1
            player_col = COLS // 2

        clear()
        for lane in lanes:
            if lane['safe']:
                continue
            for c in range(COLS):
                if _lane_has_obstacle(lane, c):
                    set_pixel(lane['row'], c, 1)
        set_pixel(player_row, player_col, 2)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Reaction — reflexní hra
# ---------------------------------------------------------------------------
_REACT_UP    = [(0,2),(1,1),(1,2),(1,3),(2,0),(2,1),(2,2),(2,3),(2,4),(3,2)]
_REACT_DOWN  = [(3 - r, c) for r, c in _REACT_UP]
_REACT_RIGHT = [(2,3),(1,2),(2,2),(3,2),(0,1),(1,1),(2,1),(3,1),(4,1),(2,0)]
_REACT_LEFT  = [(r, 3 - c) for r, c in _REACT_RIGHT]
_REACT_SHAPES = {'up': _REACT_UP, 'down': _REACT_DOWN,
                 'left': _REACT_LEFT, 'right': _REACT_RIGHT}
_REACT_ANCHOR_ROW = ROWS // 2 - 2
_REACT_ANCHOR_COL = COLS // 2 - 2

_REACT_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
_REACT_DIFF_PARAMS = [
    {'start_ms': 1100, 'min_ms': 350, 'decay': 20},
    {'start_ms': 800,  'min_ms': 200, 'decay': 25},
    {'start_ms': 550,  'min_ms': 120, 'decay': 30},
]

def _reaction_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit."""
    return _pick_option(enc, "REACT", _REACT_DIFF_NAMES, 1)

def run_reaction(enc=None, current=None):
    """
    Reflexní hra: objeví se šipka ukazující směr, musíš co nejrychleji
    zmáčknout odpovídající šipku na ovladači, než čas vyprší. Časový
    limit se s každým uhodnutým kolem zkracuje. Špatný směr nebo
    vypršení = konec hry, skóre je počet uhodnutých kol.
      Šipky = odpověď na zobrazený směr
      Stisk enkodéru = konec (jen mezi koly)
    """
    diff = _reaction_setup(enc)
    P = _REACT_DIFF_PARAMS[diff]

    limit_ms = P['start_ms']
    score = 0
    btns = Buttons()
    directions = ['up', 'down', 'left', 'right']
    wait_no_buttons(enc)
    if enc:
        enc.was_pressed()

    while True:
        if enc and enc.was_pressed():
            return score

        d = directions[_randint(0, 3)]
        clear()
        for r, c in _REACT_SHAPES[d]:
            set_pixel(_REACT_ANCHOR_ROW + r, _REACT_ANCHOR_COL + c, 2)
        show()

        t_start = utime.ticks_ms()
        pressed_dir = None
        while utime.ticks_diff(utime.ticks_ms(), t_start) < limit_ms:
            if check_test_mode():
                continue
            cur, edge = btns.poll()
            if edge['up']:      pressed_dir = 'up'
            elif edge['down']:  pressed_dir = 'down'
            elif edge['left']:  pressed_dir = 'left'
            elif edge['right']: pressed_dir = 'right'
            if pressed_dir is not None:
                break
            if enc and enc.was_pressed():
                return score
            utime.sleep_ms(5)

        if pressed_dir != d:
            return score   # špatný směr nebo čas vypršel = konec

        score += 1
        limit_ms = max(P['min_ms'], limit_ms - P['decay'])
        clear(); show(); utime.sleep_ms(80)

# ---------------------------------------------------------------------------
# Missile Command
# ---------------------------------------------------------------------------
_MISSILE_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
_MISSILE_DIFF_PARAMS = [
    {'missile_ms': 260, 'spawn_chk_ms': 900, 'spawn_chance': 2},
    {'missile_ms': 180, 'spawn_chk_ms': 650, 'spawn_chance': 2},
    {'missile_ms': 120, 'spawn_chk_ms': 400, 'spawn_chance': 2},
]

def _missile_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit."""
    return _pick_option(enc, "MISSILE", _MISSILE_DIFF_NAMES, 1)

def run_missile(enc=None, current=None):
    """
    Missile Command. Dole jsou 4 města, shora padají rakety. Kurzor
    (šipky vlevo/vpravo) míří na sloupec, Fire1/Fire2 odpálí
    zachytávač - ten vyletí a v pevné výšce vybuchne do malého okruhu,
    co je v okruhu v okamžiku výbuchu (a chvíli po něm), je zničeno.
    Raketa, která dopadne na město, ho zničí. Když padnou všechna
    města, konec hry.
      Šipky vlevo/vpravo = pohyb kurzoru
      Fire1 / Fire2      = odpálit zachytávač
      Stisk enkodéru     = konec (vrátí skóre)
    """
    diff = _missile_setup(enc)
    P = _MISSILE_DIFF_PARAMS[diff]

    EXPLODE_ROW   = 5
    CITY_COLS     = [3, 11, 19, 27]
    CITY_W        = 3
    cities        = list(CITY_COLS)
    cursor_col    = COLS // 2
    missiles      = []   # dict: row, col
    interceptors  = []   # dict: col, row, state, timer

    score = 0
    btns  = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    MOVE_MS       = 90
    INTERCEPT_MS  = 40
    EXPLODE_TICKS = 5
    last_cursor_move    = ticks_ms()
    last_spawn_chk      = ticks_ms()
    last_missile_move   = ticks_ms()
    last_intercept_move = ticks_ms()

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if cur['left']  and ticks_diff(now, last_cursor_move) >= MOVE_MS:
            last_cursor_move = now
            cursor_col = max(0, cursor_col - 1)
        if cur['right'] and ticks_diff(now, last_cursor_move) >= MOVE_MS:
            last_cursor_move = now
            cursor_col = min(COLS - 1, cursor_col + 1)

        if (edge['fire1'] or edge['fire2']) and len(interceptors) < 2:
            interceptors.append({'col': cursor_col, 'row': ROWS - 1,
                                  'state': 'rising', 'timer': 0})

        if enc and enc.was_pressed():
            return score

        if ticks_diff(now, last_spawn_chk) >= P['spawn_chk_ms']:
            last_spawn_chk = now
            if cities and len(missiles) < 5 and _randint(0, P['spawn_chance']-1) == 0:
                missiles.append({'row': 0, 'col': _randint(0, COLS - 1)})

        if ticks_diff(now, last_missile_move) >= P['missile_ms']:
            last_missile_move = now
            still = []
            for m in missiles:
                m['row'] += 1
                if m['row'] >= ROWS - 1:
                    for cc in cities:
                        if cc <= m['col'] < cc + CITY_W:
                            cities.remove(cc)
                            break
                else:
                    still.append(m)
            missiles = still
            if not cities:
                return score   # všechna města padla = konec

        if ticks_diff(now, last_intercept_move) >= INTERCEPT_MS:
            last_intercept_move = now
            still_i = []
            for ic in interceptors:
                if ic['state'] == 'rising':
                    ic['row'] -= 1
                    if ic['row'] <= EXPLODE_ROW:
                        ic['row'] = EXPLODE_ROW
                        ic['state'] = 'exploding'
                        ic['timer'] = EXPLODE_TICKS
                    still_i.append(ic)
                else:
                    still_m = []
                    for m in missiles:
                        if abs(m['row']-ic['row']) <= 2 and abs(m['col']-ic['col']) <= 2:
                            score += 1
                        else:
                            still_m.append(m)
                    missiles = still_m
                    ic['timer'] -= 1
                    if ic['timer'] > 0:
                        still_i.append(ic)
            interceptors = still_i

        clear()
        for cc in cities:
            for i in range(CITY_W):
                set_pixel(ROWS-1, cc+i, 1)
        for m in missiles:
            set_pixel(m['row'], m['col'], 2)
        for ic in interceptors:
            if ic['state'] == 'rising':
                set_pixel(ic['row'], ic['col'], 2)
            else:
                for dr2 in range(-2, 3):
                    for dc2 in range(-2, 3):
                        rr, cc2 = ic['row']+dr2, ic['col']+dc2
                        if 0 <= rr < ROWS and 0 <= cc2 < COLS:
                            set_pixel(rr, cc2, 2)
        set_pixel(EXPLODE_ROW, cursor_col, 1)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# Racer
# ---------------------------------------------------------------------------
_RACER_DIFF_NAMES  = ["EASY", "NORMAL", "HARD"]
_RACER_DIFF_PARAMS = [
    {'speed_ms': 220, 'min_ms': 90, 'spawn_ms': 750},
    {'speed_ms': 160, 'min_ms': 60, 'spawn_ms': 550},
    {'speed_ms': 110, 'min_ms': 45, 'spawn_ms': 400},
]

def _racer_setup(enc=None):
    """Obrazovka před hrou. Šipky nahoru/dolů nebo enkodér = obtížnost.
    Fire1/Fire2 nebo stisk enkodéru = potvrdit."""
    return _pick_option(enc, "RACER", _RACER_DIFF_NAMES, 1)

def run_racer(enc=None, current=None):
    """
    Jednoduchý závodní uhýbač. Auto jede ve 4 pruzích, překážky
    přijíždějí shora dolů, je potřeba včas přepnout pruh. Rychlost
    roste se skóre. Náraz = konec hry.
      Šipky vlevo/vpravo = přepnutí o jeden pruh
      Stisk enkodéru     = konec (vrátí skóre)
    """
    diff = _racer_setup(enc)
    P = _RACER_DIFF_PARAMS[diff]

    LANES = 4
    lane_w = COLS // LANES
    lane_centers = [lane_w*i + lane_w//2 for i in range(LANES)]
    PLAYER_ROW = ROWS - 2
    CAR_W = max(2, lane_w - 2)

    player_lane = LANES // 2
    obstacles = []   # dict: row, lane

    score = 0
    speed_ms = P['speed_ms']
    btns = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    last_move  = ticks_ms()
    last_spawn = ticks_ms()

    while True:
        if check_test_mode():
            continue
        now = ticks_ms()
        cur, edge = btns.poll()

        if edge['left']  and player_lane > 0:         player_lane -= 1
        if edge['right'] and player_lane < LANES - 1: player_lane += 1

        if enc and enc.was_pressed():
            return score

        if ticks_diff(now, last_spawn) >= P['spawn_ms']:
            last_spawn = now
            lane = _randint(0, LANES - 1)
            if not any(o['row'] < 3 and o['lane'] == lane for o in obstacles):
                obstacles.append({'row': 0, 'lane': lane})

        if ticks_diff(now, last_move) >= speed_ms:
            last_move = now
            still = []
            for o in obstacles:
                o['row'] += 1
                if o['row'] == PLAYER_ROW and o['lane'] == player_lane:
                    return score
                if o['row'] < ROWS:
                    still.append(o)
                else:
                    score += 1
                    speed_ms = max(P['min_ms'], speed_ms - 2)
            obstacles = still

        clear()
        for o in obstacles:
            c0 = lane_centers[o['lane']] - CAR_W // 2
            for i in range(CAR_W):
                if 0 <= c0+i < COLS:
                    set_pixel(o['row'], c0+i, 1)
        pc0 = lane_centers[player_lane] - CAR_W // 2
        for i in range(CAR_W):
            if 0 <= pc0+i < COLS:
                set_pixel(PLAYER_ROW, pc0+i, 2)
        show()
        utime.sleep_ms(10)

# ---------------------------------------------------------------------------
# 2P Tron (light cycles) — jako 2P had, ale stopa nikdy nemizí
# ---------------------------------------------------------------------------
def run_tron_2p(enc=None, ir=None, current=None, ir_state=None, ring=None):
    """
    2P Tron. Stejná síťová logika jako u 2P hada (lokální hráč +
    přeposlané tlačítka druhého zařízení), ale bez jídla - stopa za
    hráčem se jen prodlužuje a nikdy nemizí. Náraz do zdi, do vlastní
    stopy nebo do stopy soupeře = prohra. Čelní srážka obou hlav =
    prohrávají oba.
      Šipky = směr (jako u hada)
      Enkodér = jas
    """
    if ring is None:
        clear()
        draw_text("NO RING", col_start=0, row_start=5, level=2)
        show(); utime.sleep_ms(2000)
        return

    state = ring.get_state()
    if not state:
        clear()
        draw_text("WAIT", col_start=4, row_start=5, level=2)
        show()
        t = utime.ticks_ms()
        while not ring.get_state() and utime.ticks_diff(utime.ticks_ms(), t) < 3000:
            utime.sleep_ms(100)
        if not ring.get_state():
            clear()
            draw_text("NO P2", col_start=0, row_start=5, level=2)
            show(); utime.sleep_ms(2000)
            return

    clear()
    draw_text("2P", col_start=4, row_start=0, level=2)
    draw_text("TRON", col_start=2, row_start=6, level=1)
    show(); utime.sleep_ms(1200)
    countdown()

    s1 = [(ROWS//2, 6)]          # P1 vlevo, míří doprava
    s2 = [(ROWS//2, COLS-7)]     # P2 vpravo, míří doleva
    d1 = 0
    d2 = 2

    step_ms = 180
    btns = Buttons()
    ticks_ms, ticks_diff = utime.ticks_ms, utime.ticks_diff

    remote_id = list(ring.get_state().keys())[0]
    last_step = ticks_ms()

    while True:
        cur, edge = btns.poll()

        if cur['up'] and cur['down'] and cur['left'] and cur['right'] and cur['fire1'] and cur['fire2']:
            run_test_mode()
            continue

        if edge['up']    and d1 != 1: d1 = 3
        if edge['down']  and d1 != 3: d1 = 1
        if edge['left']  and d1 != 0: d1 = 2
        if edge['right'] and d1 != 2: d1 = 0

        ring.send_buttons(TokenRing.buttons_byte(
            cur['fire1'], cur['right'], cur['left'],
            cur['down'], cur['up'], cur['fire2']))

        remote = ring.get_state().get(remote_id, 0)
        rb = TokenRing.unpack_buttons(remote)
        if rb['up']    and d2 != 1: d2 = 3
        if rb['down']  and d2 != 3: d2 = 1
        if rb['left']  and d2 != 0: d2 = 2
        if rb['right'] and d2 != 2: d2 = 0

        if enc and enc.was_pressed():
            return

        now = ticks_ms()
        if ticks_diff(now, last_step) >= step_ms:
            last_step = now

            n1r = s1[0][0] + _DR[d1]; n1c = s1[0][1] + _DC[d1]
            s1_set = set(s1); s2_set = set(s2)
            p1_dead = (n1r < 0 or n1r >= ROWS or n1c < 0 or n1c >= COLS
                       or (n1r,n1c) in s1_set or (n1r,n1c) in s2_set)

            n2r = s2[0][0] + _DR[d2]; n2c = s2[0][1] + _DC[d2]
            p2_dead = (n2r < 0 or n2r >= ROWS or n2c < 0 or n2c >= COLS
                       or (n2r,n2c) in s2_set or (n2r,n2c) in s1_set)

            if (n1r,n1c) == (n2r,n2c):
                p1_dead = True; p2_dead = True

            if p1_dead or p2_dead:
                blink_all(3, 100, 80)
                clear()
                if p1_dead and p2_dead:
                    draw_text("DRAW", col_start=4, row_start=5, level=2)
                elif p1_dead:
                    draw_text("P2 WIN", col_start=0, row_start=5, level=2)
                else:
                    draw_text("P1 WIN", col_start=0, row_start=5, level=2)
                show(); utime.sleep_ms(3000)
                return

            # Stopa se jen prodlužuje, nikdy nemizí (na rozdíl od hada)
            s1.insert(0, (n1r, n1c))
            s2.insert(0, (n2r, n2c))

        clear()
        for i,(r,c) in enumerate(s1):
            set_pixel(r, c, 2 if i==0 else 1)
        s1_set = set(s1)
        p2_head_on = (ticks_ms() // 200) % 2 == 0
        for i,(r,c) in enumerate(s2):
            if i == 0:
                if p2_head_on: set_pixel(r, c, 2)
            elif (r,c) not in s1_set:
                set_pixel(r, c, 1)
        show()

# ---------------------------------------------------------------------------
# Paměťová hra "VÝTAH" — Simon-like sekvence nahoru/dolů
# ---------------------------------------------------------------------------
# Patra šachty (řádek horní hrany kabiny; kabina je 2 řádky vysoká).
_ELEV_FLOORS  = [1, 3, 5, 7, 9, 11, 13]
_ELEV_MID     = len(_ELEV_FLOORS) // 2   # start uprostřed budovy
_ELEV_WALL_L  = 2
_ELEV_WALL_R  = 8
_ELEV_CAR_COL = 3
_ELEV_CAR_W   = 2

# Tvar šipky (10 bodů), dolní šipka je stejný tvar zrcadlený svisle.
_ARROW_UP   = [(0,3),(1,2),(1,3),(1,4),(2,1),(2,2),(2,3),(2,4),(2,5),(3,3)]
_ARROW_DOWN = [(3 - dr, dc) for dr, dc in _ARROW_UP]
_ARROW_ROW  = 5
_ARROW_COL  = 19

def _elev_frame(car_row, arrow_dir=None, car_on=True):
    """Vykreslí celou scénu: šachtu se zdmi, patry, kabinu a šipku."""
    clear()
    for r in range(ROWS):
        set_pixel(r, _ELEV_WALL_L, 1)
        set_pixel(r, _ELEV_WALL_R, 1)
    for fr in _ELEV_FLOORS:
        set_pixel(fr, _ELEV_WALL_L, 1); set_pixel(fr, _ELEV_WALL_R, 1)
    if car_on:
        fill_rect(car_row, _ELEV_CAR_COL, _ELEV_CAR_W, 1, 2)
    if arrow_dir == 'up':
        for dr, dc in _ARROW_UP:   set_pixel(_ARROW_ROW+dr, _ARROW_COL+dc, 2)
    elif arrow_dir == 'down':
        for dr, dc in _ARROW_DOWN: set_pixel(_ARROW_ROW+dr, _ARROW_COL+dc, 2)
    show()

def _elev_animate(idx_from, idx_to):
    """Posune kabinu mezi patry bod po bodu (viditelná jízda výtahu)."""
    r_from = _ELEV_FLOORS[idx_from]
    r_to   = _ELEV_FLOORS[idx_to]
    step   = 1 if r_to > r_from else -1
    r = r_from
    while r != r_to:
        r += step
        _elev_frame(r, None)
        utime.sleep_ms(35)

def _elev_valid_moves(idx):
    """Které směry jsou z daného patra vůbec možné (aby šlo dostavěnou
    sekvenci vždy celou odehrát a hráč neprohrával kvůli šachtě, ale
    jen kvůli vlastní paměti)."""
    moves = []
    if idx > 0: moves.append('up')
    if idx < len(_ELEV_FLOORS) - 1: moves.append('down')
    return moves

def run_elevator(enc=None, ir=None, current=None, ir_state=None):
    """
    Paměťová hra: vlevo dům se šachtou, vpravo šipka ukazující směr.
    Každé kolo se od začátku přehraje celá dosavadní posloupnost nahoru/
    dolů (výtah se vždy vrátí doprostřed), pak ji hráč musí zopakovat
    šipkami nahoru/dolů. Špatný krok = okamžitý konec.
    Skóre = celkový počet správně zadaných kroků za celou hru (ne jen
    nejdelší dosažená sekvence).
    """
    btns = Buttons()
    seq = []
    total_score = 0

    while True:
        # --- Přidání dalšího kroku do sekvence -----------------------
        # Vybírá se jen ze směrů, které jsou v daném patře možné, takže
        # sekvence je vždy celá odehratelná (žádná "neférová" prohra
        # kvůli nárazu do stěny šachty).
        idx = _ELEV_MID
        for d in seq:
            idx = idx - 1 if d == 'up' else idx + 1
        moves = _elev_valid_moves(idx)
        seq.append(moves[_randint(0, len(moves) - 1)])

        # --- UKÁZKA: přehraje celou dosavadní sekvenci od začátku -----
        idx = _ELEV_MID
        _elev_frame(_ELEV_FLOORS[idx], None)
        utime.sleep_ms(400)
        for d in seq:
            if check_test_mode():
                continue
            if enc and enc.was_pressed():
                return total_score
            _elev_frame(_ELEV_FLOORS[idx], d)
            utime.sleep_ms(350)
            new_idx = idx - 1 if d == 'up' else idx + 1
            _elev_animate(idx, new_idx)
            idx = new_idx
            _elev_frame(_ELEV_FLOORS[idx], None)
            utime.sleep_ms(150)

        # --- VSTUP: hráč musí zopakovat celou sekvenci -----------------
        idx = _ELEV_MID
        _elev_frame(_ELEV_FLOORS[idx], None)
        wait_no_buttons(enc)

        for expected in seq:
            pressed = None
            while pressed is None:
                if check_test_mode():
                    continue
                if enc and enc.was_pressed():
                    return total_score
                cur, edge = btns.poll()
                if edge['up']:
                    pressed = 'up'
                elif edge['down']:
                    pressed = 'down'
                utime.sleep_ms(10)

            if pressed != expected:
                # Špatný krok = okamžitý konec hry
                # (blink + skóre zobrazí volající main(), stejně jako u
                # ostatních her - nezobrazovat to tady podruhé)
                return total_score

            total_score += 1
            new_idx = idx - 1 if pressed == 'up' else idx + 1
            _elev_animate(idx, new_idx)
            idx = new_idx
            _elev_frame(_ELEV_FLOORS[idx], None)
            utime.sleep_ms(120)

        # Celé kolo správně -> krátké potvrzení a další, delší kolo
        for _ in range(2):
            _elev_frame(_ELEV_FLOORS[idx], None, car_on=True)
            utime.sleep_ms(120)
            _elev_frame(_ELEV_FLOORS[idx], None, car_on=False)
            utime.sleep_ms(120)

# ---------------------------------------------------------------------------
# Hlavní program
# ---------------------------------------------------------------------------
def main():
    global _current_ref

    # Nastavení jasu displeje na maximum
    current = MatrixCurrent()
    current.set_level(7)
    _current_ref = current   # aby check_test_mode() mohl řídit auto jas odkudkoliv

    # IR přijímač na pinu 0
    ir      = NEC(pin_num=0)
    ir_state = {'cmd': None, 'dir': None}

    # Enkodér zpočátku slouží k pohybu v menu
    # (obalený přes EncoderEdge kvůli spolehlivé hranové detekci stisku)
    enc = EncoderEdge(Encoder())
    enc.set_range(0, len(MENU_ITEMS)-1, wrap=True)
    enc.value = 0

    # Propojení s druhým zařízením (pro 2P hru)
    ring = TokenRing()

    start()
    ring.start()

    # Úvodní bliknutí celé matice, potvrzení že zařízení naběhlo
    fill(); show(); utime.sleep_ms(300)
    clear(); show()

    last_selected = 0   # menu se po návratu ze hry otevře na stejné položce

    while True:
        # Menu vždy nastaví enkodér zpět na počítání položek
        enc.set_range(0, len(MENU_ITEMS)-1, wrap=True)
        selected = run_menu(enc, ir, current, ir_state, last_selected)
        last_selected = selected

        if selected == 0:   # SNAKE — had pro jednoho hráče
            enc.set_range(0, 7, wrap=False)   # v samotné hře řídí enkodér jas
            enc.value = current.get_level()
            countdown()
            score = run_snake(enc, ir, current, ir_state, ring)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 1:   # 2P SNAKE — had pro dva hráče
            enc.set_range(0, 7, wrap=False)
            enc.value = current.get_level()
            clear()
            draw_text("2P", col_start=4, row_start=0, level=2)
            draw_text("READY", col_start=0, row_start=6, level=1)
            show(); utime.sleep_ms(1500)
            countdown()
            run_2p_snake(enc, ir, current, ir_state, ring)
            wait_no_buttons(enc)

        elif selected == 2:   # LIFE — Conwayova hra Life
            run_life(enc, current, ring)
            wait_no_buttons(enc)

        elif selected == 3:   # BREAKOUT — jednohráčský pong/breakout
            enc.set_range(0, COLS - 6, wrap=False)
            enc.value = (COLS - 6) // 2
            run_pong_1p(enc, current)
            wait_no_buttons(enc)

        elif selected == 4:   # 2P PONG — pong pro dva hráče přes ring
            run_pong_2p(enc, current, ring)
            wait_no_buttons(enc)

        elif selected == 5:   # FLAPPY — uhýbací hra
            enc.set_range(20, 200, wrap=False)
            enc.value = 80
            run_flappy(enc, current)
            wait_no_buttons(enc)

        elif selected == 6:   # GALAGA — zjednodušená verze
            enc.set_range(0, COLS - 3, wrap=False)
            enc.value = (COLS - 3) // 2
            score = run_galaga(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 7:   # ASTEROID — zjednodušené Asteroids
            score = run_asteroids(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 8:   # FROGGER
            score = run_frogger(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 9:   # REACTION — reflexní hra
            score = run_reaction(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 10:  # MISSILE — Missile Command
            score = run_missile(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 11:  # RACER — závodní uhýbač
            score = run_racer(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 12:  # 2P TRON — light cycles
            run_tron_2p(enc, ir, current, ir_state, ring)
            wait_no_buttons(enc)

        elif selected == 13:  # TREX — běžecká hra se skokem
            score = run_trex(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 14:  # ELEVATOR — paměťová hra nahoru/dolů
            enc.set_range(0, 7, wrap=False)
            enc.value = current.get_level()
            countdown()
            score = run_elevator(enc, ir, current, ir_state)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 15:  # ELEV2 — vyzvedávání a rozvážení lidí výtahem
            score = run_elevator2(enc, current)
            _end_game_flash(score)
            wait_no_buttons(enc)

        elif selected == 16:  # ATTRACT — animace / šetřič displeje
            enc.set_range(0, 7, wrap=False)
            enc.value = current.get_level()
            run_attract(enc, current)
            wait_no_buttons(enc)

        elif selected == 17:  # PAINT — malování
            enc.set_range(0, 7, wrap=False)
            enc.value = current.get_level()
            run_paint(enc, current, ring)
            wait_no_buttons(enc)

        elif selected == 18:  # TIME — zobrazení aktuálního času
            run_show_time(enc)
            wait_no_buttons(enc)

        elif selected == 19:  # STOPWCH — stopky
            run_stopwatch(enc)
            wait_no_buttons(enc)

        elif selected == 20:  # BTN TEST — zobrazí + posílá stav tlačítek
            run_button_test(enc, ring)
            wait_no_buttons(enc)

        elif selected == 21:  # SETTINGS — jas (ruční/auto) a čas
            enc.set_range(0, 7, wrap=False)
            enc.value = current.get_level()
            run_settings(enc, current, ring)
            wait_no_buttons(enc)

        elif selected == 22:  # INFO — autor skriptu/hardwaru, verze
            run_info(enc)
            wait_no_buttons(enc)

if __name__ == "__main__":
    main()