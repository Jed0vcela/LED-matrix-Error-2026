[⬅ Zpět na README](../../../README.md) · [Hardwarová dokumentace](../../HW.md) · [Popis zdrojových souborů →](../../ZDROJOVE_KODY.md)

# Firmware v1.0 — Kompletní dokumentace

Tento dokument popisuje každou položku menu ve firmware v1.0: co dělá, jak se
ovládá a co mění jednotlivá nastavení/obtížnosti. Položky menu jsou seřazené
tak, jak se objevují na zařízení.

Zapojení hardwaru, gamepad a jak používat IR přijímač / fotodiodu najdeš v
[`HW.md`](../../HW.md). Návod na nahrání firmware je v hlavním
[`README.md`](../../../README.md).

---

## Přehled ovládání

| Vstup | Popis |
|---|---|
| Šipky (nahoru/dolů/vlevo/vpravo) | Směr / pohyb v menu / pohyb ve hře |
| Fire1, Fire2 | Akční tlačítka — význam záleží na konkrétní hře |
| Enkodér (otáčení) | Pohyb v menu, jas, nastavení hodnot |
| Enkodér (stisk) | Potvrzení výběru / **ukončení aktuální hry zpět do menu** |

**Z každé hry a obrazovky lze odejít stiskem enkodéru.**
Podržení šipky se tam, kde to dává smysl (Malování, Game of Life, Výtah 2),
samo opakuje; jinde jeden stisk = jeden krok.

Poznámka: k desce lze připojit i externí gamepad (9pinový D-sub, pinout
Atari) — jeho tlačítka jsou zapojená paralelně s tlačítky na desce, takže se
ve firmware chovají úplně stejně a nic z toho, co je popsané níže, se tím
nemění. Detaily viz [`HW.md`](../../HW.md).

---

## Menu

Hlavní menu ukazuje 3 položky najednou; otáčením enkodéru se posouvá výběr,
stiskem se potvrzuje. Menu si pamatuje poslední pozici — po ukončení hry se
znovu otevře tam, kde jsi skončil, ne úplně nahoře (po vypnutí/resetu se to
ale vynuluje).

Hry s **obrazovkou výběru obtížnosti/režimu** ji ukážou hned po spuštění,
ještě před samotnou hrou. Na těchto obrazovkách: šipky nahoru/dolů NEBO
enkodér mění volbu, Fire1/Fire2 NEBO stisk enkodéru ji potvrdí.

---

## SNAKE

Klasický had pro jednoho hráče. Zabíjí ho zeď i vlastní tělo.

- **Šipky**: absolutní směr (nejde se hned otočit do protisměru)
- **Fire1 / Fire2**: otočení doleva / doprava vůči aktuálnímu směru
- Sezobnutí jídla prodlouží hada a hru mírně zrychlí (až na minimum 80 ms na krok)
- **Skóre** = snězené jídlo

---

## 2P SNAKE

Stejná pravidla jako Snake, ale hrají dvě zařízení propojená řetězcem
(daisy-chain) na stejné ploše — každé zařízení ukazuje na svém displeji oba
hady. Hráč 1 je vždy lokální zařízení; hada hráče 2 řídí to, co přes řetězec
přijde jako stav tlačítek.

- Na začátku krátce čeká, jestli se v řetězci objeví druhé zařízení; pokud se
  do ~3 vteřin neobjeví, ukáže `NO P2` a vrátí se do menu
- Kolize: náraz do zdi, do **vlastního** těla nebo do těla **druhého hráče**
  ukončí hru danému hráči. Čelní srážka (oba hadi vjedou do stejného pole)
  ukončí hru oběma najednou
- Skóre se nezobrazuje — jde jen o to přežít déle než soupeř

---

## LIFE

Conwayova hra Life. Po spuštění hned běží s náhodnou počáteční deskou.

- **Fire1**: pauza / pokračování simulace
- **Šipky**: pohyb kurzoru (jen v pauze; podržením se pohyb opakuje)
- **Fire2**: přepnutí buňky pod kurzorem (jen v pauze)
- **Podržení Fire2 při pohybu**: kreslí souvisle — každá nová buňka, na
  kterou kurzor najede, rovnou ožije, místo aby se přepínala jen ta jedna,
  na které jsi začal
- **Enkodér**: rychlost simulace, 1–50 generací za vteřinu

**Multiplayer**: při spuštění hra krátce zkontroluje řetězec, jestli
neodpovídá druhé zařízení. Pokud ano, objeví se druhý kurzor ovládaný
šipkami/Fire2 druhého zařízení na stejné sdílené ploše. Pokud se nikdo
neozve, hraje se úplně stejně jako pro jednoho hráče — nic jiného se nemění.

Důležité: **pauza/běh reaguje vždy jen na lokální Fire1.** Fire1 druhého
zařízení se pro tohle ignoruje — jinak by si obě zařízení mohla myslet, že
simulace běží/je pozastavená jinak, protože stav pauzy samotný se po síti
nepřenáší.

---

## BREAKOUT

Jednohráčský breakout/pong.

- **Šipky (vlevo/vpravo) nebo enkodér**: pohyb pálky
- **Fire1 / Fire2**: vypuštění míčku (před vypuštěním se jen ukazuje pozice
  míčku; jakmile je ve hře, jeho minutí ukončí hru)
- Zbourání všech cihliček = výhra (pět oslavných bliknutí); minutí míčku =
  konec hry
- **Skóre** = rozbité cihličky

---

## 2P PONG

Pong pro dva hráče přes řetězec. Zařízení, na kterém tahle funkce běží, je
**vždy** dolní pálka (hráč 1) a vždy to, které počítá fyziku míčku a ukazuje
skóre; zařízení dál v řetězci je **vždy** hráč 2 (horní pálka), řízené tím,
co se k němu přepošle. Žádné vyjednávání "kdo je hráč 1" neprobíhá — je to
prostě ten, kdo hru spustil, versus ten, kdo mu posílá data.

- Čeká na druhé zařízení v řetězci (stejně jako 2P Snake); pokud nikoho
  nenajde, ukáže `NO P2`
- Odpočet 3-2-1 před vypuštěním míčku — **pálky jsou vidět a dají se hýbat i
  během odpočtu**
- **Šipky (vlevo/vpravo)**: pohyb vlastní pálky (enkodér pálku NEŘídí —
  úmyslně to bylo odstraněno, protože to způsobovalo zaseknutí pálky; stisk
  enkodéru pořád funguje jako odchod ze hry)
- Vítězí, kdo první dosáhne 5 bodů

---

## FLAPPY

Uhýbací hra s mezerami v překážkách.

- Výběr obtížnosti: **EASY / NORMAL / HARD** (rychlost)
- **Nahoru / dolů**: pohyb
- **Fire1 / Fire2**: výstřel (má smysl jen v režimu HARD, viz níže)
- Odpočet 3-2-1, pak se rovnou začne hýbat — není potřeba nic mačkat na
  spuštění
- **Režim HARD** přidává rozbitné bariéry uvnitř některých mezer (tlumeně
  zobrazené), které blokují cestu, dokud je nesestřelíš
- **Ukazatel skóre**: místo čísla se horní řádek plní tlumenými body, jak
  roste skóre (1 bod = 1 pixel). Jakmile je celý řádek tlumeně zaplněný,
  začne se stejný řádek znovu "rozsvěcet" na plný jas, pixel po pixelu.
  Jakmile je celý plně jasný, přesune se to na řádek pod ním a opakuje se to.

---

## GALAGA

Zjednodušená střílečka.

- Obrazovka nastavení: **obtížnost** (EASY/NORMAL/HARD, ovlivňuje rychlost
  nepřátel/střel a komíhání formace) a samostatný přepínač **MLG módu**
  (vlevo/vpravo)
- **Vlevo / vpravo**: pohyb lodi
- **Fire1 / Fire2**: střelba
- **Podržení Fire1 nebo Fire2 na 3 vteřiny**: nabije a vypálí megastřelu
  (3×3, při zásahu vybuchne do 5×5) — během nabíjení se loď nemůže hýbat
- Nepřátelé z formace se občas odpojí a zaútočí střemhlav; zásah od
  útočícího nepřítele ukončí hru. Po vyčištění vlny přiletí další
  (nekonečné — konec přijde jen srážkou)
- **Skóre**: 1 bod za sestřelení nepřítele z formace, 2 body za útočícího;
  zásahy megastřelou mají dvojnásobnou hodnotu
- **MLG mód**: každé sestřelení náhodně změní šířku lodi (1–8 pixelů)

---

## ASTEROID

Asteroids v osmi směrech s obtáčením displeje dokola (co zmizí na jedné
straně, objeví se na druhé — platí pro loď, střely i asteroidy).

- Výběr obtížnosti: **EASY / NORMAL / HARD** (počet a rychlost asteroidů)
- **Vlevo / vpravo**: otočení lodi o 45° na stisk (podržením se otáčí dál,
  zhruba 5×/s)
- **Fire1**: tah vpřed ve směru, kam loď míří
- **Fire2**: střelba
- **Podržení Fire2 na 3 vteřiny**: megastřela (3×3, výbuch 5×5), stejný
  princip jako u Galagy — otáčení i tah se během nabíjení zamknou
- **Od druhé vlny výš** je zhruba 1 ze 3 asteroidů "velký" (2×2, vydrží 3
  zásahy místo 1)
- **Skóre**: malý asteroid = 1 bod (2 megastřelou), velký = 3 body (4
  megastřelou)
- Srážka s asteroidem ukončí hru; hitbox lodi správně zacelí diagonální
  mezeru mezi jejími dvěma body při natočení na SV/JV/JZ/SZ, takže tudy
  asteroid nemůže proletět bez povšimnutí

---

## FROGGER

Přechod přes pruhy pohyblivého provozu až na horní okraj.

- Výběr obtížnosti: **EASY / NORMAL / HARD** (rychlost/hustota provozu)
- **Šipky**: pohyb o jedno políčko (krokově, ne plynule)
- Každý čtvrtý pruh je bezpečný "medián" bez provozu
- Dosažení horního okraje = bod, žabák se vrátí dolů; pruhy jedou dál stejným
  tempem
- Zásah provozem ukončí hru

---

## REACTION

Test reflexů.

- Výběr obtížnosti: **EASY / NORMAL / HARD** (počáteční časový limit a jak
  rychle se zkracuje)
- Bliká šipka náhodným směrem; stiskni odpovídající šipku, než čas vyprší
- Každé uhodnuté kolo časový limit dál zkrátí (až na obtížností daný strop)
- Špatný směr nebo vypršení = konec hry
- **Skóre** = přežitá kola

---

## MISSILE

Missile Command.

- Výběr obtížnosti: **EASY / NORMAL / HARD** (rychlost/frekvence raket)
- 4 města dole
- **Vlevo / vpravo**: pohyb mířícího kurzoru
- **Fire1 / Fire2**: odpálení zachytávače — vyletí do pevné výšky a krátce
  poté tam vybuchne do malého okruhu
- Raketa, která dopadne na zem, zničí město, na které dopadla (mimo město =
  netrefí se)
- Ztráta všech 4 měst ukončí hru
- **Skóre** = sestřelené rakety

---

## RACER

Nekonečný uhýbač ve 4 pruzích.

- Výběr obtížnosti: **EASY / NORMAL / HARD** (rychlost/frekvence provozu)
- **Vlevo / vpravo**: přepínání pruhů
- Rychlost roste se skóre
- **Skóre** = úspěšně minuté překážky

---

## 2P TRON

Light-cycles, postavené na stejném principu jako 2P Snake: zařízení, na
kterém tohle běží, je lokální hráč, druhé zařízení řídí přeposílaný stav.
Na rozdíl od Snake se stopa za hráčem **nikdy nezmenšuje** — jen roste.

- **Šipky**: řízení (stejné absolutní ovládání směru jako u Snake)
- Náraz do zdi, do vlastní stopy nebo do stopy druhého hráče ukončí hru
  danému hráči
- Čelní srážka ukončí hru oběma najednou

---

## TREX

Běžecká hra se skutečnou skokovou fyzikou (ne okamžitý skok na pevnou výšku).

- Výběr obtížnosti: **EASY / NORMAL / HARD** (rychlost a rozestupy/frekvence
  překážek; výška překážek je stejná napříč obtížnostmi — HARD je čistě
  rychlejší a přidává ptáky, ne vyšší překážky)
- **Nahoru**: skok. **Podržení nahoru** sníží gravitaci jak při stoupání,
  tak při pádu, takže skok vyjde výš i déle, čím déle se drží
- **Dolů**: okamžité zrušení skoku a pád na zem (ignoruje se prvních ~120 ms
  od odrazu, aby náhodný téměř současný stisk nahoru+dolů nezrušil skok dřív,
  než vůbec vizuálně začne)
- Překážky jsou vždy 2–3 pixely vysoké; základní (bez podržení) skok
  dosáhne zhruba 5 pixelů — 2 pixely rezervy nad nejvyšší možnou překážkou
- Rozestupy překážek mají v sobě trochu náhody místo dokonalé pravidelnosti
- **Režim HARD** přidává létající ptáky ve dvou výškách (nízký jde
  jednoduše přeskočit, vysoký je opravdu riskantní skákat na něj) —
  **Fire1** je sestřelí za bonusové body
- **Skóre** = minuté překážky (+2 za sestřeleného ptáka)

---

## ELEVATOR

Paměťová hra ve stylu Simon. Malá budova se 7 patry; kabina výtahu (jasně
blikající bod) startuje uprostřed.

- Každé kolo se přehraje **celá dosavadní posloupnost** pohybů nahoru/dolů
  (výtah se předtím vrátí doprostřed), pak ji zopakuješ pomocí **nahoru/dolů**
- Posloupnost je vždy zaručeně odehratelná — další náhodný směr se vybírá
  jen z těch, které by výtah nevyvezly mimo budovu
- Špatný krok okamžitě ukončí hru
- **Skóre** = celkový počet správných kroků za celou hru (ne jen nejdelší
  dosažené kolo)
- Bez nastavení/obtížnosti

---

## ELEV2

Rozvážková hra s výtahem. Budova je uprostřed displeje: dvě plné kolejnice s
příčkami jen na úrovni 7 pater (vypadá jako žebřík). Má dva režimy, vybírané
na úvodní obrazovce.

Oba režimy:
- **Nahoru / dolů**: pohyb výtahu o patro (jde podržet, max. 4 patra za
  vteřinu)
- Lidé přichází zleva a řadí se do fronty jeden za druhým, jeden sloupec od
  budovy, aby fronta vizuálně nesplývala s budovou
- **Skóre se zobrazuje vlevo nahoře**, průběžně, po celou dobu

### Režim NORMAL

- Lidé chodí vždy jen z **1. patra** (dole). Čísla pater jsou vůči němu
  relativní — "patro 3" znamená, že výtah musí vyjet 3 patra nad přízemí,
  a zobrazené číslo vždy přesně odpovídá tomu, kolikrát je potřeba
  zmáčknout nahoru
- Cílové patro prvního člověka ve frontě se ukazuje jako **číslice** vpravo,
  dole na displeji
- **Fire1**: vyzvednutí čekajícího na začátku fronty (funguje jen když je
  výtah v přízemí)
- **Fire2**: vysazení cestujícího — správné patro dá **+1** bod, špatné
  patro **−1** (vystoupí tak jako tak)
- Dokud někdo cestuje, číslice se nahradí **pomlčkou** — musíš si pamatovat,
  kam jede, protože je to během jízdy skryté
- Najednou lze vézt jen **jednoho** cestujícího
- Víc než **6 čekajících** ve frontě naráz hru ukončí
- Lidé zpočátku chodí pomalu, postupně čím dál rychleji

### Režim MLG

Rychlejší varianta s vyšší kapacitou a skutečným rizikem.

- Výtah pojme až **10 cestujících** najednou
- Pravá strana budovy ukazuje u každého patra malý počet teček — kolik
  aktuálních cestujících chce zrovna na tohle patro
- **Fire1** nastoupí dalšího čekajícího za každý stisk (do naplnění
  kapacity); **Fire2** vysadí **jednoho** cestujícího za stisk — přednostně
  toho, kdo chce zrovna tohle patro (+1); když nikdo nechce, vysadí prvního
  z fronty cestujících jako špatné patro (−1)
- Ve chvíli, kdy odjedeš z přízemí s někým na palubě, se spustí **časovač
  trasy**: 1 vteřina na cestujícího, zobrazený jako mizející sloupec teček v
  úplně posledním sloupci displeje. Pokud vyprší dřív, než všechny vysadíš,
  hra končí — cílem je naplánovat si trasu předem, než odjedeš z přízemí
- V tomhle režimu není limit fronty, ale zobrazí se jen tolik čekajících,
  kolik se vejde na displej
- Lidé chodí znatelně rychleji než v NORMAL režimu a postupně ještě rychleji

**"Osama"** — zvláštní cestující (bliká, nad ním svítí malý vykřičník, dokud
čeká ve frontě), který se objeví zhruba **1 z 20** krát místo běžného
cestujícího:
- Smí jet jen **sám** — nejde ho vzít, pokud už někoho vezeš, a nejde vzít
  nikoho jiného, dokud je on na palubě
- Jakmile s ním odjedeš z přízemí, má každou vteřinu **20% šanci** vybouchnout
  přímo ve výtahu — přehraje se animace rozšiřujícího se výbuchu a hra skončí
- Jediný způsob, jak ho zneškodnit: dovézt ho na speciální **střešní patro**
  (úplně nahoře) a tam stisknout Fire2. Hodí ho ze střechy — přehraje se
  animace pádu (vodorovná rychlost konstantní, svislá se zrychluje, takže
  dráha vypadá jako čtvrtkruh) — za **+20 bodů**, a riziko výbuchu tím hned
  skončí
- Když dopadne, vybuchne přímo ve frontě — přehraje se pořádná animace
  hřibovitého mraku, celá čekající fronta je zničena a na jejím místě
  vznikne kráter. Ten se viditelně **5 vteřin** zaceluje (fronta zatím
  nepřibývá), pak vše pokračuje normálně
- Ze střechy lze shodit i *běžného* cestujícího — stejná animace pádu, ale
  po dopadu jde jen o menší šplouchnutí, které zničí 2 nejbližší čekající ve
  frontě (bez kráteru), a vždy se to počítá jako špatné patro (−1 bod)

---

## ATTRACT

Šetřič displeje — dokola přehrává pár klidových animací na pozadí (vlnící
se sinusovka, poskakující tvar, šachovnice, "déšť"). Jakékoliv tlačítko
ukončí návrat do menu. Enkodér tady pořád ovládá jas.

---

## PAINT

Volné kreslení bodů po celém displeji.

- **Šipky**: pohyb kurzoru (podržením se opakuje)
- **Fire1**: přepnutí bodu pod kurzorem
- **Podržení Fire1 při pohybu**: kreslí souvisle — každé nové políčko, na
  které kurzor najede, se rozsvítí, místo aby se přepínalo jen to jedno, na
  kterém jsi začal
- **Fire2**: smazání celého plátna
- **Enkodér**: jas
- **Fire1+Fire2 zároveň, nebo stisk enkodéru**: odchod

**Multiplayer**: stejná detekce druhého zařízení jako u Game of Life — pokud
na začátku někdo odpoví v řetězci, objeví se druhý kurzor sdílející stejné
plátno, odlišený blikáním v opačné fázi než ten tvůj. Když se nikdo neozve,
hraje se úplně stejně jako pro jednoho.

---

## TIME

Zobrazení aktuálního času (`HH:MM`, dvojtečka bliká jednou za vteřinu), jen
pro čtení. Čas se nastavuje v **SETTINGS**.

---

## STOPWCH

Stopky.

- **Fire1**: start / pauza (dalším stiskem pokračuje)
- **Fire2**: vynulování (zároveň zastaví)
- V pauze displej mírně ztlumí

---

## BTN TEST

Diagnostická obrazovka: jedna tečka na tlačítko, svítí, dokud je tlačítko
stisknuté. Zároveň průběžně přeposílá stav svých tlačítek dál řetězcem —
takže tahle obrazovka může sloužit jako "ovladač" pro to, co běží na
zařízení dál v řetězci (např. posílá vstup hráče 2 do 2P Pongu).

---

## SETTINGS

- **Režim jasu**: MANUAL nebo AUTO. V MANUAL se jas nastavuje přímo pruhem.
  V AUTO se jas řídí podle fotodiody (syrová hodnota ≤3000 → minimum, ≥7000
  → maximum, lineárně mezi tím) a pruh jen ukazuje aktuální dopočítanou
  hodnotu
- **Hodiny**: hodina a minuta, upravují se po číslici (vlevo/vpravo vybere
  číslici, enkodér ji mění — vždy zabalí na platný čas, takže nikdy nemůže
  vzniknout neplatný údaj). Datum tahle verze firmware nesleduje — jen čas
- **Skóre při konci hry**: přepíná, jestli hry po konci bliknou displejem a
  ukážou skóre. Vypnuto = hra prostě potichu skončí a vrátí se do menu, bez
  blikání a bez ukázání skóre

Mezi poli se pohybuje vlevo/vpravo, vybrané pole se mění enkodérem, odchod
je Fire1/Fire2 nebo stiskem enkodéru.

---

## INFO

Zobrazí číslo verze firmware. Nic dalšího se tu nenastavuje.

---

## Známá omezení v téhle verzi

- Hodiny nemají datum a spoléhají na `machine.RTC()` — na většině desek
  RP2040 tohle **nemá baterii**, takže se čas po výpadku napájení vynuluje,
  pokud tvoje konkrétní deska nemá připojené externí RTC.
- Hry pro dva hráče potřebují, aby už druhé zařízení běželo a přeposílalo
  data v řetězci — appka nijak nerozliší, jestli je problém ve špatném
  zapojení, nebo jen to druhé zařízení ještě neběží.
- Obrazovky výběru obtížnosti/režimu si nepamatují poslední volbu mezi
  spuštěními — vždy se vrátí na NORMAL (nebo první možnost).
