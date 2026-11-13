# SPDX-License-Identifier: GPL-3.0-or-later
"""Panel emulation on the serial line: keepalive, query replies, key timing,
encoder accumulation, reconnect.  Transport-agnostic (real UART, network
socket via pyserial URL, or the built-in radio simulator)."""
from __future__ import annotations

import asyncio
import collections
import logging
import threading
import time
from typing import Callable, Optional

from . import protocol as P

log = logging.getLogger("ts480.link")


class SerialTransport:
    """Any pyserial URL: /dev/ttyUSB0, COM5, socket://host:port, rfc2217://..."""

    def __init__(self, url: str, baud: int = 57600, stopbits: float = 2):
        import serial  # pyserial
        # 8N2: the old working network bridge for this radio used 2 stop bits.
        self.ser = serial.serial_for_url(url, baudrate=baud, bytesize=8, parity="N",
                                         stopbits=stopbits, timeout=0.05, do_not_open=True)
        # Some USB-UART adapters power / reset things through DTR/RTS; keep them quiet.
        try:
            self.ser.dtr = False
            self.ser.rts = False
        except Exception:
            pass
        self.ser.open()

    def read(self) -> bytes:
        return self.ser.read(256)       # socket:// raises when the peer closes

    def reopen(self) -> None:
        try:
            self.ser.close()
        except Exception:
            pass
        self.ser.open()

    def write(self, data: bytes) -> None:
        self.ser.write(data)

    def close(self) -> None:
        self.ser.close()


class PanelLink:
    """Panel side of the link.

    passive=True is for running next to the real panel (tools/bridge.py --tap):
    the real panel answers keepalives and pot queries, we only watch the
    display and inject keys / encoders / pots.
    """
    # Real unit (2026-11-13): the radio sends FF every 5 s and the panel only
    # answers it.  Without an answer the radio powers off within ~4 s.  Our own
    # extra FF pings are harmless and let us detect a dead link.
    KEEPALIVE_S = 1.0
    LINK_TIMEOUT_S = 6.0     # radio FF every 5 s, display redraw ~4x/s when on
    RECONNECT_S = 3.0
    VFO_FLUSH_S = 0.06       # real panel batches encoder counts (~8 Hz); we go faster
    LONG_PRESS_S = 1.0

    def __init__(self, transport, on_update: Optional[Callable[[dict], None]] = None,
                 passive: bool = False):
        self.t = transport
        self.passive = passive
        self.state = P.DisplayState()
        self.on_update = on_update or (lambda ev: None)
        self.af = 0x00       # start silent; the radio asks for pot positions with "O" at power-on
        self.sql = 0x00
        self.ifshift = P.IFSHIFT_CENTER
        self.last_rx = 0.0
        self.log = collections.deque(maxlen=400)
        self._reader = P.FrameReader()
        self._acc = {"S": 0, "T": 0, "U": 0}
        self._held: dict[str, asyncio.TimerHandle] = {}
        self._wlock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop = threading.Event()
        self._dirty = False

    # ---- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        threading.Thread(target=self._rx_thread, daemon=True, name="ts480-rx").start()
        tasks = [self._flush_task(), self._notify_task()]
        if not self.passive:
            tasks.append(self._keepalive_task())
        self._tasks = [asyncio.create_task(c) for c in tasks]
        if not self.passive:
            self.send(P.RECONNECT_MSG)      # ask radio for state / redraw
        else:
            self._tasks.append(asyncio.create_task(self._redraw_if_blank()))

    async def _redraw_if_blank(self):
        """Passive mode: the bridge replays the cached display; if it had none
        (bridge started after the last redraw), ask the radio for one.  '02'
        makes the radio send 00, 01 and a full redraw to both panels."""
        await asyncio.sleep(1.5)
        if not self.state.freq_raw.strip():
            self.send(P.RECONNECT_MSG)

    async def stop(self) -> None:
        self._stop.set()
        for t in self._tasks:
            t.cancel()
        self.t.close()

    @property
    def connected(self) -> bool:
        return time.monotonic() - self.last_rx < self.LINK_TIMEOUT_S

    # ---- low level ---------------------------------------------------------
    def send(self, data: bytes) -> None:
        with self._wlock:
            self.t.write(data)
        for f in P.FrameReader().feed(data):
            self._log("tx", f, P.decode_panel_frame(f))

    def _log(self, direction: str, frame: bytes, text: str) -> None:
        if frame == P.KEEPALIVE:
            return                      # too chatty
        entry = {"t": round(time.time(), 3), "dir": direction, "hex": frame.hex(" "),
                 "ascii": "".join(chr(b) if 32 <= b < 127 else "·" for b in frame), "text": text}
        self.log.append(entry)
        self.on_update({"type": "log", "entry": entry})

    def _rx_thread(self) -> None:
        while not self._stop.is_set():
            try:
                data = self.t.read()
            except Exception as e:  # pragma: no cover - hardware errors
                log.error("serial read failed: %s", e)
                time.sleep(1)
                if hasattr(self.t, "reopen"):
                    try:
                        self.t.reopen()
                        log.info("transport reopened")
                    except Exception as e2:
                        log.error("reopen failed: %s", e2)
                continue
            if data and self._loop:
                self._loop.call_soon_threadsafe(self._on_bytes, data)

    def _on_bytes(self, data: bytes) -> None:
        self.last_rx = time.monotonic()
        for frame in self._reader.feed(data):
            action = self.state.apply(frame)
            if action == "keepalive":
                if not self.passive:
                    self.send(P.keepalive_msg())
                continue
            self._log("rx", frame, action or "")
            if action == "query" and not self.passive:
                self.send(P.ifshift_msg(self.ifshift) + P.volume_msg(self.af)
                          + P.squelch_msg(self.sql) + P.keepalive_msg())
            self._dirty = True

    # ---- periodic tasks ----------------------------------------------------
    async def _keepalive_task(self):
        last_reconnect = 0.0
        while True:
            await asyncio.sleep(self.KEEPALIVE_S)
            self.send(P.keepalive_msg())
            now = time.monotonic()
            if not self.connected and now - last_reconnect > self.RECONNECT_S:
                last_reconnect = now
                self.send(P.RECONNECT_MSG)
            self._dirty = True   # refresh "connected" indicator

    async def _flush_task(self):
        enc = {"S": P.vfo_msg, "T": P.multi_msg, "U": P.rit_msg}
        lim = {"S": 0x7FFF, "T": 0x7F, "U": 0x7F}
        while True:
            await asyncio.sleep(self.VFO_FLUSH_S)
            for k, v in self._acc.items():
                if v:
                    part = max(-lim[k], min(lim[k], v))
                    self._acc[k] -= part
                    self.send(enc[k](part))

    async def _notify_task(self):
        while True:
            await asyncio.sleep(0.03)
            if self._dirty:
                self._dirty = False
                self.on_update(self.snapshot())

    def snapshot(self) -> dict:
        return {"type": "state", "connected": self.connected, "passive": self.passive,
                "state": self.state.to_dict(),
                "pots": {"af": self.af, "sql": self.sql, "ifshift": self.ifshift}}

    # ---- panel controls ----------------------------------------------------
    def key_down(self, name: str) -> None:
        if name == "POWER":
            # VERIFIED 2026-11-13/14: the panel sends "01" to switch the radio on and "00" to
            # switch it off - not press/release.  A "00" after "01" turns the radio off again.
            self.send(P.key_msg("POWER", P.KEY_UP if self.state.power else P.KEY_DOWN))
            return
        if name not in P.KEYS or name in self._held:
            return
        self.send(P.key_msg(name, P.KEY_DOWN))
        self._held[name] = self._loop.call_later(
            self.LONG_PRESS_S, lambda: self.send(P.key_msg(name, P.KEY_LONG)))

    def key_up(self, name: str) -> None:
        h = self._held.pop(name, None)
        if h is None:
            return
        h.cancel()
        self.send(P.key_msg(name, P.KEY_UP))

    async def tap(self, name: str, long: bool = False) -> None:
        self.key_down(name)
        await asyncio.sleep(self.LONG_PRESS_S + 0.2 if long else 0.08)
        self.key_up(name)
        await asyncio.sleep(0.05)

    def encoder(self, which: str, delta: int) -> None:
        k = {"vfo": "S", "multi": "T", "rit": "U"}[which]
        self._acc[k] += int(delta)

    def set_pot(self, which: str, value: int) -> None:
        if which == "af":
            self.af = max(0, min(255, int(value)))
            self.send(P.volume_msg(self.af))
        elif which == "sql":
            self.sql = max(0, min(255, int(value)))
            self.send(P.squelch_msg(self.sql))
        elif which == "ifshift":
            self.ifshift = max(0, min(P.IFSHIFT_MAX, int(value)))
            self.send(P.ifshift_msg(self.ifshift))
        self._dirty = True

    async def direct_freq(self, khz: float) -> None:
        """ENT + digits + ENT.  First digit is the 10 MHz digit (7 MHz -> 0,7...)."""
        hz10 = int(round(khz * 100))                   # 10 Hz units
        digits = f"{hz10:07d}".rstrip("0") or "0"
        if len(digits) < 2:
            digits = digits.ljust(2, "0")
        await self.tap("ENT")
        for d in digits:
            await self.tap(P.DIGIT_KEYS[d].name)
        await self.tap("ENT")

    def raw(self, text: str) -> None:
        """Send raw frame(s). Accepts ASCII ('N1') or hex ('4E 31') ; CR appended."""
        t = text.strip()
        if t.lower().startswith("hex:"):
            data = bytes.fromhex(t[4:])
        else:
            data = t.encode("latin-1")
        if not data.endswith(P.CR):
            data += P.CR
        self.send(data)
