[⬅ Zpět na README](../README.md) · [Dokumentace firmware v1.0 →](FW/v1.0/FW_v1.0.md) · [Popis zdrojových souborů →](ZDROJOVE_KODY.md)

# Hardwarová dokumentace

Popisuje fyzické zapojení, návrhové nástroje a dvě "chytré" periferie (IR
přijímač a fotodioda).

## Přehled

- **Mikrokontrolér**: Raspberry Pi Pico / RP2040, MicroPython
- **Displej**: LED matice 32×16, multiplexovaná, řízená přes PIO (viz níže)
- **Vstup**: 6 tlačítek (nahoru, dolů, vlevo, vpravo, Fire1, Fire2) +
  1 rotační enkodér se vestavěným tlačítkem, plus volitelný externí gamepad
- **Propojení pro více hráčů**: řetězec (daisy-chain) po UART mezi zařízeními
  (viz níže)
- **Navíc**: IR přijímač (dálkové ovládání, protokol NEC), fotodioda
  (měření okolního světla pro automatický jas), reálný čas (interní RTC
  RP2040 přes `machine.RTC()`)

## Návrhové nástroje

- **PCB** je nakreslené v **KiCad**. KiCad je zdarma a open-source, takže
  projekt (schéma i desku) může kdokoliv otevřít doma, prohlédnout si ho a
  rovnou upravit — není potřeba žádná placená licence ani export do
  proprietárního formátu.
- **3D návrh** (krabička, mechanické díly) je nakreslený v **Solidworks**.
  Díly určené k 3D tisku jsou ale exportované i jako **`.STL`** — to je
  standardní formát pro 3D tisk, který přečte prakticky každý slicer i bez
  Solidworks.

## Co je GPIO

GPIO ("General Purpose Input/Output") je obecný digitální pin
mikrokontroléru, který jde v softwaru nastavit jako vstup nebo výstup a číst
z něj/zapisovat do něj logickou 0 nebo 1. Některé GPIO piny na RP2040 mají
navíc i **ADC** funkci — umí kromě digitálního 0/1 změřit i analogové napětí
(0–3,3 V). Právě tahle dvojí schopnost (digitální i analogové čtení na
stejném fyzickém pinu) je důvod, proč je GP27 níže v tabulce zajímavý — dá
se použít jak na jednoduché zapnuto/vypnuto ovládání něčeho externího, tak
na měření analogové úrovně nějakého vnějšího signálu.

## Kompletní zapojení pinů (RP2040)

| Pin | Funkce |
|---|---|
| GP0 | IR_RX (IR přijímač) |
| GP1 | row_latch |
| GP2 | row_clk |
| GP3 | row_mosi |
| GP4 | encoder B |
| GP5 | IR_TX (IR vysílač) |
| GP6 | encoder A |
| GP7 | Iset1 (LSB pro řízení jasu displeje) |
| GP8 | TX (pro multiplayer) |
| GP9 | RX (pro multiplayer) |
| GP10 | Iset2 (pro řízení jasu displeje) |
| GP11 | Iset3 (MSB pro řízení jasu displeje) |
| GP12 | LATCH (pro shift register sloupců) |
| GP13 | OE (output enable pro shift register sloupců) |
| GP14 | CLK (pro shift register sloupců) |
| GP15 | MOSI (pro shift register sloupců) |
| GP16 | button1 / fire1 (aktivní v log. 0) |
| GP17 | right (aktivní v log. 0) |
| GP18 | left (aktivní v log. 0) |
| GP19 | down (aktivní v log. 0) |
| GP20 | up (aktivní v log. 0) |
| GP21 | button2 / fire2 (aktivní v log. 0) |
| GP22 | tlačítko enkodéru |
| GP25 | onboard LED (bliká souběžně s přijímaným IR signálem, jen pro ladění) |
| GP26 | volný pin |
| GP27 | vyvedeno na 9pinový D-sub, umí digitální i ADC — viz sekce o gamepadu níže |
| GP28 | ADC, připojeno na fotodiodu — viz sekce o fotodiodě níže |

Tlačítka (GP16–GP21, GP22) se čtou jako **aktivní v log. 0** (stisknuto =
pin čte 0) — jsou tedy zapojená s pull-upem a spínačem, který při stisku
stáhne pin na zem.

Pár doplňujících technických detailů k vybraným pinům:

- **GP0** (IR přijímač) — digitální vstup, běžný IR demodulátor na 38 kHz
- **GP28** (fotodioda) — jde o ADC kanál **ADC2**
- **GP8/GP9** (řetězec pro více hráčů) — UART1, 115200 baud, 8N1

⚠️ **Známá chyba v návrhu desky**: rotační enkodér se při návrhu omylem
zapomněl připojit k Raspberry Pi Pico, takže se musel na hotové desce
zapojit ručně (mimo původní návrh DPS). Zapojení podle tabulky výše (GP4 =
B, GP6 = A, GP22 = tlačítko) ale odpovídá tomu, jak je to nakonec skutečně
zadrátované — detail ručního zapojení je na fotkách ve složce
[`obrazky/`](obrazky/).

## Externí gamepad (9pinový D-sub, pinout Atari)

K desce lze připojit externí gamepad přes **9pinový D-sub konektor** se
stejným pinoutem, jaký používaly ovladače konzole **Atari** — takže by na
desku měl jít připojit i leckterý originální/dobový Atari ovladač. Tlačítka
na gamepadu jsou zapojená **paralelně** k odpovídajícím tlačítkům přímo na
desce, takže elektricky jde jen o druhé místo ovládání téhož vstupu:
firmware nijak nepozná, jestli bylo zmáčknuté tlačítko na desce, nebo to
odpovídající na gamepadu, a pokud je stisknuté aspoň jedno z nich, vstup se
vyhodnotí jako stisknutý (log. 0 "vyhrává").

Konektor navíc vyvádí i dva signály navíc, nad rámec samotných tlačítek:

- **GP27** — nevyužitý GPIO pin, vyvedený na konektor, s funkcí digitálního
  I/O i **ADC**. Dá se tedy použít jak k jednoduchému zapnutí/vypnutí něčeho
  externího, tak k měření analogové úrovně nějakého vnějšího signálu. Pin má
  v sérii **1kΩ rezistor** kvůli větší odolnosti proti zkratu (kdyby se na
  něj omylem připojilo něco, co by se pokusilo pin natvrdo zkratovat na
  napájení nebo zem, rezistor omezí proud a ochrání pin/desku).
- **+5V** — na konektoru je vyvedené i napájecí napětí +5V, které lze použít
  k napájení připojené externí periferie (není tedy potřeba pro periferii
  řešit vlastní zdroj).

## Propojení pro více hráčů (řetězec)

Zařízení jsou propojená v řetězci po UART, TX jednoho zařízení do RX
dalšího:

```
Zařízení A  TX(GP8) ──► RX(GP9)  Zařízení B  TX(GP8) ──► RX(GP9)  Zařízení C ...
```

Hru reálně musí spustit jen **poslední** zařízení v řetězci — dřívější
zařízení mohou jen sedět v menu na obrazovce **BTN TEST**, která průběžně
přeposílá jejich vlastní stav tlačítek dál řetězcem. Poslední zařízení
kombinuje svá vlastní tlačítka s tím, co mu bylo přeposláno, a podle toho
běží hry pro dva hráče (2P Snake, 2P Pong, 2P Tron) nebo sdílené režimy
(2P Paint, 2P Life). Žádné vyjednávání/adresování mezi zařízeními neprobíhá
— ten, kdo fyzicky spustil hru pro dva hráče, je vždy "hráč 1", a cokoliv
přijde po řetězci, je vždy "hráč 2".

## Multiplexování LED matice a stmívání

Displej funguje na principu **multiplexování** — v jednu chvíli reálně
svítí vždy jen jeden řádek, ale řádky se přepínají tak rychle, že díky
setrvačnosti oka vypadá výsledek jako celý stálý obrázek najednou. Celé
časování řeší dva stavové stroje **PIO** (Programmable I/O v RP2040) — běží
tedy nezávisle na hlavním procesoru a jeho zatížení, takže obraz
neproblikává ani když CPU zrovna počítá něco náročnějšího. Jeden stavový
stroj nasype data pro sloupce do posuvného registru, druhý mezitím
přepočítá výběr řádku — a kvůli zamezení "duchů" (přechodovému prosvitu
špatného řádku, zatímco se do sloupců teprve nahrávají nová data) se výběr
řádku pokaždé nejdřív na okamžik úplně vynuluje, než se nastaví ten
skutečný.

Stmívání funguje na dvou nezávislých úrovních:

- **Jednotlivé body** (úrovně "zhasnuto / tlumeně / jasně") se řeší přímo
  časováním multiplexu — každý bod se v opakujícím se 4fázovém cyklu buď
  zobrazuje pořád (plný jas, 100 % snímků), nebo jen v jedné ze 4 fází
  (tlumeně, 25 % snímků), nebo vůbec.
- **Celkový jas celého displeje** (0–7) se nastavuje jinak — 3 digitální
  GPIO piny (`Iset1/2/3`) tvoří dohromady 3bitové číslo, které mimo tenhle
  software (už na desce) nastavuje referenční proud pro LED. Nejde tedy o
  další úroveň PWM navíc, ale o přímou změnu velikosti proudu, kterým jsou
  rozsvícené LED buzené — nezávisle na tom, jestli zrovna svítí "tlumeně"
  nebo "jasně" podle bodu výše.

Podrobný popis obou mechanismů (a jak přesně PIO kód pracuje) je v
[ZDROJOVE_KODY.md](ZDROJOVE_KODY.md#led_matrix_piopy).

## Použití IR přijímače

Firmware obsahuje IR přijímač s protokolem NEC na GP0. Aktuálně ho využívá
jen **SNAKE**, kde může řídit hada jako alternativu k tlačítkům. Namiř na
přijímač běžný dálkový ovladač s protokolem NEC (má ho spousta levných
univerzálních/TV ovladačů, typicky přiložených k levným RGB LED pásкům).

Konkrétní namapované kódy tlačítek (viz `process_ir()` v `main.py`):

| Kód příkazu (NEC) | Tlačítko na ovladači | Efekt |
|---|---|---|
| `0x0B` | nahoru | otočí hada (jako Fire1/Fire2 — ne absolutní směr jako fyzická šipka) |
| `0x0F` | dolů | otočí hada opačným směrem |
| `0x49` | vlevo | otočí hada stejným směrem jako "nahoru" |
| `0x4A` | vpravo | otočí hada stejným směrem jako "dolů" |
| `0x01` | hvězdička (`*`) | ztlumit displej |
| `0x0A` | mřížka (`#`) | zesvětlit displej |
| `0x0D` | OK | (kód je definovaný, ale zatím se nikde nepoužívá) |

Opakovaný kód, který dálkový ovladač posílá při podrženém tlačítku, se
ignoruje (`IR_CMD` se použije jen jednou za skutečný, ne opakovaný, stisk).

Piny GP0 (příjem) a GP5 (vysílání, zatím nevyužité — viz
[ZDROJOVE_KODY.md](ZDROJOVE_KODY.md#ir_necpy)) jsou popsané podrobněji v
dokumentaci zdrojových souborů.

## Použití fotodiody (automatický jas)

Fotodioda na GP28 umožňuje zařízení samo přizpůsobovat jas displeje podle
okolního světla, místo ručního nastavování. Je zapojená ve
**fotovoltaickém módu** (bez předpětí) — v tomhle zapojení fotodioda sama
generuje napětí úměrné světlu, ale s **logaritmickou** odezvou na intenzitu
světla, ne lineární. Prakticky to znamená, že fotodioda je citlivá na malé
změny jasu v šeru (kde logaritmus roste rychle) a zároveň nesaturuje na
plné slunci (kde logaritmus roste už jen pomalu) — jedním zapojením tak jde
rozumně pokrýt jak velmi tmavé, tak velmi jasné prostředí, aniž by bylo
potřeba přepínat rozsah. To se označuje jako zvětšení **dynamického
rozsahu** čidla.

- Jdi do **SETTINGS**, vyber pole s režimem jasu a otočením enkodéru přepni
  z `MAN` na `AUTO`
- V režimu AUTO se syrová hodnota z ADC přemapuje na jas zhruba takhle:
  - syrová hodnota ≤ 3000 → minimální jas
  - syrová hodnota ≥ 7000 → maximální jas
  - lineárně mezi tím
- Tohle přemapování není myšlené jako přesné — je to hrubá, levná
  (počítaná bitovým posunem) interpolace, odhadnutá od oka, ne podle
  změřené křivky v luxech. Pokud to na tvém typickém osvětlení působí moc
  tmavě/světle, právě tahle dvě prahová čísla (3000 / 7000) jsou to, co má
  smysl doladit.
- Automatický jas se přepočítává zhruba každých 300 ms a funguje i během
  hraní, ne jen v obrazovce Nastavení.

### Analýza signálu z fotodiody (`adc_sampler.py`)

Ve zdrojových kódech je i pomocný skript **`adc_sampler.py`**, který měří
hodnoty na fotodiodě relativně rychle (mnohem rychleji, než firmware
potřebuje pro automatický jas) a výsledky vypisuje do konzole v **CSV**
formátu. Takový výstup jde zkopírovat a otevřít třeba v Excelu a udělat z
něj graf — díky tomu jde odhalit i jevy, které lidské oko normálně nezachytí,
například světlo, které bliká (např. kvůli PWM stmívání) tak rychle, že to
oko vnímá jako stále svítící, ale na grafu z rychlého vzorkování je blikání
jasně vidět. Podrobnější popis viz
[`ZDROJOVE_KODY.md`](ZDROJOVE_KODY.md#adc_samplerpy).

## Co v tomhle dokumentu chybí

- Chybí poznámky ke krabičce/mechanické montáži.
- Chybí přesná specifikace napájení (napětí/konektor napájecího zdroje celé
  desky).
- Přesné přiřazení jednotlivých signálů (6 tlačítek, +5V, GP27, GND) k
  fyzickým číslům pinů 1–9 na D-sub konektoru není potvrzené — výše je
  jen jejich seznam, ne mapování na konkrétní čísla pinů konektoru.
- Přesný analogový mechanismus, kterým piny Iset1/2/3 na desce mění
  referenční proud (např. konkrétní zapojení odporové sítě), není součástí
  žádného `.py` souboru, takže to tu není popsané — jde o čistě hardwarovou
  věc na desce/schématu.
