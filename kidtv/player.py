"""mpv wrapper: spawns mpv and talks to it over its JSON IPC socket.

mpv draws straight to the screen via DRM (no X11/Wayland needed) and stays
running with an empty playlist between files; all of our UI is drawn as mpv
overlays, so this one process owns the display for the TV's whole lifetime."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Awaitable, Callable

from . import paths

log = logging.getLogger("kidtv.player")

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]

OBSERVED = ["time-pos", "duration", "pause", "path", "idle-active", "volume", "mute", "osd-dimensions", "eof-reached"]


def build_mpv_args(*, socket: Path, volume: int, max_volume: int, audio_languages: list[str],
                   subtitles: bool, dev: bool = False, extra: list[str] | None = None) -> list[str]:
    args = [
        "mpv",
        "--no-config",
        "--idle=yes",
        "--force-window=yes",
        "--keep-open=no",
        f"--input-ipc-server={socket}",
        "--no-input-default-bindings",
        "--input-vo-keyboard=no",
        "--no-input-cursor",
        "--cursor-autohide=always",
        "--osd-level=0",
        "--no-osc",
        "--no-terminal",
        "--really-quiet",
        "--msg-level=all=warn",
        f"--volume={volume}",
        f"--volume-max={max(100, max_volume)}",
        "--alang=" + ",".join(audio_languages),
        "--sid=" + ("auto" if subtitles else "no"),
        "--audio-display=embedded-first",
        "--image-display-duration=inf",
        "--cache=yes",
        "--demuxer-max-bytes=64MiB",
        "--demuxer-max-back-bytes=16MiB",
        "--hr-seek=yes",
        "--video-unscaled=no",
        "--keepaspect=yes",
    ]
    if dev:
        args += ["--vo=null", "--ao=null"]
    else:
        args += [
            "--vo=gpu",
            "--gpu-context=drm",
            "--drm-mode=preferred",
            "--hwdec=auto-copy",
            "--ao=alsa",
            "--audio-channels=stereo",
            "--fullscreen",
        ]
        conf = Path("/etc/kidtv/mpv.conf")
        if conf.exists():
            args.append(f"--include={conf}")
    if extra:
        args += extra
    return args


class Player:
    def __init__(self, args: list[str], socket: Path | None = None) -> None:
        self.args = args
        self.socket_path = socket or paths.mpv_socket()
        self.proc: asyncio.subprocess.Process | None = None
        self.reader: asyncio.StreamReader | None = None
        self.writer: asyncio.StreamWriter | None = None
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: asyncio.Task | None = None
        self._handlers: list[EventHandler] = []
        self.props: dict[str, Any] = {}
        self.alive = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------
    async def start(self, timeout: float = 15.0) -> None:
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        log.info("starting mpv: %s", " ".join(self.args))
        self.proc = await asyncio.create_subprocess_exec(
            *self.args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        deadline = asyncio.get_event_loop().time() + timeout
        while True:
            if self.proc.returncode is not None:
                raise RuntimeError(f"mpv exited early with code {self.proc.returncode}")
            if self.socket_path.exists():
                try:
                    self.reader, self.writer = await asyncio.open_unix_connection(str(self.socket_path))
                    break
                except OSError:
                    pass
            if asyncio.get_event_loop().time() > deadline:
                raise RuntimeError("mpv IPC socket did not appear")
            await asyncio.sleep(0.1)
        self._reader_task = asyncio.create_task(self._read_loop(), name="mpv-reader")
        for i, prop in enumerate(OBSERVED, start=1):
            await self.command("observe_property", i, prop)
        self.alive.set()
        log.info("mpv connected")

    async def stop(self) -> None:
        self.alive.clear()
        try:
            if self.writer:
                await self.command("quit", timeout=2)
        except Exception:
            pass
        if self._reader_task:
            self._reader_task.cancel()
        if self.writer:
            self.writer.close()
        if self.proc and self.proc.returncode is None:
            try:
                await asyncio.wait_for(self.proc.wait(), 3)
            except asyncio.TimeoutError:
                self.proc.kill()
        self.proc = None
        self.reader = self.writer = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None and self.alive.is_set()

    async def wait_exit(self) -> int | None:
        if self.proc is None:
            return None
        return await self.proc.wait()

    # -- IPC ---------------------------------------------------------------
    async def _read_loop(self) -> None:
        assert self.reader is not None
        try:
            while True:
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if "request_id" in msg:
                    fut = self._pending.pop(msg["request_id"], None)
                    if fut and not fut.done():
                        if msg.get("error", "success") == "success":
                            fut.set_result(msg.get("data"))
                        else:
                            fut.set_exception(RuntimeError(msg.get("error")))
                    continue
                event = msg.get("event")
                if event == "property-change":
                    self.props[msg.get("name")] = msg.get("data")
                for handler in list(self._handlers):
                    try:
                        result = handler(msg)
                        if asyncio.iscoroutine(result):
                            asyncio.create_task(result)
                    except Exception:  # noqa: BLE001
                        log.exception("event handler failed")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("mpv reader loop died")
        finally:
            self.alive.clear()
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("mpv connection closed"))
                    fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # mark retrieved
            self._pending.clear()
            for handler in list(self._handlers):
                try:
                    result = handler({"event": "kidtv-disconnected"})
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception:  # noqa: BLE001
                    pass

    def on_event(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    async def command(self, *cmd: Any, timeout: float = 5.0) -> Any:
        return await self._send(list(cmd), timeout)

    async def named_command(self, name: str, timeout: float = 5.0, **args: Any) -> Any:
        """Command with named arguments – immune to mpv inserting new positional
        arguments between releases (0.38 added `index` before loadfile's `options`)."""
        return await self._send({"name": name, **args}, timeout)

    async def _send(self, cmd: list[Any] | dict[str, Any], timeout: float) -> Any:
        if not self.writer:
            raise ConnectionError("mpv not connected")
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        payload = json.dumps({"command": cmd, "request_id": rid, "async": True}) + "\n"
        self.writer.write(payload.encode("utf-8"))
        await self.writer.drain()
        return await asyncio.wait_for(fut, timeout)

    async def get(self, prop: str, default: Any = None) -> Any:
        try:
            return await self.command("get_property", prop)
        except Exception:  # noqa: BLE001
            return default

    async def set(self, prop: str, value: Any) -> None:
        await self.command("set_property", prop, value)

    # -- playback helpers --------------------------------------------------
    async def loadfile(self, path: Path | str, start: float = 0.0, pause: bool = False) -> None:
        opts = f"start={max(0.0, start):.1f},pause={'yes' if pause else 'no'}"
        await self.named_command("loadfile", url=str(path), flags="replace", options=opts)

    async def stop_playback(self) -> None:
        await self.command("stop")

    async def set_pause(self, paused: bool) -> None:
        await self.set("pause", paused)

    async def set_volume(self, volume: int) -> None:
        await self.set("volume", int(volume))

    async def set_mute(self, muted: bool) -> None:
        await self.set("mute", muted)

    async def seek(self, seconds: float, mode: str = "relative") -> None:
        await self.command("seek", seconds, mode)

    @property
    def time_pos(self) -> float | None:
        v = self.props.get("time-pos")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def duration(self) -> float | None:
        v = self.props.get("duration")
        return float(v) if isinstance(v, (int, float)) else None

    @property
    def paused(self) -> bool:
        return bool(self.props.get("pause"))

    @property
    def idle(self) -> bool:
        return bool(self.props.get("idle-active", True))

    @property
    def current_path(self) -> str | None:
        p = self.props.get("path")
        return str(p) if p else None

    @property
    def osd_size(self) -> tuple[int, int]:
        d = self.props.get("osd-dimensions") or {}
        w, h = int(d.get("w") or 0), int(d.get("h") or 0)
        return (w, h) if w and h else (1920, 1080)

    # -- overlays ------------------------------------------------------------
    async def overlay_add(self, oid: int, x: int, y: int, file: Path, w: int, h: int) -> None:
        await self.command("overlay-add", oid, int(x), int(y), str(file), 0, "bgra", int(w), int(h), int(w) * 4)

    async def overlay_remove(self, oid: int) -> None:
        try:
            await self.command("overlay-remove", oid)
        except Exception:  # noqa: BLE001
            pass


def mpv_available() -> bool:
    for d in os.environ.get("PATH", "").split(os.pathsep):
        if (Path(d) / "mpv").exists():
            return True
    return False
