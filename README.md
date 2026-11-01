# TS-480 Panel: software replacement for the control head

This program emulates the Kenwood TS-480 control panel (control head) directly
on the panel ↔ radio link (RJ12, 57600 Bd TTL). It does not use CAT. The radio
behaves as if the original panel were connected. You get the same display, the
keys work including long press, and so do the VFO, MULTI and RIT/XIT knobs and
the AF, SQL and IF SHIFT potentiometers.

```
 browser (PC / tablet / phone)
        │  WebSocket
 ts480.server  (Python, aiohttp)
        │  PanelLink: keepalive, reply to the O query, reconnect, encoder accumulation
        │  DisplayState: decoding of LCD commands
 USB-UART 5 V  ──RJ12──  TS-480 (main unit)
```

The protocol is described in **[PROTOCOL.md](PROTOCOL.md)**.

## Wiring

| RJ12 (cable from the radio) | USB-UART 5 V (FTDI TTL-232R-5V, CH340 in 5 V mode…) |
|---|---|
| 3 GND | GND |
| 4 RDO (radio → panel) | **RX** |
| 5 TDO (panel → radio) | **TX** |
| 6 AF + 1 SPK GND | to an AF amplifier / sound card (the panel does not process audio) |
| 2 +8 V | do not connect |

* The original panel must be **disconnected**. Only one driver may be on the
  TX line.
* Do not connect an RS-232 converter (±12 V) to pins 4 and 5.

## Running

```bash
pip install -r requirements.txt
python -m ts480.server --port /dev/ttyUSB0            # Windows: --port COM5
python -m ts480.server --port socket://192.168.1.50:4000   # UART over the network (ser2net, ESP32…)
python -m ts480.server --sim                          # built-in simulator, no hardware
# then open http://127.0.0.1:8480   (for network access: --http 0.0.0.0:8480)
```

Controls:

* Keys are operated by mouse or touch. Holding a key for more than 1 s sends a
  long press (`--long-press` changes the threshold).
* Knobs are turned by dragging or with the mouse wheel. Wheel with Shift gives ×10.
* Keyboard: `↑`/`↓` tunes the VFO, `PgUp`/`PgDn` controls MULTI.
* The "counts/step" selector sets how many encoder pulses one step sends.
* "Direct frequency" enters a frequency via the panel keypad (ENT, digits,
  ENT).
* "Raw frames" sends an arbitrary frame (`N1` or `hex: 4E 31`). Useful for
  experiments. The log shows all traffic in both directions, including decoding.

## Filling in the undocumented parts

The sniffer `tools/sniff.py` is a passive tap between the original panel and the
radio. It needs two adapters, each with only RX and GND connected:

```bash
python tools/sniff.py --radio /dev/ttyUSB0 --panel /dev/ttyUSB1 --out tap.jsonl
```

When a key is pressed on the original panel, it prints the received frame and
the changes of the decoded state. The tables `KEYS`, `FLAG_LABELS` and
`MODE_NAMES` in `ts480/protocol.py` are in one place and easy to correct.

## Files

* `ts480/protocol.py`: codec (frames, keys, encoders, display parser)
* `ts480/link.py`: panel emulation on the line (keepalive, `O` query, reconnect, key timing)
* `ts480/sim.py`: simplified simulator of the radio main unit
* `ts480/server.py`: web server and WebSocket API
* `ts480/web/index.html`: panel UI
* `tools/sniff.py`: passive sniffer
* `tests/`: parser tests against captured dumps from a real radio

## Status

Verified in captured traffic: framing, keepalive, power-on and reconnect,
all keys except MODE and SCAN, VFO, MULTI, RIT, AF, SQL, IF SHIFT,
frequency, S-meter, most icons.

Guesses (marked "?" in the UI or as `misc` in the log):

* key codes MODE (`E`) and SCAN (`F`)
* table of the operating mode digit `9n`
* bits `B` and `L`
* decimal point mapping

## Credits and sources

* **[Stian Eklund, stianeklund/TS-480-Panel](https://github.com/stianeklund/TS-480-Panel)**
  (GPL-3.0): the reverse engineering of the panel ↔ radio protocol this project
  is built on (logic analyzer captures, key codes, display commands, timing).
  The power-on dump used in `tests/test_protocol.py` comes from its
  `Radio/Power on sequence.md`.
* RemoteRig documentation of the TS-480 separated control head operation.
* Kenwood TS-480SAT/HX instruction manual (panel layout, key functions).

## License

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version. See [LICENSE](LICENSE).

Kenwood and TS-480 are trademarks of JVCKENWOOD Corporation. This project is
not affiliated with or endorsed by Kenwood.
# TS-480 web panel
