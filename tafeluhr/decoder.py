"""Segment-Decoder für eine 4-stellige 7-Segment-LED-Uhr (MM:SS).

Ablauf pro Frame:
  1. Perspektivische Entzerrung des Uhr-Vierecks (Quad) auf ein Normbild.
  2. Farbscore-Bild (Rot-Anteil) berechnen.
  3. Pro Segment (4 Ziffern x 7 Segmente) Helligkeit messen.
  4. Pro Segment gelernte Referenzen (an/aus) -> normierte Werte.
  5. Schwellwert je Frame (Otsu über alle 28 Werte) -> an/aus.
  6. Segmentmuster -> Ziffer (Tabelle, Toleranz 1 Segment).
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import numpy as np
import cv2

SEG_NAMES = "abcdefg"

# Segmentmuster (Reihenfolge a b c d e f g). Mehrere Varianten pro Ziffer
# (z. B. 7 mit/ohne f, 9 mit/ohne d, 6 mit/ohne a).
DIGIT_PATTERNS: dict[str, list[str]] = {
    "0": ["abcdef"],
    "1": ["bc"],
    "2": ["abdeg"],
    "3": ["abcdg"],
    "4": ["bcfg"],
    "5": ["acdfg"],
    "6": ["acdefg", "cdefg"],
    "7": ["abc", "abcf"],
    "8": ["abcdefg"],
    "9": ["abcdfg", "abcfg"],
}


def _mask(segs: str) -> int:
    return sum(1 << SEG_NAMES.index(s) for s in segs)


PATTERN_TABLE: list[tuple[int, str]] = [
    (_mask(p), d) for d, ps in DIGIT_PATTERNS.items() for p in ps
]

NORM_W, NORM_H = 640, 200  # Normbild der entzerrten Uhr (Innenmaß)
PAD = 16                   # Rand um das Viereck: LED-Leuchten am Rand bleibt erhalten
FULL_W, FULL_H = NORM_W + 2 * PAD, NORM_H + 2 * PAD


@dataclass
class Config:
    # Viereck um die 4 Ziffern (Bildkoordinaten): oben-links, oben-rechts,
    # unten-rechts, unten-links. Bei kursiven Ziffern Ecken der Schräge folgen.
    quad: list[list[float]] | None = None
    digit_w: float = 0.19     # Ziffernbreite als Anteil der Quad-Breite
    colon_w: float = 0.10     # Breite der Doppelpunkt-Lücke als Anteil
    # Linke Kante jeder Ziffer als Anteil der Quad-Breite. None = gleichmäßig
    # aus digit_w/colon_w verteilen.
    digit_x: list[float] | None = None
    thick: float = 0.15       # Messkasten-Dicke als Anteil der Ziffernbreite
    y_top: float = 0.0        # Ziffern-Oberkante im Viereck (Anteil, <0 = darüber)
    y_bot: float = 1.0        # Ziffern-Unterkante im Viereck (Anteil, >1 = darunter)
    color_mode: str = "red"   # "red" | "luma"
    min_contrast: float = 20.0  # Mindestabstand an/aus (0..255)
    stable_ms: int = 150      # Übernahme bei +1 s (ca. 2 Frames bei 10 fps)
    correct_ms: int = 1200    # Übernahme bei Sprüngen (Korrektur, Reset)
    stop_ms: int = 1600       # so lange unverändert -> Uhr steht
    coast_ms: int = 30000     # max. Vorhersage ohne Lesung (verdeckt)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict:
        return asdict(self)


def digit_boxes(cfg: Config) -> list[tuple[float, float, float, float]]:
    """Ziffern-Rechtecke im Normbild (x0, y0, x1, y1)."""
    dw = cfg.digit_w * NORM_W
    xs = [x * NORM_W for x in (cfg.digit_x or default_digit_x(cfg))]
    y0, y1 = cfg.y_top * NORM_H, cfg.y_bot * NORM_H
    return [(x, y0, x + dw, y1) for x in xs]


def default_digit_x(cfg: Config) -> list[float]:
    """Gleichmäßige Verteilung: [Z][Lücke][Z][Doppelpunkt][Z][Lücke][Z]."""
    dw, cw = cfg.digit_w, cfg.colon_w
    gap = max(0.0, (1.0 - 4 * dw - cw) / 2.0)
    return [0.0, dw + gap, 2 * dw + gap + cw, 3 * dw + 2 * gap + cw]


EDGE_EXT = 0.0   # Randsegmente über das Viereck hinaus abtasten (Tests: schadet)
TOPK = 0.2       # Mittel der hellsten x-Anteile im Messrechteck
LEARN_EXPECTED = True


def segment_rects(cfg: Config) -> list[tuple[int, int, int, int]]:
    """28 Messrechtecke (x0, y0, x1, y1) im Normbild, Ziffer für Ziffer a..g."""
    rects = []
    for (x0, y0, x1, y1) in digit_boxes(cfg):
        w, h = x1 - x0, y1 - y0
        t = cfg.thick * w
        m = h / 2.0
        # Nur die Segmentmitte abtasten: Eck-LEDs gehören zu zwei Segmenten
        # und Streulicht aus Nachbarsegmenten sammelt sich in den Ecken.
        hx0, hx1 = max(t, 0.25 * w), min(w - t, 0.75 * w)
        o = EDGE_EXT * t  # Randsegmente leicht über das Viereck hinaus abtasten
        r = {
            "a": (hx0, -o, hx1, t),
            "b": (w - t, 0.13 * h, w + o, 0.37 * h),
            "c": (w - t, 0.63 * h, w + o, 0.87 * h),
            "d": (hx0, h - t, hx1, h + o),
            "e": (-o, 0.63 * h, t, 0.87 * h),
            "f": (-o, 0.13 * h, t, 0.37 * h),
            "g": (hx0, m - t / 2, hx1, m + t / 2),
        }
        for s in SEG_NAMES:
            a0, b0, a1, b1 = r[s]
            rects.append((int(round(PAD + x0 + a0)), int(round(PAD + y0 + b0)),
                          int(round(PAD + x0 + a1)), int(round(PAD + y0 + b1))))
    return rects


def color_score(bgr: np.ndarray, mode: str) -> np.ndarray:
    """Score-Bild 0..255: hoch = leuchtende rote LED."""
    b, g, r = [c.astype(np.int16) for c in cv2.split(bgr)]
    if mode == "luma":
        s = (r * 3 + g * 6 + b) // 10
    else:
        # Rot minus anteilig Grün/Blau: grünes Netz/Rasen -> ~0.
        # Überbelichtete (weiße) LED-Kerne bleiben noch deutlich positiv.
        s = r - (np.maximum(g, b) * 6) // 10
    return np.clip(s, 0, 255).astype(np.uint8)


@dataclass
class Reading:
    text: str | None          # "MMSS" oder None
    digits: list[str | None]
    on: list[bool]            # 28
    values: list[float]       # 28 normierte Werte (0..1 grob)
    raw: list[float]          # 28 Rohwerte
    threshold: float
    contrast: float
    confidence: float         # 0..1
    reason: str = ""
    dists: list[int] = field(default_factory=list)  # Segmentabweichung je Ziffer


@dataclass
class SegmentDecoder:
    cfg: Config
    on_ref: np.ndarray = field(default_factory=lambda: np.zeros(28))
    off_ref: np.ndarray = field(default_factory=lambda: np.zeros(28))
    on_n: np.ndarray = field(default_factory=lambda: np.zeros(28))
    off_n: np.ndarray = field(default_factory=lambda: np.zeros(28))
    alpha: float = 0.05

    def __post_init__(self):
        self.reconfigure(self.cfg)

    def reconfigure(self, cfg: Config, reset_refs: bool = True):
        self.cfg = cfg
        self.rects = segment_rects(cfg)
        self.M = None
        if cfg.quad:
            src = np.array(cfg.quad, dtype=np.float32)
            dst = np.array([[PAD, PAD], [PAD + NORM_W, PAD], [PAD + NORM_W, PAD + NORM_H],
                            [PAD, PAD + NORM_H]], dtype=np.float32)
            self.M = cv2.getPerspectiveTransform(src, dst)
        if reset_refs:
            for a in (self.on_ref, self.off_ref, self.on_n, self.off_n):
                a[:] = 0

    def warp(self, frame: np.ndarray) -> np.ndarray | None:
        if self.M is None:
            return None
        return cv2.warpPerspective(frame, self.M, (FULL_W, FULL_H),
                                   flags=cv2.INTER_LINEAR)

    def measure(self, score: np.ndarray) -> np.ndarray:
        vals = np.zeros(28)
        for i, (x0, y0, x1, y1) in enumerate(self.rects):
            patch = score[max(y0, 0):max(y1, 0), max(x0, 0):max(x1, 0)].ravel()
            if patch.size == 0:
                continue
            k = max(1, int(patch.size * TOPK))
            vals[i] = np.partition(patch, patch.size - k)[-k:].mean()
        return vals

    def _normalize(self, raw: np.ndarray) -> np.ndarray:
        """Per-Segment-Normierung mit gelernten Referenzen (Netz-Dimmung)."""
        known = (self.on_n >= 5) & (self.off_n >= 5)
        if known.sum() < 8:
            return raw.copy()
        span = self.on_ref - self.off_ref
        med_on = np.median(self.on_ref[known])
        med_off = np.median(self.off_ref[known])
        med_span = max(med_on - med_off, 1.0)
        out = raw.copy()
        good = known & (span > 0.3 * med_span)
        out[good] = med_off + (raw[good] - self.off_ref[good]) * med_span / span[good]
        return out

    @staticmethod
    def _otsu(v: np.ndarray) -> tuple[float, float, float]:
        s = np.sort(v)
        best, thr, m0b, m1b = -1.0, s[0], s[0], s[-1]
        for i in range(1, len(s)):
            a, b = s[:i], s[i:]
            w0, w1 = len(a) / len(s), len(b) / len(s)
            m0, m1 = a.mean(), b.mean()
            bv = w0 * w1 * (m1 - m0) ** 2
            if bv > best:
                best, thr, m0b, m1b = bv, (s[i - 1] + s[i]) / 2, m0, m1
        return thr, m0b, m1b

    def prepare(self, frame: np.ndarray) -> np.ndarray | None:
        """Entzerrtes Score-Bild (für decode und Auto-Ausrichtung)."""
        img = self.warp(frame)
        if img is None:
            return None
        score = color_score(img, self.cfg.color_mode)
        return cv2.GaussianBlur(score, (3, 3), 0)

    def decode(self, frame: np.ndarray) -> Reading | None:
        score = self.prepare(frame)
        if score is None:
            return None
        return self.classify(self.measure(score))

    def classify(self, raw: np.ndarray, learn: bool = True) -> Reading:
        norm = self._normalize(raw) if learn else raw.copy()
        thr, m_off, m_on = self._otsu(norm)
        contrast = float(m_on - m_off)
        on = norm > thr
        span = max(m_on - m_off, 1e-6)
        values = np.clip((norm - m_off) / span, -0.5, 1.5)

        r = Reading(None, [None] * 4, on.tolist(), values.tolist(), raw.tolist(),
                    float(thr), contrast, 0.0)
        if contrast < self.cfg.min_contrast or m_on < 1.6 * max(m_off, 1.0):
            r.reason = "kein Kontrast"
            return r

        digits, worst, expected, dists = [], 1.0, [], []
        for d in range(4):
            bits = 0
            for s in range(7):
                if on[d * 7 + s]:
                    bits |= 1 << s
            best_d, best_dist, second, best_m = None, 99, 99, 0
            for m, ch in PATTERN_TABLE:
                dist = bin(m ^ bits).count("1")
                if dist < best_dist:
                    if ch != best_d:
                        second = best_dist
                    best_d, best_dist, best_m = ch, dist, m
                elif dist < second and ch != best_d:
                    second = dist
            if best_dist == 0 or (best_dist == 1 and second >= 3):
                digits.append(best_d)
            else:
                digits.append(None)
            expected.append(best_m)
            dists.append(best_dist)
            seg_margin = float(np.min(np.abs(values[d * 7:(d + 1) * 7] - 0.5))) * 2
            if best_dist == 1:
                seg_margin *= 0.4
            worst = min(worst, seg_margin)
        r.digits = digits
        r.dists = dists
        if None in digits:
            r.reason = "Ziffer unbekannt"
            return r
        text = "".join(digits)
        if int(text[2]) > 5:
            r.reason = "Sekunden-Zehner > 5"
            return r
        r.text = text
        r.confidence = round(max(0.0, min(1.0, worst)), 3)
        if not learn:
            return r
        # Referenzen nur bei gültiger Lesung lernen – nach dem *erkannten*
        # Muster, damit auch gedimmte Segmente ihren eigenen Pegel lernen.
        a = self.alpha
        for i in range(28):
            if (expected[i // 7] >> (i % 7) & 1) if LEARN_EXPECTED else on[i]:
                self.on_ref[i] = raw[i] if self.on_n[i] == 0 else (1 - a) * self.on_ref[i] + a * raw[i]
                self.on_n[i] += 1
            else:
                self.off_ref[i] = raw[i] if self.off_n[i] == 0 else (1 - a) * self.off_ref[i] + a * raw[i]
                self.off_n[i] += 1
        return r

    def debug_image(self, frame: np.ndarray, reading: Reading | None, scale: int = 2) -> np.ndarray:
        img = self.warp(frame)
        if img is None:
            img = np.zeros((FULL_H, FULL_W, 3), np.uint8)
        img = cv2.resize(img, (FULL_W * scale, FULL_H * scale), interpolation=cv2.INTER_NEAREST)
        for (x0, y0, x1, y1) in digit_boxes(self.cfg):
            cv2.rectangle(img, (int((PAD + x0) * scale), int((PAD + y0) * scale)),
                          (int((PAD + x1) * scale) - 1, int((PAD + y1) * scale) - 1), (90, 90, 90), 1)
        for i, (x0, y0, x1, y1) in enumerate(self.rects):
            col = (160, 160, 160)
            if reading is not None:
                col = (0, 230, 0) if reading.on[i] else (0, 0, 230)
            cv2.rectangle(img, (x0 * scale, y0 * scale), (x1 * scale, y1 * scale), col, 2)
            if reading is not None:
                cv2.putText(img, f"{reading.values[i]:.1f}", (x0 * scale + 2, y0 * scale + 14),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        if reading is not None:
            label = reading.text and f"{reading.text[:2]}:{reading.text[2:]}" or reading.reason
            cv2.putText(img, f"{label}  K={reading.contrast:.0f} conf={reading.confidence:.2f}",
                        (8, FULL_H * scale - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        return img
