"""Read current camera frames through Tafeluhr without changing its settings.

Run from the repository: .venv/bin/python -B -m tools.eval_live --seconds 20
Uses the decoder/tracker on disk, independently of the running server version.
"""
import argparse
import json
import time
import urllib.request
from collections import Counter

import cv2
import numpy as np
from tafeluhr.decoder import Config, SegmentDecoder
from tafeluhr.tracker import ClockTracker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8090')
    parser.add_argument('--seconds', type=float, default=20)
    args = parser.parse_args()
    def get(path):
        with urllib.request.urlopen(args.url.rstrip('/') + path, timeout=5) as response:
            return response.read()
    config = Config.from_dict(json.loads(get('/api/config')))
    decoder = SegmentDecoder(config)
    tracker = ClockTracker(config.stable_ms, config.correct_ms, config.stop_ms, config.coast_ms)
    start = time.monotonic()
    counts = Counter()
    next_report = start
    while time.monotonic() - start < args.seconds:
        tick = time.monotonic()
        frame = cv2.imdecode(np.frombuffer(get('/snapshot.jpg?maxw=10000'), np.uint8), cv2.IMREAD_COLOR)
        reading = decoder.decode(frame)
        state = tracker.update(time.time(), reading.text if reading else None,
                               reading.confidence if reading else 0)
        counts['frames'] += 1
        counts['readable'] += bool(reading and reading.text)
        counts['running'] += state.running
        if tick >= next_report:
            print(json.dumps({'raw':state.raw,'time':state.time,'running':state.running,
                              'source':state.source,'confidence':state.confidence}), flush=True)
            next_report = tick + 1
        time.sleep(max(0, .1 - (time.monotonic() - tick)))
    print(json.dumps({'summary':dict(counts)}))


if __name__ == '__main__':
    main()
