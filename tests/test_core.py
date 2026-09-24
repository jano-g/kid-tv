import datetime as dt
import json
from pathlib import Path

from kidtv import library, state as state_mod, config as config_mod, i18n
from kidtv.util import natural_key, possessive_tv_name, format_clock, atomic_write_json


def test_natural_key_orders_numbers_numerically():
    names = ["kanal10", "kanal2", "Kanal1", "kanal 3"]
    assert sorted(names, key=natural_key) == ["Kanal1", "kanal2", "kanal 3", "kanal10"]


def test_possessive_tv_name():
    assert possessive_tv_name("Anna", "sk") == "Annina telka"
    assert possessive_tv_name("Adam", "sk") == "Adamova telka"
    assert possessive_tv_name("Peter", "sk") == "Petrova telka"
    assert possessive_tv_name("Emma", "en") == "Emma's TV"
    assert possessive_tv_name("", "sk") == "Telka"


def test_format_clock():
    assert format_clock(0) == "0:00"
    assert format_clock(123.4) == "2:03"
    assert format_clock(3725) == "1:02:05"
    assert format_clock(None) == "0:00"


def test_atomic_write_json_roundtrip(tmp_path):
    p = tmp_path / "sub" / "x.json"
    atomic_write_json(p, {"a": 1, "č": "ž"})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1, "č": "ž"}
    assert not list((tmp_path / "sub").glob("*.tmp"))


def make_media(tmp_path: Path) -> Path:
    media = tmp_path / "media"
    (media / "kanal1").mkdir(parents=True)
    (media / "kanal2").mkdir()
    (media / "kanal10").mkdir()
    (media / ".hidden").mkdir()
    for n in ["10 Salaš.mp4", "2_Ovečky.mkv", "1. Maťko a Kubko.avi", "notes.txt", ".part.mp4.part"]:
        (media / "kanal1" / n).write_bytes(b"x")
    for n in ["a.mp3", "b.flac"]:
        (media / "kanal10" / n).write_bytes(b"x")
    return media


def test_scan_library_numbers_channels_and_sorts_episodes(tmp_path):
    media = make_media(tmp_path)
    chans = library.scan_library(media, {"kanal1": "Rozprávky"})
    assert [c.folder for c in chans] == ["kanal1", "kanal2", "kanal10"]
    assert [c.number for c in chans] == [1, 2, 3]
    c1 = chans[0]
    assert c1.name == "Rozprávky"
    assert [e.filename for e in c1.episodes] == ["1. Maťko a Kubko.avi", "2_Ovečky.mkv", "10 Salaš.mp4"]
    assert [e.title for e in c1.episodes] == ["Maťko a Kubko", "Ovečky", "Salaš"]
    assert chans[1].is_empty and chans[1].name == "kanal2"
    assert chans[2].is_music and not chans[0].is_music
    assert c1.index_of("2_Ovečky.mkv") == 1 and c1.index_of("missing") is None


def test_next_channel_folder_name(tmp_path):
    media = make_media(tmp_path)
    assert library.next_channel_folder_name(media) == "kanal3"
    assert library.safe_filename("../../etc/passwd") == "passwd"
    assert library.safe_filename('a<b>:"c".mp4') == "abc.mp4"


def test_state_resume_and_usage(tmp_path):
    st = state_mod.State(tmp_path / "state.json")
    st.set_current_channel("kanal1")
    st.set_resume_point("kanal1", "a.mp4", 12.34)
    now = dt.datetime(2026, 9, 16, 20, 0)
    st.add_watch_time(100, now)
    st.add_bonus(60, now)
    st.save()

    st2 = state_mod.State(tmp_path / "state.json")
    assert st2.current_channel == "kanal1"
    assert st2.resume_point("kanal1") == ("a.mp4", 12.3)
    assert st2.watched_today(now) == 100
    assert st2.remaining_today(60, True, now) == 60 * 60 + 60 - 100
    assert st2.remaining_today(60, False, now) is None
    # Midnight rollover clears the counters.
    tomorrow = now + dt.timedelta(days=1)
    assert st2.watched_today(tomorrow) == 0
    assert st2.remaining_today(1, True, tomorrow) == 60


def test_config_defaults_and_tv_name(tmp_path):
    cfg = config_mod.Config(tmp_path / "config.json")
    assert cfg["tv_name"] == "Telka" and cfg["child_name"] == ""
    cfg.set("child_name", "Zuzka")
    assert cfg["tv_name"] == "Zuzkina telka"
    cfg.set("tv_name", "Naša telka")
    cfg.set("child_name", "Adam")
    assert cfg["tv_name"] == "Naša telka"  # manual name sticks
    cfg.set("tv_name", "")
    assert cfg["tv_name"] == "Adamova telka"
    cfg.set("language", "en")
    assert cfg["tv_name"] == "Adam's TV"
    cfg.set("max_volume", 70)
    cfg.set("volume", 95)
    assert cfg["volume"] == 70
    cfg2 = config_mod.Config(tmp_path / "config.json")
    assert cfg2["child_name"] == "Adam" and cfg2["language"] == "en"
    assert "parent_pin" not in cfg2.as_public_dict()


def test_i18n_fallback():
    assert i18n.t("sk", "channel.label", n=3) == "Kanál 3"
    assert i18n.t("en", "channel.label", n=3) == "Channel 3"
    assert i18n.t("en", "does.not.exist") == "does.not.exist"
    tr = i18n.Translator("xx")
    assert tr.lang == "sk"
