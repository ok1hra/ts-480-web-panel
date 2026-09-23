# SPDX-License-Identifier: GPL-3.0-or-later
"""Passive tap between the real TS-480 panel and main unit.

Wire two USB-UART adapters (5 V tolerant!) with only RX + GND connected:
    adapter A RX  <- RJ12 pin 4 (radio -> panel)
    adapter B RX  <- RJ12 pin 5 (panel -> radio)
    GND           <- RJ12 pin 3

    python tools/sniff.py --radio /dev/ttyUSB0 --panel /dev/ttyUSB1 --out log.jsonl

Every frame is printed with a timestamp, hex, ASCII and decoded meaning, and
appended to a JSON-lines file.  Use it to confirm the GUESS items in
ts480/protocol.py (MODE/SCAN key codes, mode digits, B/L flag bytes...):
press one key on the real panel and watch what changes.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ts480 import protocol as P  # noqa: E402

lock = threading.Lock()


def asc(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "·" for c in b)


def tap(url: str, side: str, out, show_keepalive: bool, t0: float) -> None:
    import serial
    ser = serial.serial_for_url(url, baudrate=57600, timeout=0.05)
    reader, state = P.FrameReader(), P.DisplayState()
    while True:
        for f in reader.feed(ser.read(256)):
            if f == P.KEEPALIVE and not show_keepalive:
                continue
            if side == "radio":
                before = state.to_dict()
                action = state.apply(f)
                after = state.to_dict()
                changed = {}
                for k in after:
                    if after[k] == before[k]:
                        continue
                    if isinstance(after[k], dict):
                        changed[k] = {i: v for i, v in after[k].items() if before[k].get(i) != v}
                    else:
                        changed[k] = after[k]
                text = action or (json.dumps(changed, ensure_ascii=False) if changed else "")
            else:
                text = P.decode_panel_frame(f)
            rec = {"t": round(time.time() - t0, 4), "dir": side, "hex": f.hex(" "), "ascii": asc(f), "text": text}
            with lock:
                arrow = "R→P" if side == "radio" else "P→R"
                print(f"{rec['t']:10.4f} {arrow} {rec['ascii']:<12} {rec['hex']:<30} {text}", flush=True)
                if out:
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    out.flush()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--radio", help="port listening on radio->panel line (RJ12 pin 4)")
    ap.add_argument("--panel", help="port listening on panel->radio line (RJ12 pin 5)")
    ap.add_argument("--out", help="append JSON lines here")
    ap.add_argument("--keepalive", action="store_true", help="also show 0xFF keepalives")
    a = ap.parse_args()
    if not (a.radio or a.panel):
        ap.error("need --radio and/or --panel")
    out = open(a.out, "a", encoding="utf-8") if a.out else None
    t0 = time.time()
    for url, side in ((a.radio, "radio"), (a.panel, "panel")):
        if url:
            threading.Thread(target=tap, args=(url, side, out, a.keepalive, t0), daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
