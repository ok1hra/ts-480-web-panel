# TS-480: panel ↔ radio protocol

This is a summary of what is known about the protocol. It is based on the
reverse engineering in
[stianeklund/TS-480-Panel](https://github.com/stianeklund/TS-480-Panel) by
Stian Eklund (logic analyzer captures, dumps), on RemoteRig documentation and
on the TS-480 manual. Every item carries a mark. **✔** means it is seen in
captured traffic. **?** is a guess that still needs to be verified
(`tools/sniff.py`).

## Physical layer ✔

| RJ12 pin | signal | note |
|---|---|---|
| 1 | SPK GND | speaker ground |
| 2 | +8 V | panel supply, always on at the radio |
| 3 | GND | |
| 4 | RDO | UART radio → panel, 5 V TTL |
| 5 | TDO | UART panel → radio, 5 V TTL |
| 6 | AF | audio output to the speaker |

The line runs at 57600 Bd, 8 data bits, no parity, idle high (non-inverted TTL,
**not RS-232**). The tools here transmit with 2 stop bits, like the old
network bridge that worked with this radio. A receiver accepts that as 8N1.
The main MCU of the radio (IC204) runs at 3.3 V, but the connector carries
5 V TTL. The USB-UART adapter must therefore tolerate 5 V.

## Framing ✔

`<command 1 byte><data…>\r`. A frame always ends with CR (0x0D). Icon bytes
(bit masks) always have bit 7 set (0x80 | bits), so CR can never appear inside
the data. The meaning of letters differs by direction (for example `O`, `P`, `S`).

## Keepalive ✔

* Real unit, 2026-11-13: the **radio** sends `FF \r` every **5.0 s**. The
  panel only answers it, 3–17 ms later. The panel sends no keepalive of its own.
* If the panel does not answer, the radio **switches itself off** within
  about 4 s (measured: `PS0` over CAT 3.8 s after the panel link was cut).
* Power on from the panel: the panel sends `01` (POWER key). The radio answers
  `01`, the panel sends `02`, and the radio sends a full redraw. Power on over
  CAT (`PS1;`) works too: the radio sends `01`, the panel answers `02`.
* `02` sent while the radio is on makes it send `00`, `01` and a full redraw.
  The radio stays on. This is how a second (web) panel gets the display.
* Display frames are sent only when something changes. For about 1 s after
  the redraw the radio repeats `: 2 6 7 ; < =` every ~250 ms, then it goes quiet
  except for keepalives.
* After power-on, the full display state arrives in about 5 s. The radio then
  sends the `O` query. The panel replies with the potentiometer positions
  `X…`, `V…`, `W…` and `FF`.

## Panel → radio

| frame | meaning | status |
|---|---|---|
| `<code><state>` | key, state `0` released, `1` pressed, `3` long press, `4` hold | ✔ |
| `S hhhh` | main VFO, 16-bit two's complement delta (`S0001`, `SFFFE`). The panel accumulates pulses and sends them about 8× per s | ✔ |
| `T hh` | MULTI/CH, 8-bit signed | ✔ |
| `U hh` | RIT/XIT knob, 8-bit signed | ✔ |
| `V hh` | AF (volume) 00–FF, absolute value | ✔ |
| `W hh` | SQL 00–FF | ✔ |
| `X hhhh` | IF SHIFT 0000–03FE, center 01FF | ✔ |
| `02` | reconnect / state request | ✔ |
| `FF` | keepalive | ✔ |

Key codes: `0` ⏻ (not press/release: `01` = switch on, `00` = switch off ✔), `1` PF ✔ (the physical PF key; `!` does nothing), `2` ATT/PRE ✔, `3` AT, `4` CH1/1, `5` CH2/2,
`6` CH3/3, `7` PWR/4, `8` MIC/5, `9` KEY/6, `:` NB/7, `<` VOX/8, `;` PROC/9,
`=` MTR/CLR, `>` AGC/0, `?` ENT, `@` DNL, `A` NR, `B` FIL, `C` BC, `D` FINE,
`G` MENU, `H` MHz, `I` A=B, `J` A/B, `K` QMI, `L` QMR, `M` CL, `N` RIT,
`O` XIT, `P` ▲ band up ✔, `Q` ▼ band down ✔ (swapped in the original notes; holding repeats).
**SCAN = `E` ✔, MODE = `F` ✔.** Verified by injecting the frames: `E` starts the
scan (`<SCAN P1`), `F` cycles mode groups and remembers the sub-mode
(USB → CW-R → FSK-R → FM → USB in the test).

Measured VFO behavior: roughly 0.5 to 5 Hz per pulse depending on the step and
FINE mode. The radio does the conversion.

## Radio → panel

| frame | meaning | status |
|---|---|---|
| `00` / `01` / `02` | off / on / on from PC | ✔ |
| `; ccccccc` | main 7-segment display, 7 characters, 10 Hz units (`;2806697` = 28.066.97) | ✔ |
| `< cccccccc` | status line, 8 characters (RIT/XIT/split, menu). RIT/XIT offset in **Hz**, `F b2=0x81` puts the dot before the last 3 (`-0.001` = −1 Hz) | ✔ |
| `= aabb` | bar graph: `aa` = S/PO 00–20 segments, `bb` = SWR/ALC/COMP | ✔ / ? `bb` |
| `> 7n` | second meter selection (71/72/73) | ? |
| `F b1 b2 b3` | decimal points: `b1` for the frequency (0x89 → `28.066.97`), `b2` for the status line (0x81 → `1.760`) | ✔ / ? bit mapping |
| `? b` | PRE, ATT, PROC, VOX, NB, MHz, FINE (bits 0–6). Bit 3 is on in CW modes (break-in) | ✔ |
| `@ b` | ★(QM), ★, ANT1, ANT2, MENU, M.CH, M.SCR | ✔ |
| `A b` | AGC, "OF", "F", NAR, 2, tuning lock, REC. AGC slow = bit 0, fast = 0+2, off = 0+1+2. No AGC icon in FM | ✔ |
| `B b` | ?, ?, NR2, NR1, BC2, BC1, DNL. Bits 0/1 probably R◂EQ / EQ▸T | ✔ / ? 0,1 |
| `C b` | T, CT, frequency lock (padlock), PC, RIT, XIT, AUTO | ✔ |
| `D b` | A, B, M, SPLIT, ▸T, ◂R, AT | ✔ (A, B) |
| `E b` | ◀A, ◀B, ◀M, A▶, B▶, M▶ arrows (bit 0 = VFO A, bit 1 = VFO B seen) | ✔ / ? |
| `L b` | unknown; bits 4 and 5 set while AT tunes (`L b0`) | ? |
| `: cc` | menu/channel number (`:  ` = blank) | ✔ |
| `P hh` | menu item number, **hex** (`P0A` = menu 10, `P30` = menu 48). Also `P00` with SG.SEL | ✔ |
| `4 hh` | value index, **hex**, the same number CAT `EXnnn` returns (`443` = 67) | ✔ |
| `2 x` | what the sub-display shows: `20` normal, `2E` menu text, others = setting read-outs (table below) | ✔ |
| `R n` | unknown (`R0` at power-on) | ? |
| `6 n` | display brightness 0–4 | ✔ |
| `7 n` | key backlight 0/1 | ✔ |
| `8 n` | LED: 0 off, 1 BUSY/RX (green, squelch open), 2 TX (red) | ✔ |
| `9 n` | operating mode = CAT `MD` code: 1 LSB, 2 USB, 3 CW, 4 FM, 5 AM, 6 FSK, 7 CW-R, 9 FSK-R | ✔ |
| `S n` | error code 0–7 | ✔ |
| `Q n` | model variant (Q0 RX only / Q1 TWIN PWR) | ✔ |
| `O` | potentiometer position query | ✔ |
| `3n` | unknown (`31`, `33` during TX) | ? |

## Texts are drawn by the panel ✔

The radio never sends menu texts or setting labels. In Menu mode it sends
`:nn`, `Pnn`, `2E`, `4hh` and the MENU icon; the panel shows the value in the
frequency field (`on`, `oFF`, `500`, `AUto`, `115200`…) and scrolls the menu
description on the sub-display (2 s hold, then about 4 characters per second).
The 61 description texts (menu 00–60) were read off the real panel with a
camera (`tools/menu_scan.py`) and are in `ts480/web/index.html` (`MENU`).

Setting read-outs (`2x` + `4hh`, 8 characters, dots ride on the previous cell):

| `2x` | key | display | value |
|---|---|---|---|
| `2Q` | PWR | `PWR-  30` | v (W) |
| `2N` | MIC | `MIC-  60` | v |
| `2P` | KEY | `KEY-  26` | 10 + v (wpm) |
| `2^` | PWR (1 s) | `TX M.-OFF` | 0 = OFF, else v |
| `2O` | MIC (1 s) | `RF G.-100` | v |
| `2R` | KEY (1 s) | `V.DLY- 50` | 5·v (VD1500 → 50) |
| `2M` | NB (1 s) | `NB LV.- 6` | v + 1 |
| `2J` | VOX (1 s) | `VOX G.- 7` | v |
| `2K` | PROC (1 s) | `PRO.I- 60` | v (also `>72` meter) |
| `` 2` `` | DNL (1 s) | `DNL LV.-2` | v + 1 |
| `2?` | FINE (1 s) | `STP-  5k` | SSB: 500/1k/2.5k/5k/10k |
| `2G` | SCAN (1 s) | `VGROUP-0` | v |
| `25` | FIL | `HI- 2400` | SSB/FM high cut 1000…5000 (AM 2500…5000) |
| `26` | FIL 2nd | `LO-  400` | SSB/FM low cut 0…1000 (AM 0…500) |
| `29` | FIL in CW | `WDH-  300` | 50/80/100/150/200/300/400/500/600/1000/2000 |
| `2:` | FIL in FSK | `WDH-  250` | 250/500/1000/1500 |
| `2C` | NR (1 s) with NR1 on | `NR1-AUTO` | 0 = AUTO, else level |
| `2b` | PF = TX TUNE (menu 48 = 67) | `TX TUNE` | radio switches to CW and transmits a carrier; PF again stops |
| `2A` | QMI (1 s) = M.IN | memory scroll, `:nn` channel, M.CH/M.SCR icons | |
| `;-------` | ENT | `--.---.--` in the frequency field | direct entry, CLR cancels |

## How things were verified (2026-11-13)

`tools/bridge.py` sits between the real panel and the radio and logs both
directions. `tools/cat_probe.py` sends CAT commands (`/dev/ttyUSB.cat`, 115200 Bd)
or injects panel frames, and prints what the radio then sends to the panel. Bits
were mapped with CAT `RA`, `PA`, `NB`, `NR`, `BC`, `PR`, `GT`, `FS`, `LK`, `AN`,
`RT`, `XT`, `FR`, `TO`, `CT`, `MD` and with injected keys `E`, `F`, `@`.
A camera on the real panel (`logs/cam.jpg`) and `tools/key_test.py` compare
the real LCD, the web panel and ARCP-480 after every key press.

## Still missing

* Bits `B0`, `B1` (EQ?), `D2`/`D4`–`D6`, `E2`–`E5`, the whole `L` byte, `R n`, `3n`.
* Glyphs for bytes ≥ 0x80 in the frequency field (service mode, menu).
* Exact timing of states `3`/`4` on long press.
* Second meter: what `bb` in `=aabb` and `>7n` mean during TX (needs a dummy load).
