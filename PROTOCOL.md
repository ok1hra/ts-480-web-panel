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

The line runs at 57600 Bd, 8N1, idle high (non-inverted TTL, **not RS-232**).
The main MCU of the radio (IC204) runs at 3.3 V, but the connector carries
5 V TTL. The USB-UART adapter must therefore tolerate 5 V.

## Framing ✔

`<command 1 byte><data…>\r`. A frame always ends with CR (0x0D). Icon bytes
(bit masks) always have bit 7 set (0x80 | bits), so CR can never appear inside
the data. The meaning of letters differs by direction (for example `O`, `P`, `S`).

## Keepalive ✔

* Both sides send `FF \r`. The radio sends it roughly every 1 s, the panel
  replies immediately and also sends its own, roughly every 1 s. (Older notes
  say 2 s and 5 s, but the `Bootsequence` capture shows a 1000 ms period.)
* After connecting, the panel sends `02`. The radio replies `00` (off) or `01`
  and sends a full display redraw.
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

Key codes: `0` ⏻, `2` PF, `!` ATT/PRE, `3` AT, `4` CH1/1, `5` CH2/2,
`6` CH3/3, `7` PWR/4, `8` MIC/5, `9` KEY/6, `:` NB/7, `<` VOX/8, `;` PROC/9,
`=` MTR/CLR, `>` AGC/0, `?` ENT, `@` DNL, `A` NR, `B` FIL, `C` BC, `D` FINE,
`G` MENU, `H` MHz, `I` A=B, `J` A/B, `K` QMI, `L` QMR, `M` CL, `N` RIT,
`O` XIT, `P` ◀ band, `Q` ▶ band ✔.
**MODE = `E` ?, SCAN = `F` ?** These two codes are missing from the
documentation and are the only free codes in the sequence.

Measured VFO behavior: roughly 0.5 to 5 Hz per pulse depending on the step and
FINE mode. The radio does the conversion.

## Radio → panel

| frame | meaning | status |
|---|---|---|
| `00` / `01` / `02` | off / on / on from PC | ✔ |
| `; ccccccc` | main 7-segment display, 7 characters, 10 Hz units (`;2806697` = 28.066.97) | ✔ |
| `< cccccccc` | status line, 8 characters (RIT/XIT/split, menu) | ✔ |
| `= aabb` | bar graph: `aa` = S/PO 00–20 segments, `bb` = SWR/ALC/COMP | ✔ / ? `bb` |
| `> 7n` | second meter selection (71/72/73) | ? |
| `F b1 b2 b3` | decimal points: `b1` for the frequency (0x89 → `28.066.97`), `b2` for the status line (0x81 → `1.760`) | ✔ / ? bit mapping |
| `? b` | PRE, ATT, PROC, VOX, NB, MHz, FINE (bits 0–6) | ✔ |
| `@ b` | ★(QM), ★, ANT1, ANT2, MENU, M.CH, M.SCR | ✔ |
| `A b` | AGC, ?, -F, NAR, 2, LOCK, REC | ✔ |
| `B b` | BC/NR/DNL/EQ, bits not mapped | ? |
| `C b` | T, CT, (F.)LOCK, PC, RIT, XIT, AUTO | ✔ |
| `D b` | A, B, M, SPLIT, ▸T, ◂R, AT | ✔ |
| `E b` | arrows ◂ ▸ (VFO/memory) | ✔ |
| `L b` | unknown | ? |
| `: cc` | menu/channel number (`:  ` = blank) | ✔ |
| `P cc`, `R n`, `2…` | menu item, parameter. `20` clears | partial |
| `6 n` | display brightness 0–4 | ✔ |
| `7 n` | key backlight 0/1 | ✔ |
| `8 n` | LED: 0 off, 1 RX (green), 2 TX (red) | ✔ |
| `9 n` | operating mode. The digit table is a guess | ? |
| `S n` | error code 0–7 | ✔ |
| `Q n` | model variant (Q0 RX only / Q1 TWIN PWR) | ✔ |
| `O` | potentiometer position query | ✔ |
| `3n` | unknown (`31`, `33` during TX) | ? |

## Still missing

* Mapping of the operating mode digit `9n`, bits `B` and `L`.
* Glyphs for bytes ≥ 0x80 in the frequency field (service mode, menu).
* Exact timing of states `3`/`4` on long press.
* Timeout behavior: how long the radio tolerates missing keepalives.
