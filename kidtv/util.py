"""Small helpers shared across modules."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

_NAT_SPLIT = re.compile(r"(\d+)")


def natural_key(text: str) -> list[Any]:
    """Sort key so that 'kanal2' < 'kanal10' and '1. epizoda' < '10. epizoda'."""
    # Whitespace is ignored so "kanal 3" and "kanal3" sort the same way.
    parts = _NAT_SPLIT.split("".join(text.casefold().split()))
    return [int(p) if p.isdigit() else p for p in parts]


def atomic_write_json(path: Path, data: Any) -> None:
    """Write JSON to *path* atomically (tmp file + fsync + rename).

    Survives a power cut half-way: either the old or the new file is on disk,
    never a truncated one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_json(path: Path, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def format_clock(seconds: float | None) -> str:
    """123.4 -> '2:03', 3725 -> '1:02:05'."""
    if seconds is None or seconds < 0:
        return "0:00"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def possessive_tv_name(child_name: str, language: str) -> str:
    """Best-effort default TV name from the child's name.

    Slovak: Anna -> Annina telka, Adam -> Adamova telka, Peter -> Petrova telka.
    English: Emma -> Emma's TV. The result is only a default; it stays editable."""
    name = child_name.strip()
    if not name:
        return "Telka" if language == "sk" else "Kids TV"
    if language != "sk":
        return f"{name}'s TV"
    low = name.casefold()
    if low.endswith("a"):
        return f"{name[:-1]}ina telka"
    if low.endswith(("e", "i", "y", "o", "u")):
        return f"{name}ho telka"
    # Common Slovak -er names drop the 'e' (Peter -> Petrova).
    if low.endswith("er") and len(name) > 3:
        return f"{name[:-2]}rova telka"
    return f"{name}ova telka"
