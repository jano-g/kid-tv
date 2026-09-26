"""Deep standby helpers: switch the HDMI signal off and slow the CPU down.

A Raspberry Pi 4 cannot sleep and be woken by a USB remote, so standby keeps it
running – but with mpv closed, the screen powered down (many TVs then go to
sleep on their own, even without HDMI-CEC) and the CPU on its slowest clock.
Every step is best effort: failing to save power must never break waking up."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("kidtv.power")

FB_BLANK = Path("/sys/class/graphics/fb0/blank")  # fbdev emulation of the KMS display
CPUFREQ = Path("/sys/devices/system/cpu/cpufreq")
FB_BLANK_UNBLANK, FB_BLANK_POWERDOWN = "0", "4"


def _write(path: Path, value: str) -> bool:
    try:
        path.write_text(value)
        return True
    except OSError as exc:
        log.debug("could not write %s to %s: %s", value, path, exc)
        return False


def screen_off(fb_blank: Path = FB_BLANK) -> bool:
    """Power the display down (DPMS off). Needs mpv closed so the console owns it."""
    return _write(fb_blank, FB_BLANK_POWERDOWN)


def screen_on(fb_blank: Path = FB_BLANK) -> bool:
    return _write(fb_blank, FB_BLANK_UNBLANK)


def set_governor(name: str, cpufreq: Path = CPUFREQ) -> str | None:
    """Switch every CPU policy to governor *name*; returns the one used before
    (to restore on wake), or None when cpufreq is not available."""
    previous = None
    try:
        policies = sorted(cpufreq.glob("policy*"))
    except OSError:
        return None
    for policy in policies:
        try:
            current = (policy / "scaling_governor").read_text().strip()
            available = (policy / "scaling_available_governors").read_text().split()
        except OSError:
            continue
        previous = previous or current
        if name in available and name != current:
            _write(policy / "scaling_governor", name)
    return previous
