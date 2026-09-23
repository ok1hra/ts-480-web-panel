# SPDX-License-Identifier: GPL-3.0-or-later
"""Web front-end replacing the TS-480 control panel.

    python -m ts480.server --port /dev/ttyUSB0          # real radio
    python -m ts480.server --port socket://10.0.0.5:4000 # UART over network (ser2net)
    python -m ts480.server --sim                          # built-in simulator
Then open http://localhost:8480
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib

from aiohttp import web, WSMsgType

from . import protocol as P
from .link import PanelLink, SerialTransport

WEB = pathlib.Path(__file__).with_name("web")
log = logging.getLogger("ts480")


class App:
    def __init__(self, transport):
        self.clients: set[web.WebSocketResponse] = set()
        self.link = PanelLink(transport, on_update=self.broadcast)

    def broadcast(self, msg: dict) -> None:
        if not self.clients:
            return
        data = json.dumps(msg)
        for ws in list(self.clients):
            if not ws.closed:
                asyncio.ensure_future(ws.send_str(data))

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=10)
        await ws.prepare(request)
        self.clients.add(ws)
        await ws.send_str(json.dumps({"type": "hello", "keys": [
            {"name": k.name, "label": k.label, "alt": k.alt, "digit": k.digit,
             "code": k.code, "verified": k.verified} for k in P.KEYS.values()]}))
        await ws.send_str(json.dumps(self.link.snapshot()))
        for e in list(self.link.log)[-100:]:
            await ws.send_str(json.dumps({"type": "log", "entry": e}))
        held: set[str] = set()
        try:
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    continue
                try:
                    await self.handle(json.loads(msg.data), held)
                except Exception as e:
                    log.warning("bad command %r: %s", msg.data, e)
        finally:
            for k in held:                      # never leave a key stuck down
                self.link.key_up(k)
            self.clients.discard(ws)
        return ws

    async def handle(self, m: dict, held: set) -> None:
        L, op = self.link, m.get("op")
        if op == "down":
            L.key_down(m["key"]); held.add(m["key"])
        elif op == "up":
            L.key_up(m["key"]); held.discard(m["key"])
        elif op == "enc":
            L.encoder(m["which"], int(m["delta"]))
        elif op == "pot":
            L.set_pot(m["which"], int(m["value"]))
        elif op == "freq":
            asyncio.create_task(L.direct_freq(float(m["khz"])))
        elif op == "raw":
            L.raw(m["text"])
        elif op == "reconnect":
            L.send(P.RECONNECT_MSG)


def main() -> None:
    ap = argparse.ArgumentParser(description="TS-480 control panel replacement")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--port", help="serial port or pyserial URL (socket://host:port)")
    g.add_argument("--sim", action="store_true", help="use built-in radio simulator")
    ap.add_argument("--baud", type=int, default=57600)
    ap.add_argument("--http", default="127.0.0.1:8480", help="listen address host:port")
    ap.add_argument("--long-press", type=float, default=1.0, help="seconds until long press")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if a.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")

    if a.sim:
        from .sim import RadioSim
        transport = RadioSim()
    else:
        transport = SerialTransport(a.port, a.baud)
    app_state = App(transport)
    app_state.link.LONG_PRESS_S = a.long_press

    app = web.Application()
    app.router.add_get("/ws", app_state.ws_handler)
    app.router.add_get("/", lambda r: web.FileResponse(WEB / "index.html"))
    app.router.add_static("/static", WEB)

    async def on_start(_):
        await app_state.link.start()

    async def on_stop(_):
        await app_state.link.stop()
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)

    host, port = a.http.rsplit(":", 1)
    print(f"TS-480 panel on http://{host}:{port}  ({'simulator' if a.sim else a.port})")
    web.run_app(app, host=host, port=int(port), print=None)


if __name__ == "__main__":
    main()
