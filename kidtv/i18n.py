"""Tiny translation layer: JSON dictionaries in kidtv/locales/<lang>.json."""

from __future__ import annotations

import json
from typing import Any

from . import paths

LANGUAGES = {"sk": "Slovenčina", "en": "English"}
_cache: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    if lang not in _cache:
        path = paths.LOCALES_DIR / f"{lang}.json"
        try:
            with open(path, encoding="utf-8") as fh:
                _cache[lang] = json.load(fh)
        except OSError:
            _cache[lang] = {}
    return _cache[lang]


def t(lang: str, key: str, **kwargs: Any) -> str:
    """Translate *key*; falls back to Slovak, then to the key itself."""
    text = _load(lang).get(key)
    if text is None and lang != "sk":
        text = _load("sk").get(key)
    if text is None:
        text = key
    if kwargs:
        try:
            text = text.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return text


class Translator:
    """Bound translator so callers can write tr("key") without passing the language."""

    def __init__(self, lang: str = "sk") -> None:
        self.lang = lang if lang in LANGUAGES else "sk"

    def __call__(self, key: str, **kwargs: Any) -> str:
        return t(self.lang, key, **kwargs)
