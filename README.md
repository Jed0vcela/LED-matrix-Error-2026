# LED Matrix Handheld — herní konzole s více hrami

Kapesní zařízení s LED maticí 32×16, postavené na Raspberry Pi Pico (RP2040)
s MicroPythonem. Samotné zařízení nabízí přes 20 vestavěných her a
pomůcek; víc zařízení lze propojit řetězcem po UART pro hry pro dva hráče
a sdílené režimy. K desce lze navíc připojit externí gamepad.
![popis obrázku](dokumentace%20CZ/IMG_20260721_112653.jpg)

## Co to umí

- **20+ vestavěných her**: Snake, Breakout, uhýbačka ve stylu Flappy Bird,
  zjednodušená Galaga a Asteroids (obě s "megastřelou" po podržení
  tlačítka), Frogger, test reflexů, Missile Command, závodní uhýbač ve 4
  pruzích, běžecká hra ve stylu T-Rex se skutečnou skokovou fyzikou,
  paměťová hra ve stylu Simon a simulace rozvážejícího výtahu s plným
  rizikovým "MLG" režimem (detaily viz dokumentace firmware)
- **Podpora pro dva hráče** přes jednoduchý řetězec po UART — žádné
  párování, žádné adresování, stačí propojit zařízení TX→RX za sebou.
  Zahrnuje 2P Snake, 2P Pong, 2P Tron (light cycles) a sdílené 2P Malování /
  2P Game of Life
- **Pomůcky**: volné kreslení, Conwayova hra Life, hodiny, stopky, režim
  šetřiče displeje a nastavení (ruční nebo automatický jas podle
  světelného čidla, hodiny a přepínač zobrazení skóre po konci hry)
- **Senzory**: IR přijímač (vstup z dálkového ovladače, protokol NEC) a
  fotodioda (automatický jas podle okolního světla)
- **Externí gamepad** přes 9pinový D-sub konektor (pinout kompatibilní s
  Atari) — viz [HW.md](dokumentace%20CZ/HW.md)

## Návrhové nástroje

- **PCB** je nakreslené v [KiCad](https://www.kicad.org/) — je to zdarma a
  open-source, takže si projekt může kdokoliv doma otevřít, prohlédnout a
  upravit bez placené licence.
- **3D návrh** (krabička apod.) je vytvořený v Solidworks. Díly určené k
  3D tisku jsou ale exportované i jako `.STL` — to je běžný formát, se
  kterým si poradí prakticky jakýkoliv slicer/3D tiskárna, i bez Solidworks.

Detaily k oběma najdeš v [HW.md](dokumentace%20CZ/HW.md).

## Dokumentace

Kompletní rozpis každé hry a nastavení: **[FW_v1.0.md](dokumentace%20CZ/FW/v1.0/FW_v1.0.md)**

Zapojení, piny, gamepad a jak používat IR přijímač / fotodiodu:
**[HW.md](dokumentace%20CZ/HW.md)**

Popis podpůrných zdrojových souborů (co jde spustit samostatně, jak se dají
upravovat): **[ZDROJOVE_KODY.md](dokumentace%20CZ/ZDROJOVE_KODY.md)**

## Jak začít

1. **Nainstaluj Thonny** (IDE, kterým se kód MicroPythonu píše/nahrává do
   zařízení): [thonny.org](https://thonny.org/)
2. **Nahraj firmware do zařízení**: 
   [Jak nahrát soubory do zařízení (YouTube)](https://youtu.be/NCa7N6zXSKU?si=G6rsxXgdZRCBtUNG)
3. Pokud si stavíš vlastní zařízení od nuly, zapoj hardware podle
   **[HW.md](dokumentace%20CZ/HW.md)**.
4. Pro hry pro dva hráče propoj UART druhého zařízení podle
   [HW.md](dokumentace%20CZ/HW.md#propojení-pro-více-hráčů-řetězec) a zapni
   obě zařízení.

## Struktura repozitáře

```
README.md                          <- tenhle soubor (v rootu)
dokumentace CZ/
  HW.md                            <- zapojení hardwaru, gamepad, PCB/3D, IR/fotodioda
  ZDROJOVE_KODY.md                 <- popis podpůrných zdrojových souborů
  obrazky/                         <- obrázky použité v .md souborech
  FW/
    v1.0/
      FW_v1.0.md                   <- kompletní dokumentace firmware v1.0
    v1.1/ (do budoucna)
      FW_v1.1.md
main.py                            <- zdrojový kód firmware (doplnit / dle verze)
```

Každá verze firmware má vlastní složku a vlastní dokumentaci, takže i starší
verze zůstanou zdokumentované i po přidání novějších. Mezi jednotlivými
`.md` soubory se dá procházet přes odkazy přímo v textu.

## Aktuální verze firmware

**v1.0** — kompletní dokumentace her a nastavení je v
[FW_v1.0.md](dokumentace%20CZ/FW/v1.0/FW_v1.0.md).

