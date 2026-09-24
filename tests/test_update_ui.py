"""Update flow through the on-screen menu and the web page, with GitHub and
systemd replaced by a fake updater."""

import asyncio
import json
import shutil

import pytest
from aiohttp.test_utils import TestClient, TestServer

from kidtv import __version__, paths
from kidtv.controller import MODE_MENU, MODE_TV, MODE_UPDATING
from kidtv.updater import ReleaseInfo, UpdateError, Updater
from kidtv.web.app import make_app

from test_tv import make_tv, press, setup_dirs, wait_for

pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")

NEW = "9.9.9"


class FakeUpdater(Updater):
    def __init__(self, *a, fail=None, **kw):
        super().__init__("o/r", *a, **kw)
        self.fail = fail
        self.handoffs = []

    async def check(self):
        info = ReleaseInfo(version=NEW, tag="v" + NEW, name="", notes="- lepšie", url="http://x/rel",
                           bundle_url="http://x/b", bundle_size=1, sha256_url="http://x/s", published="")
        from dataclasses import asdict
        from kidtv.util import atomic_write_json
        atomic_write_json(self.cache_file, {"checked_at": "2026-09-24T10:00:00", "checked_ts": 9e12,
                                            "latest": asdict(info), "error": None})
        return info

    async def prepare(self, info, progress=None):
        for p in (0.1, 0.5, 1.0):
            await progress(p)
        if self.fail:
            raise UpdateError(self.fail)
        src = self.work_dir / "src"
        src.mkdir(parents=True, exist_ok=True)
        return src

    async def handoff(self, source, version):
        self.handoffs.append((str(source), version))


def test_menu_update_flow(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        tv.updater = FakeUpdater()
        try:
            await press(tv, "MENU", "long")
            keys = [i.key for i in tv._menu_items]
            assert "update" in keys and "rollback" not in keys
            tv._menu_selected = keys.index("update")
            await tv._draw_menu()
            await press(tv, "OK")  # nothing known yet -> checks
            assert await wait_for(lambda: tv.updater.available)
            assert tv._menu_items[keys.index("update")].value == f"Nová verzia {NEW}"
            await press(tv, "OK")  # now asks to confirm
            await press(tv, "LEFT")  # select "Áno"
            await press(tv, "OK")
            assert await wait_for(lambda: tv.updater.handoffs)
            assert tv.mode == MODE_UPDATING and tv.updater.handoffs[0][1] == NEW
            assert (paths.data_dir() / "updating.png").exists()
            # Keys are ignored while updating.
            await press(tv, "POWER")
            assert tv.mode == MODE_UPDATING
        finally:
            await tv.stop()

    asyncio.run(run())


def test_failed_download_returns_to_the_menu(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        tv.updater = FakeUpdater(fail="checksum")
        try:
            await tv.updater.check()
            await press(tv, "MENU", "long")
            assert tv.mode == MODE_MENU
            assert await tv.start_update() is False
            assert tv.mode == MODE_MENU and not tv.updater.handoffs
            # Started from the web while watching: back to the cartoon.
            await press(tv, "BACK")
            assert tv.mode == MODE_TV
            await tv.start_update()
            assert tv.mode == MODE_TV and await wait_for(lambda: not tv.player.paused)
        finally:
            await tv.stop()

    asyncio.run(run())


def test_result_toast_after_restart(tmp_path):
    data = setup_dirs(tmp_path)
    (data / "update-status.json").write_text(json.dumps(
        {"state": "success", "from": "0.1.0", "to": __version__, "message": "", "time": "", "shown": False}))

    async def run():
        tv = await make_tv(data)
        try:
            assert await wait_for(lambda: tv.updater.last_status().get("shown"), timeout=8)
            assert any("last update: success" in line for line in tv.log_lines)
        finally:
            await tv.stop()

    asyncio.run(run())


def test_web_update_section(tmp_path):
    data = setup_dirs(tmp_path)

    async def run():
        tv = await make_tv(data)
        tv.updater = FakeUpdater()
        client = TestClient(TestServer(make_app(tv)))
        await client.start_server()
        try:
            body = await (await client.get("/system")).text()
            assert 'id="update"' in body and "Skontrolovať teraz" in body
            r = await client.post("/system/update/check", allow_redirects=False)
            assert r.status == 302 and r.headers["Location"].startswith("/system?ok=") and r.headers["Location"].endswith("#update")
            body = await (await client.get("/")).text()
            assert f"Je dostupná nová verzia telky {NEW}" in body  # banner on other pages
            body = await (await client.get("/system")).text()
            assert f"Aktualizovať na {NEW}" in body and "- lepšie" in body
            (paths.data_dir() / "update-status.json").write_text(json.dumps(
                {"state": "rolled_back", "from": "0.1.0", "to": "0.2.0", "message": "", "time": "2026-09-24T10:00:00+02:00"}))
            body = await (await client.get("/system")).text()
            assert "verzia 0.2.0 nenaštartovala, vrátená 0.1.0" in body
            st = await (await client.get("/api/status")).json()
            assert st["update"]["available"] and st["update"]["latest"]["version"] == NEW
            r = await client.post("/system/update/install")
            assert r.status == 200 and "Aktualizujem telku" in await r.text()
            assert await wait_for(lambda: tv.updater.handoffs)
            # Settings checkbox for the daily check.
            r = await client.post("/settings", data={"child_name": "Anna", "language": "sk"}, allow_redirects=False)
            assert r.status == 302 and tv.config["update_auto_check"] is False
        finally:
            await client.close()
            await tv.stop()

    asyncio.run(run())
