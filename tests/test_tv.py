"""End-to-end test of the controller and the web UI with a real (headless) mpv."""

import asyncio
import os
import shutil
from pathlib import Path

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from kidtv import paths
from kidtv.config import Config
from kidtv.controller import TV, MODE_TV, MODE_STANDBY, MODE_MENU, MODE_LIMIT, MODE_WIZARD, MODE_KEYBOARD, MODE_WIFI
from kidtv.net import NetStatus, WifiNetwork
from kidtv.player import Player, build_mpv_args
from kidtv.state import State
from kidtv.web.app import make_app

MEDIA = Path(__file__).parent / "media"
pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")


class FakeNetwork:
    hotspot_active = False

    def __init__(self):
        self._status = NetStatus(True, "wifi", "Doma", "192.168.1.20", False)
        self.connect_calls = []

    async def status(self):
        return self._status

    async def scan(self, rescan=True):
        return [WifiNetwork("Doma", 80, True, True), WifiNetwork("Otvorena", 40, False)]

    async def connect(self, ssid, password, hidden=False):
        self.connect_calls.append((ssid, password))
        return True, "successfully activated"

    async def saved_networks(self):
        return ["Doma"]

    async def forget(self, name):
        pass

    async def start_hotspot(self, ssid):
        self.hotspot_active = True
        return True

    async def stop_hotspot(self):
        self.hotspot_active = False


def setup_dirs(tmp_path: Path, setup_done: bool = True) -> Path:
    data = tmp_path / "data"
    media = data / "media"
    for ch in ("kanal1", "kanal2", "kanal3"):
        (media / ch).mkdir(parents=True)
    shutil.copy(MEDIA / "clip1.mp4", media / "kanal1" / "01 Prvá.mp4")
    shutil.copy(MEDIA / "clip2.mp4", media / "kanal1" / "02 Druhá.mp4")
    shutil.copy(MEDIA / "song.mp3", media / "kanal3" / "Pesnička.mp3")
    os.environ["KIDTV_DATA_DIR"] = str(data)
    os.environ["KIDTV_MEDIA_DIR"] = str(media)
    os.environ["KIDTV_RUNTIME_DIR"] = str(data / "run")
    paths.ensure_dirs()
    cfg = Config()
    cfg.update({"setup_done": setup_done, "banner_seconds": 1, "child_name": "Adam"})
    return data


class NewerMpvPlayer(Player):
    """Behaves like mpv 0.38+ (Raspberry Pi OS Trixie ships 0.40): loadfile's third
    positional argument became an insertion index, so options passed there are
    rejected with 'invalid parameter'."""

    async def _send(self, cmd, timeout):
        if isinstance(cmd, list) and cmd[:1] == ["loadfile"] and len(cmd) > 3:
            raise RuntimeError("invalid parameter")
        return await super()._send(cmd, timeout)


async def make_tv(data: Path, player_cls=Player) -> TV:
    cfg = Config()
    args = build_mpv_args(socket=paths.mpv_socket(), volume=cfg["volume"], max_volume=cfg["max_volume"],
                          audio_languages=cfg["audio_languages"], subtitles=False, dev=True)
    player = player_cls(args, socket=paths.mpv_socket())
    tv = TV(cfg, State(), player, FakeNetwork(), paths.media_dir(), dev=True)
    await tv.start()
    return tv


async def wait_for(pred, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if pred():
            return True
        await asyncio.sleep(0.05)
    return pred()


async def press(tv: TV, action: str, kind: str = "press"):
    if kind == "long":
        await tv.handle_action(action, "long")
    else:
        await tv.handle_action(action, "down")
        await tv.handle_action(action, "up")
    await asyncio.sleep(0.1)


def test_tv_playback_channels_resume_and_standby(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        try:
            assert tv.mode == MODE_TV
            assert tv.channel.folder == "kanal1"
            assert await wait_for(lambda: tv.player.time_pos is not None and tv.player.time_pos > 0.3)
            # Next episode, then back.
            await press(tv, "RIGHT")
            assert tv.episode_index == 1
            await press(tv, "LEFT")
            assert tv.episode_index == 0
            # Pause / resume.
            await press(tv, "OK")
            assert await wait_for(lambda: tv.player.paused)
            await press(tv, "OK")
            assert await wait_for(lambda: not tv.player.paused)
            # Volume.
            await tv.handle_action("VOL_UP", "down")
            assert tv.config["volume"] == 65
            await tv.handle_action("MUTE", "down")
            assert tv.muted
            await tv.handle_action("MUTE", "down")
            # Channel 2 is empty -> message screen, no playback.
            await press(tv, "UP")
            assert tv.channel.folder == "kanal2"
            assert await wait_for(lambda: tv.player.idle)
            assert tv.renderer.is_visible(1)
            # Channel 3 is music.
            await press(tv, "UP")
            assert tv.channel.folder == "kanal3" and tv.channel.is_music
            assert await wait_for(lambda: not tv.player.idle)
            # Wrap around back to channel 1 and resume where we were.
            await press(tv, "UP")
            assert tv.channel.folder == "kanal1"
            assert await wait_for(lambda: tv.player.time_pos is not None and tv.player.time_pos > 0.2)
            # Digit direct channel.
            await press(tv, "DIGIT_3")
            assert tv.channel.folder == "kanal3"
            # Standby and wake.
            await press(tv, "POWER")
            assert tv.mode == MODE_STANDBY and tv.state.standby
            assert await wait_for(lambda: tv.player.paused)
            await press(tv, "POWER")
            assert tv.mode == MODE_TV
            assert await wait_for(lambda: not tv.player.paused)
            # Resume state is persisted.
            tv._update_resume_point()
            tv.state.save(force=True)
            st = State()
            assert st.current_channel == "kanal3"
            f, pos = st.resume_point("kanal1")
            assert f == "01 Prvá.mp4"
        finally:
            await tv.stop()

    asyncio.run(run())


def test_eof_advances_and_loops(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        try:
            # Jump near the end of episode 1; mpv reaches EOF and we advance to 2.
            assert await wait_for(lambda: tv.player.time_pos is not None and tv.player.time_pos > 0.2)
            await tv.player.seek(2.7, "absolute")
            assert await wait_for(lambda: tv.episode_index == 1, timeout=8)
            assert await wait_for(lambda: tv.player.time_pos is not None and 0.1 < tv.player.time_pos < 2.0)
            await tv.player.seek(2.7, "absolute")
            assert await wait_for(lambda: tv.episode_index == 0 and tv.player.time_pos is not None and tv.player.time_pos < 2.0, timeout=8)
        finally:
            await tv.stop()

    asyncio.run(run())


def test_menu_keyboard_and_daily_limit(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        try:
            await press(tv, "MENU", "long")
            assert tv.mode == MODE_MENU and tv.player.paused
            # The menu opens on "Back to the cartoon": OK alone leaves it.
            assert tv._menu_items[tv._menu_selected].key == "close"
            await press(tv, "OK")
            assert tv.mode == MODE_TV and await wait_for(lambda: not tv.player.paused)
            await press(tv, "MENU", "long")
            await press(tv, "DOWN")
            # Language row: RIGHT switches to English.
            await press(tv, "RIGHT")
            assert tv.config["language"] == "en" and tv.config["tv_name"] == "Adam's TV"
            await press(tv, "LEFT")
            assert tv.config["language"] == "sk"
            # Child name via on-screen keyboard.
            await press(tv, "DOWN")
            await press(tv, "OK")
            assert tv.mode == MODE_KEYBOARD
            # Type "a": row 1 col 0 is 'a' – move DOWN once from (0,0) then OK.
            await press(tv, "BACK")  # delete last char of 'Adam'
            await press(tv, "DOWN")
            await press(tv, "OK")
            assert tv._kb["text"] == "Adaa"
            # Go to DONE: last row, index 4.
            for _ in range(4):
                await press(tv, "DOWN")
            assert tv._kb["cursor"][0] == 5
            for _ in range(4):
                await press(tv, "RIGHT")
            await press(tv, "OK")
            assert tv.mode == MODE_MENU
            assert tv.config["child_name"] == "Adaa"
            # Daily limit row: set it to 15 min then trigger the limit.
            tv._menu_selected = [i.key for i in tv._menu_items].index("daily_limit")
            await tv._draw_menu()
            await press(tv, "LEFT")
            assert tv.config["daily_limit_minutes"] == 45
            await press(tv, "BACK")
            assert tv.mode == MODE_TV and await wait_for(lambda: not tv.player.paused)
            tv.state.add_watch_time(45 * 60)
            await tv._tick(1.0)
            assert tv.mode == MODE_LIMIT and await wait_for(lambda: tv.player.paused)
            tv.add_bonus_minutes(30)
            await tv._resume_after_dialog()
            assert tv.mode == MODE_TV
            # Wi-Fi list from the menu.
            await press(tv, "MENU", "long")
            tv._menu_selected = [i.key for i in tv._menu_items].index("wifi")
            await tv._draw_menu()
            await press(tv, "OK")
            assert await wait_for(lambda: tv.mode == MODE_WIFI and not tv._wifi["scanning"])
            await press(tv, "DOWN")  # second network (open)
            await press(tv, "OK")
            assert await wait_for(lambda: tv.mode == MODE_MENU)
            assert tv.network.connect_calls == [("Otvorena", None)]
        finally:
            await tv.stop()

    asyncio.run(run())


def test_wizard_first_run(tmp_path):
    data = setup_dirs(tmp_path, setup_done=False)

    async def run():
        tv = await make_tv(data)
        try:
            assert tv.mode == MODE_WIZARD
            await press(tv, "OK")  # welcome
            # Standby in the middle of the wizard comes back to the same page, not to the cartoons.
            await press(tv, "POWER")
            assert tv.mode == MODE_STANDBY
            await press(tv, "POWER")
            assert tv.mode == MODE_WIZARD and tv._wizard_step == 1 and not tv.config["setup_done"]
            await press(tv, "OK")  # language (sk)
            assert await wait_for(lambda: tv.mode == MODE_WIFI and not tv._wifi["scanning"])
            items = tv._wifi_items()
            assert items[-1].key == "skip"
            tv._wifi["selected"] = len(items) - 1
            await press(tv, "OK")  # skip wifi
            assert tv.mode == MODE_KEYBOARD  # name
            await tv._cec_event("tv_standby", "")  # the TV itself switched off and on again
            assert tv.mode == MODE_STANDBY
            await tv._cec_event("tv_on", "")
            assert tv.mode == MODE_KEYBOARD and tv._wizard_step == 3
            for _ in range(5):
                await press(tv, "DOWN")
            for _ in range(4):
                await press(tv, "RIGHT")
            await press(tv, "OK")  # DONE
            assert tv.mode == MODE_WIZARD and tv._wizard_step == 4  # web page
            await press(tv, "OK")  # done page
            await press(tv, "OK")  # finish
            assert tv.mode == MODE_TV and tv.config["setup_done"]
            assert await wait_for(lambda: not tv.player.idle)
        finally:
            await tv.stop()

    asyncio.run(run())


def test_web_ui(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        client = TestClient(TestServer(make_app(tv)))
        await client.start_server()
        try:
            for path in ("/", "/channels", "/settings", "/wifi", "/remote", "/system", "/?lang=en"):
                r = await client.get(path)
                assert r.status == 200, path
                body = await r.text()
                assert "Adamova telka" in body
            r = await client.get("/api/status")
            st = await r.json()
            assert st["channel"]["folder"] == "kanal1" and st["mode"] == "tv"
            # Control from the web.
            r = await client.post("/api/control", json={"action": "UP"})
            assert (await r.json())["status"]["channel"]["folder"] == "kanal2"
            # Create a channel with a name, upload a file into it.
            r = await client.post("/channels", data={"name": "Pesničky"}, allow_redirects=False)
            assert r.status == 302
            assert (paths.media_dir() / "kanal4").is_dir()
            assert tv.config.channel_display_name("kanal4") == "Pesničky"
            with open(MEDIA / "clip1.mp4", "rb") as fh:
                r = await client.post("/channels/kanal4/upload", data={"file": fh})
            assert r.status == 200 and (await r.json())["saved"] == ["clip1.mp4"]
            assert (paths.media_dir() / "kanal4" / "clip1.mp4").exists()
            await asyncio.sleep(0.2)
            assert [c.folder for c in tv.channels] == ["kanal1", "kanal2", "kanal3", "kanal4"]
            # The channel page lists uploaded files so the browser can skip
            # re-sending them if a later batch gets dropped again.
            r = await client.get("/channels")
            body = await r.text()
            assert 'data-existing=\'["clip1.mp4"]\'' in body
            # Unsupported extension is rejected silently.
            fd = aiohttp.FormData()
            fd.add_field("file", b"MZ", filename="x.exe", content_type="application/octet-stream")
            r = await client.post("/channels/kanal4/upload", data=fd)
            assert (await r.json())["saved"] == []
            # Settings save.
            r = await client.post("/settings", data={"child_name": "Zuzka", "tv_name": "", "language": "sk",
                                                     "daily_limit_enabled": "on", "daily_limit_minutes": "90",
                                                     "max_volume": "80", "audio_languages": "slk, ces, eng",
                                                     "parent_pin": "1234", "hotspot_ssid": "Zuzkina telka"}, allow_redirects=False)
            assert r.status == 302
            assert tv.config["tv_name"] == "Zuzkina telka" and tv.config["daily_limit_minutes"] == 90
            assert tv.config["audio_languages"] == ["slk", "ces", "eng"] and tv.config["parent_pin"] == "1234"
            # Avatar upload (PNG generated on the fly) then remove.
            from PIL import Image
            import io
            buf = io.BytesIO()
            Image.new("RGB", (300, 200), (200, 100, 50)).save(buf, "PNG")
            fd = aiohttp.FormData()
            fd.add_field("avatar", buf.getvalue(), filename="a.png", content_type="image/png")
            r = await client.post("/settings/avatar", data=fd, allow_redirects=False)
            assert r.status == 302 and paths.avatar_file().exists()
            img = Image.open(paths.avatar_file())
            assert img.size == (512, 512)
            r = await client.get("/avatar.png")
            assert r.status == 200
            r = await client.post("/settings/avatar/delete", allow_redirects=False)
            assert not paths.avatar_file().exists()
            # System actions.
            r = await client.post("/system/add_time", allow_redirects=False)
            assert r.status == 302 and tv.state.bonus_today() == 1800
            # Delete file & channel.
            r = await client.post("/channels/kanal4/files/delete", data={"file": "clip1.mp4"}, allow_redirects=False)
            assert not (paths.media_dir() / "kanal4" / "clip1.mp4").exists()
            r = await client.post("/channels/kanal4/delete", allow_redirects=False)
            assert not (paths.media_dir() / "kanal4").exists()
            r = await client.get("/channels/nope/upload")
            assert r.status in (404, 405)
            # Remote learn via web.
            r = await client.post("/remote/learn", json={"action": "CH_UP"})
            assert (await r.json())["learning"] == "CH_UP"
        finally:
            await client.close()
            await tv.stop()

    asyncio.run(run())


def test_newer_mpv_and_unplayable_files(tmp_path):
    """mpv 0.38+ rejects loadfile's old argument order; and a file mpv refuses
    must never stop the TV from starting, nor make uploads or web play fail."""
    from kidtv.ui.renderer import BANNER
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data, NewerMpvPlayer)
        client = TestClient(TestServer(make_app(tv)))
        await client.start_server()
        try:
            assert tv.mode == MODE_TV
            assert await wait_for(lambda: not tv.player.idle)  # resumed channel 1 on the newer mpv

            async def refuse(*a, **kw):
                raise RuntimeError("invalid parameter")
            tv.player.loadfile = refuse
            await tv.play_channel(0, episode=1)  # must not raise
            assert tv.mode == MODE_TV and tv.renderer.is_visible(BANNER)
            r = await client.post("/channels/kanal1/play", data={"file": "01 Prvá.mp4"}, allow_redirects=False)
            assert r.status == 302
            with open(MEDIA / "clip2.mp4", "rb") as fh:
                r = await client.post("/channels/kanal2/upload", data={"file": fh})
            assert r.status == 200 and (await r.json())["saved"] == ["clip2.mp4"]
            await client.close()
            await tv.stop()

            # Restart with the resume point on a file mpv refuses: startup still completes.
            class RefusingPlayer(NewerMpvPlayer):
                loadfile = staticmethod(refuse)
            tv = await make_tv(data, RefusingPlayer)
            assert tv.mode == MODE_TV
            client = TestClient(TestServer(make_app(tv)))
            await client.start_server()
            r = await client.get("/api/status")
            assert r.status == 200 and (await r.json())["mode"] == "tv"
        finally:
            await client.close()
            await tv.stop()

    asyncio.run(run())


def test_status_line_says_what_each_press_did(tmp_path):
    from kidtv.remote import KeyPress
    from kidtv.ui.renderer import STATUS
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        try:
            await press(tv, "UP")
            assert tv.renderer.is_visible(STATUS)
            assert any(line.endswith("Hore › Kanál 2 · kanal2 – prázdny") for line in tv.log_lines)
            await tv.handle_key(KeyPress("KEY_PROG4", None, "down", "remote"))
            assert any("unknown key KEY_PROG4" in line for line in tv.log_lines)
            await tv.renderer.hide(STATUS)
            tv.config.set("status_line", False)
            await press(tv, "DOWN")
            assert not tv.renderer.is_visible(STATUS)
        finally:
            await tv.stop()

    asyncio.run(run())


def test_inbox_sorts_uploads_into_channels(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        tv.config.set_channel_name("kanal1", "Pat a Mat")
        tv.rescan()
        client = TestClient(TestServer(make_app(tv)))
        await client.start_server()
        try:
            for name in ("Pat+a+Mat+-+S1E3+Gramofon+SK.mp4", "Bluey S02E33 Circus.mp4",
                         "bluey 2x34 Bumpy.mkv", "07 - Mummy Pig at Work [STEiNO].avi"):
                fd = aiohttp.FormData(quote_fields=False)  # raw names, like a browser
                fd.add_field("file", (MEDIA / "clip1.mp4").read_bytes(), filename=name)
                r = await client.post("/inbox/upload", data=fd)
                assert r.status == 200 and (await r.json())["saved"] == [name]
            assert [c.folder for c in tv.channels] == ["kanal1", "kanal2", "kanal3"]  # nothing moved yet
            r = await client.get("/inbox")
            body = await r.text()
            assert r.status == 200 and "Bluey" in body and "S02E33 - Circus.mp4" in body
            # Groups are sorted by name: 0 = Bluey (new), 1 = Pat a Mat (existing kanal1), 2 = unsorted.
            form = aiohttp.FormData()
            for k, v in (("g0_name", "Bluey"), ("g0_target", ""), ("g0_file", "Bluey S02E33 Circus.mp4"),
                         ("g0_file", "bluey 2x34 Bumpy.mkv"),
                         ("g1_name", "Pat a Mat"), ("g1_target", "kanal1"), ("g1_file", "Pat+a+Mat+-+S1E3+Gramofon+SK.mp4"),
                         ("g2_name", ""), ("g2_target", "-"), ("g2_file", "07 - Mummy Pig at Work [STEiNO].avi")):
                form.add_field(k, v)
            r = await client.post("/inbox/apply", data=form, allow_redirects=False)
            assert r.status == 302 and r.headers["Location"].startswith("/inbox")  # one file still waits
            media = paths.media_dir()
            assert (media / "kanal1" / "S01E03 - Gramofon.mp4").exists()
            assert (media / "kanal4" / "S02E33 - Circus.mp4").exists() and (media / "kanal4" / "S02E34 - Bumpy.mkv").exists()
            assert tv.config.channel_display_name("kanal4") == "Bluey"
            assert await wait_for(lambda: [c.folder for c in tv.channels] == ["kanal1", "kanal2", "kanal3", "kanal4"])
            # The channels page lets the browser skip originals that were sorted in already.
            body = await (await client.get("/channels")).text()
            assert "Pat+a+Mat+-+S1E3+Gramofon+SK.mp4" in body and "Čaká na roztriedenie: 1" in body
            # The same file dropped again ends up as a duplicate, not a second copy.
            fd = aiohttp.FormData(quote_fields=False)  # raw names, like a browser
            fd.add_field("file", (MEDIA / "clip1.mp4").read_bytes(), filename="Pat+a+Mat+-+S1E3+Gramofon+SK.mp4")
            await client.post("/inbox/upload", data=fd)
            form = aiohttp.FormData()
            for k, v in (("g0_name", "Pat a Mat"), ("g0_target", "kanal1"), ("g0_file", "Pat+a+Mat+-+S1E3+Gramofon+SK.mp4")):
                form.add_field(k, v)
            r = await client.post("/inbox/apply", data=form, allow_redirects=False)
            assert len(list((media / "kanal1").iterdir())) == 3  # 2 test clips + Gramofon, no copy
            r = await client.post("/inbox/clear", allow_redirects=False)
            assert r.status == 302 and not any(paths.inbox_dir().iterdir())
        finally:
            await client.close()
            await tv.stop()

    asyncio.run(run())
