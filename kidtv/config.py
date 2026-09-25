"""Persistent settings (config.json) with sane defaults.

Every setting can be changed both from the on-screen menu and the web UI, so all
of them live here in one flat-ish dict."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Callable

from . import paths
from .util import atomic_write_json, possessive_tv_name, read_json

CONFIG_VERSION = 1

DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "language": "sk",  # ui language: sk | en
    "child_name": "",  # asked by the first-run wizard
    "tv_name": "Telka",
    "tv_name_auto": True,  # regenerate tv_name from child_name until edited by hand
    "setup_done": False,
    "volume": 60,
    "max_volume": 100,
    "daily_limit_enabled": True,
    "daily_limit_minutes": 60,
    # Preferred audio languages in order (ISO 639-2 + common aliases understood by mpv).
    "audio_languages": ["slk", "slo", "sk", "eng", "en"],
    "subtitles": False,
    "channel_names": {},  # folder name -> display name
    "remote_map": {},  # evdev key name -> action (overrides defaults, see remote.py)
    "settings_hold_ms": 1500,
    "parent_pin": "",  # empty = no PIN on the settings menu
    "hotspot_ssid": "",  # empty = same as the TV name
    "banner_seconds": 4,
    "show_clock": False,
    "status_line": True,
    "background": "vesmir",  # menu/screens illustration, "" = starry night (ui/screens.BACKGROUNDS)  # top-left line saying what each button press did
    # Updates: GitHub repository with releases, and a daily "is there a new
    # version?" check (installing always needs a button press).
    "update_repo": "jano-g/kid-tv",
    "update_auto_check": True,
}


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.config_file()
        self.data: dict[str, Any] = copy.deepcopy(DEFAULTS)
        self._listeners: list[Callable[[str, Any], None]] = []
        self.load()

    # -- persistence -----------------------------------------------------
    def load(self) -> None:
        stored = read_json(self.path, {})
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    self.data[key] = value
        self.data["version"] = CONFIG_VERSION

    def save(self) -> None:
        atomic_write_json(self.path, self.data)

    # -- access ----------------------------------------------------------
    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any, save: bool = True) -> None:
        if key not in DEFAULTS:
            raise KeyError(key)
        if key == "child_name":
            value = str(value).strip() or DEFAULTS["child_name"]
            if self.data.get("tv_name_auto", True):
                self.data["tv_name"] = possessive_tv_name(value, self.data["language"])
        if key == "tv_name":
            value = str(value).strip()
            if not value:
                self.data["tv_name_auto"] = True
                value = possessive_tv_name(self.data["child_name"], self.data["language"])
            else:
                self.data["tv_name_auto"] = value == possessive_tv_name(
                    self.data["child_name"], self.data["language"]
                )
        if key == "language" and self.data.get("tv_name_auto", True):
            self.data["tv_name"] = possessive_tv_name(self.data["child_name"], str(value))
        if key in ("volume", "max_volume", "daily_limit_minutes", "settings_hold_ms", "banner_seconds"):
            value = int(value)
        if key == "volume":
            value = max(0, min(int(self.data["max_volume"]), value))
        self.data[key] = value
        if save:
            self.save()
        for cb in list(self._listeners):
            cb(key, value)

    def update(self, values: dict[str, Any]) -> None:
        for key, value in values.items():
            self.set(key, value, save=False)
        self.save()

    def on_change(self, callback: Callable[[str, Any], None]) -> None:
        self._listeners.append(callback)

    # -- convenience -----------------------------------------------------
    def channel_display_name(self, folder: str) -> str | None:
        name = self.data.get("channel_names", {}).get(folder)
        return name or None

    def set_channel_name(self, folder: str, name: str) -> None:
        names = dict(self.data.get("channel_names", {}))
        name = name.strip()
        if name:
            names[folder] = name
        else:
            names.pop(folder, None)
        self.set("channel_names", names)

    def as_public_dict(self) -> dict[str, Any]:
        d = copy.deepcopy(self.data)
        d["parent_pin_set"] = bool(d.pop("parent_pin", ""))
        return d
