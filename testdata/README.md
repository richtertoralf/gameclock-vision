# Echte Testvideos der Spieluhr

Acht Ausschnitte aus den Aufnahmen vom 04.10.2026: insgesamt **22:20 Minuten**, rund **960 MiB**. Die Dateien werden mit Git LFS gespeichert. Die Originalaufnahmen wurden nicht verändert. H.264, 1920 × 1080, ohne Neukodierung; die ausgewählten Quellen enthalten keine Tonspur.

## Herunterladen

```sh
git lfs install
git clone https://github.com/richtertoralf/gameclock-vision.git
cd gameclock-vision
git lfs pull
```

Bei einer bestehenden Kopie genügt nach `git pull` ein `git lfs pull`. Ein einzelner Clip lässt sich mit `git lfs pull --include="testdata/videos/03-late-running-minute-change.mkv"` herunterladen.

## Auswahl

| Clip | Länge | Zweck | Verwendung |
| --- | --- | --- | --- |
| [01-early-stopped-net](videos/01-early-stopped-net.mkv) | 0:30 | Stehende Anzeige 15:47 hinter dem Netz; schwierige frühe Kameraposition. | development |
| [02-zero-stopped-outliers](videos/02-zero-stopped-outliers.mkv) | 0:30 | Stehende Anzeige 00:00; im früheren Prüflauf einzelne OCR-Ausreißer. | development |
| [03-late-running-minute-change](videos/03-late-running-minute-change.mkv) | 2:00 | Laufende Uhr ab etwa 16:49 mit Minutenwechseln; späte Kameraposition. | development |
| [04-start-from-zero](videos/04-start-from-zero.mkv) | 2:30 | 00:00, Start und anschließender Minutenwechsel; zeitweise Verdeckung. | development |
| [05-long-stop-restart](videos/05-long-stop-restart.mkv) | 3:50 | Langer Stillstand bei 11:46 und anschließender Wiederanlauf. | development |
| [06-period-end-reset-restart](videos/06-period-end-reset-restart.mkv) | 6:00 | Anzeige erreicht etwa 20:00, wird auf 00:00 zurückgesetzt und startet erneut. | development |
| [07-stop-restart-net](videos/07-stop-restart-net.mkv) | 3:00 | Kurzer Stillstand bei 12:35 und Wiederanlauf; Netz vor der Uhr. | holdout |
| [08-end-long-stop-reset](videos/08-end-long-stop-reset.mkv) | 4:00 | Langer Stillstand nahe 19:42, Weiterlauf bis etwa 20:00 und Rücksetzung; zeitweise Verdeckung. | holdout |

Die letzten beiden Clips sind als zurückgehaltene Prüfbeispiele (`holdout`) vorgesehen. Sie sollten bei späterer Anpassung der Erkennung nicht zur Parameterauswahl verwendet werden.

## Kalibrierung und Referenz

[manifest.json](manifest.json) enthält Originaldateinamen, angeforderte Startpositionen, Länge, Dateigröße, SHA-256 und Kalibrierungszuordnung. Die kopierten [Kalibrierungen](calibrations/) stammen aus dem Turnierbetrieb. `kalibrierung-final.json` wurde mit den ersten 30 Sekunden von Clip 03 geprüft. Die ältere Kalibrierung ist für die anderen Kamerapositionen ein Ausgangspunkt und muss vor quantitativen Tests am jeweiligen Clip kontrolliert werden.

Die Ereignisbeschreibungen beruhen auf visueller Sichtung und sind ungefähre Angaben. Es liegen **keine vollständigen Referenzzeiten pro Frame** vor. Insbesondere belegt ein Stillstand allein weder Auszeit noch Tor oder Verletzung; eine Rücksetzung belegt nicht eindeutig Halbzeit oder Spielende. FFmpeg schnitt an Schlüsselbildern ohne Neukodierung: die angeforderte Quellposition ist keine Garantie für einen framegenauen Beginn.

## Bezug zum Blindenfußball

Die [IBSA-Spielregeln 2026–2029](https://fileservice.aifdigitalsolutions.com/ibsa/2026%20IBSA%20Football%20-%20Laws%20of%20The%20Game_20260108111642669.pdf), Regeln 7 und 8, sehen zwei Halbzeiten von jeweils 20 Minuten und mehrere Gründe für Unterbrechungen der Spielzeit vor. Daher enthält die Auswahl Stillstände, Wiederanläufe sowie den Bereich um 20:00 und Rücksetzungen. Die Regeln legen nicht fest, dass diese konkrete Anzeige vorwärts zählt oder bei einer bestimmten Unterbrechungsart zurückgesetzt wird.

## Integritätsprüfung

Alle acht Dateien wurden vor dem Upload vollständig mit FFmpeg decodiert. Die SHA-256-Prüfsummen im Manifest beziehen sich auf die tatsächlichen Videodateien, nicht auf ihre Git-LFS-Zeiger.

## Lizenz

Copyright 2026 Toralf Richter. Die acht eigenen Videoausschnitte und die eigene Dokumentation in diesem Verzeichnis sind unter der [Apache License 2.0](../LICENSE) veröffentlicht. Die Lizenz gilt für die tatsächlichen Videodateien, einschließlich ihrer Bereitstellung über Git LFS.
