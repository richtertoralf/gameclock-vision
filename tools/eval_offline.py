"""Offline-Auswertung: Video + Ground Truth -> Trefferquoten.

  python3 tools/eval_offline.py --video test.mp4 --config tafeluhr.json
  python3 tools/eval_offline.py --video test.mp4 --synthetic 420   # Testvideo-Geometrie

Ohne Ground Truth (echte Aufnahme) wird nur eine Zeitreihe ausgegeben:
  python3 tools/eval_offline.py --video aufnahme.mkv --config tafeluhr.json --csv out.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tafeluhr.decoder import Config, SegmentDecoder  # noqa: E402
from tafeluhr.source import probe_size  # noqa: E402
from tafeluhr.tracker import ClockTracker, to_seconds  # noqa: E402


def synthetic_config(board_px: int) -> Config:
    """Kalibrierung passend zu tools/gen_testvideo.py (so, wie man sie von Hand zieht)."""
    W, BW = 1920, 2000
    bh = int(board_px * 720 / BW)
    bx, by = (W - board_px) // 2 + 60, 360
    k = board_px / BW
    m = 9  # mm Rand um die LED-Mitten
    skew = 0.10 * 330
    x0, x1 = 610 - m, 1265 + 165 + m
    y0, y1 = 170 - m, 500 + m
    quad = [[bx + (x0 + skew) * k, by + y0 * k], [bx + (x1 + skew) * k, by + y0 * k],
            [bx + x1 * k, by + y1 * k], [bx + x0 * k, by + y1 * k]]
    width = x1 - x0
    lefts = [610, 805, 1070, 1265]
    return Config(quad=quad, digit_w=(165 + 2 * m) / width,
                  digit_x=[(lx - m - x0) / width for lx in lefts])


def frames(path: str, fps: float):
    w, h = probe_size(path)
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", path, "-an",
                          "-vf", f"fps={fps}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         stdout=subprocess.PIPE)
    n = w * h * 3
    i = 0
    while True:
        b = p.stdout.read(n)
        if len(b) < n:
            break
        yield i / fps, np.frombuffer(b, np.uint8).reshape(h, w, 3)
        i += 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--gt")
    ap.add_argument("--config")
    ap.add_argument("--synthetic", type=int, help="Tafelbreite px des Testvideos")
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--csv", help="Zeitreihe schreiben")
    ap.add_argument("--save-config", help="verwendete Kalibrierung als JSON speichern")
    a = ap.parse_args()

    if a.synthetic:
        cfg = synthetic_config(a.synthetic)
    else:
        cfg = Config.from_dict(json.load(open(a.config)))
    if a.save_config:
        json.dump(cfg.to_dict(), open(a.save_config, "w"), indent=2)
    dec = SegmentDecoder(cfg)
    trk = ClockTracker(cfg.stable_ms, cfg.correct_ms, cfg.stop_ms, cfg.coast_ms)

    gt = None
    gt_path = a.gt or (a.video.rsplit(".", 1)[0] + "_gt.csv")
    if os.path.exists(gt_path):
        gt = list(csv.DictReader(open(gt_path)))
        gt_fps = 1 / (float(gt[1]["t"]) - float(gt[0]["t"]))

    out = csv.writer(open(a.csv, "w", newline="")) if a.csv else None
    if out:
        out.writerow(["t", "raw", "reason", "contrast", "conf", "time", "running", "source"])

    n = raw_ok = raw_wrong = raw_none = 0
    out_ok = out_off1 = out_bad = 0
    occl_frames = 0
    run_ok = run_n = 0
    max_err = 0
    wrong_examples = []
    for t, f in frames(a.video, a.fps):
        r = dec.decode(f)
        st = trk.update(t, r.text if r else None, r.confidence if r else 0)
        if out:
            out.writerow([f"{t:.2f}", r.text or "", r.reason, f"{r.contrast:.0f}", r.confidence,
                          st.time or "", int(st.running), st.source])
        if gt is None:
            continue
        gi = min(int(round(t * gt_fps)), len(gt) - 1)
        g = gt[gi]
        truth = to_seconds(g["time"].replace(":", ""))
        n += 1
        occ = g["occluded"] == "1"
        occl_frames += occ
        if r.text is None:
            raw_none += 1
        elif to_seconds(r.text) == truth:
            raw_ok += 1
        else:
            # Lesung genau im Sekundenwechsel (alter/neuer Wert) ist kein Fehler
            prev = to_seconds(gt[max(0, gi - 3)]["time"].replace(":", ""))
            if to_seconds(r.text) == prev:
                raw_ok += 1
            else:
                raw_wrong += 1
                if len(wrong_examples) < 8:
                    wrong_examples.append((round(t, 2), r.text, g["time"]))
        if st.seconds is not None:
            err = abs(st.seconds - truth)
            if err == 0:
                out_ok += 1
            elif err == 1:
                out_off1 += 1
            else:
                out_bad += 1
                max_err = max(max_err, err)
        run_n += 1
        run_ok += int(st.running == (g["running"] == "1"))

    if gt is None:
        print("Keine Ground Truth – nur Zeitreihe erzeugt." if out else "Keine Ground Truth.")
        return
    pct = lambda x: f"{100 * x / max(n, 1):.1f} %"  # noqa: E731
    print(f"Frames analysiert:          {n}  (davon verdeckt: {occl_frames})")
    print(f"Rohlesung korrekt:          {pct(raw_ok)}")
    print(f"Rohlesung keine:            {pct(raw_none)}")
    print(f"Rohlesung FALSCH:           {raw_wrong}  {wrong_examples}")
    print(f"Ausgabe exakt:              {pct(out_ok)}")
    print(f"Ausgabe 1 s daneben:        {pct(out_off1)}  (Bestätigungs-/Wechsel-Lag)")
    print(f"Ausgabe >1 s daneben:       {out_bad} Frames, max {max_err} s")
    print(f"Läuft/steht korrekt:        {100 * run_ok / max(run_n, 1):.1f} %")


if __name__ == "__main__":
    main()
