# SPDX-License-Identifier: GPL-3.0-or-later
"""Drive an X display (used for ARCP-480 under wine in Xvfb) with XTEST.

    DISPLAY=:77 python tools/xctl.py shot out.png
    DISPLAY=:77 python tools/xctl.py click 320 400 [button]
    DISPLAY=:77 python tools/xctl.py dclick 320 400
    DISPLAY=:77 python tools/xctl.py type "text"
    DISPLAY=:77 python tools/xctl.py key Return|Tab|Escape|Down|alt+f ...
    DISPLAY=:77 python tools/xctl.py windows          # list top-level windows with geometry
"""
from __future__ import annotations

import subprocess
import sys
import time

from Xlib import X, XK, display
from Xlib.ext import xtest

d = display.Display()


def move(x: int, y: int) -> None:
    xtest.fake_input(d, X.MotionNotify, x=x, y=y)
    d.sync()


def click(x: int, y: int, button: int = 1, n: int = 1) -> None:
    move(x, y)
    time.sleep(0.05)
    for _ in range(n):
        xtest.fake_input(d, X.ButtonPress, button)
        d.sync()
        time.sleep(0.06)
        xtest.fake_input(d, X.ButtonRelease, button)
        d.sync()
        time.sleep(0.08)


def _keycode(name: str) -> tuple[int, bool]:
    sym = XK.string_to_keysym(name)
    if sym == 0 and len(name) == 1:
        sym = ord(name)
    code = d.keysym_to_keycode(sym)
    shift = len(name) == 1 and (name.isupper() or name in '~!@#$%^&*()_+{}|:"<>?')
    return code, shift


def key(combo: str) -> None:
    parts = combo.split("+")
    mods = [d.keysym_to_keycode(XK.string_to_keysym({"alt": "Alt_L", "ctrl": "Control_L", "shift": "Shift_L"}[m]))
            for m in parts[:-1]]
    code, shift = _keycode(parts[-1])
    if shift:
        mods.append(d.keysym_to_keycode(XK.string_to_keysym("Shift_L")))
    for m in mods:
        xtest.fake_input(d, X.KeyPress, m)
    xtest.fake_input(d, X.KeyPress, code)
    xtest.fake_input(d, X.KeyRelease, code)
    for m in reversed(mods):
        xtest.fake_input(d, X.KeyRelease, m)
    d.sync()
    time.sleep(0.05)


def type_text(text: str) -> None:
    names = {" ": "space", ".": "period", ",": "comma", "-": "minus", "/": "slash", ":": "colon", ";": "semicolon"}
    for ch in text:
        key(names.get(ch, ch))


def windows() -> None:
    root = d.screen().root
    for w in root.query_tree().children:
        try:
            attrs = w.get_attributes()
            if attrs.map_state != X.IsViewable:
                continue
            g = w.get_geometry()
            name = w.get_wm_name() or ""
            print(f"{w.id:#x} {g.x},{g.y} {g.width}x{g.height} {name!r}")
        except Exception:
            pass


def shot(path: str) -> None:
    subprocess.run(["import", "-window", "root", path], check=True)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "click":
        click(int(args[0]), int(args[1]), int(args[2]) if len(args) > 2 else 1)
    elif cmd == "dclick":
        click(int(args[0]), int(args[1]), 1, 2)
    elif cmd == "type":
        type_text(args[0])
    elif cmd == "key":
        for k in args:
            key(k)
    elif cmd == "windows":
        windows()
    elif cmd == "shot":
        shot(args[0])
    else:
        sys.exit(__doc__)
