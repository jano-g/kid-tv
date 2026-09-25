"""Sort a heap of uploaded files into channels by what their names say.

'Pat+a+Mat+-+S1E3+Gramofon+SK.mp4'        -> series 'Pat a Mat', S01E03, 'Gramofon'
'Peppa.Pig.S01E05.Mister.Dinosaur.1080p.mkv' -> series 'Peppa Pig', S01E05, 'Mister Dinosaur'
'Maťko a Kubko - 03 - Salaš.avi'           -> series 'Maťko a Kubko', E03, 'Salaš'
'01 - Muddy Puddles [STEiNO].avi'          -> no series in the name: the parent is asked

Files are grouped by series; a group whose name matches an existing channel
goes there, otherwise a new channel is proposed. Nothing is moved until the
proposal is confirmed on the web page."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .library import Channel, PLAYABLE_EXT, safe_filename
from .util import natural_key

# Release/language/quality noise, dropped from series names and titles.
_NOISE = {
    "sk", "svk", "slo", "slovak", "cz", "cze", "cs", "czech", "en", "eng", "english", "hu", "pl", "de",
    "dabing", "dab", "dub", "dubbed", "titulky", "tit", "subs", "sub", "cc",
    "480p", "576p", "720p", "1080p", "1080i", "2160p", "4k", "uhd", "hd", "sd", "fhd",
    "x264", "x265", "h264", "h265", "hevc", "avc", "xvid", "divx", "aac", "ac3", "dts", "mp3", "dd5", "dd51",
    "web", "webrip", "webdl", "web-dl", "bluray", "bdrip", "brrip", "dvdrip", "dvd", "hdtv", "tvrip", "satrip",
    "rip", "remux", "proper", "repack", "internal", "multi", "complete",
}
_BRACKETS = re.compile(r"\[[^\]]*\]|\{[^}]*\}|\([^)]*\)")
_SEPARATORS = re.compile(r"[+_.]+")
_SPACES = re.compile(r"\s+")
_YEAR = re.compile(r"^(19|20)\d\d$")

# Episode markers, most specific first. Each yields (season, episode, start, end).
_SXE = re.compile(r"(?<![a-z0-9])s(\d{1,2})\s*[-.]?\s*e(\d{1,3})(?![0-9])", re.I)
_NXN = re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{1,3})(?![0-9])", re.I)
_WORD_EP = re.compile(r"(?<![a-z0-9])(?:e|ep|episode|epizoda|epizóda|díl|dil|diel|časť|cast|part|folge)\.?\s*(\d{1,3})(?![0-9])", re.I)
_DASH_NUM = re.compile(r"\s[-–]\s*(\d{1,3})\s*(?:[-–]\s|$)")
_LEAD_NUM = re.compile(r"^\s*(\d{1,3})\s*(?:[-–.)]\s*|\s+)")


@dataclass
class Parsed:
    original: str
    series: str | None  # None: the name does not say which series it is
    season: int | None
    episode: int | None
    title: str
    ext: str

    @property
    def clean_name(self) -> str:
        """Tidy filename for the channel folder, sorting in episode order."""
        if self.episode is not None:
            code = f"S{self.season:02d}E{self.episode:02d}" if self.season is not None else f"E{self.episode:02d}"
            name = f"{code} - {self.title}" if self.title else code
        else:
            name = self.title or Path(self.original).stem
        return safe_filename(name + self.ext)


def _strip_noise(words: list[str]) -> list[str]:
    def noise(w: str) -> bool:
        k = w.casefold().strip("-–:,;")
        return not k or k in _NOISE or bool(_YEAR.match(k))
    while words and noise(words[-1]):
        words.pop()
    while words and noise(words[0]):
        words.pop(0)
    return [w for w in words if w.casefold() not in _NOISE]


def _tidy(text: str) -> str:
    text = _SPACES.sub(" ", text).strip(" -–:,;")
    return " ".join(_strip_noise(text.split(" ")))


def parse(filename: str) -> Parsed:
    stem, ext = Path(filename).stem, Path(filename).suffix.lower()
    text = _BRACKETS.sub(" ", stem)
    text = _SEPARATORS.sub(" ", text)
    text = _SPACES.sub(" ", text).strip()
    season = episode = None
    before = after = None
    for rx in (_SXE, _NXN):
        m = rx.search(text)
        if m:
            season, episode = int(m.group(1)), int(m.group(2))
            before, after = text[:m.start()], text[m.end():]
            break
    if episode is None:
        m = _WORD_EP.search(text) or _DASH_NUM.search(text)
        if m:
            episode = int(m.group(1))
            before, after = text[:m.start()], text[m.end():]
    if episode is None:
        m = _LEAD_NUM.match(text)
        if m:  # "01 - Muddy Puddles": a number and a title, but no series
            return Parsed(filename, None, None, int(m.group(1)), _tidy(text[m.end():]), ext)
        # No marker at all: "Series - Title" when there is a dash, otherwise just a title.
        parts = re.split(r"\s[-–]\s", text, maxsplit=1)
        if len(parts) == 2:
            return Parsed(filename, _tidy(parts[0]) or None, None, None, _tidy(parts[1]), ext)
        return Parsed(filename, None, None, None, _tidy(text), ext)
    series = _tidy(before or "") or None
    return Parsed(filename, series, season, episode, _tidy(after or ""), ext)


def series_key(name: str) -> str:
    """'Pat & Mat', 'pat a mat', 'Pát a Mat' -> the same key."""
    norm = unicodedata.normalize("NFKD", name.casefold().replace("&", " a ").replace(" and ", " a "))
    norm = "".join(ch for ch in norm if not unicodedata.combining(ch))
    return "".join(ch for ch in norm if ch.isalnum())


@dataclass
class Group:
    name: str  # proposed channel name ("" = unknown, ask)
    target: str  # existing channel folder, or "" = a new channel
    files: list[Parsed] = field(default_factory=list)

    @property
    def key(self) -> str:
        return series_key(self.name)


def propose(filenames: list[str], channels: list[Channel]) -> tuple[list[Group], list[Parsed]]:
    """Group *filenames* by series. Returns (groups, unsorted files)."""
    by_channel = {}
    for ch in channels:
        for label in (ch.name, ch.folder):
            if label:
                by_channel.setdefault(series_key(label), ch.folder)
    groups: dict[str, Group] = {}
    unsorted: list[Parsed] = []
    for fn in filenames:
        if Path(fn).suffix.lower() not in PLAYABLE_EXT:
            continue
        p = parse(fn)
        if not p.series:
            unsorted.append(p)
            continue
        key = series_key(p.series)
        if not key:
            unsorted.append(p)
            continue
        g = groups.get(key)
        if g is None:
            g = groups[key] = Group(p.series, by_channel.get(key, ""))
        g.files.append(p)
    # "Series - Title" without episode numbers is only trusted when the series
    # repeats; a lone file like that is more likely just a title with a dash.
    for key, g in list(groups.items()):
        if len(g.files) == 1 and g.files[0].episode is None and not g.target:
            p = g.files[0]
            unsorted.append(Parsed(p.original, None, None, None, _tidy(" - ".join(filter(None, [p.series, p.title]))), p.ext))
            del groups[key]
    for g in groups.values():
        g.files.sort(key=lambda p: (p.season or 0, p.episode or 0, natural_key(p.title)))
        # Name the channel the way most files spell the series.
        spellings: dict[str, int] = {}
        for p in g.files:
            spellings[p.series or ""] = spellings.get(p.series or "", 0) + 1
        g.name = max(spellings, key=lambda s: (spellings[s], s != s.lower()))
        if g.target:
            ch = next(c for c in channels if c.folder == g.target)
            g.name = ch.name
    unsorted.sort(key=lambda p: natural_key(p.original))
    return sorted(groups.values(), key=lambda g: natural_key(g.name)), unsorted
