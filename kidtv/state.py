"""Runtime state that must survive a power cut: which channel was on, where each
channel's playback stopped, and how long the TV was watched today."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from . import paths
from .util import atomic_write_json, read_json


def today_str(now: dt.datetime | None = None) -> str:
    return (now or dt.datetime.now()).date().isoformat()


class State:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.state_file()
        self.data: dict[str, Any] = {
            "current_channel": None,  # folder name
            "channels": {},  # folder -> {"file": name, "position": seconds}
            "usage": {"date": today_str(), "seconds": 0.0, "bonus_seconds": 0.0},
            "standby": False,
        }
        stored = read_json(self.path, {})
        if isinstance(stored, dict):
            self.data.update({k: v for k, v in stored.items() if k in self.data})
        self.dirty = False

    def save(self, force: bool = False) -> None:
        if self.dirty or force:
            atomic_write_json(self.path, self.data)
            self.dirty = False

    # -- channel / position ---------------------------------------------
    @property
    def current_channel(self) -> str | None:
        return self.data.get("current_channel")

    def set_current_channel(self, folder: str | None) -> None:
        if self.data.get("current_channel") != folder:
            self.data["current_channel"] = folder
            self.dirty = True

    def resume_point(self, folder: str) -> tuple[str | None, float]:
        entry = self.data["channels"].get(folder) or {}
        return entry.get("file"), float(entry.get("position") or 0.0)

    def set_resume_point(self, folder: str, filename: str | None, position: float) -> None:
        entry = self.data["channels"].setdefault(folder, {})
        new = {"file": filename, "position": round(max(0.0, position), 1)}
        if entry != new:
            self.data["channels"][folder] = new
            self.dirty = True

    def forget_channel(self, folder: str) -> None:
        if folder in self.data["channels"]:
            del self.data["channels"][folder]
            self.dirty = True

    # -- standby ----------------------------------------------------------
    @property
    def standby(self) -> bool:
        return bool(self.data.get("standby"))

    def set_standby(self, value: bool) -> None:
        if self.data.get("standby") != value:
            self.data["standby"] = value
            self.dirty = True

    # -- daily usage -----------------------------------------------------
    def _rollover(self, now: dt.datetime | None = None) -> None:
        usage = self.data["usage"]
        today = today_str(now)
        if usage.get("date") != today:
            self.data["usage"] = {"date": today, "seconds": 0.0, "bonus_seconds": 0.0}
            self.dirty = True

    def add_watch_time(self, seconds: float, now: dt.datetime | None = None) -> None:
        self._rollover(now)
        if seconds > 0:
            self.data["usage"]["seconds"] = float(self.data["usage"]["seconds"]) + seconds
            self.dirty = True

    def watched_today(self, now: dt.datetime | None = None) -> float:
        self._rollover(now)
        return float(self.data["usage"]["seconds"])

    def bonus_today(self, now: dt.datetime | None = None) -> float:
        self._rollover(now)
        return float(self.data["usage"].get("bonus_seconds", 0.0))

    def add_bonus(self, seconds: float, now: dt.datetime | None = None) -> None:
        self._rollover(now)
        self.data["usage"]["bonus_seconds"] = float(self.data["usage"].get("bonus_seconds", 0.0)) + seconds
        self.dirty = True

    def reset_today(self, now: dt.datetime | None = None) -> None:
        self.data["usage"] = {"date": today_str(now), "seconds": 0.0, "bonus_seconds": 0.0}
        self.dirty = True

    def remaining_today(self, limit_minutes: int, enabled: bool, now: dt.datetime | None = None) -> float | None:
        """Seconds left today, or None when the limit is off."""
        if not enabled:
            return None
        allowed = limit_minutes * 60 + self.bonus_today(now)
        return max(0.0, allowed - self.watched_today(now))
