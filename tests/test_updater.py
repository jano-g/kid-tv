import asyncio
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from kidtv.updater import UpdateError, Updater, is_newer, parse_version, version_in

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_versions():
    assert parse_version("v0.10.2") == (0, 10, 2)
    assert parse_version("1.2") == (1, 2, 0)
    assert parse_version(None) == (0, 0, 0)
    assert is_newer("0.10.0", "0.9.9") and not is_newer("v0.1.0", "0.1.0") and not is_newer("0.1.0", "0.2.0")


def make_bundle(version: str, *, prefix="kid-tv/", extra: dict[str, bytes] | None = None) -> bytes:
    files = {
        "kidtv/__init__.py": f'__version__ = "{version}"\n'.encode(),
        "image/setup.sh": b"#!/bin/bash\necho setup\n",
        "scripts/apply-update.sh": (REPO_ROOT / "scripts/apply-update.sh").read_bytes(),
    }
    files.update(extra or {})
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeGitHub:
    def __init__(self, version="0.2.0", bundle: bytes | None = None, sha: str | None = None, status=200,
                 with_bundle=True):
        self.version = version
        self.bundle = bundle if bundle is not None else make_bundle(version)
        self.sha = sha or hashlib.sha256(self.bundle).hexdigest()
        self.status = status
        self.with_bundle = with_bundle
        self.server: TestServer | None = None

    def app(self) -> web.Application:
        app = web.Application()

        async def latest(request):
            if self.status != 200:
                return web.json_response({"message": "Not Found"}, status=self.status)
            base = str(request.url.origin())
            name = f"kid-tv-app-v{self.version}.tar.gz"
            assets = [{"name": f"kid-tv-v{self.version}.img.xz", "browser_download_url": base + "/dl/img", "size": 9}]
            if self.with_bundle:
                assets += [{"name": name, "browser_download_url": base + "/dl/bundle", "size": len(self.bundle)},
                           {"name": name + ".sha256", "browser_download_url": base + "/dl/sha", "size": 90}]
            return web.json_response({"tag_name": f"v{self.version}", "name": f"kid-tv v{self.version}",
                                      "body": "- nové veci", "html_url": base + "/rel", "published_at": "2026-09-24T10:00:00Z",
                                      "assets": assets})

        async def bundle(request):
            return web.Response(body=self.bundle)

        async def sha(request):
            return web.Response(text=f"{self.sha}  kid-tv-app-v{self.version}.tar.gz\n")

        app.router.add_get("/repos/o/r/releases/latest", latest)
        app.router.add_get("/dl/bundle", bundle)
        app.router.add_get("/dl/sha", sha)
        return app


async def with_server(fake: FakeGitHub, fn):
    server = TestServer(fake.app())
    await server.start_server()
    try:
        return await fn(str(server.make_url("")).rstrip("/"))
    finally:
        await server.close()


def make_updater(tmp_path, api, **kw):
    return Updater("o/r", current=kw.pop("current", "0.1.0"), data_dir=tmp_path / "data",
                   install_dir=tmp_path / "opt" / "kidtv", api_base=api, **kw)


def test_check_prepare_and_handoff(tmp_path):
    calls = []

    async def runner(cmd):
        calls.append(cmd)
        return 0, ""

    async def go(api):
        up = make_updater(tmp_path, api, runner=runner)
        info = await up.check()
        assert info and info.version == "0.2.0" and up.available
        assert up.info()["latest"]["notes"] == "- nové veci"
        # The answer is cached for the UI.
        again = make_updater(tmp_path, api)
        assert again.available and again.latest.version == "0.2.0" and not again.check_due()
        seen = []
        app = await up.prepare(info, progress=seen.append)
        assert version_in(app) == "0.2.0" and (app / "image/setup.sh").exists()
        assert up.progress == 1.0 and seen
        await up.handoff(app, info.version)
        cmd = calls[-1]
        assert cmd[0].endswith("systemd-run") and "--collect" in cmd
        assert cmd[-2:] == [str(app), "0.2.0"]
        assert Path(cmd[-3]).name == "apply-update.sh" and Path(cmd[-3]).exists()
        assert f"--setenv=KIDTV_DEST={tmp_path / 'opt' / 'kidtv'}" in cmd

    asyncio.run(with_server(FakeGitHub(), go))


def test_same_version_is_not_available(tmp_path):
    async def go(api):
        up = make_updater(tmp_path, api, current="0.2.0")
        assert (await up.check()).version == "0.2.0"
        assert not up.available

    asyncio.run(with_server(FakeGitHub(), go))


def test_missing_repo_and_missing_bundle(tmp_path):
    async def go404(api):
        up = make_updater(tmp_path, api)
        assert await up.check() is None
        assert up.info()["check_error"] == "not-found" and not up.available

    asyncio.run(with_server(FakeGitHub(status=404), go404))

    async def go_nobundle(api):
        up = make_updater(tmp_path, api)
        assert await up.check() is None
        assert up.info()["check_error"] == "no-bundle"

    asyncio.run(with_server(FakeGitHub(with_bundle=False), go_nobundle))


def test_offline(tmp_path):
    up = make_updater(tmp_path, "http://127.0.0.1:9")
    with pytest.raises(UpdateError) as exc:
        asyncio.run(up.check())
    assert exc.value.code == "offline" and up.busy is None


@pytest.mark.parametrize("fake,code", [
    (FakeGitHub(sha="0" * 64), "checksum"),
    (FakeGitHub(bundle=make_bundle("0.3.0")), "bad-bundle"),  # bundle says 0.3.0, release says 0.2.0
    (FakeGitHub(bundle=make_bundle("0.2.0", prefix="../")), "bad-bundle"),
    (FakeGitHub(bundle=b"not a tarball"), "bad-bundle"),
])
def test_prepare_rejects_bad_bundles(tmp_path, fake, code):
    async def go(api):
        up = make_updater(tmp_path, api)
        info = await up.check()
        with pytest.raises(UpdateError) as exc:
            await up.prepare(info)
        assert exc.value.code == code and up.error == code

    asyncio.run(with_server(fake, go))
    assert not (tmp_path / "evil").exists()


def test_rollback_uses_previous_install(tmp_path):
    calls = []

    async def runner(cmd):
        calls.append(cmd)
        return 0, ""

    prev = tmp_path / "opt" / "kidtv.prev"
    (prev / "kidtv").mkdir(parents=True)
    (prev / "kidtv/__init__.py").write_text('__version__ = "0.1.0"\n')
    (tmp_path / "opt/kidtv/scripts").mkdir(parents=True)
    (tmp_path / "opt/kidtv/scripts/apply-update.sh").write_text("#!/bin/bash\n")
    up = make_updater(tmp_path, "http://unused", current="0.2.0", runner=runner)
    assert up.previous_version() == "0.1.0"
    assert asyncio.run(up.rollback()) == "0.1.0"
    assert calls[-1][-2:] == [str(prev), "0.1.0"]


def test_status_shown_flag(tmp_path):
    up = make_updater(tmp_path, "http://unused")
    up.data_dir.mkdir(parents=True)
    up.status_file.write_text(json.dumps({"state": "success", "from": "0.1.0", "to": "0.2.0", "shown": False}))
    assert up.last_status()["state"] == "success"
    up.mark_status_shown()
    assert up.last_status()["shown"] is True
