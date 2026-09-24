"""Runs scripts/apply-update.sh for real, with systemctl and setup.sh replaced
by stand-ins and a tiny HTTP server playing the restarted app."""

import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply-update.sh"


def write_app(path: Path, version: str, *files: str) -> Path:
    (path / "kidtv").mkdir(parents=True, exist_ok=True)
    (path / "image").mkdir(parents=True, exist_ok=True)
    (path / "kidtv/__init__.py").write_text(f'__version__ = "{version}"\n')
    (path / "image/setup.sh").write_text("#!/bin/bash\n")
    for f in files:
        (path / f).write_text(f)
    return path


def installed_version(dest: Path) -> str:
    import re
    text = (dest / "kidtv/__init__.py").read_text()
    return re.search(r'__version__ = "([^"]+)"', text).group(1)


@pytest.fixture
def env(tmp_path):
    dest = write_app(tmp_path / "opt" / "kidtv", "0.1.0", "old.txt")
    data = tmp_path / "data"
    calls = tmp_path / "calls.log"
    fake_systemctl = tmp_path / "systemctl"
    fake_systemctl.write_text(f'#!/bin/sh\necho "$@" >> "{calls}"\n')
    fake_systemctl.chmod(0o755)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            broken = (dest / "BROKEN").exists()
            body = json.dumps({"version": "" if broken else installed_version(dest)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    e = dict(os.environ,
             KIDTV_DEST=str(dest), KIDTV_DATA_DIR=str(data), KIDTV_SYSTEMCTL=str(fake_systemctl),
             KIDTV_HEALTH_URL=f"http://127.0.0.1:{server.server_port}/api/status",
             KIDTV_HEALTH_TIMEOUT="2", KIDTV_HEALTH_INTERVAL="0.2",
             KIDTV_SETUP_CMD='rm -rf "$KIDTV_DEST" && cp -a "$KIDTV_SRC" "$KIDTV_DEST"')
    yield {"dest": dest, "data": data, "calls": calls, "env": e, "tmp": tmp_path}
    server.shutdown()


def run(env, src, version):
    return subprocess.run(["bash", str(SCRIPT), str(src), version], env=env["env"], capture_output=True,
                          text=True, timeout=60, stdin=subprocess.DEVNULL)


def status(env):
    return json.loads((env["data"] / "update-status.json").read_text())


def test_successful_update_keeps_a_backup(env):
    src = write_app(env["tmp"] / "src", "0.2.0", "new.txt")
    r = run(env, src, "v0.2.0")
    assert r.returncode == 0, (env["data"] / "update.log").read_text()
    dest, prev = env["dest"], Path(str(env["dest"]) + ".prev")
    assert installed_version(dest) == "0.2.0" and (dest / "new.txt").exists() and not (dest / "old.txt").exists()
    assert installed_version(prev) == "0.1.0" and (prev / "old.txt").exists()
    st = status(env)
    assert (st["state"], st["from"], st["to"], st["shown"]) == ("success", "0.1.0", "0.2.0", False)
    calls = env["calls"].read_text()
    assert "stop kidtv.service" in calls and "restart kidtv.service" in calls
    assert "kid-tv update 0.1.0 -> 0.2.0" in (env["data"] / "update.log").read_text()

    # Manual rollback: install the backup again.
    r = run(env, prev, "0.1.0")
    assert r.returncode == 0
    assert installed_version(dest) == "0.1.0" and installed_version(prev) == "0.2.0"
    assert status(env)["state"] == "success"


def test_broken_update_rolls_back(env):
    src = write_app(env["tmp"] / "src", "0.2.0", "BROKEN")
    r = run(env, src, "0.2.0")
    assert r.returncode == 1
    assert installed_version(env["dest"]) == "0.1.0" and not (env["dest"] / "BROKEN").exists()
    st = status(env)
    assert st["state"] == "rolled_back" and st["from"] == "0.1.0" and st["to"] == "0.2.0"


def test_failing_setup_rolls_back(env):
    src = write_app(env["tmp"] / "src", "0.2.0")
    env["env"]["KIDTV_SETUP_CMD"] = ('if grep -q 0.2.0 "$KIDTV_SRC/kidtv/__init__.py"; then exit 3; fi; '
                                     'rm -rf "$KIDTV_DEST" && cp -a "$KIDTV_SRC" "$KIDTV_DEST"')
    r = run(env, src, "0.2.0")
    assert r.returncode == 1 and status(env)["state"] == "rolled_back"
    assert installed_version(env["dest"]) == "0.1.0"


def test_rejects_a_directory_that_is_not_kidtv(env):
    empty = env["tmp"] / "empty"
    empty.mkdir()
    r = run(env, empty, "0.2.0")
    assert r.returncode == 1 and status(env)["state"] == "failed"
    assert installed_version(env["dest"]) == "0.1.0"


def test_update_sh_end_to_end(env, tmp_path):
    """The one-time path up from 0.1.0: scripts/update.sh against a fake GitHub
    serving a real bundle built by scripts/build_bundle.sh."""
    import hashlib
    from http.server import ThreadingHTTPServer

    root = SCRIPT.parents[1]
    dist = tmp_path / "dist"
    bundle = Path(subprocess.run(["bash", str(root / "scripts/build_bundle.sh"), "v0.2.0", str(dist)],
                                 capture_output=True, text=True, check=True).stdout.strip())
    files = {"/dl/bundle": bundle.read_bytes(),
             "/dl/sha": f"{hashlib.sha256(bundle.read_bytes()).hexdigest()}  {bundle.name}\n".encode()}

    class GH(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            base = f"http://127.0.0.1:{self.server.server_port}"
            if self.path == "/repos/o/r/releases/latest":
                body = json.dumps({"tag_name": "v0.2.0", "assets": [
                    {"name": bundle.name, "browser_download_url": base + "/dl/bundle"},
                    {"name": bundle.name + ".sha256", "browser_download_url": base + "/dl/sha"}]}).encode()
            elif self.path in files:
                body = files[self.path]
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    gh = ThreadingHTTPServer(("127.0.0.1", 0), GH)
    threading.Thread(target=gh.serve_forever, daemon=True).start()
    try:
        e = dict(env["env"], KIDTV_API=f"http://127.0.0.1:{gh.server_port}", KIDTV_REPO="o/r",
                 SSH_CONNECTION="test", HOME=str(tmp_path))
        r = subprocess.run(["bash", str(root / "scripts/update.sh")], env=e, capture_output=True, text=True,
                           timeout=120, stdin=subprocess.DEVNULL)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "Nainštalovaná verzia: 0.1.0, inštalujem: 0.2.0" in r.stdout
        assert "Hotovo, telka beží na verzii 0.2.0." in r.stdout
        assert installed_version(env["dest"]) == "0.2.0"
        assert (env["dest"] / "scripts/apply-update.sh").exists()
        assert (env["data"] / "updating.png").exists()  # drawn by the new version
        assert status(env)["state"] == "success"
        # A repository that is not there (or still private) gives a clear message.
        e["KIDTV_REPO"] = "o/missing"
        r = subprocess.run(["bash", str(root / "scripts/update.sh")], env=e, capture_output=True, text=True,
                           timeout=60, stdin=subprocess.DEVNULL)
        assert r.returncode == 1 and "verejný" in r.stderr
    finally:
        gh.shutdown()
