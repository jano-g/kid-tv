import asyncio
import shutil

import pytest

from kidtv.player import Player, build_mpv_args

pytestmark = pytest.mark.skipif(shutil.which("mpv") is None, reason="mpv not installed")


def test_build_args_dev_and_prod(tmp_path):
    dev = build_mpv_args(socket=tmp_path / "s", volume=50, max_volume=100, audio_languages=["slk", "eng"], subtitles=False, dev=True)
    assert "--vo=null" in dev and "--alang=slk,eng" in dev and "--sid=no" in dev
    prod = build_mpv_args(socket=tmp_path / "s", volume=50, max_volume=120, audio_languages=["slk"], subtitles=True, dev=False)
    assert "--gpu-context=drm" in prod and "--volume-max=120" in prod and "--sid=auto" in prod


def test_player_plays_and_reports_events(tmp_path):
    async def run():
        sock = tmp_path / "mpv.sock"
        args = build_mpv_args(socket=sock, volume=40, max_volume=100, audio_languages=["slk"], subtitles=False, dev=True)
        player = Player(args, socket=sock)
        events = []
        player.on_event(lambda m: events.append(m.get("event")))
        await player.start()
        try:
            assert await player.get("volume") == 40
            await player.loadfile("av://lavfi:sine=frequency=440:duration=2", start=0.5)
            for _ in range(100):
                await asyncio.sleep(0.05)
                if player.time_pos is not None and player.time_pos > 0.5:
                    break
            assert player.time_pos is not None and player.time_pos >= 0.5
            assert player.duration and player.duration > 1.5
            await player.set_pause(True)
            for _ in range(40):
                await asyncio.sleep(0.05)
                if player.paused:
                    break
            assert player.paused
            await player.set_volume(70)
            assert await player.get("volume") == 70
            await player.stop_playback()
            for _ in range(60):
                await asyncio.sleep(0.05)
                if "end-file" in events:
                    break
            assert "end-file" in events and "file-loaded" in events
        finally:
            await player.stop()

    asyncio.run(run())
