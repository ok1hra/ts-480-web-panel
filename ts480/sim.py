# SPDX-License-Identifier: GPL-3.0-or-later
"""Minimal TS-480 main-unit simulator speaking the panel protocol.

Lets the UI and link layer run without hardware.  It reproduces the framing,
keepalive, power-on redraw and query sequence seen in real captures; the
radio *logic* (what a key does) is a simplified model, not the real firmware.
"""
from __future__ import annotations

import queue
import random
import threading
import time

from . import protocol as P

BANDS = [1_810_000, 3_500_000, 7_000_000, 10_100_000, 14_000_000, 18_068_000,
         21_000_000, 24_890_000, 28_000_000, 50_000_000]


class RadioSim:
    def __init__(self, boot_delay: float = 1.0):
        self.out: "queue.Queue[bytes]" = queue.Queue()
        self.lock = threading.RLock()
        self.boot_delay = boot_delay
        self.on = False
        self.freq = [14_074_000, 7_074_000]
        self.vfo = 0
        self.mode = 1
        self.rit = self.xit = False
        self.rit_off = 0
        self.seg = {"?": 0x80, "@": 0x84, "A": 0x81, "B": 0x80, "C": 0xC8, "D": 0x81, "E": 0x81}
        self.meter_sel = 1
        self.ent: str | None = None
        self.pots = {}
        self._rx = P.FrameReader()
        threading.Thread(target=self._ticker, daemon=True).start()

    # transport interface --------------------------------------------------
    def read(self) -> bytes:
        try:
            chunk = self.out.get(timeout=0.05)
        except queue.Empty:
            return b""
        while not self.out.empty() and len(chunk) < 256:
            chunk += self.out.get_nowait()
        return chunk

    def write(self, data: bytes) -> None:
        with self.lock:
            for f in self._rx.feed(data):
                self._handle(f)

    def close(self) -> None:
        pass

    # helpers ----------------------------------------------------------------
    def _tx(self, *frames: bytes) -> None:
        for f in frames:
            self.out.put(f + P.CR)

    def _freq_frame(self) -> bytes:
        return b";%7d" % (self.freq[self.vfo] // 10)

    def _status(self) -> bytes:
        if self.ent is not None:
            return b"<" + self.ent.ljust(8, "-")[:8].encode()
        if self.rit or self.xit:
            v = self.rit_off
            return b"<" + ("-" if v < 0 else "+").encode() + f"{abs(v):04d}".rjust(7).encode()
        return b"<" + b" " * 8

    def _dots(self) -> bytes:
        sub = 0x81 if (self.rit or self.xit) and self.ent is None else 0x80
        return b"F\x89" + bytes([sub]) + b"\x80"

    def _redraw(self) -> None:
        c = self.seg["C"] & ~0x30 | (0x10 if self.rit else 0) | (0x20 if self.xit else 0)
        self.seg["C"] = c
        d = self.seg["D"] & ~0x03 | (0x01 if self.vfo == 0 else 0x02)
        self.seg["D"] = d
        self._tx(b":  ", b"20", b"64", b"71", b"81", b"9%d" % self.mode, self._freq_frame(),
                 self._status(), b">7%d" % self.meter_sel,
                 *[k.encode() + bytes([v]) for k, v in self.seg.items()], self._dots())

    def _power(self, on: bool) -> None:
        self.on = on
        if not on:
            self._tx(b"00", b"80", b"60", b"70")
            return
        self._tx(b"01")

        def boot():
            time.sleep(self.boot_delay)
            with self.lock:
                if self.on:
                    self._tx(b"R0", b"Q1")
                    self._redraw()
                    self._tx(b"O")          # ask panel for pot positions
        threading.Thread(target=boot, daemon=True).start()

    def _toggle(self, seg: str, bit: int) -> None:
        self.seg[seg] ^= bit

    # panel frame handling ------------------------------------------------------
    def _handle(self, f: bytes) -> None:
        if f == P.KEEPALIVE:
            return
        c, body = chr(f[0]), f[1:].decode("latin-1")
        if c == "0":                               # power key / reconnect
            if body == "2":
                if self.on:
                    self._tx(b"01")
                    self._redraw()
                else:
                    self._tx(b"00")
            elif body == "1":
                self._power(not self.on)
            return
        if not self.on:
            return
        if c in "VWX":
            self.pots[c] = int(body, 16)
            return
        if c == "S":
            d = P._signed(int(body, 16), 16)
            step = 1 if self.seg["?"] & 0x40 else 5
            self.freq[self.vfo] = max(30_000, min(60_000_000, self.freq[self.vfo] + d * step))
            self._tx(self._freq_frame())
            return
        if c == "T":
            d = P._signed(int(body, 16), 8)
            f = self.freq[self.vfo]
            self.freq[self.vfo] = max(30_000, (f // 1000 + d) * 1000)   # 1 kHz steps
            self._tx(self._freq_frame())
            return
        if c == "U":
            if self.rit or self.xit:
                self.rit_off = max(-9990, min(9990, self.rit_off + 10 * P._signed(int(body, 16), 8)))
                self._tx(self._status(), self._dots())
            return
        key = P.KEY_BY_CODE.get(c)
        if key and body == P.KEY_DOWN:
            self._key(key.name)

    def _key(self, k: str) -> None:
        if self.ent is not None:                   # direct frequency entry
            if k == "ENT":
                digits = (self.ent + "0000000")[:7]
                self.freq[self.vfo] = int(digits) * 10
                self.ent = None
                self._redraw()
            elif k in ("CH1", "CH2", "CH3", "PWR", "MIC", "KEY", "NB", "VOX", "PROC", "AGC"):
                self.ent += P.KEYS[k].digit
                self._tx(self._status())
            elif k == "MTR":                       # CLR
                self.ent = None
                self._redraw()
            return
        toggles = {"NB": ("?", 0x10), "PROC": ("?", 0x04), "VOX": ("?", 0x08),
                   "FINE": ("?", 0x40), "MHZ": ("?", 0x20), "AGC": ("A", 0x04),
                   "FIL": ("A", 0x08), "AT": ("D", 0x40)}
        if k in toggles:
            self._toggle(*toggles[k])
        elif k == "ATT":
            v = self.seg["?"] & 0x03
            self.seg["?"] = self.seg["?"] & ~0x03 | {0: 0x02, 0x02: 0x01, 0x01: 0}[v]
        elif k == "RIT":
            self.rit = not self.rit
        elif k == "XIT":
            self.xit = not self.xit
        elif k == "CL":
            self.rit_off = 0
        elif k == "AB":
            self.vfo ^= 1
        elif k == "ASB":
            self.freq[self.vfo ^ 1] = self.freq[self.vfo]
        elif k == "MODE":
            self.mode = {1: 0, 0: 2, 2: 6, 6: 5, 5: 4, 4: 3, 3: 1}.get(self.mode, 1)
        elif k == "MTR":
            self.meter_sel = self.meter_sel % 3 + 1
        elif k in ("UP", "DOWN"):
            f = self.freq[self.vfo]
            i = min(range(len(BANDS)), key=lambda j: abs(BANDS[j] - f))
            i = (i + (1 if k == "UP" else -1)) % len(BANDS)
            self.freq[self.vfo] = BANDS[i]
        elif k == "ENT":
            self.ent = ""
        self._redraw()

    def _ticker(self) -> None:
        s, n = 6.0, 0
        while True:
            time.sleep(0.2)
            n += 1
            with self.lock:
                if n % 5 == 0:
                    self._tx(P.KEEPALIVE)
                if self.on:
                    s = max(0.0, min(20.0, s + random.uniform(-1.5, 1.5) + (7 - s) * 0.1))
                    self._tx(b"=%02d00" % round(s))
