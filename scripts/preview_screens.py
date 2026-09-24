#!/usr/bin/env python3
"""Render every on-screen scene to PNG files for a quick visual check.

Usage: python3 scripts/preview_screens.py OUT_DIR [--lang sk|en] [--avatar photo.jpg] [--size 1920x1080]"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from kidtv.i18n import Translator  # noqa: E402
from kidtv.ui import screens as S  # noqa: E402
from kidtv.ui import theme as T  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--lang", default="sk")
    ap.add_argument("--avatar")
    ap.add_argument("--size", default="1920x1080")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    w, h = (int(v) for v in a.size.split("x"))
    avatar = Image.open(a.avatar).convert("RGBA") if a.avatar else None
    ctx = S.UIContext(Translator(a.lang), "Anna", "Annina telka", avatar, w, h, "0.1.0")
    tr = ctx.tr
    qr = S.make_qr("http://kid.local")
    items = [
        S.MenuItem("language", tr("menu.language"), "Slovenčina", has_arrows=True),
        S.MenuItem("child", tr("menu.child_name"), "Anna"),
        S.MenuItem("tv", tr("menu.tv_name"), "Annina telka"),
        S.MenuItem("wifi", tr("menu.wifi"), "Doma 5G"),
        S.MenuItem("hotspot", tr("menu.hotspot")),
        S.MenuItem("limit", tr("menu.daily_limit"), tr("menu.daily_limit.value", min=60), has_arrows=True),
        S.MenuItem("add", tr("menu.add_time")),
        S.MenuItem("maxvol", tr("menu.max_volume"), "100", has_arrows=True),
        S.MenuItem("remote", tr("menu.remote")),
        S.MenuItem("web", tr("menu.web"), "http://kid.local"),
        S.MenuItem("rescan", tr("menu.rescan")),
        S.MenuItem("wizard", tr("menu.wizard")),
        S.MenuItem("update", tr("menu.update"), tr("menu.update.available", version="0.2.0")),
        S.MenuItem("restart", tr("menu.restart")),
        S.MenuItem("shutdown", tr("menu.shutdown"), danger=True),
        S.MenuItem("about", tr("menu.about"), "0.1.0"),
    ]
    scenes = {
        "01-splash": S.splash(ctx),
        "02-banner": S.channel_banner(ctx, 2, "Maťko a Kubko", "Ako Maťko a Kubko stavali salaš", 3, 12, 312.0, 1290.0, False, 42),
        "03-volume": S.volume_pill(ctx, 65, False),
        "04-toast": S.toast(ctx, tr("toast.wifi_connected", ssid="Doma 5G")),
        "05-menu": S.menu(ctx, tr("menu.title"), items, 5),
        "06-keyboard": S.keyboard(ctx, tr("wifi.password", ssid="Doma 5G"), "tajneheslo", False, False, (1, 4), secret=True),
        "07-wizard-welcome": S.wizard_page(ctx, 0, 5, tr("wizard.welcome.title"), tr("wizard.welcome.text"), tr("wizard.next")),
        "08-wizard-web": S.wizard_page(ctx, 3, 5, tr("wizard.web.title"), tr("wizard.web.text"), tr("wizard.finish"), accent=T.MINT, url="http://kid.local", qr=qr),
        "09-standby": S.standby(ctx),
        "10-limit": S.limit_reached(ctx),
        "11-music": S.music(ctx, 4, "Pesničky", "Spievankovo – Mám ja doma zvieratká", 2, 18, 61.0, 190.0),
        "12-empty": S.empty_channel(ctx, 3, "http://kid.local", qr, False),
        "13-pin": S.pin_entry(ctx, 2, False),
        "14-confirm": S.confirm(ctx, tr("menu.shutdown") + "?", 1),
        "15-hotspot": S.wizard_page(ctx, 1, 5, tr("hotspot.title"), "\n".join([tr("hotspot.step1", ssid="Annina telka"), tr("hotspot.step2"), tr("hotspot.step3")]), tr("hotspot.stop"), accent=T.SKY, qr=S.make_qr("WIFI:T:nopass;S:Annina telka;;")),
        "16-learn": S.learn_remote(ctx, tr("action.CH_UP"), 2, 11),
        "17-update-download": S.updating(ctx, "0.2.0", 0.42),
        "18-update-install": S.updating(ctx, "0.2.0"),
        "19-update-confirm": S.confirm(ctx, tr("update.confirm", version="0.2.0"), 0),
        "20-menu-update": S.menu(ctx, tr("menu.title"), items, 12),
    }
    for name, (img, x, y) in scenes.items():
        # Composite partial overlays onto a dark frame so they can be judged in context.
        if img.size != (w, h):
            frame = Image.new("RGBA", (w, h), (40, 50, 70, 255))
            frame.alpha_composite(img, (x, y))
            img = frame
        img.convert("RGB").save(out / f"{name}.png")
        print("wrote", out / f"{name}.png")


if __name__ == "__main__":
    main()
