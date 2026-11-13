# SPDX-License-Identifier: GPL-3.0-or-later
"""Press panel keys through the web panel and compare three displays.

For every step the key is pressed via the web panel's WebSocket (so the whole
path web -> server -> bridge tap -> radio is exercised), then side by side:
  1. the real panel's LCD (camera, logs/cam.jpg)
  2. the web panel's LCD (headless Chrome screenshot of http://127.0.0.1:8480)
  3. ARCP-480's display (Xvfb :77)
plus the radio -> panel frames the step caused.

    python tools/key_test.py --out logs/keytest NB NB NR NR NR MODE:long ...

A step is KEY (short press), KEY:long (held 1.5 s) or KEY:hold=<s>.
Output: <out>/report.json, <out>/step-NN.jpg, <out>/sheet-NN.jpg (6 steps per sheet).
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
import subprocess
import time

import aiohttp

CAM_CROP = "1000x185+125+100"
WEB_CROP = "1010x185+195+158"
ARCP_CROP = "735x120+274+255"
CHROME = ["google-chrome", "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
          "--window-size=1500,380", "--virtual-time-budget=1500"]


def frames_since(fh) -> list[str]:
    out = []
    for line in fh.readlines():
        r = json.loads(line)
        if r["dir"] == "R→P" and r["hex"] != "ff" and not r["ascii"].startswith("="):
            out.append(r["ascii"] if all(0x20 <= int(b, 16) < 0x7f for b in r["hex"].split()) else
                       r["ascii"][:1] + " " + " ".join(r["hex"].split()[1:]))
    return out


async def press(ws, key: str, hold: float) -> None:
    await ws.send_json({"op": "down", "key": key})
    await asyncio.sleep(hold)
    await ws.send_json({"op": "up", "key": key})


def capture(out: str, n: int, label: str, frames: list[str]) -> str:
    cam = os.path.join(out, f"c{n:02d}.jpg")
    web = os.path.join(out, f"w{n:02d}.png")
    arcp = os.path.join(out, f"a{n:02d}.png")
    subprocess.run(["convert", "logs/cam.jpg", "-crop", CAM_CROP, "+repage", "-resize", "600x", cam], check=True)
    subprocess.run(CHROME + [f"--screenshot={web}", "http://127.0.0.1:8480/"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=40)
    subprocess.run(["convert", web, "-crop", WEB_CROP, "+repage", "-resize", "600x", web], check=True)
    subprocess.run(["import", "-display", ":77", "-window", "root", arcp], check=True)
    subprocess.run(["convert", arcp, "-crop", ARCP_CROP, "+repage", "-resize", "600x", arcp], check=True)
    step = os.path.join(out, f"step-{n:02d}.jpg")
    caption = f"{n:02d} {label}:  " + " | ".join(frames)[:150]
    subprocess.run(["convert", "(", cam, web, arcp, "+append", ")", "-background", "#111", "-fill", "white",
                    "-pointsize", "16", f"label:{caption}", "-swap", "0,1", "-append", step], check=True)
    return step


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="+")
    ap.add_argument("--out", default="logs/keytest")
    ap.add_argument("--settle", type=float, default=1.2)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    log = open(sorted(glob.glob("logs/bridge-*.jsonl"), key=os.path.getmtime)[-1], encoding="utf-8")
    log.seek(0, os.SEEK_END)
    report, steps = [], []
    async with aiohttp.ClientSession() as s, s.ws_connect("http://127.0.0.1:8480/ws") as ws:
        async def pump():                     # keep the socket drained
            async for _ in ws:
                pass
        drain = asyncio.create_task(pump())
        for n, st in enumerate(a.steps, 1):
            key, _, opt = st.partition(":")
            if key == "raw":                  # raw:11 -> send frame "11" as if the panel did
                await ws.send_json({"op": "raw", "text": opt})
            elif key == "wait":               # wait:3 -> just let time pass, then capture
                await asyncio.sleep(float(opt))
            else:
                hold = 1.5 if opt == "long" else float(opt.split("=")[1]) if opt.startswith("hold=") else 0.12
                await press(ws, key, hold)
            await asyncio.sleep(a.settle)
            fr = frames_since(log)
            steps.append(capture(a.out, n, st, fr))
            report.append({"step": n, "key": st, "frames": fr})
            print(f"{n:02d} {st:<10} {' | '.join(fr)}", flush=True)
        drain.cancel()
    json.dump(report, open(os.path.join(a.out, "report.json"), "w"), indent=1)
    for k in range(0, len(steps), 6):
        subprocess.run(["convert", *steps[k:k + 6], "-append", os.path.join(a.out, f"sheet-{k // 6:02d}.jpg")], check=True)


if __name__ == "__main__":
    asyncio.run(main())
