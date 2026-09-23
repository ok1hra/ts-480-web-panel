"""Kenwood TS-480 control-panel <-> main-unit serial protocol.

Physical layer (RJ12 panel cable):
    pin 1 SPK GND, 2 +8 V (panel supply), 3 GND,
    pin 4 RX  (radio -> panel, 5 V TTL UART),
    pin 5 TX  (panel -> radio, 5 V TTL UART),
    pin 6 AF  (speaker audio)
    57600 bd, 8N1, idle high.

Every message is terminated by CR (0x0D).  The first byte is the "command"
(radio -> panel: which LCD area / lamp to update; panel -> radio: which key or
knob changed).  Flag bytes always have bit 7 set (0x80 | bits), so they never
collide with CR.

Source of the reverse engineering: https://github.com/stianeklund/TS-480-Panel
Everything marked VERIFIED appears in captured traffic there; everything
marked GUESS is an inference and should be checked with tools/sniff.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

CR = b"\r"
KEEPALIVE = b"\xff"

# ---------------------------------------------------------------------------
# Panel -> radio: keys
# ---------------------------------------------------------------------------
# Key state digit appended after the key code.
KEY_UP, KEY_DOWN, KEY_LONG, KEY_HOLD = "0", "1", "3", "4"


@dataclass(frozen=True)
class Key:
    name: str        # id used by UI / API
    code: str        # single ASCII char sent on the wire
    label: str       # primary label on the panel
    alt: str = ""    # long-press / secondary function
    digit: str = ""  # digit in ENT (direct frequency entry) mode
    verified: bool = True


KEYS: dict[str, Key] = {k.name: k for k in [
    Key("POWER", "0", "⏻"),
    Key("PF", "2", "PF"),
    Key("ATT", "!", "ATT/PRE", "ANT 1/2"),
    Key("AT", "3", "AT"),
    Key("CH1", "4", "CH1", "REC", "1"),
    Key("CH2", "5", "CH2", "REC", "2"),
    Key("CH3", "6", "CH3", "REC", "3"),
    Key("PWR", "7", "PWR", "TX MONI", "4"),
    Key("MIC", "8", "MIC", "RF.G", "5"),
    Key("KEY", "9", "KEY", "DELAY", "6"),
    Key("NB", ":", "NB/T", "LEVEL", "7"),
    Key("VOX", "<", "VOX", "GAIN", "8"),
    Key("PROC", ";", "PROC", "LEVEL", "9"),
    Key("MTR", "=", "MTR", "CLR"),
    Key("AGC", ">", "AGC", "OFF", "0"),
    Key("ENT", "?", "ENT"),
    Key("DNL", "@", "DNL", "LEVEL"),
    Key("NR", "A", "NR", "LEVEL"),
    Key("FIL", "B", "FIL", "NAR"),
    Key("BC", "C", "BC", "CW.T"),
    Key("FINE", "D", "FINE", "STEP"),
    Key("MODE", "E", "MODE", "", verified=False),   # GUESS: unassigned code 0x45
    Key("SCAN", "F", "SCAN", "SG.SEL", verified=False),  # GUESS: 0x46
    Key("MENU", "G", "MENU", "F.LOCK"),
    Key("MHZ", "H", "MHz", "M.STP"),
    Key("ASB", "I", "A=B", "SPLIT"),
    Key("AB", "J", "A/B", "M/V"),
    Key("QMI", "K", "QMI", "M.IN"),
    Key("QMR", "L", "QMR", "M>VFO"),
    Key("CL", "M", "CL"),
    Key("RIT", "N", "RIT"),
    Key("XIT", "O", "XIT"),
    Key("DOWN", "P", "◀", "TF-SET"),   # band down (0x50)
    Key("UP", "Q", "▶", "TF-SET"),     # band up   (0x51)
]}
KEY_BY_CODE = {k.code: k for k in KEYS.values()}
DIGIT_KEYS = {k.digit: k for k in KEYS.values() if k.digit}


def key_msg(name: str, state: str) -> bytes:
    """e.g. key_msg('NB', KEY_DOWN) -> b':1\\r'"""
    return (KEYS[name].code + state).encode("ascii") + CR


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(v)))


def vfo_msg(delta: int) -> bytes:
    """Main tuning encoder, signed 16-bit count delta: S0001 / SFFFF."""
    d = _clamp(delta, -0x7FFF, 0x7FFF)
    return b"S%04X\r" % (d & 0xFFFF)


def multi_msg(delta: int) -> bytes:
    """MULTI/CH encoder, signed 8-bit: T01 / TFF."""
    d = _clamp(delta, -0x7F, 0x7F)
    return b"T%02X\r" % (d & 0xFF)


def rit_msg(delta: int) -> bytes:
    """RIT/XIT encoder, signed 8-bit: U01 / UFF."""
    d = _clamp(delta, -0x7F, 0x7F)
    return b"U%02X\r" % (d & 0xFF)


def volume_msg(v: int) -> bytes:
    return b"V%02X\r" % _clamp(v, 0, 0xFF)


def squelch_msg(v: int) -> bytes:
    return b"W%02X\r" % _clamp(v, 0, 0xFF)


IFSHIFT_MAX = 0x3FE
IFSHIFT_CENTER = 0x1FF


def ifshift_msg(v: int) -> bytes:
    return b"X%04X\r" % _clamp(v, 0, IFSHIFT_MAX)


def keepalive_msg() -> bytes:
    return KEEPALIVE + CR


RECONNECT_MSG = b"02\r"   # panel asks radio for power state / full redraw


def _signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v & (1 << (bits - 1)) else v


def decode_panel_frame(frame: bytes) -> str:
    """Human readable description of a panel -> radio frame (for sniffing)."""
    if frame == KEEPALIVE:
        return "keepalive"
    try:
        s = frame.decode("latin-1")
    except Exception:  # pragma: no cover
        return frame.hex(" ")
    c, rest = s[:1], s[1:]
    try:
        if c == "S" and len(rest) == 4:
            return f"VFO {_signed(int(rest, 16), 16):+d}"
        if c == "T" and len(rest) == 2:
            return f"MULTI {_signed(int(rest, 16), 8):+d}"
        if c == "U" and len(rest) == 2:
            return f"RIT/XIT {_signed(int(rest, 16), 8):+d}"
        if c == "V" and len(rest) == 2:
            return f"AF {int(rest, 16)}"
        if c == "W" and len(rest) == 2:
            return f"SQL {int(rest, 16)}"
        if c == "X" and len(rest) == 4:
            return f"IF-SHIFT {int(rest, 16) - IFSHIFT_CENTER:+d}"
    except ValueError:
        pass
    if len(rest) == 1 and c in KEY_BY_CODE:
        st = {"0": "up", "1": "down", "2": "reconnect", "3": "long", "4": "hold"}.get(rest, rest)
        return f"KEY {KEY_BY_CODE[c].name} {st}"
    return "? " + frame.hex(" ")


# ---------------------------------------------------------------------------
# Radio -> panel: display / lamp commands
# ---------------------------------------------------------------------------
# Bit 7 is always set; bits 0..6 are annunciators.  Labels from the TS-480
# manual (LCD item numbers) matched against captured values.
FLAG_LABELS: dict[str, list[str]] = {
    "?": ["PRE", "ATT", "PROC", "VOX", "NB", "MHz", "FINE"],
    "@": ["QM★", "★", "ANT1", "ANT2", "MENU", "M.CH", "M.SCR"],
    "A": ["AGC", "A1?", "-F", "NAR", "2", "LOCK", "REC"],
    "B": ["B0?", "B1?", "B2?", "B3?", "B4?", "B5?", "B6?"],   # BC/NR/DNL/EQ – unmapped
    "C": ["T", "CT", "F.LOCK", "PC", "RIT", "XIT", "AUTO"],
    "D": ["A", "B", "M", "SPLIT", "▸T", "◂R", "AT"],
    "E": ["◂1", "◂2", "◂3", "▸1", "▸2", "▸3", "E6?"],
    "L": ["L0?", "L1?", "L2?", "L3?", "L4?", "L5?", "L6?"],
}

# '9x' mode digit.  GUESS (Kenwood CAT "MD" code minus one); verify with sniff.py
MODE_NAMES = {0: "LSB", 1: "USB", 2: "CW", 3: "FM", 4: "AM", 5: "FSK", 6: "CW-R", 8: "FSK-R"}

LAMP_NAMES = {0: "off", 1: "rx", 2: "tx"}


def _text(b: bytes) -> str:
    out = []
    for ch in b:
        if 0x20 <= ch < 0x7F:
            out.append(chr(ch))
        elif ch >= 0xA0:
            out.append(bytes([ch]).decode("latin-1"))
        else:
            out.append("?")
    return "".join(out)


def _flags(code: str, value: int) -> list[str]:
    labels = FLAG_LABELS[code]
    return [labels[i] for i in range(7) if value & (1 << i)]


@dataclass
class DisplayState:
    """Mirror of everything the radio asked the panel to show."""
    power: Optional[bool] = None
    freq_raw: str = "       "
    status_raw: str = "        "
    dots: list[int] = field(default_factory=lambda: [0x80, 0x80, 0x80])
    menu_no: str = "  "
    menu_entry: str = ""
    param: str = ""
    meter_main: int = 0          # 0..20 bars (S / PO)
    meter_sub: int = 0           # 0..10 bars (SWR / ALC / COMP)
    meter_sel: str = ""
    mode_code: Optional[int] = None
    lamp: int = 0
    brightness: int = 4
    backlight: bool = True
    error: str = "0"
    model: str = ""
    flags: dict[str, int] = field(default_factory=lambda: {k: 0x80 for k in FLAG_LABELS})
    misc: dict[str, str] = field(default_factory=dict)   # unmapped commands, raw

    # --- rendering helpers -------------------------------------------------
    def freq_text(self) -> str:
        """7-char frequency field with decimal points (dot byte 1).

        Heuristic that matches captures: bit n of dots[0] lights the dot
        in front of the last (n+2) characters -> 0x89 gives '28.066.97'.
        """
        return self._with_dots(self.freq_raw, self.dots[0], 2)

    def status_text(self) -> str:
        """8-char status line (RIT/XIT/split); bit n of dots[1] -> dot before last n+3."""
        return self._with_dots(self.status_raw, self.dots[1], 3)

    @staticmethod
    def _with_dots(text: str, mask: int, base: int) -> str:
        pos = {len(text) - (n + base) for n in range(7) if mask & (1 << n)}
        return "".join(("." if i in pos and i > 0 else "") + ch for i, ch in enumerate(text))

    def frequency_hz(self) -> Optional[int]:
        digits = self.freq_raw.replace(" ", "0")
        if len(digits) == 7 and digits.isdigit():
            return int(digits) * 10
        return None

    def to_dict(self) -> dict:
        return {
            "power": self.power,
            "freq": self.freq_text(),
            "freq_raw": self.freq_raw,
            "freq_hz": self.frequency_hz(),
            "status": self.status_text(),
            "menu_no": self.menu_no,
            "menu_entry": self.menu_entry,
            "param": self.param,
            "meter_main": self.meter_main,
            "meter_sub": self.meter_sub,
            "meter_sel": self.meter_sel,
            "mode": MODE_NAMES.get(self.mode_code, f"?{self.mode_code}") if self.mode_code is not None else "",
            "mode_code": self.mode_code,
            "lamp": LAMP_NAMES.get(self.lamp, str(self.lamp)),
            "brightness": self.brightness,
            "backlight": self.backlight,
            "error": self.error,
            "model": self.model,
            "icons": sorted({lab for c, v in self.flags.items() for lab in _flags(c, v)}),
            "flags": {c: f"{v:02X}" for c, v in self.flags.items()},
            "misc": dict(self.misc),
        }

    # --- parser --------------------------------------------------------------
    def apply(self, frame: bytes) -> Optional[str]:
        """Apply one radio->panel frame (without CR).

        Returns an action the link layer must react to:
            'keepalive' - radio pinged, answer with FF
            'query'     - radio asks for pot positions (answer X, V, W, FF)
            None        - display-only update
        """
        if not frame:
            return None
        if frame == KEEPALIVE:
            return "keepalive"
        c = chr(frame[0])
        body = frame[1:]
        n = len(body)

        if c == "O" and n == 0:
            return "query"
        if c == "0" and n == 1:                       # 00 off / 01 on / 02 on (PC)
            self.power = body != b"0"
            return None
        if c == ";" and n >= 7:
            self.freq_raw = _text(body[:7])
        elif c == "<":
            self.status_raw = _text(body[:8]).ljust(8)
        elif c == "=" and n == 4:
            t = body.decode("latin-1")
            self.meter_main = _num(t[:2])
            self.meter_sub = _num(t[2:])
        elif c == ">":
            self.meter_sel = _text(body)
        elif c == "F" and n >= 1:
            for i, b in enumerate(body[:3]):
                self.dots[i] = b
        elif c in FLAG_LABELS and n == 1 and body[0] & 0x80:
            self.flags[c] = body[0]
        elif c == ":":
            self.menu_no = _text(body)
        elif c == "P":
            self.menu_entry = _text(body)
        elif c == "2":
            self.param = "" if body == b"0" else _text(body)
        elif c == "6" and n == 1:
            self.brightness = _num(chr(body[0]))
        elif c == "7" and n == 1:
            self.backlight = body == b"1"
        elif c == "8" and n == 1:
            self.lamp = _num(chr(body[0]))
        elif c == "9" and n == 1:
            self.mode_code = _num(chr(body[0]))
        elif c == "S" and n == 1:
            self.error = _text(body)
        elif c == "Q" and n == 1:
            self.model = {"0": "RX only", "1": "TWIN PWR"}.get(_text(body), _text(body))
        else:
            self.misc[c] = body.hex(" ")
        return None


def _num(s: str) -> int:
    try:
        return int(s, 10)
    except ValueError:
        try:
            return int(s, 16)
        except ValueError:
            return 0


class FrameReader:
    """Splits a byte stream on CR."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> list[bytes]:
        self._buf += data
        frames = []
        while True:
            i = self._buf.find(CR)
            if i < 0:
                break
            frame = bytes(self._buf[:i])
            del self._buf[: i + 1]
            if frame:
                frames.append(frame)
        if len(self._buf) > 256:          # garbage without CR
            self._buf.clear()
        return frames
