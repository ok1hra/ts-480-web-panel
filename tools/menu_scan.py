# SPDX-License-Identifier: GPL-3.0-or-later
"""Walk through the menu of the real radio and record what the panel shows.

The radio does not send menu texts: it sends the menu number (":nn", "Pnn"),
a sub-display mode ("2x") and the value ("4..."), and the panel draws the
text from its own ROM.  To rebuild that table this script steps through the
menu with the MULTI encoder (injected "T01" via tools/bridge.py --inject),
records the radio->panel frames for every item and grabs camera frames of
the real panel (logs/cam.jpg, written by ffmpeg) while the text scrolls.

    python tools/menu_scan.py --first 0 --last 60 --out logs/menu-scan

Output: <out>/scan.json and <out>/montage-NN.jpg (6 items per image, each item
a 6x2 grid of LCD crops 0.5 s apart).  The radio must be in Menu mode on item
--first when started; the values are not changed (only MULTI is turned).
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import socket
import subprocess
import time

CROP = "490x135+520+165"         # camera pixels covering MENU nn, main field and sub line


def latest_log() -> str:
    return sorted(glob.glob("logs/bridge-*.jsonl"), key=os.path.getmtime)[-1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", type=int, default=0)
    ap.add_argument("--last", type=int, default=60)
    ap.add_argument("--out", default="logs/menu-scan")
    ap.add_argument("--frames", type=int, default=12)
    ap.add_argument("--period", type=float, default=0.5)
    ap.add_argument("--crop", default=CROP, help="camera crop WxH+X+Y")
    ap.add_argument("--tile", default="6x2")
    ap.add_argument("--geometry", default="245x68+2+2")
    ap.add_argument("--per-montage", type=int, default=6)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    inj = socket.create_connection(("127.0.0.1", 8490)).makefile("rwb", buffering=0)
    log = open(latest_log(), encoding="utf-8")
    log.seek(0, os.SEEK_END)
    result = {}
    for n in range(a.first, a.last + 1):
        if n != a.first:
            inj.write(b"radio T01\n")
            inj.readline()
        frames = []
        shots = []
        for i in range(a.frames):
            time.sleep(a.period)
            f = os.path.join(a.out, f"m{n:02d}_{i:02d}.jpg")
            shutil.copy("logs/cam.jpg", f)
            shots.append(f)
        for line in log.readlines():
            r = json.loads(line)
            if r["dir"] == "R→P" and r["hex"] != "ff" and not r["ascii"].startswith("="):
                frames.append(r["ascii"] if all(0x20 <= int(b, 16) < 0x7f for b in r["hex"].split()) else r["hex"])
        result[f"{n:02d}"] = frames
        print(f"menu {n:02d}: {' | '.join(frames)}", flush=True)
        # one strip per item: frames cropped to the LCD, 6 x 2 grid
        for f in shots:
            subprocess.run(["convert", f, "-crop", a.crop, "+repage", f], check=True)
        subprocess.run(["montage", *shots, "-tile", a.tile, "-geometry", a.geometry,
                        "-background", "#222", os.path.join(a.out, f"item{n:02d}.jpg")], check=True)
    json.dump(result, open(os.path.join(a.out, "scan.json"), "w"), indent=1)
    items = sorted(glob.glob(os.path.join(a.out, "item*.jpg")))
    per = a.per_montage
    for k in range(0, len(items), per):
        group = items[k:k + per]
        subprocess.run(["convert", *group, "-append", os.path.join(a.out, f"montage-{k // per:02d}.jpg")], check=True)


if __name__ == "__main__":
    main()
