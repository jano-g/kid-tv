"""Command line entry point: `python3 -m kidtv run`."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

from . import __version__, paths
from .config import Config
from .net import Network
from .player import Player, build_mpv_args
from .state import State


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kidtv", description="Kids' TV for Raspberry Pi")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="start the TV (player + remote + web UI)")
    run.add_argument("--data-dir", help="writable data directory (default /var/lib/kidtv or $KIDTV_DATA_DIR)")
    run.add_argument("--media-dir", help="channel folders (default <data-dir>/media or $KIDTV_MEDIA_DIR)")
    run.add_argument("--port", type=int, default=int(os.environ.get("KIDTV_PORT", "80")), help="web UI port")
    run.add_argument("--dev", action="store_true", help="desktop development: mpv in a window instead of DRM")
    run.add_argument("--headless", action="store_true", help="no video/audio output (tests, CI)")
    run.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd != "run":
        ap.print_help()
        return 1
    if args.data_dir:
        os.environ["KIDTV_DATA_DIR"] = args.data_dir
        os.environ.setdefault("KIDTV_RUNTIME_DIR", str(Path(args.data_dir) / "run"))
    if args.media_dir:
        os.environ["KIDTV_MEDIA_DIR"] = args.media_dir
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 0


async def _run(args: argparse.Namespace) -> int:
    from .controller import TV
    from .web.app import make_app, start_web

    paths.ensure_dirs()
    config = Config()
    state = State()
    network = Network()
    dev_output = args.dev or args.headless
    mpv_args = build_mpv_args(
        socket=paths.mpv_socket(), volume=int(config["volume"]), max_volume=int(config["max_volume"]),
        audio_languages=list(config["audio_languages"]), subtitles=bool(config["subtitles"]), dev=dev_output,
    )
    if args.dev and not args.headless:
        # Desktop window instead of the null outputs used for headless runs.
        mpv_args = [a for a in mpv_args if a not in ("--vo=null", "--ao=null")] + ["--geometry=1280x720"]
    player = Player(mpv_args, socket=paths.mpv_socket())
    tv = TV(config, state, player, network, paths.media_dir(), dev=dev_output)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    await tv.start()
    web_app = make_app(tv)
    runner = await start_web(web_app, args.port)
    logging.getLogger("kidtv").info("web UI on port %d", args.port)
    try:
        await stop_event.wait()
    except SystemExit:
        pass
    finally:
        await runner.cleanup()
        await tv.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
