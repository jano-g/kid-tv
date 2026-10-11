"""Which HDMI port the TV is plugged into, and the ALSA device for its sound.

A Raspberry Pi 4 has two HDMI ports, each with its own sound card (vc4hdmi0,
vc4hdmi1). Those cards only take IEC958 frames, so sound must go through ALSA's
"hdmi:" device, which wraps them – a plain "plughw:" device opens fine but
stays silent or fails. The port is detected each time mpv starts, so moving the
cable to the other port just works after the next wake-up or restart."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("kidtv.hdmi")

DRM = Path("/sys/class/drm")
ASOUND_CARDS = Path("/proc/asound/cards")


def connected_ports(drm: Path = DRM) -> list[int]:
    """0-based HDMI ports with a screen attached (HDMI-A-1 = port 0)."""
    ports = []
    for port in (0, 1):
        for status in sorted(drm.glob(f"card*-HDMI-A-{port + 1}/status")):
            try:
                if status.read_text().strip() == "connected":
                    ports.append(port)
                    break
            except OSError:
                continue
    return ports


def audio_device(drm: Path = DRM, cards: Path = ASOUND_CARDS) -> str | None:
    """mpv --audio-device for the connected HDMI port, or None to let mpv choose."""
    try:
        card_list = cards.read_text()
    except OSError:
        card_list = ""
    ports = connected_ports(drm)
    for port in ports + [0, 1]:
        card = f"vc4hdmi{port}"
        if card in card_list:
            return f"alsa/hdmi:CARD={card},DEV=0"
    return None
