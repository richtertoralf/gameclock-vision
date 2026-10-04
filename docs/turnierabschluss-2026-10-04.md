# Turnierabschluss und Wiederaufnahme

Stand: 2026-10-04, 12:23 UTC. Turnier beendet; Aufnahme und Erkennung sollen ausgeschaltet bleiben.

## Abschaltung

Der Recorder wurde am 04.10.2026 um 12:22 UTC beendet. Der Webprozess war bei der eigentlichen Abschaltung bereits beendet, die API nicht mehr erreichbar. Es liefen keine FFmpeg-Kinder mehr. Anschließend waren keine Tafeluhr-/Recorder-/FFmpeg-Prozesse mehr vorhanden und Port 8090 geschlossen. Details: [shutdown.json](turnier-2026-10-04/shutdown.json).

Der Kamerapfad lieferte zuletzt RTSP 404; der Recorder hatte Wiederverbindungen versucht. Die letzte Aufnahme endete daher bereits vor der Abschaltung. Es wurde kein Dienst zum automatischen Neustart eingerichtet.

## Datenbestand und Sicherung

- `aufnahmen/`: 55 MKV-Dateien, davon 26 nichtleer mit insgesamt 9.713.965.470 Bytes. Die von ffprobe gemeldeten Laufzeiten summieren sich auf etwa 3 h 27 min; dies ist keine Aussage über lückenlose Abdeckung des Turniers.
- Alle 26 nichtleeren Dateien ließen sich mit ffprobe ohne gemeldeten Fehler öffnen. Das ist eine Container-/Metadatenprüfung, keine vollständige Dekodierung sämtlicher Videoframes.
- 29 leere Dateien bleiben unverändert erhalten. Sie stammen aus dem Zeitraum der Speicherplatzfehler und enthalten kein Video. Auch kurze und möglicherweise unvollständige Aufnahmen werden nicht gelöscht oder überschrieben.
- Letzte Datei: `aufnahmen/tafel_20261004_121039.mkv`, 422.864.503 Bytes, gemeldete Dauer 564,183 Sekunden, H.264, 1920×1080.
- `lesungen.csv` bleibt unverändert erhalten. Die letzte Zeile ist abgeschnitten. Nach dem Neustart lief die Erkennung ohne `--log`; für diese Phase gibt es kein vollständiges CSV-Lesungsprotokoll.
- Aktuelle Kalibrierung: `tafeluhr.json`; zusätzliche Kopie: [kalibrierung-final.json](turnier-2026-10-04/kalibrierung-final.json).
- Gesichert wurden außerdem die vorherige Kalibrierung, Diagnosebilder, Recorder-Log, Git-Status, Patch der bereits versionierten Änderungen, HEAD und Python-Abhängigkeiten in [turnier-2026-10-04/](turnier-2026-10-04/).
- Vollständige lokale Sicherung des Repository-Verzeichnisses einschließlich Aufnahmen, CSV, unversionierter Dateien, `.git` und `.venv` unter `/home/tori/backups/tafeluhr-2026-10-04/`. Dort liegen auch Prüfsummen und das Sicherungsprotokoll. Diese Sicherung liegt auf demselben Datenträger; eine externe Kopie wurde nicht erstellt.

Das [Aufnahmeinventar](turnier-2026-10-04/aufnahme-inventar.json) enthält Größen, Laufzeiten und Prüfergebnisse pro Datei. Es wurde nichts committed oder gepusht; alle vorherigen lokalen Änderungen bleiben erhalten.

### Nachtrag: Freigabe zur Versionierung

Nach der Sicherung wurde ausdrücklich beauftragt, alle Repository-Änderungen zu committen und nach GitHub (`richtertoralf/tafeluhr`, Branch `main`) zu pushen. Die obige Beschreibung und die gesicherten Git-Diagnosedateien dokumentieren den Stand **vor** diesem Auftrag. Videos, CSV, virtuelle Umgebung und andere durch `.gitignore` ausgeschlossene Laufzeitdateien bleiben im vollständigen lokalen Backup.

Prüfung vor dem Commit: 15 Tests aus `tools.test_alignment`, `tools.test_red_tracking` und `tools.test_segments` bestanden; `tools/test_tracker.py` separat ausgeführt, alle Szenarien bestanden. Der Tracker-Szenariotest beendet sich selbst mit `sys.exit` und ist deshalb nicht über pauschale unittest-Discovery aufzurufen. `git diff --check` für die zuvor versionierten Änderungen ohne Befund. Die Prüfung des gesamten vorgemerkten Bestands meldete ausschließlich beabsichtigte Markdown-Zeilenumbrüche im Audit und Leerzeilen-Kontext im archivierten Patch; diese historischen Belege bleiben unverändert. Der JavaScript-Test `tools/test_segment_ui.cjs` konnte mangels Node.js in dieser Umgebung nicht ausgeführt werden.

## Beobachtungen bei der Wiederherstellung

1. Nach dem Speicherplatzfehler waren wieder etwa 34 GB frei. Der laufende Dienst lieferte dennoch keine bestätigte Uhrzeit.
2. Die alte Kalibrierung passte nicht mehr zur Kameraposition. Das zunächst gelieferte Bild zeigte links den Spielstand; die Uhr war rechts abgeschnitten.
3. Nach Neuausrichtung der Kamera blieb das Bild der laufenden Verbindung bytegleich zum alten Snapshot. Eine unabhängige RTSP-Verbindung zeigte bereits das neue Bild. Der laufende Eingang meldete dabei rund 55–56 verarbeitete Bilder/s trotz konfigurierter 10 Bilder/s. Die genaue Ursache wurde nicht abschließend untersucht; ein Zeitstempel-/Pufferproblem ist eine Hypothese, kein bewiesener Befund.
4. Beenden des FFmpeg-Eingangs löste die vorhandene Wiederverbindung aus. Danach kamen aktuelle Bilder mit etwa 10 Bildern/s an. Kein Neustart des gesamten Servers war dafür erforderlich.
5. Die Uhr wurde im neuen mittigen Ausschnitt neu kalibriert. Autofit lieferte auf 11 Diagnosebildern 9 syntaktisch gültige Lesungen. Sichtbare Testfolgen enthielten fortlaufende Zeiten; ein Kontrollbild wurde als `15:15` gelesen.
6. Neue Kalibrierung wurde über `/api/config` übernommen und gespeichert, Tracker zurückgesetzt. Automatische Nachführung blieb aktiv; alte manuelle Segmentfelder wurden durch das neue Raster ersetzt.
7. Im anschließenden 20-Sekunden-Test waren 158 von 200 JPEG-Snapshots lesbar. Die Ausgabe blieb nach Übernahme bei `15:15`, `running=false`, passend zur sichtbar stehenden Tafel. API-Kontrollen bestätigten regelmäßig frische Tafelwerte. Die 79 % sind eine Lesbarkeitsquote dieses kurzen Tests, keine allgemeine Genauigkeitsmessung. Später meldete die API `15:36`, `running=true`.
8. Aufzeichnung wurde separat mit dem vorhandenen `Recorder` wieder aufgenommen, ohne die Erkennung anzuhalten: Streamkopie in 10-Minuten-MKV-Segmenten. Dateiwachstum wurde geprüft. Ein erster Startversuch scheiterte am aufgelösten Python-Symlink außerhalb der venv; der korrigierte Start verwendete den absoluten Pfad `.venv/bin/python` ohne Symlink-Auflösung.

## Architekturwissen und offene Aufgaben

Der ausführliche [Architektur- und Plausibilitätsaudit](architektur-und-plausibilitaetsaudit-2026-10-04.md) bleibt die maßgebliche Bestandsaufnahme und enthält einen noch nicht umgesetzten Architekturvorschlag.

- Rote Bildpunkte werden innerhalb von 28 Segmentfeldern ausgewertet; es existiert keine individuelle LED-Erkennung und kein Segmentzustand UNKNOWN. Unsichtbar kann dadurch wie AUS wirken.
- Alternative Ziffernkandidaten gehen früh verloren. Der Tracker erhält eine einzelne Rohzeit und Confidence, verwendet Confidence aber nicht als Übernahmekriterium.
- Rückwärtskorrekturen und Resets sind grundsätzlich möglich. Count-up-Annahmen, Formatregeln, Displaygeometrie und fachliche Regeln sollen künftig sauber getrennt werden.
- Optisches Vertrauen, zeitliche Plausibilität, Primary-/Recovery-Hypothesen und Ausgabevertrauen benötigen getrennte Modelle. Das Audit erteilt keine pauschale Umsetzungsfreigabe.
- Aufnahme benötigt künftig Speicherplatzüberwachung und kontrolliertes Verhalten bei voller Platte; eine Lösch-/Aufbewahrungsregel muss ausdrücklich festgelegt werden. Historische Aufnahmen wurden hier nicht automatisch gelöscht.
- Quelle benötigt eine Prüfung der tatsächlichen Bildfrische; `source_connected=true` allein bewies im beobachteten Fehlerfall keine aktuellen Bilder. Zeitstempelsprünge, Frame-Duplikate und Wiederverbindung sollten reproduzierbar getestet werden.
- Konfigurationsspeicherung und CSV-/Aufnahmefehler sollten gegen vollen Datenträger abgesichert werden. Im aktuellen Bestand gibt es abgebrochene Dateien und eine abgeschnittene CSV-Zeile.
- Veränderte Kamerapositionen benötigen erneute Kalibrierung; die begrenzte Nachführung ersetzt diese nicht. Alte Aufnahmen passen nicht zwingend zur finalen Kalibrierung. Die gesicherte vorherige Konfiguration ist ein Ausgangspunkt, keine Garantie für alle früheren Ausschnitte.

## Später fortsetzen

Zuerst diesen Bericht und den Audit lesen, dann anhand gesicherter Aufnahmen offline weiterarbeiten. Produktivprozesse bleiben aus. Beispielsweise kann `tools/eval_offline.py` mit einer zur Aufnahme passenden Kalibrierung ausgewertet werden. Für einen später ausdrücklich gewünschten Livebetrieb Aufnahme **und** CSV-Protokoll aktivieren, freien Speicher und frische Bilder prüfen und die Kalibrierung visuell kontrollieren. Keine automatische Aufnahme beim Lesen dieses Berichts starten.
