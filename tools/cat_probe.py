# SPDX-License-Identifier: GPL-3.0-or-later
"""Correlate CAT commands with panel-link traffic.

Needs tools/bridge.py running (it writes logs/bridge-*.jsonl).  For every CAT
command given, this script sends it to the radio, waits, and prints the
radio -> panel frames that appeared in the bridge log meanwhile, skipping
frames identical to the last value seen for the same command letter (the
radio redraws the display about 4x per second) and S-meter/keepalive noise.

    python tools/cat_probe.py MD1 MD2 MD3        # one command per step
    python tools/cat_probe.py --wait 1.5 "FA00014070000"

A trailing ';' is added when missing.  Read-back commands (e.g. "MD") print
the CAT answer too.

Arguments of the form P:<frame> are not CAT: they are injected towards the
radio as if the panel sent them (needs bridge.py --inject), e.g.

    python tools/cat_probe.py P:E1 P:E0      # press and release key code 'E'
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import socket
import time

from catlink import drain, open_cat

NOISE = {"=", "\xff"}


def latest_log() -> str:
    logs = sorted(glob.glob("logs/bridge-*.jsonl"), key=os.path.getmtime)
    if not logs:
        raise SystemExit("no logs/bridge-*.jsonl - is tools/bridge.py running?")
    return logs[-1]


class LogTail:
    def __init__(self, path: str) -> None:
        self.fh = open(path, encoding="utf-8")
        self.fh.seek(0, os.SEEK_END)
        self.last: dict[str, str] = {}

    def prime(self, path: str) -> None:
        """Learn the current value of every radio->panel command from the log."""
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                self._new(json.loads(line))

    def _new(self, r: dict) -> bool:
        if r["dir"] != "R→P" or not r["hex"]:
            return False
        key = bytes.fromhex(r["hex"])[:1].decode("latin-1")
        if key in NOISE or self.last.get(key) == r["hex"]:
            return False
        self.last[key] = r["hex"]
        return True

    def changes(self) -> list[dict]:
        out = []
        for line in self.fh.readlines():
            r = json.loads(line)
            if r["dir"] in ("P→R", "inj→R") and r["text"] != "keepalive":
                out.append(r)
            elif self._new(r):
                out.append(r)
        return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmds", nargs="+")
    ap.add_argument("--cat", default="/dev/ttyUSB.cat")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--wait", type=float, default=1.0)
    ap.add_argument("--inject", type=int, default=8490, help="bridge injection port")
    ap.add_argument("--cam", metavar="DIR", help="after each step copy logs/cam.jpg (camera on the real panel) here")
    a = ap.parse_args()
    path = latest_log()
    tail = LogTail(path)
    tail.prime(path)
    cat = open_cat(a.cat, a.baud)
    inj = None
    step = 0

    def snap(label: str) -> None:
        nonlocal step
        step += 1
        if a.cam and os.path.exists("logs/cam.jpg"):
            os.makedirs(a.cam, exist_ok=True)
            name = f"{step:02d}_" + "".join(ch if ch.isalnum() else "_" for ch in label) + ".jpg"
            shutil.copy("logs/cam.jpg", os.path.join(a.cam, name))
            print(f"   cam: {os.path.join(a.cam, name)}")

    for cmd in a.cmds:
        if cmd.startswith("P:"):
            if inj is None:
                inj = socket.create_connection(("127.0.0.1", a.inject)).makefile("rwb", buffering=0)
            inj.write(f"radio {cmd[2:]}\n".encode("latin-1"))
            inj.readline()
            time.sleep(a.wait)
            print(f"== PANEL {cmd[2:]}")
            for r in tail.changes():
                print(f"   {r['dir']:<6} {r['ascii']:<12} {r['hex']:<30} {r['text']}")
            snap("P" + cmd[2:])
            continue
        c = cmd if cmd.endswith(";") else cmd + ";"
        cat.reset_input_buffer()
        cat.write(c.encode())
        ans = drain(cat, a.wait).decode("latin-1", "replace").strip("\x00")
        print(f"== CAT {c}" + (f"  -> {ans}" if ans else ""))
        for r in tail.changes():
            print(f"   {r['dir']:<6} {r['ascii']:<12} {r['hex']:<30} {r['text']}")
        snap(c)


if __name__ == "__main__":
    main()
