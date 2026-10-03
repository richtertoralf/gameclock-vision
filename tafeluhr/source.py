"""Videoquelle über ffmpeg (RTSP, SRT, Datei, HTTP) mit Auto-Reconnect."""
from __future__ import annotations

import json
import logging
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger("tafeluhr.source")


def probe_size(url: str, timeout: float = 15.0) -> tuple[int, int]:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height", "-of", "json"]
    if url.startswith("rtsp://"):
        cmd += ["-rtsp_transport", "tcp"]
    cmd.append(url)
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    s = json.loads(out.stdout or "{}").get("streams", [{}])[0]
    if not s.get("width"):
        raise RuntimeError(f"ffprobe fand kein Video: {out.stderr.strip()[:300]}")
    return int(s["width"]), int(s["height"])


def parse_crop(crop: str | None):
    if not crop:
        return None
    w, h, x, y = (int(v) for v in crop.split(":"))
    return w, h, x, y


class FFmpegSource:
    """Liefert BGR-Frames mit Zeitstempel an einen Callback.

    realtime=True (Live): Zeit = Wanduhr beim Empfang.
    Bei Dateien wird mit -re in Echtzeit abgespielt (loop optional).
    """

    def __init__(self, url: str, fps: float = 10.0, crop: str | None = None,
                 loop: bool = False, size: tuple[int, int] | None = None):
        self.url, self.fps, self.loop = url, fps, loop
        self.crop = parse_crop(crop)
        self.size = size
        self.proc: subprocess.Popen | None = None
        self.running = False
        self.connected = False
        self.frames = 0
        self.last_error = ""

    def _cmd(self, w: int, h: int) -> list[str]:
        is_file = "://" not in self.url
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
        if is_file:
            cmd += ["-re"]
            if self.loop:
                cmd += ["-stream_loop", "-1"]
        else:
            cmd += ["-fflags", "nobuffer", "-flags", "low_delay"]
            if self.url.startswith("rtsp://"):
                cmd += ["-rtsp_transport", "tcp"]
        cmd += ["-i", self.url, "-an"]
        vf = [f"fps={self.fps}"]
        if self.crop:
            cw, ch, cx, cy = self.crop
            vf.append(f"crop={cw}:{ch}:{cx}:{cy}")
        cmd += ["-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return cmd

    def frame_size(self) -> tuple[int, int]:
        if self.crop:
            return self.crop[0], self.crop[1]
        if self.size is None:
            self.size = probe_size(self.url)
        return self.size

    def run(self, on_frame):
        self.running = True
        backoff = 1.0
        while self.running:
            try:
                w, h = self.frame_size()
                nbytes = w * h * 3
                cmd = self._cmd(w, h)
                log.info("Starte: %s", " ".join(cmd))
                self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, bufsize=nbytes * 2)
                errbuf: list[str] = []
                threading.Thread(target=self._drain, args=(self.proc, errbuf), daemon=True).start()
                while self.running:
                    buf = self.proc.stdout.read(nbytes)
                    if not buf or len(buf) < nbytes:
                        break
                    self.connected = True
                    backoff = 1.0
                    self.frames += 1
                    frame = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                    on_frame(frame, time.time())
                self.connected = False
                self.proc.kill()
                self.proc.wait()
                self.last_error = (errbuf[-1] if errbuf else "Stream beendet")
                log.warning("Quelle getrennt: %s", self.last_error)
                if "://" not in self.url and not self.loop:
                    self.running = False
                    break
            except Exception as e:  # noqa: BLE001
                self.connected = False
                self.last_error = str(e)
                log.warning("Quelle Fehler: %s", e)
            if self.running:
                time.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    @staticmethod
    def _drain(proc, errbuf):
        for line in proc.stderr:
            errbuf.append(line.decode(errors="replace").strip())
            del errbuf[:-20]

    def stop(self):
        self.running = False
        if self.proc:
            self.proc.kill()


class Recorder:
    """Rohaufzeichnung des Streams (-c copy) in 10-Minuten-Segmenten."""

    def __init__(self, url: str, outdir: str):
        self.url, self.outdir = url, outdir
        self.proc: subprocess.Popen | None = None
        self.running = False

    def run(self):
        import os
        os.makedirs(self.outdir, exist_ok=True)
        self.running = True
        while self.running:
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
            if self.url.startswith("rtsp://"):
                cmd += ["-rtsp_transport", "tcp"]
            cmd += ["-i", self.url, "-map", "0:v:0", "-c", "copy", "-f", "segment",
                    "-segment_time", "600", "-reset_timestamps", "1", "-strftime", "1",
                    os.path.join(self.outdir, "tafel_%Y%m%d_%H%M%S.mkv")]
            log.info("Aufnahme: %s", " ".join(cmd))
            self.proc = subprocess.Popen(cmd)
            self.proc.wait()
            if self.running:
                time.sleep(2)

    def stop(self):
        self.running = False
        if self.proc:
            self.proc.terminate()
