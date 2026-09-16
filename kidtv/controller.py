"""The TV itself: turns remote-control actions into playback, keeps the
per-channel resume points, enforces the daily limit and drives the on-screen
menus, first-run wizard and Wi-Fi setup."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import __version__, paths
from .cec import CecListener
from .config import Config
from .i18n import LANGUAGES, Translator
from .library import Channel, scan_library
from .net import Network, NetStatus, web_urls
from .player import Player
from .remote import ACTIONS, LEARNABLE, KeyMapper, KeyPress, RemoteListener
from .state import State
from .ui import screens as S
from .ui import theme as T
from .ui.renderer import BANNER, PANEL, TOAST, VOLUME, Renderer

log = logging.getLogger("kidtv.tv")

MODE_TV, MODE_STANDBY, MODE_LIMIT, MODE_MENU, MODE_KEYBOARD, MODE_WIFI, MODE_HOTSPOT = (
    "tv", "standby", "limit", "menu", "keyboard", "wifi", "hotspot")
MODE_PIN, MODE_CONFIRM, MODE_LEARN, MODE_WIZARD, MODE_ABOUT = "pin", "confirm", "learn", "wizard", "about"

WIZARD_STEPS = ["welcome", "language", "wifi", "name", "web", "done"]
LIMIT_STEPS = [0, 15, 30, 45, 60, 75, 90, 120, 150, 180, 240]
VOLUME_STEP = 5


class TV:
    def __init__(self, config: Config, state: State, player: Player, network: Network, media_dir: Path,
                 dev: bool = False) -> None:
        self.config = config
        self.state = state
        self.player = player
        self.network = network
        self.media_dir = media_dir
        self.dev = dev
        self.renderer = Renderer(player)
        self.mapper = KeyMapper(config.get("remote_map") or {})
        self.remote: RemoteListener | None = None
        self.cec: CecListener | None = None
        self.avatar = T.load_avatar()
        self.channels: list[Channel] = []
        self.channel_index = 0
        self.episode_index = 0
        self.mode = MODE_TV
        self.muted = False
        self.net_status = NetStatus(False, "none", None, None, False)
        self.started_at = time.monotonic()
        self.log_lines: list[str] = []
        self._tasks: list[asyncio.Task] = []
        self._save_counter = 0
        self._digit_buffer = ""
        self._digit_task: asyncio.Task | None = None
        self._media_signature: tuple = ()
        self._limit_warned = False
        # Menu / dialog state.
        self._menu_selected = 0
        self._menu_items: list[S.MenuItem] = []
        self._menu_return: str = MODE_TV
        self._kb: dict[str, Any] = {}
        self._wifi: dict[str, Any] = {}
        self._confirm: dict[str, Any] = {}
        self._pin_entered = ""
        self._pin_error = False
        self._learn: dict[str, Any] = {}
        self._wizard_step = 0
        self._wizard_option = 0
        self._web_learn_action: str | None = None
        self._hotspot_task: asyncio.Task | None = None
        self._standby_black_task: asyncio.Task | None = None
        self.config.on_change(self._config_changed)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @property
    def tr(self) -> Translator:
        return Translator(self.config["language"])

    def ctx(self) -> S.UIContext:
        w, h = self.renderer.size
        return S.UIContext(self.tr, self.config["child_name"], self.config["tv_name"], self.avatar, w, h, __version__)

    @property
    def channel(self) -> Channel | None:
        if not self.channels:
            return None
        self.channel_index = max(0, min(self.channel_index, len(self.channels) - 1))
        return self.channels[self.channel_index]

    def log_event(self, text: str) -> None:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        self.log_lines.append(f"{stamp}  {text}")
        del self.log_lines[:-60]
        log.info(text)

    def web_url(self) -> str | None:
        urls = web_urls(self.net_status)
        return urls[0] if urls else None

    async def show(self, layer: int, scene: S.Scene, hide_after: float | None = None) -> None:
        img, x, y = scene
        await self.renderer.show(layer, img, x, y, hide_after)

    async def toast(self, text: str, accent: T.RGBA = T.MINT, seconds: float = 3.0) -> None:
        await self.show(TOAST, S.toast(self.ctx(), text, accent), hide_after=seconds)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        paths.ensure_dirs()
        await self.player.start()
        self.player.on_event(self._player_event)
        await self.show(PANEL, S.splash(self.ctx()))
        await self.player.set_volume(int(self.config["volume"]))
        self.rescan(initial=True)
        self._tasks.append(asyncio.create_task(self._ticker(), name="tv-ticker"))
        self._tasks.append(asyncio.create_task(self._network_monitor(), name="tv-net"))
        self._tasks.append(asyncio.create_task(self._media_monitor(), name="tv-media"))
        self.remote = RemoteListener(self.handle_key, self.mapper, int(self.config["settings_hold_ms"]))
        self._tasks.append(asyncio.create_task(self.remote.run(), name="tv-remote"))
        self.cec = CecListener(self._cec_event, self.config["tv_name"])
        self._tasks.append(asyncio.create_task(self.cec.run(), name="tv-cec"))
        self.net_status = await self.network.status()
        if not (paths.data_dir() / "splash.png").exists():
            self.write_splash()
        await asyncio.sleep(1.2)  # let the splash be seen
        if not self.config["setup_done"]:
            await self.start_wizard()
        else:
            await self.renderer.hide(PANEL)
            await self.play_channel(self._restore_channel_index(), resume=True)
        self.log_event("started")

    async def stop(self) -> None:
        self._update_resume_point()
        self.state.save(force=True)
        for t in self._tasks:
            t.cancel()
        if self.remote:
            self.remote.stop()
        if self.cec:
            self.cec.stop()
        await self.player.stop()

    def _restore_channel_index(self) -> int:
        folder = self.state.current_channel
        for i, ch in enumerate(self.channels):
            if ch.folder == folder:
                return i
        return 0

    # ------------------------------------------------------------------
    # Library
    # ------------------------------------------------------------------
    def rescan(self, initial: bool = False) -> bool:
        """Re-read the media folder. Returns True when something changed."""
        current_folder = self.channel.folder if self.channel else self.state.current_channel
        new = scan_library(self.media_dir, self.config.get("channel_names") or {})
        sig = tuple((c.folder, tuple(e.filename for e in c.episodes)) for c in new)
        changed = sig != self._media_signature
        self._media_signature = sig
        self.channels = new
        self.channel_index = 0
        for i, ch in enumerate(new):
            if ch.folder == current_folder:
                self.channel_index = i
        return changed and not initial

    def _media_sig_quick(self) -> tuple:
        try:
            items = [(p.name, p.stat().st_mtime_ns) for p in self.media_dir.iterdir() if p.is_dir()]
        except OSError:
            items = []
        items.sort()
        try:
            root = self.media_dir.stat().st_mtime_ns
        except OSError:
            root = 0
        return (root, tuple(items))

    async def _media_monitor(self) -> None:
        last = self._media_sig_quick()
        while True:
            await asyncio.sleep(4)
            try:
                sig = self._media_sig_quick()
                if sig != last:
                    last = sig
                    await self.media_changed()
            except Exception:  # noqa: BLE001
                log.exception("media monitor failed")

    async def media_changed(self) -> None:
        current = self.channel
        current_file = self._current_episode_name()
        if not self.rescan():
            return
        self.log_event("media changed")
        if self.mode in (MODE_TV, MODE_LIMIT):
            await self.toast(self.tr("toast.media_changed"))
        ch = self.channel
        if self.mode != MODE_TV or ch is None:
            return
        if current is None or ch.folder != current.folder or ch.index_of(current_file) is None:
            await self.play_channel(self.channel_index, resume=True)
        else:
            self.episode_index = ch.index_of(current_file) or 0
            if self.player.idle:
                await self.play_channel(self.channel_index, resume=True)

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------
    def _current_episode_name(self) -> str | None:
        ch = self.channel
        if ch and ch.episodes and 0 <= self.episode_index < len(ch.episodes):
            return ch.episodes[self.episode_index].filename
        return None

    async def play_channel(self, index: int, resume: bool = True, episode: int | None = None,
                           position: float = 0.0) -> None:
        if not self.channels:
            self.state.set_current_channel(None)
            await self.player.stop_playback()
            await self.renderer.hide(BANNER)
            await self.show(PANEL, S.no_channels(self.ctx(), self.web_url(), self._qr(self.web_url())))
            return
        self.channel_index = index % len(self.channels)
        ch = self.channels[self.channel_index]
        self.state.set_current_channel(ch.folder)
        if ch.is_empty:
            await self.player.stop_playback()
            await self.renderer.hide(BANNER)
            await self.show(PANEL, S.empty_channel(self.ctx(), ch.number, self.web_url(), self._qr(self.web_url()),
                                                   not self.net_status.connected))
            self.state.save()
            return
        if episode is not None:
            self.episode_index = episode % len(ch.episodes)
            start = position
        elif resume:
            filename, start = self.state.resume_point(ch.folder)
            idx = ch.index_of(filename)
            if idx is None:
                idx, start = 0, 0.0
            self.episode_index = idx
        else:
            self.episode_index, start = 0, 0.0
        ep = ch.episodes[self.episode_index]
        self.log_event(f"play channel {ch.number} '{ch.name}' episode {self.episode_index + 1}: {ep.filename} @ {start:.0f}s")
        await self.player.loadfile(ep.path, start=start, pause=False)
        self.state.set_resume_point(ch.folder, ep.filename, start)
        self.state.save()
        if ch.is_music:
            await self._show_music()
        else:
            await self.renderer.hide(PANEL)
        await self.show_banner()

    async def next_episode(self, step: int = 1, from_eof: bool = False) -> None:
        ch = self.channel
        if not ch or ch.is_empty:
            return
        new_index = (self.episode_index + step) % len(ch.episodes)
        await self.play_channel(self.channel_index, episode=new_index, position=0.0)

    async def change_channel(self, step: int) -> None:
        if not self.channels:
            return
        self._update_resume_point()
        await self.play_channel((self.channel_index + step) % len(self.channels), resume=True)

    async def goto_channel(self, number: int) -> None:
        if 1 <= number <= len(self.channels):
            self._update_resume_point()
            await self.play_channel(number - 1, resume=True)

    async def toggle_pause(self) -> None:
        if self.player.idle:
            await self.play_channel(self.channel_index, resume=True)
            return
        await self.player.set_pause(not self.player.paused)
        await asyncio.sleep(0.05)
        await self.show_banner()

    async def change_volume(self, delta: int) -> None:
        vol = int(self.config["volume"]) + delta
        vol = max(0, min(int(self.config["max_volume"]), vol))
        self.config.set("volume", vol)
        if self.muted and delta > 0:
            self.muted = False
            await self.player.set_mute(False)
        await self.player.set_volume(vol)
        await self.show(VOLUME, S.volume_pill(self.ctx(), vol, self.muted, int(self.config["max_volume"])), hide_after=2.5)

    async def toggle_mute(self) -> None:
        self.muted = not self.muted
        await self.player.set_mute(self.muted)
        await self.show(VOLUME, S.volume_pill(self.ctx(), int(self.config["volume"]), self.muted,
                                              int(self.config["max_volume"])), hide_after=2.5)

    def _update_resume_point(self) -> None:
        ch = self.channel
        name = self._current_episode_name()
        if ch and name and not self.player.idle and self.player.current_path:
            pos = self.player.time_pos or 0.0
            dur = self.player.duration
            if dur and pos > dur - 3:
                pos = 0.0  # nearly finished: start over next time
            self.state.set_resume_point(ch.folder, name, pos)

    async def show_banner(self) -> None:
        ch = self.channel
        if not ch or ch.is_empty or self.mode not in (MODE_TV,):
            return
        ep = ch.episodes[self.episode_index]
        remaining = self.state.remaining_today(int(self.config["daily_limit_minutes"]), bool(self.config["daily_limit_enabled"]))
        rem_min = None if remaining is None else int(remaining // 60)
        scene = S.channel_banner(self.ctx(), ch.number, ch.name, ep.title, self.episode_index + 1, len(ch.episodes),
                                 self.player.time_pos, self.player.duration, self.player.paused, rem_min)
        await self.show(BANNER, scene, hide_after=None if self.player.paused else float(self.config["banner_seconds"]))

    async def _show_music(self) -> None:
        ch = self.channel
        if not ch or not ch.is_music or self.mode != MODE_TV:
            return
        ep = ch.episodes[self.episode_index]
        await self.show(PANEL, S.music(self.ctx(), ch.number, ch.name, ep.title, self.episode_index + 1,
                                       len(ch.episodes), self.player.time_pos, self.player.duration))

    def _qr(self, url: str | None):  # type: ignore[no-untyped-def]
        return S.make_qr(url) if url else None

    # ------------------------------------------------------------------
    # mpv events
    # ------------------------------------------------------------------
    async def _player_event(self, msg: dict[str, Any]) -> None:
        event = msg.get("event")
        if event == "end-file":
            reason = msg.get("reason")
            if reason == "eof" and self.mode == MODE_TV:
                await self.next_episode(1, from_eof=True)
            elif reason == "error" and self.mode == MODE_TV:
                self.log_event(f"playback error: {msg.get('file_error')}")
                await self.toast(str(msg.get("file_error") or "error"), T.RED)
                await asyncio.sleep(1)
                if self.channel and len(self.channel.episodes) > 1:
                    await self.next_episode(1)
        elif event == "file-loaded":
            # mpv's option 'start=' handles seeking; refresh the banner once we know the duration.
            await asyncio.sleep(0.3)
            if self.mode == MODE_TV:
                if self.channel and self.channel.is_music:
                    await self._show_music()
                if self.renderer.is_visible(BANNER):
                    await self.show_banner()
        elif event == "kidtv-disconnected":
            self.log_event("mpv died – restarting")
            asyncio.create_task(self._restart_player())

    async def _restart_player(self) -> None:
        await asyncio.sleep(1.0)
        try:
            await self.player.stop()
            await self.player.start()
            self.player.on_event(self._player_event)
            await self.player.set_volume(int(self.config["volume"]))
            await self.renderer.refresh()
            if self.mode == MODE_TV:
                await self.play_channel(self.channel_index, resume=True)
        except Exception:  # noqa: BLE001
            log.exception("mpv restart failed; retrying")
            asyncio.create_task(self._restart_player())

    async def _cec_event(self, kind: str, value: str) -> None:
        if kind == "key":
            await self.handle_action(value, "down")
            await self.handle_action(value, "up")
        elif kind == "tv_standby" and self.mode not in (MODE_STANDBY,):
            await self.enter_standby(from_tv=True)
        elif kind == "tv_on" and self.mode == MODE_STANDBY:
            await self.leave_standby()

    # ------------------------------------------------------------------
    # Periodic work
    # ------------------------------------------------------------------
    async def _ticker(self) -> None:
        last = time.monotonic()
        while True:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            elapsed, last = now - last, now
            try:
                await self._tick(min(elapsed, 5.0))
            except Exception:  # noqa: BLE001
                log.exception("tick failed")

    async def _tick(self, elapsed: float) -> None:
        playing = (self.mode == MODE_TV and not self.player.idle and not self.player.paused
                   and self.channel is not None and not self.channel.is_empty)
        if playing:
            self.state.add_watch_time(elapsed)
            self._update_resume_point()
            remaining = self.state.remaining_today(int(self.config["daily_limit_minutes"]),
                                                  bool(self.config["daily_limit_enabled"]))
            if remaining is not None:
                if remaining <= 0:
                    await self.enter_limit()
                elif remaining <= 300 and not self._limit_warned:
                    self._limit_warned = True
                    await self.toast(self.tr("toast.limit_soon", min=max(1, int(remaining // 60))), T.SKY, 5)
                elif remaining > 300:
                    self._limit_warned = False
        self._save_counter += 1
        if self._save_counter >= 5:
            self._save_counter = 0
            self.state.save()
            if playing and self.channel and self.channel.is_music:
                await self._show_music()

    async def _network_monitor(self) -> None:
        prev: NetStatus | None = None
        while True:
            try:
                status = await self.network.status()
                if prev is not None and (status.connected, status.ssid) != (prev.connected, prev.ssid):
                    if status.connected and self.mode in (MODE_TV, MODE_LIMIT):
                        await self.toast(self.tr("toast.wifi_connected", ssid=status.ssid or self.tr("wifi.ethernet")))
                    elif not status.connected and not status.hotspot and self.mode in (MODE_TV, MODE_LIMIT):
                        await self.toast(self.tr("toast.wifi_lost"), T.ORANGE)
                    self.log_event(f"network: {status.kind} {status.ssid or ''} {status.ip or ''}")
                self.net_status = status
                prev = status
            except Exception:  # noqa: BLE001
                log.exception("network monitor failed")
            await asyncio.sleep(10)

    # ------------------------------------------------------------------
    # Input dispatch
    # ------------------------------------------------------------------
    async def handle_key(self, press: KeyPress) -> None:
        if press.kind == "down":
            self.log_event(f"key {press.keyname} -> {press.action}") if self.dev else None
        if self._web_learn_action and press.kind == "down":
            self.mapper.learn(press.keyname, self._web_learn_action)
            self.config.set("remote_map", dict(self.mapper.overrides))
            self._web_learn_action = None
            await self.toast(self.tr("remote.learn.done"))
            return
        if self.mode == MODE_LEARN:
            await self._learn_key(press)
            return
        if press.action is None:
            return
        await self.handle_action(press.action, press.kind)

    async def handle_action(self, action: str, kind: str = "down") -> None:
        """kind: down | up | repeat | long | up-after-long. Web callers use 'down'+'up'."""
        if action not in ACTIONS:
            return
        # Volume works everywhere and repeats while held.
        if action in ("VOL_UP", "VOL_DOWN") and kind in ("down", "repeat"):
            if self.mode != MODE_STANDBY:
                await self.change_volume(VOLUME_STEP if action == "VOL_UP" else -VOLUME_STEP)
            return
        if action == "MUTE" and kind == "down":
            if self.mode != MODE_STANDBY:
                await self.toggle_mute()
            return
        if action == "MENU" and kind == "long" and self.mode in (MODE_TV, MODE_LIMIT):
            await self.open_menu()
            return
        if action == "POWER" and kind == "down":
            if self.mode == MODE_STANDBY:
                await self.leave_standby()
            else:
                await self.enter_standby()
            return
        if kind not in ("down",):
            return
        handler = {
            MODE_TV: self._key_tv, MODE_STANDBY: self._key_standby, MODE_LIMIT: self._key_limit,
            MODE_MENU: self._key_menu, MODE_KEYBOARD: self._key_keyboard, MODE_WIFI: self._key_wifi,
            MODE_HOTSPOT: self._key_hotspot, MODE_PIN: self._key_pin, MODE_CONFIRM: self._key_confirm,
            MODE_WIZARD: self._key_wizard, MODE_ABOUT: self._key_about,
        }.get(self.mode)
        if handler:
            await handler(action)

    async def _key_tv(self, action: str) -> None:
        if action in ("UP", "CH_UP"):
            await self.change_channel(1)
        elif action in ("DOWN", "CH_DOWN"):
            await self.change_channel(-1)
        elif action in ("RIGHT", "NEXT"):
            await self.next_episode(1)
        elif action in ("LEFT", "PREV"):
            await self.next_episode(-1)
        elif action in ("OK", "PLAY_PAUSE"):
            await self.toggle_pause()
        elif action in ("BACK", "INFO", "HOME", "MENU"):
            if self.renderer.is_visible(BANNER) and not self.player.paused:
                await self.renderer.hide(BANNER)
            else:
                await self.show_banner()
        elif action.startswith("DIGIT_"):
            await self._digit(action[-1])

    async def _digit(self, digit: str) -> None:
        self._digit_buffer = (self._digit_buffer + digit)[-2:]
        if self._digit_task:
            self._digit_task.cancel()
        number = int(self._digit_buffer)
        await self.toast(self.tr("channel.label", n=self._digit_buffer), T.ORANGE, 1.5)
        if number * 10 > len(self.channels) or len(self._digit_buffer) == 2:
            self._digit_buffer = ""
            await self.goto_channel(number)
        else:
            self._digit_task = asyncio.create_task(self._digit_timeout(number))

    async def _digit_timeout(self, number: int) -> None:
        await asyncio.sleep(1.5)
        self._digit_buffer = ""
        await self.goto_channel(number)

    async def _key_standby(self, action: str) -> None:
        if action in ("OK", "PLAY_PAUSE"):
            await self.leave_standby()

    async def _key_limit(self, action: str) -> None:
        if action in ("OK", "BACK", "UP", "DOWN"):
            await self.show(PANEL, S.limit_reached(self.ctx()))

    # ------------------------------------------------------------------
    # Standby / limit
    # ------------------------------------------------------------------
    async def enter_standby(self, from_tv: bool = False) -> None:
        if self.mode == MODE_STANDBY:
            return
        self._update_resume_point()
        self.state.set_standby(True)
        self.state.save(force=True)
        self.mode = MODE_STANDBY
        if not self.player.idle:
            await self.player.set_pause(True)
        await self.renderer.hide(BANNER)
        await self.renderer.hide(VOLUME)
        await self.show(PANEL, S.standby(self.ctx()))
        if self.cec and not from_tv:
            await self.cec.tv_standby()
        self._standby_black_task = asyncio.create_task(self._standby_black())
        self.log_event("standby")

    async def _standby_black(self) -> None:
        await asyncio.sleep(20)
        if self.mode == MODE_STANDBY:
            from PIL import Image
            w, h = self.renderer.size
            await self.renderer.show(PANEL, Image.new("RGBA", (w, h), (0, 0, 0, 255)))

    async def leave_standby(self) -> None:
        if self._standby_black_task:
            self._standby_black_task.cancel()
        self.state.set_standby(False)
        self.mode = MODE_TV
        if self.cec:
            await self.cec.tv_on()
        await self.renderer.hide(PANEL)
        remaining = self.state.remaining_today(int(self.config["daily_limit_minutes"]), bool(self.config["daily_limit_enabled"]))
        if remaining is not None and remaining <= 0:
            await self.enter_limit()
            return
        if self.player.idle:
            await self.play_channel(self.channel_index, resume=True)
        else:
            await self.player.set_pause(False)
            if self.channel and self.channel.is_music:
                await self._show_music()
            await self.show_banner()
        self.log_event("wake up")

    async def enter_limit(self) -> None:
        if self.mode == MODE_LIMIT:
            return
        self._update_resume_point()
        self.state.save(force=True)
        self.mode = MODE_LIMIT
        if not self.player.idle:
            await self.player.set_pause(True)
        await self.renderer.hide(BANNER)
        await self.show(PANEL, S.limit_reached(self.ctx()))
        self.log_event("daily limit reached")

    async def _resume_after_dialog(self) -> None:
        """Return to TV mode (or the limit screen) after a menu/wizard closed."""
        remaining = self.state.remaining_today(int(self.config["daily_limit_minutes"]), bool(self.config["daily_limit_enabled"]))
        if remaining is not None and remaining <= 0:
            self.mode = MODE_LIMIT
            await self.show(PANEL, S.limit_reached(self.ctx()))
            return
        self.mode = MODE_TV
        await self.renderer.hide(PANEL)
        if self.player.idle or self.channel is None or self.channel.is_empty:
            await self.play_channel(self.channel_index, resume=True)
        else:
            if self.player.paused:
                await self.player.set_pause(False)
            if self.channel.is_music:
                await self._show_music()
            await self.show_banner()

    # ------------------------------------------------------------------
    # Settings menu
    # ------------------------------------------------------------------
    async def open_menu(self) -> None:
        self._menu_return = MODE_TV
        if self.config.get("parent_pin"):
            self.mode = MODE_PIN
            self._pin_entered, self._pin_error = "", False
            await self.show(PANEL, S.pin_entry(self.ctx(), 0, False))
            return
        await self._enter_menu()

    async def _enter_menu(self, selected: int = 0) -> None:
        if not self.player.idle and not self.player.paused:
            await self.player.set_pause(True)
        self.mode = MODE_MENU
        self._menu_selected = selected
        await self.renderer.hide(BANNER)
        await self._draw_menu()

    def _menu_definition(self) -> list[S.MenuItem]:
        tr = self.tr
        lang = LANGUAGES.get(self.config["language"], "?")
        limit_on = bool(self.config["daily_limit_enabled"])
        limit_val = tr("menu.daily_limit.value", min=int(self.config["daily_limit_minutes"])) if limit_on else tr("menu.daily_limit.off")
        wifi_val = self.net_status.ssid or (tr("wifi.ethernet") if self.net_status.kind == "ethernet" else "–")
        url = self.web_url() or "–"
        return [
            S.MenuItem("language", tr("menu.language"), lang, has_arrows=True),
            S.MenuItem("child_name", tr("menu.child_name"), self.config["child_name"]),
            S.MenuItem("tv_name", tr("menu.tv_name"), self.config["tv_name"]),
            S.MenuItem("wifi", tr("menu.wifi"), wifi_val),
            S.MenuItem("hotspot", tr("menu.hotspot")),
            S.MenuItem("daily_limit", tr("menu.daily_limit"), limit_val, has_arrows=True),
            S.MenuItem("add_time", tr("menu.add_time")),
            S.MenuItem("reset_today", tr("menu.reset_today")),
            S.MenuItem("max_volume", tr("menu.max_volume"), str(int(self.config["max_volume"])), has_arrows=True),
            S.MenuItem("remote", tr("menu.remote")),
            S.MenuItem("web", tr("menu.web"), url),
            S.MenuItem("rescan", tr("menu.rescan")),
            S.MenuItem("wizard", tr("menu.wizard")),
            S.MenuItem("restart", tr("menu.restart")),
            S.MenuItem("shutdown", tr("menu.shutdown"), danger=True),
            S.MenuItem("about", tr("menu.about"), __version__),
        ]

    async def _draw_menu(self) -> None:
        self._menu_items = self._menu_definition()
        self._menu_selected = max(0, min(self._menu_selected, len(self._menu_items) - 1))
        item = self._menu_items[self._menu_selected]
        hint = self.tr("menu.hint.value") if item.has_arrows else None
        await self.show(PANEL, S.menu(self.ctx(), self.tr("menu.title"), self._menu_items, self._menu_selected, hint))

    async def _key_menu(self, action: str) -> None:
        if action in ("UP", "CH_UP"):
            self._menu_selected = (self._menu_selected - 1) % len(self._menu_items)
            await self._draw_menu()
        elif action in ("DOWN", "CH_DOWN"):
            self._menu_selected = (self._menu_selected + 1) % len(self._menu_items)
            await self._draw_menu()
        elif action in ("LEFT", "RIGHT", "PREV", "NEXT"):
            await self._menu_adjust(self._menu_items[self._menu_selected].key, 1 if action in ("RIGHT", "NEXT") else -1)
        elif action in ("OK", "PLAY_PAUSE"):
            await self._menu_activate(self._menu_items[self._menu_selected].key)
        elif action in ("BACK", "MENU", "HOME"):
            await self.close_menu()

    async def close_menu(self) -> None:
        self.config.save()
        await self._resume_after_dialog()

    async def _menu_adjust(self, key: str, direction: int) -> None:
        if key == "language":
            langs = list(LANGUAGES)
            i = (langs.index(self.config["language"]) + direction) % len(langs)
            self.config.set("language", langs[i])
        elif key == "daily_limit":
            current = int(self.config["daily_limit_minutes"]) if self.config["daily_limit_enabled"] else 0
            steps = LIMIT_STEPS
            nearest = min(range(len(steps)), key=lambda k: abs(steps[k] - current))
            new = steps[max(0, min(len(steps) - 1, nearest + direction))]
            if new == 0:
                self.config.set("daily_limit_enabled", False)
            else:
                self.config.update({"daily_limit_enabled": True, "daily_limit_minutes": new})
        elif key == "max_volume":
            new = max(20, min(130, int(self.config["max_volume"]) + 10 * direction))
            self.config.set("max_volume", new)
            if int(self.config["volume"]) > new:
                self.config.set("volume", new)
                await self.player.set_volume(new)
        else:
            return
        await self._draw_menu()

    async def _menu_activate(self, key: str) -> None:
        tr = self.tr
        if key == "language":
            await self._menu_adjust(key, 1)
        elif key == "child_name":
            await self.text_input(tr("menu.child_name"), self.config["child_name"], self._set_child_name, MODE_MENU)
        elif key == "tv_name":
            await self.text_input(tr("menu.tv_name"), self.config["tv_name"], lambda v: self.config.set("tv_name", v), MODE_MENU)
        elif key == "wifi":
            await self.open_wifi_list(return_mode=MODE_MENU, allow_skip=False)
        elif key == "hotspot":
            await self.start_hotspot_flow(return_mode=MODE_MENU)
        elif key == "daily_limit":
            await self._menu_adjust(key, 1)
        elif key == "add_time":
            self.add_bonus_minutes(30)
            await self.toast(tr("menu.add_time.done"))
        elif key == "reset_today":
            self.state.reset_today()
            self.state.save(force=True)
            await self.toast(tr("menu.reset_today"))
        elif key == "max_volume":
            await self._menu_adjust(key, 1)
        elif key == "remote":
            await self.start_learn(return_mode=MODE_MENU)
        elif key == "web":
            await self.show_about()
        elif key == "rescan":
            self.rescan()
            await self.toast(tr("menu.rescan.done"))
            await self._draw_menu()
        elif key == "wizard":
            await self.start_wizard()
        elif key == "restart":
            await self.confirm(tr("menu.restart") + "?", self.restart_app)
        elif key == "shutdown":
            await self.confirm(tr("menu.shutdown") + "?", self.shutdown_system)
        elif key == "about":
            await self.show_about()

    def _set_child_name(self, value: str) -> None:
        self.config.set("child_name", value)
        if self.cec:
            self.cec.osd_name = self.config["tv_name"][:14]

    async def show_about(self) -> None:
        self.mode = MODE_ABOUT
        tr = self.tr
        url = self.web_url()
        lines = [tr("about.version", version=__version__)]
        if self.net_status.ip:
            lines.append(tr("about.ip", ip=self.net_status.ip))
        if self.net_status.ssid:
            lines.append(tr("wifi.connected", ssid=self.net_status.ssid))
        text = "\n".join(lines) if url else "\n".join(lines + [tr("web.offline")])
        await self.show(PANEL, S.message(self.ctx(), self.config["tv_name"], text, hint=tr("menu.hint.nav"),
                                         accent=T.MINT, url=url, qr=self._qr(url)))

    async def _key_about(self, action: str) -> None:
        if action in ("OK", "BACK", "MENU"):
            await self._enter_menu(self._menu_selected)

    # ------------------------------------------------------------------
    # PIN / confirm
    # ------------------------------------------------------------------
    async def _key_pin(self, action: str) -> None:
        if action.startswith("DIGIT_"):
            self._pin_entered += action[-1]
            self._pin_error = False
            if len(self._pin_entered) >= len(str(self.config["parent_pin"])):
                if self._pin_entered == str(self.config["parent_pin"]):
                    await self._enter_menu()
                    return
                self._pin_entered, self._pin_error = "", True
            await self.show(PANEL, S.pin_entry(self.ctx(), len(self._pin_entered), self._pin_error))
        elif action in ("BACK", "MENU"):
            await self._resume_after_dialog()
        elif action in ("UP", "DOWN", "LEFT", "RIGHT", "OK"):
            # Remotes without digits: arrows spell the PIN (up=1 right=2 down=3 left=4 ok=5).
            digit = {"UP": "1", "RIGHT": "2", "DOWN": "3", "LEFT": "4", "OK": "5"}[action]
            await self._key_pin("DIGIT_" + digit)

    async def confirm(self, question: str, on_yes: Callable[[], Awaitable[None] | None]) -> None:
        self._confirm = {"question": question, "on_yes": on_yes, "selected": 1, "return": self.mode}
        self.mode = MODE_CONFIRM
        await self.show(PANEL, S.confirm(self.ctx(), question, 1))

    async def _key_confirm(self, action: str) -> None:
        if action in ("LEFT", "RIGHT", "UP", "DOWN"):
            self._confirm["selected"] = 1 - self._confirm["selected"]
            await self.show(PANEL, S.confirm(self.ctx(), self._confirm["question"], self._confirm["selected"]))
        elif action == "OK":
            if self._confirm["selected"] == 0:
                result = self._confirm["on_yes"]()
                if asyncio.iscoroutine(result):
                    await result
            else:
                await self._enter_menu(self._menu_selected)
        elif action in ("BACK", "MENU"):
            await self._enter_menu(self._menu_selected)

    # ------------------------------------------------------------------
    # On-screen keyboard
    # ------------------------------------------------------------------
    async def text_input(self, title: str, initial: str, on_done: Callable[[str], Any], return_mode: str,
                         secret: bool = False, on_cancel: Callable[[], Any] | None = None) -> None:
        self._kb = {"title": title, "text": initial, "symbols": False, "shift": False, "cursor": (0, 0),
                    "on_done": on_done, "on_cancel": on_cancel, "return": return_mode, "secret": secret}
        self.mode = MODE_KEYBOARD
        await self._draw_keyboard()

    async def _draw_keyboard(self) -> None:
        kb = self._kb
        await self.show(PANEL, S.keyboard(self.ctx(), kb["title"], kb["text"], kb["symbols"], kb["shift"], kb["cursor"],
                                          secret=kb["secret"]))

    async def _key_keyboard(self, action: str) -> None:
        kb = self._kb
        rows = S.keyboard_layout(kb["symbols"], kb["shift"])
        r, c = kb["cursor"]
        if action in ("UP", "DOWN"):
            r = (r + (1 if action == "DOWN" else -1)) % len(rows)
            # Keep the relative horizontal position when rows differ in length.
            c = min(c, len(rows[r]) - 1)
        elif action in ("LEFT", "RIGHT"):
            c = (c + (1 if action == "RIGHT" else -1)) % len(rows[r])
        elif action == "BACK":
            if kb["text"]:
                kb["text"] = kb["text"][:-1]
            elif kb["on_cancel"]:
                await self._keyboard_finish(cancel=True)
                return
        elif action in ("OK", "PLAY_PAUSE"):
            key = rows[r][c]
            if key == "SHIFT":
                kb["shift"] = not kb["shift"]
            elif key == "SYMBOLS":
                kb["symbols"] = not kb["symbols"]
            elif key == "SPACE":
                kb["text"] += " "
            elif key == "DELETE":
                kb["text"] = kb["text"][:-1]
            elif key == "DONE":
                await self._keyboard_finish(cancel=False)
                return
            elif key == "CANCEL":
                await self._keyboard_finish(cancel=True)
                return
            else:
                kb["text"] += key
                if kb["shift"] and not kb["symbols"]:
                    kb["shift"] = False  # one capital letter at a time
        elif action in ("NEXT", "PREV", "CH_UP", "CH_DOWN"):
            pass
        kb["cursor"] = (r, c)
        await self._draw_keyboard()

    async def _keyboard_finish(self, cancel: bool) -> None:
        kb = self._kb
        if cancel:
            if kb.get("on_cancel"):
                result = kb["on_cancel"]()
                if asyncio.iscoroutine(result):
                    await result
                    return
        else:
            result = kb["on_done"](kb["text"].strip())
            if asyncio.iscoroutine(result):
                await result
                return
        await self._return_to(kb["return"])

    async def _return_to(self, mode: str) -> None:
        if mode == MODE_MENU:
            await self._enter_menu(self._menu_selected)
        elif mode == MODE_WIZARD:
            await self._wizard_next()
        else:
            await self._resume_after_dialog()

    # ------------------------------------------------------------------
    # Wi-Fi list
    # ------------------------------------------------------------------
    async def open_wifi_list(self, return_mode: str, allow_skip: bool) -> None:
        self.mode = MODE_WIFI
        self._wifi = {"return": return_mode, "allow_skip": allow_skip, "networks": [], "selected": 0, "scanning": True}
        await self._draw_wifi()
        networks = await self.network.scan()
        if self.mode != MODE_WIFI:
            return
        self._wifi["networks"] = networks
        self._wifi["scanning"] = False
        await self._draw_wifi()

    def _wifi_items(self) -> list[S.MenuItem]:
        tr = self.tr
        items: list[S.MenuItem] = []
        for n in self._wifi["networks"]:
            label = ("• " if n.in_use else "") + n.ssid
            items.append(S.MenuItem("net:" + n.ssid, label, f"{n.signal} %", meta={"net": n}))
        items.append(S.MenuItem("rescan", tr("wifi.rescan")))
        items.append(S.MenuItem("hotspot", tr("wifi.use_phone")))
        if self._wifi["allow_skip"]:
            items.append(S.MenuItem("skip", tr("wifi.skip")))
        else:
            items.append(S.MenuItem("back", tr("menu.back")))
        return items

    async def _draw_wifi(self) -> None:
        items = self._wifi_items()
        self._wifi["selected"] = max(0, min(self._wifi["selected"], len(items) - 1))
        subtitle = self.tr("wifi.scanning") if self._wifi["scanning"] else (
            self.tr("wifi.connected", ssid=self.net_status.ssid) if self.net_status.ssid else None)
        if not self._wifi["scanning"] and not self._wifi["networks"]:
            subtitle = self.tr("wifi.none")
        await self.show(PANEL, S.menu(self.ctx(), self.tr("wifi.title"), items, self._wifi["selected"], accent=T.SKY,
                                      subtitle=subtitle))

    async def _key_wifi(self, action: str) -> None:
        items = self._wifi_items()
        if action in ("UP", "CH_UP"):
            self._wifi["selected"] = (self._wifi["selected"] - 1) % len(items)
            await self._draw_wifi()
        elif action in ("DOWN", "CH_DOWN"):
            self._wifi["selected"] = (self._wifi["selected"] + 1) % len(items)
            await self._draw_wifi()
        elif action in ("BACK", "MENU"):
            await self._wifi_finish(skipped=True)
        elif action in ("OK", "PLAY_PAUSE"):
            item = items[self._wifi["selected"]]
            if item.key == "rescan":
                await self.open_wifi_list(self._wifi["return"], self._wifi["allow_skip"])
            elif item.key == "hotspot":
                await self.start_hotspot_flow(self._wifi["return"])
            elif item.key in ("skip", "back"):
                await self._wifi_finish(skipped=True)
            elif item.key.startswith("net:"):
                net = item.meta["net"]
                if net.secured:
                    await self.text_input(self.tr("wifi.password", ssid=net.ssid), "",
                                          lambda pw, ssid=net.ssid: self._wifi_connect(ssid, pw), MODE_WIFI, secret=True,
                                          on_cancel=lambda: self.open_wifi_list(self._wifi["return"], self._wifi["allow_skip"]))
                else:
                    await self._wifi_connect(net.ssid, None)

    async def _wifi_connect(self, ssid: str, password: str | None) -> None:
        self.mode = MODE_WIFI
        await self.show(PANEL, S.message(self.ctx(), self.tr("wifi.connecting", ssid=ssid), "", accent=T.SKY))
        ok, _out = await self.network.connect(ssid, password)
        self.net_status = await self.network.status()
        if ok:
            self.log_event(f"wifi connected: {ssid}")
            await self.toast(self.tr("toast.wifi_connected", ssid=ssid))
            await self._wifi_finish(skipped=False)
        else:
            self.log_event(f"wifi failed: {ssid}")
            await self.show(PANEL, S.message(self.ctx(), self.tr("wifi.failed"), "", accent=T.RED))
            await asyncio.sleep(2.5)
            await self.open_wifi_list(self._wifi["return"], self._wifi["allow_skip"])

    async def _wifi_finish(self, skipped: bool) -> None:
        await self._return_to(self._wifi["return"])

    # ------------------------------------------------------------------
    # Hotspot (phone) setup
    # ------------------------------------------------------------------
    async def start_hotspot_flow(self, return_mode: str) -> None:
        self.mode = MODE_HOTSPOT
        self._wifi["return"] = return_mode
        ssid = self.config["hotspot_ssid"] or self.config["tv_name"]
        started = await self.network.start_hotspot(ssid)
        self.net_status = await self.network.status()
        tr = self.tr
        text = "\n".join([tr("hotspot.step1", ssid=ssid), tr("hotspot.step2"), tr("hotspot.step3")])
        if not started:
            text = tr("wifi.failed")
        qr = S.make_qr(f"WIFI:T:nopass;S:{ssid};;")
        await self.show(PANEL, S.wizard_page(self.ctx(), 1, 5, tr("hotspot.title"), text, tr("hotspot.stop"), accent=T.SKY, qr=qr))
        if self._hotspot_task:
            self._hotspot_task.cancel()
        self._hotspot_task = asyncio.create_task(self._hotspot_wait())

    async def _hotspot_wait(self) -> None:
        try:
            while self.mode == MODE_HOTSPOT:
                await asyncio.sleep(3)
                status = await self.network.status()
                self.net_status = status
                if status.connected and not status.hotspot:
                    await self.toast(self.tr("toast.wifi_connected", ssid=status.ssid or ""))
                    await self._return_to(self._wifi.get("return", MODE_TV))
                    return
        except asyncio.CancelledError:
            pass

    async def _key_hotspot(self, action: str) -> None:
        if action in ("OK", "BACK", "MENU"):
            if self._hotspot_task:
                self._hotspot_task.cancel()
            await self.network.stop_hotspot()
            self.net_status = await self.network.status()
            await self._return_to(self._wifi.get("return", MODE_TV))

    # ------------------------------------------------------------------
    # Learn remote
    # ------------------------------------------------------------------
    async def start_learn(self, return_mode: str) -> None:
        self.mode = MODE_LEARN
        self._learn = {"index": 0, "return": return_mode, "hold": None, "pending": {}}
        await self._draw_learn()

    async def _draw_learn(self) -> None:
        i = self._learn["index"]
        action = LEARNABLE[i]
        await self.show(PANEL, S.learn_remote(self.ctx(), self.tr("action." + action), i, len(LEARNABLE)))
        await self.toast(self.tr("remote.learn.skip"), T.LAVENDER, 4)

    async def _learn_key(self, press: KeyPress) -> None:
        if press.kind == "long":
            # Hold any button to skip this action.
            self._learn["index"] += 1
        elif press.kind == "down":
            action = LEARNABLE[self._learn["index"]]
            self._learn["pending"][press.keyname] = action
            self._learn["index"] += 1
        else:
            return
        if self._learn["index"] >= len(LEARNABLE):
            for keyname, action in self._learn["pending"].items():
                self.mapper.learn(keyname, action)
            self.config.set("remote_map", dict(self.mapper.overrides))
            await self.toast(self.tr("remote.learn.done"))
            await self._return_to(self._learn["return"])
            return
        await self._draw_learn()

    # ------------------------------------------------------------------
    # Wizard
    # ------------------------------------------------------------------
    async def start_wizard(self) -> None:
        if not self.player.idle:
            await self.player.set_pause(True)
        self.mode = MODE_WIZARD
        self._wizard_step = 0
        self._wizard_option = list(LANGUAGES).index(self.config["language"]) if self.config["language"] in LANGUAGES else 0
        await self._draw_wizard()

    async def _draw_wizard(self) -> None:
        tr = self.tr
        step = WIZARD_STEPS[self._wizard_step]
        total = len(WIZARD_STEPS)
        c = self.ctx()
        if step == "welcome":
            scene = S.wizard_page(c, 0, total, tr("wizard.welcome.title"), tr("wizard.welcome.text"), tr("wizard.next"))
        elif step == "language":
            scene = S.wizard_page(c, 1, total, tr("wizard.language.title"), "", None, accent=T.MINT,
                                  options=list(LANGUAGES.values()), selected=self._wizard_option)
        elif step == "name":
            scene = S.wizard_page(c, 3, total, tr("wizard.name.title"), tr("wizard.name.text"), tr("wizard.next"), accent=T.PINK)
        elif step == "web":
            url = self.web_url()
            text = tr("wizard.web.text") if url else tr("wizard.web.offline")
            scene = S.wizard_page(c, 4, total, tr("wizard.web.title"), text, tr("wizard.next"), accent=T.MINT, url=url,
                                  qr=self._qr(url))
        elif step == "done":
            scene = S.wizard_page(c, 5, total, tr("wizard.done.title"), tr("wizard.done.text"), tr("wizard.finish"), accent=T.YELLOW)
        else:  # wifi handled by the wifi list
            return
        await self.show(PANEL, scene)

    async def _key_wizard(self, action: str) -> None:
        step = WIZARD_STEPS[self._wizard_step]
        if step == "language":
            if action in ("LEFT", "RIGHT", "UP", "DOWN"):
                self._wizard_option = (self._wizard_option + (1 if action in ("RIGHT", "DOWN") else -1)) % len(LANGUAGES)
                await self._draw_wizard()
                return
            if action == "OK":
                self.config.set("language", list(LANGUAGES)[self._wizard_option])
                await self._wizard_next()
                return
        if action == "OK":
            await self._wizard_next()
        elif action == "BACK" and self._wizard_step > 0:
            self._wizard_step -= 1
            if WIZARD_STEPS[self._wizard_step] == "wifi":
                self._wizard_step -= 1
            await self._draw_wizard()

    async def _wizard_next(self) -> None:
        self.mode = MODE_WIZARD
        self._wizard_step += 1
        if self._wizard_step >= len(WIZARD_STEPS):
            await self._wizard_finish()
            return
        step = WIZARD_STEPS[self._wizard_step]
        if step == "wifi":
            if self.net_status.kind == "ethernet":
                await self._wizard_next()
                return
            await self.open_wifi_list(return_mode=MODE_WIZARD, allow_skip=True)
            return
        if step == "name":
            await self.text_input(self.tr("wizard.name.title"), self.config["child_name"], self._set_child_name, MODE_WIZARD)
            return
        if step == "web":
            self.net_status = await self.network.status()
        await self._draw_wizard()

    async def _wizard_finish(self) -> None:
        self.config.set("setup_done", True)
        self.log_event("wizard finished")
        self.rescan()
        self.mode = MODE_TV
        await self.renderer.hide(PANEL)
        await self.play_channel(self._restore_channel_index(), resume=True)

    # ------------------------------------------------------------------
    # System / web API
    # ------------------------------------------------------------------
    def add_bonus_minutes(self, minutes: int) -> None:
        self.state.add_bonus(minutes * 60)
        self.state.save(force=True)
        self._limit_warned = False

    async def restart_app(self) -> None:
        self.log_event("restart requested")
        await self.stop()
        raise SystemExit(0)

    async def shutdown_system(self) -> None:
        self.log_event("shutdown requested")
        await self.show(PANEL, S.standby(self.ctx()))
        await self.stop()
        if not self.dev and shutil.which("systemctl"):
            await asyncio.create_subprocess_exec("systemctl", "poweroff")
        raise SystemExit(0)

    async def reboot_system(self) -> None:
        self.log_event("reboot requested")
        await self.stop()
        if not self.dev and shutil.which("systemctl"):
            await asyncio.create_subprocess_exec("systemctl", "reboot")
        raise SystemExit(0)

    def reload_avatar(self) -> None:
        self.avatar = T.load_avatar()
        asyncio.create_task(self._redraw_current())
        self.write_splash()

    def write_splash(self) -> None:
        """Save the personalised boot splash used by kidtv-splash.service."""
        try:
            ctx = S.UIContext(self.tr, self.config["child_name"], self.config["tv_name"], self.avatar, 1920, 1080, __version__)
            img, _, _ = S.splash(ctx)
            target = paths.data_dir() / "splash.png"
            tmp = target.with_suffix(".tmp")
            img.convert("RGB").save(tmp, "PNG", optimize=True)
            tmp.replace(target)
        except Exception:  # noqa: BLE001
            log.debug("splash write failed", exc_info=True)

    async def _redraw_current(self) -> None:
        if self.mode == MODE_MENU:
            await self._draw_menu()
        elif self.mode == MODE_STANDBY:
            await self.show(PANEL, S.standby(self.ctx()))
        elif self.mode == MODE_LIMIT:
            await self.show(PANEL, S.limit_reached(self.ctx()))
        elif self.mode == MODE_TV and self.channel and self.channel.is_music:
            await self._show_music()

    def _config_changed(self, key: str, value: Any) -> None:
        if key in ("child_name", "tv_name", "language"):
            if self.cec:
                self.cec.osd_name = self.config["tv_name"][:14]
            asyncio.create_task(self._redraw_current())
            self.write_splash()
        elif key == "volume":
            asyncio.create_task(self.player.set_volume(int(value)))
        elif key == "audio_languages":
            asyncio.create_task(self._set_player_option("alang", ",".join(value)))
        elif key == "subtitles":
            asyncio.create_task(self._set_player_option("sid", "auto" if value else "no"))
        elif key == "remote_map":
            self.mapper.overrides = dict(value)
        elif key == "settings_hold_ms" and self.remote:
            self.remote.set_hold_ms(int(value))
        elif key == "channel_names":
            self.rescan()

    async def _set_player_option(self, name: str, value: Any) -> None:
        try:
            await self.player.set(name, value)
        except Exception:  # noqa: BLE001
            log.debug("could not set %s", name, exc_info=True)

    def learn_next_key(self, action: str | None) -> None:
        self._web_learn_action = action if action in ACTIONS else None

    async def web_play(self, folder: str, filename: str | None = None) -> None:
        for i, ch in enumerate(self.channels):
            if ch.folder == folder:
                if self.mode in (MODE_STANDBY,):
                    await self.leave_standby()
                if self.mode != MODE_TV:
                    return
                idx = ch.index_of(filename) if filename else None
                if idx is None:
                    await self.play_channel(i, resume=filename is None)
                else:
                    await self.play_channel(i, episode=idx, position=0.0)
                return

    def status_dict(self) -> dict[str, Any]:
        ch = self.channel
        ep = None
        if ch and ch.episodes and 0 <= self.episode_index < len(ch.episodes):
            ep = ch.episodes[self.episode_index]
        limit_enabled = bool(self.config["daily_limit_enabled"])
        remaining = self.state.remaining_today(int(self.config["daily_limit_minutes"]), limit_enabled)
        return {
            "mode": self.mode,
            "version": __version__,
            "tv_name": self.config["tv_name"],
            "child_name": self.config["child_name"],
            "channel": None if not ch else {"number": ch.number, "folder": ch.folder, "name": ch.name,
                                            "is_music": ch.is_music, "episodes": len(ch.episodes)},
            "episode": None if not ep else {"filename": ep.filename, "title": ep.title, "index": self.episode_index + 1},
            "position": self.player.time_pos,
            "duration": self.player.duration,
            "paused": self.player.paused,
            "idle": self.player.idle,
            "volume": int(self.config["volume"]),
            "muted": self.muted,
            "watched_seconds": self.state.watched_today(),
            "bonus_seconds": self.state.bonus_today(),
            "limit_enabled": limit_enabled,
            "limit_minutes": int(self.config["daily_limit_minutes"]),
            "remaining_seconds": remaining,
            "network": {"connected": self.net_status.connected, "kind": self.net_status.kind, "ssid": self.net_status.ssid,
                        "ip": self.net_status.ip, "hotspot": self.net_status.hotspot},
            "urls": web_urls(self.net_status),
            "uptime_seconds": int(time.monotonic() - self.started_at),
            "remote_devices": self.remote.devices if self.remote else [],
            "last_key": None if not (self.remote and self.remote.last_key) else {
                "key": self.remote.last_key[0], "device": self.remote.last_key[1],
                "age": round(time.monotonic() - self.remote.last_key[2], 1)},
            "learning": self._web_learn_action,
        }
