# Tafeluhr

Liest die Spieluhr (MM:SS) einer LED-Anzeigetafel aus einem Videostream – auch durch ein Netz vor der Tafel – und stellt sie als JSON, WebSocket und Text für eigene Programme und Overlays bereit.

Kein OCR, sondern ein Segment-Decoder: 4 Ziffern × 7 Segmente werden einzeln auf „leuchtet rot / leuchtet nicht“ geprüft. Darüber liegt eine Uhrlogik, die Fehllesungen filtert und kurze Verdeckungen überbrückt.

## Einrichtung (Linux-VM)

```bash
sudo apt install -y ffmpeg python3-venv
./setup.sh
```

## Start

```bash
# SRT von MediaMTX (Pfad anpassen)
.venv/bin/python -m tafeluhr --source 'srt://MEDIAMTX:8890?streamid=read:tafel' \
    --record aufnahmen --log lesungen.csv

# oder RTSP von MediaMTX (--size spart den ~10-s-ffprobe beim Start)
.venv/bin/python -m tafeluhr --source rtsp://MEDIAMTX:8554/tafel --size 1920x1080 \
    --record aufnahmen --log lesungen.csv
```

Web-Oberfläche: `http://<vm>:8090/`

| Option | Zweck |
|---|---|
| `--record DIR` | Rohaufzeichnung des Streams (`-c copy`, 10-min-Dateien) – **morgen unbedingt an**, das ist das Testmaterial für später |
| `--log DATEI` | CSV mit jeder Lesung (Rohwert, Grund bei Fehlschlag, Ausgabe) |
| `--fps 10` | Analyse-Framerate. 10 reicht; mehr = genauerer Sekundenwechsel, mehr CPU |
| `--crop B:H:X:Y` | Ausschnitt schon in ffmpeg – bei 4K spart das viel CPU |
| `--config` | Kalibrierung, Standard `tafeluhr.json` (wird beim Ändern gespeichert) |

## Ablauf morgen (ca. 15–30 min)

1. **Kamera** ausrichten. Die Tafel sollte im Bild **mindestens ~350 px breit** sein (getestet: 420 px sehr gut, 260 px geht noch). Fokus, Belichtung und Weißabgleich **manuell** fixieren. Belichtung eher knapp: Die LEDs dürfen nicht zu einem roten Brei überstrahlen.
2. **Starten** (siehe oben), Browser öffnen. Oben muss „Stream verbunden“ stehen.
3. **Rechteck ziehen**: um die 4 Uhrziffern, ohne die Tore, lieber etwas zu groß. Kursiv ist egal.
4. **„Automatisch ausrichten“** drücken (~15–25 s). Am besten bei *laufender* Uhr: Dann sieht die Suche verschiedene Sekundenziffern und prüft, ob die Folge plausibel ist.
5. **Kontrolle im Debug-Bild**: Die Kästen müssen auf den LED-Segmenten sitzen (grün = an, rot = aus), oben links steht der gelesene Wert. Wenn eine Ziffer danebenliegt, mit den Schiebereglern nachjustieren oder Rechteck korrigieren und erneut automatisch ausrichten.
6. Dein Programm an `/api/state` oder `/ws` hängen.

Falls die Erkennung nicht stabil wird: einfach mit `--record` weiterlaufen lassen. Die Aufnahme lässt sich danach beliebig oft durchspielen (siehe unten).

## Schnittstellen

- `GET /api/state` – JSON
- `GET /api/time.txt` – nur `MM:SS` (z. B. vMix/OBS-Textquelle)
- `WS /ws` – JSON-Push bei jeder Änderung, sonst alle 0,5 s

```json
{"time": "15:03", "seconds": 903, "running": true, "source": "board",
 "raw": "15:03", "confidence": 0.42, "last_board_age_ms": 80, "ts": 1791050000.1,
 "fps": 10.0, "proc_ms": 2.1, "source_connected": true, "source_error": ""}
```

| `source` | Bedeutung |
|---|---|
| `board` | Wert direkt von der Tafel gelesen (bestätigt) |
| `predicted` | Tafel gerade nicht lesbar (Spieler davor, Stream weg) – Uhr zählt ab letztem Sekundenwechsel weiter |
| `stale` | > 30 s keine Lesung – Wert nicht mehr verlässlich |
| `none` | noch kein Wert |

`raw` ist die letzte Einzellesung (kann flackern), `time` die gefilterte Uhr – im Overlay immer `time` verwenden.

## Verhalten der Uhrlogik

- Neuer Wert = alter + 1 s → sofort übernommen, Uhr „läuft“.
- Einstieg in eine schon laufende Uhr: nach ~2 Sekundenwechseln erkannt.
- Uhr angehalten → nach 1,6 s `running: false`. Die Anzeige läuft dabei nie über den Tafelwert hinaus.
- Korrektur am Bedienteil oder Halbzeit-Reset (Sprung) → nach 1,2 s übernommen.
- Einzelne Fehllesungen werden ignoriert; Verdeckung → Weiterzählen.
- Alle Zeiten sind im Web-UI unter „Feintuning“ einstellbar.

**Verzögerung im Overlay:** Die Erkennung sollte nah an der Kamera laufen (auf dem MediaMTX-Pfad der Kamera, nicht auf dem fertigen Programmsignal). Wenn das Programmbild verzögert ausgespielt wird, das Overlay um dieselbe Zeit verzögern.

## Nachbereitung: Aufnahme offline auswerten

```bash
# Live-Oberfläche auf eine Aufnahme (Echtzeit, endlos)
.venv/bin/python -m tafeluhr --source aufnahmen/tafel_....mkv --loop --config tafeluhr.json

# Ganze Aufnahme schnell durchrechnen -> Zeitreihe als CSV
.venv/bin/python tools/eval_offline.py --video aufnahmen/tafel_....mkv --config tafeluhr.json --csv auswertung.csv
```

## Testen ohne Kamera

```bash
.venv/bin/python tools/gen_testvideo.py --out test.mp4 --seconds 180            # Tafel 420 px, Netz, Wind, Verdeckung, Pause, Korrektur, Halbzeit
.venv/bin/python tools/eval_offline.py --video test.mp4 --synthetic 420          # Trefferquote gegen Ground Truth
.venv/bin/python tools/test_tracker.py                                           # Uhrlogik-Szenarien
.venv/bin/python -m tafeluhr --source test.mp4 --loop                            # Web-UI ausprobieren
```

Testergebnisse (synthetisch, 6-mm-Netz 30 cm vor 1-cm-LEDs, Kamera ~40 m, automatisch ausgerichtet):

| Tafel im Bild | Rohlesung korrekt | Falschlesungen | Ausgabe exakt* |
|---|---|---|---|
| 420 px | 98 % | 0 | 97 % |
| 260 px | 92 % | 15 Frames (von 1800, gefiltert) | 96 % |

\* Die restlichen Abweichungen liegen ausschließlich in den 1,2-s-Bestätigungsfenstern nach Korrektur/Reset und im Start/Stopp-Erkennungsfenster. Das echte Foto der Tafel (15:03) wird nach automatischer Ausrichtung aus grob gezogenen Rechtecken korrekt gelesen.

## Dateien

```
tafeluhr/decoder.py   Entzerrung, Rotfilter, Segmentmessung, Ziffernerkennung
tafeluhr/autofit.py   automatische Ausrichtung (Schräge, Höhe, Ziffernlage)
tafeluhr/tracker.py   Uhrlogik
tafeluhr/source.py    ffmpeg-Eingang mit Reconnect, Rohaufzeichnung
tafeluhr/app.py       Web-Server, API, CLI
tafeluhr/static/      Web-Oberfläche
tools/                Testvideo-Generator, Offline-Auswertung, Tests
```
