# SPDX-License-Identifier: GPL-3.0-or-later
"""Share the radio's CAT port between ARCP-480 (under wine) and scripts.

    python tools/cat_proxy.py                 # /dev/ttyUSB.cat, 115200 Bd

* creates a pseudo terminal and the symlink logs/arcp-com -> /dev/pts/N;
  wine's COM1 points at that symlink, so ARCP-480 talks to it
* TCP 127.0.0.1:8492 for scripts (pyserial: socket://127.0.0.1:8492)
* commands from each source are forwarded whole (up to ';'), so ARCP and a
  script never interleave inside one command; every reply of the radio goes
  to all clients (Kenwood replies carry the command name, so clients filter)
* everything is logged to logs/cat-YYYYmmdd-HHMMSS.log
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import pty
import select
import socket
import termios
import threading
import time
import tty

import serial


class Proxy:
    def __init__(self, port: str, baud: int, link: str, tcp: int) -> None:
        self.ser = serial.Serial(port, baud, timeout=0)
        self.wlock = threading.Lock()
        self.master, slave = pty.openpty()
        tty.setraw(slave)
        attrs = termios.tcgetattr(slave)
        attrs[3] &= ~termios.ECHO
        termios.tcsetattr(slave, termios.TCSANOW, attrs)
        self.slave_name = os.ttyname(slave)
        self.slave_fd = slave              # keep open so the pty survives ARCP closing it
        if os.path.islink(link) or os.path.exists(link):
            os.unlink(link)
        os.symlink(self.slave_name, link)
        self.link = link
        self.srv = socket.socket()
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("127.0.0.1", tcp))
        self.srv.listen(4)
        self.clients: list[socket.socket] = []
        self.bufs: dict[object, bytearray] = {"arcp": bytearray()}
        self.log = open(f"logs/cat-{dt.datetime.now():%Y%m%d-%H%M%S}.log", "a", encoding="utf-8")
        self.t0 = time.time()

    def note(self, src: str, data: bytes) -> None:
        txt = data.decode("latin-1").replace("\x00", "\\0")
        self.log.write(f"{time.time() - self.t0:9.3f} {src:<6} {txt}\n")
        self.log.flush()

    def to_radio(self, key, src: str, data: bytes) -> None:
        buf = self.bufs.setdefault(key, bytearray())
        buf += data
        while b";" in buf:
            i = buf.index(b";") + 1
            cmd = bytes(buf[:i])
            del buf[:i]
            with self.wlock:
                self.ser.write(cmd)
            self.note(src + ">", cmd)

    def run(self) -> None:
        print(f"# cat proxy {self.ser.port} {self.ser.baudrate}  pty {self.slave_name} -> {self.link}  tcp 127.0.0.1:{self.srv.getsockname()[1]}", flush=True)
        rx = bytearray()
        while True:
            fds = [self.master, self.srv, self.ser.fileno()] + self.clients
            r, _, _ = select.select(fds, [], [], 0.5)
            for f in r:
                if f is self.srv:
                    c, _ = self.srv.accept()
                    self.clients.append(c)
                    self.bufs[c] = bytearray()
                elif f == self.ser.fileno():
                    data = self.ser.read(4096)
                    if not data:
                        continue
                    os.write(self.master, data)
                    for c in list(self.clients):
                        try:
                            c.sendall(data)
                        except OSError:
                            self.clients.remove(c)
                    rx += data
                    while b";" in rx:
                        i = rx.index(b";") + 1
                        self.note("radio", bytes(rx[:i]))
                        del rx[:i]
                elif f == self.master:
                    try:
                        data = os.read(self.master, 4096)
                    except OSError:
                        continue
                    self.to_radio("arcp", "arcp", data)
                else:
                    try:
                        data = f.recv(4096)
                    except OSError:
                        data = b""
                    if not data:
                        self.clients.remove(f)
                        self.bufs.pop(f, None)
                        f.close()
                        continue
                    self.to_radio(f, "tcp", data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", default="/dev/ttyUSB.cat")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--link", default="logs/arcp-com")
    ap.add_argument("--tcp", type=int, default=8492)
    a = ap.parse_args()
    Proxy(a.port, a.baud, os.path.abspath(a.link), a.tcp).run()


if __name__ == "__main__":
    main()
