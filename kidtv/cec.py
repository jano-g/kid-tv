"""HDMI-CEC via cec-client (package cec-utils): receive key presses from the
TV's own remote and switch the TV on/off together with the kid TV."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
from typing import Awaitable, Callable

log = logging.getLogger("kidtv.cec")

# libcec key names as printed by cec-client ("key pressed: volume up (41)").
CEC_KEY_ACTIONS: dict[str, str] = {
    "select": "OK", "enter": "OK",
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "exit": "BACK", "return": "BACK", "back": "BACK", "previous channel": "BACK",
    "root menu": "MENU", "setup menu": "MENU", "contents menu": "MENU", "options": "MENU",
    "favorite menu": "HOME",
    "channel up": "CH_UP", "channel down": "CH_DOWN", "page up": "CH_UP", "page down": "CH_DOWN",
    "volume up": "VOL_UP", "volume down": "VOL_DOWN", "mute": "MUTE",
    "play": "PLAY_PAUSE", "pause": "PLAY_PAUSE", "stop": "PLAY_PAUSE",
    "forward": "NEXT", "backward": "PREV", "fast forward": "NEXT", "rewind": "PREV",
    "skip forward": "NEXT", "skip backward": "PREV", "next": "NEXT", "previous": "PREV",
    "power": "POWER", "power off": "POWER", "power on": "POWER", "power toggle": "POWER",
    "display information": "INFO", "info": "INFO",
    "0": "DIGIT_0", "1": "DIGIT_1", "2": "DIGIT_2", "3": "DIGIT_3", "4": "DIGIT_4",
    "5": "DIGIT_5", "6": "DIGIT_6", "7": "DIGIT_7", "8": "DIGIT_8", "9": "DIGIT_9",
}

_KEY_RE = re.compile(r"key (pressed|released):\s*(.+?)\s*\(([0-9a-fA-F]+)\)", re.IGNORECASE)
_TRAFFIC_STANDBY_RE = re.compile(r">>\s*0f:36\b")  # TV broadcasts standby
_TRAFFIC_ACTIVE_RE = re.compile(r">>\s*0f:82\b")

Callback = Callable[[str, str], Awaitable[None] | None]


class CecListener:
    """Runs `cec-client` for as long as the app lives and reports remote keys.

    callback(kind, value) with kind in {"key", "tv_standby", "tv_on"}."""

    def __init__(self, callback: Callback, osd_name: str = "Telka") -> None:
        self.callback = callback
        self.osd_name = osd_name[:14]
        self.proc: asyncio.subprocess.Process | None = None
        self.available = shutil.which("cec-client") is not None
        self._running = False

    async def run(self) -> None:
        if not self.available:
            log.info("cec-client not installed – HDMI-CEC disabled")
            return
        self._running = True
        backoff = 2.0
        while self._running:
            try:
                await self._run_once()
            except Exception:  # noqa: BLE001
                log.exception("cec-client crashed")
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)

    async def _run_once(self) -> None:
        self.proc = await asyncio.create_subprocess_exec(
            "cec-client", "-d", "8", "-t", "p", "-o", self.osd_name,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        assert self.proc.stdout is not None
        log.info("cec-client started")
        while True:
            line = await self.proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").strip()
            m = _KEY_RE.search(text)
            if m and m.group(1).lower() == "pressed":
                name = m.group(2).strip().lower()
                action = CEC_KEY_ACTIONS.get(name)
                if action:
                    await self._fire("key", action)
                continue
            if _TRAFFIC_STANDBY_RE.search(text):
                await self._fire("tv_standby", "")
            elif _TRAFFIC_ACTIVE_RE.search(text):
                await self._fire("tv_on", "")
        await self.proc.wait()
        self.proc = None

    async def _fire(self, kind: str, value: str) -> None:
        try:
            result = self.callback(kind, value)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001
            log.exception("cec callback failed")

    async def _send(self, command: str) -> None:
        if self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write((command + "\n").encode())
                await self.proc.stdin.drain()
            except (OSError, ConnectionError):
                pass

    async def tv_on(self) -> None:
        await self._send("on 0")
        await self._send("as")

    async def tv_standby(self) -> None:
        await self._send("standby 0")

    async def active_source(self) -> None:
        await self._send("as")

    def stop(self) -> None:
        self._running = False
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.terminate()
            except ProcessLookupError:
                pass
