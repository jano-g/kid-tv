"""Pushes Pillow images to mpv as overlays.

Layers (mpv overlay ids) – higher ids are drawn on top:
  1 PANEL   full-screen scenes (splash, menu, wizard, messages)
  2 BANNER  channel banner at the bottom
  3 VOLUME  volume pill
  4 TOAST   short notices
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from PIL import Image

from .. import paths

log = logging.getLogger("kidtv.ui")

PANEL, BANNER, VOLUME, TOAST = 1, 2, 3, 4
DESIGN_W, DESIGN_H = 1920, 1080


class Renderer:
    def __init__(self, player, runtime_dir: Path | None = None) -> None:  # type: ignore[no-untyped-def]
        self.player = player
        self.runtime_dir = runtime_dir or paths.runtime_dir()
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self._visible: dict[int, tuple[int, int, int, int]] = {}
        self._lock = asyncio.Lock()
        self._hide_tasks: dict[int, asyncio.Task] = {}

    # -- geometry -------------------------------------------------------------
    @property
    def size(self) -> tuple[int, int]:
        return self.player.osd_size if self.player else (DESIGN_W, DESIGN_H)

    @property
    def scale(self) -> float:
        w, h = self.size
        return min(w / DESIGN_W, h / DESIGN_H)

    # -- overlays -------------------------------------------------------------
    async def show(self, layer: int, image: Image.Image, x: int = 0, y: int = 0, hide_after: float | None = None) -> None:
        """Show *image* (RGBA) at screen position (x, y)."""
        if image.mode != "RGBA":
            image = image.convert("RGBA")
        w, h = image.size
        sw, sh = self.size
        # Clip to the screen – mpv rejects overlays that stick out.
        x = max(0, min(x, sw - w))
        y = max(0, min(y, sh - h))
        if w > sw or h > sh:
            image = image.crop((0, 0, min(w, sw), min(h, sh)))
            w, h = image.size
        data = image.tobytes("raw", "BGRA")
        file = self.runtime_dir / f"ovl-{layer}.bgra"
        tmp = file.with_suffix(".tmp")
        async with self._lock:
            tmp.write_bytes(data)
            tmp.replace(file)
            self._visible[layer] = (x, y, w, h)
            if self.player and self.player.running:
                try:
                    await self.player.overlay_add(layer, x, y, file, w, h)
                except Exception:  # noqa: BLE001
                    log.debug("overlay-add failed", exc_info=True)
        self._cancel_hide(layer)
        if hide_after:
            self._hide_tasks[layer] = asyncio.create_task(self._hide_later(layer, hide_after))

    async def hide(self, layer: int) -> None:
        self._cancel_hide(layer)
        if layer in self._visible:
            del self._visible[layer]
            if self.player and self.player.running:
                await self.player.overlay_remove(layer)

    async def hide_all(self) -> None:
        for layer in list(self._visible):
            await self.hide(layer)

    async def refresh(self) -> None:
        """Re-send all visible overlays (after mpv restarted)."""
        for layer, (x, y, w, h) in list(self._visible.items()):
            file = self.runtime_dir / f"ovl-{layer}.bgra"
            if file.exists() and self.player and self.player.running:
                try:
                    await self.player.overlay_add(layer, x, y, file, w, h)
                except Exception:  # noqa: BLE001
                    pass

    def is_visible(self, layer: int) -> bool:
        return layer in self._visible

    def _cancel_hide(self, layer: int) -> None:
        task = self._hide_tasks.pop(layer, None)
        if task:
            task.cancel()

    async def _hide_later(self, layer: int, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            self._hide_tasks.pop(layer, None)
            await self.hide(layer)
        except asyncio.CancelledError:
            pass
