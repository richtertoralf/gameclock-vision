"""Erzeugt ein synthetisches Testvideo einer LED-Tafel hinter einem Netz.

Simuliert: Tafel 2,0 x 0,72 m mit 1-cm-LEDs (10 pro Ziffernhöhe, kursiv),
grünes 6-mm-Netz 30 cm davor (bewegt sich im Wind), Kamera aus ~40 m,
Rauschen, Kamerazittern, Helligkeitsschwankung, kurze Verdeckung,
Spielunterbrechung, Uhr-Korrektur und Halbzeit-Reset auf 45:00.

Ausgabe: Video (H.264) + Ground-Truth-CSV (Frame, Zeit, Anzeige, läuft).

  python3 tools/gen_testvideo.py --out test.mp4 --seconds 180
"""
from __future__ import annotations

import argparse
import csv
import subprocess

import cv2
import numpy as np

FPS = 25
W, H = 1920, 1080

# Uhrverlauf: (ab Sekunde, Modus, Anzeigewert in s)
TIMELINE = [
    (0, "stop", 0),
    (4, "run", 0),
    (80, "stop", 76),      # Unterbrechung
    (86, "run", 76),
    (110, "stop", 100),
    (111, "stop", 130),    # Korrektur am Bedienteil (+30 s)
    (113, "run", 130),
    (140, "stop", 157),
    (143, "stop", 0),      # Halbzeit: Reset
    (146, "stop", 2700),   # 2. Halbzeit startet bei 45:00
    (150, "run", 2700),
]
OCCLUSIONS = [(95.0, 98.0)]        # Kopf/Spieler vor der Tafel
HOME_GOAL_AT = 60.0


def clock_at(t: float) -> tuple[int, bool]:
    seg = TIMELINE[0]
    for s in TIMELINE:
        if t >= s[0]:
            seg = s
    t0, mode, v0 = seg
    if mode == "run":
        return v0 + int(t - t0), True
    return v0, False


SEG_MAP = {
    "0": "abcdef", "1": "bc", "2": "abdeg", "3": "abcdg", "4": "bcfg",
    "5": "acdfg", "6": "acdefg", "7": "abc", "8": "abcdefg", "9": "abcdfg",
}


def led_positions(w: float, h: float) -> dict[str, list[tuple[float, float]]]:
    """LED-Positionen pro Segment in einer Ziffer (mm, ohne Kursiv)."""
    m = h / 2
    hx = [w * f for f in (0.18, 0.5, 0.82)]
    vy_top = [m * f for f in (0.14, 0.38, 0.62, 0.86)]
    vy_bot = [m + y for y in vy_top]
    return {
        "a": [(x, 0) for x in hx],
        "g": [(x, m) for x in hx],
        "d": [(x, h) for x in hx],
        "f": [(0, y) for y in vy_top],
        "b": [(w, y) for y in vy_top],
        "e": [(0, y) for y in vy_bot],
        "c": [(w, y) for y in vy_bot],
    }


class BoardRenderer:
    MM = 0.8  # Pixel pro mm im Hochauflösungs-Canvas
    BW, BH = 2000, 720
    DIG_W, DIG_H = 165, 330
    SKEW = 0.10
    # linke Kanten der Ziffern (mm): Heim 2x, Uhr 4x, Gast 2x
    XS = [130, 330, 610, 805, 1070, 1265, 1560, 1755]
    Y0 = 170

    def __init__(self):
        self.cache: dict[str, np.ndarray] = {}
        self.leds = led_positions(self.DIG_W, self.DIG_H)

    def _p(self, x, y):
        s = self.MM
        return int(round(x * s)), int(round(y * s))

    def render(self, text8: str) -> np.ndarray:
        if text8 in self.cache:
            return self.cache[text8]
        s = self.MM
        cw, ch = int(self.BW * s), int(self.BH * s)
        img = np.full((ch, cw, 3), (28, 22, 22), np.uint8)
        glow = np.zeros_like(img)
        r = max(2, int(6 * s))  # LED-Radius ~5 mm + Überstrahlung
        for di, ch_ in enumerate(text8):
            x0 = self.XS[di]
            lit = set(SEG_MAP.get(ch_, ""))
            for seg, pts in self.leds.items():
                for (lx, ly) in pts:
                    x = x0 + lx + self.SKEW * (self.DIG_H - ly)
                    y = self.Y0 + ly
                    if seg in lit:
                        cv2.circle(glow, self._p(x, y), int(r * 2.2), (60, 60, 255), -1, cv2.LINE_AA)
                        cv2.circle(img, self._p(x, y), r, (225, 225, 255), -1, cv2.LINE_AA)
                    else:
                        cv2.circle(img, self._p(x, y), max(1, r // 3), (70, 70, 80), -1, cv2.LINE_AA)
        # Doppelpunkt
        for cy in (self.Y0 + 110, self.Y0 + 230):
            x = 1000 + self.SKEW * (self.DIG_H - (cy - self.Y0))
            cv2.circle(img, self._p(x, cy), r, (215, 215, 255), -1, cv2.LINE_AA)
        glow = cv2.GaussianBlur(glow, (0, 0), 7 * s)
        img = cv2.add(img, cv2.add(glow, glow))
        cv2.putText(img, "DOMACI", self._p(150, 640), cv2.FONT_HERSHEY_SIMPLEX, 2.2 * s, (235, 235, 235), int(6 * s))
        cv2.putText(img, "HOSTE", self._p(1600, 640), cv2.FONT_HERSHEY_SIMPLEX, 2.2 * s, (235, 235, 235), int(6 * s))
        cv2.putText(img, "WWW.LEGRA.CZ", self._p(1150, 90), cv2.FONT_HERSHEY_SIMPLEX, 1.2 * s, (150, 150, 150), int(3 * s))
        self.cache[text8] = img
        return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="test.mp4")
    ap.add_argument("--gt", default=None)
    ap.add_argument("--seconds", type=float, default=180)
    ap.add_argument("--board-px", type=int, default=420, help="Tafelbreite im Bild (px)")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    gt_path = a.gt or a.out.rsplit(".", 1)[0] + "_gt.csv"
    rng = np.random.default_rng(a.seed)

    br = BoardRenderer()
    bw = a.board_px
    bh = int(bw * br.BH / br.BW)
    bx, by = (W - bw) // 2 + 60, 360
    px_per_mm = bw / br.BW

    # Hintergrund: grüne Plane/Zaun mit Struktur
    bg = np.zeros((H, W, 3), np.uint8)
    bg[:] = (95, 120, 55)
    noise = cv2.GaussianBlur(rng.normal(0, 25, (H // 8, W // 8)).astype(np.float32), (0, 0), 3)
    noise = cv2.resize(noise, (W, H))
    bg = np.clip(bg.astype(np.float32) + noise[..., None], 0, 255).astype(np.uint8)
    cv2.rectangle(bg, (0, 700), (W, H), (60, 140, 70), -1)  # Rasen

    rx0, ry0 = max(0, bx - 120), max(0, by - 120)
    rx1, ry1 = min(W, bx + bw + 120), min(H, by + bh + 120)

    mesh_px = 100 * px_per_mm          # 10 cm Maschen
    strand_px = max(1.0, 6 * px_per_mm)  # 6 mm Faden

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "23", "-pix_fmt", "yuv420p", a.out], stdin=subprocess.PIPE)

    n = int(a.seconds * FPS)
    with open(gt_path, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(["frame", "t", "time", "running", "occluded"])
        for i in range(n):
            t = i / FPS
            sec, running = clock_at(t)
            mm, ss = divmod(sec, 60)
            home = "01" if t >= HOME_GOAL_AT else "00"
            text8 = f"{home}{mm:02d}{ss:02d}02"
            board = br.render(text8)
            frame = bg.copy()
            roi = frame[ry0:ry1, rx0:rx1].astype(np.float32)
            small = cv2.resize(board, (bw, bh), interpolation=cv2.INTER_AREA)
            roi[by - ry0:by - ry0 + bh, bx - rx0:bx - rx0 + bw] = small

            # Netz 30 cm vor der Tafel, Wind bewegt es (Koordinaten im ROI)
            wind_x = 2.0 * np.sin(2 * np.pi * t / 3.7) + 0.8 * np.sin(2 * np.pi * t / 1.3)
            wind_y = 1.2 * np.sin(2 * np.pi * t / 4.9)
            net = np.zeros(roi.shape[:2], np.uint8)
            thick = max(1, int(round(strand_px)))
            rw, rh = rx1 - rx0, ry1 - ry0
            x = wind_x % mesh_px
            while x < rw:
                xi = int(round(x))
                cv2.line(net, (xi, 0), (xi + 4, rh), 255, thick, cv2.LINE_AA)
                x += mesh_px
            y = wind_y % mesh_px
            while y < rh:
                yi = int(round(y))
                cv2.line(net, (0, yi), (rw, yi + 3), 255, thick, cv2.LINE_AA)
                y += mesh_px
            alpha = (net.astype(np.float32) / 255.0 * 0.8)[..., None]
            net_col = np.array((110, 175, 95), np.float32)
            roi = roi * (1 - alpha) + net_col * alpha

            occluded = any(s0 <= t < e0 for s0, e0 in OCCLUSIONS)
            if occluded:
                cx = int(bx - rx0 + bw * (0.35 + 0.1 * (t - OCCLUSIONS[0][0])))
                cv2.ellipse(roi, (cx, by - ry0 + bh // 2 + 30), (70, 95), 0, 0, 360, (40, 45, 55), -1)

            gain = 1.0 + 0.06 * np.sin(2 * np.pi * t / 23.0)
            roi = roi * gain + rng.normal(0, 5, roi.shape)
            roi = np.clip(roi, 0, 255).astype(np.uint8)
            # Kamerazittern + leichte Unschärfe (Tele, Hitzeflimmern)
            jx, jy = rng.normal(0, 0.4), rng.normal(0, 0.4)
            M = np.float32([[1, 0, jx], [0, 1, jy]])
            roi = cv2.warpAffine(roi, M, (rw, rh), borderMode=cv2.BORDER_REFLECT)
            roi = cv2.GaussianBlur(roi, (0, 0), 0.7)
            frame[ry0:ry1, rx0:rx1] = roi
            ff.stdin.write(frame.tobytes())
            wr.writerow([i, f"{t:.3f}", f"{mm:02d}:{ss:02d}", int(running), int(occluded)])
            if i % (FPS * 20) == 0:
                print(f"{t:.0f}s / {a.seconds:.0f}s", flush=True)
    ff.stdin.close()
    ff.wait()
    # Hilfsangabe für die Kalibrierung: Tafel-Lage im Bild
    print(f"Tafel im Bild: x={bx} y={by} w={bw} h={bh}")
    print(f"Fertig: {a.out}, {gt_path}")


if __name__ == "__main__":
    main()
