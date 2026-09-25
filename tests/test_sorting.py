from pathlib import Path

from kidtv.library import Channel, Episode
from kidtv.sorting import parse, propose, series_key


def test_parse_real_world_names():
    cases = {
        "Pat+a+Mat+-+S1E3+Gramofon+SK.mp4": ("Pat a Mat", 1, 3, "Gramofon", "S01E03 - Gramofon.mp4"),
        "Peppa.Pig.S01E05.Mister.Dinosaur.Is.Lost.1080p.WEB.x264.mkv":
            ("Peppa Pig", 1, 5, "Mister Dinosaur Is Lost", "S01E05 - Mister Dinosaur Is Lost.mkv"),
        "bluey 2x34 Bumpy.mkv": ("bluey", 2, 34, "Bumpy", "S02E34 - Bumpy.mkv"),
        "Maťko a Kubko - 03 - Salaš.avi": ("Maťko a Kubko", None, 3, "Salaš", "E03 - Salaš.avi"),
        "Tlapková patrola díl 13 CZ dabing.mp4": ("Tlapková patrola", None, 13, "", "E13.mp4"),
        "01 - Muddy Puddles [STEiNO].avi": (None, None, 1, "Muddy Puddles", "E01 - Muddy Puddles.avi"),
        "S02E01 - Dance Mode.mp4": (None, 2, 1, "Dance Mode", "S02E01 - Dance Mode.mp4"),
        "Krtko a autíčko (1963) CZ.mp4": (None, None, None, "Krtko a autíčko", "Krtko a autíčko.mp4"),
    }
    for name, (series, season, episode, title, clean) in cases.items():
        p = parse(name)
        assert (p.series, p.season, p.episode, p.title, p.clean_name) == (series, season, episode, title, clean), name


def test_series_key_ignores_case_accents_and_ampersand():
    assert series_key("Pat & Mat") == series_key("pat a mat") == series_key("Pát a Mat")


def test_propose_groups_matches_existing_channels_and_asks_for_the_rest(tmp_path):
    bluey = Channel(1, "kanal1", tmp_path / "kanal1", [Episode(tmp_path / "kanal1" / "S02E01 - Dance Mode.mp4", False)], "Bluey")
    files = ["Pat+a+Mat+-+S1E5+Houpací+křeslo+SK.mp4", "Pat+a+Mat+-+S1E3+Gramofon+SK.mp4",
             "Bluey S02E33 Circus.mp4", "bluey 2x34 Bumpy.mkv",
             "01 - Muddy Puddles [STEiNO].avi", "Just a title - with a dash.mp4", "notes.txt"]
    groups, unsorted = propose(files, [bluey])
    by_name = {g.name: g for g in groups}
    assert set(by_name) == {"Bluey", "Pat a Mat"}
    assert by_name["Bluey"].target == "kanal1" and len(by_name["Bluey"].files) == 2
    assert by_name["Pat a Mat"].target == ""
    assert [p.episode for p in by_name["Pat a Mat"].files] == [3, 5]  # episode order
    assert [p.original for p in unsorted] == ["01 - Muddy Puddles [STEiNO].avi", "Just a title - with a dash.mp4"]
