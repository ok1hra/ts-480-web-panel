# TS-480 Panel: softwarová náhrada ovládacího panelu

Program emuluje ovládací panel (control head) Kenwood TS-480 přímo na lince
panel ↔ rádio (RJ12, 57600 Bd TTL). Nepoužívá CAT. Rádio se chová, jako by
k němu byl připojený originální panel. Vidíte stejný displej, klávesy fungují
včetně dlouhého stisku, stejně tak knoflíky VFO, MULTI a RIT/XIT a potenciometry
AF, SQL a IF SHIFT.

```
 prohlížeč (PC / tablet / mobil)
        │  WebSocket
 ts480.server  (Python, aiohttp)
        │  PanelLink: keepalive, odpověď na dotaz O, reconnect, sčítání enkodérů
        │  DisplayState: dekódování příkazů pro LCD
 USB-UART 5 V  ──RJ12──  TS-480 (tělo)
```

Popis protokolu je v **[PROTOCOL.md](PROTOCOL.md)**.

## Zapojení

| RJ12 (kabel od rádia) | USB-UART 5 V (FTDI TTL-232R-5V, CH340 v režimu 5 V…) |
|---|---|
| 3 GND | GND |
| 4 RDO (rádio → panel) | **RX** |
| 5 TDO (panel → rádio) | **TX** |
| 6 AF + 1 SPK GND | na nf zesilovač/zvukovku (panel nf nezpracovává) |
| 2 +8 V | nezapojovat |

* Originální panel musí být **odpojený**. Na TX lince může být jen jeden
  budič.
* Na piny 4 a 5 nepřipojujte převodník RS-232 (±12 V).

## Spuštění

```bash
pip install -r requirements.txt
python -m ts480.server --port /dev/ttyUSB0            # Windows: --port COM5
python -m ts480.server --port socket://192.168.1.50:4000   # UART přes síť (ser2net, ESP32…)
python -m ts480.server --sim                          # vestavěný simulátor, bez hardwaru
# pak otevřete http://127.0.0.1:8480   (pro síť: --http 0.0.0.0:8480)
```

Ovládání:

* Klávesy se ovládají myší nebo dotykem. Držení déle než 1 s pošle dlouhý
  stisk (`--long-press` mění prahovou dobu).
* Knoflíky se otáčejí tažením nebo kolečkem myši. Kolečko se Shiftem dává ×10.
* Klávesnice: `↑`/`↓` ladí VFO, `PgUp`/`PgDn` ovládá MULTI.
* Přepínač „counts/step“ určuje, kolik impulsů enkodéru pošle jeden krok.
* „Direct frequency“ zadá frekvenci přes klávesnici panelu (ENT, číslice,
  ENT).
* „Raw frames“ pošle libovolný rámec (`N1` nebo `hex: 4E 31`). Hodí se na
  experimenty. Log ukazuje veškerý provoz oběma směry i s dekódováním.

## Doladění nezdokumentovaných míst

Sniffer `tools/sniff.py` je pasivní odposlech mezi originálním panelem a rádiem.
Potřebuje dva převodníky, u každého se zapojuje jen RX a GND:

```bash
python tools/sniff.py --radio /dev/ttyUSB0 --panel /dev/ttyUSB1 --out tap.jsonl
```

Po stisku klávesy na originálním panelu vypíše přijatý rámec a změny
dekódovaného stavu. Tabulky `KEYS`, `FLAG_LABELS` a `MODE_NAMES`
v `ts480/protocol.py` jsou na jednom místě a snadno se opraví.

## Soubory

* `ts480/protocol.py`: kodek (rámce, klávesy, enkodéry, parser displeje)
* `ts480/link.py`: emulace panelu na lince (keepalive, dotaz `O`, reconnect, časování kláves)
* `ts480/sim.py`: zjednodušený simulátor těla rádia
* `ts480/server.py`: web server a WebSocket API
* `ts480/web/index.html`: UI panelu
* `tools/sniff.py`: pasivní sniffer
* `tests/`: testy parseru nad zachycenými výpisy z reálného rádia

## Stav

Ověřené v zachyceném provozu: rámcování, keepalive, zapnutí a reconnect,
všechny klávesy kromě MODE a SCAN, VFO, MULTI, RIT, AF, SQL, IF SHIFT,
frekvence, S-metr, většina ikon.

Odhady (v UI označené „?“ nebo v logu jako `misc`):

* kódy kláves MODE (`E`) a SCAN (`F`)
* tabulka číslice druhu provozu `9n`
* bity `B` a `L`
* mapování desetinných teček
