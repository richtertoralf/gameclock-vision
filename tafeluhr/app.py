"""Tafeluhr: liest die Spieluhr einer LED-Anzeigetafel aus einem Videostream.

Start:  python3 -m tafeluhr --source srt://... --port 8090
Web-UI: http://<host>:8090/          (Kalibrierung + Status)
API:    GET /api/state   JSON
        GET /api/time.txt  nur "MM:SS"
        WS  /ws          JSON-Push (5x pro Sekunde + bei Änderung)
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from collections import deque

from .autofit import autofit
from .decoder import Config, SegmentDecoder, default_digit_x, segment_rects, FULL_W, FULL_H
from .source import FFmpegSource, Recorder
from .tracker import ClockTracker

log = logging.getLogger("tafeluhr")
STATIC = Path(__file__).parent / "static"
GEOMETRY_KEYS = {"auto_follow", "segment_overrides", "quad", "digit_w", "colon_w", "thick", "digit_x", "color_mode", "y_top", "y_bot"}


class Engine:
    def __init__(self, cfg_path: str, log_path: str | None = None):
        self.cfg_path = cfg_path
        self.cfg = self._load()
        self.decoder = SegmentDecoder(self.cfg)
        self.tracker = ClockTracker()
        self._apply_timing()
        self.lock = threading.Lock()
        self.frame: np.ndarray | None = None
        self.reading = None
        self.state = self.tracker.state(time.time())
        self.fps = 0.0
        self._fps_t, self._fps_n = time.time(), 0
        self.proc_ms = 0.0
        self.source: FFmpegSource | None = None
        self.history: deque = deque(maxlen=12)   # 1 Frame/s für Auto-Ausrichtung
        self._hist_t = 0.0
        self.fit = {"running": False, "info": None, "error": None}
        self.csv = None
        if log_path:
            new = not os.path.exists(log_path)
            f = open(log_path, "a", newline="")
            self.csv = (f, csv.writer(f))
            if new:
                self.csv[1].writerow(["ts", "raw", "reason", "contrast", "conf",
                                      "time", "running", "source"])

    def _load(self) -> Config:
        if os.path.exists(self.cfg_path):
            with open(self.cfg_path) as f:
                return Config.from_dict(json.load(f))
        return Config()

    def save(self):
        with open(self.cfg_path, "w") as f:
            json.dump(self.cfg.to_dict(), f, indent=2)

    def _apply_timing(self):
        c = self.cfg
        self.tracker.configure(c.stable_ms, c.correct_ms, c.stop_ms, c.coast_ms)

    def update_config(self, patch: dict):
        with self.lock:
            d = self.cfg.to_dict()
            d.update({k: v for k, v in patch.items() if k in d})
            # Grobe Rasteränderungen lösen die manuell gesetzten Messfelder ab.
            if any(k in patch for k in ("digit_w", "colon_w", "thick", "digit_x", "y_top", "y_bot")) and "segment_overrides" not in patch:
                d["segment_overrides"] = None
            geometry_changed = any(d[k] != getattr(self.cfg, k) for k in GEOMETRY_KEYS)
            self.cfg = Config.from_dict(d)
            self.decoder.reconfigure(self.cfg, reset_refs=geometry_changed)
            self._apply_timing()
            if patch.get("reset_clock"):
                self.tracker.reset()
            self.save()

    def on_frame(self, frame: np.ndarray, t: float):
        t0 = time.perf_counter()
        with self.lock:
            reading = self.decoder.decode(frame) if self.cfg.quad else None
        text = reading.text if reading else None
        conf = reading.confidence if reading else 0.0
        if t - self._hist_t >= 1.0:
            self.history.append(frame.copy())
            self._hist_t = t
        with self.lock:
            self.frame = frame
            self.reading = reading
            self.state = self.tracker.update(t, text, conf)
        self.proc_ms = (time.perf_counter() - t0) * 1000
        self._fps_n += 1
        if t - self._fps_t >= 2:
            self.fps = self._fps_n / (t - self._fps_t)
            self._fps_t, self._fps_n = t, 0
        if self.csv:
            s = self.state
            self.csv[1].writerow([f"{t:.3f}", text or "", reading.reason if reading else "",
                                  f"{reading.contrast:.0f}" if reading else "", f"{conf:.2f}",
                                  s.time or "", int(s.running), s.source])

    def start_autofit(self) -> bool:
        if self.fit["running"] or not self.cfg.quad or len(self.history) < 3:
            return False
        self.fit = {"running": True, "info": None, "error": None}

        def job():
            try:
                frames = list(self.history)[-10:]
                best, info = autofit(self.cfg, frames)
                if info["valid_frames"] == 0:
                    self.fit = {"running": False, "info": info,
                                "error": "Keine gültige Lesung gefunden – Viereck prüfen (alle 4 Uhrziffern drin?)"}
                    return
                self.update_config({k: getattr(best, k) for k in
                                    ("quad", "digit_w", "colon_w", "digit_x", "thick", "y_top", "y_bot", "segment_overrides")})
                self.tracker.reset()
                self.fit = {"running": False, "info": info, "error": None}
            except Exception as e:  # noqa: BLE001
                log.exception("Autofit")
                self.fit = {"running": False, "info": None, "error": str(e)}

        threading.Thread(target=job, daemon=True).start()
        return True

    def current_state(self) -> dict:
        with self.lock:
            st = self.tracker.state(time.time())
        d = asdict(st)
        d["fps"] = round(self.fps, 1)
        d["proc_ms"] = round(self.proc_ms, 1)
        d["source_connected"] = bool(self.source and self.source.connected)
        d["source_error"] = self.source.last_error if self.source else ""
        return d


def create_app(engine: Engine) -> FastAPI:
    app = FastAPI(title="Tafeluhr")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/state")
    def state():
        return JSONResponse(engine.current_state(), headers={"Cache-Control": "no-store"})

    @app.get("/api/time.txt")
    def time_txt():
        return PlainTextResponse(engine.current_state()["time"] or "--:--",
                                 headers={"Cache-Control": "no-store"})

    @app.get("/api/config")
    def get_config():
        with engine.lock:
            d = engine.cfg.to_dict()
            d["digit_x_effective"] = engine.cfg.digit_x or default_digit_x(engine.cfg)
            d["segment_rects"] = list(engine.decoder.rects)
            d["alignment_offsets"] = list(engine.decoder.alignment.offsets)
            f = engine.frame
        d["debug_size"] = [FULL_W, FULL_H]
        d["frame_size"] = None if f is None else [f.shape[1], f.shape[0]]
        return d

    @app.post("/api/config")
    async def set_config(req: Request):
        try:
            engine.update_config(await req.json())
        except ValueError as exc:
            return JSONResponse({"ok": False, "error": str(exc)}, 400)
        return {"ok": True}

    @app.post("/api/autofit")
    def autofit_start():
        if not engine.cfg.quad:
            return JSONResponse({"ok": False, "error": "Erst das Viereck um die Uhr ziehen."}, 400)
        if len(engine.history) < 3:
            return JSONResponse({"ok": False, "error": "Noch zu wenig Bilder – ein paar Sekunden warten."}, 400)
        return {"ok": engine.start_autofit()}

    @app.get("/api/autofit")
    def autofit_status():
        return engine.fit

    @app.get("/snapshot.jpg")
    def snapshot(x: int = 0, y: int = 0, w: int = 0, h: int = 0, maxw: int = 1600):
        with engine.lock:
            f = engine.frame
        if f is None:
            f = np.zeros((360, 640, 3), np.uint8)
            cv2.putText(f, "kein Bild", (220, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (200, 200, 200), 2)
        elif w > 0 and h > 0:
            x, y = max(0, x), max(0, y)
            f = f[y:y + h, x:x + w]
        if f.shape[1] > maxw:
            f = cv2.resize(f, (maxw, int(f.shape[0] * maxw / f.shape[1])), interpolation=cv2.INTER_AREA)
        elif f.shape[1] < 800:
            s = 800 / f.shape[1]
            f = cv2.resize(f, (800, int(f.shape[0] * s)), interpolation=cv2.INTER_NEAREST)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.get("/debug.jpg")
    def debug(plain: bool = False):
        with engine.lock:
            f, r = engine.frame, engine.reading
        if f is None:
            f = np.zeros((360, 640, 3), np.uint8)
        if plain:
            # Browser zeichnet die beweglichen Messfelder selbst. Keine alten
            # Rahmen ins Hintergrundbild einbrennen.
            img = engine.decoder.warp(f)
            if img is None:
                img = np.zeros((FULL_H, FULL_W, 3), np.uint8)
            img = cv2.resize(img, (FULL_W * 2, FULL_H * 2), interpolation=cv2.INTER_NEAREST)
        else:
            img = engine.decoder.debug_image(f, r)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        return Response(buf.tobytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        last = None
        try:
            n = 0
            while True:
                d = engine.current_state()
                key = (d["time"], d["running"], d["source"])
                if key != last or n % 5 == 0:
                    await sock.send_json(d)
                    last = key
                n += 1
                await asyncio.sleep(0.1)
        except (WebSocketDisconnect, RuntimeError):
            pass

    return app


def main():
    p = argparse.ArgumentParser(description="Spieluhr einer LED-Tafel aus Video lesen")
    p.add_argument("--source", required=True, help="srt://, rtsp://, Datei, ...")
    p.add_argument("--port", type=int, default=8090)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--fps", type=float, default=10.0, help="Analyse-Framerate")
    p.add_argument("--crop", help="Vorab-Ausschnitt w:h:x:y (spart CPU bei 4K)")
    p.add_argument("--config", default="tafeluhr.json")
    p.add_argument("--record", help="Ordner für Rohaufzeichnung (ffmpeg -c copy)")
    p.add_argument("--log", help="CSV-Log aller Lesungen")
    p.add_argument("--loop", action="store_true", help="Datei endlos wiederholen")
    p.add_argument("--size", help="Bildgröße BxH, überspringt ffprobe (z. B. 1920x1080)")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    engine = Engine(a.config, a.log)
    size = tuple(int(v) for v in a.size.lower().split("x")) if a.size else None
    src = FFmpegSource(a.source, fps=a.fps, crop=a.crop, loop=a.loop, size=size)
    engine.source = src
    threading.Thread(target=src.run, args=(engine.on_frame,), daemon=True).start()
    if a.record:
        rec = Recorder(a.source, a.record)
        threading.Thread(target=rec.run, daemon=True).start()

    import uvicorn
    uvicorn.run(create_app(engine), host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
