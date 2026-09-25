"""Updates from GitHub releases, without taking the SD card out.

check()    asks the GitHub API for the latest release and remembers the answer
           in update.json (so the web page and the menu can show it offline).
prepare()  downloads the release's app bundle kid-tv-app-vX.Y.Z.tar.gz,
           verifies its sha256 and unpacks it under /var/lib/kidtv/updates.
handoff()  starts scripts/apply-update.sh through systemd-run, i.e. outside
           kidtv.service: it stops the TV, backs up /opt/kidtv to
           /opt/kidtv.prev, installs the new version, restarts the service and
           goes back to the old version when the new one does not come up.

Nothing is ever installed without somebody pressing a button; the daily
check only looks. Cartoons, settings and the photo are never touched.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import shutil
import tarfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import aiohttp

from . import __version__, paths
from .util import atomic_write_json, read_json

log = logging.getLogger("kidtv.update")

API_BASE = "https://api.github.com"
BUNDLE_RE = re.compile(r"^kid-tv-app-v?(\d+\.\d+\.\d+)\.tar\.gz$")
MAX_BUNDLE_BYTES = 200 * 1024 * 1024
FINAL_STATES = ("success", "rolled_back", "failed")

Runner = Callable[[list[str]], Awaitable[tuple[int, str]]]
Progress = Callable[[float], Any]


class UpdateError(Exception):
    """Something the user should see, in plain words (codes are translated by the UI)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def parse_version(text: str | None) -> tuple[int, int, int]:
    """'v0.10.2' -> (0, 10, 2); anything unparsable -> (0, 0, 0)."""
    nums = re.findall(r"\d+", (text or "").split("-")[0].split("+")[0])
    parts = [int(n) for n in nums[:3]] + [0, 0, 0]
    return parts[0], parts[1], parts[2]


def is_newer(candidate: str | None, current: str | None) -> bool:
    return parse_version(candidate) > parse_version(current)


def version_in(app_dir: Path) -> str | None:
    """Read __version__ from an unpacked or installed app directory."""
    try:
        text = (app_dir / "kidtv" / "__init__.py").read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"__version__\s*=\s*[\"']([^\"']+)[\"']", text)
    return m.group(1) if m else None


@dataclass
class ReleaseInfo:
    version: str  # without the leading "v"
    tag: str
    name: str
    notes: str
    url: str  # release page
    bundle_url: str
    bundle_size: int
    sha256_url: str | None
    published: str


def _pick_release(data: dict[str, Any]) -> ReleaseInfo | None:
    assets = {a.get("name", ""): a for a in data.get("assets", []) if isinstance(a, dict)}
    for name, asset in assets.items():
        m = BUNDLE_RE.match(name)
        if not m:
            continue
        sha = assets.get(name + ".sha256")
        return ReleaseInfo(
            version=m.group(1),
            tag=str(data.get("tag_name") or ("v" + m.group(1))),
            name=str(data.get("name") or ""),
            notes=str(data.get("body") or "")[:4000],
            url=str(data.get("html_url") or ""),
            bundle_url=str(asset.get("browser_download_url") or ""),
            bundle_size=int(asset.get("size") or 0),
            sha256_url=str(sha.get("browser_download_url")) if sha else None,
            published=str(data.get("published_at") or ""),
        )
    return None


async def _run_subprocess(cmd: list[str]) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), 30)
    return proc.returncode or 0, out.decode("utf-8", "replace")


class Updater:
    def __init__(self, repo: str, current: str = __version__, data_dir: Path | None = None,
                 install_dir: Path | None = None, api_base: str = API_BASE,
                 runner: Runner | None = None) -> None:
        self.repo = repo
        self.current = current
        self.data_dir = data_dir or paths.data_dir()
        self.install_dir = install_dir or paths.install_dir()
        self.api_base = api_base.rstrip("/")
        self.runner = runner or _run_subprocess
        self.cache_file = self.data_dir / "update.json"
        self.status_file = self.data_dir / "update-status.json"
        self.log_file = self.data_dir / "update.log"
        self.work_dir = self.data_dir / "updates"
        self.busy: str | None = None  # checking | downloading | installing
        self.progress = 0.0
        self.error: str | None = None
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # State shown in the UI
    # ------------------------------------------------------------------
    def cached(self) -> dict[str, Any]:
        data = read_json(self.cache_file, {})
        return data if isinstance(data, dict) else {}

    @property
    def latest(self) -> ReleaseInfo | None:
        raw = self.cached().get("latest")
        if not isinstance(raw, dict):
            return None
        try:
            return ReleaseInfo(**raw)
        except TypeError:
            return None

    @property
    def available(self) -> bool:
        latest = self.latest
        return bool(latest and is_newer(latest.version, self.current))

    @property
    def previous_dir(self) -> Path:
        return Path(str(self.install_dir) + ".prev")

    def previous_version(self) -> str | None:
        v = version_in(self.previous_dir)
        return v if v and v != self.current else None

    def last_status(self) -> dict[str, Any] | None:
        data = read_json(self.status_file, None)
        return data if isinstance(data, dict) else None

    def mark_status_shown(self) -> None:
        data = self.last_status()
        if data and not data.get("shown"):
            data["shown"] = True
            atomic_write_json(self.status_file, data)

    def log_tail(self, lines: int = 40) -> list[str]:
        try:
            return self.log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]
        except OSError:
            return []

    def info(self) -> dict[str, Any]:
        cache = self.cached()
        latest = self.latest
        return {
            "current": self.current,
            "latest": asdict(latest) if latest else None,
            "available": self.available,
            "checked_at": cache.get("checked_at"),
            "check_error": cache.get("error"),
            "busy": self.busy,
            "progress": round(self.progress, 3),
            "error": self.error,
            "last": self.last_status(),
            "previous": self.previous_version(),
            "repo": self.repo,
        }

    def check_due(self, max_age_hours: float = 20.0) -> bool:
        checked = self.cached().get("checked_ts") or 0
        return time.time() - float(checked) > max_age_hours * 3600

    # ------------------------------------------------------------------
    # Network
    # ------------------------------------------------------------------
    def _session(self, timeout: float) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=timeout),
            headers={"User-Agent": f"kid-tv/{self.current}", "Accept": "application/vnd.github+json"},
        )

    async def check(self) -> ReleaseInfo | None:
        """Ask GitHub for the latest release. Returns it (newer or not), or None."""
        async with self._lock:
            self.busy, self.error = "checking", None
            try:
                url = f"{self.api_base}/repos/{self.repo}/releases/latest"
                async with self._session(20) as session:
                    async with session.get(url) as resp:
                        if resp.status == 404:
                            info = None  # no release yet, or the repository is private
                            error = "not-found"
                        elif resp.status != 200:
                            log.warning("update check: GitHub answered HTTP %s", resp.status)
                            raise UpdateError("http", str(resp.status))
                        else:
                            info = _pick_release(await resp.json(content_type=None))
                            error = None if info else "no-bundle"
                atomic_write_json(self.cache_file, {
                    "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checked_ts": time.time(),
                    "latest": asdict(info) if info else None, "error": error,
                })
                log.info("update check: latest=%s current=%s", info.version if info else None, self.current)
                return info
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError) as exc:
                log.warning("update check failed: %s: %s", type(exc).__name__, exc)
                cache = self.cached()
                cache.update({"error": "offline", "checked_ts": cache.get("checked_ts", 0)})
                atomic_write_json(self.cache_file, cache)
                raise UpdateError("offline", str(exc)) from exc
            finally:
                self.busy = None

    async def _download(self, session: aiohttp.ClientSession, url: str, target: Path,
                        size_hint: int, progress: Progress | None) -> str:
        digest = hashlib.sha256()
        done = 0
        tmp = target.with_suffix(target.suffix + ".part")
        async with session.get(url) as resp:
            if resp.status != 200:
                raise UpdateError("download", f"HTTP {resp.status}")
            total = int(resp.headers.get("Content-Length") or size_hint or 0)
            with open(tmp, "wb") as fh:
                async for chunk in resp.content.iter_chunked(256 * 1024):
                    done += len(chunk)
                    if done > MAX_BUNDLE_BYTES:
                        raise UpdateError("download", "bundle too large")
                    digest.update(chunk)
                    fh.write(chunk)
                    if total:
                        self.progress = min(0.99, done / total)
                        if progress:
                            result = progress(self.progress)
                            if asyncio.iscoroutine(result):
                                await result
        tmp.replace(target)
        return digest.hexdigest()

    async def prepare(self, info: ReleaseInfo, progress: Progress | None = None) -> Path:
        """Download, verify and unpack a release. Returns the app directory."""
        async with self._lock:
            self.busy, self.error, self.progress = "downloading", None, 0.0
            try:
                return await self._prepare(info, progress)
            except UpdateError as exc:
                self.error = exc.code
                raise
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as exc:
                self.error = "download"
                raise UpdateError("download", str(exc)) from exc
            finally:
                self.busy = None

    async def _prepare(self, info: ReleaseInfo, progress: Progress | None) -> Path:
        if not info.bundle_url or not info.sha256_url:
            raise UpdateError("no-bundle")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        bundle = self.work_dir / f"kid-tv-app-v{info.version}.tar.gz"
        async with self._session(60) as session:
            async with session.get(info.sha256_url) as resp:
                if resp.status != 200:
                    raise UpdateError("download", f"checksum HTTP {resp.status}")
                expected = (await resp.text()).split()[0].strip().lower()
            actual = await self._download(session, info.bundle_url, bundle, info.bundle_size, progress)
        if actual != expected:
            bundle.unlink(missing_ok=True)
            raise UpdateError("checksum")
        target = self.work_dir / f"kid-tv-v{info.version}"
        shutil.rmtree(target, ignore_errors=True)
        target.mkdir(parents=True)
        _safe_extract(bundle, target)
        app = _find_app_root(target)
        if app is None:
            raise UpdateError("bad-bundle")
        found = version_in(app)
        if found != info.version:
            raise UpdateError("bad-bundle", f"bundle says {found}, release says {info.version}")
        # Old downloads are no longer needed.
        for old in self.work_dir.iterdir():
            if old.name.startswith("kid-tv-") and old not in (bundle, target):
                if old.is_dir():
                    shutil.rmtree(old, ignore_errors=True)
                else:
                    old.unlink(missing_ok=True)
        self.progress = 1.0
        return app

    # ------------------------------------------------------------------
    # Installing
    # ------------------------------------------------------------------
    async def handoff(self, source: Path, version: str) -> None:
        """Start apply-update.sh outside kidtv.service. It will stop this process."""
        script_src = source / "scripts" / "apply-update.sh"
        if not script_src.exists():  # rolling back to a version without the script
            script_src = self.install_dir / "scripts" / "apply-update.sh"
        if not script_src.exists():
            raise UpdateError("no-script")
        systemd_run = shutil.which("systemd-run")
        if systemd_run is None and self.runner is _run_subprocess:
            raise UpdateError("no-systemd")
        self.work_dir.mkdir(parents=True, exist_ok=True)
        # Run a copy: the original is replaced while the script runs.
        script = self.work_dir / "apply-update.sh"
        shutil.copy2(script_src, script)
        cmd = [
            systemd_run or "systemd-run", "--unit", f"kidtv-update-{int(time.time())}", "--collect", "--quiet",
            f"--setenv=KIDTV_DATA_DIR={self.data_dir}", f"--setenv=KIDTV_DEST={self.install_dir}",
            "/bin/bash", str(script), str(source), version,
        ]
        self.busy = "installing"
        code, out = await self.runner(cmd)
        if code != 0:
            self.busy = None
            self.error = "handoff"
            raise UpdateError("handoff", out.strip()[:300])
        log.info("update to %s handed over to %s", version, cmd[2])

    async def rollback(self) -> str:
        version = self.previous_version()
        if not version:
            raise UpdateError("no-previous")
        await self.handoff(self.previous_dir, version)
        return version


def _safe_extract(bundle: Path, target: Path) -> None:
    try:
        with tarfile.open(bundle, "r:gz") as tar:
            root = target.resolve()
            for member in tar.getmembers():
                dest = (target / member.name).resolve()
                if root != dest and root not in dest.parents:
                    raise UpdateError("bad-bundle", f"unsafe path {member.name}")
                if member.issym() or member.islnk() or member.isdev():
                    raise UpdateError("bad-bundle", f"link or device {member.name}")
            if hasattr(tarfile, "data_filter"):
                tar.extractall(target, filter="data")
            else:  # pragma: no cover – Python without PEP 706
                tar.extractall(target)
    except (tarfile.TarError, EOFError) as exc:
        raise UpdateError("bad-bundle", str(exc)) from exc


def _find_app_root(target: Path) -> Path | None:
    candidates = [target] + [p for p in target.iterdir() if p.is_dir()]
    for c in candidates:
        if (c / "kidtv" / "__init__.py").exists() and (c / "image" / "setup.sh").exists():
            return c
    return None
