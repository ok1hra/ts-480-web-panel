# SPDX-License-Identifier: GPL-3.0-or-later
"""Open the radio's CAT port: through tools/cat_proxy.py when it runs, else directly."""
from __future__ import annotations

import os
import socket

import serial

PROXY = ("127.0.0.1", 8492)


def open_cat(port: str = "/dev/ttyUSB.cat", baud: int = 115200, timeout: float = 0.3):
    url = os.environ.get("TS480_CAT")
    if not url:
        try:
            socket.create_connection(PROXY, timeout=0.2).close()
            url = f"socket://{PROXY[0]}:{PROXY[1]}"
        except OSError:
            url = port
    return serial.serial_for_url(url, baudrate=baud, timeout=timeout)


def drain(s, wait: float = 0.15, quiet: float = 0.05) -> bytes:
    """Read everything that arrives within `wait`, then until `quiet` s of silence.
    (pyserial's socket:// reports in_waiting as 0/1, not a byte count.)"""
    import time
    time.sleep(wait)
    out = bytearray()
    old = s.timeout
    s.timeout = quiet
    try:
        while True:
            chunk = s.read(4096)
            if not chunk:
                break
            out += chunk
    finally:
        s.timeout = old
    return bytes(out)
