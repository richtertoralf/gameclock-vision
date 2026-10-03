"""Automatisches Ausrichten der Ziffern im markierten Viereck.

Der Nutzer zieht das Viereck nur grob um die vier Uhrziffern. Die Suche
probiert Ziffernbreite, Abstände, Doppelpunkt-Lücke, horizontale Lage,
vertikale Grenzen und Messkasten-Dicke durch und bewertet jede Variante an
mehreren Frames aus den letzten Sekunden (verschiedene Sekundenziffern):
  + gültige Lesung, + Ziffern mit wenig Segmentabweichung, + Sicherheit.
"""
from __future__ import annotations

import time
from dataclasses import replace

import cv2
import numpy as np

from .decoder import (Config, SegmentDecoder, segment_rects, default_digit_x,
                      PAD, NORM_W, NORM_H)


def dark_rects(cfg: Config) -> list[tuple[int, int, int, int]]:
    """Bereiche, die bei richtiger Lage dunkel sein müssen: die zwei Löcher
    jeder Ziffer und die Lücken innerhalb der Ziffernpaare (MM und SS)."""
    from .decoder import digit_boxes
    out = []
    boxes = digit_boxes(cfg)
    for (x0, y0, x1, y1) in boxes:
        w, h = x1 - x0, y1 - y0
        t = cfg.thick * w
        ix0, ix1 = x0 + max(1.6 * t, 0.3 * w), x1 - max(1.6 * t, 0.3 * w)
        for (a, b) in ((0.2, 0.38), (0.62, 0.8)):
            out.append((ix0, y0 + a * h, ix1, y0 + b * h))
    for i in (0, 2):  # Lücke Z1-Z2 und Z3-Z4
        gx0, gx1 = boxes[i][2], boxes[i + 1][0]
        if gx1 - gx0 > 4:
            out.append((gx0 + 0.25 * (gx1 - gx0), boxes[i][1] + 0.1 * (boxes[i][3] - boxes[i][1]),
                        gx1 - 0.25 * (gx1 - gx0), boxes[i][3] - 0.1 * (boxes[i][3] - boxes[i][1])))
    return [(int(PAD + a), int(PAD + b), int(PAD + c), int(PAD + d)) for a, b, c, d in out]


class _Scorer:
    def __init__(self, cfg: Config, scores: list[np.ndarray]):
        self.dec = SegmentDecoder(cfg)
        self.scores = scores
        self.evals = 0

    def __call__(self, cfg: Config) -> float:
        self.evals += 1
        dx = cfg.digit_x or default_digit_x(cfg)
        # Ziffern dürfen sich nicht überlappen und nicht weit aus dem Viereck ragen
        if any(dx[i + 1] - dx[i] < cfg.digit_w * 1.02 for i in range(3)):
            return -1e9
        if dx[0] < -0.08 or dx[3] + cfg.digit_w > 1.08:
            return -1e9
        self.dec.cfg = cfg
        self.dec.rects = segment_rects(cfg)
        dark = dark_rects(cfg)
        total, values = 0.0, []
        for sc in self.scores:
            raw = self.dec.measure(sc)
            r = self.dec.classify(raw, learn=False)
            on = np.array(r.on)
            if on.any() and (~on).any():
                on_m, off_m = raw[on].mean(), raw[~on].mean()
                span = max(on_m - off_m, 1.0)
                # Licht in Löchern/Lücken = falsche Lage
                dk = []
                for (x0, y0, x1, y1) in dark:
                    patch = sc[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)]
                    if patch.size:
                        k = max(1, int(patch.size * 0.2))
                        dk.append(np.partition(patch.ravel(), patch.size - k)[-k:].mean())
                if dk:
                    total -= 2.5 * max(0.0, (float(np.mean(dk)) - off_m) / span)
            if r.dists:
                total += sum(max(0, 3 - d) for d in r.dists) / 12.0
            if r.text:
                total += 2.0 + 2.0 * r.confidence
                values.append(int(r.text[:2]) * 60 + int(r.text[2:]))
            else:
                values.append(None)
        # Zeitliche Plausibilität: Bilder im Sekundenabstand -> Uhr steht oder
        # läuft weiter (Differenz 0..2 s); große Sprünge sprechen gegen die Lage
        for a, b in zip(values, values[1:]):
            if a is not None and b is not None:
                total += 0.8 if 0 <= b - a <= 2 else -1.5
        return total / len(self.scores)


def _even(cfg: Config, dw: float, cw: float, off: float, span: float) -> Config:
    gap = max(0.0, (span - 4 * dw - cw) / 2.0)
    xs = [off, off + dw + gap, off + 2 * dw + gap + cw, off + 3 * dw + 2 * gap + cw]
    return replace(cfg, digit_w=round(dw, 4), colon_w=round(cw, 4), digit_x=[round(x, 4) for x in xs])


def vertical_guess(scores: list[np.ndarray]) -> tuple[float, float] | None:
    """Ober-/Unterkante der LED-Ziffern aus dem Zeilenprofil (Maximum über Frames)."""
    m = np.max(np.stack(scores), axis=0).astype(np.float32)
    rows = m[:, PAD:PAD + NORM_W].mean(axis=1)
    rows = np.convolve(rows, np.ones(3) / 3, mode="same")
    base = np.percentile(rows, 10)
    peak = rows.max()
    if peak - base < 5:
        return None
    on = np.where(rows > base + 0.35 * (peak - base))[0]
    top, bot = on[0], on[-1]
    yt = float(np.clip((top - PAD) / NORM_H, -0.08, 0.4))
    yb = float(np.clip((bot - PAD) / NORM_H, 0.6, 1.08))
    return (yt, yb) if yb - yt > 0.4 else None


def estimate_skew(scores: list[np.ndarray], yt: float, yb: float) -> float:
    """Kursiv-Schräge (Versatz oben nach rechts pro Höhe). Richtig entzerrt
    bilden die senkrechten Segmente scharfe Spalten im Spaltenprofil."""
    m = np.max(np.stack(scores), axis=0).astype(np.float32)
    h, w = m.shape
    y0 = int(PAD + max(yt, -0.08) * NORM_H)
    y1 = int(PAD + min(yb, 1.08) * NORM_H)
    ybot = float(y1)
    best_s, best_v = 0.0, -1.0
    for sk in np.arange(-0.1, 0.36, 0.02):
        M = np.float32([[1, -sk, sk * ybot], [0, 1, 0]])
        u = cv2.warpAffine(m, M, (w, h), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        prof = u[y0:y1].mean(axis=0)
        prof = prof - prof.mean()
        v = float((prof ** 2).mean())
        if v > best_v:
            best_s, best_v = float(sk), v
    return round(best_s, 3)


def apply_skew(cfg: Config, sk: float) -> Config:
    """Oberkante des Vierecks um sk x Höhe nach rechts schieben (Parallelogramm)."""
    dec = SegmentDecoder(cfg)
    Minv = np.linalg.inv(dec.M)
    pts = np.float32([[PAD + sk * NORM_H, PAD], [PAD + NORM_W + sk * NORM_H, PAD],
                      [PAD + NORM_W, PAD + NORM_H], [PAD, PAD + NORM_H]]).reshape(-1, 1, 2)
    q = cv2.perspectiveTransform(pts, Minv).reshape(-1, 2)
    return replace(cfg, quad=[[round(float(x), 1), round(float(y), 1)] for x, y in q])


def autofit(cfg: Config, frames: list[np.ndarray], budget_s: float = 30.0) -> tuple[Config, dict]:
    """Liefert die beste Konfiguration und Infos (Score, Lesequote).
    frames: Originalbilder (die Suche kann das Viereck schräg stellen)."""
    t0 = time.time()
    base = replace(cfg, y_top=0.0, y_bot=1.0, thick=0.15, digit_x=None)
    scores = [SegmentDecoder(base).prepare(f) for f in frames]
    # Kursiv-Schräge schätzen und ins Viereck übernehmen
    vg0 = vertical_guess(scores) or (0.0, 1.0)
    sk = estimate_skew(scores, *vg0)
    if abs(sk) >= 0.02:
        base = apply_skew(base, sk)
        dec = SegmentDecoder(base)
        scores = [dec.prepare(f) for f in frames]
    f = _Scorer(base, scores)
    # Stufe 1 mit Teilmenge der Frames (schneller), Feinsuche mit allen
    sub = scores[:: max(1, len(scores) // 4)][:4]
    f1 = _Scorer(base, sub)

    verticals = [(0.0, 1.0)]
    vg = vertical_guess(scores)
    if vg:
        verticals.insert(0, vg)

    # Stufe 1: horizontales Raster (gleichmäßige Verteilung + Spannweite)
    best, bs = base, -1e9
    for (yt, yb), span in ((v, sp) for v in verticals for sp in (0.72, 0.8, 0.87, 0.93, 0.98, 1.03)):
        for dw in np.arange(0.12, 0.265, 0.015):
            for cw in np.arange(0.0, 0.25, 0.03):
                if 4 * dw + cw > span:
                    continue
                for off in np.arange(-0.06, 1.0 - span + 0.07, 0.02):
                    c = replace(_even(base, dw, cw, off, span), y_top=yt, y_bot=yb)
                    s = f1(c)
                    if s > bs:
                        best, bs = c, s
    bs = f(best)
    # Stufe 2: vertikale Grenzen
    best, bs = _refine_vertical(f, best, bs)
    # Stufe 3: Feinsuche je Ziffer, Breite, Dicke (zwei Durchgänge)
    for _ in range(2):
        if time.time() - t0 > budget_s:
            break
        for i in range(4):
            for d in np.arange(-0.025, 0.026, 0.005):
                xs = list(best.digit_x)
                xs[i] = round(xs[i] + d, 4)
                c = replace(best, digit_x=xs)
                s = f(c)
                if s > bs:
                    best, bs = c, s
        for d in np.arange(-0.012, 0.013, 0.003):
            c = replace(best, digit_w=round(best.digit_w + d, 4))
            s = f(c)
            if s > bs:
                best, bs = c, s
        for th in (0.10, 0.12, 0.15, 0.18, 0.21):
            c = replace(best, thick=th)
            s = f(c)
            if s > bs:
                best, bs = c, s
        best, bs = _refine_vertical(f, best, bs, fine=True)

    # Ergebnis bewerten
    f.dec.cfg = best
    f.dec.rects = segment_rects(best)
    ok = sum(1 for sc in scores if f.dec.classify(f.dec.measure(sc), learn=False).text)
    best = replace(best, digit_w=float(best.digit_w), colon_w=float(best.colon_w),
                   digit_x=[float(x) for x in best.digit_x], thick=float(best.thick),
                   y_top=float(best.y_top), y_bot=float(best.y_bot))
    info = {"score": round(float(bs), 3), "valid_frames": ok, "frames": len(scores),
            "evals": f.evals + f1.evals, "vertical_guess": vg, "skew": sk, "seconds": round(time.time() - t0, 1)}
    return best, info


def _refine_vertical(f, best, bs, fine=False):
    if fine:
        tops = best.y_top + np.arange(-0.03, 0.031, 0.01)
        bots = best.y_bot + np.arange(-0.03, 0.031, 0.01)
    else:
        tops = np.arange(-0.07, 0.3, 0.02)
        bots = np.arange(0.7, 1.075, 0.02)
    for yt in tops:
        for yb in bots:
            if yb - yt < 0.5 or yt < -0.08 or yb > 1.08:
                continue
            c = replace(best, y_top=round(float(yt), 4), y_bot=round(float(yb), 4))
            s = f(c)
            if s > bs:
                best, bs = c, s
    return best, bs
