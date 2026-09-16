# Architektúra

```
┌──────────────────────────── Raspberry Pi OS Lite (Bookworm, arm64) ────────────────────────────┐
│                                                                                                │
│  systemd: kidtv-splash.service (fbi, splash.png)  →  kidtv.service (python3 -m kidtv run)      │
│                                                                                                │
│  ┌──────────────── kidtv (jeden asyncio proces) ────────────────┐     ┌───────────────┐        │
│  │ controller.TV        stavový automat telky                   │────▶│ mpv           │──▶ HDMI│
│  │  ├ library           priečinky → kanály → epizódy            │ IPC │ --vo=gpu drm  │        │
│  │  ├ state             resume pozície, denný čas (state.json)  │     │ --hwdec       │──▶ ALSA│
│  │  ├ config            nastavenia (config.json)                │     │ overlay-add   │        │
│  │  ├ ui/*              Pillow → BGRA overlaye (banner, menu…)  │     └───────────────┘        │
│  │  ├ remote            evdev (USB/2.4G/BT ovládač, klávesnica) │◀── /dev/input/event*          │
│  │  ├ cec               cec-client (TV ovládač, zapnutie TV)    │◀── /dev/cec0                  │
│  │  ├ net               nmcli: scan/connect/hotspot             │──▶ NetworkManager             │
│  │  └ web/app (aiohttp) :80  HTML+JS, upload, captive portal    │◀── mobil / počítač            │
│  └──────────────────────────────────────────────────────────────┘                              │
│                                                                                                │
│  /var/lib/kidtv/{config.json,state.json,avatar.png,splash.png}   /var/lib/kidtv/media/kanalN/  │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
```

## Moduly

| Modul | Úloha |
|-------|-------|
| `kidtv/library.py` | Skenuje `media/`. Každý podpriečinok = kanál (číslo podľa prirodzeného poradia názvov, `kanal2 < kanal10`). Súbory s video/audio príponou = epizódy, tiež prirodzene zoradené. Kanál len s audio súbormi je *hudobný*. |
| `kidtv/state.py` | `state.json`: aktuálny kanál, `{kanál: {file, position}}`, dnešný čas + bonus. Atomický zápis (tmp + fsync + rename) – prežije vytiahnutie zo zásuvky. |
| `kidtv/config.py` | `config.json` s predvolenými hodnotami; odvodenie názvu telky z mena (*Anna → Annina telka*), notifikácie zmien pre controller. |
| `kidtv/player.py` | Spustí mpv (`--idle --force-window`, DRM, `--hwdec=auto-copy`, `--alang=slk,…`), JSON IPC cez unix socket, sleduje `time-pos`, `duration`, `pause`, `eof`. Overlaye cez `overlay-add` (surové BGRA súbory v `/run/kidtv`). |
| `kidtv/remote.py` | Číta všetky evdev zariadenia s klávesami, mapuje `KEY_*` → akcie (`CH_UP`, `OK`, …). Predvolená mapa pokrýva G10S/G20S/MX3/Rii aj klávesnicu (`BTN_LEFT` = OK, lebo air-mouse posiela OK ako klik myši). Dlhé stlačenie (MENU 1,5 s). Učenie: prepíše mapu v `config.remote_map`. |
| `kidtv/cec.py` | `cec-client -d 8 -t p`: parsuje `key pressed: … (xx)` → akcie; posiela `on 0`, `standby 0`, `as`. Reaguje na standby televízora. |
| `kidtv/ui/theme.py` | Farby (nočná obloha + jeden akcent na kanál), fonty (Fredoka/Nunito, variabilné), avatar v kruhu, pomocné kreslenie. |
| `kidtv/ui/screens.py` | Všetky scény: splash, banner kanála, hlasitosť, toast, menu, klávesnica, PIN, sprievodca, hudobný kanál, prázdny kanál, dobrú noc, limit. Návrh v 1080p jednotkách, škáluje sa podľa `osd-dimensions` mpv. |
| `kidtv/ui/renderer.py` | 4 vrstvy (PANEL, BANNER, VOLUME, TOAST), zápis BGRA do tmpfs, `overlay-add/remove`, automatické skrytie. |
| `kidtv/controller.py` | Režimy: `tv`, `standby`, `limit`, `menu`, `keyboard`, `wifi`, `hotspot`, `pin`, `confirm`, `learn`, `wizard`, `about`. Tik každú sekundu: počítanie času, ukladanie pozície, limit. Sledovanie zmien v `media/` (každé 4 s podľa mtime). Sieťový monitor (10 s). Reštart mpv pri páde. |
| `kidtv/net.py` | `nmcli` wrapper. Hotspot = NM profil `kidtv-hotspot` (AP, `ipv4.method shared`, 10.42.0.1). DNS pre captive portál: `/etc/NetworkManager/dnsmasq-shared.d/kidtv.conf` (`address=/#/10.42.0.1`). |
| `kidtv/web/app.py` | aiohttp + Jinja2. Streamované multipart nahrávanie (súbory v GB, zápis do `.part` a rename). Captive-portal middleware: pri zapnutom hotspote presmeruje cudzie hostiteľské mená na `/setup`. `/api/status`, `/api/control` pre ovládanie z webu. |

## Tok udalostí

1. **Boot** → `kidtv-splash` ukáže `splash.png` cez `fbi` → `kidtv.service`.
2. `TV.start()` spustí mpv, ukáže splash overlay, načíta knižnicu a stav, spustí
   ticker, monitor médií, monitor siete, evdev a CEC.
3. Ak `setup_done == false` → sprievodca; inak `play_channel(posledný kanál, resume=True)`.
4. Kláves → `RemoteListener` → `KeyPress(action, kind)` → `TV.handle_action` →
   podľa režimu. `VOL_*` a `POWER` fungujú vo všetkých režimoch.
5. `end-file (eof)` → ďalšia epizóda, po poslednej prvá. Chyba súboru → toast + ďalšia.
6. Každú sekundu pri prehrávaní: `state.add_watch_time`, `set_resume_point`;
   každých 5 s `state.save()`. Limit dosiahnutý → `MODE_LIMIT`, pauza, obrazovka.
7. Web upload → zápis → `tv.media_changed()` → rescan, toast, prípadne reštart
   prehrávania kanála, ak zmizol aktuálny súbor.

## Odolnosť

- Stav a konfigurácia sa zapisujú atomicky; pri výpadku napájania je na karte
  buď stará, alebo nová verzia, nikdy poškodená.
- Journald len v RAM, swap vypnutý, Wi-Fi power-save vypnutý.
- Pád mpv → automatický reštart a pokračovanie z uloženej pozície.
- Služba `Restart=always`.
- Systém **nie je** read-only (kvôli nahrávaniu na tú istú kartu). Ext4 s
  journalom je v praxi robustný; pre maximálnu istotu pred dlhším odpojením
  použiť *Vypnúť* v menu.

## Bezpečnosť

Zariadenie je určené do domácej siete. Web nemá heslo (podľa požiadavky),
SSH je vypnuté, používateľ `kidtv` má zamknuté heslo. Web rozhranie
neumožňuje spúšťať príkazy ani čítať mimo `media/`; názvy súborov sa čistia
(`safe_filename`).
