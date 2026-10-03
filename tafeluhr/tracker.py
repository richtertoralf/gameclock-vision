"""Uhr-Tracker: macht aus wackeligen Einzellesungen eine saubere Spieluhr.

Zwei Stufen:
  1. "kurz-stabil": Ein Wert gilt als gesehen, wenn er stable_ms lang
     (ca. 2 Frames) durchgehend gelesen wurde. Filtert Einzelfehler.
  2. Übernahme als Tafelwert:
     * Wert = bisheriger + 1 s               -> sofort, Uhr läuft.
     * Wert = Vorgänger + 1 in einer sauberen Sekundenfolge (zwei kurz-stabile
       Werte im Sekundenabstand)              -> Übernahme auch bei Sprung.
       So wird eine bereits laufende Uhr beim Start und nach Korrekturen
       binnen ~1-2 s erkannt.
     * Wert steht correct_ms lang still      -> Übernahme (Reset, Korrektur
       bei stehender Uhr, Startwert).
  Gleicher Wert länger als stop_ms -> Uhr steht.
  Keine gültige Lesung -> Weiterzählen ab letztem Sekundenwechsel bis coast_ms.
"""
from __future__ import annotations

from dataclasses import dataclass


def to_seconds(text: str) -> int:
    return int(text[:2]) * 60 + int(text[2:])


def fmt(sec: int) -> str:
    sec = max(0, min(sec, 99 * 60 + 59))
    return f"{sec // 60:02d}:{sec % 60:02d}"


@dataclass
class ClockState:
    time: str | None = None
    seconds: int | None = None
    running: bool = False
    source: str = "none"       # board | predicted | stale | none
    raw: str | None = None     # letzte Rohlesung "MM:SS" (oder None)
    confidence: float = 0.0
    last_board_age_ms: int | None = None
    ts: float = 0.0


class ClockTracker:
    def __init__(self, stable_ms=150, correct_ms=1200, stop_ms=1600, coast_ms=30000):
        self.configure(stable_ms, correct_ms, stop_ms, coast_ms)
        self.reset()

    def configure(self, stable_ms, correct_ms, stop_ms, coast_ms):
        self.stable = stable_ms / 1000
        self.correct = correct_ms / 1000
        self.stop = stop_ms / 1000
        self.coast = coast_ms / 1000

    def reset(self):
        self.observed: int | None = None     # übernommener Tafelwert
        self.observed_since: float = 0.0     # seit wann die Tafel ihn zeigt
        self.last_valid_t: float | None = None
        self.running = False
        self.anchor_v: int | None = None
        self.anchor_t: float = 0.0
        self.run_v: int | None = None        # aktuelle Leseserie (gleicher Wert)
        self.run_t0: float = 0.0
        self.run_last: float = -1e9
        self.recent: dict[int, list[float]] = {}  # abweichende Lesungen (v -> Zeiten)
        self.last_read_t: float = -1e9
        self.last_update_t: float | None = None
        self.dt = 0.1                        # Frame-Abstand (gelernt)
        self.short: list[tuple[int, float]] = []   # kurz-stabile Werte (v, Startzeit)
        self.last_conf = 0.0
        self.last_raw: str | None = None

    def update(self, t: float, text: str | None, confidence: float = 1.0) -> ClockState:
        if self.last_update_t is not None and 0 < t - self.last_update_t < 1:
            self.dt = 0.9 * self.dt + 0.1 * (t - self.last_update_t)
        self.last_update_t = t
        self.last_raw = f"{text[:2]}:{text[2:]}" if text else None
        if text is not None:
            v = to_seconds(text)
            self.last_valid_t = t
            self.last_conf = confidence
            self.last_read_t = t
            # Leseserie: Einzelne abweichende Frames (auch mehrere verschiedene)
            # unterbrechen sie nicht. Ein neuer Wert startet eine Serie, sobald er
            # zweimal binnen 0.5 s gelesen wurde – mit dem Zeitpunkt der ersten
            # Lesung (wichtig für den exakten Sekundenwechsel).
            for k in list(self.recent):
                self.recent[k] = [x for x in self.recent[k] if t - x <= 0.5]
                if not self.recent[k]:
                    del self.recent[k]
            if self.run_v is None or t - self.run_last > 0.5:
                self.run_v, self.run_t0, self.recent = v, t, {}
            elif v != self.run_v:
                self.recent.setdefault(v, []).append(t)
                if len(self.recent[v]) >= 2:
                    self.run_v, self.run_t0 = v, self.recent[v][0]
                    self.recent = {}
            if v == self.run_v:
                self.run_last = t
                dur = t - self.run_t0
                if dur >= self.stable and (not self.short or self.short[-1][0] != v
                                           or self.run_t0 - self.short[-1][1] > 3):
                    self.short.append((v, self.run_t0))
                    del self.short[:-6]
                self._consider(t, v, dur)
                if (self.running and self.observed is not None and v == self.observed
                        and t - self.observed_since >= self.stop):
                    self.running = False
        return self.state(t)

    def _accept(self, v: int, since: float, running: bool):
        self.observed, self.observed_since = v, since
        self.running = running
        self.anchor_v, self.anchor_t = v, since

    def _consider(self, t: float, v: int, dur: float):
        if v == self.observed or not self.short or self.short[-1][0] != v:
            return
        since = self.short[-1][1]
        if self.observed is not None and v == self.observed + 1:
            self._accept(v, since, True)
            return
        # Saubere Sekundenfolge: vorheriger kurz-stabiler Wert war v-1, ~1 s davor
        if len(self.short) >= 2:
            pv, pt = self.short[-2]
            if pv == v - 1 and 0.6 <= since - pt <= 1.6:
                self._accept(v, since, True)
                return
        if dur >= self.correct:
            self._accept(v, since, False)

    def state(self, t: float) -> ClockState:
        st = ClockState(ts=t, raw=self.last_raw, confidence=round(self.last_conf, 3))
        if self.observed is None:
            return st
        age = None if self.last_valid_t is None else t - self.last_valid_t
        st.last_board_age_ms = None if age is None else int(age * 1000)
        fresh = age is not None and age <= 0.5
        # Aktuell sichtbarer Tafelwert: nur wenn der letzte Frame lesbar war
        # und zur Serie gehörte (sonst: verdeckt oder neuer Wert im Anflug).
        latest = (self.last_read_t == self.last_update_t
                  and t - self.last_read_t <= 1.5 * self.dt)
        current = self.run_v if latest and self.run_last == self.last_read_t else None
        # +0.02 s: Rundungstoleranz; der echte Wechsel lag ohnehin bis zu 1 Frame früher
        pred = self.anchor_v + int(t - self.anchor_t + 0.02) if self.anchor_v is not None else None
        pend_matches = (pred is not None and latest and pred in self.recent
                        and self.recent[pred][-1] == self.last_read_t)
        if self.running and pred is not None and (
                current is None or pend_matches
                or (current != self.observed and abs(current - pred) <= 1)):
            # Tafel nicht lesbar, oder sie zeigt schon den nächsten (noch nicht
            # bestätigten) Wert -> ab letztem Sekundenwechsel weiterzählen.
            # Ein großer Sprung (Korrektur) wird nicht vorhergesagt, sondern
            # nach correct_ms übernommen.
            sec = pred
        else:
            # Tafel zeigt den bestätigten Wert -> genau den anzeigen (kein
            # Vorlaufen, kein Zurückspringen, wenn die Uhr angehalten wird)
            sec = self.observed
        st.seconds, st.time, st.running = sec, fmt(sec), self.running
        if age is not None and age > self.coast:
            st.source = "stale"
        elif not fresh:
            st.source = "predicted"
        else:
            st.source = "board"
        return st
