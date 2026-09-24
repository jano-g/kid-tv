#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one version (used as the release text,
which the TV shows under "Čo je nové").

Usage: scripts/release_notes.py v0.2.0 [CHANGELOG.md]"""

from __future__ import annotations

import re
import sys
from pathlib import Path


def notes_for(version: str, text: str) -> str:
    m = re.search(rf"^## {re.escape(version)}\b[^\n]*\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def main() -> None:
    version = sys.argv[1]
    path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parents[1] / "CHANGELOG.md"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    print(notes_for(version, text) or f"kid-tv {version}")


if __name__ == "__main__":
    main()
