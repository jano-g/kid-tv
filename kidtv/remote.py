"""Remote control input via Linux evdev.

Any USB/2.4 GHz/Bluetooth remote that shows up as a keyboard works out of the
box; the mapping from raw key names to logical TV actions is configurable and
can be re-learned from the on-screen menu or the web UI."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("kidtv.remote")

try:  # evdev is Linux-only; keep the module importable elsewhere for tests.
    import evdev
    from evdev import ecodes
except ImportError:  # pragma: no cover
    evdev = None
    ecodes = None

ACTIONS = [
    "POWER", "VOL_UP", "VOL_DOWN", "MUTE", "CH_UP", "CH_DOWN", "NEXT", "PREV",
    "UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK", "MENU", "HOME", "PLAY_PAUSE", "INFO",
    "DIGIT_0", "DIGIT_1", "DIGIT_2", "DIGIT_3", "DIGIT_4", "DIGIT_5", "DIGIT_6", "DIGIT_7", "DIGIT_8", "DIGIT_9",
]

# Actions offered in the "learn remote" wizard, in order.
LEARNABLE = ["POWER", "UP", "DOWN", "LEFT", "RIGHT", "OK", "BACK", "MENU", "VOL_UP", "VOL_DOWN", "MUTE"]

# Default mapping covering common air-mouse remotes (G10S, G20S, MX3, Rii),
# HDMI-CEC forwarded keys and a plain keyboard for development.
DEFAULT_MAP: dict[str, str] = {
    "KEY_POWER": "POWER", "KEY_POWER2": "POWER", "KEY_SLEEP": "POWER", "KEY_WAKEUP": "POWER", "KEY_SUSPEND": "POWER",
    "KEY_VOLUMEUP": "VOL_UP", "KEY_VOLUMEDOWN": "VOL_DOWN", "KEY_MUTE": "MUTE",
    "KEY_KPPLUS": "VOL_UP", "KEY_KPMINUS": "VOL_DOWN", "KEY_EQUAL": "VOL_UP", "KEY_MINUS": "VOL_DOWN",
    "KEY_CHANNELUP": "CH_UP", "KEY_CHANNELDOWN": "CH_DOWN", "KEY_PAGEUP": "CH_UP", "KEY_PAGEDOWN": "CH_DOWN",
    "KEY_NEXTSONG": "NEXT", "KEY_PREVIOUSSONG": "PREV", "KEY_FASTFORWARD": "NEXT", "KEY_REWIND": "PREV",
    "KEY_NEXT": "NEXT", "KEY_PREVIOUS": "PREV", "KEY_N": "NEXT", "KEY_P": "PREV",
    "KEY_UP": "UP", "KEY_DOWN": "DOWN", "KEY_LEFT": "LEFT", "KEY_RIGHT": "RIGHT",
    "KEY_ENTER": "OK", "KEY_KPENTER": "OK", "KEY_SELECT": "OK", "KEY_OK": "OK", "BTN_LEFT": "OK", "BTN_MOUSE": "OK",
    "KEY_SPACE": "PLAY_PAUSE", "KEY_PLAYPAUSE": "PLAY_PAUSE", "KEY_PLAY": "PLAY_PAUSE", "KEY_PAUSE": "PLAY_PAUSE",
    "KEY_PLAYCD": "PLAY_PAUSE", "KEY_PAUSECD": "PLAY_PAUSE", "KEY_STOP": "PLAY_PAUSE", "KEY_STOPCD": "PLAY_PAUSE",
    "KEY_BACK": "BACK", "KEY_ESC": "BACK", "KEY_EXIT": "BACK", "BTN_RIGHT": "BACK", "KEY_BACKSPACE": "BACK",
    "KEY_MENU": "MENU", "KEY_COMPOSE": "MENU", "KEY_CONTEXT_MENU": "MENU", "KEY_SETUP": "MENU", "KEY_M": "MENU",
    "KEY_CONFIG": "MENU", "KEY_PROPS": "MENU", "KEY_F1": "MENU",
    "KEY_HOMEPAGE": "HOME", "KEY_HOME": "HOME", "KEY_H": "HOME", "KEY_ROOT_MENU": "HOME",
    "KEY_INFO": "INFO", "KEY_I": "INFO",
    "KEY_0": "DIGIT_0", "KEY_1": "DIGIT_1", "KEY_2": "DIGIT_2", "KEY_3": "DIGIT_3", "KEY_4": "DIGIT_4",
    "KEY_5": "DIGIT_5", "KEY_6": "DIGIT_6", "KEY_7": "DIGIT_7", "KEY_8": "DIGIT_8", "KEY_9": "DIGIT_9",
    "KEY_KP0": "DIGIT_0", "KEY_KP1": "DIGIT_1", "KEY_KP2": "DIGIT_2", "KEY_KP3": "DIGIT_3", "KEY_KP4": "DIGIT_4",
    "KEY_KP5": "DIGIT_5", "KEY_KP6": "DIGIT_6", "KEY_KP7": "DIGIT_7", "KEY_KP8": "DIGIT_8", "KEY_KP9": "DIGIT_9",
}

# Codes whose "press" we never want to treat as a button (mouse movement etc.).
IGNORED_PREFIXES = ("REL_", "ABS_", "SYN_", "MSC_", "LED_")

KeyHandler = Callable[["KeyPress"], Awaitable[None] | None]


class KeyPress:
    """A logical key event: press / release / repeat / long-press."""

    __slots__ = ("keyname", "action", "kind", "device")

    def __init__(self, keyname: str, action: str | None, kind: str, device: str) -> None:
        self.keyname = keyname  # e.g. KEY_VOLUMEUP
        self.action = action  # e.g. VOL_UP (None when unmapped)
        self.kind = kind  # "down" | "up" | "repeat" | "long"
        self.device = device

    def __repr__(self) -> str:  # pragma: no cover
        return f"KeyPress({self.keyname}, {self.action}, {self.kind})"


class KeyMapper:
    def __init__(self, overrides: dict[str, str] | None = None) -> None:
        self.overrides = dict(overrides or {})

    def action_for(self, keyname: str) -> str | None:
        if keyname in self.overrides:
            act = self.overrides[keyname]
            return act if act in ACTIONS else None
        return DEFAULT_MAP.get(keyname)

    def learn(self, keyname: str, action: str) -> None:
        # One physical button = one action: drop older assignments of this key.
        self.overrides = {k: v for k, v in self.overrides.items() if k != keyname}
        self.overrides[keyname] = action

    def mapping_for_action(self, action: str) -> list[str]:
        keys = [k for k, v in DEFAULT_MAP.items() if v == action and k not in self.overrides]
        keys += [k for k, v in self.overrides.items() if v == action]
        return keys


def keyname_for(code: int) -> str:
    if ecodes is None:  # pragma: no cover
        return f"KEY_{code}"
    name = ecodes.bytype[ecodes.EV_KEY].get(code) if code in ecodes.bytype[ecodes.EV_KEY] else None
    if name is None:
        name = f"KEY_{code}"
    if isinstance(name, (list, tuple)):
        name = name[0]
    return str(name)


class LongPressTracker:
    """Turns raw down/up events into KeyPress objects, adding a synthetic 'long'
    event once a key is held for *hold_ms*."""

    def __init__(self, hold_ms: int = 1500) -> None:
        self.hold_ms = hold_ms
        self._down: dict[str, float] = {}
        self._long_fired: set[str] = set()

    def down(self, keyname: str, now: float | None = None) -> None:
        self._down[keyname] = now if now is not None else time.monotonic()
        self._long_fired.discard(keyname)

    def up(self, keyname: str) -> bool:
        """Return True when this release should count as a short press."""
        was_long = keyname in self._long_fired
        self._down.pop(keyname, None)
        self._long_fired.discard(keyname)
        return not was_long

    def check_long(self, now: float | None = None) -> list[str]:
        now = now if now is not None else time.monotonic()
        fired = []
        for keyname, since in list(self._down.items()):
            if keyname not in self._long_fired and (now - since) * 1000 >= self.hold_ms:
                self._long_fired.add(keyname)
                fired.append(keyname)
        return fired


class RemoteListener:
    """Reads all input devices that look like remotes/keyboards and calls the
    handler with logical key presses. Devices are re-scanned periodically so a
    dongle plugged in later just works."""

    def __init__(self, handler: KeyHandler, mapper: KeyMapper, hold_ms: int = 1500) -> None:
        self.handler = handler
        self.mapper = mapper
        self.tracker = LongPressTracker(hold_ms)
        self._tasks: dict[str, asyncio.Task] = {}
        self._devices: dict[str, str] = {}  # path -> name
        self.last_key: tuple[str, str, float] | None = None  # (keyname, device, monotonic)
        self._running = False

    @property
    def devices(self) -> list[str]:
        return sorted(set(self._devices.values()))

    def set_hold_ms(self, hold_ms: int) -> None:
        self.tracker.hold_ms = hold_ms

    async def run(self) -> None:
        if evdev is None:
            log.warning("evdev not available – remote control disabled")
            return
        self._running = True
        long_task = asyncio.create_task(self._long_press_loop(), name="remote-longpress")
        try:
            while self._running:
                self._rescan()
                await asyncio.sleep(2.0)
        finally:
            long_task.cancel()
            for t in self._tasks.values():
                t.cancel()

    def stop(self) -> None:
        self._running = False

    def _rescan(self) -> None:
        assert evdev is not None
        present = set()
        for path in evdev.list_devices():
            present.add(path)
            if path in self._tasks and not self._tasks[path].done():
                continue
            try:
                dev = evdev.InputDevice(path)
            except OSError:
                continue
            caps = dev.capabilities()
            keys = set(caps.get(ecodes.EV_KEY, []))
            if not keys:
                dev.close()
                continue
            # Skip pure mice/touchpads (buttons only) – but keep devices that
            # carry at least one keyboard/remote key.
            if not any(k < 0x100 or 0x160 <= k < 0x300 for k in keys):
                dev.close()
                continue
            self._devices[path] = dev.name
            self._tasks[path] = asyncio.create_task(self._read_device(dev), name=f"remote-{Path(path).name}")
            log.info("remote: listening on %s (%s)", path, dev.name)
        for path in list(self._tasks):
            if path not in present:
                self._tasks.pop(path).cancel()
                self._devices.pop(path, None)

    async def _read_device(self, dev) -> None:  # type: ignore[no-untyped-def]
        assert evdev is not None
        try:
            async for event in dev.async_read_loop():
                if event.type != ecodes.EV_KEY:
                    continue
                keyname = keyname_for(event.code)
                if keyname.startswith(IGNORED_PREFIXES):
                    continue
                if event.value == 1:  # down
                    self.tracker.down(keyname)
                    self.last_key = (keyname, dev.name, time.monotonic())
                    await self._emit(keyname, "down", dev.name)
                elif event.value == 2:  # autorepeat
                    await self._emit(keyname, "repeat", dev.name)
                elif event.value == 0:  # up
                    short = self.tracker.up(keyname)
                    await self._emit(keyname, "up" if short else "up-after-long", dev.name)
        except (OSError, asyncio.CancelledError):
            pass
        finally:
            try:
                dev.close()
            except Exception:  # noqa: BLE001
                pass

    async def _long_press_loop(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            for keyname in self.tracker.check_long():
                await self._emit(keyname, "long", "")

    async def _emit(self, keyname: str, kind: str, device: str) -> None:
        press = KeyPress(keyname, self.mapper.action_for(keyname), kind, device)
        try:
            result = self.handler(press)
            if asyncio.iscoroutine(result):
                await result
        except Exception:  # noqa: BLE001
            log.exception("key handler failed for %r", press)
