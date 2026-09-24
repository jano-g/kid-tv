from PIL import Image

from kidtv.i18n import Translator
from kidtv.ui import screens as S
from kidtv.ui.renderer import DESIGN_W, DESIGN_H


def ctx(lang="sk", w=DESIGN_W, h=DESIGN_H):
    return S.UIContext(Translator(lang), "Anna", "Annina telka", None, w, h, "0.1.0")


def test_full_screen_scenes_have_screen_size():
    for c in (ctx(), ctx("en", 1280, 720)):
        for scene in (S.splash(c), S.standby(c), S.limit_reached(c), S.pin_entry(c, 1, True),
                      S.menu(c, "x", [S.MenuItem("a", "A", "1", has_arrows=True)] * 20, 15),
                      S.keyboard(c, "t", "abc", False, True, (0, 0)),
                      S.wizard_page(c, 0, 3, "T", "text", "Next", options=["a", "b"]),
                      S.empty_channel(c, 2, "http://kid.local", S.make_qr("http://kid.local"), False),
                      S.no_channels(c, None, None),
                      S.music(c, 1, "Pesničky", "Song", 1, 3, 10.0, 100.0)):
            img, x, y = scene
            assert (img.size, x, y) == ((c.width, c.height), 0, 0)


def test_partial_overlays_fit_on_screen():
    c = ctx()
    for img, x, y in (S.channel_banner(c, 12, "N" * 80, "T" * 120, 1, 1, None, None, True, 5),
                      S.volume_pill(c, 100, False), S.volume_pill(c, 30, True),
                      S.toast(c, "Wi-Fi pripojená: Doma")):
        assert x >= 0 and y >= 0
        assert x + img.size[0] <= c.width and y + img.size[1] <= c.height


def test_keyboard_layout_modes():
    lower = S.keyboard_layout(False, False)
    upper = S.keyboard_layout(False, True)
    sym = S.keyboard_layout(True, False)
    assert lower[0][0] == "q" and upper[0][0] == "Q" and sym[0][0] == "1"
    assert lower[-1] == ["SHIFT", "SYMBOLS", "SPACE", "DELETE", "DONE", "CANCEL"]
    assert "ž" in "".join(lower[4]) and "€" in "".join(sym[4])


def test_make_qr_returns_image():
    qr = S.make_qr("WIFI:T:nopass;S:Annina telka;;")
    assert isinstance(qr, Image.Image) and qr.size[0] > 20


def test_screens_without_a_name():
    c = S.UIContext(Translator("sk"), "", "Telka", None, DESIGN_W, DESIGN_H, "0.2.1")
    for img, x, y in (S.splash(c), S.standby(c), S.limit_reached(c), S.music(c, 1, "P", "S", 1, 1, 0.0, 1.0)):
        assert img.size == (DESIGN_W, DESIGN_H)
    assert c.initial == ""
    assert Translator("sk")("standby.goodnight.anon") == "Dobrú noc!"
