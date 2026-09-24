# Vývoj

## Lokálne spustenie (Linux / macOS s mpv)

```bash
sudo apt install mpv python3-pip        # alebo brew install mpv
python3 -m pip install -e . pytest
mkdir -p /tmp/kidtv/media/kanal1 && cp nejake-video.mp4 /tmp/kidtv/media/kanal1/
python3 -m kidtv run --dev --data-dir /tmp/kidtv --port 8080
```

`--dev` otvorí mpv v okne (1280×720). Ovládanie klávesnicou (okno terminálu
nemusí mať fokus – evdev číta klávesnicu priamo, na Linuxe treba práva na
`/dev/input`, teda skupina `input` alebo `sudo`): šípky, Enter, Esc, `+`/`-`,
`m`, medzerník, `n`/`p`, `1`–`9`, podržané `F1` = nastavenia. Web:
`http://localhost:8080`.

`--headless` (`--vo=null --ao=null`) používajú testy a CI.

## Testy

```bash
python3 -m pytest -q
```

`tests/test_tv.py` spúšťa skutočné mpv bez výstupu a preklikáva celú telku:
kanály, pokračovanie, standby, EOF, menu, klávesnicu, limit, sprievodcu a web
(vrátane nahrávania). Testovacie videá (`tests/media/*.mp4`, 3 s) sú
vygenerované `ffmpeg -f lavfi`.

Ukážky obrazoviek do PNG:

```bash
python3 scripts/preview_screens.py /tmp/screens --avatar fotka.jpg [--lang en] [--size 1280x720]
```

## Štruktúra repozitára

```
kidtv/            aplikácia (Python 3.11+, bez build kroku)
  ui/             grafika (Pillow → mpv overlay)
  web/            aiohttp + Jinja2 šablóny + static
  locales/        sk.json, en.json
  assets/fonts/   Fredoka, Nunito (OFL)
image/            provisioning (setup.sh), pi-gen stage, mpv.conf, asound.conf
systemd/          kidtv.service, kidtv-splash.service
scripts/          install.sh (existujúce RPi OS), preview_screens.py, make_splash.py
tests/
.github/workflows ci.yml (testy), release.yml (vydanie: balík aplikácie + voliteľne SD obraz),
                  cleanup.yml (ručne: zmazať tag s vydaním, behy mimo histórie)
```

## Inštalácia na existujúce Raspberry Pi OS Lite (bez obrazu)

```bash
sudo apt install git
git clone https://github.com/jano-g/kid-tv.git
sudo bash kid-tv/scripts/install.sh
sudo reboot
```

Skript nainštaluje balíky, skopíruje aplikáciu do `/opt/kidtv`, zapne služby,
upraví `config.txt`/`cmdline.txt` (tichý boot, HDMI zvuk) a hostname `kid`.

## Vydanie novej verzie

1. Do `CHANGELOG.md` pridaj sekciu `## vX.Y.Z` (po slovensky, pre rodiča – telka
   ju ukáže na webe pod „Čo je nové“).
2. *Actions → Release → Run workflow*, verzia `vX.Y.Z`. Políčko *Also build the
   SD card image* zaškrtni len keď treba nový obraz (45–90 minút).
3. Workflow `.github/workflows/release.yml` spustí testy, zostaví balík
   `kid-tv-app-vX.Y.Z.tar.gz` + `.sha256` (`scripts/build_bundle.sh`, verzia sa
   zapíše do `kidtv/__init__.py` automaticky) a vytvorí Release s textom z
   CHANGELOG. Telky ho uvidia pri najbližšej kontrole.

Push tagu `vX.Y.Z` spustí to isté vrátane obrazu.

### Ako prebieha aktualizácia na telke

`kidtv/updater.py` → GitHub API `releases/latest` → stiahne balík a overí
sha256 → rozbalí do `/var/lib/kidtv/updates/` → spustí
`scripts/apply-update.sh` cez `systemd-run` (mimo `kidtv.service`). Skript
zastaví službu, zálohuje `/opt/kidtv` do `/opt/kidtv.prev`, spustí
`image/setup.sh` z nového balíka (doinštaluje len chýbajúce balíky, nerobí
upgrade), reštartuje službu a čaká, kým `/api/status` nahlási novú verziu.
Keď sa to do 2 minút nestane, vráti zálohu. Výsledok je v
`/var/lib/kidtv/update-status.json`, priebeh v `/var/lib/kidtv/update.log`.

Ručne na telke (SSH), napríklad na skúšku konkrétnej verzie:

```bash
curl -fsSL https://raw.githubusercontent.com/jano-g/kid-tv/main/scripts/update.sh | sudo bash -s v0.2.0
```

Lokálny balík na skúšku: `scripts/build_bundle.sh v0.2.1 /tmp/dist`, skopírovať
na telku, rozbaliť a `sudo bash kid-tv/scripts/apply-update.sh kid-tv 0.2.1`.

## Zostavenie SD obrazu

### GitHub Actions (odporúčané)

Job `image` vo workflowe `release.yml` používa
[usimd/pi-gen-action](https://github.com/usimd/pi-gen-action) s oficiálnym
[pi-gen](https://github.com/RPi-Distro/pi-gen): `stage0 stage1 stage2` (= Raspberry
Pi OS Lite Trixie) + náš `image/stage-kidtv`, ktorý spustí `image/setup.sh` v
chroote. Obraz `kid-tv-vX.Y.Z.img.xz` + `.sha256` pripojí k tomu istému Release.

- Na x86 runneri (`ubuntu-latest`) beží pod QEMU, trvá **45–90 minút**. Na
  ARM runneri (`ubuntu-24.04-arm`, pre verejné repozitáre zdarma) by mal byť
  podstatne rýchlejší – stačí zmeniť `runs-on` (zatiaľ neskúšané).

### Lokálne (Docker)

```bash
git clone https://github.com/RPi-Distro/pi-gen.git -b arm64
cp image/pi-gen-config pi-gen/config
cd pi-gen && ln -s ../image/stage-kidtv stage-kidtv
# v config zmeň STAGE_LIST na "stage0 stage1 stage2 stage-kidtv"
./build-docker.sh
# výsledok: pi-gen/deploy/image_*kid-tv*.img.xz
```

## Čo overiť na skutočnom hardvéri (zatiaľ netestované)

Kód bol vyvíjaný a testovaný bez Raspberry Pi (mpv bez výstupu). Po prvom
zostavení obrazu treba na RPi 4 overiť najmä:

1. `mpv --vo=gpu --gpu-context=drm --hwdec=auto-copy` na Trixie – plynulé 1080p
   H.264 a HEVC; ak nie, upraviť `/etc/kidtv/mpv.conf` (`hwdec=v4l2m2m-copy`,
   `drm-connector=HDMI-A-1`).
2. Zvuk cez HDMI (`dtparam=audio=off`, `/etc/asound.conf` → `vc4hdmi0`).
3. `cec-client` na Trixie/KMS (`/dev/cec0`) – názvy klávesov v logu.
4. Hotspot cez NetworkManager (`ipv4.method shared`) a DNS `address=/#/` –
   otvorenie `http://kid.tv` na iPhone/Androide.
5. Boot bez textu (`console=tty3`, `quiet`) a splash cez `fbi`.
6. Skutočný G10S ovládač – ktoré `KEY_*` kódy posiela (web → Ovládač →
   *Posledné stlačené tlačidlo*), doplniť do `DEFAULT_MAP`.
