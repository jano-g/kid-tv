"""aiohttp web UI. Plain HTML + a little vanilla JS, no build step.

Runs inside the same process as the TV so it can talk to the controller
directly. Also serves as the captive portal when the phone-setup hotspot is on."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import jinja2
from aiohttp import web

from .. import __version__, paths
from ..i18n import LANGUAGES, Translator
from ..ui.screens import BACKGROUNDS
from ..library import next_channel_folder_name, safe_filename, scan_library, PLAYABLE_EXT
from ..remote import ACTIONS, LEARNABLE, DEFAULT_MAP
from ..util import format_clock

log = logging.getLogger("kidtv.web")

TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"
CAPTIVE_HOSTS = ("kid.tv", "10.42.0.1", "127.0.0.1", "localhost")
PROBE_PATHS = {"/generate_204", "/gen_204", "/hotspot-detect.html", "/library/test/success.html",
               "/connecttest.txt", "/ncsi.txt", "/success.txt", "/canonical.html", "/redirect", "/check_network_status.txt"}


def human_size(n: float) -> str:
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "kB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def make_app(tv) -> web.Application:  # type: ignore[no-untyped-def]
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app["tv"] = tv  # noqa: string keys keep the templates simple
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(TEMPLATES)), autoescape=True,
                             trim_blocks=True, lstrip_blocks=True)
    env.filters["clock"] = format_clock
    env.filters["size"] = human_size
    app["jinja"] = env
    app.middlewares.append(captive_middleware)
    app.add_routes([
        web.get("/", home),
        web.get("/channels", channels_page),
        web.post("/channels", channel_create),
        web.post("/channels/{folder}/rename", channel_rename),
        web.post("/channels/{folder}/delete", channel_delete),
        web.post("/channels/{folder}/upload", channel_upload),
        web.post("/channels/{folder}/play", channel_play),
        web.post("/channels/{folder}/files/delete", file_delete),
        web.post("/channels/{folder}/files/rename", file_rename),
        web.get("/settings", settings_page),
        web.post("/settings", settings_save),
        web.post("/settings/avatar", avatar_upload),
        web.post("/settings/avatar/delete", avatar_delete),
        web.get("/avatar.png", avatar_image),
        web.get("/wifi", wifi_page),
        web.get("/setup", wifi_page),
        web.get("/api/wifi/scan", wifi_scan),
        web.post("/wifi/connect", wifi_connect),
        web.post("/wifi/forget", wifi_forget),
        web.post("/wifi/hotspot", wifi_hotspot),
        web.get("/remote", remote_page),
        web.post("/remote/learn", remote_learn),
        web.post("/remote/reset", remote_reset),
        web.get("/system", system_page),
        web.post("/system/update/check", update_check),
        web.post("/system/update/install", update_install),
        web.post("/system/update/rollback", update_rollback),
        web.post("/system/{action}", system_action),
        web.get("/api/status", api_status),
        web.post("/api/control", api_control),
        web.static("/static/fonts", str(paths.FONTS_DIR)),
        web.static("/static/bg", str(paths.BACKGROUNDS_DIR)),
        web.static("/static", str(STATIC), append_version=True),
    ])
    return app


async def start_web(app: web.Application, port: int) -> web.AppRunner:
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port, reuse_address=True)
    await site.start()
    return runner


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _tr(request: web.Request) -> Translator:
    lang = request.query.get("lang") or request.cookies.get("lang") or request.app["tv"].config["language"]
    return Translator(lang)


def render(request: web.Request, template: str, **ctx: Any) -> web.Response:
    tv = request.app["tv"]
    tr = _tr(request)
    status = tv.status_dict()
    html = request.app["jinja"].get_template(template).render(
        tr=tr, lang=tr.lang, languages=LANGUAGES, tv=status, cfg=tv.config.as_public_dict(), version=__version__,
        has_avatar=paths.avatar_file().exists(), page=template.split(".")[0], flash=request.query.get("ok"),
        error=request.query.get("error"), backgrounds=BACKGROUNDS, **ctx)
    resp = web.Response(text=html, content_type="text/html")
    if "lang" in request.query and request.query["lang"] in LANGUAGES:
        resp.set_cookie("lang", request.query["lang"], max_age=365 * 86400)
    return resp


def redirect(path: str, ok: str | None = None, error: str | None = None) -> web.HTTPFound:
    path, _, fragment = path.partition("#")
    params = {k: v for k, v in (("ok", ok), ("error", error)) if v}
    return web.HTTPFound(path + ("?" + urlencode(params) if params else "") + ("#" + fragment if fragment else ""))


def _channel_dir(request: web.Request) -> Path:
    tv = request.app["tv"]
    folder = safe_filename(request.match_info["folder"])
    path = (tv.media_dir / folder)
    if not folder or not path.is_dir() or path.parent != tv.media_dir:
        raise web.HTTPNotFound(text="channel not found")
    return path


def _disk(path: Path) -> tuple[int, int]:
    try:
        usage = shutil.disk_usage(path)
        return usage.free, usage.total
    except OSError:
        return 0, 0


@web.middleware
async def captive_middleware(request: web.Request, handler):  # type: ignore[no-untyped-def]
    """While the hotspot is on, any foreign host (captive-portal probes) is sent to the Wi-Fi page."""
    tv = request.app["tv"]
    host = request.host.split(":")[0]
    if tv.network.hotspot_active and request.path in PROBE_PATHS:
        raise web.HTTPFound("http://kid.tv/setup")
    if tv.network.hotspot_active and host not in CAPTIVE_HOSTS and not host.startswith("10.42.0."):
        raise web.HTTPFound("http://kid.tv/setup")
    return await handler(request)


# ----------------------------------------------------------------------
# pages
# ----------------------------------------------------------------------

async def home(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    channels = scan_library(tv.media_dir, tv.config.get("channel_names") or {})
    return render(request, "home.html", channels=channels)


async def channels_page(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    channels = scan_library(tv.media_dir, tv.config.get("channel_names") or {})
    free, total = _disk(tv.media_dir)
    sizes = {}
    for ch in channels:
        for ep in ch.episodes:
            try:
                sizes[str(ep.path)] = ep.path.stat().st_size
            except OSError:
                sizes[str(ep.path)] = 0
    return render(request, "channels.html", channels=channels, free=free, total=total, sizes=sizes,
                  open_folder=request.query.get("open"), extensions=", ".join(sorted(e[1:] for e in PLAYABLE_EXT)))


async def channel_create(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    form = await request.post()
    name = str(form.get("name", "")).strip()
    folder = next_channel_folder_name(tv.media_dir)
    (tv.media_dir / folder).mkdir(parents=True, exist_ok=True)
    if name:
        tv.config.set_channel_name(folder, name)
    await tv.media_changed()
    raise redirect("/channels", ok=folder)


async def channel_rename(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    path = _channel_dir(request)
    form = await request.post()
    tv.config.set_channel_name(path.name, str(form.get("name", "")))
    tv.rescan()
    raise redirect("/channels")


async def channel_delete(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    path = _channel_dir(request)
    shutil.rmtree(path, ignore_errors=True)
    tv.config.set_channel_name(path.name, "")
    tv.state.forget_channel(path.name)
    await tv.media_changed()
    raise redirect("/channels")


async def channel_play(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    path = _channel_dir(request)
    form = await request.post()
    await tv.web_play(path.name, str(form.get("file") or "") or None)
    raise redirect("/")


async def channel_upload(request: web.Request) -> web.Response:
    """Streaming multipart upload – files may be several GB."""
    tv = request.app["tv"]
    path = _channel_dir(request)
    reader = await request.multipart()
    saved: list[str] = []
    while True:
        field = await reader.next()
        if field is None:
            break
        if field.name != "file" or not field.filename:
            continue
        name = safe_filename(field.filename)
        if Path(name).suffix.lower() not in PLAYABLE_EXT:
            log.warning("upload rejected (unsupported extension): %s", name)
            continue
        target = path / name
        tmp = path / f".{name}.part"
        try:
            with open(tmp, "wb") as fh:
                while True:
                    chunk = await field.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, target)
            saved.append(name)
        except Exception:  # noqa: BLE001
            log.exception("upload failed for %s", name)
            try:
                tmp.unlink()
            except OSError:
                pass
            return web.json_response({"ok": False, "error": "write failed"}, status=500)
    if saved:
        tv.log_event(f"uploaded to {path.name}: {', '.join(saved)}")
        try:
            await tv.media_changed()
        except Exception:  # noqa: BLE001
            # The file is safely on disk; a playback hiccup must not report the upload as failed.
            log.exception("refresh after upload failed")
    return web.json_response({"ok": True, "saved": saved})


async def file_delete(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    path = _channel_dir(request)
    form = await request.post()
    name = safe_filename(str(form.get("file", "")))
    target = path / name
    if target.is_file():
        target.unlink()
        await tv.media_changed()
    raise redirect(f"/channels?open={path.name}")


async def file_rename(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    path = _channel_dir(request)
    form = await request.post()
    old = safe_filename(str(form.get("file", "")))
    new = safe_filename(str(form.get("name", "")))
    src, dst = path / old, path / new
    if src.is_file() and new and not dst.exists():
        if Path(new).suffix.lower() not in PLAYABLE_EXT:
            dst = dst.with_suffix(src.suffix)
        src.rename(dst)
        file, pos = tv.state.resume_point(path.name)
        if file == old:
            tv.state.set_resume_point(path.name, dst.name, pos)
        await tv.media_changed()
    raise redirect(f"/channels?open={path.name}")


async def settings_page(request: web.Request) -> web.Response:
    return render(request, "settings.html")


async def settings_save(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    form = await request.post()
    values: dict[str, Any] = {}
    values["child_name"] = str(form.get("child_name", "")).strip() or tv.config["child_name"]
    values["tv_name"] = str(form.get("tv_name", "")).strip()
    lang = str(form.get("language", "sk"))
    values["language"] = lang if lang in LANGUAGES else "sk"
    values["daily_limit_enabled"] = form.get("daily_limit_enabled") == "on"
    try:
        values["daily_limit_minutes"] = max(5, min(600, int(form.get("daily_limit_minutes", 60))))
    except ValueError:
        pass
    try:
        values["max_volume"] = max(20, min(130, int(form.get("max_volume", 100))))
    except ValueError:
        pass
    langs = [p.strip().lower() for p in str(form.get("audio_languages", "")).replace(";", ",").split(",") if p.strip()]
    if langs:
        values["audio_languages"] = langs
    values["subtitles"] = form.get("subtitles") == "on"
    values["status_line"] = form.get("status_line") == "on"
    bg = str(form.get("background", ""))
    values["background"] = bg if bg in BACKGROUNDS else ""
    pin = "".join(ch for ch in str(form.get("parent_pin", "")) if ch.isdigit())
    if form.get("parent_pin_clear") == "on":
        values["parent_pin"] = ""
    elif pin:
        values["parent_pin"] = pin[:8]
    values["update_auto_check"] = form.get("update_auto_check") == "on"
    hotspot = str(form.get("hotspot_ssid", "")).strip()
    if hotspot:
        values["hotspot_ssid"] = hotspot[:32]
    tv.config.update(values)
    tv.log_event("settings saved from web")
    tr = _tr(request)
    raise redirect("/settings", ok=tr("web.settings.saved"))


async def avatar_upload(request: web.Request) -> web.Response:
    from PIL import Image, ImageOps

    tv = request.app["tv"]
    reader = await request.multipart()
    field = await reader.next()
    while field is not None and field.name != "avatar":
        field = await reader.next()
    if field is None:
        raise redirect("/settings", error="no file")
    data = io.BytesIO()
    size = 0
    while True:
        chunk = await field.read_chunk(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > 40 * 1024 * 1024:
            raise redirect("/settings", error="file too large")
        data.write(chunk)
    try:
        img = Image.open(data)
        img = ImageOps.exif_transpose(img).convert("RGBA")
        w, h = img.size
        side = min(w, h)
        img = img.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
        img = img.resize((512, 512), Image.LANCZOS)
        tmp = paths.avatar_file().with_suffix(".tmp")
        img.save(tmp, "PNG")
        os.replace(tmp, paths.avatar_file())
    except Exception:  # noqa: BLE001
        log.exception("avatar upload failed")
        raise redirect("/settings", error="bad image")
    tv.reload_avatar()
    tv.log_event("avatar updated")
    raise redirect("/settings", ok="avatar")


async def avatar_delete(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    try:
        paths.avatar_file().unlink()
    except FileNotFoundError:
        pass
    tv.reload_avatar()
    raise redirect("/settings")


async def avatar_image(request: web.Request) -> web.Response:
    file = paths.avatar_file()
    if not file.exists():
        raise web.HTTPNotFound()
    return web.FileResponse(file, headers={"Cache-Control": "no-cache"})


async def wifi_page(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    saved = await tv.network.saved_networks()
    status = await tv.network.status()
    tv.net_status = status
    return render(request, "wifi.html", saved=saved, net=status, setup=request.path == "/setup")


async def wifi_scan(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    nets = await tv.network.scan(rescan=request.query.get("rescan", "1") == "1")
    return web.json_response([{"ssid": n.ssid, "signal": n.signal, "secured": n.secured, "in_use": n.in_use} for n in nets])


async def wifi_connect(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    form = await request.post()
    ssid = str(form.get("ssid", "")).strip()
    password = str(form.get("password", "")) or None
    hidden = form.get("hidden") == "on"
    if not ssid:
        raise redirect("/wifi", error="ssid")
    tv.log_event(f"wifi connect requested from web: {ssid}")
    # Respond first – on the hotspot the client loses us the moment we switch networks.
    asyncio.create_task(tv.network.connect(ssid, password, hidden))
    tr = _tr(request)
    return render(request, "message.html", title=tr("wifi.connecting", ssid=ssid), text=tr("web.wifi.connecting"))


async def wifi_forget(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    form = await request.post()
    await tv.network.forget(str(form.get("name", "")))
    raise redirect("/wifi")


async def wifi_hotspot(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    form = await request.post()
    if form.get("state") == "on":
        await tv.start_hotspot_flow(return_mode="tv")
    else:
        await tv.handle_action("BACK")
    raise redirect("/wifi")


async def remote_page(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    mapping = {a: tv.mapper.mapping_for_action(a) for a in ACTIONS}
    return render(request, "remote.html", actions=ACTIONS, learnable=LEARNABLE, mapping=mapping,
                  overrides=tv.mapper.overrides, defaults=DEFAULT_MAP)


async def remote_learn(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    data = await request.json()
    action = data.get("action")
    tv.learn_next_key(action if action else None)
    return web.json_response({"ok": True, "learning": tv._web_learn_action})


async def remote_reset(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    tv.mapper.overrides = {}
    tv.config.set("remote_map", {})
    raise redirect("/remote")


async def system_page(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    free, total = _disk(tv.media_dir)
    return render(request, "system.html", free=free, total=total, log_lines=list(reversed(tv.log_lines)),
                  hostname=os.uname().nodename, update_log=tv.updater.log_tail(40))


async def update_check(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    text, ok = await tv.check_updates()
    raise redirect("/system#update", ok=text if ok else None, error=None if ok else text)


def _updating_page(request: web.Request, version: str | None) -> web.Response:
    tr = _tr(request)
    return render(request, "updating.html", target=version or "", start_version=__version__,
                  title=tr("update.installing.title"), text=tr("web.update.progress"))


async def update_install(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    latest = tv.updater.latest
    if not tv.updater.available or latest is None:
        raise redirect("/system#update", error=_tr(request)("update.none", version=__version__))
    asyncio.create_task(tv.start_update())
    return _updating_page(request, latest.version)


async def update_rollback(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    version = tv.updater.previous_version()
    if not version:
        raise redirect("/system#update")
    asyncio.create_task(tv.start_update(rollback=True))
    return _updating_page(request, version)


async def system_action(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    action = request.match_info["action"]
    if action == "add_time":
        tv.add_bonus_minutes(30)
        if tv.mode == "limit":
            await tv._resume_after_dialog()
    elif action == "reset_today":
        tv.state.reset_today()
        tv.state.save(force=True)
        if tv.mode == "limit":
            await tv._resume_after_dialog()
    elif action == "rescan":
        await tv.media_changed()
    elif action == "wizard":
        await tv.start_wizard()
    elif action == "restart":
        asyncio.get_running_loop().call_later(0.5, lambda: asyncio.create_task(tv.restart_app()))
    elif action == "reboot":
        asyncio.get_running_loop().call_later(0.5, lambda: asyncio.create_task(tv.reboot_system()))
    elif action == "shutdown":
        asyncio.get_running_loop().call_later(0.5, lambda: asyncio.create_task(tv.shutdown_system()))
    else:
        raise web.HTTPNotFound()
    raise redirect("/system", ok=action)


async def api_status(request: web.Request) -> web.Response:
    return web.json_response(request.app["tv"].status_dict())


async def api_control(request: web.Request) -> web.Response:
    tv = request.app["tv"]
    data = await request.json()
    action = str(data.get("action", "")).upper()
    kind = str(data.get("kind", "press"))
    if action not in ACTIONS:
        return web.json_response({"ok": False, "error": "unknown action"}, status=400)
    if kind == "long":
        await tv.handle_action(action, "long")
    else:
        await tv.handle_action(action, "down")
        await tv.handle_action(action, "up")
    return web.json_response({"ok": True, "status": tv.status_dict()})
