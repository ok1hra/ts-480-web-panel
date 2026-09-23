# TS-480: protokol mezi panelem a rádiem

Tady je souhrn toho, co je o protokolu známo. Vychází z reverzního inženýrství
[stianeklund/TS-480-Panel](https://github.com/stianeklund/TS-480-Panel) (logické
analyzátory, výpisy), z dokumentace RemoteRig a z manuálu TS-480. Každá položka
má značku. **✔** znamená, že je vidět v zachyceném provozu. **?** je odhad, který
je potřeba ověřit (`tools/sniff.py`).

## Fyzická vrstva ✔

| RJ12 pin | signál | poznámka |
|---|---|---|
| 1 | SPK GND | zem reproduktoru |
| 2 | +8 V | napájení panelu, na rádiu je trvale |
| 3 | GND | |
| 4 | RDO | UART rádio → panel, 5 V TTL |
| 5 | TDO | UART panel → rádio, 5 V TTL |
| 6 | AF | nf výstup na reproduktor |

Linka je 57600 Bd, 8N1, v klidu v úrovni H (neinvertovaná TTL, **ne RS-232**).
Hlavní MCU rádia (IC204) běží na 3,3 V, ale na konektoru je 5 V TTL. Převodník
USB-UART proto musí 5 V snést.

## Rámcování ✔

`<příkaz 1 bajt><data…>\r`. Rámec vždy končí CR (0x0D). Bajty s ikonami
(bitové masky) mají vždy nastavený bit 7 (0x80 | bity), takže se CR nemůže
objevit uvnitř dat. Významy písmen se podle směru liší (například `O`, `P`, `S`).

## Udržování spojení ✔

* Obě strany posílají `FF \r`. Rádio zhruba každou 1 s, panel na něj hned
  odpoví a posílá i vlastní, zhruba každou 1 s. (Starší poznámky uvádějí 2 s
  a 5 s, ale záznam `Bootsequence` ukazuje periodu 1000 ms.)
* Panel po připojení pošle `02`. Rádio odpoví `00` (vypnuto) nebo `01`
  a pošle kompletní překreslení displeje.
* Po zapnutí přijde zhruba za 5 s celý stav displeje. Rádio pak pošle dotaz
  `O`. Panel na něj odpoví polohou potenciometrů `X…`, `V…`, `W…` a `FF`.

## Panel → rádio

| rámec | význam | stav |
|---|---|---|
| `<kód><stav>` | klávesa, stav `0` puštěno, `1` stisk, `3` dlouhý stisk, `4` držení | ✔ |
| `S hhhh` | hlavní VFO, 16bit delta v dvojkovém doplňku (`S0001`, `SFFFE`). Panel sčítá impulsy a posílá je asi 8× za s | ✔ |
| `T hh` | MULTI/CH, 8bit se znaménkem | ✔ |
| `U hh` | RIT/XIT knoflík, 8bit se znaménkem | ✔ |
| `V hh` | AF (hlasitost) 00–FF, absolutní hodnota | ✔ |
| `W hh` | SQL 00–FF | ✔ |
| `X hhhh` | IF SHIFT 0000–03FE, střed 01FF | ✔ |
| `02` | reconnect / žádost o stav | ✔ |
| `FF` | keepalive | ✔ |

Kódy kláves: `0` ⏻, `2` PF, `!` ATT/PRE, `3` AT, `4` CH1/1, `5` CH2/2,
`6` CH3/3, `7` PWR/4, `8` MIC/5, `9` KEY/6, `:` NB/7, `<` VOX/8, `;` PROC/9,
`=` MTR/CLR, `>` AGC/0, `?` ENT, `@` DNL, `A` NR, `B` FIL, `C` BC, `D` FINE,
`G` MENU, `H` MHz, `I` A=B, `J` A/B, `K` QMI, `L` QMR, `M` CL, `N` RIT,
`O` XIT, `P` ◀ pásmo, `Q` ▶ pásmo ✔.
**MODE = `E` ?, SCAN = `F` ?** Tyto dva kódy v dokumentaci chybí a jsou to
jediné volné kódy v řadě.

Chování VFO z měření: zhruba 0,5 až 5 Hz na impuls podle kroku a režimu FINE.
Přepočet dělá rádio.

## Rádio → panel

| rámec | význam | stav |
|---|---|---|
| `00` / `01` / `02` | vypnuto / zapnuto / zapnuto z PC | ✔ |
| `; ccccccc` | hlavní 7segmentový displej, 7 znaků, jednotky 10 Hz (`;2806697` = 28.066.97) | ✔ |
| `< cccccccc` | stavový řádek, 8 znaků (RIT/XIT/split, menu) | ✔ |
| `= aabb` | bargraf: `aa` = S/PO 00–20 dílků, `bb` = SWR/ALC/COMP | ✔ / ? `bb` |
| `> 7n` | výběr druhého měřidla (71/72/73) | ? |
| `F b1 b2 b3` | desetinné tečky: `b1` pro frekvenci (0x89 → `28.066.97`), `b2` pro stavový řádek (0x81 → `1.760`) | ✔ / ? mapování bitů |
| `? b` | PRE, ATT, PROC, VOX, NB, MHz, FINE (bity 0–6) | ✔ |
| `@ b` | ★(QM), ★, ANT1, ANT2, MENU, M.CH, M.SCR | ✔ |
| `A b` | AGC, ?, -F, NAR, 2, LOCK, REC | ✔ |
| `B b` | BC/NR/DNL/EQ, bity nejsou zmapované | ? |
| `C b` | T, CT, (F.)LOCK, PC, RIT, XIT, AUTO | ✔ |
| `D b` | A, B, M, SPLIT, ▸T, ◂R, AT | ✔ |
| `E b` | šipky ◂ ▸ (VFO/paměť) | ✔ |
| `L b` | neznámé | ? |
| `: cc` | číslo menu/kanálu (`:  ` = zhasnuto) | ✔ |
| `P cc`, `R n`, `2…` | položka menu, parametr. `20` maže | částečně |
| `6 n` | jas displeje 0–4 | ✔ |
| `7 n` | podsvícení kláves 0/1 | ✔ |
| `8 n` | LED: 0 zhasnuto, 1 RX (zelená), 2 TX (červená) | ✔ |
| `9 n` | druh provozu. Tabulka číslic je odhad | ? |
| `S n` | chybový kód 0–7 | ✔ |
| `Q n` | varianta modelu (Q0 RX only / Q1 TWIN PWR) | ✔ |
| `O` | dotaz na polohu potenciometrů | ✔ |
| `3n` | neznámé (`31`, `33` při TX) | ? |

## Co zatím chybí

* Mapování číslice druhu provozu `9n`, bitů `B` a `L`.
* Glyfy bajtů ≥ 0x80 ve frekvenčním poli (servisní režim, menu).
* Přesné načasování stavů `3`/`4` u dlouhého stisku.
* Chování na timeout: jak dlouho rádio toleruje chybějící keepalive.
