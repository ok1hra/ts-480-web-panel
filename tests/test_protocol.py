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


# Captured on a real TS-480 on 2026-11-13 with tools/bridge.py + tools/cat_probe.py
REAL_BOOT = bytes.fromhex("""
30 31 0D 3A 20 20 0D 52 30 0D 32 30 0D 36 31 0D 37 30 0D 38 30 0D 39 32 0D
3B 20 37 30 37 38 32 37 0D 3C 20 20 20 20 20 20 20 20 0D 3D 30 30 30 30 0D 3E 37 31 0D
3F 80 0D 40 88 0D 41 85 0D 42 80 0D 43 88 0D 44 81 0D 45 81 0D 46 89 80 80 0D 4C 80 0D
""")


def test_real_boot_dump():
    st, _ = run(REAL_BOOT)
    d = st.to_dict()
    assert d["freq"] == " 7.078.27" and d["freq_hz"] == 7_078_270
    assert d["mode"] == "USB"                      # CAT MD2 <-> panel "92"
    assert {"ANT2", "AGC", "-F", "PC", "A"} <= set(d["icons"])


def test_mode_digit_is_cat_md_code():
    from ts480.protocol import MODE_NAMES
    assert [MODE_NAMES[i] for i in (1, 2, 3, 4, 5, 6, 7, 9)] == \
        ["LSB", "USB", "CW", "FM", "AM", "FSK", "CW-R", "FSK-R"]


def test_verified_flag_bits():
    # each pair: frame -> icon that CAT toggling proved
    cases = {b"?\x82": "ATT", b"?\x81": "PRE", b"?\x84": "PROC", b"?\x90": "NB", b"?\xc0": "FINE",
             b"B\x88": "NR1", b"B\x84": "NR2", b"B\xa0": "BC1", b"B\x90": "BC2", b"B\xc0": "DNL",
             b"C\x90": "RIT", b"C\xa0": "XIT", b"C\x81": "T", b"C\x82": "CT", b"@\x84": "ANT1"}
    for frame, icon in cases.items():
        st = DisplayState()
        st.apply(frame)
        assert icon in st.to_dict()["icons"], (frame, icon)


def test_rit_offset_status_in_hz():
    st, _ = run(b"<   -0001\rF\x89\x81\x80\r")
    assert st.status_text().strip() == "-0.001"      # kHz, i.e. -1 Hz


def test_scan_and_mode_key_codes():
    assert key_msg("SCAN", KEY_DOWN) == b"E1\r"
    assert key_msg("MODE", KEY_DOWN) == b"F1\r"


def test_menu_frames():
    # real unit, menu 10 (P0A) with value 0, menu 48 (P30) with value 0x43 = 67
    st, _ = run(b":10\rP0A\r2E\r400\r@\x98\r")
    d = st.to_dict()
    assert d["menu_no"] == "10" and d["menu_item"] == 10 and d["menu_value"] == 0
    assert d["param"] == "E" and "MENU" in d["icons"]
    st.apply(b"P30"); st.apply(b"443")
    assert st.menu_item == 48 and st.menu_value == 67


def test_power_key_is_on_off_not_press_release():
    import asyncio
    from ts480.link import PanelLink

    class T:
        def __init__(self): self.out = []
        def write(self, d): self.out.append(d)
        def read(self): return b""
        def close(self): pass

    t = T()
    link = PanelLink(t)
    link.state.power = False
    link.key_down("POWER"); link.key_up("POWER")
    assert t.out == [b"01\r"]                 # switch on, nothing on release
    link.state.power = True
    link.key_down("POWER"); link.key_up("POWER")
    assert t.out[-1] == b"00\r" and len(t.out) == 2
