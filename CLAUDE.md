# kid-tv (Annina telka)

Detský „televízor“ pre Raspberry Pi 4: priečinky `media/kanalN/` = kanály,
ovládanie diaľkovým ovládačom, web rozhranie na nahrávanie. Dokumentácia pre
používateľa je v [README.md](README.md) (slovensky), technické detaily v
`docs/architecture.md` a `docs/development.md`.

## Stack a obmedzenia
- **Python 3.11+, asyncio, jeden proces** (`python3 -m kidtv run`): mpv cez JSON IPC,
  evdev, cec-client, nmcli, aiohttp web. Žiadny build krok, žiadny JS framework.
- Beží na **Raspberry Pi OS Lite Bookworm arm64** ako root (`systemd/kidtv.service`).
  Používaj len balíky z Debian repozitára (`image/stage-kidtv/00-install/00-packages`).
- Grafika telky sú **Pillow obrázky vkladané do mpv ako overlay** (`kidtv/ui/`),
  nie X11/Wayland. Návrh v 1080p jednotkách cez `ctx.s()`, fonty Fredoka/Nunito
  (nemajú ▲▼◀▶●○✓ – v textoch používaj slová).
- Texty UI **vždy cez i18n** (`kidtv/locales/sk.json` + `en.json`, kľúče musia
  byť v oboch). Slovenčina je primárna.
- Stav (`state.json`) a konfigurácia (`config.json`) sa zapisujú **atomicky**
  (`util.atomic_write_json`) – telka sa bežne vypína zo zásuvky.

## Testy
```bash
python3 -m pytest -q            # 26 testov, potrebuje nainštalované mpv
python3 scripts/preview_screens.py /tmp/screens --avatar fotka.jpg   # PNG náhľady obrazoviek
```
`tests/test_tv.py` je end-to-end test so skutočným mpv (`--vo=null`). Pri zmene
controllera alebo webu ho spusti; pri zmene obrazoviek si pozri PNG náhľady.

## Konvencie
- Commit a push po každej ucelenej zmene, nie vo veľkých dávkach.
- Novú akciu pridaj na **všetky** povrchy naraz: ovládač (`remote.py` mapa),
  on-screen menu (`controller.py`), web (`web/app.py` + šablóna), obidva jazyky.
- Nastavenia idú do `config.DEFAULTS`; reaguj na zmenu v `TV._config_changed`.
- SD obraz stavia `.github/workflows/build-image.yml` (pi-gen) po tagu `vX.Y.Z`.
  Provisioning je v `image/setup.sh` – rovnaký skript používa aj `scripts/install.sh`.
- Kód zatiaľ **nebol overený na skutočnom Raspberry Pi**; zoznam vecí na overenie
  je v `docs/development.md`.
