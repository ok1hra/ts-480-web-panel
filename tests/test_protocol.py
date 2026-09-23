# SPDX-License-Identifier: GPL-3.0-or-later
from ts480.protocol import (DisplayState, FrameReader, key_msg, vfo_msg, multi_msg,
                            rit_msg, ifshift_msg, volume_msg, decode_panel_frame, KEY_DOWN)

# radio -> panel power-on dump from stianeklund/TS-480-Panel "Radio/Power on sequence.md"
BOOT = bytes.fromhex("""
0D 0D 30 31 0D 30 31 0D 3A 20 20 0D 52 30 0D 32 30 0D 36 31 0D 37 31 0D 38 30 0D
39 32 0D 3B 32 38 30 36 36 39 37 0D 3C 20 20 20 20 20 20 20 20 0D 3D 30 30 30 30 0D
3E 37 31 0D 3F 80 0D 40 84 0D 41 81 0D 42 81 0D 43 C0 0D 44 81 0D 45 81 0D
46 89 80 80 0D 4C 80 0D 3D 31 33 30 30 0D 51 30 0D 4F 0D 33 31 0D 38 31 0D 53 30 0D FF 0D
""")


def run(data: bytes):
    st, r, actions = DisplayState(), FrameReader(), []
    for f in r.feed(data):
        a = st.apply(f)
        if a:
            actions.append(a)
    return st, actions


def test_boot_dump():
    st, actions = run(BOOT)
    assert st.power is True
    assert st.freq_text() == "28.066.97"
    assert st.frequency_hz() == 28_066_970
    assert st.meter_main == 13 and st.meter_sub == 0
    assert st.lamp == 1 and st.brightness == 1 and st.backlight
    d = st.to_dict()
    assert {"ANT1", "AGC", "A", "AUTO", "◂1"} <= set(d["icons"])
    assert d["model"] == "RX only"
    assert actions == ["query", "keepalive"]


def test_xit_status_line():
    st, _ = run(bytes.fromhex("3C 20 20 20 20 31 37 36 30 0D 43 E8 0D 46 89 81 80 0D"))
    assert st.status_text().strip() == "1.760"
    assert {"XIT", "PC", "AUTO"} <= set(st.to_dict()["icons"])


def test_split_frames_across_reads():
    r = FrameReader()
    assert r.feed(b";28") == []
    assert r.feed(b"50000\r=08") == [b";2850000"]
    assert r.feed(b"00\r") == [b"=0800"]


def test_panel_messages():
    assert key_msg("NB", KEY_DOWN) == b":1\r"
    assert key_msg("POWER", KEY_DOWN) == b"01\r"
    assert vfo_msg(1) == b"S0001\r"
    assert vfo_msg(-2) == b"SFFFE\r"
    assert multi_msg(-1) == b"TFF\r"
    assert rit_msg(1) == b"U01\r"
    assert ifshift_msg(0x201) == b"X0201\r"
    assert volume_msg(0x2A) == b"V2A\r"
    assert decode_panel_frame(b"SFFFE") == "VFO -2"
    assert decode_panel_frame(b"N1") == "KEY RIT down"
