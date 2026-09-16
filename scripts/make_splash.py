#!/usr/bin/env python3
"""Render the generic boot splash (kidtv/assets/splash.png). The running app
writes a personalised copy to /var/lib/kidtv/splash.png."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kidtv.i18n import Translator  # noqa: E402
from kidtv.ui import screens as S  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1] / "kidtv/assets/splash.png"
    ctx = S.UIContext(Translator("sk"), "", "Telka", None, 1920, 1080, "")
    img, _, _ = S.splash(ctx)
    img.convert("RGB").save(out, "PNG", optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
