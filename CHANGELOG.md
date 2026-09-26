# Zmeny

Každá verzia má vlastnú sekciu `## vX.Y.Z`. Jej text sa pri vydaní použije ako
popis vydania na GitHube a telka ho ukáže na webe pod „Čo je nové“.

## v0.2.7

- **Tlačidlo ⏻ už nevypína celé Raspberry Pi.** Systém ho doteraz bral aj ako
  „vypni počítač“, takže sa telka potom nedala tlačidlom zapnúť. Teraz ⏻ len
  uspí telku a ďalšie stlačenie ju zobudí.
- **Úspornejšia pohotovosť:** 20 s po „Dobrú noc“ sa vypne HDMI signál (aj
  televízor bez HDMI-CEC tak zvyčajne sám zaspí) a procesor prejde na najnižší
  takt. Po zobudení rozprávka pokračuje tam, kde skončila.
- Oprava: keď sa prehrávač po chybe sám znova spustil, telka odvtedy
  spracúvala každú udalosť dvakrát (napr. na konci epizódy mohla preskočiť
  o dve).

## v0.2.6

- **Nahrať všetko naraz** (Kanály): pusti súbory z viacerých seriálov, telka
  z názvov zistí seriál, sériu a epizódu, odstráni prípony ako SK, CZ dabing,
  1080p či [STEiNO] a navrhne kanály. Existujúci kanál s rovnakým názvom
  predvolí, pri súboroch bez názvu seriálu sa spýta. Nič sa nepresunie, kým
  návrh nepotvrdíš; súbory dostanú názvy ako `S01E03 - Gramofon.mp4`, aby išli
  v poradí epizód. Čo už v kanáloch je, preskočí.
- **Pozadia**: Vesmír, Dinosaury, Hasiči, Dážďovky, Havinkovia (alebo
  Hviezdičky) v menu, na obrazovkách telky aj na webe. Mení sa v menu
  *Pozadie* alebo na webe v Nastaveniach.
- **Stavový riadok**: po každom stlačení na chvíľu ukáže, čo telka urobila
  (napr. „Hore › Kanál 2 · Bluey“), pri neznámom tlačidle jeho kód. Dá sa
  vypnúť v menu aj na webe.
- Menu sa otvára na **Späť k rozprávke**, takže sa z neho dá vždy odísť
  tlačidlom OK. Tlačidlo Domov funguje všade tam, kde Späť.
- **Aktualizácia v menu**: kontrola sa ukáže na celej obrazovke; keď je nová
  verzia, hneď sa spýta s predvoleným Áno. Každá kontrola sa zapíše do
  záznamu aj s dôvodom, prečo zlyhala.

## v0.2.5

- **Oprava prehrávania na Raspberry Pi.** Novší prehrávač mpv v systéme telky
  zmenil poradie parametrov pri spúšťaní súboru, takže sa rozprávky vôbec
  nepúšťali. Presne toto spôsobovalo aj „Nahrávanie zlyhalo“ (súbor sa uložil,
  ale hneď potom zlyhalo jeho spustenie), chybu 500 pri ▶ na webe, čiernu
  obrazovku a telku, ktorá sa po zapnutí dokola reštartovala.
- Ak sa niektorý súbor predsa nedá prehrať, telka ukáže hlásenie a pás
  s kanálom, ale nespadne – web ostane dostupný a súbor sa dá zmazať.

## v0.2.4

- Nahrávanie na webe (Kanály) teraz zvládne aj veľa súborov do viacerých
  kanálov naraz: pretiahneš ich všade, kde treba, a nahrávajú sa jeden po
  druhom, kanál po kanáli, bez čakania pri obrazovke.
- Ak sa nahrávanie preruší, súbory, ktoré sa už nahrali, telka pri opätovnom
  pretiahnutí rozpozná podľa názvu a preskočí – nemusia sa posielať znova.

## v0.2.3

- Vypnutie a zapnutie počas sprievodcu prvým zapnutím (tlačidlom ⏻ alebo
  televízorom) ho už nepreskočí: telka sa vráti na stránku, kde bola. Predtým
  sa takto preskočený sprievodca ukázal znova pri ďalšom zapnutí telky.

## v0.2.2

- Rovnaký obsah ako v0.2.1, vydaný znova po upratovaní histórie repozitára.
  Telka s v0.2.1 nemusí nič robiť, nová verzia len nahradí predchádzajúcu.

## v0.2.1

- Nová telka už nemá predvolené meno dieťaťa: sprievodca sa naň spýta a telka
  sa podľa neho pomenuje. Na už nastavenej telke ostáva meno aj názov tak, ako sú.
- Wi-Fi sieť telky pri nastavovaní cez mobil sa predvolene volá rovnako ako telka.
- Obrazovky „Dobrú noc“ a denný limit fungujú aj bez mena.

## v0.2.0

- **Aktualizácie bez vyťahovania karty.** Na webe v časti *Systém → Aktualizácia*
  alebo v menu telky (*Aktualizácia*) telka stiahne novú verziu, nainštaluje ju
  a reštartuje sa. Trvá to asi minútu, rozprávky, nastavenia aj fotka ostanú.
- Ak by nová verzia nenaštartovala, telka sa sama vráti na predchádzajúcu.
  Predchádzajúcu verziu sa dá vrátiť aj ručne (web aj menu).
- Raz denne telka skontroluje, či je nová verzia, a na webe ukáže upozornenie.
  Inštaluje sa vždy až po potvrdení. Kontrola sa dá vypnúť v nastaveniach.
- Aktualizácia už nevytvára znova zmazané kanály a nerobí upgrade celého systému.

## v0.1.0

- Prvé vydanie: kanály z priečinkov, pokračovanie tam, kde sa skončilo,
  slovenský zvuk, hudobný kanál, denný limit, web rozhranie, sprievodca,
  nastavenie Wi-Fi cez mobil, obraz na SD kartu.
