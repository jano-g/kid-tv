"""Scan the media directory: every sub-folder is a channel, every playable file
inside is an episode. Nothing is converted or indexed – files are played as-is."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .util import natural_key

VIDEO_EXT = {
    ".mp4", ".m4v", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".mpg", ".mpeg", ".m2ts",
    ".mts", ".ts", ".vob", ".flv", ".3gp", ".ogv", ".divx", ".asf", ".rm", ".rmvb", ".f4v",
}
AUDIO_EXT = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".aiff", ".ape"}
PLAYABLE_EXT = VIDEO_EXT | AUDIO_EXT


def is_hidden_or_partial(name: str) -> bool:
    return name.startswith(".") or name.endswith((".part", ".tmp", ".crdownload"))


def pretty_title(filename: str) -> str:
    """'03_Maťko a Kubko - Salaš.mp4' -> 'Maťko a Kubko - Salaš' (best effort)."""
    stem = Path(filename).stem
    stem = stem.replace("_", " ").replace(".", " ").strip()
    # Drop a leading track/episode number like '03', '03 -', '3.'.
    parts = stem.split(" ", 1)
    if len(parts) == 2 and parts[0].rstrip("-.)").isdigit():
        stem = parts[1].lstrip("-. ").strip() or stem
    return " ".join(stem.split())


@dataclass(frozen=True)
class Episode:
    path: Path
    is_audio: bool

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def title(self) -> str:
        return pretty_title(self.path.name)


@dataclass
class Channel:
    number: int
    folder: str
    path: Path
    episodes: list[Episode] = field(default_factory=list)
    display_name: str | None = None

    @property
    def is_music(self) -> bool:
        return bool(self.episodes) and all(e.is_audio for e in self.episodes)

    @property
    def is_empty(self) -> bool:
        return not self.episodes

    @property
    def name(self) -> str:
        return self.display_name or self.folder

    def index_of(self, filename: str | None) -> int | None:
        if not filename:
            return None
        for i, ep in enumerate(self.episodes):
            if ep.filename == filename:
                return i
        return None


def scan_channel_dir(path: Path) -> list[Episode]:
    episodes: list[Episode] = []
    try:
        entries = list(path.iterdir())
    except OSError:
        return episodes
    for entry in entries:
        if not entry.is_file() or is_hidden_or_partial(entry.name):
            continue
        ext = entry.suffix.lower()
        if ext not in PLAYABLE_EXT:
            continue
        episodes.append(Episode(path=entry, is_audio=ext in AUDIO_EXT))
    episodes.sort(key=lambda e: natural_key(e.filename))
    return episodes


def scan_library(media_dir: Path, channel_names: dict[str, str] | None = None) -> list[Channel]:
    """Return channels numbered 1..n in natural folder order."""
    channel_names = channel_names or {}
    try:
        folders = [p for p in media_dir.iterdir() if p.is_dir() and not is_hidden_or_partial(p.name)]
    except OSError:
        folders = []
    folders.sort(key=lambda p: natural_key(p.name))
    channels: list[Channel] = []
    for number, folder in enumerate(folders, start=1):
        channels.append(
            Channel(
                number=number,
                folder=folder.name,
                path=folder,
                episodes=scan_channel_dir(folder),
                display_name=channel_names.get(folder.name) or None,
            )
        )
    return channels


def next_channel_folder_name(media_dir: Path, prefix: str = "kanal") -> str:
    """kanal1, kanal2, ... whichever is free next."""
    existing = set()
    try:
        existing = {p.name.casefold() for p in media_dir.iterdir() if p.is_dir()}
    except OSError:
        pass
    n = 1
    while f"{prefix}{n}".casefold() in existing:
        n += 1
    return f"{prefix}{n}"


def safe_filename(name: str) -> str:
    """Strip path separators and control characters from an uploaded filename."""
    name = name.replace("\\", "/").split("/")[-1]
    name = "".join(ch for ch in name if ch.isprintable() and ch not in '<>:"|?*')
    name = name.strip().strip(".")
    return name[:200] or "subor"
