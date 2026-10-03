"""Szenario-Tests für die Uhrlogik (ohne Video).  python3 tools/test_tracker.py"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tafeluhr.tracker import ClockTracker, fmt  # noqa: E402

FPS = 10


def board(sec: int) -> str:
    return fmt(sec).replace(":", "")


def run(script, start=0.0, end=None, phase=0.37):
    """script(t) -> (anzeige_sekunden | None, lesbar). Liefert [(t, state)]."""
    tr = ClockTracker()
    out = []
    n = int(((end or 60) - start) * FPS)
    for i in range(n):
        t = start + i / FPS + phase
        v, readable = script(t)
        st = tr.update(t, board(v) if readable and v is not None else None)
        out.append((t, v, st))
    return out


def check(name, res, cond, from_t=0.0):
    bad = [(round(t, 1), v, s.seconds, s.running, s.source) for t, v, s in res if t >= from_t and not cond(t, v, s)]
    status = "OK " if not bad else "FEHLER"
    print(f"[{status}] {name}" + ("" if not bad else f"  {len(bad)} Frames, z.B. {bad[:4]}"))
    return not bad


ok = True

# 1) Einstieg in eine bereits laufende Uhr (23:10) -> nach spätestens 2,5 s korrekt
res = run(lambda t: (1390 + int(t), True), end=20)
ok &= check("Einstieg in laufende Uhr", res, lambda t, v, s: s.seconds == v and s.running, from_t=2.6)

# 2) Verdeckung 4 s während die Uhr läuft -> Vorhersage, keine Sprünge
res = run(lambda t: (600 + int(t), not (10 <= t < 14)), end=25)
ok &= check("Verdeckung 4 s (Vorhersage)", res, lambda t, v, s: abs(s.seconds - v) <= 0 if not (13.9 <= t <= 14.2) else abs(s.seconds - v) <= 1, from_t=3)
ok &= check("  Quelle während Verdeckung = predicted", res,
            lambda t, v, s: s.source == "predicted" if 10.6 <= t < 14 else True, from_t=3)

# 3) Uhr hält an -> Anzeige springt nie über den Haltewert hinaus
def stop_script(t):
    return (300 + int(min(t, 10.0)), True)
res = run(stop_script, end=20)
ok &= check("Anhalten: kein Vorlaufen", res, lambda t, v, s: s.seconds <= v, from_t=3)
ok &= check("Anhalten: steht nach <= 1,7 s", res, lambda t, v, s: not s.running if t > 11.7 else True, from_t=3)

# 4) Korrektur (+30 s) bei stehender Uhr -> nach correct_ms übernommen, vorher alter Wert
def corr(t):
    if t < 8:
        return (100 + int(t), True)
    if t < 12:
        return (107, True)
    return (137, True)
res = run(corr, end=20)
ok &= check("Korrektur: vorher Altwert", res, lambda t, v, s: s.seconds == 107 if 9 < t < 12 else True, from_t=3)
ok &= check("Korrektur: nach 1,3 s übernommen", res, lambda t, v, s: s.seconds == 137 if t > 13.3 else True, from_t=3)

# 5) Einzelne Fehllesungen (alle 7 Frames ein Zufallswert) -> keine Auswirkung
import random  # noqa: E402
random.seed(3)
def noisy(t):
    v = 2000 + int(t)
    if int(t * FPS) % 7 == 0:
        return (random.randint(0, 5999), True)
    return (v, True)
res = run(noisy, end=40)
# Fällt eine Fehllesung genau auf den Sekundenwechsel, ist der Wechsel unsichtbar
# -> max. 1 Frame Verzögerung erlaubt, sonst exakt.
ok &= check("Einzelne Fehllesungen ignoriert", res,
            lambda t, v, s: abs(s.seconds - (2000 + int(t))) <= (1 if (t % 1) < 0.2 else 0), from_t=3)

# 6) Halbzeit: Reset auf 00:00, dann 45:00, dann Start
def half(t):
    if t < 5:
        return (2690 + int(t), True)
    if t < 8:
        return (2694, True)   # Abpfiff
    if t < 12:
        return (0, True)
    if t < 16:
        return (2700, True)
    return (2700 + int(t - 16), True)
res = run(half, end=25)
ok &= check("Halbzeit-Reset & Start 45:00", res, lambda t, v, s: s.seconds == v if (9.4 < t < 12 or 13.4 < t < 16 or t > 17.2) else True, from_t=3)

print("\nALLE TESTS OK" if ok else "\nTESTS FEHLGESCHLAGEN")
sys.exit(0 if ok else 1)
