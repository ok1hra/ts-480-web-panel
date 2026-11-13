# SPDX-License-Identifier: GPL-3.0-or-later
"""Back up / restore all TS-480 menu settings (Menu A and Menu B) over CAT.

    python tools/menu_backup.py backup  logs/menu-backup.json
    python tools/menu_backup.py restore logs/menu-backup.json
    python tools/menu_backup.py diff    logs/menu-backup.json   # what differs now

CAT: EXnnn0000; reads menu nnn (000..060 on this radio), EXnnn0000<value>;
writes it.  MF0/MF1 selects Menu A/B.  Also saved: the CAT state that the
menu tests may change (MF, PC, AG, SQ, MG, VX, PR, AN, GT, NB, NR, BC, RA, PA, FS, MD, FA, FB).
"""
from __future__ import annotations

import json
import sys
import time

from catlink import drain, open_cat

PORT, BAUD = "/dev/ttyUSB.cat", 115200
EXTRA = ["MF", "PC", "AG0", "SQ0", "MG", "VX", "PR", "AN", "GT", "NB", "NR", "BC", "RA", "PA", "FS", "MD", "FA", "FB"]


class Cat:
    def __init__(self) -> None:
        self.s = open_cat(PORT, BAUD)

    def q(self, cmd: str) -> str | None:
        self.s.reset_input_buffer()
        self.s.write((cmd + ";").encode())
        raw = drain(self.s, 0.08).decode("latin-1").replace("\x00", "")
        for part in raw.split(";"):       # the reply repeats the whole query (EX0080000 -> EX0080000<v>)
            if part.startswith(cmd):
                return part
        return None

    def w(self, cmd: str) -> None:
        self.s.write((cmd + ";").encode())
        time.sleep(0.06)


def read_menus(c: Cat) -> dict[str, str]:
    out = {}
    for n in range(0, 100):
        r = c.q(f"EX{n:03d}0000")
        if r and r.startswith("EX"):
            out[f"{n:03d}"] = r[9:]
    return out


def backup(path: str) -> None:
    c = Cat()
    mf = c.q("MF")
    data = {"extra": {k: c.q(k) for k in EXTRA}, "menu": {}}
    for bank in ("0", "1"):
        c.w("MF" + bank)
        data["menu"][bank] = read_menus(c)
    c.w(mf or "MF0")
    json.dump(data, open(path, "w"), indent=1)
    print(f"saved {path}: Menu A {len(data['menu']['0'])} items, Menu B {len(data['menu']['1'])} items")


def current(c: Cat) -> dict:
    mf = c.q("MF")
    menus = {}
    for bank in ("0", "1"):
        c.w("MF" + bank)
        menus[bank] = read_menus(c)
    c.w(mf or "MF0")
    return {"extra": {k: c.q(k) for k in EXTRA}, "menu": menus}


def diff(path: str) -> list[str]:
    c = Cat()
    old, now = json.load(open(path)), current(c)
    lines = []
    for bank in ("0", "1"):
        for n, v in old["menu"][bank].items():
            if now["menu"][bank].get(n) != v:
                lines.append(f"menu {'AB'[int(bank)]} {n}: {v} -> {now['menu'][bank].get(n)}")
    for k, v in old["extra"].items():
        if now["extra"].get(k) != v:
            lines.append(f"{k}: {v} -> {now['extra'].get(k)}")
    return lines


def restore(path: str) -> None:
    c = Cat()
    data = json.load(open(path))
    for bank in ("0", "1"):
        c.w("MF" + bank)
        for n, v in data["menu"][bank].items():
            c.w(f"EX{n}0000{v}")
    ex = data["extra"]
    order = [k for k in EXTRA if k not in ("MF", "FA", "FB", "MD")] + ["FB", "FA", "MD", "MF"]
    for k in order:
        v = ex.get(k)
        if v:
            c.w(v)
    left = diff(path)
    print("restored; remaining differences:" if left else "restored, no differences", *left, sep="\n  ")


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("backup", "restore", "diff"):
        sys.exit(__doc__)
    if sys.argv[1] == "diff":
        print("\n".join(diff(sys.argv[2])) or "no differences")
    else:
        {"backup": backup, "restore": restore}[sys.argv[1]](sys.argv[2])
