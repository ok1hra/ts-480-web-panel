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

## Bench setup (2026-11-13, this machine)
- `/dev/ttyUSB.panel` is wired to the RADIO, `/dev/ttyUSB.ts480` to the PANEL (udev names swapped).
  `tools/bridge.sh` already uses the right roles. CAT: `/dev/ttyUSB.cat` 115200 Bd.
- The radio powers OFF ~4 s after the panel stops answering keepalives. Restart the bridge only
  with `tools/bridge.sh restart`. Power on again over CAT with `PS1;`.
- Never `pkill -f` a pattern that also appears in your own shell command line; kill by PID
  (`logs/bridge.pid`, `logs/web.pid`).
- ARCP-480 (Kenwood CAT program) is installed under wine in `~/.wine-arcp480`. It runs in Xvfb `:77`
  and talks through `tools/cat_proxy.py` (COM1 -> `logs/arcp-com` pty; scripts use TCP 8492 via
  `tools/catlink.py`). All other wine COM ports are blocked in the registry so ARCP can never open the
  panel/radio lines. Drive it with `tools/xctl.py` clicks only: a stray Enter hit ARCP's focused POWER
  button once (it sends `PS9;` = power off).
- A camera looks at the real panel: `ffmpeg ... -update 1 logs/cam.jpg` (pid in `logs/cam.pid`).
- Menu settings backup (Menu A and B + main CAT state): `logs/menu-backup.json`;
  `tools/menu_backup.py diff|restore logs/menu-backup.json`. The user allowed menu changes only if restored.
- The user allowed transmitting for tests.

## Open items
1. Verified on the real unit: SCAN=`E`, MODE=`F`, `9n` = CAT MD code, most flag bits, keepalive.
   Still unknown: bits `B0`/`B1` (EQ?), `D2`, `D4`–`D6`, `E2`–`E5`, the `L` byte, `R n`, `3n`, the sub-meter `bb`.
2. Check state `4` (hold) and long-press timing on the real panel.
3. Ideas: port to ESP32 (UART ↔ WiFi/WebSocket), AF audio over the network, multiple clients at once.

## Running
    pip install -r requirements.txt
    python -m ts480.server --sim            # or --port /dev/ttyUSB0
    # http://127.0.0.1:8480
