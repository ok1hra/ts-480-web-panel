# Project context for Claude Code

Goal: software replacement of the Kenwood TS-480 control panel. The application
emulates the panel on the panel ↔ radio link (RJ12, 5 V TTL UART, 57600 8N1).
It does not use CAT.

## Status (handed over from the cloud session 2026-09-23)
- The protocol is taken from the reverse engineering at https://github.com/stianeklund/TS-480-Panel
  (Stian Eklund, GPL-3.0) and summarized in `PROTOCOL.md`. Mark ✔ = verified in captures, ? = guess.
- `ts480/protocol.py`: codec and display parser (`DisplayState`). The tables `KEYS`,
  `FLAG_LABELS` and `MODE_NAMES` are the only place where guesses get corrected.
- `ts480/link.py`: panel emulation (keepalive FF ~1 s, reply to `O` → X/V/W/FF,
  `02` reconnect, long press `3` after 1 s, encoder accumulation over 60 ms).
- `ts480/sim.py`: simplified radio simulator (`--sim`).
- `ts480/server.py` + `ts480/web/index.html`: aiohttp + WebSocket, panel UI.
- `tools/sniff.py`: passive tap of both RX lines with decoding.
- Tests: `python -m pytest -q tests`. Also verified in a browser (Playwright) against the simulator.
- License GPL-3.0 (`LICENSE`), credits in `README.md`. All texts are in English.

## Open items
1. Verify with the sniffer on a real unit: codes MODE (`E`?) and SCAN (`F`?), the
   operating mode digit `9n`, bits `B` and `L`, decimal point mapping (`F b1 b2 b3`), meaning of `3n`.
2. Check whether the radio requires exact timing of the keepalive and state `4` (hold).
3. Ideas: port to ESP32 (UART ↔ WiFi/WebSocket), AF audio over the network, multiple clients at once.

## Running
    pip install -r requirements.txt
    python -m ts480.server --sim            # or --port /dev/ttyUSB0
    # http://127.0.0.1:8480
