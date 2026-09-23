# Kontext projektu pro Claude Code

Cíl: softwarová náhrada ovládacího panelu Kenwood TS-480. Aplikace emuluje
panel na lince panel ↔ rádio (RJ12, 5 V TTL UART, 57600 8N1). Nepoužívá CAT.

## Stav (předáno z cloudové session 2026-09-23)
- Protokol je převzatý z reverzního inženýrství https://github.com/stianeklund/TS-480-Panel
  a shrnutý v `PROTOCOL.md`. Značka ✔ = ověřeno v záznamech, ? = odhad.
- `ts480/protocol.py`: kodek a parser displeje (`DisplayState`). Tabulky `KEYS`,
  `FLAG_LABELS` a `MODE_NAMES` jsou jediné místo, kde se opravují odhady.
- `ts480/link.py`: emulace panelu (keepalive FF ~1 s, odpověď na `O` → X/V/W/FF,
  `02` reconnect, dlouhý stisk `3` po 1 s, sčítání enkodérů po 60 ms).
- `ts480/sim.py`: zjednodušený simulátor rádia (`--sim`).
- `ts480/server.py` + `ts480/web/index.html`: aiohttp + WebSocket, UI panelu.
- `tools/sniff.py`: pasivní odposlech dvou RX linek s dekódováním.
- Testy: `python -m pytest -q tests`. Ověřeno i v prohlížeči (Playwright) proti simulátoru.

## Otevřené body
1. Ověřit snifferem na reálném kusu: kódy MODE (`E`?) a SCAN (`F`?), číslici druhu
   provozu `9n`, bity `B` a `L`, mapování desetinných teček (`F b1 b2 b3`), význam `3n`.
2. Zkontrolovat, zda rádio vyžaduje přesné načasování keepalive a stavu `4` (hold).
3. Nápady: port na ESP32 (UART ↔ WiFi/WebSocket), nf audio přes síť, víc klientů najednou.

## Spuštění
    pip install -r requirements.txt
    python -m ts480.server --sim            # nebo --port /dev/ttyUSB0
    # http://127.0.0.1:8480
