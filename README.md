# gameclock-vision

Erkennt Spielzeiten aus abgefilmten Sportuhren und stellt sie anderen Anwendungen über eine HTTP-API, WebSocket und Textausgabe bereit.

Das Projekt entstand beim Einsatz an einer alten LED-Spieluhr während eines Blindenfußballturniers. Ein Netz vor der Anzeige, teilweise verdeckte Lämpchen und die Segmentdarstellung erschwerten die Erkennung mit Standard-OCR. Deshalb verwendet die Anwendung eine eigene Auswertung der einzelnen Siebensegmente und eine zeitliche Stabilisierung der Lesungen.

Ziel sind Anwendungen bei Sportarten wie Fußball, Basketball und Boxen. **Die aktuelle Implementierung unterstützt vierstellige Siebensegmentanzeigen im Format `MM:SS` und einen aufwärtszählenden Uhr-Tracker.** Countdown, zusätzliche Anzeigeformate und sportartspezifische Spielregeln sind noch nicht implementiert. Die getestete Anzeige stammt aus dem Blindenfußball; eine allgemeine Eignung für alle Sportuhren ist damit nicht belegt.

Der Python-Paketname und Startbefehl bleiben für diese Version `tafeluhr`.

## Funktionsweise

1. FFmpeg liest eine Videodatei oder einen Stream, etwa über RTSP, SRT oder HTTP.
2. Ein manuell markiertes Viereck wird perspektivisch auf ein Normbild entzerrt.
3. Der Decoder misst die 28 Segmente der vier Ziffern. Im Rotmodus unterdrückt er weiße und grüne Bildbereiche; alternativ kann die Helligkeit ausgewertet werden.
4. Eine begrenzte Nachführung gleicht kleine Verschiebungen der einzelnen Ziffernfelder aus.
5. Der Tracker bestätigt Lesungen, filtert einzelne Ausreißer und überbrückt fehlende Beobachtungen.
6. Browser, API und WebSocket liefern Uhrzeit, Laufstatus und Herkunft des Werts.

Die Anwendung sucht nicht selbstständig im gesamten Kamerabild nach einer Uhr. Für jede Kameraansicht ist eine passende Kalibrierung erforderlich.

## Installation

Voraussetzungen: Linux, Python 3.10 oder neuer sowie FFmpeg und FFprobe. Für SRT muss der lokale FFmpeg-Build dieses Protokoll unterstützen.

```bash
git clone https://github.com/richtertoralf/gameclock-vision.git
cd gameclock-vision
sudo apt install -y ffmpeg python3-venv
./setup.sh
```

`setup.sh` erstellt `.venv` und installiert die Pakete aus `requirements.txt`.

## Start

RTSP-Beispiel; `SERVER` und `STREAM` durch die tatsächliche Quelle ersetzen:

```bash
.venv/bin/python -m tafeluhr \
  --source 'rtsp://SERVER:8554/STREAM' \
  --config tafeluhr.json \
  --record aufnahmen \
  --log lesungen.csv
```

SRT oder Wiedergabe einer Aufnahme:

```bash
.venv/bin/python -m tafeluhr --source 'srt://SERVER:8890?streamid=read:STREAM'
.venv/bin/python -m tafeluhr --source aufnahmen/beispiel.mkv --loop --config kalibrierung.json
```

Die Weboberfläche ist standardmäßig unter `http://HOST:8090/` erreichbar. Der Server bindet standardmäßig an `0.0.0.0`. Er enthält keine eigene Zugangskontrolle; `--host 127.0.0.1` beschränkt den Zugriff auf den lokalen Rechner.

| Option | Wirkung |
|---|---|
| `--source QUELLE` | Erforderliche Videoquelle oder Datei |
| `--host HOST`, `--port PORT` | Bind-Adresse und Port, standardmäßig `0.0.0.0:8090` |
| `--fps FPS` | Analysebildrate, standardmäßig 10 Bilder pro Sekunde |
| `--size BxH` | Erwartete Eingangsgröße; überspringt FFprobe, skaliert das Bild nicht |
| `--crop B:H:X:Y` | Vorab-Ausschnitt durch FFmpeg; Kalibrierung gilt dann für das zugeschnittene Bild |
| `--config DATEI` | Kalibrierung und Trackerparameter, standardmäßig `tafeluhr.json` |
| `--record ORDNER` | Separate Rohaufzeichnung ohne Neukodierung in ungefähr zehnminütigen MKV-Segmenten |
| `--log DATEI` | CSV-Protokoll der Rohlesungen und Tracker-Ausgaben |
| `--loop` | Endlose Wiedergabe einer Datei |

Eine Aufnahme benötigt eine zusätzliche Verbindung zur Quelle. Der Recorder besitzt keine automatische Speicherbereinigung oder Speicherplatzüberwachung.

## Kalibrierung im Browser

1. Kamera stabil ausrichten und die vier Uhrziffern gut sichtbar abbilden. Fokus, Belichtung und Weißabgleich möglichst konstant halten.
2. Ein Viereck um die vier Uhrziffern ziehen, ohne benachbarte Spielstandsanzeigen. Bei kursiven Ziffern der Schräglage folgen.
3. „Automatisch ausrichten“ starten. Die Suche verwendet mehrere Bilder aus den letzten Sekunden; unterschiedliche Ziffern einer laufenden Uhr helfen bei der Ausrichtung.
4. Messfelder im Debug-Bild kontrollieren. Einzelne Segmente oder ganze Ziffern lassen sich verschieben; der Griff eines Segmentfelds verändert dessen Größe. Pfeiltasten bewegen das ausgewählte Feld, Umschalt vergrößert die Schrittweite.
5. Die ausgegebene Uhrzeit mit der tatsächlichen Anzeige vergleichen, auch bei Stillstand, Wiederanlauf und Minutenwechseln.

Änderungen werden in der Konfigurationsdatei gespeichert. Manuelles Verschieben deaktiviert die automatische Nachführung; das Häkchen aktiviert sie erneut. Größere Kamerabewegungen erfordern eine neue Kalibrierung. „Bild anhalten“ friert die Browserbilder ein, während die Erkennung weiterarbeitet.

Die Nachführung sucht im entzerrten Bild höchstens ±24 Pixel horizontal und ±16 Pixel vertikal. Erfolgreiches Autofit und Änderungen der Rasterparameter ersetzen manuelle Segmentfelder.

## API

| Schnittstelle | Ausgabe |
|---|---|
| `GET /api/state` | Gefilterte Uhrzeit, Laufstatus, Qualitätshinweise und Betriebsmetriken als JSON |
| `GET /api/time.txt` | Nur `MM:SS`, vor der ersten Übernahme `--:--` |
| `WS /ws` | JSON bei Änderungen von Uhrzeit, Laufstatus oder Herkunft; ansonsten ungefähr alle 0,5 Sekunden |
| `GET /api/config` | Kalibrierung, effektive Messfelder, Nachführungsversatz und Bildgrößen |
| `POST /api/config` | Konfigurationsänderungen; `{"reset_clock": true}` setzt den Tracker zurück |
| `POST /api/autofit` | Automatische Ausrichtung starten |
| `GET /api/autofit` | Status und Ergebnis der Ausrichtung |
| `GET /snapshot.jpg` | Aktuelles Kamerabild |
| `GET /debug.jpg` | Entzerrtes Bild mit Diagnosefeldern; `?plain=true` ohne eingezeichnete Felder |

Beispiel eines Zustands:

```json
{
  "time": "15:03",
  "seconds": 903,
  "running": true,
  "source": "board",
  "raw": "15:03",
  "confidence": 0.42,
  "last_board_age_ms": 80,
  "ts": 1791050000.1,
  "fps": 10.0,
  "proc_ms": 12.1,
  "source_connected": true,
  "source_error": ""
}
```

| `source` | Bedeutung |
|---|---|
| `board` | Frische bestätigte Beobachtung, die zum übernommenen Wert passt |
| `predicted` | Keine aktuelle Bestätigung des Ausgabewerts; je nach Trackerzustand Vorhersage oder Beibehalten des Werts |
| `stale` | Alter der bestätigten Beobachtung übersteigt `coast_ms` |
| `none` | Noch kein Wert übernommen |

`raw` ist die letzte Einzellesung, `time` der Trackerwert. `confidence` beschreibt die letzte nichtleere Rohlesung und ist keine kalibrierte Wahrscheinlichkeit für die Richtigkeit von `time`. Integrationen sollten neben `time` auch `source` und `last_board_age_ms` berücksichtigen. Die Textschnittstelle enthält diese Qualitätshinweise nicht.

## Trackerverhalten und aktuelle Grenzen

Standardwerte: 150 ms kurze Bestätigung, 1200 ms Bestätigung eines konstanten abweichenden Werts, 1600 ms Stillstandserkennung und 30 Sekunden bis zur Kennzeichnung als veraltet. Die Werte sind im Browser einstellbar.

Der Tracker kann anhand passender aufwärtslaufender Folgen auch nach Korrekturen wieder einsteigen. Er berücksichtigt dabei bis zu zwei fehlende Sekunden zwischen bestätigten Werten. Stillstand, Reset und Korrekturen benötigen ausreichend lesbare Bilder.

Bekannte Grenzen des übernommenen Stands:

- Countdown wird nicht als gleichwertiger laufender Uhrmodus unterstützt.
- Nach Ablauf von `coast_ms` wird die Ausgabe als `stale` markiert, eine laufende Vorhersage aber weiterhin fortgeschrieben.
- Der Tracker verwendet `confidence` nicht für seine Übernahmeentscheidungen.
- Vollständig verdeckte Segmente und unpassende Kalibrierung können Lesungen verhindern oder falsche Ziffern erzeugen.
- Der Code kennt keine sportartspezifischen Regeln für Halbzeiten, Runden, Auszeiten oder Periodenwechsel.
- Die Zeitstempel des Livebetriebs beziehen sich auf den Empfang der Bilder; Stream- und Overlayverzögerungen müssen bei der Integration berücksichtigt werden.

## Tests und Offline-Auswertung

```bash
.venv/bin/python -B -m unittest tools.test_alignment tools.test_red_tracking tools.test_segments
.venv/bin/python -B tools/test_tracker.py
node tools/test_segment_ui.cjs
```

Der JavaScript-Test benötigt Node.js, aber keine npm-Pakete. Der Tracker-Szenariotest muss separat aufgerufen werden, weil er sich mit `sys.exit` beendet.

Eine vorhandene Aufnahme mit passender Kalibrierung auswerten:

```bash
.venv/bin/python -B tools/eval_offline.py \
  --video aufnahmen/beispiel.mkv \
  --config kalibrierung.json \
  --csv /tmp/auswertung.csv
```

Ohne Referenz-CSV liefert die Offline-Auswertung eine Zeitreihe, keine Genauigkeitsmessung. Synthetisches Testmaterial lässt sich erzeugen und mit seiner Referenz auswerten:

```bash
.venv/bin/python tools/gen_testvideo.py --out /tmp/test.mp4 --seconds 180
.venv/bin/python tools/eval_offline.py --video /tmp/test.mp4 --synthetic 420
```

Für eine laufende Instanz steht zusätzlich eine unabhängige Auswertung ihrer Kamerabilder zur Verfügung:

```bash
.venv/bin/python -B -m tools.eval_live --url http://127.0.0.1:8090 --seconds 20
```

Eine Lesequote misst die Anzahl vollständiger Rohlesungen, nicht deren tatsächliche Richtigkeit.

## Herkunft und Testmaterial

Ausgangspunkt dieses Repositorys ist Commit `840905f` vom 4. Oktober 2026 aus dem bisherigen Projekt `tafeluhr`. Die ursprüngliche Git-Historie bleibt erhalten. Die Umbenennung des Repositorys verändert die Erkennungslogik nicht.

Die vorhandenen Turnierunterlagen liegen unter [docs/turnier-2026-10-04](docs/turnier-2026-10-04/). Dort sind Kalibrierungen, Aufnahmeinventar und Diagnosebilder archiviert. Der [Turnierabschlussbericht](docs/turnierabschluss-2026-10-04.md) dokumentiert den damaligen Betrieb; der [Architekturaudit](docs/architektur-und-plausibilitaetsaudit-2026-10-04.md) beschreibt Grenzen und mögliche Weiterentwicklungen. Historische Angaben zu Sicherungsorten oder früheren Arbeitsständen sind keine aktuellen Installationsanweisungen.

**Acht echte Videoausschnitte sind über Git LFS enthalten:** insgesamt 22:20 Minuten (rund 960 MiB), mit Stopps, Wiederanläufen, Minutenwechseln und Rücksetzungen. [Auswahl, Download und Kalibrierungen](testdata/README.md) sowie [Herkunft und Prüfsummen](testdata/manifest.json) sind dokumentiert. Nach dem Klonen `git lfs install` und `git lfs pull` ausführen. Die historischen Kalibrierungen sind teilweise Ausgangspunkte; vollständige Referenzzeiten pro Frame liegen noch nicht vor.

## Projektstruktur

```text
tafeluhr/decoder.py       Perspektivische Entzerrung und Segmenterkennung
tafeluhr/alignment.py     Begrenzte Ziffernnachführung
tafeluhr/autofit.py       Automatische Geometrieoptimierung
tafeluhr/tracker.py       Zeitliche Stabilisierung
tafeluhr/source.py        FFmpeg-Quelle und Recorder
tafeluhr/app.py           Webserver, API und Startparameter
tafeluhr/static/          Kalibrieroberfläche
tools/                    Tests, Testvideoerzeugung und Auswertungen
docs/                     Audit und archivierte Turnierbefunde
```
