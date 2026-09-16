"""Network helpers built on NetworkManager's nmcli (default on Raspberry Pi OS
Bookworm) plus a hotspot fallback so the TV can be set up from a phone."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import socket
from dataclasses import dataclass

log = logging.getLogger("kidtv.net")

HOTSPOT_CON = "kidtv-hotspot"
HOTSPOT_IP = "10.42.0.1"
HOTSPOT_DOMAIN = "kid.tv"


@dataclass
class WifiNetwork:
    ssid: str
    signal: int
    secured: bool
    in_use: bool = False


@dataclass
class NetStatus:
    connected: bool
    kind: str  # wifi | ethernet | hotspot | none
    ssid: str | None
    ip: str | None
    hotspot: bool


async def _run(*cmd: str, timeout: float = 30.0) -> tuple[int, str]:
    if shutil.which(cmd[0]) is None:
        return 127, ""
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        return proc.returncode or 0, out.decode("utf-8", "replace")
    except asyncio.TimeoutError:
        log.warning("command timed out: %s", " ".join(cmd))
        return 124, ""
    except OSError as exc:
        log.warning("command failed: %s (%s)", " ".join(cmd), exc)
        return 1, ""


def _unescape(field: str) -> str:
    return field.replace("\\:", ":").replace("\\\\", "\\")


def _split_terse(line: str) -> list[str]:
    # nmcli -t escapes ':' inside fields as '\:'.
    return [_unescape(p) for p in re.split(r"(?<!\\):", line)]


class Network:
    def __init__(self, wifi_iface: str = "wlan0") -> None:
        self.wifi_iface = wifi_iface
        self.available = shutil.which("nmcli") is not None
        self._hotspot_active = False

    # -- status ------------------------------------------------------------
    async def status(self) -> NetStatus:
        if not self.available:
            ip = local_ip()
            return NetStatus(bool(ip), "ethernet" if ip else "none", None, ip, False)
        code, out = await _run("nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "dev", "status", timeout=10)
        kind, ssid, connected = "none", None, False
        hotspot = False
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) < 4:
                continue
            dev, typ, state, con = parts[:4]
            if state.startswith("connected") and typ == "ethernet":
                kind, connected = "ethernet", True
                break
            if state.startswith("connected") and typ == "wifi":
                if con == HOTSPOT_CON:
                    hotspot = True
                    kind = "hotspot"
                else:
                    kind, connected, ssid = "wifi", True, con
        ip = await self.ip_address()
        if kind == "hotspot":
            ip = HOTSPOT_IP
        self._hotspot_active = hotspot
        return NetStatus(connected, kind, ssid, ip, hotspot)

    async def ip_address(self) -> str | None:
        code, out = await _run("hostname", "-I", timeout=5)
        for token in out.split():
            if "." in token and not token.startswith("10.42.0.") and not token.startswith("127."):
                return token
        return local_ip()

    # -- wifi ----------------------------------------------------------------
    async def scan(self, rescan: bool = True) -> list[WifiNetwork]:
        if not self.available:
            return []
        args = ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list", "ifname", self.wifi_iface]
        if rescan:
            args += ["--rescan", "yes"]
        code, out = await _run(*args, timeout=40)
        seen: dict[str, WifiNetwork] = {}
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) < 4:
                continue
            in_use, ssid, signal, security = parts[0], parts[1], parts[2], parts[3]
            if not ssid:
                continue
            try:
                sig = int(signal)
            except ValueError:
                sig = 0
            net = WifiNetwork(ssid=ssid, signal=sig, secured=bool(security.strip()) and security.strip() != "--",
                              in_use=in_use.strip() == "*")
            if ssid not in seen or seen[ssid].signal < sig:
                if ssid in seen and seen[ssid].in_use:
                    net.in_use = True
                seen[ssid] = net
        return sorted(seen.values(), key=lambda n: (-int(n.in_use), -n.signal))

    async def connect(self, ssid: str, password: str | None, hidden: bool = False) -> tuple[bool, str]:
        if not self.available:
            return False, "nmcli not available"
        was_hotspot = self._hotspot_active
        if was_hotspot:
            await self.stop_hotspot()
        # Drop a stale profile with the same name so a changed password is taken.
        await _run("nmcli", "con", "delete", ssid, timeout=10)
        args = ["nmcli", "dev", "wifi", "connect", ssid, "ifname", self.wifi_iface]
        if password:
            args += ["password", password]
        if hidden:
            args += ["hidden", "yes"]
        code, out = await _run(*args, timeout=60)
        ok = code == 0 and "successfully" in out.lower()
        if not ok:
            log.warning("wifi connect failed: %s", out.strip())
            await _run("nmcli", "con", "delete", ssid, timeout=10)
            if was_hotspot:
                await self.start_hotspot(self._last_hotspot_ssid or "Telka")
        return ok, out.strip()

    async def saved_networks(self) -> list[str]:
        code, out = await _run("nmcli", "-t", "-f", "NAME,TYPE", "con", "show", timeout=10)
        names = []
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) >= 2 and parts[1].endswith("wireless") and parts[0] != HOTSPOT_CON:
                names.append(parts[0])
        return names

    async def forget(self, name: str) -> None:
        await _run("nmcli", "con", "delete", name, timeout=10)

    # -- hotspot ---------------------------------------------------------------
    _last_hotspot_ssid: str | None = None

    async def start_hotspot(self, ssid: str) -> bool:
        if not self.available:
            return False
        self._last_hotspot_ssid = ssid
        await _run("nmcli", "con", "delete", HOTSPOT_CON, timeout=10)
        code, out = await _run(
            "nmcli", "con", "add", "type", "wifi", "ifname", self.wifi_iface, "con-name", HOTSPOT_CON,
            "autoconnect", "no", "ssid", ssid, "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
            "ipv4.method", "shared", "ipv4.addresses", f"{HOTSPOT_IP}/24", "ipv6.method", "disabled",
            timeout=20,
        )
        if code != 0:
            log.warning("hotspot add failed: %s", out.strip())
            return False
        code, out = await _run("nmcli", "con", "up", HOTSPOT_CON, timeout=30)
        self._hotspot_active = code == 0
        if not self._hotspot_active:
            log.warning("hotspot up failed: %s", out.strip())
        return self._hotspot_active

    async def stop_hotspot(self) -> None:
        await _run("nmcli", "con", "down", HOTSPOT_CON, timeout=20)
        await _run("nmcli", "con", "delete", HOTSPOT_CON, timeout=10)
        self._hotspot_active = False

    @property
    def hotspot_active(self) -> bool:
        return self._hotspot_active


def local_ip() -> str | None:
    """Best-effort primary IPv4 without shelling out (works without NetworkManager)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        finally:
            s.close()
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def hostname() -> str:
    return socket.gethostname()


def web_urls(status: NetStatus, host: str | None = None) -> list[str]:
    """Addresses to show on screen: hotspot domain, mDNS name, raw IP."""
    urls: list[str] = []
    if status.hotspot:
        urls.append(f"http://{HOTSPOT_DOMAIN}")
    if status.connected:
        h = (host or hostname()).split(".")[0]
        if h and h != "localhost":
            urls.append(f"http://{h}.local")
        if status.ip:
            urls.append(f"http://{status.ip}")
    return urls
