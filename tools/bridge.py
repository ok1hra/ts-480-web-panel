# SPDX-License-Identifier: GPL-3.0-or-later
"""Man-in-the-middle bridge between the real TS-480 panel and main unit.

The panel cable is cut in two: the panel side goes to one USB-UART adapter,
the radio side to another.  This program copies every byte from one side to
the other immediately (no frame buffering on the forwarding path) and, in a
separate thread, splits the copied stream into frames, decodes them and logs
them.

    python tools/bridge.py --panel /dev/ttyUSB.panel --radio /dev/ttyUSB.ts480

Output:
  * console: one line per frame (keepalives hidden unless --keepalive)
  * logs/bridge-YYYYmmdd-HHMMSS.jsonl: every frame, including keepalives

Injection (optional, --inject PORT, localhost only): connect with
`nc 127.0.0.1 PORT` and type lines

    radio E1          send "E1\\r" to the radio, as if the panel sent it
    radio E0
    panel ;0145000    send to the panel, as if the radio sent it
    radio hex 45 31   raw bytes (CR appended unless the last byte is 0D)

Injected frames are inserted only at a frame boundary of the forwarded
stream so they never split a frame in flight.

Tap (optional, --tap PORT, localhost only): a raw binary TCP stream for
programs.  A client receives every radio -> panel byte as it is forwarded and
whatever it sends (CR-terminated frames) is injected towards the radio.  The
web panel uses it:  python -m ts480.server --bridge 127.0.0.1:PORT

Serial settings: 57600 Bd, 8 data bits, no parity.  The old working network
bridge (ts480front_linux.py) used 2 stop bits; that is the default here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import queue
import socket
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ts480 import protocol as P  # noqa: E402

import serial  # noqa: E402

BOUNDARY_WAIT = 0.05   # max time an injection waits for a frame boundary


def asc(b: bytes) -> str:
    return "".join(chr(c) if 32 <= c < 127 else "·" for c in b)


class Side:
    """One serial port plus the state needed to write into it safely."""

    def __init__(self, name: str, url: str, baud: int, stopbits: float) -> None:
        self.name = name
        self.ser = serial.serial_for_url(url, baudrate=baud, bytesize=8, parity="N",
                                         stopbits=stopbits, timeout=0.005)
        self.wlock = threading.Lock()
        self.boundary = threading.Event()   # last byte written to this side was CR
        self.boundary.set()
        self.tx_bytes = 0

    def forward(self, data: bytes) -> None:
        with self.wlock:
            self.ser.write(data)
            self.tx_bytes += len(data)
            if data.endswith(P.CR):
                self.boundary.set()
            else:
                self.boundary.clear()

    def inject(self, frame: bytes) -> None:
        self.boundary.wait(BOUNDARY_WAIT)
        with self.wlock:
            self.ser.write(frame)
            self.tx_bytes += len(frame)


class Bridge:
    def __init__(self, a) -> None:
        self.t0 = time.time()
        self.radio = Side("radio", a.radio, a.baud, a.stopbits)
        self.panel = Side("panel", a.panel, a.baud, a.stopbits)
        self.q: queue.Queue = queue.Queue()
        self.show_keepalive = a.keepalive
        self.raw = a.raw
        logdir = pathlib.Path(a.logdir)
        logdir.mkdir(parents=True, exist_ok=True)
        self.logpath = logdir / f"bridge-{dt.datetime.now():%Y%m%d-%H%M%S}.jsonl"
        self.log = open(self.logpath, "a", encoding="utf-8")
        self.state = P.DisplayState()
        self.last_ka = {"R→P": None, "P→R": None}
        self.taps: list[socket.socket] = []
        self.last_frames: dict[bytes, bytes] = {}   # radio->panel, latest per command byte
        self.taps_lock = threading.Lock()

    # --- forwarding (hot path) ---------------------------------------------
    def pump(self, src: Side, dst: Side, tag: str) -> None:
        ser = src.ser
        while True:
            try:
                data = ser.read(ser.in_waiting or 1)
            except serial.SerialException as e:
                self.q.put((time.time(), "ERR", f"{src.name}: {e}".encode()))
                time.sleep(1)
                continue
            if data:
                dst.forward(data)
                self.q.put((time.time(), tag, data))
                if tag == "R→P" and self.taps:
                    self.tap_broadcast(data)

    # --- logging -------------------------------------------------------------
    def logger(self) -> None:
        readers = {"R→P": P.FrameReader(), "P→R": P.FrameReader(),
                   "inj→R": P.FrameReader(), "inj→P": P.FrameReader()}
        while True:
            t, tag, data = self.q.get()
            if tag == "ERR":
                self.emit(t, tag, b"", data.decode())
                continue
            if self.raw:
                self.emit(t, tag + " raw", data, "")
            for f in readers[tag].feed(data):
                if tag == "R→P" and f[:1] not in (b"\xff", b"O"):
                    self.last_frames[f[:1]] = f
                self.emit(t, tag, f, self.decode(tag, f))

    def decode(self, tag: str, f: bytes) -> str:
        if tag.endswith("R") and tag != "R→P":          # P→R, inj→R
            return P.decode_panel_frame(f)
        if f == P.KEEPALIVE:
            return "keepalive"
        before = self.state.to_dict()
        action = self.state.apply(f)
        after = self.state.to_dict()
        changed = {}
        for k in after:
            if after[k] == before[k] or k in ("freq_raw", "flags"):
                continue
            if isinstance(after[k], dict):
                changed[k] = {i: v for i, v in after[k].items() if before[k].get(i) != v}
            else:
                changed[k] = after[k]
        if action:
            return action
        return json.dumps(changed, ensure_ascii=False) if changed else "(no change)"

    def emit(self, t: float, tag: str, f: bytes, text: str) -> None:
        rel = t - self.t0
        extra = ""
        if f == P.KEEPALIVE and tag in self.last_ka:
            prev = self.last_ka[tag]
            self.last_ka[tag] = t
            if prev is not None:
                extra = f" Δ{(t - prev) * 1000:.0f} ms"
        rec = {"t": round(rel, 4), "wall": dt.datetime.fromtimestamp(t).isoformat(timespec="milliseconds"),
               "dir": tag, "hex": f.hex(" "), "ascii": asc(f), "text": text + extra}
        self.log.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.log.flush()
        if f == P.KEEPALIVE and not self.show_keepalive:
            return
        print(f"{rel:10.3f} {tag:<6} {rec['ascii']:<12} {rec['hex']:<30} {rec['text']}", flush=True)

    # --- injection -----------------------------------------------------------
    def injector(self, port: int) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
        while True:
            conn, _ = srv.accept()
            threading.Thread(target=self.inject_client, args=(conn,), daemon=True).start()

    def inject_client(self, conn: socket.socket) -> None:
        with conn, conn.makefile("rwb", buffering=0) as fh:
            for raw in fh:
                line = raw.decode("latin-1").strip()
                if not line:
                    continue
                try:
                    target, frame = self.parse_inject(line)
                except ValueError as e:
                    fh.write(f"ERR {e}\n".encode())
                    continue
                side, tag = (self.radio, "inj→R") if target == "radio" else (self.panel, "inj→P")
                side.inject(frame)
                self.q.put((time.time(), tag, frame))
                fh.write(f"OK {target} {frame.hex(' ')}\n".encode())

    @staticmethod
    def parse_inject(line: str) -> tuple[str, bytes]:
        target, _, rest = line.partition(" ")
        if target not in ("radio", "panel"):
            raise ValueError("line must start with 'radio' or 'panel'")
        if rest.startswith("hex "):
            frame = bytes.fromhex(rest[4:])
        else:
            frame = rest.encode("latin-1")
        if not frame.endswith(P.CR):
            frame += P.CR
        return target, frame

    # --- tap (binary stream for the web panel) -------------------------------
    def tap_broadcast(self, data: bytes) -> None:
        with self.taps_lock:
            for c in list(self.taps):
                try:
                    c.sendall(data)
                except OSError:
                    self.taps.remove(c)

    def tap_server(self, port: int) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
        while True:
            conn, addr = srv.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            with self.taps_lock:
                self.taps.append(conn)
            self.q.put((time.time(), "ERR", f"tap client {addr[0]}:{addr[1]} connected".encode()))
            threading.Thread(target=self.tap_client, args=(conn,), daemon=True).start()

    def tap_client(self, conn: socket.socket) -> None:
        reader = P.FrameReader()
        # Replay the current display so the client does not start blank.  Wait a
        # moment first: pyserial's socket:// flushes its input right after connect.
        time.sleep(0.3)
        try:
            conn.sendall(b"".join(f + P.CR for f in list(self.last_frames.values())))
        except OSError:
            pass
        try:
            while True:
                data = conn.recv(256)
                if not data:
                    break
                for f in reader.feed(data):
                    frame = f + P.CR
                    self.radio.inject(frame)
                    self.q.put((time.time(), "inj→R", frame))
        except OSError:
            pass
        finally:
            with self.taps_lock:
                if conn in self.taps:
                    self.taps.remove(conn)
            conn.close()
            self.q.put((time.time(), "ERR", b"tap client disconnected"))

    def run(self, inject_port: int | None, tap_port: int | None = None) -> None:
        threads = [
            threading.Thread(target=self.pump, args=(self.radio, self.panel, "R→P"), daemon=True),
            threading.Thread(target=self.pump, args=(self.panel, self.radio, "P→R"), daemon=True),
            threading.Thread(target=self.logger, daemon=True),
        ]
        if inject_port:
            threads.append(threading.Thread(target=self.injector, args=(inject_port,), daemon=True))
        if tap_port:
            threads.append(threading.Thread(target=self.tap_server, args=(tap_port,), daemon=True))
        for th in threads:
            th.start()
        print(f"# bridge radio={self.radio.ser.port} panel={self.panel.ser.port} "
              f"{self.radio.ser.baudrate} 8N{self.radio.ser.stopbits:g}  log={self.logpath}"
              + (f"  inject=127.0.0.1:{inject_port}" if inject_port else "")
              + (f"  tap=127.0.0.1:{tap_port}" if tap_port else ""), flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--radio", default="/dev/ttyUSB.ts480", help="port wired to the main unit")
    ap.add_argument("--panel", default="/dev/ttyUSB.panel", help="port wired to the front panel")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--stopbits", type=float, default=2, choices=(1, 1.5, 2))
    ap.add_argument("--logdir", default="logs")
    ap.add_argument("--keepalive", action="store_true", help="also print 0xFF keepalives")
    ap.add_argument("--raw", action="store_true", help="also log raw read chunks")
    ap.add_argument("--inject", type=int, metavar="PORT", help="TCP port (127.0.0.1) for frame injection")
    ap.add_argument("--tap", type=int, metavar="PORT", help="TCP port (127.0.0.1) for the binary tap (web panel)")
    a = ap.parse_args()
    Bridge(a).run(a.inject, a.tap)


if __name__ == "__main__":
    main()
