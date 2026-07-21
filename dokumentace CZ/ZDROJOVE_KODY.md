[⬅ Zpět na README](../README.md) · [Hardwarová dokumentace](HW.md) · [Dokumentace firmware v1.0](FW/v1.0/FW_v1.0.md)

# Popis zdrojových souborů

Firmware `main.py` (viz [FW_v1.0.md](FW/v1.0/FW_v1.0.md) pro popis her a
nastavení) importuje několik samostatných modulů, které mají každý na
starosti jednu konkrétní část hardwaru. Tenhle dokument popisuje **tyhle
podpůrné moduly** — ne samotné hry, ty už jsou popsané ve firmware
dokumentaci.

Každý z nich jde **spustit i samostatně** (nahraný a puštěný sám v Thonny,
bez zbytku firmware — hodí se to při ladění konkrétní periferie) a jde
normálně otevřít a upravit v Thonny jako kterýkoliv jiný `.py` soubor.

---

## `photodiode.py`

Jednoduchý samostatně spustitelný soubor pro čtení fotodiody na **GP28**.

- **Konfigurace pull rezistoru** nahoře v souboru (proměnná `PULL`) — lze
  přepnout mezi žádným pull rezistorem, pull-up nebo pull-down podle toho,
  jak je fotodioda v konkrétním zapojení zadrátovaná (bez rezistoru = plovoucí
  vstup, nejcitlivější; pull-down bývá obvykle nejlepší volba pro holou
  fotodiodu bez externího rezistoru — tma = 0 V, světlo = vyšší napětí).
- **Funkce k použití z jiného kódu**:
  - `read_raw()` — vrátí syrovou 16bitovou hodnotu ADC (0–65535)
  - `read_voltage()` — totéž převedené na napětí (0,0–3,3 V)
  - `read_percent()` — totéž jako 0–100 %
- **Spuštění samostatně**: každých 500 ms (`INTERVAL_MS`) vypíše do konzole
  syrovou hodnotu, napětí a procenta. Zastavení přes Ctrl-C.
- Tohle je jednodušší a pomalejší nástroj než `adc_sampler.py` (viz níže) —
  hodí se spíš na rychlou kontrolu "svítí/nesvítí něco na fotodiodu", ne na
  zachycení rychlých změn.

Poznámka: komentář v souboru říká "GP28 = ADC channel 0" — ve skutečnosti je
GP28 kanál **ADC2** (GP26=ADC0, GP27=ADC1, GP28=ADC2). Na funkčnost to
nemá vliv (kód si kanál najde sám podle čísla pinu), je to jen nepřesnost
v popisném komentáři.

---

## `adc_sampler.py`

Rychlejší a přesnější sourozenec `photodiode.py` — místo průběžného
vypisování **nejdřív nasbírá pevný počet vzorků do předalokovaného pole a
až pak je celé vypíše**, aby samotné měření neovlivňovalo žádné
alokování paměti, tisk na obrazovku ani přerušení.

- **Konfigurace** nahoře v souboru:
  - `NUM_SAMPLES = 1000` — kolik vzorků nabrat
  - `INTERVAL_US = 1000` — rozestup mezi vzorky v mikrosekundách (1000 = 1 ms);
    nastavením na `0` se vzorkuje maximální možnou rychlostí (~500 kHz)
- **`capture(num, interval_us)`** — nasbírá vzorky do předalokovaných polí
  (`array` typu `H`/`I`, žádná alokace za běhu), buď v pevném intervalu
  (aktivní čekání do dalšího vzorku), nebo na maximální rychlost
- **`print_samples(n, show_time, show_voltage)`** — vypíše všechny
  zachycené vzorky ve formátu **CSV** (`index,time_us,raw[,voltage]`,
  s hlavičkovým komentářem `# ...` na začátku)
- **`print_stats(n)`** — vypíše min/max/průměr a skutečně dosaženou
  vzorkovací frekvenci
- **Samostatné spuštění**: nasbírá `NUM_SAMPLES` vzorků, vypíše statistiky a
  pak celý CSV výstup, zakončený řádkem `# END`

Výstup jde zkopírovat z konzole Thonny a vložit třeba do Excelu (Data →
Text do sloupců, oddělovač čárka) a udělat z něj graf. Díky rychlému
vzorkování jde odhalit i to, co lidské oko nezachytí — třeba světlo, které
ve skutečnosti bliká (např. kvůli PWM řízení jiného zdroje světla v
místnosti) tak rychle, že to oko vnímá jako trvale svítící, ale na grafu
z dostatečně rychlého vzorkování je blikání jasně vidět jako pravidelné
výkyvy hodnoty.

---

## `encoder.py`

Ovladač rotačního enkodéru s tlačítkem, dekódovaný přes **kvadraturu** (obě
hrany na obou fázových signálech A/B — 4× rozlišení oproti dekódování jen
jedné hrany).

- **Piny**: `ENC_A = GP6`, `ENC_B = GP4`, `ENC_SW = GP22` (tlačítko, aktivní
  v log. 0, s interním pull-upem)
- Zajímavý detail v kódu: konstruktor **schválně prohodí A a B**
  (`self._pin_a = machine.Pin(pin_b, ...)` a naopak) — je to oprava správného
  směru otáčení, která zůstala z ladění na reálném hardwaru. Fyzické
  zapojení (GP6=A, GP4=B) tím zůstává stejné, jen se to uvnitř softwarově
  "přehodí", aby otáčení doprava odpovídalo očekávanému směru.
- Dekódování běží na **hardwarových přerušeních** (IRQ) na obou hranách
  obou pinů — enkodér tedy reaguje okamžitě, nezávisle na tom, jak často
  hlavní kód volá jeho metody.
- **4 syrové kroky kvadratury = 1 mechanický cvakl** enkodéru (`_raw_steps`
  se akumuluje a teprve při `abs(...) >= 4` se promítne do `value`/`delta`).

### API

```python
enc = Encoder()
enc.value                     # aktuální pozice (int, může být záporná)
enc.value = 5                 # nastavení pozice (zároveň vynuluje delta)
enc.reset()                   # nastaví pozici na 0
enc.delta()                   # změna od posledního volání, pak se vynuluje
enc.pressed                   # True, pokud je tlačítko PRÁVĚ TEĎ drženo (syrový stav)
enc.was_pressed()             # True, pokud bylo tlačítko stisknuto od posledního volání
                               # (jednorázový příznak, čtením se maže)
enc.set_range(min, max, wrap=False)   # omezí/zabalí pozici do rozsahu
enc.deinit()                  # odregistruje přerušení
```

Poznámka k hlavnímu firmware: `main.py` má vlastní obal `EncoderEdge` nad
touhle třídou, který dělá **vlastní** hranovou detekci stisku tlačítka
(pollováním `enc.pressed`), místo aby se spoléhal přímo na `was_pressed()`
téhle třídy — ukázalo se to jako spolehlivější řešení jednoho okrajového
případu (hra se občas hned po výběru z menu sama ukončila). Metoda
`was_pressed()` v tomhle souboru je nicméně sama o sobě navržená jako
jednorázový příznak nastavovaný v přerušení, takže by principiálně měla
fungovat správně i bez toho obalu — příčina toho konkrétního chování nebyla
nakonec s jistotou dohledaná.

---

## `ir_nec.py`

Obsahuje dvě oddělené věci v jednom souboru:

### Třída `NEC` — příjem IR dálkového ovladače

- **Piny**: `IR_RX_PIN = GP0` (příjem, aktivní v log. 0, pull-up), `GP5`
  je v komentáři zmíněný jako **IR-TX** (vysílání) přes PIO1 SM0, ale v
  tomhle souboru **není vysílání implementované** — GP5 je zatím jen
  rezervovaný/zadrátovaný pin pro budoucí použití
- Onboard LED na **GP25** bliká synchronně s přijímaným IR signálem — hodí
  se to jako vizuální potvrzení "něco se přijímá", i bez připojeného PC
- Dekóduje protokol **NEC** čistě měřením délek pulzů na hraně přerušení
  (leader pulz, pak 32 bitů adresa/~adresa/příkaz/~příkaz s kontrolou
  negace), včetně rozpoznání "repeat" rámce (držení tlačítka na dálkovém
  ovladači)
- **Použití**:
  ```python
  ir = NEC(pin_num=0, callback=my_fn)   # callback(addr, cmd, repeat)
  # nebo bez callbacku:
  ir = NEC(pin_num=0)
  ir.update()          # zavolat pravidelně (zpracuje nasbírané hrany)
  event = ir.poll()    # vrátí (addr, cmd, repeat) nebo None
  ```

### Třída `MatrixCurrent` — celkový jas displeje

Řídí **3 digitální GPIO piny** (`Iset1=GP7`, `Iset2=GP10`, `Iset3=GP11`),
které dohromady tvoří 3bitové číslo 0–7 (Iset1 = LSB, Iset3 = MSB, všechny
piny v log. 1 = maximální jas). Tenhle 3bitový kód pak mimo tenhle
softwarový soubor (na desce) nastavuje referenční proud, kterým se řídí
celkový jas LED matice — přesný analogový mechanismus (např. odporová síť
apod.) není součástí tohoto `.py` souboru, je to už čistě hardwarová věc na
desce.

```python
current = MatrixCurrent()
current.set_level(5)     # 0 (min) - 7 (max)
current.get_level()
current.step_up()        # o úroveň výš (won't přetéct nad 7)
current.step_down()
current.toggle()         # přepne mezi úplným minimem a maximem
```

---

## `led_matrix_pio.py`

Nejsložitější modul — řídí LED matici 16×32 pomocí dvou stavových strojů
**PIO** (Programmable I/O v RP2040), plus dvě vlákna (Core 0 / Core 1).

### Piny

| Signál | Pin |
|---|---|
| row_mosi | GP3 |
| row_clk | GP2 |
| row_latch | GP1 |
| col_mosi | GP15 |
| col_clk | GP14 |
| col_latch | GP12 |
| col_OE (aktivní v log. 0) | GP13 |

### Princip multiplexování

Displej se zobrazuje po jednotlivých řádcích (multiplexování — viz i
[HW.md](HW.md#multiplexování-led-matice-a-stmívání)):

1. **SM0** (`col_program`, 8 MHz) nejdřív zhasne výstup (OE=1), pošle
   signál SM1, ať připraví "slepý" řádek (všechny řádky odpojené) a počká,
   až SM1 potvrdí
2. Nasype 32 bitů dat pro sloupce do posuvného registru a zacvakne je
   (`col_latch`)
3. Pošle signál SM1, ať tentokrát připraví **skutečný** vybraný řádek, počká
   na potvrzení
4. Zapne výstup (OE=0) a chvíli počká (řádek svítí)
5. Opakuje se pro další řádek

**SM1** (`row_program`, 2 MHz) jen čeká na signál od SM0, nasype 16 bitů
výběru řádku a zacvakne je (`row_latch`) — volá se **dvakrát na řádek**
(jednou se slepým/nulovým výběrem, jednou se skutečným) právě kvůli kroku
2–3 výše, což zabraňuje "duchům" (ghosting) — přechodovému prosvítnutí
špatného řádku, zatímco se do sloupců teprve nahrávají nová data.

### Stmívání (3 úrovně na bod)

Firmware si interně drží dva bitové obrazy za snímek — `_full` (všechny
body úrovně ≥1) a `_bright` (jen body úrovně 2). Zobrazovací cyklus má
4 fáze (`_GS_CYCLE = (_full, _bright, _bright, _bright)`):

- Bod úrovně **2** (plný jas): je v `_bright`, takže svítí ve všech
  4 fázích → 100 % svitu
- Bod úrovně **1** (tlumeně): je jen v `_full`, které se použije jen
  1 ze 4 fází → **25 %** svitu (ne 50 %, jak by se dalo čekat z názvu
  "half brightness" v úvodním komentáři souboru — to je drobná nepřesnost
  v komentáři, skutečné chování podle kódu je 25 %)
- Bod úrovně **0**: nikde, nesvítí vůbec

Tohle se řeší čistě časováním multiplexu (viz
[HW.md](HW.md#multiplexování-led-matice-a-stmívání)) — je to jiná věc než
celkový jas přes `MatrixCurrent`/Iset piny, který mění fyzický proud, ne
poměr času svícení.

### Souřadnice řádků jsou uvnitř otočené

`set_pixel(row, col, level)` si interně ukládá do `_back[ROWS-1-row][col]`
— řádek 0 podle volajícího kódu (main.py, hry) tedy fyzicky odpovídá
**poslednímu** řádku vnitřního bufferu. To znamená, že displej je fyzicky
zapojený "vzhůru nohama" vůči tomu, jak si ho vnitřně ukládá framebuffer, a
ovladač to sám neviditelně kompenzuje — volající kód (main.py) se o tohle
nemusí starat, řádek 0 je vždy nahoře, jak by se čekalo.

### Core 0 / Core 1

- **Core 1** běží nekonekonečnou smyčku (`_core1_loop`), která pořád dokola
  volá `fill_fifo()` (posílá další snímek do PIO) a mezi tím i volitelný
  **callback** zaregistrovaný přes `register_callback(fn)` — přesně tady se
  do multiplexovací smyčky "zavěsí" `token_ring.py` (jeho `_tick()` metoda),
  aby síťová komunikace běžela nezávisle na tom, co dělá hlavní kód her na
  Core 0.
- **Core 0** (hlavní kód her) jen kreslí do back-bufferu (`set_pixel`,
  `clear`, `fill`, `fill_rect`, ...) a zavolá `show()`, když je snímek
  hotový — `show()` jen přepočítá `_full`/`_bright` z back-bufferu, samotné
  posílání do PIO běží pořád na Core 1 na pozadí.

### API

```python
from led_matrix_pio import *
start()                         # spustí PIO + Core 1 smyčku
set_pixel(row, col, level)      # level: 0=off, 1=tlumeně, 2=plně
get_pixel(row, col)
clear()
fill(level=2)
show()                           # přepočítá _full/_bright z back-bufferu
draw_hline(row, col, w, level)
draw_vline(col, row, h, level)  # pozor - row/col je tu v OPAČNÉM pořadí než u draw_hline!
draw_rect(row, col, h, w, level)
fill_rect(row, col, h, w, level)
scroll_left(n) / scroll_right(n)
register_callback(fn)           # zaregistruje funkci volanou na Core 1 mezi snímky
stop()
```

⚠️ **Pozor na pořadí parametrů `h, w`** (výška, pak šířka) u `fill_rect` a
`draw_rect` — je to jiné pořadí, než by člověk čekal ("šířka, výška"), a
zrovna v tomhle souboru se navíc `draw_hline`/`draw_vline` neshodují ani
samy mezi sebou (`draw_vline` má `col` a `row` prohozené oproti
`draw_hline`). Při čtení `main.py` jsem narazil na **tři místa, kde jsou
parametry `fill_rect` pravděpodobně prohozené** oproti tomuhle skutečnému
pořadí:

- sloupcový ukazatel jasu v **SETTINGS** (vykreslí se jako 3 řádky × 2
  sloupce místo zamýšlených ~2 řádků × 3 sloupce)
- záblesk megastřely v **GALAGA** (šířka/výška výbuchu prohozené — většinou
  neviditelné, protože výbuch bývá symetrický, ale u okraje displeje by se
  mohl neplánovaně oříznout v jiném rozměru, než by měl)
- kabina výtahu v **ELEVATOR** (vykreslí se jako 1 sloupec × 2 řádky místo
  zamýšlených 2 sloupců × 1 řádek)

Žádné z toho nespadne ani se nezasekne, jde jen o drobné vizuální
nepřesnosti — zmiňuji to tu, protože bez skutečného zdrojového kódu tohohle
souboru nebylo možné poznat, že se jedná o mou vlastní chybu při psaní
`main.py`, ne o neověřený předpoklad.

---

## `token_ring.py`

Kompletní implementace řetězcového (daisy-chain) propojení pro víc hráčů
přes UART1 (**TX = GP8, RX = GP9**, 115200 baud). Tohle je jádro toho, jak
funguje multiplayer popsaný v [HW.md](HW.md#propojení-pro-více-hráčů-řetězec).

### Formát paketu (11 bajtů)

| Bajt | Význam |
|---|---|
| 0 | sync1 (`0xAA`) |
| 1 | sync2 (`0x55`) |
| 2 | ORIGIN — id zařízení, které paket vyslalo (poslední bajt `machine.unique_id()`) |
| 3 | HOP_COUNT — při každém přeposlání se zvýší o 1 |
| 4 | SEQ — pořadové číslo |
| 5 | FLAGS — rezervováno |
| 6 | BUTTONS — bit0=fire1, bit1=right, bit2=left, bit3=down, bit4=up, bit5=fire2 |
| 7–8 | PAYLOAD — rezervováno |
| 10 | CRC (XOR bajtů 2–9) |

Každé zařízení navíc jednou za vteřinu (výchozí `heartbeat_ms`) posílá i
čitelný textový řádek (`HB <id> <uptime> mem=... ring=... lat=... ...`) s
diagnostickými údaji — to není součást herního paketu, posílá se to vždy,
nezávisle na stavu řetězce, a přijaté řádky se vypisují do konzole s
prefixem `<<< `.

### Použití (z jiného kódu)

```python
from token_ring import TokenRing
ring = TokenRing()
ring.start()               # zaregistruje se do PIO smyčky (Core 1)
ring.send_buttons(byte)    # volat z hlavní smyčky, každý průchod
ring.get_state()           # {id_zařízení: byte_tlačítek, ...}
ring.get_info()            # (velikost řetězce, latence v ms)
ring.node_id()             # vlastní id tohoto zařízení
TokenRing.buttons_byte(fire1, right, left, down, up, fire2)  # sbalí stav do bajtu
TokenRing.unpack_buttons(byte)  # rozbalí bajt zpět na jednotlivé booleany
```

### Samostatné spuštění

Soubor jde spustit i sám o sobě — projde postupně několika kroky (surový
UART loopback test, test jednoho paketu, test heartbeatu, 10s syrový
monitor příchozích bajtů, a nakonec plnou smyčku s `ring.debug = True`, kde
se vypisuje každá odeslaná/přijatá/přeposlaná zpráva). Hodí se to hlavně na
ověření zapojení GP8/GP9 mezi dvěma zařízeními, než se zkouší cokoliv výš
(hry pro dva hráče apod.).
