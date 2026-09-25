"""Filesystem locations. Everything writable lives under DATA_DIR so the rest of
the system can be treated as read-only."""

from __future__ import annotations

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BACKGROUNDS_DIR = ASSETS_DIR / "backgrounds"
LOCALES_DIR = PACKAGE_DIR / "locales"


def data_dir() -> Path:
    return Path(os.environ.get("KIDTV_DATA_DIR", "/var/lib/kidtv"))


def media_dir() -> Path:
    return Path(os.environ.get("KIDTV_MEDIA_DIR", str(data_dir() / "media")))


def inbox_dir() -> Path:
    """Uploads waiting to be sorted into channels (next to media: moving is a rename)."""
    return data_dir() / "inbox"


def runtime_dir() -> Path:
    return Path(os.environ.get("KIDTV_RUNTIME_DIR", "/run/kidtv"))


def config_file() -> Path:
    return data_dir() / "config.json"


def state_file() -> Path:
    return data_dir() / "state.json"


def avatar_file() -> Path:
    return data_dir() / "avatar.png"


def install_dir() -> Path:
    """Where the app is installed on the Raspberry Pi (replaced by updates)."""
    return Path(os.environ.get("KIDTV_DEST", "/opt/kidtv"))


def updates_dir() -> Path:
    return data_dir() / "updates"


def mpv_socket() -> Path:
    return runtime_dir() / "mpv.sock"


def ensure_dirs() -> None:
    for d in (data_dir(), media_dir(), runtime_dir()):
        d.mkdir(parents=True, exist_ok=True)
