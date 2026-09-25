# kid-tv · detská telka

Detský „televízor“ pre Raspberry Pi. Rozprávky nahráš do priečinkov
**kanal1, kanal2, kanal3…**, každý priečinok je jeden kanál a dieťa medzi nimi
prepína diaľkovým ovládačom ako na skutočnej telke. Žiadne menu, žiadne
odporúčania, žiadny internet – len kanály, hlasitosť a tlačidlo vypnúť.

- **Zapne sa tam, kde skončila.** Každý kanál si pamätá epizódu aj presné miesto,
  pri vypnutí aj pri vytiahnutí zo zásuvky.
- **Takmer akýkoľvek formát** (mp4, mkv, avi, mov, wmv, mpg, webm, mp3…), nič sa
  nekonvertuje – prehráva mpv s hardvérovým dekódovaním.
- **Slovenský zvuk automaticky**, keď má film viac zvukových stôp (fallback
  angličtina, poradie je nastaviteľné).
- **Hudobný kanál** – priečinok s mp3 sa hrá s peknou obrazovkou s fotkou dieťaťa.
- **Denný limit** (predvolene 60 min) s obrazovkou „na dnes je to všetko“; rodič
  vie pridať čas z telky alebo z webu.
- **Web rozhranie** na mobile či počítači: nahrávanie rozprávok pretiahnutím,
  kanály, nastavenia, Wi-Fi, fotka a meno dieťaťa, ovládanie na diaľku.
- **Sprievodca pri prvom zapnutí** – jazyk, Wi-Fi (aj nastavenie cez mobil),
  meno dieťaťa, adresa webu. Ľahko sa presunie do hotela či k babke.
- **Aktualizácie tlačidlom** na webe alebo v menu, bez vyťahovania karty; ak
  nová verzia nenaštartuje, telka sa sama vráti na predchádzajúcu.
- **Personalizácia** – meno a fotka dieťaťa sú na úvodnej obrazovke, pri
  prepínaní kanálov, na hudobnom kanáli, na obrazovke dobrú noc aj vo webe.

Dokumentácia: [hardvér a nákupný zoznam](docs/hardware.md) ·
[architektúra](docs/architecture.md) · [vývoj a zostavenie obrazu](docs/development.md)

---

## 1. Čo kúpiť

Raspberry Pi 4 (2 GB), oficiálny zdroj, krabička, micro-HDMI kábel, microSD
karta 128 GB a 2,4 GHz ovládač G10S (alebo ovládač televízora cez HDMI-CEC).
Presné odkazy a ceny: **[docs/hardware.md](docs/hardware.md)**.

## 2. Zápis obrazu na SD kartu

Pre Raspberry Pi sa nepoužíva `.iso`, ale `.img`. Hotový obraz
`kid-tv-vX.Y.Z.img.xz` je v sekcii **Releases** tohto repozitára (zostavuje sa
automaticky v GitHub Actions, pozri `docs/development.md`). Kartu treba
zapisovať len pri prvej inštalácii, ďalšie verzie sa inštalujú tlačidlom
(sekcia 8).

1. Stiahni a nainštaluj **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)**
   (Windows, macOS, Linux).
2. Vlož microSD kartu do počítača (cez čítačku alebo SD adaptér z balenia).
3. V Imageri:
   - **Raspberry Pi Device** → *Raspberry Pi 4*
   - **Operating System** → posuň úplne dole → **Use custom** → vyber stiahnutý
     súbor `kid-tv-….img.xz` (netreba rozbaľovať).
   - **Storage** → tvoja microSD karta.
   - **Next** → pri otázke *Would you like to apply OS customisation settings?*
     zvoľ **No** (všetko sa nastavuje sprievodcom v telke). Potvrď zápis.
4. Po dokončení kartu vyber, vlož do Raspberry Pi, pripoj HDMI do televízora,
   USB prijímač ovládača a nakoniec napájanie.

Alternatíva pre pokročilých: [balenaEtcher](https://etcher.balena.io/) alebo
`xzcat kid-tv.img.xz | sudo dd of=/dev/sdX bs=4M status=progress`.

Overenie súboru: pri obraze je `*.sha256` – `sha256sum -c kid-tv-….img.xz.sha256`.

## 3. Prvé zapnutie – sprievodca

Telka nabootuje asi za 20 sekúnd a spustí sprievodcu. Ovládaš ho šípkami a OK.

1. **Vitaj** – OK.
2. **Jazyk** – slovenčina / angličtina.
3. **Wi-Fi** – vyber domácu sieť a napíš heslo klávesnicou na obrazovke,
   alebo zvoľ **Nastaviť cez mobil**: telka vytvorí vlastnú Wi-Fi sieť
   s názvom telky (napr. *Annina telka*), pripojíš sa na ňu mobilom (alebo naskenuješ QR kód),
   otvoríš `http://kid.tv` a heslo napíšeš na mobile. Kábel do routera funguje
   bez nastavovania. Wi-Fi sa dá aj preskočiť – rozprávky idú aj bez siete.
4. **Meno dieťaťa** – podľa mena sa telka pomenuje (*Anna → Annina telka*).
5. **Adresa webu** – ukáže `http://kid.local` (a IP adresu) s QR kódom.
6. **Hotovo** – zapne sa kanál 1.

Sprievodca sa dá kedykoľvek spustiť znova z nastavení. Kým nedôjde po **Hotovo**,
ukáže sa pri každom zapnutí znova (vypnutie tlačidlom ⏻ ho len preruší).
Rozprávky, kanály ani miesto, kde sa skončilo, sa ním nemažú.

## 4. Nahrávanie rozprávok

Na mobile alebo počítači **na tej istej Wi-Fi** otvor **http://kid.local**
(alebo IP adresu, ktorú telka ukazuje v *Nastavenia → Webová adresa*).

- **Kanály → Nahrať všetko naraz**: pretiahni sem súbory aj z viacerých
  seriálov. Telka z názvov zistí seriál, sériu, epizódu a názov
  (`Pat+a+Mat+-+S1E3+Gramofon+SK.mp4` → kanál *Pat a Mat*, súbor
  `S01E03 - Gramofon.mp4`), odstráni prípony ako SK, CZ dabing, 1080p, [STEiNO]
  a ukáže **návrh**: ktoré súbory pôjdu do ktorého kanála, existujúci kanál
  s rovnakým názvom predvolí. Názvy môžeš prepísať, súbory odškrtnúť. Tie, pri
  ktorých z názvu nevie seriál, dá do „Kam s týmito?“ a spýta sa. Nič sa
  nepresunie, kým nedáš **Roztriediť**. Súbory, ktoré už v kanáloch sú,
  preskočí.
- **Kanály** → *Nový kanál* (napr. „Maťko a Kubko“) → do rámčeka pretiahni
  súbory alebo klikni a vyber. Priebeh nahrávania vidíš pri každom súbore,
  po dokončení sa kanál v telke sám obnoví.
- Poradie epizód je podľa názvu súboru – ak chceš pevné poradie, pomenuj ich
  `01 …`, `02 …`, `03 …`. Po poslednej epizóde kanál začne od prvej.
- Dá sa naraz pretiahnuť veľa súborov do viacerých kanálov – nahrávajú sa
  jeden po druhom (kanál po kanáli), takže netreba pri tom čakať. Ak sa
  nahrávanie preruší (strata siete, zavretá stránka), stačí tie isté súbory
  pretiahnuť znova – tie, čo sa už nahrali, telka rozpozná podľa názvu a
  preskočí ich.
- Priečinok s **mp3** sa stane hudobným kanálom.
- **Nastavenia** → fotka dieťaťa (oreže sa do kruhu), meno, názov telky, jazyk,
  denný limit, maximálna hlasitosť, poradie jazykov zvuku, rodičovský PIN.
- **Prehľad** → čo práve hrá, koľko sa dnes pozeralo, ovládanie z webu
  (funguje aj keď sa ovládač stratí).

> **Prečo nie `https://kid.tv`?** Adresa `kid.tv` funguje len počas
> nastavovania cez hotspot telky, keď je telka sama routerom. Na domácej sieti
> prekladá mená router, ktorý o `kid.tv` nevie, preto sa používa `kid.local`
> (mDNS – funguje na iPhone, Androide 12+, Windows 10+ aj macOS). HTTPS by na
> lokálnej sieti vyžadoval certifikát, ktorému by mobil neveril a pri každom
> otvorení by hlásil chybu, takže web beží na HTTP. Ak router vie nastaviť
> lokálne DNS (Mikrotik, OpenWrt, Fritz!Box, UniFi), pridaj záznam
> `kid.tv → IP telky` a `http://kid.tv` bude fungovať aj doma.

## 5. Ovládanie

| Tlačidlo | V telke |
|----------|---------|
| šípka hore / dole, CH+/CH− | ďalší / predchádzajúci kanál (pokračuje, kde skončil) |
| šípka vľavo / vpravo, ⏮ ⏭ | predchádzajúca / ďalšia epizóda |
| OK, ⏯ | pauza / pokračovať (zobrazí pruh s názvom) |
| hlasitosť +/−, stlmiť | hlasitosť (strop v nastaveniach) |
| čísla | priamo kanál 1–99 |
| späť / info / domov | ukázať alebo skryť pruh s informáciami |
| **MENU podržať 1,5 s** | nastavenia (voliteľne za rodičovským PINom) |
| ⏻ zapnúť/vypnúť | pohotovostný režim „Dobrú noc“ – cez HDMI-CEC vypne aj televízor; znova zapne tam, kde skončila |

Vytiahnutie zo zásuvky je v poriadku: pozícia sa ukladá každých pár sekúnd.
Pred dlhším odpojením je slušné použiť *Nastavenia → Vypnúť*.

**HDMI-CEC:** ak to televízor podporuje (Anynet+, Simplink, Bravia Sync,
EasyLink…), fungujú tlačidlá TV ovládača a zapnutie televízora prebudí telku.

**Iný ovládač:** *Nastavenia → Naučiť ovládač* (alebo web → Ovládač) – telka sa
postupne spýta na každé tlačidlo.

## 6. Nastavenia v telke (podržať MENU)

Späť k rozprávke · Jazyk · Meno dieťaťa · Názov telky · Wi-Fi · Nastavenie cez mobil ·
Denný limit (vypnuté – 15 – 240 min) · Pridať 30 min na dnes · Vynulovať dnešný čas ·
Maximálna hlasitosť · Pozadie · Stavový riadok · Naučiť ovládač · Webová adresa (s QR) ·
Znovu načítať rozprávky · Spustiť sprievodcu · Aktualizácia · Vrátiť verziu (keď je
k dispozícii) · Reštartovať · Vypnúť · O telke.

- Menu sa otvára na **Späť k rozprávke** – OK ho hneď zavrie, aj keď tlačidlo
  Späť na ovládači nefunguje.
- **Pozadie**: Vesmír, Dinosaury, Hasiči, Dážďovky, Havinkovia alebo Hviezdičky
  (šípkami vľavo/vpravo). Rovnaké pozadie má aj web.
- **Stavový riadok**: po každom stlačení na chvíľu ukáže, čo telka urobila
  (napr. „Hore › Kanál 2 · Bluey“). Pri tlačidle, ktoré telka nepozná, ukáže
  jeho kód – vtedy ho priraď v *Naučiť ovládač*. Dá sa vypnúť aj na webe
  (Nastavenia).
- **Aktualizácia**: OK skontroluje GitHub; ak je nová verzia, hneď sa spýta
  (predvolené Áno). Keď kontrola zlyhá, ukáže prečo a zapíše to do záznamu.

## 7. Presun inam (hotel, babka)

1. Odpoj telku, zober HDMI kábel, zdroj a USB prijímač ovládača.
2. Po zapnutí sa telka pokúsi pripojiť na známe Wi-Fi. Ak žiadnu nenájde,
   **rozprávky idú aj tak** – iba web nie je dostupný.
3. Na novú Wi-Fi: podrž MENU → *Wi-Fi* (heslo klávesnicou) alebo *Nastavenie cez
   mobil* (hotspot + `http://kid.tv` na mobile). V hoteli s prihlasovacou
   stránkou býva jednoduchšie pripojiť sa káblom, alebo Wi-Fi vôbec neriešiť.

## 8. Aktualizácie

Nová verzia sa inštaluje **bez vyťahovania karty**. Rozprávky, nastavenia aj
fotka ostanú.

- **Web:** *Systém → Aktualizácia → Aktualizovať na X.Y.Z*. Keď je nová verzia
  vonku, upozornenie sa ukáže hore na každej stránke webu.
- **Telka:** podrž MENU → *Aktualizácia* → OK → *Áno*.

Telka stiahne balík z GitHubu (skontroluje jeho kontrolný súčet), na obrazovke
ukáže priebeh, nainštaluje ho a reštartuje sa. Trvá to asi minútu. Ak by nová
verzia nenaštartovala, **telka sa sama vráti na predchádzajúcu** a po
reštarte to oznámi. Predchádzajúca verzia sa dá vrátiť aj ručne (*Vrátiť na
verziu …* na webe aj v menu). Raz denne telka sama pozrie, či je nová verzia
(len pozrie, inštaluje sa vždy až po potvrdení; vypína sa v nastaveniach).

Aktualizácie sťahuje z verejného repozitára `jano-g/kid-tv`, takže repozitár
musí byť **verejný**. Nový obraz karty je potrebný len pri veľkej zmene
systému (napríklad nová verzia Raspberry Pi OS).

### Jednorazovo: prechod z verzie 0.1.0

Verzia 0.1.0 ešte nevie aktualizovať sama, preto prvý prechod na 0.2.0 ide cez
SSH. Robí sa to raz, ďalšie verzie už tlačidlom.

1. Vypni telku (MENU → *Vypnúť*), vytiahni microSD kartu a vlož ju do počítača.
2. Na karte sa ukáže disk **bootfs**. Vytvor na ňom prázdny súbor s názvom
   `ssh` (vo Windows kľudne `ssh.txt`). Kartu bezpečne vysuň a vráť do telky.
3. Zapni telku. Na počítači v tej istej Wi-Fi otvor terminál (Windows:
   PowerShell, Mac: Terminal) a napíš:
   ```bash
   ssh kidtv@kid.local
   ```
   Heslo je `kidtv` (pri písaní sa nezobrazuje). Ak `kid.local` nejde, použi IP
   adresu z *Nastavenia → Webová adresa*.
4. Spusti aktualizáciu (heslo pre `sudo` je znova `kidtv`):
   ```bash
   curl -fsSL https://raw.githubusercontent.com/jano-g/kid-tv/main/scripts/update.sh | sudo bash
   ```
   Telka sa na chvíľu vypne a naštartuje už vo verzii 0.2.0. Skript na konci
   napíše, ako to dopadlo.
5. SSH potom znova vypni (alebo si aspoň zmeň heslo príkazom `passwd`):
   ```bash
   sudo systemctl disable --now ssh
   ```

Ten istý príkaz zo 4. kroku je aj záchranná cesta, keby web niekedy nešiel.

## 9. Riešenie problémov

| Problém | Čo skúsiť |
|---------|-----------|
| Čierna obrazovka po zapnutí | Skús druhý HDMI port RPi (ten bližšie k USB-C napájaniu je HDMI0 – použi ten). Zapni TV skôr ako telku. |
| Nejde zvuk | TV: vstup HDMI musí mať zvuk z HDMI (nie ARC/optika). Pokročilí: `/etc/kidtv/mpv.conf` – riadok `audio-device=…`. |
| Ovládač nereaguje | Zasuň USB prijímač do iného portu, vymeň batérie. Klávesnica funguje vždy (šípky, Enter, Esc, +/−, medzerník). |
| Po zapnutí je znova sprievodca | Nebol dokončený po **Hotovo** (vo verzii 0.2.2 a staršej ho preskočilo vypnutie a zapnutie tlačidlom ⏻). Prejdi ho do konca – Wi-Fi a meno ostanú, rozprávky sa nemažú. |
| Kanál je prázdny | Súbory idú do `kanal1`, `kanal2`… cez web. Podporované prípony sú vypísané pri nahrávaní. |
| Film trhá | Spravidla 4K alebo veľmi vysoký dátový tok – RPi 4 zvláda 1080p. Prekonvertuj na 1080p H.264 (HandBrake). |
| Zabudnutý PIN | Web → Nastavenia → Rodičovský PIN → vymazať. |
| Nedá sa otvoriť `kid.local` | Použi IP adresu (v telke: *Nastavenia → Webová adresa*). Mobil musí byť na rovnakej Wi-Fi ako telka, nie na mobilných dátach. |
| Potrebujem SSH alebo terminál | Systémový používateľ je `kidtv` s heslom `kidtv`. SSH je vypnuté; zapneš ho prázdnym súborom `ssh` (alebo `ssh.txt`) na disku `bootfs` na karte, potom `ssh kidtv@kid.local`. Heslo si zmeň (`passwd`). |
| Aktualizácia zlyhala | Telka sa vráti na pôvodnú verziu sama. Podrobnosti: web → *Systém → Aktualizácia → Záznam aktualizácií*. Najčastejšie chýba internet. |
| Na webe „repozitár nenájdený“ | Repozitár `jano-g/kid-tv` na GitHube musí byť verejný (*Settings → General → Change visibility*). |

## 10. Ako to funguje

Raspberry Pi OS Lite (bez desktopu) → služba `kidtv` (Python) spustí **mpv**,
ktorý kreslí priamo na HDMI cez DRM. Všetka grafika telky (pruhy, menu,
sprievodca) sú obrázky, ktoré aplikácia kreslí Pillow a vkladá do mpv ako
overlay. Ovládač sa číta cez Linux `evdev` (čokoľvek, čo je „klávesnica“),
HDMI-CEC cez `cec-client`. Web beží v tom istom procese (aiohttp) na porte 80.
Wi-Fi rieši NetworkManager (`nmcli`), hotspot pre nastavenie cez mobil je
NetworkManager v režime *shared* s DNS, ktorý všetko smeruje na telku
(preto funguje `kid.tv`). Stav (kanál, pozície, dnešný čas) je v
`/var/lib/kidtv/state.json`, nastavenia v `config.json`, rozprávky v
`/var/lib/kidtv/media/kanalN/`. Aktualizácie sú balíky z GitHub Releases, ktoré
nainštaluje `scripts/apply-update.sh` mimo bežiacej služby, so zálohou a
automatickým návratom. Podrobnosti: [docs/architecture.md](docs/architecture.md).

## Licencia

MIT. Fonty Fredoka a Nunito sú pod licenciou SIL Open Font License
(`kidtv/assets/fonts/OFL-*.txt`).
